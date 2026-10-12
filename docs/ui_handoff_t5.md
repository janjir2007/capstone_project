# HANDOFF REPORT — T5 (UI quality + Dockerfile)

```
HANDOFF REPORT
TASK ID: T5 (5.x quality + Dockerfile)
STATUS: DONE (commit + push to ui pending Ari's OK; PR ui → main NOT opened, boss decides)
DEMO-KNOWN-GOOD: 21124d2 (task 5.4). T5 changes are on top of it in small commits.
SUMMARY:
  1. src/ui/Dockerfile: python:3.11-slim, only requirements-ui.txt, non-root (appuser, uid
     10001, code read-only), WORKDIR /app/src/ui (theme loads), API_URL env (default
     http://api:8000), UI_PASSWORD only at run time, port 8501, HEALTHCHECK on
     /_stcore/health. Context allow-list src/ui/Dockerfile.dockerignore → image holds only
     requirements-ui.txt, src/__init__.py, src/ui/ (verified with find inside the image).
     Built and run with `docker run` against the local compose API.
  2. HEIC: uploaders accept jpg/jpeg/png/heic/heif from ONE list (logic.UPLOAD_TYPES),
     including upper-case IMG_0001.HEIC. Content type is guessed from the extension when the
     browser sends none (image/heic). The API decodes bytes anyway (pillow-heif).
  3. name_mn (D-071): shown when present; null, "" and spaces-only fall back to name.
     Tested in logic and on the real form pills (missing / null / "" / present).
  4. docs/ui_run.md: local run from src/ui, env vars, Docker build/run, measured image facts,
     compose service values for 6.1.
  5. Quality: no old lookup-screen leftovers (grep); removed dead api_client.health() (never
     called by the UI since 5.1); phone search with no match now says «Энэ утасны дугаартай
     үйлчилгээ бүртгэгдээгүй байна» (was "this truck is not registered") and offers no
     new-vehicle button; Mongolian audit of all user-visible strings.
FILES: src/ui/Dockerfile (new), src/ui/Dockerfile.dockerignore (new), src/ui/logic.py,
  src/ui/common.py, src/ui/api_client.py, src/ui/views/record.py, src/ui/views/search.py,
  tests/test_ui_{logic,app,api_client}.py, docs/ui_run.md (new),
  docs/ui_screens.md, docs/ui_handoff_t5.md
HOW TO RUN: docs/ui_run.md. Short:
  local:  cd src/ui && ../../.venv/bin/streamlit run app.py
  docker: docker build -f src/ui/Dockerfile -t ocp-ui .
          docker run --rm -p 8501:8501 --network capstone_project_default -e UI_PASSWORD=… ocp-ui
DECISIONS MADE:
  - Build context = repo root + per-Dockerfile allow-list (BuildKit "<Dockerfile>.dockerignore"),
    so the root .dockerignore (backend-owned) is not touched. With an old non-BuildKit builder
    the root .dockerignore applies; it also excludes data/models/.env.
  - pytest stays in requirements-ui.txt (the brief says "only requirements-ui.txt"); it adds
    3.6 MB to the image (measured: pytest + pluggy + iniconfig). It can be split into a runtime list later if wanted.
  - AT_RISK_GRACE_DAYS: single named constant in src/ui/logic.py with the comment "mirrors
    D-007 / backend; remove when API adds segment field" (done before the 5.4 commit).
METRICS / EVIDENCE:
  - pytest (full repo): 592 passed, 2 skipped (backend ONNX, expected on the iMac), exit 0.
    UI tests: 94 (+3: iPhone HEIC upload → "file" field + image/heic + confirm step;
    content-type guess; phone no-match state; name_mn cases extended).
  - Image (D-067 server sizing): 180 MB compressed / ~605 MB unpacked (Docker Desktop shows
    818 MB = both). Biggest: pyarrow 143 MB, pandas 79 MB, numpy 71 MB (Streamlit's own deps).
  - RAM (docker stats): 49 MiB idle, no browser · 61 MiB after one full browser session
    (login → search → card → form → dashboard) · 62 MiB with 4 sessions open · CPU idle < 1%.
    → API ~190–310 MB (D-067) + UI ~60–100 MB + Postgres: 2 GB server still looks enough.
  - In the container: health=healthy, user=appuser, theme background rgb(244,245,247) =
    #F4F5F7, API reached as http://api:8000 (compose network) and via
    http://host.docker.internal:8000. Browser upload of IMG_0001.HEIC accepted by the
    container's uploader and sent to the API (503 → manual-entry message, as expected without
    recognizer files on the iMac). Login gate works in the container (UI_PASSWORD).
ASSUMPTIONS NEEDING PM/ARI CONFIRMATION:
  1. Contract v0.6 is NOT in origin/main yet: docs/api_contract.md there is still v0.5
     (checked with git show origin/main:docs/api_contract.md, HEAD 1738dbb). name_mn was built
     from D-071 in PROJECT_STATE v2.10 ("nullable; UI shows name when name_mn empty").
     Please confirm the field name/shape when v0.6 lands.
  2. D-068 calls the at-risk group «Алдагдах эрсдэлтэй»; the T4 brief said «Эрсдэлтэй» (used).
     Pick one.
  3. Demo path in D-071 (1001 УБА, 1002 УБЕ, 1003 УНА, phone 0000 0009) needs the 4.5 seed,
     which is also not on origin/main yet. The UI does not depend on it, but tomorrow's demo
     DB does.
PROBLEMS / RISKS:
  - Phone camera over plain http on the LAN is blocked by browsers (needs HTTPS or localhost).
    For a LAN demo use «Эсвэл зураг оруулах» or type the plate. Real fix = HTTPS (6.3).
  - Unknown future 422 messages from the API are shown in English (known ones translated).
  - The manager warning names the env var GEO_EXPERT_PHONE (deliberate setup hint).
  - CI still installs only requirements.txt → UI screen tests (AppTest) are skipped in CI
    (logic + client tests run). Fix = add `pip install -r requirements-ui.txt` to ci.yml (PM/Mac).
CONTRACT CHANGES: none.
NEEDED FROM BACKEND (6.1, prod compose): ui service = build context ".", dockerfile
  src/ui/Dockerfile; env API_URL=http://api:8000, UI_PASSWORD=${UI_PASSWORD}; expose 8501
  (proxy only); depends_on api healthy; restart unless-stopped. Caddy reverse_proxy ui:8501
  (must pass WebSockets, Caddy does by default). Full snippet in docs/ui_run.md §3.
SLIDE MATERIAL: "UI container: 180 MB download, ~60 MB RAM, non-root, no data inside";
  architecture slide: phone browser → Caddy (HTTPS) → Streamlit UI → FastAPI → PostgreSQL.
NEXT STEP: Ari OK → push T5 commits to ui. Then the boss decides on the PR ui → main (UI
  includes merge 93375fe of main@a85293c; main has since moved to 1738dbb, docs only).
```
