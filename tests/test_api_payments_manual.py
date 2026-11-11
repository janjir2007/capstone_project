"""Task 9.16b-2: manual payment in the API (migration 013).

POST /services price_mnt, POST /services/{id}/payment, PUT /services/{id}/price, GET /payments/receivables,
and the status on cards / lookup / search. Postgres (sample data + migrations up to 013, TODAY = 2026-09-30,
tests/test_api_data.py); SKIPPED without a database. All values are SYNTHETIC.

"Now" is frozen through the get_now dependency, and each new service's created_at is set to SAVED, so the
24 h rule is tested exactly (Postgres now() is the start of the test transaction, not the test's clock).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, text

from src.api.clock import get_now
from tests.test_api_data import client, pg, service_body  # noqa: F401  (fixtures)

UB = timezone(timedelta(hours=8))
SAVED = datetime(2026, 9, 30, 10, 0, tzinfo=UB)


class Clock:
    """The API's "now" for one test; move it with .at(hours after SAVED)."""

    def __init__(self) -> None:
        self.now = SAVED

    def at(self, hours: float) -> None:
        self.now = SAVED + timedelta(hours=hours)


@pytest.fixture
def clock(client: TestClient) -> Iterator[Clock]:  # noqa: F811
    c = Clock()
    client.app.dependency_overrides[get_now] = lambda: c.now
    yield c
    client.app.dependency_overrides.pop(get_now, None)


def save(client: TestClient, pg: Connection, plate: str = "4321 УБД", **fields: Any) -> dict:  # noqa: F811
    """POST /services, then pin created_at to SAVED. Returns the service from the answer."""
    response = client.post("/services", json=service_body(identifier=plate, **fields))
    assert response.status_code == 201, response.text
    sid = response.json()["service"]["id"]
    pg.execute(text("UPDATE service_records SET created_at = :t WHERE id = :id"), {"t": SAVED, "id": sid})
    return response.json()["service"]


def card_service(client: TestClient, sid: int) -> dict:  # noqa: F811
    """The service as the API shows it now (search rows with services = the same service_out as the card)."""
    rows = client.get("/vehicles/search", params={"with_services": True, "limit": 1000}).json()["vehicles"]
    return next(s for r in rows for s in (r["services"] or []) if s["id"] == sid)


def pay(client: TestClient, sid: int, action: str) -> Any:  # noqa: F811
    return client.post(f"/services/{sid}/payment", json={"action": action})


# ---------------------------------------------------------------- POST /services


def test_new_service_with_price_is_pending(client: TestClient, pg: Connection, clock: Clock) -> None:  # noqa: F811
    s = save(client, pg, price_mnt=85000)
    assert (s["payment_status"], s["price_mnt"], s["amount_due"], s["paid_at"]) == ("pending", 85000, None, None)
    tracked = pg.execute(text("SELECT payment_tracked FROM service_records WHERE id = :id"), {"id": s["id"]})
    assert tracked.scalar() is True


def test_new_service_without_price_is_pending_too(client: TestClient, pg: Connection, clock: Clock) -> None:  # noqa: F811
    s = save(client, pg)
    assert (s["payment_status"], s["price_mnt"]) == ("pending", None)


def test_price_zero_is_paid_at_once(client: TestClient, pg: Connection, clock: Clock) -> None:  # noqa: F811
    s = save(client, pg, price_mnt=0)
    assert s["payment_status"] == "paid" and s["paid_at"] is None
    clock.at(48)
    assert card_service(client, s["id"])["payment_status"] == "paid"


@pytest.mark.parametrize("price", [-1, 1.5, "85000", 100_000_001])
def test_bad_price_is_422_and_nothing_saved(client: TestClient, pg: Connection, price: Any) -> None:  # noqa: F811
    before = pg.execute(text("SELECT count(*) FROM service_records")).scalar()
    assert client.post("/services", json=service_body(price_mnt=price)).status_code == 422
    assert pg.execute(text("SELECT count(*) FROM service_records")).scalar() == before


# ---------------------------------------------------------------- the 24 h rule through the API


def test_exactly_24_hours_turns_unpaid(client: TestClient, pg: Connection, clock: Clock) -> None:  # noqa: F811
    sid = save(client, pg, price_mnt=60000)["id"]
    clock.at(24 - 1 / 60)
    assert card_service(client, sid)["payment_status"] == "pending"
    clock.at(24)
    s = card_service(client, sid)
    assert (s["payment_status"], s["amount_due"]) == ("unpaid", 60000.0)
    assert datetime.fromisoformat(s["unpaid_since"]) == SAVED + timedelta(hours=24)


def test_no_price_still_turns_unpaid(client: TestClient, pg: Connection, clock: Clock) -> None:  # noqa: F811
    sid = save(client, pg)["id"]
    clock.at(30)
    s = card_service(client, sid)
    assert (s["payment_status"], s["amount_due"], s["price_mnt"]) == ("unpaid", None, None)


def test_due_hours_setting(client: TestClient, pg: Connection, clock: Clock,  # noqa: F811
                           monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYMENT_DUE_HOURS", "2")
    sid = save(client, pg, price_mnt=1000)["id"]
    clock.at(2)
    assert card_service(client, sid)["payment_status"] == "unpaid"
    assert client.get("/payments/receivables").json()["due_hours"] == 2


def test_old_services_have_no_status(client: TestClient, clock: Clock) -> None:  # noqa: F811
    """Sample services were saved before 013 (payment_tracked false): null, and not counted."""
    clock.at(24 * 365)
    card = client.get("/vehicles/1").json()
    assert all(s["payment_status"] is None for s in card["history"])
    assert client.get("/payments/receivables").json()["count"] == 0


def test_server_timezone_does_not_matter(client: TestClient, pg: Connection, clock: Clock) -> None:  # noqa: F811
    """created_at stored by a session in UTC, "now" in UB: still exactly 24 h."""
    sid = save(client, pg, price_mnt=5000)["id"]
    pg.execute(text("SET LOCAL TIME ZONE 'UTC'"))
    pg.execute(text("UPDATE service_records SET created_at = '2026-09-30 02:00:00' WHERE id = :id"), {"id": sid})
    clock.at(23.9)
    assert card_service(client, sid)["payment_status"] == "pending"
    clock.at(24)
    assert card_service(client, sid)["payment_status"] == "unpaid"


# ---------------------------------------------------------------- POST /services/{id}/payment


def test_paid_then_undo(client: TestClient, pg: Connection, clock: Clock) -> None:  # noqa: F811
    sid = save(client, pg, price_mnt=80000)["id"]
    clock.at(0.2)
    body = pay(client, sid, "paid").json()
    assert body["payment_status"] == "paid"
    assert datetime.fromisoformat(body["paid_at"]) == SAVED + timedelta(hours=0.2)
    clock.at(0.3)  # a second tap keeps the first time
    assert pay(client, sid, "paid").json()["paid_at"] == body["paid_at"]
    undone = pay(client, sid, "undo_paid").json()
    assert (undone["payment_status"], undone["paid_at"]) == ("pending", None)  # still inside the 24 h
    clock.at(25)
    assert card_service(client, sid)["payment_status"] == "unpaid"            # undo after 24 h -> «Авлага»
    assert pay(client, sid, "undo_paid").json()["payment_status"] == "unpaid"  # idempotent


def test_unpaid_pressed_then_paid(client: TestClient, pg: Connection, clock: Clock) -> None:  # noqa: F811
    sid = save(client, pg, price_mnt=60000)["id"]
    clock.at(0.1)
    marked = pay(client, sid, "unpaid").json()
    assert (marked["payment_status"], marked["amount_due"]) == ("unpaid", 60000.0)
    first = marked["marked_unpaid_at"]
    clock.at(5)
    assert pay(client, sid, "unpaid").json()["marked_unpaid_at"] == first  # idempotent
    clock.at(200)
    paid = pay(client, sid, "paid").json()
    assert (paid["payment_status"], paid["marked_unpaid_at"]) == ("paid", first)  # history kept


def test_unpaid_corrects_a_paid(client: TestClient, pg: Connection, clock: Clock) -> None:  # noqa: F811
    sid = save(client, pg, price_mnt=60000)["id"]
    pay(client, sid, "paid")
    body = pay(client, sid, "unpaid").json()
    assert (body["payment_status"], body["paid_at"]) == ("unpaid", None)


def test_an_older_service_can_be_paid(client: TestClient, pg: Connection, clock: Clock) -> None:  # noqa: F811
    """The plate screen pays the truck's OLDER «Авлага» service, not only the newest."""
    old = save(client, pg, price_mnt=70000, service_date="2026-09-01")["id"]
    save(client, pg, price_mnt=80000)  # a newer one the same truck (different day)
    clock.at(30)
    assert pay(client, old, "paid").json()["payment_status"] == "paid"


def test_payment_errors(client: TestClient, pg: Connection, clock: Clock) -> None:  # noqa: F811
    assert pay(client, 999999, "paid").status_code == 404
    old = client.post("/services/3/payment", json={"action": "paid"})  # sample service, saved before 9.16b
    assert old.status_code == 409 and old.json()["detail"]["code"] == "not_tracked"
    sid = save(client, pg, price_mnt=1000)["id"]
    assert pay(client, sid, "pending").status_code == 422
    assert client.post(f"/services/{sid}/payment", json={}).status_code == 422
    zero = save(client, pg, plate="9999 УБА", price_mnt=0)["id"]
    for action in ("unpaid", "undo_paid"):
        response = pay(client, zero, action)
        assert response.status_code == 409 and response.json()["detail"]["code"] == "price_zero"
    assert pay(client, zero, "paid").json()["payment_status"] == "paid"


# ---------------------------------------------------------------- PUT /services/{id}/price


def test_price_can_be_changed_and_cleared(client: TestClient, pg: Connection, clock: Clock) -> None:  # noqa: F811
    sid = save(client, pg)["id"]
    clock.at(30)
    put = client.put(f"/services/{sid}/price", json={"price_mnt": 45000}).json()
    assert (put["price_mnt"], put["payment_status"], put["amount_due"]) == (45000, "unpaid", 45000.0)
    assert client.put(f"/services/{sid}/price", json={"price_mnt": 0}).json()["payment_status"] == "paid"
    cleared = client.put(f"/services/{sid}/price", json={"price_mnt": None}).json()
    assert (cleared["price_mnt"], cleared["payment_status"]) == (None, "unpaid")


def test_price_change_keeps_a_paid_service_paid(client: TestClient, pg: Connection, clock: Clock) -> None:  # noqa: F811
    sid = save(client, pg, price_mnt=1000)["id"]
    pay(client, sid, "paid")
    assert client.put(f"/services/{sid}/price", json={"price_mnt": 2000}).json()["payment_status"] == "paid"


def test_price_errors(client: TestClient, pg: Connection, clock: Clock) -> None:  # noqa: F811
    assert client.put("/services/999999/price", json={"price_mnt": 1}).status_code == 404
    assert client.put("/services/3/price", json={"price_mnt": 1}).status_code == 409
    sid = save(client, pg)["id"]
    for bad in ({}, {"price_mnt": -1}, {"price_mnt": 1.5}, {"price_mnt": 100_000_001}):
        assert client.put(f"/services/{sid}/price", json=bad).status_code == 422


# ---------------------------------------------------------------- GET /payments/receivables


def test_receivables_totals_and_trucks(client: TestClient, pg: Connection, clock: Clock) -> None:  # noqa: F811
    a1 = save(client, pg, plate="1111 УБА", price_mnt=50000, service_date="2026-09-01", driver_phone="99110001")["id"]
    a2 = save(client, pg, plate="1111 УБА", price_mnt=30000, driver_phone="99110002")["id"]
    b1 = save(client, pg, plate="2222 УБА", price_mnt=100000)["id"]
    c1 = save(client, pg, plate="3333 УБА")["id"]                    # no price
    paid = save(client, pg, plate="4444 УБА", price_mnt=70000)["id"]
    save(client, pg, plate="5555 УБА", price_mnt=0)                    # nothing owed
    pay(client, paid, "paid")
    clock.at(1)
    pending = client.get("/payments/receivables").json()
    assert (pending["count"], pending["total_mnt"], pending["trucks"]) == (0, 0, [])
    pay(client, c1, "unpaid")
    clock.at(24)
    body = client.get("/payments/receivables").json()
    assert (body["total_mnt"], body["count"], body["count_no_price"], body["total_trucks"]) == (180000, 4, 1, 3)
    assert [t["identifier"] for t in body["trucks"]] == ["2222 УБА", "1111 УБА", "3333 УБА"]  # biggest first
    truck = body["trucks"][1]
    assert (truck["services"], truck["amount_mnt"], truck["services_no_price"]) == (2, 80000, 0)
    assert (truck["service_ids"], truck["oldest_service_date"]) == ([a1, a2], "2026-09-01")
    assert truck["driver_phone"] == "99110002"                         # the newest «Авлага» service's phone
    assert body["trucks"][2]["services_no_price"] == 1
    assert datetime.fromisoformat(body["trucks"][2]["oldest_unpaid_since"]) == SAVED + timedelta(hours=1)
    assert body["trucks"][0]["service_ids"] == [b1]
    assert client.get("/payments/receivables", params={"limit": 1}).json()["total_trucks"] == 3
    assert len(client.get("/payments/receivables", params={"limit": 1}).json()["trucks"]) == 1
    assert client.get("/payments/receivables", params={"limit": 0}).status_code == 422


def test_receivables_is_read_only(client: TestClient) -> None:  # noqa: F811
    assert client.post("/payments/receivables").status_code == 405


# ---------------------------------------------------------------- lookup + search


def test_lookup_and_search_show_the_status(client: TestClient, pg: Connection, clock: Clock) -> None:  # noqa: F811
    sid = save(client, pg, price_mnt=60000)["id"]
    clock.at(24)
    card = client.get("/vehicles/lookup", params={"q": "4321УБД"}).json()["vehicles"][0]
    assert (card["last_service"]["id"], card["last_service"]["payment_status"]) == (sid, "unpaid")
    found = client.get("/vehicles/search", params={"payment_status": "unpaid"}).json()["vehicles"]
    assert [v["identifier"] for v in found] == ["4321 УБД"]
    clock.at(1)
    assert client.get("/vehicles/search", params={"payment_status": "pending"}).json()["total"] == 1
