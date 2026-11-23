"""One claim through the real orchestrator code against the DEPLOYED door, as a signed-in Cognito user (used by the
incident drill to measure user impact during the incident and to verify recovery after it).

    python M4/drill/claim_probe.py alice CLM-2024-1800        # prints one JSON line: outcome, net payable, ...

Same settings as the ECS task (D-049): Cognito ID token -> orchestrator -> 5-minute delegated token -> the door's
/mcp. Fresh state directory per run, so nothing is resumed from an earlier checkpoint. Live models (~$0.02).
"""
import importlib.util
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONF = Path.home() / ".claimsense"


def main(user, claim_id):
    cog = json.loads((CONF / "cognito.json").read_text())
    door = json.loads((CONF / "deploy.json").read_text())["door_url"]
    iss = f"https://cognito-idp.{cog.get('region', 'us-east-1')}.amazonaws.com/{cog['pool_id']}"
    state = tempfile.mkdtemp(prefix="claimsense-probe-")
    os.environ.update({"COGNITO_JWKS_URL": f"{iss}/.well-known/jwks.json", "CLAIMSENSE_JWT_ISSUER": iss,
                       "CLAIMSENSE_JWT_AUDIENCE": cog["client_id"], "BOUNDARY_URL": door,
                       "CLAIMSENSE_MCP_URL": f"{door}/mcp", "MOCK_BRAIN": "0", "CLAIMSENSE_STATE": state,
                       "AUDIT_LOG": f"{state}/audit.jsonl", "CLAIMSENSE_METRICS": "0"})
    env_file = ROOT / "M2" / ".env"                     # the key is read, never printed
    if "OPENAI_API_KEY" not in os.environ and env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("OPENAI_API_KEY="):
                os.environ["OPENAI_API_KEY"] = line.split("=", 1)[1].strip()
    sys.path[:0] = [str(ROOT / "M2" / "services"), str(ROOT / "M2"), str(ROOT / "M3" / "door")]
    os.chdir(ROOT / "M2")
    from claimsense_door.cognito import token_for
    spec = importlib.util.spec_from_file_location("orch_probe", ROOT / "M2/services/orchestrator/app.py")
    orch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(orch)
    from fastapi.testclient import TestClient
    c = TestClient(orch.app, raise_server_exceptions=False)
    last = None
    with c.stream("POST", f"/claims/{claim_id}/recommend/stream", json={"run_id": f"{claim_id}:{uuid.uuid4().hex[:12]}"},
                  headers={"Authorization": f"Bearer {token_for(user)}"}) as r:
        if r.status_code != 200:
            r.read()
            print(json.dumps({"user": user, "claim": claim_id, "http": r.status_code, "outcome": None}))
            return
        for line in r.iter_lines():
            ev = json.loads(line)
            if ev.get("kind") in ("result", "error"):
                last = ev
    res = (last or {}).get("result") or {}
    resp = res.get("response") or {}
    err = resp.get("error") or {}
    print(json.dumps({"user": user, "claim": claim_id, "outcome": resp.get("outcome"),
                      "net_payable": (resp.get("computed") or {}).get("net_payable"),
                      "decided_by": res.get("decided_by"), "route_to": resp.get("route_to"),
                      "error": err.get("code") or (last or {}).get("error")}))


if __name__ == "__main__":
    main(*(sys.argv[1:3] or ["alice", "CLM-2024-1800"]))
