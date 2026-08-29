import uuid
import psycopg2
import pytest
import app.db as db
from app.audit.logger import AuditLogger
from app.decision.replay import DecisionStore


def test_postgres_audit_logs_append_only_permissions():
    """The application role cannot mutate or delete the append-only ledger."""
    db.init_db()
    case_id = f"case_test_{uuid.uuid4().hex[:8]}"
    logger = AuditLogger()
    record = {
        "event_id": f"evt_test_{uuid.uuid4().hex[:8]}",
        "case_id": case_id,
        "timestamp": "2026-08-29T18:40:00Z",
        "payload": {"status": "EXECUTION_REQUESTED", "recovered_amount": 0.0},
    }
    logger.log(record)

    # Verify insertion succeeded
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM audit_logs WHERE case_id = ?", (case_id,)).fetchone()
        assert row is not None
        row_id = row["id"]

    # UPDATE and DELETE are denied by PostgreSQL grants, not client-side code.
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE audit_logs SET payload_json = ? WHERE id = ?",
                ('{"tampered": true}', row_id),
            )
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        with db.get_conn() as conn:
            conn.execute("DELETE FROM audit_logs WHERE id = ?", (row_id,))
    # Verify that the row remains unaltered
    with db.get_conn() as conn:
        row_after = conn.execute("SELECT * FROM audit_logs WHERE case_id = ?", (case_id,)).fetchone()
        assert row_after is not None
        assert "tampered" not in str(row_after["payload_json"])
