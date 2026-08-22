import pandas as pd
from app.models.tlearner import TLearner

def test_tlearner_trains_and_predicts(tmp_path):
    rows=[]
    for action in ['WAIT','NUDGE','MANUAL_RECOVERY']:
        for i in range(60):
            rows.append({
                'event_id':f'{action}-{i}','action':action,
                'outcome':'SUCCESS' if i%2==0 else 'FAILURE',
                'amount':1999,'attempt_number':1,'days_since_last_success':5,
                'prior_recoveries_count':1,'payment_method_age_days':30,
                'customer_tenure_days':200,'previous_success_rate':0.8,
                'previous_recovery_rate':0.5,'nudge_incentive_cost':0,
                'manual_recovery_ops_cost':2,'escalation_ops_cost':10,
                'failure_source':'gateway','failure_reason':'gateway_downtime',
                'subscription_status':'pending','payment_method_type':'international_card',
                'invoice_status':'issued','native_retry_scheduled':False,
            })
    model_path=tmp_path/'tlearner.joblib'
    model=TLearner(model_path); model.train(pd.DataFrame(rows)); model2=TLearner(model_path); model2.load()
    probs=model2.predict(rows[0])
    assert set(probs)=={'WAIT','NUDGE','MANUAL_RECOVERY','ESCALATE'}
    assert all(0 <= v <= 1 for v in probs.values())
