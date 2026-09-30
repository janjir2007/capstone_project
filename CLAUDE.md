# CLAUDE.md — Oil Change Predictor (Geo-Expert LLC capstone)

Claude Code reads this file automatically at the start of every session.

## Read first
- `docs/PROJECT_STATE.md` is the single source of truth: scope, decisions (D-xxx),
  task list, API contract, repo structure. Read it before any task.
- Do not change a decision marked APPROVED/Final. If a task seems to need it,
  stop and say so.

## Project in one paragraph
Mobile-first web app for Geo-Expert's truck oil change service in Mongolia.
(1) Customer database: photo → YOLO plate detection + Cyrillic recognition →
pre-filled service form; lookup by plate/phone. (2) ML predicts next oil change
date (must beat a fixed-interval baseline), trained on SYNTHETIC data, tested on
real records; Mongolian reminder message. Stack: Python 3.11, pandas,
scikit-learn, XGBoost, SHAP, Ultralytics YOLO, FastAPI, PostgreSQL (local Docker /
Supabase), Next.js, Docker, GitHub Actions.

## How to work
- Work only on the TASK BRIEF Ari gives you. Nothing outside it.
- Explain the code: after each file, explain what it does, key lines, and why.
  Ari is learning.
- Never invent facts, library features, numbers, or results. If unsure, say
  "needs verification" and show how to check.
- Python 3.11, type hints, docstrings, small functions, fixed random seeds.
- Add packages to `requirements.txt` with exact versions (==), only if your
  code imports them.
- Write pytest tests for core functions. Run `pytest -v` before finishing.
- Feature engineering lives ONLY in `src/common/features.py` (training and API
  share it). Plate normalization lives ONLY in `src/common/plates.py`.

## Privacy (RISK-06)
- `data/raw/` holds REAL customer records and photos (driver names, phones,
  plates). Do not open or print these files. Develop and test on synthetic or
  masked data; Ari runs scripts on real data himself and shares only summaries.
- Never commit data, models, photos, CSV/Excel files, or `.env`.

## Finish every task with this report (Ari pastes it to the PM chat)
```
HANDOFF REPORT
TASK ID:
STATUS: DONE / PARTIAL / BLOCKED
SUMMARY:
FILES:
HOW TO RUN:
DECISIONS MADE:
METRICS / EVIDENCE:
ASSUMPTIONS NEEDING PM/ARI CONFIRMATION:
PROBLEMS / RISKS:
CONTRACT CHANGES:
SLIDE MATERIAL:
NEXT STEP:
```
