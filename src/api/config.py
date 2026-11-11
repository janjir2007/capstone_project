"""API settings, read from environment variables (task 4.1).

No secrets live in code: the database password must come from the environment
(.env locally, docker-compose, or the cloud host's secret settings).

Two ways to point the API at a database, same rule as tests/test_schema.py:
1. DATABASE_URL (full URL, e.g. Supabase later) — used if set.
2. Otherwise POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_HOST / POSTGRES_PORT /
   POSTGRES_DB (the local Docker setup in .env.example).
"""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
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
# Task 9.14a: 12,000 km (was 15,000, D-030), stored on each service when it is saved
# (service_records.interval_km / target_km, migration 010). Mine trucks (engine hours only) get none.
DEFAULT_OIL_INTERVAL_KM = 12000


def oil_interval_km(env: Mapping[str, str] | None = None) -> int:
    """OIL_INTERVAL_KM from the environment (default 12000). Not a whole number > 0 -> ConfigError."""
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


# Task 9.5c (D-119): one reminder REMINDER_DAYS after the latest service; «Эрсдэлтэй» (at_risk)
# AT_RISK_DAYS after it without a new service.
DEFAULT_REMINDER_DAYS = 75
DEFAULT_AT_RISK_DAYS = 150
# Task 9.14a: with the truck's km/day known, the reminder goes REMINDER_LEAD_DAYS before the due day;
# without it, a «Км шалгах» message asks the driver for his km KM_CHECK_DAYS after the service.
DEFAULT_REMINDER_LEAD_DAYS = 5
DEFAULT_KM_CHECK_DAYS = 34


@dataclass(frozen=True)
class ReminderRules:
    """Day counts of the reminder rule, all counted from the truck's latest service
    (lead_days: back from the km/day due day)."""

    reminder_days: int
    at_risk_days: int
    lead_days: int = DEFAULT_REMINDER_LEAD_DAYS
    km_check_days: int = DEFAULT_KM_CHECK_DAYS


def _whole_days(env: Mapping[str, str], name: str, default: int) -> int:
    """A whole number of days > 0 from env[name]; empty -> default; anything else -> ConfigError."""
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value <= 0:
        raise ConfigError(f"{name} must be a whole number of days > 0, got {raw!r}")
    return value


def reminder_rules(env: Mapping[str, str] | None = None) -> ReminderRules:
    """REMINDER_DAYS (75), AT_RISK_DAYS (150), REMINDER_LEAD_DAYS (5) and KM_CHECK_DAYS (34) from the
    environment.

    ConfigError if one is not a whole number > 0, AT_RISK_DAYS <= REMINDER_DAYS (a truck would be at
    risk before its reminder is due), REMINDER_LEAD_DAYS >= AT_RISK_DAYS (the latest reminder day,
    AT_RISK_DAYS - REMINDER_LEAD_DAYS, would be on or before the service) or KM_CHECK_DAYS >=
    REMINDER_DAYS (the km check would come after the reminder it is meant to move). main.py calls
    this at startup, so a bad value stops it.
    """
    env = os.environ if env is None else env
    rules = ReminderRules(reminder_days=_whole_days(env, "REMINDER_DAYS", DEFAULT_REMINDER_DAYS),
                          at_risk_days=_whole_days(env, "AT_RISK_DAYS", DEFAULT_AT_RISK_DAYS),
                          lead_days=_whole_days(env, "REMINDER_LEAD_DAYS", DEFAULT_REMINDER_LEAD_DAYS),
                          km_check_days=_whole_days(env, "KM_CHECK_DAYS", DEFAULT_KM_CHECK_DAYS))
    if rules.at_risk_days <= rules.reminder_days:
        raise ConfigError(f"AT_RISK_DAYS ({rules.at_risk_days}) must be greater than "
                          f"REMINDER_DAYS ({rules.reminder_days})")
    if rules.lead_days >= rules.at_risk_days:
        raise ConfigError(f"REMINDER_LEAD_DAYS ({rules.lead_days}) must be less than "
                          f"AT_RISK_DAYS ({rules.at_risk_days})")
    if rules.km_check_days >= rules.reminder_days:
        raise ConfigError(f"KM_CHECK_DAYS ({rules.km_check_days}) must be less than "
                          f"REMINDER_DAYS ({rules.reminder_days})")
    return rules


# Task 9.12-3: the «Төлөөгүй» list shows only bills from the last N days. Same setting (and default)
# as the nightly sync's re-check window (src/artlab/sync.py): an older bill is never re-checked, so
# its «unpaid» may be stale and must not be listed as money owed.
DEFAULT_UNPAID_LOOKBACK_DAYS = 90


def unpaid_lookback_days(env: Mapping[str, str] | None = None) -> int:
    """ARTLAB_UNPAID_LOOKBACK_DAYS (default 90). Not a whole number > 0 -> ConfigError."""
    env = os.environ if env is None else env
    return _whole_days(env, "ARTLAB_UNPAID_LOOKBACK_DAYS", DEFAULT_UNPAID_LOOKBACK_DAYS)


# Task 9.16b: a tracked service not marked «Төлсөн» becomes «Авлага» this many hours after it was saved.
# Its own setting: ARTLAB_UNPAID_LOOKBACK_DAYS (D-133) is the Artlab re-check window, a different thing.
DEFAULT_PAYMENT_DUE_HOURS = 24


def payment_due_hours(env: Mapping[str, str] | None = None) -> int:
    """PAYMENT_DUE_HOURS (default 24). Not a whole number > 0 -> ConfigError (the API does not start)."""
    env = os.environ if env is None else env
    raw = env.get("PAYMENT_DUE_HOURS", "").strip()
    if not raw:
        return DEFAULT_PAYMENT_DUE_HOURS
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value <= 0:
        raise ConfigError(f"PAYMENT_DUE_HOURS must be a whole number of hours > 0, got {raw!r}")
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


# Task 9.15a: Messenger km bot. Secrets come ONLY from the server .env (never in git, never logged):
# META_APP_SECRET (checks Meta's signature), META_VERIFY_TOKEN (webhook set-up), META_PAGE_TOKEN
# (Send API). META_GRAPH_VERSION = the ONE place the Graph API version is set (e.g. v26.0; take it
# from the app dashboard). Both switches default to off: safe to deploy before Meta is ready.
MESSENGER_REQUIRED = ("META_APP_SECRET", "META_VERIFY_TOKEN", "META_PAGE_TOKEN", "META_PAGE_ID", "META_GRAPH_VERSION")
_TRUE, _FALSE = ("1", "true", "yes", "on"), ("", "0", "false", "no", "off")


@dataclass(frozen=True)
class MessengerSettings:
    """Messenger bot settings. repr=False on the secrets: printing the object never shows them."""

    enabled: bool = False
    otn_enabled: bool = False
    app_secret: str = field(default="", repr=False)
    verify_token: str = field(default="", repr=False)
    page_token: str = field(default="", repr=False)
    page_id: str = ""
    graph_version: str = ""
    page_username: str = ""  # 9.15a-3: the Page's m.me name (not a secret); empty = no link in the SMS


def _switch(env: Mapping[str, str], name: str) -> bool:
    raw = env.get(name, "").strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    raise ConfigError(f"{name} must be true or false")  # the value is not repeated: never echo settings


def messenger_settings(env: Mapping[str, str] | None = None) -> MessengerSettings:
    """MESSENGER_ENABLED / MESSENGER_OTN_ENABLED (default false) + the META_* values.

    ConfigError (the API does not start) when MESSENGER_ENABLED=true and a META_* value is empty,
    MESSENGER_OTN_ENABLED=true without MESSENGER_ENABLED, or META_GRAPH_VERSION / META_PAGE_ID /
    MESSENGER_PAGE_USERNAME look wrong. MESSENGER_PAGE_USERNAME (9.15a-3) is optional: empty -> the
    km-check SMS has no m.me link. Errors name the setting only, never its value.
    """
    env = os.environ if env is None else env
    settings = MessengerSettings(
        enabled=_switch(env, "MESSENGER_ENABLED"), otn_enabled=_switch(env, "MESSENGER_OTN_ENABLED"),
        app_secret=env.get("META_APP_SECRET", "").strip(), verify_token=env.get("META_VERIFY_TOKEN", "").strip(),
        page_token=env.get("META_PAGE_TOKEN", "").strip(), page_id=env.get("META_PAGE_ID", "").strip(),
        graph_version=env.get("META_GRAPH_VERSION", "").strip(),
        page_username=env.get("MESSENGER_PAGE_USERNAME", "").strip())
    if settings.otn_enabled and not settings.enabled:
        raise ConfigError("MESSENGER_OTN_ENABLED=true needs MESSENGER_ENABLED=true")
    if settings.enabled:
        missing = [name for name in MESSENGER_REQUIRED if not env.get(name, "").strip()]
        if missing:
            raise ConfigError(f"MESSENGER_ENABLED=true but empty in .env: {', '.join(missing)}")
    if settings.graph_version and not re.fullmatch(r"v[0-9]+\.[0-9]+", settings.graph_version):
        raise ConfigError("META_GRAPH_VERSION must look like v26.0")
    if settings.page_id and not settings.page_id.isdigit():
        raise ConfigError("META_PAGE_ID must be the Page's number")
    if settings.page_username and not re.fullmatch(r"[A-Za-z0-9.]{5,50}", settings.page_username):
        raise ConfigError("MESSENGER_PAGE_USERNAME must be the Page username only (letters, digits, dots), "
                          "e.g. WolfCenterMongolia, not a link")
    return settings
