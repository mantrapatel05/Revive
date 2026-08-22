import json,sys
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from app.pipeline import RecoveryPipeline
from app.policy.gate import PolicyGate
from app.execution.simulator import SubscriptionSimulator
from app.models.calibrated_tlearner import CalibratedTLearner
from app.config import DATA_DIR,RESULTS_DIR,MODEL_DIR

def run(mode):
    df=pd.read_csv(DATA_DIR/'eval_cases.csv'); model=CalibratedTLearner(MODEL_DIR); model.load(); pipe=RecoveryPipeline(model=model,policy=PolicyGate(),simulator=SubscriptionSimulator(42),risk_mode=mode); net=0; unnecessary=0; abstain=0
    for _,r in df.iterrows():
        rec=pipe.process(r.to_dict(),source='ml'); net+=rec['net_recovered']; abstain+=int(rec['chosen_action'] in ('WAIT','ESCALATE')); unnecessary+=int(rec['chosen_action'] in ('NUDGE','MANUAL_RECOVERY') and rec['execution_status']!='SUCCESS')
    return {'net_recovered':net,'abstentions':abstain,'unnecessary_actions':unnecessary}

def main():
    out={m:run(m) for m in ['CONSERVATIVE','BALANCED','AGGRESSIVE']}; RESULTS_DIR.mkdir(parents=True,exist_ok=True); (RESULTS_DIR/'risk_sensitivity.json').write_text(json.dumps(out,indent=2)); print(json.dumps(out,indent=2))
if __name__=='__main__': main()
