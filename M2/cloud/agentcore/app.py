"""AgentCore Runtime entry point for the ClaimSense pipeline (W15 stretch: "AgentCore config written out").

The three lines the course shows, around the SAME pipeline the orchestrator, CI and Lambda run unchanged:

    agentcore configure --entrypoint app.py      # writes .bedrock_agentcore.yaml (ours is committed beside this)
    agentcore launch                             # ARM64 container via CodeBuild -> ECR -> Runtime
    agentcore invoke '{"claim_id": "CLM-2024-1800", "user_id": "alice"}'

AgentCore's runtime session id becomes the ClaimSense run_id, so re-invoking the same session RESUMES the claim
from its checkpoints (D-027) instead of re-running finished agents. Written, not deployed (D-028).
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))       # M2/ (claimsense package)
os.environ.setdefault("CLAIMSENSE_STATE", "/tmp/claimsense-state")    # M3: AgentCore Memory / DynamoDB

from bedrock_agentcore import BedrockAgentCoreApp  # noqa: E402

from claimsense.pipeline import Pipeline  # noqa: E402

app = BedrockAgentCoreApp()
PIPE = Pipeline()


@app.entrypoint
async def invoke(payload, context=None):
    claim_id, user_id = payload.get("claim_id"), payload.get("user_id")
    if not claim_id or not user_id:
        return {"error": {"code": "invalid_request", "message": "claim_id and user_id are required."}}
    session = getattr(context, "session_id", None) if context is not None else None
    run_id = f"{claim_id}:{session}" if session else None
    resume = bool(run_id) and PIPE.checkpoints.has(run_id)
    result = await PIPE.run(claim_id, user_id, run_id=run_id, resume=resume)
    return {"run_id": result["run_id"], "resumed": resume, "decided_by": result["decided_by"],
            "card": result["response"], "cost_usd": result["cost_usd"], "trace_id": result.get("trace_id")}


if __name__ == "__main__":
    app.run()
