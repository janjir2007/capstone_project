# API image (task 4.1). Build + run via docker-compose.yml (service "api").
# Python 3.11 = project version (D-020). "slim" = small Debian base.
FROM python:3.11-slim

# No .pyc files in the image; logs go straight to `docker compose logs`.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first: Docker caches this layer, so code edits don't reinstall them.
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

# Only the source code (.dockerignore keeps data, models, .env out of the context).
COPY src/ ./src/

# Run as a normal user, not root.
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

# Docker marks the container "unhealthy" if /health stops returning 200.
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=4)"

# PORT lets a cloud host choose the port (task 6.3); 8000 locally.
# exec: uvicorn replaces the shell, so it receives the stop signal and shuts down cleanly.
CMD ["sh", "-c", "exec uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
