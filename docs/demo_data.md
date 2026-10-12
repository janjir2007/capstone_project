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
docker compose up -d --build    # schema.sql + migrations 001, 002, 003 run automatically; API on :8000
POSTGRES_PASSWORD=oil_dev_password .venv/bin/python -m src.data.seed_demo
```

- Needs the model files in `models/` (task 4.3 handoff). The script uses the same predictor
  as the API.
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
| **1002 УБЕ** | **Overdue** (returning, 2 services). It is on the **due-reminder list** with the Mongolian "overdue" message |
| **1003 УНА** | **New** truck, first visit: prediction falls back to **B1** (route formula), status due soon |

More trucks:

| Try | What it shows |
|---|---|
| **1004 УБВ** | **At risk**: predicted date + 7 days has passed and the truck has not come back. Its reminder is already marked sent, so it is not on the due list |
| phone **0000 0009** | Phone lookup → **2 trucks** (1002 УБЕ, and 1001 УБА from that driver's older trips; D-004) |
| `GET /reminders/due` | 7 trucks (statuses overdue + due soon; methods Ridge + B1) |
| `GET /destinations` | Mongolian labels (`name_mn`) for the 5 road destinations |

Two more trucks show the **B0** fallback: one went to "Ulaanbaatar city" (a route the model
does not cover) and one had its destination typed by hand ("Сайншанд"). Find them with
the plates the seed prints, or in the vehicle list.

## What the database looks like (seeded 2026-10-12, real model files)

Output of `seed_demo.py`, checked through the running API (`/stats/segments`, `/reminders/due`):

| | |
|---|---|
| Trucks / services | 40 / 105, in 6 "Демо …" companies |
| Segments | new 8 · returning 11 · loyal 17 · **at_risk 4** |
| Statuses | ok 24 · due soon 10 · overdue 6 |
| Methods | Ridge 29 · B1 9 · B0 2 |
| Due reminders | 7 (2 more at-risk trucks already marked sent) |

On another day the counts can differ by one or two. The model's season feature changes
at month edges (e.g. Aug → Sep), so a truck can land a day or two away from its planned
date. The script prints the counts. If a segment would be empty or the due list would not
have 5–10 trucks, it stops and writes nothing (`NOT seeded: …`).
