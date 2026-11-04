"""Task 9.14a endpoints: stored target km + 'service' readings on POST /services, the card's pace,
POST /vehicles/{id}/readings + DELETE /readings/{id}, the km-check list, km_checks_sent.

Postgres + sample data (migration 010 applied after it: stored interval 15000), today = 2026-10-12
(the client of tests/test_reminders.py). Trucks created here are made up. SKIPPED without a database.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, text

from src.api.clock import today_ulaanbaatar
from src.api.reminders import km_check_message
from tests.test_api_data import pg  # noqa: F401  (fixture)
from tests.test_reminders import CONTACT, client, default_rules, due_ids, new_service  # noqa: F401
from tests.test_serving import model_dir  # noqa: F401  (fixture)


def card(client: TestClient, vid: int) -> dict:  # noqa: F811
    r = client.get(f"/vehicles/{vid}")
    assert r.status_code == 200, r.text
    return r.json()


def reading(client: TestClient, vid: int, value: float, day: str | None = None):  # noqa: F811
    body = {"value": value} | ({"reading_date": day} if day else {})
    return client.post(f"/vehicles/{vid}/readings", json=body)


def checks(client: TestClient, **params: str) -> dict:  # noqa: F811
    r = client.get("/km-checks/due", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def check_ids(client: TestClient, **params: str) -> list[int]:  # noqa: F811
    return [c["vehicle_id"] for c in checks(client, **params)["checks"]]


# ---------------------------------------------------------------- POST /services stores the target + a reading


def test_service_stores_its_interval_target_and_reading(client: TestClient, pg: Connection,  # noqa: F811
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    first = new_service(client, "0101 ТЕС", "2026-07-01", km=100_000)
    vid = first["vehicle_id"]
    assert (first["service"]["interval_km"], first["service"]["target_km"]) == (12_000, 112_000)
    monkeypatch.setenv("OIL_INTERVAL_KM", "10000")            # a later change does not move the old target
    new_service(client, "0101 ТЕС", "2026-09-01", km=118_000)
    history = card(client, vid)["history"]
    assert [(s["interval_km"], s["target_km"]) for s in history] == [(10_000, 128_000), (12_000, 112_000)]
    new_service(client, "0101 ТЕС", "2026-10-01", km=110_000)  # odometer went down: stored, but flagged
    rows = pg.execute(text("SELECT reading_date, value, source, status, flag_reason, rate_per_day "
                           "FROM odometer_readings WHERE vehicle_id = :v ORDER BY reading_date"), {"v": vid}).all()
    assert [(str(d), float(v), src, st, fr) for d, v, src, st, fr, _ in rows] == [
        ("2026-07-01", 100_000, "service", "ok", None), ("2026-09-01", 118_000, "service", "ok", None),
        ("2026-10-01", 110_000, "service", "flagged", "not_higher")]
    assert [None if r is None else float(r) for *_, r in rows] == [None, 290.3, -266.7]


# ---------------------------------------------------------------- the card's pace


def test_card_pace_from_services_none_or_hours(client: TestClient) -> None:  # noqa: F811
    """Sample v1: 286.6 km/day between its last 2 services · v3: one service -> 75 days + km check ·
    v5: mine truck -> hours per day only."""
    v1 = card(client, 1)["pace"]
    assert v1 == {"unit": "km", "rate_per_day": 286.6, "source": "services", "reading_value": None,
                  "reading_date": None, "interval_km": 15_000, "next_due_date": "2026-10-01",
                  "reminder_on": "2026-09-26", "basis": "pace", "km_check_on": None}
    v3 = card(client, 3)["pace"]
    assert (v3["rate_per_day"], v3["basis"], v3["reminder_on"], v3["km_check_on"]) == \
        (None, "fixed", "2026-12-04", "2026-10-24")
    v5 = card(client, 5)["pace"]
    assert (v5["unit"], v5["rate_per_day"], v5["reminder_on"], v5["basis"], v5["next_due_date"]) == \
        ("hours", 8.7, None, None, None)
    readings = card(client, 1)["readings"]
    assert [(r["reading_date"], r["source"]) for r in readings] == \
        [("2026-08-10", "service"), ("2026-05-20", "service"), ("2026-03-05", "service")]


# ---------------------------------------------------------------- readings


def test_reply_moves_the_first_reminder(client: TestClient) -> None:  # noqa: F811
    """A first-visit truck (09-01, no pace): km check from 10-05, reminder 11-15. The driver replies
    on 10-11: 16 000 km in 40 days = 400 km/day -> due 10-01, reminder 09-26 -> already past: due on
    the reply's day. It leaves the km-check list and is on today's reminder list."""
    vid = new_service(client, "0102 ТЕС", "2026-09-01", km=100_000)["vehicle_id"]
    assert vid in check_ids(client) and vid not in due_ids(client)
    r = reading(client, vid, 116_000, "2026-10-11")
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["reading"]["source"], body["reading"]["status"], body["reading"]["rate_per_day"]) == \
        ("manual", "ok", 400.0)
    assert body["pace"] == card(client, vid)["pace"]
    assert (body["pace"]["source"], body["pace"]["rate_per_day"], body["pace"]["reading_date"]) == \
        ("reading", 400.0, "2026-10-11")
    assert (body["pace"]["next_due_date"], body["pace"]["reminder_on"]) == ("2026-10-01", "2026-10-11")
    assert vid not in check_ids(client) and vid in due_ids(client)
    assert vid not in due_ids(client, as_of="2026-10-10")            # as_of before the reply: not known yet


def test_unusable_reply_is_stored_flagged_and_not_used(client: TestClient) -> None:  # noqa: F811
    vid = new_service(client, "0103 ТЕС", "2026-09-01", km=100_000)["vehicle_id"]
    lower = reading(client, vid, 99_000, "2026-10-01").json()
    fast = reading(client, vid, 200_000, "2026-10-02").json()        # 3 226 km/day
    assert [(x["reading"]["status"], x["reading"]["flag_reason"]) for x in (lower, fast)] == \
        [("flagged", "not_higher"), ("flagged", "too_fast")]
    assert (fast["pace"]["rate_per_day"], fast["pace"]["basis"]) == (None, "fixed")
    assert vid in check_ids(client)                                  # still no pace: still asked
    ok = reading(client, vid, 112_000, "2026-10-03").json()          # 375 km/day
    assert ok["reading"]["status"] == "ok"
    lower_than_ok = reading(client, vid, 111_000, "2026-10-05").json()  # below the usable reply of 10-03
    assert lower_than_ok["reading"]["flag_reason"] == "not_higher"
    assert lower_than_ok["pace"]["reading_value"] == 112_000.0
    assert [r["status"] for r in card(client, vid)["readings"]] == ["flagged", "ok", "flagged", "flagged", "ok"]


@pytest.mark.parametrize(("body", "code"), [
    ({"value": 120_000, "reading_date": "2026-10-13"}, 422),         # future (today 10-12)
    ({"value": 120_000, "reading_date": "2026-09-01"}, 422),         # the service's own day
    ({"value": 120_000, "reading_date": "2026-08-31"}, 422),         # before the service
    ({"value": 0}, 422), ({"value": -5}, 422), ({}, 422),
    ({"value": 120_000, "source": "messenger"}, 422),                # no other fields
])
def test_reading_refusals(client: TestClient, body: dict, code: int) -> None:  # noqa: F811
    vid = new_service(client, "0104 ТЕС", "2026-09-01", km=100_000)["vehicle_id"]
    assert client.post(f"/vehicles/{vid}/readings", json=body).status_code == code
    assert client.post("/vehicles/999999/readings", json={"value": 1}).status_code == 404


def test_reply_date_defaults_to_today(client: TestClient) -> None:  # noqa: F811
    vid = new_service(client, "0105 ТЕС", "2026-09-01", km=100_000)["vehicle_id"]
    assert reading(client, vid, 112_000).json()["reading"]["reading_date"] == "2026-10-12"


def test_mine_truck_reading_in_hours(client: TestClient) -> None:  # noqa: F811
    r = reading(client, 5, 13_300.5, "2026-10-10").json()            # v5: 12 980.5 h on 08-25, 46 days
    assert (r["reading"]["unit"], r["reading"]["status"], r["reading"]["rate_per_day"]) == ("hours", "ok", 7.0)
    assert (r["pace"]["source"], r["pace"]["reminder_on"]) == ("reading", None)


def test_delete_only_typed_in_readings(client: TestClient, pg: Connection) -> None:  # noqa: F811
    vid = new_service(client, "0106 ТЕС", "2026-09-01", km=100_000)["vehicle_id"]
    rid = reading(client, vid, 116_000, "2026-10-11").json()["reading"]["id"]
    assert card(client, vid)["pace"]["source"] == "reading"
    assert client.delete(f"/readings/{rid}").status_code == 204
    assert card(client, vid)["pace"]["source"] is None and vid in check_ids(client)
    assert client.delete(f"/readings/{rid}").status_code == 404
    service_row = pg.execute(text("SELECT id FROM odometer_readings WHERE vehicle_id = :v AND source = 'service'"),
                             {"v": vid}).scalar_one()
    assert client.delete(f"/readings/{service_row}").status_code == 422


# ---------------------------------------------------------------- km checks


def test_km_check_list_window_and_text(client: TestClient) -> None:  # noqa: F811
    """Sample v3 (one service 09-20, no pace): asked from 10-24 (34 days) until its reminder day 12-04.
    v1 / v2 / v6 have a pace, v4 is past its reminder day, v5 is a mine truck."""
    assert check_ids(client, as_of="2026-10-23") == []
    on = checks(client, as_of="2026-10-24")
    assert [c["vehicle_id"] for c in on["checks"]] == [3] and on["contact_is_placeholder"] is False
    v3 = on["checks"][0]
    assert (v3["service_id"], v3["check_on"], v3["reminder_on"], v3["days_since"], v3["odometer_km"]) == \
        (6, "2026-10-24", "2026-12-04", 34, 150_200)
    assert v3["message_mn"] == km_check_message("9012 ДАА", date(2026, 9, 20), CONTACT)
    assert check_ids(client, as_of="2026-12-03") == [3] and check_ids(client, as_of="2026-12-04") == []


def test_km_check_sent_once_and_counted_apart_from_reminders(client: TestClient, pg: Connection) -> None:  # noqa: F811
    first = new_service(client, "0107 ТЕС", "2026-09-01", km=100_000)
    vid, sid = first["vehicle_id"], first["service"]["id"]
    r = client.post(f"/km-checks/{sid}/sent")
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["check_on"], body["channel"], body["phone"], body["already_sent"]) == \
        ("2026-10-05", "manual", "99110009", False)
    assert body["message_text"] == km_check_message("0107 ТЕС", date(2026, 9, 1), CONTACT)
    again = client.post(f"/km-checks/{sid}/sent")
    assert again.status_code == 200 and again.json() == body | {"already_sent": True}
    assert vid not in check_ids(client)
    assert pg.execute(text("SELECT count(*) FROM reminders_sent WHERE service_id = :s"), {"s": sid}).scalar_one() == 0
    # sent_at = the real now(): count on the real Ulaanbaatar day (CI runs in UTC)
    stats = client.get("/stats/period", params={"period": "today", "as_of": today_ulaanbaatar().isoformat()}).json()
    assert (stats["km_checks_sent"], stats["reminders_sent"]) == (1, 0)
    back = new_service(client, "0107 ТЕС", "2026-10-10", km=100_500)       # new cycle (2 km/day: no pace)
    assert client.post(f"/km-checks/{sid}/sent").status_code == 200        # stored before: still idempotent
    assert back["service"]["id"] != sid


@pytest.mark.parametrize(("service_id", "code"), [
    (1, 409),        # v1's older service
    (9, 422),        # v5 mine truck
    (999_999, 404),
])
def test_km_check_refusals(client: TestClient, service_id: int, code: int) -> None:  # noqa: F811
    assert client.post(f"/km-checks/{service_id}/sent").status_code == code


def test_km_check_not_due_yet_or_stopped_phone(client: TestClient) -> None:  # noqa: F811
    fresh = new_service(client, "0108 ТЕС", "2026-10-01")             # check day 11-04
    assert client.post(f"/km-checks/{fresh['service']['id']}/sent").status_code == 422
    old = new_service(client, "0109 ТЕС", "2026-09-01", phone="99110088")
    assert old["vehicle_id"] in check_ids(client)
    assert client.post("/reminders/stops", json={"phone": "99110088"}).status_code == 201
    assert old["vehicle_id"] not in check_ids(client)
    assert client.post(f"/km-checks/{old['service']['id']}/sent").status_code == 422
