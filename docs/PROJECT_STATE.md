# PROJECT_STATE — "Oil Change Predictor" (Geo-Expert LLC)

- **Version:** 2.19
- **Last updated:** 2026-10-30
- **Phase:** POST-CAPSTONE — capstone defended Oct 20, 2026. The system is being turned into Geo-Expert's real working tool (Phase 8 fixes, Phase 9 dashboard + new reminder logic).
- **Live:** https://168.144.143.203.sslip.io (demo data only; domain app.geoexpert.mn parked, see D-103)
- **Health:** 🟢 working and deployed in batches. 🟡 Not ready for real customers yet (see §5 "Before real use").

> Structure: §0–§9 = CURRENT truth. The ARCHIVE at the end is v2.18 unchanged (capstone scope, task list, decisions D-001–D-097, contracts, slide map) — read it for history; where it disagrees with §0–§9, §0–§9 win.

---

## 0. Where we are (short)

1. Capstone defended Oct 20. Geo-Expert will really use the system, so work continues.
2. Done since the defense: zoom fix, CI green again + secrets scan, daily tested backups, new camera screen, responsive dashboard with search/filters/Excel, simpler form, target km, month-based Viber reminders (last two: accepted, deploy pending).
3. Prediction changed: the ML route model is no longer shown. Drivers don't stick to one route, so the app shows **target km = last odometer + 15,000** and sends reminders at **1/2/3 months**. ML code + data collection stay; a model without route is trained later on real data.
4. Waiting on others: Artlab (accounting API test account + docs), DNS record for the domain.
5. Before real customers: personal logins (8.5), demo wipe, personal-data check, off-server backup.

### How we work (unchanged rules + new ones)
- PM chat plans, writes short task briefs (goal, deliverable, done-when, do-not), reviews handoffs. Ari pastes briefs into Claude Code (one NEW session per task) and handoffs back.
- **ONE Claude Code session at a time in the repo folder** (D-100).
- **A task is done only when CI is green on the pushed commit — handoff must include the run link** (D-099). `gh` CLI is installed/logged in so Claude Code can check CI itself.
- Deploys may be **batched** (D-101); after a batch, test each change separately on the phone.
- Ari's preferences: short prompts; state file named with version (PROJECT_STATE_vX.Y.md); PM does not build/edit files on agreement alone — waits for an explicit "do it".
- Update state: `cp ~/Downloads/PROJECT_STATE_v2.19.md docs/PROJECT_STATE.md && git add docs/PROJECT_STATE.md && git commit -m "docs: PROJECT_STATE v2.19" && git push` (repo: ~/Downloads/Capstone/oil-change-predictor).

---

## 1. Current scope (post-capstone, v2)

Internal website for Geo-Expert (phone browser + computer), login, HTTPS. Users: Ari (manager), the accountant, the oil changer.

**Record (oil changer, phone):** photo → plate read → **worker confirms plate** → form. Form = plate, odometer (or engine hours), oil grade, liters, driver name, phone. **No destination field** (D-111). Date automatic. New odometer must be higher than last (warning + confirm). Photo kept 12 months once 9.2 is built (D-109).

**Truck card / dashboard:** last service, history, **next change at target km** (last odometer + OIL_INTERVAL_KM = 15,000). Mine trucks (engine hours only): no target. No predicted date shown (D-112).

**Reminders («Сануулга»):** stages 1m/2m/3m at 30/60/90 days after the latest service; prepared Mongolian message with target km + oil changer's phone; one-tap Viber button (manual send) → «Илгээсэн»; stop list per phone; 90+ days without return = «Эрсдэлтэй» (D-113).

**Dashboard («Хяналтын самбар»):** works on computer (full width) and phone; search by plate/phone/company/fleet no.; filters (dates, company, route, oil grade); truck history; Excel export (one row per service); segment tiles; read-only due list; view only (D-108). Planned additions: photos in history (9.2), stats per day/month + company history (9.3), photo gallery by month (9.4), payments from Artlab (9.6).

**Roles (8.5, planned):** manager = everything; accountant = dashboard + Excel; oil changer = record, search, reminders. API enforces roles, not only the UI (D-110).

**Segments:** New (1 visit), Returning (2), Loyal (3+), At risk (90+ days, no return).

---

## 2. Task list — Phase 8 (fixes) + Phase 9 (dashboard & logic)

| ID | Task | Status |
|---|---|---|
| 8.0a | New UI_PASSWORD (examiners had old one) | ✅ DONE |
| 8.0b | Reset Label Studio token (seen in screenshot Oct 16) | ⏳ Ari |
| 8.1 | iPhone tap-zoom fix + «Хяналтын самбар» button on home | ✅ DONE, deployed (35fe060) |
| 8.1b | CI green again (2 models/-dependent skips allowed; was red since 7.2) + gitleaks full-history scan (82 commits, no leaks) + slide/latency files committed | ✅ DONE (aafbcf7, f4dd0c3) |
| 8.2 | Daily backups (systemd timer 03:00 UB, 14 days, /root/backups) + restore test + safe wipe_demo script | ✅ DONE (e55d2a3), installed on server, restore test OK (8 tables) |
| 8.2c | Off-server backup copy (proposal: Backblaze B2, encrypted, upload-only key) — incl. photos once 9.2 exists | ⏳ Ari yes/no |
| 8.3 | Own domain app.geoexpert.mn (DOMAIN/OLD_DOMAIN in .env, 302 redirect, runbook §11) | ✅ code (ac205f2); ⏸ server switch PARKED — DNS A record missing |
| 8.4 | Record page camera: live square view + round shutter, native-camera fallback, gallery, Mongolian, ≤2560 px resize | ✅ DONE, deployed (e1f6c36) |
| 8.4b | iPhone gallery "Зураг уншсангүй" fix (read file before input reset) + `?diag=1` shows «Алдаа» line | ✅ DONE, deployed (59d8f82). Real cause on Ari's phone = iOS Lockdown Mode (D-107) |
| 8.4c | Measure: 27 field photos, original vs 2560 px resize → plates read | TODO (optional, before real use) |
| 8.5 | Personal logins + roles + remember-me 30 days (STEP 1 plan → PM review) | ❓ brief given — status unknown, check first |
| 9.1 | Responsive dashboard + search + filters + Excel (service rows, formula-safe) | ✅ DONE, deployed (779c354, dffab12) |
| 9.1c | Engine hours column in Excel | ✅ DONE, deployed (b1578c9) |
| 9.2 | Keep photos 12 months + small photo per service in dashboard history | Brief ready (see §9) — not started |
| 9.3 | Dashboard: stats per day/month (count, liters), history per company | Brief not written |
| 9.4 | Photo gallery by month (manager + accountant) | After 9.2 |
| 9.5a | Simpler record form (no destination) + target km everywhere | ✅ ACCEPTED; 3 fixes requested before commit («—» not "None"; phone not clipped in history panel; fix browser test test_spacing_exact_values[/dashboard]) → confirm commit + CI |
| 9.5b | Month-based Viber reminders (migration 006, stages, stop list, CONTACT_PHONE) | ✅ ACCEPTED; commit + CI link pending |
| 9.5-deploy | Deploy 9.5a + 9.5b together: backup → set CONTACT_PHONE → pull → build → migrate (006) → up → phone test (form, card, reminders, stop/undo) | TODO after both CI green |
| 9.6 | Payments section + Artlab sync robot (on Artlab TEST account first) | Waiting for Artlab |
| 9.7 | gitleaks check in CI (every push) | TODO — before any Artlab credentials exist |
| 9.8 | Demo wipe (scripts/wipe_demo.sh, typed confirmation) | When real use starts |
| 9.9 | README polish for portfolio (problem, key numbers, screenshot, stack, honest note) | Later |

---

## 3. New decisions (D-098 →)

| ID | Date | Decision | Status |
|---|---|---|---|
| D-098 | 10-21 | Project continues after the capstone: Geo-Expert uses the system for real. Droplet kept | APPROVED by Ari |
| D-099 | 10-22 | A handoff is DONE only with CI green on the pushed commit (run link in handoff). CI had been red unnoticed from task 7.2 to 8.1 | APPROVED (PM) |
| D-100 | 10-22 | Only one Claude Code session at a time in the repo folder (parallel sessions mixed commits) | APPROVED |
| D-101 | 10-27 | Batch deploys allowed; each task still committed with CI green; after a batch, test each change separately | APPROVED by Ari |
| D-102 | 10-22 | Repo stays PUBLIC (portfolio). Secrets only in server .env; gitleaks history scan clean; Artlab credentials never in git. Link the repo in the portfolio, not the live app | APPROVED by Ari |
| D-103 | 10-22 | Domain = app.geoexpert.mn via DOMAIN in .env; old sslip.io address 302-redirects (switch to 301 after 2 weeks stable). PARKED: DNS A record (app → 168.144.143.203) not added; geoexpert.mn name servers = ns1–4.dns.mn (probably Datacom — unverified). geoexpert.mn website is WordPress elsewhere — never put the app under a path | APPROVED; ⏸ waiting DNS |
| D-104 | 10-22 | Backups: daily pg_dump at 03:00 UB (systemd timer, Persistent), kept 14 days, each checked; restore test proved on server. Off-server copy pending (rec. Backblaze B2, encrypted, upload-only key). Keep .env values in a password manager (not in any backup) | APPROVED; off-server ⏳ |
| D-105 | 10-22 | iPhone zoom fix = 16 px inputs + touch-action: manipulation; never maximum-scale / user-scalable=no | APPROVED |
| D-106 | 10-22 | Record camera: in-page live view (rear) + round shutter, automatic fallback to native camera button, gallery; browser resizes to ≤2560 px JPEG, EXIF/GPS stripped. Worker confirms the plate before lookup (replaces D-072 auto-lookup). Search page camera unchanged (Later) | APPROVED by Ari |
| D-107 | 10-28 | iOS Lockdown Mode blocks the in-browser photo processing and Streamlit's icon font. Ari excludes the site in Safari (aA → Website Settings). Workers' phones expected without Lockdown. Later: if browser processing fails, upload the original file instead | NOTED |
| D-108 | 10-28 | Dashboard (9.1): ≥1024 px full width, phone one column, other pages stay 480 px; search contains-match in Python (D-043), phone from 3 digits; filters; Excel = one row per matching service, all text written as text (no formulas), engine-hours column; CSV toolbar hidden (one export path); view only | APPROVED |
| D-109 | 10-28 | Photos are KEPT 12 months (reverses "photos not stored", D-065): saved services only, resized JPEG without EXIF, Docker volume, shown only via login-protected endpoint, daily deletion after 12 months; record text «Зураг 12 сар хадгалагдана». Not built yet (9.2) | APPROVED by Ari |
| D-110 | 10-29 | Roles: manager all; accountant dashboard + Excel; oil_changer record, search, reminders. API checks roles. 30-day remember-me (token hashed in DB), 5 wrong → 15 min lock, saved_by on service, CLI user_add/user_disable, shared UI_PASSWORD removed, no admin UI | APPROVED (plan review pending) |
| D-111 | 10-29 | Destination removed from the record form (Ari's brother: drivers don't keep one route). Overrides D-033 and the D-042 one-of rule. DB columns + old data kept | APPROVED by Ari |
| D-112 | 10-29 | No predicted date shown. Next change = last odometer + OIL_INTERVAL_KM (15,000, same for every oil; setting). Mine trucks: no target, no reminders for now. ML model + prediction code kept unused; a model WITHOUT route is trained later on real data and compared with the simple rule — winner decided by data | APPROVED by Ari |
| D-113 | 10-29 | Reminders: stages 1m/2m/3m at 30/60/90 days after latest service; only highest stage reached; each once (UNIQUE service_id, stage); «Илгээсэн» sends its stage; new service resets; at risk = 90+ days everywhere (replaces D-007/D-074 rule); stop list per phone with undo; CONTACT_PHONE = oil changer's number (setting); messages = Ari's 3 texts (thank-you → 2-month check → change at target km, "we come to you"); nothing sent automatically. Replaces ML reminder timing (D-036, D-066 send-date rule) | APPROVED by Ari |
| D-114 | 10-27 | Artlab plan: our code only reads (fixed allow-list of read requests, others refused + tested). Artlab provides sales + customer settlement data; API access is full rights only. Develop on Artlab TEST account first. Asked Artlab: IP restriction to our server, separate API user, activity log, docs, plate/phone fields, lump-sum payment allocation. Real connection needs OK from whoever is responsible for accounting. Individuals' register numbers not requested | APPROVED |
| D-115 | 10-29 | Automatic Viber sending rejected for now: chatbot costs EUR 100/month + per message and can only message subscribers. One-tap button stays. SMS gateway = alternative later | APPROVED by Ari |
| D-116 | 10-29 | Auto-km for new routes (Nominatim + OSRM) → Later; less important after D-111 | APPROVED |

---

## 4. Artlab integration (9.6) — agreed design

- **Flow:** oil changer works as today (our app + Artlab receipt with plate + phone). A sync robot on our server logs in to Artlab every 30 min (credentials only in .env), copies recent receipts + all still-unpaid ones into our DB.
- **Matching:** normalized plate (normalize_plate) + receipt date within ±1 day of the service; phone = fallback. Never "latest receipt".
- **Statuses per service:** Төлсөн (paid) · Төлбөр хүлээгдэж буй (unpaid, amount left + days waiting) · Баримтгүй (no receipt by end of next day) · Шалгах (2+ matches, a person decides).
- **Tables (sketch):** artlab_receipts (artlab_id, receipt_date, plate_raw, plate_normalized, phone, amount, paid_amount, synced_at) + service_payments (service_id PK, artlab_id, status CHECK 4 values, checked_at). Unpaid re-checked every run → credit payments switch to paid by themselves.
- **Risk:** if Artlab books lump-sum payments only against the company balance, show paid/owes per company instead of per service.
- **Status:** Artlab CTO replied (sales + settlement data possible; no read-only access; test account offered). Ari replied with safeguard questions. Waiting.

---

## 5. Before real use (checklist)

1. 8.5 logins + roles done and deployed.
2. Personal-data check: driver names, phones, photos on a server in Singapore (open question).
3. Off-server backup (8.2c), including photos once 9.2 exists.
4. CONTACT_PHONE set on the server.
5. Demo wipe (9.8) — Ari's 2 test trucks go too (re-enter if real).
6. Drivers can opt out (stop list exists in 9.5b).

---

## 6. Server & deploy facts

- DigitalOcean Singapore, 1 vCPU / 2 GB, Ubuntu 24.04. `ssh root@168.144.143.203`, repo `~/oil-change-predictor`, `alias dc='docker compose -f docker-compose.prod.yml'`.
- Prompts: `root@ubuntu…#` = server, `➜` = Mac.
- Standard deploy: `git status --short` (must be empty) → `git pull && dc build && dc run --rm api python -m scripts.migrate && dc up -d` → `dc ps` (api/db/ui healthy, caddy Up) → `git log --oneline -1`.
- DB change? Run `systemctl start ocp-backup.service` first.
- Backups: /root/backups, `journalctl -u ocp-backup`, `scripts/restore_test.sh`.
- .env keys (values never in git): UI_PASSWORD (changed), DOMAIN, OLD_DOMAIN, GEO_EXPERT_PHONE, CONTACT_PHONE (to set), OIL_INTERVAL_KM (default 15000), later Artlab credentials.
- Data now: demo seed + 2 trucks/1 company added by Ari (42 trucks, 107 services, 7 companies).
- Server DNS had a one-time resolver timeout (Oct 22); fine since.

---

## 7. Open questions

1. Backblaze B2 for off-server backups — yes/no?
2. Who manages geoexpert.mn DNS (accountant's invoice / website builder)? Add A record `app` → 168.144.143.203.
3. Personal-data law for driver data + photos abroad.
4. 8.5 — running, finished, or not started?
5. Artlab: test account, API docs, answers on IP restriction / separate user / activity log / plate+phone fields / lump-sum payments.
6. Mine trucks: engine-hours interval (skipped for now).
7. Optional: different orange text when the photo itself failed («Зураг уншигдсангүй — дахин авах эсвэл гараар оруулна уу»).
8. Ari proofreads Mongolian wording of 9.5a/9.5b screens.
9. 8.0b Label Studio token reset.

---

## 8. Open risks

| ID | Risk | Mitigation |
|---|---|---|
| RISK-06 | Personal data leak (phones, photos, Excel export) | Roles (8.5) before real users; export only manager + accountant; photos via login-only endpoint; gitleaks in CI; public repo holds no data |
| RISK-09 | Ultralytics YOLO AGPL-3.0 | Repo public helps; decide license before commercial scaling |
| RISK-22 | Artlab credentials = full write access to accounting | Read-only allow-list in our code + tests; IP restriction; separate API user; test account first; approval before production |
| RISK-23 | Backups only on the droplet | 8.2c off-server copy |
| RISK-24 | Lower plate reading after 2560 px resize on whole-truck photos | 8.4c measurement |
| RISK-25 | Simple target-km rule may be less accurate than ML for some trucks | Compare on real data after 2–3 months (D-112) |
| RISK-26 | Reminders list long on real data (every truck 30+ days) | Expected by design; watch workload |

---

## 9. Ready briefs + Later list

**9.2 brief (ready):**
```
TASK ID: 9.2 — Keep each saved service photo 12 months (D-109).
- On save: keep resized JPEG (≤2560 px, EXIF stripped), linked to the service (migration).
- Docker volume on server; shown only via login-protected endpoint, never a public URL.
- Daily job deletes photos older than 12 months (timer like backups).
- Record text «Зураг хадгалагдахгүй» → «Зураг 12 сар хадгалагдана».
- Dashboard truck history: small photo per service (tap → full size); «Зураггүй» when none.
- Report disk use per 100 photos; propose photo backup (do not build).
DONE WHEN: tests pass, CI green (gh run link); runbook section in deploy.md.
DO NOT: keep photos of retakes/unsaved attempts; commit photos.
```

**Later list (merged):** admin edit page (view/edit/delete records); search-page camera like record page; auto-km for new routes (D-116); automatic Viber/SMS sending (D-115); new ML model without route on real data + comparison; promote/retrain plate reader with kept photos (field-test set, segmentation fix for 4/27 plates); fallback upload of original photo when browser processing fails (D-107); read-only demo mode for sharing; README polish; Next.js frontend; data drift monitoring + continuous training; offline mode for mine sites; LLM assistant for drivers; oil lab reports.

---
---

# ARCHIVE — v2.18 (capstone, unchanged; headings demoted)

### 1. Agreed scope (frozen — changes need Ari's approval)

**Form (D-061):** internal company website for Geo-Expert only (opened in the phone browser) — NOT a native mobile app. Login required, HTTPS (needed for browser camera). Instructor gets a demo login.

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

**Stack:** Python 3.11, pandas, scikit-learn, XGBoost, SHAP, Ultralytics YOLO (yolo26n) + EasyOCR vs custom PyTorch char CNN, FastAPI, PostgreSQL (local Docker / Supabase cloud), Streamlit frontend (D-022), Docker, GitHub Actions, cloud host TBD in 6.3.

---

### 2. Requirement checklist (from AI Academy Asia slides)

Status: ✅ covered by plan · 🟡 covered but at risk · 🔴 gap — action needed

| # | Requirement (source) | Maps to | Status | Notes / action |
|---|---|---|---|---|
| R1 | Real, uncleaned data; API / web scraping (slide "Хичээлийн даалгавар vs Capstone") | F1 records, F2 test set | 🟡 | Training is synthetic. Need: (a) real messy Geo-Expert records as test set, (b) at least one real external API, (c) ✅ instructor confirmed synthetic training is OK. Real Excel records available. |
| R2 | Multi-model comparison + hyperparameter tuning | F2 model, DL | ✅ | B0 fixed interval + B1 route formula + Ridge + Random Forest + XGBoost; RandomizedSearchCV with grouped/time-aware CV. |
| R3 | F-Score, Latency P99, inference speed, business ROI | F2, Backend, Slide 11 | 🟡 | F-score needs a classification view → derived from status buckets (OK/due soon/overdue). P99 measured by load test. ROI needs Ari's real business numbers. Business metric = reminder hit rate (D-036). |
| R4 | FastAPI, CI/CD, web interface, Cloud; not local, working link | Backend, Frontend, Deploy | 🟡 | YOLO + torch images are heavy for free tiers — memory risk. See RISK-04. |
| R5 | Core ML metrics: RMSE (regression), F-Score, ROC-AUC, Feature Importance | F2 | ✅ | RMSE, MAE, R² primary; F1 + ROC-AUC on derived "overdue" class. |
| R6 | CV track: custom CNN vs transfer learning; mAP, IoU, Accuracy | DL | 🟡 | 3.3 done (EasyOCR vs custom char CNN, docs/cv_ocr_results.md, commit 687f0e9). PM review of numbers pending. |
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

### 3. Phase plan (v2.4 — re-planned 2026-10-16, D-081/D-082)

All tasks run on the Mac, branch main (D-080). One Claude Code session per task.

| Date | Mac (main) | Ari |
|---|---|---|
| Fri Oct 16 | ✅ 3.6 + 3.6b CNN → 6.1+6.2+4.4b deploy prep → 1.6 part 1 (if route list arrives; else 1.6 CUT) | Route list; hosting + domain; labels ✓/✗; commit PROJECT_STATE v2.14 |
| Sat Oct 17 | 1.6 part 2 (retrain + evaluate + SHAP + export), 5.3d, 3.5 segmentation fix ONLY if 6.1 done. **FEATURE FREEZE end of day.** Local backup video | ROI numbers (price ₮ + margin %); server ready |
| Sun Oct 18 | **6.3 cloud deploy** + 6.4 P99 timed script + cloud demo video | Test on phone |
| Mon Oct 19 | Deck final; 2 rehearsals; warm up cloud URL | — |
| **Tue Oct 20** | **Defense** | |

**Cut list (in this order):** 0) 3.5 plate fallback + 5.3d hint (first to cut if behind, D-082); 1) 1.5 external API → covered by 1.6 OSRM API script if 1.6 runs, else drop; 2) 5.4 dashboard → segment counts + due list inside lookup screen; 3) 6.4 Locust → simple timed script; 4) 2.5 calibration → if dates not filled by Oct 14, report "ML ≈ B0 on synthetic" honestly (D-050); 5) 1.1c name_mn → UI shows English destination names.
**Never cut:** cloud live demo, baseline comparison, SHAP, honest synthetic-vs-real reporting, backup video.

**Commit rule (RISK-14):** every task ends with tests run + commit + push before the handoff. Uncommitted work = not done.

### 4. Task list

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
| 1.4b | Service dates for repeat trucks (D-046) | Data Eng + Ari | ✂ CUT Oct 12 (D-063) — dates not findable in Messenger. Script stays in repo for future use |
| 1.1b | Schema migration: destination on service record + destinations reference table (name, route category, one-way km, round-trip days, source) | Data Eng | ✅ DONE Oct 6 — migration 001 (plain SQL up/down, psql --single-transaction), 7 destinations seeded, nullable destination_id + destination_raw, 16 tests (112 pass locally; DB tests skip in CI until 6.2), data_dictionary v0.2 |
| 1.1c | Migration 002: name_mn for destinations (D-040, D-062) | Data Eng | ✅ ACCEPTED Oct 12 — contract v0.6 (name_mn nullable); UB city + Other unlabeled → migration 004 in 6.1 (labels pending Ari: "Улаанбаатар хот" / "Бусад") |
| 1.2 | Synthetic rules (1.2a): research + Ari inputs → docs/synthetic_rules.md → Ari marks ✓/✗. Redesigned per D-033–D-036. First draft (Oct 5) was lost/never saved; rewritten from scratch Oct 6 | Data Eng + Ari | ✅ DRAFT DONE (OSRM distances, 7 variations, 13 noise rules, 16 open items) → ⏳ BLOCKED on Ari: A1–A4 + ✓/✗ |
| 1.3 | Synthetic generator with noise injection — unknowns as config ranges (D-045) | Data Eng | ✅ DONE Oct 10 — 500 trucks, 3,845 clean / 3,927 dirty rows, seed 42 reproducible, every param tagged; days to next change p5 36 / median 58 / p95 88; real comparison pending 1.4b |
| 1.4 | Cleaning script (tested on dirty file + noise_log) | Data Eng | ✅ DONE Oct 10 — 3,927 → 3,845 rows; precision/recall 100% on own noise (circular — see D-048); 0 truck identity errors; 274 tests pass |
| 1.4c | Real record intake template / Excel column mapping | Data Eng | LATER (post-defense; not needed for real test, which uses 1.4b intervals) |
| 1.5 | External API evaluation (1 source) | Data Eng | TODO |
| 2.1–2.3a | EDA + `features.py` + vehicle/time split + baselines B0, B1 (one session; clean file first, switch to cleaned later) | ML Eng | ✅ DONE Oct 10 — 6 EDA charts, features.py, split (46 test trucks / 202 visits), B0 MAE 12.3 hit 9.4%, B1 worse (MAE 17.8); history features weak (|r| ≤ 0.16); 313 tests pass |
| 2.3b | Verify B1 km/day includes waiting; Ridge / RF / XGBoost + RandomizedSearchCV; reminder buffer tuned on validation (not test) | ML Eng | ✅ DONE Oct 10 — B1 not a bug (route switching V6); test MAE: B0 12.3, Ridge 11.9, RF 12.1, XGB 12.1, B1 16.8; no model beats B0 beyond noise (95% CI incl. 0); buffer raises B0 hit 9.4% → 14.9%; 322 tests pass |
| 2.5 | Calibration check vs real 1.4b intervals (D-050) | ML Eng | ✂ CUT (D-063) — moved to Later: calibrate once the live system has collected real dated services |
| 2.4 | SHAP (Ridge + XGBoost) + D-038 variation-off check + derived status F1/ROC-AUC (D-007) + reminder metric with D-051 window (1–14 days) | ML Eng | ✅ ACCEPTED Oct 12 (commit pending) — SHAP additive (err ≤1e-4); macro F1 B0 .61 / B1 .56 / Ridge .63 / RF .63 / XGB .64; ROC-AUC overdue .50/.63/.68/.65/.65; hit rate 1–14 d B0 33.7% / B1 21.3% / Ridge 36.6% (+3.0, CI −3.9..+9.2) / RF 35.1% / XGB 35.6%; D-038 "needs a look" (D-059); serving = Ridge, buffer 9 d |
| 2.4b | Replace n_prior_visits with has_history 0/1 in features.py (censoring artifact, D-058); retrain; rerun evaluate + D-038; refresh ml_results.md (1–14 window) | ML Eng | ✅ ACCEPTED Oct 12 (commit pending Ari OK) — MAE unchanged (Ridge 11.9, B0 12.3); hit 1–14 Ridge 37.6% vs B0 33.7% (+4.0, CI −4.0..+11.2 → ML ≈ B0); buffer Ridge 7; top SHAP now km_per_day_hist, past_late_share, one_way_km; D-038 gain +0.31 (CI +0.08..+0.58) → D-060; 340 tests pass |
| 2.1b | notebooks/01_eda.ipynb filters on n_prior_visits → KeyError on rerun; one-line fix | ML Eng | LATER (before slide charts are regenerated) |
| 3.1 | Labeling setup (Label Studio local, box + plate_type + plate_text) | CV Eng | ✅ DONE (export tested) |
| 3.1c | Pre-label with pretrained detector (oim YOLOv9-t, thr 0.6) → import as predictions | CV Eng | ✅ DONE |
| 3.1d | Ari checks boxes + types Cyrillic plate text | Ari | ✅ DONE — 183 labeled, 9 skipped, 135 trucks, 35 repeat trucks (83 photos), all 183 match 4 digits + 3 Cyrillic |
| 3.2 | Vehicle-grouped split + YOLO fine-tune + eval vs pretrained oim | CV Eng | ✅ DONE — test (27 img / 20 trucks): yolo26n mAP50 0.991, P 0.93, R 1.00, 21.5 ms MPS; oim P 0.73 (10 false boxes) |
| 3.3 | Recognition: pretrained OCR vs custom CNN — REDUCED scope: small CNN on character crops, same split.json | CV Eng | ✅ DONE (commit 687f0e9) — EasyOCR vs custom char CNN, docs/cv_ocr_results.md + 2 figures. PM review of metrics pending (no handoff received) |
| 3.4 | Normalization + confidence fallback (pulled forward: independent of synthetic data) | CV Eng | ✅ DONE Oct 6 — read_plate() + normalize_plate(); 21 letters seen; 183/183 labels pass format; 291 tests pass |
| 4.1 | FastAPI skeleton + DB + migrations (decide: keep plain SQL or move to Alembic) | Backend Eng | ✅ DONE Oct 6 — src/api (config, db, /health 200/503), Dockerfile (310 MB, non-root), compose "api", requirements-api.txt; 130 tests pass locally |
| 4.2 | Endpoints per contract (§8) — data endpoints only (lookup, services, vehicle card, segments); prediction field null until 4.3 | Backend Eng | ✅ DONE Oct 6 — 4 endpoints, plates.py (spaces/case only), contract docs/api_contract.md v0.2, 204 tests pass locally |
| 4.2b | GET /destinations (dropdown, name_mn when 002 lands), lookup by fleet_no, case/space-insensitive company match, same-vehicle same-day duplicate guard (409 + force flag) | Backend Eng | ✅ DONE Oct 6 — api_contract v0.3, src/api/matching.py, 232 tests pass |
| 4.3 | Model + CV serving | Backend Eng | ✅ ACCEPTED Oct 12 (commit pending Ari OK) — prediction in card + GET /vehicles/{id}/prediction (method ridge/b1/b0, fallback_reason, model_version); POST /plates/recognize = yolo26n + char CNN, both ONNX/onnxruntime CPU, no torch in image; 27 test photos: 19/27 exact, 9 auto-filled correct, 18 → manual, 0 wrong auto-fills (= 3.3); recognize median 50 ms / p95 106 ms; RAM idle 190 MB, after use 308 MB; image 1.05 GB unpacked; contract v0.4; 469 tests pass |
| 4.4 | Segments + reminders (D-065, D-066) + small fixes: fleet_no dash-insensitive; HEIC upload | Backend Eng | ✅ ACCEPTED Oct 12 (commit pending Ari OK) — GET /reminders/due, POST /reminders/{service_id}/sent (idempotent, table reminders_sent, migration 003); at_risk from served prediction; buffers from model files (ridge 7, B0 12, B1 1); message 130–135 chars; contract v0.5; 500 tests pass. Open: Ari approves message wording + real contact phone (D-068) |
| 5.1–5.3 | Streamlit skeleton + Recording mode + Lookup/vehicle card — iMac, branch `ui` | Frontend (iMac) | ✅ ACCEPTED Oct 12 (commit to ui pending Ari OK) — Mongolian UI, HTTP-only; record (pre-fill, fresh odometer + destination, free-text destination + route, 409 → force); lookup by plate/phone/fleet no.; card null-safe; login via UI_PASSWORD; views/ not pages/ (login bypass found + regression test); 58 UI tests; verified in Chrome 390×844, no horizontal scroll |
| 5.3b | Wire recognize + prediction (iMac T2) | Frontend (iMac) | ✅ ACCEPTED Oct 12 — main (v0.5) merged into ui; photo → recognize automatically → clear read looks up at once, needs_manual pre-fills plate_raw and waits; any recognizer error → manual entry; card prediction tinted by status + progress bar + method note; 67 UI tests, 565 total. Live clear-read path still to verify on the Mac (ONNX files not on iMac) |
| 5.3c | Design v2 (iMac T3) | Frontend (iMac) | ✅ ACCEPTED (caa6789) — all views guarded by login; «Сүүлд үзсэн» session-only, no phone stored |
| 5.4 | Manager dashboard (iMac T4) | Frontend (iMac) | ✅ ACCEPTED (21124d2 = DEMO-KNOWN-GOOD) — segment tiles, due list «Илгээх» / «Эрсдэлтэй», message + copy, «Илгээсэн» idempotent. AT_RISK_GRACE_DAYS=7 duplicated in UI → removed after D-074 |
| T5 | UI quality + src/ui/Dockerfile (iMac) | Frontend (iMac) | ✅ ACCEPTED (429fc09) — non-root image 180 MB, ~60 MB RAM; docs/ui_run.md (§3 prod compose values for 6.1); 592 passed / 3 skipped |
| T6 | Ari's UX changes (iMac) | Frontend (iMac) | ✅ ACCEPTED by PM on summary (D-073); handoff file to be pasted for record |
| T7 | Design polish (lighter fonts, fewer borders) — visual only | Frontend (iMac) | ❓ status unknown — `ui` retired (D-080); check origin/ui for unmerged commits in UI-RETIRE |
| UI-RETIRE | Merge any remaining `ui` commits into main, delete `ui` (local + origin), rewrite docs/IMAC_BRIEFING.md as backup guide, update CLAUDE.md | Mac | TODO (origin/ui still exists, seen Oct 16) |
| 5.9 | Merge ui → main + local demo prep | Integrator (Mac) | ✅ DONE Oct 13 — merge 32814da, CI green; demo path 14/14 at 390 px; docs/demo_runbook.md; plate reading end-to-end = 4.3 results (27/27 detected, 9 auto-read, 0 wrong) |
| 5.9b | HOTFIX home navigation (Сануулга card not clickable after T7) | Mac | ✅ DONE Oct 13 — st.button + st.switch_page; «Сүүлд үзсэн» dead spot fixed; 0 console errors; 654 tests |
| 5.3d | Camera hint «Дугаарыг 2–3 метрээс, урдаас нь авна уу» (+ plate frame if easy) | Mac (iMac-OK) | ❓ status unknown — no handoff received; run before freeze or cut. Ari also instructs workers to photograph closer |
| 0.7 | Repo cleanup (branch chore/cleanup): placeholders removed, README rewritten (run, demo, honest results), pretrained .pt → models/pretrained/, parent CLAUDE.md → ~/Downloads/Capstone/old/ | Mac | ✅ MERGED Oct 16 (PR #1, main = 8d9af2b, includes 3.6a) |
| 7.0 | Progress-check demo (local) | Ari | ✅ DONE Oct 13 — went well |
| 3.5 | Plate fallback for small plates / harsh light: detect at 1280 on no_plate; wider crop + upscale + CLAHE on empty/low_confidence; tune on val, report test, wrong auto-fills must stay 0; time-box 3 h. Note: 4/27 test plates fail segmentation ("empty") — the main target | CV Eng | TODO — cut #0 if behind |
| 3.6a | Pre-label 44 new photos ("More photos") in Label Studio project plates_new with fine-tuned yolo26n (D-083) | CV Eng | ✅ ACCEPTED Oct 16 — 41/44 boxes at ≥0.6, 26 ms/photo CPU, ONNX = .pt (0 diffs); src/cv/ls_setup.py; docs/labeling_howto.md |
| 3.6 | Retrain char CNN on old + new labels (YOLO unchanged, D-081) | CV Eng | ✅ DONE Oct 16 — v1 KEPT (D-086). 42 photos after dedupe (D-084), chars 784 → 994; old test (27): exact 19 → 20, auto-filled 9 → 14, wrong 0 → 0; McNemar exact p = 1.0; v2 saved as char_cnn_v2.onnx; 675 tests pass. Field tests: none exist |
| 3.6b | Char CNN: field augmentation + val-only tuning (epochs, strength, per-model threshold); test once; target D-087 | CV Eng | ✅ DONE Oct 16 — target NOT met: val winner = v2 recipe (no aug, 60 ep, thr 0.60, weights = v2); test v1 9 / v2 14 / v3 14 of 27 correct auto-fills, 0 wrong (need 18) → v1 stays. Augmentation: more exact reads on val but confident errors → needs thr 0.70–0.95 → fewer safe auto-fills. Ceiling 23/27 (4 plates fail segmentation). Recognizer reads threshold from char_cnn_version.json (D-089). 693 tests pass |
| 3.6c | Fix ocr_extend.py section marker "## Task 3.6" (prefix of "## Task 3.6b" → re-running compare deletes the 3.6b section) | CV Eng | LATER — 5 min, before anyone re-runs `ocr_extend compare` |
| 5.6 | Phone readability fix + redeploy | Frontend | ✅ DONE Oct 19 — Montserrat (T7) replaced by system font (San Francisco), body 400 / headings 600, greys darkened to WCAG AA on 8 screens incl. Lockdown simulation; Ari confirmed readable on iPhone. Commits 6fd1e34, 8cf5576. Open: icons show stray letters with Lockdown ON (workaround: Lockdown off for this site); 'Take Photo' from upload button not yet confirmed on device |
| 3.6d | Serve char CNN v2 as a product decision (override) | CV Eng | ✅ DONE Oct 19 — served char_cnn.onnx = v2 (ebd12a4c), threshold 0.60 (val-chosen in 3.6b); v1 kept as char_cnn_v1.* + rollback command in handoff. Test (27): exact 19 → 20, char acc .810 → .815, correct auto-fills 9 → 14, wrong 0 → 0, manual 18 → 13; McNemar p = 1.0. Gain is mostly higher confidence, not better reading → worker still confirms every plate. Deployed (api restarted only). D-097 |
| 5.7 | Phone photo path | Frontend | ✅ Upload from iPhone works (used for demo); live camera blocked on Ari's iPhone (browser/Lockdown settings) — not fixed. 5.7b EXIF-orientation check: status unknown |
| 7.3 | Defense | Ari | ✅ DONE Oct 20 — went well |
| 1.6 | New MN–China / MN–Russia destinations (OSRM API, migration 005, regenerate, retrain, evaluate, SHAP, export) | Data + ML Eng | ✅ DONE Oct 17 — part 1 accepted: 4 routes (Ганцмод from Tavan Tolgoi 247 km, Сэхээ 928, Улаан-Үд 578, Кош-Агач 1,786; OSRM, crossing as waypoint, cache, no network in tests), migration 005, 11 destinations, N8 two-reading carve-out. Part 2: Ridge 12.2 → 12.3 MAE, B0 12.3 → 13.3 (gap grows from baseline weakness, not model gain). Part 2 handoff + commit status to confirm. D-092 |
| 2.9 | Noise floor + vehicle-grouped CV tuning + 80% prediction range; test once | ML Eng | ✅ DONE Oct 17 — oracle test 11.34 · Ridge 12.30 · B0 13.28 · B1 17.19; Ridge closes ~half the reachable gap (vs B0 +0.98 d, CI +0.38..+1.55). Tuned best CV gain +0.06 < 0.3 → NOT kept (D-093). Range: train OOF residual p10–p90, coverage 83.2% on test, width ~40 d; API v0.9 range_low/high_date. serving_params re-exported (9 routes, B0 53 d). 781 tests. D-094 |
| 5.5 | One-tap «Viber-ээр илгээх» (viber://forward, pre-filled Mongolian text) + «Илгээсэн үү?» → POST /sent | Frontend | ✅ ACCEPTED Oct 16 (D-091) — 740 tests; real-phone check pending (Android empty-tab risk) |
| 7.2a | Live-demo photo test: print the demo plate "1001 УБА" on paper, check the detector + CNN read it (detector was trained on real truck plates — may fail); fallback = demo photo file or manual entry | Ari + PM | TODO — by Oct 16 |
| 4.5 | Demo seed (RISK-06) | Data Eng | ✅ ACCEPTED Oct 12 — 40 trucks / 105 services placed with the served model; as of seed day: new 8 / returning 11 / loyal 17 / at risk 4, due list 7, methods ridge 29 / b1 9 / b0 2; refuses non-empty DB; demo path in docs/demo_data.md; 532 tests pass |
| 5.0 | UI design mockup (Design canvas, phone flow: login, home, record, search, card) — Ari + PM iterate, then addendum to iMac | PM + Ari | ▶ IN REVIEW (v2: modern look, simplified card) |
| 6.1 | Deploy prep (host-agnostic): migration 004 (labels) + apply-missing-migrations script (D-041, D-069) + docker-compose.prod.yml (db + api + ui + Caddy HTTPS, models mount, export_serving step) + runbook docs/deploy.md | Backend Eng | ✅ ACCEPTED Oct 16 (with 6.2 + 4.4b) — prod compose (db/api/ui/Caddy 2.11.7, only Caddy exposed), scripts/migrate.py (idempotent), migration 004, docs/deploy.md, CI with Postgres + UI tests + image builds; local https://localhost OK; RAM ≈ 430 MiB; 731 tests. D-090 |
| 6.2 | CI: Postgres service so DB tests run + requirements-ui.txt so UI screen tests run; build API image; known flake: exit 134 after all tests pass (native teardown) → handle | Backend Eng | ▶ BRIEF RE-ISSUED Oct 12 (with 6.1 + 4.4b) |
| 4.4b | Add `segment` to GET /reminders/due items (contract v0.7) so the UI drops its copy of the D-007 rule | Backend Eng | ▶ in 6.1 brief (status unknown) |
| 6.3 | Deploy: login + HTTPS + domain (D-061) | DevOps | ✅ DONE Oct 19 — DigitalOcean Singapore 1 vCPU / 2 GB, Ubuntu 24.04, ufw 22/80/443, key-only SSH, swap, Docker 29.9.1; repo via read-only deploy key; models rsynced (byte-identical); .env root-only (secrets typed by Ari); migrate 001–005 (2nd run no-op); seed as-of 2026-10-20: 40 trucks / 105 services, new 8 / returning 11 / loyal 17 / at risk 4, 8 due; Let's Encrypt via sslip.io. Runbook fixes: openrsync path bug, real clone steps, 8 due. Phone test OK (mobile data). Test truck 1001УАМ (manual entry, not auto-fill) deleted |
| 6.4 | P99 latency | DevOps | ✅ DONE Oct 19 — server (private net, 200 calls): plate read P50 430 / P99 1,105 ms (model work P99 464 ms; synthetic photo, CNN step not included), prediction P99 111 ms; /health over HTTPS from UB home Wi-Fi P99 463 ms (ping ~111 ms → mostly network). ~8× slower than Mac (1 shared vCPU). Not measured: concurrent users. docs/latency_6_4.json, deploy.md §10 |
| 7.1 | 13-slide deck | PM + Ari | ▶ v1 exists (PDF, 13 slides, follows course structure); corrections sent (slides 1,2,3,4,5,7,8,9,13); slide 12 costs: MVP ≈ $15 (DO 2 GB $12 + backup $2.40), Mid ≈ $45 + SMS, Enterprise $300+ [ESTIMATE]; ROI waits on Ari price + margin |
| 7.1b | Teacher request: 3 professional-but-understandable architecture diagrams — DB architecture (slide 3), ML + CV training architecture (slide 5), system architecture + MLOps (slide 8); same colours, ≤8 boxes, real tool names + Mongolian labels | PM + Ari | TODO — after freeze, Sun/Mon |
| 6.5 | TCO 3 tiers + ROI | PM + Ari | TODO |
| 7.2 | Demo script + backup video + rehearsals | Ari | TODO |

---

### 5. Decisions log

| ID | Date | Decision | Reason | Status |
|---|---|---|---|---|
| D-001 | 2026-09-30 | Scope frozen as in §1 | Agreed with Ari | Final |
| D-002 | 2026-09-30 | Train on synthetic data; real records only for test/validation | Not enough real history | Final (instructor approved) |
| D-003 | 2026-09-30 | Oil lab reports out of scope | Geo-Expert not taking lab reports now | Final |
| D-004 | 2026-09-30 | Driver + phone stored per service record, not per vehicle | Drivers change between trips | Final |
| D-005 | 2026-09-30 | Vehicle identifier has type: `plate` or `fleet_no` | Mine haul trucks may lack plates | Final |
| D-006 | — | Primary ML target: `days_to_next_change` (regression). Mine-site vehicles may use engine hours → generator must support hour-based intervals | Date is what the reminder needs | APPROVED (PM, Oct 10 — used in 2.1–2.3a) |
| D-007 | — | Status buckets: OK (> 14 days left), Due soon (0–14 days), Overdue (< 0). At risk = overdue + 7 days grace, no new record | Needed for F1 and segments | APPROVED as default (adjustable parameter; Ari may change later) |
| D-008 | — | CV comparison: pretrained OCR vs small custom PyTorch CNN char classifier (both after YOLO detection) | Satisfies "custom CNN vs transfer learning" (R6) | IMPLEMENTED in 3.3 (EasyOCR vs char CNN) |
| D-009 | — | Splits grouped by vehicle (no same truck in train and test), time-ordered for ML | Prevent leakage | APPROVED (PM, Oct 10 — used in 2.1–2.3a) |
| D-010 | — | Reminder delivery for demo: generate message + mark "sent" + copy/share button; real SMS gateway = Later | Gateway cost/contract unknown | APPROVED (PM, Oct 12 — D-066) |
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
| D-049 | 2026-10-10 | Baselines: official B1 uses 17,500 km (expected ACTUAL behavior, D-030) — we predict when the truck really returns; 15,000 km shown as sensitivity. B0 = median train interval. Reminder hit window 3–7 days early (default until Ari decides, D-036); buffer tuned on validation only | Fair baseline; 2.1–2.3a handoff | APPROVED (PM) |
| D-050 | 2026-10-10 | If ML ≈ B0 on synthetic data: do NOT inflate generator variation to make ML win. Only calibrate generator to REAL repeat-truck intervals (1.4b): if real trucks are consistent per vehicle, raise per-vehicle variation to match real spread — documented before/after. Otherwise report "ML ≈ baseline on synthetic; value grows with real history" honestly | Integrity; RISK-03 | APPROVED (PM) |
| D-051 | 2026-10-10 | Serving model = Ridge (not XGBoost): validation MAE tie (12.4 vs 12.5, within noise) → simplest wins; Ridge has best test MAE (11.9), no OpenMP/torch clash, tiny, explainable. XGBoost + RF stay in the comparison and SHAP. Reminder: "useful" window widened to 1–14 days early (PROPOSED, Ari to confirm) — 3–7 is narrower than the ±12-day error of any method; applied to ALL methods equally; buffer objective = maximize useful rate, ties → fewer late (late worse, D-036) | 2.3b handoff | APPROVED (PM); window APPROVED by Ari Oct 12 (D-054) |
| D-052 | 2026-10-10 | Two devices: Mac = ML/backend/data on `main`; iMac (separate Claude account) = Streamlit frontend on branch `ui`, merged to main by GitHub PR after PM accepts. iMac owns only src/ui/, tests/test_ui*, docs/ui_*, requirements-ui.txt; never edits PROJECT_STATE/CLAUDE.md/requirements.txt. UI talks to backend only via docs/api_contract.md. One PM chat for both. Context file: docs/IMAC_BRIEFING.md. Private data copied by hand (AirDrop/USB), never via git | Ari works on 2 Macs | APPROVED by Ari |
| D-053 | 2026-10-12 | Branch fix: remote `origin/UI` (capital U, 0 own commits) is deleted; frontend branch is lowercase `ui`, created from current main. Reason: macOS file system is case-insensitive → `UI` and `ui` refs can collide | Status check Oct 12 | APPROVED (PM) |
| D-054 | 2026-10-12 | D-051 reminder "useful" window = 1–14 days before actual due date, applied to all methods equally | Ari confirmed | APPROVED by Ari |
| D-055 | 2026-10-12 | Re-plan §3 v2.3: Oct 14 cut checkpoint, Oct 16 feature freeze. Commit rule: tests + commit + push before every handoff (2.4 found uncommitted; 1.2a draft was lost before) | 8 days left | APPROVED (PM) |
| D-056 | 2026-10-12 | Frontend stays in src/ui/ (IMAC_BRIEFING, D-052); empty frontend/ folder (Next.js placeholder) removed or ignored. §8 tree updated | Repo matches plan | APPROVED (PM) |
| D-057 | 2026-10-12 | 2.4 accepted: Ridge = serving model (models/next_change_model.joblib, buffer 9 days, retuned in 2.4b); shap==0.51.0 (0.52+ needs Py ≥3.12, D-020); status truth = actual next visit, checked every 7 days until +14 [ESTIMATE]; "B1 refit" (a·B1+b on train) added as fair route-formula reference; example truck shown anonymously | 2.4 handoff | APPROVED (PM) |
| D-058 | 2026-10-12 | n_prior_visits removed from features → has_history (0/1). Reason: top SHAP feature is a split-cutoff censoring artifact (r +0.68 with service date, r 0.04 with true truck pace); in real use it would wrongly shorten predictions for loyal trucks. Target censoring near the cutoff stays as a stated limitation (affects all methods) | 2.4 handoff | APPROVED (PM) |
| D-059 | 2026-10-12 | D-038: Ridge beats B1 refit by +0.43 d (CI +0.18..+0.71) with variation OFF; tolerance 0.5 [ESTIMATE] is NOT changed. Gap explained by season + destination averages + n_prior_visits, no leak found. Rerun after 2.4b; whatever the result, it is reported as-is on slide 6 | Integrity (D-050) | APPROVED (PM) |
| D-060 | 2026-10-12 | D-038 after 2.4b: Ridge gain over B1 refit +0.31 d (CI +0.08..+0.58) with variation OFF; upper end above 0.5 tolerance (unchanged). Ridge vs 3-input linear fit +0.10 (+0.01..+0.21) → gap explained by legitimate inputs (season, destination, has_history), no leak. ACCEPTED with this explanation; slide 6 shows the numbers and the tolerance as-is. has_history r +0.48 with service date on train, effect small (0.38 d) → watch on real data | 2.4b handoff | APPROVED (PM) |
| D-061 | 2026-10-12 | Product form: internal website for Geo-Expert only, on a server, opened in the phone browser; no native app (cost). Needs login (company password; API not exposed publicly) and HTTPS + domain (browser camera requires HTTPS). Hosting: A) free tiers split or B) one small VPS running docker compose (PM recommends B: no cold start, data in one place, reused after capstone) | Ari Oct 12 | APPROVED by Ari (form); host A/B PENDING |
| D-062 | 2026-10-12 | Destination spellings confirmed by Ari: Замын-Үүд, Эрээн, Бээжин, Алтанбулаг, Хиагт → 1.1c unblocked. Waiting 0–5 days/trip (incl. MN–Russia) stays [ESTIMATE, unverified] — Ari unsure; stated as assumption on slides | Ari Oct 12 | APPROVED by Ari |
| D-063 | 2026-10-12 | Cut #4 applied: 1.4b + 2.5 cut — repeat-truck photo dates cannot be recovered from Messenger. No real-interval test before defense. Slides: "model trained and tested on synthetic data; ML ≈ B0; real validation starts once the system records dated services (date is automatic in the app)". Real data still used: 183 real photos (detector + OCR), 338-truck Excel registry (messy-data profiling, R1) | Ari Oct 12 | APPROVED (PM + Ari) |
| D-064 | 2026-10-12 | Hosting decision (A/B, provider) parked until 6.3 at Ari's request; PM raises it then. ROI (6.5) built as a scenario from D-031 return estimates (50% on time / 40% late / 10% never) + Ari's typical price/margin per oil change, all labelled [ESTIMATE] — no historical data exists | Ari Oct 12 | APPROVED by Ari |
| D-065 | 2026-10-12 | 4.3 accepted: recognizer = custom char CNN (70.4% exact vs EasyOCR 33.3%, 1.2 MB vs 98 MB) → R6 answered (custom CNN beats transfer OCR on our data). Detector + CNN served as ONNX on CPU (no torch). Fallback order: route not MN–CN/MN–RU → b0; destination_raw only → b0 (also on first visit); no destination → b0; first visit → b1; else ridge; min 1 day. model_version = name + 8 hex of SHA-256. status/days_left use the predicted date WITHOUT buffer; buffer only decides the reminder send date (4.4). API starts without model files (prediction null, model endpoints 503). Photos not stored. Confidence threshold 0.6 stays (tuning on test = leak); 2/3 of photos go to manual confirm, 0 wrong auto-fills → slide: "never fills a wrong plate" | 4.3 handoff | APPROVED (PM) |
| D-066 | 2026-10-12 | Reminders (D-010 accepted): app generates the Mongolian message (plate, last change date, oil used, Geo-Expert contact from config) + "mark sent" + copy/share button; no SMS gateway (Later). Send date = predicted_date − per-method buffer (ridge 7, b0 12, b1 1 days; from docs/ml_evaluation.md). One reminder per (vehicle, latest service); marking sent twice is idempotent. Recipient = phone on the latest service record (D-004) | Plan 4.4 | APPROVED (PM) |
| D-067 | 2026-10-12 | Server sizing input (for 6.3, decision still parked D-064): API uses ~190–310 MB RAM, image 1.05 GB unpacked; with Postgres + Streamlit a 2 GB server is likely enough — confirm in 6.3 after UI is measured | 4.3 metrics | NOTED |
| D-068 | 2026-10-12 | 4.4 accepted: reminder id = vehicle's newest service id (UNIQUE service_id; newer service → 409 not_latest_service); new table reminders_sent (old reminders/predictions tables untouched); B0/B1 buffers tuned on train validation in export_serving; segments in API from served prediction (SQL function = fallback); due list = send_on ≤ as_of and not sent, no age limit — at_risk trucks STAY on the list and the UI (5.4) shows them in a separate "Алдагдах эрсдэлтэй" group (no backend change); contact = env GEO_EXPERT_NAME / GEO_EXPERT_PHONE (real number only in .env, never committed). SMS length (UCS-2, ~2 SMS) irrelevant until a gateway exists (Later) | 4.4 handoff | APPROVED (PM); message wording PENDING Ari |
| D-069 | 2026-10-12 | Migration order: 003 applied before 002 → the D-041 apply script (6.3) must apply EVERY missing version from schema_migrations, not only versions above the max. Deploy runbook must run `python -m src.ml.export_serving` and mount ./models (else prediction 503) | 4.4 handoff | APPROVED (PM) |
| D-070 | 2026-10-12 | 5.1–5.3 accepted. Corrections for T2: POST /plates/recognize multipart field is "file" (not "image", contract v0.4); prediction shape = contract v0.4/v0.5 (method, fallback_reason, model_version, predicted_date, days_left, status) — read the contract, don't assume. service_date never sent by UI (API default = today UB). Photo never uploaded except to recognize, never stored. Segment labels: Ari to choose (short: Шинэ / Давтан / Байнгын / Эрсдэлтэй) | 5.1–5.3 handoff | APPROVED (PM); labels PENDING Ari |
| D-071 | 2026-10-12 | 1.1c + 4.5 accepted: name_mn nullable + unique; UI shows name when name_mn empty; seed dates placed with the served Predictor (seed and API agree); seed refuses a non-empty DB; 2 at-risk trucks pre-marked sent; demo oil grades/liters are placeholders. Demo goes stale daily → the CLOUD DB is seeded with --as-of 2026-10-20 (defense day) so no re-seed is needed on the day; local dev re-seeds as needed. Live demo path: 1001 УБА (loyal) → 1002 УБЕ (overdue + reminder) → 1003 УНА (first visit, B1) → phone 0000 0009 (2 trucks) | 1.1c + 4.5 handoff | APPROVED (PM) |
| D-072 | 2026-10-12 | 5.3b accepted: recognize runs automatically when a photo is taken (no extra button); clear read → immediate lookup, needs_manual → never auto-lookup; model_version hidden from the oil changer; method notes ridge «Загварын таамаглал» / b1 «Маршрутын тооцоо» / b0 «Дундаж хугацаа». iMac model files rebuilt from synthetic data only (seed 42, reports byte-identical). PR ui → main after T5 | 5.3b handoff | APPROVED (PM); wording PENDING Ari proofread |
| D-073 | 2026-10-12 | iMac work reviewed by a temporary PM chat (5.3c, 5.4, T5) is confirmed. T6 UX changes accepted: photo preview client-side only (not stored); company field only for new vehicles (D-042 kept); truck model = searchable list + «Бусад» (top models from the Excel registry = counts only, no plates); oil grade list 15W-40 / 10W-40 / 20W-50 + «Бусад»; «Тос солигч» field removed (one oil changer); fleet no. behind «Дугааргүй машин» (D-005 kept); search label «Улсын дугаар эсвэл утас»; «Залгах» removed; font Montserrat; Streamlit Deploy menu hidden. Segment labels short: Шинэ / Давтан / Байнгын / Эрсдэлтэй (Ari may change) | iMac report | APPROVED (PM) |
| D-074 | 2026-10-12 | GET /reminders/due returns `segment` per item (contract v0.7); UI then removes AT_RISK_GRACE_DAYS (single source of the D-007 rule = API) | iMac request | APPROVED (PM) |
| D-075 | 2026-10-12 | Integration order: (1) all finished Mac work (2.4, 2.4b, 4.3, 4.4, 1.1c+4.5) committed per task and pushed to origin/main; (2) 6.1/6.2/4.4b on main; (3) PR ui → main; (4) live end-to-end photo test on the Mac. Progress-check demo Oct 13 runs locally on the Mac from the `ui` worktree (21124d2 known-good) + docker compose backend | iMac report: Mac work not on origin/main | APPROVED (PM) |
| D-076 | 2026-10-13 | Demo-day hotfixes may be done directly on main by the Mac (one-time exception to D-052 ownership); iMac then merges main into ui | 5.9b | APPROVED (PM) |
| D-077 | 2026-10-13 | Field test: phone photos of whole trucks (plate ~10% of image width, harsh sun, new phone DOOGEE with date stamp) → often not read; closer photos (~13%) → read. Detector is strong; char CNN is the weak link (183 photos / 135 trucks). Policy stays: never auto-fill a wrong plate (pre-fill + ask). Improvements: camera hint (5.3d), fallback ladder (3.5), more training data = Later (needs storing photos with driver consent — decision post-defense) | Ari field test Oct 13 | APPROVED (PM) |
| D-078 | 2026-10-13 | Demo hygiene: re-seed before every demo (down -v, up, seed_demo); never show real plates/phones on the projector — live plate demo with Ari's own car or upload + type; phone-style window: `open -na "Google Chrome" --args --app=http://localhost:8501 --window-size=400,860` | Demo Oct 13 | APPROVED (PM) |
| D-079 | 2026-10-14 | Process: PM chat moves to a new chat (this one too long). State file is updated once per evening or on big changes. Repo path on Mac: ~/Downloads/Capstone/oil-change-predictor; update state with: cp ~/Downloads/PROJECT_STATE_v<N>.md docs/PROJECT_STATE.md && git add … && git commit && git push | Ari Oct 14 | APPROVED |

| D-080 | 2026-10-14 | All work runs on the Mac on branch main. iMac (second Claude account) = backup capacity only for small independent tasks (briefs marked `iMac-OK`; pull → work → test → push). Branch `ui` retired. Supersedes D-052 and D-076 | Ari | APPROVED by Ari |
| D-081 | 2026-10-14 | Model upgrade scope: retrain char CNN with new photos (3.6); NO YOLO retrain (detector recall 1.00, CNN is the weak link, D-077); NO ML model changes (synthetic data — would be circular, D-050); add new MN–China / MN–Russia destinations from Ari (1.6). Deploy moved to Sun Oct 18; freeze Sat Oct 17 | Ari Oct 14 | APPROVED by Ari |
| D-082 | 2026-10-14 | Moved to Later: admin data page (view/edit/delete companies, vehicles, services), one-tap «Viber-ээр илгээх» button (viber://forward), automatic Viber Business sending (needs approved business account + fees). Copy/share button stays the reminder delivery for the defense (D-066) | Ari Oct 14 | APPROVED by Ari |
| D-083 | 2026-10-16 | 3.6a pre-labels = fine-tuned yolo26n (D-028) ONNX, threshold 0.6, plate text empty. 3.1c stays on oim (D-025) for reproducibility | 3.6a handoff | APPROVED (PM) |
| D-084 | 2026-10-16 | Duplicates removed by SHA-256 before any split (1 within new, 1 matching an old photo → 42 kept). Only byte-identical copies are caught; near-duplicates are still grouped by plate text (no leak) | 3.6a handoff | APPROVED (PM) |
| D-085 | 2026-10-16 | 3.6 keep rule, fixed BEFORE results: new CNN served only if 0 wrong auto-fills AND ≥3 more exact reads on test AND correct auto-fills ≥ old | Pre-registration; 1–2 plates = noise (3.3) | APPROVED (PM) |
| D-086 | 2026-10-16 | 3.6 result: exact +1 (19 → 20 of 27, McNemar p = 1.0) → rule not met → char_cnn v1 stays served; v2 saved (char_cnn_v2.onnx). Auto-fill 9 → 14 with 0 wrong is reported as "promising, not proven" on slides. Rule is NOT changed after seeing results. Promote v2 later only after a field-test set exists and v2 passes it | 3.6 handoff; integrity (same principle as D-050) | APPROVED (PM) |
| D-087 | 2026-10-16 | CV product target (set BEFORE 3.6b): ≥ 18/27 (2/3) old test plates auto-filled correctly with 0 wrong auto-fills; model promoted only if met, else v1 stays served | Ari: CV must be useful in practice | APPROVED by Ari |
| D-088 | 2026-10-16 | 3.6b result: augmentation did not help (confident errors); val-chosen model = v2 recipe; test 14/27, 0 wrong → D-087 not met → v1 stays served, v2/v3 saved. Next CV levers = character segmentation (4/27 plates never split into 7 chars, ceiling 23/27) + more labeled photos + field-test set. CV work stops until after 6.1 | 3.6b handoff | APPROVED (PM) |
| D-089 | 2026-10-16 | Changes D-065: auto-fill threshold stored per served model in models/plate_ocr/char_cnn_version.json {threshold, served_sha256_8}; recognizer refuses to load on hash mismatch (503 + log); default 0.6 if absent (today = 0.6, v1). Threshold is chosen on validation only, never on test | 3.6b handoff | APPROVED (PM) |
| D-090 | 2026-10-16 | Deploy design: migrate + seed run inside the API image (DB port never exposed); export_serving runs on the Mac, then model files (incl. char_cnn_version.json, serving_params.json) are rsynced to the server; Caddy forwards only /health to the API, everything else to the UI; CI allows only 3 skips (opt-in browser test + 2 real-ONNX tests), any DB/UI skip fails CI | 6.1 handoff | APPROVED (PM) |
| D-091 | 2026-10-16 | One-tap Viber button (5.5) brought back from Later (overrides that part of D-082). No Viber API, tokens or automatic sending (D-010) | Ari | APPROVED by Ari |
| D-092 | 2026-10-17 | 1.6 routes confirmed by Ari: Ганцмод (Tavan Tolgoi → Gashuunsukhait → Ganqimaodu), Сэхээ (UB → Shiveekhuren → Ceke), Улаан-Үд (UB → Altanbulag → Ulan-Ude), Кош-Агач (UB → Tsagaannuur → Kosh-Agach). Distances from OSRM API (counts as R1 external API). AI-made route research was checked and corrected before use (D-032) | Ari + 1.6 part 1 | APPROVED by Ari |
| D-093 | 2026-10-17 | 2.9 keep rule, fixed BEFORE results: a new served ML model only if vehicle-grouped CV MAE beats current Ridge by ≥ 0.3 days; test run once at the end | PM, same principle as D-085 | APPROVED (PM) |
| D-094 | 2026-10-17 | 2.9 result: no model change (CV gain +0.06 d). Approved exception to D-081: 80% prediction range added (no feature/model change). Noise floor is for THIS generator only; real floor unknown. Deploy must run export_serving so ranges + 9 routes are served. Known limitation: cleaner cannot tell which reading is wrong when a truck has only 2 readings (1.6 N8 carve-out) → Later: flag for manual review | 2.9 handoff | APPROVED (PM) |
| D-095 | 2026-10-17 | Hosting: DigitalOcean Singapore 2 GB droplet, everything (Caddy, UI, API, Postgres) on one server via docker compose; address <ip>.sslip.io (free, Let's Encrypt). $20 billing alert. AWS Lightsail/EC2 and Vercel considered: Vercel cannot run Streamlit/Docker; AWS = mid tier on TCO slide | Ari: "do it your way" | APPROVED by Ari |
| D-096 | 2026-10-19 | UI font = phone system font (replaces Montserrat from T7) for readability and identical rendering with iOS Lockdown Mode | 5.6 | APPROVED by Ari (phone check) |
| D-097 | 2026-10-19 | Serve char CNN v2 at threshold 0.60 as an EXPLICIT OVERRIDE of D-085/D-087 (rules NOT met): v2 ≥ v1 on every test metric with 0 wrong auto-fills; gain not statistically proven. Presented honestly as a product decision; worker confirms every plate. v1 kept for rollback. Supersedes the "v1 stays served" part of D-086/D-088 | Ari | APPROVED by Ari |
---

### 6. Open questions

1. ~~Hosting~~ DONE (D-095)
1b. Route list for 1.6: one line per destination — Mongolian name | city | country | border crossing — needed Fri Oct 16
2. Domain: does Geo-Expert have one for service.<domain>? Else <ip>.sslip.io
3. ROI inputs from Ari: typical price of one truck oil change (₮) + rough margin % (slide 12)
4. Brand color hex (placeholder #1F4E9D)
5. Labels ✓/✗: segments Шинэ / Давтан / Байнгын / Эрсдэлтэй; destinations «Улаанбаатар хот» / «Бусад» (migration 004 in 6.1)
6. Reminder message wording (Ari approves) + real GEO_EXPERT_PHONE in .env (never in git)
7. GitHub repo public? (link on slide 13; no real data in git per cleanup audit)
8. Teacher feedback from Oct 13 demo
11. Field-test photo set (phone photos the system failed on) — none saved; needed before promoting char_cnn v2 (D-086)
12. Label Studio token was visible in a screenshot (Oct 16) — Ari to reset it in Account & Settings
9. Personal-data law: storing driver data on a foreign server — check before REAL use (not blocking defense)
10. Does oil grade change the interval? (stays out, D-034)

### 7. Risks

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
| RISK-10 | No real prediction test set (D-063) | HIT | Med | Report honestly; synthetic holdout = main metric; real validation = post-defense from app-recorded dates |
| RISK-13 | ML may not beat B0: synthetic history features weak (|r| ≤ 0.16), noise large vs per-vehicle signal | High | HIT (2.3b: ML ≈ B0) | D-050: calibrate to real 1.4b intervals (Ari dates = now critical); honest reporting; buffer tuning improves business metric |
| RISK-12 | Critical path blocked on Ari inputs A1–A4 | — | HIT | Resolved by D-045 (ranges). ML starts ~Oct 11 → 9 days left; cut list active if 2.x slips past Oct 14 |
| RISK-16 | ~~UI not started~~ CLOSED — UI built, merged, demo Oct 13 OK | — | — | — |
| RISK-17 | iPhone HEIC photos rejected (422) → recording fails on phone | Med | High | 4.4 adds pillow-heif; test camera upload on a real phone in 5.x |
| RISK-18 | Repo PROJECT_STATE behind (v2.12 seen in 3.6 session) → sessions miss recent decisions | HIT | Med | Ari commits PROJECT_STATE v2.14 now, before the next session |
| RISK-21 | ~~Cloud deploy late~~ CLOSED Oct 19 — deployed and phone-tested | — | — | 6.1 prep finished and tested locally through Caddy before Sunday; local backup video Sat Oct 17; hosting decided by Sat |
| RISK-19 | Finished Mac work not on origin/main | CLOSED Oct 12 | — | Only 1.1c+4.5 was missing → 17278bb pushed, CI green |
| RISK-20 | Cloud deploy not started, 6 days left; depends on hosting answer | High | High | 6.1 prep is host-agnostic → run now; decide host by Oct 14; deploy Oct 15 |
| RISK-14 | Uncommitted work lost or untested (2.4 found untracked; 1.2a draft lost before) | Med | High | Commit rule D-055: tests + commit + push before every handoff |
| RISK-15 | Critical path: 4.3 → 4.4 → 6.3 not started with 8 days left | High | High | Mac does only critical path; Oct 14 cut checkpoint; feature freeze Oct 16 |
| RISK-08 | Plate letters misread (Cyrillic/Latin look-alikes) | High | Med | Normalization map + format regex + confirmation step |

---

### 8. Contracts (shared by all roles)

**Repo structure**
```
oil-change-predictor/
├── data/            # raw/ interim/ processed/ synthetic/  (git-ignored except samples)
├── src/
│   ├── common/      # features.py (shared train+serve), config.py, plates.py (normalization)
│   ├── data/        # generator.py, cleaning.py, external_api.py
│   ├── ml/          # train.py, evaluate.py, explain.py
│   ├── cv/          # detect.py, recognize.py, cnn_char.py
│   ├── api/         # main.py, routers/, db.py, models.py, schemas.py
│   └── ui/          # Streamlit app (iMac, branch ui)
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

### 9. Slide map (13 slides → producing phase)

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

### 10. Later list (not in scope unless Ari approves)
- Next.js production frontend (post-capstone, D-022)
- Real SMS / Viber gateway integration (automatic Viber Business sending, D-082)
- One-tap «Viber-ээр илгээх» button via viber://forward (D-082)
- Admin data page: view / edit / delete companies, vehicles, services (D-082)
- Promote char_cnn v2 after a field-test set exists (D-086, D-088); keep collecting + labeling photos
- Cleaner: flag 2-reading ambiguous odometer errors for manual review instead of guessing (D-094)
- ML: real service records, new features (driver, season × route, load), per-truck correction
- Character segmentation fix (4/27 test plates fail) — task 3.5, Sat only if 6.1 done
- Look at 4 test plates failing character segmentation
- Automated data drift monitoring + continuous training
- Oil lab report analysis
- Multi-branch / multi-user roles beyond one oil changer + admin
- Offline mode for mine sites without signal
- LLM chat assistant for drivers

---

### 11. Post-defense housekeeping (superseded by §2 of v2.19) (Oct 21+)
1. Change `UI_PASSWORD` on the server (`nano .env` → `docker compose -f docker-compose.prod.yml up -d ui`); examiners had the old one.
2. Decide the droplet: keep (~$12/month, billed hourly) for Geo-Expert pilot, or Destroy to stop billing (powered-off still bills).
3. Reset Label Studio access token (was visible in a screenshot, Oct 16).
4. Commit leftovers: 7.1c slide facts files if still uncommitted; deploy.md "(v1)" → "(v2)".
5. Fix 3.6c (OCR doc section-marker bug) before anyone re-runs ocr_extend/ocr_tune.
6. Field-test set: collect + label real failed phone photos → re-evaluate v2 vs v1 honestly.
7. Post-capstone roadmap (Later list): real Geo-Expert service records → retrain ML; admin data page (edit/delete); read-only demo mode for public sharing; real domain (app.<company>.mn); automatic Viber Business sending; character-segmentation fix / whole-plate reader; cleaner flags ambiguous 2-reading errors; live camera on iPhone.

