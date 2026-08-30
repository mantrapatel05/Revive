"""Evaluate policy performance across multiple data-generation seeds.

Measures Safe Policy Capture, Mean Regret, and realized net recovery across
multiple distinct synthetic cohorts to establish true sampling variance
and empirical confidence ranges.
"""
import sys, json, subprocess
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import DATA_DIR, RESULTS_DIR

SEEDS = [20260820, 42, 12345, 7, 999]

def evaluate_seed(seed: int) -> dict:
    print(f"\nEvaluating data generation seed {seed}...")
    # 1. Generate data for seed
    subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_data.py"), "--seed", str(seed)], check=True, capture_output=True)
    # 2. Train model
    subprocess.run([sys.executable, str(ROOT / "scripts" / "train_model.py")], check=True, capture_output=True)
    # 3. Evaluate benchmark
    subprocess.run([sys.executable, str(ROOT / "scripts" / "evaluate_final.py")], check=True, capture_output=True)
    
    results_path = RESULTS_DIR / "final_results.json"
    with open(results_path, encoding="utf-8") as f:
        data = json.load(f)
    
    summary_data = data.get("summary", {})
    cap = float(data.get("safe_policy_capture", 0.0)) * 100.0
    regret = float(data.get("mean_decision_regret", 0.0))
    return {
        "seed": seed,
        "safe_policy_capture": round(cap, 2),
        "mean_regret": round(regret, 2),
        "revive_realized": summary_data.get("revive", {}).get("mean_realized_net", 0.0),
        "constrained_oracle_realized": summary_data.get("constrained_oracle", {}).get("mean_realized_net", 0.0),
    }

def main():
    print("=" * 70)
    print("DATA-GENERATION SEED SENSITIVITY EVALUATION (5 SYNTHETIC COHORTS)")
    print("=" * 70)
    
    runs = []
    for s in SEEDS:
        res = evaluate_seed(s)
        runs.append(res)
        print(f"  Seed {s:8d} -> Safe Policy Capture: {res['safe_policy_capture']:6.2f}% | Mean Regret: INR {res['mean_regret']:5.2f}")

    # Restore canonical baseline data
    print("\nRestoring canonical baseline seed (20260820)...")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_data.py"), "--seed", "20260820"], check=True, capture_output=True)
    subprocess.run([sys.executable, str(ROOT / "scripts" / "train_model.py")], check=True, capture_output=True)
    subprocess.run([sys.executable, str(ROOT / "scripts" / "evaluate_final.py")], check=True, capture_output=True)

    captures = [r["safe_policy_capture"] for r in runs]
    regrets = [r["mean_regret"] for r in runs]

    mean_cap = float(np.mean(captures))
    std_cap = float(np.std(captures))
    min_cap = float(np.min(captures))
    max_cap = float(np.max(captures))

    mean_reg = float(np.mean(regrets))
    std_reg = float(np.std(regrets))

    summary = {
        "n_seeds": len(SEEDS),
        "seeds": SEEDS,
        "runs": runs,
        "safe_policy_capture": {
            "mean_pct": round(mean_cap, 2),
            "std_pct": round(std_cap, 2),
            "min_pct": round(min_cap, 2),
            "max_pct": round(max_cap, 2),
            "range_str": f"{min_cap:.1f}% - {max_cap:.1f}%",
        },
        "mean_regret_inr": {
            "mean": round(mean_reg, 2),
            "std": round(std_reg, 2),
        }
    }

    out_path = RESULTS_DIR / "seed_sensitivity.json"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\n" + "=" * 70)
    print("SUMMARY ACROSS 5 SYNTHETIC COHORTS:")
    print(f"  Safe Policy Capture : {mean_cap:.2f}% +/- {std_cap:.2f}% (Range: {min_cap:.2f}% - {max_cap:.2f}%)")
    print(f"  Mean Decision Regret: INR {mean_reg:.2f} +/- INR {std_reg:.2f}")
    print(f"  Reference Seed      : 84.09% (Seed 20260820)")
    print(f"Saved report to: {out_path}")
    print("=" * 70)

if __name__ == "__main__":
    main()
