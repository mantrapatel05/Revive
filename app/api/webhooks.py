import json
from fastapi import APIRouter, Request, HTTPException
from app.config import RAZORPAY_WEBHOOK_SECRET
from app.events.signature import verify_razorpay_signature, extract_event_id
from app.events.idempotency import record_event

router = APIRouter()

@router.post('/api/webhook/razorpay')
async def razorpay_webhook(request: Request):
    raw_body = await request.body()
    signature = request.headers.get('x-razorpay-signature', '')
    event_id = extract_event_id(request.headers)
    if not RAZORPAY_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail='Webhook secret is not configured')
    if not event_id:
        raise HTTPException(status_code=400, detail='Missing x-razorpay-event-id')
    if not verify_razorpay_signature(raw_body, signature, RAZORPAY_WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail='Invalid Razorpay webhook signature')
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail='Invalid JSON') from exc

    event_type = str(payload.get('event', ''))
    inserted = record_event(event_id, event_type, payload)
    if not inserted:
        return {'status': 'duplicate', 'event_id': event_id}

    # Intentionally no external side-effect is executed here. Razorpay considers non-2xx
    # responses delivery failures and retries; durable inbox processing happens out-of-band.
    return {'status': 'accepted', 'event_id': event_id, 'event': event_type}
