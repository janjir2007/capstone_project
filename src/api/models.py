"""SQLAlchemy ORM classes for the tables the data endpoints use (task 4.2).

These classes only MAP the existing tables to Python objects. The tables
themselves come from src/data/schema.sql + migrations (never create_all()), and
the column names follow docs/data_dictionary.md (the contract).

Not mapped: predictions, reminders (schema.sql) — predictions are computed at read
time (task 4.3), and sent reminders live in reminders_sent (migration 003, task 4.4).
Computed objects (v_vehicle_service_summary, vehicle_segments()) are not mapped; vehicle_segments() is
deprecated (task 9.5c): the API's segments come from src/api/reminders.segment_of.

server_default=func.now() / identity primary keys: the database fills these,
so SQLAlchemy leaves them out of the INSERT and reads them back.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Common base of all ORM classes."""


class Company(Base):
    """companies: the customer (fleet owner, or a private owner)."""

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Vehicle(Base):
    """vehicles: one truck, identified by plate or fleet number (D-005)."""

    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("companies.id"))
    identifier_type: Mapped[str] = mapped_column(Text)
    identifier: Mapped[str] = mapped_column(Text)
    plate_normalized: Mapped[str | None] = mapped_column(Text)
    vehicle_model: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    company: Mapped[Company] = relationship()


class Destination(Base):
    """destinations: where a truck heads after its oil change (migrations 001, 002)."""

    __tablename__ = "destinations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    route_category: Mapped[str] = mapped_column(Text)
    one_way_km: Mapped[int | None] = mapped_column(Integer)
    round_trip_days_min: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    round_trip_days_max: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    source: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    name_mn: Mapped[str | None] = mapped_column(Text)  # Mongolian label (migration 002, D-040)


class ServiceRecord(Base):
    """service_records: one oil change. Driver + phone live here (D-004)."""

    __tablename__ = "service_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("vehicles.id"))
    service_date: Mapped[date]
    odometer_km: Mapped[int | None] = mapped_column(Integer)
    engine_hours: Mapped[Decimal | None] = mapped_column(Numeric(8, 1))
    oil_grade: Mapped[str] = mapped_column(Text)
    liters: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    route: Mapped[str | None] = mapped_column(Text)
    driver_name: Mapped[str | None] = mapped_column(Text)
    driver_phone: Mapped[str | None] = mapped_column(Text)
    oil_changer: Mapped[str | None] = mapped_column(Text)
    photo_ref: Mapped[str | None] = mapped_column(Text)
    destination_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("destinations.id"))
    destination_raw: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Task 9.14a (migration 010): the interval in force when saved, and odometer_km + it. None for mine trucks.
    interval_km: Mapped[int | None] = mapped_column(Integer)
    target_km: Mapped[int | None] = mapped_column(Integer)

    vehicle: Mapped[Vehicle] = relationship()
    destination: Mapped[Destination | None] = relationship()


class ReminderSent(Base):
    """reminders_sent: a reminder that went out for one (vehicle, newest service) (migration 003).
    Task 9.5b (migration 006): one row per (service, month stage); old prediction rows have stage None.
    Task 9.5c (migration 007): new rows have stage 'single' (one per service) and a channel."""

    __tablename__ = "reminders_sent"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("vehicles.id"))
    service_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("service_records.id"))
    phone: Mapped[str | None] = mapped_column(Text)
    message_text: Mapped[str] = mapped_column(Text)
    stage: Mapped[str | None] = mapped_column(Text)  # 'single' (9.5c); '1m'/'2m'/'3m' (9.5b); None = prediction row
    channel: Mapped[str] = mapped_column(Text, server_default="manual")  # 'manual' / 'sms' (migration 007)
    method: Mapped[str | None] = mapped_column(Text)
    model_version: Mapped[str | None] = mapped_column(Text)
    predicted_date: Mapped[date | None]
    send_on: Mapped[date]
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReminderStop(Base):
    """reminder_stops (migration 006, task 9.5b): a driver phone that asked for no more messages."""

    __tablename__ = "reminder_stops"

    phone: Mapped[str] = mapped_column(Text, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OdometerReading(Base):
    """odometer_readings (migration 010, task 9.14a): one meter value of a truck on one day.
    source 'service' = a service's own odometer / engine hours; 'manual' = the driver's reply typed in."""

    __tablename__ = "odometer_readings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("vehicles.id"))
    service_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("service_records.id"))
    unit: Mapped[str] = mapped_column(Text)  # 'km' / 'hours'
    value: Mapped[Decimal] = mapped_column(Numeric(9, 1))
    reading_date: Mapped[date]
    source: Mapped[str] = mapped_column(Text)  # 'service' / 'manual' / 'messenger'
    status: Mapped[str] = mapped_column(Text)  # 'ok' / 'flagged'
    flag_reason: Mapped[str | None] = mapped_column(Text)  # 'not_higher' / 'too_slow' / 'too_fast'
    rate_per_day: Mapped[Decimal | None] = mapped_column(Numeric(9, 1))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KmCheck(Base):
    """km_checks (migration 010, task 9.14a): a «Км шалгах» message sent for one service. Not a reminder."""

    __tablename__ = "km_checks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("vehicles.id"))
    service_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("service_records.id"))
    phone: Mapped[str | None] = mapped_column(Text)
    message_text: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(Text, server_default="manual")
    check_on: Mapped[date]
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
