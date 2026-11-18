"""D-1 + D-2 on AWS: the deployed door (API Gateway HTTP API with a Cognito JWT authorizer -> Lambda -> the door).

Every route in the deployed OpenAPI and every MCP tool gets six bad credentials:
- none;
- malformed;
- forged (an attacker's key);
- tampered (a real Cognito token with its groups edited);
- alg=none;
- a token from another issuer (the local dev issuer).
All must be 401. A valid Cognito token must get through. Refusals are recorded in two places: the edge (the API
Gateway access log, for requests the authorizer stops) or the door's DynamoDB audit trail (for any that reach it).

    python evals/deployed_route_check.py         # needs `aws login` + M3/cloud/deploy.sh
"""
import base64
import re
import json
import os
import subprocess
import sys
import time

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from _common import Report

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "door"))
from claimsense_door.cognito import token_for  # noqa: E402

DEPLOY = json.load(open(os.path.expanduser("~/.claimsense/deploy.json")))
URL = DEPLOY["door_url"]
SAMPLE = {"claim_id": "CLM-2024-1800", "policy_id": "POL-AU-08812", "doc_id": "DOC-2024-1800-FNOL-FORM",
          "rec_id": "REC-000000000000"}
PUBLIC = {"/healthz", "/.well-known/jwks.json", "/.well-known/oauth-protected-resource",
          "/.well-known/oauth-protected-resource/mcp", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc",
          "/dev/token", "/oauth/token", "/webhooks/ticketing"}


def b64(d):
    return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()


def main():
    R = Report(14, "deployed-route-auth", "D-1 + D-2 on AWS: every route and tool refuses a bad token")
    R.say(f"door: {URL} (API Gateway HTTP API · Cognito JWT authorizer · Lambda image {DEPLOY['image_tag']} "
          f"@ {DEPLOY['image_digest'][:19]}…)", "")
    valid = token_for("alice")
    h, p, s = valid.split(".")
    claims = json.loads(base64.urlsafe_b64decode(p + "=="))
    attacker = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    bads = {"no token": None, "malformed": "Token abc",
            "forged (attacker's key)": "Bearer " + jwt.encode(dict(claims, exp=int(time.time()) + 600), attacker,
                                                              algorithm="RS256", headers={"kid": jwt.get_unverified_header(valid)["kid"]}),
            "tampered (groups edited)": "Bearer " + ".".join([h, b64(dict(claims, **{"cognito:groups": ["senior-adjuster"]})), s]),
            "alg=none": "Bearer " + ".".join([b64({"alg": "none", "typ": "JWT"}), b64(claims), ""]),
            "another issuer (local dev issuer)": "Bearer " + jwt.encode(
                {"cognito:username": "alice", "cognito:groups": ["adjuster"], "iss": "https://claimsense.local/dev-issuer",
                 "aud": "claimsense-console", "token_use": "id", "exp": int(time.time()) + 600}, other, algorithm="RS256")}
    R.check("D-1: the deployed door answers its health check (public)", httpx.get(f"{URL}/healthz").json().get("ok") is True)
    spec = httpx.get(f"{URL}/openapi.json", headers={"Authorization": f"Bearer {valid}"}, timeout=30).json()
    routes = [(m.upper(), path) for path, ops in spec["paths"].items() for m in ops if path not in PUBLIC]
    start_ms = int(time.time() * 1000) - 2000
    sent = 0
    for method, path in routes:
        url = URL + path
        for k, v in SAMPLE.items():
            url = url.replace("{" + k + "}", v)
        codes = []
        for auth in bads.values():
            hd = {"Authorization": auth} if auth else {}
            if method == "POST":
                hd["Idempotency-Key"] = "deployed-route-check-01"
            codes.append(httpx.request(method, url, headers=hd, json={} if method == "POST" else None, timeout=30).status_code)
            sent += 1
        R.check(f"{method:<5} {path:<48}", all(c == 401 for c in codes), "all 401" if len(set(codes)) == 1 else str(codes))
    tools = [t["name"] for t in httpx.post(f"{URL}/mcp", headers={"Authorization": f"Bearer {valid}"},
                                           json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()["result"]["tools"]]
    for name in tools:
        codes = []
        for auth in bads.values():
            codes.append(httpx.post(f"{URL}/mcp", headers={"Authorization": auth} if auth else {},
                                    json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                          "params": {"name": name, "arguments": {"claim_id": "CLM-2024-1800"}}}).status_code)
            sent += 1
        R.check(f"MCP   tools/call {name:<38}", all(c == 401 for c in codes), "all 401" if len(set(codes)) == 1 else str(codes))
    ok = httpx.get(f"{URL}/claims/CLM-2024-1800", headers={"Authorization": f"Bearer {valid}"})
    R.check("a valid Cognito token gets through the edge AND the door", ok.status_code == 200
            and ok.json().get("claim_id") == "CLM-2024-1800")
    R.check("/dev/token does not exist on AWS (dev issuer off)", httpx.post(f"{URL}/dev/token", json={"user_id": "alice"},
                                                                             headers={"Authorization": f"Bearer {valid}"}).status_code == 404)
    ex = httpx.post(f"{URL}/oauth/token", json={"grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                                                 "subject_token": "forged", "actor": "agent:claimsense-pipeline"})
    R.check("token exchange refuses a forged subject token (RFC 6749 invalid_grant)", ex.status_code == 400)
    good = httpx.post(f"{URL}/oauth/token", json={"grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                                                   "subject_token": valid, "actor": "agent:claimsense-pipeline"})
    R.check("token exchange with alice's real Cognito token issues a narrowed delegated token (OBO on a real IdP)",
            good.status_code == 200 and "confirm_recommendation" not in good.json().get("scope", ""),
            f"scope: {good.json().get('scope')} · expires_in {good.json().get('expires_in')}s")
    R.say("", f"bad-credential requests sent: {sent}")
    edge = 0
    for _ in range(24):                                     # access logs land within seconds to a minute
        out = subprocess.run(["aws", "logs", "filter-log-events", "--log-group-name", "/claimsense/door-api-access",
                              # a TEXT match: the authorizer's error can contain quotes ('no "kid"'), which makes
                              # that line invalid JSON, so a JSON filter would silently skip it (found in this check)
                              "--start-time", str(start_ms), "--filter-pattern", '"\\"status\\":\\"401\\""',
                              "--query", "events[].message", "--output", "json"], capture_output=True, text=True)
        lines = json.loads(out.stdout or "[]")
        edge = len(lines)
        if edge >= sent:
            break
        time.sleep(5)
    rows = httpx.get(f"{URL}/audit", params={"limit": 1000}, headers={"Authorization": f"Bearer {token_for('bob')}"}).json()["rows"]
    door_denies = [r for r in rows if r["user_id"] == "anonymous" and r["decision"] == "deny"]
    R.check("every refusal is recorded: at the edge (API Gateway access log) or in the door's DynamoDB audit trail",
            edge + len(door_denies) >= sent, f"edge 401 log lines: {edge} · door anonymous deny rows: {len(door_denies)}")
    if lines:
        R.say("   e.g. edge: " + re.sub(r'"ip":"[^"]*"', '"ip":"<masked>"', lines[-1]))
    R.check("the door's audit trail on AWS is the DynamoDB table (append-only rows carry user, action, resource)",
            rows and all(r.get("user_id") and r.get("action") and r.get("resource") for r in rows),
            f"{len(rows)} rows read back through GET /audit as bob (senior-adjuster)")
    return R.finish("python evals/deployed_route_check.py")


if __name__ == "__main__":
    sys.exit(main())
