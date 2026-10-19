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
    assert set(SERVICES) == {"db", "api", "ui", "caddy"}


def test_only_caddy_publishes_ports() -> None:
    """D-061: the API and the database are not reachable from the internet."""
    published = {name for name, s in SERVICES.items() if s.get("ports")}
    assert published == {"caddy"}
    assert {p.split(":")[0] for p in SERVICES["caddy"]["ports"]} == {"80", "443"}


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
    ("db", "POSTGRES_PASSWORD"), ("api", "POSTGRES_PASSWORD"), ("ui", "UI_PASSWORD"), ("caddy", "DOMAIN")])
def test_secrets_have_no_default(service: str, var: str) -> None:
    """${VAR:?...} = compose refuses to start without it; no dev password slips into production."""
    assert re.fullmatch(r"\$\{" + var + r":\?[^}]+\}", SERVICES[service]["environment"][var])


def test_ui_talks_to_api_inside_the_network() -> None:
    assert SERVICES["ui"]["environment"]["API_URL"] == "http://api:8000"


def test_caddy_proxies_ui_and_only_health_of_api() -> None:
    caddyfile = (ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8")
    assert "{$DOMAIN}" in caddyfile
    assert "reverse_proxy ui:8501" in caddyfile
    api_routes = re.findall(r"handle (\S+) \{\s*reverse_proxy api:8000", caddyfile)
    assert api_routes == ["/health"]


def test_env_example_covers_compose_and_holds_no_real_values() -> None:
    """Every ${VAR} the prod compose reads is in .env.prod.example; secrets are CHANGE_ME, phone is the placeholder."""
    text = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    used = set(re.findall(r"\$\{([A-Z_]+)", text))
    values = dict(line.split("=", 1) for line in ENV_EXAMPLE.splitlines() if line and not line.startswith("#"))
    assert used <= set(values)
    for var in ("POSTGRES_PASSWORD", "UI_PASSWORD", "DOMAIN"):
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
