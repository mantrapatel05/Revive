import json, sys
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from app.economics import MerchantConfig
from app.pipeline import RecoveryPipeline
from app.policy.gate import PolicyGate
from app.execution.simulator import SubscriptionSimulator
from app.config import DATA_DIR, RESULTS_DIR

def run_profile(cfg):
    df=pd.read_csv(DATA_DIR/'eval_cases.csv'); sim=SubscriptionSimulator(seed=42)
    pipe=RecoveryPipeline(simulator=sim, policy=PolicyGate.from_merchant_config(cfg), risk_mode=cfg.risk_mode, merchant_config=cfg)
    net=0.0; escalations=0
    for _, row in df.iterrows():
        rec=pipe.process(row.to_dict(), source='sim')
        net += rec['net_recovered']; escalations += int(rec['chosen_action']=='ESCALATE')
    return {'net_recovered':net,'escalations':escalations}

def main():
    profiles={
        'Revenue Maximizer': MerchantConfig(risk_mode='AGGRESSIVE', customer_fatigue_penalty=0),
        'Balanced Default': MerchantConfig(risk_mode='BALANCED'),
        'Brand Protector': MerchantConfig(risk_mode='CONSERVATIVE', customer_fatigue_penalty=200),
    }
    out={k:run_profile(v) for k,v in profiles.items()}; RESULTS_DIR.mkdir(exist_ok=True); (RESULTS_DIR/'merchant_utility_profiles.json').write_text(json.dumps(out,indent=2)); print(json.dumps(out,indent=2))
if __name__=='__main__': main()
