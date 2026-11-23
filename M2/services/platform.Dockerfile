# Mock systems of record + the data boundary / MCP door + the mock SIU ticketing system (same small image,
# different command; M3 adds the door package and the ticketing service). Build context: repo root.
# Multi-stage (W15 "Containerise"): the builder installs pinned dependencies into a virtualenv; the runtime stage
# copies only that venv and the app, runs as a non-root user and carries its own HEALTHCHECK.

# ── builder: dependencies only (pip, build caches and wheels never reach the runtime image) ─────────────
FROM python:3.12-slim AS builder
# retries + timeout: a first build pulls many wheels in parallel; one slow download must not fail the build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_DEFAULT_TIMEOUT=60 PIP_RETRIES=10
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install fastapi==0.162.0 uvicorn==0.54.0 httpx==0.28.1 PyJWT==2.15.1 cryptography==50.0.2 \
        numpy==2.5.4

# ── runtime ────────────────────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime
# OS security patches at build time; CI's Trivy gate blocks any HIGH/CRITICAL CVE that has a fix
RUN apt-get update && apt-get upgrade -y --no-install-recommends && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app && mkdir -p /state /secrets && chown app /state /secrets \
    && chmod 700 /secrets
COPY --from=builder /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CLAIMSENSE_ROOT=/app \
    PYTHONPATH=/app/M2:/app/M2/services:/app/M3/door:/app/M3/services PORT=8001 CLAIMSENSE_SECRETS_DIR=/secrets
WORKDIR /app
COPY M0/evals/score.py M0/evals/cases.json M0/evals/
COPY M1/2-architecture/reference_guardrails.py M1/2-architecture/
COPY M1/5-system-contracts/reference_boundary.py M1/5-system-contracts/
COPY M1/5-system-contracts/schemas M1/5-system-contracts/schemas
COPY M1/6-synthetic-data/fixtures M1/6-synthetic-data/fixtures
COPY M1/tools/jsonschema_lite.py M1/tools/
COPY M2/claimsense/__init__.py M2/claimsense/_m1.py M2/claimsense/boundary_client.py M2/claimsense/deterministic.py \
     M2/claimsense/identity.py M2/claimsense/config.py M2/claimsense/audit_trail.py M2/claimsense/retrieval.py M2/claimsense/doc_store.py M2/claimsense/metrics.py \
     M2/claimsense/
COPY M2/services/mock_systems M2/services/mock_systems
COPY M2/services/boundary M2/services/boundary
COPY M3/door/claimsense_door M3/door/claimsense_door
COPY M3/services/ticketing M3/services/ticketing
USER app
# both services in this image answer /healthz on $PORT (compose sets 8001 for mock systems, 8002 for the boundary)
HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=12 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://localhost:'+os.environ['PORT']+'/healthz')" || exit 1
