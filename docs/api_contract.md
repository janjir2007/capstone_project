# API contract — data, model and reminder endpoints (tasks 4.2, 4.2b, 4.3, 4.4)

- **Version:** 0.8 (task 1.6, 2026-10-17) · **Owner:** Backend Engineer
- Extends PROJECT_STATE §8 "API contract" with exact fields. The live, always
  current version is the OpenAPI page of the running API: `http://localhost:8000/docs`.
- Field names follow [`data_dictionary.md`](data_dictionary.md). Code:
  [`src/api/schemas.py`](../src/api/schemas.py).
- **"Today"** = current date in Ulaanbaatar (UTC+8), computed by the API, not by the database.
- **Forgiving matching** (`src/api/matching.py`): company names ignore case and extra
  spaces (`"  говь  ТЭЭВЭР ххк"` = `"Говь Тээвэр ХХК"`); fleet numbers ignore case, all
  spaces **and dashes** (v0.5): `"ht 12"` = `"HT12"` = `"HT-12"`, in lookup and in `POST /services`.

## Common shapes

**ServiceOut** (one service record)

| Field | Type | Note |
|---|---|---|
| `id`, `vehicle_id` | int | |
| `service_date` | date `YYYY-MM-DD` | |
| `odometer_km` | int \| null | |
| `engine_hours` | number \| null | |
| `oil_grade` | string | |
| `liters` | number | |
| `route` | `ub_city` \| `mn_china` \| `mn_russia` \| `mine_site` \| `mixed` \| null | |
| `destination` | `{id, name, name_mn, route_category}` \| null | same object as `GET /destinations` items |
| `destination_raw` | string \| null | |
| `driver_name`, `driver_phone`, `oil_changer`, `photo_ref` | string \| null | phone = 8 digits |
| `created_at` | datetime with offset | |

**VehicleCard**

| Field | Type | Note |
|---|---|---|
| `id` | int | |
| `identifier_type` | `plate` \| `fleet_no` | |
| `identifier` | string | as confirmed, e.g. `1234 УБА` |
| `plate_normalized` | string \| null | e.g. `1234УБА`; null for fleet numbers |
| `vehicle_model` | string \| null | |
| `company` | `{id, name}` | |
| `service_count` | int | |
| `segment` | `new` \| `returning` \| `loyal` \| `at_risk` \| null | today; `at_risk` from the card's `prediction` (same rule as `GET /stats/segments`); without the model: `vehicle_segments()` |
| `usual_liters` | number \| null | most frequent liters; tie → most recent |
| `last_service` | ServiceOut \| null | pre-fills the recording form |
| `history` | ServiceOut[] | newest first |
| `prediction` | Prediction \| null | next oil change (task 4.3); null if the vehicle has no service or the model files are not loaded |

**Prediction** (next oil change after the vehicle's NEWEST service)

| Field | Type | Note |
|---|---|---|
| `vehicle_id` | int | |
| `method` | `ridge` \| `b1` \| `b0` | which predictor answered (rules below) |
| `fallback_reason` | `first_visit` \| `destination_raw_only` \| `route_not_modelled` \| `unknown_destination` \| null | why not `ridge`; null for `ridge` |
| `model_version` | string | serving model file, e.g. `ridge-c8b211cb` (name + first 8 hex of its SHA-256); same for all methods |
| `based_on_service_id` | int | the newest service |
| `last_service_date` | date | |
| `predicted_days` | number | days from the last service, 1 decimal, at least 1 |
| `predicted_date` | date | `last_service_date + round(predicted_days)` |
| `today` | date | Ulaanbaatar date used for `days_left` |
| `days_left` | int | `predicted_date − today`; negative = overdue |
| `status` | `ok` \| `due_soon` \| `overdue` | D-007: ok > 14 days left, due_soon 0–14, overdue < 0 |

Method rules (checked on the newest service, in this order):

| # | Condition | method | fallback_reason |
|---|---|---|---|
| 1 | route not `mn_china` / `mn_russia` (only these are modelled, D-047) | `b0` | `route_not_modelled` |
| 2 | only `destination_raw` (typed by hand) | `b0` | `destination_raw_only` |
| 3 | no destination at all (records before migration 001) or a destination the model has no route numbers for | `b0` | `unknown_destination` |
| 4 | first visit (no earlier service) | `b1` | `first_visit` |
| 5 | otherwise | `ridge` | null |

`b0` = median days between visits in the training data (58 days on the current synthetic data);
`b1` = 17,500 km ÷ route km/day (D-035, D-049); `ridge` = the 2.4b model with inputs from
`src/common/features.py`. All numbers are from SYNTHETIC training data until real calibration (D-050).

## Endpoints

### `GET /vehicles/lookup?q=`
`q` = plate or fleet number (any spacing / case) or phone (8 digits, `+976` and
separators allowed). A valid phone is searched as a phone; anything else as a plate
(normalized by `src/common/plates.py`) **and** as a fleet number.

- **200** `{query, match_type: "plate"|"fleet_no"|"phone", normalized, vehicles: VehicleCard[]}`
  - plate → 0 or 1 vehicle; fleet number → every truck with that number (unique only per
    company, D-005); plate matches come first; phone → every vehicle the phone ever
    appeared on, newest service first
  - `match_type` = `fleet_no` only when every match is a fleet number (then `normalized` is
    the fleet-number key, lower case, no spaces or dashes, e.g. `ht12`); no match → `plate`
  - **unknown plate/phone → 200 with `vehicles: []`** (app opens the new-vehicle form)
- **422** `q` missing or blank

### `GET /vehicles/{id}`
- **200** VehicleCard · **404** unknown id

### `GET /vehicles/{id}/prediction`
- **200** Prediction (same object as the card's `prediction`)
- **404** unknown id, or the vehicle has no service yet · **503** model files not loaded

### `POST /plates/recognize`
Multipart form upload, field **`file`** = the photo (JPEG, PNG or HEIC/HEIF — iPhone default, v0.5; rotation from EXIF is applied).
The photo is processed in memory and **not stored**. Max 15 MB.

- **200** — also when no plate is found (then `needs_manual: true`):

| Field | Type | Note |
|---|---|---|
| `plate_raw` | string | recognizer text before normalization (`""` if nothing read) |
| `plate_normalized` | string \| null | `normalize_plate(plate_raw)` (D-044); null if nothing read |
| `confidence` | number 0–1 | product of the 7 character probabilities |
| `needs_manual` | bool | true → the oil changer must type or confirm the plate |
| `reason` | `no_plate` \| `empty` \| `invalid_format` \| `low_confidence` \| null | `no_plate` = detector found nothing; `empty` = 7 characters not found; the other two = D-044 rules (threshold 0.6) |
| `detection` | `{box: [x1, y1, x2, y2], confidence}` \| null | best plate box in pixels of the upright photo |
| `detector`, `recognizer` | string | `yolo26n (onnx)`, `char_cnn (onnx)` |
| `ms` | number | server time for detect + read |

- **413** file larger than 15 MB · **422** no `file` field, or not an image · **503** recognizer files not loaded

The app pre-fills the plate field with `plate_normalized` and looks it up with
`GET /vehicles/lookup?q=`; with `needs_manual: true` it asks the oil changer to check it first.

### `POST /services`
Body:

| Field | Required | Rule |
|---|---|---|
| `identifier_type` | no | `plate` (default) or `fleet_no` |
| `identifier` | **yes** | not blank |
| `company_name` | if the vehicle is new, and always for `fleet_no` | existing company with the same name **ignoring case and extra spaces** is reused (if old data has two, the oldest); else created with spacing cleaned, case kept. Ignored for an existing plate vehicle |
| `vehicle_model` | no | used only when the vehicle is new |
| `service_date` | no | default today; future date → 422 |
| `odometer_km` / `engine_hours` | **at least one** | ≥ 0; hours 1 decimal |
| `oil_grade` | **yes** | not blank |
| `liters` | **yes** | > 0, 1 decimal |
| `destination_id` / `destination_raw` | **exactly one** | D-033 |
| `route` | with `destination_raw`: **yes** · with `destination_id`: no | D-039: with `destination_id` the route is taken from the destination; a different route → 422 |
| `driver_name`, `oil_changer`, `photo_ref` | no | blank → null |
| `driver_phone` | no | normalized to 8 digits; invalid → 422 |

Unknown fields → 422 (typo protection).

Query parameter: `force` (bool, default `false`) — see 409 duplicate below.

- **201** `{service: ServiceOut, vehicle_id, vehicle_created, company_created}`
- **422** a rule above is broken, or `destination_id` does not exist
- **409 duplicate** — the vehicle already has a service on the same `service_date`; nothing saved.
  `detail` = `{code: "duplicate_service", message, existing_service_id}`. Send again with
  `?force=true` to save a second service that day.
- **409 conflict** — other conflict with existing data (e.g. the same new plate saved twice at
  the same moment); nothing saved, retry. `detail` = string

### `GET /destinations`
List for the "where are you heading next?" picker; send the chosen `id` as `destination_id`.

- **200** `[{id, name, name_mn, route_category}]`, seeded order (id), `Other / several / unknown`
  (`mixed`) always last (v0.8: also after the 4 rows of migration 005)
- `name_mn` (v0.6, migration 002, D-040) = Mongolian label to SHOW, e.g. `Замын-Үүд`; `null` = no label
  yet → show `name`. Since migration 004 (task 6.1) all 7 seeded rows have one (`Улаанбаатар хот`, `Бусад`);
  the field stays nullable. Migration 005 (task 1.6) adds 4 rows, all with a label:
  `Ганцмод`, `Сэхээ` (`mn_china`), `Улаан-Үд`, `Кош-Агач` (`mn_russia`) → 11 destinations.
  `name` stays the key; send `id` as before

### `GET /stats/segments?as_of=`
`as_of` optional (default today).

- **200** `{as_of, total, counts: {new, returning, loyal, at_risk}}`. All four keys are always present.
- D-007: `new` 1 service · `returning` 2 · `loyal` 3+ · **`at_risk`** (wins) = predicted date + 7 days
  grace < `as_of` and no newer service. v0.5: the predicted date is the served prediction, made from
  services up to `as_of`. Without the model files: `vehicle_segments()` (count-based only on real data).

### `GET /reminders/due?as_of=`
Vehicles to remind: **`send_on` ≤ `as_of`** and the reminder for the vehicle's newest service is
not marked sent. `send_on = predicted_date − buffer`, buffer per method, tuned on validation
(now ridge 7, b0 12, b1 1 days; read from the model files, D-036). `as_of` optional (default today);
only services up to `as_of` are used.

- **200** `{as_of, contact_is_placeholder, reminders: DueReminder[]}`, oldest `send_on` first.
  `contact_is_placeholder: true` = `GEO_EXPERT_PHONE` is not set (the message shows a fake number).
- **503** model files not loaded

**DueReminder**

| Field | Type | Note |
|---|---|---|
| `service_id` | int | the vehicle's newest service = the reminder's id for `POST /reminders/{service_id}/sent` |
| `vehicle_id` | int | |
| `identifier_type`, `identifier`, `plate_normalized` | | as on the card |
| `company` | string | company name |
| `phone`, `driver_name` | string \| null | from the newest service (D-004); null = not recorded |
| `last_change_date`, `oil_grade`, `liters` | | the newest service |
| `method` | `ridge` \| `b1` \| `b0` | |
| `buffer_days` | int | days early for this method |
| `predicted_date`, `send_on` | date | |
| `days_left` | int | `predicted_date − as_of` |
| `status` | `ok` \| `due_soon` \| `overdue` | D-007 |
| `segment` | `new` \| `returning` \| `loyal` \| `at_risk` | v0.7 (D-074): segment on `as_of`, same rule as the card and `GET /stats/segments`. The UI groups «Эрсдэлтэй» by `segment == "at_risk"` (no copy of the 7-day grace in the UI) |
| `message_mn` | string | Mongolian text: plate, last change date + oil, Geo-Expert contact (`GEO_EXPERT_NAME`, `GEO_EXPERT_PHONE`). Wording: draft, Ari to approve |

### `POST /reminders/{service_id}/sent`
Marks the reminder for this (vehicle, newest service) as sent; stores phone, exact message, method,
model version, predicted date and send day (`reminders_sent`, migration 003). No SMS is sent by the API.

- **201** stored → `{id, service_id, vehicle_id, phone, message_text, method, model_version, predicted_date, send_on, sent_at, already_sent: false}`
- **200** already marked before → the same stored row, `already_sent: true` (idempotent; nothing changes)
- **404** unknown service · **409** `{code: "not_latest_service", message, latest_service_id}` — the
  truck has a newer service (reload the due list) · **503** model files not loaded

## Change log

| Version | Date | Change |
|---|---|---|
| 0.1 | 2026-09-30 | PROJECT_STATE §8: endpoint list only |
| 0.2 | 2026-10-06 | Task 4.2: exact fields of lookup / vehicle card / POST /services / segments. Lookup returns a **list** of cards (a phone can match several trucks). Unknown plate → 200 + empty list |
| 0.3 | 2026-10-06 | Task 4.2b: `GET /destinations`; lookup also matches fleet numbers (`match_type` adds `fleet_no`); company name match ignores case + extra spaces; same vehicle + same date → 409 `duplicate_service` unless `?force=true` |
| 0.4 | 2026-10-12 | Task 4.3: card `prediction` filled (Prediction object with `method` + `model_version`); `GET /vehicles/{id}/prediction`; `POST /plates/recognize`. Model files are mounted from `./models` (not in the image); without them the API runs and these answer null / 503 |
| 0.5 | 2026-10-12 | Task 4.4: `GET /reminders/due`, `POST /reminders/{service_id}/sent`; segments + card `at_risk` from the served prediction; fleet numbers ignore dashes (lookup + `POST /services`, `normalized` e.g. `ht12`); HEIC photos accepted |
| 0.6 | 2026-10-12 | Task 1.1c: `name_mn` added to `GET /destinations` items and to `ServiceOut.destination` (additive; null for 2 of 7 destinations) |
| 0.7 | 2026-10-17 | Task 4.4b (D-074): `segment` added to every `GET /reminders/due` item (additive). Migration 004 (task 6.1): `name_mn` filled for the last 2 destinations |
| 0.8 | 2026-10-17 | Task 1.6: migration 005 adds 4 cross-border destinations (no field change). `GET /destinations` keeps `mixed` last (order by `route_category = 'mixed'`, then id) |
