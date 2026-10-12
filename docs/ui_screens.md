# UI screens — Streamlit frontend (tasks 5.1–5.4)

- **Owner:** Frontend Engineer (iMac, branch `ui`, D-052) · **Version:** 0.4 (2026-10-12, DESIGN v2 + 5.4 dashboard)
- Stack: Streamlit 1.64 (D-022), calls FastAPI over HTTP only (`docs/api_contract.md` v0.5).
- UI text: Mongolian. Fake demo data only (RISK-06).

## Run

```bash
pip install -r requirements-ui.txt              # Python 3.11 venv
docker compose up -d --build                    # db + api on :8000
cd src/ui && streamlit run app.py               # from src/ui/ -> .streamlit/config.toml theme applies
# phone on the same Wi-Fi: http://<mac-ip>:8501
```

| Env var | Default | Meaning |
|---|---|---|
| `API_URL` | `http://localhost:8000` | FastAPI base URL |
| `UI_PASSWORD` | unset | Set → password screen (D-061). Unset/empty → no login (local dev) |

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

The folder is `views/`, **not** `pages/`: Streamlit runs a folder named `pages/` in legacy mode,
which skips `app.py` (and the login gate) when a URL is opened directly. Guarded by
`test_no_streamlit_pages_folder`.

## DESIGN v2 (how it is built)

- Theme (config.toml): grey background, white cards, black text, primary #1F4E9D, one column
  (max 560 px).
- White cards = `st.container(key="card_…")`; CSS hooks on Streamlit's `st-key-card_…` class:
  radius 24, soft shadow. All buttons ≥ 56 px, radius 18. Black button = key `btn_black…`.
- Header on every screen: «Гео-Эксперт» pill + big title; inner screens have «‹ Буцах».
- Navigation menu is hidden; screens are linked by their big buttons.

## Screens

**Login** (only if `UI_PASSWORD` set): password card → «Нэвтрэх». Until logged in only this page
exists, so a direct URL cannot skip it.

**Нүүр (Home)**: big primary card «📷 Бүртгэх» (opens the camera step), white card «🔍 Хайх»,
link «Сануулга» → dashboard.

**Бүртгэх (Record)**
1. *Capture*: camera (+ upload jpg/png/heic). New photo → `POST /plates/recognize` (field `file`,
   not stored). Clear read → lookup → confirm. `needs_manual` or recognizer down → manual step
   with the read text and a reason message. «Дугаарыг гараар оруулах» → manual.
2. *Manual*: Улсын дугаар / Парк дугаар + «Дугаар» → «Шалгах» → lookup → confirm. A phone typed
   here → hint to use «Хайх».
3. *Confirm*: plate large in monospace in a bordered box + chip «Бүртгэлтэй · N удаа ирсэн» (green)
   or «Шинэ машин» (blue); fleet number in several companies → company radio. «Зөв, үргэлжлүүлэх»
   / «Буруу байна — засах» (back to manual, plate kept).
4. *Form*: small plate box + chip. Card 1 (always fresh, D-033): «Гүйлт (км)» (hint = previous km),
   «Моторын цаг» (fleet numbers, or if the truck had hours before), «Дараа нь хаашаа явах вэ?» as tap
   pills from `GET /destinations` (`name_mn` else `name`) + «Бусад» → place name + route pills
   (D-039). Card 2: existing truck → «Өмнөхөөс авсан» one line (oil · liters · driver · phone) +
   «Засах» expander; new truck → company, model, oil, liters, driver, phone, oil changer.
   «Хадгалах» → `POST /services` (no date: API = today). 409 duplicate → warning +
   «Ингээд хадгалах» (`force=true`) / «Болих». 422 → Mongolian messages.
5. *Success*: ✓ «Хадгалагдлаа», plate, «Дараагийн машин» (back to camera; oil changer remembered),
   «Машины карт үзэх».

**Хайх (Search)**: white card with input + «Хайх» (primary) and black «📷 Камераар хайх» (camera +
upload; clear read searches, `needs_manual` fills the field). One match → card opens; several →
list (plate · company · segment); none → «Олдсонгүй» + «Шинэ машин бүртгэх» (form, new truck).
«Сүүлд үзсэн»: cards opened in this session (max 5).

**Машины карт (Card)** (fresh `GET /vehicles/{id}`): plate box + segment badge (Шинэ / Давтан /
Байнгын / Эрсдэлтэй), company · model · N удаа · ердийн L; **status card** from `prediction`:
ok #1e6b34 on #e3f1e7 «Хэвийн», due_soon #8a5300 on #fbefd6 «Удахгүй», overdue #b3261e on
#f9e3e1 «Хэтэрсэн»; big «N хоног үлдсэн/хэтэрсэн», `predicted_date`, progress bar (share of
last_service_date → predicted_date used), note = method + fallback_reason; `null` → grey
«Таамаглал удахгүй нэмэгдэнэ». 3 tiles: Сүүлд солисон, Тос (grade · liters), Чиглэл. Call row
«Жолооч · утас — Залгах» (`tel:` link). «Түүх (N)» expander. Primary «Тос солилт бүртгэх».

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

- Built-in widget text stays English: camera permission prompt ("This app would like to use your
  camera", "Take Photo"), uploader ("Upload", "15MB per file" — limit set to the API's 15 MB in config.toml).
- The copy button's tooltip says "Copy to clipboard" (built-in).
- Pills wrap to several rows on a phone (7 destinations).
- No real "card" component: white cards are keyed containers + CSS.
