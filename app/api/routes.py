import json
from pathlib import Path
import pandas as pd
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from app.config import DATA_DIR, RESULTS_DIR
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

@router.post('/api/run-case')
async def run_case(request: Request):
    body = await request.json()
    event_id = body.get('event_id')
    if not event_id:
        raise HTTPException(400, 'event_id required')
    p = DATA_DIR / 'eval_cases.csv'
    if not p.exists():
        raise HTTPException(500, 'Generate evaluation data first')
    df = pd.read_csv(p)
    row = df[df.event_id == event_id]
    if row.empty:
        raise HTTPException(404, 'case not found')
    return request.app.state.pipeline.process(row.iloc[0].to_dict())

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


@router.get('/api/approvals')
def approvals():
    return {"approvals": get_pending_approvals()}

@router.post('/api/approvals/{approval_id}/resolve')
async def resolve_approval_route(approval_id: int, request: Request):
    body = await request.json()
    resolve_approval(approval_id, body.get('decision','REJECTED'), body.get('reviewer','demo-reviewer'))
    return {"status":"resolved","approval_id":approval_id,"decision":body.get('decision','REJECTED').upper()}


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
