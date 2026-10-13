# HANDOFF REPORT — T8 (remove company field + fix spacing)

```
HANDOFF REPORT
TASK ID: T8 (remove company field + fix spacing)
STATUS: DONE — pushed to origin/ui. Demo-known-good stays 21124d2.
SUMMARY:
  1. COMPANY FIELD (Ari's decision), commit a67d052:
     - Plate vehicles: «Компани / эзэмшигч» removed from the form. A NEW plate vehicle is sent
       with company_name = "Тодорхойгүй" automatically (logic.UNKNOWN_COMPANY; API needs it, D-042).
     - «Дугааргүй машин» (fleet_no) mode keeps the field and still requires it (fleet numbers are
       unique per company). Existing fleet truck: the UI sends that truck's company (unchanged).
     - Existing plate truck: no company sent (unchanged).
     - Note for backend: backend may make company_name optional later → remove the default
       (logic.UNKNOWN_COMPANY + the 2 lines in build_service_payload).
  2. SPACING (exact values, CSS in src/ui/common.py), commit 1e2654a:
     - Streamlit header / top bar / ⋮ menu hidden. Page padding 16 top, 20 sides, 32 bottom.
       Content max-width 480 px, centered — every screen, including the dashboard (2×2 tiles).
     - Top row («‹ Буцах» + «Гео-Эксперт») 44 px → 8 px → title 22/600 → 16 px.
     - Element → element 12 px (Streamlit default was 15 px). Before/after a card or section 20 px.
     - Card padding 16. Label → input 6 px. Field → field 14 px inside cards.
     - No empty blocks: the CSS-only markdown blocks (0 px tall, but each took a 15 px gap at the
       top of every screen) are now taken out of the layout. No st.write("") spacers existed.
     - «Хадгалах» 20 px below the last card, full width, no frame.
     - Usual liters back in the «Тос» pair: «15W-40 · ердийн 30 л» (last liters if the API has
       no usual value); number + unit never split over two lines.
FILES: src/ui/common.py, src/ui/logic.py, src/ui/views/record.py, src/ui/views/reminders.py,
  tests/test_ui_{app,logic,browser}.py, docs/ui_screens.md, docs/ui_handoff_t8.md
HOW TO RUN: unchanged — docs/ui_run.md (cd src/ui && streamlit run app.py).
DECISIONS MADE:
  - Default company is set in logic.build_service_payload (one place, unit-tested) for
    is_new_vehicle AND identifier_type == "plate", so a stale typed value can never leak in.
  - Dashboard now uses the same 480 px column (brief: "content max-width 480px"); it was 1100 px
    on desktop. Segment tiles are 2×2 at every width.
  - Measured, not eyeballed: a script reads the real pixel gaps on 8 screens at 390 px (home,
    search, card, existing form, capture, new plate form, new fleet form, dashboard); all match.
METRICS / EVIDENCE:
  - pytest (full repo): 609 passed, 3 skipped (2 backend ONNX + opt-in browser), exit 0.
    New tests: new plate → company "Тодорхойгүй" and no field; new fleet → field shown, typed
    company sent; new fleet without company → blocked with Mongolian error, nothing sent;
    payload rules for plate/fleet; empty-form error counts; usual-liters pair text.
  - Opt-in browser (UI_BROWSER=1, live API, 390 px): 17 passed — new: exact padding 16/20/32,
    top row at y=16 and 44 px tall, top row → title 8 px, no empty blocks (4 screens),
    Streamlit top bar not visible.
  - Screenshots (fake data, not in git): ~/Desktop/sncir/ui_screenshots/v5/ (after),
    t8_before_after/{home,record_form_new,record_form_existing,card,dashboard}.png.
ASSUMPTIONS NEEDING PM/ARI CONFIRMATION:
  1. Every new plate vehicle shares ONE company record «Тодорхойгүй» in the DB; the card and
     reminder rows show «Тодорхойгүй» as the company. OK until backend makes it optional?
  2. Dashboard narrowed to 480 px on desktop (was 1100) — OK for the manager?
PROBLEMS / RISKS:
  - Hiding Streamlit's top bar also hides its ⋮ menu (Settings/Print) — intended by the brief.
  - Spacing rules hook onto Streamlit's internal test-ids (stVerticalBlock, stLayoutWrapper,
    stElementContainer). The browser test checks the exact values, so a Streamlit upgrade that
    changes them shows up as a failing test.
  - Second clone ~/capstone_project still serves the OLD T5 design on :8501 (someone started
    it there at 00:00). git pull on branch ui + restart to see T6–T8. My check ran on :8502.
CONTRACT CHANGES: none (company_name still sent for new vehicles; value is the default for plates).
NEXT STEP: Pushed to origin/ui: a67d052 (company field), 1e2654a (spacing), docs commit = tip
  of origin/ui (hash in the reply). PR ui → main stays the boss's decision.
```
