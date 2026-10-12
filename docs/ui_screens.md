# UI screens — Streamlit frontend (tasks 5.1–5.3)

- **Owner:** Frontend Engineer (iMac, branch `ui`, D-052) · **Version:** 0.1 (2026-10-11)
- Stack: Streamlit 1.64 (D-022), calls FastAPI over HTTP only (`docs/api_contract.md` v0.3).
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
| `UI_ENABLE_RECOGNIZE` | off | `1` shows the "🔎 Дугаар таних" button. Keep off until task 4.3 merges `POST /plates/recognize` |

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

1. **📷 Зураг** (folded): «Камер нээх» toggle → camera; or upload jpg/png. The photo is only
   shown, not stored or sent (no endpoint yet). With the flag on, «Дугаар таних» calls
   `POST /plates/recognize` and fills the plate field.
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

One field: plate / phone / fleet number → `GET /vehicles/lookup`. Caption tells how it was matched
and how many trucks. Phone/fleet number can return several cards (one under another).
Unknown → «Олдсонгүй» + «➕ Шинэ машин бүртгэх» (opens Screen 1 with the plate filled).

**Vehicle card:** plate · segment badge (Шинэ / Давтан / Байнгын / Эрсдэлтэй) · company · model;
2×3 tiles (service count, usual liters, last date, last km/engine hours, oil, destination);
driver + phone; prediction box (`null` → «Таамаглал удахгүй нэмэгдэнэ»; when 4.3 lands it shows
date · days left · status); «Түүх (N)» one line per service, newest first;
«➕ Үйлчилгээ бүртгэх» opens Screen 1 pre-filled.

## Phone width (~390 px)

Checked in Chrome at 390×844 (mobile emulation): no horizontal scroll (`scrollWidth` = 390),
tiles stay 2 columns, buttons full width, smaller titles. On phones Streamlit folds the top menu
into «»», so each page also has a one-tap link to the other screen.
