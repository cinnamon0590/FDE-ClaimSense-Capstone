#!/usr/bin/env python3
"""AgentCore Gateway: the MANAGED twin of the ClaimSense door (M3 Architect tier). Adapted from the W16 lab ladder.

    python gateway_setup.py plan      # $0 floor: prints every AWS call `apply` would make, real payloads, no creds
    python gateway_setup.py apply     # role -> gateway (Cognito JWT inbound) -> target (openapi.json)
    python gateway_setup.py invoke    # MCP tools/list + get_claim, with an adjuster's Cognito token
    python gateway_setup.py destroy   # leave nothing running

The difference from the lab (and the reason it matters for ClaimSense): the lab's gateway authenticates callers with
AWS_IAM and injects ONE scoped API key into every backend call. For AutoSure that would turn every adjuster into the
same identity and destroy per-user scope. So the ClaimSense gateway uses a CUSTOM_JWT inbound authorizer (the Cognito
user pool, audience = the console's app client) and the target is the door's own REST API, which re-verifies the
token and applies grants + entitlement + audit itself. Whether Gateway can pass the CALLER's token through to an
OpenAPI target unchanged must be verified against the current AgentCore docs at apply time; until it is, writes and
any per-user-scoped tool stay on the hand-built MCP door (see README.md, the one-page decision).

`apply` needs: AWS credentials with bedrock-agentcore-control + iam:CreateRole/PutRolePolicy/PassRole, the deployed
door URL (CLAIMSENSE_DOOR_URL), and the Cognito discovery URL + app client id (from ../cloud/deploy.sh outputs).
Nothing here runs unless Susan approves the spend (D-040; expected $0 within the free tier, destroyed after).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
REGION = os.environ.get("AWS_REGION", "us-east-1")
GATEWAY_NAME = "claimsense-gateway"
TARGET_NAME = "claimsense-door"
ROLE_NAME = "ClaimSenseAgentCoreGatewayRole"
STATE_FILE = HERE / "gateway_state.json"          # gitignored; ids/ARNs apply created, for destroy
OPENAPI = json.loads((HERE / "openapi.json").read_text())

TRUST_POLICY = {"Version": "2012-10-17", "Statement": [{
    "Effect": "Allow", "Principal": {"Service": "bedrock-agentcore.amazonaws.com"}, "Action": "sts:AssumeRole"}]}
ROLE_POLICY = {"Version": "2012-10-17", "Statement": [{     # least privilege: the gateway holds no data access
    "Effect": "Allow", "Action": ["bedrock-agentcore:GetWorkloadAccessToken"], "Resource": "*"}]}


def _cfg():
    return {"door": os.environ.get("CLAIMSENSE_DOOR_URL", "https://<door-api-id>.execute-api.us-east-1.amazonaws.com"),
            "discovery": os.environ.get("CLAIMSENSE_COGNITO_DISCOVERY",
                                        "https://cognito-idp.us-east-1.amazonaws.com/<pool-id>/.well-known/openid-configuration"),
            "audience": os.environ.get("CLAIMSENSE_COGNITO_CLIENT_ID", "<console app client id>")}


def _spec(door_url):
    spec = dict(OPENAPI, servers=[{"url": door_url}])
    return json.dumps(spec)


def calls(role_arn="arn:aws:iam::<your-account>:role/" + ROLE_NAME):
    c = _cfg()
    ops = [op["operationId"] for p in OPENAPI["paths"].values() for op in p.values()]
    return [
        ("iam.create_role (once)", {"RoleName": ROLE_NAME, "AssumeRolePolicyDocument": TRUST_POLICY,
                                    "_inline_policy": ROLE_POLICY}),
        ("bedrock-agentcore-control.create_gateway", {
            "name": GATEWAY_NAME, "roleArn": role_arn, "protocolType": "MCP",
            "authorizerType": "CUSTOM_JWT",
            "authorizerConfiguration": {"customJWTAuthorizer": {"discoveryUrl": c["discovery"],
                                                                "allowedAudience": [c["audience"]]}},
            "description": "Managed MCP door over the ClaimSense REST door (AutoSure, synthetic) — M3 twin"}),
        ("bedrock-agentcore-control.create_gateway_target", {
            "gatewayIdentifier": "<gateway id from create_gateway>", "name": TARGET_NAME,
            "targetConfiguration": {"mcp": {"openApiSchema": {
                "inlinePayload": f"<openapi.json, servers=[{c['door']}], {len(ops)} operations: {', '.join(ops)}>"}}},
            "credentialProviderConfigurations": [{"credentialProviderType": "GATEWAY_IAM_ROLE",
                                                  "_note": "no stored credential: the caller's bearer token must reach "
                                                           "the door, which re-verifies it (verify pass-through at apply)"}]}),
    ]


def plan():
    print("PLAN: the calls `apply` will make (nothing is created, no credentials needed):\n")
    for i, (name, payload) in enumerate(calls(), 1):
        print(f"  {i}. {name}")
        print("     " + json.dumps(payload, indent=2).replace("\n", "\n     "))
        print()
    print("Then: the MCP endpoint is the gatewayUrl create_gateway returns. Callers present an adjuster's Cognito "
          "token;\nGateway validates it at the edge (CUSTOM_JWT) and the door validates it AGAIN and applies grants, "
          "entitlement\nand the audit. Gateway replaces tool wiring; it never replaces enforcement.")


def _clients():
    import boto3
    return boto3.client("iam"), boto3.client("bedrock-agentcore-control", region_name=REGION)


def apply():
    from botocore.exceptions import ClientError
    c = _cfg()
    if "<" in c["door"] + c["discovery"] + c["audience"]:
        sys.exit("Set CLAIMSENSE_DOOR_URL, CLAIMSENSE_COGNITO_DISCOVERY and CLAIMSENSE_COGNITO_CLIENT_ID first "
                 "(outputs of ../cloud/deploy.sh).")
    iam, ctl = _clients()
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    try:
        try:
            role_arn = iam.create_role(RoleName=ROLE_NAME, AssumeRolePolicyDocument=json.dumps(TRUST_POLICY))["Role"]["Arn"]
            iam.put_role_policy(RoleName=ROLE_NAME, PolicyName="gateway-least-priv", PolicyDocument=json.dumps(ROLE_POLICY))
        except ClientError as e:
            if e.response["Error"]["Code"] != "EntityAlreadyExists":
                raise
            role_arn = iam.get_role(RoleName=ROLE_NAME)["Role"]["Arn"]
        print(f"✓ role {role_arn}")
        if "gateway_id" not in state:
            gw = ctl.create_gateway(name=GATEWAY_NAME, roleArn=role_arn, protocolType="MCP", authorizerType="CUSTOM_JWT",
                                    authorizerConfiguration={"customJWTAuthorizer": {
                                        "discoveryUrl": c["discovery"], "allowedAudience": [c["audience"]]}},
                                    description="Managed MCP door over the ClaimSense REST door (M3 twin)")
            state.update(gateway_id=gw["gatewayId"], gateway_url=gw.get("gatewayUrl"))
        print(f"✓ gateway {state['gateway_id']} → {state.get('gateway_url')}")
        _wait_ready(ctl, state["gateway_id"])                 # the lab's race fix: target only after READY
        if "target_id" not in state:
            tgt = ctl.create_gateway_target(gatewayIdentifier=state["gateway_id"], name=TARGET_NAME,
                                            targetConfiguration={"mcp": {"openApiSchema": {
                                                "inlinePayload": _spec(c["door"])}}},
                                            credentialProviderConfigurations=[
                                                {"credentialProviderType": "GATEWAY_IAM_ROLE"}])
            state["target_id"] = tgt["targetId"]
        print(f"✓ target {state['target_id']}\n\nNext: python gateway_setup.py invoke")
    finally:
        if state:
            STATE_FILE.write_text(json.dumps(state, indent=2))


def _wait_ready(ctl, gateway_id, timeout=180):
    import time
    for _ in range(timeout // 5):
        status = ctl.get_gateway(gatewayIdentifier=gateway_id)["status"]
        if status == "READY":
            return
        if status in ("FAILED", "DELETING"):
            sys.exit(f"gateway entered {status}")
        time.sleep(5)
    sys.exit("gateway not READY in time")


def invoke():
    import urllib.request
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else sys.exit("run apply first")
    sys.path.insert(0, str(HERE.parent / "door"))
    from claimsense_door.cognito import token_for
    for user in ("alice", "carol"):
        for body in ({"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                     {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                      "params": {"name": f"{TARGET_NAME}___get_claim", "arguments": {"claim_id": "CLM-2024-1800"}}}):
            req = urllib.request.Request(state["gateway_url"], data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json",
                                                  "Authorization": f"Bearer {token_for(user)}"})
            with urllib.request.urlopen(req, timeout=30) as r:
                print(user, body["method"], "→", r.read().decode()[:300])


def destroy():
    from botocore.exceptions import ClientError
    import time
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    iam, ctl = _clients()

    def target():
        ctl.delete_gateway_target(gatewayIdentifier=state["gateway_id"], targetId=state["target_id"])
        for _ in range(24):                           # async: the gateway can't go while a target remains
            if not ctl.list_gateway_targets(gatewayIdentifier=state["gateway_id"]).get("items"):
                return
            time.sleep(5)
    for what, fn in [("target", target), ("gateway", lambda: ctl.delete_gateway(gatewayIdentifier=state["gateway_id"])),
                     ("role policy", lambda: iam.delete_role_policy(RoleName=ROLE_NAME, PolicyName="gateway-least-priv")),
                     ("role", lambda: iam.delete_role(RoleName=ROLE_NAME))]:
        try:
            fn()
            print(f"✓ deleted {what}")
        except (ClientError, KeyError) as e:
            print(f"  (skip {what}: {e})")
    STATE_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    {"plan": plan, "apply": apply, "invoke": invoke, "destroy": destroy}[sys.argv[1] if len(sys.argv) > 1 else "plan"]()
