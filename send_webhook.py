import hmac
import hashlib
import json
import requests
from dotenv import load_dotenv
import os

load_dotenv()
secret = os.getenv('RAZORPAY_WEBHOOK_SECRET', 'revive-webhook-secret-123')

# Example webhook payload - matches the error.md bank/payment_failed case
payload_dict = {
    "event": "payment_link.paid",
    "payload": {
        "payment_link": {
            "entity": "payment_link",
            "id": "plink_demo",
            "status": "paid",
            "amount": 199900
        },
        "payment": {
            "entity": "payment",
            "status": "captured"
        }
    }
}

# Use separators (',', ':') to get canonical JSON exactly as sent
body = json.dumps(payload_dict, separators=(',', ':'))
sig = hmac.new(secret.encode('utf-8'), body.encode('utf-8'), hashlib.sha256).hexdigest()

print(f"secret: {secret}")
print(f"sig: {sig}")
print(f"body: {body}")

r = requests.post(
    'http://127.0.0.1:8000/api/webhook/razorpay',
    data=body,
    headers={
        'Content-Type': 'application/json',
        'x-razorpay-event-id': 'evt_live_demo_007',
        'x-razorpay-signature': sig
    },
    timeout=10
)
print(r.status_code)
print(r.text)
