"""Tests for task 8.5r (D-117): shared password + 30-day remember-me cookie.

No database needed: the auth routes never touch it (an in-memory SQLite engine is passed
only so create_app does not read POSTGRES_*). The real Caddy checks (forward_auth, the
websocket, data routes not public, X-Forwarded-For) are in tests/test_stack_auth.py.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from src.api import auth
from src.api.config import ConfigError
from src.api.main import create_app

PASSWORD = "demo-pass"
SECRET = "test-secret-0123456789abcdef"
T0 = 1_800_000_000.0   # a fixed "now" (2027-01-15), so expiry tests do not depend on the clock
KEY = auth.signing_key(SECRET, PASSWORD)


class Clock:
    """Replaces time.time in the app; tests move it forward."""

    def __init__(self, now: float = T0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def make_client(monkeypatch, password: str | None = PASSWORD, secret: str | None = SECRET,
                clock: Clock | None = None) -> TestClient:
    for var, value in (("UI_PASSWORD", password), ("AUTH_SECRET", secret)):
        if value is None:
            monkeypatch.delenv(var, raising=False)
        else:
            monkeypatch.setenv(var, value)
    app = create_app(engine=create_engine("sqlite://", poolclass=StaticPool))
    app.state.clock = clock or Clock()
    # https: the cookie is Secure, so the test client only sends it back over https
    return TestClient(app, base_url="https://testserver", follow_redirects=False)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def client(monkeypatch, clock) -> Iterator[TestClient]:
    with make_client(monkeypatch, clock=clock) as c:
        yield c


def login(client: TestClient, password: str = PASSWORD, remember: bool = True, next_path: str = "/",
          headers: dict | None = None):
    form = {"password": password, "next": next_path}
    if remember:
        form["remember"] = "1"
    return client.post("/auth/login", data=form, headers=headers)


def cookie_header(token: str) -> dict:
    return {"Cookie": f"{auth.COOKIE_NAME}={token}"}


# ==========================================================================
# tokens (pure functions)
# ==========================================================================

def test_valid_token_accepted() -> None:
    assert auth.token_valid(KEY, auth.make_token(KEY, T0, 60), T0 + 59)


def test_expired_token_refused() -> None:
    token = auth.make_token(KEY, T0, 60)
    assert not auth.token_valid(KEY, token, T0 + 60)
    assert not auth.token_valid(KEY, token, T0 + 3600)


@pytest.mark.parametrize("change", ["expiry", "nonce", "signature", "version"])
def test_tampered_token_refused(change: str) -> None:
    version, expires, nonce, sig = auth.make_token(KEY, T0, 60).split(".")
    if change == "expiry":        # try to make it last longer
        expires = str(int(expires) + 10**6)
    elif change == "nonce":
        nonce = "A" + nonce[1:] if nonce[0] != "A" else "B" + nonce[1:]
    elif change == "signature":
        sig = sig[:-1] + ("A" if sig[-1] != "A" else "B")
    else:
        version = "v2"
    assert not auth.token_valid(KEY, ".".join([version, expires, nonce, sig]), T0)


@pytest.mark.parametrize("junk", [None, "", "abc", "v1.1.2", "v1.notanumber.x.y", "....", "v1." * 10])
def test_junk_token_refused(junk) -> None:
    assert not auth.token_valid(KEY, junk, T0)


def test_password_change_invalidates_tokens() -> None:
    """D-117: changing UI_PASSWORD = log everyone out (new key, old signatures fail)."""
    token = auth.make_token(KEY, T0, auth.REMEMBER_SECONDS)
    assert not auth.token_valid(auth.signing_key(SECRET, "new-pass"), token, T0)


def test_secret_change_invalidates_tokens() -> None:
    token = auth.make_token(KEY, T0, auth.REMEMBER_SECONDS)
    assert not auth.token_valid(auth.signing_key("another-secret-0123456789", PASSWORD), token, T0)


def test_tokens_are_random() -> None:
    assert auth.make_token(KEY, T0, 60) != auth.make_token(KEY, T0, 60)


# ==========================================================================
# config
# ==========================================================================

def test_no_password_means_no_login() -> None:
    assert auth.load_auth_config({}) is None
    assert auth.load_auth_config({"UI_PASSWORD": "", "AUTH_SECRET": SECRET}) is None


@pytest.mark.parametrize("secret", [None, "", "short"])
def test_password_without_secret_refuses_to_start(secret) -> None:
    env = {"UI_PASSWORD": PASSWORD} if secret is None else {"UI_PASSWORD": PASSWORD, "AUTH_SECRET": secret}
    with pytest.raises(ConfigError, match="AUTH_SECRET"):
        auth.load_auth_config(env)


def test_api_does_not_start_without_secret(monkeypatch) -> None:
    with pytest.raises(ConfigError):
        with make_client(monkeypatch, secret=None):
            pass


def test_config_repr_hides_key_and_password_is_not_logged() -> None:
    config = auth.load_auth_config({"UI_PASSWORD": PASSWORD, "AUTH_SECRET": SECRET})
    assert config is not None and "key=" not in repr(config)


# ==========================================================================
# next (open-redirect guard)
# ==========================================================================

@pytest.mark.parametrize(("raw", "expected"), [
    ("/", "/"), ("/record", "/record"), ("/card?id=5", "/card?id=5"), ("/dashboard#x", "/dashboard#x"),
    (None, "/"), ("", "/"),
    ("https://evil.com", "/"), ("evil.com", "/"), ("javascript:alert(1)", "/"),
    ("//evil.com", "/"), ("///evil.com", "/"), ("/\\evil.com", "/"), ("/\\/evil.com", "/"),
    ("/%2F%2Fevil.com", "/"), ("/%5Cevil.com", "/"), ("/ok\\x", "/"),
    ("/\r\nSet-Cookie:x=1", "/"), ("/\tx", "/"),
    ("/auth", "/"), ("/auth/login", "/"), ("/auth/logout?next=/x", "/"), ("/AUTH/login", "/"),
    ("/%61uth/login", "/"), ("/_stcore/stream", "/"), ("/static/js/main.js", "/"),
    ("/authors", "/authors"),   # only the /auth prefix itself is refused
])
def test_safe_next(raw, expected) -> None:
    assert auth.safe_next(raw) == expected


def test_bad_next_is_not_followed_after_login(client) -> None:
    for bad in ("//evil.com", "/\\evil.com", "https://evil.com", "/auth/logout"):
        response = login(client, next_path=bad)
        assert response.status_code == 303 and response.headers["location"] == "/"


def test_good_next_is_followed_after_login(client) -> None:
    response = login(client, next_path="/reminders")
    assert response.status_code == 303 and response.headers["location"] == "/reminders"


def test_next_is_escaped_in_the_page(client) -> None:
    page = client.get("/auth/login", params={"next": '/x"><script>alert(1)</script>'}).text
    assert "<script>alert(1)" not in page and "&lt;script&gt;" in page


# ==========================================================================
# login / logout / check routes
# ==========================================================================

def test_login_page_lets_the_phone_save_the_password(client) -> None:
    response = client.get("/auth/login")
    page = response.text
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert 'method="post"' in page and 'action="/auth/login"' in page
    assert 'type="password"' in page and 'autocomplete="current-password"' in page
    assert 'autocomplete="username"' in page
    assert 'name="remember" value="1" checked' in page and "Намайг сана" in page   # on by default


def test_right_password_sets_30_day_cookie(client) -> None:
    response = login(client, next_path="/record")
    assert response.status_code == 303 and response.headers["location"] == "/record"
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{auth.COOKIE_NAME}=v1.")
    for part in ("HttpOnly", "Secure", "SameSite=lax", "Path=/", "Max-Age=2592000"):
        assert part.lower() in cookie.lower()
    token = client.cookies[auth.COOKIE_NAME]
    assert auth.token_valid(KEY, token, T0 + auth.REMEMBER_SECONDS - 1)
    assert not auth.token_valid(KEY, token, T0 + auth.REMEMBER_SECONDS)   # 30 days, not more


def test_without_remember_cookie_is_browser_session_only(client) -> None:
    response = login(client, remember=False)
    cookie = response.headers["set-cookie"].lower()
    assert "max-age" not in cookie and "expires" not in cookie and "httponly" in cookie
    assert not auth.token_valid(KEY, client.cookies[auth.COOKIE_NAME], T0 + auth.SESSION_SECONDS)


def test_wrong_password_401_no_cookie(client) -> None:
    response = login(client, password="wrong")
    assert response.status_code == 401 and auth.WRONG_PASSWORD in response.text
    assert "set-cookie" not in response.headers


def test_check_without_cookie_redirects_to_login_with_next(client) -> None:
    response = client.get("/auth/check", headers={"X-Forwarded-Uri": "/record?diag=1"})
    assert response.status_code == 302
    assert response.headers["location"] == "/auth/login?next=%2Frecord%3Fdiag%3D1"


def test_check_drops_unsafe_forwarded_uri(client) -> None:
    for uri in ("//evil.com", "/_stcore/stream", None):
        headers = {"X-Forwarded-Uri": uri} if uri else {}
        assert client.get("/auth/check", headers=headers).headers["location"] == "/auth/login"


def test_check_after_login_ok(client) -> None:
    login(client)
    response = client.get("/auth/check")
    assert response.status_code == 200 and response.json() == {"login_required": True}


def test_check_expired_cookie_redirects(client, clock) -> None:
    login(client)
    clock.now = T0 + auth.REMEMBER_SECONDS + 1
    assert client.get("/auth/check").status_code == 302


def test_check_tampered_cookie_redirects(client) -> None:
    login(client)
    token = client.cookies[auth.COOKIE_NAME]
    client.cookies.clear()
    assert client.get("/auth/check", headers=cookie_header(token)).status_code == 200   # counter-check
    assert client.get("/auth/check", headers=cookie_header(token[:-2] + "xx")).status_code == 302


def test_new_password_logs_everyone_out(monkeypatch, clock) -> None:
    """Restarting the API with a new UI_PASSWORD (`up -d` after editing .env) -> old cookie refused."""
    with make_client(monkeypatch, clock=clock) as old:
        login(old)
        token = old.cookies[auth.COOKIE_NAME]
        assert old.get("/auth/check").status_code == 200
    with make_client(monkeypatch, password="new-pass", clock=clock) as new:
        assert new.get("/auth/check", headers=cookie_header(token)).status_code == 302
        assert login(new, password=PASSWORD).status_code == 401      # old password no longer works
        assert login(new, password="new-pass").status_code == 303


def test_logged_in_login_page_goes_to_next(client) -> None:
    login(client)
    response = client.get("/auth/login", params={"next": "/search"})
    assert response.status_code == 303 and response.headers["location"] == "/search"


def test_logout_clears_cookie(client) -> None:
    login(client)
    response = client.get("/auth/logout")
    assert response.status_code == 303 and response.headers["location"] == "/auth/login"
    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith(f'{auth.COOKIE_NAME}=""') and "max-age=0" in cookie and "path=/" in cookie
    assert auth.COOKIE_NAME not in client.cookies
    assert client.get("/auth/check").status_code == 302


def test_form_too_big_refused(client) -> None:
    assert client.post("/auth/login", content=b"password=" + b"x" * 5000).status_code == 413


def test_login_off_everything_passes(monkeypatch) -> None:
    """Local dev without UI_PASSWORD: no login, the same as before 8.5r."""
    with make_client(monkeypatch, password=None, secret=None) as c:
        assert c.get("/auth/check").json() == {"login_required": False}
        assert c.get("/auth/login", params={"next": "/record"}).headers["location"] == "/record"


# ==========================================================================
# 5 wrong -> 15 min lock
# ==========================================================================

def test_five_wrong_lock_then_unlock(client, clock) -> None:
    for _ in range(auth.MAX_FAILURES - 1):
        assert login(client, password="wrong").status_code == 401
    fifth = login(client, password="wrong")
    assert fifth.status_code == 429 and "15 минутын дараа" in fifth.text
    right_while_locked = login(client)
    assert right_while_locked.status_code == 429 and "set-cookie" not in right_while_locked.headers
    clock.now = T0 + auth.LOCK_SECONDS - 61
    assert "2 минутын дараа" in login(client).text     # 61 s left -> rounded up to 2 min
    clock.now = T0 + auth.LOCK_SECONDS
    assert login(client).status_code == 303            # unlocked
    for _ in range(auth.MAX_FAILURES - 1):             # and the count starts fresh
        assert login(client, password="wrong").status_code == 401


def test_right_password_resets_the_count(client) -> None:
    for _ in range(auth.MAX_FAILURES - 1):
        login(client, password="wrong")
    assert login(client).status_code == 303
    for _ in range(auth.MAX_FAILURES - 1):
        assert login(client, password="wrong").status_code == 401


def test_lock_is_per_ip(client) -> None:
    """X-Real-IP is what Caddy sets from the real connection; one IP's lock does not block another."""
    a, b = {"X-Real-IP": "203.0.113.1"}, {"X-Real-IP": "203.0.113.2"}
    for _ in range(auth.MAX_FAILURES):
        login(client, password="wrong", headers=a)
    assert login(client, headers=a).status_code == 429
    assert login(client, headers=b).status_code == 303


def test_x_forwarded_for_does_not_change_the_ip(client) -> None:
    """A client can write anything into X-Forwarded-For, so it is never read."""
    for i in range(auth.MAX_FAILURES):
        login(client, password="wrong", headers={"X-Forwarded-For": f"198.51.100.{i}"})
    assert login(client, headers={"X-Forwarded-For": "198.51.100.99"}).status_code == 429


def test_client_ip() -> None:
    assert auth.client_ip({"x-real-ip": " 203.0.113.7 "}, "172.18.0.5") == "203.0.113.7"
    assert auth.client_ip({"x-forwarded-for": "1.2.3.4"}, "172.18.0.5") == "172.18.0.5"
    assert auth.client_ip({}, None) == "unknown"


def test_limiter_memory_is_bounded() -> None:
    limiter = auth.LoginLimiter()
    limiter.MAX_TRACKED = 3
    for i in range(10):
        limiter.record_failure(f"10.0.0.{i}", T0)
    assert len(limiter._failures) <= 4
