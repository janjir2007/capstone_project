"""GET /destinations — the list for the "where are you heading next?" picker (task 4.2b).

The recording form sends the chosen id as destination_id in POST /services
(D-033); the route then comes from the destination (D-039). name_mn, the
Mongolian label (D-040), is added after migration 002.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.db import get_session
from src.api.models import Destination
from src.api.schemas import DestinationOut

router = APIRouter(tags=["destinations"])


@router.get("/destinations", response_model=list[DestinationOut])
def list_destinations(session: Annotated[Session, Depends(get_session)]) -> list[DestinationOut]:
    """All destinations in seeded order (id): the list was written in a useful
    order, with "Other / several / unknown" last."""
    destinations = session.scalars(select(Destination).order_by(Destination.id)).all()
    return [DestinationOut.model_validate(destination) for destination in destinations]
