"""Task 9.15a-2: Messenger km bot backend — parser, signature, webhook flow, OTN, logs, cleanup.

No network: the Send API client is replaced by FakeSender (records the calls) and urlopen is mocked.
Secrets, PSIDs and plates here are made up; the secrets are low-entropy on purpose (gitleaks).
Database tests use Postgres + the synthetic sample data (tests/test_reminders.py client, today =
2026-10-12) and are SKIPPED without a database.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import logging
import urllib.error
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.api.clock import ULAANBAATAR, get_now
from src.api.config import ConfigError, MessengerSettings, messenger_settings
from src.api.main import create_app
from src.api.messenger import send as S
from src.api.messenger import texts
from src.api.messenger.cleanup import cleanup
from src.api.messenger.logs import HideWebhookQuery
from src.api.messenger.parse import KmMessage, is_no, is_yes, parse_km_message
from src.api.messenger.refs import REF_ALPHABET, new_ref_code
from src.api.routers.messenger import get_sender, signature_ok
from src.api.routers.reminders import get_messenger_settings
from tests.test_api_data import pg  # noqa: F401  (fixture)
from tests.test_reminders import client, default_rules, new_service  # noqa: F401  (fixtures + helper)
from tests.test_serving import model_dir  # noqa: F401  (fixture)

SECRET, VERIFY, PAGE_TOKEN = "s" * 24, "v" * 24, "p" * 24
PAGE_ID, VERSION = "100000000000001", "v26.0"
PSID, OTHER_PSID = "7000000000000001", "7000000000000002"
ON = MessengerSettings(enabled=True, otn_enabled=False, app_secret=SECRET, verify_token=VERIFY, page_token=PAGE_TOKEN,
                       page_id=PAGE_ID, graph_version=VERSION)
ON_OTN = MessengerSettings(**{**ON.__dict__, "otn_enabled": True})
OFF = MessengerSettings(**{**ON.__dict__, "enabled": False})


def at(day: int, hour: int, minute: int = 0) -> datetime:
    """A moment in October 2026, Ulaanbaatar time."""
    return datetime(2026, 10, day, hour, minute, tzinfo=ULAANBAATAR)


MESSAGE_TIME = at(11, 10)                      # the km message (today in the tests = 10-12)
NOW = at(12, 12)
# 9.15a-3: the unknown-truck reply with the test client's CONTACT_PHONE (tests/test_reminders.py CONTACT)
UNKNOWN_TRUCK = ("Энэ дугаар манай бүртгэлд олдсонгүй. Дугаараа шалгаад дахин бичнэ үү, эсвэл 99000001 "
                 "руу залгана уу.")


# ==========================================================================
# Parser (pure)
# ==========================================================================

@pytest.mark.parametrize(("raw", "plate", "km"), [
    ("871234 9988НАА", "9988НАА", 871_234),           # km first
    ("9988 НАА, 871234", "9988НАА", 871_234),         # plate first, space + comma
    ("9988 НАА 871 234", "9988НАА", 871_234),         # thousands split by a space
    ("9988HAA, 871,234", "9988НАА", 871_234),         # Latin look-alikes H, A + thousands comma
    ("9988нАа 871234 км", "9988НАА", 871_234),        # mixed case + «км»
    ("9988-HAA 871234km", "9988НАА", 871_234),        # hyphen, «km» stuck to the number
    ("  112000  1234 yba. ", "1234УВА", 112_000),     # Latin y -> У, b -> В, punctuation around
    ("9988 НАА 871.234", "9988НАА", 871_234),
    ("0101 ТЕС 999", "0101ТЕС", 999),                 # 3 digits is the minimum
])
def test_parser_reads_plate_and_km_in_any_order(raw: str, plate: str, km: int) -> None:
    assert parse_km_message(raw) == KmMessage(plate=plate, km=km)


@pytest.mark.parametrize("raw", [
    "сайн уу", "", None, "871234",                    # no plate
    "9988НАА",                                        # no number
    "9988НАА 1234УБА 871234",                         # two plates
    "9988НАА 871234 5", "9988НАА 871234 112000",      # two numbers
    "9988НАА 12",                                     # too short
    "9988НАА 12345678",                               # too long
    "9988ЖЖЖ 871234",                                 # letter never seen on a plate
    "19988НАА 871234",                                # 5 digits before the letters
    "9988НААБ 871234",                                # 4 letters
    "9988НАА 871234 км явсан",                        # extra words -> a person reads it
])
def test_parser_refuses_anything_else(raw: str | None) -> None:
    assert parse_km_message(raw) is None


def test_yes_no_words() -> None:
    assert all(is_yes(t) for t in ("Тийм", "тийм", "ТИЙМ!", " тиймээ "))
    assert all(is_no(t) for t in ("Үгүй", "үгүй."))
    assert not is_yes("тийм биш") and not is_no("Тийм") and not is_yes(None)


def test_texts() -> None:
    assert texts.confirm_question("9988НАА", 871_234) == "9988НАА — 871 234 км. Зөв үү?"
    assert texts.usable_thanks("9988НАА", 310.4, datetime(2026, 12, 15).date(), 883_234) == \
        "Баярлалаа! 9988НАА өдөрт ~310 км явж байна. Дараагийн тос солих: ~2026.12.15 (883 234 км)."
    assert len(texts.YES) <= 20 and len(texts.NO) <= 20           # Meta: quick reply title <= 20 chars


def test_ref_codes_are_random_8_chars() -> None:
    codes = {new_ref_code() for _ in range(200)}
    assert len(codes) == 200 and all(len(c) == 8 and set(c) <= set(REF_ALPHABET) for c in codes)
    assert not set("01IO") - set("IO") & set(REF_ALPHABET)        # no 0 / 1 (look like O / I)


# ==========================================================================
# Signature + settings (pure)
# ==========================================================================

def sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_signature_check() -> None:
    body = b'{"object":"page"}'
    assert signature_ok(SECRET, body, sign(body))
    assert signature_ok(SECRET, body, sign(body).upper().replace("SHA256=", "sha256="))  # hex case
    assert not signature_ok(SECRET, body, None)
    assert not signature_ok(SECRET, body, sign(body, "x" * 24))                        # other secret
    assert not signature_ok(SECRET, body + b" ", sign(body))                           # body changed
    assert not signature_ok(SECRET, body, sign(body).replace("sha256=", "sha1="))
    assert not signature_ok("", body, sign(body, ""))                                  # no secret: never ok


def test_settings_off_by_default_and_checked() -> None:
    assert messenger_settings({}) == MessengerSettings()
    full = {"MESSENGER_ENABLED": "true", "META_APP_SECRET": SECRET, "META_VERIFY_TOKEN": VERIFY,
            "META_PAGE_TOKEN": PAGE_TOKEN, "META_PAGE_ID": PAGE_ID, "META_GRAPH_VERSION": VERSION}
    assert messenger_settings(full) == ON
    with pytest.raises(ConfigError, match="META_PAGE_TOKEN, META_GRAPH_VERSION") as err:
        messenger_settings({**full, "META_PAGE_TOKEN": " ", "META_GRAPH_VERSION": ""})
    assert SECRET not in str(err.value) and VERIFY not in str(err.value)
    with pytest.raises(ConfigError, match="needs MESSENGER_ENABLED"):
        messenger_settings({"MESSENGER_OTN_ENABLED": "true"})
    with pytest.raises(ConfigError, match="META_GRAPH_VERSION"):
        messenger_settings({**full, "META_GRAPH_VERSION": "26"})
    with pytest.raises(ConfigError, match="MESSENGER_ENABLED must be true or false") as err:
        messenger_settings({"MESSENGER_ENABLED": "maybe"})
    assert "maybe" not in str(err.value)
    shown = repr(ON) + str(ON)
    assert SECRET not in shown and VERIFY not in shown and PAGE_TOKEN not in shown


def test_api_starts_and_is_healthy_with_messenger_off_and_no_meta_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """PM 9.15a-2: the deploy with the flag off must work on a server .env that has NO META_* line at all."""
    for name in ("MESSENGER_OTN_ENABLED", "META_APP_SECRET", "META_VERIFY_TOKEN", "META_PAGE_TOKEN", "META_PAGE_ID",
                 "META_GRAPH_VERSION"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MESSENGER_ENABLED", "false")
    app = create_app(engine=create_engine("sqlite://", poolclass=StaticPool))  # SELECT 1 answers: db ok
    with TestClient(app) as client:  # noqa: F811
        assert app.state.messenger_sender is None
        health = client.get("/health")
        assert (health.status_code, health.json()) == (200, {"status": "ok", "db": "ok"})
        assert client.get("/messenger/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "",
                                                        "hub.challenge": "1"}).status_code == 403
        assert client.post("/messenger/webhook", content=b"{}").status_code == 403   # no secret: nothing accepted
    monkeypatch.delenv("MESSENGER_ENABLED")                                          # not set at all: same
    with TestClient(create_app(engine=create_engine("sqlite://", poolclass=StaticPool))) as client:  # noqa: F811
        assert client.get("/health").status_code == 200


def test_api_refuses_to_start_when_enabled_with_empty_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MESSENGER_ENABLED", "true")
    for name in ("META_APP_SECRET", "META_VERIFY_TOKEN", "META_PAGE_TOKEN", "META_PAGE_ID", "META_GRAPH_VERSION"):
        monkeypatch.delenv(name, raising=False)
    app = create_app(engine=create_engine("sqlite://", poolclass=StaticPool))
    with pytest.raises(ConfigError, match="MESSENGER_ENABLED=true but empty"):
        with TestClient(app):
            pass


# ==========================================================================
# Send API client: mocked urlopen, no network
# ==========================================================================

class FakeResponse(io.BytesIO):
    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def test_graph_sender_request(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: float) -> FakeResponse:
        seen.update(url=request.full_url, body=json.loads(request.data), timeout=timeout)
        return FakeResponse(b'{"recipient_id": "1", "message_id": "m"}')

    monkeypatch.setattr(S.urllib.request, "urlopen", fake_urlopen)
    S.GraphSender(PAGE_ID, PAGE_TOKEN, VERSION).send(S.yes_no_to(PSID, "Зөв үү?"))
    assert seen["url"] == f"https://graph.facebook.com/{VERSION}/{PAGE_ID}/messages?access_token={PAGE_TOKEN}"
    assert seen["body"]["recipient"] == {"id": PSID} and seen["body"]["messaging_type"] == "RESPONSE"
    assert [q["payload"] for q in seen["body"]["message"]["quick_replies"]] == ["KM_YES", "KM_NO"]
    assert PAGE_TOKEN not in repr(S.GraphSender(PAGE_ID, PAGE_TOKEN, VERSION))


@pytest.mark.parametrize("error", [
    urllib.error.HTTPError("https://graph.facebook.com/x?access_token=" + PAGE_TOKEN, 400, "Bad", {}, None),
    urllib.error.URLError("no route"), TimeoutError()])
def test_graph_sender_errors_hold_no_token(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    def fail(request: Any, timeout: float) -> None:
        raise error

    monkeypatch.setattr(S.urllib.request, "urlopen", fail)
    with pytest.raises(S.SendError) as err:
        S.GraphSender(PAGE_ID, PAGE_TOKEN, VERSION).send(S.text_to(PSID, "x"))
    assert PAGE_TOKEN not in str(err.value) and err.value.__cause__ is None and err.value.__suppress_context__


# ==========================================================================
# Logs
# ==========================================================================

def test_access_log_filter_hides_the_verify_query() -> None:
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d', (
        "1.2.3.4:5", "GET", f"/messenger/webhook?hub.mode=subscribe&hub.verify_token={VERIFY}&hub.challenge=1",
        "1.1", 200), None)
    assert HideWebhookQuery().filter(record)
    assert record.getMessage() == '1.2.3.4:5 - "GET /messenger/webhook HTTP/1.1" 200'
    other = logging.LogRecord("x", logging.INFO, "", 0, "%s", (f"/other?hub.verify_token={VERIFY}&a=1",), None)
    HideWebhookQuery().filter(other)
    assert VERIFY not in other.getMessage() and "a=1" in other.getMessage()


def test_filter_installed_on_uvicorn_access_logger() -> None:
    create_app(engine=create_engine("sqlite://", poolclass=StaticPool))
    create_app(engine=create_engine("sqlite://", poolclass=StaticPool))
    filters = [f for f in logging.getLogger("uvicorn.access").filters if isinstance(f, HideWebhookQuery)]
    assert len(filters) == 1


# ==========================================================================
# Webhook (Postgres)
# ==========================================================================

class FakeSender:
    """Records every Send API call instead of calling Meta."""

    def __init__(self) -> None:
        self.calls: list[S.Outgoing] = []
        self.fail = False

    def send(self, out: S.Outgoing) -> None:
        if self.fail:
            raise S.SendError("meta_error: HTTP 400")
        self.calls.append(out)

    def texts(self) -> list[str]:
        return [c.message.get("text", "") for c in self.calls]


@pytest.fixture
def bot(client: TestClient) -> Iterator[tuple[TestClient, FakeSender]]:  # noqa: F811
    """The test client with the bot ON (OTN off), a fake sender and a fixed 'now'."""
    sender = FakeSender()
    overrides = client.app.dependency_overrides
    overrides[get_messenger_settings] = lambda: ON
    overrides[get_sender] = lambda: sender
    overrides[get_now] = lambda: NOW
    yield client, sender


def settings_on(client: TestClient, settings: MessengerSettings) -> None:  # noqa: F811
    client.app.dependency_overrides[get_messenger_settings] = lambda: settings


def ms(when: datetime) -> int:
    return int(when.timestamp() * 1000)


def message(text_: str | None, when: datetime = MESSAGE_TIME, psid: str = PSID, mid: str | None = None,
            quick: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"mid": mid or f"m.{psid}.{ms(when)}.{text_}"}
    if text_ is not None:
        body["text"] = text_
    if quick:
        body["quick_reply"] = {"payload": quick}
    return {"sender": {"id": psid}, "recipient": {"id": PAGE_ID}, "timestamp": ms(when), "message": body}


def referral(ref: str, when: datetime = at(11, 9), psid: str = PSID) -> dict[str, Any]:
    return {"sender": {"id": psid}, "recipient": {"id": PAGE_ID}, "timestamp": ms(when),
            "referral": {"ref": ref, "source": "SHORTLINK", "type": "OPEN_THREAD"}}


def delivery(*events: dict[str, Any], page_id: str = PAGE_ID) -> dict[str, Any]:
    return {"object": "page", "entry": [{"id": page_id, "time": ms(NOW), "messaging": list(events)}]}


def post(client: TestClient, body: dict[str, Any] | bytes, signature: str | None = "good"):  # noqa: F811
    raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if signature == "good":
        headers["X-Hub-Signature-256"] = sign(raw)
    elif signature is not None:
        headers["X-Hub-Signature-256"] = signature
    return client.post("/messenger/webhook", content=raw, headers=headers)


def send_events(client: TestClient, *events: dict[str, Any]) -> None:  # noqa: F811
    r = post(client, delivery(*events))
    assert r.status_code == 200 and r.text == "EVENT_RECEIVED", r.text


def count(pg: Connection, sql: str, **params: Any) -> int:  # noqa: F811
    return pg.execute(text(sql), params).scalar_one()


def ref_of(pg: Connection, service_id: int) -> str:  # noqa: F811
    return pg.execute(text("SELECT ref FROM messenger_refs WHERE service_id = :s"), {"s": service_id}).scalar_one()


def truck(client: TestClient, plate: str, km: int = 100_000, day: str = "2026-09-01") -> dict:  # noqa: F811
    return new_service(client, plate, day, km=km)


# ---------------------------------------------------------------- verify (GET)


@pytest.mark.parametrize(("settings", "params", "code"), [
    (ON, {"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "12345"}, 200),
    (OFF, {"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "12345"}, 200),  # works disabled
    (ON, {"hub.mode": "subscribe", "hub.verify_token": "w" * 24, "hub.challenge": "12345"}, 403),
    (ON, {"hub.mode": "unsubscribe", "hub.verify_token": VERIFY, "hub.challenge": "12345"}, 403),
    (ON, {"hub.challenge": "12345"}, 403),
    (MessengerSettings(), {"hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "1"}, 403),  # no token set
])
def test_verify_get(bot: tuple[TestClient, FakeSender], settings: MessengerSettings, params: dict, code: int) -> None:
    client, _ = bot
    settings_on(client, settings)
    r = client.get("/messenger/webhook", params=params)
    assert r.status_code == code
    if code == 200:
        assert r.text == "12345" and r.headers["content-type"].startswith("text/plain")


# ---------------------------------------------------------------- signature (POST)


@pytest.mark.parametrize("signature", [None, "sha256=" + "0" * 64, "sha256=", "nonsense", "wrong-secret",
                                       "changed-body"])
def test_unsigned_or_wrong_signature_is_refused_and_nothing_stored(bot: tuple[TestClient, FakeSender],
                                                                   pg: Connection, signature: str | None) -> None:  # noqa: F811
    client, sender = bot
    truck(client, "9988 НАА")
    raw = json.dumps(delivery(message("112000 9988НАА"))).encode()
    if signature == "wrong-secret":
        signature = sign(raw, "x" * 24)
    elif signature == "changed-body":
        signature, raw = sign(raw), raw.replace(b"112000", b"999999")
    assert post(client, raw, signature).status_code == 403
    assert count(pg, "SELECT count(*) FROM messenger_seen") == 0
    assert count(pg, "SELECT count(*) FROM messenger_pending") == 0
    assert sender.calls == []


def test_signed_event_is_accepted(bot: tuple[TestClient, FakeSender], pg: Connection) -> None:  # noqa: F811
    client, sender = bot
    truck(client, "9988 НАА")
    send_events(client, message("112000 9988НАА"))
    assert count(pg, "SELECT count(*) FROM messenger_pending") == 1 and len(sender.calls) == 1


def test_body_over_64_kb_is_refused(bot: tuple[TestClient, FakeSender]) -> None:
    client, sender = bot
    raw = b'{"object": "page", "x": "' + b"a" * (64 * 1024) + b'"}'
    assert post(client, raw).status_code == 413 and sender.calls == []


def test_disabled_answers_200_and_does_nothing(bot: tuple[TestClient, FakeSender], pg: Connection) -> None:  # noqa: F811
    client, sender = bot
    settings_on(client, OFF)
    truck(client, "9988 НАА")
    send_events(client, message("112000 9988НАА"))
    assert count(pg, "SELECT count(*) FROM messenger_seen") == 0
    assert count(pg, "SELECT count(*) FROM messenger_pending") == 0 and sender.calls == []
    assert post(client, delivery(message("112000 9988НАА")), signature=None).status_code == 403  # still checked first


def test_other_page_and_echo_ignored(bot: tuple[TestClient, FakeSender], pg: Connection) -> None:  # noqa: F811
    client, sender = bot
    truck(client, "9988 НАА")
    r = post(client, delivery(message("112000 9988НАА"), page_id="999"))
    assert r.status_code == 200
    echo = message("112000 9988НАА", mid="echo-1")
    echo["message"]["is_echo"] = True
    send_events(client, echo)
    assert count(pg, "SELECT count(*) FROM messenger_pending") == 0 and sender.calls == []


# ---------------------------------------------------------------- the flow


def test_ref_tap_links_and_greets(bot: tuple[TestClient, FakeSender], pg: Connection) -> None:  # noqa: F811
    client, sender = bot
    t = truck(client, "9988 НАА")
    send_events(client, referral(ref_of(pg, t["service"]["id"])))
    assert sender.texts() == [texts.GREETING]
    link = pg.execute(text("SELECT vehicle_id, linked_via, service_id FROM messenger_links WHERE psid = :p"),
                      {"p": PSID}).one()
    assert tuple(link) == (t["vehicle_id"], "ref", t["service"]["id"])
    # new thread: Get Started postback with the ref inside (another driver, same truck)
    send_events(client, {"sender": {"id": OTHER_PSID}, "recipient": {"id": PAGE_ID}, "timestamp": ms(at(11, 9, 5)),
                         "postback": {"title": "Get Started", "payload": "GET_STARTED",
                                      "referral": {"ref": ref_of(pg, t["service"]["id"]), "source": "SHORTLINK"}}})
    assert count(pg, "SELECT count(*) FROM messenger_links WHERE vehicle_id = :v", v=t["vehicle_id"]) == 2
    send_events(client, referral("ZZZZZZZZ", when=at(11, 9, 10), psid="7000000000000003"))  # unknown ref: greeting only
    assert sender.texts()[-1] == texts.GREETING
    assert count(pg, "SELECT count(*) FROM messenger_links WHERE psid = '7000000000000003'") == 0


def test_km_message_then_yes_saves_a_messenger_reading(bot: tuple[TestClient, FakeSender], pg: Connection) -> None:  # noqa: F811
    """09-01 at 100 000 km; the driver writes 116 000 on 10-11 and taps «Тийм» the NEXT day (10-12, within
    24 h): 400 km/day, reading dated 10-11 (P3), source messenger. The reminder day moves to 10-11."""
    client, sender = bot
    t = truck(client, "9988 НАА")
    vid = t["vehicle_id"]
    before = client.get(f"/vehicles/{vid}").json()["pace"]
    assert (before["source"], before["reminder_on"]) == (None, "2026-11-15")
    send_events(client, message("116 000 9988 haa км"))
    assert sender.calls[-1].message["text"] == "9988НАА — 116 000 км. Зөв үү?"
    assert [q["title"] for q in sender.calls[-1].message["quick_replies"]] == ["Тийм", "Үгүй"]
    pending = pg.execute(text("SELECT plate, value, reading_date FROM messenger_pending WHERE psid = :p"),
                         {"p": PSID}).one()
    assert (pending.plate, float(pending.value), str(pending.reading_date)) == ("9988НАА", 116_000, "2026-10-11")
    assert count(pg, "SELECT count(*) FROM odometer_readings WHERE vehicle_id = :v AND source = 'messenger'",
                 v=vid) == 0                                                  # nothing saved before «Тийм»
    send_events(client, message("Тийм", when=at(12, 9), quick=texts.YES_PAYLOAD))
    row = pg.execute(text("SELECT reading_date, value, source, status, rate_per_day FROM odometer_readings "
                          "WHERE vehicle_id = :v AND source = 'messenger'"), {"v": vid}).one()
    assert (str(row.reading_date), float(row.value), row.status, float(row.rate_per_day)) == \
        ("2026-10-11", 116_000, "ok", 400.0)
    pace = client.get(f"/vehicles/{vid}").json()["pace"]
    assert (pace["source"], pace["rate_per_day"], pace["reminder_on"]) == ("reading", 400.0, "2026-10-11")
    assert sender.texts()[-1] == ("Баярлалаа! 9988НАА өдөрт ~400 км явж байна. Дараагийн тос солих: "
                                  "~2026.10.01 (112 000 км).")
    assert count(pg, "SELECT count(*) FROM messenger_pending") == 0
    assert count(pg, "SELECT count(*) FROM messenger_links WHERE psid = :p AND vehicle_id = :v AND "
                     "linked_via = 'plate'", p=PSID, v=vid) == 1


def test_typed_yes_counts_too(bot: tuple[TestClient, FakeSender], pg: Connection) -> None:  # noqa: F811
    client, _ = bot
    vid = truck(client, "9988 НАА")["vehicle_id"]
    send_events(client, message("9988НАА 112000"), message("ТИЙМ", when=at(11, 10, 1)))
    assert count(pg, "SELECT count(*) FROM odometer_readings WHERE vehicle_id = :v AND source = 'messenger'",
                 v=vid) == 1


def test_no_deletes_the_question(bot: tuple[TestClient, FakeSender], pg: Connection) -> None:  # noqa: F811
    client, sender = bot
    vid = truck(client, "9988 НАА")["vehicle_id"]
    send_events(client, message("9988НАА 112000"), message("Үгүй", when=at(11, 10, 1), quick=texts.NO_PAYLOAD))
    assert sender.texts()[-1] == texts.WRITE_AGAIN
    assert count(pg, "SELECT count(*) FROM messenger_pending") == 0
    assert count(pg, "SELECT count(*) FROM odometer_readings WHERE vehicle_id = :v AND source = 'messenger'",
                 v=vid) == 0
    send_events(client, message("Тийм", when=at(11, 10, 2), quick=texts.YES_PAYLOAD))  # nothing open: no reply
    assert sender.texts()[-1] == texts.WRITE_AGAIN and len(sender.calls) == 2


def test_yes_after_24_hours_stores_nothing(bot: tuple[TestClient, FakeSender], pg: Connection) -> None:  # noqa: F811
    client, sender = bot
    vid = truck(client, "9988 НАА")["vehicle_id"]
    send_events(client, message("9988НАА 112000"))
    send_events(client, message("Тийм", when=MESSAGE_TIME + timedelta(hours=24, minutes=1), quick=texts.YES_PAYLOAD))
    assert sender.texts()[-1] == texts.WRITE_AGAIN
    assert count(pg, "SELECT count(*) FROM odometer_readings WHERE vehicle_id = :v AND source = 'messenger'",
                 v=vid) == 0
    assert count(pg, "SELECT count(*) FROM messenger_pending") == 0


def test_a_new_km_message_replaces_the_question(bot: tuple[TestClient, FakeSender], pg: Connection) -> None:  # noqa: F811
    client, _ = bot
    truck(client, "9988 НАА")
    send_events(client, message("9988НАА 112000"), message("9988НАА 113000", when=at(11, 10, 5)))
    assert [float(v) for (v,) in pg.execute(text("SELECT value FROM messenger_pending")).all()] == [113_000]


def test_duplicate_delivery_is_handled_once(bot: tuple[TestClient, FakeSender], pg: Connection) -> None:  # noqa: F811
    client, sender = bot
    truck(client, "9988 НАА")
    body = delivery(message("9988НАА 112000", mid="mid.same"))
    assert post(client, body).status_code == 200 and post(client, body).status_code == 200
    assert count(pg, "SELECT count(*) FROM messenger_pending") == 1 and len(sender.calls) == 1
    send_events(client, referral("ZZZZZZZZ"), referral("ZZZZZZZZ"))          # no mid: same event, one greeting
    assert len(sender.calls) == 2


def test_not_a_km_message_gets_no_reply(bot: tuple[TestClient, FakeSender], pg: Connection) -> None:  # noqa: F811
    client, sender = bot
    truck(client, "9988 НАА")
    send_events(client, message("Сайн байна уу, тос хэзээ солих вэ?"), message("871234", when=at(11, 11)),
                message(None, when=at(11, 12)))                              # e.g. a photo: no text
    assert sender.calls == []
    assert count(pg, "SELECT count(*) FROM messenger_pending") == 0


def test_unknown_plate_without_ref_stores_nothing(bot: tuple[TestClient, FakeSender], pg: Connection) -> None:  # noqa: F811
    client, sender = bot
    send_events(client, message("0000ААА 112000"))
    assert sender.texts() == [UNKNOWN_TRUCK]                               # 9.15a-3: check the plate or call
    assert count(pg, "SELECT count(*) FROM messenger_pending") == 0


def test_truck_without_a_usable_day_gets_a_person(bot: tuple[TestClient, FakeSender], pg: Connection) -> None:  # noqa: F811
    """Service on the message's own day: the reading check refuses it (422) -> staff reply, nothing kept."""
    client, sender = bot
    truck(client, "9988 НАА", day="2026-10-11")
    send_events(client, message("9988НАА 112000"))
    assert sender.texts() == [texts.STAFF_WILL_CHECK] and count(pg, "SELECT count(*) FROM messenger_pending") == 0


def flagged_pace(client: TestClient, vid: int) -> tuple:  # noqa: F811
    card = client.get(f"/vehicles/{vid}").json()
    messenger = [r for r in card["readings"] if r["source"] == "messenger"]
    return card["pace"]["source"], [(r["status"], r["flag_reason"]) for r in messenger]


def test_mismatch_typed_plate_known_is_flagged_on_typed_truck(bot: tuple[TestClient, FakeSender],
                                                              pg: Connection) -> None:  # noqa: F811
    """P1: ref link = truck A, typed plate = truck B (in our DB) -> stored on B, flagged, never used."""
    client, sender = bot
    a = truck(client, "9988 НАА")
    b = truck(client, "1235 УБА")
    send_events(client, referral(ref_of(pg, a["service"]["id"])))
    send_events(client, message("1235УБА 112000"), message("Тийм", when=at(11, 10, 1), quick=texts.YES_PAYLOAD))
    assert flagged_pace(client, b["vehicle_id"]) == (None, [("flagged", "plate_mismatch")])  # 300 km/day, not used
    assert flagged_pace(client, a["vehicle_id"]) == (None, [])
    assert sender.texts()[-1] == texts.FLAGGED_THANKS
    assert b["vehicle_id"] not in [r["vehicle_id"] for r in client.get("/reminders/due").json()["reminders"]]


def test_mismatch_typed_plate_unknown_is_flagged_on_ref_truck(bot: tuple[TestClient, FakeSender],
                                                              pg: Connection) -> None:  # noqa: F811
    client, sender = bot
    a = truck(client, "9988 НАА")
    send_events(client, referral(ref_of(pg, a["service"]["id"])))
    send_events(client, message("0000ААА 112000"))
    assert sender.calls[-1].message["text"] == "0000ААА — 112 000 км. Зөв үү?"
    send_events(client, message("Тийм", when=at(11, 10, 1), quick=texts.YES_PAYLOAD))
    assert flagged_pace(client, a["vehicle_id"]) == (None, [("flagged", "plate_mismatch")])
    assert sender.texts()[-1] == texts.FLAGGED_THANKS


def test_ref_of_an_older_service_does_not_count(bot: tuple[TestClient, FakeSender], pg: Connection) -> None:  # noqa: F811
    client, sender = bot
    a = truck(client, "9988 НАА", day="2026-08-01")
    send_events(client, referral(ref_of(pg, a["service"]["id"])))
    new_service(client, "9988 НАА", "2026-09-01", km=110_000)             # a new cycle: the old link is stale
    send_events(client, message("0000ААА 120000"))
    assert sender.texts()[-1] == UNKNOWN_TRUCK


def test_messenger_reading_can_be_undone(bot: tuple[TestClient, FakeSender], pg: Connection) -> None:  # noqa: F811
    client, _ = bot
    vid = truck(client, "9988 НАА")["vehicle_id"]
    send_events(client, message("9988НАА 112000"), message("Тийм", when=at(11, 10, 1), quick=texts.YES_PAYLOAD))
    rid = count(pg, "SELECT id FROM odometer_readings WHERE vehicle_id = :v AND source = 'messenger'", v=vid)
    assert client.delete(f"/readings/{rid}").status_code == 204
    service_row = count(pg, "SELECT id FROM odometer_readings WHERE vehicle_id = :v AND source = 'service'", v=vid)
    assert client.delete(f"/readings/{service_row}").status_code == 422


def test_service_gets_a_ref_mine_truck_none(client: TestClient, pg: Connection) -> None:  # noqa: F811
    t = truck(client, "9988 НАА")
    assert len(ref_of(pg, t["service"]["id"])) == 8
    r = client.post("/services", json={"identifier": "9989 НАА", "company_name": "Test 9.15a", "engine_hours": 1200.5,
                                       "oil_grade": "15W-40", "liters": 30, "service_date": "2026-09-01"})
    assert r.status_code == 201, r.text
    assert count(pg, "SELECT count(*) FROM messenger_refs WHERE service_id = :s", s=r.json()["service"]["id"]) == 0


# ---------------------------------------------------------------- One-Time Notification (behind its flag)


def otn_optin(vehicle_id: int, token: str = "otn-token-1", when: datetime = at(11, 10, 3)) -> dict[str, Any]:
    return {"sender": {"id": PSID}, "recipient": {"id": PAGE_ID}, "timestamp": ms(when),
            "optin": {"type": "one_time_notif_req", "payload": S.otn_payload(vehicle_id), "one_time_notif_token": token}}


def due_truck_with_reply(client: TestClient) -> dict:  # noqa: F811
    """400 km/day reply on 10-11 -> reminder due on 10-11 (<= today 10-12)."""
    t = truck(client, "9988 НАА")
    send_events(client, message("9988НАА 116000"), message("Тийм", when=at(11, 10, 1), quick=texts.YES_PAYLOAD))
    return t


def due_row(client: TestClient, vid: int) -> dict:  # noqa: F811
    return next(r for r in client.get("/reminders/due").json()["reminders"] if r["vehicle_id"] == vid)


def test_otn_off_nothing_asked_nothing_kept(bot: tuple[TestClient, FakeSender], pg: Connection) -> None:  # noqa: F811
    client, sender = bot
    t = due_truck_with_reply(client)
    assert not any("attachment" in c.message for c in sender.calls)
    send_events(client, otn_optin(t["vehicle_id"]))
    assert count(pg, "SELECT count(*) FROM messenger_otn") == 0
    assert due_row(client, t["vehicle_id"])["messenger_ready"] is False
    assert client.post(f"/reminders/{t['service']['id']}/messenger").status_code == 422


def test_otn_on_ask_keep_token_send_once(bot: tuple[TestClient, FakeSender], pg: Connection) -> None:  # noqa: F811
    client, sender = bot
    settings_on(client, ON_OTN)
    t = due_truck_with_reply(client)
    vid, sid = t["vehicle_id"], t["service"]["id"]
    request = sender.calls[-1].message["attachment"]["payload"]
    assert (request["template_type"], request["payload"]) == ("one_time_notif_req", f"otn:{vid}")
    assert due_row(client, vid)["messenger_ready"] is False                # no token yet
    send_events(client, otn_optin(vid), otn_optin(999_999, token="other"))  # a truck it is not linked to: ignored
    assert count(pg, "SELECT count(*) FROM messenger_otn") == 1
    assert due_row(client, vid)["messenger_ready"] is True
    r = client.post(f"/reminders/{sid}/messenger")
    assert r.status_code == 201, r.text
    assert (r.json()["channel"], r.json()["phone"], r.json()["already_sent"]) == ("messenger", None, False)
    assert sender.calls[-1].recipient == {"one_time_notif_token": "otn-token-1"}
    assert sender.calls[-1].message["text"] == r.json()["message_text"]
    assert count(pg, "SELECT count(*) FROM messenger_otn WHERE used_at IS NOT NULL") == 1
    calls = len(sender.calls)
    again = client.post(f"/reminders/{sid}/messenger")
    assert again.status_code == 200 and again.json()["already_sent"] is True and len(sender.calls) == calls
    assert vid not in [x["vehicle_id"] for x in client.get("/reminders/due").json()["reminders"]]


def test_otn_meta_error_stores_nothing_and_keeps_the_token(bot: tuple[TestClient, FakeSender],
                                                           pg: Connection) -> None:  # noqa: F811
    client, sender = bot
    settings_on(client, ON_OTN)
    t = due_truck_with_reply(client)
    send_events(client, otn_optin(t["vehicle_id"]))
    sender.fail = True
    r = client.post(f"/reminders/{t['service']['id']}/messenger")
    assert r.status_code == 502 and r.json()["detail"]["code"] == "meta_error"
    assert count(pg, "SELECT count(*) FROM reminders_sent WHERE service_id = :s", s=t["service"]["id"]) == 0
    assert count(pg, "SELECT count(*) FROM messenger_otn WHERE used_at IS NULL") == 1


def test_otn_refusals(bot: tuple[TestClient, FakeSender]) -> None:
    client, _ = bot
    settings_on(client, ON_OTN)
    assert client.post("/reminders/999999/messenger").status_code == 404
    assert client.post("/reminders/1/messenger").status_code == 409            # sample v1's older service
    t = truck(client, "9988 НАА")                                              # not due yet, no token
    assert client.post(f"/reminders/{t['service']['id']}/messenger").status_code == 422


# ---------------------------------------------------------------- logs: no secret, token, PSID, plate or text


def test_logs_hold_no_secret_psid_or_text(bot: tuple[TestClient, FakeSender], pg: Connection,  # noqa: F811
                                          caplog: pytest.LogCaptureFixture) -> None:
    client, _ = bot
    settings_on(client, ON_OTN)
    caplog.set_level(logging.DEBUG)
    t = truck(client, "9988 НАА")
    client.get("/messenger/webhook", params={"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "1"})
    client.get("/messenger/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "w" * 24})
    post(client, delivery(message("9988НАА 116000")), signature=None)
    send_events(client, referral(ref_of(pg, t["service"]["id"])), message("9988НАА 116000"),
                message("Тийм", when=at(11, 10, 1), quick=texts.YES_PAYLOAD), otn_optin(t["vehicle_id"]))
    client.post(f"/reminders/{t['service']['id']}/messenger")
    # The API's own records only: httpx* is the TEST client logging its request URL (not in production).
    logged = "\n".join(r.getMessage() for r in caplog.records if not r.name.startswith("httpx"))
    assert "messenger event: asked" in logged and "messenger verify: refused" in logged
    for secret in (SECRET, VERIFY, PAGE_TOKEN, PSID, "otn-token-1", "9988", "116000", "116 000", "Тийм"):
        assert secret not in logged, secret


# ---------------------------------------------------------------- daily cleanup


def test_cleanup_deletes_old_seen_and_expired_questions(pg: Connection) -> None:  # noqa: F811
    savepoint = pg.begin_nested()
    pg.execute(text("INSERT INTO messenger_seen (mid, received_at) VALUES ('old', :o), ('new', :n)"),
               {"o": NOW - timedelta(days=8), "n": NOW - timedelta(days=6)})
    pg.execute(text("INSERT INTO messenger_pending (psid, plate, value, reading_date, expires_at) VALUES "
                    "('1', '9988НАА', 1, '2026-10-11', :e), ('2', '9988НАА', 1, '2026-10-12', :f)"),
               {"e": NOW - timedelta(minutes=1), "f": NOW + timedelta(hours=1)})
    with Session(bind=pg, join_transaction_mode="create_savepoint") as session:
        assert cleanup(session, NOW) == (1, 1)
    assert [r for (r,) in pg.execute(text("SELECT mid FROM messenger_seen"))] == ["new"]
    assert [r for (r,) in pg.execute(text("SELECT psid FROM messenger_pending"))] == ["2"]
    savepoint.rollback()


def test_fake_messenger_script_signs_like_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import fake_messenger as F

    monkeypatch.setenv("META_PAGE_ID", PAGE_ID)
    event = F.build_event(PSID, "9988НАА 871234", None, False, 1)
    body = json.dumps(event).encode()
    assert signature_ok(SECRET, body, F.signature(SECRET, body))
    assert event["entry"][0]["id"] == PAGE_ID and event["entry"][0]["messaging"][0]["message"]["text"] == "9988НАА 871234"
    assert F.build_event(PSID, "Тийм", None, True, 1)["entry"][0]["messaging"][0]["message"]["quick_reply"] == \
        {"payload": "KM_YES"}
