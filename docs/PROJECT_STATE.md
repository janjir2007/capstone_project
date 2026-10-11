# PROJECT_STATE — Capstone "Oil Change Predictor" (Geo-Expert LLC)

- **Version:** 1.9
- **Last updated:** 2026-10-10
- **Deadline (defense day):** 2026-10-20 (20 days from 2026-09-30)
- **Current phase:** P3 done (detector) → P1 synthetic data (redesigned around destination, D-033–D-036) + P4 backend URGENT
- **Overall health:** 🟠 Orange — detector finished and strong, but synthetic data, ML model and backend have NOT started; ~3–4 days behind plan with 15 days left.

---

## 1. Agreed scope (frozen — changes need Ari's approval)

**Feature 1 — Customer database**
- Recording mode: photo → plate detection + Cyrillic recognition → oil changer confirms plate.
  - Existing plate → form pre-filled from last service (oil grade, liters, route, driver, phone) → check, edit, save.
  - New plate → fill everything once.
  - Always fresh: odometer km / engine hours + **destination (where the truck is heading next)**. Date automatic. (D-033)
- Lookup mode: plate or phone → vehicle card (last oil, usual liters, last date, route, history, next predicted change + status OK / due soon / overdue).
- Structure: company → vehicles → service records (driver + phone stored per service record). Service count computed from rows.
- Segments: New (1), Returning (2), Loyal (3+), At risk (predicted date passed, not returned).

**Feature 2 — Prediction + reminder**
- **Purpose = reminder timing** (D-036): send the reminder just before the truck is due — too late = customer lost, too early = forgotten.
- Model predicts next oil change date from destination/route (UB city / MN–China / MN–Russia / mine site / mixed) + distance, the vehicle's own history (km/day from odometer readings, past intervals, lateness), season, road vs haul flag. Vehicle model is NOT a model feature (D-034); oil grade TBD.
- Baselines: B0 fixed interval, B1 route formula (distance ÷ route km/day) (D-035).
- Must beat B0 and B1 baselines (or report honestly that it doesn't).
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
| R2 | Multi-model comparison + hyperparameter tuning | F2 model, DL | ✅ | B0 fixed interval + B1 route formula + Ridge + Random Forest + XGBoost; RandomizedSearchCV with grouped/time-aware CV. |
| R3 | F-Score, Latency P99, inference speed, business ROI | F2, Backend, Slide 11 | 🟡 | F-score needs a classification view → derived from status buckets (OK/due soon/overdue). P99 measured by load test. ROI needs Ari's real business numbers. Business metric = reminder hit rate (D-036). |
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
| 1.4b | Service dates for repeat trucks: Claude Code makes fill-in CSV → Ari types dates from Messenger chat → script computes real intervals (D-046) | Data Eng + Ari | ▶ BRIEF ISSUED Oct 10 (was due Oct 8) |
| 1.1b | Schema migration: destination on service record + destinations reference table (name, route category, one-way km, round-trip days, source) | Data Eng | ✅ DONE Oct 6 — migration 001 (plain SQL up/down, psql --single-transaction), 7 destinations seeded, nullable destination_id + destination_raw, 16 tests (112 pass locally; DB tests skip in CI until 6.2), data_dictionary v0.2 |
| 1.1c | Migration 002: Ari's round-trip days + mine-site rows + name_mn (D-040) | Data Eng | TODO — after Ari fills A1–A4 (same session as 1.3 start) |
| 1.2 | Synthetic rules (1.2a): research + Ari inputs → docs/synthetic_rules.md → Ari marks ✓/✗. Redesigned per D-033–D-036. First draft (Oct 5) was lost/never saved; rewritten from scratch Oct 6 | Data Eng + Ari | ✅ DRAFT DONE (OSRM distances, 7 variations, 13 noise rules, 16 open items) → ⏳ BLOCKED on Ari: A1–A4 + ✓/✗ |
| 1.3 | Synthetic generator with noise injection — unknowns as config ranges (D-045) | Data Eng | ✅ DONE Oct 10 — 500 trucks, 3,845 clean / 3,927 dirty rows, seed 42 reproducible, every param tagged; days to next change p5 36 / median 58 / p95 88; real comparison pending 1.4b |
| 1.4 | Cleaning script (tested on dirty file + noise_log) | Data Eng | ✅ DONE Oct 10 — 3,927 → 3,845 rows; precision/recall 100% on own noise (circular — see D-048); 0 truck identity errors; 274 tests pass |
| 1.4c | Real record intake template / Excel column mapping | Data Eng | LATER (post-defense; not needed for real test, which uses 1.4b intervals) |
| 1.5 | External API evaluation (1 source) | Data Eng | TODO |
| 2.1–2.3a | EDA + `features.py` + vehicle/time split + baselines B0, B1 (one session; clean file first, switch to cleaned later) | ML Eng | ▶ BRIEF ISSUED Oct 10 |
| 2.3b | Ridge / RF / XGBoost + RandomizedSearchCV | ML Eng | TODO (Oct 11–12) |
| 2.4 | Evaluation (regression + derived classification + reminder hit rate D-036) + D-038 variation-off check + SHAP | ML Eng | TODO (Oct 12–13) |
| 3.1 | Labeling setup (Label Studio local, box + plate_type + plate_text) | CV Eng | ✅ DONE (export tested) |
| 3.1c | Pre-label with pretrained detector (oim YOLOv9-t, thr 0.6) → import as predictions | CV Eng | ✅ DONE |
| 3.1d | Ari checks boxes + types Cyrillic plate text | Ari | ✅ DONE — 183 labeled, 9 skipped, 135 trucks, 35 repeat trucks (83 photos), all 183 match 4 digits + 3 Cyrillic |
| 3.2 | Vehicle-grouped split + YOLO fine-tune + eval vs pretrained oim | CV Eng | ✅ DONE — test (27 img / 20 trucks): yolo26n mAP50 0.991, P 0.93, R 1.00, 21.5 ms MPS; oim P 0.73 (10 false boxes) |
| 3.3 | Recognition: pretrained OCR vs custom CNN — REDUCED scope (cut list #1): small CNN on character crops, same split.json | CV Eng | ▶ BRIEF ISSUED Oct 6 (pulled forward: 1.3 waits on Ari) |
| 3.4 | Normalization + confidence fallback (pulled forward: independent of synthetic data) | CV Eng | ✅ DONE Oct 6 — read_plate() + normalize_plate(); 21 letters seen; 183/183 labels pass format; 291 tests pass |
| 4.1 | FastAPI skeleton + DB + migrations (decide: keep plain SQL or move to Alembic) | Backend Eng | ✅ DONE Oct 6 — src/api (config, db, /health 200/503), Dockerfile (310 MB, non-root), compose "api", requirements-api.txt; 130 tests pass locally |
| 4.2 | Endpoints per contract (§8) — data endpoints only (lookup, services, vehicle card, segments); prediction field null until 4.3 | Backend Eng | ✅ DONE Oct 6 — 4 endpoints, plates.py (spaces/case only), contract docs/api_contract.md v0.2, 204 tests pass locally |
| 4.2b | GET /destinations (dropdown, name_mn when 002 lands), lookup by fleet_no, case/space-insensitive company match, same-vehicle same-day duplicate guard (409 + force flag) | Backend Eng | ✅ DONE Oct 6 — api_contract v0.3, src/api/matching.py, 232 tests pass |
| 4.3 | Model + CV serving | Backend Eng | TODO |
| 4.4 | Segments + reminders. Small fixes: fleet_no matching ignores dashes (lookup + POST /services uses matching.py, not exact) | Backend Eng | TODO |
| 5.1 | UX flow + wireframes | Frontend | TODO |
| 5.2 | Recording mode | Frontend | TODO |
| 5.3 | Lookup + vehicle card | Frontend | TODO |
| 5.4 | Dashboard (segments, due list, reminders) | Frontend | TODO |
| 6.1 | Docker + compose | Backend Eng | TODO |
| 6.2 | CI/CD GitHub Actions (+ Postgres service so DB tests run in CI) | Backend Eng | TODO |
| 6.3 | Cloud deploy + public URL (Supabase DB + backend host + Vercel) + schema_migrations table & apply script (D-041) | Backend Eng | TODO |
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
| D-028 | 2026-10-05 | Production plate detector = fine-tuned yolo26n (best test mAP50/P/R, fastest on MPS). yolo11n kept as comparison only. No retraining unless data changes (yolo26n took ~3 h) | Test results 3.2 | APPROVED (PM) |
| D-029 | 2026-10-05 | Schedule recovery: order = 1.2a+1.3 synthetic data → 2.x ML model → 4.1–4.4 backend → 3.3/3.4 OCR (reduced) → Streamlit UI → deploy. Ari's parallel work: date repeat-truck photos (1.4b), keep collecting photos_new | 15 days left, data/ML/backend not started | APPROVED by Ari |
| D-030 | 2026-10-05 | Interval rules: recommended = change before 15,000 km (low fuel quality in MN) → reminder target. ACTUAL driver behavior (CONFIRMED by Ari) = 15,000–20,000 km → generator models actual. Gap = business argument for reminders | Ari's domain knowledge | APPROVED |
| D-031 | 2026-10-05 | Customer return behavior (Ari ESTIMATE): ~50% on time, ~40% late, ~10% never return. Trips/month unknown → estimated from route research, UNCONFIRMED parameter; calibrate later with 35 repeat trucks' real dates | Ari's estimate | APPROVED as parameters |
| D-032 | 2026-10-05 | Route research PDF (docs/research/routes_ub.pdf, AI-generated): use only Medium/High routes (Zamyn-Uud–Erenhot, Altanbulag–Kyakhta, Beijing); citation markers not real links → find real sources; Chita-via-Altai route is wrong; UB city + mine site researched separately. Not cited directly on slides | PM review | APPROVED |
| D-033 | 2026-10-05 | Destination ("where are you heading next") is asked at every service and stored on the service record; mapped to route category + round-trip distance. Core input of generator and model. Collected from now on (real data) | Geo-Expert has no usable service history; destination is real, cheap to collect | APPROVED by Ari |
| D-034 | 2026-10-05 | Vehicle model removed from generator rules and model features (field stays in DB + vehicle card). Keep one coarse flag: road truck vs mine haul truck (engine hours, D-006). Oil grade: open question | Interval 15k–20k km regardless of model; 62% VOLVO → little signal; saves time | APPROVED by Ari (scope §1 updated) |
| D-035 | 2026-10-05 | Formula = Baseline B1: days = interval_km ÷ route km/day, where km/day = round-trip km ÷ round-trip days incl. waiting. ML must beat B0 and B1. ML adds vehicle's own history (km/day from odometer, past intervals, lateness), season, return behavior. One global model; history follows the VEHICLE (D-004), phone = message recipient. First visit → falls back to B1 | Keep ML meaningful and comparison fair | APPROVED by Ari |
| D-036 | 2026-10-05 | Project purpose = reminder timing for customer retention. Business metric = reminder hit rate (% of reminders inside useful window before actual due date); RMSE/MAE kept for course. Late reminder worse than early → send with safety buffer before predicted date. Window size TBD (Ari) | Ari's business goal | APPROVED by Ari (window TBD) |
| D-037 | 2026-10-06 | 1.2a rules accepted as draft: one-way km from OpenStreetMap/OSRM (UB centre → town point); round trip = 2× one-way; aggregator 834 km UB–Zamyn-Uud excluded pending Ari (A5); "late" = beyond 20,000 km point, extra days exponential mean 10 / max 60; if haul-truck values missing by Oct 8 → generator makes road trucks only (mine SITE stays as a destination). All [ESTIMATE] values remain Ari ✓/✗ | Handoff 1.2a review | APPROVED (PM), estimates pending Ari |
| D-038 | 2026-10-06 | Sanity check in 2.4: retrain with generator variation OFF → ML must ≈ B1. If ML beats B1 by much more than the injected variation explains, something leaks | Guards RISK-03 | APPROVED (PM) |
| D-039 | 2026-10-06 | Route source of truth: if destination_id is set → service_records.route = destinations.route_category (backend 4.2 sets it, user can't override); if only destination_raw → oil changer picks route manually. Keep the route column | 1.1b handoff: the two could disagree | APPROVED (PM) |
| D-040 | 2026-10-06 | Destinations get a Mongolian label column name_mn (UI shows Mongolian; English name stays as key). Added in migration 002 with Ari's values. Mine-site rows also via 002. Migrations = numbered plain SQL up/down until 4.1 decides on Alembic | Oil changer UI is Mongolian | APPROVED (PM) |
| D-041 | 2026-10-06 | Migrations stay numbered plain SQL up/down for the capstone (no Alembic). Before the 2nd DB (Supabase, 6.3): add schema_migrations(version, applied_at) + small script applying missing *.up.sql in order in one transaction. Alembic = post-capstone option (baseline + wrap SQL). Role doc "Alembic" line superseded. Config stays in src/api/config.py (API-only) | 4.1 handoff: schema uses SQL function, CHECKs, seeds; no ORM models; 16 tests run .sql directly | APPROVED (PM) |
| D-042 | 2026-10-06 | 4.2 API rules accepted: lookup returns a list (phone can match several trucks), unknown → 200 + []; 8-digit (+976 optional) = phone, else plate; POST /services needs exactly one of destination_id/destination_raw; destination_id + different route → 422; new vehicle needs company_name; fleet_no needs company_name; service_date default = today UB (UTC+8), future → 422; usual_liters = mode, tie → most recent; "today" computed in API (UB), not DB CURRENT_DATE. Exact contract = docs/api_contract.md (source of truth; §8 is summary) | 4.2 handoff | APPROVED (PM) |
| D-043 | 2026-10-06 | 4.2b matching rules: done in Python (casefold), not SQL (Cyrillic locale differs on Supabase). Company key = case-insensitive, spaces collapsed. Duplicate = same vehicle + same calendar date → 409 {code: duplicate_service}; ?force=true overrides. No DB constraint (rare race accepted). Destinations ordered by id. Fleet_no dash-insensitive + POST matching → 4.4 | 4.2b handoff | APPROVED (PM) |
| D-044 | 2026-10-06 | Plate rules (3.4): clean spaces/hyphens/dots + case → 12 Latin look-alikes + U→У → O↔0 by position (7 chars only) → format = 4 digits + 3 of 21 letters SEEN in 183 labels (АБВГДЕКМНОПРСТУХЦЧЭҮӨ) → confidence ≥ 0.6 (inclusive) else needs_manual. Unseen letter → manual input; add letters as photos_new grows | 3.4 handoff; 183/183 labels pass | APPROVED (PM) |
| D-045 | 2026-10-10 | A1–A4 replaced: Ari has no per-destination numbers (real trips vary too much). Generator uses RANGES in configs/generator.yaml, all [ESTIMATE]: whole-day avg speed 90–110 km/h (Ari: trucks drive 100+ most of the time), 8–11 driving h/day, 0–5 days waiting per trip, equal destination mix. Driving days = km ÷ (speed × hours). Realism checked against real days-between-visits of repeat trucks (1.4b), gap reported, not tuned yet | Unblock critical path; honest uncertainty | APPROVED by Ari |
| D-046 | 2026-10-10 | 1.4b: Messenger photos have no EXIF/filename date (known since 1.4a), so dates must come from the Messenger chat. Claude Code builds a fill-in CSV (photo file → date column, repeat trucks only, ~35 trucks); Ari fills dates from the chat; script then computes days between visits (hashed vehicle key + days only). Missing dates counted, not guessed | Smallest manual effort | APPROVED (PM) |
| D-047 | 2026-10-10 | 1.3 generator accepted: road trucks only; 5 OSRM destinations (MN–China + MN–Russia), equal mix; speed/hours drawn once per vehicle, waiting per trip; on-time = U(15k,20k) km, late = 20k + Exp(10) days, >60 → never; per-vehicle lateness ~Beta; records after end_date censored. ub_city / mixed / mine_site NOT generated → model covers MN–China/MN–Russia only; other routes fall back to B0 (fixed interval) in the app, stated on slides. Weak destination signal (medians 51–64 days) = honest finding: waiting + truck's own pace matter more than distance | 1.3 handoff | APPROVED (PM) |
| D-048 | 2026-10-10 | 1.4 cleaning accepted: reuses plates/phone normalizers; missing values kept empty (never impute phones); destination alias → transliteration → fuzzy ≥ 0.8; duplicate = same plate + date (D-043), keep most complete; odometer plausibility ≤ 1,500 km/day [ESTIMATE], ×10/÷10 repair only if ≥5× off. Slide wording must say the 100% scores are on our OWN injected noise — real data will be harder | 1.4 handoff | APPROVED (PM) |

---

## 6. Open questions

1. ~~Deadline~~ → Oct 20. ~~Instructor~~ → synthetic OK.
2. Do the photo plates match the Excel records? ("maybe" — check during 1.4a / 3.1)
3. How many real past service records exist, and in what form?
4. How many truck photos can Ari collect per week? Any fleet-number-only trucks available to photograph?
5. ~~Interval rules~~ → D-030. Still open: does oil grade change the interval? (else drop, D-034)
10. Destination table: main destinations + real round-trip days incl. waiting (Ari) + one-way km from a real map source. Replaces "trips per month" estimate (D-031)
11. Reminder window: how many days before due date is ideal? (D-036)
12. Do repeat-truck photos show odometer, or dates only? (decides if real test can use km)
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
| RISK-03 | Model only learns generator rules (circular evaluation) | High | Med | Report synthetic vs real test separately; B1 formula baseline makes the gain visible; state limitation on slide |
| RISK-04 | Docker image with torch/YOLO too big for free cloud tier RAM | Med | High | Use smallest YOLO; CPU-only torch; ONNX export; or host CV service separately |
| RISK-05 | One person, 20 days → schedule slip | High | High | Strict dates in §3; cut list; Streamlit (D-022); Ari labels photos in parallel |
| RISK-06 | Personal data (driver names, phones) leaked in repo/demo | Med | High | Never commit real data; seed demo DB with synthetic people; `.gitignore` data folders |
| RISK-07 | Live demo fails (network, cloud cold start) | Med | High | Warm up URL before defense; backup video; demo on known-good plate photos |
| RISK-09 | Licensing: Ultralytics YOLO is AGPL-3.0; pre-label weights license unstated. Fine for capstone; Geo-Expert production use may need Ultralytics commercial license or a permissive alternative | Med | Med | Decide after defense; document in model card |
| RISK-11 | Detector baseline comparison biased: GT boxes started as oim pre-labels → oim mAP50-95/IoU inflated (0.97/0.997). Compare on precision/false boxes, state on slide | — | Low | Stated in docs/cv_detection_results.md |
| RISK-10 | Real prediction test set is tiny (repeat trucks only, dates entered manually) | High | Med | Report honestly; add photos_new over time; synthetic holdout as main metric |
| RISK-12 | Critical path blocked on Ari inputs A1–A4 | — | HIT | Resolved by D-045 (ranges). ML starts ~Oct 11 → 9 days left; cut list active if 2.x slips past Oct 14 |
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

**API contract v0.2 — exact fields in `docs/api_contract.md` (source of truth); summary below**
- `GET /health` → `{status: "ok"|"error", db: "ok"|"error"}`, 200 or 503 (4.1)
- `POST /plates/recognize` (image) → `{plate_raw, plate_normalized, confidence, bbox, needs_manual}`
- `GET /vehicles/lookup?q=` (plate or phone; fleet_no in 4.2b) → `{query, match_type, normalized, vehicles: VehicleCard[]}`
- `GET /destinations` → list for dropdown (4.2b)
- `POST /services` → create service record → 201 `{service, vehicle_id, vehicle_created, company_created}`, 422/409 cases (creates vehicle/company if new); includes `destination_id` OR `destination_raw` (+ manual route) per D-039; odometer/engine hours required
- `GET /vehicles/{id}` → card: last service, usual liters, history, service_count, segment, prediction
- `GET /vehicles/{id}/prediction` → `{predicted_date, days_left, status, model_version}`
- `GET /reminders/due` → list of vehicles due soon/overdue with generated Mongolian message
- `POST /reminders/{id}/sent`
- `GET /stats/segments` → `{as_of, total, counts{new, returning, loyal, at_risk}}`

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
