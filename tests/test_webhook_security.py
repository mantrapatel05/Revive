import hashlib,hmac
from app.events.signature import verify_razorpay_signature

def test_signature():
    body=b'{"event":"subscription.pending"}'; secret='abc'; sig=hmac.new(secret.encode(),body,hashlib.sha256).hexdigest(); assert verify_razorpay_signature(body,sig,secret); assert not verify_razorpay_signature(body,sig+'x',secret)
