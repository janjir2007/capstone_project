# Demo runbook (task 7.2a): local demo on the Mac

Full system on one Mac: Streamlit UI (:8501) → FastAPI (:8000) → PostgreSQL (Docker) +
Ridge prediction + plate reading (YOLO + char CNN, ONNX). All demo data is **synthetic**
([`demo_data.md`](demo_data.md)). UI details: [`ui_run.md`](ui_run.md).

Checked on 2026-10-13 (merge `32814da`): all steps below work in a 390 px phone viewport.

## 0. Before the demo (once, ~5 min)

```bash
cd ~/Downloads/Capstone/oil-change-predictor
git checkout main && git pull
ls models/plate_yolo/yolo26n.onnx models/plate_ocr/char_cnn.onnx \
   models/next_change_model.joblib models/serving_params.json   # all 4 must exist (git-ignored)
.venv/bin/python -m src.ml.export_serving                        # refresh serving_params.json
.venv/bin/pip install -r requirements-ui.txt                     # UI packages, same venv
```

Docker Desktop must be running.

## 1. Start (re-seed on the demo day: dates are relative to the seed day)

```bash
# terminal 1: backend + fresh demo data
docker compose down -v                  # WARNING: deletes the local dev DB (demo data only)
docker compose up -d --build
curl http://localhost:8000/health       # {"status":"ok","db":"ok"}
POSTGRES_PASSWORD=oil_dev_password .venv/bin/python -m src.data.seed_demo
#   expect: 40 trucks · due reminders: 7 · 1001 УБА ridge · 1002 УБЕ overdue · 1003 УНА b1

# terminal 2: UI (start FROM src/ui so the theme loads)
cd src/ui
API_URL=http://localhost:8000 UI_PASSWORD=demo-pass ../../.venv/bin/streamlit run app.py
#   Mac: http://localhost:8501 · phone on the same Wi-Fi: http://<mac-ip>:8501
#   Mac IP: ipconfig getifaddr en0
```

Browser at phone width: Chrome DevTools → device toolbar → 390 px (iPhone 12/13/14).

## 2. Demo path (about 5 min)

| # | Do | Expect |
|---|---|---|
| 1 | Open the UI, password `demo-pass` → «Нэвтрэх» | Home: «Өнөөдөр 5 машин сануулга хүлээж байна.», 3 numbers |
| 2 | «Хайх» → `1001 УБА` | Card: «Байнгын · 5 удаа», green «Хэвийн», ~26 days left, «Загварын таамаглал» (= Ridge), history timeline |
| 3 | Back → `1002 УБЕ` | Red «Хэтэрсэн», «4 хоног хоцорсон», «Загварын таамаглал» |
| 4 | Back → `1003уна` (any spacing/case) | «Удахгүй», «Маршрутын тооцоо (анхны үйлчилгээ)» = B1 fallback, first visit |
| 5 | Back → phone `0000 0009` | «утасны дугаараар · 2 машин»: 1002 УБЕ and 1001 УБА |
| 6 | Home → «Сануулга» | 5 today · 4 overdue · 2 at risk; 1002 УБЕ row with its Mongolian message (copy button) |
| 7 | «Илгээсэн» on one row | «Илгээсэн гэж тэмдэглэлээ», the row leaves the list |
| 8 | «Машинуудын тойм харах» | Segments: new 8 · returning 11 · loyal 17 · at risk 4 |
| 9 | Plate reading: «Хайх» → «Камераар хайх» → «Эсвэл зураг оруулах» → photo | «Дугаар уншигдлаа: …» → lookup, or a yellow «check the plate» message → type it |

Numbers in rows 1, 2, 3, 6 and 8 are from the 2026-10-13 seed. Seeded on another day they can
differ by one or two.

Step 7 changes the data. To run the demo again from the start, repeat the 3 commands in §1
(down -v, up, seed_demo).

## 3. Fallbacks

| Problem | Do this |
|---|---|
| Plate not read / yellow message | Normal: 2/3 of photos go to manual confirmation by design (D-065, "never fills a wrong plate"). Type the plate in the field and press «Хайх» |
| Camera does not open on the phone | Phone over `http://<mac-ip>` has no camera (browser needs HTTPS). Use «Эсвэл зураг оруулах» (gallery upload, HEIC works) or type the plate |
| Uploading a photo of a printed / on-screen «1001 УБА» | **Not detected** in our check (synthetic plate images → `no_plate`). Don't rely on it. Type `1001 УБА` instead |
| Card shows no prediction / reminders say model not loaded | Model files missing in `models/` → §0, then `docker compose up -d --build` |
| `curl /health` fails | `docker compose ps`, `docker compose logs api --tail 50`; Docker Desktop running? |
| `seed_demo` says `NOT seeded: … already has …` | DB not empty → `docker compose down -v && docker compose up -d`, then seed again |
| UI looks unstyled | Streamlit was not started from `src/ui/` → restart from there |
| Port 8501 busy | `lsof -i :8501`, stop the old Streamlit (Ctrl+C in its terminal) |

## 4. Stop

```bash
# terminal 2: Ctrl+C (UI)
docker compose down        # keeps the demo data
docker compose down -v     # also deletes it
```

## 5. Notes for the presenter

- The reminder text ends with the placeholder contact `Geo-Expert: 99000000`. The UI shows a
  yellow note about it. Set the real number before the demo: `GEO_EXPERT_PHONE=<number>` in
  `.env` (never committed), then `docker compose up -d`.
- **Privacy (RISK-06):** a test-split photo is a real truck. The read plate appears on screen.
  Show plate reading with a photo the company has approved for showing, or a truck on site.
- Optional automatic screen check (390 px, screenshots): see [`ui_run.md`](ui_run.md) §0
  (`UI_BROWSER=1 UI_BROWSER_PLATE="1001 УБА" pytest tests/test_ui_browser.py`).
