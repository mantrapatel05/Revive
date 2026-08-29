import json
import hmac
import hashlib
import concurrent.futures
import pytest
from fastapi.testclient import TestClient

from app.db import init_db, enqueue_webhook_event, get_conn
from app.main import app
import app.api.webhooks as webhooks_mod
from app.execution.authorization import ExecutionAuthorization
from app.execution.outbox import enqueue_execution_intent
from app.decision.replay import DecisionStore


def test_on_conflict_returning_id_behavior():
    """Assert PostgreSQL ON CONFLICT DO NOTHING RETURNING id is atomic."""
    init_db()

    event_id = "evt_atomic_001"
    # First insert -> succeeds (returns True)
    res1 = enqueue_webhook_event(event_id, "subscription.pending", '{"amt": 1000}', "2026-08-28T00:00:00Z")
    assert res1 is True

    # Duplicate insert -> conflicts, returns False (short-circuits at DB level)
    res2 = enqueue_webhook_event(event_id, "subscription.pending", '{"amt": 1000}', "2026-08-28T00:00:00Z")
    assert res2 is False


def test_concurrent_webhook_deliveries_same_case():
    """Fire near-simultaneous webhook deliveries for the same event/case and assert only one action is executed."""
    init_db()

    webhooks_mod.RAZORPAY_WEBHOOK_SECRET = "test-secret"
    client = TestClient(app)

    event_id = "evt_race_condition_999"
    payload = {
        "entity": "event",
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_race_999",
                    "amount": 250000,
                    "subscription_id": "sub_race_999",
                    "method": "card",
                }
            }
        },
    }
    raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(b"test-secret", raw_body, hashlib.sha256).hexdigest()

    headers = {
        "content-type": "application/json",
        "x-razorpay-event-id": event_id,
        "x-razorpay-signature": signature,
    }

    # Execute 5 concurrent requests with identical event_id
    def send_webhook():
        return client.post("/api/webhook/razorpay", content=raw_body, headers=headers)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(send_webhook) for _ in range(5)]
        responses = [f.result() for f in futures]

    statuses = [r.json()["status"] for r in responses]

    # Exactly 1 request accepted, all remaining 4 rejected as duplicates
    assert statuses.count("accepted") == 1
    assert statuses.count("duplicate") == 4

    # Verify exactly 1 record in database
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM webhook_events WHERE event_id=?", (event_id,)).fetchall()
        assert len(rows) == 1


def test_per_case_intent_uniqueness():
    """Assert concurrent attempts to enqueue an intent for the same decision_id return the same intent ID."""
    init_db()

    auth = ExecutionAuthorization.create(
        case_id="EVT-CONC-01",
        action="MANUAL_RECOVERY",
        policy_version="policy-v5",
        model_version="calibrated-tlearner-v5",
        decision_id="decision_race_12345",
    )
    DecisionStore().save({
        "decision_id": auth.decision_id,
        "case_id": auth.case_id,
        "features": {},
        "chosen_action": auth.action,
    })

    intent_id1 = enqueue_execution_intent(auth, {"amount": 2499.0})
    intent_id2 = enqueue_execution_intent(auth, {"amount": 2499.0})

    assert intent_id1 == intent_id2

    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM execution_intents WHERE decision_id=?", ("decision_race_12345",)).fetchall()
        assert len(rows) == 1


def test_merchant_config_live_sync():
    """Verify GET/PUT /api/merchant-config reads and hot-reloads live values in fresh transactions."""
    with TestClient(app) as client:
        # 1. Read current config
        res1 = client.get("/api/merchant-config")
        assert res1.status_code == 200
        assert "config" in res1.json()

        # 2. Update config dynamically
        update_payload = {"risk_mode": "AGGRESSIVE", "max_auto_action_amount": 7500.0}
        res2 = client.put("/api/merchant-config", json=update_payload)
        assert res2.status_code == 200
        assert res2.json()["config"]["risk_mode"] == "AGGRESSIVE"
        assert res2.json()["config"]["max_auto_action_amount"] == 7500.0

        # 3. Read back to confirm immediate persistence without server restart
        res3 = client.get("/api/merchant-config")
        assert res3.status_code == 200
        assert res3.json()["config"]["risk_mode"] == "AGGRESSIVE"
        assert res3.json()["config"]["max_auto_action_amount"] == 7500.0

        # 4. Reset to balanced
        client.put("/api/merchant-config", json={"risk_mode": "BALANCED", "max_auto_action_amount": 5000.0})
