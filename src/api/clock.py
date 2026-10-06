"""Today's date for the API, in Ulaanbaatar time (task 4.2).

The business runs in Mongolia, but the cloud database (Supabase) and the API
host usually run in UTC, so the date must not come from the server clock or
from Postgres CURRENT_DATE. Mongolia is UTC+8 all year (no daylight saving
since 2017), so a fixed offset is enough and no tz database is needed in the
Docker image.

Endpoints get today through the ``get_today`` dependency; tests override it
to freeze time (segments depend on the date).
"""

from datetime import date, datetime, timedelta, timezone

ULAANBAATAR = timezone(timedelta(hours=8), name="Asia/Ulaanbaatar")


def today_ulaanbaatar() -> date:
    """Current calendar date in Ulaanbaatar."""
    return datetime.now(ULAANBAATAR).date()


def get_today() -> date:
    """FastAPI dependency: today's date (override in tests)."""
    return today_ulaanbaatar()
