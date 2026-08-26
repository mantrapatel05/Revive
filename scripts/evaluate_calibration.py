import json, sys
from pathlib import Path
import numpy as np, pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from app.models.calibrated_tlearner import CalibratedTLearner
from app.execution.simulator import SubscriptionSimulator
from app.config import DATA_DIR, MODEL_DIR, RESULTS_DIR

ACTIONS = ['WAIT', 'NUDGE', 'MANUAL_RECOVERY']
SEEDS = [42, 7, 2024, 1337, 999]
ACTION_COLORS = {
    'WAIT': '#6366f1',
    'NUDGE': '#f59e0b',
    'MANUAL_RECOVERY': '#10b981'
}

def main():
    model = CalibratedTLearner(MODEL_DIR); model.load()
    df = pd.read_csv(DATA_DIR / 'eval_cases.csv')

    action_trials = {a: [] for a in ACTIONS}
    all_trials = []

    # Run multi-seed evaluation across all 5 benchmark seeds (3,000 total evaluations)
    for seed in SEEDS:
        sim = SubscriptionSimulator(seed)
        for _, r in df.iterrows():
            c = r.to_dict()
            for a in ACTIONS:
                p = model.predict_proba(c, a)['mean']
                y = int(sim.execute(c, a).success)
                action_trials[a].append((p, y))
                all_trials.append((p, y))

    def compute_quantile_bins(data, n_bins=5):
        p_arr = np.array([x[0] for x in data])
        y_arr = np.array([x[1] for x in data])
        quantiles = np.percentile(p_arr, np.linspace(0, 100, n_bins + 1))
        quantiles = np.unique(quantiles)
        out = []
        for i in range(len(quantiles) - 1):
            lo, hi = quantiles[i], quantiles[i+1]
            mask = (p_arr >= lo) & (p_arr <= hi if i == len(quantiles) - 2 else p_arr < hi)
            if np.sum(mask) >= 15:
                n = int(np.sum(mask))
                p_mean = float(np.mean(p_arr[mask]))
                y_mean = float(np.mean(y_arr[mask]))
                se = float(np.sqrt(max(1e-6, y_mean * (1.0 - y_mean)) / n))
                out.append({
                    'bin_range': [round(float(lo), 4), round(float(hi), 4)],
                    'count': n,
                    'pred': round(p_mean, 4),
                    'observed': round(y_mean, 4),
                    'std_error': round(se, 4)
                })
        brier = float(np.mean((p_arr - y_arr)**2)) if len(data) > 0 else 0.0
        return {'brier': round(brier, 4), 'bins': out}

    overall = compute_quantile_bins(all_trials, n_bins=6)
    per_action = {a: compute_quantile_bins(action_trials[a], n_bins=4) for a in ACTIONS}

    calib_payload = {
        'brier': overall['brier'],
        'bins': overall['bins'],
        'overall': overall,
        'per_action': per_action,
        'seeds': SEEDS,
        'total_trials': len(all_trials)
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = RESULTS_DIR / 'calibration.json'
    json_path.write_text(json.dumps(calib_payload, indent=2))

    # Render Publication-Quality Multi-Panel Calibration Curves
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6), dpi=300)
    fig.patch.set_facecolor('#ffffff')

    # Panel 1: Overall Pooled Model Calibration Curve
    ax1.plot([0, 0.5], [0, 0.5], 'k--', alpha=0.5, label='Perfect Calibration (y = x)')
    pred_x = [b['pred'] for b in overall['bins']]
    obs_y = [b['observed'] for b in overall['bins']]
    err_y = [1.96 * b['std_error'] for b in overall['bins']]
    counts = [b['count'] for b in overall['bins']]

    ax1.errorbar(pred_x, obs_y, yerr=err_y, fmt='o-', color='#2563eb', linewidth=2, markersize=8, capsize=4, capthick=1.5, label=f"Calibrated T-Learner (Brier: {overall['brier']:.4f})")

    for x, y, n in zip(pred_x, obs_y, counts):
        ax1.annotate(f"n={n}", (x, y), textcoords="offset points", xytext=(0, 10), ha='center', fontsize=8, fontweight='semibold', color='#1e293b')

    ax1.set_xlim(-0.01, 0.45)
    ax1.set_ylim(-0.01, 0.55)
    ax1.set_xlabel('Predicted Probability', fontsize=11, fontweight='bold')
    ax1.set_ylabel('Observed Recovery Rate (with 95% CI)', fontsize=11, fontweight='bold')
    ax1.set_title('Overall Pooled Calibration (5 Evaluation Seeds, N=3,000)', fontsize=12, fontweight='bold')
    ax1.grid(True, linestyle=':', alpha=0.6)
    ax1.legend(loc='upper left', frameon=True, fontsize=10)

    # Panel 2: Per-Action Calibration Curves
    ax2.plot([0, 0.5], [0, 0.5], 'k--', alpha=0.5, label='Perfect Calibration (y = x)')
    for a in ACTIONS:
        act_bins = per_action[a]['bins']
        if act_bins:
            px = [b['pred'] for b in act_bins]
            oy = [b['observed'] for b in act_bins]
            ey = [1.96 * b['std_error'] for b in act_bins]
            ax2.errorbar(
                px, oy, yerr=ey,
                fmt='s-',
                linewidth=1.8,
                markersize=7,
                capsize=3,
                color=ACTION_COLORS.get(a, '#333333'),
                label=f"{a} (Brier: {per_action[a]['brier']:.4f})"
            )

    ax2.set_xlim(-0.01, 0.45)
    ax2.set_ylim(-0.01, 0.55)
    ax2.set_xlabel('Predicted Probability', fontsize=11, fontweight='bold')
    ax2.set_ylabel('Observed Recovery Rate (with 95% CI)', fontsize=11, fontweight='bold')
    ax2.set_title('Per-Action Calibration Curves (N=1,000 per Action)', fontsize=12, fontweight='bold')
    ax2.grid(True, linestyle=':', alpha=0.6)
    ax2.legend(loc='upper left', frameon=True, fontsize=10)

    plt.suptitle('REVIVE Causal Model Reliability Diagram (Calibrated T-Learner)', fontsize=14, fontweight='bold', y=0.98)
    plt.tight_layout()

    png_path = RESULTS_DIR / 'calibration_curve.png'
    plt.savefig(png_path, bbox_inches='tight')
    plt.close()

    print(f"Calibration JSON written to {json_path}")
    print(f"Calibration plot saved to {png_path}")

if __name__ == '__main__':
    main()
