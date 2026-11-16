# Adjuster console (Streamlit). Build context: repo root.
# Multi-stage (W15 "Containerise"): builder venv -> slim runtime, non-root, own HEALTHCHECK.

FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv && /opt/venv/bin/pip install streamlit==1.67.0 httpx==0.28.1

FROM python:3.12-slim AS runtime
# OS security patches at build time; CI's Trivy gate blocks any HIGH/CRITICAL CVE that has a fix
RUN apt-get update && apt-get upgrade -y --no-install-recommends && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app
COPY --from=builder /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY M0/evals/cases.json M0/evals/
COPY M2/evals/cases-m2.json M2/evals/
COPY M1/6-synthetic-data/fixtures/clauses.json M1/6-synthetic-data/fixtures/
COPY M2/services/console/app.py console/app.py
USER app
EXPOSE 8501
# Streamlit's own liveness endpoint
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=6 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1
CMD ["streamlit", "run", "console/app.py", "--server.address=0.0.0.0", "--server.port=8501", "--browser.gatherUsageStats=false"]
