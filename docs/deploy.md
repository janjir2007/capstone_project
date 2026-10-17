# Deploy runbook — one Linux server, HTTPS (tasks 6.1 / 6.3)

- **Version:** 1.0 (2026-10-17, task 6.1) · **Owner:** Backend Engineer
- **Host-agnostic:** any Linux VPS with Docker (provider still open, PROJECT_STATE §6 q1).
  Sizing: measured on the Mac with the full stack running, **~430 MiB RAM** in total
  (api 261, ui 75, caddy 56, db 39 MiB) → **2 GB RAM** is enough (D-067); **≥ 15 GB disk**
  (images ≈ 2 GB unpacked + build cache + database).
- **What runs** (`docker-compose.prod.yml`): `db` (Postgres 16) · `api` (FastAPI + models) ·
  `ui` (Streamlit) · `caddy` (HTTPS). **Only Caddy is reachable from outside** (ports 80/443).
  The API is private (D-061); only `GET /health` is passed through for checks.

```
phone browser ──HTTPS──> caddy :443 ──> ui :8501 ──HTTP──> api :8000 ──> db :5432
                                   └──> /health only ─────> api
```

Below, `dc` means `docker compose -f docker-compose.prod.yml`. Make the alias once per shell:

```bash
alias dc='docker compose -f docker-compose.prod.yml'
```

## 0. Before Sunday (needs Ari)

| Need | Why | If missing |
|---|---|---|
| Server: Ubuntu 22.04/24.04, 2 GB RAM, public IPv4, SSH access | runs everything | — (blocker) |
| Ports **80 and 443** open in the provider's firewall | Let's Encrypt + HTTPS | certificate fails (§8) |
| A name: `service.<company-domain>` with a DNS **A record → server IP**, or no domain: `<server-ip>.sslip.io` | HTTPS needs a name; the phone camera needs HTTPS (D-061) | use sslip.io (works at once, no DNS setup) |
| `UI_PASSWORD` chosen | company login; instructor gets it | — |
| Real `GEO_EXPERT_PHONE` (optional) | reminder message contact (D-068) | placeholder 99000000, UI warns |

## 1. Server: install Docker (once)

```bash
ssh root@<server-ip>
curl -fsSL https://get.docker.com | sh          # official Docker install script (Engine + compose plugin)
docker compose version                          # must print v2.x or newer
ufw allow OpenSSH && ufw allow 80 && ufw allow 443/tcp && ufw allow 443/udp && ufw --force enable
```

## 2. Clone the code + `.env`

```bash
git clone https://github.com/janjir2007/oil-change-predictor.git   # private repo: use a token or deploy key
cd oil-change-predictor
cp .env.prod.example .env
nano .env               # replace every CHANGE_ME: DOMAIN, POSTGRES_PASSWORD, UI_PASSWORD
chmod 600 .env          # only root can read the secrets
```

`POSTGRES_PASSWORD`: e.g. `openssl rand -base64 24 | tr -d '/+='`. `.env` is git-ignored — never commit it.
Compose refuses to start if `DOMAIN`, `POSTGRES_PASSWORD` or `UI_PASSWORD` is empty.

## 3. Model files (from the Mac)

Models are git-ignored (D-015), so they are copied, not cloned. First, **on the Mac**, refresh the
serving numbers (D-069; needs the synthetic data that only exists on the Mac):

```bash
cd ~/Downloads/Capstone/oil-change-predictor
.venv/bin/python -m src.ml.export_serving       # writes models/serving_params.json
```

Then copy exactly the 5 files the API loads (nothing else; no `.pt`, no training output):

```bash
cd ~/Downloads/Capstone/oil-change-predictor
rsync -avR \
  models/./next_change_model.joblib \
  models/./serving_params.json \
  models/./plate_yolo/yolo26n.onnx \
  models/./plate_ocr/char_cnn.onnx \
  models/./plate_ocr/char_cnn_version.json \
  root@<server-ip>:oil-change-predictor/models/
```

`char_cnn_version.json` says which CNN is served (v1) and its auto-fill threshold (D-089); the
recognizer refuses a CNN file whose hash does not match it (503 + log line).
On the server, check: `ls -R models` shows those 5 files.

## 4. Build, migrate, seed, start

```bash
dc build                                                   # ~3–5 min the first time
dc run --rm api python -m scripts.migrate                  # starts db; applies 001, 002, 003, 004
dc run --rm api python -m scripts.migrate                  # again: "nothing to apply" (idempotent)
dc run --rm api python -m src.data.seed_demo --as-of 2026-10-20   # demo DB for defense day (D-071)
dc up -d
dc ps                                                      # api, db, ui "healthy"; caddy "Up"
```

- `migrate` works on a fresh volume: the db container runs `schema.sql` once, then the script
  applies every missing `src/data/migrations/*.up.sql` in order, each in its own transaction, and
  records it in `schema_migrations` (D-041, D-069).
- `seed_demo` refuses a database that already has data (never mixes with real records). It prints
  segments new 8 / returning 11 / loyal 17 / at risk 4, 7 due reminders (as of 2026-10-20).

## 5. Check

```bash
curl https://<DOMAIN>/health                # {"status":"ok","db":"ok"}
dc logs caddy | grep -i "certificate obtained"   # Let's Encrypt worked (first start, ~10–30 s)
```

Then on the **phone** (mobile data, not office Wi-Fi, to test from outside):

1. Open `https://<DOMAIN>` → padlock shown → login with `UI_PASSWORD`.
2. «Хайх» → `1001 УБА` → card: Байнгын, prediction «Загварын таамаглал».
3. «Бүртгэх» → take a photo of a plate (Ari's own car or the printed demo plate, D-078 — never a
   customer's plate on the projector) → the camera opens (it only does on HTTPS) → plate read or
   «гараар оруулна уу» (manual) → no error message.
4. «Сануулга» → due list with «Эрсдэлтэй» group.

## 6. Local rehearsal on the Mac (https://localhost)

Same file, with a separate env file so the dev `.env` is not used. The dev stack can keep running
(different project name `ocp-prod`, no shared ports except 80/443).

```bash
cat > /tmp/prod-local.env <<'EOF'
DOMAIN=localhost
POSTGRES_PASSWORD=local-prod-test
UI_PASSWORD=demo-pass
EOF
alias dcl='docker compose -f docker-compose.prod.yml --env-file /tmp/prod-local.env'
dcl build && dcl run --rm api python -m scripts.migrate \
  && dcl run --rm api python -m src.data.seed_demo --as-of 2026-10-20 && dcl up -d
curl -k https://localhost/health        # -k: Caddy's local certificate is not trusted by curl
open https://localhost                  # Chrome warns once ("Advanced → Proceed")
dcl down -v                             # remove everything (incl. the test database)
```

## 7. Day-to-day

| Task | Command |
|---|---|
| Update code | `git pull && dc build && dc run --rm api python -m scripts.migrate && dc up -d` |
| Logs | `dc logs -f api` (or `ui`, `caddy`, `db`) |
| Restart | `dc restart` (data stays in the `pgdata` volume) |
| Backup DB | `dc exec -T db pg_dump -U oil oil_change \| gzip > backup_$(date +%F).sql.gz` |
| Re-seed demo | `dc down && docker volume rm ocp-prod_pgdata && dc up -d db` → §4 migrate + seed → `dc up -d`. **Deletes all data** — demo only, never once real records exist |
| Existing DB from before the runner | `dc run --rm api python -m scripts.migrate --mark-applied 001 002 003` then migrate |

Never `dc down -v` on the server without a backup: `-v` also deletes the certificates volume
(Let's Encrypt allows only a few new certificates per name per week).

## 8. Troubleshooting

| Symptom | Cause → fix |
|---|---|
| Browser: certificate error / `dc logs caddy` shows ACME errors | DNS A record not pointing at the server yet, or port 80/443 closed in the provider firewall. Check `dig +short <DOMAIN>` = server IP; or switch `DOMAIN` to `<ip>.sslip.io` and `dc up -d caddy` |
| `/health` → `{"status":"error","db":"error"}` 503 | db not healthy: `dc ps`, `dc logs db` |
| Card has no prediction / reminders 503 | model files missing or wrong place: `ls -R models`; `dc logs api` shows a `... not loaded from /app/models: ...` warning naming the missing file |
| Plate photo always manual + `dc logs api` shows hash mismatch | `char_cnn.onnx` does not match `char_cnn_version.json` (D-089): copy both again from the Mac |
| `migrate: FAILED: migrations were applied by hand…` | database older than the runner: `--mark-applied` the versions it has (§7) |
| `seed_demo`: `NOT seeded: database is not empty …` | it never writes into a database with data: re-seed only per §7 |
| Login page loops / "connection error" after login | WebSocket blocked by a proxy in front of Caddy (e.g. a provider load balancer): Caddy must be the first hop |
| Camera button missing on the phone | page opened over `http://` or an IP without HTTPS → use `https://<DOMAIN>` |

## 9. Managed Postgres instead of the `db` container (option, not used now)

Set `DATABASE_URL` for the `api` service and remove `db` from the file. There is no init script
there, so run `schema.sql` once by hand (`psql "$DATABASE_URL" -f src/data/schema.sql`), then
`python -m scripts.migrate` as above.
