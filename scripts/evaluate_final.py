import argparse, json, sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from app.config import DATA_DIR,RESULTS_DIR,MODEL_DIR
from app.models.calibrated_tlearner import CalibratedTLearner
from app.models.calibrated_xlearner import CalibratedXLearner
from app.execution.simulator import SubscriptionSimulator
from app.policy.gate import PolicyGate
from app.economics import EconomicsEngine

SEEDS=[42,7,2024,1337,999]

def rec_result(r):
    return {'action':r.action,'success':r.success,'recovered_amount':r.recovered_amount,'cost':r.cost,'net_recovered':r.recovered_amount-r.cost}

def main():
    parser = argparse.ArgumentParser(description="Evaluate REVIVE policy benchmark")
    parser.add_argument("--model", choices=["tlearner", "xlearner"], default="tlearner", help="Model architecture to evaluate")
    args = parser.parse_args()

    cases=pd.read_csv(DATA_DIR/'eval_cases.csv').to_dict('records')
    if args.model == "xlearner":
        model = CalibratedXLearner(MODEL_DIR); model.load()
    else:
        model = CalibratedTLearner(MODEL_DIR); model.load()
    model_predictions=model.predict_dataset(cases)
    gate=PolicyGate(); econ=EconomicsEngine(); runs={}
    for seed in SEEDS:
        sim=SubscriptionSimulator(seed)
        buckets={k:[] for k in ['native','rule','ml_only','revive','constrained_oracle','oracle']}
        expected_policy_values={k:[] for k in buckets}
        regrets=[]; blocked_upside=[]
        for idx,case in enumerate(cases):
            def add(name,action):
                realized=sim.execute(case,action)
                buckets[name].append(rec_result(realized))
                expected_policy_values[name].append(econ.expected_net_value(case,action,sim.get_true_probability(case,action),econ.expected_days(case,action)))
            add('native','WAIT')
            reason=case.get('failure_reason'); source=case.get('failure_source')
            if reason=='card_expired': rule_action='NUDGE'
            elif source in ('gateway','network'): rule_action='WAIT'
            elif reason=='insufficient_funds' and case.get('attempt_number',1)<=2: rule_action='MANUAL_RECOVERY'
            elif reason=='bank_declined': rule_action='NUDGE'
            else: rule_action='WAIT'
            add('rule',rule_action)
            preds=model_predictions[idx]
            probs={a:preds[a]['mean'] for a in preds}; std={a:preds[a]['std'] for a in preds}
            conservative={a:max(0.0,probs[a]-std[a]) for a in probs}
            inc=econ.rank_incremental(case,conservative,std,1.0)
            ml_action=max(inc,key=inc.get)
            if ml_action!='WAIT' and inc[ml_action] <= 0: ml_action='WAIT'
            add('ml_only',ml_action)
            feasible=gate.feasible(case,preds,bool(case.get('native_retry_scheduled',False)))
            approved=[a for a,r in feasible.items() if r.decision=='APPROVED']
            best=max(approved,key=lambda a:inc.get(a,-1e18)) if approved else 'ESCALATE'
            if best!='WAIT' and inc.get(best,-1e18)<=0: best='WAIT' if 'WAIT' in approved else 'ESCALATE'
            add('revive',best)
            true={a:sim.get_true_probability(case,a) for a in sim.ACTIONS}
            true_inc=econ.rank_incremental(case,true)
            tf=gate.feasible(case,true,bool(case.get('native_retry_scheduled',False)))
            tapproved=[a for a,r in tf.items() if r.decision=='APPROVED']
            co=max(tapproved,key=lambda a:true_inc.get(a,-1e18)) if tapproved else 'ESCALATE'
            if co!='WAIT' and true_inc.get(co,-1e18)<=0: co='WAIT' if 'WAIT' in tapproved else 'ESCALATE'
            add('constrained_oracle',co)
            oe=sim.expected_values(case); oo=max(oe,key=oe.get)
            add('oracle',oo)
            best_safe_true=max([true_inc[a] for a in tapproved], default=0.0)
            regrets.append(max(0.0,best_safe_true-true_inc.get(best,0.0)))
            blocked_upside.append(max(0.0,best_safe_true-true_inc.get(best,0.0)) if best=='WAIT' else 0.0)
        total=sum(float(c['amount']) for c in cases)
        runs[str(seed)]={'realized_metrics':{k:{'net_recovered':float(sum(x['net_recovered'] for x in v)),'gross_recovered':float(sum(x['recovered_amount'] for x in v))} for k,v in buckets.items()},
                         'expected_policy_value':{k:float(np.sum(v)) for k,v in expected_policy_values.items()},
                         'mean_decision_regret':float(np.mean(regrets)),
                         'policy_avoided_upside':float(np.sum(blocked_upside)),'total_at_risk':total}

    names=['native','rule','ml_only','revive','constrained_oracle','oracle']
    summary={}
    for name in names:
        vals=[runs[s]['expected_policy_value'][name] for s in runs]
        realized=[runs[s]['realized_metrics'][name]['net_recovered'] for s in runs]
        summary[name]={'mean_expected_net':float(np.mean(vals)),'std_expected_net':float(np.std(vals)),'mean_realized_net':float(np.mean(realized)),'std_realized_net':float(np.std(realized))}
    native=summary['native']['mean_expected_net']; revive=summary['revive']['mean_expected_net']; constrained=summary['constrained_oracle']['mean_expected_net']
    capture=(revive-native)/(constrained-native) if constrained>native else 0.0
    output={'seeds':SEEDS,'case_count':len(cases),'summary':summary,'safe_policy_capture':float(capture),'mean_decision_regret':float(np.mean([runs[s]['mean_decision_regret'] for s in runs])),'mean_policy_avoided_upside':float(np.mean([runs[s]['policy_avoided_upside'] for s in runs])),'risk_mode':'BALANCED'}
    RESULTS_DIR.mkdir(parents=True,exist_ok=True); (RESULTS_DIR/'final_results.json').write_text(json.dumps(output,indent=2))
    print('REVIVE EXPECTED-VALUE EVALUATION')
    for k,v in summary.items():
        try:
            print(f'{k:20s} expected ₹{v["mean_expected_net"]:,.2f} ± ₹{v["std_expected_net"]:,.2f} | realized ₹{v["mean_realized_net"]:,.2f}')
        except UnicodeEncodeError:
            print(f'{k:20s} expected INR {v["mean_expected_net"]:,.2f} +/- INR {v["std_expected_net"]:,.2f} | realized INR {v["mean_realized_net"]:,.2f}')
    print(f'Safe Policy Capture: {capture*100:.2f}%')
if __name__=='__main__': main()
