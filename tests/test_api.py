"""API skeleton tests (task 4.1): settings from env, /health, DB session, pins.

Most tests need NO Postgres (in-memory SQLite stands in for "a database that
answers", an unused port for "a database that is down"), so they run in CI.
The last test talks to the real local Postgres and is SKIPPED if it is not
running, like tests/test_schema.py.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.api.config import ConfigError, build_database_url, load_settings, to_sqlalchemy_url
from src.api.db import create_db_engine, database_is_up, get_session
from src.api.main import create_app
from tests.test_schema import database_url as postgres_test_url

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def sqlite_engine() -> Iterator[Engine]:
    """An in-memory database that always answers (StaticPool = one shared connection)."""
    engine = create_engine("sqlite://", poolclass=StaticPool)
    yield engine
    engine.dispose()


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

def test_url_built_from_postgres_vars() -> None:
    env = {"POSTGRES_USER": "u", "POSTGRES_PASSWORD": "pw", "POSTGRES_HOST": "db",
           "POSTGRES_PORT": "5433", "POSTGRES_DB": "x"}
    assert build_database_url(env) == "postgresql+psycopg://u:pw@db:5433/x"


def test_defaults_match_local_docker_except_password() -> None:
    assert build_database_url({"POSTGRES_PASSWORD": "pw"}) == "postgresql+psycopg://oil:pw@localhost:5432/oil_change"


def test_password_special_characters_are_escaped() -> None:
    assert build_database_url({"POSTGRES_PASSWORD": "a@b/c:d"}).startswith("postgresql+psycopg://oil:a%40b%2Fc%3Ad@")


def test_missing_password_is_an_error() -> None:
    """No password default in code: forgetting it fails loudly at startup."""
    with pytest.raises(ConfigError):
        build_database_url({"POSTGRES_USER": "oil"})


def test_database_url_wins_over_postgres_vars() -> None:
    env = {"DATABASE_URL": "postgresql://a:b@cloud:6543/postgres", "POSTGRES_PASSWORD": "ignored"}
    assert build_database_url(env) == "postgresql+psycopg://a:b@cloud:6543/postgres"


@pytest.mark.parametrize("url", ["postgres://a:b@h/d", "postgresql://a:b@h/d", "postgresql+psycopg://a:b@h/d"])
def test_provider_urls_get_psycopg_driver(url: str) -> None:
    assert to_sqlalchemy_url(url) == "postgresql+psycopg://a:b@h/d"


def test_non_postgres_url_rejected() -> None:
    with pytest.raises(ConfigError):
        to_sqlalchemy_url("mysql://a:b@h/d")


def test_load_settings_reads_app_env() -> None:
    settings = load_settings({"APP_ENV": "cloud", "POSTGRES_PASSWORD": "pw"})
    assert settings.app_env == "cloud"


# --------------------------------------------------------------------------
# Database helpers
# --------------------------------------------------------------------------

def test_database_is_up_true_for_working_db(sqlite_engine: Engine) -> None:
    assert database_is_up(sqlite_engine) is True


def test_database_is_up_false_when_nothing_listens() -> None:
    """Port 1 on localhost: connection refused -> False, not an exception."""
    engine = create_db_engine("postgresql+psycopg://oil:pw@127.0.0.1:1/oil_change")
    try:
        assert database_is_up(engine) is False
    finally:
        engine.dispose()


def test_get_session_gives_a_working_session(sqlite_engine: Engine) -> None:
    """A test-only route proves the dependency yields a usable Session."""
    app = create_app(engine=sqlite_engine)

    @app.get("/_test_session")
    def _route(session: Annotated[Session, Depends(get_session)]) -> dict[str, int]:
        return {"value": session.execute(text("SELECT 41 + 1")).scalar_one()}

    with TestClient(app) as client:
        assert client.get("/_test_session").json() == {"value": 42}


# --------------------------------------------------------------------------
# GET /health
# --------------------------------------------------------------------------

def test_health_ok_when_db_answers(sqlite_engine: Engine) -> None:
    with TestClient(create_app(engine=sqlite_engine)) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}


def test_health_503_when_db_down() -> None:
    engine = create_db_engine("postgresql+psycopg://oil:pw@127.0.0.1:1/oil_change")
    with TestClient(create_app(engine=engine)) as client:
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"status": "error", "db": "error"}


def test_app_reads_settings_from_env_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without an injected engine, the app builds one from env vars at startup."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_PASSWORD", "pw")
    monkeypatch.setenv("POSTGRES_HOST", "127.0.0.1")
    monkeypatch.setenv("POSTGRES_PORT", "1")  # nothing listens -> 503, but startup worked
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 503


def test_health_ok_against_real_postgres() -> None:
    """Integration: the real local database (docker compose up -d db)."""
    engine = create_db_engine(to_sqlalchemy_url(postgres_test_url()))
    if not database_is_up(engine):
        engine.dispose()
        pytest.skip("PostgreSQL not reachable (run `docker compose up -d db`)")
    with TestClient(create_app(engine=engine)) as client:
        response = client.get("/health")
    assert (response.status_code, response.json()) == (200, {"status": "ok", "db": "ok"})


# --------------------------------------------------------------------------
# Packaging
# --------------------------------------------------------------------------

def pinned_lines(path: Path) -> set[str]:
    """Requirement lines without comments/blank lines, e.g. {'fastapi==0.142.2'}."""
    lines = (line.split("#", 1)[0].strip() for line in path.read_text(encoding="utf-8").splitlines())
    return {line for line in lines if line}


def test_api_requirements_are_pinned_subset_of_main() -> None:
    """The Docker image uses exactly the versions everyone else uses."""
    api = pinned_lines(ROOT / "requirements-api.txt")
    assert api, "requirements-api.txt is empty"
    assert all("==" in line for line in api)
    assert api <= pinned_lines(ROOT / "requirements.txt")
