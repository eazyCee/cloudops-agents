FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    ADK_DISABLE_LOCAL_STORAGE=1

WORKDIR /workspace

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8080

# Serves the ADK Web UI + REST API directly on Cloud Run ($PORT)
CMD ["sh", "-c", "exec adk web --host 0.0.0.0 --port ${PORT:-8080} --no-reload ."]
