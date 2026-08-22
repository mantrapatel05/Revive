import json
import sys
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import MODEL_DIR
from app.db import init_db, claim_webhook_events, mark_webhook_processed, mark_webhook_failed, get_conn
from app.models.calibrated_tlearner import CalibratedTLearner
from app.pipeline import RecoveryPipeline


def build_case(payload: dict) -> dict:
    sub = payload.get('payload', {}).get('subscription', {}).get('entity', payload.get('payload', {}).get('subscription', {}))
    event_type = payload.get('event', '')
    status = sub.get('status') or ('pending' if event_type == 'subscription.pending' else 'halted' if event_type == 'subscription.halted' else 'unknown')
    amount = float(sub.get('amount', sub.get('charge_at', 0)) or 0)
    if amount > 100: amount /= 100.0
    return {
        'event_id': f"web-{sub.get('id','unknown')}-{event_type}",
        'subscription_id': sub.get('id','unknown'),
        'customer_id': sub.get('customer_id','unknown'),
        'amount': amount,
        'attempt_number': int(sub.get('charge_attempt_count', sub.get('auth_attempts', 1)) or 1),
        'failure_source': 'unknown',
        'failure_reason': 'UNKNOWN_FROM_WEBHOOK',
        'days_since_last_success': 0,
        'prior_recoveries_count': 0,
        'payment_method_age_days': 0,
        'customer_tenure_days': 0,
        'previous_success_rate': 0.5,
        'previous_recovery_rate': 0.0,
        'customer_opted_out': False,
        'subscription_status': status,
        'payment_method_type': 'unknown',
        'invoice_status': 'unknown',
        'native_retry_scheduled': status == 'pending',
    }


def main_once(limit=20):
    init_db()
    model = None
    model_path = MODEL_DIR / 'calibrated_tlearner.joblib'
    if model_path.exists():
        model = CalibratedTLearner(MODEL_DIR)
        model.load()
    pipeline = RecoveryPipeline(model=model)
    rows = claim_webhook_events(limit)
    for row in rows:
        try:
            payload = json.loads(row['payload_json'])
            event_type = row['event_type'] or payload.get('event','')
            if event_type in {'subscription.pending', 'subscription.halted'}:
                case = build_case(payload)
                pipeline.process(case)
            mark_webhook_processed(row['event_id'], datetime.now(timezone.utc).isoformat())
        except Exception as exc:
            mark_webhook_failed(row['event_id'], repr(exc))
    return len(rows)

if __name__ == '__main__':
    print(f'Processed {main_once()} webhook inbox events')
