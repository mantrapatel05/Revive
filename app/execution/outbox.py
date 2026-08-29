import json
from datetime import datetime, timezone
from app.db import get_conn
from app.execution.authorization import ExecutionAuthorization


def enqueue_execution_intent(auth: ExecutionAuthorization, payload: dict) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "INSERT INTO execution_intents (decision_id, case_id, action, payload_json, status, created_at) "
            "VALUES (?, ?, ?, ?, 'PENDING', ?) "
            "ON CONFLICT (decision_id) DO UPDATE SET decision_id=EXCLUDED.decision_id "
            "RETURNING id",
            (auth.decision_id, auth.case_id, auth.action, json.dumps(payload, default=str), datetime.now(timezone.utc)),
        ).fetchone()
        return int(row["id"])


def get_pending_intents(limit: int = 10):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM execution_intents WHERE status='PENDING' ORDER BY id LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def mark_intent_status(intent_id: int, status: str, result: dict | None = None):
    with get_conn() as conn:
        conn.execute(
            "UPDATE execution_intents SET status=?, result_json=?, updated_at=? WHERE id=?",
            (status, json.dumps(result or {}, default=str), datetime.now(timezone.utc).isoformat(), intent_id),
        )
