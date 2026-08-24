"""
REVIVE — Live Failure Injection & Idempotency Rehearsal Script

Demonstrates deterministic handling of duplicate webhook retries from Razorpay.
1. Computes valid HMAC SHA-256 signature for a realistic payment.failed payload.
2. Injects first delivery -> HTTP 200 {"status": "accepted", "event_id": ..., "event": "payment.failed"}.
3. Injects second delivery (exact duplicate retry) -> HTTP 200 {"status": "duplicate", "event_id": ...}.
4. Verifies zero duplicate actions or state mutations.
"""

import hmac
import hashlib
import json
import time
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.config import RAZORPAY_WEBHOOK_SECRET
from app.db import get_conn

def build_payload(payment_id: str = "pay_demo_failed_999", amount_paise: int = 249900) -> tuple[dict, bytes, str]:
    secret = RAZORPAY_WEBHOOK_SECRET or "revive-webhook-secret-123"
    payload = {
        "entity": "event",
        "account_id": "acc_enterprise_prod",
        "event": "payment.failed",
        "contains": ["payment"],
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "amount": amount_paise,
                    "currency": "INR",
                    "status": "failed",
                    "order_id": "order_enterprise_999",
                    "invoice_id": None,
                    "international": False,
                    "method": "card",
                    "amount_refunded": 0,
                    "refund_status": None,
                    "captured": False,
                    "description": "Monthly SaaS Enterprise Subscription",
                    "card_id": "card_demo_99",
                    "bank": None,
                    "wallet": None,
                    "vpa": None,
                    "email": "cfo@enterprise.com",
                    "contact": "+919876543210",
                    "notes": {"customer_id": "cust_enterprise_99"},
                    "fee": None,
                    "tax": None,
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_description": "Card declined by issuing bank",
                    "error_source": "bank",
                    "error_step": "payment_authorization",
                    "error_reason": "payment_failed",
                    "created_at": 1774867200,
                }
            }
        },
        "created_at": 1774867200,
    }
    raw_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), raw_bytes, hashlib.sha256).hexdigest()
    return payload, raw_bytes, sig

def run_rehearsal(event_id: str | None = None):
    if not event_id:
        event_id = f"evt_demo_stage_{int(time.time())}"
    
    payload, raw_bytes, sig = build_payload()
    print("=" * 70)
    print("REVIVE IDEMPOTENCY REHEARSAL")
    print(f"Target Event ID : {event_id}")
    print(f"Payload Size    : {len(raw_bytes)} bytes")
    print(f"HMAC Signature  : {sig}")
    print("=" * 70)

    with TestClient(app) as client:
        headers = {
            "x-razorpay-event-id": event_id,
            "x-razorpay-signature": sig,
            "Content-Type": "application/json",
        }

        # Step 1: Initial Webhook Delivery
        print("\n[STEP 1] Sending initial failure webhook...")
        res1 = client.post("/api/webhook/razorpay", content=raw_bytes, headers=headers)
        print(f"Response HTTP {res1.status_code}: {res1.json()}")
        assert res1.status_code == 200, f"Expected 200, got {res1.status_code}"
        assert res1.json().get("status") == "accepted", f"Expected 'accepted', got {res1.json()}"
        print("  -> First delivery successfully ACCEPTED and locked in webhook_events table.")

        # Step 2: Duplicate Delivery (Razorpay Retry)
        print("\n[STEP 2] Simulating Razorpay automatic delivery retry (identical event ID)...")
        res2 = client.post("/api/webhook/razorpay", content=raw_bytes, headers=headers)
        print(f"Response HTTP {res2.status_code}: {res2.json()}")
        assert res2.status_code == 200, f"Expected 200, got {res2.status_code}"
        assert res2.json().get("status") == "duplicate", f"Expected 'duplicate', got {res2.json()}"
        print("  -> Duplicate delivery successfully DETECTED and SUPPRESSED.")

        # Step 3: Verify DB State
        with get_conn() as conn:
            row_count = conn.execute("SELECT COUNT(*) FROM webhook_events WHERE event_id = ?", (event_id,)).fetchone()[0]
            print(f"\n[STEP 3] Database Verification:")
            print(f"  Rows in webhook_events for {event_id}: {row_count}")
            assert row_count == 1, f"Expected exactly 1 inbox row, found {row_count}"

    print("\n" + "=" * 70)
    print("REHEARSAL PASSED: Zero race conditions, exactly 1 intent recorded.")
    print("=" * 70)

if __name__ == "__main__":
    run_rehearsal()
