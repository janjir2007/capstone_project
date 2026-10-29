"""FastAPI application entry point (task 4.1).

Run locally:   uvicorn src.api.main:app --reload
In Docker:     see Dockerfile / docker-compose.yml (service "api")

Data endpoints: tasks 4.2 + 4.2b. Models (task 4.3): the prediction model and
the plate recognizer are loaded ONCE at startup from MODEL_DIR. If a model file
is missing the API still starts (data endpoints keep working): the card's
prediction is null and the model endpoints answer 503.
"""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from sqlalchemy import Engine

from src.api.config import load_settings, oil_interval_km
from src.api.config import model_dir as model_dir_from_env
from src.api.db import create_db_engine
from src.api.prediction import load_predictor
from src.api.routers import destinations, health, plates, reminders, services, stats, vehicles
from src.cv.plate_reader import PlateRecognizer

API_VERSION = "0.5.0"  # = docs/api_contract.md version
log = logging.getLogger("uvicorn.error")


def _load(what: str, loader: Callable[[Path], Any], folder: Path) -> Any:
    """Load one model; on failure log why and return None (the API runs without it)."""
    try:
        return loader(folder)
    except (OSError, ValueError, KeyError) as exc:
        log.warning("%s not loaded from %s: %s", what, folder, exc)
        return None


def create_app(engine: Engine | None = None, model_dir: Path | None = None) -> FastAPI:
    """Build the FastAPI app.

    ``engine`` is for tests (e.g. an in-memory SQLite engine). When it is None,
    settings are read from the environment at startup, not at import time, so
    importing this module never needs a database or a password.
    ``model_dir`` is for tests too; default = MODEL_DIR env or ./models.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        oil_interval_km()  # 9.5a: a bad OIL_INTERVAL_KM stops the start here, not every card request
        app.state.engine = engine if engine is not None else create_db_engine(load_settings().database_url)
        folder = model_dir if model_dir is not None else model_dir_from_env()
        app.state.predictor = _load("prediction model", load_predictor, folder)
        app.state.recognizer = _load("plate recognizer", PlateRecognizer, folder)
        yield
        app.state.engine.dispose()  # close pooled connections on shutdown

    app = FastAPI(title="Oil Change Predictor API", version=API_VERSION, lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(vehicles.router)
    app.include_router(services.router)
    app.include_router(stats.router)
    app.include_router(destinations.router)
    app.include_router(plates.router)
    app.include_router(reminders.router)
    return app


app = create_app()
