"""Streamlit entry point (tasks 5.1–5.3, D-022).

Run:  streamlit run src/ui/app.py
Env:  API_URL (default http://localhost:8000)
      UI_PASSWORD (unset -> no login, local dev; D-061)
      UI_ENABLE_RECOGNIZE=1 (show the plate-recognize button, after task 4.3)
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
    page_icon="🛢️",
    layout="centered",
    initial_sidebar_state="collapsed",
)
common.inject_css()


def login_screen() -> None:
    """Password screen; shown only when UI_PASSWORD is set."""
    st.title("🛢️ Тос солилт")
    with st.form("login"):
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
    pages = [
        st.Page(common.RECORD_PAGE, title="Бүртгэл", icon=":material/add_circle:", default=True),
        st.Page(common.LOOKUP_PAGE, title="Хайлт", icon=":material/search:"),
    ]
    st.navigation(pages, position="top").run()
