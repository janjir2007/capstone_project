# HANDOFF REPORT — T9 (UI matches the mockup PDF)

```
HANDOFF REPORT
TASK ID: T9 (Streamlit app matches the mockup PDF)
STATUS: DONE locally, tests green; NOT committed/pushed yet (waiting for Ari's OK, CLAUDE.md).
  Demo-known-good stays 21124d2.
SUMMARY:
  Theme + CSS + layout in src/ui/ only (DESIGN v5). Screens (mockup page → screen):
  1. Home (p1): «ГЭ Гео-Эксперт» + date, «Сайн байна уу» + «Өнөөдөр N машин сануулга хүлээж
     байна.», numbers card (Сануулах · Хэтэрсэн · Машин), blue «Үйлчилгээ бүртгэх», one card
     «Хайх» / «Сануулга» with red badge, «Сүүлд үзсэн» rows (plate · company · status).
  2. Recognized truck (p2) «Машин танигдлаа»: plate strip cropped from the photo around the
     detected box + «✓ Автоматаар уншсан», truck card + «Буруу», arrival block («Цагтаа ирсэн ·
     2 хоног эрт ирсэн · Таамаглаж байсан огноо»), «Өмнөх удаа», odometer, destination pills +
     amber «Өмнө нь X байсан → шинэ чиглэлээр дахин таамаглана», Тос/Жолооч rows + «Тос, жолооч
     өөрчлөх», «Хадгалах», «Машины карт бүтэн харах».
  3. Full form (p3) «Үйлчилгээ бүртгэх»: header card (plate tile, status, «Засах»), «Энэ удаа»
     (km + «Өмнөх», pills, oil segmented control, liters − 30 + with «Ердийн»), «Жолооч» card.
  4. Card (p4): big plate, status block «5 хоног хоцорсон · Солих ёстой байсан: 10-р сарын 7»,
     fact rows, «Түүх» timeline, «+ Үйлчилгээ бүртгэх».
  5. Reminders (p5): info card, 3 tiles, «Өнөөдрийн дараалал» / «Эрсдэлтэй» cards (row: plate,
     driver, days · phone, status pill, message + copy, «Залгах», «Илгээсэн»), «Удахгүй».
  6. Dashboard: «Тойм» = segment tiles (moved out of «Сануулга»; linked from it).
  Flow change that the layout needs: a plate no longer has a separate confirm step — lookup goes
  straight to the form, whose header shows the plate + «Бүртгэлтэй/Шинэ машин» + «Буруу»/«Засах».
  Confirm stays only for a fleet number found in a company (company choice, D-005).
FILES: src/ui/common.py, src/ui/logic.py, src/ui/app.py, src/ui/views/{home,record,search,card,
  reminders}.py, NEW src/ui/views/dashboard.py, tests/test_ui_{app,logic,browser}.py,
  docs/ui_screens.md, docs/ui_handoff_t9.md
HOW TO RUN: unchanged — docs/ui_run.md (cd src/ui && streamlit run app.py).
DECISIONS MADE:
  - Only real API data is shown. Mockup items with no endpoint are replaced, not faked:
    home «Өнөөдөр 5» (services today) → «Машин» (total, /stats/segments); reminders «Автомат
    илгээлт · Viber 09:00» toggle → «Гараар илгээнэ» info card; «Илгээсэн 24» / «Алдаа 1» tiles
    → «Хэтэрсэн» / «Эрсдэлтэй»; delivery statuses («Хүргэгдсэн», «Viber бүртгэлгүй») and
    «Дахин илгээх» → status pill + «Залгах» (tel:) + «Илгээсэн».
  - Recognized layout only for an EXISTING truck read from a photo; typed / card / search / new
    → full form. Arrival words: >14 days early «Эрт ирсэн», 0–14 «Цагтаа ирсэн», late «Хоцорсон».
  - «Удахгүй» = GET /reminders/due?as_of=(API today + 7) minus today's list (no contract change).
  - Overdue wording on the card: «хоцорсон» (mockup) instead of «хэтэрсэн»; status word unchanged.
METRICS / EVIDENCE:
  - pytest (full repo): 618 passed, 3 skipped. UI: 120 passed (new tests: recognized layout +
    destination-change note + save, «Буруу» back to edit, home numbers/badge, overview tiles,
    reminder «Залгах» link, logic helpers for dates/phone/arrival/previous visit/counts).
  - Opt-in browser (390 px): 20 passed against a fake API with predictions; 19 passed + 1 skipped
    against the local API. New check: no block starts < 12 px below the previous one (this caught
    Streamlit's markdown margin -1rem making HTML blocks overlap — fixed in CSS).
  - Screenshots (fake data, not in git): ~/Desktop/sncir/ui_screenshots/t9/ (1_home … 6_dashboard).
ASSUMPTIONS NEEDING PM/ARI CONFIRMATION:
  1. The substitutions listed above for mockup items the API cannot provide (auto-send, sent /
     error counts, services today). Real versions need backend endpoints.
  2. The mockup PDF has 5 pages; «dashboard» was built as the segment overview in the same style.
  3. Dropping the separate confirm step for plates (the header «Буруу»/«Засах» replaces it).
PROBLEMS / RISKS:
  - The local DB has no Mongolian destination names (name_mn, migration 002) → pills show the
    English names until the backend applies it; the UI already prefers name_mn.
  - The local API has no model files → no predictions/reminders there; the card status block,
    arrival block and reminders lists were checked against the fake API.
  - CSS hooks onto Streamlit internals (stNumberInputStepDown, stButtonGroup, markdown margin);
    the browser test checks the key ones, so a Streamlit upgrade shows up as a failing test.
  - Icon buttons: Streamlit puts the Material icon name into the button text, so a screen reader
    may hear "arrow_back_ios_new Буцах" (Streamlit behaviour).
CONTRACT CHANGES: none.
NEXT STEP: Ari's OK → commits on branch ui (theme/CSS+components, screens, tests, docs) → push →
  check the Actions tab. PR ui → main stays the boss's decision.
```
