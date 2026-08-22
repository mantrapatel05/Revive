import numpy as np

def compute_metrics(results: list[dict], total_at_risk: float, oracle_values: list[float] | None = None):
    gross = sum(r["recovered_amount"] for r in results)
    net = sum(r["net_recovered"] for r in results)
    cost = sum(r["cost"] for r in results)
    interventions = [r for r in results if r["action"] in {"NUDGE","MANUAL_RECOVERY"}]
    return {
        "cases":len(results),
        "total_at_risk":total_at_risk,
        "gross_recovered":gross,
        "net_recovered":net,
        "intervention_cost":cost,
        "net_recovery_rate": net/total_at_risk if total_at_risk else 0,
        "intervention_rate": len(interventions)/len(results) if results else 0,
        "success_rate": sum(bool(r["success"]) for r in results)/len(results) if results else 0,
        "unnecessary_interventions": sum((r["action"] in {"NUDGE","MANUAL_RECOVERY"} and not r["success"]) for r in results),
        "escalation_rate": sum(r["action"]=="ESCALATE" for r in results)/len(results) if results else 0,
        "wait_rate": sum(r["action"]=="WAIT" for r in results)/len(results) if results else 0,
        "mean_net_per_case": net/len(results) if results else 0,
    }

def bootstrap_mean_ci(values: list[float], n=5000, seed=42):
    arr=np.asarray(values,dtype=float)
    rng=np.random.default_rng(seed)
    samples=rng.choice(arr,size=(n,len(arr)),replace=True).mean(axis=1)
    return float(np.quantile(samples,0.025)), float(np.quantile(samples,0.975))
