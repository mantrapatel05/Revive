from app.config import MODEL_VERSION, POLICY_VERSION, PROMPT_VERSION, SCENARIO_VERSION

def versions() -> dict:
    return {"model_version":MODEL_VERSION,"policy_version":POLICY_VERSION,"prompt_version":PROMPT_VERSION,"scenario_version":SCENARIO_VERSION}
