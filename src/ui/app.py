"""Streamlit entry point (tasks 5.1–5.3, D-022).

Run:  cd src/ui && streamlit run app.py   (from src/ui/ so .streamlit/config.toml = theme applies)
Env:  API_URL (default http://localhost:8000)
      UI_PASSWORD (unset -> no login, local dev; D-061)
"""

import sys
from pathlib import Path

# `streamlit run` puts only src/ui/ on sys.path; add the repo root so the
# pages can `from src.ui import ...` (same import style as the tests).
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from src.ui import auth, common  # noqa: E402

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
    """Password screen; shown only when UI_PASSWORD is set."""
    common.header("Нэвтрэх")
    with st.form("login", border=False), st.container(key="card_login"):
        password = st.text_input("Нууц үг", type="password")
        if st.form_submit_button("Нэвтрэх", width="stretch", type="primary"):
            if auth.check_password(password):
                st.session_state["authed"] = True
                st.rerun()
            st.error("Нууц үг буруу байна.")


if auth.login_required() and not st.session_state.get("authed"):
    # Only the login page exists until the password is right, so no other
    # page can be opened by URL.
    st.navigation([st.Page(login_screen, title="Нэвтрэх")], position="hidden").run()
else:
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
