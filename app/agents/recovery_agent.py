import json
import requests
from app.config import GROQ_API_KEY, GROQ_MODEL, PROMPT_VERSION
from app.economics import EconomicsEngine

ACTIONS = ["WAIT","NUDGE","MANUAL_RECOVERY","ESCALATE"]

class RecoveryAgent:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key if api_key is not None else GROQ_API_KEY
        self.model = model or GROQ_MODEL
        self.economics = EconomicsEngine()

    def deterministic(self, case: dict, probabilities: dict[str,float]) -> dict:
        # Decision objective is incremental value versus WAIT, not raw recovery probability.
        values = self.economics.rank_incremental(case, probabilities)
        best = max(values, key=values.get)
        # Never proactively choose human escalation in the automated optimizer.
        if values[best] > 0:
            action = best
        else:
            action = "WAIT" if case.get("native_retry_scheduled", False) else "ESCALATE"
        return {"action":action,"reason":f"Maximum expected incremental net value: ₹{values.get(action,0.0):.2f}","reason_codes":["INCREMENTAL_VALUE_MAX"],"confidence":1.0,"source":"deterministic","prompt_version":PROMPT_VERSION}

    def _call_llm(self, prompt: dict) -> dict | None:
        if not self.api_key:
            return None
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization":f"Bearer {self.api_key}","Content-Type":"application/json"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "user", "content": json.dumps(prompt)}
                    ],
                    "temperature": 0.2
                },
                timeout=20,
            )
            r.raise_for_status()
            res_data = r.json()
            if "choices" in res_data and len(res_data["choices"]) > 0:
                text = res_data["choices"][0].get("message", {}).get("content", "").strip()
            else:
                text = res_data.get("output_text", "").strip()

            if not text:
                return None

            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            parsed = json.loads(text)
            action = str(parsed.get("action","")).upper()
            if action not in ACTIONS:
                return None
            return {"action":action,"reason":str(parsed.get("reason","")),"reason_codes":parsed.get("reason_codes",[]),"confidence":float(parsed.get("confidence",0.0)),"source":"llm","prompt_version":PROMPT_VERSION}
        except Exception:
            return None

    def llm(self, case: dict, probabilities: dict[str,float], incremental_values: dict[str,float]) -> dict | None:
        prompt = {
            "role":"payment_recovery_decision_assistant",
            "instructions":"Analyze the payment failure case and return a JSON object with: 'action' (one of WAIT, NUDGE, MANUAL_RECOVERY, ESCALATE), 'reason' (clear justification), 'reason_codes' (list of tags), and 'confidence' (float between 0 and 1).",
            "rules":["Choose exactly one action from WAIT, NUDGE, MANUAL_RECOVERY, ESCALATE.","Do not invent facts.","Never override policy constraints.","Treat WAIT as the default baseline; intervene only when there is clear positive incremental value."],
            "case":case,
            "recovery_probabilities":probabilities,
            "incremental_expected_values":incremental_values,
        }
        return self._call_llm(prompt)

    def llm_only(self, case: dict) -> dict | None:
        prompt = {
            "role":"payment_recovery_decision_assistant",
            "rules":["Choose exactly one action from WAIT, NUDGE, MANUAL_RECOVERY, ESCALATE.","Use only supplied case facts.","Do not invent recovery probabilities.","WAIT is the default when intervention value is unclear."],
            "case":case,
            "actions":{
                "WAIT":"Let Razorpay's native retry lifecycle continue.",
                "NUDGE":"Ask the customer to fix/update the payment method.",
                "MANUAL_RECOVERY":"Attempt an eligible issued invoice manually.",
                "ESCALATE":"Stop automation and route to human operations.",
            },
        }
        return self._call_llm(prompt)

    def decide(self, case: dict, probabilities: dict[str,float]) -> dict:
        incremental_values = self.economics.rank_incremental(case, probabilities)
        result = self.llm(case, probabilities, incremental_values)
        return result if result is not None else self.deterministic(case, probabilities)
