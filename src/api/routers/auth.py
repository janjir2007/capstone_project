"""Login, logout and the cookie check for Caddy (task 8.5r, D-117).

Only these /auth/* routes (and /health) are public through Caddy; every data route
stays inside the compose network (D-061, changed by D-117 for /auth/* only).

- GET  /auth/login   HTML form (password + «Намайг сана»)
- POST /auth/login   right password -> cookie + 303 to `next`; wrong -> 401; locked -> 429
- GET  /auth/logout  clears the cookie on this phone/computer -> 303 /auth/login
- GET  /auth/check   Caddy `forward_auth` asks this before EVERY UI request (pages, the
                     Streamlit websocket). 200 = let it through; otherwise a 302 to the login
                     page, which Caddy hands to the browser. The UI asks it too (second check).
"""

from __future__ import annotations

from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from src.api import auth

router = APIRouter(prefix="/auth", tags=["auth"])

MAX_FORM_BYTES = 4096    # the form has 4 short fields; Caddy also limits /auth/* bodies
NO_STORE = {"Cache-Control": "no-store"}


def _config(request: Request) -> auth.AuthConfig | None:
    return request.app.state.auth


def _now(request: Request) -> float:
    return request.app.state.clock()


def _login_redirect(next_path: str) -> RedirectResponse:
    target = "/auth/login"
    if next_path != "/":
        target += "?next=" + quote(next_path, safe="")
    return RedirectResponse(target, status_code=302, headers=NO_STORE)


def _page(next_path: str, error: str | None = None, status: int = 200) -> HTMLResponse:
    return HTMLResponse(auth.login_page(next_path, error), status_code=status, headers=NO_STORE)


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/") -> Response:
    """The login page. Already logged in (or login off) -> straight to `next`."""
    target = auth.safe_next(next)
    config = _config(request)
    if config is None or auth.token_valid(config.key, request.cookies.get(auth.COOKIE_NAME), _now(request)):
        return RedirectResponse(target, status_code=303, headers=NO_STORE)
    return _page(target)


@router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request) -> Response:
    """Check the password; the form is read with the standard library (urllib parse_qs)."""
    config = _config(request)
    body = await request.body()
    if len(body) > MAX_FORM_BYTES:
        return Response(status_code=413)
    form = parse_qs(body.decode("utf-8", errors="replace"), max_num_fields=10)
    target = auth.safe_next(form.get("next", ["/"])[0])
    if config is None:
        return RedirectResponse(target, status_code=303, headers=NO_STORE)

    ip = auth.client_ip(request.headers, request.client.host if request.client else None)
    now = _now(request)
    limiter: auth.LoginLimiter = request.app.state.login_limiter
    locked = limiter.seconds_locked(ip, now)
    if locked:   # while locked even the right password is refused
        return _page(target, auth.locked_message(locked), status=429)

    if not auth.check_password(form.get("password", [""])[0], config.password):
        if limiter.record_failure(ip, now):
            return _page(target, auth.locked_message(limiter.lock_seconds), status=429)
        return _page(target, auth.WRONG_PASSWORD, status=401)

    limiter.record_success(ip)
    remember = form.get("remember", [""])[0] == "1"
    lifetime = auth.REMEMBER_SECONDS if remember else auth.SESSION_SECONDS
    response = RedirectResponse(target, status_code=303, headers=NO_STORE)
    response.set_cookie(
        auth.COOKIE_NAME, auth.make_token(config.key, now, lifetime),
        max_age=auth.REMEMBER_SECONDS if remember else None,   # None = gone when the browser closes
        path="/", secure=True, httponly=True, samesite="lax",
    )
    return response


@router.get("/logout")
def logout() -> Response:
    """«Гарах»: delete the cookie on this device only (other phones stay logged in)."""
    response = RedirectResponse("/auth/login", status_code=303, headers=NO_STORE)
    response.delete_cookie(auth.COOKIE_NAME, path="/", secure=True, httponly=True, samesite="lax")
    return response


@router.get("/check")
def check(request: Request) -> Response:
    """200 {"login_required": bool} when the request may go on, else 302 to the login page.

    Caddy forward_auth sends the original path in X-Forwarded-Uri; it becomes `next`.
    """
    config = _config(request)
    if config is None:
        return JSONResponse({"login_required": False}, headers=NO_STORE)
    if auth.token_valid(config.key, request.cookies.get(auth.COOKIE_NAME), _now(request)):
        return JSONResponse({"login_required": True}, headers=NO_STORE)
    return _login_redirect(auth.safe_next(request.headers.get("x-forwarded-uri")))
