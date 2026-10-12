# UI screens — Streamlit frontend (tasks 5.1–5.4)

- **Owner:** Frontend Engineer (iMac, branch `ui`, D-052) · **Version:** 0.8 (2026-10-12, T8: no company field for plates + exact spacing)
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
| `src/ui/common.py` | DESIGN v4 CSS, header, plate chip, chips, home action cards, card parts, navigation hand-off |
| `src/ui/api_client.py` | HTTP client (no Streamlit): one function per endpoint, `ApiError`, `DuplicateService` |
| `src/ui/logic.py` | Pure helpers: labels, pre-fill, payload, prediction view, recognize outcome, errors |
| `src/ui/auth.py` | `UI_PASSWORD` check (constant-time compare) |
| `src/ui/Dockerfile` (+ `.dockerignore`) | UI image: python:3.11-slim, non-root, WORKDIR src/ui, port 8501 |

The folder is `views/`, **not** `pages/`: Streamlit runs a folder named `pages/` in legacy mode,
which skips `app.py` (and the login gate) when a URL is opened directly. Guarded by
`test_no_streamlit_pages_folder`.

## DESIGN v4 (T7) — how it is built

Goal (Ari): "understandable but elegant, like a modern banking/delivery app — less ink, more space".

- **Font:** Montserrat (Google Fonts via `theme.font`), only weights 400/500/600 loaded. Mongolian
  Ө ө Ү ү render in Montserrat (checked in T6 with Chrome DevTools).
- **Type:** page title 22/600 · section 15/600 · body 15/400 · labels 13/500 grey #6B7280 · big
  numbers 28/600 (status) and 24/600 (dashboard). **Max weight anywhere = 600**
  (`tests/test_ui_browser.py::test_max_font_weight_600`).
- **Colors:** background #F6F7F9, cards white, text #111827 (16.5:1), secondary #6B7280 (4.8:1 on
  white). Primary #1F4E9D (placeholder) only for main buttons, the «Бүртгэх» home card and selected
  chips. Status = soft tint + small dot + the word, the same on card and dashboard:
  Хэвийн #1E7A4C on #E8F5EE (4.75:1) · Удахгүй #A05A00 on #FFF4E0 (4.87:1) · Хэтэрсэн #B42318 on
  #FDECEC (5.76:1) · no prediction #4B5563 on #F3F4F6 (6.9:1). WCAG AA, guarded by
  `test_status_colors_are_readable` (≥ 4.5:1).
- **Surfaces, almost no borders:** cards = `st.container(key="card_…")`, white, radius 16, shadow
  `0 1px 3px rgba(0,0,0,.06)`. Inputs = grey fill #F3F4F6, no border (`theme.showWidgetBorder =
  false`), 1 px primary border only on focus. Info pairs in a card = label + value, 2 columns, no
  boxes. Plate = small chip (grey fill, 1 px #E5E7EB, 19/600, letter-spacing .05em).
- **Spacing** 8/16/24/32 · **buttons** 52 px, radius 14, 16/600; secondary = white + soft shadow
  (grey fill inside a card); text buttons (tertiary) 14/600 in primary color, ≥ 44 px tap height ·
  **chips** 36 px, 14 px, wrap, 8 px gaps.
- Visible focus ring (3 px primary), `prefers-reduced-motion` respected, no emoji (Material icons;
  inline SVG in HTML blocks).
- Header: «‹ Буцах» (inner screens) + small «Гео-Эксперт» + title. Streamlit's own top bar
  (incl. the ⋮ menu) is hidden (T8).
- **Spacing (T8, exact values, `src/ui/common.py`, checked at 390 px by the browser test):** page
  padding 16 top / 20 sides / 32 bottom, content max 480 px centered (all screens, dashboard too) ·
  top row 44 px → 8 px → title 22/600 → 16 px · element → element 12 px · before/after a card or
  section 20 px · card padding 16 · label → input 6 px · field → field 14 px · «Хадгалах» 20 px
  below the last card, full width, no frame · no empty blocks (CSS-only markdown blocks are taken
  out of the layout).

## Screens

**Login** (only if `UI_PASSWORD` set): password card → «Нэвтрэх». Until logged in only this page
exists, so a direct URL cannot skip it.

**Нүүр (Home)**: «Сайн байна уу · 10-р сарын 11, Ням» (today, Mongolian weekday) and three row cards
with icon + title + 1-line subtitle + chevron: «Бүртгэх» — «Зураг авч бүртгэх» (primary color, opens
the camera step), «Хайх» — «Дугаар эсвэл утсаар», «Сануулга» — «Өнөөдөр сануулах: N» (the «Илгээх»
count from `GET /reminders/due`; plain subtitle if the API has no predictions). The real
`st.button` / `st.page_link` is stretched over each card, so the whole card is one tap target.

**Бүртгэх (Record)**
1. *Capture*: camera (+ upload jpg/png/heic/heif, also upper-case `IMG_0001.HEIC` from an iPhone,
   sent as `image/heic` when the browser gives no type, RISK-17). New photo → `POST /plates/recognize`
   (field `file`). Clear read → lookup → confirm. `needs_manual` or recognizer down → manual step
   with the read text and a reason message. «Дугаарыг гараар оруулах» → manual; small
   «Дугааргүй машин» → manual in **fleet-number mode** (D-005; no radio on the main form).
2. *Manual*: «Улсын дугаар» (or «Парк дугаар») → «Шалгах» → lookup → confirm. «Дугааргүй машин» /
   «Улсын дугаартай машин» toggles the mode. A phone typed here → hint to use «Хайх».
3. *Confirm*: **photo preview** (120 px thumbnail, radius 12) + plate chip + chip «Бүртгэлтэй · N удаа ирсэн» /
   «Шинэ машин»; fleet number in several companies → company radio. «Зөв, үргэлжлүүлэх» /
   «Буруу байна — засах».
4. *Form*: photo thumbnail, plate chip + chip. «Дугааргүй машин» / «Зураг авах» are text buttons.
   - Card 1 (always fresh, D-033): «Гүйлт (км)» (numeric keypad; hint = previous km), «Моторын цаг»
     (fleet numbers, or if the truck had hours before), «Дараа нь хаашаа явах вэ?» tap pills from
     `GET /destinations` (`name_mn` when present, else `name`, D-071) + «Бусад» → place + route,
     **«Тосны төрөл»: 15W-40 · 10W-40 · 20W-50 · «Бусад»** (free text); default = last service value
     (not in the 3 → «Бусад» with it as text), else 15W-40.
   - Card 2, existing truck: «Өмнөхөөс авсан» one line (liters · driver · phone) + «Засах».
     **No company field** (existing truck) (the API ignores it for an existing plate; for a fleet number the UI sends
     the chosen truck's company, D-042).
   - Card 2, new truck: «Компани / эзэмшигч» **only in «Дугааргүй машин» (fleet_no) mode** (required:
     fleet numbers are unique per company). New plate vehicle: no field, the UI sends
     `company_name = "Тодорхойгүй"` (`logic.UNKNOWN_COMPANY`, T8; API still requires it, D-042;
     remove the default if backend makes company_name optional). Then **«Машины загвар»
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

**Машины карт (Card)** (fresh `GET /vehicles/{id}`): **plate chip** + small grey segment chip with a
colored dot («Давтан · 2 удаа») → one line company · model → compact **status block** on a soft tint:
dot + status word (Хэвийн / Удахгүй / Хэтэрсэн), «N хоног» 28/600 + үлдсэн/хэтэрсэн, «Дараагийн
солилт: date», 4 px bar, method note 12 px grey; `null` → grey «Таамаглал удахгүй нэмэгдэнэ» →
**4 info pairs** (2 columns, no boxes): Сүүлд солисон, Тос («15W-40 · ердийн 30 л»; last liters if no usual, T8), Чиглэл, Жолооч (name ·
phone) → «Түүх (N)» collapsed → primary «Тос солилт бүртгэх». No «Залгах», no separate badge (T7).

**Сануулга (Manager dashboard, 5.4)** — wider on desktop (max 1100 px), 2×2 tiles on a phone.
- 4 segment tiles from `GET /stats/segments`: colored dot + word (Шинэ / Давтан / Байнгын /
  Эрсдэлтэй), number 24/600; + total, as_of.
- `GET /reminders/due` split in two groups, API order kept (oldest `send_on` first):
  **«Илгээх»** and **«Эрсдэлтэй»** = at_risk by D-007 (`days_left < −7`, i.e. predicted date +
  7 days grace already passed; same rule and number as the API).
- Row (white card): plate chip, status chip (dot + word, same colors as the card) + «N хоног үлдсэн/хэтэрсэн»,
  «Утас:» phone · driver · company, «Илгээх өдөр» (send_on) · predicted date · last change, the
  `message_mn` text in a code box whose built-in button copies it to the clipboard, and
  «Илгээсэн» → `POST /reminders/{service_id}/sent`: new → «Илгээсэн гэж тэмдэглэлээ» and the row
  leaves the list; `already_sent` → «Өмнө нь илгээсэн гэж тэмдэглэгдсэн (time)»;
  409 `not_latest_service` → «шинэ үйлчилгээтэй болсон» + list reloaded.
- `contact_is_placeholder` → one small grey line (amber dot) that the contact phone in the text is a
  placeholder.
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
