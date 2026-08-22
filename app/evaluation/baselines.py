from app.economics import EconomicsEngine

def native(case, sim):
    r=sim.execute(case,"WAIT")
    return r

def rule_based(case, sim):
    source=case.get("failure_source","unknown"); reason=case.get("failure_reason","unknown"); attempt=int(case.get("attempt_number",1))
    if case.get("native_retry_scheduled",False):
        action="WAIT"
    elif reason=="card_expired": action="NUDGE"
    elif reason=="insufficient_funds" and attempt<=2: action="MANUAL_RECOVERY"
    elif attempt>=4: action="ESCALATE"
    else: action="WAIT"
    return sim.execute(case,action)


def baseline_rule_based(case):
    """Return the deterministic rule action for compatibility with evaluation scripts."""
    source=case.get("failure_source","unknown"); reason=case.get("failure_reason","unknown"); attempt=int(case.get("attempt_number",1))
    if case.get("native_retry_scheduled",False): return "WAIT"
    if reason=="card_expired": return "NUDGE"
    if reason=="insufficient_funds" and attempt<=2: return "MANUAL_RECOVERY"
    if attempt>=4: return "ESCALATE"
    return "WAIT"
