# HANDOFF REPORT — 5.3c (queue T3)

```
HANDOFF REPORT
TASK ID: 5.3c (queue T3)
STATUS: DONE
SUMMARY: DESIGN v2 applied. Theme in src/ui/.streamlit/config.toml (background #F4F5F7,
  primary #1F4E9D placeholder, black text, button radius 18), minimal CSS for white
  cards (radius 24, soft shadow) and buttons >= 56 px. One column, Mongolian only. Screens:
  - Header: big title + «Гео-Эксперт» pill; «‹ Буцах» on inner screens; menu hidden.
  - Home: big primary «📷 Бүртгэх» card, white «🔍 Хайх» card.
  - Record: camera (+ upload) / «Дугаарыг гараар оруулах» → confirm (plate large monospace
    in a bordered box + chip «Бүртгэлтэй · N удаа ирсэн» / «Шинэ машин») → «Зөв,
    үргэлжлүүлэх» / «Буруу байна — засах» → form: card 1 odometer + destination tap pills
    (GET /destinations, «Бусад» → text + route pills); card 2 «Өмнөхөөс авсан» one line +
    «Засах» expander (new truck: all fields) → «Хадгалах» → success ✓ «Хадгалагдлаа»,
    «Дараагийн машин», «Машины карт үзэх». Duplicate → «Ингээд хадгалах».
  - Search: input + «Хайх», black «Камераар хайх», «Сүүлд үзсэн» (session). One match →
    card; several → list; none → new-vehicle form.
  - Card: plate box + segment badge; status card (colors per brief, big «N хоног», date,
    progress bar); 3 tiles (last change, oil · liters, destination); «Жолооч · утас —
    Залгах» (tel:); history expander; primary «Тос солилт бүртгэх».
FILES: src/ui/.streamlit/config.toml (new), src/ui/app.py, src/ui/common.py, src/ui/logic.py,
  src/ui/views/home.py (new), src/ui/views/record.py (rewritten), src/ui/views/search.py
  (new, replaces views/lookup.py), src/ui/views/card.py (new), tests/test_ui_app.py
  (rewritten for the new flow), tests/test_ui_logic.py, docs/ui_screens.md,
  docs/ui_handoff_5.3c.md
HOW TO RUN: cd src/ui && streamlit run app.py   (must start from src/ui/ for the theme)
  env API_URL, UI_PASSWORD as before.
DECISIONS MADE:
  - Card is its own screen (GET /vehicles/{id}, always fresh after a save); search with one
    match opens it directly. The auto-open happens only right after a search, so «Буцах»
    from the card does not bounce back.
  - From the card («Тос солилт бүртгэх») and from «Олдсонгүй → Шинэ машин бүртгэх» the form
    opens directly (plate already known, no confirm step).
  - Engine hours shown only for fleet numbers, or if the truck had engine hours before
    (card 1 stays "odometer + destination" for normal trucks).
  - Usual liters kept on the card as a short line («ердийн 32 л»): it was in the 5.1–5.3
    DONE criteria.
  - Oil changer field lives in «Засах» (existing truck) and is remembered for the session.
  - server.maxUploadSize = 15 MB, same as the API limit.
METRICS / EVIDENCE:
  - pytest (full repo): 568 passed, 2 skipped (backend ONNX, expected on the iMac).
    UI tests: 78 (+8 login-bypass tests over all 4 views; 24 screen tests rewritten for the step flow: home buttons, back button,
    confirm chip, wrong → edit, pills + «Бусад», duplicate/force/cancel, fleet radio, photo
    → confirm / manual / recognizer down, single/several/no match, phone search + recent,
    camera search, card parts incl. tel: link, save → find by plate AND phone).
  - Browser walk in Chrome 390×844 against the live API: home → manual plate → confirm
    (new) → form → save → success → card → record again (existing, «Өмнөхөөс авсан») →
    search 1234 УБА → overdue card → back → «Сүүлд үзсэн». scrollWidth = 390 (no sideways
    scroll). Screenshots (fake data): ~/Desktop/sncir/ui_screenshots/v2/ (not in git, PNGs
    are git-ignored).
  - PM pre-commit checks:
    1. Login bypass covers the NEW views: test_ui_app.py::test_logged_out_cannot_open_any_view
       (home, record, search, card: with UI_PASSWORD set none is a navigation page → only
       login) + counter-test test_logged_in_can_open_every_view; test_no_streamlit_pages_folder
       now asserts views/ holds exactly these 4 files. Browser: /, /record, /search, /card on
       a UI_PASSWORD instance all show only the login screen.
    2. «Сүүлд үзсэн» = st.session_state only (common.remember_viewed). Stores {id, plate,
       company}, no phone. No disk / browser storage / cookie / query-param / API writes
       anywhere in src/ui (grep). Gone when the browser session ends.
ASSUMPTIONS NEEDING PM/ARI CONFIRMATION:
  1. Primary #1F4E9D is still a placeholder; one line in config.toml to change.
  2. «Сануулга» link on Home is added with T4 (5.4) as planned.
  3. Card as a separate screen (vs. inline under search results) OK?
PROBLEMS / RISKS:
  - Streamlit built-in text stays English: camera permission prompt / «Take Photo»,
    uploader «Upload» / «15MB per file». Cannot be translated from the app.
  - Destination pills show English names until migration 002 adds name_mn (UI prefers
    name_mn already). 7 pills wrap to ~5 rows on a phone.
  - Must start Streamlit from src/ui/, or the theme is not applied (the app still works).
    The T5 Dockerfile will set this.
  - CI still installs only requirements.txt → UI screen tests skip in CI.
CONTRACT CHANGES: none.
SLIDE MATERIAL: v2 screenshots (home, confirm plate box, form with pills, success, card
  ok/overdue, search). Returning truck: photo → «Зөв» → type km + tap destination → «Хадгалах» (everything else pre-filled).
NEXT STEP: T4 (5.4) manager dashboard + «Сануулга» link on Home.
  Carried to T5: Dockerfile WORKDIR src/ui (theme) + run command in docs/ui_*; check the
  uploaders accept HEIC (RISK-17); show name_mn when present (contract v0.6, D-071) without
  merging main now.
```
