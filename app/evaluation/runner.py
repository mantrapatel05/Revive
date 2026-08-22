import pandas as pd
from app.execution.simulator import SubscriptionSimulator
from app.evaluation.baselines import native, rule_based
from app.pipeline import RecoveryPipeline
from app.evaluation.metrics import compute_metrics
from app.economics import EconomicsEngine
from app.db import init_db

class EvaluationRunner:
    """Frozen-world evaluator with an incremental-value decision objective."""
    def __init__(self, model=None, seed=42):
        init_db()
        self.sim = SubscriptionSimulator(seed)
        self.pipeline = RecoveryPipeline(model=model, simulator=self.sim)
        self.economics = EconomicsEngine()

    def _result(self, r):
        return {
            "action": r.action,
            "success": r.success,
            "recovered_amount": r.recovered_amount,
            "cost": r.cost,
            "net_recovered": r.recovered_amount-r.cost,
        }

    def run(self, cases):
        total=sum(float(c["amount"]) for c in cases)
        buckets={k:[] for k in ["native","rule","ml_only","revive","oracle","constrained_oracle"]}
        oracle_expected=[]
        revive_expected=[]
        safety={"revive_policy_blocks":0,"revive_fallbacks":0,"ml_unsafe_actions":0}

        for case in cases:
            n=native(case,self.sim)
            buckets["native"].append(self._result(n))

            rb=rule_based(case,self.sim)
            buckets["rule"].append(self._result(rb))

            # Unconstrained ML: choose the highest predicted *incremental* value.
            if self.pipeline.model:
                probs=self.pipeline.model.predict(case)
            else:
                latent=self.sim.latent_state(case)
                probs={a:self.sim.probability(case,a,latent) for a in self.sim.ACTIONS}
            inc=self.economics.rank_incremental(case, probs)
            ml_action=max(inc,key=inc.get)
            # Human escalation is not an automated ML action; use WAIT when no positive intervention value exists.
            if inc[ml_action] <= 0:
                ml_action="WAIT"
            if ml_action == "MANUAL_RECOVERY":
                payment_method = case.get("payment_method_type")
                eligible = case.get("invoice_status")=="issued" and payment_method!="domestic_card"
                if not eligible:
                    safety["ml_unsafe_actions"] += 1
            ml=self.sim.execute(case,ml_action)
            buckets["ml_only"].append(self._result(ml))

            full=self.pipeline.process(case)
            if full["policy_decision"] == "BLOCKED":
                safety["revive_policy_blocks"] += 1
            if full["policy_action"] != full["recommended_action"]:
                safety["revive_fallbacks"] += 1
            buckets["revive"].append({
                "action":full["policy_action"],
                "success":full["execution_status"]=="SUCCESS",
                "recovered_amount":full["recovered_amount"],
                "cost":full["intervention_cost"],
                "net_recovered":full["net_recovered"],
            })

            oracle_action,oracle_ev,oracle_probs=self.sim.oracle_action(case)
            oe=self.sim.execute(case,oracle_action)
            buckets["oracle"].append(self._result(oe))
            oracle_expected.append(oracle_ev)
            revive_expected.append(full["incremental_values"].get(full["policy_action"],0.0))

            constrained_action, constrained_ev, constrained_probs = self.sim.constrained_oracle_action(case, self.pipeline.policy)
            coe=self.sim.execute(case, constrained_action)
            buckets["constrained_oracle"].append(self._result(coe))

        metrics={k:compute_metrics(v,total) for k,v in buckets.items()}
        metrics["regret_mean"] = sum(oracle_expected[i]-revive_expected[i] for i in range(len(cases)))/len(cases)
        metrics["safety"]=safety
        return metrics
