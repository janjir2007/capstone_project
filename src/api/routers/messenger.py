"""Messenger km bot endpoints (task 9.15a-2, plan §5).

GET  /messenger/webhook                Meta's set-up check (hub.mode, hub.verify_token, hub.challenge)
POST /messenger/webhook                Meta's events, signed with the App Secret
POST /reminders/{service_id}/messenger the reminder via a One-Time Notification token (P2; internal)

/messenger/webhook is the ONLY API path Caddy makes public without the login (D-118 exception, PM).
So the POST checks X-Hub-Signature-256 = "sha256=" + HMAC-SHA256(META_APP_SECRET, raw body) FIRST:
missing / wrong -> 403 and nothing is read. Then MESSENGER_ENABLED=false -> 200 and nothing else
(safe to deploy before Meta is ready). The GET works even when disabled, so the webhook can be set
up first. Replies go out after the 200 (BackgroundTask): Meta wants the 200 within a few seconds.
Logs: event type + result only (src/api/messenger/logs.py).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from src.api.clock import get_today
from src.api.config import Contact, MessengerSettings, ReminderRules
from src.api.db import get_session
from src.api.history import driver_readings, schedule_of, service_records
from src.api.messenger.flow import handle_event
from src.api.messenger.send import Outgoing, Sender, SendError, otn_send
from src.api.models import MessengerOtn, ReminderSent, ServiceRecord, Vehicle
from src.api.reminders import STAGE
from src.api.routers.reminders import (ContactDep, MessengerDep, NowDep, RulesDep, _already, _existing, stopped_phones,
                                       text_for)
from src.api.schemas import ReminderSentOut

router = APIRouter(tags=["messenger"])
log = logging.getLogger("src.api.messenger")

MAX_BODY_BYTES = 64 * 1024  # same as Caddy's request_body limit for this path
SIGNATURE_PREFIX = "sha256="

SessionDep = Annotated[Session, Depends(get_session)]
TodayDep = Annotated[date, Depends(get_today)]


def get_sender(request: Request) -> Sender | None:
    """FastAPI dependency: the Send API client made at startup (None while disabled; a fake in tests)."""
    return getattr(request.app.state, "messenger_sender", None)


SenderDep = Annotated[Sender | None, Depends(get_sender)]


def signature_ok(app_secret: str, body: bytes, header: str | None) -> bool:
    """True when ``header`` is Meta's HMAC-SHA256 of the raw body. Constant-time compare."""
    if not app_secret or not header or not header.startswith(SIGNATURE_PREFIX):
        return False
    expected = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[len(SIGNATURE_PREFIX):].strip().lower())


@router.get("/messenger/webhook", response_class=PlainTextResponse)
def verify_webhook(request: Request, messenger: MessengerDep) -> PlainTextResponse:
    """Meta's set-up check: the right token -> 200 + hub.challenge as text; anything else -> 403."""
    params = request.query_params
    token = params.get("hub.verify_token") or ""
    if (not messenger.verify_token or params.get("hub.mode") != "subscribe"
            or not hmac.compare_digest(token.encode("utf-8"), messenger.verify_token.encode("utf-8"))):
        log.warning("messenger verify: refused")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    log.info("messenger verify: ok")
    return PlainTextResponse(params.get("hub.challenge") or "")


def deliver(sender: Sender | None, out: Outgoing) -> None:
    """Send one reply (runs after the 200). A failure is logged with its class only."""
    if sender is None:
        return
    try:
        sender.send(out)
    except SendError as exc:
        log.warning("messenger reply not sent: %s", exc)
    except Exception as exc:  # noqa: BLE001 — never let one reply break the others
        log.warning("messenger reply not sent: %s", type(exc).__name__)


def process(session: Session, payload: dict[str, Any], messenger: MessengerSettings, rules: ReminderRules,
            today: date, contact: Contact) -> list[Outgoing]:
    """Every event of a (signed) delivery, each in its own transaction. Returns the replies."""
    replies: list[Outgoing] = []
    for entry in payload.get("entry") or []:
        if str(entry.get("id")) != messenger.page_id:
            log.warning("messenger entry for another page ignored")
            continue
        for event in entry.get("messaging") or []:
            try:
                result, out = handle_event(session, event, messenger, rules, today, contact)
                session.commit()
            except Exception as exc:  # noqa: BLE001 — class only: a database error could hold a PSID
                session.rollback()
                log.warning("messenger event failed: %s", type(exc).__name__)
                continue
            log.info("messenger event: %s", result)
            replies.extend(out)
    return replies


@router.post("/messenger/webhook", response_class=PlainTextResponse)
async def receive_webhook(request: Request, background: BackgroundTasks, session: SessionDep,
                          messenger: MessengerDep, rules: RulesDep, today: TodayDep, contact: ContactDep,
                          sender: SenderDep) -> PlainTextResponse:
    """Meta's events. 413 body > 64 KB · 403 bad signature · 200 otherwise (also when disabled)."""
    length = request.headers.get("content-length")
    if length is not None and length.isdigit() and int(length) > MAX_BODY_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "body too large")
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "body too large")
    if not signature_ok(messenger.app_secret, body, request.headers.get("x-hub-signature-256")):
        log.warning("messenger event: bad signature")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    if not messenger.enabled:
        return PlainTextResponse("EVENT_RECEIVED")
    try:
        payload = json.loads(body)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "not JSON") from None
    if not isinstance(payload, dict) or payload.get("object") != "page":
        return PlainTextResponse("EVENT_RECEIVED")
    replies = await run_in_threadpool(process, session, payload, messenger, rules, today, contact)
    for out in replies:
        background.add_task(deliver, sender, out)
    return PlainTextResponse("EVENT_RECEIVED")


# ---------------------------------------------------------------- P2: reminder via One-Time Notification


@router.post("/reminders/{service_id}/messenger", response_model=ReminderSentOut, status_code=status.HTTP_201_CREATED,
             responses={200: {"description": "Already marked sent (any channel): that row, nothing sent"},
                        502: {"description": "{code: meta_error}: Meta refused; nothing stored, token not used"}})
def send_reminder_by_messenger(service_id: int, response: Response, session: SessionDep, today: TodayDep,
                               now: NowDep, contact: ContactDep, rules: RulesDep, messenger: MessengerDep,
                               sender: SenderDep) -> ReminderSentOut:
    """Send the reminder text with the truck's One-Time Notification token (only when the oil changer
    taps the button, P2) and store it as sent (channel 'messenger').

    404 unknown service · 409 a newer service exists · 422 OTN off, not due, no odometer, phone
    stopped, or no unused token · 502 Meta refused (no row stored, the token stays unused).
    """
    existing = _existing(session, service_id)
    if existing is not None:
        return _already(response, existing)
    service = session.get(ServiceRecord, service_id)
    if service is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"service {service_id} not found")
    records = service_records(session, service.vehicle_id)  # newest first
    if records[0].id != service_id:
        raise HTTPException(status.HTTP_409_CONFLICT, {
            "code": "not_latest_service", "message": "the truck has a newer service; reload the due list",
            "latest_service_id": records[0].id})
    if not messenger.otn_enabled or sender is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Messenger reminders are off (MESSENGER_OTN_ENABLED)")
    if service.odometer_km is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "no reminders for a truck without odometer")
    plan = schedule_of(list(reversed(records)), driver_readings(session, [service.vehicle_id], today).get(
        service.vehicle_id, []), rules)
    if plan.reminder_on > today:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "the reminder is not due yet")
    if service.driver_phone and service.driver_phone in stopped_phones(session):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "this phone asked for no more messages")
    token = session.scalar(select(MessengerOtn).where(
        MessengerOtn.vehicle_id == service.vehicle_id, MessengerOtn.used_at.is_(None), MessengerOtn.expires_at > now)
        .order_by(MessengerOtn.created_at.desc(), MessengerOtn.id.desc()).limit(1).with_for_update())
    if token is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "no Messenger permission for this truck")
    vehicle = session.get(Vehicle, service.vehicle_id)
    text = text_for(vehicle, service, contact)
    try:
        sender.send(otn_send(token.token, text))
    except SendError:
        session.rollback()  # token untouched
        log.warning("messenger reminder not sent: meta_error")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, {
            "code": "meta_error", "message": "Messenger did not take the message; send it by SMS"}) from None
    token.used_at = now
    row = ReminderSent(vehicle_id=service.vehicle_id, service_id=service_id, stage=STAGE, channel="messenger",
                       phone=None, message_text=text, send_on=plan.reminder_on)
    session.add(row)
    try:
        session.commit()
    except IntegrityError:  # marked sent at the same moment by another request
        session.rollback()
        return _already(response, _existing(session, service_id))
    session.refresh(row)
    log.info("messenger reminder: sent")
    return ReminderSentOut.model_validate(row)

