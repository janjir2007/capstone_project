# UI screens — Streamlit frontend (tasks 5.1–5.4)

- **Owner:** Frontend Engineer (iMac, branch `ui`, D-052) · **Version:** 0.6 (2026-10-12, T6: DESIGN v3 + simpler form)
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
| `src/ui/views/reminders.py` | «Сануулга» manager dashboard (5.4) |
| `src/ui/common.py` | DESIGN v2 CSS, header, plate box, chips, card parts, navigation hand-off |
| `src/ui/api_client.py` | HTTP client (no Streamlit): one function per endpoint, `ApiError`, `DuplicateService` |
| `src/ui/logic.py` | Pure helpers: labels, pre-fill, payload, prediction view, recognize outcome, errors |
| `src/ui/auth.py` | `UI_PASSWORD` check (constant-time compare) |
| `src/ui/Dockerfile` (+ `.dockerignore`) | UI image: python:3.11-slim, non-root, WORKDIR src/ui, port 8501 |

The folder is `views/`, **not** `pages/`: Streamlit runs a folder named `pages/` in legacy mode,
which skips `app.py` (and the login gate) when a URL is opened directly. Guarded by
`test_no_streamlit_pages_folder`.

## DESIGN v3 (T6) — how it is built

- **Font:** Montserrat (Google Fonts via `theme.font` in config.toml). Mongolian Ө ө Ү ү render in
  Montserrat (Chrome DevTools: all glyphs from Montserrat, no fallback font; control text in
  `sans-serif` → Helvetica).
- **Colors** (WCAG contrast computed): text #14171C 18:1, muted #4A5160 7.3:1, white on primary
  #1F4E9D 8:1 (placeholder brand color). Status, the same everywhere (card, dashboard), always with
  the word next to the color: Хэвийн #14532D on #E3F1E7 (7.8:1) · Удахгүй #6B3F00 on #FBEFD6 (7.9:1)
  · Хэтэрсэн #8C1D18 on #F9E3E1 (7.4:1) · no prediction #3F4552 on #ECEEF1 (8.3:1). All AAA,
  for outdoor light. `tests/test_ui_logic.py::test_status_colors_are_aaa_contrast` guards it.
- **Spacing** 4/8/12/16/24/32 px · **type** title 28/800, section 18/700, body 16/500, small 14
  (nothing smaller) · **tap targets** buttons ≥ 56 px, pills ≥ 48 px, links ≥ 44 px, gaps ≥ 8 px.
- White cards = `st.container(key="card_…")` (radius 20, soft shadow); dark button = key `btn_dark…`;
  visible focus ring (3 px primary); `prefers-reduced-motion` respected.
- No emoji: Material icons on buttons (camera, search, keyboard) and in the browser tab.
- Header on every screen: «Гео-Эксперт» pill + big title; inner screens have «‹ Буцах».
  Top padding 64 px keeps it below Streamlit's top bar (checked in `tests/test_ui_browser.py`).
- Toolbar: `client.toolbarMode = "viewer"` (no Deploy / developer menu; the ⋮ viewer menu stays).

## Screens

**Login** (only if `UI_PASSWORD` set): password card → «Нэвтрэх». Until logged in only this page
exists, so a direct URL cannot skip it.

**Нүүр (Home)**: big primary card «Бүртгэх» with a camera icon (opens the camera step), white card «Хайх»,
link «Сануулга» → dashboard.

**Бүртгэх (Record)**
1. *Capture*: camera (+ upload jpg/png/heic/heif, also upper-case `IMG_0001.HEIC` from an iPhone,
   sent as `image/heic` when the browser gives no type, RISK-17). New photo → `POST /plates/recognize`
   (field `file`). Clear read → lookup → confirm. `needs_manual` or recognizer down → manual step
   with the read text and a reason message. «Дугаарыг гараар оруулах» → manual; small
   «Дугааргүй машин» → manual in **fleet-number mode** (D-005; no radio on the main form).
2. *Manual*: «Улсын дугаар» (or «Парк дугаар») → «Шалгах» → lookup → confirm. «Дугааргүй машин» /
   «Улсын дугаартай машин» toggles the mode. A phone typed here → hint to use «Хайх».
3. *Confirm*: **photo preview** + plate large in a bordered box + chip «Бүртгэлтэй · N удаа ирсэн» /
   «Шинэ машин»; fleet number in several companies → company radio. «Зөв, үргэлжлүүлэх» /
   «Буруу байна — засах».
4. *Form*: photo preview, small plate box + chip.
   - Card 1 (always fresh, D-033): «Гүйлт (км)» (numeric keypad; hint = previous km), «Моторын цаг»
     (fleet numbers, or if the truck had hours before), «Дараа нь хаашаа явах вэ?» tap pills from
     `GET /destinations` (`name_mn` when present, else `name`, D-071) + «Бусад» → place + route,
     **«Тосны төрөл»: 15W-40 · 10W-40 · 20W-50 · «Бусад»** (free text); default = last service value
     (not in the 3 → «Бусад» with it as text), else 15W-40.
   - Card 2, existing truck: «Өмнөхөөс авсан» one line (liters · driver · phone) + «Засах».
     **No company field** (the API ignores it for an existing plate; for a fleet number the UI sends
     the chosen truck's company, D-042).
   - Card 2, new truck: «Компани / эзэмшигч» (required, D-042, no default), **«Машины загвар»
     searchable list** (26 models, `logic.VEHICLE_MODELS`) + «Бусад» (free text; an old value not in
     the list still shows, D-019), liters, driver, phone.
   - **«Тос солигч» removed** (optional in the contract; not sent).
   - «Хадгалах» → `POST /services`; 409 duplicate → «Ингээд хадгалах» (`force=true`) / «Болих».
5. *Success*: check mark «Хадгалагдлаа», plate, «Дараагийн машин», «Машины карт үзэх».

The photo lives only in this browser session for the preview; it is never stored and never sent
anywhere except `POST /plates/recognize` (D-070). A photo the UI cannot decode (iPhone HEIC: the API
converts it, the UI has no HEIC decoder) shows «Зураг: … (урьдчилж харах боломжгүй)», never an error.

**Хайх (Search)**: white card with «Улсын дугаар эсвэл утас» + «Хайх» (primary; the API still matches
fleet numbers) and dark «Камераар хайх» (camera +
upload; clear read searches, `needs_manual` fills the field). One match → card opens; several →
list (plate · company · segment); none → «Олдсонгүй» + «Шинэ машин бүртгэх» (form, new truck).
«Сүүлд үзсэн»: cards opened in this session (max 5).

**Машины карт (Card)** (fresh `GET /vehicles/{id}`), ordered by importance: **plate** large →
**status block**, the biggest colored block: status word (Хэвийн / Удахгүй / Хэтэрсэн), big «N хоног
үлдсэн/хэтэрсэн», «Дараагийн солилт: date», progress bar, small method note; `null` → grey
«Таамаглал удахгүй нэмэгдэнэ» → segment badge (Шинэ / Давтан / Байнгын / Эрсдэлтэй) + company ·
model · N удаа · ердийн L → **4 tiles** (2×2): Сүүлд солисон, Тос (grade · liters), Чиглэл, Жолооч
(name · phone) → «Түүх (N)» collapsed → primary «Тос солилт бүртгэх». No «Залгах» button (T6).

**Сануулга (Manager dashboard, 5.4)** — wider on desktop (max 1100 px), 2×2 tiles on a phone.
- 4 segment tiles from `GET /stats/segments` (Шинэ / Давтан / Байнгын / Эрсдэлтэй) + total, as_of.
- `GET /reminders/due` split in two groups, API order kept (oldest `send_on` first):
  **«Илгээх»** and **«Эрсдэлтэй»** = at_risk by D-007 (`days_left < −7`, i.e. predicted date +
  7 days grace already passed; same rule and number as the API).
- Row (white card): plate box, status chip (same colors as the card) + «N хоног үлдсэн/хэтэрсэн»,
  📞 phone · driver · company, «Илгээх өдөр» (send_on) · predicted date · last change, the
  `message_mn` text in a code box whose built-in button copies it to the clipboard, and
  «Илгээсэн» → `POST /reminders/{service_id}/sent`: new → «Илгээсэн гэж тэмдэглэлээ» and the row
  leaves the list; `already_sent` → «Өмнө нь илгээсэн гэж тэмдэглэгдсэн (time)»;
  409 `not_latest_service` → «шинэ үйлчилгээтэй болсон» + list reloaded.
- `contact_is_placeholder` → warning that the contact phone in the text is a placeholder.
  503 → «Таамаглалын загвар ачаалагдаагүй». The API sends no SMS: the manager copies and sends.

## Streamlit limits (accepted, "close is enough")

- The phone field opens the full keyboard: `st.text_input` cannot set `inputmode="tel"` (km and
  liters are number inputs → numeric keypad).
- Built-in widget text stays English: camera permission prompt ("This app would like to use your
  camera", "Take Photo"), uploader ("Upload", "15MB per file" — limit set to the API's 15 MB in config.toml).
- The copy button's tooltip says "Copy to clipboard"; help icons are announced as "Help for …"
  (built-in).
- Pills wrap to several rows on a phone (7 destinations).
- No real "card" component: white cards are keyed containers + CSS.
