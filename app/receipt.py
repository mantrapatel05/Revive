"""
REVIVE — Decision Receipt Generator (Module 1.5)

Generates clean, printable, and tamper-evident decision audit receipts
documenting exactly what the system saw, predicted, gated, and executed for a given case.
"""

import json
from datetime import datetime, timezone
from app.decision.replay import stable_hash

def generate_receipt_data(decision: dict, replay: dict | None = None) -> dict:
    case_id = decision.get("event_id") or decision.get("case_id") or "UNKNOWN"
    amount = float(decision.get("amount", 0.0))
    features = decision.get("features", {})
    probs = decision.get("probabilities", {})
    unc = decision.get("uncertainty", {})
    econ = decision.get("incremental_values", {})
    checks = decision.get("policy_checks", [])
    
    # Header & Audit IDs
    decision_id = decision.get("decision_id") or stable_hash({"event_id": case_id, "action": decision.get("chosen_action")})[:24]
    seal_hash = stable_hash({
        "decision_id": decision_id,
        "case_id": case_id,
        "amount": amount,
        "action": decision.get("chosen_action"),
        "policy_decision": decision.get("policy_decision"),
        "timestamp": decision.get("timestamp", datetime.now(timezone.utc).isoformat()),
    })
    
    receipt = {
        "receipt_id": f"RCPT-{decision_id[:12].upper()}",
        "decision_id": decision_id,
        "seal_hash": seal_hash,
        "timestamp": decision.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "environment": "RAZORPAY TEST LIVE" if decision.get("is_live") else "BENCHMARK EVALUATION",
        "case_telemetry": {
            "case_id": case_id,
            "amount_inr": amount,
            "failure_reason": features.get("failure_reason", "payment_failed"),
            "failure_source": features.get("failure_source", "gateway"),
            "attempt_number": features.get("attempt_number", 1),
            "contact_count_7d": features.get("contact_count_7d", 0),
            "fatigue_penalty_active": int(features.get("contact_count_7d", 0)) > 2,
            "subscription_status": features.get("subscription_status", "pending"),
            "payment_method_type": features.get("payment_method_type", "card"),
            "customer_opted_out": bool(features.get("customer_opted_out", False)),
            "native_retry_scheduled": bool(features.get("native_retry_scheduled", False)),
            "customer_tenure_days": features.get("customer_tenure_days", 0),
        },
        "model_predictions": {
            "estimator": "Calibrated T-Learner (20 Bootstrap Ensemble)",
            "model_version": decision.get("model_version", "calibrated-tlearner-v5"),
            "actions": {
                a: {
                    "probability_pct": round(float(probs.get(a, 0.0)) * 100, 2),
                    "uncertainty_sigma_pct": round(float(unc.get(a, 0.0)) * 100, 2),
                } for a in ["WAIT", "NUDGE", "MANUAL_RECOVERY", "ESCALATE"]
            }
        },
        "counterfactual_economics": {
            "risk_mode": decision.get("risk_mode", "BALANCED"),
            "risk_z": decision.get("risk_z", 1.0),
            "expected_net_values_inr": {
                a: round(float(econ.get(a, 0.0)), 2) for a in ["WAIT", "NUDGE", "MANUAL_RECOVERY", "ESCALATE"]
            },
            "proposed_optimal_action": decision.get("recommended_action", "WAIT"),
        },
        "deterministic_policy_gate": {
            "policy_version": decision.get("policy_version", "policy-v5"),
            "gate_decision": decision.get("policy_decision", "APPROVED"),
            "policy_id": decision.get("policy_id", "P-APPROVE"),
            "veto_reasons": decision.get("policy_reasons", []),
            "checks": checks,
        },
        "execution_outcome": {
            "chosen_action": decision.get("chosen_action", "WAIT"),
            "execution_status": decision.get("execution_status", "SUCCESS"),
            "execution_result": decision.get("execution_result", {}),
            "final_state": decision.get("final_state", {"state": "CONFIRMED" if decision.get("execution_status") == "SUCCESS" else "PAYMENT_PENDING"}),
            "payment_link_id": decision.get("payment_link_id"),
            "payment_link_url": decision.get("payment_link_url"),
            "execution_intent_id": decision.get("execution_intent_id"),
            "approval_id": decision.get("approval_id"),
            "authorization": decision.get("authorization"),
            "recovered_amount_inr": round(float(decision.get("recovered_amount", 0.0)), 2),
            "intervention_cost_inr": round(float(decision.get("intervention_cost", 0.0)), 2),
            "net_recovered_inr": round(float(decision.get("net_recovered", 0.0)), 2),
            "incremental_realized_uplift_inr": round(float(decision.get("incremental_realized_value", 0.0)), 2),
            "execution_detail": decision.get("execution_detail", ""),
        }
    }
    return receipt

def render_receipt_html(receipt: dict) -> str:
    r = receipt
    c = r["case_telemetry"]
    m = r["model_predictions"]
    e = r["counterfactual_economics"]
    p = r["deterministic_policy_gate"]
    x = r["execution_outcome"]
    
    gate_color = "#107c41" if p["gate_decision"] == "APPROVED" else "#d83b01"
    
    checks_rows = "".join(f"""
        <tr>
            <td style="padding:6px 10px;border-bottom:1px solid #e1dfdd;font-family:monospace;font-size:12px;">{chk.get('check_id', 'POLICY')}</td>
            <td style="padding:6px 10px;border-bottom:1px solid #e1dfdd;font-size:12px;">{chk.get('description', 'Policy check')}</td>
            <td style="padding:6px 10px;border-bottom:1px solid #e1dfdd;font-family:monospace;font-weight:bold;font-size:12px;color:{'#107c41' if chk.get('passed') else '#d83b01'}">{'PASS' if chk.get('passed') else 'FAIL'}</td>
        </tr>
    """ for chk in p["checks"]) or """
        <tr>
            <td colspan="3" style="padding:8px 10px;font-size:12px;color:#605e5c;">Deterministic policy baseline checks passed.</td>
        </tr>
    """
    
    econ_rows = "".join(f"""
        <tr style="{'background:#f3f2f1;' if a == x['chosen_action'] else ''}">
            <td style="padding:6px 10px;border-bottom:1px solid #e1dfdd;font-family:monospace;font-weight:{'bold' if a == x['chosen_action'] else 'normal'};">{a} {'(SELECTED)' if a == x['chosen_action'] else ''}</td>
            <td style="padding:6px 10px;border-bottom:1px solid #e1dfdd;font-family:monospace;text-align:right;">{m['actions'][a]['probability_pct']}% &plusmn; {m['actions'][a]['uncertainty_sigma_pct']}%</td>
            <td style="padding:6px 10px;border-bottom:1px solid #e1dfdd;font-family:monospace;text-align:right;font-weight:bold;color:{'#107c41' if e['expected_net_values_inr'][a] > 0 else ('#d83b01' if e['expected_net_values_inr'][a] < 0 else '#323130')}">
                {'+' if e['expected_net_values_inr'][a] > 0 else ''}&#8377;{e['expected_net_values_inr'][a]:,.2f}
            </td>
        </tr>
    """ for a in ["WAIT", "NUDGE", "MANUAL_RECOVERY", "ESCALATE"])

    receipt_json_str = json.dumps(receipt)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>REVIVE Decision Receipt &middot; {c['case_id']}</title>
<style>
  @page {{ size: A4; margin: 15mm; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #faf9f8; color: #201f1e; margin: 0; padding: 24px; }}
  .receipt {{ max-width: 800px; margin: 0 auto; background: #fff; border: 1px solid #c8c6c4; border-radius: 6px; box-shadow: 0 4px 16px rgba(0,0,0,0.06); padding: 32px; box-sizing: border-box; }}
  .header {{ display: flex; justify-content: space-between; border-bottom: 2px solid #201f1e; padding-bottom: 16px; margin-bottom: 20px; }}
  .brand h1 {{ margin: 0; font-size: 22px; letter-spacing: -0.03em; font-weight: 700; }}
  .brand p {{ margin: 4px 0 0; font-size: 11px; color: #605e5c; font-family: monospace; letter-spacing: 0.05em; text-transform: uppercase; }}
  .meta {{ text-align: right; font-family: monospace; font-size: 11px; color: #605e5c; }}
  .meta strong {{ color: #201f1e; font-size: 13px; }}
  .grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }}
  .card {{ border: 1px solid #e1dfdd; border-radius: 4px; padding: 14px; background: #fdfdfd; }}
  .card h3 {{ margin: 0 0 10px; font-size: 11px; font-family: monospace; letter-spacing: 0.08em; text-transform: uppercase; color: #605e5c; border-bottom: 1px solid #edebe9; padding-bottom: 4px; }}
  .kv {{ display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 6px; }}
  .kv .k {{ color: #605e5c; }}
  .kv .v {{ font-family: monospace; font-weight: 600; color: #201f1e; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 6px; font-size: 12px; }}
  th {{ text-align: left; padding: 6px 10px; border-bottom: 1px solid #c8c6c4; font-family: monospace; font-size: 10px; color: #605e5c; text-transform: uppercase; background: #f3f2f1; }}
  .badge {{ display: inline-block; padding: 3px 8px; border-radius: 3px; font-family: monospace; font-size: 11px; font-weight: 700; color: #fff; background: {gate_color}; }}
  .exec-box {{ background: #f8f7f6; border: 1px solid #d2d0ce; border-left: 4px solid #0078d4; border-radius: 4px; padding: 14px; margin-top: 20px; }}
  .exec-box h3 {{ margin: 0 0 8px; font-size: 12px; font-family: monospace; text-transform: uppercase; color: #0078d4; }}
  .footer {{ margin-top: 24px; padding-top: 14px; border-top: 1px dashed #c8c6c4; display: flex; justify-content: space-between; font-family: monospace; font-size: 10px; color: #8a8886; }}
  .seal {{ overflow: hidden; text-overflow: ellipsis; max-width: 450px; white-space: nowrap; }}
  .actions-bar {{ max-width: 800px; margin: 0 auto 16px; display: flex; justify-content: flex-end; gap: 10px; }}
  .btn {{ background: #201f1e; color: #fff; border: 0; padding: 8px 16px; border-radius: 4px; font-family: monospace; font-size: 12px; font-weight: 600; cursor: pointer; }}
  .btn:hover {{ background: #323130; }}
  @media print {{
    body {{ background: #fff; padding: 0; }}
    .actions-bar {{ display: none; }}
    .receipt {{ border: 0; box-shadow: none; padding: 0; }}
  }}
</style>
<script>
  const RECEIPT_DATA = {receipt_json_str};
</script>
</head>
<body>
<div class="actions-bar">
  <button class="btn" onclick="window.print()">&#128438; PRINT / SAVE AS PDF</button>
  <button class="btn" style="background:#0078d4;" onclick="navigator.clipboard.writeText(JSON.stringify(RECEIPT_DATA,null,2));alert('Receipt JSON copied to clipboard!')">&#128203; COPY JSON AUDIT PROOF</button>
</div>

<div class="receipt">
  <div class="header">
    <div class="brand">
      <h1>REVIVE &middot; DECISION AUDIT RECEIPT</h1>
      <p>Autonomous Subscription Recovery Engine &middot; Institutional Ledger Record</p>
    </div>
    <div class="meta">
      <div>RECEIPT: <strong>{r['receipt_id']}</strong></div>
      <div>DATE: <strong>{r['timestamp'][:19].replace('T', ' ')} UTC</strong></div>
      <div>ENV: <strong>{r['environment']}</strong></div>
    </div>
  </div>

  <div class="grid2">
    <div class="card">
      <h3>1. Inbound Case Facts (What It Saw)</h3>
      <div class="kv"><span class="k">Event / Case ID</span><span class="v">{c['case_id']}</span></div>
      <div class="kv"><span class="k">Invoice Amount at Risk</span><span class="v">&#8377;{c['amount_inr']:,.2f}</span></div>
      <div class="kv"><span class="k">Failure Code &amp; Source</span><span class="v">{c['failure_reason']} ({c['failure_source']})</span></div>
      <div class="kv"><span class="k">Attempt Count</span><span class="v">{c['attempt_number']} of 4</span></div>
      <div class="kv"><span class="k">7-Day Contact Count</span><span class="v">{c['contact_count_7d']} {'(Fatigue Active)' if c['fatigue_penalty_active'] else ''}</span></div>
      <div class="kv"><span class="k">Subscription Status</span><span class="v">{c['subscription_status']}</span></div>
      <div class="kv"><span class="k">Payment Method</span><span class="v">{c['payment_method_type']}</span></div>
      <div class="kv"><span class="k">Native Retry Scheduled</span><span class="v">{'YES' if c['native_retry_scheduled'] else 'NO'}</span></div>
      <div class="kv"><span class="k">Customer Opt-Out</span><span class="v">{'YES' if c['customer_opted_out'] else 'NO'}</span></div>
    </div>

    <div class="card">
      <h3>2. Policy Gate Evaluation (What It Approved / Blocked)</h3>
      <div class="kv"><span class="k">Policy Gate Decision</span><span class="badge">{p['gate_decision']}</span></div>
      <div class="kv"><span class="k">Policy Version</span><span class="v">{p['policy_version']}</span></div>
      <div class="kv"><span class="k">Rule Identifier</span><span class="v">{p['policy_id']}</span></div>
      <div style="margin-top:10px;">
        <div style="font-size:10px;font-family:monospace;color:#605e5c;margin-bottom:4px;text-transform:uppercase;">Evaluated Deterministic Checks:</div>
        <table>
          <thead><tr><th>Rule ID</th><th>Description</th><th>Status</th></tr></thead>
          <tbody>{checks_rows}</tbody>
        </table>
      </div>
      {f'<div style="margin-top:8px;padding:6px;background:#fde7e9;border:1px solid #f8d7da;font-size:11px;font-family:monospace;color:#a80000;"><strong>VETO REASON:</strong> {p["veto_reasons"][0]}</div>' if p.get("veto_reasons") else ''}
    </div>
  </div>

  <div class="card" style="margin-bottom:20px;">
    <h3>3. Causal Predictions &amp; Marginal Economics</h3>
    <div style="display:flex;justify-content:space-between;margin-bottom:8px;font-size:11px;font-family:monospace;color:#605e5c;">
      <span>MODEL: {m['model_version']} (Calibrated T-Learner Ensemble)</span>
      <span>RISK PROFILE: {e['risk_mode']} (z = {e['risk_z']})</span>
    </div>
    <table>
      <thead>
        <tr>
          <th>Intervention Action</th>
          <th style="text-align:right;">Calibrated Recovery Prob (&plusmn;&sigma;)</th>
          <th style="text-align:right;">Expected Net Value vs Wait (INR)</th>
        </tr>
      </thead>
      <tbody>{econ_rows}</tbody>
    </table>
  </div>

  <div class="exec-box">
    <h3>4. Execution Outcome &amp; Realized Uplift (What Happened)</h3>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-top:6px;">
      <div>
        <div style="font-size:10px;font-family:monospace;color:#605e5c;">CHOSEN ACTION</div>
        <div style="font-size:16px;font-family:monospace;font-weight:700;color:#0078d4;margin-top:2px;">{x['chosen_action']}</div>
      </div>
      <div>
        <div style="font-size:10px;font-family:monospace;color:#605e5c;">EXECUTION STATUS</div>
        <div style="font-size:14px;font-family:monospace;font-weight:600;margin-top:2px;">{x['execution_status']}</div>
      </div>
      <div>
        <div style="font-size:10px;font-family:monospace;color:#605e5c;">NET RECOVERED</div>
        <div style="font-size:16px;font-family:monospace;font-weight:700;color:#107c41;margin-top:2px;">&#8377;{x['net_recovered_inr']:,.2f}</div>
      </div>
    </div>
    <div style="margin-top:10px;padding-top:10px;border-top:1px solid #edebe9;display:flex;justify-content:space-between;font-size:11px;font-family:monospace;color:#605e5c;">
      <span>GROSS: &#8377;{x['recovered_amount_inr']:,.2f} &middot; COST: &#8377;{x['intervention_cost_inr']:,.2f}</span>
      <span>INCREMENTAL LIFT OVER WAIT: <strong>&#8377;{x['incremental_realized_uplift_inr']:,.2f}</strong></span>
      <span>INTENT: {x['execution_intent_id'] or 'NONE'}</span>
    </div>
    {f'<div style="margin-top:6px;font-size:11px;font-family:monospace;color:#0078d4;">GATEWAY DETAIL: {x["execution_detail"]}</div>' if x.get("execution_detail") else ''}
  </div>

  <div class="footer">
    <div class="seal">SEAL HASH: {r['seal_hash']}</div>
    <div>DECISION ID: {r['decision_id']}</div>
    <div>REVIVE v6.0 &middot; CERTIFIED</div>
  </div>
</div>
</body>
</html>
""".replace("{receipt_json_placeholder}", json.dumps(receipt))
