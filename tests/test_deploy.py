"""Tests for tasks 6.1 + 6.2: production compose rules and the CI pytest checker.

No Docker needed: the compose file is read as YAML. The real "starts from a fresh volume
and works over https://localhost" check is in docs/deploy.md §5 (done by hand / in the
6.1 handoff), because it needs Docker, the model files and ports 80/443.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from scripts import ci_check_pytest as C

ROOT = Path(__file__).resolve().parent.parent
PROD = yaml.safe_load((ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8"))
SERVICES = PROD["services"]
ENV_EXAMPLE = (ROOT / ".env.prod.example").read_text(encoding="utf-8")


# ==========================================================================
# docker-compose.prod.yml
# ==========================================================================

def test_four_services() -> None:
    """`up -d` starts these four; artlab-sync (task 9.6b-3) only runs under the "sync" profile."""
    always = {name for name, s in SERVICES.items() if not s.get("profiles")}
    assert always == {"db", "api", "ui", "caddy"}
    assert set(SERVICES) - always == {"artlab-sync"}


def test_artlab_credentials_only_in_the_sync_service() -> None:
    """Task 9.6b-3 (RISK-22): the web API never holds Artlab credentials; the sync holds no web secrets."""
    sync = SERVICES["artlab-sync"]
    assert sync["profiles"] == ["sync"] and not sync.get("ports")
    assert {"ARTLAB_URL", "ARTLAB_USER", "ARTLAB_PASS"} <= set(sync["environment"])
    assert not {"UI_PASSWORD", "AUTH_SECRET"} & set(sync["environment"])
    for name in ("api", "ui", "caddy", "db"):
        assert not any(k.startswith("ARTLAB_") for k in SERVICES[name].get("environment") or {}), name


def test_only_caddy_publishes_ports() -> None:
    """D-061: the API and the database are not reachable from the internet."""
    published = {name for name, s in SERVICES.items() if s.get("ports")}
    assert published == {"caddy"}
    assert {p.split(":")[0] for p in SERVICES["caddy"]["ports"]} == {"80", "443"}


def test_api_gets_the_reminder_settings() -> None:
    """Task 9.14a: the engine settings reach the API with the decided defaults (interval 12000, was 15000)."""
    env = SERVICES["api"]["environment"]
    assert env["OIL_INTERVAL_KM"] == "${OIL_INTERVAL_KM:-12000}"
    assert (env["REMINDER_LEAD_DAYS"], env["KM_CHECK_DAYS"]) == ("${REMINDER_LEAD_DAYS:-5}", "${KM_CHECK_DAYS:-34}")
    assert "OIL_INTERVAL_KM=12000" in ENV_EXAMPLE.splitlines()


def test_models_mounted_read_only_into_api() -> None:
    """D-069 / D-089: ./models (with plate_ocr/char_cnn_version.json) is mounted, not baked in."""
    assert "./models:/app/models:ro" in SERVICES["api"]["volumes"]
    assert SERVICES["api"]["environment"]["MODEL_DIR"] == "/app/models"


def test_db_runs_only_schema_sql_migrations_come_from_migrate_py() -> None:
    init = [v for v in SERVICES["db"]["volumes"] if "docker-entrypoint-initdb.d" in v]
    assert init == ["./src/data/schema.sql:/docker-entrypoint-initdb.d/01_schema.sql:ro"]


def test_dev_compose_also_leaves_migrations_to_migrate_py() -> None:
    """Task 7.2: dev = prod. Fresh volume -> schema.sql only; scripts.migrate applies AND records 001+
    (mounting them as init scripts skipped schema_migrations, so migrate refused, and 005 was forgotten)."""
    dev = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))["services"]
    init = [v for v in dev["db"]["volumes"] if "docker-entrypoint-initdb.d" in v]
    assert init == ["./src/data/schema.sql:/docker-entrypoint-initdb.d/01_schema.sql:ro"]


@pytest.mark.parametrize(("service", "var"), [
    ("db", "POSTGRES_PASSWORD"), ("api", "POSTGRES_PASSWORD"), ("api", "UI_PASSWORD"), ("api", "AUTH_SECRET"),
    ("caddy", "DOMAIN")])
def test_secrets_have_no_default(service: str, var: str) -> None:
    """${VAR:?...} = compose refuses to start without it; no dev password slips into production."""
    assert re.fullmatch(r"\$\{" + var + r":\?[^}]+\}", SERVICES[service]["environment"][var])


def test_ui_talks_to_api_inside_the_network() -> None:
    assert SERVICES["ui"]["environment"]["API_URL"] == "http://api:8000"


def test_password_only_in_api_not_in_ui() -> None:
    """8.5r: the API checks the password and signs the cookie; the UI never sees the password."""
    assert set(SERVICES["ui"]["environment"]) == {"API_URL"}


CADDYFILE = (ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8")


def _handle_blocks() -> dict[str, str]:
    """{matcher: body} of the top-level `handle` blocks of the DOMAIN site ("" = catch-all)."""
    site = re.search(r"^\{\$DOMAIN\} \{\n(.*?)^\}", CADDYFILE, re.S | re.M).group(1)
    return {m.group(1): m.group(2) for m in re.finditer(r"^\thandle ?(\S*) \{\n(.*?)^\t\}", site, re.S | re.M)}


def test_caddy_makes_only_health_auth_and_the_webhook_of_the_api_public() -> None:
    """D-061 + D-117: of the API only /health and /auth/* are public; 9.15a (D-118 exception) adds
    /messenger/webhook (signed Meta requests only) and nothing else."""
    blocks = _handle_blocks()
    assert set(blocks) == {"/health", "/auth/*", "/messenger/webhook", ""}
    api_public = {m for m, body in blocks.items() if re.search(r"reverse_proxy api:8000", body)}
    assert api_public == {"/health", "/auth/*", "/messenger/webhook"}
    assert "reverse_proxy ui:8501" in blocks[""]


def test_webhook_block_is_exact_small_and_not_logged() -> None:
    """9.15a: the webhook path only (no wildcard), 64 KB body, never in Caddy's access log (the verify
    token is in its query string), no login (Meta cannot log in; the API checks the signature)."""
    body = _handle_blocks()["/messenger/webhook"]
    assert [line.strip() for line in body.strip().splitlines()] == [
        "log_skip", "request_body {", "max_size 64KB", "}", "reverse_proxy api:8000"]
    assert "forward_auth" not in body
    site = re.search(r"^\{\$DOMAIN\} \{\n(.*?)^\}", CADDYFILE, re.S | re.M).group(1)
    assert not re.search(r"^\s*log\b(?!_skip)", site, re.M)        # no access log today


def test_caddy_checks_the_cookie_before_every_ui_request() -> None:
    body = _handle_blocks()[""]
    assert re.search(r"forward_auth api:8000 \{\s*uri /auth/check\s*\}", body)
    assert body.index("forward_auth") < body.index("reverse_proxy ui:8501")


def test_caddy_sets_the_ip_for_the_login_lock() -> None:
    """The lock counts per X-Real-IP; Caddy overwrites it with the real peer (header_up replaces)."""
    assert "header_up X-Real-IP {remote_host}" in _handle_blocks()["/auth/*"]


def test_old_domain_redirects_to_domain() -> None:
    """Task 8.3: the old sslip.io address sends every request (same path) to DOMAIN; nothing else.
    302 (temporary) until 2 weeks stable, then 301 (PM review 8.3)."""
    caddyfile = (ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8")
    block = re.search(r"^\{\$OLD_DOMAIN\} \{\n(.*?)^\}", caddyfile, re.S | re.M)
    assert block is not None
    assert block.group(1).strip() == "redir https://{$DOMAIN}{uri} temporary"


def test_old_domain_is_optional_but_never_empty() -> None:
    """An empty site address makes Caddy refuse the whole Caddyfile, so compose fills in a dummy name."""
    assert SERVICES["caddy"]["environment"]["OLD_DOMAIN"] == "${OLD_DOMAIN:-old.localhost}"


def test_env_example_covers_compose_and_holds_no_real_values() -> None:
    """Every ${VAR} the prod compose reads is in .env.prod.example; secrets are CHANGE_ME, phone is the placeholder."""
    text = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    used = set(re.findall(r"\$\{([A-Z_]+)", text))
    values = dict(line.split("=", 1) for line in ENV_EXAMPLE.splitlines() if line and not line.startswith("#"))
    assert used <= set(values)
    for var in ("POSTGRES_PASSWORD", "UI_PASSWORD", "AUTH_SECRET", "DOMAIN"):
        assert values[var] == "CHANGE_ME"
    assert values["GEO_EXPERT_PHONE"] == "99000000"  # placeholder (D-068), not a real number


def test_env_example_is_tracked_but_env_is_ignored() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in gitignore and "!.env.prod.example" in gitignore


def test_api_image_contains_the_one_off_jobs() -> None:
    """docs/deploy.md runs migrate + seed_demo inside the API image."""
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY scripts/ ./scripts/" in dockerfile and "COPY configs/ ./configs/" in dockerfile


# ==========================================================================
# scripts/ci_check_pytest.py
# ==========================================================================

def junit(cases: str) -> str:
    return f'<?xml version="1.0"?><testsuites><testsuite name="pytest">{cases}</testsuite></testsuites>'


PASS = '<testcase classname="tests.test_a" name="test_ok"/>'
FAIL = '<testcase classname="tests.test_a" name="test_bad"><failure message="boom"/></testcase>'
DB_SKIP = ('<testcase classname="tests.test_schema" name="test_x">'
           '<skipped message="PostgreSQL not reachable (run `docker compose up -d db`)"/></testcase>')
# Module-level skips (pytest.skip(allow_module_level=True) / importorskip) look like this in JUnit:
BROWSER_SKIP = ('<testcase classname="" name="tests.test_ui_browser"><skipped message="collection skipped">'
                "('tests/test_ui_browser.py', 30, 'Skipped: opt-in: set UI_BROWSER=1 (see module docstring)')"
                '</skipped></testcase>')
UI_SKIP = ('<testcase classname="" name="tests.test_ui_app"><skipped message="collection skipped">'
           "('tests/test_ui_app.py', 17, \"Skipped: could not import 'streamlit'\")</skipped></testcase>")


def check(tmp_path: Path, cases: str, exit_code: int) -> int:
    path = tmp_path / "report.xml"
    path.write_text(junit(cases), encoding="utf-8")
    return C.main([str(path), str(exit_code)])


def test_all_passed(tmp_path: Path) -> None:
    assert check(tmp_path, PASS + BROWSER_SKIP, 0) == 0


def test_exit_134_after_all_passed_is_accepted(tmp_path: Path) -> None:
    assert check(tmp_path, PASS, 134) == 0


@pytest.mark.parametrize(("cases", "code"), [
    (FAIL, 1), (FAIL, 134),          # a real failure, also when the run then aborted
    (PASS + DB_SKIP, 0),             # DB tests skipped = Postgres service missing -> fail
    (PASS + UI_SKIP, 0),             # UI tests skipped = requirements-ui.txt not installed -> fail
    (PASS, 1), (PASS, 139),          # other exit codes are not excused
    ("", 0),                         # nothing ran
])
def test_rejected(tmp_path: Path, cases: str, code: int) -> None:
    assert check(tmp_path, cases, code) == 1


def test_missing_report_fails(tmp_path: Path) -> None:
    assert C.main([str(tmp_path / "nope.xml"), "134"]) == 1


# ==========================================================================
# Task 9.15a: Messenger settings
# ==========================================================================

MESSENGER_VARS = ("MESSENGER_ENABLED", "MESSENGER_OTN_ENABLED", "META_APP_SECRET", "META_VERIFY_TOKEN",
                  "META_PAGE_TOKEN", "META_PAGE_ID", "META_GRAPH_VERSION",
                  "MESSENGER_PAGE_USERNAME")  # 9.15a-3: + the Page username


def test_messenger_settings_reach_only_the_api_and_are_off_by_default() -> None:
    env = SERVICES["api"]["environment"]
    assert (env["MESSENGER_ENABLED"], env["MESSENGER_OTN_ENABLED"]) == \
        ("${MESSENGER_ENABLED:-false}", "${MESSENGER_OTN_ENABLED:-false}")
    for var in MESSENGER_VARS[2:]:
        assert env[var] == "${" + var + ":-}"                           # no value in git, empty default
    for name in ("ui", "caddy", "db", "artlab-sync"):
        assert not any(k.startswith(("META_", "MESSENGER_")) for k in SERVICES[name].get("environment") or {}), name


@pytest.mark.parametrize("example", [".env.example", ".env.prod.example"])
def test_env_examples_have_empty_meta_placeholders(example: str) -> None:
    values = dict(line.split("=", 1) for line in (ROOT / example).read_text(encoding="utf-8").splitlines()
                  if line and not line.startswith("#"))
    assert (values["MESSENGER_ENABLED"], values["MESSENGER_OTN_ENABLED"]) == ("false", "false")
    for var in MESSENGER_VARS[2:]:
        assert values[var] == "", var


def test_cleanup_timer_runs_the_cleanup_daily() -> None:
    service = (ROOT / "deploy" / "systemd" / "ocp-messenger-cleanup.service").read_text(encoding="utf-8")
    timer = (ROOT / "deploy" / "systemd" / "ocp-messenger-cleanup.timer").read_text(encoding="utf-8")
    assert "exec -T api python -m src.api.messenger.cleanup" in service
    assert "OnCalendar=*-*-* 03:30:00 Asia/Ulaanbaatar" in timer and "Unit=ocp-messenger-cleanup.service" in timer
