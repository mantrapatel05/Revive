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
    if 'is_live' in body:
        case['is_live'] = body['is_live']
    pipe = request.app.state.pipeline
    is_live_req = bool(body.get('is_live', False))
    # Live execution must not be treated as preview: preview is risk-dial exploration without side effects.
    # When is_live is true we ignore explicit risk_mode and use persisted merchant config.
    is_preview = raw_risk_mode is not None and not is_live_req
    if is_live_req:
        risk_mode = pipe.risk_mode
    else:
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

@router.get('/demo/pay/{link_id}', response_class=HTMLResponse)
def demo_pay_page(link_id: str, request: Request):
    """Local demo checkout page for when Razorpay Test Mode is rate-limited (429).
    Shows a working payment page for demo recording instead of dead rzp.io link.
    """
    from app.execution.razorpay import RazorpayAdapter
    data = RazorpayAdapter._DEMO_STORE.get(link_id, {})
    amount_paise = int(data.get("amount_paise") or data.get("amount") or 0)
    amount_inr = amount_paise / 100 if amount_paise else 0
    desc = data.get("description") or f"REVIVE recovery — {link_id}"
    # Fallback if not in store (e.g., real rzp.io link or direct access)
    if not data:
        # Try to show generic demo
        amount_inr = 1999
        desc = f"REVIVE Test Mode Payment — {link_id}"
    # Pretty amount
    amount_str = f"₹{amount_inr:,.2f}" if amount_inr else "₹1,999.00"
    html = f"""
<!doctype html>
<html lang=\"en\">
<head>
<meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>REVIVE — Test Checkout {link_id}</title>
<style>
:root{{--paper:#F6F3EA;--ink:#1E1C18;--stamp:#1F3A5F;--rule:#DBD4C2;}}
*{{box-sizing:border-box}}body{{margin:0;font:14px/1.5 system-ui;background:var(--paper);color:var(--ink);display:grid;place-items:center;min-height:100vh;padding:24px}}
.card{{max-width:480px;width:100%;background:#fff;border:1px solid var(--rule);border-top:3px solid var(--stamp);padding:28px;box-shadow:0 4px 24px rgba(0,0,0,.06)}}
.badge{{display:inline-flex;align-items:center;gap:6px;padding:4px 8px;border:1px solid var(--stamp);color:var(--stamp);font:700 10px system-ui;letter-spacing:.06em;text-transform:uppercase;background:#E3E9F1}}
h1{{margin:14px 0 6px;font:600 20px Georgia}} .muted{{color:#55524A;font-size:12px}}
.amount{{margin:18px 0;font:700 32px ui-monospace;letter-spacing:-.02em}} .desc{{padding:12px;background:#F6F3EA;border-left:2px solid var(--stamp);font-size:12px;line-height:1.6}}
.btn{{display:block;width:100%;margin-top:18px;height:44px;background:var(--stamp);color:#fff;border:0;font:700 13px system-ui;cursor:pointer}} .btn:hover{{background:#152C48}}
.foot{{margin-top:14px;text-align:center;color:#8C8878;font:11px system-ui}}
.dot{{width:6px;height:6px;border-radius:50%;background:#2E5C46;display:inline-block}}
</style>
</head>
<body>
<div class=\"card\">
  <div class=\"badge\"><span class=\"dot\"></span> Razorpay Test Mode — REVIVE Demo</div>
  <h1>Complete your payment</h1>
  <div class=\"muted\">Payment Link <code>{link_id}</code> &middot; Test Mode &middot; No real money moves</div>
  <div class=\"amount\">{amount_str}</div>
  <div class=\"desc\"><b>For:</b> {desc}<br><b>Status:</b> PAYMENT_PENDING — created by REVIVE LiveExecutor<br><span style=\"color:#6B4E12\">Demo fallback: Razorpay returned 429 rate-limit, so this local page is shown for recording. A real key would show rzp.io checkout.</span></div>
  <button class=\"btn\" onclick=\"this.textContent='✓ Payment simulated — check webhook';this.style.background='#2E5C46'\">Pay {amount_str} — Test Card</button>
  <div class=\"foot\">REVIVE 6.0 — Risk-aware recovery &middot; <a href=\"/\" style=\"color:var(--stamp)\">Back to Control Room</a><br>Real Razorpay Test Mode would use <code>https://rzp.io/i/{link_id}</code></div>
</div>
</body>
</html>
"""
    return HTMLResponse(html)


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
