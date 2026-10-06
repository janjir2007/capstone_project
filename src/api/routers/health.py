"""GET /health — is the API running, and can it reach the database? (task 4.1)

Used by docker-compose, the cloud host and the demo warm-up (RISK-07).
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import Engine

from src.api.db import database_is_up, get_engine

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Body of GET /health."""

    status: Literal["ok", "error"]
    db: Literal["ok", "error"]


@router.get("/health", response_model=HealthResponse)
def health(response: Response, engine: Annotated[Engine, Depends(get_engine)]) -> HealthResponse:
    """200 ``{status: ok, db: ok}`` if the database answers, else 503 with ``error``.

    503 (Service Unavailable) lets Docker / the cloud host see that the service
    is not usable yet, instead of a misleading 200.
    """
    if database_is_up(engine):
        return HealthResponse(status="ok", db="ok")
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="error", db="error")
