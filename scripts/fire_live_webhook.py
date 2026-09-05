import hmac
import hashlib
import json
import time
import requests
from app.config import RAZORPAY_WEBHOOK_SECRET

def fire_webhook():
    secret = (RAZORPAY_WEBHOOK_SECRET or "revive-webhook-secret-123").encode("utf-8")
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
    
    # We use the current timestamp to make sure the event ID is always unique 
    # so it doesn't get blocked as a duplicate from previous runs!
    event_id = f"evt_live_demo_{int(time.time())}"
    
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
