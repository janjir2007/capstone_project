"""Login gate of the UI (task 8.5r, D-117; before: D-061 password form in Streamlit).

The UI no longer knows the password. The API serves the login page (/auth/login) and
sets an HttpOnly cookie; Caddy checks that cookie before every request. The UI checks
it a second time by asking the API (GET /auth/check), so a Caddy mistake or a direct
connection to Streamlit still shows only the login link. This module has no Streamlit
import: the cookie is read in app.py (st.context.cookies).
"""

from urllib.parse import quote

from src.ui import api_client

COOKIE_NAME = "ocp_session"   # = src/api/auth.py COOKIE_NAME
LOGIN_URL = "/auth/login"
LOGOUT_URL = "/auth/logout"


def status(token: str | None) -> dict | None:
    """{"login_required": bool} when this browser may use the app, None when it must log in.

    Raises api_client.ApiError when the API cannot answer (shown as a connection error;
    nothing is opened then either).
    """
    return api_client.auth_check(token)


def login_url(next_path: str = "/") -> str:
    """Link to the API's login page; after login the browser comes back to next_path."""
    if not next_path.startswith("/") or next_path == "/":
        return LOGIN_URL
    return f"{LOGIN_URL}?next={quote(next_path, safe='')}"
