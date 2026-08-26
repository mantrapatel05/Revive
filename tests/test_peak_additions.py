from app.models.uplift import TwoModelUplift
from app.approval import create_approval_request, get_pending_approvals, resolve_approval
from app.db import init_db

def test_uplift_module_has_actions():
    assert TwoModelUplift.ACTIONS == ['NUDGE','MANUAL_RECOVERY']

def test_approval_queue_roundtrip(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, 'DATABASE_PATH', tmp_path/'t.db')
    import app.db as db
    monkeypatch.setattr(db, 'DATABASE_PATH', tmp_path/'t.db')
    init_db()
    approval_id=create_approval_request('CASE-X', 9000, 'high value')
    assert get_pending_approvals()[0]['id']==approval_id
    resolve_approval(approval_id,'APPROVED','tester')
    assert get_pending_approvals()==[]


def test_pipeline_escalate_creates_approval_request(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, 'DATABASE_PATH', tmp_path/'test_pipeline.db')
    import app.db as db
    monkeypatch.setattr(db, 'DATABASE_PATH', tmp_path/'test_pipeline.db')
    init_db()

    from app.pipeline import RecoveryPipeline
    from app.policy.gate import PolicyGate
    from app.execution.simulator import SubscriptionSimulator

    pipe = RecoveryPipeline(policy=PolicyGate(), simulator=SubscriptionSimulator(42))

    # Case that forces ESCALATE: subscription halted and customer opted out with amount > 3000
    case_escalate = {
        'event_id': 'ESC-001',
        'amount': 15000.0,
        'attempt_number': 4,
        'subscription_status': 'halted',
        'customer_opted_out': True,
        'failure_reason': 'bank_declined',
        'native_retry_scheduled': False,
    }

    res = pipe.process(case_escalate, source='sim')
    assert res['chosen_action'] == 'ESCALATE'
    assert res['approval_id'] is not None

    pending = get_pending_approvals()
    assert len(pending) == 1
    req = pending[0]
    assert req['case_id'] == 'ESC-001'
    assert req['amount'] == 15000.0
    assert req['status'] == 'PENDING'
    assert 'Customer opted out' in req['reason'] or 'Amount within automatic action ceiling' in req['reason']

    import json
    payload = json.loads(req['payload_json'])
    assert 'probabilities' in payload
    assert 'policy_reasons' in payload
    assert 'chosen_action' in payload
    assert payload['chosen_action'] == 'ESCALATE'
    assert 'uncertainty' in payload
