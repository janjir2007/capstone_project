"""Read-only probe of the Artlab Cloud ERP API v2 (task 9.6a, Artlab TEST account).

Logs in, checks paging and date filters, lists POS bills + invoices for a date range and prints a
FIELD SUMMARY: key names, types, counts, enum values (type / status / payment type), date range and
amount totals. It never prints descriptions, names, phones, register numbers, the token or the
password (RISK-06, RISK-22) -- for descriptions it only counts how many contain a plate / a phone.

Safety (D-114): the only POST allowed is /auth/login; every other request must be a GET on the
fixed READ_PATHS allow-list, anything else raises before a request is sent. Note
GET /auth/connections/switch/:id is a GET that CHANGES the session, so it is not on the list.

Credentials come from .env (ARTLAB_URL, ARTLAB_USER, ARTLAB_PASS); real environment variables win.

    .venv/bin/python -m scripts.artlab_probe --from 2026-10-01 --to 2026-10-31
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.common.plates import is_valid_plate, normalize_plate

LOGIN_PATH = "/auth/login"
READ_PATHS = frozenset(
    {
        "/auth/check",
        "/auth/connections",
        "/pos/bills",
        "/pos/bills/types",
        "/pos/bills/statuses",
        "/invoices",
    }
)
ENV_KEYS = ("ARTLAB_URL", "ARTLAB_USER", "ARTLAB_PASS")
REQUEST_PAUSE_S = 0.3  # stay far below any rate limit (the docs list 429 but no number)
PAGE_LIMIT = 50
MAX_PAGES = 20  # cap: at most 1,000 rows per list in one probe run

# Only these fields have their VALUES counted and printed (enums, not personal data).
ENUM_FIELDS = ("type", "status")

# "1234 УБА", "1234-уба", "1234УБА" in free text; normalize_plate() + is_valid_plate() decide.
_PLATE_IN_TEXT = re.compile(r"(?<![0-9])([0-9]{4})[\s\-.]*([А-ЯЁӨҮа-яёөү]{3})(?![А-ЯЁӨҮа-яёөү])")
# Letter triples that are words, not plates: "5000 төг" (tugrik) would otherwise read as 5000ТӨГ.
_NOT_PLATE_LETTERS = frozenset({"ТӨГ"})
# Mongolian phone numbers have 8 digits, often written "9911 2233" or "9911-2233".
_PHONE_IN_TEXT = re.compile(r"(?<![0-9])([0-9]{4})[\s\-]?([0-9]{4})(?![0-9])")

# send(method, url, headers, body) -> (status, response headers, response body bytes)
Sender = Callable[[str, str, dict[str, str], bytes | None], tuple[int, dict[str, str], bytes]]


class NotAllowedError(RuntimeError):
    """A request outside the read-only allow-list was attempted."""


# ---------------------------------------------------------------- config


def load_env(path: Path = Path(".env")) -> dict[str, str]:
    """Read ARTLAB_* keys from a .env file, then let real environment variables override them.

    Minimal KEY=VALUE parser (comments, blank lines, optional quotes); no extra package needed.
    Raises SystemExit naming the MISSING keys (never their values).
    """
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip().removeprefix("export ").strip()
            if key in ENV_KEYS:
                values[key] = value.strip().strip('"').strip("'")
    for key in ENV_KEYS:
        if os.environ.get(key):
            values[key] = os.environ[key]
    missing = [k for k in ENV_KEYS if not values.get(k)]
    if missing:
        raise SystemExit(f"Missing in .env: {', '.join(missing)}")
    values["ARTLAB_URL"] = values["ARTLAB_URL"].rstrip("/")
    return values


# ---------------------------------------------------------------- HTTP


def urllib_send(
    method: str, url: str, headers: dict[str, str], body: bytes | None
) -> tuple[int, dict[str, str], bytes]:
    """Real network sender (stdlib). HTTP errors are returned as a status, not raised."""
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, dict(resp.headers.items()), resp.read()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers.items()), err.read()


def _header(headers: dict[str, str], name: str) -> str | None:
    """Case-insensitive header lookup."""
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return None


@dataclass
class ArtlabClient:
    """Tiny read-only Artlab client: login once, then GETs on READ_PATHS only."""

    base_url: str
    send: Sender = urllib_send
    pause_s: float = REQUEST_PAUSE_S
    token: str | None = field(default=None, repr=False)  # repr=False: never printed by accident

    def login(self, username: str, password: str) -> dict[str, Any]:
        """POST /auth/login. The token comes back in the Authorization RESPONSE header and
        already starts with "Bearer ", so it is stored and later sent unchanged."""
        body = json.dumps({"username": username, "password": password, "type": "api"}).encode()
        status, headers, raw = self.send(
            "POST",
            self.base_url + LOGIN_PATH,
            {"Content-Type": "application/json", "Accept": "application/json"},
            body,
        )
        token = _header(headers, "Authorization")
        if status != 200 or not token:
            raise SystemExit(f"Login failed: HTTP {status}, token header present: {bool(token)}")
        self.token = token
        return _json_or_empty(raw)

    def get(
        self, path: str, params: dict[str, str] | None = None, headers: dict[str, str] | None = None
    ) -> tuple[int, dict[str, str], Any]:
        """GET an allow-listed path. Returns (status, response headers, parsed JSON or None)."""
        if path not in READ_PATHS:
            raise NotAllowedError(f"GET {path} is not on the read-only allow-list")
        if self.token is None:
            raise RuntimeError("login() first")
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        all_headers = {"Authorization": self.token, "Accept": "application/json"}
        all_headers.update(headers or {})
        time.sleep(self.pause_s)
        status, resp_headers, raw = self.send("GET", url, all_headers, None)
        return status, resp_headers, _json_or_empty(raw) if raw else None

    def count(self, path: str, params: dict[str, str]) -> int | None:
        """Total rows matching params, via the documented X-Summary: 1 header (empty list back)."""
        _, headers, _ = self.get(path, params, {"X-Summary": "1"})
        total = _header(headers, "X-Total-Records")
        return int(total) if total and total.isdigit() else None

    def page(self, path: str, params: dict[str, str], offset: int, limit: int) -> tuple[list, dict]:
        """One page via the documented X-Offset / X-Limit request headers."""
        status, headers, data = self.get(
            path, params, {"X-Offset": str(offset), "X-Limit": str(limit)}
        )
        if status == 204 or data is None:
            return [], headers
        if status != 200:
            raise SystemExit(f"GET {path}: HTTP {status}")
        return _as_list(data), headers

    def fetch_all(
        self, path: str, params: dict[str, str], limit: int = PAGE_LIMIT, max_pages: int = MAX_PAGES
    ) -> tuple[list, bool]:
        """All rows (up to max_pages). Returns (rows, truncated)."""
        rows: list = []
        offset = 0
        for _ in range(max_pages):
            items, headers = self.page(path, params, offset, limit)
            rows.extend(items)
            nxt = _header(headers, "X-Offset-Next")
            if len(items) < limit:
                return rows, False
            offset = int(nxt) if nxt and nxt.isdigit() and int(nxt) > offset else offset + limit
        return rows, True


def _json_or_empty(raw: bytes) -> Any:
    """Parse JSON; {} for an empty or non-JSON body."""
    try:
        return json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _as_list(data: Any) -> list:
    """List endpoints return {"value": [...], "success": true} (seen on the test DB); a bare list
    or a {"data": [...]}-style wrapper is tolerated too."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("value", "data", "items", "list", "rows"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


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


def find_plates(text: str) -> list[str]:
    """Valid normalized plates found in free text (uses the ONE normalizer, src/common/plates)."""
    found = []
    for digits, letters in _PLATE_IN_TEXT.findall(text or ""):
        plate = normalize_plate(digits + letters)
        if is_valid_plate(plate) and plate[-3:] not in _NOT_PLATE_LETTERS:
            found.append(plate)
    return found


def find_phones(text: str) -> list[str]:
    """8-digit phone numbers found in free text, digits only."""
    return [a + b for a, b in _PHONE_IN_TEXT.findall(text or "")]


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
            k: {"count": pay_count[k], "amount_sum": round(pay_amount[k], 2)} for k in pay_count
        },
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
        "status": {k: {"count": by_status[k], "gross_sum": round(gross_by_status[k], 2)}
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
        "x_offset_next": _header(h1, "X-Offset-Next"),
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


def run(client: ArtlabClient, start: str, end: str) -> dict[str, Any]:
    """The whole probe; returns a JSON-safe summary."""
    report: dict[str, Any] = {"range": [start, end]}
    status, _, check = client.get("/auth/check")
    report["auth_check"] = {"status": status, "keys": sorted(check) if isinstance(check, dict) else None}
    _, _, conns = client.get("/auth/connections")
    conn_list = _as_list(conns)
    report["connections"] = {"count": len(conn_list),
                             "fields": sorted(field_summary(conn_list))}
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    today = date.today()
    parser.add_argument("--from", dest="start", default=str(today - timedelta(days=30)))
    parser.add_argument("--to", dest="end", default=str(today))
    parser.add_argument("--env", type=Path, default=Path(".env"))
    args = parser.parse_args()

    env = load_env(args.env)
    client = ArtlabClient(env["ARTLAB_URL"])
    login_body = client.login(env["ARTLAB_USER"], env["ARTLAB_PASS"])
    assert client.token is not None
    report = {
        "login": {"body_keys": sorted(login_body) if isinstance(login_body, dict) else None,
                  "token_starts_with_bearer": client.token.startswith("Bearer "),
                  "token_jwt": token_lifetime(client.token)},
        **run(client, args.start, args.end),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
