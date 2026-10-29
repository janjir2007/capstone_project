"""GET /stats/segments — how many vehicles are in each segment (tasks 4.2, 4.4, 9.5b).

Segments: new (1 service), returning (2), loyal (3+); at_risk wins = 90+ days since the latest
service without coming back (task 9.5b, src/api/reminders.segment_of — the same rule as the card,
the dashboard and the reminder list; it replaced the predicted date + 7 days rule of D-007).
Counted as of ``as_of`` (only services up to that day). Needs no model files.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.api.clock import get_today
from src.api.db import get_session
from src.api.history import records_as_of
from src.api.reminders import segment_of
from src.api.schemas import SegmentCounts, SegmentStats

router = APIRouter(prefix="/stats", tags=["stats"])


def segment_counts(session: Session, as_of: date) -> dict[str, int]:
    """Vehicles per segment on as_of (vehicles without a service by then are not counted)."""
    counts: dict[str, int] = {}
    for rs in records_as_of(session, as_of).values():  # services oldest first
        segment = segment_of(len(rs), rs[-1].service_date, as_of)
        counts[segment] = counts.get(segment, 0) + 1
    return counts


@router.get("/segments", response_model=SegmentStats)
def segment_stats(
    session: Annotated[Session, Depends(get_session)],
    today: Annotated[date, Depends(get_today)],
    as_of: Annotated[date | None, Query(description="Default: today (Ulaanbaatar). Past dates give past answers")] = None,
) -> SegmentStats:
    """Vehicle count per segment on ``as_of``; all four segments always present."""
    as_of = as_of or today
    counts = segment_counts(session, as_of)
    return SegmentStats(as_of=as_of, total=sum(counts.values()), counts=SegmentCounts(**counts))
