# AgentCore Runtime: the managed rung of the deploy ladder (written, not deployed)

W15 stretch: *"AgentCore config written out."* Lambda (`../lambda/`) is the rung we deployed, invoked and tore
down. This is the next one, ready to review: start on Lambda, graduate to AgentCore when sessions outgrow
15 minutes or procurement asks the isolation and identity questions (W15 slide 32).

| File | What it is |
|---|---|
| [`app.py`](app.py) | The entry point: `BedrockAgentCoreApp` around the **unchanged** ClaimSense pipeline. The AgentCore session id becomes the `run_id`, so re-invoking a session resumes the claim from its checkpoints (D-027) |
| [`.bedrock_agentcore.yaml`](.bedrock_agentcore.yaml) | The starter-toolkit config `agentcore configure` would write: ARM64, us-east-1, observability on, Bedrock models, short-term memory |
| [`execution-role-policy.json`](execution-role-policy.json) | Least privilege: invoke only the pilot's two Claude profiles, read only the one secret, write logs/traces, pull the image |
| [`requirements.txt`](requirements.txt) | The image dependencies (orchestrator pins + Bedrock bridge + AgentCore SDK) |

## Deploy (when approved; needs `bedrock-agentcore:*`, ECR push, CodeBuild, `iam:PassRole`)

```bash
pip install bedrock-agentcore-starter-toolkit
aws iam create-role --role-name claimsense-agentcore-runtime ...   # trust: bedrock-agentcore.amazonaws.com
aws iam put-role-policy --role-name claimsense-agentcore-runtime --policy-name claimsense \
    --policy-document file://execution-role-policy.json            # after filling <ACCOUNT_ID>
agentcore configure --entrypoint app.py        # or use the committed .bedrock_agentcore.yaml
agentcore launch
agentcore invoke '{"claim_id": "CLM-2024-1800", "user_id": "alice"}'
agentcore destroy                              # consumption-priced, but still tear down after the demo
```

## How AgentCore's services map onto what ClaimSense already built

| AgentCore service | ClaimSense today (M2) | What changes |
|---|---|---|
| **Runtime** (microVM per session, hours-long) | Docker container / Lambda (15-minute cap) | Per-session isolation; long claims never hit a timeout |
| **Memory** | SDK `SQLiteSession` (Ask ClaimSense) + per-step checkpoints on `/state` (D-027) | Managed short- and long-term memory; no volume to run |
| **Identity** (OAuth vault, on-behalf-of) | `X-User-Id` + `X-On-Behalf-Of-Agent` headers; agents can't confirm (D-024) | Real scoped tokens instead of headers (M3 also adds Cognito) |
| **Gateway** (APIs → MCP tools) | Hand-written tools over the data boundary | The boundary's OpenAPI becomes an MCP toolset (W16) |
| **Observability** (OTel → CloudWatch) | `JsonlTraceProcessor` + OpenAI Traces | Same spans, in the client's CloudWatch |

Model tokens are billed separately by Bedrock; runtime is CPU- and memory-seconds while working (no idle burn).
