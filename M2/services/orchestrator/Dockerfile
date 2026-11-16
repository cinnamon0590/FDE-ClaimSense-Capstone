# The ClaimSense orchestrator (four agents on the OpenAI Agents SDK). This is the image CI pushes to ECR.
# Build context: repo root.
# Multi-stage (W15 "Containerise"):
#   lambda-adapter  the AWS Lambda Web Adapter binary (deploy ladder; inert outside Lambda)
#   builder         pinned dependencies into a virtualenv (pip, caches and build tooling stay here)
#   runtime         patched slim base + the venv + the app, non-root, own HEALTHCHECK
# The same image also speaks AgentCore Runtime's HTTP contract (GET /ping, POST /invocations; D-033).
FROM public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1 AS lambda-adapter

FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install openai-agents==0.24.0 openai==3.46.0 pydantic==2.14.3 numpy==2.5.4 \
        fastapi==0.162.0 uvicorn==0.54.0 httpx==0.28.1 boto3==1.43.125 PyJWT==2.15.1 cryptography==50.0.2

FROM python:3.12-slim AS runtime
# OS security patches at build time; CI's Trivy gate blocks any HIGH/CRITICAL CVE that has a fix
RUN apt-get update && apt-get upgrade -y --no-install-recommends && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app && mkdir -p /state && chown app /state
# Lambda Web Adapter: the SAME image also runs on AWS Lambda (deploy ladder, M2/cloud/lambda/). Inert elsewhere.
COPY --from=lambda-adapter /lambda-adapter /opt/extensions/lambda-adapter
COPY --from=builder /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CLAIMSENSE_ROOT=/app \
    PYTHONPATH=/app/M2:/app/M2/services CLAIMSENSE_STATE=/state PORT=8003 AWS_LWA_READINESS_CHECK_PATH=/healthz
WORKDIR /app
COPY M0/evals/score.py M0/evals/cases.json M0/evals/
COPY M1/2-architecture/reference_guardrails.py M1/2-architecture/
COPY M1/5-system-contracts/reference_boundary.py M1/5-system-contracts/
COPY M1/5-system-contracts/schemas M1/5-system-contracts/schemas
COPY M1/6-synthetic-data/fixtures M1/6-synthetic-data/fixtures
COPY M1/tools/jsonschema_lite.py M1/tools/
COPY M2/claimsense M2/claimsense
COPY M2/evals/replays M2/evals/replays
COPY M2/evals/cases-m2.json M2/evals/g1b-cache.json M2/evals/
COPY M2/services/orchestrator M2/services/orchestrator
USER app
EXPOSE 8003
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=6 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://localhost:'+os.environ.get('PORT','8003')+'/healthz')" || exit 1
# $PORT: 8003 locally; AgentCore Runtime expects 8080 (set PORT=8080 there); Lambda's adapter reads it too
CMD ["sh", "-c", "exec uvicorn orchestrator.app:app --host 0.0.0.0 --port ${PORT:-8003}"]
