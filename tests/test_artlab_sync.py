"""Tests for task 9.6b-3: src/artlab/sync.py (+ migration 009).

A fake Artlab (no network) serves SYNTHETIC bills / acc-txn reports; the database is a throwaway
schema (schema.sql + sample data + migrations 001–009) inside a transaction that is rolled back.
Needs a running PostgreSQL (``docker compose up -d db``); otherwise the DB tests are SKIPPED.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import uuid
from collections.abc import Iterator
from datetime import date

import psycopg
import pytest

from scripts import migrate as M
from src.artlab import sync as Y
from src.artlab.client import ArtlabClient, ArtlabError, artlab_settings
from tests.test_migrate import SQL_DIR
from tests.test_schema import database_url

D = date(2026, 10, 15)
TOKEN = "Bearer sync.test.token"
ACC_A, ACC_B = "127000000001", "111000000002"


def bill(i: int, day: str, desc: str | None, payments: list[dict], typ: str = "SALE_VAT") -> dict:
    return {"id": i, "num": "N", "billDate": day, "type": typ, "status": "COMPLETE",
            "description": desc, "totalGross": 80000, "payments": payments}


CASH = [{"type": "CASH", "amount": 80000}]
MIXED = [{"type": "CASH", "amount": 20000}, {"type": "LOAN", "amount": 60000}]
BILLS = [
    bill(1, "2026-10-15", "4821 ТЭК 9911 2233", CASH),          # links by plate + phone
    bill(2, "2026-10-14", "утас 9911-2233", MIXED, "SALE"),     # links by phone, unpaid
    bill(3, "2026-10-15", "4821 ТЭК", CASH, "PURCHASE"),        # not a sale: skipped
    bill(4, "2026-10-15", "5555 ВВВ 8800 1122", CASH),          # no such service: unlinked
    {"id": None, "billDate": "2026-10-15", "type": "SALE", "status": "COMPLETE"},  # malformed
]


class FakeArtlab:
    """Serves login, paged + date-filtered bills, and acc-txn per account. Records calls."""

    def __init__(self, bills: list[dict], acc_rows: dict[str, int] | None = None,
                 fail: set[str] | None = None) -> None:
        self.bills, self.acc_rows, self.fail = bills, acc_rows or {}, fail or set()
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, method, url, headers, body):
        parsed = urllib.parse.urlparse(url)
        path = parsed.path.removeprefix("/v2")
        params = dict(urllib.parse.parse_qsl(parsed.query))
        self.calls.append((method, path, params if method == "GET" else json.loads(body)))
        if path == "/auth/login":
            return 200, {"Authorization": TOKEN}, b'{"connId": 1}'
        if path == "/pos/bills":
            if "bills" in self.fail:
                return 500, {}, b"{}"
            rows = [b for b in self.bills
                    if params.get("from", "0") <= str(b.get("billDate")) <= params.get("to", "9")]
            off, lim = int(headers.get("X-Offset", 0)), int(headers.get("X-Limit", 25))
            return 200, {}, json.dumps({"value": rows[off:off + lim], "success": True}).encode()
        if path == "/report/acc-txn":
            account = json.loads(body)["accountCodes"][0]
            if account in self.fail:
                return 500, {}, b"{}"
            rows = [{"n": i} for i in range(self.acc_rows.get(account, 0))]
            return 200, {}, json.dumps({"value": rows, "success": True}).encode()
        return 404, {}, b"{}"


def client_for(fake: FakeArtlab) -> ArtlabClient:
    client = ArtlabClient("https://artlab.test/v2", send=fake, pause_s=0)
    client.login("u", "p")
    return client


def cfg(**over) -> Y.SyncConfig:
    base = dict(credit_types=frozenset({"LOAN"}), bank_accounts=(ACC_A,), zero_row_warn_runs=3)
    base.update(over)
    return Y.SyncConfig(**base)


@pytest.fixture
def pg() -> Iterator[psycopg.Connection]:
    """Throwaway schema at migration 009 + one synthetic truck 4821ТЭК serviced on D (phone 99112233)."""
    try:
        conn = psycopg.connect(database_url(), connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL not reachable (run `docker compose up -d db`)")
    schema = f"test_sync_{uuid.uuid4().hex[:8]}"
    conn.execute(f"CREATE SCHEMA {schema}")
    conn.execute(f"SET search_path TO {schema}")
    conn.execute((SQL_DIR / "schema.sql").read_text(encoding="utf-8"))
    conn.execute((SQL_DIR / "sample_data.sql").read_text(encoding="utf-8"))
    M.ensure_table(conn)
    for m in M.find_migrations():
        M.apply_one(conn, m)
    vid = conn.execute(
        "INSERT INTO vehicles (company_id, identifier_type, identifier, plate_normalized) "
        "VALUES (1, 'plate', '4821 ТЭК', '4821ТЭК') RETURNING id").fetchone()[0]
    conn.execute(
        "INSERT INTO service_records (vehicle_id, service_date, odometer_km, oil_grade, liters, driver_phone) "
        "VALUES (%s, %s, 100000, '15W-40', 30, '99112233')", (vid, D))
    yield conn
    conn.rollback()
    conn.close()


def bills_table(conn) -> dict[int, tuple]:
    rows = conn.execute("SELECT artlab_id, match_confidence, match_note, payment_status, credit_amount "
                        "FROM artlab_bills ORDER BY artlab_id").fetchall()
    return {r[0]: r[1:] for r in rows}


def runs(conn) -> list[tuple]:
    return conn.execute("SELECT kind, account_code, ok, bills_seen, transfers_seen, error_class "
                        "FROM sync_runs ORDER BY id").fetchall()


# ---------------------------------------------------------------- settings (no DB)


def test_sync_config_defaults_and_values():
    c = Y.sync_config({})
    assert (c.bank_accounts, c.sync_days, c.acc_txn_days, c.unpaid_lookback_days, c.zero_row_warn_runs) \
        == ((), 3, 2, 90, 12)
    c = Y.sync_config({"ARTLAB_BANK_ACCOUNTS": f" {ACC_A}, {ACC_B} ", "ARTLAB_ZERO_ROW_WARN_RUNS": "4"})
    assert c.bank_accounts == (ACC_A, ACC_B) and c.zero_row_warn_runs == 4


@pytest.mark.parametrize("env", [{"ARTLAB_BANK_ACCOUNTS": "12-34"}, {"ARTLAB_SYNC_DAYS": "0"},
                                 {"ARTLAB_ZERO_ROW_WARN_RUNS": "x"}])
def test_sync_config_rejects_bad_values(env):
    with pytest.raises(ArtlabError):
        Y.sync_config(env)


def test_artlab_settings_reads_only_artlab_keys(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(f"POSTGRES_PASSWORD=secret\nARTLAB_BANK_ACCOUNTS={ACC_A}\nexport ARTLAB_SYNC_DAYS=5\n")
    monkeypatch.setenv("ARTLAB_SYNC_DAYS", "7")
    values = artlab_settings(env)
    assert values["ARTLAB_BANK_ACCOUNTS"] == ACC_A and values["ARTLAB_SYNC_DAYS"] == "7"
    assert "POSTGRES_PASSWORD" not in values


def test_main_fails_cleanly_without_credentials(tmp_path, monkeypatch, caplog):
    for key in ("ARTLAB_URL", "ARTLAB_USER", "ARTLAB_PASS"):
        monkeypatch.delenv(key, raising=False)
    with caplog.at_level(logging.ERROR, logger="artlab.sync"):
        assert Y.main(["--kind", "bills", "--env", str(tmp_path / "none.env")]) == 1
    assert "Missing in .env" in caplog.text


# ---------------------------------------------------------------- bills run


def test_bills_run_parses_matches_and_records(pg, caplog):
    fake = FakeArtlab(BILLS)
    with caplog.at_level(logging.INFO, logger="artlab.sync"):
        Y.run("bills", client_for(fake), pg, cfg(), D)
    assert bills_table(pg) == {
        1: ("both", None, "paid", 0),
        2: ("phone", None, "unpaid", 60000),
        4: (None, "none", "paid", 0),
    }
    assert runs(pg) == [("bills", None, True, 3, 0, None)]
    bill_call = next(p for m, path, p in fake.calls if path == "/pos/bills")
    assert (bill_call["from"], bill_call["to"]) == ("2026-10-13", "2026-10-15")  # 3 days
    assert "1 rows without a valid id" in caplog.text
    for secret in ("ТЭК", "99112233", "9911", "sync.test.token"):
        assert secret not in caplog.text


def test_bills_run_is_idempotent_and_keeps_paid_later(pg):
    Y.run("bills", client_for(FakeArtlab(BILLS)), pg, cfg(), D)
    first_seen = pg.execute("SELECT first_seen_at FROM artlab_bills WHERE artlab_id = 2").fetchone()
    pg.execute("INSERT INTO artlab_transfers (txn_key, txn_date, account_code, amount) "
               "VALUES ('t1', '2026-10-16', %s, 60000)", (ACC_A,))
    pg.execute("UPDATE artlab_bills SET payment_status = 'paid_later', paid_by_txn = 't1' WHERE artlab_id = 2")
    Y.run("bills", client_for(FakeArtlab(BILLS)), pg, cfg(), D)
    assert pg.execute("SELECT count(*) FROM artlab_bills").fetchone() == (3,)
    assert pg.execute("SELECT payment_status, paid_by_txn FROM artlab_bills WHERE artlab_id = 2"
                      ).fetchone() == ("paid_later", "t1")          # Artlab still says LOAN
    assert pg.execute("SELECT first_seen_at FROM artlab_bills WHERE artlab_id = 2").fetchone() == first_seen


def test_bills_run_failure_is_recorded_and_raised(pg):
    with pytest.raises(ArtlabError):
        Y.run("bills", client_for(FakeArtlab(BILLS, fail={"bills"})), pg, cfg(), D)
    assert runs(pg) == [("bills", None, False, 0, 0, "ArtlabError")]
    assert bills_table(pg) == {}


# ---------------------------------------------------------------- nightly


def test_nightly_relinks_a_bill_once_the_service_exists(pg):
    late = [bill(7, "2026-10-15", "7777 ННН", CASH)]
    Y.run("bills", client_for(FakeArtlab(late)), pg, cfg(), D)
    assert bills_table(pg)[7][:2] == (None, "none")
    vid = pg.execute("INSERT INTO vehicles (company_id, identifier_type, identifier, plate_normalized) "
                     "VALUES (1, 'plate', '7777ННН', '7777ННН') RETURNING id").fetchone()[0]
    pg.execute("INSERT INTO service_records (vehicle_id, service_date, odometer_km, oil_grade, liters) "
               "VALUES (%s, '2026-10-16', 5000, '15W-40', 30)", (vid,))
    Y.run("nightly", client_for(FakeArtlab([])), pg, cfg(), date(2026, 10, 18))
    assert bills_table(pg)[7][:2] == ("plate", None)


def test_nightly_window_goes_back_to_oldest_unpaid_within_lookback(pg):
    Y.run("bills", client_for(FakeArtlab([bill(9, "2026-09-01", "x", MIXED, "SALE")])), pg,
          cfg(sync_days=60), D)
    fake = FakeArtlab([])
    Y.run("nightly", client_for(fake), pg, cfg(unpaid_lookback_days=90), D)
    call = next(p for m, path, p in fake.calls if path == "/pos/bills")
    assert call["from"] == "2026-09-01"
    fake = FakeArtlab([])
    Y.run("nightly", client_for(fake), pg, cfg(unpaid_lookback_days=10), D)
    call = next(p for m, path, p in fake.calls if path == "/pos/bills")
    assert call["from"] == "2026-10-05"                               # capped at the lookback
    acc = next(p for m, path, p in fake.calls if path == "/report/acc-txn")
    assert acc["startDate"] == "2026-10-05"
    kinds = [r[:3] for r in runs(pg)]
    assert ("nightly", None, True) in kinds and ("nightly", ACC_A, True) in kinds


# ---------------------------------------------------------------- acc-txn


def test_acc_txn_counts_rows_per_account(pg):
    fake = FakeArtlab([], acc_rows={ACC_A: 4, ACC_B: 0})
    Y.run("acc_txn", client_for(fake), pg, cfg(bank_accounts=(ACC_A, ACC_B)), D)
    assert runs(pg) == [("acc_txn", ACC_A, True, 0, 4, None), ("acc_txn", ACC_B, True, 0, 0, None)]
    body = next(p for m, path, p in fake.calls if path == "/report/acc-txn")
    assert body == {"accountCodes": [ACC_A], "startDate": "2026-10-14", "endDate": "2026-10-15"}
    assert pg.execute("SELECT count(*) FROM artlab_transfers").fetchone() == (0,)  # parser is a stub


def test_zero_row_warning_after_n_runs_in_a_row(pg, caplog):
    fake = FakeArtlab([], acc_rows={ACC_A: 0, ACC_B: 2})
    config = cfg(bank_accounts=(ACC_A, ACC_B), zero_row_warn_runs=3)
    for n in range(1, 4):
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="artlab.sync"):
            Y.run("acc_txn", client_for(fake), pg, config, D)
        warned = [r.getMessage() for r in caplog.records if "0 rows in the last 3 runs" in r.getMessage()]
        assert len(warned) == (1 if n == 3 else 0), n           # only after the 3rd empty run
        assert all(ACC_A in w and ACC_B not in w for w in warned)  # never for the account with rows


def test_one_failing_account_does_not_hide_the_others(pg, caplog):
    fake = FakeArtlab([], acc_rows={ACC_B: 1}, fail={ACC_A})
    with pytest.raises(ArtlabError), caplog.at_level(logging.ERROR, logger="artlab.sync"):
        Y.run("acc_txn", client_for(fake), pg, cfg(bank_accounts=(ACC_A, ACC_B)), D)
    assert runs(pg) == [("acc_txn", ACC_A, False, 0, 0, "ArtlabError"), ("acc_txn", ACC_B, True, 0, 1, None)]


def test_failed_runs_break_the_zero_row_streak(pg):
    for _ in range(2):
        Y.run("acc_txn", client_for(FakeArtlab([])), pg, cfg(), D)
    with pytest.raises(ArtlabError):
        Y.run("acc_txn", client_for(FakeArtlab([], fail={ACC_A})), pg, cfg(), D)
    assert not Y.zero_row_streak(pg, ACC_A, 3)


def test_unknown_kind_is_refused(pg):
    with pytest.raises(ValueError):
        Y.run("hourly", client_for(FakeArtlab([])), pg, cfg(), D)
    assert runs(pg) == []


def test_migration_009_down_then_up(pg):
    down = (SQL_DIR / "migrations" / "009_sync_runs_account.down.sql").read_text(encoding="utf-8")
    up = (SQL_DIR / "migrations" / "009_sync_runs_account.up.sql").read_text(encoding="utf-8")
    pg.execute(down)
    cols = {r[0] for r in pg.execute("SELECT column_name FROM information_schema.columns "
                                     "WHERE table_schema = current_schema() AND table_name = 'sync_runs'")}
    assert "account_code" not in cols
    pg.execute(up)
    pg.execute("SAVEPOINT s")
    with pytest.raises(psycopg.errors.CheckViolation):
        pg.execute("INSERT INTO sync_runs (kind, account_code) VALUES ('acc_txn', '12-3')")
    pg.execute("ROLLBACK TO SAVEPOINT s")
