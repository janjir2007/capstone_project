# API contract — data, model and reminder endpoints (tasks 4.2, 4.2b, 4.3, 4.4)

- **Version:** 0.22 (task 9.16b-2, 2026-11-11) · **Owner:** Backend Engineer
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
| `target_km` | int \| null | v0.12 (task 9.5a): odometer of the next oil change = `odometer_km` + `interval_km`. Null without `odometer_km` (mine trucks: engine hours only). v0.18 (task 9.14a): **stored** when the service is saved (was computed when shown with today's setting); services saved before have 15000 (migration 010 backfill) |
| `interval_km` | int \| null | v0.18: the `OIL_INTERVAL_KM` in force when the service was saved (default **12000** since 9.14a, was 15000); null for mine trucks |
| `engine_hours` | number \| null | |
| `oil_grade` | string | |
| `liters` | number | |
| `route` | `ub_city` \| `mn_china` \| `mn_russia` \| `mine_site` \| `mixed` \| null | |
| `destination` | `{id, name, name_mn, route_category}` \| null | same object as `GET /destinations` items |
| `destination_raw` | string \| null | |
| `driver_name`, `driver_phone`, `oil_changer`, `photo_ref` | string \| null | phone = 8 digits |
| `created_at` | datetime with offset | |
| `payment_status` | `paid` \| `unpaid` \| `pending` \| null (`paid_later` \| `unknown` reserved) | **v0.22 (task 9.16b, meaning change):** the MANUAL payment of this service, computed when read (no timer, rule below). `paid` «Төлсөн» · `unpaid` «Авлага» · `pending` «Хүлээгдэж байна». **null** = saved before migration 013 (`payment_tracked` false): no payment status. Also filled in the `POST /services` answer. `paid_later` / `unknown` (v0.16 Artlab roll-up) are no longer produced; kept in the type for a later Artlab fill |
| `amount_due` | number \| null | v0.22: = `price_mnt` while `unpaid` (null without a price, or when not unpaid). Was the Artlab credit (v0.16) |
| `match_confidence` | `both` \| `plate` \| `phone` \| null | v0.16 Artlab only; always null since v0.22 (Artlab not connected) |
| `price_mnt` | int \| null | v0.22: total price in MNT (whole number); null = no price entered |
| `paid_at` | datetime with offset \| null | v0.22: when «Төлсөн» was pressed |
| `marked_unpaid_at` | datetime with offset \| null | v0.22: when «Авлага» was pressed (kept after a later «Төлсөн») |
| `unpaid_since` | datetime with offset \| null | v0.22: only with `unpaid`: the earlier of «Авлага» pressed and saved + `PAYMENT_DUE_HOURS` |

**Payment rule (v0.22, task 9.16b, `src/api/payments.py` `manual_status`)**, in this order:
1. saved before migration 013 (`payment_tracked` false) → **null**
2. `paid_at` set, **or `price_mnt` = 0** (nothing owed) → `paid`
3. «Авлага» pressed (`marked_unpaid_at` set) → `unpaid`
4. now − `created_at` ≥ `PAYMENT_DUE_HOURS` (default **24**; exactly 24 h counts) → `unpaid`
5. else → `pending`

The clock starts at `created_at` (when the service was saved), not `service_date`. Both moments are
timezone-aware, so the server / DB timezone (UTC) vs Ulaanbaatar (+08:00) does not change the answer.
A service without a price can be `unpaid` (counted, adds 0 ₮). Setting `PAYMENT_DUE_HOURS`: whole number
> 0, else the API does not start (not the Artlab `ARTLAB_UNPAID_LOOKBACK_DAYS`, D-133).

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
| `segment` | `new` \| `returning` \| `loyal` \| `at_risk` \| null | today; same rule as `GET /stats/segments` (`at_risk` = `AT_RISK_DAYS`+ days since the latest service, v0.15); needs no model |
| `usual_liters` | number \| null | most frequent liters; tie → most recent |
| `last_service` | ServiceOut \| null | pre-fills the recording form |
| `history` | ServiceOut[] | newest first |
| `prediction` | Prediction \| null | next oil change (task 4.3); null if the vehicle has no service or the model files are not loaded |
| `pace` | Pace \| null | v0.18 (task 9.14a): km/day + the dates of the latest service; null without services |
| `readings` | Reading[] | v0.18: the 5 newest meter readings (every source), newest first |

**Pace** (v0.18, task 9.14a; rules in `src/api/pace.py`)

| Field | Type | Note |
|---|---|---|
| `unit` | `km` \| `hours` | `hours` = mine truck (engine hours only) |
| `rate_per_day` | number \| null | km (or hours) per day, 1 decimal; null = no usable pace |
| `source` | `reading` \| `services` \| null | `reading` = the newest usable driver reading after the latest service, counted from that service's odometer; else `services` = previous → latest service; null = none (one service only, or the pair is flagged) |
| `reading_value`, `reading_date` | number, date \| null | the driver reading used (`source = reading`) |
| `interval_km` | int \| null | stored on the latest service |
| `next_due_date` | date \| null | latest service + floor(`interval_km` ÷ `rate_per_day`) days; km trucks with a pace only |
| `reminder_on` | date \| null | `pace`: `next_due_date` − `REMINDER_LEAD_DAYS` (5), never before the day the pace became known (a late reply = due that day), never after service + `AT_RISK_DAYS` − `REMINDER_LEAD_DAYS` (145 days); `fixed`: service + `REMINDER_DAYS` (75). Null for mine trucks (no reminders) |
| `basis` | `pace` \| `fixed` \| null | null for mine trucks |
| `km_check_on` | date \| null | service + `KM_CHECK_DAYS` (34): km trucks without a pace only |

Usable = higher than the reading it counts from and 20–1200 km/day (engine hours: at most 24 h/day). Anything
else is **flagged** and never used (`not_higher`, `too_slow`, `too_fast`; higher on the same day = `too_fast`).

**Reading** (v0.18, `odometer_readings`)

| Field | Type | Note |
|---|---|---|
| `id`, `vehicle_id` | int | |
| `service_id` | int | the service it counts from (`source = service`: that service) |
| `unit` | `km` \| `hours` | |
| `value` | number | |
| `reading_date` | date | |
| `source` | `service` \| `manual` \| `messenger` | `service` = the service's own odometer / engine hours (one per service); `manual` = the driver's reply, typed in; `messenger` = the driver's reply confirmed in Messenger (v0.20, task 9.15a) |
| `status` | `ok` \| `flagged` | `flagged` = not used for the pace |
| `flag_reason` | `not_higher` \| `too_slow` \| `too_fast` \| `plate_mismatch` \| null | only when flagged. v0.20: `plate_mismatch` = Messenger reading whose typed plate is not the truck of the driver's m.me link (stored, never used for the pace) |
| `rate_per_day` | number \| null | per day from the reading it was checked against (null: nothing before it) |
| `created_at` | datetime with offset | |

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
| `range_low_date` | date \| null | task 2.9: `last_service_date + round(predicted_days + low)`, low = 10th percentile of the method's validation errors (never before the day after the service); null if `serving_params.json` has no `ranges` |
| `range_high_date` | date \| null | same with the 90th percentile → together an 80% range ("≈ date (low – high)"); on the synthetic test 83% of actual visits fell inside |

Method rules (checked on the newest service, in this order):

| # | Condition | method | fallback_reason |
|---|---|---|---|
| 1 | route not `mn_china` / `mn_russia` (only these are modelled, D-047) | `b0` | `route_not_modelled` |
| 2 | only `destination_raw` (typed by hand) | `b0` | `destination_raw_only` |
| 3 | no destination at all (records before migration 001) or a destination the model has no route numbers for | `b0` | `unknown_destination` |
| 4 | first visit (no earlier service) | `b1` | `first_visit` |
| 5 | otherwise | `ridge` | null |

`b0` = median days between visits in the training data (53 days on the current synthetic data, task 2.9 export);
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

### `GET /vehicles/search?q=&limit=` (v0.10, task 9.1 — dashboard, read only)
- `q` (optional, max 100 chars): a truck matches when its plate (`normalize_plate`), fleet number
  key, company key or **any** driver phone it ever had (digits, from 3 digits; `+976` dropped from a
  full number) **contains** `q`. Blank `q` = every truck. `limit` 1–1000, default 200.
- **200** `{query, total, vehicles: VehicleRow[]}` — `total` counts all matches, `vehicles` holds
  at most `limit`, newest last service first.
- VehicleRow: `id, identifier_type, identifier, vehicle_model, company{id,name}, service_count,
  last_service` (ServiceOut | null), `segment, status, days_left` (status/days_left null without the
  model; `segment` = the card's rule, also without the model), `matched_on` (list of `plate | fleet_no | company | phone`).
- Full history of one truck: `GET /vehicles/{id}`.
- **Filters (v0.11, step 2)**, all optional: `company_id` (the truck's owner); `date_from`, `date_to`
  (YYYY-MM-DD, both ends included), `route` (Route), `oil_grade` (case + spaces ignored). The last
  four filter SERVICES: a truck stays when **one** of its services passes all of them. The row
  still shows the truck's newest service.
- `with_services=true` (default false): each VehicleRow gets `services` = its services that pass the
  date / route / oil filters (all of them when none is used), newest first. Used by the dashboard's
  Excel export (one row per service). Without it `services` is null.
- `options: {companies: [{id, name}], oil_grades: [str]}` = choices for the filter lists, from the
  whole database (they do not shrink while filtering).
- `payment_status` (v0.16, task 9.6b-4; **v0.22 manual status**), optional: `paid` \| `unpaid` \| `pending`
  (`paid_later` \| `unknown` accepted, match nothing) — a fifth SERVICE filter (one service must pass it
  together with the others). Rows' `last_service` / `services` carry the ServiceOut payment fields
  (incl. `price_mnt`: the Excel export's price + status).
- `segment` (v0.17, task 9.12-1), optional: `new` \| `returning` \| `loyal` \| `at_risk` — a TRUCK filter (like
  `company_id`): the truck's segment today, the same rule as each row's `segment` and `GET /stats/segments`
  (trucks without a service never match). The dashboard's segment cards use it.
- **422** `limit` out of range, `q` too long, unknown `route`, bad date, `date_from` after `date_to`, unknown `payment_status` or `segment`

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
| `destination_id` / `destination_raw` | no — **at most one** (v0.12, task 9.5a: was exactly one, D-033) | the app's form no longer asks; old records keep theirs. No destination → prediction falls back to `b0` (`unknown_destination`) |
| `route` | with `destination_raw`: **yes** · otherwise no | D-039: with `destination_id` the route is taken from the destination; a different route → 422 |
| `driver_name`, `oil_changer`, `photo_ref` | no | blank → null |
| `driver_phone` | no | normalized to 8 digits; invalid → 422 |
| `price_mnt` | no | v0.22 (task 9.16b): «Нийт үнэ (₮)», whole number 0–100 000 000 (a JSON integer: `1.5`, `85000.0`, `"85000"` → 422). 0 = nothing owed → `paid` at once |

Unknown fields → 422 (typo protection).

Query parameter: `force` (bool, default `false`) — see 409 duplicate below.

- **201** `{service: ServiceOut, vehicle_id, vehicle_created, company_created}` — v0.22: `service.payment_status`
  = `pending` (or `paid` for price 0), `payment_tracked` true for every new service
- **422** a rule above is broken, or `destination_id` does not exist
- **409 duplicate** — the vehicle already has a service on the same `service_date`; nothing saved.
  `detail` = `{code: "duplicate_service", message, existing_service_id}`. Send again with
  `?force=true` to save a second service that day.
- **409 conflict** — other conflict with existing data (e.g. the same new plate saved twice at
  the same moment); nothing saved, retry. `detail` = string

### `POST /services/{id}/payment` · `PUT /services/{id}/price` (v0.22, task 9.16b)
Manual payment of ONE service (any of the truck's services, not only the newest). Behind the login like
every data route. No user name is stored (one shared password, D-117).

`POST /services/{id}/payment` body `{"action": "paid" | "unpaid" | "undo_paid"}` (unknown fields → 422):

| action | Button | Effect | Second call |
|---|---|---|---|
| `paid` | «Төлсөн» | `paid_at` = now, if not set | no change |
| `unpaid` | «Авлага» | `marked_unpaid_at` = now, if not set; `paid_at` cleared (corrects a «Төлсөн») | no change |
| `undo_paid` | «Буцаах» | `paid_at` cleared → the rule decides again (`pending`, or `unpaid` after 24 h) | no change |

`PUT /services/{id}/price` body `{"price_mnt": int | null}` (field required; null clears the price; same
limits as `POST /services`). Clicks are kept: a paid service stays paid; price 0 → `paid`.

Both: **200** = the updated ServiceOut · **404** unknown service · **409** `detail.code = "not_tracked"`
(saved before 9.16b) · **409** `detail.code = "price_zero"` (`unpaid` / `undo_paid` on a price-0 service:
nothing owed, change the price first) · **422** bad body.

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
- v0.15 (task 9.5c, D-119): `new` 1 service · `returning` 2 · `loyal` 3+ · **`at_risk`** (wins) =
  **`AT_RISK_DAYS` (default 150)+ days** since the latest service up to `as_of` (v0.13: 90 days;
  before that predicted date + 7 days, D-007). The same rule gives the card's and the search rows'
  `segment`. Needs no model files.

- v0.17 (task 9.12-1): the answer also has **`at_risk_days`** (int) = `AT_RISK_DAYS` (default 150), so the
  UI can label the at_risk card («Эргэж ирээгүй» · 150+ хоног) without its own copy of the setting.

### `GET /stats/period?period=&as_of=` (v0.17, task 9.12-1 — dashboard, read only)
Work numbers of one period, both ends included, in **Ulaanbaatar time**:
- `period`: `today` (default) \| `week` (**Monday** to `as_of`) \| `month` (the 1st to `as_of`); `as_of` (YYYY-MM-DD,
  optional) = the period's last day, default today.
- **200** `{period, date_from, date_to, services, new_vehicles, liters, reminders_sent, km_checks_sent}`:
  `services` = service records dated in the range · `new_vehicles` = vehicles whose **first-ever** service is in
  the range (not "created in the system") · `liters` = their oil liters (number) · `reminders_sent` = reminders
  marked sent with `sent_at` on a UB day in the range (any stage / channel) · `km_checks_sent` (v0.18) = «Км шалгах»
  messages marked sent the same way; **not** counted in `reminders_sent` (a km check is not a reminder).
- **422** unknown `period`, bad `as_of`

### `GET /reminders/due?as_of=` (v0.15, task 9.5c: one reminder per service; v0.18: reminder day from km/day)
Trucks to remind on `as_of`: **one reminder per service**, due on the latest service's **reminder day**
(v0.18, task 9.14a = Pace `reminder_on`: from the truck's km/day when known, else the latest service date +
**`REMINDER_DAYS` (default 75)**), if nothing was marked sent for that service yet. Only driver readings up
to `as_of` count. A row of the old
1m / 2m / 3m stages (v0.13) for that service also counts as sent. A new service = new `service_id`
→ a new cycle (the old reminder is no longer due). A truck `AT_RISK_DAYS`+ days out stays on the list
with `segment: at_risk` («Эрсдэлтэй») until it is marked sent or comes back. Left out: trucks whose
latest service has no `odometer_km` (mine trucks, engine hours only) and phones in
`GET /reminders/stops`. `as_of` optional (default today); only services up to `as_of` are used.
**The ML model is not used** (no 503).

- **200** `{as_of, contact_is_placeholder, reminders: DueReminder[]}`, oldest `send_on` first (then `vehicle_id`).
  `contact_is_placeholder: true` = neither `CONTACT_PHONE` nor `GEO_EXPERT_PHONE` is set (fake number).

**DueReminder**

| Field | Type | Note |
|---|---|---|
| `service_id` | int | the truck's latest service = the reminder's id for `POST /reminders/{service_id}/sent` |
| `vehicle_id` | int | |
| `identifier_type`, `identifier`, `plate_normalized` | | as on the card |
| `company` | string | company name |
| `phone`, `driver_name` | string \| null | from the latest service (D-004); null = not recorded |
| `last_change_date`, `oil_grade`, `liters`, `odometer_km` | | the latest service |
| `target_km` | int \| null | v0.18: stored on the service (`odometer_km` + `interval_km`); null only for a service written outside the API |
| `days_since` | int | `as_of − last_change_date` |
| `send_on` | date | the reminder day (v0.18: Pace `reminder_on`; was always `last_change_date` + `REMINDER_DAYS`) |
| `next_due_date` | date \| null | v0.18: Pace `next_due_date` |
| `rate_per_day` | number \| null | v0.18: km per day |
| `pace_source` | `reading` \| `services` \| null | v0.18 |
| `basis` | `pace` \| `fixed` | v0.18 |
| `segment` | `new` \| `returning` \| `loyal` \| `at_risk` | segment on `as_of` (the rule above); the UI shows «Эрсдэлтэй» by it |
| `messenger_ready` | bool | v0.20 (task 9.15a): an unused, unexpired One-Time Notification token exists for this truck → `POST /reminders/{service_id}/messenger` can send it. Always **false** while `MESSENGER_OTN_ENABLED=false` |
| `message_mn` | string | the Mongolian text (`src/api/reminders.py`). v0.21 (TXT-1 B): «Сайн байна уу! {plate}: {date}-нд {oil} тос солиулсан. Дахин солих хугацаа боллоо. Wolf Oil: {CONTACT_PHONE}» — **2 SMS parts** (UCS-2) with a usual plate, also with the longest oil name seen (v0.18–0.20: 3 parts, with «Гео-Эксперт») |

Removed in v0.15: `stage`. Removed in v0.13: `method`, `buffer_days`, `predicted_date`, `days_left`, `status`.

### `POST /reminders/{service_id}/sent`
Marks the reminder of this (truck, latest service) as sent; stores phone, exact message and the
reminder day (`reminders_sent`, migrations 003 + 006 + 007: `stage = 'single'`, UNIQUE (`service_id`,
`stage`), `channel = 'manual'`). No SMS is sent by the API. v0.15: **no `?stage=`** (an extra one is ignored).

- **201** stored → `{id, service_id, vehicle_id, stage: "single", channel: "manual", phone, message_text, method: null, model_version: null, predicted_date: null, send_on, sent_at, already_sent: false}`
  (rows from v0.13 have `stage` `1m` / `2m` / `3m`; rows from before v0.13 have `stage: null` and the prediction fields)
- **200** already marked for this service (also by a v0.13 `1m` / `2m` / `3m` row) → that stored row, `already_sent: true` (idempotent)
- **404** unknown service · **409** `{code: "not_latest_service", message, latest_service_id}` — the
  truck has a newer service (reload the due list) · **422** the reminder is not due yet (v0.18: its Pace
  `reminder_on` is after today; `send_on` stores that day), the truck has no odometer, or its phone asked to stop

### `POST /vehicles/{id}/readings` · `DELETE /readings/{id}` (v0.18, task 9.14a)
The driver's current km, typed in by the oil changer (`source = manual`). Body `{value, reading_date?}`:
`value` > 0 (km; mine trucks: engine hours, 1 decimal), `reading_date` default today. It counts from the
truck's **latest** service and is checked against it (and against earlier usable replies of the same service);
one that cannot be used is still stored, `status: flagged` + `flag_reason`.

- **201** `{reading: Reading, pace: Pace}` (the truck's pace after it)
- **404** unknown truck · **422** no service yet, `reading_date` in the future or not after the latest
  service (the same day is refused too), `value` ≤ 0, unknown fields

`POST /vehicles/{id}/readings/preview` (v0.19, task 9.14a-3): the same body, checks and errors, but **nothing
is stored** → **200** `{unit, value, reading_date, status, flag_reason, rate_per_day, pace}` = what the save
would store and the Pace after it. The UI's «Км бүртгэх» confirm step uses it (the UI has no copy of the rules).

`DELETE /readings/{id}` removes a driver reading (a typo; v0.20: also `source = messenger`, «Буцаах», RISK-34):
**204** · **404** unknown · **422** `source = service` (a service's own reading is part of the service).

### `GET /readings/flagged` · `POST /readings/{id}/reviewed` (v0.21, task 9.15a-3)
«Сануулга» → «Шалгах (N)»: Messenger readings the API stored **flagged** (any `flag_reason`, e.g.
`plate_mismatch`) that nobody marked checked yet. Needs migration 012 (`odometer_readings.reviewed_at`).

- `GET /readings/flagged` → **200** `{readings: FlaggedReading[]}`, newest first. FlaggedReading =
  `{reading_id, vehicle_id, identifier_type, identifier, company, unit, value, reading_date, flag_reason,
  phone, driver_name, created_at}`; `phone` / `driver_name` = of the service the reading counts from.
  Manual readings are not listed (the oil changer saw the warning when typing them).
- `POST /readings/{id}/reviewed` («Шалгасан») → **200** `{reading_id, reviewed_at}`; idempotent (a second call
  keeps the first `reviewed_at`). The reading **stays flagged** (never used for the pace); it only leaves the
  list. **404** unknown · **422** not a flagged Messenger reading.

### `GET /km-checks/due?as_of=` · `POST /km-checks/{service_id}/sent` (v0.18, task 9.14a)
«Км шалгах»: asks the driver for his current km. **Not a reminder** (own table `km_checks`, not in
`reminders_sent`, not in `reminders_sent` of `GET /stats/period`). A truck is listed on `as_of` when its
latest service has an odometer, **no usable pace** (Pace `source` null), `km_check_on` ≤ `as_of` <
`reminder_on` (34 ≤ days < 75 by default), no check was marked for that service and its phone is not in
`GET /reminders/stops`. Oldest `check_on` first (then `vehicle_id`). A usable reply (POST readings) gives
the truck a pace: it leaves this list and its reminder day moves.

- **200** `{as_of, contact_is_placeholder, checks: KmCheck[]}`; KmCheck = `{service_id, vehicle_id,
  identifier_type, identifier, plate_normalized, company, phone, driver_name, last_change_date, odometer_km,
  days_since, check_on, reminder_on, segment, message_mn}`. `message_mn` (v0.21):
  - `MESSENGER_ENABLED=true` + `MESSENGER_PAGE_USERNAME` set → «Сайн байна уу! {plate} машины одоогийн км-ээ
    хариу бичнэ үү эсвэл https://m.me/{MESSENGER_PAGE_USERNAME}?ref={ref} Wolf Oil: {CONTACT_PHONE}» (no date;
    `ref` = the service's `messenger_refs` code). 2 SMS parts with an 8-character plate, 8-digit phone and an
    18-character username (130 of 134); a 10-character fleet number **and** a "+976" phone together → 3 parts.
  - otherwise → «Сайн байна уу! {plate} машины тосыг {date}-нд солиулсан. Одоогийн км-ээ хариу бичнэ үү.
    Wolf Oil: {CONTACT_PHONE}» (2 SMS parts; v0.18–0.20 ended «Wolf Oil - Гео-Эксперт: …»)

`POST /km-checks/{service_id}/sent`: **201** `{id, service_id, vehicle_id, phone, message_text, channel:
"manual", check_on, sent_at, already_sent: false}` · **200** already marked (that row, `already_sent: true`)
· **404** unknown service · **409** `not_latest_service` (as for reminders) · **422** check day not come
yet, no odometer (mine truck), or the phone asked to stop

### Messenger km bot (v0.20, task 9.15a-2)
Plan: `docs/plans/9.15a_plan.md`. Code: `src/api/routers/messenger.py`, `src/api/messenger/`.
**Off by default** (`MESSENGER_ENABLED=false`, `MESSENGER_OTN_ENABLED=false`).

`GET /messenger/webhook?hub.mode=&hub.verify_token=&hub.challenge=` — Meta's set-up check. **Public**
(Caddy, no login; D-118 exception). Works also when `MESSENGER_ENABLED=false`, so the webhook can be set up first.
- **200** text/plain = `hub.challenge` when `hub.mode = subscribe` and `hub.verify_token` = `META_VERIFY_TOKEN`
  (constant-time compare) · **403** anything else (also when `META_VERIFY_TOKEN` is empty)

`POST /messenger/webhook` — Meta's events. **Public** (Caddy), signed requests only. In this order:
1. body > 64 KB → **413**
2. `X-Hub-Signature-256` must be `sha256=` + HMAC-SHA256(`META_APP_SECRET`, raw body); missing / wrong → **403**, nothing read
3. `MESSENGER_ENABLED=false` → **200** and nothing else (nothing stored, nothing sent)
4. not JSON → **400** · `object` ≠ `page` or `entry.id` ≠ `META_PAGE_ID` → ignored
5. each event once (`message.mid`, else a hash; table `messenger_seen`), each in its own transaction
6. **200** `EVENT_RECEIVED`; replies go out after it (Send API, `messaging_type: RESPONSE`)

What an event does:
| Event | Result |
|---|---|
| m.me link tap (`referral`, or Get Started `postback` with `referral`) | PSID linked to the ref's truck + service (`messenger_links`, `ref`); greeting |
| text with exactly one plate + one number (3–7 digits, any order, Latin look-alikes, «км») | the truck (below); the reading checks of `POST /vehicles/{id}/readings` **without saving**; plate + km kept 24 h (`messenger_pending`, no text); «{plate} — {km} км. Зөв үү?» + quick replies «Тийм» / «Үгүй» |
| «Тийм» (quick reply `KM_YES` or typed) within 24 h | saved like the manual form (same code), `source = messenger`, `reading_date` = the Ulaanbaatar day of the ORIGINAL message; reply with km/day + next change date, or «… ажилтан шалгаад холбогдоно» when flagged |
| «Үгүй», or «Тийм» after 24 h | nothing saved; «Дахин бичнэ үү: улсын дугаар + км» |
| anything else | **no reply** (a person answers in the Page inbox) |

Which truck: the typed plate's truck if it is in our DB; else the truck of the PSID's newest ref link whose
service is still that truck's latest. A typed plate ≠ that ref truck (or unknown with a ref truck) →
saved **flagged `plate_mismatch`**. No truck at all (v0.21) → «Энэ дугаар манай бүртгэлд олдсонгүй. Дугаараа
шалгаад дахин бичнэ үү, эсвэл {CONTACT_PHONE} руу залгана уу.», nothing stored. The checks refuse the day →
«Баярлалаа, манай ажилтан шалгаад холбогдоно.», nothing stored.

Get Started button (v0.21): every postback is handled as above, whatever its payload.
`scripts/messenger_get_started.py` prints the Page's current payload + greeting and sets `GET_STARTED`
(+ a short greeting if none) only when the Page has no Get Started button.

`POST /reminders/{service_id}/messenger` — internal (behind the login). Sends the reminder text
(`message_mn`) with the truck's One-Time Notification token, only when the oil changer taps the button (P2).
- **201** the stored reminder (`channel: messenger`, `phone: null`); the token is used
- **200** already marked sent (any channel): that row, `already_sent: true`, nothing sent
- **404** unknown service · **409** `not_latest_service` · **422** `MESSENGER_OTN_ENABLED=false`, not due,
  no odometer, phone stopped, or no unused token · **502** `{code: "meta_error", message}` — Meta refused:
  **no row stored, token not used** (send by SMS)
- OTN request / opt-in / send format: **UNVERIFIED** (Meta's OTN page answered 404 on 2026-11-04); check in dev mode first

Every `POST /services` with an odometer also stores a random 8-character ref code (`messenger_refs`, A–Z 2–9)
for the m.me link (used by the SMS text in 9.15a-3). Not in any answer yet.

Settings (server `.env` only; never logged): `MESSENGER_ENABLED`, `MESSENGER_OTN_ENABLED` (needs
`MESSENGER_ENABLED`), `META_APP_SECRET`, `META_VERIFY_TOKEN`, `META_PAGE_TOKEN`, `META_PAGE_ID`,
`META_GRAPH_VERSION` (e.g. `v26.0`, the only place the Graph version is set). `MESSENGER_ENABLED=true` with any
`META_*` empty → the API does not start.

### `GET /reminders/stops` · `POST /reminders/stops` · `DELETE /reminders/stops/{phone}` (v0.13)
Phones that asked for no more messages (`reminder_stops`, migration 006).

- `GET` → `[{phone, created_at}]`, newest first
- `POST {phone}` (8 digits, +976 optional, normalized) → **201** stored · **200** already there · **422** not a phone
- `DELETE /reminders/stops/{phone}` → **204** (also when it was not there) · **422** not a phone

### `GET /payments/receivables?limit=` (v0.22, task 9.16b — read only)
Dashboard «Төлбөр»: every service whose payment rule gives `unpaid` («Авлага»), grouped per truck.
`limit` 1–1000 (default 200) trucks; the totals count all.
- **200** `{due_hours, total_mnt, count, count_no_price, total_trucks, trucks: TruckReceivable[]}`
  - `total_mnt` = sum of prices of every «Авлага» service (a service without a price adds 0)
  - `count` = «Авлага» services, with or without price · `count_no_price` = of these, without a price
    (UI: «Үнэ оруулаагүй: N») · `due_hours` = `PAYMENT_DUE_HOURS` in force
- TruckReceivable: `vehicle_id, identifier, company_name, services, amount_mnt, services_no_price,
  oldest_service_date, oldest_unpaid_since, driver_phone` (newest «Авлага» service with a phone; on screen
  only, never in Excel), `service_ids` (oldest first). Order: biggest `amount_mnt` first, then the oldest
  `oldest_unpaid_since`, then `vehicle_id`.
- **422** `limit` out of range

### `GET /payments/unpaid?limit=` (v0.16, task 9.6b-4 — read only)
Unpaid Artlab receipts (`payment_status = unpaid`, credit sale «Зээл»), **oldest first**. Data =
the sync's copy in our database (`artlab_bills`); the API never calls Artlab. `limit` 1–1000, default 200.
- **200** `{connected, total, total_due, items: UnpaidBill[]}` — `total` / `total_due` count every
  unpaid receipt, `items` at most `limit`. `connected` false = no successful sync yet (then empty).
- UnpaidBill: `artlab_id` (**string**: Artlab ids exceed 2^53), `bill_date`, `days_waiting` (today in
  UB − bill_date), `amount_due` (credit part, MNT), `total_gross` (number \| null), `match_confidence`
  (`both` \| `plate` \| `phone` \| null), `match_note` (`none` \| `multiple` \| `conflict` \| null = why
  not linked), `service_id`, `vehicle_id`, `identifier` (plate / fleet no), `company_name` (null when
  not linked), `plates` + `phones` (found in the receipt text; the text itself is not stored)
- **422** `limit` out of range

### `GET /payments/sync-status` (v0.16, task 9.6b-4 — read only)
- **200** `{connected, runs: SyncRun[]}` — the latest run per kind (`bills`, `nightly`) and per acc-txn
  bank account (`kind = acc_txn`, `account_code` set; includes the per-account calls a nightly run
  makes). Empty `runs` before the first sync.
- SyncRun: `kind, account_code, started_at, finished_at` (null = running or crashed), `ok, bills_seen,
  transfers_seen, error_class` (exception class only, e.g. `ArtlabError`), `last_ok_at` (end of the
  latest successful run of that kind / account), `zero_row_streak` (acc_txn only: finished ok runs in
  a row with 0 rows; the sync logs a warning at `ARTLAB_ZERO_ROW_WARN_RUNS`, default 12)

### Login: `GET/POST /auth/login` · `GET /auth/logout` · `GET /auth/check` (v0.14, task 8.5r, D-117)
The only API routes besides `/health` that Caddy makes public. Not used by the UI's data code;
`src/api/routers/auth.py`. Without `UI_PASSWORD` in the API's env: no login (check always 200).

- `GET /auth/login?next=/path` → **200** HTML form (password, «Намайг сана» ticked) · **303** to `next` if already logged in
- `POST /auth/login` (form: `password`, `remember=1`, `next`) → **303** to `next` + cookie
  `ocp_session` (HttpOnly, Secure, SameSite=Lax, Path=/; Max-Age 30 days with remember, else
  browser session) · **401** wrong password · **429** locked (5 wrong from one IP → 15 min) · **413** body > 4 KB.
  `next` must be a path on this site: `//…`, `/\…`, `/auth/*`, `/_stcore/*`, `/static/*` → `/`
- `GET /auth/logout` → **303** `/auth/login`, cookie deleted (this device only)
- `GET /auth/check` → **200** `{login_required: bool}` · **302** `/auth/login?next=<X-Forwarded-Uri>` (no or bad cookie).
  Caddy `forward_auth` calls it before every UI request; the UI calls it too (`api_client.auth_check`)
- Token = `v1.<expires>.<nonce>.<HMAC-SHA256>`, key from `AUTH_SECRET` + `UI_PASSWORD`; nothing stored.
  New `UI_PASSWORD` → every cookie invalid. New settings: `AUTH_SECRET` (required with `UI_PASSWORD`,
  ≥ 16 chars, else the API does not start); `UI_PASSWORD` moved from the ui to the api service

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
| 0.9 | 2026-10-17 | Task 2.9: `range_low_date`, `range_high_date` added to Prediction (card + `GET /vehicles/{id}/prediction`; additive, nullable). `serving_params.json` gains `ranges` |
| 0.10 | 2026-10-27 | Task 9.1: `GET /vehicles/search` (dashboard search, read only; additive — no existing field changed) |
| 0.11 | 2026-10-28 | Task 9.1 step 2: search filters `date_from`, `date_to`, `company_id`, `route`, `oil_grade` + `options` in the answer; `with_services=true` adds each row's matching `services` (additive) |
| 0.12 | 2026-10-29 | Task 9.5a: `target_km` added to ServiceOut (additive, everywhere a service appears: card `last_service` / `history`, search rows, `POST /services` answer); `POST /services` destination optional (at most one of `destination_id` / `destination_raw`). New API setting `OIL_INTERVAL_KM` (default 15000; not a whole number > 0 → the API does not start) |
| 0.13 | 2026-10-29 | Task 9.5b: **breaking** for `GET /reminders/due` (month stages: `stage`, `days_since`, `odometer_km`, `target_km` added; `method`, `buffer_days`, `predicted_date`, `days_left`, `status` removed; no 503). `POST /reminders/{id}/sent` needs `?stage=`. New `GET/POST/DELETE /reminders/stops`. `at_risk` = 90+ days since the latest service everywhere (card, search, stats, reminders). New setting `CONTACT_PHONE` (falls back to `GEO_EXPERT_PHONE`). Migration 006 |
| 0.14 | 2026-10-30 | Task 8.5r (D-117): `/auth/login`, `/auth/logout`, `/auth/check` (additive; data endpoints unchanged and still private). API settings `UI_PASSWORD` + `AUTH_SECRET` |
| 0.15 | 2026-11-02 | Task 9.5c (D-119): **breaking** — one reminder per service at `REMINDER_DAYS` (75) after the latest service replaces the 1m/2m/3m stages: `stage` removed from `GET /reminders/due` items; `POST /reminders/{id}/sent` takes no `?stage=` (stores `single`); old 1m/2m/3m rows count as sent. `channel` added to the sent row (additive). `at_risk` = `AT_RISK_DAYS` (150)+ days everywhere. New settings `REMINDER_DAYS`, `AT_RISK_DAYS` (bad value or `AT_RISK_DAYS <= REMINDER_DAYS` → the API does not start). Migration 007 |
| 0.16 | 2026-11-02 | Task 9.6b-4: Artlab payments, **additive + read only**. ServiceOut gets `payment_status`, `amount_due`, `match_confidence` (card `history` / `last_service`, lookup cards, search rows; null in the `POST /services` answer and before the first successful sync). `GET /vehicles/search?payment_status=`. New `GET /payments/unpaid`, `GET /payments/sync-status`. Needs migrations 008 + 009 (run `scripts.migrate` before the new API starts) |
| 0.17 | 2026-11-02 | Task 9.12-1: **additive, read only**. New `GET /stats/period?period=today\|week\|month&as_of=` (services, new vehicles = first-ever service, liters, reminders sent; week = Monday to today, UB). `GET /vehicles/search?segment=` (truck filter, same segment rule). `at_risk_days` added to `GET /stats/segments` |
| 0.18 | 2026-11-04 | Task 9.14a-2: per-truck km/day engine. ServiceOut `target_km` now **stored** (+ `interval_km`; `OIL_INTERVAL_KM` default 12000, was 15000; older services 15000 by migration 010). VehicleCard `pace` + `readings` (additive). `GET /reminders/due`: `send_on` = the km/day reminder day when the pace is known (meaning change; else 75 days as before) + `next_due_date`, `rate_per_day`, `pace_source`, `basis` (additive); `target_km` nullable. New: `POST /vehicles/{id}/readings`, `DELETE /readings/{id}`, `GET /km-checks/due`, `POST /km-checks/{service_id}/sent`. `GET /stats/period` + `km_checks_sent` (additive). Settings `REMINDER_LEAD_DAYS` (5), `KM_CHECK_DAYS` (34) |
| 0.19 | 2026-11-04 | Task 9.14a-3: `POST /vehicles/{id}/readings/preview` (additive): what a reading would give, nothing stored — for the UI's confirm step |
| 0.20 | 2026-11-04 | Task 9.15a-2: Messenger km bot, **additive, off by default**. New `GET/POST /messenger/webhook` (public via Caddy, signed only) and `POST /reminders/{service_id}/messenger` (OTN, behind `MESSENGER_OTN_ENABLED`). `messenger_ready` in `GET /reminders/due` items. Reading `source` `messenger` now written; `flag_reason` + `plate_mismatch`; reminder `channel` + `messenger`. `DELETE /readings/{id}` also removes `messenger` readings. Settings `MESSENGER_ENABLED`, `MESSENGER_OTN_ENABLED`, `META_*`. Needs migration 011 (run `scripts.migrate` before the new API starts). KmCheck `message_mn` **unchanged** (the m.me text is 9.15a-3) |
| 0.21 | 2026-11-05 | Task 9.15a-3: new `GET /readings/flagged`, `POST /readings/{id}/reviewed` (needs migration 012, `reviewed_at`). Reminder `message_mn` = TXT-1 B (2 SMS, no «Гео-Эксперт»). KmCheck `message_mn` with the m.me link when `MESSENGER_ENABLED=true` + `MESSENGER_PAGE_USERNAME` (new optional setting), else the dated text ending «Wolf Oil: {contact}». Bot reply for an unknown plate: «Энэ дугаар манай бүртгэлд олдсонгүй. … {contact} руу залгана уу.» |
| 0.22 | 2026-11-11 | Task 9.16b-2: manual payment per service. Needs **migration 013** (`price_mnt`, `paid_at`, `marked_unpaid_at`, `payment_tracked`; run `scripts.migrate` before the new API starts). ServiceOut `payment_status` now the manual status (**meaning change**: + `pending`; null = saved before 013; `paid_later` / `unknown` no longer produced), `amount_due` = price while `unpaid`, `match_confidence` always null; new `price_mnt`, `paid_at`, `marked_unpaid_at`, `unpaid_since` (additive); also in the `POST /services` answer. `POST /services` + optional `price_mnt`. New `POST /services/{id}/payment`, `PUT /services/{id}/price`, `GET /payments/receivables`. `GET /vehicles/search?payment_status=` on the manual status (+ `pending`). New setting `PAYMENT_DUE_HOURS` (24). `GET /payments/unpaid` + `/sync-status` (Artlab) unchanged |
