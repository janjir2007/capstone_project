"""Shared-password login with a 30-day "remember me" cookie (task 8.5r, D-117).

There is still ONE company password (UI_PASSWORD). What is new:
- The login form is a plain HTML page served by the API (Streamlit cannot set an
  HttpOnly cookie). On success the API sets the cookie `ocp_session`.
- The cookie holds a SIGNED token, nothing is stored on the server:
      v1.<expires unix>.<random nonce>.<HMAC-SHA256 signature>
  The signing key is derived from AUTH_SECRET *and* UI_PASSWORD, so changing
  UI_PASSWORD makes every old cookie invalid = "log everyone out".
- 5 wrong passwords from one client IP -> that IP is locked for 15 minutes.

This module has no FastAPI import: the routes are in src/api/routers/auth.py.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import unquote

from src.api.config import ConfigError

COOKIE_NAME = "ocp_session"
REMEMBER_SECONDS = 30 * 24 * 3600   # «Намайг сана» on: 30 days, counted from login (not extended by use)
SESSION_SECONDS = 12 * 3600         # off: the cookie dies with the browser; the token itself after 12 h
MAX_FAILURES = 5
LOCK_SECONDS = 15 * 60
MIN_SECRET_LENGTH = 16
TOKEN_VERSION = "v1"


@dataclass(frozen=True)
class AuthConfig:
    """Login settings read once at API startup. ``key`` signs and checks the cookies."""

    password: str
    key: bytes = field(repr=False)


def signing_key(secret: str, password: str) -> bytes:
    """HMAC key from AUTH_SECRET and UI_PASSWORD: a new password gives a new key."""
    return hmac.new(secret.encode(), b"ocp-session|" + password.encode(), hashlib.sha256).digest()


def load_auth_config(env: Mapping[str, str] | None = None) -> AuthConfig | None:
    """None when UI_PASSWORD is unset or empty (local dev: no login, as before).

    With a password, AUTH_SECRET is required: without it a stolen cookie could be
    used to guess the password offline (the key would depend on the password only).
    """
    env = os.environ if env is None else env
    password = env.get("UI_PASSWORD") or ""
    if not password:
        return None
    secret = env.get("AUTH_SECRET") or ""
    if len(secret) < MIN_SECRET_LENGTH:
        raise ConfigError(f"UI_PASSWORD is set, so AUTH_SECRET must be set too (at least "
                          f"{MIN_SECRET_LENGTH} characters; e.g. `openssl rand -hex 32`)")
    return AuthConfig(password=password, key=signing_key(secret, password))


def check_password(entered: str, expected: str) -> bool:
    """Constant-time compare (timing does not show how many leading characters were right)."""
    return hmac.compare_digest(entered.encode(), expected.encode())


def _sign(key: bytes, body: str) -> str:
    digest = hmac.new(key, body.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def make_token(key: bytes, now: float, lifetime: int) -> str:
    """A new signed token that is valid until now + lifetime seconds."""
    body = f"{TOKEN_VERSION}.{int(now) + lifetime}.{secrets.token_urlsafe(16)}"
    return f"{body}.{_sign(key, body)}"


def token_valid(key: bytes, token: str | None, now: float) -> bool:
    """True only for a token signed with this key that has not expired yet."""
    if not token:
        return False
    parts = token.split(".")
    if len(parts) != 4 or parts[0] != TOKEN_VERSION:
        return False
    body = ".".join(parts[:3])
    if not hmac.compare_digest(_sign(key, body), parts[3]):
        return False   # tampered with, or signed with an old password / secret
    try:
        expires = int(parts[1])
    except ValueError:
        return False
    return now < expires


# Paths the login page must never send someone back to: the login pages themselves and
# Streamlit's internal routes (a websocket URL is not a page).
_NO_RETURN_PREFIXES = ("/auth", "/_stcore", "/static", "/component")


def safe_next(raw: str | None) -> str:
    """Where to go after login. Only paths on OUR site; anything else -> "/".

    "//evil.com" and "/\\evil.com" are treated by browsers as another site
    ("open redirect"), so they are refused, like any backslash or control character.
    """
    if not raw or not raw.startswith("/") or raw.startswith("//"):
        return "/"
    if "\\" in raw or any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        return "/"
    path = unquote(raw.split("?", 1)[0].split("#", 1)[0]).lower()
    if "\\" in path or path.startswith("//"):
        return "/"
    if any(path == p or path.startswith(p + "/") for p in _NO_RETURN_PREFIXES):
        return "/"
    return raw


class LoginLimiter:
    """5 wrong passwords in a row from one IP -> locked for 15 min (in memory).

    The API runs as ONE uvicorn process (Dockerfile: no --workers), so one dict
    covers every request. It is emptied when the API restarts, which is acceptable.
    """

    MAX_TRACKED = 10_000   # a flood of different IPs cannot fill the memory

    def __init__(self, max_failures: int = MAX_FAILURES, lock_seconds: int = LOCK_SECONDS) -> None:
        self.max_failures = max_failures
        self.lock_seconds = lock_seconds
        self._failures: dict[str, int] = {}
        self._locked_until: dict[str, float] = {}

    def seconds_locked(self, ip: str, now: float) -> int:
        """Seconds left on this IP's lock (0 = not locked). An ended lock starts a fresh count."""
        until = self._locked_until.get(ip)
        if until is None:
            return 0
        if now >= until:
            del self._locked_until[ip]
            self._failures.pop(ip, None)
            return 0
        return int(until - now) + 1

    def record_failure(self, ip: str, now: float) -> bool:
        """Count one wrong password. True if this one locked the IP."""
        if len(self._failures) >= self.MAX_TRACKED and ip not in self._failures:
            self._prune(now)
        count = self._failures.get(ip, 0) + 1
        self._failures[ip] = count
        if count >= self.max_failures:
            self._locked_until[ip] = now + self.lock_seconds
            return True
        return False

    def record_success(self, ip: str) -> None:
        """A right password resets the count ("5 wrong in a row")."""
        self._failures.pop(ip, None)

    def _prune(self, now: float) -> None:
        """Forget ended locks and counts that are not locked (rarely needed)."""
        for ip in [ip for ip, until in self._locked_until.items() if now >= until]:
            del self._locked_until[ip]
        self._failures = {ip: n for ip, n in self._failures.items() if ip in self._locked_until}


def client_ip(headers: Mapping[str, str], peer: str | None) -> str:
    """The IP to count wrong passwords for.

    Caddy overwrites X-Real-IP with the real TCP peer ({remote_host}), so a value the
    browser sends itself never arrives here. X-Forwarded-For is NOT read: a client can
    put anything in it. Without Caddy (local dev) the direct peer is used.
    """
    return (headers.get("x-real-ip") or "").strip() or peer or "unknown"


# --- the login page (Mongolian; checked by Ari) ---------------------------------------

_PAGE = """<!doctype html>
<html lang="mn">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Нэвтрэх · Тос солилт</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: #F6F7F9; color: #111827;
         font: 16px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
  main {{ max-width: 420px; margin: 0 auto; padding: 48px 16px; }}
  h1 {{ font-size: 22px; font-weight: 600; margin: 0 0 20px; }}
  form {{ background: #fff; border-radius: 16px; padding: 20px; box-shadow: 0 1px 3px rgba(17,24,39,.08); }}
  label.field {{ display: block; font-size: 14px; color: #4B5563; margin-bottom: 6px; }}
  input[type=password] {{ width: 100%; font-size: 17px; padding: 14px; border: 1px solid #E5E7EB;
         border-radius: 12px; background: #F3F4F6; }}
  input[type=password]:focus {{ outline: 2px solid #1F4E9D; background: #fff; }}
  .remember {{ display: flex; align-items: center; gap: 10px; margin: 16px 0 20px; font-size: 15px; }}
  .remember input {{ width: 22px; height: 22px; accent-color: #1F4E9D; }}
  button {{ width: 100%; min-height: 54px; border: 0; border-radius: 14px; background: #1F4E9D;
           color: #fff; font-size: 17px; font-weight: 600; }}
  .error {{ background: #FEF2F2; color: #991B1B; border-radius: 12px; padding: 12px 14px; margin-bottom: 16px; }}
  /* in the page (not display:none) so iOS links the saved password to this "username" */
  .hidden {{ position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }}
</style>
</head>
<body>
<main>
<h1>Нэвтрэх</h1>
<form method="post" action="/auth/login">
  {error}
  <input class="hidden" type="text" name="username" value="geo-expert" autocomplete="username" tabindex="-1" aria-hidden="true">
  <label class="field" for="password">Нууц үг</label>
  <input id="password" type="password" name="password" autocomplete="current-password" required autofocus>
  <label class="remember"><input type="checkbox" name="remember" value="1" checked> Намайг сана</label>
  <input type="hidden" name="next" value="{next}">
  <button type="submit">Нэвтрэх</button>
</form>
</main>
</body>
</html>
"""

WRONG_PASSWORD = "Нууц үг буруу байна."


def locked_message(seconds: int) -> str:
    minutes = max(1, -(-seconds // 60))   # round up: 61 s -> 2 min
    return f"Нууц үгийг олон удаа буруу оруулсан. {minutes} минутын дараа дахин оролдоно уу."


def login_page(next_path: str, error: str | None = None) -> str:
    """The login HTML. ``next_path`` must already be safe (safe_next); it is escaped anyway."""
    error_html = f'<div class="error" role="alert">{html.escape(error)}</div>' if error else ""
    return _PAGE.format(error=error_html, next=html.escape(next_path, quote=True))
