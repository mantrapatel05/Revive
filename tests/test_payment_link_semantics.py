import json
import time
import hmac
import hashlib
from datetime import datetime, timezone
import pytest

from app.db import init_db, get_conn
from app.pipeline import RecoveryPipeline
from app.execution.simulator import SubscriptionSimulator
from app.execution.live_executor import LiveExecutor
from app.execution.razorpay import RazorpayAdapter, RazorpayAPIError
from app.execution.reconciliation import (
    ReconciliationState,
    reconcile_payment_live,
    reconcile_webhook_event,
)
from app.events.idempotency import is_duplicate_event, record_event
from app.audit.logger import AuditLogger


class MockRazorpayAdapter:
    """Mock RazorpayAdapter returning real-shape Test Mode responses."""

    def __init__(self, should_fail=False, should_timeout=False, link_status="created"):
        self.should_fail = should_fail
        self.should_timeout = should_timeout
        self.link_status = link_status
        self.created_links = []

    def create_payment_link(self, amount_paise: int, description: str, customer: dict = None) -> dict:
        if self.should_timeout:
            raise RazorpayAPIError("Connection timed out waiting for Razorpay API")
        if self.should_fail:
            raise RazorpayAPIError("Bad Request: Invalid parameters")
        link_id = f"plink_mock_{int(time.time() * 1000)}"
        res = {
            "id": link_id,
            "short_url": f"https://rzp.io/rzp/{link_id[-8:]}",
            "status": "created",
            "amount": amount_paise,
            "amount_paid": 0,
            "description": description,
            "created_at": int(time.time()),
        }
        self.created_links.append(res)
        return res

    def fetch_payment_link(self, payment_link_id: str) -> dict:
        if self.should_timeout:
            raise RazorpayAPIError("Timeout connecting to Razorpay")
        if self.should_fail:
            raise RazorpayAPIError("Payment link not found")
        return {
            "id": payment_link_id,
            "status": self.link_status,
            "amount": 249900,
            "amount_paid": 249900 if self.link_status == "paid" else 0,
        }


def test_payment_link_creation_is_not_recovery():
    """Assert Payment Link API success produces EXECUTION_REQUESTED and PAYMENT_PENDING, NOT CONFIRMED or RECOVERED."""
    init_db()

    mock_adapter = MockRazorpayAdapter()
    live_executor = LiveExecutor(adapter=mock_adapter)
    pipeline = RecoveryPipeline(simulator=SubscriptionSimulator(42))
    pipeline.live_executor = live_executor

    case = {
        "event_id": "EVT-TEST-SEMANTICS-01",
        "subscription_id": "sub_sem_01",
        "customer_id": "cust_sem_01",
        "amount": 2499.0,
        "subscription_status": "pending",
        "invoice_status": "issued",
        "payment_method_type": "international_card",
        "attempt_number": 2,
        "contact_count_7d": 1,
        "customer_opted_out": False,
        "native_retry_scheduled": False,
        "is_live": True,
        "current_time": "2026-08-28T12:00:00+05:30",
    }

    # Execute manual recovery action directly
    exec_res = live_executor.execute(case, "MANUAL_RECOVERY")

    # 1. ExecutionResult asserts
    assert exec_res.status == "EXECUTION_REQUESTED"
    assert exec_res.success is False  # Payment not yet completed
    assert exec_res.recovered_amount == 0.0  # Zero money collected upon link creation
    assert exec_res.payment_link_id is not None
    assert exec_res.payment_link_id.startswith("plink_mock_")
    assert exec_res.payment_link_url is not None

    # 2. Pipeline processing asserts
    decision = pipeline.process(case)
    assert decision["chosen_action"] in ("MANUAL_RECOVERY", "NUDGE")
    assert decision["execution_status"] == "EXECUTION_REQUESTED"
    assert decision["execution_result"]["status"] == "EXECUTION_REQUESTED"
    assert decision["final_state"]["state"] == "PAYMENT_PENDING"
    assert decision["final_state"]["state"] != "CONFIRMED"
    assert decision["final_state"]["state"] != "RECOVERED"
    assert decision["recovered_amount"] == 0.0


def test_successful_payment_event_confirms_recovery():
    """Simulate a verified Razorpay payment-success webhook and assert final_state transitions to CONFIRMED."""
    init_db()

    mock_adapter = MockRazorpayAdapter()
    pipeline = RecoveryPipeline(simulator=SubscriptionSimulator(42))
    pipeline.live_executor = LiveExecutor(adapter=mock_adapter)

    case = {
        "event_id": "EVT-RECONCILE-02",
        "subscription_id": "sub_reconcile_02",
        "customer_id": "cust_02",
        "amount": 1999.0,
        "subscription_status": "pending",
        "invoice_status": "issued",
        "payment_method_type": "international_card",
        "attempt_number": 2,
        "contact_count_7d": 1,
        "customer_opted_out": False,
        "native_retry_scheduled": False,
        "is_live": True,
        "current_time": "2026-08-28T12:00:00+05:30",
    }

    # Process initial case and establish payment link
    decision = pipeline.process(case)
    created_link_id = decision["payment_link_id"]
    decision_id = decision["decision_id"]
    assert created_link_id is not None
    assert decision["final_state"]["state"] == "PAYMENT_PENDING"

    # Simulate inbound verified payment_link.paid webhook event from Razorpay
    webhook_event_id = "evt_rzp_paid_12345"
    payload = {
        "entity": "event",
        "event": "payment_link.paid",
        "contains": ["payment_link", "payment"],
        "payload": {
            "payment_link": {
                "entity": {
                    "id": created_link_id,
                    "status": "paid",
                    "amount": 199900,
                    "amount_paid": 199900,
                }
            },
            "payment": {
                "entity": {
                    "id": "pay_test_succ_999",
                    "status": "captured",
                    "amount": 199900,
                    "payment_link_id": created_link_id,
                }
            },
        },
    }

    recon_res = reconcile_webhook_event(payload, event_id=webhook_event_id)

    # Assert reconciliation result
    assert recon_res["status"] == "reconciled"
    assert recon_res["final_state"] == "CONFIRMED"
    assert recon_res["payment_link_id"] == created_link_id
    assert recon_res["payment_id"] == "pay_test_succ_999"
    assert recon_res["case_id"] == "EVT-RECONCILE-02"
    assert recon_res["decision_id"] == decision_id

    # Verify updated execution intent in database
    with get_conn() as conn:
        intent_row = conn.execute("SELECT * FROM execution_intents WHERE decision_id=?", (decision_id,)).fetchone()
        assert intent_row is not None
        assert intent_row["status"] == "CONFIRMED"
        raw_res = intent_row["result_json"]
        res_json = raw_res if isinstance(raw_res, dict) else json.loads(raw_res)
        assert res_json["final_state"]["state"] == "CONFIRMED"
        assert res_json["final_state"]["source"] == "razorpay_webhook"


def test_duplicate_payment_event_is_idempotent():
    """Send the same provider event twice and assert exactly one state transition without duplicate processing."""
    init_db()

    from fastapi.testclient import TestClient
    from app.main import app
    import app.api.webhooks as webhooks_mod

    webhooks_mod.RAZORPAY_WEBHOOK_SECRET = "test-secret"
    client = TestClient(app)

    event_id = "evt_dup_test_555"
    payload = {
        "entity": "event",
        "event": "payment_link.paid",
        "payload": {
            "payment_link": {
                "entity": {
                    "id": "plink_dup_001",
                    "status": "paid",
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

    # 1. First webhook delivery -> accepted
    res1 = client.post("/api/webhook/razorpay", content=raw_body, headers=headers)
    assert res1.status_code == 200
    assert res1.json()["status"] == "accepted"

    # 2. Second webhook delivery with identical event_id -> duplicate
    res2 = client.post("/api/webhook/razorpay", content=raw_body, headers=headers)
    assert res2.status_code == 200
    assert res2.json()["status"] == "duplicate"

    # Verify exactly one record in webhook_events table
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM webhook_events WHERE event_id=?", (event_id,)).fetchall()
        assert len(rows) == 1


def test_payment_link_timeout_is_not_false_recovery(tmp_path, monkeypatch):
    """Mock timeout during payment link status check and assert state remains UNKNOWN or PAYMENT_PENDING (never CONFIRMED)."""
    timeout_adapter = MockRazorpayAdapter(should_timeout=True)
    state = reconcile_payment_live("plink_timeout_123", adapter=timeout_adapter)
    assert state == ReconciliationState.UNKNOWN
    assert state != ReconciliationState.CONFIRMED

    # Active created link without payment completion is PAYMENT_PENDING
    pending_adapter = MockRazorpayAdapter(link_status="created")
    pending_state = reconcile_payment_live("plink_pending_123", adapter=pending_adapter)
    assert pending_state == ReconciliationState.PAYMENT_PENDING
    assert pending_state != ReconciliationState.CONFIRMED


def test_audit_distinguishes_execution_from_final_state():
    """Assert that the audit log distinctly records execution_result vs. final_state without conflation."""
    init_db()

    mock_adapter = MockRazorpayAdapter()
    pipeline = RecoveryPipeline(simulator=SubscriptionSimulator(42))
    pipeline.live_executor = LiveExecutor(adapter=mock_adapter)

    case = {
        "event_id": "EVT-AUDIT-SEP-01",
        "subscription_id": "sub_audit_01",
        "customer_id": "cust_audit_01",
        "amount": 2999.0,
        "subscription_status": "pending",
        "invoice_status": "issued",
        "payment_method_type": "international_card",
        "attempt_number": 2,
        "contact_count_7d": 1,
        "customer_opted_out": False,
        "native_retry_scheduled": False,
        "is_live": True,
        "current_time": "2026-08-28T12:00:00+05:30",
    }

    decision = pipeline.process(case)

    # Check decision record structure
    assert "execution_result" in decision
    assert "final_state" in decision
    assert decision["execution_result"]["status"] == "EXECUTION_REQUESTED"
    assert decision["final_state"]["state"] == "PAYMENT_PENDING"

    # Check persisted audit logs
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM audit_logs WHERE event_id=?", ("EVT-AUDIT-SEP-01",)).fetchone()
        assert row is not None
        raw_payload = row["payload_json"]
        payload = raw_payload if isinstance(raw_payload, dict) else json.loads(raw_payload)
        assert "execution_result" in payload
        assert "final_state" in payload
        assert payload["execution_result"]["status"] == "EXECUTION_REQUESTED"
        assert payload["final_state"]["state"] == "PAYMENT_PENDING"


def test_manual_recovery_does_not_claim_immediate_recovery():
    """Assert action name remains MANUAL_RECOVERY while state remains EXECUTION_REQUESTED / PAYMENT_PENDING before payment event."""
    init_db()

    mock_adapter = MockRazorpayAdapter()
    live_executor = LiveExecutor(adapter=mock_adapter)

    case = {
        "event_id": "EVT-MAN-REC-01",
        "subscription_id": "sub_man_rec_01",
        "amount": 1499.0,
        "subscription_status": "pending",
        "invoice_status": "issued",
        "payment_method_type": "international_card",
        "attempt_number": 2,
        "contact_count_7d": 1,
        "customer_opted_out": False,
        "native_retry_scheduled": False,
        "is_live": True,
        "current_time": "2026-08-28T12:00:00+05:30",
    }

    # 1. Direct executor invocation for MANUAL_RECOVERY
    exec_res = live_executor.execute(case, "MANUAL_RECOVERY")
    assert exec_res.action == "MANUAL_RECOVERY"
    assert exec_res.status == "EXECUTION_REQUESTED"
    assert exec_res.recovered_amount == 0.0
    assert exec_res.success is False

    # 2. Pipeline processing
    pipeline = RecoveryPipeline(simulator=SubscriptionSimulator(42))
    pipeline.live_executor = live_executor
    decision = pipeline.process(case)
    assert decision["execution_status"] == "EXECUTION_REQUESTED"
    assert decision["final_state"]["state"] == "PAYMENT_PENDING"
    assert decision["recovered_amount"] == 0.0
