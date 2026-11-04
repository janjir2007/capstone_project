"""Tests for task 9.6b-4: Artlab payments in the API (read only).

Card history / search rows get payment_status, amount_due, match_confidence; GET /vehicles/search
gets ?payment_status=; GET /payments/unpaid and GET /payments/sync-status.
Postgres (sample data + migrations up to 009, TODAY = 2026-09-30, tests/test_api_data.py);
SKIPPED without a database. Artlab rows below are SYNTHETIC.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, text

from src.api.config import DEFAULT_UNPAID_LOOKBACK_DAYS, ConfigError, unpaid_lookback_days
from src.artlab.sync import SyncConfig
from tests.test_api_data import client, pg  # noqa: F401  (fixtures)

BIG_ID = 104400000000000001  # Artlab ids exceed 2^53 (notes §8c)


def connect_sync(pg: Connection) -> None:  # noqa: F811
    """One successful bills run = payments connected."""
    pg.execute(text("INSERT INTO sync_runs (kind, started_at, finished_at, ok, bills_seen) "
                    "VALUES ('bills', '2026-09-30 08:00+08', '2026-09-30 08:01+08', true, 5)"))


def add_bill(pg: Connection, artlab_id: int, day: str, status: str, *, service_id: int | None = None,  # noqa: F811
             confidence: str | None = None, note: str | None = None, credit: float = 0,
             gross: float | None = 80000, txn: str | None = None, plates=(), phones=()) -> None:
    pg.execute(text(
        "INSERT INTO artlab_bills (artlab_id, bill_date, bill_type, bill_status, total_gross, credit_amount, "
        "plates, phones, service_id, match_confidence, match_note, payment_status, paid_by_txn) "
        "VALUES (:id, :day, 'SALE', 'COMPLETE', :gross, :credit, :plates, :phones, :sid, :conf, :note, :st, :txn)"),
        dict(id=artlab_id, day=day, gross=gross, credit=credit, plates=list(plates), phones=list(phones),
             sid=service_id, conf=confidence, note=note if service_id is None else None, st=status, txn=txn))


def seed(pg: Connection) -> None:  # noqa: F811
    """Vehicle 1, service 3 (2026-08-10): a paid oil receipt + an unpaid filter receipt (credit 60,000).
    Vehicle 3, service 6 (2026-09-20): paid later by a transfer. One unpaid receipt links to nothing."""
    connect_sync(pg)
    pg.execute(text("INSERT INTO artlab_transfers (txn_key, txn_date, account_code, amount) "
                    "VALUES ('t1', '2026-09-25', '127000000001', 90000)"))
    add_bill(pg, 11, "2026-08-10", "paid", service_id=3, confidence="both")
    add_bill(pg, 12, "2026-08-11", "unpaid", service_id=3, confidence="phone", credit=60000)
    add_bill(pg, 13, "2026-09-20", "paid_later", service_id=6, confidence="both", credit=90000, txn="t1")
    add_bill(pg, BIG_ID, "2026-09-25", "unpaid", note="multiple", credit=45000.5, gross=None,
             plates=["1234УБА", "5678УНА"], phones=["99112233"])


def service(card: dict, sid: int) -> dict:
    return next(s for s in card["history"] if s["id"] == sid)


# ---------------------------------------------------------------- not connected


def test_before_the_first_sync_everything_is_null(client: TestClient) -> None:  # noqa: F811
    card = client.get("/vehicles/1").json()
    assert all(s["payment_status"] is None and s["amount_due"] is None and s["match_confidence"] is None
               for s in card["history"])
    assert client.get("/payments/unpaid").json() == {"connected": False, "total": 0, "total_due": 0, "items": []}
    assert client.get("/payments/sync-status").json() == {"connected": False, "runs": []}
    assert client.get("/vehicles/search", params={"payment_status": "unknown"}).json()["total"] == 0


def test_a_failed_first_sync_is_not_connected(client: TestClient, pg: Connection) -> None:  # noqa: F811
    pg.execute(text("INSERT INTO sync_runs (kind, finished_at, ok, error_class) VALUES ('bills', now(), false, 'ArtlabError')"))
    assert client.get("/vehicles/1").json()["history"][0]["payment_status"] is None
    status = client.get("/payments/sync-status").json()
    assert status["connected"] is False and status["runs"][0]["error_class"] == "ArtlabError"


# ---------------------------------------------------------------- card


def test_card_history_rolls_up_receipts_per_service(client: TestClient, pg: Connection) -> None:  # noqa: F811
    seed(pg)
    card = client.get("/vehicles/1").json()
    s3 = service(card, 3)
    assert (s3["payment_status"], s3["amount_due"], s3["match_confidence"]) == ("unpaid", 60000.0, "phone")
    assert card["last_service"]["id"] == 3 and card["last_service"]["payment_status"] == "unpaid"
    for sid in (1, 2):  # no receipt linked -> unknown («Тодорхойгүй»)
        assert (service(card, sid)["payment_status"], service(card, sid)["amount_due"]) == ("unknown", None)
    s6 = service(client.get("/vehicles/3").json(), 6)
    assert (s6["payment_status"], s6["amount_due"], s6["match_confidence"]) == ("paid_later", None, "both")


def test_lookup_cards_carry_the_same_fields(client: TestClient, pg: Connection) -> None:  # noqa: F811
    seed(pg)
    card = client.get("/vehicles/lookup", params={"q": "1234 УБА"}).json()["vehicles"][0]
    assert service(card, 3)["payment_status"] == "unpaid"


# ---------------------------------------------------------------- search


def ids(body: dict) -> set[int]:
    return {row["id"] for row in body["vehicles"]}


def test_search_filter_by_payment_status(client: TestClient, pg: Connection) -> None:  # noqa: F811
    seed(pg)
    assert ids(client.get("/vehicles/search", params={"payment_status": "unpaid"}).json()) == {1}
    assert ids(client.get("/vehicles/search", params={"payment_status": "paid_later"}).json()) == {3}
    assert client.get("/vehicles/search", params={"payment_status": "paid"}).json()["total"] == 0
    unknown = ids(client.get("/vehicles/search", params={"payment_status": "unknown"}).json())
    assert 1 in unknown and 3 not in unknown                      # vehicle 1 also has services 1, 2
    assert client.get("/vehicles/search", params={"payment_status": "late"}).status_code == 422


def test_search_rows_and_excel_services_carry_payment(client: TestClient, pg: Connection) -> None:  # noqa: F811
    seed(pg)
    body = client.get("/vehicles/search", params={"payment_status": "unpaid", "with_services": True}).json()
    row = body["vehicles"][0]
    assert row["last_service"]["payment_status"] == "unpaid"
    assert [(s["id"], s["payment_status"]) for s in row["services"]] == [(3, "unpaid")]  # only passing services


def test_payment_filter_combines_with_other_service_filters(client: TestClient, pg: Connection) -> None:  # noqa: F811
    seed(pg)
    params = {"payment_status": "unpaid", "date_to": "2026-08-01"}  # service 3 (unpaid) is on 08-10
    assert client.get("/vehicles/search", params=params).json()["total"] == 0


# ---------------------------------------------------------------- GET /payments/unpaid


def test_unpaid_list_oldest_first_with_truck_or_receipt_data(client: TestClient, pg: Connection) -> None:  # noqa: F811
    seed(pg)
    body = client.get("/payments/unpaid").json()
    assert (body["connected"], body["total"], body["total_due"]) == (True, 2, 105000.5)
    linked, unlinked = body["items"]
    assert linked == {
        "artlab_id": "12", "bill_date": "2026-08-11", "days_waiting": 50, "amount_due": 60000.0,
        "total_gross": 80000.0, "match_confidence": "phone", "match_note": None, "service_id": 3,
        "vehicle_id": 1, "identifier": linked["identifier"], "company_name": linked["company_name"],
        "plates": [], "phones": [],
    }
    assert linked["identifier"] and linked["company_name"]
    assert unlinked["artlab_id"] == str(BIG_ID)                   # exact, as a string
    assert (unlinked["service_id"], unlinked["vehicle_id"], unlinked["match_note"]) == (None, None, "multiple")
    assert (unlinked["plates"], unlinked["phones"], unlinked["total_gross"]) == (["1234УБА", "5678УНА"], ["99112233"], None)
    assert unlinked["days_waiting"] == 5


def test_unpaid_lookback_setting() -> None:
    """9.12-3: ARTLAB_UNPAID_LOOKBACK_DAYS default 90, same as the sync; a bad value stops the API."""
    assert unpaid_lookback_days({}) == DEFAULT_UNPAID_LOOKBACK_DAYS == SyncConfig.unpaid_lookback_days == 90
    assert unpaid_lookback_days({"ARTLAB_UNPAID_LOOKBACK_DAYS": " 30 "}) == 30
    for raw in ("0", "-5", "abc", "1.5"):
        with pytest.raises(ConfigError, match="ARTLAB_UNPAID_LOOKBACK_DAYS"):
            unpaid_lookback_days({"ARTLAB_UNPAID_LOOKBACK_DAYS": raw})


def test_unpaid_list_only_within_lookback(client: TestClient, pg: Connection, monkeypatch) -> None:  # noqa: F811
    """9.12-3: bills older than ARTLAB_UNPAID_LOOKBACK_DAYS (default 90) are not listed, linked or
    not: a 780-day-old receipt without a plate is left out, 90 days is still in, 91 is out."""
    monkeypatch.delenv("ARTLAB_UNPAID_LOOKBACK_DAYS", raising=False)
    seed(pg)
    add_bill(pg, 21, "2024-08-11", "unpaid", note="none", credit=10000)   # 780 days before TODAY
    add_bill(pg, 22, "2026-07-02", "unpaid", note="none", credit=20000)   # 90 days
    add_bill(pg, 23, "2026-07-01", "unpaid", note="none", credit=30000)   # 91 days
    body = client.get("/payments/unpaid").json()
    assert [i["artlab_id"] for i in body["items"]] == ["22", "12", str(BIG_ID)]
    assert (body["total"], body["total_due"]) == (3, 125000.5)                # totals skip old bills too
    monkeypatch.setenv("ARTLAB_UNPAID_LOOKBACK_DAYS", "10")
    assert [i["artlab_id"] for i in client.get("/payments/unpaid").json()["items"]] == [str(BIG_ID)]


def test_unpaid_limit_keeps_the_totals(client: TestClient, pg: Connection) -> None:  # noqa: F811
    seed(pg)
    body = client.get("/payments/unpaid", params={"limit": 1}).json()
    assert (body["total"], body["total_due"], len(body["items"])) == (2, 105000.5, 1)
    assert client.get("/payments/unpaid", params={"limit": 0}).status_code == 422


# ---------------------------------------------------------------- GET /payments/sync-status


def test_sync_status_latest_run_per_kind_and_account(client: TestClient, pg: Connection) -> None:  # noqa: F811
    connect_sync(pg)
    for started, ok, seen in (("2026-09-29 10:15+08", True, 3), ("2026-09-30 00:15+08", True, 0),
                              ("2026-09-30 02:15+08", True, 0)):
        pg.execute(text("INSERT INTO sync_runs (kind, account_code, started_at, finished_at, ok, transfers_seen) "
                        "VALUES ('acc_txn', '127000000001', :s, :s, :ok, :n)"), dict(s=started, ok=ok, n=seen))
    pg.execute(text("INSERT INTO sync_runs (kind, account_code, started_at, finished_at, ok, transfers_seen) "
                    "VALUES ('nightly', '127000000001', '2026-09-30 02:30+08', '2026-09-30 02:31+08', true, 0)"))
    pg.execute(text("INSERT INTO sync_runs (kind, started_at, finished_at, ok) VALUES "
                    "('nightly', '2026-09-29 02:30+08', '2026-09-29 02:40+08', true), "
                    "('nightly', '2026-09-30 02:30+08', '2026-09-30 02:35+08', false)"))
    pg.execute(text("UPDATE sync_runs SET error_class = 'ArtlabError' WHERE kind = 'nightly' AND NOT ok"))
    body = client.get("/payments/sync-status").json()
    assert body["connected"] is True
    runs = {(r["kind"], r["account_code"]): r for r in body["runs"]}
    assert set(runs) == {("bills", None), ("nightly", None), ("acc_txn", "127000000001")}
    nightly = runs[("nightly", None)]
    assert (nightly["ok"], nightly["error_class"]) == (False, "ArtlabError")
    assert at(nightly["last_ok_at"]) == at("2026-09-29T02:40:00+08:00")  # the earlier, successful night
    account = runs[("acc_txn", "127000000001")]
    assert at(account["started_at"]) == at("2026-09-30T02:30:00+08:00")  # the nightly per-account row is latest
    assert account["zero_row_streak"] == 3                        # 00:15, 02:15, nightly 02:30; 3 rows before
    assert runs[("bills", None)]["zero_row_streak"] is None


def at(value: str) -> datetime:
    """Compare instants, not text: the database answers in its own time zone (UB in Docker)."""
    return datetime.fromisoformat(value)


# ---------------------------------------------------------------- read only


def test_payments_routes_are_read_only(client: TestClient) -> None:  # noqa: F811
    for path in ("/payments/unpaid", "/payments/sync-status"):
        for method in ("post", "put", "patch", "delete"):
            assert getattr(client, method)(path).status_code == 405, (method, path)
