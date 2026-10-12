# HANDOFF REPORT — T7 (design polish: calm, modern, light)

```
HANDOFF REPORT
TASK ID: T7 (design polish — calm, modern, light)
STATUS: DONE — pushed to origin/ui (hashes in NEXT STEP). Demo-known-good stays 21124d2.
SUMMARY:
  Answer to Ari's feedback (too plain, text too big/bold, too many borders/labels). Only theme +
  CSS + layout inside src/ui/. No new features, no backend or contract change.
  1. Type: Montserrat 400/500/600 only. Title 22/600, section 15/600, body 15/400, labels 13/500
     grey #6B7280, big numbers 28/600 (dashboard 24/600). Max weight 600, checked in a real browser
     on every screen.
  2. Surfaces: almost no borders. White cards radius 16 + shadow 0 1px 3px rgba(0,0,0,.06).
     Inputs: grey fill, no border, 1 px primary only on focus. Plate = small grey chip (1 px
     #E5E7EB, 19/600, letter-spacing .05em), no thick black box. Info pairs = label + value, no tiles.
  3. Color: background #F6F7F9, text #111827, secondary #6B7280. Primary #1F4E9D only for main
     buttons, the «Бүртгэх» home card and selected chips. Status = soft tint + dot + word, Ari's
     values (OK #1E7A4C/#E8F5EE, Удахгүй #A05A00/#FFF4E0, Хэтэрсэн #B42318/#FDECEC).
  4. Home: «Сайн байна уу · 10-р сарын 11, Ням» + 3 row cards (icon, title, 1-line subtitle,
     chevron): «Бүртгэх — Зураг авч бүртгэх», «Хайх — Дугаар эсвэл утсаар», «Сануулга —
     Өнөөдөр сануулах: N» (count from GET /reminders/due; plain subtitle if the API is down/503).
     The whole card is one tap target.
  5. Card: plate chip + grey segment chip with dot («Давтан · 2 удаа», replaces the colored badge),
     one line company · model, compact status block (dot + word, days 28/600, date, 4 px bar, note
     12 px), 4 info pairs, history collapsed (no border).
  6. Record: «Дугааргүй машин» / «Зураг авах» = text buttons 14/600 primary. Photo preview = 120 px
     thumbnail, radius 12. Chips 36 px tall, 14 px, wrap; selected = primary fill, white text.
  7. Dashboard: 4 segment tiles with colored dot, number 24/600; placeholder-phone warning = one
     small grey line (was a big yellow block); rows use the plate chip + dot status chip.
  8. Buttons 52 px, radius 14, 16/600; secondary white + soft shadow (grey fill inside a card);
     «Камераар хайх» is no longer a black button.
FILES: src/ui/.streamlit/config.toml, src/ui/common.py, src/ui/logic.py,
  src/ui/views/{home,card,record,search,reminders}.py, tests/test_ui_{app,logic,browser}.py,
  docs/ui_screens.md, docs/ui_handoff_t7.md
HOW TO RUN: unchanged — docs/ui_run.md (cd src/ui && streamlit run app.py). After editing
  common.py/logic.py restart Streamlit: it does not reload imported modules on its own.
DECISIONS MADE:
  - ui-ux-pro-max (run from the second clone's untracked copy, nothing copied/committed): kept its
    rules: visible labels above inputs (not placeholder-only), focus ring, contrast ≥ 4.5:1,
    44 px touch targets for text buttons. Its "soft UI / neumorphism" match warns of low contrast,
    so every grey and tint was measured (numbers in docs/ui_screens.md).
  - Status colors are now WCAG AA (4.75–5.76:1), not AAA as in T6 — they are Ari's T7 values.
    The test now guards ≥ 4.5:1 (was ≥ 7:1).
  - Home cards: Streamlit buttons cannot hold a 2-line label with icon, so each card is HTML and
    the real st.button / st.page_link is stretched over it (keeps its accessible name; tests still
    click "Бүртгэх" / "Хайх" / page_link "Сануулга"). Browser test taps the card itself.
  - Home summary shows only «Өнөөдөр сануулах: N» (the «Илгээх» group). Adding «Эрсдэлтэй: M»
    wrapped to 2 lines at 390 px; at-risk stays on the dashboard.
  - Card: «ердийн L» (usual liters) dropped from the top line (brief: "one line company · model");
    count moved into the segment chip. Last liters still in the «Тос» pair.
  - Chips: 36 px (brief) is below the 44 px touch guideline; kept with 8 px gaps as specified.
  - Before committing T7, the uncommitted T6 work was committed as its own baseline
    (e7182c2 code, 7c14b70 docs), so T7 is a separate, revertible change on top.
METRICS / EVIDENCE:
  - pytest (full repo): 604 passed, 3 skipped (2 backend ONNX + opt-in browser), exit 0.
    UI tests +3: home summary count, home works without predictions (503), Mongolian date text.
  - Opt-in browser (UI_BROWSER=1, live API, 390 px): 13 passed — incl. new: max weight ≤ 600 on
    4 screens, home card tap opens «Хайх», selected chip = rgb(31,78,157)/white and ≥ 36 px,
    secondary button grey + no border, theme background rgb(246,247,249).
  - 390 px walkthrough, 10 screens, scrollWidth 390 on all: home, search, cards overdue / due soon
    (fleet) / ok, existing form, capture, confirm, new form, dashboard.
  - Screenshots (fake data, git-ignored, not in git): ~/Desktop/sncir/ui_screenshots/v4/ (after),
    v3/ (before), t7_before_after/{home,record_form,record_form_existing,card,dashboard}.png.
ASSUMPTIONS NEEDING PM/ARI CONFIRMATION:
  1. Status colors AA instead of AAA (Ari's values) — OK for outdoor use?
  2. Usual liters removed from the card's top line — OK?
  3. Home summary = «Өнөөдөр сануулах: N» only (no at-risk count) — OK?
PROBLEMS / RISKS:
  - Home card = HTML + stretched button: depends on Streamlit's DOM classes
    (stElementContainer, st-key-*). The browser test catches a break after a Streamlit upgrade.
  - Destination chips still English until name_mn lands (contract v0.6 not on main yet).
  - Streamlit built-ins stay English ("Take Photo", "Upload").
  - Second clone ~/capstone_project still runs ocp-api with empty ./models (see T6 handoff).
CONTRACT CHANGES: none.
SLIDE MATERIAL: t7_before_after/*.png ("less ink, more space": 800 → 600 weight, no borders,
  status = soft tint + dot + word).
NEXT STEP: Ari reviews http://localhost:8501 / screenshots. PR ui → main stays the boss's decision.
```
