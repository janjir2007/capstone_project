"""Daily Messenger cleanup (task 9.15a-2): forget old event ids and expired «Зөв үү?» questions.

- messenger_seen older than 7 days (Meta re-sends a failed event for a while, not for a week)
- messenger_pending past its expires_at (24 h after the km message)

Run once a day by deploy/systemd/ocp-messenger-cleanup.timer (docs/deploy.md §14):
    docker compose -f docker-compose.prod.yml exec -T api python -m src.api.messenger.cleanup
Prints only the two counts (no PSID, no plate).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.orm import Session

from src.api.config import load_settings
from src.api.db import create_db_engine
from src.api.models import MessengerPending, MessengerSeen

SEEN_KEEP_DAYS = 7


def cleanup(session: Session, now: datetime) -> tuple[int, int]:
    """Delete the old rows and commit. Returns (seen_deleted, pending_deleted)."""
    seen = session.execute(delete(MessengerSeen).where(
        MessengerSeen.received_at < now - timedelta(days=SEEN_KEEP_DAYS))).rowcount
    pending = session.execute(delete(MessengerPending).where(MessengerPending.expires_at < now)).rowcount
    session.commit()
    return seen, pending


def main() -> None:
    engine = create_db_engine(load_settings().database_url)
    try:
        with Session(engine) as session:
            seen, pending = cleanup(session, datetime.now(timezone.utc))
    finally:
        engine.dispose()
    print(f"messenger cleanup: {seen} seen ids, {pending} expired questions deleted")


if __name__ == "__main__":
    main()
