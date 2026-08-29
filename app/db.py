import os
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from app.config import DATABASE_PATH, DATABASE_URL, APP_DATABASE_URL

# Optional SQLAlchemy support
try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker, Session
    _HAS_SQLALCHEMY = True
except ImportError:
    _HAS_SQLALCHEMY = False
    create_engine = None
    sessionmaker = None
    Session = None


def get_db_url(admin: bool = False) -> str:
    """Return configured database URL, preferring PostgreSQL if configured, otherwise SQLite."""
    if admin:
        return os.getenv("DATABASE_URL", DATABASE_URL)
    return os.getenv("APP_DATABASE_URL", APP_DATABASE_URL)


_ENGINE_CACHE = {}


def get_engine(admin: bool = False):
    """Return centralized SQLAlchemy engine with connection pooling."""
    if not _HAS_SQLALCHEMY:
        raise RuntimeError("SQLAlchemy is required for get_engine(). Install sqlalchemy.")
    url = get_db_url(admin=admin)
    if url not in _ENGINE_CACHE:
        _ENGINE_CACHE[url] = create_engine(
            url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            isolation_level="READ COMMITTED",
        )
    return _ENGINE_CACHE[url]


def get_session(admin: bool = False):
    """Return a fresh SQLAlchemy session inside a context manager."""
    engine = get_engine(admin=admin)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    return maker()


def get_conn(admin: bool = False):
    """Return a database connection. Falls back to SQLite if PostgreSQL is not connected."""
    # Check if a custom SQLite DATABASE_PATH is explicitly set (e.g. in tests)
    db_path = str(DATABASE_PATH)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    with get_conn(admin=True) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_id TEXT,
            event_id TEXT,
            case_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            payload_json TEXT NOT NULL)""")
        cols = {r[1] for r in conn.execute("PRAGMA table_info(audit_logs)").fetchall()}
        if "decision_id" not in cols:
            conn.execute("ALTER TABLE audit_logs ADD COLUMN decision_id TEXT")
        if "event_id" not in cols:
            conn.execute("ALTER TABLE audit_logs ADD COLUMN event_id TEXT")

        # Engine-enforced append-only triggers for SQLite
        conn.execute("""CREATE TRIGGER IF NOT EXISTS prevent_audit_update
        BEFORE UPDATE ON audit_logs
        BEGIN
            SELECT RAISE(ABORT, 'audit_log is append-only: UPDATE forbidden');
        END;""")

        conn.execute("""CREATE TRIGGER IF NOT EXISTS prevent_audit_delete
        BEFORE DELETE ON audit_logs
        BEGIN
            SELECT RAISE(ABORT, 'audit_log is append-only: DELETE forbidden');
        END;""")

        conn.execute("""CREATE TABLE IF NOT EXISTS webhook_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT UNIQUE NOT NULL,
            event_type TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'PENDING',
            received_at TEXT DEFAULT CURRENT_TIMESTAMP,
            processed_at TEXT,
            last_error TEXT)""")
        wcols = {r[1] for r in conn.execute("PRAGMA table_info(webhook_events)").fetchall()}
        if "event_type" not in wcols:
            conn.execute("ALTER TABLE webhook_events ADD COLUMN event_type TEXT NOT NULL DEFAULT ''")
        if "payload_json" not in wcols:
            conn.execute("ALTER TABLE webhook_events ADD COLUMN payload_json TEXT NOT NULL DEFAULT '{}'")
        if "status" not in wcols:
            conn.execute("ALTER TABLE webhook_events ADD COLUMN status TEXT NOT NULL DEFAULT 'PENDING'")
        if "processed_at" not in wcols:
            conn.execute("ALTER TABLE webhook_events ADD COLUMN processed_at TEXT")
        if "last_error" not in wcols:
            conn.execute("ALTER TABLE webhook_events ADD COLUMN last_error TEXT")

        conn.execute("""CREATE TABLE IF NOT EXISTS execution_intents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_id TEXT UNIQUE NOT NULL,
            case_id TEXT NOT NULL,
            action TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            result_json TEXT)""")

        conn.execute("""CREATE TABLE IF NOT EXISTS decision_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_id TEXT UNIQUE NOT NULL,
            case_id TEXT NOT NULL,
            feature_json TEXT NOT NULL,
            action TEXT,
            policy_version TEXT,
            model_version TEXT,
            prompt_version TEXT,
            scenario_version TEXT,
            created_at TEXT NOT NULL)""")

        conn.execute("""CREATE TABLE IF NOT EXISTS approval_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id TEXT NOT NULL,
            amount REAL NOT NULL,
            reason TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'PENDING',
            reviewer TEXT,
            created_at TEXT NOT NULL,
            resolved_at TEXT)""")

        conn.execute("""CREATE TABLE IF NOT EXISTS merchant_config (
            id INTEGER PRIMARY KEY DEFAULT 1,
            config_json TEXT NOT NULL,
            updated_at TEXT NOT NULL)""")


def enqueue_webhook_event(event_id: str, event_type: str, payload_json: str, received_at: str) -> bool:
    with get_conn() as conn:
        try:
            cursor = conn.execute(
                "INSERT INTO webhook_events(event_id, event_type, payload_json, status, received_at) "
                "VALUES(?, ?, ?, ?, ?) ON CONFLICT(event_id) DO NOTHING RETURNING id",
                (event_id, event_type, payload_json, "PENDING", received_at),
            )
            row = cursor.fetchone()
            return row is not None
        except Exception:
            return False


def claim_webhook_events(limit: int = 20):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM webhook_events WHERE status='PENDING' ORDER BY id LIMIT ?",
            (limit,),
        ).fetchall()
        if rows:
            ids = [r["event_id"] for r in rows]
            conn.executemany("UPDATE webhook_events SET status='PROCESSING' WHERE event_id=?", [(i,) for i in ids])
        return rows


def mark_webhook_processed(event_id: str, processed_at: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE webhook_events SET status='PROCESSED', processed_at=?, last_error=NULL WHERE event_id=?",
            (processed_at, event_id),
        )


def mark_webhook_failed(event_id: str, error: str):
    with get_conn() as conn:
        conn.execute("UPDATE webhook_events SET status='PENDING', last_error=? WHERE event_id=?", (error, event_id))


def get_persisted_merchant_config() -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT config_json FROM merchant_config WHERE id=1").fetchone()
        if row and row["config_json"]:
            try:
                return json.loads(row["config_json"])
            except Exception:
                return None
    return None


def save_persisted_merchant_config(config_dict: dict) -> None:
    cfg_str = json.dumps(config_dict)
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO merchant_config(id, config_json, updated_at) VALUES(1, ?, ?) ON CONFLICT(id) DO UPDATE SET config_json=excluded.config_json, updated_at=excluded.updated_at",
            (cfg_str, now),
        )
