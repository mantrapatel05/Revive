# REVIVE — Interactive Demo Script & Operator Runbook

## Pre-flight Checklist (DO THIS BEFORE RECORDING)
1. Ensure your `.env` file has `ENABLE_TESTMODE_EXECUTION=true` and valid `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET`. (If this isn't set, clicking "Run Live" will silently fall back to the simulator!)
2. Ensure `RAZORPAY_WEBHOOK_SECRET` is set in `.env` (the placeholder is fine).

## Target Duration: ~5 minutes

> **DEMO RULE: NO TYPING.** You will drive this entire demo using only your mouse to click the Preset Buttons and UI controls. It is highly recommended to record this in three separate parts and merge them later for the most professional delivery.

---

### PART 1: The Intro & Overview
*(Face-to-camera or just screen with dashboard open on the `Bank declined (Blocked)` case. Don't touch your mouse.)*

**0:00 — Problem Framing**
* **ACTION**: Point to the 10-field Context Grid on the left.
* **SPEAK**: "Payment failures are expensive. Naive retries annoy customers, and manual outreach costs too much. REVIVE fixes this by using causal ML to find the most profitable recovery action, while using hard policy gates to guarantee safety."

**0:20 — Executive Dashboard & Evaluation KPIs**
* **ACTION**: Point directly to the top KPI metrics bar.
* **SPEAK**: "Our dashboard tracks performance. We capture 84% of the absolute maximum possible recovery, but we do it safely. We're driving over ₹1.2 Lakhs in expected recovery, significantly beating naive waiting strategies."

*(Cut the recording here)*

---

### PART 2: The Core Walkthrough
*(Start recording. You interacting with the dashboard.)*

**0:45 — Case Context Grid & Model Predictions**
* **ACTION**: Point to the Context Grid. 
* **SPEAK**: "Let's look at a Bank Declined case. The Grid shows the exact customer state, including active fatigue penalties."
* **ACTION**: Point down to the Model Predictions panel with the progress bars.
* **SPEAK**: "Below, our ML ensemble predicts the success probability and confidence intervals for every action: Wait, Nudge, and Manual Recovery."

**1:45 — Counterfactual Economics & Gate Arbitration**
* **ACTION**: Point to the Counterfactual Economics panel and the Policy Evidence checklist.
* **SPEAK**: "Here's where it gets interesting. The ML model saw high upside and recommended a Manual Recovery. But look at the Policy Checks."
* **ACTION**: Point to the failed policy checks (e.g., domestic card, native retry scheduled).
* **SPEAK**: "It's a domestic card and a native retry is already scheduled. Because it broke these hard rules, our deterministic gate instantly blocked the ML and fell back to Wait. Safety always overrides the model."
* **ACTION**: Click the `GATE: ON (ENFORCED)` button to toggle it to OFF. 
* **SPEAK**: "We can toggle the gate off to see the theoretical unconstrained optimum, but it is strictly audited and never executed."

**2:45 — Live Execution & Payment Link Generation**
* **ACTION**: Click the `Expired (Passes Gate)` preset button.
* **ACTION**: Click the cyan `⚡ Run Live` button next to the Run Case button.
* **SPEAK**: "Now let's run a live case that actually passes the gate. I've triggered a Live webhook execution. For an expired card, the ML correctly predicts that trying to blindly charge it will fail, and instead proposes a Nudge. Because it passes all safety boundaries, it is approved for live execution."
* **ACTION**: Point to the Execution Trace timeline at the bottom right.
* **SPEAK**: "Look at the Execution trace. It moves through Decision, Authorization, Outbox, and Execution. The Live Executor securely hits the Razorpay API and instantly returns a live checkout link."
* **ACTION**: Point to the cyan `OPEN PAYMENT LINK ↗` that just appeared on screen.

**3:20 — Failure Handling & Reconciliation**
* **ACTION**: Point to the Reconciliation step in the Execution Trace box.
* **SPEAK**: "Our execution architecture is fully asynchronous and idempotent. An external timeout from Razorpay does not equal an operation failure. Blind retries are unsafe. Ambiguous gateway responses enter a reconciliation query queue rather than risking double-charging a customer."

*(Cut the recording here)*

---

### PART 3: The Terminal Drop-the-Mic
*(Start recording. Keep the browser open, but switch your screen to the PowerShell terminal window.)*

**3:45 — Live Failure Injection & Webhook Idempotency**
* **ACTION**: Run the live idempotency script by pressing UP arrow and hitting ENTER (or typing `python scripts/fire_live_webhook.py`).
* **SPEAK**: "Watch — I'm sending Razorpay's real signed payment failure webhook directly into REVIVE. The boundary verifies the cryptographic HMAC signature, acquires the idempotency lock, and queues the decision."
* **ACTION**: Run the exact same script a second time immediately. 
* **SPEAK**: "Now watch what happens when Razorpay retries delivery—which is standard gateway behavior over the wire. Notice the terminal returns an HTTP 200 acknowledgment, but flags it as a duplicate. Zero duplicate outbox intents were generated, and the customer is never double-charged. This failure mode breaks naive recovery systems in production; REVIVE treats it as a first-class mathematical guarantee."

**4:40 — Conclusion**
* **ACTION**: Switch back to the dashboard, scroll down, and expand the `RAW DECISION PAYLOAD · JSON INSPECTOR` dropdown.
* **SPEAK**: "REVIVE does not give a probabilistic model permission to move money autonomously. It uses causal ML to estimate incremental uplift, deterministic policy boundaries to guarantee safety, and an idempotent outbox with reconciliation to execute real gateway operations without operational risk. Every decision is immutably logged right here."
