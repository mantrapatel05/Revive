import json
from pathlib import Path
import pandas as pd
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from app.config import DATA_DIR, RESULTS_DIR, ENABLE_TESTMODE_EXECUTION, RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET
from app.approval import get_pending_approvals, resolve_approval

router = APIRouter()

@router.get('/api/health')
def health():
    return {'status': 'ok', 'service': 'revive', 'version': '6.0'}

@router.get('/api/evaluation')
def evaluation():
    p = RESULTS_DIR / 'final_results.json'
    return json.loads(p.read_text()) if p.exists() else {'error': 'Run scripts/evaluate_final.py first'}

@router.get('/api/audit')
def audit(request: Request, limit: int = 50):
    return {'logs': request.app.state.audit.recent(limit)}

@router.post('/api/create-payment-link')
async def create_payment_link_route(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    event_id = body.get('event_id', 'EVT-TEST')
    amount = float(body.get('amount', 1999.0))
    if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
        raise HTTPException(400, "Razorpay credentials not set in .env")
    try:
        from app.execution.razorpay import RazorpayAdapter
        adapter = RazorpayAdapter()
        res = adapter.create_payment_link(
            amount_paise=int(amount * 100),
            description=f"REVIVE Recovery Checkout for {event_id}",
        )
        return {
            "status": "created",
            "payment_link_id": res.get("id"),
            "short_url": res.get("short_url"),
            "amount": amount,
            "event_id": event_id,
        }
    except Exception as exc:
        raise HTTPException(502, f"Razorpay link creation failed: {exc}")

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
    if ENABLE_TESTMODE_EXECUTION:
        case['is_live'] = True
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
