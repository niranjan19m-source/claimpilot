"""Thin wrapper over the Anthropic SDK: one place for model choice, effort, refusal
fallbacks, PII masking and structured JSON output."""
from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from .config import EFFORT, FAST_MODEL, PRIMARY_MODEL

log = logging.getLogger("claimpilot.llm")
_client: anthropic.Anthropic | None = None
_fallbacks_supported = True


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(max_retries=3, timeout=180)
    return _client


class LLMRefusal(RuntimeError):
    pass


def create(*, model: str = PRIMARY_MODEL, effort: str | None = None, schema: dict | None = None,
           max_tokens: int = 16000, **kw: Any):
    """messages.create with house defaults. `schema` turns on structured JSON output."""
    global _fallbacks_supported
    output_config: dict[str, Any] = {"effort": effort or EFFORT}
    if schema:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    params = {"model": model, "max_tokens": max_tokens, "output_config": output_config, **kw}
    # Server-side refusal fallback: on a policy decline the API re-runs the request on a
    # fallback model inside the same call. Not offered for Haiku.
    if _fallbacks_supported and "haiku" not in model:
        try:
            msg = client().beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params)
            return _check(msg)
        except anthropic.BadRequestError as e:
            if "fallback" not in str(e).lower():
                raise
            log.warning("Server-side fallbacks unavailable on this account; continuing without them.")
            _fallbacks_supported = False
    return _check(client().messages.create(**params))


def _check(msg):
    if msg.stop_reason == "refusal":
        raise LLMRefusal(getattr(msg, "stop_details", None) or "Model declined the request")
    return msg


def text_of(msg) -> str:
    return "".join(b.text for b in msg.content if b.type == "text")


def json_call(prompt: str | list, schema: dict, *, system: str, model: str = FAST_MODEL,
              effort: str = "low", max_tokens: int = 8000) -> dict:
    content = prompt if isinstance(prompt, list) else [{"type": "text", "text": prompt}]
    msg = create(model=model, effort=effort, schema=schema, max_tokens=max_tokens, system=system,
                 messages=[{"role": "user", "content": content}])
    return json.loads(text_of(msg))


def usage_of(msg) -> dict[str, int]:
    u = msg.usage
    return {"input": u.input_tokens, "output": u.output_tokens,
            "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0}


def strict_schema(props: dict[str, Any], required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or list(props),
            "additionalProperties": False}
