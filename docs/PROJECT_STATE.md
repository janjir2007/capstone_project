# PROJECT_STATE — Capstone "Oil Change Predictor" (Geo-Expert LLC)

- **Version:** 0.5
- **Last updated:** 2026-09-30
- **Deadline (defense day):** ❓ NOT SET — plan below assumes 4 weeks (defense ≈ 2026-10-28). Replace when known.
- **Current phase:** P1 — Data foundation
- **Overall health:** 🟡 Yellow — scope is clear, but 3 requirement gaps and 2 data-collection dependencies are open.

---

## 1. Agreed scope (frozen — changes need Ari's approval)

**Feature 1 — Customer database**
- Recording mode: photo → plate detection + Cyrillic recognition → oil changer confirms plate.
  - Existing plate → form pre-filled from last service (oil grade, liters, route, driver, phone) → check, edit, save.
  - New plate → fill everything once.
  - Always fresh: odometer km / engine hours. Date automatic.
- Lookup mode: plate or phone → vehicle card (last oil, usual liters, last date, route, history, next predicted change + status OK / due soon / overdue).
- Structure: company → vehicles → service records (driver + phone stored per service record). Service count computed from rows.
- Segments: New (1), Returning (2), Loyal (3+), At risk (predicted date passed, not returned).

**Feature 2 — Prediction + reminder**
- Model predicts next oil change date from vehicle model, oil grade, route (UB city / MN–China / MN–Russia / mine site / mixed), odometer history, season.
- Must beat a naive fixed-interval baseline. Honest reporting.
- Trained on SYNTHETIC data from documented rules; real collected records used for test/validation. Stated openly.
- Mongolian reminder message: plate, last change date, oil used, contact.

**DL:** plate detection (YOLO) + recognition (4 digits + 3 Cyrillic letters), look-alike normalization, manual fallback, fleet-number mode for mine haul trucks.

**Stack:** Python, pandas, scikit-learn, XGBoost, SHAP, Ultralytics YOLO + OCR (EasyOCR/PaddleOCR) vs custom PyTorch CNN, FastAPI + SQLAlchemy, PostgreSQL (local Docker / Supabase cloud), React/Next.js on Vercel, Docker, GitHub Actions, backend host TBD (see D-011 to D-013).

---

## 2. Requirement checklist (from AI Academy Asia slides)

Status: ✅ covered by plan · 🟡 covered but at risk · 🔴 gap — action needed

| # | Requirement (source) | Maps to | Status | Notes / action |
|---|---|---|---|---|
| R1 | Real, uncleaned data; API / web scraping (slide "Хичээлийн даалгавар vs Capstone") | F1 records, F2 test set | 🔴 | Training is synthetic. Need: (a) real messy Geo-Expert records as test set, (b) at least one real external API, (c) **instructor confirmation that synthetic training is acceptable**. |
| R2 | Multi-model comparison + hyperparameter tuning | F2 model, DL | ✅ | Baseline (fixed interval) + Linear Regression + Random Forest + XGBoost; RandomizedSearchCV with grouped/time-aware CV. |
| R3 | F-Score, Latency P99, inference speed, business ROI | F2, Backend, Slide 11 | 🟡 | F-score needs a classification view → derived from status buckets (OK/due soon/overdue). P99 measured by load test. ROI needs Ari's real business numbers. |
| R4 | FastAPI, CI/CD, web interface, Cloud; not local, working link | Backend, Frontend, Deploy | 🟡 | YOLO + torch images are heavy for free tiers — memory risk. See RISK-04. |
| R5 | Core ML metrics: RMSE (regression), F-Score, ROC-AUC, Feature Importance | F2 | ✅ | RMSE, MAE, R² primary; F1 + ROC-AUC on derived "overdue" class. |
| R6 | CV track: custom CNN vs transfer learning; mAP, IoU, Accuracy | DL | 🔴 | Current plan has no "custom CNN vs transfer" comparison. Proposal D-008: pretrained OCR vs small custom PyTorch CNN char classifier. Needs Ari's approval. |
| R7 | 5 mandatory steps: EDA & cleaning, Feature Eng., Multi-model, Metrics, XAI (SHAP) | F2 | ✅ | All in Phase 2. |
| R8 | Unified data pipeline against training–serving skew | F2 + Backend | ✅ | One shared module `src/common/features.py` used by training AND API. |
| R9 | API → Docker → Cloud → CI/CD → demo | Deploy | ✅ | Phase 5. |
| R10 | TCO for 3 infra tiers (MVP / mid / enterprise) + revenue model | Slide 10–11 | 🟡 | Needs real price lookups at time of writing + Ari's business model choice. |
| R11 | 13-slide structure + LIVE demo mandatory | Presentation | ✅ | Slide map in §9. Backup demo video mandatory too. |
| R12 | Presentation content: problem & user, 5-layer architecture, one-request path, data, features & training, model comparison, limitations & responsibility, conclusion | Presentation | ✅ | Each phase must produce its slide material. |
| R13 | Portfolio: GitHub clean code, requirements.txt, Dockerfile, demo link | Repo | ✅ | Enforced from Day 1 via repo structure + CI. |
| R14 | MLOps next step: data drift, continuous training (Level 0→1→2) | Slide 12 | ✅ | Presented as "next steps"; optional basic drift check if time allows. |
| R15 | Responsibility: where the model fails, risks, who is affected | Slide 7/limitations | 🟡 | Personal data (driver names, phones), wrong reminders, OCR misreads. Needs consent statement for reminders. |

---

## 3. Phase plan (assumes 4 weeks; W = week)

| Phase | Goal | Owner(s) | When | Deliverable | Done when |
|---|---|---|---|---|---|
| P0 Setup & decisions | Repo, contracts, collection started | PM, Ari | D1–D2 | Repo skeleton, this file, open questions answered | Repo on GitHub with structure + CI stub; deadline set; instructor answer on synthetic data requested |
| P1 Data foundation | Schema + synthetic generator + real data intake | Data Eng | W1 | `schema.sql`, `generator.py`, `synthetic_rules.md`, `cleaning.py`, `data_dictionary.md` | Generator reproducible (seed); Ari has confirmed every rule parameter; real records cleaned with issue log |
| P2 Prediction model | Beat baseline honestly, explain it | ML Eng | W2 | `features.py`, `train.py`, `evaluate.py`, `explain.py`, model artifact, `model_card.md` | ≥3 models + baseline compared on synthetic holdout AND real test set; SHAP plots; results table |
| P3 Plate recognition | Detect + read plates with fallback | CV/DL Eng | W1–W3 (data-bound) | YOLO weights, `recognize.py`, `normalize.py`, eval report | mAP50/IoU reported; exact-plate-match rate on held-out trucks; manual fallback path works |
| P4 Backend | Serve everything via API + DB | Backend Eng | W2–W3 | FastAPI app, migrations, endpoints, reminder generator, tests | All contract endpoints pass tests; P50/P95/P99 measured locally |
| P5 Frontend | Mobile-first screens | Frontend/UX | W3 | Recording, Lookup, Vehicle card, Dashboard | Full flow works on a phone against real API |
| P6 Deploy & MLOps | Public link, CI/CD, latency, TCO | Backend Eng (+PM) | W4 (early) | Dockerfiles, compose, GitHub Actions, cloud URL, load test, TCO table | Push to main → tests → deploy; public URL works; P99 under load reported |
| P7 Presentation | 13 slides + demo rehearsal | PM, all | W4 (late) | Deck, demo script, backup video | 2 full rehearsals; demo works from a phone on mobile data |

**Critical path:** real truck photos (for P3) and real service records (for P2 test set). Both depend on Ari collecting at work, starting **today**.

**If only 3 weeks:** cut P3 custom CNN comparison to a smaller version, cut Next.js → Streamlit/Gradio UI, drop external API to a single enrichment feature. Never cut: live demo, baseline comparison, SHAP, cloud link.

---

## 4. Task list

| ID | Task | Owner | Status |
|---|---|---|---|
| 0.1 | Set deadline, get instructor answer on synthetic training | Ari | TODO |
| 0.2 | Start collecting truck photos (target 300+, min ~150, different trucks, angles, light, dirt) | Ari | TODO |
| 0.3 | Gather existing real service records in whatever form exists (notebook, Excel, Viber) | Ari | TODO |
| 0.4 | Create GitHub repo with agreed structure (§8) | Backend Eng | ✅ DONE (private, CI green) |
| 0.5 | Add CLAUDE.md + .claude/settings.json to repo root, commit | Ari | ✅ DONE |
| 0.6 | Local Python 3.11 venv; fix settings.json (.env.example readable); fill .env.example DB vars | Claude Code | TODO |
| 1.1 | PostgreSQL schema + data dictionary | Data Eng | ✅ DONE (26 tests pass; DB tests skip in CI until 6.2) |
| 1.2 | Synthetic rules draft → Ari confirms numbers | Data Eng + Ari | TODO |
| 1.3 | Synthetic generator with noise injection | Data Eng | TODO |
| 1.4 | Real record intake template + cleaning script | Data Eng | TODO |
| 1.5 | External API evaluation (1 source) | Data Eng | TODO |
| 2.1 | EDA notebook (synthetic + real) | ML Eng | TODO |
| 2.2 | Shared feature pipeline `features.py` | ML Eng | TODO |
| 2.3 | Baseline + 3 models + tuning | ML Eng | TODO |
| 2.4 | Evaluation (regression + derived classification) + SHAP | ML Eng | TODO |
| 3.1 | Labeling setup + labeled dataset (split by vehicle) | CV Eng | TODO |
| 3.2 | YOLO plate detector fine-tune | CV Eng | TODO |
| 3.3 | Recognition: pretrained OCR vs custom CNN | CV Eng | TODO |
| 3.4 | Normalization + confidence fallback | CV Eng | TODO |
| 4.1 | FastAPI skeleton + DB + migrations | Backend Eng | TODO |
| 4.2 | Endpoints per contract (§8) | Backend Eng | TODO |
| 4.3 | Model + CV serving | Backend Eng | TODO |
| 4.4 | Segments + reminders | Backend Eng | TODO |
| 5.1 | UX flow + wireframes | Frontend | TODO |
| 5.2 | Recording mode | Frontend | TODO |
| 5.3 | Lookup + vehicle card | Frontend | TODO |
| 5.4 | Dashboard (segments, due list, reminders) | Frontend | TODO |
| 6.1 | Docker + compose | Backend Eng | TODO |
| 6.2 | CI/CD GitHub Actions (+ Postgres service so DB tests run in CI) | Backend Eng | TODO |
| 6.3 | Cloud deploy + public URL (Supabase DB + backend host + Vercel) | Backend Eng | TODO |
| 6.4 | Load test (P50/P95/P99) | Backend Eng | TODO |
| 6.5 | TCO 3 tiers + ROI | PM + Ari | TODO |
| 7.1 | 13-slide deck | PM + Ari | TODO |
| 7.2 | Demo script + backup video + rehearsals | Ari | TODO |

---

## 5. Decisions log

| ID | Date | Decision | Reason | Status |
|---|---|---|---|---|
| D-001 | 2026-09-30 | Scope frozen as in §1 | Agreed with Ari | Final |
| D-002 | 2026-09-30 | Train on synthetic data; real records only for test/validation | Not enough real history | Final (pending instructor OK) |
| D-003 | 2026-09-30 | Oil lab reports out of scope | Geo-Expert not taking lab reports now | Final |
| D-004 | 2026-09-30 | Driver + phone stored per service record, not per vehicle | Drivers change between trips | Final |
| D-005 | 2026-09-30 | Vehicle identifier has type: `plate` or `fleet_no` | Mine haul trucks may lack plates | Final |
| D-006 | — | Primary ML target: `days_to_next_change` (regression). Mine-site vehicles may use engine hours → generator must support hour-based intervals | Date is what the reminder needs | PROPOSED |
| D-007 | — | Status buckets: OK (> 14 days left), Due soon (0–14 days), Overdue (< 0). At risk = overdue + 7 days grace, no new record | Needed for F1 and segments | PROPOSED — Ari to confirm thresholds |
| D-008 | — | CV comparison: pretrained OCR vs small custom PyTorch CNN char classifier (both after YOLO detection) | Satisfies "custom CNN vs transfer learning" (R6) | PROPOSED |
| D-009 | — | Splits grouped by vehicle (no same truck in train and test), time-ordered for ML | Prevent leakage | PROPOSED |
| D-010 | — | Reminder delivery for demo: generate message + mark "sent" + copy/share button; real SMS gateway = Later | Gateway cost/contract unknown | PROPOSED |
| D-011 | 2026-09-30 | Database = PostgreSQL. Local dev: Postgres in Docker. Cloud: Supabase, used ONLY for Postgres + Storage (photos). No Supabase Auth/auto-API; all logic in FastAPI via SQLAlchemy + standard connection string | Course grades FastAPI; stays portable to AWS (TCO tiers) | APPROVED by Ari |
| D-012 | 2026-09-30 | Model line-up: Prediction = fixed-interval baseline, Linear/Ridge Regression, Random Forest, XGBoost + SHAP. CV = Ultralytics YOLO (smallest size) for detection; recognition compares pretrained OCR (EasyOCR or PaddleOCR) vs custom PyTorch CNN | Meets multi-model + custom-vs-transfer requirements | APPROVED by Ari (OCR Cyrillic support must be verified by CV Eng) |
| D-013 | 2026-09-30 | Services: GitHub + GitHub Actions, Supabase, Docker, Colab/Kaggle (GPU training), Label Studio or CVAT (private labeling), backend host TBD in P6 (HF Spaces / Render — check current free-tier limits), Vercel (frontend), Open-Meteo (candidate external API), Locust (P99) | All free tier = MVP TCO tier | APPROVED by Ari (host choice open) |
| D-014 | 2026-09-30 | Workflow: PM chat = planning/decisions/briefs/handoff reviews. Role chats cannot see each other; Ari relays briefs and handoff reports. PROJECT_STATE.md in Project files is the single source of truth (replace old version on every update). Optional Mentor/Q&A chat for learning questions | Chats are isolated | APPROVED |
| D-015 | 2026-09-30 | Repo privacy rules: data/**, models/**, .env, all photo types, *.csv/*.xlsx ignored everywhere; only docs/figures/*.png allowed. If tests need small sample CSVs later, add exception `!tests/fixtures/**` with SYNTHETIC data only | Protect real driver/plate data (RISK-06) | APPROVED (verified by PM test) |
| D-016 | 2026-09-30 | PROJECT_STATE.md lives in 2 places: Claude Project files + repo docs/. On every new version, replace both (commit message: `docs: PROJECT_STATE vX.Y`) | Roles read Project files; repo is the portfolio | APPROVED |
| D-017 | 2026-09-30 | Claude Code usage: web role chats plan/explain; Claude Code may execute tasks inside the repo. Context comes from repo files only: CLAUDE.md (auto-read) + docs/PROJECT_STATE.md. `.claude/settings.json` denies reading .env and data/raw/**. Real data: Claude Code writes/tests cleaning scripts on synthetic or masked data; Ari runs them on real data and shares summaries only | Claude Code cannot see claude.ai chats or Project files; protect personal data | APPROVED |
| D-018 | 2026-09-30 | Workflow: PM chat writes short briefs → one NEW Claude Code session per task (role line + brief) → handoff back to PM. Claude Code commits + pushes after Ari's OK (routine in CLAUDE.md). Web role chats = optional tutors | Less copy-paste; repo files carry context | APPROVED |
| D-019 | 2026-09-30 | Schema (task 1.1): phone = 8 digits, no +976; private owner stored as a company row; oil_grade/vehicle_model free text; route nullable; TEXT+CHECK not ENUM; segments via vehicle_segments(as_of, grace_days); days_left/status computed at read time; names in docs/data_dictionary.md are the contract | Reviewed by PM | APPROVED |
| D-020 | 2026-09-30 | Python 3.11 is the project version (local venv, CI, Docker) even though Mac has 3.14 | ML/CV libraries (torch, ultralytics) are safest on 3.11 | APPROVED |

---

## 6. Open questions

1. **Deadline** — exact defense date?
2. **Instructor:** is synthetic training + real test set acceptable for the "real uncleaned data" requirement?
3. How many real past service records exist, and in what form?
4. How many truck photos can Ari collect per week? Any fleet-number-only trucks available to photograph?
5. Real service interval rules per oil grade / route / vehicle type (Ari's domain knowledge) — needed for P1.2.
6. Hosting budget: free tiers only, or small paid? (Default now: free tiers, D-013)
7. Which Cyrillic letters actually appear on Mongolian plates (to be verified from real photos, not assumed).
8. Status thresholds for D-007.
9. Frontend: keep Next.js, or accept Streamlit/Gradio if behind schedule?

---

## 7. Risks

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| RISK-01 | Instructor rejects synthetic training | Med | High | Ask in week 1; maximize real messy data; show generator rules transparently |
| RISK-02 | Too few truck photos → weak YOLO/OCR | High | High | Start collecting today; augmentations; manual fallback is part of the product |
| RISK-03 | Model only learns generator rules (circular evaluation) | High | Med | Report synthetic vs real test separately; state limitation on slide |
| RISK-04 | Docker image with torch/YOLO too big for free cloud tier RAM | Med | High | Use smallest YOLO; CPU-only torch; ONNX export; or host CV service separately |
| RISK-05 | One person running 5 roles → schedule slip | High | High | Strict phase gates; cut list in §3; Streamlit fallback |
| RISK-06 | Personal data (driver names, phones) leaked in repo/demo | Med | High | Never commit real data; seed demo DB with synthetic people; `.gitignore` data folders |
| RISK-07 | Live demo fails (network, cloud cold start) | Med | High | Warm up URL before defense; backup video; demo on known-good plate photos |
| RISK-08 | Plate letters misread (Cyrillic/Latin look-alikes) | High | Med | Normalization map + format regex + confirmation step |

---

## 8. Contracts (shared by all roles)

**Repo structure**
```
oil-change-predictor/
├── data/            # raw/ interim/ processed/ synthetic/  (git-ignored except samples)
├── src/
│   ├── common/      # features.py (shared train+serve), config.py, plates.py (normalization)
│   ├── data/        # generator.py, cleaning.py, external_api.py
│   ├── ml/          # train.py, evaluate.py, explain.py
│   ├── cv/          # detect.py, recognize.py, cnn_char.py
│   └── api/         # main.py, routers/, db.py, models.py, schemas.py
├── frontend/        # Next.js app
├── notebooks/       # EDA, experiments (numbered)
├── models/          # artifacts (git-ignored; versioned by name)
├── tests/
├── docs/            # PROJECT_STATE.md, data_dictionary.md, synthetic_rules.md, model_card.md
├── Dockerfile(s), docker-compose.yml, requirements.txt
└── .github/workflows/ci.yml
```

**API contract v0 (draft — Backend owns, changes logged here)**
- `POST /plates/recognize` (image) → `{plate_raw, plate_normalized, confidence, bbox, needs_manual}`
- `GET /vehicles/lookup?q=` (plate or phone) → vehicle card
- `POST /services` → create service record (creates vehicle/company if new)
- `GET /vehicles/{id}` → card: last service, usual liters, history, service_count, segment, prediction
- `GET /vehicles/{id}/prediction` → `{predicted_date, days_left, status, model_version}`
- `GET /reminders/due` → list of vehicles due soon/overdue with generated Mongolian message
- `POST /reminders/{id}/sent`
- `GET /stats/segments` → counts per segment

---

## 9. Slide map (13 slides → producing phase)

| # | Slide | Material from |
|---|---|---|
| 1 | Title | P7 |
| 2 | Business problem & solution | P0 (Ari's real story, numbers) |
| 3 | Data overview & EDA | P1, P2.1 |
| 4 | Feature engineering | P2.2 |
| 5 | Model architecture (ML + CV) | P2, P3 |
| 6 | Experiment results & metrics | P2.4, P3 |
| 7 | Explainable AI (SHAP) | P2.4 |
| 8 | System architecture (5 layers) & MLOps | P4, P6 |
| 9 | LIVE demo | P5, P6 |
| 10 | Production cost (TCO 3 tiers) | P6.5 |
| 11 | Business model & ROI | P6.5 |
| 12 | Future development (MLOps levels, SMS, drift) | Later list |
| 13 | Conclusion & Q&A | P7 |

---

## 10. Later list (not in scope unless Ari approves)
- Real SMS / Viber gateway integration
- Automated data drift monitoring + continuous training
- Oil lab report analysis
- Multi-branch / multi-user roles beyond one oil changer + admin
- Offline mode for mine sites without signal
- LLM chat assistant for drivers
