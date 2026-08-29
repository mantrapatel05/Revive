import sqlite3
import pytest
from app import config
import app.db as db
from app.audit.logger import AuditLogger


def test_sqlite_audit_logs_append_only_triggers(tmp_path, monkeypatch):
    """Assert that SQLite engine-level BEFORE UPDATE and BEFORE DELETE triggers abort mutation attempts with IntegrityError."""
    test_db = tmp_path / "test_triggers.db"
    monkeypatch.setattr(config, "DATABASE_PATH", test_db)
    monkeypatch.setattr(db, "DATABASE_PATH", test_db)
    db.init_db()

    logger = AuditLogger()
    record = {
        "decision_id": "dec_test_immutability_01",
        "event_id": "evt_test_01",
        "case_id": "case_test_01",
        "timestamp": "2026-08-29T18:40:00Z",
        "payload": {"status": "EXECUTION_REQUESTED", "recovered_amount": 0.0},
    }
    logger.log(record)

    # Verify insertion succeeded
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM audit_logs WHERE decision_id = ?", ("dec_test_immutability_01",)).fetchone()
        assert row is not None
        row_id = row["id"]

    # 1. Attempt UPDATE -> must raise sqlite3.IntegrityError from trigger prevent_audit_update
    with pytest.raises(sqlite3.IntegrityError) as exc_update:
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE audit_logs SET payload_json = ? WHERE id = ?",
                ('{"tampered": true}', row_id),
            )
    assert "audit_log is append-only: UPDATE forbidden" in str(exc_update.value)

    # 2. Attempt DELETE -> must raise sqlite3.IntegrityError from trigger prevent_audit_delete
    with pytest.raises(sqlite3.IntegrityError) as exc_delete:
        with db.get_conn() as conn:
            conn.execute("DELETE FROM audit_logs WHERE id = ?", (row_id,))
    assert "audit_log is append-only: DELETE forbidden" in str(exc_delete.value)

    # Verify that the row remains unaltered
    with db.get_conn() as conn:
        row_after = conn.execute("SELECT * FROM audit_logs WHERE id = ?", (row_id,)).fetchone()
        assert row_after is not None
        assert "tampered" not in row_after["payload_json"]
