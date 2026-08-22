import json, sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.execution.simulator import SubscriptionSimulator
from app.evaluation.ope import estimate_ips, estimate_snips, estimate_dr, overlap_diagnostics
from app.evaluation.baselines import baseline_rule_based
from app.config import RESULTS_DIR
ACTIONS = ["WAIT", "NUDGE", "MANUAL_RECOVERY", "ESCALATE"]

def generate_logs(n=1000, seed=42):
    rng = np.random.default_rng(seed); sim = SubscriptionSimulator(seed=seed); probs = np.array([0.4,0.3,0.2,0.1]); rows=[]
    for i in range(n):
        case={"event_id":f"OPE-{i}","amount":float(rng.choice([199,999,1999,4999])),"attempt_number":int(rng.integers(1,4)),"failure_source":str(rng.choice(["customer","bank","gateway","network"])),"failure_reason":str(rng.choice(["insufficient_funds","card_expired","bank_declined","gateway_downtime"])),"customer_opted_out":False,"subscription_status":"pending","contact_count_7d":int(rng.integers(0,4)),"previous_success_rate":float(rng.uniform(.3,1.0)),"previous_recovery_rate":float(rng.uniform(0,.8)),"payment_method_age_days":int(rng.integers(1,365)),"customer_tenure_days":int(rng.integers(30,1000))}
        idx=int(rng.choice(4,p=probs)); action=ACTIONS[idx]; ex=sim.execute(case,action); rows.append({**case,"action":action,"reward":ex.recovered_amount-ex.cost})
    return pd.DataFrame(rows), probs

def main():
    RESULTS_DIR.mkdir(exist_ok=True)
    df, b = generate_logs()
    idx={a:i for i,a in enumerate(ACTIONS)}; actions=df.action.map(idx).to_numpy(); rewards=df.reward.to_numpy(float); behavior=np.tile(b,(len(df),1)); policy=np.zeros_like(behavior); pred=np.zeros_like(behavior); sim=SubscriptionSimulator(seed=42); true=[]
    for i,row in df.iterrows():
        case=row.to_dict(); action=baseline_rule_based(case); policy[i,idx[action]]=1.0
        for j,a in enumerate(ACTIONS): pred[i,j]=sim.expected_values(case)[a]
        true.append(sim.expected_values(case)[action])
    empty=df.iloc[:,0:0]
    result={"ips":estimate_ips(empty,policy,behavior,actions,rewards),"snips":estimate_snips(empty,policy,behavior,actions,rewards),"dr":estimate_dr(empty,policy,behavior,actions,rewards,pred),"true_policy_value":float(np.mean(true)),"overlap":overlap_diagnostics(empty,behavior,actions,ACTIONS),"n":len(df)}
    (RESULTS_DIR/"causal_evaluation.json").write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
if __name__=='__main__': main()
