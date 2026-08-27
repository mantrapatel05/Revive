import json
from fastapi import APIRouter, Request, HTTPException
from app.config import RAZORPAY_WEBHOOK_SECRET
from app.events.signature import verify_razorpay_signature, extract_event_id
from app.events.idempotency import record_event
from app.execution.reconciliation import reconcile_webhook_event

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

    # If this is a payment resolution event, correlate and reconcile final state
    if event_type in {'payment_link.paid', 'payment.captured', 'invoice.paid', 'order.paid', 'payment_link.cancelled', 'payment_link.expired'}:
        reconciliation_result = reconcile_webhook_event(payload, event_id=event_id)
        return {'status': 'accepted', 'event_id': event_id, 'event': event_type, 'reconciliation': reconciliation_result}

    return {'status': 'accepted', 'event_id': event_id, 'event': event_type}
