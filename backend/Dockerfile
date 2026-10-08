# --- build stage: compile deps that need gcc/libpq headers -----------------
FROM python:3.12-slim AS builder

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# --- runtime stage: slim image, no compilers, non-root user -----------------
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 appuser

WORKDIR /app
COPY --from=builder /root/.local /home/appuser/.local
COPY . .
RUN chmod +x entrypoint.sh && chown -R appuser:appuser /app /home/appuser/.local

USER appuser
ENV PATH=/home/appuser/.local/bin:$PATH

EXPOSE 8000
# Healthchecks are defined per-service in docker-compose.yml, not here — this
# image is shared by backend (HTTP), celery-worker, and celery-beat (neither
# of which listens on 8000), so a single Dockerfile-level check can't fit all three.

ENTRYPOINT ["./entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
