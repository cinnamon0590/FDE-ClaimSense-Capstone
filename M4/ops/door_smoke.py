"""Post-deploy smoke test for the deployed door (incident-drill-1 action item, D-050): the same four reads the drill's
canary makes, as a real signed-in adjuster (alice, Cognito), through API Gateway, plus the agents' own path (the
delegated token on /mcp, RCA-2). Exit 0 only if every one passes.

    python M4/ops/door_smoke.py            # also usable as a scheduled canary (cron / GitHub Actions schedule)

`M3/cloud/deploy.sh` runs it after every door release and restores the previous image and configuration when it
fails, so a release that can't read its data never stays live. A /healthz check alone was not enough evidence:
health says the process is up, not that a user can read a claim, a policy, its documents and the KB.
"""
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "M3" / "door"), str(ROOT / "M2")]
ROUTES = ["/claims/CLM-2024-1800", "/policies/POL-AU-10418", "/claims/CLM-2024-1800/documents",
          "/policy-kb/search?q=collision"]


def main():
    from claimsense_door.cognito import token_for
    door = json.loads((Path.home() / ".claimsense" / "deploy.json").read_text())["door_url"]
    h = {"Authorization": f"Bearer {token_for('alice')}"}
    ok = True
    for path in ROUTES:
        try:
            code = httpx.get(door + path, headers=h, timeout=30).status_code
        except httpx.HTTPError as e:
            code = type(e).__name__
        ok &= code == 200
        print(f"  {'PASS' if code == 200 else 'FAIL'}  GET {path:36} -> {code}")
    # the agents' path (RCA-2): trade alice's token for the 5-minute delegated token and use it on /mcp
    try:
        obo = httpx.post(f"{door}/oauth/token", timeout=30, json={
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange", "subject_token": h["Authorization"][7:],
            "actor": "agent:claimsense-pipeline"}).json().get("access_token", "")
        r = httpx.post(f"{door}/mcp", timeout=30, headers={"Authorization": f"Bearer {obo}",
                                                           "MCP-Protocol-Version": "2025-06-18"},
                       json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                             "params": {"name": "get_claim", "arguments": {"claim_id": "CLM-2024-1800"}}})
        good = r.status_code == 200 and "CLM-2024-1800" in r.text and '"isError": true' not in r.text
        code = r.status_code
    except (httpx.HTTPError, ValueError) as e:
        good, code = False, type(e).__name__
    ok &= good
    print(f"  {'PASS' if good else 'FAIL'}  POST /mcp get_claim (delegated token)    -> {code}")
    print(f"door smoke: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
