"""SQLite persistence. One file, zero setup, safe for a single-node demo server."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from .config import DB_PATH

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
  id TEXT PRIMARY KEY, name TEXT, phone TEXT, email TEXT, address TEXT, city TEXT,
  dob TEXT, pan TEXT, bank_account TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS policies (
  policy_no TEXT PRIMARY KEY, customer_id TEXT, product TEXT, line TEXT,
  start_date TEXT, end_date TEXT, status TEXT, premium REAL, premium_paid INTEGER,
  sum_insured REAL, deductible REAL, details TEXT
);
CREATE TABLE IF NOT EXISTS garages (
  id TEXT PRIMARY KEY, name TEXT, city TEXT, network INTEGER, phone TEXT
);
CREATE TABLE IF NOT EXISTS hospitals (
  id TEXT PRIMARY KEY, name TEXT, city TEXT, network INTEGER, flagged INTEGER
);
CREATE TABLE IF NOT EXISTS handlers (
  id TEXT PRIMARY KEY, name TEXT, role TEXT, lines TEXT, authority_limit REAL,
  open_cases INTEGER, region TEXT, email TEXT
);
CREATE TABLE IF NOT EXISTS claims (
  id TEXT PRIMARY KEY, policy_no TEXT, customer_id TEXT, line TEXT, claim_type TEXT,
  incident_date TEXT, incident_time TEXT, reported_date TEXT, location TEXT, city TEXT,
  lat REAL, lon REAL, description TEXT, amount_claimed REAL, garage_id TEXT,
  hospital_id TEXT, contact_phone TEXT, bank_account TEXT, insured_member TEXT,
  status TEXT, historical INTEGER DEFAULT 0, outcome TEXT, created_at TEXT,
  severity TEXT, fraud_score REAL, coverage_status TEXT, route TEXT,
  assigned_handler TEXT, triage TEXT, scenario TEXT, triage_ms INTEGER
);
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT, claim_id TEXT, kind TEXT, filename TEXT,
  path TEXT, mime TEXT, extracted_text TEXT, meta TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS image_hashes (
  claim_id TEXT, filename TEXT, phash TEXT
);
CREATE TABLE IF NOT EXISTS claim_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, claim_id TEXT, ts TEXT, type TEXT,
  node TEXT, payload TEXT
);
CREATE TABLE IF NOT EXISTS tickets (
  id TEXT PRIMARY KEY, claim_id TEXT, queue TEXT, handler_id TEXT, priority TEXT,
  sla_due TEXT, status TEXT, summary TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT, claim_id TEXT, channel TEXT, recipient TEXT,
  subject TEXT, body TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, claim_id TEXT, original_queue TEXT, decision TEXT,
  new_queue TEXT, reason TEXT, note TEXT, reviewer TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS policy_library (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, filename TEXT, path TEXT, product TEXT,
  clauses TEXT, status TEXT, created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_claim ON claim_events(claim_id, id);
CREATE INDEX IF NOT EXISTS idx_claims_policy ON claims(policy_no);
CREATE INDEX IF NOT EXISTS idx_docs_claim ON documents(claim_id);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        c = _connect()
        _local.conn = c
    return c


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    c = conn()
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise


def init_db() -> None:
    with tx() as c:
        c.executescript(SCHEMA)


def query(sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in conn().execute(sql, params).fetchall()]


def one(sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
    r = conn().execute(sql, params).fetchone()
    return dict(r) if r else None


def execute(sql: str, params: tuple | list = ()) -> int:
    with tx() as c:
        cur = c.execute(sql, params)
        return cur.lastrowid or 0


def insert(table: str, row: dict[str, Any]) -> int:
    cols = ", ".join(row.keys())
    marks = ", ".join("?" for _ in row)
    vals = [json.dumps(v) if isinstance(v, (dict, list)) else v for v in row.values()]
    return execute(f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({marks})", vals)


def update(table: str, key: str, key_val: Any, fields: dict[str, Any]) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = [json.dumps(v) if isinstance(v, (dict, list)) else v for v in fields.values()]
    execute(f"UPDATE {table} SET {sets} WHERE {key} = ?", [*vals, key_val])


def loads(v: Any, default: Any = None) -> Any:
    if v is None or v == "":
        return default
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return default
