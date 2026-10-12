"""GET /stats/segments — how many vehicles are in each segment (tasks 4.2, 4.4).

Segments (D-007): new (1 service), returning (2), loyal (3+); at_risk wins =
predicted date + 7 days grace has passed and the truck has not come back.

Task 4.4: predictions are computed by the API (task 4.3) and never written to
the `predictions` table (only sample_data.sql has 4 hand-written rows), so on
real data the database function vehicle_segments(as_of) could not find at_risk. The counts are therefore made here with
``prediction.segment_of`` on the served prediction, as of ``as_of`` (only
services up to that day). Without the model files the database function
answers (count-based segments only).
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.api.clock import get_today
from src.api.db import get_session
from src.api.history import records_as_of, to_visit
from src.api.prediction import Predictor, segment_of
from src.api.routers.vehicles import get_predictor
from src.api.schemas import SegmentCounts, SegmentStats

router = APIRouter(prefix="/stats", tags=["stats"])


def counts_from_predictions(session: Session, predictor: Predictor, as_of: date) -> dict[str, int]:
    """Segment counts with at_risk from the served predictions (D-007)."""
    records = records_as_of(session, as_of)
    predictions = predictor.predict_many({vid: [to_visit(r) for r in rs] for vid, rs in records.items()}, as_of)
    counts: dict[str, int] = {}
    for vid, rs in records.items():
        segment = segment_of(len(rs), predictions[vid].predicted_date, as_of)
        counts[segment] = counts.get(segment, 0) + 1
    return counts


def counts_from_database(session: Session, as_of: date) -> dict[str, int]:
    """Fallback without the model: the SQL function vehicle_segments (schema.sql)."""
    rows = session.execute(
        text("SELECT segment, COUNT(*) AS vehicles FROM vehicle_segments(:as_of) GROUP BY segment"),
        {"as_of": as_of},
    ).all()
    return {segment: vehicles for segment, vehicles in rows}


@router.get("/segments", response_model=SegmentStats)
def segment_stats(
    session: Annotated[Session, Depends(get_session)],
    today: Annotated[date, Depends(get_today)],
    predictor: Annotated[Predictor | None, Depends(get_predictor)],
    as_of: Annotated[date | None, Query(description="Default: today (Ulaanbaatar). Past dates give past answers")] = None,
) -> SegmentStats:
    """Vehicle count per segment on ``as_of``; all four segments always present."""
    as_of = as_of or today
    counts = (counts_from_predictions(session, predictor, as_of) if predictor is not None
              else counts_from_database(session, as_of))
    return SegmentStats(as_of=as_of, total=sum(counts.values()), counts=SegmentCounts(**counts))
