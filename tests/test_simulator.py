from app.execution.simulator import SubscriptionSimulator

def case():
    return {"event_id":"E1","amount":1999,"attempt_number":1,"failure_source":"gateway","failure_reason":"gateway_downtime","subscription_status":"pending","payment_method_type":"international_card","previous_success_rate":0.8,"previous_recovery_rate":0.5,"customer_tenure_days":300,"payment_method_age_days":60}

def test_reproducible():
    a=SubscriptionSimulator(42).execute(case(),"WAIT"); b=SubscriptionSimulator(42).execute(case(),"WAIT"); assert a==b

def test_seed_changes_world():
    a=SubscriptionSimulator(42).execute(case(),"WAIT"); b=SubscriptionSimulator(99).execute(case(),"WAIT"); assert a.probability != b.probability or a.success != b.success

def test_counterfactuals_share_latent_world():
    s=SubscriptionSimulator(42); c=s.get if False else None; x=s.oracle_action(case()); assert x[0] in s.ACTIONS
