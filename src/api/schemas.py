"""Request and response shapes of the data endpoints (task 4.2, contract §8 v0.1).

Pydantic checks every request BEFORE any database work: a bad request gets a
422 with a clear message instead of a database error. Field names follow
docs/data_dictionary.md.

Rules enforced here:
- at least one meter: odometer_km or engine_hours (like the DB CHECK)
- destination: exactly one of destination_id / destination_raw (D-033)
- destination_raw only -> route is required (D-039)
- driver_phone normalized to 8 digits, no +976 (D-019)
"""

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

Route = Literal["ub_city", "mn_china", "mn_russia", "mine_site", "mixed"]
Segment = Literal["new", "returning", "loyal", "at_risk"]

PHONE_SEPARATORS = re.compile(r"[\s\-().]")


def normalize_phone(raw: str) -> str:
    """Return a Mongolian phone number as 8 digits, e.g. '+976 9911-0001' -> '99110001'.

    Removes spaces, dashes, dots and brackets, then a leading +976 / 976
    country code. Raises ValueError if the result is not exactly 8 digits.
    """
    phone = PHONE_SEPARATORS.sub("", raw)
    for prefix in ("+976", "976"):
        if phone.startswith(prefix) and len(phone) == len(prefix) + 8:
            phone = phone[len(prefix):]
    if not re.fullmatch(r"[0-9]{8}", phone):
        raise ValueError("phone must be 8 digits (Mongolian number, +976 optional)")
    return phone


def _blank_to_none(value: object) -> object:
    """Strip text; an empty or spaces-only string means 'not given' (None)."""
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


# Optional free-text field: "" and "   " become None, other text is stripped.
OptionalText = Annotated[str | None, BeforeValidator(_blank_to_none)]
# Required free-text field: stripped, must not be blank.
RequiredText = Annotated[str, Field(min_length=1)]


# --------------------------------------------------------------------------
# POST /services
# --------------------------------------------------------------------------

class ServiceCreate(BaseModel):
    """Body of POST /services: one oil change, as entered by the oil changer.

    Vehicle part: identifier (+ identifier_type). If the vehicle is new, it is
    created and company_name is required. For an existing vehicle,
    company_name and vehicle_model are ignored (the vehicle keeps its data).
    """

    # extra="forbid": a typo in a field name -> 422, not silently dropped.
    # str_strip_whitespace: required text like " 15W-40 " is stored as "15W-40".
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # Vehicle
    identifier_type: Literal["plate", "fleet_no"] = "plate"
    identifier: RequiredText = Field(description="Plate as confirmed (e.g. '1234 УБА') or fleet number")
    company_name: OptionalText = Field(default=None, description="Required only when the vehicle is new")
    vehicle_model: OptionalText = None

    # Service
    service_date: date | None = Field(default=None, description="Default: today (Ulaanbaatar). Not in the future")
    odometer_km: int | None = Field(default=None, ge=0)
    engine_hours: Decimal | None = Field(default=None, ge=0, max_digits=8, decimal_places=1)
    oil_grade: RequiredText
    liters: Decimal = Field(gt=0, max_digits=5, decimal_places=1)

    # Destination + route (D-033, D-039)
    destination_id: int | None = Field(default=None, description="id of a destinations row")
    destination_raw: OptionalText = Field(default=None, description="Free text when the place is not in the list")
    route: Route | None = Field(
        default=None,
        description="Required with destination_raw. With destination_id it is set from the destination",
    )

    # People (D-004: per service record)
    driver_name: OptionalText = None
    driver_phone: OptionalText = None
    oil_changer: OptionalText = None
    photo_ref: OptionalText = None

    @field_validator("driver_phone")
    @classmethod
    def _phone_is_mongolian(cls, value: str | None) -> str | None:
        return None if value is None else normalize_phone(value)

    @model_validator(mode="after")
    def _check_rules(self) -> "ServiceCreate":
        if self.odometer_km is None and self.engine_hours is None:
            raise ValueError("give odometer_km or engine_hours (at least one)")
        if (self.destination_id is None) == (self.destination_raw is None):
            raise ValueError("give exactly one of destination_id or destination_raw")
        if self.destination_raw is not None and self.route is None:
            raise ValueError("route is required when the destination is free text (D-039)")
        return self


# --------------------------------------------------------------------------
# Responses
# --------------------------------------------------------------------------

class DestinationOut(BaseModel):
    """Short form of a destinations row: inside a service record, and the
    items of GET /destinations (the form's destination picker).

    name_mn (Mongolian label, D-040) is added after migration 002.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    route_category: Route


class ServiceOut(BaseModel):
    """One service record as shown on the vehicle card / history."""

    model_config = ConfigDict(from_attributes=True)  # build directly from an ORM object

    id: int
    vehicle_id: int
    service_date: date
    odometer_km: int | None
    engine_hours: float | None  # float, so JSON gets a number (Decimal would become a string)
    oil_grade: str
    liters: float
    route: Route | None
    destination: DestinationOut | None
    destination_raw: str | None
    driver_name: str | None
    driver_phone: str | None
    oil_changer: str | None
    photo_ref: str | None
    created_at: datetime


class ServiceCreated(BaseModel):
    """Response of POST /services (201)."""

    service: ServiceOut
    vehicle_id: int
    vehicle_created: bool
    company_created: bool


class CompanyOut(BaseModel):
    """Owner of a vehicle."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


# --------------------------------------------------------------------------
# Prediction (task 4.3)
# --------------------------------------------------------------------------

PredictionMethod = Literal["ridge", "b1", "b0"]
Status = Literal["ok", "due_soon", "overdue"]


class PredictionOut(BaseModel):
    """GET /vehicles/{id}/prediction and VehicleCard.prediction: next oil change after the LAST service."""

    vehicle_id: int
    method: PredictionMethod = Field(
        description="ridge = ML model; b1 = route formula (first visit, D-035); "
                    "b0 = fixed interval (route not MN–China/MN–Russia, destination typed by hand, D-047)"
    )
    fallback_reason: Literal["first_visit", "destination_raw_only", "route_not_modelled", "unknown_destination"] | None
    model_version: str = Field(description="Serving model file, e.g. ridge-1a2b3c4d (first 8 hex of its SHA-256)")
    based_on_service_id: int
    last_service_date: date
    predicted_days: float = Field(description="Days from the last service to the next oil change")
    predicted_date: date = Field(description="last_service_date + round(predicted_days)")
    today: date = Field(description="Ulaanbaatar date used for days_left")
    days_left: int = Field(description="predicted_date − today; negative = overdue")
    status: Status = Field(description="D-007: ok > 14 days left, due_soon 0–14, overdue < 0")


# --------------------------------------------------------------------------
# POST /plates/recognize (task 4.3)
# --------------------------------------------------------------------------

class DetectionOut(BaseModel):
    """Best plate box in pixels of the upright (EXIF-rotated) photo."""

    box: tuple[float, float, float, float] = Field(description="x1, y1, x2, y2")
    confidence: float


class PlateRecognitionOut(BaseModel):
    """What the photo says; the oil changer confirms or types it when needs_manual is true."""

    plate_raw: str = Field(description="Recognizer text before normalization ('' if nothing read)")
    plate_normalized: str | None = Field(description="normalize_plate(plate_raw); null if nothing read")
    confidence: float = Field(description="Recognizer confidence 0–1 (product of the 7 character probabilities)")
    needs_manual: bool
    reason: Literal["no_plate", "empty", "invalid_format", "low_confidence"] | None = Field(
        description="no_plate = detector found no plate; empty = 7 characters not found; "
                    "invalid_format / low_confidence = D-044 rules"
    )
    detection: DetectionOut | None
    detector: str
    recognizer: str
    ms: float = Field(description="Server time for detect + read, milliseconds")


class VehicleCard(BaseModel):
    """GET /vehicles/{id}: everything the lookup screen shows about one truck."""

    id: int
    identifier_type: Literal["plate", "fleet_no"]
    identifier: str
    plate_normalized: str | None
    vehicle_model: str | None
    company: CompanyOut
    service_count: int
    segment: Segment | None = Field(description="Today's segment (vehicle_segments); None only without services")
    usual_liters: float | None = Field(description="Most frequent liters over all services; tie -> most recent")
    last_service: ServiceOut | None = Field(description="Pre-fills the recording form")
    history: list[ServiceOut] = Field(description="All services, newest first")
    prediction: PredictionOut | None = Field(
        default=None, description="Next oil change (task 4.3); null if the vehicle has no service or the model is not loaded"
    )


class LookupResult(BaseModel):
    """GET /vehicles/lookup: all vehicles matching a plate, fleet number or phone."""

    query: str
    match_type: Literal["plate", "fleet_no", "phone"] = Field(
        description="fleet_no only if every match is a fleet number; no match -> plate"
    )
    normalized: str = Field(
        description="What was searched: normalized plate, fleet-number key (lower case) or 8-digit phone"
    )
    vehicles: list[VehicleCard] = Field(description="Empty list = unknown -> new vehicle form")


class SegmentCounts(BaseModel):
    """Number of vehicles per segment (every segment present, 0 if none)."""

    new: int = 0
    returning: int = 0
    loyal: int = 0
    at_risk: int = 0


class SegmentStats(BaseModel):
    """GET /stats/segments."""

    as_of: date
    total: int
    counts: SegmentCounts
