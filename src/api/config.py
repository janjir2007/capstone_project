"""API settings, read from environment variables (task 4.1).

No secrets live in code: the database password must come from the environment
(.env locally, docker-compose, or the cloud host's secret settings).

Two ways to point the API at a database, same rule as tests/test_schema.py:
1. DATABASE_URL (full URL, e.g. Supabase later) — used if set.
2. Otherwise POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_HOST / POSTGRES_PORT /
   POSTGRES_DB (the local Docker setup in .env.example).
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

# SQLAlchemy needs the driver in the URL: "+psycopg" = psycopg 3 (already pinned).
SQLALCHEMY_SCHEME = "postgresql+psycopg://"


class ConfigError(RuntimeError):
    """A required setting is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    """Everything the API reads from the environment."""

    app_env: str
    database_url: str


def to_sqlalchemy_url(url: str) -> str:
    """Make a Postgres URL use the psycopg 3 driver.

    Providers (Supabase, Render, ...) usually give ``postgresql://`` or the old
    ``postgres://`` form; SQLAlchemy would pick psycopg2 (not installed) for
    those, so the scheme is rewritten.
    """
    for prefix in ("postgresql+psycopg://", "postgresql://", "postgres://"):
        if url.startswith(prefix):
            return SQLALCHEMY_SCHEME + url[len(prefix):]
    raise ConfigError("DATABASE_URL must start with postgresql:// or postgres://")


def build_database_url(env: Mapping[str, str]) -> str:
    """Return the SQLAlchemy database URL from DATABASE_URL or POSTGRES_* values.

    Non-secret values default to the local Docker setup; the password has no
    default on purpose.
    """
    url = env.get("DATABASE_URL")
    if url:
        return to_sqlalchemy_url(url)

    password = env.get("POSTGRES_PASSWORD")
    if not password:
        raise ConfigError("Set DATABASE_URL or POSTGRES_PASSWORD (see .env.example).")
    user = env.get("POSTGRES_USER", "oil")
    host = env.get("POSTGRES_HOST", "localhost")
    port = env.get("POSTGRES_PORT", "5432")
    name = env.get("POSTGRES_DB", "oil_change")
    # quote(): characters like @ / : in a password would otherwise break the URL.
    return f"{SQLALCHEMY_SCHEME}{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}/{name}"


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Read settings from ``env`` (defaults to the real process environment)."""
    env = os.environ if env is None else env
    return Settings(
        app_env=env.get("APP_ENV", "local"),
        database_url=build_database_url(env),
    )


# Folder with the git-ignored model files (task 4.3). docker-compose mounts ./models here read-only.
DEFAULT_MODEL_DIR = "models"


def model_dir(env: Mapping[str, str] | None = None) -> Path:
    """MODEL_DIR from the environment, else ./models. Needs no database settings."""
    env = os.environ if env is None else env
    return Path(env.get("MODEL_DIR", DEFAULT_MODEL_DIR))


# Geo-Expert contact in the reminder message (task 4.4). Placeholder = the made-up number of
# src/data/sample_data.sql; set the real one in .env / the host's settings before any real SMS.
PLACEHOLDER_PHONE = "99000000"


@dataclass(frozen=True)
class Contact:
    """Who the customer calls back: shown at the end of every reminder."""

    name: str
    phone: str
    is_placeholder: bool


# Task 9.5a: target km of the next oil change = odometer at the last change + this interval.
# 15,000 km = the recommended interval in Mongolia (D-030). Mine trucks (engine hours only) get none.
DEFAULT_OIL_INTERVAL_KM = 15000


def oil_interval_km(env: Mapping[str, str] | None = None) -> int:
    """OIL_INTERVAL_KM from the environment (default 15000). Not a whole number > 0 -> ConfigError."""
    env = os.environ if env is None else env
    raw = env.get("OIL_INTERVAL_KM", "").strip()
    if not raw:
        return DEFAULT_OIL_INTERVAL_KM
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value <= 0:
        raise ConfigError(f"OIL_INTERVAL_KM must be a whole number of km > 0, got {raw!r}")
    return value


def reminder_contact(env: Mapping[str, str] | None = None) -> Contact:
    """Contact at the end of every reminder (needs no database settings).

    Task 9.5b: CONTACT_PHONE = the oil changer's number. The older GEO_EXPERT_PHONE is still read
    when CONTACT_PHONE is not set, so a server .env from before 9.5b keeps its real number.
    """
    env = os.environ if env is None else env
    phone = (env.get("CONTACT_PHONE", "").strip() or env.get("GEO_EXPERT_PHONE", "").strip()
             or PLACEHOLDER_PHONE)
    name = env.get("GEO_EXPERT_NAME", "").strip() or "Geo-Expert"
    return Contact(name=name, phone=phone, is_placeholder=phone == PLACEHOLDER_PHONE)
