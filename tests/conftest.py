"""PostgreSQL test isolation for REVIVE.

Tests intentionally use the same migration-managed schema as the application.
The administrator role clears operational data between tests; the application
role remains unable to modify the append-only audit ledger directly.
"""

import pytest

from app.db import get_conn


@pytest.fixture(autouse=True)
def reset_operational_data():
    tables = "execution_intents, webhook_events, approval_queue, decision_records, merchant_config"
    with get_conn(admin=True) as conn:
        conn.execute(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE")
    yield
    with get_conn(admin=True) as conn:
        conn.execute(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE")
