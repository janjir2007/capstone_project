"""OPT-IN check of the login through the REAL Caddy (task 8.5r, D-117; PM review conditions).

Skipped unless STACK_AUTH=1, because it needs the whole prod stack running locally
(docs/deploy.md §6: DOMAIN=localhost). The pure logic is tested in tests/test_auth.py; this
file proves what only Caddy can show:
- data routes (/vehicles, /reminders, /services, ...) are NOT reachable through Caddy,
  with or without a login cookie (D-061: only /health and /auth/* of the API are public);
- forward_auth guards every UI request, including Streamlit's websocket;
- a fake X-Forwarded-For / X-Real-IP sent by the client does NOT dodge the 5-wrong lock.
Optional browser part (Playwright Chromium + WebKit = Safari's engine): real form, reload stays
logged in, «Гарах» logs out.

Run (repo root, stack from docs/deploy.md §6 up):
    STACK_AUTH=1 STACK_PASSWORD=demo-pass .venv/bin/pytest -v tests/test_stack_auth.py
The LAST test locks this computer's IP for 15 min: `dcl restart api` clears it.
"""

from __future__ import annotations

import base64
import os
import secrets
import socket
import ssl
from urllib.parse import urlsplit

import pytest

if os.environ.get("STACK_AUTH") != "1":
    pytest.skip("opt-in: set STACK_AUTH=1 (see module docstring)", allow_module_level=True)
import httpx  # noqa: E402

BASE = os.environ.get("STACK_URL", "https://localhost").rstrip("/")
PASSWORD = os.environ.get("STACK_PASSWORD", "")
COOKIE = "ocp_session"
# The data routes the UI uses (docs/api_contract.md) + FastAPI's own docs.
DATA_ROUTES = [
    ("GET", "/vehicles/lookup?q=1001"), ("GET", "/vehicles/1"), ("GET", "/vehicles/search"),
    ("GET", "/reminders/due"), ("GET", "/reminders/stops"), ("POST", "/reminders/1/sent"),
    ("POST", "/services"), ("GET", "/stats/segments"), ("GET", "/destinations"),
    ("POST", "/plates/recognize"), ("GET", "/docs"), ("GET", "/openapi.json"),
    ("GET", "/payments/unpaid"), ("GET", "/payments/sync-status"),  # task 9.6b-4
    ("GET", "/stats/period"),  # task 9.12-1
]


def _client() -> httpx.Client:
    # verify=False: Caddy's local CA for "localhost" is not in Python's trust store
    return httpx.Client(base_url=BASE, verify=False, follow_redirects=False, timeout=15)


@pytest.fixture(scope="module")
def http() -> httpx.Client:
    if not PASSWORD:
        pytest.skip("set STACK_PASSWORD (= UI_PASSWORD of the local stack)")
    with _client() as c:
        try:
            c.get("/health")
        except httpx.HTTPError as exc:
            pytest.skip(f"stack not reachable at {BASE}: {exc}")
        yield c


@pytest.fixture(autouse=True)
def no_saved_cookie(request) -> None:
    """Every test starts without a cookie; tests that want one send it explicitly (_cookie)."""
    if "http" in request.fixturenames:
        request.getfixturevalue("http").cookies.clear()


@pytest.fixture(scope="module")
def token(http) -> str:
    response = http.post("/auth/login", data={"password": PASSWORD, "remember": "1", "next": "/"})
    assert response.status_code == 303, response.text[:300]
    value = response.cookies.get(COOKIE)
    assert value
    http.cookies.clear()
    return value


def _cookie(token: str) -> dict:
    return {"Cookie": f"{COOKIE}={token}"}


def _api_json(response: httpx.Response) -> bool:
    """True if this answer came from FastAPI (JSON / Swagger), i.e. the API leaked."""
    kind = response.headers.get("content-type", "")
    return "application/json" in kind or "swagger" in response.text.lower()


# --- public part -------------------------------------------------------------------------

def test_health_is_public(http) -> None:
    response = http.get("/health")
    assert response.status_code in (200, 503) and "status" in response.json()


@pytest.mark.parametrize(("method", "path"), DATA_ROUTES)
def test_data_route_not_reachable_without_cookie(http, method, path) -> None:
    response = http.request(method, path)
    assert response.status_code == 302 and response.headers["location"].startswith("/auth/login")
    assert not _api_json(response)


@pytest.mark.parametrize(("method", "path"), DATA_ROUTES)
def test_data_route_not_reachable_with_cookie(http, token, method, path) -> None:
    """Logged in, these paths go to Streamlit (its HTML or an error), never to the API."""
    response = http.request(method, path, headers=_cookie(token))
    assert response.status_code != 302
    assert not _api_json(response), f"{method} {path} answered by the API: {response.text[:200]}"


# --- login / cookie ----------------------------------------------------------------------

def test_ui_without_cookie_goes_to_login_with_next(http) -> None:
    response = http.get("/record")
    assert response.status_code == 302 and response.headers["location"] == "/auth/login?next=%2Frecord"


def test_login_page_and_cookie_flags(http) -> None:
    page = http.get("/auth/login").text
    assert 'autocomplete="current-password"' in page and "Намайг сана" in page
    response = http.post("/auth/login", data={"password": PASSWORD, "remember": "1", "next": "/record"})
    assert response.status_code == 303 and response.headers["location"] == "/record"
    cookie = response.headers["set-cookie"].lower()
    for part in ("httponly", "secure", "samesite=lax", "max-age=2592000", "path=/"):
        assert part in cookie


def test_ui_with_cookie_opens(http, token) -> None:
    response = http.get("/", headers=_cookie(token))
    assert response.status_code == 200 and "<html" in response.text.lower()


def test_tampered_cookie_refused(http, token) -> None:
    assert http.get("/", headers=_cookie(token[:-2] + "xx")).status_code == 302


def test_wrong_password_401(http) -> None:
    assert http.post("/auth/login", data={"password": "wrong-" + PASSWORD}).status_code == 401


def test_logout_clears_cookie(http) -> None:
    response = http.get("/auth/logout")
    assert response.status_code == 303 and response.headers["location"] == "/auth/login"
    assert "max-age=0" in response.headers["set-cookie"].lower()


# --- Streamlit websocket through forward_auth -------------------------------------------

def _websocket_status(cookie: str | None) -> int:
    """Open wss://<host>/_stcore/stream by hand (no extra package) and return the HTTP status."""
    parts = urlsplit(BASE)
    host, port = parts.hostname, parts.port or 443
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    lines = [
        "GET /_stcore/stream HTTP/1.1", f"Host: {host}", "Upgrade: websocket", "Connection: Upgrade",
        f"Sec-WebSocket-Key: {base64.b64encode(secrets.token_bytes(16)).decode()}",
        "Sec-WebSocket-Version: 13", "Sec-WebSocket-Protocol: streamlit", f"Origin: {BASE}",
    ]
    if cookie:
        lines.append(f"Cookie: {COOKIE}={cookie}")
    with socket.create_connection((host, port), timeout=10) as raw, \
            context.wrap_socket(raw, server_hostname=host) as tls:
        tls.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
        status_line = tls.recv(4096).split(b"\r\n", 1)[0].decode()
    return int(status_line.split()[1])


def test_websocket_refused_without_cookie(http) -> None:
    assert _websocket_status(None) == 302
    assert _websocket_status("v1.1.fake.token") == 302


def test_websocket_opens_with_cookie(http, token) -> None:
    assert _websocket_status(token) == 101   # 101 Switching Protocols = Streamlit is connected


# --- real browsers (optional: Playwright) -------------------------------------------------

@pytest.mark.parametrize("engine", ["chromium", "webkit"])
def test_browser_login_reload_logout(http, engine) -> None:
    """Real form -> home; reload = still logged in (cookie kept); «Гарах» -> login page."""
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        try:
            browser = getattr(p, engine).launch()
        except Exception as exc:  # noqa: BLE001 - browser not installed
            pytest.skip(f"Playwright {engine} not installed: {exc}")
        context = browser.new_context(ignore_https_errors=True, viewport={"width": 390, "height": 844})
        page = context.new_page()
        page.goto(BASE + "/search")
        assert "/auth/login" in page.url
        page.fill('input[name="password"]', PASSWORD)
        page.click('button[type="submit"]')
        page.wait_for_selector("text=Камераар хайх", timeout=30000)   # came back to /search
        assert page.url.rstrip("/").endswith("/search")
        page.goto(BASE + "/")
        page.wait_for_selector("text=Сайн байна уу", timeout=30000)
        page.reload()
        page.wait_for_selector("text=Сайн байна уу", timeout=30000)   # still logged in
        cookie = next(c for c in context.cookies() if c["name"] == COOKIE)
        assert cookie["httpOnly"] and cookie["secure"] and cookie["sameSite"] == "Lax"
        assert page.evaluate("document.cookie").find(COOKIE) == -1   # JavaScript cannot read it
        page.click("a.logout")
        page.wait_for_url("**/auth/login", timeout=15000)              # same tab
        assert not [c for c in context.cookies() if c["name"] == COOKIE]
        page.goto(BASE + "/")
        assert "/auth/login" in page.url
        browser.close()


# --- LAST: the lock cannot be dodged with fake headers --------------------------------------

def test_fake_forwarded_headers_do_not_bypass_lock(http) -> None:
    """Each wrong try claims another IP in X-Forwarded-For and X-Real-IP. Caddy replaces
    X-Real-IP with the real peer, the API never reads X-Forwarded-For -> one IP -> locked."""
    for i in range(5):
        fake = {"X-Forwarded-For": f"198.51.100.{i}", "X-Real-IP": f"203.0.113.{i}"}
        response = http.post("/auth/login", data={"password": "wrong"}, headers=fake)
        assert response.status_code == (429 if i == 4 else 401), (i, response.status_code)
    fresh = {"X-Forwarded-For": "198.51.100.200", "X-Real-IP": "203.0.113.200"}
    response = http.post("/auth/login", data={"password": PASSWORD}, headers=fresh)
    assert response.status_code == 429 and "set-cookie" not in response.headers
