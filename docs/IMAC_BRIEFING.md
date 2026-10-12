# iMac Briefing — Oil Change Predictor (Capstone)

Read this first, then `docs/PROJECT_STATE.md` (source of truth) and `docs/api_contract.md`.
You are the **Frontend Engineer** on the iMac. Another Claude account on Ari's other Mac does
ML/backend. A **PM chat** (separate) writes task briefs and reviews your HANDOFF REPORTs.
Ari relays messages. You never see the PM chat — this file + the repo docs are your context.

## The project (1 paragraph)
Geo-Expert LLC (Mongolia) runs a mobile oil change service for trucks. We build an app:
(1) **Customer database** — the oil changer photographs the truck, the plate is read
automatically (YOLO detector + OCR, manual fallback), the form is pre-filled from the last
service; he enters odometer + **destination** (where the truck goes next) and saves.
Lookup by plate / phone / fleet number shows a **vehicle card** (history, usual liters,
segment New / Returning / Loyal / At risk). (2) **Prediction + reminder** — predict when the
truck needs its next oil change and send a Mongolian reminder just before it is due
(purpose = customer retention, D-036). Deadline: **2026-10-20** (defense, 13 slides, live demo).

## Status (Oct 10)
- Done: repo + CI, DB schema + destinations (PostgreSQL), FastAPI data endpoints, plate
  detector (mAP50 0.991), plate normalization, synthetic data generator + cleaning, ML
  baselines + 3 models (honest result: ML ≈ fixed-interval baseline on synthetic data).
- In progress (other Mac): ML evaluation + SHAP (2.4), real-date calibration (1.4b).
- Not built yet: prediction + plate-recognition endpoints (4.3), reminders (4.4) → until then
  the card's `prediction` is `null`. **Build the UI so it works with null and shows it later.**

## Your job: Streamlit frontend (D-022), tasks 5.1–5.4
Mobile-friendly Streamlit app that calls FastAPI over HTTP. UI text in **Mongolian**.
Screens: Recording mode (5.2), Lookup + vehicle card (5.3), Dashboard (5.4).
Talk to the backend ONLY through the endpoints in `docs/api_contract.md` — never import
backend code or query the DB directly.

## Rules
1. **Folders you own:** `src/ui/`, `tests/test_ui*`, `docs/ui_*`, `requirements-ui.txt`.
   Do not edit other files. If you need a backend change, STOP and write it in the handoff.
2. **Never edit** `docs/PROJECT_STATE.md`, `CLAUDE.md`, `requirements.txt` (PM / other Mac own them).
3. **Branch:** work on branch `ui` only. Never push to `main`. Merge happens via GitHub pull
   request after the PM accepts a task.
4. **Privacy:** no real photos, plates, phones or names in git. Use fake demo data only.
5. Don't guess decisions. If PROJECT_STATE doesn't say it, ask in the handoff.
6. Finish every task with a HANDOFF REPORT: TASK ID, STATUS, SUMMARY, FILES, HOW TO RUN,
   DECISIONS MADE, METRICS/EVIDENCE, ASSUMPTIONS NEEDING PM/ARI CONFIRMATION,
   PROBLEMS/RISKS, CONTRACT CHANGES, SLIDE MATERIAL, NEXT STEP.

## Run the backend locally (so the UI has something to call)
```
docker compose up -d --build        # db + api
curl http://localhost:8000/health   # {"status":"ok","db":"ok"}
```
API docs: http://localhost:8000/docs . The dev DB has a few fake sample records.
