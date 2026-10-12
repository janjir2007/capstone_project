# Running the UI (Streamlit frontend)

- **Owner:** Frontend Engineer (written on the iMac, branch `ui`) · **Version:** 1.1 (2026-10-12, task T5)
- **Permanent machine = the Mac** (Docker, cloud, demo, final version). Everything needed is in git;
  §0 is the complete Mac setup. Nothing is required from the iMac.
- Screens and behaviour: [`ui_screens.md`](ui_screens.md). API: [`api_contract.md`](api_contract.md).

The UI only talks to the API over HTTP (`API_URL`). It never touches the database or model files.

## 0. On the Mac (permanent machine): complete setup, step by step

Assumes the Mac already runs the backend (Python 3.11 venv with `requirements.txt`, Docker Desktop,
`./models` built, as in the backend handoffs).

```bash
cd <repo>                                   # the Mac's clone of the capstone repo
git fetch --prune
git checkout ui && git pull --ff-only       # demo-known-good: 21124d2 · latest: tip of origin/ui

# 1) UI packages into the SAME venv as the backend. Compatible: on the iMac requirements.txt +
#    requirements-ui.txt live in one venv and the full suite passes (592 passed, 2 skipped).
.venv/bin/pip install -r requirements-ui.txt

# 2) backend up
docker compose up -d --build
curl http://localhost:8000/health           # {"status":"ok","db":"ok"}

# 3) UI tests (API mocked; no backend needed)
.venv/bin/pytest -q tests/test_ui_*.py

# 4) run the UI (from src/ui/ so the theme loads)
cd src/ui && ../../.venv/bin/streamlit run app.py      # http://localhost:8501
```

Optional, to re-check phone width and regenerate the slide screenshots (PNGs are git-ignored):

```bash
.venv/bin/pip install playwright==1.55.0    # dev tool only, not in requirements-ui.txt
.venv/bin/playwright install chromium       # once: Playwright's own Chromium (~82 MB download)
UI_BROWSER=1 UI_BROWSER_PLATE="1001 УБА" UI_SCREENSHOT_DIR=~/Desktop/ui_screens \
  .venv/bin/pytest -v tests/test_ui_browser.py
# use the installed Google Chrome instead: add UI_BROWSER_CHANNEL=chrome (then no install step)
```

Without `UI_BROWSER=1`, or without Playwright installed, this file **skips** (it never fails
collection, so CI and the normal `pytest` are unaffected).

No `.env` entries are needed for the UI in local dev (all defaults are in git). In production only
`UI_PASSWORD` is secret (server `.env`, never committed); `API_URL` is set by compose (§3).

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `API_URL` | `http://localhost:8000` locally · `http://api:8000` in the Docker image | FastAPI base URL, no trailing slash needed |
| `UI_PASSWORD` | unset | Company password (D-061). **Unset or empty → no login** (local dev only). Never commit it; pass at run time |

Theme and limits (primary color, background, 15 MB upload, minimal toolbar) live in
`src/ui/.streamlit/config.toml`. Streamlit reads that file from the **current folder**, so the
app must be **started from `src/ui/`**. Started elsewhere, it still works but without the theme.

## 1. Local (development)

```bash
# once: Python 3.11 venv in the repo root
python3.11 -m venv .venv
.venv/bin/pip install -r requirements-ui.txt

# backend (db + api on :8000); see README for model files / sample data
docker compose up -d --build
curl http://localhost:8000/health            # {"status":"ok","db":"ok"}

# UI: start FROM src/ui/
cd src/ui
../../.venv/bin/streamlit run app.py         # http://localhost:8501
# with login:   UI_PASSWORD=demo-pass ../../.venv/bin/streamlit run app.py
# other API:    API_URL=http://192.168.1.20:8000 ../../.venv/bin/streamlit run app.py
```

Phone on the same Wi-Fi: `http://<mac-ip>:8501`. The camera in the phone browser needs **HTTPS**
(or localhost). Over plain http on the LAN, use «Эсвэл зураг оруулах» (upload, which also works
with iPhone HEIC) or type the plate. HTTPS comes with the deploy (D-061, task 6.3).

Tests (from the repo root): `.venv/bin/pytest -v tests/test_ui_*.py`. All API calls are mocked.
`tests/test_ui_browser.py` is opt-in (real browser, see §0) and skips by default.

If Python 3.11 is missing (new machine): `brew install python@3.11`. XGBoost tests in the full
suite also need `brew install libomp` on macOS (backend requirement, not the UI's).

## 2. Docker

Build from the **repo root** (the context allow-list is `src/ui/Dockerfile.dockerignore`, so only
`requirements-ui.txt`, `src/__init__.py` and `src/ui/` enter the image):

```bash
docker build -f src/ui/Dockerfile -t ocp-ui .
```

Run against the local compose API (same Docker network, API reached by service name `api`):

```bash
# the compose network name depends on the repo FOLDER name (iMac: capstone_project_default),
# so read it from the running API container instead of typing it:
NET=$(docker inspect ocp-api --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}')
docker run --rm --name ocp-ui -p 8501:8501 --network "$NET" \
  -e UI_PASSWORD=demo-pass \
  ocp-ui
# API_URL defaults to http://api:8000 in the image; override with -e API_URL=...
docker inspect ocp-ui --format '{{.State.Health.Status}}'   # "healthy" after ~15 s
```

Or against an API on the host: `-e API_URL=http://host.docker.internal:8000` (Docker Desktop).

Image facts (measured 2026-10-12 on the iMac, Docker Desktop; re-measure on the Mac/server in 6.3):

| | |
|---|---|
| Base | `python:3.11-slim`, only `requirements-ui.txt` |
| User | `appuser` (uid 10001), code read-only (root-owned) |
| Workdir | `/app/src/ui` (theme loads; verified background `#F4F5F7` in the container) |
| Port | 8501 |
| Healthcheck | `GET /_stcore/health` every 15 s |
| Size | **180 MB compressed** (download) · **~605 MB unpacked** (Docker Desktop shows 818 MB = both). ~260 MB of it are Streamlit's required deps (pyarrow, pandas, numpy) |
| RAM | **49 MiB** idle, no browser · **~62 MiB** after a full session and with 4 sessions open |

## 3. Compose service (for backend task 6.1, not added by the UI)

The UI does not edit compose files. Values the prod compose needs:

```yaml
  ui:
    build:
      context: .
      dockerfile: src/ui/Dockerfile
    environment:
      API_URL: http://api:8000          # internal network; the API need not be public (D-061)
      UI_PASSWORD: ${UI_PASSWORD}       # from .env on the server, never committed
    expose:
      - "8501"                          # reverse proxy (Caddy, HTTPS) -> ui:8501
    depends_on:
      api:
        condition: service_healthy
    restart: unless-stopped
```

The reverse proxy must pass **WebSockets** (Streamlit uses `/_stcore/stream`). Caddy's
`reverse_proxy ui:8501` does this by default. Upload limit: Streamlit 15 MB (config.toml) =
API 15 MB.
