"""Common result envelope for every investigation tool.

Tools are deterministic, auditable Python functions. The LLM decides *which* to
call and *how to interpret* them; it never invents the facts they return."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass
class ToolResult:
    ok: bool
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    signals: list[dict[str, Any]] = field(default_factory=list)  # fraud / coverage signals raised

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "summary": self.summary, "data": self.data, "signals": self.signals}


def signal(code: str, label: str, weight: float, detail: str, kind: str = "fraud") -> dict[str, Any]:
    """A red flag raised by a tool. `weight` is the flag's standalone contribution (0-100)."""
    return {"code": code, "label": label, "weight": weight, "detail": detail, "kind": kind}


def parse_date(v: str | date | None) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, date):
        return v
    head = str(v).strip()[:10]
    for fmt in ("%Y-%m-%d", "%Y:%m:%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(head, fmt).date()
        except ValueError:
            continue
    return None


def inr(v: float | int | None) -> str:
    if v is None:
        return "—"
    v = round(float(v))
    s = str(abs(int(v)))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return ("-" if v < 0 else "") + "₹" + s
