import json, sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from app.config import DATA_DIR, RESULTS_DIR, MODEL_DIR
from app.models.calibrated_tlearner import CalibratedTLearner
from app.execution.simulator import SubscriptionSimulator
from app.policy.gate import PolicyGate
from app.economics import EconomicsEngine

SEEDS = [42, 7, 2024, 1337, 999]

def main():
    cases = pd.read_csv(DATA_DIR / 'eval_cases.csv').to_dict('records')
    model = CalibratedTLearner(MODEL_DIR); model.load()
    model_predictions = model.predict_dataset(cases)
    gate = PolicyGate(); econ = EconomicsEngine()

    case_metrics = []
    for idx, case in enumerate(cases):
        preds = model_predictions[idx]
        probs = {a: preds[a]['mean'] for a in preds}
        std = {a: preds[a]['std'] for a in preds}
        conservative = {a: max(0.0, probs[a] - std[a]) for a in probs}
        inc = econ.rank_incremental(case, conservative, std, 1.0)
        feasible = gate.feasible(case, preds, bool(case.get('native_retry_scheduled', False)))
        approved = [a for a, r in feasible.items() if r.decision == 'APPROVED']
        revive_action = max(approved, key=lambda a: inc.get(a, -1e18)) if approved else 'ESCALATE'
        if revive_action != 'WAIT' and inc.get(revive_action, -1e18) <= 0:
            revive_action = 'WAIT' if 'WAIT' in approved else 'ESCALATE'

        native_vals = []; revive_vals = []; co_vals = []; regrets = []
        for seed in SEEDS:
            sim = SubscriptionSimulator(seed)
            true = {a: sim.get_true_probability(case, a) for a in sim.ACTIONS}
            true_inc = econ.rank_incremental(case, true)
            tf = gate.feasible(case, true, bool(case.get('native_retry_scheduled', False)))
            tapproved = [a for a, r in tf.items() if r.decision == 'APPROVED']
            co_action = max(tapproved, key=lambda a: true_inc.get(a, -1e18)) if tapproved else 'ESCALATE'
            if co_action != 'WAIT' and true_inc.get(co_action, -1e18) <= 0:
                co_action = 'WAIT' if 'WAIT' in tapproved else 'ESCALATE'

            nat_v = econ.expected_net_value(case, 'WAIT', sim.get_true_probability(case, 'WAIT'), econ.expected_days(case, 'WAIT'))
            rev_v = econ.expected_net_value(case, revive_action, sim.get_true_probability(case, revive_action), econ.expected_days(case, revive_action))
            co_v = econ.expected_net_value(case, co_action, sim.get_true_probability(case, co_action), econ.expected_days(case, co_action))
            best_safe_true = max([true_inc[a] for a in tapproved], default=0.0)
            regret = max(0.0, best_safe_true - true_inc.get(revive_action, 0.0))

            native_vals.append(nat_v); revive_vals.append(rev_v); co_vals.append(co_v); regrets.append(regret)

        case_metrics.append({
            **case,
            'revive_action': revive_action,
            'mean_native_val': float(np.mean(native_vals)),
            'mean_revive_val': float(np.mean(revive_vals)),
            'mean_co_val': float(np.mean(co_vals)),
            'mean_regret': float(np.mean(regrets)),
        })

    df = pd.DataFrame(case_metrics)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    def slice_stats(sub_df):
        nat = sub_df['mean_native_val'].sum()
        rev = sub_df['mean_revive_val'].sum()
        co = sub_df['mean_co_val'].sum()
        cap = (rev - nat) / (co - nat) if (co - nat) > 0 else 1.0
        return {
            'count': int(len(sub_df)),
            'native_expected_net': round(float(nat), 2),
            'revive_expected_net': round(float(rev), 2),
            'constrained_oracle_expected_net': round(float(co), 2),
            'safe_policy_capture': round(float(cap), 4),
            'mean_decision_regret': round(float(sub_df['mean_regret'].mean()), 2)
        }

    # 1. By failure reason (scenario breakdown)
    scenario_out = {}
    for reason, g in df.groupby('failure_reason'):
        scenario_out[reason] = slice_stats(g)
    (RESULTS_DIR / 'scenario_breakdown.json').write_text(json.dumps(scenario_out, indent=2))

    # 2. Segment breakdowns
    segments_out = {
        'amount_buckets': {
            'low_under_1500': slice_stats(df[df['amount'] < 1500]),
            'mid_1500_to_3000': slice_stats(df[(df['amount'] >= 1500) & (df['amount'] <= 3000)]),
            'high_above_3000': slice_stats(df[df['amount'] > 3000]),
        },
        'attempt_number': {
            'attempt_1': slice_stats(df[df['attempt_number'] == 1]),
            'attempt_2': slice_stats(df[df['attempt_number'] == 2]),
            'attempt_3': slice_stats(df[df['attempt_number'] == 3]),
            'attempt_4_plus': slice_stats(df[df['attempt_number'] >= 4]),
        },
        'prior_recoveries': {
            'new_0_prior': slice_stats(df[df['prior_recoveries_count'] == 0]),
            'medium_1_2_prior': slice_stats(df[df['prior_recoveries_count'].isin([1, 2])]),
            'frequent_3_plus_prior': slice_stats(df[df['prior_recoveries_count'] >= 3]),
        },
        'contact_fatigue_7d': {
            'normal_under_3_touches': slice_stats(df[df['contact_count_7d'] <= 2]),
            'fatigued_over_2_touches': slice_stats(df[df['contact_count_7d'] > 2]),
        }
    }
    (RESULTS_DIR / 'segment_breakdown.json').write_text(json.dumps(segments_out, indent=2))

    print("=== SEGMENT & SCENARIO EVALUATION COMPLETE ===")
    print(f"Scenarios: {list(scenario_out.keys())}")
    print(f"Segment breakdown written to {RESULTS_DIR / 'segment_breakdown.json'}")

if __name__ == '__main__':
    main()
