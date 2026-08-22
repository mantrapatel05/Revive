from datetime import datetime, timezone
from typing import Any, Dict, List
from app.db import get_conn


def create_approval_request(case_id: str, amount: float, reason: str, payload: Dict[str, Any] | None = None) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO approval_queue(case_id, amount, reason, payload_json, status, created_at) VALUES(?,?,?,?,?,?)",
            (case_id, float(amount), reason, __import__('json').dumps(payload or {}), "PENDING", datetime.now(timezone.utc).isoformat()),
        )
        return int(cur.lastrowid)


def get_pending_approvals(limit: int = 50) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM approval_queue WHERE status='PENDING' ORDER BY id LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def resolve_approval(approval_id: int, decision: str, reviewer: str = "demo-reviewer") -> None:
    decision = decision.upper()
    if decision not in {"APPROVED", "REJECTED"}:
        raise ValueError("decision must be APPROVED or REJECTED")
    with get_conn() as conn:
        conn.execute(
            "UPDATE approval_queue SET status=?, reviewer=?, resolved_at=? WHERE id=?",
            (decision, reviewer, datetime.now(timezone.utc).isoformat(), approval_id),
        )
