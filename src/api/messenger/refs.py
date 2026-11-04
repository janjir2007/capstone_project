"""The m.me link code of one service (task 9.15a, D-131): messenger_refs.

One random 8-character code per service with an odometer, made when the service is saved. 8 characters
keep the km-check SMS at 2 parts (plan §7); 34 symbols ** 8 ~ 1.8e12 codes, so a code cannot be
guessed and a clash is practically impossible (the PRIMARY KEY would refuse one anyway).
"""

from __future__ import annotations

import secrets

from sqlalchemy.orm import Session

from src.api.models import MessengerRef, ServiceRecord

REF_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ23456789"  # A-Z 2-9 (same set as the migration 011 backfill)
REF_LENGTH = 8


def new_ref_code() -> str:
    """A fresh random code from a cryptographic source (``secrets``, not ``random``)."""
    return "".join(secrets.choice(REF_ALPHABET) for _ in range(REF_LENGTH))


def add_ref(session: Session, record: ServiceRecord) -> MessengerRef | None:
    """Add the ref row of a just-flushed service (it needs the service id). None for mine trucks."""
    if record.odometer_km is None:
        return None
    ref = MessengerRef(ref=new_ref_code(), service_id=record.id, vehicle_id=record.vehicle_id)
    session.add(ref)
    return ref
