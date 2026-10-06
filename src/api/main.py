"""FastAPI application entry point (task 4.1).

Run locally:   uvicorn src.api.main:app --reload
In Docker:     see Dockerfile / docker-compose.yml (service "api")

Data endpoints: tasks 4.2 + 4.2b. ML/CV model loading (task 4.3) is added later;
this file only wires settings, the database engine and the routers.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import Engine

from src.api.config import load_settings
from src.api.db import create_db_engine
from src.api.routers import destinations, health, services, stats, vehicles

API_VERSION = "0.1.0"


def create_app(engine: Engine | None = None) -> FastAPI:
    """Build the FastAPI app.

    ``engine`` is for tests (e.g. an in-memory SQLite engine). When it is None,
    settings are read from the environment at startup, not at import time, so
    importing this module never needs a database or a password.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = engine if engine is not None else create_db_engine(load_settings().database_url)
        yield
        app.state.engine.dispose()  # close pooled connections on shutdown

    app = FastAPI(title="Oil Change Predictor API", version=API_VERSION, lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(vehicles.router)
    app.include_router(services.router)
    app.include_router(stats.router)
    app.include_router(destinations.router)
    return app


app = create_app()
