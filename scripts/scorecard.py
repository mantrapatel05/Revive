import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.config import RESULTS_DIR

def main():
    p=RESULTS_DIR/'final_results.json'
    if not p.exists():
        raise SystemExit('Run scripts/evaluate_final.py first')
    d=json.loads(p.read_text()); s=d['summary']
    print('REVIVE SCORECARD')
    print('='*72)
    for name,m in s.items():
        print(f"{name:22s} expected ₹{m['mean_expected_net']:>12,.0f} ± ₹{m['std_expected_net']:>9,.0f} | realized ₹{m['mean_realized_net']:>12,.0f}")
    print(f"Safe Policy Capture: {d['safe_policy_capture']*100:.2f}%")
    print(f"Mean Decision Regret: ₹{d['mean_decision_regret']:,.2f}")
    print(f"Policy Avoided Upside: ₹{d['mean_policy_avoided_upside']:,.2f}")
if __name__=='__main__': main()
