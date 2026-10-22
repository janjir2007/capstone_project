# Deploy runbook — one Linux server, HTTPS (tasks 6.1 / 6.3 / 8.3)

- **Version:** 1.2 (2026-10-22, task 8.3: own domain, §11) · 1.1 (2026-10-19, tasks 6.3 + 6.4: deployed, §10 results) · **Owner:** Backend Engineer
- **Deployed (6.3):** DigitalOcean droplet, Singapore, Ubuntu 24.04, 1 vCPU / 2 GB → **https://app.geoexpert.mn**
  (task 8.3; the first address https://168.144.143.203.sslip.io now redirects there, §11)
- **Host-agnostic:** any Linux VPS with Docker.
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
| A name: `app.<company-domain>` with a DNS **A record → server IP** (live: `app.geoexpert.mn`), or no domain: `<server-ip>.sslip.io` | HTTPS needs a name; the phone camera needs HTTPS (D-061) | use sslip.io (works at once, no DNS setup) |
| `UI_PASSWORD` chosen | company login; instructor gets it | — |
| Real `GEO_EXPERT_PHONE` (optional) | reminder message contact (D-068) | placeholder 99000000, UI warns |

## 1. Server: install Docker (once)

```bash
ssh root@<server-ip>
export DEBIAN_FRONTEND=noninteractive
apt-get update && apt-get -y upgrade            # security updates first
# Firewall: deny incoming, allow 22/80/443 only. The SSH rule goes in BEFORE enable (no lock-out).
ufw default deny incoming && ufw default allow outgoing
ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp && ufw allow 443/udp && ufw --force enable
# Key-only SSH: a 00- file is read before the provider's 50-cloud-init.conf, so it wins.
printf "PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin prohibit-password\n" \
  > /etc/ssh/sshd_config.d/00-keys-only.conf && sshd -t && systemctl reload ssh
# 2 GB swap: safety margin for image builds on a 2 GB server.
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo "/swapfile none swap sw 0 0" >> /etc/fstab && echo "vm.swappiness=10" > /etc/sysctl.d/99-swappiness.conf
curl -fsSL https://get.docker.com | sh          # official Docker install script (Engine + compose plugin)
docker compose version                          # must print v2.x or newer (6.3: Docker 29.9.1, Compose v5.6.0)
```

Test a NEW ssh login after the SSH change, while the old session is still open. Docker can publish
ports past ufw, but only Caddy publishes any (80/443); db, api and ui publish none.

## 2. Clone the code + `.env`

```bash
# Private repo: read-only deploy key (made on the server, public half added in GitHub ->
# repo Settings -> Deploy keys, "Allow write access" OFF).
ssh-keygen -t ed25519 -N "" -C "ocp-server-deploy" -f ~/.ssh/github_deploy && cat ~/.ssh/github_deploy.pub
printf "Host github.com\n  IdentityFile ~/.ssh/github_deploy\n  IdentitiesOnly yes\n" > ~/.ssh/config
git clone git@github.com:janjir2007/capstone_project.git oil-change-predictor
cd oil-change-predictor
cp .env.prod.example .env
nano .env               # replace every CHANGE_ME: DOMAIN, POSTGRES_PASSWORD, UI_PASSWORD (OLD_DOMAIN: §11)
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

Then copy exactly the 5 files the API loads (nothing else; no `.pt`, no training output).
Run it from **inside** `models/`: macOS ships `openrsync`, which ignores the `models/./` marker
(6.3: files landed in `models/models/…` and had to be moved).

```bash
cd ~/Downloads/Capstone/oil-change-predictor/models
rsync -avR \
  next_change_model.joblib \
  serving_params.json \
  plate_yolo/yolo26n.onnx \
  plate_ocr/char_cnn.onnx \
  plate_ocr/char_cnn_version.json \
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
  40 trucks, 105 services, segments new 8 / returning 11 / loyal 17 / at risk 4, 8 due reminders
  (as of 2026-10-20; same as docs/demo_data.md).

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
| Caddy restarts in a loop, log says `server block without any key is global configuration` | a site address is empty. `OLD_DOMAIN` is optional (compose fills in `old.localhost`); check `dc config \| grep DOMAIN` |

## 9. Managed Postgres instead of the `db` container (option, not used now)

Set `DATABASE_URL` for the `api` service and remove `db` from the file. There is no init script
there, so run `schema.sql` once by hand (`psql "$DATABASE_URL" -f src/data/schema.sql`), then
`python -m scripts.migrate` as above.

## 10. Results on the deployed server (tasks 6.3 + 6.4, 2026-10-19)

**6.3 checks:** `/health` from the Mac over the internet → `{"status":"ok","db":"ok"}`; certificate
Let's Encrypt for `168.144.143.203.sslip.io`, valid to 2027-01-17 (Caddy renews it); `http://` → 308
to `https://`; only `/health` reaches the API (other paths get the Streamlit page); ports 5432, 8000,
8501 closed from outside. Build 3 min 36 s; images api 1.14 GB, ui 805 MB; disk 7.4 GB used of 48 GB.

**6.4 latency** (raw numbers: `docs/latency_6_4.json`). Two **separate** measurements, one client,
sequential calls, 10 warm-up calls then 200 timed calls each, all HTTP 200:

| Measurement | Where it runs | P50 | P95 | P99 | Max |
|---|---|---|---|---|---|
| **A1.** `POST /plates/recognize`, round trip (synthetic 12 MP JPEG, no plate → CNN skipped) | on the server, private network → `http://api:8000` | 430 ms | 905 ms | **1,105 ms** | 1,335 ms |
| ↳ A1 model time inside the API (`server_ms`) | same | 158 ms | 353 ms | 464 ms | 544 ms |
| **A2.** `GET /vehicles/{id}/prediction` (demo trucks 1–40) | same | 33 ms | 91 ms | **111 ms** | 129 ms |
| **B.** `GET /health` over HTTPS (new TCP + TLS connection per call) | Ari's Mac in Ulaanbaatar (home Wi-Fi) → internet → Caddy (Singapore) → api → db | 326 ms | 409 ms | **463 ms** | 1,629 ms |

How to read it:
- A = speed of the API itself. Same script as task 7.1c (`scripts/latency_bench.py`), run once in a
  throw-away container from the api image; the server has **1 vCPU**, shared by the benchmark and the
  API, so A is ~8× the Mac numbers (7.1c: recognize P99 84 ms, prediction P99 12 ms) and slightly
  pessimistic. Real plate photos add the char-CNN time (not measured here).
- B = what one browser request waits over the internet. Ping Mac → server was 86–163 ms (avg 111);
  a new HTTPS connection needs ~3 round trips (TCP, TLS, request), so B ≈ network, not the server.
  The one 1.6 s maximum was a single slow network call. Measured from Ulaanbaatar (home Wi-Fi);
  a phone on mobile data will differ.
- Not measured: many users at once (concurrency). One process on 1 vCPU serves one plate photo at
  a time; fine for one service desk, re-test before more users.

Re-run A (on the server; the script is not in the image, `git` is not either):
```bash
mkdir -p /root/bench && chmod 777 /root/bench        # then scp scripts/latency_bench.py there from the Mac
dc run --rm --no-deps -T -v /root/bench/latency_bench.py:/app/scripts/latency_bench.py:ro -v /root/bench:/bench \
  api python -c "import scripts.latency_bench as b; b.git_head=lambda:'<commit>'; \
  raise SystemExit(b.main(['--url','http://api:8000','--out','/bench/latency_6_4_server.json']))"
```

## 11. Own domain: app.geoexpert.mn (task 8.3, 2026-10-22)

DNS (done by Ari, not by these steps): A record `app.geoexpert.mn → 168.144.143.203`.

Two values in `.env` decide the addresses (no secret changes, no data touched):
- `DOMAIN=app.geoexpert.mn` → the site. Caddy gets a Let's Encrypt certificate for it on start.
- `OLD_DOMAIN=168.144.143.203.sslip.io` → the old address keeps its certificate (already in the
  `caddy_data` volume) and answers every request with **302 → same path on DOMAIN**, so old links
  and phone bookmarks keep working. Optional; without it nothing is redirected.

On the server (from the repo folder, after `git pull`):

```bash
dig +short app.geoexpert.mn                         # must print 168.144.143.203, else stop (§8)
cp .env .env.bak-8.3                                # rollback copy (stays on the server)
sed -i 's/^DOMAIN=.*/DOMAIN=app.geoexpert.mn/' .env
grep -q '^OLD_DOMAIN=' .env && sed -i 's/^OLD_DOMAIN=.*/OLD_DOMAIN=168.144.143.203.sslip.io/' .env \
  || echo 'OLD_DOMAIN=168.144.143.203.sslip.io' >> .env
grep -E '^(OLD_)?DOMAIN=' .env                      # shows the two lines only, no secrets
dc up -d caddy                                      # recreates only Caddy; db, api, ui keep running
dc logs caddy | grep -iE 'certificate obtained|error'   # wait ~10–30 s for app.geoexpert.mn
```

Check (from the Mac or any machine):

```bash
curl -s https://app.geoexpert.mn/health                               # {"status":"ok","db":"ok"}
curl -sI https://168.144.143.203.sslip.io/health | grep -iE '^HTTP|^location'
#   HTTP/2 302  +  location: https://app.geoexpert.mn/health
curl -sI http://app.geoexpert.mn | grep -iE '^HTTP|^location'         # 308 → https://app.geoexpert.mn/
echo | openssl s_client -connect app.geoexpert.mn:443 -servername app.geoexpert.mn 2>/dev/null \
  | openssl x509 -noout -issuer -subject -enddate                     # Let's Encrypt, CN=app.geoexpert.mn
```

Then §5 on the phone with `https://app.geoexpert.mn` (padlock, login, camera).

Rollback: `cp .env.bak-8.3 .env && dc up -d caddy` (back to the sslip.io address). The redirect
is a 302 (temporary): browsers do not cache it, so a rollback takes effect at once.

**Switch to 301 after 2 weeks stable** (PM review 8.3; earliest 2026-11-05): in `deploy/Caddyfile`
change `temporary` → `permanent`, update `test_old_domain_redirects_to_domain`, commit, then on the
server `git pull && dc up -d --force-recreate caddy` (the Caddyfile is a mounted file; recreate so
Caddy reads it). A 301 is cached by browsers, so after that switch a rollback no longer reaches
phones that already followed it.
