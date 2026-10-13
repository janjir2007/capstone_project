# HANDOFF REPORT — 5.4 (queue T4)

```
HANDOFF REPORT
TASK ID: 5.4 (queue T4)
STATUS: DONE
SUMMARY: Manager dashboard «Сануулга» (src/ui/views/reminders.py), contract v0.5, linked
  from Home. 4 segment tiles (GET /stats/segments). Due reminders (GET /reminders/due) in
  two groups, «Илгээх» and «Эрсдэлтэй» (at_risk). Each row: plate, phone, send_on, status,
  message text with a copy button, «Илгээсэн» → POST /reminders/{service_id}/sent, with
  already_sent shown. Handles contact_is_placeholder, 503 (no model) and 409
  not_latest_service.
FILES: src/ui/views/reminders.py (new), src/ui/api_client.py (segment_stats, reminders_due,
  mark_reminder_sent, NotLatestService), src/ui/logic.py (split_reminders, is_at_risk,
  days_left_text), src/ui/common.py, src/ui/app.py, src/ui/views/home.py,
  tests/test_ui_{api_client,logic,app}.py, docs/ui_screens.md, docs/ui_handoff_5.4.md
HOW TO RUN: cd src/ui && streamlit run app.py → Home → «Сануулга» (or /reminders).
DECISIONS MADE:
  - «Эрсдэлтэй» group = days_left < −7 (D-007: predicted date + 7 days grace < as_of). DueReminder
    has no segment field, so the UI applies the same rule and the same number as the API
    (src/api/prediction.py AT_RISK_GRACE_DAYS = 7). The constant is copied, not imported (D-052).
    Live check: «Эрсдэлтэй (1)» in the list = at_risk tile (1).
  - Copy button = st.code's built-in "Copy to clipboard" (no JS component). Browser-verified:
    the clipboard gets exactly message_mn.
  - After «Илгээсэн» the list reloads; the row disappears (API excludes sent reminders).
  - The dashboard is behind the same UI_PASSWORD as the rest (no separate manager login;
    roles are on the Later list).
  - Wider layout on desktop (max 1100 px); tiles become 2×2 on a phone.
METRICS / EVIDENCE:
  - pytest (full repo): 589 passed, 2 skipped (backend ONNX, expected on the iMac).
    UI tests: 91 (+13: client paths/already_sent/not_latest, D-007 split incl. −7 boundary,
    tiles + groups + copy text + placeholder warning, mark → row gone, mark twice →
    «Өмнө нь илгээсэн» (stored once), not_latest, 503, Home link, login-bypass over 5 views).
  - Live API (synthetic sample DB): desktop 1280 px and phone 390 px (scrollWidth 390). Groups
    «Илгээх (2)» / «Эрсдэлтэй (1)». «Илгээсэн» on 1234 УБА → 201 «Илгээсэн гэж тэмдэглэлээ ·
    99110002», list → «Илгээх (1)». Screenshots: ~/Desktop/sncir/ui_screenshots/v2/t4_*.png.
ASSUMPTIONS NEEDING PM/ARI CONFIRMATION:
  1. Is the «Эрсдэлтэй» split right? Today: overdue > 7 days, by the D-007 at_risk rule.
     Alternative: put every overdue in «Эрсдэлтэй».
  2. Should at_risk rows also have «Илгээсэн»? Today: yes, a reminder is still useful.
  3. Message wording is the API's draft (Ari to approve, contract v0.5).
PROBLEMS / RISKS:
  - The grace rule is in two places (API + UI). If D-007's 7 days changes, the UI must change
    too. See CONTRACT CHANGES.
  - "Copy to clipboard" tooltip is Streamlit's English text.
  - Local dev DB: one sample reminder (service 3, synthetic) is now marked sent.
  - One full-suite run on the iMac aborted at exit with a native "libc++abi recursive_mutex"
    error (torch/XGBoost teardown, outside src/ui); 3 reruns clean, exit 0. Watch on the Mac.
CONTRACT CHANGES: none made. Suggestion for backend (later, optional): add `segment` (or
  `at_risk: bool`) to DueReminder, so the UI does not repeat the D-007 rule.
SLIDE MATERIAL: dashboard screenshots (desktop + phone); "reminder loop": predict → due list →
  copy message → mark sent (stored with method + model_version for the hit-rate metric, D-036).
NEXT STEP: T5 quality. Carried over: Dockerfile with WORKDIR src/ui (theme) + run command in
  docs/ui_*, check HEIC in the uploaders (RISK-17), show name_mn when present (contract v0.6,
  D-071) without merging main.
```
