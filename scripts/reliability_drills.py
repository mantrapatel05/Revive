import random, time, sys
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from app.policy.gate import PolicyGate
from app.execution.authorization import ExecutionAuthorization
from app.execution.outbox import enqueue_execution_intent, get_pending_intents
from app.decision.replay import DecisionStore
from app.execution.circuit_breaker import CircuitBreaker
from app.execution.reconciliation import reconcile_payment, ReconciliationState
from app.db import init_db, get_conn

def case(seed):
    r=random.Random(seed)
    return {'amount':r.choice([199,999,1999,5000,10000]),'attempt_number':r.randint(1,5),'customer_opted_out':r.random()<.2,'subscription_status':'pending','invoice_status':'issued','payment_method_type':'international_card'}

def main():
    init_db(); gate=PolicyGate()
    for i in range(100):
        c=case(i); c['customer_opted_out']=True
        p={'WAIT':{'mean':.5},'NUDGE':{'mean':.6},'MANUAL_RECOVERY':{'mean':.7},'ESCALATE':{'mean':0}}
        f=gate.feasible(c,p); assert f['NUDGE'].decision=='BLOCKED' and f['MANUAL_RECOVERY'].decision=='BLOCKED'
    auth=ExecutionAuthorization.create('REL','MANUAL_RECOVERY','policy-v5','calibrated-tlearner-v5')
    auth=replace(auth, expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)); assert not auth.is_valid('policy-v5','calibrated-tlearner-v5')
    with get_conn() as conn: conn.execute('DELETE FROM execution_intents')
    auth=ExecutionAuthorization.create('REL2','MANUAL_RECOVERY','policy-v5','calibrated-tlearner-v5')
    DecisionStore().save({"decision_id": auth.decision_id, "case_id": auth.case_id, "features": {}, "chosen_action": auth.action})
    i1=enqueue_execution_intent(auth,{'x':1}); i2=enqueue_execution_intent(auth,{'x':2}); assert i1==i2; assert len(get_pending_intents())==1
    cb=CircuitBreaker(3,.05); [cb.record_failure() for _ in range(3)]; assert not cb.allow_request(); time.sleep(.06); assert cb.allow_request()
    for i in range(50): assert reconcile_payment(f'R-{i}','MANUAL_RECOVERY') in (ReconciliationState.CONFIRMED,ReconciliationState.FAILED)
    print('All reliability drills passed.')
if __name__=='__main__': main()
