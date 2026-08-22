import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from app.policy.gate import PolicyGate

def main():
    gate=PolicyGate()
    base={'event_id':'X','amount':1000,'attempt_number':1,'customer_opted_out':False,'subscription_status':'pending','invoice_status':'issued','payment_method_type':'international_card','native_retry_scheduled':False}
    preds={'WAIT':{'mean':.5,'std':0},'NUDGE':{'mean':.7,'std':0},'MANUAL_RECOVERY':{'mean':.8,'std':0},'ESCALATE':{'mean':0,'std':0}}
    cases=[{**base,'customer_opted_out':True},{**base,'amount':5000},{**base,'attempt_number':4},{**base,'native_retry_scheduled':True},{**base,'payment_method_type':'domestic_card'}]
    for case in cases:
        f=gate.feasible(case,preds,bool(case.get('native_retry_scheduled',False)))
        assert f['MANUAL_RECOVERY'].decision=='BLOCKED'
    print('Property tests passed.')
if __name__=='__main__': main()
