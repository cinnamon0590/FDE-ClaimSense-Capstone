# The ClaimSense governed door for AWS Lambda behind API Gateway (M3 D-1). Build context: repo root.
# Same code as the local boundary container, plus the AWS Lambda Web Adapter (the deploy ladder, as for M2's image):
#   records      the synthetic fixtures baked into the image (SYSTEMS_URL=local; no mock-systems service on AWS)
#   audit trail  the append-only DynamoDB table M1 provisioned (CLAIMSENSE_AUDIT_TABLE=claimsense-audit)
#   identity     the Cognito user pool M1 provisioned (COGNITO_JWKS_URL + issuer + app client id, set by deploy.sh)
#   state        /tmp (drafts, idempotency, OBO keys); the function runs with reserved concurrency 1 so one warm
#                instance holds it (documented limit; DynamoDB-backed state is the M4 hardening item)
# No secret is COPY'd, set in ENV/ARG, or baked in: tokens come from Cognito, keys are generated at runtime in /tmp.
FROM public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1 AS lambda-adapter

FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_DEFAULT_TIMEOUT=60 PIP_RETRIES=10
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install fastapi==0.162.0 uvicorn==0.54.0 httpx==0.28.1 PyJWT==2.15.1 cryptography==50.0.2 \
        numpy==2.5.4 boto3==1.43.125

FROM python:3.12-slim AS runtime
RUN apt-get update && apt-get upgrade -y --no-install-recommends && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app
COPY --from=lambda-adapter /lambda-adapter /opt/extensions/lambda-adapter
COPY --from=builder /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CLAIMSENSE_ROOT=/app \
    PYTHONPATH=/app/M2:/app/M2/services:/app/M3/door PORT=8080 AWS_LWA_READINESS_CHECK_PATH=/healthz \
    SYSTEMS_URL=local AUDIT_LOG=/tmp/state/audit.jsonl BOUNDARY_STATE=/tmp/state/boundary.db \
    CLAIMSENSE_STATE=/tmp/state CLAIMSENSE_SECRETS_DIR=/tmp/secrets CLAIMSENSE_STS_KEYS=/tmp/state/door-sts \
    CLAIMSENSE_DEV_ISSUER=0
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
COPY M2/services/boundary M2/services/boundary
COPY M3/door/claimsense_door M3/door/claimsense_door
USER app
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn boundary.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
