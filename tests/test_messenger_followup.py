"""Task 9.15a-3: km-check SMS with the m.me link, «Шалгах» list API, Get Started script, settings.

Fake data only (made-up plates, phones, PSIDs, tokens). The API tests need the test PostgreSQL
(``docker compose up -d db``); otherwise they are SKIPPED like the other API tests.
"""

from __future__ import annotations

import io
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, text

from scripts import messenger_get_started as G
from src.api.config import ConfigError, MessengerSettings, messenger_settings
from src.api.messenger import texts
from src.api.reminders import sms_parts
from tests.test_api_data import pg  # noqa: F401  (fixture)
from tests.test_messenger import (ON, PAGE_ID, PAGE_TOKEN, VERSION, FakeSender, at, bot, message,  # noqa: F401
                                  ref_of, referral, send_events, truck)
from tests.test_reminders import client, default_rules  # noqa: F401  (fixtures)
from tests.test_serving import model_dir  # noqa: F401  (fixture)

PAGE = "WolfCenterMongolia"
ON_LINK = MessengerSettings(**{**ON.__dict__, "page_username": PAGE})


def use(client: TestClient, settings: MessengerSettings) -> None:  # noqa: F811
    from src.api.routers.reminders import get_messenger_settings

    client.app.dependency_overrides[get_messenger_settings] = lambda: settings


# ---------------------------------------------------------------- settings


def test_page_username_is_optional_and_checked() -> None:
    assert messenger_settings({}).page_username == ""
    assert messenger_settings({"MESSENGER_PAGE_USERNAME": f" {PAGE} "}).page_username == PAGE
    for bad in ("https://m.me/WolfCenterMongolia", "Wolf Center", "abc"):
        with pytest.raises(ConfigError, match="MESSENGER_PAGE_USERNAME") as err:
            messenger_settings({"MESSENGER_PAGE_USERNAME": bad})
        assert bad not in str(err.value)


# ---------------------------------------------------------------- texts


def test_unknown_truck_and_greeting_texts() -> None:
    assert texts.unknown_truck("99112233") == ("Энэ дугаар манай бүртгэлд олдсонгүй. Дугаараа шалгаад дахин "
                                               "бичнэ үү, эсвэл 99112233 руу залгана уу.")
    assert "Гео-Эксперт" not in texts.PROFILE_GREETING and len(texts.PROFILE_GREETING) <= 160


# ---------------------------------------------------------------- km-check SMS through the API


def km_check_of(client: TestClient, vehicle_id: int) -> dict:  # noqa: F811
    r = client.get("/km-checks/due")
    assert r.status_code == 200, r.text
    return next(c for c in r.json()["checks"] if c["vehicle_id"] == vehicle_id)


def test_km_check_text_has_the_services_link_only_when_on(bot: tuple[TestClient, FakeSender],  # noqa: F811
                                                          pg: Connection) -> None:  # noqa: F811
    client, _ = bot
    made = truck(client, "9988 НАА")
    vid, sid = made["vehicle_id"], made["service"]["id"]
    link = f"https://m.me/{PAGE}?ref={ref_of(pg, sid)}"

    use(client, MessengerSettings())                           # Messenger off: the dated text, no link
    off = km_check_of(client, vid)["message_mn"]
    assert "m.me" not in off and "2026.09.01" in off and off.endswith("Wolf Oil: 99000001")
    use(client, ON)                                            # on, but no Page username: no link either
    assert km_check_of(client, vid)["message_mn"] == off

    use(client, ON_LINK)
    on = km_check_of(client, vid)["message_mn"]
    assert on == f"Сайн байна уу! 9988 НАА машины одоогийн км-ээ хариу бичнэ үү эсвэл {link} Wolf Oil: 99000001"
    assert sms_parts(on) == 2
    r = client.post(f"/km-checks/{sid}/sent")                  # the stored text = the one sent
    assert r.status_code == 201 and r.json()["message_text"] == on


def test_reminder_text_is_txt1_b(bot: tuple[TestClient, FakeSender]) -> None:  # noqa: F811
    client, _ = bot
    vid = truck(client, "9988 НАА", day="2026-07-01")["vehicle_id"]
    row = next(r for r in client.get("/reminders/due").json()["reminders"] if r["vehicle_id"] == vid)
    assert row["message_mn"] == ("Сайн байна уу! 9988 НАА: 2026.07.01-нд 10W-40 тос солиулсан. Дахин солих "
                                 "хугацаа боллоо. Wolf Oil: 99000001")


# ---------------------------------------------------------------- «Шалгах» list


def flagged(client: TestClient) -> list[dict]:  # noqa: F811
    r = client.get("/readings/flagged")
    assert r.status_code == 200, r.text
    return r.json()["readings"]


def test_flagged_messenger_reading_listed_then_hidden(bot: tuple[TestClient, FakeSender],  # noqa: F811
                                                      pg: Connection) -> None:  # noqa: F811
    """A plate mismatch (P1) shows in «Шалгах» with the truck, km, date, reason and driver phone;
    «Шалгасан» hides it (idempotent), the reading stays flagged."""
    client, _ = bot
    a = truck(client, "9988 НАА")
    send_events(client, referral(ref_of(pg, a["service"]["id"])))
    send_events(client, message("0000ААА 112000"), message("Тийм", when=at(11, 10, 1), quick=texts.YES_PAYLOAD))
    manual = client.post(f"/vehicles/{a['vehicle_id']}/readings", json={"value": 99_000, "reading_date": "2026-10-10"})
    assert manual.status_code == 201 and manual.json()["reading"]["status"] == "flagged"   # manual: not listed

    rows = flagged(client)
    assert len(rows) == 1
    row = rows[0]
    assert {k: row[k] for k in ("vehicle_id", "identifier", "unit", "value", "reading_date", "flag_reason",
                                "phone")} == {
        "vehicle_id": a["vehicle_id"], "identifier": "9988 НАА", "unit": "km", "value": 112000.0,
        "reading_date": "2026-10-11", "flag_reason": "plate_mismatch", "phone": "99110009"}

    first = client.post(f"/readings/{row['reading_id']}/reviewed")
    assert first.status_code == 200
    again = client.post(f"/readings/{row['reading_id']}/reviewed")
    assert again.json()["reviewed_at"] == first.json()["reviewed_at"]
    assert flagged(client) == []
    status = pg.execute(text("SELECT status FROM odometer_readings WHERE id = :i"), {"i": row["reading_id"]}).scalar_one()
    assert status == "flagged"                                             # still never used for the pace

    assert client.post(f"/readings/{manual.json()['reading']['id']}/reviewed").status_code == 422
    assert client.post("/readings/999999/reviewed").status_code == 404


# ---------------------------------------------------------------- Get Started script (no network)


class FakeGraph:
    """Answers like Meta's Messenger Profile API: GETs in order from ``gets``, POST -> ``post``."""

    def __init__(self, gets: list[tuple[int, dict]], post: tuple[int, dict] = (200, {"result": "success"})) -> None:
        self.gets, self.post = list(gets), post
        self.calls: list[tuple[str, str, Any]] = []

    def __call__(self, method: str, url: str, body: dict | None) -> tuple[int, dict]:
        self.calls.append((method, url, body))
        return self.post if method == "POST" else self.gets.pop(0)


def profile(payload: str | None = None, greeting: str | None = None) -> tuple[int, dict]:
    row: dict[str, Any] = {}
    if payload:
        row["get_started"] = {"payload": payload}
    if greeting:
        row["greeting"] = [{"locale": "default", "text": greeting}]
    return 200, {"data": [row] if row else []}


def run_script(settings: MessengerSettings, graph: FakeGraph) -> tuple[bool, str]:
    out = io.StringIO()
    ok = G.check_get_started(settings, graph, lambda line: out.write(line + "\n"))
    return ok, out.getvalue()


def test_existing_button_is_printed_and_left_alone() -> None:
    """Set earlier (e.g. by n8n) with another payload: the bot answers every postback -> no POST."""
    graph = FakeGraph([profile("N8N_START", "Сайн байна уу!")])
    ok, printed = run_script(ON, graph)
    assert ok and [m for m, *_ in graph.calls] == ["GET"]
    assert "payload = 'N8N_START'" in printed and "greeting = 'Сайн байна уу!'" in printed
    assert "nothing changed" in printed and PAGE_TOKEN not in printed
    url = graph.calls[0][1]
    assert url.startswith(f"https://graph.facebook.com/{VERSION}/me/messenger_profile?")
    assert "fields=get_started%2Cgreeting" in url


def test_missing_button_is_set_with_greeting_then_checked() -> None:
    graph = FakeGraph([profile(), profile(texts.GET_STARTED_PAYLOAD, texts.PROFILE_GREETING)])
    ok, printed = run_script(ON, graph)
    assert ok and [m for m, *_ in graph.calls] == ["GET", "POST", "GET"]
    assert graph.calls[1][2] == {"get_started": {"payload": "GET_STARTED"},
                                 "greeting": [{"locale": "default", "text": texts.PROFILE_GREETING}]}
    assert "payload = None" in printed and "set: get_started, greeting" in printed and PAGE_TOKEN not in printed


def test_missing_button_keeps_an_existing_greeting() -> None:
    graph = FakeGraph([profile(greeting="Old greeting"), profile(texts.GET_STARTED_PAYLOAD, "Old greeting")])
    assert run_script(ON, graph)[0]
    assert graph.calls[1][2] == {"get_started": {"payload": "GET_STARTED"}}


def test_get_started_script_failures_print_status_only() -> None:
    refused = FakeGraph([(400, {"error": {"code": 190, "type": "OAuthException",
                                          "message": f"Invalid token {PAGE_TOKEN}"}})])
    ok, printed = run_script(ON, refused)
    assert not ok and "HTTP 400, code 190 (OAuthException)" in printed and PAGE_TOKEN not in printed
    ok, printed = run_script(MessengerSettings(), FakeGraph([]))
    assert not ok and "META_PAGE_TOKEN" in printed
    not_kept = FakeGraph([profile(), profile()])
    ok, printed = run_script(ON, not_kept)
    assert not ok and "NOT SET" in printed


def test_get_started_payload_is_handled_by_the_bot(bot: tuple[TestClient, FakeSender],  # noqa: F811
                                                   pg: Connection) -> None:  # noqa: F811
    """The payload the script sets: a new-thread tap with a ref links the truck and greets."""
    client, sender = bot
    a = truck(client, "9988 НАА")
    event = {"sender": {"id": "7000000000000009"}, "recipient": {"id": PAGE_ID}, "timestamp": 1_791_000_000_000,
             "postback": {"title": "Get Started", "payload": texts.GET_STARTED_PAYLOAD, "mid": "m.gs.1",
                          "referral": {"ref": ref_of(pg, a["service"]["id"]), "source": "SHORTLINK",
                                       "type": "OPEN_THREAD"}}}
    send_events(client, event)
    assert sender.texts() == [texts.GREETING]
    linked = pg.execute(text("SELECT vehicle_id FROM messenger_links WHERE psid = '7000000000000009'")).scalar_one()
    assert linked == a["vehicle_id"]

