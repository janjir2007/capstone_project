"""Send API client (task 9.15a). Tests replace it with a fake: no network in tests.

Request (verified 2026-11-04, developers.facebook.com/documentation/business-messaging/
messenger-platform/send-messages, "Send a basic text"):
    POST https://graph.facebook.com/<META_GRAPH_VERSION>/<META_PAGE_ID>/messages?access_token=<page token>
    {"recipient": {"id": "<PSID>"}, "messaging_type": "RESPONSE", "message": {"text": "..."}}
Quick replies (verified, .../send-messages/quick-replies): message.quick_replies =
[{content_type: "text", title (<= 20 chars), payload (<= 1000 chars)}]; the tap comes back as
message.quick_reply.payload.
One-Time Notification (UNVERIFIED: Meta's OTN page answered 404 on 2026-11-04): request =
template "one_time_notif_req" {title, payload}; send = recipient {"one_time_notif_token": token}.
Only used with MESSENGER_OTN_ENABLED=true; check the format in dev mode before turning it on.

The token is in the URL (Meta's documented form), so the URL is never logged, and errors carry
only the HTTP status, never the URL or Meta's answer.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import quote, urlencode

from src.api.messenger import texts

GRAPH_HOST = "https://graph.facebook.com"
TIMEOUT_SECONDS = 10


class SendError(RuntimeError):
    """Meta refused the message or could not be reached. The message holds no token or PSID."""


@dataclass(frozen=True)
class Outgoing:
    """One Send API call."""

    recipient: dict[str, str]
    message: dict[str, Any]
    messaging_type: str | None = "RESPONSE"

    def body(self) -> dict[str, Any]:
        out: dict[str, Any] = {"recipient": self.recipient, "message": self.message}
        if self.messaging_type is not None:
            out["messaging_type"] = self.messaging_type
        return out


class Sender(Protocol):
    """Anything that can deliver an Outgoing (the Graph client, or a fake in tests)."""

    def send(self, out: Outgoing) -> None: ...


@dataclass
class GraphSender:
    """The real Send API client (standard library only, no new package)."""

    page_id: str
    page_token: str = field(repr=False)  # repr=False: never printed with the object
    graph_version: str

    def url(self) -> str:
        return (f"{GRAPH_HOST}/{quote(self.graph_version, safe='.')}/{quote(self.page_id, safe='')}/messages?"
                + urlencode({"access_token": self.page_token}))

    def send(self, out: Outgoing) -> None:
        request = urllib.request.Request(self.url(), data=json.dumps(out.body()).encode("utf-8"),
                                         headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 (fixed https host)
                response.read()
        except urllib.error.HTTPError as exc:
            raise SendError(f"meta_error: HTTP {exc.code}") from None
        except (urllib.error.URLError, OSError) as exc:
            raise SendError(f"meta_error: {type(exc).__name__}") from None


def text_to(psid: str, text: str) -> Outgoing:
    return Outgoing({"id": psid}, {"text": text})


def yes_no_to(psid: str, text: str) -> Outgoing:
    """The question with «Тийм» / «Үгүй» quick replies."""
    return Outgoing({"id": psid}, {"text": text, "quick_replies": [
        {"content_type": "text", "title": texts.YES, "payload": texts.YES_PAYLOAD},
        {"content_type": "text", "title": texts.NO, "payload": texts.NO_PAYLOAD}]})


def otn_request_to(psid: str, vehicle_id: int) -> Outgoing:
    """Ask for a One-Time Notification permission for this truck (UNVERIFIED format, see the docstring)."""
    return Outgoing({"id": psid}, {"attachment": {"type": "template", "payload": {
        "template_type": "one_time_notif_req", "title": texts.OTN_TITLE, "payload": otn_payload(vehicle_id)}}})


def otn_send(token: str, text: str) -> Outgoing:
    """The reminder sent with an OTN token (the token, not a PSID, names the person)."""
    return Outgoing({"one_time_notif_token": token}, {"text": text}, messaging_type=None)


OTN_PAYLOAD_PREFIX = "otn:"


def otn_payload(vehicle_id: int) -> str:
    return f"{OTN_PAYLOAD_PREFIX}{vehicle_id}"


def otn_vehicle(payload: str | None) -> int | None:
    """The truck id in an OTN payload we sent, or None."""
    if not payload or not payload.startswith(OTN_PAYLOAD_PREFIX):
        return None
    tail = payload[len(OTN_PAYLOAD_PREFIX):]
    return int(tail) if tail.isdigit() else None
