# REVIVE 6.0 — Deterministic Policy Specification

## Authority Architecture

The machine learning subsystem (Calibrated T-Learner) computes probabilistic recovery estimates and bootstrap uncertainty. The economics engine computes risk-discounted marginal uplift. The **Policy Gate** is the sole deterministic authority that determines action feasibility. An action that fails any hard check is stripped from the candidate set before optimization.

```text
ML Uplift Prediction ───► Economics Ranking ───► Policy Gate ───► Execution Authorization
                                                      │
                                                      ├─ Hard Failure: Block Action
                                                      └─ Feasible: Pass to Outbox
```

## Deterministic Hard Constraints

| Check ID | Rule Description | Logic & Parameters | Enforcement Action |
|---|---|---|---|
| `TIME-QUIET-001`| Quiet Hours Compliance | `08:00 <= current_time_IST < 19:00` | Rejects `NUDGE` and `MANUAL_RECOVERY` outside 08:00–19:00 IST with `"outside_quiet_hours"`; non-customer-facing `WAIT` allowed |
| `FREQ-DAILY-001`| Daily Frequency Cap | `case.contacted_today == False` | Rejects `NUDGE` and `MANUAL_RECOVERY` on same-day repeat touches with `"daily_contact_cap"`; non-customer-facing `WAIT` allowed |
| `CUST-OPT-001` | Customer Opt-Out Compliance | `case.customer_opted_out == False` | Blocks `NUDGE` and `MANUAL_RECOVERY` immediately; routes to `WAIT` or `ESCALATE` |
| `SUB-STATE-001`| Eligible Subscription State | `case.subscription_status in {"pending", "halted"}` | Blocks automated recovery on canceled/terminated subscriptions |
| `WAIT-STATE-001`| Native Retry Eligibility | `case.subscription_status == "pending"` | Forbids `WAIT` if subscription is already halted (no native retry exists) |
| `FIN-AUTO-002` | Automatic Action Ceiling | `case.amount <= merchant_config.max_auto_action_amount` (₹3,000) | Blocks automated outreach on high-value transactions; mandates human escalation |
| `RET-LIMIT-001`| Attempt Budget Limit | `case.attempt_number < 4` | Blocks additional automated retry attempts after 4 failed cycles |
| `INV-ELIG-001` | Invoice Chargeability | `case.invoice_status == "issued"` | Forbids manual charge paths on draft, paid, or voided invoices |
| `PM-ELIG-001`  | Payment Method Support | `case.payment_method_type != "domestic_card"` | Rejects manual recovery attempts on domestic cards requiring step-up 2FA |
| `DUP-NATIVE-001`| Native Retry Collision | `case.native_retry_scheduled == False` | Blocks manual charging when the payment gateway already has an active retry scheduled |
| `PROB-MIN-001` | Minimum Probability Floor | `P_cal(MANUAL_RECOVERY) >= 0.20` | Rejects low-probability manual outreach where expected cost exceeds recovery likelihood |
| `RISK-DECLINE-001` | Risk Decline Safety Block | `case.decline_class not in {"risk", "risk_decline"}` | Blocks `NUDGE` and `MANUAL_RECOVERY` on fraud/risk-flagged declines with `"Decline flagged as risk or suspected fraud"`; routes to `WAIT` or `ESCALATE` |

## Soft Constraints & Economic Adjustments

| Factor | Description | Implementation |
|---|---|---|
| Contact Fatigue | Accounts with $>2$ touches in 7 days incur penalty | Adds ₹50 penalty cost in `EconomicsEngine.action_cost()` |
| Risk Mode Discounting | Penalizes high-uncertainty actions | Subtracts $z \cdot \sigma(a, x)$ from expected recovery ($z=2.0$ Conservative, $z=1.0$ Balanced, $z=0.0$ Aggressive) |
| Inbound Auth Gate | Stale TTL or version mismatch verification | Rejects stale tokens ($>300\text{s}$) or mismatched `policy_version`/`model_version` |
| Drift Gating | Inbound cases deviating from training distribution | PSI $>0.25$ flags `distribution_shift_flagged=True` and routes directly to `ESCALATE` |
