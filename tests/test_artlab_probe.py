"""Tests for scripts/artlab_probe.py summaries (tasks 9.6a, 9.6b-1). No network: the fake Artlab
from tests/test_artlab_client.py stands in. Client safety tests live in test_artlab_client.py."""

from __future__ import annotations

import base64
import json
import urllib.parse

from scripts.artlab_probe import bill_summary, field_summary, payment_type_label, run, token_lifetime
from tests.test_artlab_client import FakeArtlab, make_client, synthetic_bill

def test_only_post_ever_sent_is_login():
    fake = FakeArtlab([synthetic_bill(i) for i in range(12)])
    run(make_client(fake), "2026-10-01", "2026-10-31")
    methods = {(m, urllib.parse.urlparse(u).path) for m, u, _ in fake.calls if m != "GET"}
    assert methods == {("POST", "/v2/auth/login")}


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


def test_text_shape_masks_every_letter_and_digit():
    from scripts.artlab_probe import text_shape

    assert text_shape("1234 УБА 9911-2233") == "9999 ААА 9999-9999"
    assert text_shape("Bat ӨҮ") == "aaa АА"
    assert text_shape("x" * 25) == "a" * 20 + "…"


def test_run_acc_txn_summarizes_without_values():
    from scripts.artlab_probe import run_acc_txn

    summary = run_acc_txn(make_client(FakeArtlab()), ["127000000001"], "2026-06-01", "2026-06-30")
    assert summary["rows_path"] == ".value.rows" and summary["rows"] == 2
    cols = summary["columns"]
    assert cols["amount"] == {"non_empty": 2, "unique": True, "kind": "number", "sum": 30000,
                              "min": -50000, "max": 80000, "negatives": 1}
    assert cols["txnDate"]["kind"] == "date" and cols["id"]["unique"] is True
    assert cols["descr"]["has_plate"] == 1 and cols["descr"]["has_phone"] == 1
    text = json.dumps(summary, ensure_ascii=False)
    assert "УБА" not in text and "99112233" not in text


def test_find_rows_picks_largest_object_list():
    from scripts.artlab_probe import find_rows

    data = {"a": [{"x": 1}], "b": {"c": [{"y": 1}, {"y": 2}]}, "d": [1, 2, 3]}
    assert find_rows(data) == (".b.c", [{"y": 1}, {"y": 2}])
    assert find_rows([{"z": 0}]) == ("$", [{"z": 0}])
    assert find_rows({"x": 1}) == ("", [])


def test_shape_tree_keeps_structure_drops_values():
    from scripts.artlab_probe import shape_tree

    assert shape_tree({"v": [{"name": "Бат", "n": 1}], "ok": True}) == {
        "v": [1, {"name": "str", "n": "int"}], "ok": "bool"}
