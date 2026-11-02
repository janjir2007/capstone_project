"""Tests for task 9.12-1: GET /stats/period, GET /vehicles/search?segment=, at_risk_days on /stats/segments.

Postgres sample data (tests/test_api_data.py, the API's today = 2026-09-30, a Wednesday). Sample
services in September: 09-01 (vehicle 6, 30 l), 09-10 (vehicle 2, 28 l), 09-20 (vehicle 3, 30 l,
its FIRST-ever service). SKIPPED without a database.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, text

from src.api.clock import get_today, today_ulaanbaatar
from src.api.routers.stats import period_start
from tests.test_api_data import client, pg  # noqa: F401  (fixtures)


def period(client: TestClient, which: str | None = None, as_of: str | None = None) -> dict:  # noqa: F811
    params = {k: v for k, v in (("period", which), ("as_of", as_of)) if v}
    r = client.get("/stats/period", params=params)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- period dates (no DB)


@pytest.mark.parametrize(
    ("which", "end", "start"),
    [
        ("today", date(2026, 9, 30), date(2026, 9, 30)),
        ("week", date(2026, 9, 30), date(2026, 9, 28)),   # Wednesday -> Monday
        ("week", date(2026, 9, 28), date(2026, 9, 28)),   # Monday -> itself
        ("week", date(2026, 9, 27), date(2026, 9, 21)),   # Sunday -> the Monday before
        ("month", date(2026, 9, 30), date(2026, 9, 1)),
        ("month", date(2026, 10, 1), date(2026, 10, 1)),
    ],
)
def test_period_start(which, end, start):
    assert period_start(which, end) == start


# ---------------------------------------------------------------- GET /stats/period


def test_default_is_today_in_ub(client: TestClient) -> None:  # noqa: F811
    assert period(client) == {"period": "today", "date_from": "2026-09-30", "date_to": "2026-09-30",
                              "services": 0, "new_vehicles": 0, "liters": 0.0, "reminders_sent": 0}


def test_month_counts_services_liters_and_first_ever_vehicles(client: TestClient) -> None:  # noqa: F811
    body = period(client, "month")
    assert (body["date_from"], body["date_to"]) == ("2026-09-01", "2026-09-30")
    assert (body["services"], body["liters"]) == (3, 88.0)
    assert body["new_vehicles"] == 1        # only vehicle 3 had its FIRST service in September


def test_week_is_monday_to_today_not_last_7_days(client: TestClient) -> None:  # noqa: F811
    sunday = period(client, "week", "2026-09-20")
    assert (sunday["date_from"], sunday["services"], sunday["new_vehicles"]) == ("2026-09-14", 1, 1)
    monday = period(client, "week", "2026-09-21")
    assert (monday["date_from"], monday["services"]) == ("2026-09-21", 0)  # 09-20 is in the last 7 days, not this week


def test_reminders_sent_counted_by_ub_day(client: TestClient, pg: Connection) -> None:  # noqa: F811
    sql = text("INSERT INTO reminders_sent (vehicle_id, service_id, stage, message_text, send_on, sent_at) "
               "VALUES (:v, :s, 'single', 'x', '2026-09-30', :at)")
    for v, s, at in ((1, 3, "2026-09-29T23:59:00+08:00"),   # Tuesday in UB
                     (2, 5, "2026-09-29T16:30:00+00:00"),   # = Wednesday 00:30 in UB
                     (3, 6, "2026-09-30T23:59:59+08:00")):  # Wednesday, last second
        pg.execute(sql, {"v": v, "s": s, "at": at})
    assert period(client)["reminders_sent"] == 2
    assert period(client, "week")["reminders_sent"] == 3
    assert period(client, "today", "2026-10-01")["reminders_sent"] == 0


@pytest.mark.parametrize(
    ("as_of", "date_from", "services"),
    [("2026-09-21", "2026-09-21", 0),    # Monday: the week is that day only
     ("2026-09-20", "2026-09-14", 1)],   # Sunday: Monday-Sunday, incl. the 09-20 service
)
def test_week_boundary_monday_and_sunday(client: TestClient, as_of: str, date_from: str, services: int) -> None:  # noqa: F811
    body = period(client, "week", as_of)
    assert (body["date_from"], body["date_to"], body["services"]) == (date_from, as_of, services)


@pytest.mark.parametrize(
    ("utc_now", "ub_day", "week_from"),
    [("2026-09-20T15:59:00+00:00", date(2026, 9, 20), date(2026, 9, 14)),   # Sunday 23:59 UB: still Mon-Sun
     ("2026-09-20T16:00:00+00:00", date(2026, 9, 21), date(2026, 9, 21))],  # Monday 00:00 UB (Sunday in UTC)
)
def test_week_follows_ub_time_not_utc(monkeypatch, utc_now: str, ub_day: date, week_from: date) -> None:
    """The week turns at midnight in Ulaanbaatar: at 16:00 UTC on a Sunday it is already Monday in UB."""
    from datetime import datetime

    import src.api.clock as clock

    class FrozenUTC(datetime):
        @classmethod
        def now(cls, tz=None):  # the server clock, in UTC
            return datetime.fromisoformat(utc_now).astimezone(tz)

    monkeypatch.setattr(clock, "datetime", FrozenUTC)
    assert today_ulaanbaatar() == ub_day
    assert period_start("week", today_ulaanbaatar()) == week_from


@pytest.mark.parametrize("params", [{"period": "year"}, {"as_of": "30/09/2026"}])
def test_bad_params_are_422(client: TestClient, params) -> None:  # noqa: F811
    assert client.get("/stats/period", params=params).status_code == 422


def test_period_is_read_only(client: TestClient) -> None:  # noqa: F811
    assert client.post("/stats/period").status_code == 405


# ---------------------------------------------------------------- GET /vehicles/search?segment=


@pytest.mark.parametrize("today", [date(2026, 9, 30), date(2026, 10, 7)])  # 10-07: vehicle 4 is at_risk
def test_every_segment_card_count_equals_its_filtered_table(client: TestClient, today: date) -> None:  # noqa: F811
    """PM 9.12-1 review: for every card the number on it = the rows the table shows after tapping it
    (GET /stats/segments count == GET /vehicles/search?segment= total), Бүгд included."""
    client.app.dependency_overrides[get_today] = lambda: today
    stats = client.get("/stats/segments").json()
    assert stats["as_of"] == today.isoformat()
    for segment, n in stats["counts"].items():
        body = client.get("/vehicles/search", params={"segment": segment, "limit": 1000}).json()
        assert body["total"] == n, (today, segment)
        assert all(row["segment"] == segment for row in body["vehicles"]), (today, segment)
    every = client.get("/vehicles/search", params={"limit": 1000}).json()     # «Бүгд» = no segment filter
    assert every["total"] == stats["total"] == sum(stats["counts"].values())
    if today == date(2026, 10, 7):
        assert stats["counts"]["at_risk"] == 1                                  # the test really covers at_risk


def test_segment_filter_combines_with_query_and_rejects_unknown(client: TestClient) -> None:  # noqa: F811
    returning = client.get("/vehicles/search", params={"segment": "returning"}).json()["vehicles"]
    plate = returning[0]["identifier"]
    body = client.get("/vehicles/search", params={"segment": "returning", "q": plate}).json()
    assert [row["identifier"] for row in body["vehicles"]] == [plate]
    assert client.get("/vehicles/search", params={"segment": "loyal", "q": plate}).json()["total"] == 0
    assert client.get("/vehicles/search", params={"segment": "risky"}).status_code == 422


def test_segments_report_at_risk_days(client: TestClient) -> None:  # noqa: F811
    assert client.get("/stats/segments").json()["at_risk_days"] == 150
