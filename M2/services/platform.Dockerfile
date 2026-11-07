# Mock systems of record + the data boundary (same small image, different command). Build context: repo root.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CLAIMSENSE_ROOT=/app PYTHONPATH=/app/M2:/app/M2/services
RUN pip install --no-cache-dir fastapi==0.162.0 uvicorn==0.54.0 httpx==0.28.1 \
    && useradd --create-home --uid 10001 app && mkdir -p /state && chown app /state
WORKDIR /app
COPY M0/evals/score.py M0/evals/cases.json M0/evals/
COPY M1/2-architecture/reference_guardrails.py M1/2-architecture/
COPY M1/5-system-contracts/reference_boundary.py M1/5-system-contracts/
COPY M1/5-system-contracts/schemas M1/5-system-contracts/schemas
COPY M1/6-synthetic-data/fixtures M1/6-synthetic-data/fixtures
COPY M1/tools/jsonschema_lite.py M1/tools/
COPY M2/claimsense/__init__.py M2/claimsense/_m1.py M2/claimsense/boundary_client.py M2/claimsense/deterministic.py M2/claimsense/
COPY M2/services/mock_systems M2/services/mock_systems
COPY M2/services/boundary M2/services/boundary
USER app
