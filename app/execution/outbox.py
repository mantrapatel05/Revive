import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from app.db import get_conn
from app.execution.authorization import ExecutionAuthorization


def save_decision_and_intent(
    decision_record: Dict[str, Any],
    auth: Optional[ExecutionAuthorization] = None,
    intent_payload: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Optional[int]]:
    """
    Persists decision record and transactional outbox intent in a SINGLE atomic database transaction.
    Guarantees durable state exists BEFORE any external provider call.
    """
    decision_id = str(decision_record["decision_id"])
    case_id = str(decision_record.get("case_id", decision_record.get("event_id", decision_id)))
    features = decision_record.get("features") or decision_record.get("case_snapshot") or {}

    with get_conn() as conn:
        # 1. Insert decision record
        conn.execute(
            """INSERT INTO decision_records
            (decision_id, case_id, feature_json, action, policy_version, model_version, prompt_version, scenario_version, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(decision_id) DO NOTHING""",
            (
                decision_id,
                case_id,
                json.dumps(features, default=str),
                decision_record.get("chosen_action"),
                decision_record.get("policy_version"),
                decision_record.get("model_version"),
                decision_record.get("prompt_version"),
                decision_record.get("scenario_version"),
                datetime.now(timezone.utc).isoformat(),
            ),
        )

        intent_id = None
        # 2. Insert outbox intent in the same transaction if authorized action exists
        if auth is not None and intent_payload is not None:
            row = conn.execute(
                """INSERT INTO execution_intents (decision_id, case_id, action, payload_json, status, created_at)
                VALUES (?, ?, ?, ?, 'PENDING', ?)
                ON CONFLICT (decision_id) DO UPDATE SET decision_id=EXCLUDED.decision_id
                RETURNING id""",
                (
                    auth.decision_id,
                    auth.case_id,
                    auth.action,
                    json.dumps(intent_payload, default=str),
                    datetime.now(timezone.utc),
                ),
            ).fetchone()
            if row:
                intent_id = int(row["id"])

        return decision_id, intent_id


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


def get_pending_intents(limit: int = 100, case_id: str | None = None):
    with get_conn() as conn:
        if case_id is not None:
            rows = conn.execute("SELECT * FROM execution_intents WHERE status='PENDING' AND case_id=? ORDER BY id DESC LIMIT ?", (case_id, limit)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM execution_intents WHERE status='PENDING' ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def claim_pending_intent(intent_id: int | None = None) -> Optional[Dict[str, Any]]:
    """
    Atomically claims a pending execution intent with row-level locking.
    Transitions status: 'PENDING' -> 'PROCESSING'.
    """
    with get_conn() as conn:
        if intent_id is not None:
            row = conn.execute(
                "UPDATE execution_intents SET status='PROCESSING', updated_at=? "
                "WHERE id=? AND status='PENDING' RETURNING *",
                (datetime.now(timezone.utc), intent_id),
            ).fetchone()
        else:
            row = conn.execute(
                "WITH claimed AS ("
                " SELECT id FROM execution_intents WHERE status='PENDING' ORDER BY id"
                " FOR UPDATE SKIP LOCKED LIMIT 1"
                ") "
                "UPDATE execution_intents intent SET status='PROCESSING', updated_at=? "
                "FROM claimed WHERE intent.id = claimed.id RETURNING intent.*",
                (datetime.now(timezone.utc),),
            ).fetchone()
        return dict(row) if row else None


def mark_intent_status(intent_id: int, status: str, result: dict | None = None):
    with get_conn() as conn:
        conn.execute(
            "UPDATE execution_intents SET status=?, result_json=?, updated_at=? WHERE id=?",
            (status, json.dumps(result or {}, default=str), datetime.now(timezone.utc).isoformat(), intent_id),
        )
