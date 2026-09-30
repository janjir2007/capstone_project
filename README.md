# Oil Change Predictor — Geo-Expert LLC

AI Academy Asia · AI Engineer capstone project.

**Live demo:** _not deployed yet (Phase 6)_

## What it does

Geo-Expert LLC runs a mobile oil change service for trucks in Mongolia.
This app helps the oil changer and the office:

1. **Customer database** — photograph a truck → the plate is detected and read →
   known trucks get the form pre-filled from their last service, new trucks are
   entered once. Look up any truck by plate or phone to see its history and
   next predicted oil change (OK / due soon / overdue).
2. **Prediction + reminder** — an ML model predicts the next oil change date from
   vehicle model, oil grade, route, odometer history and season, and must beat a
   fixed-interval baseline. A Mongolian reminder message is generated for the driver.

> **Data honesty:** the prediction model is trained on **synthetic data** generated
> from documented rules (`docs/synthetic_rules.md`). Real service records are used
> only for testing. No real personal data is stored in this repository.

## Tech stack

Python 3.11 · pandas · scikit-learn · XGBoost · SHAP · Ultralytics YOLO + OCR ·
FastAPI · PostgreSQL · React/Next.js · Docker · GitHub Actions · cloud host

## Repository structure

```
data/        raw/ interim/ processed/ synthetic/  (git-ignored)
src/common/  shared code used by training AND the API (features.py, plates.py)
src/data/    synthetic generator, cleaning, external API
src/ml/      training, evaluation, SHAP explanations
src/cv/      plate detection and recognition
src/api/     FastAPI service
frontend/    web app
notebooks/   numbered EDA and experiments
models/      trained artifacts (git-ignored)
tests/       pytest tests
docs/        project state, data dictionary, model card, slide figures
```

## How to run (current stage: skeleton only)

```bash
python3.11 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest -v
```

API, database, Docker and deployment instructions will be added in later phases.

## Project status

See [`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md).
