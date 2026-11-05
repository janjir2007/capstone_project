"""Tests for scripts/artlab_probe.py summaries (tasks 9.6a, 9.6b-1). No network: the fake Artlab
from tests/test_artlab_client.py stands in. Client safety tests live in test_artlab_client.py."""

from __future__ import annotations

import base64
import json
import urllib.parse

from scripts.artlab_probe import bill_summary, field_summary, payment_type_label, run, token_lifetime
from tests.test_artlab_client import BASE, FakeArtlab, make_client, synthetic_bill

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
    assert summary["payment_types"]["CASH"] == {"count": 4, "amount_sum": "hidden (<5)"}
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
    assert cols["amount"] == {"non_empty": 2, "unique": True, "kind": "number", "sum": "hidden (<5)",
                              "negatives": 1, "digits": [5, 5]}
    assert cols["txnDate"]["kind"] == "date" and cols["id"]["unique"] is True
    assert cols["descr"]["has_plate"] == 1 and cols["descr"]["has_phone"] == 1
    text = json.dumps(summary, ensure_ascii=False)
    assert "УБА" not in text and "99112233" not in text
    assert "80000" not in text and "50000" not in text  # 9.6c-2 (G2): no single transfer amount


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


# ---------------------------------------------------------------- task 9.6c-2: first REAL run safety

import subprocess  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

import scripts.artlab_probe as probe_mod  # noqa: E402
from src.artlab.client import ArtlabClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# Synthetic "personal" values planted everywhere a real DB could hold them. None may reach the output.
SECRETS = [
    "Батболд", "Дорж",            # customer / counterparty names
    "Бат-Эрдэнэ",                 # a person-named terminal
    "УБА", "1234",                # plate (1234 УБА) in a description
    "99112233", "88112233",       # phones (text and number column)
    "5005123456",                 # counterparty bank account (number column)
    "777777", "654321", "4444444", "313131",  # single-customer amounts
    "probe_login_x9", "pw_S3cret_x9", "abc.def.ghi",  # login user, password, token
]


def _bill(i: int, **kw) -> dict:
    bill = {"id": i, "num": f"N{i}", "billDate": "2026-11-0" + str(1 + i % 4), "type": "SALE",
            "status": "COMPLETE", "description": "",
            "terminal": {"code": "T1", "name": "Бат-Эрдэнэ касс", "branch": {"code": "B1", "name": "Дорж"}},
            "payments": [{"type": "CASH", "name": "Бэлэн", "amount": 1000}], "totalGross": 313131}
    bill.update(kw)
    return bill


class DatedFake(FakeArtlab):
    """/pos/bills honours from / to (inclusive, artlab_api_notes §4) and a chosen sort order."""

    def __init__(self, bills: list[dict], order: str = "newest_first") -> None:
        key = {"newest_first": lambda b: b["billDate"], "oldest_first": lambda b: b["billDate"],
               "by_id": lambda b: b["id"]}[order]
        super().__init__(sorted(bills, key=key, reverse=order == "newest_first"))

    def __call__(self, method, url, headers, body):
        parsed = urllib.parse.urlparse(url)
        if parsed.path.removeprefix("/v2") != "/pos/bills":
            return super().__call__(method, url, headers, body)
        q = dict(urllib.parse.parse_qsl(parsed.query))
        everything = self.bills
        self.bills = [b for b in everything
                      if q.get("from", "0000") <= b["billDate"][:10] <= q.get("to", "9999")]
        try:
            return super().__call__(method, url, headers, body)
        finally:
            self.bills = everything


class PrivateFake(DatedFake):
    """A fake REAL database full of personal data, serving every endpoint the probe uses."""

    def __init__(self) -> None:
        bills = [_bill(i) for i in range(6)]
        bills[0]["description"] = "Батболд 1234 УБА 99112233"
        bills[1]["payments"] = [{"type": "LOAN", "name": "Зээл", "amount": 777777}]  # the only LOAN
        super().__init__(bills)

    def __call__(self, method, url, headers, body):
        path = urllib.parse.urlparse(url).path.removeprefix("/v2")
        if path == "/auth/connections":
            self.calls.append((method, url, headers))
            conns = [{"id": 1, "code": "GEO", "name": "Гео Эксперт", "company": {"name": "Гео Эксперт Трейд ХХК"}},
                     {"id": 3, "code": "TEST", "name": "Туршилт", "company": {"name": "Artlab demo"}}]
            return 200, {}, json.dumps({"value": conns, "success": True}).encode()
        if path == "/invoices":
            self.calls.append((method, url, headers))
            inv = [{"id": 1, "invoiceDate": "2026-11-02", "status": "open", "totalGross": 4444444,
                    "description": "Дорж 88112233", "customer": {"code": "C1", "name": "Батболд"}}]
            return 200, {}, json.dumps({"value": inv, "success": True}).encode()
        if path == "/pos/paymethods":
            self.calls.append((method, url, headers))
            rows = [{"id": 1, "name": "Бэлэн", "type": "CASH"}, {"id": 4, "name": "Зээл", "type": "LOAN"}]
            return 200, {}, json.dumps({"value": rows, "success": True}).encode()
        if method == "POST" and path == "/report/acc-txn":
            self.calls.append((method, url, headers))
            rows = [{"id": 7, "txnDate": "2026-11-02", "amount": 654321, "counterAccount": 5005123456,
                     "phone": 88112233, "descr": "Батболд Дорж 1234 УБА"},
                    {"id": 8, "txnDate": "2026-11-03", "amount": 1000, "counterAccount": 5005123456,
                     "phone": 88112233, "descr": "x"}]
            return 200, {}, json.dumps({"value": rows, "success": True}).encode()
        return super().__call__(method, url, headers, body)


def _run_main(monkeypatch, tmp_path, fake, argv):
    monkeypatch.setenv("ARTLAB_URL", BASE)
    monkeypatch.setenv("ARTLAB_USER", "probe_login_x9")
    monkeypatch.setenv("ARTLAB_PASS", "pw_S3cret_x9")
    monkeypatch.setattr(probe_mod, "ArtlabClient", lambda url: ArtlabClient(url, send=fake, pause_s=0))
    return probe_mod.main(["--env", str(tmp_path / "none.env"), *argv])


@pytest.mark.parametrize("section", ["all", "bills", "paymethods", "acc-txn", "months"])
def test_no_personal_value_in_any_probe_output(monkeypatch, tmp_path, capsys, section):
    fake = PrivateFake()
    code = _run_main(monkeypatch, tmp_path, fake,
                     ["--section", section, "--account", "120100", "--from", "2026-11-01", "--to", "2026-11-04"])
    out, err = capsys.readouterr()
    assert code == 0
    json.loads(out)  # the file Ari saves is valid JSON
    for value in SECRETS:
        assert value not in out and value not in err, value


def test_every_request_is_read_only(monkeypatch, tmp_path, capsys):
    fake = PrivateFake()
    _run_main(monkeypatch, tmp_path, fake, ["--section", "all", "--account", "120100"])
    for method, url, _ in fake.calls:
        path = urllib.parse.urlparse(url).path.removeprefix("/v2")
        assert (method == "GET" and path in probe_mod.READ_PATHS) or \
            (method == "POST" and path in ("/auth/login", "/report/acc-txn")), (method, path)


def test_allow_list_unchanged():
    assert probe_mod.READ_PATHS == {
        "/auth/check", "/auth/connections", "/pos/bills", "/pos/bills/types", "/pos/bills/statuses",
        "/invoices", "/pos/paymethods", "/pos/paymethods/types"}
    assert probe_mod.ACC_TXN_PATH == "/report/acc-txn"


def test_active_connection_is_shown_first_on_every_run(monkeypatch, tmp_path, capsys):
    _run_main(monkeypatch, tmp_path, PrivateFake(), ["--section", "paymethods"])
    out, err = capsys.readouterr()
    assert err.splitlines()[0] == ("Artlab connection: GEO Гео Эксперт / Гео Эксперт Трейд ХХК; "
                                   "newest bill 2026-11-04 (sort one_page, bills after it: 0)")
    conn = json.loads(out)["connection"]
    assert [c["current"] for c in conn["connections"]] == [True, False]


def test_unknown_connection_says_not_found():
    line = probe_mod.connection_line({"login_conn_id": "9", "connections": [], "newest_bill_date": None})
    assert "NOT FOUND" in line


def test_small_money_groups_are_hidden_big_ones_shown():
    bills = [_bill(i) for i in range(6)]
    bills[1]["payments"] = [{"type": "LOAN", "amount": 777777}]
    summary = bill_summary(bills)
    assert summary["payment_types"]["LOAN"] == {"count": 1, "amount_sum": "hidden (<5)"}
    assert summary["payment_types"]["CASH"] == {"count": 5, "amount_sum": 5000.0}


def test_extraction_rate_counts_completed_sales_only_per_terminal():
    bills = [
        _bill(1, description="1234 УБА"),                                   # plate
        _bill(2, type="SALE_VAT", description="9911 2233"),                  # phone
        _bill(3, description="тос", terminal={"code": "T2", "branch": {"code": "B1"}}),  # neither
        _bill(4, type="PURCHASE", description="1234 УБА"),                   # not a sale
        _bill(5, status="CANCEL", description="1234 УБА"),                  # not complete
    ]
    sales = bill_summary(bills)["completed_sales"]
    assert (sales["rows"], sales["plate"], sales["phone"], sales["neither"]) == (3, 1, 1, 1)
    assert sales["rate_plate_or_phone"] == 0.667 and sales["meets_sync_bar"] is True
    assert sales["by_terminal"]["terminal T2 / branch B1"]["rate_plate_or_phone"] == 0.0
    assert bill_summary(bills)["by_terminal"] == {"terminal T1 / branch B1": 4, "terminal T2 / branch B1": 1}


def test_sync_bar_not_met_below_half():
    sales = bill_summary([_bill(1, description="1234 УБА"), _bill(2), _bill(3)])["completed_sales"]
    assert sales["rate_plate_or_phone"] == 0.333 and sales["meets_sync_bar"] is False


def test_unexpected_error_prints_class_only(monkeypatch, tmp_path, capsys):
    class Broken(PrivateFake):
        def __call__(self, method, url, headers, body):
            if "/pos/paymethods" in url:
                raise KeyError("Батболд 88112233")
            return super().__call__(method, url, headers, body)

    code = _run_main(monkeypatch, tmp_path, Broken(), ["--section", "paymethods"])
    out, err = capsys.readouterr()
    assert code == 1 and out == ""
    assert "probe failed: KeyError" in err and "Батболд" not in err


def test_refuses_to_print_to_a_terminal(monkeypatch, tmp_path, capsys):
    fake = PrivateFake()
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    assert _run_main(monkeypatch, tmp_path, fake, ["--section", "paymethods"]) == 2
    assert fake.calls == []  # not even a login
    assert "/root/artlab_probe" in capsys.readouterr().err


@pytest.mark.parametrize("arg", [["--account", "12a"], ["--from", "2026/11/01"]])
def test_bad_arguments_stop_before_any_request(monkeypatch, tmp_path, arg):
    fake = PrivateFake()
    with pytest.raises(SystemExit):
        _run_main(monkeypatch, tmp_path, fake, ["--section", "acc-txn", *arg])
    assert fake.calls == []


def test_server_script_saves_only_under_root_artlab_probe():
    script = ROOT / "deploy" / "artlab_probe.sh"
    text = script.read_text()
    assert script.stat().st_mode & 0o111  # executable
    subprocess.run(["bash", "-n", str(script)], check=True)
    assert "OUT_DIR=/root/artlab_probe" in text and "umask 077" in text
    assert "--profile sync run --rm --no-deps -T artlab-sync" in text
    assert "systemctl enable" not in text and "systemctl start" not in text


def test_server_script_rejects_unknown_section():
    result = subprocess.run(["bash", str(ROOT / "deploy" / "artlab_probe.sh"), "all"],
                            capture_output=True, text=True)
    assert result.returncode == 2 and "usage" in result.stderr


# ---------------------------------------------------------------- task 9.6c-2b: plate check, newest date, months

import os  # noqa: E402
from datetime import date  # noqa: E402

from scripts import probe_privacy_check as ppc  # noqa: E402

SCRIPT = ROOT / "deploy" / "artlab_probe.sh"


def _write(tmp_path, obj, name="out.json", ascii_only=False) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(obj, ensure_ascii=ascii_only), encoding="utf-8")
    return path


def test_plate_check_masked_shapes_pass(tmp_path):
    path = _write(tmp_path, {"shapes": {"9999 ААА 99999999": 3, "9999-ААА": 1}, "sum": 88001234, "id": 12345678})
    code, lines = ppc.check(path)
    assert code == ppc.OK and lines[0] == "plate check: none found"
    assert "8-digit numbers: 1" in lines[1] and lines[2] == "  at $.sum"


@pytest.mark.parametrize("ascii_only", [False, True])  # \u-escaped Cyrillic is caught too
def test_plate_check_finds_real_plate_and_prints_count_only(tmp_path, ascii_only):
    path = _write(tmp_path, {"x": "Батболд 1234 УБА", "y": "5678ӨҮЁ"}, ascii_only=ascii_only)
    code, lines = ppc.check(path)
    assert code == ppc.FOUND and lines == ["STOP: 2 plate-like text(s) found; do NOT share this file"]


@pytest.mark.parametrize("content", [None, b"", b"\xff\xfe broken", b"{not json"])
def test_plate_check_fails_loudly_when_it_cannot_run(tmp_path, capsys, content):
    path = tmp_path / "out.json"
    if content is not None:
        path.write_bytes(content)
    assert ppc.main([str(path)]) == ppc.CANNOT_RUN
    out, err = capsys.readouterr()
    assert "none found" not in out + err and "could NOT run" in err


def test_plate_check_crash_is_not_none_found(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(ppc, "load", lambda p: 1 / 0)
    assert ppc.main([str(_write(tmp_path, {}))]) == ppc.CANNOT_RUN
    out, err = capsys.readouterr()
    assert out == "" and "ZeroDivisionError" in err


def test_plate_check_source_has_no_raw_cyrillic():
    text = (ROOT / "scripts" / "probe_privacy_check.py").read_text(encoding="utf-8")
    assert text.isascii()  # \u escapes only: nothing for a locale to mis-read


def _sh(args, tmp_path, path_dirs):
    env = {"PATH": os.pathsep.join(str(d) for d in path_dirs), "LC_ALL": "C"}
    return subprocess.run(["/bin/bash", str(SCRIPT), *args], capture_output=True, text=True, env=env,
                          cwd=tmp_path)


def _real_python_dir(tmp_path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "python3").symlink_to(sys.executable)
    return bin_dir


def test_server_check_clean_file_under_c_locale(tmp_path):
    result = _sh(["check", str(_write(tmp_path, {"shape": "9999 ААА"}))], tmp_path, [_real_python_dir(tmp_path)])
    assert result.returncode == 0 and "plate check: none found" in result.stdout


def test_server_check_plate_found_exits_3(tmp_path):
    _write(tmp_path, {"d": "1234 УБА"})
    result = _sh(["check", "out.json"], tmp_path, [_real_python_dir(tmp_path)])  # relative path
    assert result.returncode == 3 and "STOP: 1" in result.stderr and "УБА" not in result.stderr


def test_server_check_without_python_fails_loudly(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    result = _sh(["check", str(_write(tmp_path, {}))], tmp_path, [empty])
    assert result.returncode == 4 and "python3 not found" in result.stderr
    assert "none found" not in result.stdout + result.stderr


def test_server_check_python_crash_fails_loudly(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "python3").write_text("#!/bin/sh\nexit 1\n")
    (bin_dir / "python3").chmod(0o755)
    result = _sh(["check", str(_write(tmp_path, {}))], tmp_path, [bin_dir])
    assert result.returncode == 4 and "could NOT run (exit 1)" in result.stderr
    assert "none found" not in result.stdout + result.stderr


def test_server_script_has_no_grep_plate_check():
    text = SCRIPT.read_text()
    code = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    assert not any("none found" in line for line in code)  # only the Python check may say it
    assert not any("grep -nE" in line for line in code)


def _dated(days: list[str]) -> list[dict]:
    return [_bill(i, billDate=d) for i, d in enumerate(days)]


DAYS = ["2025-03-27", "2026-10-30", "2024-06-01", "2026-11-03", "2025-12-31", "2026-01-15"]


@pytest.mark.parametrize("order", ["newest_first", "oldest_first", "by_id"])
def test_newest_bill_does_not_trust_the_sort_order(order):
    client = make_client(DatedFake(_dated(DAYS), order=order))
    info = probe_mod.newest_bill(client, date(2026, 11, 5))
    assert info["newest_bill_date"] == "2026-11-03" and info["bills_after_newest"] == 0
    assert info["total_records"] == 6 and info["bills_last_30_days"] == 2


def test_newest_bill_flags_bills_it_missed(monkeypatch):
    """Ordered by id + a short edge window: neither end holds the newest date -> loud warning."""
    monkeypatch.setattr(probe_mod, "EDGE_ROWS", 1)
    client = make_client(DatedFake(_dated(DAYS), order="by_id"))
    info = probe_mod.newest_bill(client, date(2026, 11, 5))
    assert info["newest_bill_date"] == "2026-01-15" and info["bills_after_newest"] == 2
    line = probe_mod.connection_line({"login_conn_id": "1", "connections": [], **info})
    assert line.endswith("bills after it: 2) WARNING: newest date is wrong")


def test_sort_order_detection():
    assert probe_mod.sort_order(("2026-01-01", "2026-02-01"), ("2024-01-01", "2024-02-01")) == "newest_first"
    assert probe_mod.sort_order(("2024-01-01", "2024-02-01"), ("2026-01-01", "2026-02-01")) == "oldest_first"
    assert probe_mod.sort_order(("2024-01-01", "2026-02-01"), ("2025-01-01", "2025-02-01")) == "mixed"
    assert probe_mod.sort_order((None, None), ("2025-01-01", "2025-02-01")) == "unknown"


def test_month_windows_cross_year_and_leap_day():
    wins = probe_mod.month_windows(date(2024, 3, 10), 3)
    assert wins == [("2024-01", "2024-01-01", "2024-01-31"), ("2024-02", "2024-02-01", "2024-02-29"),
                    ("2024-03", "2024-03-01", "2024-03-31")]
    assert len(probe_mod.month_windows(date(2026, 11, 5))) == 24


def test_months_section_counts_only(monkeypatch, tmp_path, capsys):
    fake = PrivateFake()
    fake.bills += _dated(["2025-03-27", "2025-03-01", "2024-11-30", "2020-01-01"])  # last two: outside
    code = _run_main(monkeypatch, tmp_path, fake, ["--section", "months", "--to", "2026-11-05"])
    out, err = capsys.readouterr()
    assert code == 0
    months = json.loads(out)["months"]
    assert len(months["months"]) == 24 and list(months["months"])[0] == "2024-12"
    assert months["months"]["2025-03"] == 2 and months["months"]["2026-11"] == 6
    assert months["total"] == 8 and months["all_time"] == 10 and months["unknown_months"] == []
    assert (months["first_month_with_bills"], months["last_month_with_bills"]) == ("2025-03", "2026-11")
    assert set(months) == {"months", "total", "all_time", "unknown_months",
                           "first_month_with_bills", "last_month_with_bills"}
    assert all(isinstance(v, int) for v in months["months"].values())
    for value in SECRETS:
        assert value not in out and value not in err, value
    # only X-Summary count requests: no bill rows are fetched for this section
    month_calls = [h for m, u, h in fake.calls if "from=20" in u and "-01&to=" in u]
    assert len(month_calls) == 24 and all(h.get("X-Summary") == "1" for h in month_calls)


def test_months_missing_count_header_is_null_not_zero(monkeypatch):
    client = make_client(DatedFake(_dated(DAYS)))
    monkeypatch.setattr(client, "count", lambda path, params: None)
    result = probe_mod.run_months(client, date(2026, 11, 5), 2)
    assert result["months"] == {"2026-10": None, "2026-11": None}
    assert result["unknown_months"] == ["2026-10", "2026-11"] and result["total"] == 0
