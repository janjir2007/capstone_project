# HANDOFF REPORT — T6 (5.3d: simpler form + better design)

```
HANDOFF REPORT
TASK ID: T6 (5.3d — simpler form + better design)
STATUS: DONE (commit + push to ui pending Ari's OK). Demo-known-good stays 21124d2.
  Note: the brief arrived cut off after "DONE WHEN: tests updated + green; 390 px Chrome". Read
  as "… 390 px Chrome screenshots of each screen + HANDOFF REPORT" (same as earlier tasks).
SUMMARY:
  DESIGN (whole app)
  1. Montserrat everywhere (theme.font = Google Fonts URL). Mongolian Ө ө Ү ү: RENDER IN MONTSERRAT.
     Proof: Chrome DevTools CSS.getPlatformFontsForNode on «ҮүӨө Үйлчилгээ Өмнөх» at weight 500
     and 800 → 20/20 glyphs from Montserrat, no fallback font; the same text forced to sans-serif →
     Helvetica (control). The Google CSS includes the cyrillic-ext subset.
  2. Palette / spacing / cards / buttons / type, all with checked numbers: text 18:1, muted
     7.3:1, white on primary #1F4E9D 8:1. Spacing 4/8/12/16/24/32. Buttons ≥ 56 px, pills ≥ 48,
     links ≥ 44. Title 28/800, body 16/500, nothing below 14 px. White cards radius 20.
     Emoji titles/icons removed → Material icons (camera, search, keyboard, browser tab).
  3. Status colors, the same everywhere (card + dashboard), always with the word:
     Хэвийн #14532D/#E3F1E7 7.8:1 · Удахгүй #6B3F00/#FBEFD6 7.9:1 · Хэтэрсэн #8C1D18/#F9E3E1 7.4:1
     · none #3F4552/#ECEEF1 8.3:1. All AAA (outdoor light). Darker than the T3 values (those were
     only AA 5.3–5.6). Test guards ≥ 7:1.
  4. client.toolbarMode = "viewer": Deploy + developer menu hidden. The ⋮ viewer menu (Settings,
     Print) stays; Streamlit has no setting to remove it without CSS hacks.
  RECORD FORM
  5. Photo preview on confirm + form (+ manual) steps; session memory only, never stored, never
     sent except POST /plates/recognize (D-070). Test: exactly 1 upload to /plates/recognize.
     A photo the UI can't decode (iPhone HEIC, decoded only by the API) shows a text line, never
     an error. This was a crash found by the tests and fixed.
  6. «Компани / эзэмшигч»: only for new vehicles (required, no default, D-042). Existing fleet
     truck: the UI sends the chosen truck's company (D-042: fleet_no always needs it). Test added.
  7. Vehicle model: searchable selectbox over ONE list (logic.VEHICLE_MODELS, 26 models from the
     brief) + «Бусад» (free text). An old free-text value not in the list is put first and still
     shows (D-019). Typing "Shac" filters to the 3 Shacman models (browser-verified).
  8. Oil grade: 15W-40 · 10W-40 · 20W-50 + «Бусад» as big tap options (pills, 48 px). Default =
     last service value; a value outside the 3 → «Бусад» with it as text; else 15W-40.
  9. «Тос солигч» removed. Contract: oil_changer is optional ("blank → null"), so nothing breaks;
     the UI no longer sends it.
  10. Park-number radio removed; small «Дугааргүй машин» link (on capture and manual) switches
     to fleet-number mode («Парк дугаар», placeholder HT-12); «Улсын дугаартай машин» switches back.
  SEARCH + CARD
  11. Label «Улсын дугаар эсвэл утас» (API still matches fleet numbers).
  12. «Залгах» removed (driver name + phone shown as a tile).
  13. Card order: large plate → status block = biggest colored block (status word, «N хоног»,
     «Дараагийн солилт: date», bar) → badge + facts → 4 tiles (2×2: last change, oil · liters,
     destination, driver) → history collapsed → primary button.
FILES: src/ui/.streamlit/config.toml, src/ui/app.py, src/ui/common.py, src/ui/logic.py,
  src/ui/views/{record,card,search,home,reminders}.py, tests/test_ui_{app,logic,browser}.py,
  docs/ui_screens.md, docs/ui_handoff_t6.md
HOW TO RUN: unchanged — docs/ui_run.md (cd src/ui && streamlit run app.py; Docker in §2).
DECISIONS MADE:
  - ui-ux-pro-max: the skill is NOT in this session's checkout. It is installed only in a SECOND
    clone on this iMac (~/capstone_project/src/ui/.claude/skills/ui-ux-pro-max, untracked). I ran
    it from there (not copied, not committed). Its --design-system output did not fit (it matched
    an app-store landing page with esports fonts Russo One / Chakra Petch and an orange CTA), so
    I kept the brief's fixed choices (Montserrat, #1F4E9D). I applied its UX database rules:
    touch ≥ 44 px + ≥ 8 px gaps, no color-only status, contrast ≥ 4.5 (we are at AAA), visible
    focus ring (added), reduced motion (added), no emoji icons, numeric keyboards (km/liters
    yes; phone see risks).
  - Status colors darkened to AAA (point 3); T3 hex values replaced.
  - Oil grade is in card 1 (always visible, 0 taps if unchanged); liters/driver/phone stay in
    «Өмнөхөөс авсан» for existing trucks.
  - Fleet-mode link also on the capture step: a truck without a plate can't be photographed
    for plate reading.
  - Plate box now in Montserrat (tabular numbers), was monospace (brief: Montserrat everywhere).
METRICS / EVIDENCE:
  - pytest (full repo): 601 passed, 3 skipped (2 backend ONNX + opt-in browser), exit 0.
    UI tests: 103 (+9 T6: defaults/hidden fields, existing hides company+model, «Бусад» oil and
    model saved as typed, existing fleet sends company, photo preview confirm+form + single
    upload, undecodable photo → text, model list + old value, oil split/resolve, AAA contrast).
  - Opt-in browser (UI_BROWSER=1, live API, 390 px): 7 passed, incl. new CSS check (header row
    below Streamlit's top bar; dark button really dark). That check caught 2 CSS bugs the
    AppTest suite cannot see: header hidden under the viewer top bar, and the «Камераар хайх»
    button white-on-white. Both fixed.
  - 390 px walkthrough, 15 screens, scrollWidth 390 on all (no sideways scroll): home, capture,
    manual+photo, confirm+photo, model search, new form, success, new card (B1, ok), existing form,
    search, cards overdue / due soon (fleet) / ok, fleet mode, dashboard. Screenshots (fake data):
    ~/Desktop/sncir/ui_screenshots/v3/ (git-ignored PNGs; regenerate with tests/test_ui_browser.py).
ASSUMPTIONS NEEDING PM/ARI CONFIRMATION:
  1. Brief text was cut off at "390 px Chrome" (see STATUS). Anything else in DONE WHEN?
  2. Status colors are darker than the T3 hex values (AAA instead of AA). OK?
  3. The 26-model list and oil grades are from the brief; Ari to confirm spellings
     ("HOWO (Sinotruk)" vs old data "Howo A7", which still shows as its own option).
  4. Should «Сануулга» (manager) also lose the ⋮ menu? Only possible with CSS that hides
     Streamlit's own header; not done.
PROBLEMS / RISKS:
  - SECOND CLONE + CONTAINERS: during T6 someone ran `docker compose up` from
    ~/capstone_project (branch ui @ 1c856cd, clean except the untracked skill). That recreated
    ocp-api/ocp-db from that folder, whose ./models is EMPTY → live API = no predictions
    (cards null, /reminders/due 503). I did NOT touch it. For my checks I ran a separate API
    container (ocp-api-t6, port 8001, my ./models, same DB) and removed it afterwards. Before the
    demo on the Mac: make sure the API runs from the folder that has ./models (README /
    ui_run.md §0), else the demo shows "Таамаглал удахгүй нэмэгдэнэ" everywhere.
  - Phone field opens the full keyboard (st.text_input has no inputmode); km/liters numeric OK.
  - Destination pills still English until name_mn lands (contract v0.6 not on main yet).
  - Streamlit built-ins stay English ("Take Photo", "Upload", "Help for …" aria labels).
  - Full suite: rare native abort at interpreter exit (see T5 handoff); not seen in T6 runs.
CONTRACT CHANGES: none (oil_changer optional → simply not sent).
SLIDE MATERIAL: v3 screenshots; "status = biggest block, word + color, AAA contrast for
  sunlight"; "returning truck: photo → «Зөв» → km + destination tap → «Хадгалах»; oil grade,
  liters, driver pre-filled".
NEXT STEP: Ari OK → small commits to ui (design · form · card/search · tests+docs), suite
  green before each push. PR ui → main stays the boss's decision.
```
