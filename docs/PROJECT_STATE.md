# PROJECT_STATE — Capstone "Oil Change Predictor" (Geo-Expert LLC)

- **Version:** 0.7
- **Last updated:** 2026-10-01
- **Deadline (defense day):** 2026-10-20 (20 days from 2026-09-30)
- **Current phase:** P1 Data foundation + P3 labeling (parallel)
- **Overall health:** 🟡 Yellow — instructor approved synthetic data; 200 truck photos + real Excel records available. Main risk: only 20 days for 1 person.

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
| R1 | Real, uncleaned data; API / web scraping (slide "Хичээлийн даалгавар vs Capstone") | F1 records, F2 test set | 🟡 | Training is synthetic. Need: (a) real messy Geo-Expert records as test set, (b) at least one real external API, (c) ✅ instructor confirmed synthetic training is OK. Real Excel records available. |
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

## 3. Phase plan (deadline 2026-10-20 — 20 days)

| Phase | When | Owner(s) | Deliverable | Done when |
|---|---|---|---|---|
| P0 Setup | ✅ Sep 30 | PM, Ari | Repo, CI, CLAUDE.md, roles | Done |
| P1 Data foundation | Oct 1–5 | Data Eng + Ari | Excel profile, `synthetic_rules.md`, `generator.py`, `cleaning.py` | Generator reproducible; rules have sources or Ari's OK; real records cleaned with issue log |
| P3 Plate recognition (starts in parallel) | Oct 1–12 | Ari labels, CV Eng | Labeled set (split by vehicle), YOLO weights, OCR vs CNN, normalization | mAP50/IoU + exact-plate-match on held-out trucks; manual fallback |
| P4 Backend | Oct 3–11 | Backend Eng | FastAPI, endpoints, serving, reminders | Contract endpoints pass tests |
| P2 Prediction model | Oct 6–10 | ML Eng | features, 4 models, tuning, SHAP, model card | Baseline beaten (or honestly not) on synthetic + real test |
| P5 Frontend | Oct 11–14 | Frontend | Recording, Lookup, Vehicle card, Dashboard | Full flow works on a phone |
| P6 Deploy & MLOps | Oct 14–16 | Backend Eng + PM | Docker, CI/CD, cloud URL, P99, TCO | Public URL works; P99 reported |
| P7 Presentation | Oct 17–19 | PM + Ari | 13 slides, demo script, backup video | 2 rehearsals done |
| Defense | **Oct 20** | Ari | Live demo | — |

**Buffer:** almost none. Any slip → apply cut list immediately.

**Cut list (in this order):** 1) custom CNN comparison → small version on character crops only; 2) external API → one weather feature or drop; 3) dashboard screen → merge into lookup; 4) load test → simple timed script.
**Never cut:** live demo, baseline comparison, SHAP, cloud link, honest synthetic-vs-real reporting.

**Parallel rule:** Claude Code runs one task at a time; Ari's own work (labeling photos, checking rules) runs in parallel with it.

## 4. Task list

| ID | Task | Owner | Status |
|---|---|---|---|
| 0.1 | Set deadline, get instructor answer on synthetic training | Ari | ✅ DONE (Oct 20; synthetic OK) |
| 0.2 | Collect truck photos (target 300+, min ~150) | Ari | 🟡 200 collected (trucks only, readable, repeat vehicles) — keep adding |
| 0.3 | Gather existing real service records | Ari | ✅ DONE (Excel sheet → data/raw/records/) |
| 0.4 | Create GitHub repo with agreed structure (§8) | Backend Eng | ✅ DONE (private, CI green) |
| 0.5 | Add CLAUDE.md + .claude/settings.json to repo root, commit | Ari | ✅ DONE |
| 0.6 | Local Python 3.11 venv; fix settings.json (.env.example readable); fill .env.example DB vars | Claude Code | TODO |
| 1.1 | PostgreSQL schema + data dictionary | Data Eng | ✅ DONE (26 tests pass; DB tests skip in CI until 6.2) |
| 1.4a | Excel profiling script (Ari runs it; only summaries shared) | Data Eng | ✅ DONE — finding: Excel = vehicle registry (338 trucks, VOLVO 62%, built 2004–2013, odometer 99.4% empty), NOT service history |
| 1.4b | Service dates for repeat trucks (Messenger photos have no EXIF/filename date) → Ari dates repeat-truck photos manually from the chat | Ari | ⏸ by ~Oct 8, after labeling |
| 1.2 | Synthetic rules: 1.2a web research with sources + Excel profile → Ari confirms | Data Eng + Ari | ⏸ PAUSED (restart by Oct 3) |
| 1.3 | Synthetic generator with noise injection | Data Eng | TODO |
| 1.4 | Real record intake template + cleaning script | Data Eng | TODO |
| 1.5 | External API evaluation (1 source) | Data Eng | TODO |
| 2.1 | EDA notebook (synthetic + real) | ML Eng | TODO |
| 2.2 | Shared feature pipeline `features.py` | ML Eng | TODO |
| 2.3 | Baseline + 3 models + tuning | ML Eng | TODO |
| 2.4 | Evaluation (regression + derived classification) + SHAP | ML Eng | TODO |
| 3.1 | Labeling setup (Label Studio local, box + plate_type + plate_text) | CV Eng | ✅ DONE (export tested) |
| 3.1c | Pre-label with pretrained detector (oim YOLOv9-t, thr 0.6) → import as predictions | CV Eng | 🟡 code done; Ari runs import |
| 3.1d | Ari checks boxes + types Cyrillic plate text for 192 photos; export JSON after each session | Ari | TODO — target Oct 4 |
| 3.2 | Vehicle-grouped split (~70/15/15) + YOLO fine-tune; evaluate pretrained oim on same test split as baseline | CV Eng | TODO |
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
| D-002 | 2026-09-30 | Train on synthetic data; real records only for test/validation | Not enough real history | Final (instructor approved) |
| D-003 | 2026-09-30 | Oil lab reports out of scope | Geo-Expert not taking lab reports now | Final |
| D-004 | 2026-09-30 | Driver + phone stored per service record, not per vehicle | Drivers change between trips | Final |
| D-005 | 2026-09-30 | Vehicle identifier has type: `plate` or `fleet_no` | Mine haul trucks may lack plates | Final |
| D-006 | — | Primary ML target: `days_to_next_change` (regression). Mine-site vehicles may use engine hours → generator must support hour-based intervals | Date is what the reminder needs | PROPOSED |
| D-007 | — | Status buckets: OK (> 14 days left), Due soon (0–14 days), Overdue (< 0). At risk = overdue + 7 days grace, no new record | Needed for F1 and segments | APPROVED as default (adjustable parameter; Ari may change later) |
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
| D-021 | 2026-09-30 | Deadline 2026-10-20; plan compressed to 20 days (§3) | Instructor date | APPROVED |
| D-022 | 2026-09-30 | Frontend for the capstone = Streamlit (mobile-friendly, camera input) calling FastAPI. Next.js moves to Later (production version after capstone) | 20 days, 1 person; FastAPI backend stays so the UI can be swapped later | APPROVED by Ari |
| D-023 | 2026-09-30 | Geo-Expert will use the system after the capstone → ROI slide uses real operations; code quality matters beyond the demo | Ari confirmed | APPROVED |
| D-024 | 2026-10-01 | Real data roles: Excel = vehicle registry (seed vehicles table, real fleet mix for generator, messy-data evidence). Photos = real service events (plate via labels; dates only for repeat trucks). Real prediction test set = repeat-truck intervals from photos (small; reported honestly) | Excel has no service history | APPROVED |
| D-025 | 2026-10-01 | Pre-labeling detector = open-image-models YOLOv9-t-640 (ONNX, MIT code; weights license unstated → internal labeling aid only). Import threshold 0.6. Plate text NOT pre-filled (keeps OCR ground truth unbiased) | Pilot: fewer false boxes than hf26n; 187/192 photos got boxes | APPROVED |
| D-026 | 2026-10-01 | Labeling rules: box every real readable plate (incl. background trucks); delete non-plate boxes; Cyrillic, no spaces; `?` for unreadable char; no plate → Skip | Detector must learn all plates are plates | APPROVED |
| D-027 | 2026-10-01 | Photos taken from now on go to data/raw/photos_new/ → second, unseen test set | Most honest evaluation | APPROVED |

---

## 6. Open questions

1. ~~Deadline~~ → Oct 20. ~~Instructor~~ → synthetic OK.
2. Do the photo plates match the Excel records? ("maybe" — check during 1.4a / 3.1)
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
| RISK-01 | ~~Instructor rejects synthetic training~~ CLOSED | — | — | Ask in week 1; maximize real messy data; show generator rules transparently |
| RISK-02 | Too few truck photos → weak YOLO/OCR | High | High | Start collecting today; augmentations; manual fallback is part of the product |
| RISK-03 | Model only learns generator rules (circular evaluation) | High | Med | Report synthetic vs real test separately; state limitation on slide |
| RISK-04 | Docker image with torch/YOLO too big for free cloud tier RAM | Med | High | Use smallest YOLO; CPU-only torch; ONNX export; or host CV service separately |
| RISK-05 | One person, 20 days → schedule slip | High | High | Strict dates in §3; cut list; Streamlit (D-022); Ari labels photos in parallel |
| RISK-06 | Personal data (driver names, phones) leaked in repo/demo | Med | High | Never commit real data; seed demo DB with synthetic people; `.gitignore` data folders |
| RISK-07 | Live demo fails (network, cloud cold start) | Med | High | Warm up URL before defense; backup video; demo on known-good plate photos |
| RISK-09 | Licensing: Ultralytics YOLO is AGPL-3.0; pre-label weights license unstated. Fine for capstone; Geo-Expert production use may need Ultralytics commercial license or a permissive alternative | Med | Med | Decide after defense; document in model card |
| RISK-10 | Real prediction test set is tiny (repeat trucks only, dates entered manually) | High | Med | Report honestly; add photos_new over time; synthetic holdout as main metric |
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
- Next.js production frontend (if D-022 approved)
- Real SMS / Viber gateway integration
- Automated data drift monitoring + continuous training
- Oil lab report analysis
- Multi-branch / multi-user roles beyond one oil changer + admin
- Offline mode for mine sites without signal
- LLM chat assistant for drivers
