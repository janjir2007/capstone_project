# UI image (task T5): Streamlit frontend. Build from the REPO ROOT:
#   docker build -f src/ui/Dockerfile -t ocp-ui .
#   docker run --rm -p 8501:8501 -e API_URL=http://host.docker.internal:8000 ocp-ui
# The context allow-list is src/ui/Dockerfile.dockerignore (only UI code goes in).
# Python 3.11 = project version (D-020). "slim" = small Debian base.
FROM python:3.11-slim

# No .pyc files; logs go straight to `docker logs`; pip keeps no cache in the image.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first: Docker caches this layer, so code edits don't reinstall them.
# Only the UI's own list (no ML / CV / API packages).
COPY requirements-ui.txt .
RUN pip install -r requirements-ui.txt

# Code: src/__init__.py (package marker for `from src.ui import ...`) + src/ui/.
COPY src/__init__.py ./src/__init__.py
COPY src/ui/ ./src/ui/

# Run as a normal user, not root. Code stays root-owned = read-only for the app.
RUN useradd --create-home --uid 10001 appuser
USER appuser

# Start from src/ui/ so Streamlit finds .streamlit/config.toml (theme, 15 MB upload limit).
WORKDIR /app/src/ui

# API base URL: override at run time. "api" = the API service name in a compose network.
# UI_PASSWORD is NOT set here (a secret): pass it at run time (-e / compose env / .env).
ENV API_URL=http://api:8000

EXPOSE 8501

# Docker marks the container "unhealthy" if Streamlit's health endpoint stops returning 200.
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=4)"

# exec form: streamlit is PID 1 and receives the stop signal (clean shutdown).
# 0.0.0.0 = reachable from outside the container (a reverse proxy adds HTTPS, D-061).
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
