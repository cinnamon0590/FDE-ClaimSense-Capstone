# Adjuster console (Streamlit). Build context: repo root.
FROM python:3.12-slim
# OS security patches at build time; CI's Trivy gate blocks any HIGH/CRITICAL CVE that has a fix
RUN apt-get update && apt-get upgrade -y --no-install-recommends && rm -rf /var/lib/apt/lists/*
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir streamlit==1.67.0 httpx==0.28.1 && useradd --create-home --uid 10001 app
WORKDIR /app
COPY M0/evals/cases.json M0/evals/
COPY M2/evals/cases-m2.json M2/evals/
COPY M1/6-synthetic-data/fixtures/clauses.json M1/6-synthetic-data/fixtures/
COPY M2/services/console/app.py console/app.py
USER app
EXPOSE 8501
CMD ["streamlit", "run", "console/app.py", "--server.address=0.0.0.0", "--server.port=8501", "--browser.gatherUsageStats=false"]
