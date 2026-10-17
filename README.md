# Oil Change Predictor — Geo-Expert LLC

AI Academy Asia · AI Engineer capstone project.

**Live demo:** not deployed yet (task 6.3). Local demo: [`docs/demo_runbook.md`](docs/demo_runbook.md).

## What it does

Geo-Expert LLC runs a mobile oil change service for trucks in Mongolia. This internal web app
(opened in a phone browser) helps the oil changer and the office:

1. **Customer database.** Photograph a truck → the plate is detected (YOLO) and read (custom
   character CNN) → known trucks get the form pre-filled from their last service, new trucks
   are entered once. Look up any truck by plate, phone or fleet number: history, segment
   (new / returning / loyal / at risk) and the next predicted oil change (ok / due soon / overdue).
2. **Prediction + reminder.** A Ridge model predicts the next oil change date. A Mongolian
   reminder message is generated for the driver; the manager sends it and marks it «Илгээсэн».

> **Data honesty:** the prediction model is trained on **synthetic data** generated from
> documented rules ([`docs/synthetic_rules.md`](docs/synthetic_rules.md)). No real personal
> data is stored in this repository (data, photos and models are git-ignored).

## Honest results

| Part | Result | Source |
|---|---|---|
| Next-change prediction | **ML ≈ fixed-interval baseline on synthetic data.** Test MAE: Ridge 11.9 days vs baseline B0 (median interval) 12.3; the gain (+0.42 days, 95% interval −0.21 to +1.01) includes 0. Reminder hit rate (1–14 days early): Ridge 37.6% vs B0 33.7%, also within noise. Expected: history features are weak in the synthetic data, and the generator was not tuned to make ML win (D-050). Value should grow with real dated history | [`docs/ml_results.md`](docs/ml_results.md), [`docs/ml_evaluation.md`](docs/ml_evaluation.md) |
| Plate detection | YOLO26n fine-tuned: mAP50 0.991 on 27 held-out test photos (20 trucks) | [`docs/cv_detection_results.md`](docs/cv_detection_results.md) |
| Plate reading | Custom character CNN 70.4% exact vs EasyOCR 33.3%. In the served app: 9 of 27 test photos auto-filled, all correct; 18 sent to manual confirmation; **0 wrong auto-fills** (confidence threshold 0.6) | [`docs/cv_ocr_results.md`](docs/cv_ocr_results.md) |

Full status, decisions (D-xxx) and risks: [`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md).

## Tech stack

Python 3.11 · pandas · scikit-learn · XGBoost · SHAP · Ultralytics YOLO · PyTorch (training) ·
ONNX Runtime (serving) · FastAPI · SQLAlchemy · PostgreSQL · Streamlit · Docker · GitHub Actions

## Folder map

```
src/
  api/        FastAPI service: routers/, db.py, models.py, schemas.py, prediction.py, reminders.py
  common/     shared by training AND the API: features.py (features), plates.py (plate normalization)
  data/       schema.sql + migrations/, synthetic generator, cleaning, seed_demo.py (demo database)
  ml/         baselines, train, evaluate, SHAP explain, export_serving (serving parameters)
  cv/         plate detector training/eval, OCR comparison, ONNX export, plate_reader.py (serving)
  ui/         Streamlit app: app.py, views/ (one file per screen), api_client.py, Dockerfile
configs/      generator.yaml, cleaning.yaml, ml.yaml (seeds and settings)
tests/        pytest (API, data, ML, CV, UI)
notebooks/    01_eda.ipynb (synthetic data)
docs/         PROJECT_STATE, api_contract, data dictionary, results, demo runbook, figures/
data/         raw/ interim/ processed/ synthetic/   (git-ignored)
models/       trained files + pretrained/ base weights (git-ignored)
Dockerfile, docker-compose.yml        API image; local db + api
requirements.txt                      full dev environment (training + API + tests)
requirements-api.txt / -ui.txt        what the API / UI images install
```

## How to run

Needs Python 3.11, Docker Desktop, and the model files in `models/` (git-ignored; made by the
training steps below). On macOS, XGBoost also needs `brew install libomp`.

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-ui.txt
```

### Backend (PostgreSQL + FastAPI)

```bash
docker compose up -d --build                  # db + api on http://localhost:8000
curl http://localhost:8000/health             # {"status":"ok","db":"ok"}
POSTGRES_PASSWORD=oil_dev_password .venv/bin/python -m src.data.seed_demo   # 40 synthetic trucks
```

Interactive API docs: http://localhost:8000/docs. Endpoints: [`docs/api_contract.md`](docs/api_contract.md).

Without Docker for the API (the database still runs in Docker):

```bash
docker compose up -d db
POSTGRES_PASSWORD=oil_dev_password .venv/bin/uvicorn src.api.main:app --port 8000
```

### Frontend (Streamlit)

Start it **from `src/ui/`** so the theme loads:

```bash
cd src/ui
API_URL=http://localhost:8000 UI_PASSWORD=demo-pass ../../.venv/bin/streamlit run app.py   # http://localhost:8501
```

Leave out `UI_PASSWORD` to skip the login locally. More: [`docs/ui_run.md`](docs/ui_run.md).

### Demo

Step-by-step demo path, re-seeding and fallbacks: [`docs/demo_runbook.md`](docs/demo_runbook.md).
Demo plates (`1001 УБА`, `1002 УБЕ`, `1003 УНА`): [`docs/demo_data.md`](docs/demo_data.md).

### Tests

```bash
.venv/bin/pytest -v
```

Tests that need the database run against `docker compose up -d db` and skip if it is not reachable. Real-browser UI
checks are opt-in: `UI_BROWSER=1 .venv/bin/pytest tests/test_ui_browser.py` (see `docs/ui_run.md`).
CI (GitHub Actions) runs on every push to `main`: a Postgres service (DB tests run, never skip), the UI
packages (UI tests run), migrations twice (second = no-op), `pytest`, and builds both Docker images.

### Production (one server, HTTPS)

`docker-compose.prod.yml` = db + api + ui + Caddy (HTTPS). Step by step: [`docs/deploy.md`](docs/deploy.md).

### Rebuild the models (optional)

```bash
.venv/bin/python -m src.data.generator          # synthetic records (configs/generator.yaml)
.venv/bin/python -m src.data.cleaning           # cleaned synthetic file
.venv/bin/python -m src.ml.train                # model comparison → models/next_change_model.joblib
.venv/bin/python -m src.ml.export_serving       # models/serving_params.json
.venv/bin/python -m src.cv.train_detector --model models/pretrained/yolo26n.pt   # needs the labelled photos
.venv/bin/python -m src.cv.export_onnx          # detector + char CNN → ONNX for the API
```

Each script's docstring lists its inputs and options.

## Privacy

Real customer records and truck photos live only in `data/raw/` on the project Mac and are
never committed (`.gitignore`, RISK-06). Demo data is synthetic: company names start with
"Демо", phones are `0000xxxx`.
