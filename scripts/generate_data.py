import random, sys
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from app.config import DATA_DIR
from app.execution.simulator import SubscriptionSimulator

import argparse
parser = argparse.ArgumentParser(description="Generate synthetic case and training data")
parser.add_argument("--seed", type=int, default=20260820, help="Random seed for data generation")
args, _ = parser.parse_known_args()

random.seed(args.seed)
N=1000
AMOUNTS=[499,999,1499,1999,2499,2999,3999,4999,7999]
TRAIN_SEEDS=[101,202,303,404,505]

# Realistic decline distribution matching Razorpay failure taxonomy (60% soft / 25% hard / 15% risk)
DECLINE_SCENARIOS = [
    # Soft declines (60% total)
    {"source": "customer", "reason": "insufficient_funds", "decline_class": "soft", "weight": 0.28},
    {"source": "gateway", "reason": "payment_timed_out", "decline_class": "soft", "weight": 0.12},
    {"source": "bank", "reason": "bank_declined", "decline_class": "soft", "weight": 0.10},
    {"source": "customer", "reason": "authentication_failed", "decline_class": "soft", "weight": 0.05},
    {"source": "network", "reason": "gateway_downtime", "decline_class": "soft", "weight": 0.05},

    # Hard declines (25% total)
    {"source": "customer", "reason": "card_expired", "decline_class": "hard", "weight": 0.14},
    {"source": "customer", "reason": "invalid_card", "decline_class": "hard", "weight": 0.06},
    {"source": "bank", "reason": "card_disabled", "decline_class": "hard", "weight": 0.05},

    # Risk / Fraud declines (15% total)
    {"source": "bank", "reason": "issuer_suspected_fraud", "decline_class": "risk", "weight": 0.07},
    {"source": "bank", "reason": "do_not_honor", "decline_class": "risk", "weight": 0.05},
    {"source": "bank", "reason": "stolen_card", "decline_class": "risk", "weight": 0.03},
]
SCENARIO_WEIGHTS = [s["weight"] for s in DECLINE_SCENARIOS]

def make_case(i):
    scen = random.choices(DECLINE_SCENARIOS, weights=SCENARIO_WEIGHTS)[0]
    source = scen["source"]
    reason = scen["reason"]
    decline_class = scen["decline_class"]
    attempt=random.choices([1,2,3,4],[.48,.30,.15,.07])[0]
    state="pending" if attempt < 4 else "halted"
    return {
        "event_id":f"EVT-{i:05d}","subscription_id":f"SUB-{i:05d}","customer_id":f"CUST-{i:05d}",
        "customer_name":f"Customer {i:04d}",
        "amount":random.choice(AMOUNTS),"attempt_number":attempt,"failure_source":source,"failure_reason":reason,
        "decline_class":decline_class,"subscription_status":state,"payment_method_type":random.choice(["domestic_card","international_card"]),
        "invoice_status":random.choice(["issued","issued","draft"]),"days_since_last_success":random.randint(1,90),
        "prior_recoveries_count":random.randint(0,4),"payment_method_age_days":random.randint(7,720),
        "customer_tenure_days":random.randint(30,1500),"previous_success_rate":round(random.uniform(.25,.98),3),
        "previous_recovery_rate":round(random.uniform(.02,.85),3),"customer_opted_out":random.random()<.05,
        "native_retry_scheduled":state=="pending" and attempt<3,"contact_count_7d":random.randint(0,5),
        "contacted_today":random.random()<.15,
        "nudge_incentive_cost":random.choice([0,0,25,50]),"manual_recovery_ops_cost":random.choice([0,2,5]),
        "escalation_ops_cost":random.choice([0,10,20]),"wait_expected_days":1.5,
        "expected_days_by_action":'{"NUDGE":1.5,"MANUAL_RECOVERY":0.0}',
    }

def main():
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    rows=[make_case(i+1) for i in range(N)]
    random.shuffle(rows)
    df=pd.DataFrame(rows)
    df.iloc[:800].to_csv(DATA_DIR/'dev_cases.csv',index=False)
    df.iloc[800:].to_csv(DATA_DIR/'eval_cases.csv',index=False)
    df.to_csv(DATA_DIR/'all_cases.csv',index=False)
    train=[]
    for seed in TRAIN_SEEDS:
        sim=SubscriptionSimulator(seed)
        for row in df.iloc[:800].to_dict('records'):
            for action in sim.ACTIONS[:3]:
                r=sim.execute(row,action)
                train.append({**row,'world_seed':seed,'action':action,'outcome':'SUCCESS' if r.success else 'FAILURE'})
    pd.DataFrame(train).to_csv(DATA_DIR/'training_data.csv',index=False)
    print(f'Generated {N} cases: 800 dev / 200 held-out; {len(train)} training observations across {len(TRAIN_SEEDS)} worlds')
if __name__=='__main__': main()
