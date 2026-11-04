# Demo data (task 4.5)

A demo database with 40 **synthetic** trucks. Every app feature has something to show
on the day you seed it: all segments, all statuses, a due-reminder list, phone lookup
and the B0/B1/Ridge prediction methods. Script: [`src/data/seed_demo.py`](../src/data/seed_demo.py).

**Nothing in it is real (RISK-06).** The histories come from the synthetic generator
(same config and seed as training). Plates are random but use the real format
(4 digits + 3 of the 21 plate letters, D-044). Company names start with "Демо", phones
are `0000xxxx` (no real Mongolian number starts with 0000), and driver names are the
generator's fake names. Oil grades and liters are demo values only.

## Load it (fresh database)

```bash
docker compose down -v          # WARNING: deletes the local dev database volume
docker compose up -d --build    # fresh volume: schema.sql only; API on :8000
POSTGRES_PASSWORD=oil_dev_password .venv/bin/python -m scripts.migrate     # applies + records 001–007
POSTGRES_PASSWORD=oil_dev_password .venv/bin/python -m src.data.seed_demo
```

- Needs the model files in `models/` (task 4.3 handoff): the script places each truck's dates with
  the same predictor as the API. Since task 9.5b the due list no longer uses the prediction; since 9.5c (D-119) a
  truck is on it once, `REMINDER_DAYS` (75) after its latest service, and is «Эрсдэлтэй» after
  `AT_RISK_DAYS` (150). Since 9.14a a truck with 2+ services (or a driver reply) has its own km/day:
  its reminder is 5 days before 12 000 km are used up (`src/api/pace.py`), usually long before 75 days.
  Run `pytest tests/test_seed_demo.py` after changing the plan: it checks every segment and both kinds
  of due reminder (queue, at risk), and that the API's due list equals the script's.
- 9.14a: every service stores `interval_km` = 12000 / `target_km` and its odometer reading; **1003 УНА**
  gets a driver reply (350 km/day, typed in yesterday) and another first-visit truck a typo below its
  odometer (flagged, not used).
- It refuses to write into a database that already has companies, vehicles or services,
  so it can never mix with real records.
- `--as-of YYYY-MM-DD` builds the demo for another day. The default is today in Ulaanbaatar.

**Re-seed on the demo day.** The dates are placed relative to the day you run the script.
Every day after that, trucks move toward "overdue" (the 2026-10-12 seed still works on
2026-10-20, but the numbers below will have changed). To refresh, run the three
commands again.

## Plates to try

Type a plate in any spacing or case (`1001уба` works too).

| Plate | What it shows |
|---|---|
| **1001 УБА** | **Loyal** customer: 5 services, history list, Ridge prediction, status **ok**. Its 2 oldest services had another driver (see phone below). The last destination has a Mongolian label |
| **1002 УБЕ** | **Overdue** (returning, 2 services). 9.14a: its km/day from the 2 services puts it on the **due-reminder list** |
| **1003 УНА** | **New** truck, first visit: prediction falls back to **B1** (route formula), status due soon. 9.14a: the card shows km/day **from the driver's reply** (350) and the next due day |

More trucks:

| Try | What it shows |
|---|---|
| **1004 УБВ** | **At risk** (9.5c): 150+ days since its latest service, not back. Its reminder is already marked sent, so it is not on the due list |
| phone **0000 0009** | Phone lookup → **2 trucks** (1002 УБЕ, and 1001 УБА from that driver's older trips; D-004) |
| `GET /reminders/due` | 9.14a: most trucks with a km/day (see the counts below) |
| `GET /km-checks/due` | 9.14a: first-visit trucks 34–74 days after their service with no reply |
| `GET /destinations` | 11 destinations, all with a Mongolian label (`name_mn`). The form hides the «Бусад» list row: its own «Бусад» asks for the place + route |

Two more trucks show the **B0** fallback: one went to "Ulaanbaatar city" (a route the model
does not cover) and one had its destination typed by hand ("Сайншанд"). Find them with
the plates the seed prints, or in the vehicle list.

## What the database looks like (seeded 2026-10-19, real model files, task 7.2 plan)

Output of `seed_demo.py`, checked through the running API (`/stats/segments`, `/reminders/due`):

| | |
|---|---|
| Trucks / services | 40 / 105, in 6 "Демо …" companies |
| Segments | new 9 · returning 11 · loyal 17 · **at_risk 3** |
| Statuses | ok 27 · due soon 6 · overdue 7 |
| Methods | Ridge 29 · B1 9 · B0 2 |
| Due reminders | 3 on 2026-11-02: 2 in «Өнөөдрийн дараалал» (75–149 days) + 1 «Эрсдэлтэй» (150+ days, not sent); 2 more at-risk trucks have their reminder marked sent. Small on purpose (9.5c): most trucks come back within 75 days |
| Due reminders since 9.14a | **26** on 2026-11-04 (25 by km/day, 1 by 75 days; 1 of them at risk). The demo's synthetic trucks drive ~250–400 km/day, so 12 000 km are used up after ~30–48 days. Pace: 31 from services, 1 from a reply, 8 none · km-check list: 3 (built by `build_demo` with the real served model, not yet seeded through the API) |

Checked for seed days 2026-11-02, 11-05 and 11-10 (task 9.5c, real served model): the same counts each day. On other days they can
differ by one or two. The model's season feature changes
at month edges (e.g. Aug → Sep), so a truck can land a day or two away from its planned
date. The script prints the counts. If a segment would be empty, or the due list would have no
queue truck or no at-risk truck (task 9.5c; 9.5b: every month stage), it stops and writes nothing (`NOT seeded: …`).
