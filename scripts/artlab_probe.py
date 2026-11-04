"""Read-only probe of the Artlab Cloud ERP API v2 (tasks 9.6a + 9.6b-1, Artlab TEST account).

Logs in and prints a FIELD SUMMARY per section: key names, types, counts, enum values, date ranges,
amount totals. It never prints descriptions, names, phones, register numbers, the token or the
password (RISK-06, RISK-22) -- free text is only counted (has plate / has phone) or masked
("1234 УБА" -> "9999 ААА").

Sections (--section, default all):
  bills       9.6a: paging, date filters, POS bills + invoices for --from/--to
  paymethods  9.6b-1: payment methods + their type enum (find the credit type code)
  acc-txn     9.6b-1: account transaction report («Дансны хуулга») for --account codes

Safety (D-114): POSTs allowed are /auth/login and /report/acc-txn (Artlab confirmed read-only),
each with a body built here from fixed keys -- there is no generic POST. Every other request must
be a GET on the fixed READ_PATHS allow-list; anything else raises before a request is sent.
GET /auth/connections/switch/:id is a GET that CHANGES the session, so it is not on the list.

Task 9.6c-2 (first REAL run, docs/plans/9.6c_plan.md): money sums are hidden for groups of fewer than
MIN_GROUP rows (one LOAN bill's sum = one customer's credit), numeric acc-txn columns show no min/max,
every run starts with the active Artlab CONNECTION (test or real DB?) on stderr, bills are counted per
terminal, and the plate/phone extraction rate is measured on completed sales only. The JSON goes to
stdout, but never to a terminal: on the server deploy/artlab_probe.sh saves it under /root/artlab_probe/.

Credentials come from .env (ARTLAB_URL, ARTLAB_USER, ARTLAB_PASS); real environment variables win.

    .venv/bin/python -m scripts.artlab_probe --section bills --from 2026-10-01 --to 2026-10-31 > out.json
    .venv/bin/python -m scripts.artlab_probe --section acc-txn --account 127000000001 \\
        --from 2026-06-01 --to 2026-06-30 > out.json
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.artlab.client import (  # noqa: F401  (re-exported for tests / interactive use)
    ACC_TXN_PATH,
    MAX_PAGES,
    READ_PATHS,
    ArtlabClient,
    ArtlabError,
    NotAllowedError,
    as_list,
    header,
    load_env,
)
from src.artlab.bills import COMPLETE, SALE_TYPES
from src.artlab.extract import find_phones, find_plates  # noqa: F401

PAGE_LIMIT = 50  # probe pages stay small (date-filter checks look at the first page only)
_ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")

# Only these fields have their VALUES counted and printed (enums, not personal data).
ENUM_FIELDS = ("type", "status")

# 9.6c-2: a money sum over fewer rows than this is hidden (a group of 1 = one customer's amount).
MIN_GROUP = 5
# PM 9.6c: sync may start when at least this share of completed sales has a plate or a phone.
SYNC_BAR = 0.5
OUT_DIR = "/root/artlab_probe"  # where deploy/artlab_probe.sh saves the JSON on the server

# ---------------------------------------------------------------- summaries (no personal values)


def token_lifetime(token: str) -> dict[str, Any] | None:
    """If the token is a JWT, read iat/exp from its payload (NOT verified) -> lifetime info.

    Only the numbers are returned, never the token. None if it is not a JWT.
    """
    parts = token.removeprefix("Bearer ").strip().split(".")
    if len(parts) != 3:
        return None
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, json.JSONDecodeError):
        return None
    iat, exp = payload.get("iat"), payload.get("exp")
    info: dict[str, Any] = {"claims": sorted(payload)}
    if isinstance(exp, (int, float)):
        info["expires_utc"] = datetime.fromtimestamp(exp, tz=timezone.utc).isoformat()
        if isinstance(iat, (int, float)):
            info["lifetime_min"] = round((exp - iat) / 60, 1)
    return info


def field_summary(rows: list[dict], prefix: str = "") -> dict[str, dict[str, Any]]:
    """Every key path -> {types, non_empty, rows}. Lists of objects are flattened as path[].*

    Only key NAMES and type names come out, no values.
    """
    out: dict[str, dict[str, Any]] = {}

    def add(path: str, value: Any) -> None:
        entry = out.setdefault(path, {"types": set(), "non_empty": 0, "seen": 0})
        entry["seen"] += 1
        entry["types"].add(type(value).__name__)
        if value not in (None, "", [], {}):
            entry["non_empty"] += 1

    def walk(obj: dict, base: str) -> None:
        for key, value in obj.items():
            path = f"{base}{key}"
            add(path, value)
            if isinstance(value, dict):
                walk(value, path + ".")
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        walk(item, path + "[].")

    for row in rows:
        if isinstance(row, dict):
            walk(row, prefix)
    return {k: {**v, "types": sorted(v["types"])} for k, v in sorted(out.items())}


def text_shape(text: str, max_len: int = 20) -> str:
    """Mask free text so only its SHAPE is printed: digit -> 9, Cyrillic -> А, Latin -> a.

    "1234 УБА 99112233" -> "9999 ААА 99999999". Spaces and punctuation stay.
    """
    out = []
    for ch in text.strip()[:max_len]:
        if ch in "0123456789":
            out.append("9")
        elif "\u0400" <= ch <= "\u04ff":
            out.append("А")
        elif ch.isascii() and ch.isalpha():
            out.append("a")
        elif ch.isalnum():
            out.append("?")
        else:
            out.append(ch)
    return "".join(out) + ("…" if len(text.strip()) > max_len else "")


def payment_type_label(value: Any) -> str:
    """payments[].type may be a string/number or an object -> a short printable label."""
    if isinstance(value, dict):
        parts = [str(value[k]) for k in ("code", "name", "id") if value.get(k) not in (None, "")]
        return " / ".join(parts) or "{}"
    return str(value)


def _money(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def safe_sum(count: int, total: float) -> float | str:
    """The rounded sum, or a placeholder when the group is too small to hide one person's amount."""
    return round(total, 2) if count >= MIN_GROUP else f"hidden (<{MIN_GROUP})"


def terminal_key(bill: dict) -> str:
    """'terminal <code> / branch <code>': codes only, so no free-text name ever reaches the output."""
    terminal = bill.get("terminal") if isinstance(bill.get("terminal"), dict) else {}
    branch = terminal.get("branch") if isinstance(terminal.get("branch"), dict) else {}
    return f"terminal {terminal.get('code') or '?'} / branch {branch.get('code') or '?'}"


def extraction_counts(texts: list[str]) -> dict[str, Any]:
    """How many descriptions hold a valid plate, a phone, both, either, neither (+ the either rate)."""
    plate = [bool(find_plates(t)) for t in texts]
    phone = [bool(find_phones(t)) for t in texts]
    either = sum(a or b for a, b in zip(plate, phone))
    return {
        "rows": len(texts),
        "plate": sum(plate),
        "phone": sum(phone),
        "both": sum(a and b for a, b in zip(plate, phone)),
        "plate_or_phone": either,
        "neither": len(texts) - either,
        "rate_plate_or_phone": round(either / len(texts), 3) if texts else None,
    }


def sales_extraction(bills: list[dict]) -> dict[str, Any]:
    """9.6c-2 (G5): the extraction rate on completed SALE_VAT / SALE bills only (what matching uses),
    overall and per terminal (G4), with the PM's sync bar (>= 50 % plate or phone)."""
    sales = [b for b in bills if b.get("type") in SALE_TYPES and b.get("status") == COMPLETE]
    by_terminal: dict[str, list[str]] = {}
    for bill in sales:
        by_terminal.setdefault(terminal_key(bill), []).append(str(bill.get("description") or ""))
    overall = extraction_counts([str(b.get("description") or "") for b in sales])
    rate = overall["rate_plate_or_phone"]
    return {
        **overall,
        "sync_bar": SYNC_BAR,
        "meets_sync_bar": rate is not None and rate >= SYNC_BAR,
        "by_terminal": {k: extraction_counts(v) for k, v in sorted(by_terminal.items())},
    }


def bill_summary(bills: list[dict]) -> dict[str, Any]:
    """Counts + totals for POS bills; descriptions only counted, never printed."""
    dates = sorted(str(b.get("billDate", ""))[:10] for b in bills if b.get("billDate"))
    pay_count: Counter[str] = Counter()
    pay_amount: Counter[str] = Counter()
    n_payments: Counter[int] = Counter()
    desc = Counter()
    for bill in bills:
        payments = bill.get("payments") or []
        n_payments[len(payments)] += 1
        for pay in payments:
            label = payment_type_label(pay.get("type"))
            pay_count[label] += 1
            pay_amount[label] += _money(pay.get("amount"))
        text = str(bill.get("description") or "")
        desc["non_empty"] += bool(text.strip())
        desc["has_plate"] += bool(find_plates(text))
        desc["has_phone"] += bool(find_phones(text))
        desc["has_both"] += bool(find_plates(text)) and bool(find_phones(text))
    return {
        "rows": len(bills),
        "date_min": dates[0] if dates else None,
        "date_max": dates[-1] if dates else None,
        "enums": {f: dict(Counter(str(b.get(f)) for b in bills)) for f in ENUM_FIELDS},
        "payments_per_bill": dict(sorted(n_payments.items())),
        "payment_types": {
            k: {"count": pay_count[k], "amount_sum": safe_sum(pay_count[k], pay_amount[k])}
            for k in pay_count
        },
        "by_terminal": dict(sorted(Counter(terminal_key(b) for b in bills).items())),
        "completed_sales": sales_extraction(bills),
        "description": dict(desc),
        "description_shapes_top5": dict(
            Counter(text_shape(str(b.get("description"))) for b in bills
                    if str(b.get("description") or "").strip()).most_common(5)
        ),
        "unique_num": len({b.get("num") for b in bills}),
        "unique_id": len({b.get("id") for b in bills}),
    }


def invoice_summary(invoices: list[dict]) -> dict[str, Any]:
    """Counts + totals for invoices; descriptions only counted."""
    dates = sorted(str(i.get("invoiceDate", ""))[:10] for i in invoices if i.get("invoiceDate"))
    by_status: Counter[str] = Counter()
    gross_by_status: Counter[str] = Counter()
    for inv in invoices:
        by_status[str(inv.get("status"))] += 1
        gross_by_status[str(inv.get("status"))] += _money(inv.get("totalGross"))
    texts = [str(i.get("description") or "") for i in invoices]
    return {
        "rows": len(invoices),
        "date_min": dates[0] if dates else None,
        "date_max": dates[-1] if dates else None,
        "status": {k: {"count": by_status[k], "gross_sum": safe_sum(by_status[k], gross_by_status[k])}
                   for k in by_status},
        "description": {
            "non_empty": sum(bool(t.strip()) for t in texts),
            "has_plate": sum(bool(find_plates(t)) for t in texts),
            "has_phone": sum(bool(find_phones(t)) for t in texts),
        },
    }


# ---------------------------------------------------------------- experiments


def date_range(rows: list[dict], key: str) -> tuple[str | None, str | None]:
    """(min, max) of a YYYY-MM-DD field."""
    dates = sorted(str(r.get(key, ""))[:10] for r in rows if r.get(key))
    return (dates[0], dates[-1]) if dates else (None, None)


def probe_paging(client: ArtlabClient, path: str) -> dict[str, Any]:
    """Two pages of 5: do X-Limit / X-Offset work, and which paging headers come back?"""
    first, h1 = client.page(path, {}, 0, 5)
    second, _ = client.page(path, {}, 5, 5)
    ids1 = {r.get("id") for r in first}
    ids2 = {r.get("id") for r in second}
    total = client.count(path, {})
    last, _ = client.page(path, {}, max((total or 0) - 5, 0), 5)  # first vs last page -> sort order
    return {
        "last_page_dates": date_range(last, "billDate"),
        "page1_rows": len(first),
        "page2_rows": len(second),
        "pages_overlap": bool(ids1 & ids2),
        "page1_dates": date_range(first, "billDate"),
        "page2_dates": date_range(second, "billDate"),
        "paging_headers": sorted(k for k in h1 if k.lower().startswith("x-")),
        "x_offset_next": header(h1, "X-Offset-Next"),
        "total_records": total,
    }


def probe_date_filter(
    client: ArtlabClient, path: str, date_key: str, start: str, end: str, from_names: tuple[str, ...]
) -> dict[str, Any]:
    """Does each candidate 'from' parameter (and 'to') really filter? Compare totals + dates."""
    result: dict[str, Any] = {"total_no_filter": client.count(path, {})}
    to_rows, _ = client.page(path, {"to": end}, 0, PAGE_LIMIT)
    result["to_only"] = {"total": client.count(path, {"to": end}),
                         "first_page_dates": date_range(to_rows, date_key)}
    for name in from_names:
        params = {name: start, "to": end}
        rows, _ = client.page(path, params, 0, PAGE_LIMIT)
        lo, hi = date_range(rows, date_key)
        result[f"{name}+to"] = {
            "total": client.count(path, params),
            "first_page_dates": (lo, hi),
            "all_rows_in_range": all(start <= str(r.get(date_key))[:10] <= end for r in rows),
        }
    return result


def shape_tree(obj: Any, depth: int = 0, max_depth: int = 4) -> Any:
    """Structure of a JSON value without its values: dict -> {key: shape}, list -> [len, shape of
    first item], scalar -> type name. Used for the undocumented acc-txn response."""
    if depth >= max_depth:
        return type(obj).__name__
    if isinstance(obj, dict):
        return {k: shape_tree(v, depth + 1, max_depth) for k, v in obj.items()}
    if isinstance(obj, list):
        return [len(obj), shape_tree(obj[0], depth + 1, max_depth) if obj else None]
    return type(obj).__name__


def find_rows(obj: Any, path: str = "") -> tuple[str, list[dict]]:
    """The largest list of objects anywhere in the response -> (its JSON path, the list)."""
    best: tuple[str, list[dict]] = ("", [])
    if isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj):
        best = (path or "$", obj)
    children = obj.items() if isinstance(obj, dict) else enumerate(obj) if isinstance(obj, list) else []
    for key, value in children:
        sub = find_rows(value, f"{path}.{key}" if isinstance(key, str) else f"{path}[{key}]")
        if len(sub[1]) > len(best[1]):
            best = sub
    return best


def column_profile(rows: list[dict]) -> dict[str, dict[str, Any]]:
    """Per top-level column: no values, only counts / sums / masked shapes.

    numbers -> sum (only for MIN_GROUP+ values), negatives, digit-length range -- never min / max,
    which would be ONE transfer's amount or one account number (9.6c-2, G2); dates -> min, max;
    other text -> distinct count, max length, plate / phone counts, top-3 masked shapes.
    'unique' = every non-empty value differs (a candidate row key).
    """
    out: dict[str, dict[str, Any]] = {}
    keys = sorted({k for r in rows for k in r})
    for key in keys:
        values = [r.get(key) for r in rows if r.get(key) not in (None, "")]
        info: dict[str, Any] = {"non_empty": len(values)}
        hashable = [json.dumps(v, sort_keys=True, default=str) for v in values]
        info["unique"] = bool(values) and len(set(hashable)) == len(values)
        nums = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
        texts = [v for v in values if isinstance(v, str)]
        if nums and len(nums) == len(values):
            digits = [len(str(abs(int(n)))) for n in nums]
            info.update(kind="number", sum=safe_sum(len(nums), sum(nums)),
                        negatives=sum(n < 0 for n in nums), digits=[min(digits), max(digits)])
        elif texts and len(texts) == len(values) and all(_ISO_DATE.match(t[:10]) for t in texts):
            info.update(kind="date", min=min(t[:10] for t in texts), max=max(t[:10] for t in texts))
        elif texts and len(texts) == len(values):
            info.update(
                kind="text", distinct=len(set(texts)), max_len=max(len(t) for t in texts),
                has_plate=sum(bool(find_plates(t)) for t in texts),
                has_phone=sum(bool(find_phones(t)) for t in texts),
                shapes_top3=dict(Counter(text_shape(t) for t in texts).most_common(3)),
            )
        else:
            info["kind"] = ",".join(sorted({type(v).__name__ for v in values})) or "empty"
        out[key] = info
    return out


def paymethods_summary(rows: list[dict]) -> list[dict[str, Any]]:
    """Payment methods are company settings (e.g. «Бэлэн», «Зээл»), not personal data:
    id, name, type and active are printed as they are."""
    keep = ("id", "name", "type", "active")
    return [{k: r.get(k) for k in keep if k in r} for r in rows]


def run_paymethods(client: ArtlabClient) -> dict[str, Any]:
    """9.6b-1: which payment method / type code means credit (zeel)?"""
    st_types, _, types = client.get("/pos/paymethods/types")
    st_list, _, methods = client.get("/pos/paymethods")
    rows = as_list(methods)
    return {
        "types": {"status": st_types, "values": types},
        "methods": {"status": st_list, "count": len(rows), "fields": sorted(field_summary(rows)),
                    "rows": paymethods_summary(rows),
                    "by_type": dict(Counter(str(r.get("type")) for r in rows))},
    }


def run_acc_txn(client: ArtlabClient, accounts: list[str], start: str, end: str) -> dict[str, Any]:
    """9.6b-1: shape of the undocumented account-transaction report, summaries only."""
    t0 = time.monotonic()
    status, headers, data = client.acc_txn(accounts, start, end)
    elapsed = round(time.monotonic() - t0, 2)
    path, rows = find_rows(data)
    return {
        "request": {"accounts": accounts, "startDate": start, "endDate": end},
        "status": status,
        "seconds": elapsed,
        "response_headers": sorted(k.lower() for k in headers),
        "shape": shape_tree(data),
        "rows_path": path,
        "rows": len(rows),
        "columns": column_profile(rows),
        "nested_fields": sorted(k for k in field_summary(rows) if "." in k or "[]" in k),
    }


def connection_summary(client: ArtlabClient, login_body: Any) -> dict[str, Any]:
    """9.6c-2 (G3): WHICH Artlab database this token reads -- test or real?

    Per connection: id, code, name, company name (company / database names, not people) and
    whether it is the login's connId. Plus the newest bill date: the test DB ends 2026-08-10,
    the real one should reach today. Switching connection is NOT allowed (not on the allow-list).
    """
    current = str(login_body.get("connId")) if isinstance(login_body, dict) else None
    _, _, conns = client.get("/auth/connections")
    rows = [c for c in as_list(conns) if isinstance(c, dict)]
    company = lambda c: c["company"].get("name") if isinstance(c.get("company"), dict) else None  # noqa: E731
    newest, _ = client.page("/pos/bills", {}, 0, 1)  # newest first (artlab_api_notes §3)
    return {
        "login_conn_id": current,
        "connections": [{"id": c.get("id"), "code": c.get("code"), "name": c.get("name"),
                         "company": company(c), "current": str(c.get("id")) == current}
                        for c in rows],
        "newest_bill_date": date_range(newest, "billDate")[1],
    }


def connection_line(info: dict[str, Any]) -> str:
    """One line for the screen (stderr) so Ari sees the database before opening the JSON file."""
    current = [c for c in info["connections"] if c["current"]]
    who = (f"{current[0]['code']} {current[0]['name']} / {current[0]['company']}" if current
           else f"NOT FOUND (connId {info['login_conn_id']}, {len(info['connections'])} connections)")
    return f"Artlab connection: {who}; newest bill {info['newest_bill_date']}"


def run(client: ArtlabClient, start: str, end: str) -> dict[str, Any]:
    """The 9.6a probe (bills + invoices); returns a JSON-safe summary."""
    report: dict[str, Any] = {"range": [start, end]}
    status, _, check = client.get("/auth/check")
    report["auth_check"] = {"status": status, "keys": sorted(check) if isinstance(check, dict) else None}
    for path in ("/pos/bills/types", "/pos/bills/statuses"):
        st, _, data = client.get(path)
        report[path] = {"status": st, "values": data}  # enums from Artlab, not personal data

    report["paging_bills"] = probe_paging(client, "/pos/bills")
    report["filter_bills"] = probe_date_filter(
        client, "/pos/bills", "billDate", start, end, ("from", "startDate", "beginDate")
    )
    report["filter_invoices"] = probe_date_filter(
        client, "/invoices", "invoiceDate", start, end, ("from",)
    )
    bills, b_trunc = client.fetch_all("/pos/bills", {"withDtl": "1", "from": start, "to": end})
    report["bills"] = {"truncated": b_trunc, **bill_summary(bills),
                       "fields": _fields_for_print(field_summary(bills))}
    invoices, i_trunc = client.fetch_all("/invoices", {"from": start, "to": end})
    report["invoices"] = {"truncated": i_trunc, **invoice_summary(invoices),
                          "fields": _fields_for_print(field_summary(invoices))}
    return report


def _fields_for_print(summary: dict[str, dict[str, Any]]) -> dict[str, str]:
    """{path: "str,int  12/50"} -- compact one line per field."""
    return {k: f"{','.join(v['types'])}  {v['non_empty']}/{v['seen']}" for k, v in summary.items()}


def _iso_date(text: str) -> str:
    """argparse type: YYYY-MM-DD (checked here, so a bad value never reaches the client)."""
    if not _ISO_DATE.match(text):
        raise argparse.ArgumentTypeError("dates must be YYYY-MM-DD")
    return text


def _account(text: str) -> str:
    """argparse type: an account code is 1-20 digits (the client checks it again)."""
    if not re.fullmatch(r"[0-9]{1,20}", text):
        raise argparse.ArgumentTypeError("account codes are 1-20 digits")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    today = date.today()
    parser.add_argument("--from", dest="start", type=_iso_date, default=str(today - timedelta(days=30)))
    parser.add_argument("--to", dest="end", type=_iso_date, default=str(today))
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--section", choices=("all", "bills", "paymethods", "acc-txn"), default="all")
    parser.add_argument("--account", action="append", default=[], type=_account,
                        help="account code for acc-txn (repeatable); acc-txn is skipped without one")
    args = parser.parse_args(argv)

    if sys.stdout.isatty():
        print(f"Refusing to print to a terminal: redirect into {OUT_DIR}/ "
              "(on the server: deploy/artlab_probe.sh <section>)", file=sys.stderr)
        return 2
    try:
        report = probe(args)
    except (ArtlabError, NotAllowedError) as err:  # our own messages: no secrets, no data
        print(f"probe failed: {err}", file=sys.stderr)
        return 1
    except Exception as err:  # anything else: class only (a traceback could quote a value)
        print(f"probe failed: {type(err).__name__}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


def probe(args: argparse.Namespace) -> dict[str, Any]:
    """Log in, say which connection is active (stderr + report), then run the chosen sections."""
    env = load_env(args.env)
    client = ArtlabClient(env["ARTLAB_URL"])
    login_body = client.login(env["ARTLAB_USER"], env["ARTLAB_PASS"])
    assert client.token is not None
    connection = connection_summary(client, login_body)
    print(connection_line(connection), file=sys.stderr)
    report: dict[str, Any] = {
        "login": {"body_keys": sorted(login_body) if isinstance(login_body, dict) else None,
                  "token_starts_with_bearer": client.token.startswith("Bearer "),
                  "token_jwt": token_lifetime(client.token)},
        "connection": connection,
    }
    if args.section in ("all", "bills"):
        report["bills_section"] = run(client, args.start, args.end)
    if args.section in ("all", "paymethods"):
        report["paymethods"] = run_paymethods(client)
    if args.section in ("all", "acc-txn"):
        report["acc_txn"] = (run_acc_txn(client, args.account, args.start, args.end)
                             if args.account else "skipped: no --account")
    return report

if __name__ == "__main__":
    sys.exit(main())
