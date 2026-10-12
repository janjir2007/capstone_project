# UI screens — Streamlit frontend (tasks 5.1–5.4)

- **Owner:** Frontend Engineer (iMac, branch `ui`, D-052) · **Version:** 0.9 (2026-10-12, T9: layout matches the mockup PDF)
- Stack: Streamlit 1.64 (D-022), calls FastAPI over HTTP only (`docs/api_contract.md` v0.5).
- UI text: Mongolian. Fake demo data only (RISK-06).

## Run

See **[`ui_run.md`](ui_run.md)**: local run (start from `src/ui/` so the theme loads), env vars
`API_URL` / `UI_PASSWORD`, Docker image (`src/ui/Dockerfile`), and the compose service values for 6.1.
Tests: `pytest -v tests/test_ui_*.py` (API mocked with `httpx.MockTransport`; screen tests use
Streamlit `AppTest` and are skipped if Streamlit is not installed).

## Code map

| File | Role |
|---|---|
| `src/ui/app.py` | Entry: page config, login gate, hidden navigation |
| `src/ui/.streamlit/config.toml` | Theme: background #F4F5F7, primary #1F4E9D (placeholder), radius, minimal toolbar |
| `src/ui/views/home.py` | Home |
| `src/ui/views/record.py` | Record flow (5.2): capture → manual → confirm → form → success |
| `src/ui/views/search.py` | Search (5.3) |
| `src/ui/views/card.py` | Vehicle card (5.3) |
| `src/ui/views/reminders.py` | «Сануулга» manager screen (5.4) |
| `src/ui/views/dashboard.py` | «Тойм»: segment tiles (5.4), opened from «Сануулга» |
| `src/ui/common.py` | DESIGN v5 CSS, header, plate chip, chips, row cards, status/arrival blocks, fact rows, timeline, plate strip, navigation hand-off |
| `src/ui/api_client.py` | HTTP client (no Streamlit): one function per endpoint, `ApiError`, `DuplicateService` |
| `src/ui/logic.py` | Pure helpers: labels, pre-fill, payload, prediction view, recognize outcome, errors |
| `src/ui/auth.py` | `UI_PASSWORD` check (constant-time compare) |
| `src/ui/Dockerfile` (+ `.dockerignore`) | UI image: python:3.11-slim, non-root, WORKDIR src/ui, port 8501 |

The folder is `views/`, **not** `pages/`: Streamlit runs a folder named `pages/` in legacy mode,
which skips `app.py` (and the login gate) when a URL is opened directly. Guarded by
`test_no_streamlit_pages_folder`.

## DESIGN v5 (T9) — the mockup PDF

Supersedes DESIGN v4 (T7) and the T8 spacing values. Source: the 5-page mockup (home, recognized
truck, full form, card, reminders) + the brief (Montserrat 400/500/600, line-height 1.4, bg
#F6F7F9, white cards radius 18, soft shadow, no borders).

- **Type:** home greeting 26/600 · screen title 20/600 (same row as the back chevron) · section
  label 14/600 grey (or 16/600 dark for «Сүүлд үзсэн», «Энэ удаагийн мэдээлэл») · body 15 ·
  labels 14/500 · status number 34/600 · tile numbers 26/600. Max weight 600, line-height 1.4.
- **Surfaces:** cards = `st.container(key="card_…")`, white, radius 18, shadow
  `0 1px 2px rgba(16,24,40,.04), 0 4px 16px rgba(16,24,40,.05)`, padding 20. Row groups =
  `grp_…` containers holding tappable `act_…` rows (button stretched over the row) with thin
  dividers. Inputs 52 px, grey fill, radius 14, 16 px text (no iOS zoom), primary border on focus.
- **Controls:** destination = round pills (selected primary, «Бусад» grey text); oil grade =
  segmented control (grey track, selected segment white); liters = − value + stepper; km field
  has no stepper. Primary button 54 px, radius 16, soft blue glow; secondary grey in cards.
- **Status** (word + dot, never color alone; same colors as v4): card block «Хэтэрсэн · 5 хоног
  хоцорсон · Солих ёстой байсан: 10-р сарын 7 · method»; recognized truck arrival block
  «Цагтаа ирсэн (0–14 days early) / Эрт ирсэн (>14) / Хоцорсон (late)».
- **Spacing:** page 12 top / 20 sides / 40 bottom, max 480 px · element → element 12 · section
  label → its card 8 · card padding 20. HTML blocks never spill out of their Streamlit box
  (Streamlit's markdown `margin-bottom: -1rem` is reset). Checked by
  `tests/test_ui_browser.py::test_spacing_exact_values` (no block starts < 12 px below the previous).

## Screens

**Login** (only if `UI_PASSWORD` set): password card → «Нэвтрэх». Until logged in only this page
exists, so a direct URL cannot skip it.

**Нүүр (Home)**: «ГЭ Гео-Эксперт» + today («10-р сарын 12, Даваа»), «Сайн байна уу», line «Өнөөдөр N
машин сануулга хүлээж байна.» → numbers card: Сануулах (the «Илгээх» group of `GET /reminders/due`),
Хэтэрсэн (days_left < 0, red), Машин (`GET /stats/segments` total); «—» when unavailable → blue
«Үйлчилгээ бүртгэх» (camera step) → one card «Хайх» / «Сануулга» (red count badge) → «Сүүлд үзсэн»
rows (plate · company · status), this session only.

**Бүртгэх (Record)**
1. *Capture*: camera + upload (jpg/png/heic/heif, RISK-17) → `POST /plates/recognize`. Clear read →
   lookup → form. `needs_manual` / recognizer down → manual. «Дугаарыг гараар оруулах»; small
   «Дугааргүй машин» → manual in fleet-number mode (D-005).
2. *Manual*: plate (or fleet number) → «Шалгах» → lookup → form.
3. *Confirm* (fleet number found in one or more companies only): «Аль компанийн машин бэ?».
   A plate goes straight to the form (T9).
4. *Form*, two layouts:
   - **«Машин танигдлаа»** (existing truck read from a photo): plate strip (crop of the photo
     around the detected box, in memory only, D-070) with «✓ Автоматаар уншсан» → truck card
     (plate, segment · N удаа · company, «Буруу» → manual) + arrival block + «Өмнөх удаа
     08-19 · 186 300 км · Замын-Үүд» → «Энэ удаагийн мэдээлэл»: odometer, «Одоо хаашаа явах вэ?»
     pills (+ amber note when it differs from last time), rows Тос / Жолооч, «Тос, жолооч өөрчлөх»
     (oil, liters, name, phone) → «Хадгалах» → «Машины карт бүтэн харах».
   - **«Үйлчилгээ бүртгэх»** (typed plate, from card/search, new truck): header card (plate tile,
     plate, «● Бүртгэлтэй · N удаа ирсэн» / «● Шинэ машин», «Засах») → new truck only: «Машин»
     (company only for fleet numbers, T8; model list + «Бусад») → «Энэ удаа»: km («Өмнөх: … км»),
     engine hours (fleet / had hours), destination pills («Бусад» → place + route, D-039), oil
     segmented control (default = last service, else 15W-40), liters stepper («Ердийн: 30 л») →
     «Жолооч»: name, phone («Өмнөх үйлчилгээнээс бөглөгдсөн…») → «Хадгалах».
   - Payload rules unchanged (T8): new plate vehicle → `company_name = "Тодорхойгүй"`; 409
     duplicate → «Ингээд хадгалах» (`force=true`) / «Болих».
5. *Success*: «Хадгалагдлаа», plate, «Дараагийн машин», «Машины карт үзэх».

**Хайх (Search)**: unchanged behaviour (one match → card; several → list; none → «Шинэ машин
бүртгэх»); «Сүүлд үзсэн» uses the same rows as home.

**Машины карт (Card)**: big plate (white, thin line) + segment chip → company · model → status block
(null → «Таамаглал удахгүй нэмэгдэнэ») → fact rows (Сүүлд солисон, Тос «15W-40 · ердийн 32 л»,
Чиглэл, Жолооч «Ганбат Т. · 9911 0002») → «Түүх» timeline (newest blue dot) → «+ Үйлчилгээ бүртгэх».

**Сануулга (5.4)**: «Гараар илгээнэ» card (the API sends nothing) → tiles Өнөөдөр / Хэтэрсэн /
Эрсдэлтэй → «Өнөөдрийн дараалал (N)» and «Эрсдэлтэй (N)» (D-007), one card each; row = plate,
driver, «5 хоног хэтэрсэн · 9911 0002», status pill, `message_mn` (copy button), «Залгах»
(`tel:`), «Илгээсэн» → `POST /reminders/{service_id}/sent` (already_sent / not_latest_service as
before) → «Удахгүй»: `GET /reminders/due?as_of=<API today + 7>` minus today's list → «Машинуудын
тойм харах», «Шинэчлэх». 503 → «Таамаглалын загвар ачаалагдаагүй».

**Тойм (dashboard, 5.4)**: 2×2 segment tiles (number + dot + word: Шинэ / Давтан / Байнгын /
Эрсдэлтэй), «Нийт N машин · as_of».

## Streamlit limits (accepted, "close is enough")

- The phone field opens the full keyboard: `st.text_input` cannot set `inputmode="tel"` (km and
  liters are number inputs → numeric keypad).
- Built-in widget text stays English: camera permission prompt ("This app would like to use your
  camera", "Take Photo"), uploader ("Upload", "15MB per file" — limit set to the API's 15 MB in config.toml).
- The copy button's tooltip says "Copy to clipboard"; help icons are announced as "Help for …"
  (built-in).
- Pills wrap to several rows on a phone (7 destinations).
- No real "card" component: white cards are keyed containers + CSS.
