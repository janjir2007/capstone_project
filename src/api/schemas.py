"""Request and response shapes of the data endpoints (task 4.2, contract §8 v0.1).

Pydantic checks every request BEFORE any database work: a bad request gets a
422 with a clear message instead of a database error. Field names follow
docs/data_dictionary.md.

Rules enforced here:
- at least one meter: odometer_km or engine_hours (like the DB CHECK)
- destination: at most one of destination_id / destination_raw (9.5a: optional, was exactly one, D-033)
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
# Task 9.6b-4: Artlab payment of a service (labels: Төлсөн / Төлөөгүй / Төлсөн (дараа) / Тодорхойгүй).
PaymentStatus = Literal["paid", "unpaid", "paid_later", "unknown"]
MatchConfidence = Literal["both", "plate", "phone"]

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

    # Destination + route (D-033, D-039). Optional since 9.5a: the form no longer asks for it;
    # old records keep theirs and the API still accepts one (at most one of id / raw).
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
        if self.destination_id is not None and self.destination_raw is not None:
            raise ValueError("give at most one of destination_id or destination_raw")
        if self.destination_raw is not None and self.route is None:
            raise ValueError("route is required when the destination is free text (D-039)")
        return self


# --------------------------------------------------------------------------
# Responses
# --------------------------------------------------------------------------

class DestinationOut(BaseModel):
    """Short form of a destinations row: inside a service record, and the
    items of GET /destinations (the form's destination picker).

    name_mn: Mongolian label for the UI (D-040, migration 002); null = no
    label yet, show ``name``. ``name`` stays the key (model route table).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    name_mn: str | None
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
    # Task 9.6b-4 (filled by the API from artlab_bills, not stored on the service). All null while
    # payments are not connected (no successful Artlab sync yet).
    payment_status: PaymentStatus | None = Field(
        None, description="paid «Төлсөн» · unpaid «Төлөөгүй» · paid_later «Төлсөн (дараа)» · "
                          "unknown «Тодорхойгүй» (no Artlab receipt linked); null = payments not connected")
    amount_due: float | None = Field(None, description="Credit still owed (MNT); only when payment_status = unpaid")
    match_confidence: MatchConfidence | None = Field(
        None, description="How the receipt was linked: plate + phone, plate only, phone only (weakest of its receipts)")
    # Task 9.14a (migration 010): STORED when the service is saved (was computed when shown, 9.5a).
    interval_km: int | None = Field(None, description="OIL_INTERVAL_KM in force when the service was saved "
                                                      "(15000 for services saved before 9.14a); null for mine trucks")
    target_km: int | None = Field(None, description="Odometer of the next oil change = odometer_km + interval_km; "
                                                    "null without odometer_km (mine trucks: engine hours only)")


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
    range_low_date: date | None = Field(
        default=None, description="Task 2.9: early end of the 80% range (10th percentile of validation errors); "
                                  "null if the model files have no ranges")
    range_high_date: date | None = Field(default=None, description="Task 2.9: late end of the 80% range (90th percentile)")


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


# --------------------------------------------------------------------------
# Task 9.14a: meter readings + the truck's pace (km/day)
# --------------------------------------------------------------------------

MeterUnit = Literal["km", "hours"]
ReadingSource = Literal["service", "manual", "messenger"]
ReadingFlag = Literal["not_higher", "too_slow", "too_fast"]


class ReadingOut(BaseModel):
    """One meter reading (odometer_readings)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    vehicle_id: int
    service_id: int = Field(description="The service it counts from (source 'service': that service)")
    unit: MeterUnit
    value: float
    reading_date: date
    source: ReadingSource = Field(description="service = the service's own meter · manual = the driver's reply, "
                                              "typed in · messenger = later")
    status: Literal["ok", "flagged"] = Field(description="flagged = never used for the pace")
    flag_reason: ReadingFlag | None = Field(description="not_higher · too_slow (< 20 km/day) · too_fast "
                                                        "(> 1200 km/day, > 24 h/day, or higher on the same day)")
    rate_per_day: float | None = Field(description="Units/day from the reading it was checked against")
    created_at: datetime


class PaceOut(BaseModel):
    """The truck's pace and the dates of its latest service (src/api/pace.py)."""

    unit: MeterUnit
    rate_per_day: float | None = Field(description="km (or engine hours) per day; null = not known")
    source: Literal["reading", "services"] | None = Field(
        description="reading = the driver's reading after the latest service · services = previous -> latest "
                    "service · null = no usable pace")
    reading_value: float | None = Field(description="The driver reading used (source = reading)")
    reading_date: date | None
    interval_km: int | None = Field(description="Interval stored on the latest service")
    next_due_date: date | None = Field(description="Latest service + floor(interval_km / rate_per_day); km trucks "
                                                   "with a pace only")
    reminder_on: date | None = Field(description="The reminder day; null for mine trucks (no reminders)")
    basis: Literal["pace", "fixed"] | None = Field(
        description="pace = from km/day (due - REMINDER_LEAD_DAYS, at most AT_RISK_DAYS - REMINDER_LEAD_DAYS after "
                    "the service) · fixed = REMINDER_DAYS after the service · null for mine trucks")
    km_check_on: date | None = Field(description="Day to ask the driver for his km (KM_CHECK_DAYS after the "
                                                 "service); km trucks without a pace only")


class ReadingIn(BaseModel):
    """POST /vehicles/{id}/readings: the driver's current km (or engine hours), typed in."""

    model_config = ConfigDict(extra="forbid")

    value: Decimal = Field(gt=0, max_digits=9, decimal_places=1, description="Odometer km (mine trucks: engine hours)")
    reading_date: date | None = Field(default=None, description="Default: today (Ulaanbaatar). After the latest "
                                                                "service, not in the future")


class ReadingPreview(BaseModel):
    """POST /vehicles/{id}/readings/preview (9.14a-3): the reading as it WOULD be stored + the pace after it."""

    unit: MeterUnit
    value: float
    reading_date: date
    status: Literal["ok", "flagged"]
    flag_reason: ReadingFlag | None
    rate_per_day: float | None
    pace: PaceOut


class ReadingSaved(BaseModel):
    """POST /vehicles/{id}/readings answer: the stored reading and the truck's pace after it."""

    reading: ReadingOut
    pace: PaceOut


class VehicleCard(BaseModel):
    """GET /vehicles/{id}: everything the lookup screen shows about one truck."""

    id: int
    identifier_type: Literal["plate", "fleet_no"]
    identifier: str
    plate_normalized: str | None
    vehicle_model: str | None
    company: CompanyOut
    service_count: int
    segment: Segment | None = Field(description="Today's segment (9.5c: at_risk = AT_RISK_DAYS (150)+ days since "
                                                "the latest service); None only without services")
    usual_liters: float | None = Field(description="Most frequent liters over all services; tie -> most recent")
    last_service: ServiceOut | None = Field(description="Pre-fills the recording form")
    history: list[ServiceOut] = Field(description="All services, newest first")
    prediction: PredictionOut | None = Field(
        default=None, description="Next oil change (task 4.3); null if the vehicle has no service or the model is not loaded"
    )
    pace: PaceOut | None = Field(default=None, description="Task 9.14a: km/day + next due day; null without services")
    readings: list[ReadingOut] = Field(default_factory=list, description="Task 9.14a: the 5 newest meter readings "
                                                                        "(every source), newest first")


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


SearchMatch = Literal["plate", "fleet_no", "company", "phone"]


class VehicleRow(BaseModel):
    """One truck in the dashboard search (task 9.1): a light row, not the whole card.
    The full history comes from GET /vehicles/{id} when the manager opens the truck."""

    id: int
    identifier_type: Literal["plate", "fleet_no"]
    identifier: str
    vehicle_model: str | None
    company: CompanyOut
    service_count: int
    last_service: ServiceOut | None = Field(description="Newest service (date, odometer, oil, liters, driver, phone)")
    segment: Segment | None = Field(description="Same rule as the card (9.5c: at_risk = AT_RISK_DAYS+ days since the latest service)")
    status: Status | None = Field(description="Prediction status (D-007); null when the model is not loaded")
    days_left: int | None = Field(description="Predicted date − today; null when the model is not loaded")
    matched_on: list[SearchMatch] = Field(description="Why the truck matched q; [] when q is blank (all trucks)")
    services: list[ServiceOut] | None = Field(
        default=None, description="Only with with_services=true: the truck's services that pass the date / route / "
                                  "oil filters (all services when none is used), newest first (Excel export, 9.1)")


class SearchOptions(BaseModel):
    """Choices for the dashboard filter lists, from the whole database (not only the matches)."""

    companies: list[CompanyOut] = Field(description="Every company with a truck, by name")
    oil_grades: list[str] = Field(description="Every oil grade ever recorded (one spelling per case-insensitive value)")


class VehicleSearch(BaseModel):
    """GET /vehicles/search."""

    query: str
    total: int = Field(description="All matching trucks; `vehicles` holds at most `limit` of them")
    vehicles: list[VehicleRow] = Field(description="Newest service first")
    options: SearchOptions = Field(description="Filter choices (task 9.1 step 2)")


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
    at_risk_days: int = Field(description="Task 9.12-1: AT_RISK_DAYS, the days without a service after which "
                                          "a truck is at_risk («Эргэж ирээгүй»), for the card label")


class PeriodStats(BaseModel):
    """GET /stats/period (task 9.12-1): one period's work numbers for the dashboard."""

    period: Literal["today", "week", "month"]
    date_from: date
    date_to: date
    services: int = Field(description="Service records dated in the period")
    new_vehicles: int = Field(description="Vehicles whose FIRST-EVER service is in the period")
    liters: float = Field(description="Oil liters of those services")
    reminders_sent: int = Field(description="Reminders marked sent (sent_at on a UB day in the period)")
    km_checks_sent: int = Field(description="Task 9.14a: «Км шалгах» messages marked sent (not reminders)")


# --------------------------------------------------------------------------
# Reminders (task 4.4)
# --------------------------------------------------------------------------

# 9.5c stores 'single'; '1m' / '2m' / '3m' only on rows from 9.5b (kept as history).
ReminderStage = Literal["single", "1m", "2m", "3m"]
ReminderChannel = Literal["manual", "sms"]


class DueReminder(BaseModel):
    """One truck to remind today: GET /reminders/due (task 9.5c: one reminder per service, D-119)."""

    service_id: int = Field(description="Latest service = the reminder's id: POST /reminders/{service_id}/sent")
    vehicle_id: int
    identifier_type: Literal["plate", "fleet_no"]
    identifier: str = Field(description="Plate or fleet number as confirmed, e.g. 1234 УБА")
    plate_normalized: str | None
    company: str
    phone: str | None = Field(description="driver_phone of the latest service (D-004); null = no phone recorded")
    driver_name: str | None
    last_change_date: date
    oil_grade: str
    liters: float
    odometer_km: int = Field(description="Odometer at the latest service (trucks without one get no reminders)")
    target_km: int | None = Field(description="Stored on the service (9.14a): odometer_km + interval_km")
    days_since: int = Field(description="Days from the latest service to as_of")
    send_on: date = Field(description="Reminder day (9.14a): with a pace = next_due_date - REMINDER_LEAD_DAYS (5), "
                                      "not before the day the pace became known, at most last_change_date + "
                                      "AT_RISK_DAYS - REMINDER_LEAD_DAYS; without = last_change_date + REMINDER_DAYS (75)")
    next_due_date: date | None = Field(description="9.14a: latest service + floor(interval / km per day); null "
                                                   "without a pace")
    rate_per_day: float | None = Field(description="9.14a: the truck's km per day; null = not known")
    pace_source: Literal["reading", "services"] | None = Field(description="9.14a: where the km/day comes from")
    basis: Literal["pace", "fixed"] = Field(description="9.14a: pace = send_on from km/day · fixed = REMINDER_DAYS")
    segment: Segment = Field(description="Segment on as_of; at_risk = AT_RISK_DAYS (150)+ days since the latest "
                                         "service: shown as «Эрсдэлтэй» (9.5c)")
    message_mn: str = Field(description="Mongolian reminder text (copy into Viber)")


class DueReminders(BaseModel):
    """GET /reminders/due."""

    as_of: date
    contact_is_placeholder: bool = Field(description="true = CONTACT_PHONE (or GEO_EXPERT_PHONE) is not set, "
                                                     "the message has a fake number")
    reminders: list[DueReminder] = Field(description="send_on <= as_of and not sent yet; oldest send_on first")


class ReminderSentOut(BaseModel):
    """POST /reminders/{service_id}/sent: the stored reminder."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    service_id: int
    vehicle_id: int
    stage: ReminderStage | None = Field(description="'single' (9.5c); 1m/2m/3m = a 9.5b row; null = before 9.5b")
    channel: ReminderChannel = Field(description="How it went out (migration 007): 'manual' = the manager sent it")
    phone: str | None
    message_text: str
    method: PredictionMethod | None = Field(default=None, description="Rows from before 9.5b only")
    model_version: str | None = None
    predicted_date: date | None = None
    send_on: date
    sent_at: datetime
    already_sent: bool = Field(default=False, description="true = it was marked before; nothing changed")


class StopIn(BaseModel):
    """POST /reminders/stops: a driver asked for no more messages."""

    model_config = ConfigDict(extra="forbid")

    phone: RequiredText

    @field_validator("phone")
    @classmethod
    def _phone_is_mongolian(cls, value: str) -> str:
        return normalize_phone(value)


class StopOut(BaseModel):
    """A phone that gets no reminders (task 9.5b)."""

    model_config = ConfigDict(from_attributes=True)

    phone: str
    created_at: datetime


# --------------------------------------------------------------------------
# Task 9.14a: «Км шалгах» (asks the driver for his km; not a reminder)
# --------------------------------------------------------------------------

class KmCheckDue(BaseModel):
    """One truck to ask for its km: GET /km-checks/due."""

    service_id: int = Field(description="Latest service = the check's id: POST /km-checks/{service_id}/sent")
    vehicle_id: int
    identifier_type: Literal["plate", "fleet_no"]
    identifier: str
    plate_normalized: str | None
    company: str
    phone: str | None = Field(description="driver_phone of the latest service; null = no phone recorded")
    driver_name: str | None
    last_change_date: date
    odometer_km: int
    days_since: int = Field(description="Days from the latest service to as_of")
    check_on: date = Field(description="last_change_date + KM_CHECK_DAYS (34)")
    reminder_on: date = Field(description="The reminder day if no reply comes: last_change_date + REMINDER_DAYS (75); "
                                          "the check leaves the list on that day")
    segment: Segment
    message_mn: str = Field(description="Mongolian km-check text")


class KmChecksDue(BaseModel):
    """GET /km-checks/due."""

    as_of: date
    contact_is_placeholder: bool
    checks: list[KmCheckDue] = Field(description="check_on <= as_of < reminder_on, no pace, not sent; oldest first")


class KmCheckOut(BaseModel):
    """POST /km-checks/{service_id}/sent: the stored check."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    service_id: int
    vehicle_id: int
    phone: str | None
    message_text: str
    channel: ReminderChannel
    check_on: date
    sent_at: datetime
    already_sent: bool = Field(default=False, description="true = it was marked before; nothing changed")


# ---------------------------------------------------------------- task 9.6b-4: payments (read only)


class UnpaidBillOut(BaseModel):
    """One unpaid Artlab receipt (GET /payments/unpaid)."""

    artlab_id: str = Field(description="Artlab bill id as a STRING: ids exceed 2^53 (JavaScript-safe)")
    bill_date: date
    days_waiting: int = Field(description="Days since the receipt, up to today (Ulaanbaatar)")
    amount_due: float = Field(description="Credit part still owed (MNT)")
    total_gross: float | None
    match_confidence: MatchConfidence | None
    match_note: Literal["none", "multiple", "conflict"] | None = Field(
        description="Why the receipt is not linked to a service (null when linked)")
    service_id: int | None
    vehicle_id: int | None
    identifier: str | None = Field(description="The linked truck's plate or fleet number")
    company_name: str | None
    plates: list[str] = Field(description="Plates found in the receipt text (normalized)")
    phones: list[str] = Field(description="Phones found in the receipt text (8 digits)")


class UnpaidList(BaseModel):
    """GET /payments/unpaid: oldest receipt first."""

    connected: bool = Field(description="False until the first successful Artlab sync")
    total: int
    total_due: float
    items: list[UnpaidBillOut]


class SyncRunOut(BaseModel):
    """Latest run of one sync kind, or of one acc-txn bank account."""

    kind: Literal["bills", "acc_txn", "nightly"]
    account_code: str | None = Field(description="acc_txn rows only: the bank account")
    started_at: datetime
    finished_at: datetime | None = Field(description="null = still running, or crashed")
    ok: bool | None
    bills_seen: int
    transfers_seen: int
    error_class: str | None = Field(description="Exception class of a failed run, e.g. ArtlabError")
    last_ok_at: datetime | None = Field(description="End of the latest successful run of this kind / account")
    zero_row_streak: int | None = Field(
        description="acc_txn only: finished runs in a row with 0 rows (sync warns at ARTLAB_ZERO_ROW_WARN_RUNS)")


class SyncStatusOut(BaseModel):
    """GET /payments/sync-status."""

    connected: bool
    runs: list[SyncRunOut]
