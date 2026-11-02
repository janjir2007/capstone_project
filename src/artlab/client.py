"""Read-only Artlab Cloud ERP API v2 client (task 9.6b-2; moved from scripts/artlab_probe.py).

Safety (D-114, RISK-22): our code only READS from Artlab.
- GET only on the fixed READ_PATHS allow-list; anything else raises before a request is sent.
  GET /auth/connections/switch/:id is a GET that CHANGES the session, so it is not on the list.
- POST only /auth/login and /report/acc-txn (Artlab confirmed read-only), each with a body built
  here from fixed keys. There is no generic POST / PATCH / PUT / DELETE method.

The token (60-min JWT, "Bearer ..." in the login RESPONSE header) lives only in memory and is never
logged. Credentials come from .env (ARTLAB_URL, ARTLAB_USER, ARTLAB_PASS); env variables win.
API facts (paging, filters, wrapper) are in docs/artlab_api_notes.md.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LOGIN_PATH = "/auth/login"
READ_PATHS = frozenset(
    {
        "/auth/check",
        "/auth/connections",
        "/pos/bills",
        "/pos/bills/types",
        "/pos/bills/statuses",
        "/invoices",
        "/pos/paymethods",
        "/pos/paymethods/types",
    }
)
ACC_TXN_PATH = "/report/acc-txn"  # POST, but read-only (Artlab confirmed, PM 9.6b review)
_ACCOUNT_CODE = re.compile(r"^[0-9]{1,20}$")
_ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
ENV_KEYS = ("ARTLAB_URL", "ARTLAB_USER", "ARTLAB_PASS")
REQUEST_PAUSE_S = 0.3  # stay far below any rate limit (the docs list 429 but no number)
PAGE_LIMIT = 500  # the server caps X-Limit at 500 (observed, 9.6a)
MAX_PAGES = 20  # safety cap per list: 10,000 rows


# send(method, url, headers, body) -> (status, response headers, response body bytes)
Sender = Callable[[str, str, dict[str, str], bytes | None], tuple[int, dict[str, str], bytes]]


class NotAllowedError(RuntimeError):
    """A request outside the read-only allow-list was attempted."""


class ArtlabError(RuntimeError):
    """Artlab answered with an error, or config is missing. The message never holds a secret."""


def artlab_settings(path: Path = Path(".env")) -> dict[str, str]:
    """Every ARTLAB_* key from a .env file, then real environment variables override them.

    Minimal KEY=VALUE parser (comments, blank lines, optional quotes, "export "); no extra package.
    Other keys in the file (POSTGRES_*, ...) are not read.
    """
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip().removeprefix("export ").strip()
            if key.startswith("ARTLAB_"):
                values[key] = value.strip().strip('"').strip("'")
    values.update({k: v for k, v in os.environ.items() if k.startswith("ARTLAB_") and v})
    return values


def load_env(path: Path = Path(".env")) -> dict[str, str]:
    """The three login settings (ARTLAB_URL / USER / PASS) from .env + environment.

    Raises ArtlabError naming the MISSING keys (never their values).
    """
    values = {k: v for k, v in artlab_settings(path).items() if k in ENV_KEYS}
    missing = [k for k in ENV_KEYS if not values.get(k)]
    if missing:
        raise ArtlabError(f"Missing in .env: {', '.join(missing)}")
    values["ARTLAB_URL"] = values["ARTLAB_URL"].rstrip("/")
    return values


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


def header(headers: dict[str, str], name: str) -> str | None:
    """Case-insensitive header lookup."""
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return None


@dataclass
class ArtlabClient:
    """Tiny read-only Artlab client: login once, then GETs on READ_PATHS + the acc-txn report."""

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
        token = header(headers, "Authorization")
        if status != 200 or not token:
            raise ArtlabError(f"Login failed: HTTP {status}, token header present: {bool(token)}")
        self.token = token
        return json_or_empty(raw)

    def get(
        self, path: str, params: dict[str, str] | None = None, headers: dict[str, str] | None = None
    ) -> tuple[int, dict[str, str], Any]:
        """GET an allow-listed path. Returns (status, response headers, parsed JSON or None)."""
        if path not in READ_PATHS:
            raise NotAllowedError(f"GET {path} is not on the read-only allow-list")
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        all_headers = self._auth_headers()
        all_headers.update(headers or {})
        time.sleep(self.pause_s)
        status, resp_headers, raw = self.send("GET", url, all_headers, None)
        return status, resp_headers, json_or_empty(raw) if raw else None

    def acc_txn(
        self, account_codes: list[str], start: str, end: str
    ) -> tuple[int, dict[str, str], Any]:
        """POST /report/acc-txn («Дансны хуулга»). The body is built HERE from exactly three keys;
        account codes must be digits and dates YYYY-MM-DD, so nothing else can be sent."""
        if not account_codes or not all(_ACCOUNT_CODE.match(c) for c in account_codes):
            raise ValueError("account codes must be 1-20 digits")
        if not (_ISO_DATE.match(start) and _ISO_DATE.match(end)):
            raise ValueError("dates must be YYYY-MM-DD")
        body = json.dumps({"accountCodes": account_codes, "startDate": start, "endDate": end})
        headers = self._auth_headers()
        headers["Content-Type"] = "application/json"
        time.sleep(self.pause_s)
        status, resp_headers, raw = self.send(
            "POST", self.base_url + ACC_TXN_PATH, headers, body.encode()
        )
        return status, resp_headers, json_or_empty(raw) if raw else None

    def _auth_headers(self) -> dict[str, str]:
        if self.token is None:
            raise RuntimeError("login() first")
        return {"Authorization": self.token, "Accept": "application/json"}

    def count(self, path: str, params: dict[str, str]) -> int | None:
        """Total rows matching params, via the documented X-Summary: 1 header (empty list back)."""
        _, headers, _ = self.get(path, params, {"X-Summary": "1"})
        total = header(headers, "X-Total-Records")
        return int(total) if total and total.isdigit() else None

    def page(self, path: str, params: dict[str, str], offset: int, limit: int) -> tuple[list, dict]:
        """One page via the documented X-Offset / X-Limit request headers."""
        status, headers, data = self.get(
            path, params, {"X-Offset": str(offset), "X-Limit": str(limit)}
        )
        if status == 204 or data is None:
            return [], headers
        if status != 200:
            raise ArtlabError(f"GET {path}: HTTP {status}")
        return as_list(data), headers

    def fetch_all(
        self, path: str, params: dict[str, str], limit: int = PAGE_LIMIT, max_pages: int = MAX_PAGES
    ) -> tuple[list, bool]:
        """All rows (up to max_pages). Returns (rows, truncated)."""
        rows: list = []
        offset = 0
        for _ in range(max_pages):
            items, headers = self.page(path, params, offset, limit)
            rows.extend(items)
            nxt = header(headers, "X-Offset-Next")
            if len(items) < limit:
                return rows, False
            offset = int(nxt) if nxt and nxt.isdigit() and int(nxt) > offset else offset + limit
        return rows, True


def json_or_empty(raw: bytes) -> Any:
    """Parse JSON; {} for an empty or non-JSON body."""
    try:
        return json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}


def as_list(data: Any) -> list:
    """List endpoints return {"value": [...], "success": true} (seen on the test DB); a bare list
    or a {"data": [...]}-style wrapper is tolerated too."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("value", "data", "items", "list", "rows"):
            if isinstance(data.get(key), list):
                return data[key]
    return []
