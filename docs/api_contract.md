# API contract — data endpoints (task 4.2)

- **Version:** 0.2 (task 4.2, 2026-10-06) · **Owner:** Backend Engineer
- Extends PROJECT_STATE §8 "API contract" with exact fields. The live, always
  current version is the OpenAPI page of the running API: `http://localhost:8000/docs`.
- Field names follow [`data_dictionary.md`](data_dictionary.md). Code:
  [`src/api/schemas.py`](../src/api/schemas.py).
- **"Today"** = current date in Ulaanbaatar (UTC+8), computed by the API, not by the database.

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
`q` = plate (any spacing / case) or phone (8 digits, `+976` and separators allowed).
A valid phone is searched as a phone, anything else as a plate (normalized by
`src/common/plates.py`).

- **200** `{query, match_type: "plate"|"phone", normalized, vehicles: VehicleCard[]}`
  - plate → 0 or 1 vehicle; phone → every vehicle the phone ever appeared on, newest service first
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
| `company_name` | if the vehicle is new, and always for `fleet_no` | existing company with the exact name is reused, else created. Ignored for an existing vehicle |
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

- **201** `{service: ServiceOut, vehicle_id, vehicle_created, company_created}`
- **422** a rule above is broken, or `destination_id` does not exist
- **409** conflict with existing data (e.g. the same new plate saved twice at once); nothing saved

### `GET /stats/segments?as_of=`
`as_of` optional (default today).

- **200** `{as_of, total, counts: {new, returning, loyal, at_risk}}`. All four keys are always present.

## Change log

| Version | Date | Change |
|---|---|---|
| 0.1 | 2026-09-30 | PROJECT_STATE §8: endpoint list only |
| 0.2 | 2026-10-06 | Task 4.2: exact fields of lookup / vehicle card / POST /services / segments. Lookup returns a **list** of cards (a phone can match several trucks). Unknown plate → 200 + empty list |
