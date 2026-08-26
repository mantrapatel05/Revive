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


def test_api_approvals_endpoints(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, 'DATABASE_PATH', tmp_path/'test_api_app.db')
    import app.db as db
    monkeypatch.setattr(db, 'DATABASE_PATH', tmp_path/'test_api_app.db')
    init_db()

    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    app_id = create_approval_request('API-CASE-1', 5000.0, 'High value manual review')

    # GET /api/approvals/pending
    res = client.get('/api/approvals/pending')
    assert res.status_code == 200
    assert len(res.json()['approvals']) == 1
    assert res.json()['approvals'][0]['id'] == app_id

    # POST /api/approvals/{id}/resolve (Invalid decision)
    res_bad = client.post(f'/api/approvals/{app_id}/resolve', json={'decision': 'INVALID'})
    assert res_bad.status_code == 400

    # POST /api/approvals/{id}/resolve (Valid decision)
    res_ok = client.post(f'/api/approvals/{app_id}/resolve', json={'decision': 'APPROVED', 'reviewer': 'supervisor-bob'})
    assert res_ok.status_code == 200
    assert res_ok.json()['status'] == 'resolved'
    assert res_ok.json()['decision'] == 'APPROVED'

    # Pending queue should now be empty
    res_empty = client.get('/api/approvals/pending')
    assert len(res_empty.json()['approvals']) == 0


def test_merchant_config_endpoints(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, 'DATABASE_PATH', tmp_path/'test_config.db')
    import app.db as db
    monkeypatch.setattr(db, 'DATABASE_PATH', tmp_path/'test_config.db')
    init_db()

    from fastapi.testclient import TestClient
    from app.main import app
    from app.pipeline import RecoveryPipeline
    from app.policy.gate import PolicyGate
    from app.execution.simulator import SubscriptionSimulator

    # Setup pipeline on app state
    pipe = RecoveryPipeline(policy=PolicyGate(), simulator=SubscriptionSimulator(42))
    app.state.pipeline = pipe
    client = TestClient(app)

    # 1. GET /api/merchant-config
    res = client.get('/api/merchant-config')
    assert res.status_code == 200
    cfg = res.json()['config']
    assert cfg['risk_mode'] == 'BALANCED'
    assert cfg['max_auto_action_amount'] == 3000.0
    assert cfg['require_human_above'] == 10000.0

    # 2. PUT /api/merchant-config with new settings
    new_settings = {
        "risk_mode": "AGGRESSIVE",
        "max_auto_action_amount": 7500.0,
        "require_human_above": 15000.0,
        "max_customer_nudges_7d": 4
    }
    put_res = client.put('/api/merchant-config', json=new_settings)
    assert put_res.status_code == 200
    updated_cfg = put_res.json()['config']
    assert updated_cfg['risk_mode'] == 'AGGRESSIVE'
    assert updated_cfg['max_auto_action_amount'] == 7500.0
    assert updated_cfg['require_human_above'] == 15000.0
    assert updated_cfg['max_customer_nudges_7d'] == 4

    # 3. Verify pipeline state reflects the updated config
    assert pipe.risk_mode == 'AGGRESSIVE'
    assert pipe.risk_z == 0.0
    assert pipe.policy.max_auto_action_amount == 7500.0
    assert pipe.policy.require_human_above == 15000.0
    assert pipe.policy.max_customer_nudges_7d == 4


def test_pipeline_dynamic_merchant_config_behavior(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, 'DATABASE_PATH', tmp_path/'test_dyn_pipe.db')
    import app.db as db
    monkeypatch.setattr(db, 'DATABASE_PATH', tmp_path/'test_dyn_pipe.db')
    init_db()

    from app.pipeline import RecoveryPipeline
    from app.policy.gate import PolicyGate
    from app.execution.simulator import SubscriptionSimulator

    pipe = RecoveryPipeline(simulator=SubscriptionSimulator(42))

    # A case with amount 4999 (above default 3000 limit)
    case_high_val = {
        "event_id": "EVT-TEST-HIGH-VAL",
        "amount": 4999.0,
        "subscription_status": "pending",
        "customer_opted_out": False,
        "payment_method_type": "upi_autopay",
        "contact_count_7d": 1,
        "invoice_status": "issued",
        "attempt_number": 1,
        "nudge_incentive_cost": 0.0,
        "manual_recovery_ops_cost": 0.0,
        "escalation_ops_cost": 0.0,
        "native_retry_scheduled": False,
        "customer_tenure_days": 180
    }

    # Under default 3000 max_auto_action_amount:
    res_default = pipe.process(case_high_val, is_preview=True)
    # NUDGE should be blocked due to amount ceiling
    feasible = pipe.policy.feasible(case_high_val, {"NUDGE": 0.5, "WAIT": 0.1, "MANUAL_RECOVERY": 0.1})
    fin_check = next(c for c in feasible["NUDGE"].checks if c.check_id == "FIN-AUTO-002")
    assert not fin_check.passed
    assert "Amount exceeds automatic action ceiling" in feasible["NUDGE"].hard_failures

    # Now raise max_auto_action_amount to 6000
    pipe.update_merchant_config({"max_auto_action_amount": 6000.0})
    feasible_updated = pipe.policy.feasible(case_high_val, {"NUDGE": 0.5, "WAIT": 0.1, "MANUAL_RECOVERY": 0.1})
    # Now NUDGE passes amount ceiling check!
    fin_check_updated = next(c for c in feasible_updated["NUDGE"].checks if c.check_id == "FIN-AUTO-002")
    assert fin_check_updated.passed
    assert "Amount exceeds automatic action ceiling" not in feasible_updated["NUDGE"].hard_failures
