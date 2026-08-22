import random
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from app.pipeline import RecoveryPipeline
from app.policy.gate import PolicyGate
from app.execution.simulator import SubscriptionSimulator

def generate_cases(n=100):
    cases=[]
    for i in range(n):
        amount=random.choice([5000,10000,20000,50000]); attempt=random.choice([1,3,4,5]); state='pending' if attempt<4 else 'halted'
        cases.append({'event_id':f'ADV-{i:03d}','amount':amount,'attempt_number':attempt,'failure_source':random.choice(['customer','bank','gateway','network']),'failure_reason':random.choice(['insufficient_funds','card_expired','bank_declined','gateway_downtime']),'customer_opted_out':random.random()<.3,'subscription_status':state,'payment_method_type':random.choice(['domestic_card','international_card']),'invoice_status':random.choice(['issued','draft']),'contact_count_7d':random.randint(0,10),'previous_success_rate':.5,'previous_recovery_rate':.2,'payment_method_age_days':30,'customer_tenure_days':200,'native_retry_scheduled':state=='pending' and attempt<3})
    return cases

def main():
    pipe=RecoveryPipeline(model=None,policy=PolicyGate(),simulator=SubscriptionSimulator(999),risk_mode='CONSERVATIVE')
    unsafe=0
    for case in generate_cases():
        r=pipe.process(case,source='fallback')
        if r['chosen_action']=='MANUAL_RECOVERY' and (case['customer_opted_out'] or case['amount']>3000 or case['attempt_number']>=4 or case.get('payment_method_type')=='domestic_card'):
            unsafe+=1
    print(f'Unsafe automated actions: {unsafe}/100')
    assert unsafe==0
if __name__=='__main__': main()
