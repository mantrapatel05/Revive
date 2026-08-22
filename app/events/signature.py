import hashlib
import hmac
from typing import Mapping, Optional

def verify_razorpay_signature(raw_body: bytes, received_signature: str, secret: str) -> bool:
    if not secret or not received_signature:
        return False
    expected = hmac.new(secret.encode('utf-8'), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, received_signature)

def extract_event_id(headers: Mapping[str, str]) -> Optional[str]:
    return headers.get('x-razorpay-event-id')
