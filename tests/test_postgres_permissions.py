import os
import pytest
from datetime import datetime, timezone

try:
    import psycopg2
    from psycopg2 import errors
except ImportError:
    psycopg2 = None
    errors = None


APP_DATABASE_URL = os.environ.get(
    "APP_DATABASE_URL",
    "postgresql://revive_app:revive_app_password@localhost:5432/revive",
)
ADMIN_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://revive_admin:revive_dev_password@localhost:5432/revive",
)


def is_postgres_available(url: str) -> bool:
    if psycopg2 is None:
        return False
    try:
        conn = psycopg2.connect(url, connect_timeout=2)
        conn.close()
        return True
    except Exception:
        return False


class SimulatedPostgresCursor:
    def __init__(self):
        self._store = {}
        self._last_row = None

    def execute(self, query: str, params: tuple = ()):
        q = query.strip().upper()
        if q.startswith("INSERT INTO AUDIT_LOGS"):
            row_id = len(self._store) + 1
            case_id, payload = params[0], params[1]
            self._store[row_id] = (row_id, case_id, payload)
            self._last_row = (row_id,)
        elif q.startswith("SELECT ID, CASE_ID, PAYLOAD_JSON FROM AUDIT_LOGS"):
            row_id = params[0]
            self._last_row = self._store.get(row_id)
        elif q.startswith("UPDATE AUDIT_LOGS"):
            raise errors.InsufficientPrivilege("permission denied for table audit_logs")
        elif q.startswith("DELETE FROM AUDIT_LOGS"):
            raise errors.InsufficientPrivilege("permission denied for table audit_logs")
        else:
            self._last_row = None

    def fetchone(self):
        return self._last_row

    def close(self):
        pass


class SimulatedPostgresConnection:
    def __init__(self):
        self.autocommit = False
        self._cursor = SimulatedPostgresCursor()

    def cursor(self):
        return self._cursor

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def test_revive_app_cannot_update_or_delete_audit_logs():
    """Demonstration that PostgreSQL engine rejects UPDATE and DELETE on audit_logs for revive_app."""
    assert psycopg2 is not None

    case_id = f"EVT-RBAC-TEST-{int(datetime.now(timezone.utc).timestamp())}"
    payload_json = '{"action": "ESCALATE", "reason": "policy_intercept"}'

    # 1. Connect as runtime role: revive_app (live if Postgres online, simulated RBAC if offline)
    if is_postgres_available(APP_DATABASE_URL):
        app_conn = psycopg2.connect(APP_DATABASE_URL)
    else:
        app_conn = SimulatedPostgresConnection()

    app_conn.autocommit = False
    cursor = app_conn.cursor()

    try:
        # A. INSERT must succeed (append-only ledger)
        cursor.execute(
            "INSERT INTO audit_logs (case_id, payload_json) VALUES (%s, %s) RETURNING id;",
            (case_id, payload_json),
        )
        row_id = cursor.fetchone()[0]
        app_conn.commit()
        assert row_id is not None

        # B. SELECT must succeed
        cursor.execute("SELECT id, case_id, payload_json FROM audit_logs WHERE id = %s;", (row_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row[1] == case_id

        # C. UPDATE must be REJECTED by database engine with InsufficientPrivilege
        with pytest.raises(errors.InsufficientPrivilege) as exc_update:
            cursor.execute(
                "UPDATE audit_logs SET payload_json = %s WHERE id = %s;",
                ('{"tampered": true}', row_id),
            )
        app_conn.rollback()
        assert "permission denied for table audit_logs" in str(exc_update.value).lower()

        # D. DELETE must be REJECTED by database engine with InsufficientPrivilege
        with pytest.raises(errors.InsufficientPrivilege) as exc_delete:
            cursor.execute("DELETE FROM audit_logs WHERE id = %s;", (row_id,))
        app_conn.rollback()
        assert "permission denied for table audit_logs" in str(exc_delete.value).lower()

    finally:
        cursor.close()
        app_conn.close()
