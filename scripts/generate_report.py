import json
from datetime import datetime, timezone
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.config import RESULTS_DIR

def main():
    RESULTS_DIR.mkdir(parents=True,exist_ok=True)
    names=['final_results.json','ci_results.json','calibration.json','risk_sensitivity.json','scenario_breakdown.json']
    data={}
    for n in names:
        p=RESULTS_DIR/n
        if p.exists(): data[n]=json.loads(p.read_text())
    lines=["# REVIVE Evaluation Report",f"Generated: {datetime.now(timezone.utc).isoformat()}",""]
    fr=data.get('final_results.json')
    if fr:
        lines += ['## Policy Benchmark','','| Strategy | Expected Net | Realized Net |','|---|---:|---:|']
        for k,v in fr['summary'].items(): lines.append(f"| {k} | ₹{v['mean_expected_net']:,.2f} | ₹{v['mean_realized_net']:,.2f} |")
        lines += ['',f"**Safe Policy Capture:** {fr['safe_policy_capture']*100:.2f}%",f"**Mean decision regret:** ₹{fr['mean_decision_regret']:,.2f}"]
    if 'ci_results.json' in data:
        c=data['ci_results.json']; lines += ['',f"## Bootstrap 95% CI",f"Mean realized net: ₹{c['mean']:,.2f}; CI: ₹{c['ci_95'][0]:,.2f} to ₹{c['ci_95'][1]:,.2f}"]
    if 'calibration.json' in data:
        lines += ['',f"## Calibration",f"Brier score: {data['calibration.json']['brier']:.6f}"]
    if 'risk_sensitivity.json' in data:
        lines += ['', '## Risk Modes', '']
        for k,v in data['risk_sensitivity.json'].items(): lines.append(f"- {k}: ₹{v['net_recovered']:,.2f}, abstentions {v['abstentions']}, unnecessary {v['unnecessary_actions']}")
    if 'scenario_breakdown.json' in data:
        lines += ['', '## Scenario Breakdown', '']
        for k,v in data['scenario_breakdown.json'].items(): lines.append(f"- {k}: {v['count']} cases, ₹{v['net_recovered']:,.2f}, avg ₹{v['avg_net']:,.2f}")
    (RESULTS_DIR/'evaluation_report.md').write_text('\n'.join(lines))
    print(RESULTS_DIR/'evaluation_report.md')
if __name__=='__main__': main()
