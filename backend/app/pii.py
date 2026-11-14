"""PII masking applied to every string before it is sent to the LLM.

The agent never needs a claimant's phone number or PAN to reason about a claim; it
needs to know *whether two claims share one*. So identifiers are replaced with
stable pseudonyms (same input -> same token), which keeps link analysis intact
while the raw value never leaves our boundary."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("AADHAAR", re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")),
    ("ACCOUNT", re.compile(r"\b(?:A/C|Acct|Account)\s*(?:No\.?)?\s*[:#]?\s*\d{9,18}\b", re.I)),
]


def _token(kind: str, value: str) -> str:
    digest = hashlib.sha256(re.sub(r"\s|-", "", value).encode()).hexdigest()[:6].upper()
    return f"<{kind}_{digest}>"


@dataclass
class Masker:
    names: list[str] = field(default_factory=list)
    count: int = 0

    def mask(self, text: str) -> str:
        if not text:
            return text
        out = text
        for kind, pat in _PATTERNS:
            def repl(m: re.Match[str], kind: str = kind) -> str:
                self.count += 1
                return _token(kind, m.group(0))
            out = pat.sub(repl, out)
        for name in self.names:
            if name and len(name) > 2 and name in out:
                self.count += out.count(name)
                out = out.replace(name, "<CLAIMANT>")
        return out
