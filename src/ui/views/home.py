"""Home screen (DESIGN v5 / T9 mockup): «ГЭ Гео-Эксперт» + date, «Сайн байна уу» + today's
reminder line, 3 numbers (to remind / overdue / all trucks), the blue «Үйлчилгээ бүртгэх» card,
one card with «Хайх», «Сануулга» (red count badge) and «Хяналтын самбар» (8.1), and «Сүүлд үзсэн»
(this session)."""

from datetime import date

import streamlit as st

from src.ui import api_client, common, logic


def reminder_counts() -> dict[str, int] | None:
    """Counts from GET /reminders/due; None when the API has no predictions (503) or is down."""
    try:
        due = api_client.reminders_due()
    except api_client.ApiError:
        return None
    return logic.reminder_counts(due.get("reminders") or [])


def total_vehicles() -> int | None:
    try:
        return api_client.segment_stats().get("total")
    except api_client.ApiError:
        return None


counts = reminder_counts()
total = total_vehicles()

common.home_header(date.today())
if counts is None:
    greet = "Тос солилтын бүртгэл, сануулга."
elif counts["to_send"]:
    greet = f"Өнөөдөр {counts['to_send']} машин сануулга хүлээж байна."
else:
    greet = "Өнөөдөр сануулах машин алга."
common.html_block(f'<div class="greet">{greet}</div>')


def _num(value: int | None) -> str:
    return logic.NOT_GIVEN if value is None else str(value)


overdue = None if counts is None else counts["overdue"]
red = ' style="color:#B42318"' if overdue else ""
common.html_block(
    '<div class="stats">'
    f'<div><div class="k">Сануулах</div><div class="v">{_num(None if counts is None else counts["to_send"])}</div></div>'
    f'<div><div class="k">Хэтэрсэн</div><div class="v"{red}>{_num(overdue)}</div></div>'
    f'<div><div class="k">Машин</div><div class="v">{_num(total)}</div></div></div>'
)

with common.action_card("act_record", "camera", "Үйлчилгээ бүртгэх", "Дугаарын зураг авч эхлэх"):
    if st.button("Үйлчилгээ бүртгэх", key="home_record", width="stretch"):
        common.go_record_start()
with st.container(key="grp_nav"):
    with common.action_card("act_search", "search", "Хайх", "Дугаар эсвэл утсаар"):
        if st.button("Хайх", key="home_search", width="stretch"):
            st.switch_page(common.SEARCH_PAGE)
    with common.action_card("act_reminders", "bell", "Сануулга", "Жолооч нарт мессеж илгээх", tone="amber",
                            badge=counts["to_send"] if counts else None):
        # A real button, like «Хайх»: st.page_link's <a> is only one text line tall inside
        # the stretched wrapper, so most of the card did nothing when tapped (5.9b).
        if st.button("Сануулга", key="home_reminders", width="stretch"):
            st.switch_page(common.REMINDERS_PAGE)
    with common.action_card("act_dashboard", "chart", "Хяналтын самбар", "Сегмент, машины тоо", tone="green"):
        if st.button("Хяналтын самбар", key="home_dashboard", width="stretch"):  # 8.1 -> 5.4 manager screen
            st.switch_page(common.DASHBOARD_PAGE)

if st.session_state.get(common.RECENT):
    common.section("Сүүлд үзсэн", right="Өнөөдөр")
    common.recent_rows("home_recent")

common.logout_button()
