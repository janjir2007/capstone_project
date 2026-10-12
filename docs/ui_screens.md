# UI screens — Streamlit frontend (tasks 5.1–5.3)

- **Owner:** Frontend Engineer (iMac, branch `ui`, D-052) · **Version:** 0.2 (2026-10-12, T2 / 5.3b: contract v0.5)
- Stack: Streamlit 1.64 (D-022), calls FastAPI over HTTP only (`docs/api_contract.md` v0.5).
- UI text: Mongolian. Fake demo data only (RISK-06).

## Run

```bash
pip install -r requirements-ui.txt              # Python 3.11 venv
docker compose up -d --build                    # db + api on :8000
streamlit run src/ui/app.py --client.toolbarMode minimal
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
| `src/ui/app.py` | Entry: page config, login gate, top navigation |
| `src/ui/views/record.py` | Screen 1 — Recording mode (5.2) |
| `src/ui/views/lookup.py` | Screen 2 — Lookup + vehicle card (5.3) |
| `src/ui/common.py` | Mobile CSS, vehicle card component, cached destinations, page hand-off |
| `src/ui/api_client.py` | HTTP client (no Streamlit): one function per endpoint, `ApiError`, `DuplicateService` |
| `src/ui/logic.py` | Pure helpers: Mongolian labels, pre-fill, payload, error translation |
| `src/ui/auth.py` | `UI_PASSWORD` check (constant-time compare) |

The folder is `views/`, **not** `pages/`: Streamlit runs a folder named `pages/` in legacy mode,
which skips `app.py` — and therefore the login gate — when a URL such as `/lookup` is opened
directly. Found in browser testing; guarded by `test_no_streamlit_pages_folder`.

## Screen 0 — Login (only if `UI_PASSWORD` is set)

Password field → «Нэвтрэх». Wrong → «Нууц үг буруу байна.» Until logged in, only this page
exists in the navigation, so `/lookup` cannot be opened by URL. «Гарах» at the bottom of each page.

## Screen 1 — Үйлчилгээ бүртгэх (Recording, 5.2)

1. **📷 Зургаар таних** (folded): «Камер нээх» → camera, or upload jpg/png/heic. A new photo is
   sent at once to `POST /plates/recognize` (field `file`; the API does not store it).
   - Clear read → plate field = `plate_normalized`, looked up immediately («Дугаар уншигдлаа: …»).
   - `needs_manual` → field filled with what was read (may be empty) + warning by `reason`;
     the oil changer fixes it and presses «Шалгах».
   - 503 (recognizer not loaded) / 413 / 422 / no connection → «… гараар оруулна уу», manual entry.
2. **Төрөл**: Улсын дугаар / Парк дугаар. **Дугаар** + «Шалгах» → `GET /vehicles/lookup`.
   - Found → «Бүртгэлтэй машин · N удаа · segment», folded «Машины карт», form pre-filled from
     the last service: oil grade, liters (fallback `usual_liters`), driver, phone. Company is
     shown locked (the API ignores it for an existing plate).
   - Not found → «🆕 Шинэ машин», empty form + company (required) and model fields.
   - Fleet number in several companies → radio «Аль компанийн машин бэ?» (+ «Өөр компанийн шинэ машин»).
   - A phone typed here → hint to use «Хайлт». Plate edited after checking → form hidden until re-check.
3. **Always fresh (D-033):** Гүйлт (км) / Моторын цаг (one required; hint shows previous km) and
   «Дараа нь хаашаа явах вэ?» from `GET /destinations` (label = `name_mn` if present, else `name`;
   cached 5 min). «Жагсаалтад байхгүй…» → free text + route type (D-039).
4. «💾 Хадгалах» → `POST /services` (no `service_date`: API uses today, Ulaanbaatar).
   - Missing fields → Mongolian errors, nothing sent. API 422 → known messages translated.
   - **409 `duplicate_service`** → «Энэ машинд өнөөдөр үйлчилгээ аль хэдийн бүртгэгдсэн байна (№id).
     Дахин хадгалах уу?» + «Ингээд хадгалах» (resend `?force=true`) / «Болих».
   - 201 → «✅ Хадгалагдлаа: <plate> (шинэ машин)», form cleared, «Тос солигч» remembered,
     «Картыг харах» opens the card.
   - API down → «Сервертэй холбогдож чадсангүй…».

## Screen 2 — Машин хайх (Lookup + card, 5.3)

One field: plate / phone / fleet number → `GET /vehicles/lookup`. **📷 Камераар хайх**: photo →
recognize → clear read searches at once; `needs_manual` fills the field and waits for «Хайх». Caption tells how it was matched
and how many trucks. Phone/fleet number can return several cards (one under another).
Unknown → «Олдсонгүй» + «➕ Шинэ машин бүртгэх» (opens Screen 1 with the plate filled).

**Vehicle card:** plate · segment badge (Шинэ / Давтан / Байнгын / Эрсдэлтэй) · company · model;
2×3 tiles (service count, usual liters, last date, last km/engine hours, oil, destination);
driver + phone; **prediction card** from `prediction` (v0.5): tinted by `status` — ok #1e6b34 on
#e3f1e7 «Хэвийн», due_soon #8a5300 on #fbefd6 «Удахгүй», overdue #b3261e on #f9e3e1 «Хэтэрсэн»;
big «N хоног үлдсэн / хэтэрсэн» (or «Өнөөдөр»), `predicted_date`, progress bar = share of
`last_service_date → predicted_date` already used, small note = `method` (Загварын таамаглал /
Маршрутын тооцоо / Дундаж хугацаа) + `fallback_reason`. `null` → grey card «Таамаглал удахгүй нэмэгдэнэ»; «Түүх (N)» one line per service, newest first;
«➕ Үйлчилгээ бүртгэх» opens Screen 1 pre-filled.

## Phone width (~390 px)

Checked in Chrome at 390×844 (mobile emulation): no horizontal scroll (`scrollWidth` = 390),
tiles stay 2 columns, buttons full width, smaller titles. On phones Streamlit folds the top menu
into «»», so each page also has a one-tap link to the other screen.
