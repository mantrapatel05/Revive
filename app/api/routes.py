import json
from pathlib import Path
import pandas as pd
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from app.config import DATA_DIR, RESULTS_DIR, ENABLE_TESTMODE_EXECUTION, RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET
from app.approval import get_pending_approvals, resolve_approval
from app.receipt import generate_receipt_data, render_receipt_html

router = APIRouter()

@router.get('/api/health')
def health():
    return {'status': 'ok', 'service': 'revive', 'version': '6.0'}

@router.get('/api/policy-spec')
def policy_spec():
    spec_path = Path(__file__).resolve().parents[2] / 'docs/POLICY_SPEC.md'
    content = spec_path.read_text(encoding='utf-8') if spec_path.exists() else ""
    return {
        "title": "REVIVE 6.0 — Deterministic Policy Specification",
        "raw_markdown": content,
        "hard_constraints": [
            {
                "check_id": "TIME-QUIET-001",
                "name": "Quiet Hours Compliance",
                "logic": "08:00 <= current_time_IST < 19:00",
                "enforcement": "Rejects NUDGE and MANUAL_RECOVERY outside 08:00–19:00 IST with outside_quiet_hours; WAIT allowed"
            },
            {
                "check_id": "FREQ-DAILY-001",
                "name": "Daily Frequency Cap",
                "logic": "case.contacted_today == False",
                "enforcement": "Rejects NUDGE and MANUAL_RECOVERY on same-day repeat touches with daily_contact_cap; WAIT allowed"
            },
            {
                "check_id": "CUST-OPT-001",
                "name": "Customer Opt-Out Compliance",
                "logic": "case.customer_opted_out == False",
                "enforcement": "Blocks NUDGE and MANUAL_RECOVERY immediately; routes to WAIT or ESCALATE"
            },
            {
                "check_id": "SUB-STATE-001",
                "name": "Eligible Subscription State",
                "logic": "case.subscription_status in {'pending', 'halted'}",
                "enforcement": "Blocks automated recovery on canceled/terminated subscriptions"
            },
            {
                "check_id": "WAIT-STATE-001",
                "name": "Native Retry Eligibility",
                "logic": "case.subscription_status == 'pending'",
                "enforcement": "Forbids WAIT if subscription is already halted (no native retry exists)"
            },
            {
                "check_id": "FIN-AUTO-002",
                "name": "Automatic Action Ceiling",
                "logic": "case.amount <= merchant_config.max_auto_action_amount",
                "enforcement": "Blocks automated outreach on high-value transactions; mandates human escalation"
            },
            {
                "check_id": "RET-LIMIT-001",
                "name": "Attempt Budget Limit",
                "logic": "case.attempt_number < 4",
                "enforcement": "Blocks additional automated retry attempts after 4 failed cycles"
            },
            {
                "check_id": "INV-ELIG-001",
                "name": "Invoice Chargeability",
                "logic": "case.invoice_status == 'issued'",
                "enforcement": "Forbids manual charge paths on draft, paid, or voided invoices"
            },
            {
                "check_id": "PM-ELIG-001",
                "name": "Payment Method Support",
                "logic": "case.payment_method_type != 'domestic_card'",
                "enforcement": "Rejects manual recovery attempts on domestic cards requiring step-up 2FA"
            },
            {
                "check_id": "DUP-NATIVE-001",
                "name": "Native Retry Collision",
                "logic": "case.native_retry_scheduled == False",
                "enforcement": "Blocks manual charging when gateway has active retry scheduled"
            },
            {
                "check_id": "PROB-MIN-001",
                "name": "Minimum Probability Floor",
                "logic": "P_cal(MANUAL_RECOVERY) >= 0.20",
                "enforcement": "Rejects low-probability manual outreach where cost exceeds recovery likelihood"
            }
        ]
    }

@router.get('/api/evaluation')
def evaluation():
    p = RESULTS_DIR / 'final_results.json'
    return json.loads(p.read_text()) if p.exists() else {'error': 'Run scripts/evaluate_final.py first'}

@router.get('/api/audit')
def audit(request: Request, limit: int = 50):
    return {'logs': request.app.state.audit.recent(limit)}

@router.post('/api/run-case')
async def run_case(request: Request):
    body = await request.json()
    event_id = body.get('event_id')
    raw_risk_mode = body.get('risk_mode')
    if not event_id:
        raise HTTPException(400, 'event_id required')
    p = DATA_DIR / 'eval_cases.csv'
    if not p.exists():
        raise HTTPException(500, 'Generate evaluation data first')
    df = pd.read_csv(p)
    row = df[df.event_id == event_id]
    if row.empty:
        raise HTTPException(404, 'case not found')
    case = row.iloc[0].to_dict()
    pipe = request.app.state.pipeline
    is_preview = raw_risk_mode is not None
    risk_mode = str(raw_risk_mode).upper() if raw_risk_mode is not None else pipe.risk_mode
    if risk_mode not in pipe.RISK_MODES:
        raise HTTPException(400, f"Invalid risk_mode '{risk_mode}'. Must be one of: {list(pipe.RISK_MODES.keys())}")
    return pipe.process(case, source="ml", risk_mode=risk_mode, is_preview=is_preview)

@router.get('/api/random-case')
def random_case():
    p = DATA_DIR / 'eval_cases.csv'
    if not p.exists():
        raise HTTPException(500, 'Generate evaluation data first')
    df = pd.read_csv(p)
    if df.empty:
        raise HTTPException(404, 'no evaluation cases')
    row = df.sample(1, random_state=None).iloc[0]
    return {'event_id': row['event_id']}

@router.get('/api/replay/{case_id}')
def replay(case_id: str, request: Request):
    p = DATA_DIR / 'eval_cases.csv'
    if not p.exists():
        raise HTTPException(500, 'Generate evaluation data first')
    df = pd.read_csv(p)
    row = df[df.event_id == case_id]
    if row.empty:
        raise HTTPException(404, 'case not found')
    case = row.iloc[0].to_dict()
    sim = request.app.state.pipeline.simulator
    true = {a: sim.get_true_probability(case, a) for a in sim.ACTIONS}
    values = sim.economics.rank_incremental(case, true)
    return {'case_id': case_id, 'probabilities': true, 'expected_net_values': values}

@router.get('/')
def dashboard():
    return FileResponse(Path(__file__).resolve().parents[2] / 'frontend/index.html')


@router.get('/api/approvals/pending')
@router.get('/api/approvals')
def pending_approvals():
    return {"approvals": get_pending_approvals()}

@router.post('/api/approvals/{approval_id}/resolve')
async def resolve_approval_route(approval_id: int, request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    decision = str(body.get('decision', '')).upper()
    if decision not in {"APPROVED", "REJECTED"}:
        raise HTTPException(400, "decision must be 'APPROVED' or 'REJECTED'")

    reviewer = str(body.get('reviewer', 'human-reviewer')).strip() or 'human-reviewer'
    try:
        updated = resolve_approval(approval_id, decision, reviewer)
    except Exception as exc:
        raise HTTPException(400, str(exc))

    if not updated:
        raise HTTPException(404, f"Approval request with id {approval_id} not found")

    return {
        "status": "resolved",
        "approval_id": approval_id,
        "decision": decision,
        "reviewer": reviewer
    }


@router.get('/api/merchant-config')
def get_merchant_config_route(request: Request):
    pipe = request.app.state.pipeline
    return {"config": pipe.merchant_config.to_dict()}


@router.put('/api/merchant-config')
async def update_merchant_config_route(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    pipe = request.app.state.pipeline
    try:
        updated = pipe.update_merchant_config(body)
        return {"status": "updated", "config": updated.to_dict()}
    except Exception as exc:
        raise HTTPException(400, str(exc))


@router.get('/api/explain/{case_id}')
def explain_case(case_id: str, request: Request):
    p = DATA_DIR / 'eval_cases.csv'
    if not p.exists(): raise HTTPException(500, 'Generate evaluation data first')
    df = pd.read_csv(p); row = df[df.event_id == case_id]
    if row.empty: raise HTTPException(404, 'case not found')
    from app.explain import SHAPExplainer
    pipe=request.app.state.pipeline
    if pipe.model is None: return {'available':False,'reason':'No trained model loaded'}
    chosen=pipe.process(row.iloc[0].to_dict())['chosen_action']
    return SHAPExplainer(pipe.model).explain_case(row.iloc[0].to_dict(), chosen)


@router.get('/api/decisions/{decision_id}')
def get_decision(decision_id: str, request: Request):
    rec = request.app.state.pipeline.decision_store.get_decision(decision_id)
    if rec is None:
        raise HTTPException(404, 'decision not found')
    return rec

@router.post('/api/decisions/{decision_id}/replay')
def replay_decision(decision_id: str, request: Request):
    try:
        return request.app.state.pipeline.decision_store.replay_with_current(decision_id, request.app.state.pipeline)
    except ValueError as exc:
        raise HTTPException(404, str(exc))

@router.get('/api/receipt/{case_id}')
def api_receipt(case_id: str, request: Request):
    p = DATA_DIR / 'eval_cases.csv'
    if not p.exists():
        raise HTTPException(500, 'Generate evaluation data first')
    df = pd.read_csv(p)
    row = df[df.event_id == case_id]
    if row.empty:
        raise HTTPException(404, 'case not found')
    case = row.iloc[0].to_dict()
    pipe = request.app.state.pipeline
    decision = pipe.process(case, is_preview=True)
    return generate_receipt_data(decision)

@router.get('/receipt/{case_id}', response_class=HTMLResponse)
def view_receipt(case_id: str, request: Request):
    p = DATA_DIR / 'eval_cases.csv'
    if not p.exists():
        raise HTTPException(500, 'Generate evaluation data first')
    df = pd.read_csv(p)
    row = df[df.event_id == case_id]
    if row.empty:
        raise HTTPException(404, 'case not found')
    case = row.iloc[0].to_dict()
    pipe = request.app.state.pipeline
    decision = pipe.process(case, is_preview=True)
    receipt_data = generate_receipt_data(decision)
    return HTMLResponse(render_receipt_html(receipt_data))
