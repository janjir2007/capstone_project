"""Streamlit entry point (tasks 5.1–5.3, D-022).

Run:  cd src/ui && streamlit run app.py   (from src/ui/ so .streamlit/config.toml = theme applies)
Env:  API_URL (default http://localhost:8000)
Login (task 8.5r, D-117): the API decides. UI_PASSWORD + AUTH_SECRET live in the API's
environment; unset UI_PASSWORD there -> no login (local dev). The UI only reads the cookie.
"""

import sys
from pathlib import Path

# `streamlit run` puts only src/ui/ on sys.path; add the repo root so the
# pages can `from src.ui import ...` (same import style as the tests).
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from src.ui import api_client, auth, common  # noqa: E402

st.set_page_config(
    page_title="Тос солилт",
    page_icon=":material/oil_barrel:",
    layout="centered",
    initial_sidebar_state="collapsed",
)
common.inject_css()
# 8.4 phone check: open any page with ?diag=1 -> the record screen shows the photo size for this
# session (in-app page switches drop query params, so remember it here).
if st.query_params.get("diag") == "1":
    st.session_state[common.DIAG] = True


def login_screen() -> None:
    """Not logged in (or the cookie has just expired): only a link to the API's login page.
    Behind Caddy this screen is rare: Caddy already sends a browser without a valid cookie
    to /auth/login before Streamlit is reached."""
    common.header("Нэвтрэх")
    with st.container(key="card_login"):
        common.html_block("<p>Үргэлжлүүлэхийн тулд нэвтэрнэ үү.</p>")
        # target="_self": the same tab; the API's page sets the cookie and comes back here
        common.html_block(f'<a class="logout" href="{auth.login_url()}" target="_self">Нэвтрэх</a>')


check_error: api_client.ApiError | None = None
try:
    status = common.auth_status(common.session_cookie())
except api_client.ApiError as exc:
    status, check_error = None, exc   # the API did not answer: open nothing (fail closed)


def connection_error_screen() -> None:
    """The login check failed (API down): the usual connection message, no screens."""
    common.header("Нэвтрэх")
    if check_error is not None:
        common.show_api_error(check_error)


if status is None:
    # Only the login page exists until the API accepts the cookie, so no other
    # page can be opened by URL (login-bypass guard, 5.3).
    gate = login_screen if check_error is None else connection_error_screen
    st.navigation([st.Page(gate, title="Нэвтрэх")], position="hidden").run()
else:
    st.session_state[common.LOGIN_ON] = status.get("login_required", False)
    # Screens navigate with their own big buttons (DESIGN v2), so the menu is hidden.
    pages = [
        st.Page(common.HOME_PAGE, title="Нүүр", default=True),
        st.Page(common.RECORD_PAGE, title="Бүртгэх"),
        st.Page(common.SEARCH_PAGE, title="Хайх"),
        st.Page(common.CARD_PAGE, title="Машины карт"),
        st.Page(common.REMINDERS_PAGE, title="Сануулга"),
        st.Page(common.DASHBOARD_PAGE, title="Хяналтын самбар"),
    ]
    st.navigation(pages, position="hidden").run()
