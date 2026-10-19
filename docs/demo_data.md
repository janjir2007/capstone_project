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
POSTGRES_PASSWORD=oil_dev_password .venv/bin/python -m scripts.migrate     # applies + records 001–005
POSTGRES_PASSWORD=oil_dev_password .venv/bin/python -m src.data.seed_demo
```

- Needs the model files in `models/` (task 4.3 handoff). The script uses the same predictor
  as the API, with the served reminder buffers (task 2.9: Ridge 16, B1 4, B0 13 days). A truck is
  on the due list when its days left ≤ its method's buffer, so the plan in `seed_demo.py` keeps
  "not due yet" Ridge trucks at 19+ days (task 7.2). If the buffers change again, run
  `pytest tests/test_seed_demo.py`: it checks the plan against the real model files.
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
| `GET /reminders/due` | 8 trucks: 4 overdue + 4 due soon; Ridge 6 + B1 2. The app shows 6 «today» + 2 «at risk» |
| `GET /destinations` | 11 destinations, all with a Mongolian label (`name_mn`). The form hides the «Бусад» list row: its own «Бусад» asks for the place + route |

Two more trucks show the **B0** fallback: one went to "Ulaanbaatar city" (a route the model
does not cover) and one had its destination typed by hand ("Сайншанд"). Find them with
the plates the seed prints, or in the vehicle list.

## What the database looks like (seeded 2026-10-19, real model files, task 7.2 plan)

Output of `seed_demo.py`, checked through the running API (`/stats/segments`, `/reminders/due`):

| | |
|---|---|
| Trucks / services | 40 / 105, in 6 "Демо …" companies |
| Segments | new 8 · returning 11 · loyal 17 · **at_risk 4** |
| Statuses | ok 28 · due soon 6 · overdue 6 |
| Methods | Ridge 29 · B1 9 · B0 2 |
| Due reminders | 8 (2 more at-risk trucks already marked sent) |

Checked for seed days 2026-10-19 … 10-26: the same counts every day. On other days they can
differ by one or two. The model's season feature changes
at month edges (e.g. Aug → Sep), so a truck can land a day or two away from its planned
date. The script prints the counts. If a segment would be empty or the due list would not
have 5–10 trucks, it stops and writes nothing (`NOT seeded: …`).
