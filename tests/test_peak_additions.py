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
