# The ClaimSense orchestrator (four agents on the OpenAI Agents SDK). This is the image CI pushes to ECR.
# Build context: repo root.
FROM public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1 AS lambda-adapter
FROM python:3.12-slim
# Lambda Web Adapter: the SAME image also runs on AWS Lambda (deploy ladder, M2/cloud/lambda/). Inert elsewhere.
COPY --from=lambda-adapter /lambda-adapter /opt/extensions/lambda-adapter
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CLAIMSENSE_ROOT=/app PYTHONPATH=/app/M2:/app/M2/services \
    CLAIMSENSE_STATE=/state PORT=8003 AWS_LWA_READINESS_CHECK_PATH=/healthz
RUN pip install --no-cache-dir openai-agents==0.24.0 openai==3.46.0 pydantic==2.14.3 numpy==2.5.4 \
        fastapi==0.162.0 uvicorn==0.54.0 httpx==0.28.1 boto3==1.43.125 \
    && useradd --create-home --uid 10001 app && mkdir -p /state && chown app /state
WORKDIR /app
COPY M0/evals/score.py M0/evals/cases.json M0/evals/
COPY M1/2-architecture/reference_guardrails.py M1/2-architecture/
COPY M1/5-system-contracts/reference_boundary.py M1/5-system-contracts/
COPY M1/5-system-contracts/schemas M1/5-system-contracts/schemas
COPY M1/6-synthetic-data/fixtures M1/6-synthetic-data/fixtures
COPY M1/tools/jsonschema_lite.py M1/tools/
COPY M2/claimsense M2/claimsense
COPY M2/evals/replays M2/evals/replays
COPY M2/evals/cases-m2.json M2/evals/
COPY M2/services/orchestrator M2/services/orchestrator
USER app
EXPOSE 8003
HEALTHCHECK --interval=10s --timeout=3s --retries=6 CMD python -c "import urllib.request,sys;urllib.request.urlopen('http://localhost:8003/healthz')" || exit 1
CMD ["uvicorn", "orchestrator.app:app", "--host", "0.0.0.0", "--port", "8003"]
