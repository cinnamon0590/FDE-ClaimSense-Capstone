#!/usr/bin/env bash
# Prove "nothing leaves this machine" on the default path (D-034): run the stack on an internal Docker network
# with no route to the internet, show that egress really is impossible, then run all 40 eval cases from a client
# container INSIDE that sealed network. Writes M2/evidence/no-egress.txt. $0 (replay brain, no key).
#   cd M2 && scripts/no-egress-proof.sh
set -euo pipefail
cd "$(dirname "$0")/.."
export COMPOSE_PROJECT_NAME=claimsense-sealed
OUT=evidence/no-egress.txt
trap 'docker compose -f docker-compose.yml -f sealed.compose.yml down -v >/dev/null 2>&1' EXIT
docker compose -f docker-compose.yml -f sealed.compose.yml build -q
MOCK_BRAIN=1 OPENAI_API_KEY= docker compose -f docker-compose.yml -f sealed.compose.yml up -d --wait
NET="${COMPOSE_PROJECT_NAME}_default"
{
  echo "ClaimSense no-egress proof · $(date -u '+%Y-%m-%d %H:%M:%S') UTC"
  echo "network ${NET}: internal=$(docker network inspect -f '{{.Internal}}' "$NET") (Docker gives it no route off this machine)"
  echo "MOCK_BRAIN=1, no OPENAI_API_KEY, no AWS credentials in any container"
  echo
  echo "Egress attempts from inside the orchestrator container (each must FAIL):"
  for url in https://api.openai.com https://bedrock-runtime.us-east-1.amazonaws.com https://pypi.org; do
    if docker compose -f docker-compose.yml -f sealed.compose.yml exec -T orchestrator \
         python -c "import urllib.request; urllib.request.urlopen('$url', timeout=5)" >/dev/null 2>&1; then
      echo "  FAIL  reached $url"; LEAK=1
    else
      echo "  PASS  cannot reach $url"
    fi
  done
  echo
  echo "All 40 eval cases from a client INSIDE the sealed network (same orchestrator image, scripts mounted read-only):"
  docker run --rm --network "$NET" --entrypoint python \
    -e ORCHESTRATOR_URL=http://orchestrator:8003 -e BOUNDARY_URL=http://boundary:8002 \
    -v "$PWD/evals/container_eval.py:/app/M2/evals/container_eval.py:ro" \
    -v "$PWD/evals/_auth.py:/app/M2/evals/_auth.py:ro" \
    claimsense/orchestrator:local /app/M2/evals/container_eval.py | sed 's/^/  /'
} | tee "$OUT"
grep -q "CONTAINER EVAL: PASS" "$OUT" && ! grep -q "  FAIL  reached" "$OUT" && echo && echo "NO-EGRESS PROOF: PASS" | tee -a "$OUT"
