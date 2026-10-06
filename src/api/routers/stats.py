"""GET /stats/segments — how many vehicles are in each segment (task 4.2).

Segments come from the database function vehicle_segments(as_of) (schema.sql,
data_dictionary §3): new (1 service), returning (2), loyal (3+), at_risk
(predicted date + 7 days passed and not returned, D-007). The API only counts.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.api.clock import get_today
from src.api.db import get_session
from src.api.schemas import SegmentCounts, SegmentStats

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/segments", response_model=SegmentStats)
def segment_stats(
    session: Annotated[Session, Depends(get_session)],
    today: Annotated[date, Depends(get_today)],
    as_of: Annotated[date | None, Query(description="Default: today (Ulaanbaatar). Past dates give past answers")] = None,
) -> SegmentStats:
    """Vehicle count per segment on ``as_of``; all four segments always present."""
    as_of = as_of or today
    rows = session.execute(
        text("SELECT segment, COUNT(*) AS vehicles FROM vehicle_segments(:as_of) GROUP BY segment"),
        {"as_of": as_of},
    ).all()
    counts = {segment: vehicles for segment, vehicles in rows}
    return SegmentStats(as_of=as_of, total=sum(counts.values()), counts=SegmentCounts(**counts))
