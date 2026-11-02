"""Tests for scripts/artlab_probe.py (task 9.6a). No network: a fake sender stands in for Artlab."""

from __future__ import annotations

import base64
import json
import urllib.parse

import pytest

from scripts.artlab_probe import (
    ArtlabClient,
    NotAllowedError,
    bill_summary,
    field_summary,
    find_phones,
    find_plates,
    load_env,
    payment_type_label,
    run,
    token_lifetime,
)

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


# ---------------------------------------------------------------- safety


def test_login_sends_token_unchanged_and_hides_it_from_repr():
    fake = FakeArtlab()
    client = make_client(fake)
    client.get("/auth/check")
    assert fake.calls[-1][2]["Authorization"] == TOKEN  # already "Bearer ...", sent as-is
    assert "abc.def" not in repr(client)


@pytest.mark.parametrize(
    "path", ["/auth/connections/switch/5", "/pos/bills/123", "/gl/save", "/entities", "/auth/login"]
)
def test_get_outside_allow_list_is_refused_before_sending(path):
    fake = FakeArtlab()
    client = make_client(fake)
    n_calls = len(fake.calls)
    with pytest.raises(NotAllowedError):
        client.get(path)
    assert len(fake.calls) == n_calls


def test_only_post_ever_sent_is_login():
    fake = FakeArtlab([synthetic_bill(i) for i in range(12)])
    run(make_client(fake), "2026-10-01", "2026-10-31")
    methods = {(m, urllib.parse.urlparse(u).path) for m, u, _ in fake.calls if m != "GET"}
    assert methods == {("POST", "/v2/auth/login")}


def test_failed_login_exits_without_token():
    client = ArtlabClient(BASE, send=lambda *a: (401, {}, b"{}"), pause_s=0)
    with pytest.raises(SystemExit, match="HTTP 401"):
        client.login("user", "wrong")


# ---------------------------------------------------------------- env


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
    with pytest.raises(SystemExit) as err:
        load_env(env)
    assert "ARTLAB_USER" in str(err.value) and "topsecret" not in str(err.value)


# ---------------------------------------------------------------- paging


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


# ---------------------------------------------------------------- text + summaries


@pytest.mark.parametrize(
    "text, plates",
    [("1234 УБА солих", ["1234УБА"]), ("1234-уба", ["1234УБА"]), ("1234УБА", ["1234УБА"]),
     ("тос 5000 төг", []), ("", []), ("99112233", [])],
)
def test_find_plates(text, plates):
    assert find_plates(text) == plates


@pytest.mark.parametrize(
    "text, phones",
    [("утас 9911 2233", ["99112233"]), ("99112233", ["99112233"]), ("9911-2233", ["99112233"]),
     ("1234 УБА", []), ("123456789", [])],
)
def test_find_phones(text, phones):
    assert find_phones(text) == phones


def test_payment_type_label_handles_string_and_object():
    assert payment_type_label("CASH") == "CASH"
    assert payment_type_label({"code": "Q", "name": "QPay"}) == "Q / QPay"


def test_bill_summary_counts_without_printing_text():
    bills = [synthetic_bill(i) for i in range(4)]
    summary = bill_summary(bills)
    assert summary["payment_types"]["CASH"] == {"count": 4, "amount_sum": 400.0}
    assert summary["description"] == {"non_empty": 2, "has_plate": 2, "has_phone": 2, "has_both": 2}
    assert "УБА" not in json.dumps(summary, ensure_ascii=False)  # no description text leaks


def test_field_summary_lists_key_paths_not_values():
    summary = field_summary([{"a": "secret", "o": {"b": 1}, "l": [{"c": None}]}])
    assert set(summary) == {"a", "o", "o.b", "l", "l[].c"}
    assert summary["l[].c"]["non_empty"] == 0
    assert "secret" not in json.dumps(summary)


def _jwt(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"Bearer xx.{body}.yy"


def test_token_lifetime_reads_jwt_claims():
    info = token_lifetime(_jwt({"iat": 1_700_000_000, "exp": 1_700_003_600, "sub": "x"}))
    assert info is not None and info["lifetime_min"] == 60.0 and info["claims"] == ["exp", "iat", "sub"]


def test_token_lifetime_none_for_opaque_token():
    assert token_lifetime("Bearer opaque-token") is None


def test_as_list_unwraps_artlab_value_wrapper():
    from scripts.artlab_probe import _as_list

    assert _as_list({"value": [1, 2], "success": True}) == [1, 2]
    assert _as_list([3]) == [3] and _as_list({"success": True}) == []


def test_text_shape_masks_every_letter_and_digit():
    from scripts.artlab_probe import text_shape

    assert text_shape("1234 УБА 9911-2233") == "9999 ААА 9999-9999"
    assert text_shape("Bat ӨҮ") == "aaa АА"
    assert text_shape("x" * 25) == "a" * 20 + "…"
