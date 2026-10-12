"""SQLAlchemy ORM classes for the tables the data endpoints use (task 4.2).

These classes only MAP the existing tables to Python objects. The tables
themselves come from src/data/schema.sql + migrations (never create_all()), and
the column names follow docs/data_dictionary.md (the contract).

Not mapped: predictions, reminders (schema.sql) — predictions are computed at read
time (task 4.3), and sent reminders live in reminders_sent (migration 003, task 4.4).
Computed objects (v_vehicle_service_summary, vehicle_segments()) are queried with SQL directly.

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
    """destinations: where a truck heads after its oil change (migration 001)."""

    __tablename__ = "destinations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    route_category: Mapped[str] = mapped_column(Text)
    one_way_km: Mapped[int | None] = mapped_column(Integer)
    round_trip_days_min: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    round_trip_days_max: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    source: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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

    vehicle: Mapped[Vehicle] = relationship()
    destination: Mapped[Destination | None] = relationship()


class ReminderSent(Base):
    """reminders_sent: a reminder that went out for one (vehicle, newest service) (migration 003)."""

    __tablename__ = "reminders_sent"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("vehicles.id"))
    service_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("service_records.id"))
    phone: Mapped[str | None] = mapped_column(Text)
    message_text: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(Text)
    model_version: Mapped[str] = mapped_column(Text)
    predicted_date: Mapped[date]
    send_on: Mapped[date]
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
