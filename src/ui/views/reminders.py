"""Manager dashboard «Сануулга» (task 5.4, contract v0.5). Desktop-friendly, works on a phone.

- Segment counts (GET /stats/segments): 4 tiles.
- Due reminders (GET /reminders/due) in two groups: «Илгээх» and «Эрсдэлтэй»
  (at_risk, D-007: overdue by more than logic.AT_RISK_GRACE_DAYS). Each row: plate, phone, send_on,
  status, message text (st.code has a built-in copy button) and «Илгээсэн»
  -> POST /reminders/{service_id}/sent (already_sent shown). The API sends no SMS:
  the manager copies the text and sends it by phone.
"""

import html

import streamlit as st

from src.ui import api_client, common, logic

WIDE_CSS = """<style>
.block-container {max-width: 1100px;}
.seg-grid {display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin: 8px 0 8px;}
@media (max-width: 640px) {.seg-grid {grid-template-columns: repeat(2, 1fr);}}
.seg {background: #fff; border-radius: 16px; padding: 12px 16px; box-shadow: 0 1px 3px rgba(0,0,0,.06);}
.seg .k {display: flex; align-items: center; gap: 6px;}
.seg .v {font-size: 24px; font-weight: 600; margin-top: 2px;}
.rem-top {display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px;}
.rem-status {display: inline-flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600;
  border-radius: 999px; padding: 4px 10px;}
.rem-meta {font-size: 13px; color: #4B5563; margin: 8px 0; line-height: 1.6;}
.rem-meta b {color: #111827; font-weight: 500 !important;}
.note-line {display: flex; align-items: center; gap: 6px; font-size: 13px; color: #6B7280; margin: 0 0 8px;}
[data-testid="stCode"] pre {background: #F6F7F9; border: none; font-family: inherit; font-size: 14px;}
</style>"""


def on_sent(service_id: int) -> None:
    """«Илгээсэн»: mark in the API, keep the answer for the message, reload the list."""
    try:
        row = api_client.mark_reminder_sent(service_id)
    except api_client.NotLatestService:
        st.session_state["rem_msg"] = ("warning", "Энэ машин шинэ үйлчилгээтэй болсон — жагсаалтыг шинэчиллээ.")
    except api_client.ApiError as exc:
        st.session_state["rem_msg"] = ("error", " ".join(logic.error_messages(exc.status, exc.detail)))
    else:
        if row.get("already_sent"):
            st.session_state["rem_msg"] = ("info", f"Өмнө нь илгээсэн гэж тэмдэглэгдсэн ({row.get('sent_at', '')[:16]}).")
        else:
            st.session_state["rem_msg"] = ("success", f"Илгээсэн гэж тэмдэглэлээ · {row.get('phone') or ''}")


def segment_tiles(stats: dict) -> None:
    counts = stats.get("counts") or {}
    tiles = "".join(
        f'<div class="seg"><div class="k"><i class="dot" style="background:{logic.SEGMENT_DOTS[s]}"></i>'
        f'{logic.SEGMENT_LABELS[s]}</div><div class="v">{counts.get(s, 0)}</div></div>'
        for s in logic.SEGMENT_ORDER
    )
    st.markdown(f'<div class="seg-grid">{tiles}</div>', unsafe_allow_html=True)
    st.markdown(f'<span class="muted">Нийт {stats.get("total", 0)} машин · {stats.get("as_of", "")}</span>',
                unsafe_allow_html=True)


def reminder_row(r: dict) -> None:
    fg, bg = logic.STATUS_COLORS.get(r.get("status"), logic.PENDING_COLORS)
    status = logic.PREDICTION_STATUS_LABELS.get(r.get("status"), r.get("status") or "")
    with st.container(key=f"card_rem_{r['service_id']}"):
        st.markdown(
            f'<div class="rem-top"><span class="plate">{html.escape(r["identifier"])}</span>'
            f'<span class="rem-status" style="color:{fg};background:{bg}"><i class="dot" style="background:{fg}"></i>'
            f'{html.escape(status)} · '
            f'{html.escape(logic.days_left_text(r.get("days_left")))}</span></div>'
            f'<div class="rem-meta">Утас: <b>{html.escape(r.get("phone") or "—")}</b>'
            f' · {html.escape(r.get("driver_name") or "")} · {html.escape(r.get("company") or "")}<br>'
            f'Илгээх өдөр: <b>{html.escape(r.get("send_on", ""))}</b> · Таамаг: {html.escape(r.get("predicted_date", ""))}'
            f' · Сүүлд: {html.escape(r.get("last_change_date", ""))}</div>',
            unsafe_allow_html=True,
        )
        st.code(r.get("message_mn", ""), language=None, wrap_lines=True)
        st.button("Илгээсэн", key=f"sent_{r['service_id']}", on_click=on_sent, args=(r["service_id"],),
                  type="primary", width="stretch")


st.markdown(WIDE_CSS, unsafe_allow_html=True)
common.header("Сануулга", back=common.HOME_PAGE)

msg = st.session_state.pop("rem_msg", None)
if msg:
    getattr(st, msg[0])(msg[1])

st.subheader("Сегмент")
try:
    segment_tiles(api_client.segment_stats())
except api_client.ApiError as exc:
    common.show_api_error(exc)

try:
    due = api_client.reminders_due()
except api_client.ApiError as exc:
    due = None
    if exc.status == 503:
        st.info("Таамаглалын загвар ачаалагдаагүй — сануулга одоогоор гарахгүй.")
    else:
        common.show_api_error(exc)

if due is not None:
    if due.get("contact_is_placeholder"):
        st.markdown('<div class="note-line"><i class="dot" style="background:#A05A00"></i>'
                    'Мессеж дэх утас түр дугаар байна (API-д GEO_EXPERT_PHONE тохируулаагүй).</div>',
                    unsafe_allow_html=True)
    to_send, at_risk = logic.split_reminders(due.get("reminders") or [])
    st.button("Шинэчлэх", key="rem_refresh", type="tertiary")  # any click reruns -> reloads the list
    for title, group, empty in (
        ("Илгээх", to_send, "Илгээх сануулга алга."),
        ("Эрсдэлтэй", at_risk, "Эрсдэлтэй машин алга."),
    ):
        st.subheader(f"{title} ({len(group)})")
        if not group:
            st.markdown(f'<span class="muted">{empty}</span>', unsafe_allow_html=True)
        for r in group:
            reminder_row(r)

common.logout_button()
