# Synthetic data rules (Task 1.2a — DRAFT for Ari)

- **Version:** 0.1 draft · **Owner:** Data Engineer · **Date:** 2026-10-06
- **Basis:** [PROJECT_STATE v1.0](PROJECT_STATE.md) — D-002, D-004, D-006, D-030 – D-036
- **Used by:** generator (task 1.3), baselines B0/B1 and ML features (task 2.x)
- **Status:** nothing here is final until Ari marks each row ✓ or ✗.

## 0. How to read this file

Purpose (D-036): the generator must produce realistic **service histories** so the
model can learn **when a truck will come back for its next oil change**, so the
reminder is sent at the right time. The core input is the truck's **next
destination** (D-033).

Every rule carries exactly one tag:

| Tag | Meaning | What Ari does |
|---|---|---|
| **[SOURCE: link]** | Comes from a checkable source: a web/map link, an approved decision in PROJECT_STATE, or the 1.4a Excel profile | Nothing (may spot-check) |
| **[ARI ✓ needed]** | Only Ari knows this (business knowledge). Value may be `TO FILL` | Fill in / mark ✓ or ✗ |
| **[ESTIMATE]** | Placeholder chosen by the Data Engineer so the generator can run. Not a fact | Mark ✓, ✗, or write a better value |

Two things are deliberately **not** in any rule (D-034): **vehicle model** (stays in
the DB and on the vehicle card only) and **oil grade** (open question 5 in PROJECT_STATE).

---

## 1. Destinations table (template)

The oil changer asks "where are you heading next?" at every service (D-033) [SOURCE: [D-033](PROJECT_STATE.md)].
Each answer maps to one row of this table.

**How the km were measured** [SOURCE: links in table]: road route on OpenStreetMap
data, computed by the public OSRM router from Ulaanbaatar city centre
(OSM relation 270090, 47.9185 N, 106.9177 E) to the town point of the destination.
Every link below opens the raw route result; `distance` is in metres.
Distances are to the town, not to a specific terminal or customs yard, so ±10–20 km
is possible [ESTIMATE].

| # | Destination | Route category | One-way km from UB | Source link | Round-trip days incl. waiting (border, loading) [ARI] | Ari ✓/✗ |
|---|---|---|---|---|---|---|
| 1 | Ulaanbaatar city (local work) | `ub_city` | not applicable (no trip) | — | not applicable → fill **km/day** in §2 instead | |
| 2 | Zamyn-Uud (MN–CN border) | `mn_china` | **656** | [OSRM](https://router.project-osrm.org/route/v1/driving/106.9177016,47.9184676;111.9049227,43.7180017?overview=false) · [OSM town node 459470390](https://www.openstreetmap.org/node/459470390) | TO FILL | |
| 3 | Erenhot (CN side of border) | `mn_china` | **668** | [OSRM](https://router.project-osrm.org/route/v1/driving/106.9177016,47.9184676;111.9435190,43.6407813?overview=false) · [OSM relation 2753021](https://www.openstreetmap.org/relation/2753021) | TO FILL | |
| 4 | Beijing | `mn_china` | **1,330** | [OSRM](https://router.project-osrm.org/route/v1/driving/106.9177016,47.9184676;116.3912972,39.9057136?overview=false) | TO FILL | |
| 5 | Altanbulag (MN–RU border) | `mn_russia` | **345** | [OSRM](https://router.project-osrm.org/route/v1/driving/106.9177016,47.9184676;106.4970360,50.3141390?overview=false) · [OSM relation 7302713](https://www.openstreetmap.org/relation/7302713) | TO FILL | |
| 6 | Kyakhta (RU side of border) | `mn_russia` | **351** | [OSRM](https://router.project-osrm.org/route/v1/driving/106.9177016,47.9184676;106.4491500,50.3531760?overview=false) | TO FILL | |
| 7 | Mine site: TO FILL (name) | `mine_site` | TO FILL | TO FILL (real map source) | TO FILL | |
| 8 | Mine site: TO FILL (name) | `mine_site` | TO FILL | TO FILL (real map source) | TO FILL | |
| 9 | Other / several / unknown | `mixed` | — | — | TO FILL (or: use average of all rows) | |

Notes:
- Only Medium/High-confidence routes from the route research are used; Chita-via-Altai and Low-confidence routes are excluded [SOURCE: [D-032](PROJECT_STATE.md)].
- Check of the distances: road km ÷ straight-line km = 1.08 (Zamyn-Uud), 1.09 (Erenhot), 1.14 (Beijing), 1.29 (Altanbulag, Kyakhta). A real road is usually a bit longer than the straight line, so these are plausible [SOURCE: computed from the OSM coordinates above].
- One web aggregator states 834 km for UB–Zamyn-Uud ([distancesfrom.com](https://www.distancesfrom.com/mn/distance-from-Ulaanbaatar-to-Zamiin-Uud/DistanceHistory/6693584.aspx)). That would be 1.38× the straight line; the OSM route is used instead, but drivers' experience should confirm [ARI ✓ needed].
- All trips are assumed to start and end in Ulaanbaatar, where the service happens [ARI ✓ needed].
- Round-trip km = 2 × one-way km (same road back) [ESTIMATE].
- Rows can be added or deleted by Ari; the generator reads only this table, nothing else.
- Task 1.6 (2026-10-17) added 4 routes from Ari, NOT in this table (migration 005, `configs/generator.yaml`, `configs/routes_1_6.yaml`): Ganqimaodu 247 km (start **Tavan Tolgoi**, via Gashuunsukhait), Ceke 928 km (via Shiveekhuren), Ulan-Ude 578 km (via Altanbulag–Kyakhta), Kosh-Agach 1,786 km (via Tsagaannuur–Tashanta). OSRM through the border crossing as a waypoint (`src/data/external_api.py`). Road ÷ straight line = 1.13, 1.25, 1.27, 1.31 [SOURCE: computed from the OSM points in routes_1_6.yaml].

**Destination mix** — share of service visits per route category (used to draw destinations in the generator):

| Route category | Share of visits | Ari ✓/✗ |
|---|---|---|
| `ub_city` | TO FILL [ARI ✓ needed] | |
| `mn_china` | TO FILL [ARI ✓ needed] | |
| `mn_russia` | TO FILL [ARI ✓ needed] | |
| `mine_site` | TO FILL [ARI ✓ needed] | |
| `mixed` | TO FILL [ARI ✓ needed] | |

---

## 2. Route speed: km per day (D-035)

```
round_trip_km  = 2 × one_way_km                         (§1)
km_per_day     = round_trip_km ÷ round_trip_days        (round-trip days INCLUDE waiting)
B1 days        = interval_km ÷ km_per_day               (Baseline B1)
```
[SOURCE: [D-035](PROJECT_STATE.md)]

| Rule | Value | Tag | Ari ✓/✗ |
|---|---|---|---|
| km/day for a destination | formula above | [SOURCE: [D-035](PROJECT_STATE.md)] | |
| km/day for `ub_city` (no round trip) | TO FILL | [ARI ✓ needed] | |
| Idle days at base between trips (no cargo, repairs) are **not** in round-trip days and are added separately | TO FILL days per trip, or "already included" | [ARI ✓ needed] | |
| Baseline B0 = fixed interval of 15,000 km, ignoring destination | — | [SOURCE: [D-030, D-035](PROJECT_STATE.md)] | |

Worked example, **illustrative only**, numbers invented to show the arithmetic [ESTIMATE]:
Zamyn-Uud 656 km → round trip 1,312 km; *if* a round trip took 4 days → 328 km/day →
B1 = 15,000 ÷ 328 ≈ 46 days to the next oil change.

---

## 3. Oil change interval (D-030)

| Rule | Value | Tag | Ari ✓/✗ |
|---|---|---|---|
| Recommended interval = **reminder target** | change before **15,000 km** (low fuel quality in MN) | [SOURCE: [D-030](PROJECT_STATE.md)] | ✓ (approved) |
| Actual driver behavior (what the generator simulates) | **15,000 – 20,000 km** | [SOURCE: [D-030](PROJECT_STATE.md), confirmed by Ari] | ✓ (approved) |
| Shape inside 15k – 20k | uniform (every value equally likely) | [ESTIMATE] | |
| Same for every road truck, regardless of model or oil grade | yes | [SOURCE: [D-034](PROJECT_STATE.md)] | ✓ (approved) |
| ML target | `days_to_next_change` = days from this service to the next one | [SOURCE: [D-006](PROJECT_STATE.md), status PROPOSED] | |

The gap between 15k (should) and 15k–20k (does) is the business case for reminders [SOURCE: [D-030](PROJECT_STATE.md)].

---

## 4. Return behavior (D-031)

After each service, the truck's next visit is drawn as:

| Outcome | Share | Meaning in the generator | Tag | Ari ✓/✗ |
|---|---|---|---|---|
| On time | **~50 %** | next service when km since last change is inside 15k – 20k (§3) | [SOURCE: [D-031](PROJECT_STATE.md), Ari estimate] | ✓ (approved as parameter) |
| Late | **~40 %** | next service after the 20,000 km point, by the extra days below | [SOURCE: [D-031](PROJECT_STATE.md), Ari estimate] | ✓ (approved as parameter) |
| Never returns | **~10 %** | no next record (customer lost); the vehicle's history ends | [SOURCE: [D-031](PROJECT_STATE.md), Ari estimate] | ✓ (approved as parameter) |

How "late" is distributed:

| Rule | Value | Tag | Ari ✓/✗ |
|---|---|---|---|
| "Late" is measured from the day the truck passes 20,000 km | definition | [ESTIMATE] | |
| Extra days late | exponential, mean **10 days** (many a few days late, few very late) | [ESTIMATE] | |
| Maximum lateness | **60 days**; later than that counts as "never returns" | [ESTIMATE] | |
| The 50 / 40 / 10 split is drawn **per visit** (not fixed per customer) | per visit; per-vehicle tendency is added in §6 | [ARI ✓ needed] | |

---

## 5. Road truck vs mine haul truck (D-034, D-006)

| Rule | Value | Tag | Ari ✓/✗ |
|---|---|---|---|
| One coarse flag per vehicle: `road_truck` or `mine_haul` | only this flag, no vehicle model | [SOURCE: [D-034](PROJECT_STATE.md)] | ✓ (approved) |
| `road_truck`: interval in **km**, odometer recorded | §3 rules | [SOURCE: [D-030](PROJECT_STATE.md)] | ✓ (approved) |
| `mine_haul`: interval in **engine hours**, odometer empty | engine hours | [SOURCE: [D-006, D-034](PROJECT_STATE.md)] | ✓ (approved) |
| `mine_haul` interval (hours) | **OPEN** — TO FILL | [ARI ✓ needed] | |
| `mine_haul` engine hours per day | TO FILL | [ARI ✓ needed] | |
| Share of `mine_haul` among vehicles | TO FILL | [ARI ✓ needed] | |
| `mine_haul` vehicles may have a fleet number instead of a plate | `identifier_type = fleet_no` | [SOURCE: [D-005](PROJECT_STATE.md)] | ✓ (approved) |
| A **road** truck driving to a mine (`mine_site` destination) stays `road_truck` (km interval) | route ≠ vehicle class | [ARI ✓ needed] | |
| Fallback if the haul values are not filled by Oct 8: generator makes road trucks only, haul trucks documented as a limitation | scope cut | [ESTIMATE] | |

---

## 6. Variation the ML can learn

B1 knows only the destination's average km/day. ML can beat B1 only if real trucks
differ from that average in ways that show up in their own history (D-035). These
are the differences the generator adds. **All sizes are [ESTIMATE].** Ari must judge
whether they match reality: if they are too large, the ML wins only because we made
the data that way (RISK-03).

| # | Variation | Generator rule | Tag | Ari ✓/✗ |
|---|---|---|---|---|
| V1 | Per-vehicle speed | each vehicle gets a fixed factor × route km/day, drawn once from Normal(mean 1.0, sd 0.15), clipped to 0.6 – 1.4 (e.g. some owners wait longer for cargo) | [ESTIMATE] | |
| V2 | Per-trip noise | each round trip's days × Normal(1.0, sd 0.20), clipped to 0.5 – 2.0 (border queues, breakdowns) | [ESTIMATE] | |
| V3 | Season | km/day factor: winter (Dec – Feb) **0.85**, spring/autumn **1.0**, summer (Jun – Aug) **1.05** | [ESTIMATE] | |
| V4 | Holiday stops | trips pause around Tsagaan Sar and Naadam: TO FILL days, or "no effect" | [ARI ✓ needed] | |
| V5 | Lateness tendency | each vehicle gets its own chance of being late, drawn from Beta with mean 0.40 (fleet average stays at D-031's 40 %), so some customers are habitually late | [ESTIMATE] | |
| V6 | Destination changes between trips | after each trip: same destination again with probability **0.70**; otherwise a new destination drawn from the destination mix (§1). The next service records only the *first* trip's destination | [ESTIMATE] | |
| V7 | Usual route per vehicle | each vehicle has a home route category drawn from the destination mix; V6 changes start from it | [ESTIMATE] | |

What the model can learn from these: the vehicle's own km/day from odometer
readings (V1), its past intervals and lateness (V5), the season (V3), and how
reliable the stated destination is for that vehicle (V6, V7).

Honesty check, planned for task 2.4: also generate a dataset with V1, V5 and V6 switched
off. There, ML should be no better than B1. If it is, there is a leak [ESTIMATE: proposed check].

---

## 7. Noise rules for the "dirty" dataset

The generator writes two files: **clean truth** (with the target and the true
destination/return type for evaluation) and **dirty**, which goes through
`cleaning.py` (task 1.4) like real data.

Evidence from the real Excel vehicle registry (task 1.4a, counts only)
[SOURCE: 1.4a profile, `data/interim/records_profile.md`, private, not committed]:
phone column 72.5 % empty; odometer column 99.4 % empty; 26 same-day repeat visits
(possible duplicates); plate typos split one truck into two. That file is a
**registry**, not service records, so the rates below are lower and are estimates.

| # | Noise | Rule (share of service records) | Tag | Ari ✓/✗ |
|---|---|---|---|---|
| N1 | Missing driver phone | 10 % | [ESTIMATE] | |
| N2 | Missing driver name | 15 % | [ESTIMATE] | |
| N3 | Missing destination → `route` NULL | 10 % | [ESTIMATE] | |
| N4 | Missing odometer (road truck) | 3 % | [ESTIMATE] | |
| N5 | Destination written differently (e.g. Замын-Үүд / Zamyn Uud / short forms) | 20 %; cleaning must map them to the §1 table | [ESTIMATE] | |
| N6 | Plate typo: Cyrillic ↔ Latin look-alike (А/A, В/B, Е/E, К/K, М/M, Н/H, О/O, Р/P, С/C, Т/T, Х/X, У/Y) | 5 % | [ESTIMATE] (letter pairs: [SOURCE: CV role brief](roles/03_cv_dl_engineer.md)) | |
| N7 | Plate with extra space / different spacing | 5 % | [ESTIMATE] | |
| N8 | Odometer digit error (one digit added or dropped → ×10 or ÷10) | 1 % | [ESTIMATE] | |
| N9 | Odometer lower than last service (typo or replaced dashboard) | 1 % | [ESTIMATE] | |
| N10 | Phone format: `+976` prefix, spaces or dashes (cleaning → 8 digits, D-019) | 10 % | [ESTIMATE] | |
| N11 | Duplicate record (same truck, same day) | 2 % | [ESTIMATE] | |
| N12 | Late entry: `created_at` 1 – 7 days after `service_date` | 5 % | [ESTIMATE] | |
| N13 | Haul truck: engine hours typed into the odometer field | 2 % of haul records | [ESTIMATE] | |

---

## 8. Open items for Ari

| # | Question | Where used | Blocks 1.3? |
|---|---|---|---|
| A1 | Round-trip days incl. waiting for each destination in §1 | §1, §2 (B1) | **yes** |
| A2 | Which mine sites (names)? I then add the real map km | §1 | **yes** if mine_site is used |
| A3 | Destination mix: share of visits per route category | §1, V6, V7 | **yes** |
| A4 | km/day for UB city work | §2 | **yes** |
| A5 | Do all trips start/end in UB? Do drivers confirm ~656 km to Zamyn-Uud (not 834)? | §1 | no |
| A6 | Idle days at base between trips — separate, or already inside round-trip days? | §2 | no (default: already included) |
| A7 | Haul trucks: interval in engine hours, hours/day, share of fleet; or drop haul (fallback §5) | §5 | no (fallback exists) |
| A8 | Is a road truck going to a mine still a road truck? | §5 | no |
| A9 | 50 / 40 / 10: per visit or per customer? | §4 | no |
| A10 | Lateness: mean 10 days and max 60 days realistic? | §4 | no |
| A11 | Holiday stops (Tsagaan Sar, Naadam) | V4 | no |
| A12 | Variation sizes V1 – V7 | §6 | no |
| A13 | Noise rates N1 – N13 | §7 | no |
| A14 | Does oil grade change the interval? (else dropped, D-034) | — | no |
| A15 | Reminder window (days before due), D-036 — needed for the hit-rate metric, not for the generator | 2.4 | no |
| A16 | When should `mixed` be used (several destinations / unknown)? | §1 | no |
