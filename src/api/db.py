"""Database connection for the API (task 4.1): engine, per-request session, health check.

The schema itself is NOT created here: it comes from src/data/schema.sql and the
numbered SQL migrations (see the 4.1 handoff for the plain SQL vs Alembic note).
"""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

# Seconds to wait for Postgres to answer before giving up (health must not hang).
CONNECT_TIMEOUT_SECONDS = 3


def create_db_engine(database_url: str) -> Engine:
    """Create the connection pool. Nothing connects until the first query.

    pool_pre_ping: test a pooled connection before using it, so a database
    restart (or a cloud DB closing idle connections) does not cause errors.
    """
    connect_args = {"connect_timeout": CONNECT_TIMEOUT_SECONDS} if database_url.startswith("postgresql") else {}
    return create_engine(database_url, pool_pre_ping=True, connect_args=connect_args)


def get_engine(request: Request) -> Engine:
    """FastAPI dependency: the engine created at startup (see main.lifespan)."""
    return request.app.state.engine


def get_session(engine: Annotated[Engine, Depends(get_engine)]) -> Iterator[Session]:
    """FastAPI dependency: one Session per request, always closed afterwards.

    Endpoints (task 4.2) use it as ``session: Annotated[Session, Depends(get_session)]``
    and call ``session.commit()`` themselves when they write.
    """
    with Session(engine) as session:
        yield session


def database_is_up(engine: Engine) -> bool:
    """Return True if a trivial query (SELECT 1) succeeds."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True
