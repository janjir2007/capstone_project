"""One Messenger webhook event -> database changes + the bot's replies (task 9.15a, plan §4).

Called by src/api/routers/messenger.py AFTER the signature check, once per event, in its own
transaction. Returns (result, replies): ``result`` is a short word for the log (never a PSID or
text), ``replies`` are sent after the 200 (BackgroundTask).

Steps (PM decisions P1-P3 in the plan):
- m.me link tap (referral, or Get Started postback with a referral) -> PSID linked to the ref's
  truck + greeting.
- «plate + km» message -> which truck (P1), the reading checks WITHOUT saving, then a pending row
  (parsed plate + km, no text) and «Зөв үү?» with «Тийм» / «Үгүй».
- «Тийм» within 24 h of the message (P3) -> saved through store_reading (source 'messenger'; the
  reading date is the day of the ORIGINAL message) -> thanks with the km/day and next change.
  Mismatch -> flagged 'plate_mismatch' (never used for the pace).
- anything else -> no reply: a person answers it in the Page inbox.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.api.clock import ULAANBAATAR
from src.api.config import Contact, MessengerSettings, ReminderRules
from src.api.history import service_records
from src.api.messenger import texts
from src.api.messenger.parse import KmMessage, is_no, is_yes, parse_km_message
from src.api.messenger.send import Outgoing, otn_request_to, otn_vehicle, text_to, yes_no_to
from src.api.models import MessengerLink, MessengerOtn, MessengerPending, MessengerRef, MessengerSeen, Vehicle
from src.api.routers.readings import new_reading, store_reading
from src.api.schemas import ReadingIn

PENDING_HOURS = 24      # P3: «Тийм» counts within 24 h of the km message
OTN_VALID_DAYS = 360    # Meta: an OTN token "expires within 1 year of creation"; a little less, to be safe
MISMATCH = "plate_mismatch"

Result = tuple[str, list[Outgoing]]


def event_time(event: dict[str, Any]) -> datetime:
    """The event's own time (Meta's ``timestamp``, milliseconds since 1970, UTC)."""
    stamp = event.get("timestamp")
    if isinstance(stamp, int) and stamp > 0:
        return datetime.fromtimestamp(stamp / 1000, tz=timezone.utc)
    return datetime.now(timezone.utc)


def event_key(event: dict[str, Any]) -> str:
    """Id for the duplicate check: the message id, else a hash (no PSID stored in clear)."""
    for kind in ("message", "postback"):
        mid = (event.get(kind) or {}).get("mid")
        if isinstance(mid, str) and mid:
            return mid
    raw = repr((sorted(k for k in event if k not in ("sender", "recipient")), event.get("sender"),
                event.get("timestamp"), event.get("referral"), event.get("optin")))
    return "evt:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def first_time_seen(session: Session, key: str) -> bool:
    """Store the key; False when it was already there (Meta sent the event again)."""
    stored = session.execute(pg_insert(MessengerSeen).values(mid=key).on_conflict_do_nothing()
                             .returning(MessengerSeen.mid)).first()
    return stored is not None


# ---------------------------------------------------------------- which truck


def ref_truck(session: Session, psid: str) -> int | None:
    """The PSID's newest 'ref' link whose service is still that truck's latest service."""
    links = session.scalars(select(MessengerLink).where(MessengerLink.psid == psid, MessengerLink.linked_via == "ref")
                            .order_by(MessengerLink.linked_at.desc())).all()
    for link in links:
        records = service_records(session, link.vehicle_id)
        if records and records[0].id == link.service_id:
            return link.vehicle_id
    return None


def which_truck(session: Session, psid: str, plate: str) -> tuple[int, bool] | None:
    """(vehicle_id, mismatch) by P1, or None (typed plate unknown and no ref truck)."""
    typed = session.scalar(select(Vehicle.id).where(Vehicle.plate_normalized == plate))
    ref = ref_truck(session, psid)
    if typed is not None:
        return typed, ref is not None and ref != typed
    if ref is not None:
        return ref, True
    return None


def link_plate(session: Session, psid: str, vehicle_id: int) -> None:
    """Link the PSID to the truck it confirmed a reading for (kept as it is when already linked)."""
    if session.get(MessengerLink, (psid, vehicle_id)) is None:
        session.add(MessengerLink(psid=psid, vehicle_id=vehicle_id, linked_via="plate"))


def link_ref(session: Session, psid: str, code: str | None, when: datetime) -> bool:
    """Link the PSID to the truck + service of a tapped m.me link. False for an unknown code."""
    ref = session.get(MessengerRef, code.strip().upper()) if isinstance(code, str) and code.strip() else None
    if ref is None:
        return False
    link = session.get(MessengerLink, (psid, ref.vehicle_id))
    if link is None:
        session.add(MessengerLink(psid=psid, vehicle_id=ref.vehicle_id, linked_via="ref", service_id=ref.service_id,
                                  linked_at=when))
    else:
        link.linked_via, link.service_id, link.linked_at = "ref", ref.service_id, when
    return True


# ---------------------------------------------------------------- steps


def on_km_message(session: Session, psid: str, km: KmMessage, when: datetime, today: date,
                  contact: Contact) -> Result:
    """Check the reading WITHOUT saving, keep plate + km, ask «Зөв үү?»."""
    truck = which_truck(session, psid, km.plate)
    if truck is None:  # 9.15a-3: ask to check the plate, or call the oil changer
        return "unknown_truck", [text_to(psid, texts.unknown_truck(contact.phone))]
    day = when.astimezone(ULAANBAATAR).date()
    try:
        new_reading(session, truck[0], ReadingIn(value=km.km, reading_date=day), today, "messenger")
    except HTTPException:  # no service yet, the service's own day, ...: a person looks at it
        return "refused", [text_to(psid, texts.STAFF_WILL_CHECK)]
    old = session.get(MessengerPending, psid)
    if old is not None:  # a new km message replaces the open question
        session.delete(old)
        session.flush()
    session.add(MessengerPending(psid=psid, plate=km.plate, value=km.km, reading_date=day,
                                 expires_at=when + timedelta(hours=PENDING_HOURS)))
    return "asked", [yes_no_to(psid, texts.confirm_question(km.plate, km.km))]


def has_open_token(session: Session, psid: str, vehicle_id: int, now: datetime) -> bool:
    return session.scalar(select(MessengerOtn.id).where(
        MessengerOtn.psid == psid, MessengerOtn.vehicle_id == vehicle_id, MessengerOtn.used_at.is_(None),
        MessengerOtn.expires_at > now).limit(1)) is not None


def on_answer(session: Session, psid: str, yes: bool, when: datetime, today: date, rules: ReminderRules,
              settings: MessengerSettings, contact: Contact) -> Result:
    """«Тийм» / «Үгүй» to the open question."""
    pending = session.get(MessengerPending, psid)
    if pending is None:
        return "no_question", []
    plate, value, day, expires = pending.plate, pending.value, pending.reading_date, pending.expires_at
    session.delete(pending)
    if not yes:
        return "no", [text_to(psid, texts.WRITE_AGAIN)]
    if when > expires:
        return "expired", [text_to(psid, texts.WRITE_AGAIN)]
    truck = which_truck(session, psid, plate)
    if truck is None:
        return "unknown_truck", [text_to(psid, texts.unknown_truck(contact.phone))]
    vehicle_id, mismatch = truck
    try:
        saved = store_reading(session, vehicle_id, ReadingIn(value=value, reading_date=day), today, rules,
                              source="messenger", flag=MISMATCH if mismatch else None)
    except HTTPException:  # e.g. a new service was saved since the question
        return "refused", [text_to(psid, texts.STAFF_WILL_CHECK)]
    link_plate(session, psid, vehicle_id)
    reading, pace = saved.reading, saved.pace
    if reading.status == "flagged":
        return f"saved_flagged_{reading.flag_reason}", [text_to(psid, texts.FLAGGED_THANKS)]
    if reading.unit == "hours" or pace.rate_per_day is None:
        return "saved", [text_to(psid, texts.HOURS_THANKS)]
    target = service_records(session, vehicle_id)[0].target_km
    replies = [text_to(psid, texts.usable_thanks(plate, pace.rate_per_day, pace.next_due_date, target))]
    if settings.otn_enabled and not has_open_token(session, psid, vehicle_id, when):
        replies.append(otn_request_to(psid, vehicle_id))
    return "saved", replies


def on_optin(session: Session, psid: str, optin: dict[str, Any], when: datetime) -> Result:
    """OTN permission given (UNVERIFIED event shape, src/api/messenger/send.py): keep its token."""
    token = optin.get("one_time_notif_token")
    vehicle_id = otn_vehicle(optin.get("payload"))
    if optin.get("type") != "one_time_notif_req" or not isinstance(token, str) or not token or vehicle_id is None:
        return "optin_ignored", []
    if session.get(MessengerLink, (psid, vehicle_id)) is None:  # only for a truck this PSID is linked to
        return "optin_ignored", []
    if session.scalar(select(MessengerOtn.id).where(MessengerOtn.token == token)) is None:
        session.add(MessengerOtn(psid=psid, vehicle_id=vehicle_id, token=token,
                                 expires_at=when + timedelta(days=OTN_VALID_DAYS)))
    return "optin_saved", []


def handle_event(session: Session, event: dict[str, Any], settings: MessengerSettings, rules: ReminderRules,
                 today: date, contact: Contact) -> Result:
    """Route one ``entry[].messaging[]`` event. ``contact`` = the oil changer's phone (unknown-truck reply)."""
    psid = (event.get("sender") or {}).get("id")
    if not isinstance(psid, str) or not psid.isdigit():
        return "no_sender", []
    when = event_time(event)
    if not first_time_seen(session, event_key(event)):
        return "duplicate", []
    if "message" in event:
        message = event.get("message") or {}
        if message.get("is_echo"):  # our own reply, echoed back
            return "echo", []
        payload = (message.get("quick_reply") or {}).get("payload")
        text = message.get("text") if isinstance(message.get("text"), str) else None
        if payload == texts.YES_PAYLOAD or (payload is None and is_yes(text)):
            return on_answer(session, psid, True, when, today, rules, settings, contact)
        if payload == texts.NO_PAYLOAD or (payload is None and is_no(text)):
            return on_answer(session, psid, False, when, today, rules, settings, contact)
        km = parse_km_message(text)
        if km is None:
            return "not_km", []  # a person answers it in the Page inbox
        return on_km_message(session, psid, km, when, today, contact)
    if "postback" in event:  # Get Started (texts.GET_STARTED_PAYLOAD, a new thread); the ref comes inside it
        referral = (event.get("postback") or {}).get("referral") or {}
        linked = link_ref(session, psid, referral.get("ref"), when)
        return ("linked" if linked else "greeted"), [text_to(psid, texts.GREETING)]
    if "referral" in event:  # m.me link tapped in an existing thread
        linked = link_ref(session, psid, (event.get("referral") or {}).get("ref"), when)
        return ("linked" if linked else "greeted"), [text_to(psid, texts.GREETING)]
    if "optin" in event and settings.otn_enabled:
        return on_optin(session, psid, event.get("optin") or {}, when)
    return "ignored", []
