#!/usr/bin/env bash
# Invoke the deployed orchestrator with an IAM-signed call (no public URL needed).
# Usage: ./invoke.sh CLM-2024-1800 [user]
set -euo pipefail
CLAIM="${1:?claim id}"; USER_ID="${2:-alice}"; export AWS_DEFAULT_REGION="${AWS_REGION:-us-east-1}"
EVENT=$(python3 -c "
import json,sys
print(json.dumps({'version':'2.0','routeKey':'\$default','rawPath':'/claims/$CLAIM/recommend','rawQueryString':'',
 'headers':{'content-type':'application/json'},'body':json.dumps({'user_id':'$USER_ID'}),'isBase64Encoded':False,
 'requestContext':{'http':{'method':'POST','path':'/claims/$CLAIM/recommend','sourceIp':'127.0.0.1'}}}))")
OUT=$(mktemp)
aws lambda invoke --function-name claimsense-orchestrator --cli-binary-format raw-in-base64-out \
  --payload "$EVENT" "$OUT" >/dev/null
python3 - "$OUT" <<'PY'
import json, sys
r = json.load(open(sys.argv[1])); body = json.loads(r.get("body", "{}"))
card = body.get("response", {})
print(json.dumps({"claim_id": body.get("claim_id"), "decided_by": body.get("decided_by"), "outcome": card.get("outcome"),
                  "route_to": card.get("route_to"), "verdict_source": card.get("verdict_source"),
                  "guardrails_fired": card.get("guardrails_fired"), "latency_s": body.get("latency_s"),
                  "cost_usd": body.get("cost_usd"), "brain": body.get("brain")}, indent=1))
PY
