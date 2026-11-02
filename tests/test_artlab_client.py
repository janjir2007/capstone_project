"""Tests for src/artlab/client.py (tasks 9.6a, 9.6b-1; moved in 9.6b-2): the read-only allow-list,
env loading, paging, the acc-txn body. No network: FakeArtlab stands in for Artlab."""

from __future__ import annotations

import json
import urllib.parse

import pytest

from src.artlab.client import ArtlabClient, ArtlabError, NotAllowedError, as_list, load_env

BASE = "https://artlab.test/v2"


TOKEN = "Bearer abc.def.ghi"


class FakeArtlab:
    """Records every call; serves /auth/login and a list of synthetic bills with paging."""

    def __init__(self, bills: list[dict] | None = None) -> None:
        self.calls: list[tuple[str, str, dict[str, str]]] = []
        self.bills = bills or []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers))
        parsed = urllib.parse.urlparse(url)
        path = parsed.path.removeprefix("/v2")
        if method == "POST" and path == "/auth/login":
            return 200, {"Authorization": TOKEN}, b'{"connId": 1, "type": "api", "userId": 2}'
        if path in ("/pos/bills", "/invoices"):
            if headers.get("X-Summary") == "1":
                return 200, {"X-Total-Records": str(len(self.bills))}, b"[]"
            offset = int(headers.get("X-Offset", 0))
            limit = int(headers.get("X-Limit", 25))
            page = self.bills[offset : offset + limit]
            body = {"value": page, "success": True}  # Artlab's wrapper (seen on the test DB)
            return 200, {"X-Offset-Next": str(offset + limit)}, json.dumps(body).encode()
        if method == "POST" and path == "/report/acc-txn":
            self.acc_body = json.loads(body)
            rows = [{"txnDate": "2026-06-02", "amount": -50000, "descr": "1234 УБА 99112233",
                     "id": 7}, {"txnDate": "2026-06-05", "amount": 80000, "descr": "x", "id": 8}]
            return 200, {}, json.dumps({"value": {"total": 2, "rows": rows}}).encode()
        return 200, {}, b'{"value": true, "success": true}'


def make_client(fake: FakeArtlab) -> ArtlabClient:
    client = ArtlabClient(BASE, send=fake, pause_s=0)
    client.login("user", "secret")
    return client


def synthetic_bill(i: int) -> dict:
    """Fake bill: plate + phone in the description for even ids (no real data)."""
    desc = f"1234 УБА 9911{i:04d}" if i % 2 == 0 else ""
    return {
        "id": i, "num": f"N{i}", "billDate": f"2026-10-{1 + i % 28:02d}", "type": "SALE",
        "status": "COMPLETE", "description": desc,
        "payments": [{"type": "CASH", "amount": 100}, {"type": {"code": "Q", "name": "QPay"}, "amount": 50}],
        "dtls": [{"product": {"code": "P1"}, "qty": 1}],
    }


def test_login_sends_token_unchanged_and_hides_it_from_repr():
    fake = FakeArtlab()
    client = make_client(fake)
    client.get("/auth/check")
    assert fake.calls[-1][2]["Authorization"] == TOKEN  # already "Bearer ...", sent as-is
    assert "abc.def" not in repr(client)


@pytest.mark.parametrize(
    "path",
    ["/auth/connections/switch/5", "/pos/bills/123", "/gl/save", "/entities", "/auth/login",
     "/report/acc-txn", "/pos/paymethods/5"],
)
def test_get_outside_allow_list_is_refused_before_sending(path):
    fake = FakeArtlab()
    client = make_client(fake)
    n_calls = len(fake.calls)
    with pytest.raises(NotAllowedError):
        client.get(path)
    assert len(fake.calls) == n_calls


def test_failed_login_exits_without_token():
    client = ArtlabClient(BASE, send=lambda *a: (401, {}, b"{}"), pause_s=0)
    with pytest.raises(ArtlabError, match="HTTP 401"):
        client.login("user", "wrong")


def test_load_env_reads_file_and_env_overrides(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('# c\nARTLAB_URL="https://x/v2/"\nARTLAB_USER=u\nARTLAB_PASS=p\nOTHER=1\n')
    monkeypatch.setenv("ARTLAB_USER", "from_env")
    for key in ("ARTLAB_URL", "ARTLAB_PASS"):
        monkeypatch.delenv(key, raising=False)
    values = load_env(env)
    assert values == {"ARTLAB_URL": "https://x/v2", "ARTLAB_USER": "from_env", "ARTLAB_PASS": "p"}


def test_load_env_names_missing_keys_not_values(tmp_path, monkeypatch):
    for key in ("ARTLAB_URL", "ARTLAB_USER", "ARTLAB_PASS"):
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / ".env"
    env.write_text("ARTLAB_URL=https://x\nARTLAB_PASS=topsecret\n")
    with pytest.raises(ArtlabError) as err:
        load_env(env)
    assert "ARTLAB_USER" in str(err.value) and "topsecret" not in str(err.value)


def test_fetch_all_walks_pages_and_stops_on_short_page():
    fake = FakeArtlab([synthetic_bill(i) for i in range(12)])
    rows, truncated = make_client(fake).fetch_all("/pos/bills", {}, limit=5)
    assert [r["id"] for r in rows] == list(range(12)) and truncated is False
    offsets = [h.get("X-Offset") for m, _, h in fake.calls if m == "GET"]
    assert offsets == ["0", "5", "10"]


def test_fetch_all_reports_truncation_at_page_cap():
    fake = FakeArtlab([synthetic_bill(i) for i in range(30)])
    rows, truncated = make_client(fake).fetch_all("/pos/bills", {}, limit=5, max_pages=2)
    assert len(rows) == 10 and truncated is True


def test_count_uses_summary_header():
    fake = FakeArtlab([synthetic_bill(i) for i in range(7)])
    assert make_client(fake).count("/pos/bills", {}) == 7


def test_as_list_unwraps_artlab_value_wrapper():
    assert as_list({"value": [1, 2], "success": True}) == [1, 2]
    assert as_list([3]) == [3] and as_list({"success": True}) == []


def test_acc_txn_body_has_exactly_three_keys():
    fake = FakeArtlab()
    client = make_client(fake)
    client.acc_txn(["127000000001"], "2026-06-01", "2026-06-30")
    method, url, headers = fake.calls[-1]
    assert (method, urllib.parse.urlparse(url).path) == ("POST", "/v2/report/acc-txn")
    assert fake.acc_body == {"accountCodes": ["127000000001"], "startDate": "2026-06-01",
                             "endDate": "2026-06-30"}
    assert headers["Authorization"] == TOKEN


@pytest.mark.parametrize(
    "codes, start, end",
    [([], "2026-06-01", "2026-06-30"), (["12a"], "2026-06-01", "2026-06-30"),
     (["1; DROP"], "2026-06-01", "2026-06-30"), (["127"], "June", "2026-06-30")],
)
def test_acc_txn_rejects_bad_input_before_sending(codes, start, end):
    fake = FakeArtlab()
    client = make_client(fake)
    n_calls = len(fake.calls)
    with pytest.raises(ValueError):
        client.acc_txn(codes, start, end)
    assert len(fake.calls) == n_calls


def test_client_has_no_generic_post():
    assert not any(name in dir(ArtlabClient) for name in ("post", "patch", "put", "delete", "request"))


def test_paymethod_paths_are_allowed():
    fake = FakeArtlab()
    client = make_client(fake)
    client.get("/pos/paymethods")
    client.get("/pos/paymethods/types")
    assert [m for m, _, _ in fake.calls] == ["POST", "GET", "GET"]
