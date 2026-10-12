"""Home screen (DESIGN v4 / T7): greeting + today's date, two action cards (icon + title +
1-line subtitle), and the «Сануулга» card with today's reminder summary (GET /reminders/due)."""

from datetime import date

import streamlit as st

from src.ui import api_client, common, logic


def reminder_summary() -> str:
    """«Өнөөдөр сануулах: N» (the «Илгээх» group of the dashboard); plain hint if unavailable."""
    try:
        due = api_client.reminders_due()
    except api_client.ApiError:
        return "Үйлчлүүлэгчдэд сануулга илгээх"
    to_send, _ = logic.split_reminders(due.get("reminders") or [])
    return f"Өнөөдөр сануулах: {len(to_send)}"


common.header("Тос солилт")
st.markdown(f'<div class="greet">Сайн байна уу · {logic.today_text(date.today())}</div>', unsafe_allow_html=True)

with common.action_card("act_record", "camera", "Бүртгэх", "Зураг авч бүртгэх"):
    if st.button("Бүртгэх", key="home_record", width="stretch"):
        common.go_record_start()
with common.action_card("act_search", "search", "Хайх", "Дугаар эсвэл утсаар"):
    if st.button("Хайх", key="home_search", width="stretch"):
        st.switch_page(common.SEARCH_PAGE)
with common.action_card("act_reminders", "bell", "Сануулга", reminder_summary()):
    st.page_link(common.REMINDERS_PAGE, label="Сануулга", width="stretch")

common.logout_button()
