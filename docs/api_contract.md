# API contract — data endpoints (tasks 4.2, 4.2b)

- **Version:** 0.3 (task 4.2b, 2026-10-06) · **Owner:** Backend Engineer
- Extends PROJECT_STATE §8 "API contract" with exact fields. The live, always
  current version is the OpenAPI page of the running API: `http://localhost:8000/docs`.
- Field names follow [`data_dictionary.md`](data_dictionary.md). Code:
  [`src/api/schemas.py`](../src/api/schemas.py).
- **"Today"** = current date in Ulaanbaatar (UTC+8), computed by the API, not by the database.
- **Forgiving matching** (`src/api/matching.py`): company names ignore case and extra
  spaces (`"  говь  ТЭЭВЭР ххк"` = `"Говь Тээвэр ХХК"`); fleet numbers ignore case and
  all spaces, dashes count (`"ht - 12"` = `"HT-12"`, but `"HT12"` ≠ `"HT-12"`).

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
| `destination` | `{id, name, route_category}` \| null | |
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
| `segment` | `new` \| `returning` \| `loyal` \| `at_risk` \| null | today, from `vehicle_segments()` |
| `usual_liters` | number \| null | most frequent liters; tie → most recent |
| `last_service` | ServiceOut \| null | pre-fills the recording form |
| `history` | ServiceOut[] | newest first |
| `prediction` | null | always null until task 4.3 |

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
    the fleet-number key, lower case, e.g. `ht-12`); no match → `plate`
  - **unknown plate/phone → 200 with `vehicles: []`** (app opens the new-vehicle form)
- **422** `q` missing or blank

### `GET /vehicles/{id}`
- **200** VehicleCard · **404** unknown id

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

- **200** `[{id, name, route_category}]`, seeded order (`Other / several / unknown` last)
- `name_mn` (Mongolian label, D-040) is added after migration 002

### `GET /stats/segments?as_of=`
`as_of` optional (default today).

- **200** `{as_of, total, counts: {new, returning, loyal, at_risk}}`. All four keys are always present.

## Change log

| Version | Date | Change |
|---|---|---|
| 0.1 | 2026-09-30 | PROJECT_STATE §8: endpoint list only |
| 0.2 | 2026-10-06 | Task 4.2: exact fields of lookup / vehicle card / POST /services / segments. Lookup returns a **list** of cards (a phone can match several trucks). Unknown plate → 200 + empty list |
| 0.3 | 2026-10-06 | Task 4.2b: `GET /destinations`; lookup also matches fleet numbers (`match_type` adds `fleet_no`); company name match ignores case + extra spaces; same vehicle + same date → 409 `duplicate_service` unless `?force=true` |
