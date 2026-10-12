"""HTTP client for the FastAPI backend (contract: docs/api_contract.md).

The UI talks to the backend ONLY through these functions (D-052): no import of
src/api, no database access. This module does not import Streamlit, so it can
be tested without it (CI installs only requirements.txt, which has httpx).

Base URL comes from the env var API_URL (default http://localhost:8000).
Tests replace the network with `httpx.MockTransport` via `set_transport()`.
"""

import os
from typing import Any

import httpx

DEFAULT_API_URL = "http://localhost:8000"
TIMEOUT_SECONDS = 10.0

# None = real network. Tests set an httpx.MockTransport here.
_transport: httpx.BaseTransport | None = None


class ApiError(Exception):
    """The API answered with an error, or could not be reached.

    `status` is the HTTP status code (0 = no connection), `detail` the
    FastAPI `detail` field (string, list of pydantic errors, or dict).
    """

    def __init__(self, status: int, detail: Any) -> None:
        super().__init__(f"API error {status}: {detail}")
        self.status = status
        self.detail = detail


class DuplicateService(ApiError):
    """409 duplicate_service: the vehicle already has a service on that date.

    Nothing was saved. Send again with force=True to save anyway.
    """

    @property
    def existing_service_id(self) -> int | None:
        return self.detail.get("existing_service_id") if isinstance(self.detail, dict) else None


def api_url() -> str:
    """Base URL of the API, without a trailing slash."""
    return (os.environ.get("API_URL") or DEFAULT_API_URL).rstrip("/")


def set_transport(transport: httpx.BaseTransport | None) -> None:
    """Replace the network layer (tests only). None restores the real network."""
    global _transport
    _transport = transport


def _request(method: str, path: str, **kwargs: Any) -> Any:
    """Send one request and return the decoded JSON body.

    Raises DuplicateService for 409 duplicate_service, ApiError for any other
    non-2xx status or a connection failure (status 0).
    """
    try:
        with httpx.Client(base_url=api_url(), timeout=TIMEOUT_SECONDS, transport=_transport) as client:
            response = client.request(method, path, **kwargs)
    except httpx.HTTPError as exc:
        raise ApiError(0, str(exc)) from exc

    if response.is_success:
        return response.json()

    try:
        detail = response.json().get("detail")
    except ValueError:  # body is not JSON (e.g. a proxy error page)
        detail = response.text
    if response.status_code == 409 and isinstance(detail, dict) and detail.get("code") == "duplicate_service":
        raise DuplicateService(409, detail)
    raise ApiError(response.status_code, detail)


def health() -> dict:
    """GET /health -> {status, db}."""
    return _request("GET", "/health")


def lookup(query: str) -> dict:
    """GET /vehicles/lookup?q= -> {query, match_type, normalized, vehicles: [VehicleCard]}.

    Unknown plate/phone is NOT an error: 200 with an empty `vehicles` list.
    """
    return _request("GET", "/vehicles/lookup", params={"q": query})


def get_vehicle(vehicle_id: int) -> dict:
    """GET /vehicles/{id} -> VehicleCard (ApiError 404 if unknown)."""
    return _request("GET", f"/vehicles/{vehicle_id}")


def destinations() -> list[dict]:
    """GET /destinations -> [{id, name, route_category, name_mn?}] in seeded order."""
    return _request("GET", "/destinations")


def create_service(payload: dict, force: bool = False) -> dict:
    """POST /services -> {service, vehicle_id, vehicle_created, company_created}.

    force=True saves a second service on the same date (after a 409 duplicate).
    """
    params = {"force": "true"} if force else None
    return _request("POST", "/services", json=payload, params=params)


def recognize_plate(image: bytes, filename: str, content_type: str = "image/jpeg") -> dict:
    """POST /plates/recognize -> {plate_raw, plate_normalized, confidence, bbox, needs_manual}.

    The endpoint does not exist yet (task 4.3). The multipart field name
    "image" is an ASSUMPTION — verify against the 4.3 contract before enabling
    the UI flag UI_ENABLE_RECOGNIZE.
    """
    return _request("POST", "/plates/recognize", files={"image": (filename, image, content_type)})
