import hmac
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

# Ensure project root is on sys.path so `import app.*` works when running
# as `py scripts/fire_live_webhook.py` (Python adds `scripts/` to sys.path, not project root)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv()

try:
    from app.config import RAZORPAY_WEBHOOK_SECRET  # type: ignore
except ModuleNotFoundError:
    RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")

def fire_webhook():
    secret = (RAZORPAY_WEBHOOK_SECRET or os.getenv("RAZORPAY_WEBHOOK_SECRET", "revive-webhook-secret-123")).encode("utf-8")
    payload = {
        "entity": "event",
        "account_id": "acc_enterprise_prod",
        "event": "payment.failed",
        "contains": ["payment"],
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_demo_999",
                    "amount": 249900,
                    "currency": "INR",
                    "status": "failed",
                    "method": "card",
                    "international": False,
                    "contact": "+919876543210",
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_source": "bank",
                    "error_reason": "payment_failed",
                }
            }
        }
    }
    
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(secret, body, hashlib.sha256).hexdigest()
    
    # IMPORTANT FOR DEMO RECORDING: 
    # Using a fixed ID guarantees the second run always triggers the "duplicate" idempotency logic.
    # To do a fresh take or dry run, change "001" to "002", etc., before you start recording!
    event_id = "evt_live_demo_fixed_001"
    
    headers = {
        "Content-Type": "application/json",
        "x-razorpay-event-id": event_id,
        "x-razorpay-signature": sig
    }
    
    print(f"Firing live webhook to backend: {event_id}...")
    try:
        r = requests.post("http://127.0.0.1:8000/api/webhook/razorpay", data=body, headers=headers)
        print(f"HTTP {r.status_code}")
        print(r.json())
        print(f"\nSUCCESS! Go check your dashboard for {event_id}. The Payment Link should be visible in the Execution Trace.")
    except Exception as e:
        print(f"Failed to connect to backend: {e}")

if __name__ == "__main__":
    fire_webhook()
