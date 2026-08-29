"""PostgreSQL access helpers for REVIVE.

Operational code always connects with ``APP_DATABASE_URL``. Administrative
operations must opt into ``ADMIN_DATABASE_URL`` explicitly, mirroring the
database roles in ``schema.sql``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from psycopg2 import connect
from psycopg2.extras import DictCursor

from app.config import get_db_url


class DatabaseError(RuntimeError):
    """Raised when the configured PostgreSQL database is not ready."""


def _postgres_sql(sql: str) -> str:
    """Translate legacy DB-API qmark placeholders to psycopg2 placeholders."""

    return re.sub(r"\?", "%s", sql)


class PostgresConnection:
    """Transaction-scoped DB-API façade used by application services."""

    def __init__(self, *, admin: bool = False) -> None:
        try:
            self._raw = connect(get_db_url(admin=admin), cursor_factory=DictCursor)
        except Exception as exc:  # pragma: no cover - environment dependent
            role = "administrator" if admin else "application"
            raise DatabaseError(
                f"Could not connect as the {role} database role. "
                "Start PostgreSQL and run `make db-migrate`."
            ) from exc
        self._raw.autocommit = False

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> DictCursor:
        cursor = self._raw.cursor()
        cursor.execute(_postgres_sql(sql), params)
        return cursor

    def executemany(self, sql: str, params_seq: Sequence[Sequence[Any]]) -> DictCursor:
        cursor = self._raw.cursor()
        cursor.executemany(_postgres_sql(sql), params_seq)
        return cursor

    def __enter__(self) -> "PostgresConnection":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        try:
            if exc_type is None:
                self._raw.commit()
            else:
                self._raw.rollback()
        finally:
            self._raw.close()


def get_conn(*, admin: bool = False) -> PostgresConnection:
    """Open a transaction using the application role by default."""

    return PostgresConnection(admin=admin)


def init_db() -> None:
    """Verify that migrations have created the required schema.

    Runtime startup deliberately does not create tables or audit controls: the
    application role can only operate within an administrator-provisioned
    schema.
    """

    required_tables = {
        "webhook_events",
        "decision_records",
        "execution_intents",
        "audit_logs",
        "approval_queue",
        "merchant_config",
    }
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"
        ).fetchall()
    present = {row["tablename"] for row in rows}
    missing = sorted(required_tables - present)
    if missing:
        raise DatabaseError(
            "PostgreSQL schema is incomplete (missing: "
            f"{', '.join(missing)}). Run `make db-migrate`."
        )


def enqueue_webhook_event(event_id: str, event_type: str, payload_json: str, received_at: str) -> bool:
    """Insert a webhook once, using PostgreSQL's unique-key conflict guard."""

    with get_conn() as conn:
        row = conn.execute(
            "INSERT INTO webhook_events(event_id, event_type, payload_json, status, received_at) "
            "VALUES(?, ?, ?, 'PENDING', ?) "
            "ON CONFLICT(event_id) DO NOTHING RETURNING id",
            (event_id, event_type, payload_json, received_at),
        ).fetchone()
    return row is not None


def claim_webhook_events(limit: int = 20):
    """Atomically lease pending events without two workers processing one event."""

    with get_conn() as conn:
        return conn.execute(
            "WITH claimed AS ("
            " SELECT id FROM webhook_events WHERE status='PENDING' ORDER BY id"
            " FOR UPDATE SKIP LOCKED LIMIT ?"
            ") "
            "UPDATE webhook_events event SET status='PROCESSING' "
            "FROM claimed WHERE event.id = claimed.id RETURNING event.*",
            (limit,),
        ).fetchall()


def mark_webhook_processed(event_id: str, processed_at: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE webhook_events SET status='PROCESSED', processed_at=?, last_error=NULL "
            "WHERE event_id=?",
            (processed_at, event_id),
        )


def mark_webhook_failed(event_id: str, error: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE webhook_events SET status='PENDING', last_error=? WHERE event_id=?",
            (error, event_id),
        )


def get_persisted_merchant_config() -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT config_json FROM merchant_config WHERE id=1").fetchone()
    if row and row["config_json"]:
        if isinstance(row["config_json"], dict):
            return row["config_json"]
        try:
            return json.loads(row["config_json"])
        except json.JSONDecodeError:
            return None
    return None


def save_persisted_merchant_config(config_dict: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO merchant_config(id, config_json, updated_at) VALUES(1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET config_json=excluded.config_json, "
            "updated_at=excluded.updated_at",
            (json.dumps(config_dict), datetime.now(timezone.utc)),
        )
