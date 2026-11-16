#!/usr/bin/env bash
# Prove a team member can clone and run ClaimSense in under five minutes (W15 "Scaffold the repo"/"Containerise").
# Clones the branch FRESH from GitHub into a temp dir, builds with NO layer cache and freshly pulled base images,
# brings the stack up until every service is healthy, then proves the wiring (evals/wiring_check.py).
# Runs as a separate compose project ("claimsense-fresh"), so it never touches your own stack's state volume.
#
# Usage: M2/scripts/fresh-clone-proof.sh [branch]        (default: main) - needs Docker running and ports free
set -euo pipefail
BRANCH="${1:-main}"
REPO="${REPO_URL:-https://github.com/cinnamon0590/FDE-ClaimSense-Capstone.git}"
PY="${PYTHON:-python3}"
EVIDENCE="$(cd "$(dirname "$0")/.." && pwd)/evidence"      # this repo's evidence folder, not the temp clone's
export COMPOSE_PROJECT_NAME=claimsense-fresh                # overrides the file's name: a separate project
for port in 8002 8003 8510; do
  if lsof -nP -iTCP:$port -sTCP:LISTEN >/dev/null 2>&1; then
    echo "port $port is in use: stop your local stack first (cd M2 && make down)"; exit 2; fi
done
TMP="$(mktemp -d)"
trap 'cd "$TMP/repo/M2" 2>/dev/null && docker compose down -v >/dev/null 2>&1; rm -rf "$TMP"' EXIT
git clone -q --depth 1 --branch "$BRANCH" "$REPO" "$TMP/repo"
cd "$TMP/repo/M2"
start=$(date +%s)
docker compose build --no-cache --pull --quiet
MOCK_BRAIN=1 docker compose up -d --wait
end=$(date +%s)
echo "fresh clone -> healthy stack in $((end - start)) s (no layer cache, base images pulled)"
EVIDENCE_DIR="$EVIDENCE" "$PY" evals/wiring_check.py "$((end - start))"
