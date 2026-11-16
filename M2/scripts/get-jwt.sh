#!/usr/bin/env bash
# Print a ClaimSense ID token for a synthetic user (dev issuer = local stand-in for Cognito's hosted login; D-030).
# Usage: scripts/get-jwt.sh <user>      e.g.  TOKEN=$(scripts/get-jwt.sh carol)
#        curl -H "Authorization: Bearer $TOKEN" http://localhost:8003/claims/CLM-2024-1873/recommend -d '{}' ...
# M3: replace with the Cognito hosted-login/InitiateAuth flow; the boundary and orchestrator verify the same way.
set -euo pipefail
USER_ID="${1:?usage: get-jwt.sh <user>  (alice | bob | carol | eve | dave)}"
BOUNDARY="${BOUNDARY_URL:-http://localhost:8002}"
curl -sf -X POST "$BOUNDARY/dev/token" -H 'Content-Type: application/json' -d "{\"user_id\": \"$USER_ID\"}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])'
