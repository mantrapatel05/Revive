import sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from app.execution.simulator import SubscriptionSimulator
from app.economics import EconomicsEngine
from app.evaluation.ope import estimate_dr

ACTIONS=['WAIT','NUDGE','MANUAL_RECOVERY','ESCALATE']

class RandomBehavior:
    def get_probability(self, context, action): return 0.25

class TrueOutcome:
    def __init__(self,sim): self.sim=sim
    def predict(self,context,action): return self.sim.expected_values(context)[action]

class FixedPolicy:
    def get_action_probabilities(self,context):
        # deterministic oracle-like target for a synthetic OPE sanity check
        sim=SubscriptionSimulator(42); action=max(sim.expected_values(context), key=sim.expected_values(context).get)
        return {a:1.0 if a==action else 0.0 for a in ACTIONS}

def generate(n=300):
    rng=np.random.default_rng(2026); sim=SubscriptionSimulator(42); rows=[]
    for i in range(n):
        c={'event_id':f'OPE-{i}','amount':float(rng.choice([199,999,1999,4999])),'attempt_number':int(rng.integers(1,4)),'failure_source':str(rng.choice(['customer','bank','gateway','network'])),'failure_reason':str(rng.choice(['insufficient_funds','card_expired','bank_declined','gateway_downtime'])),'customer_opted_out':False,'subscription_status':'pending','payment_method_type':'international_card','invoice_status':'issued','previous_success_rate':float(rng.uniform(.3,1)),'previous_recovery_rate':float(rng.uniform(0,.8)),'customer_tenure_days':int(rng.integers(30,1000)),'payment_method_age_days':int(rng.integers(1,365))}
        a=str(rng.choice(ACTIONS)); x=sim.execute(c,a); rows.append({**c,'action':a,'reward':x.recovered_amount-x.cost})
    return pd.DataFrame(rows)

def main():
    df=generate()
    n=len(df)
    action_to_idx={a:i for i,a in enumerate(ACTIONS)}
    actions=np.array([action_to_idx[a] for a in df['action']])
    rewards=np.array(df['reward'])
    behavior_probs=np.full((n,len(ACTIONS)),0.25)
    policy=FixedPolicy(); sim=SubscriptionSimulator(42)
    policy_probs=np.zeros((n,len(ACTIONS)))
    outcome_model_pred=np.zeros((n,len(ACTIONS)))
    for i,row in df.iterrows():
        ctx=row.to_dict()
        pp=policy.get_action_probabilities(ctx)
        for j,a in enumerate(ACTIONS):
            policy_probs[i,j]=pp[a]
            outcome_model_pred[i,j]=sim.expected_values(ctx).get(a,0.0)
    result=estimate_dr(df,policy_probs,behavior_probs,actions,rewards,outcome_model_pred)
    print(result)
if __name__=='__main__': main()
