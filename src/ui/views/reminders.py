"""«Сануулга» (task 5.4, DESIGN v5 / T9 mockup; month stages since task 9.5b), contract v0.13.

- How it works card: the API sends nothing; the manager sends the text and taps «Илгээсэн».
- Messages are built by the API: stage 1m / 2m / 3m = 30 / 60 / 90 days after the truck's latest
  service, only the highest stage reached, each stage once; a new service starts again.
- «Viber-ээр илгээх» (task 5.5, D-091): viber://forward link with the text pre-filled; the tap also
  reruns the app, so that row then asks «Илгээсэн үү?» -> «Тийм» marks it sent. No Viber API / auto send.
- 3 numbers: messages per stage today («1 сар», «2 сар», «3 сар»).
- «Өнөөдрийн дараалал» (1m, 2m) and «Эрсдэлтэй» (API `segment` = at_risk = 90+ days, 3m): a row per
  truck = plate, driver, days since the change · phone, stage pill; the message text (st.code has a
  copy button = desktop fallback); «Залгах» (tel:) and «Илгээсэн» -> POST /reminders/{id}/sent?stage=.
- «Дахиж илгээхгүй» (the driver said stop) -> «Тийм» -> POST /reminders/stops: no more messages to
  that phone. «Мессеж хүсээгүй утас» lists them; «Буцаах» = DELETE (a mistaken tap).
- «Удахгүй»: GET /reminders/due?as_of=<API today + 7> minus today's list = stages starting this week.
- Link to «Хяналтын самбар» (segment counts, views/dashboard.py).
"""

import html
from datetime import date, timedelta

import streamlit as st

from src.ui import api_client, common, logic

UPCOMING_DAYS = 7
VIBER_TAPPED = "rem_viber_tapped"  # session: service_ids whose Viber link was tapped -> ask «Илгээсэн үү?»
STOP_ASKING = "rem_stop_asking"    # session: service_ids whose «Дахиж илгээхгүй» was tapped -> ask to confirm


def viber_tapped() -> set[int]:
    return st.session_state.setdefault(VIBER_TAPPED, set())


def on_viber(service_id: int) -> None:
    """«Viber-ээр илгээх» tapped: the browser opens Viber; this rerun shows the confirm question."""
    viber_tapped().add(service_id)


def on_not_sent(service_id: int) -> None:
    """«Үгүй»: hide the question again (e.g. the manager closed Viber without sending)."""
    viber_tapped().discard(service_id)


def stop_asking() -> set[int]:
    return st.session_state.setdefault(STOP_ASKING, set())


def on_stop_ask(service_id: int) -> None:
    stop_asking().add(service_id)


def on_stop_cancel(service_id: int) -> None:
    stop_asking().discard(service_id)


def on_stop(service_id: int, phone: str) -> None:
    """«Тийм» after «Дахиж илгээхгүй»: this phone gets no more reminders (any truck)."""
    stop_asking().discard(service_id)
    try:
        api_client.stop_phone(phone)
    except api_client.ApiError as exc:
        st.session_state["rem_msg"] = ("error", " ".join(logic.error_messages(exc.status, exc.detail)))
    else:
        st.session_state["rem_msg"] = ("success", f"{logic.phone_text(phone)} утсанд дахиж мессеж илгээхгүй.")


def on_unstop(phone: str) -> None:
    """«Буцаах»: reminders go to this phone again."""
    try:
        api_client.unstop_phone(phone)
    except api_client.ApiError as exc:
        st.session_state["rem_msg"] = ("error", " ".join(logic.error_messages(exc.status, exc.detail)))
    else:
        st.session_state["rem_msg"] = ("success", f"{logic.phone_text(phone)} утсанд дахин сануулга очно.")


def on_sent(service_id: int, stage: str) -> None:
    """«Илгээсэн» / «Тийм»: mark this stage in the API, keep the answer for the message, reload the list."""
    viber_tapped().discard(service_id)
    try:
        row = api_client.mark_reminder_sent(service_id, stage)
    except api_client.NotLatestService:
        st.session_state["rem_msg"] = ("warning", "Энэ машин шинэ үйлчилгээтэй болсон — жагсаалтыг шинэчиллээ.")
    except api_client.ApiError as exc:
        st.session_state["rem_msg"] = ("error", " ".join(logic.error_messages(exc.status, exc.detail)))
    else:
        if row.get("already_sent"):
            st.session_state["rem_msg"] = ("info", f"Өмнө нь илгээсэн гэж тэмдэглэгдсэн ({row.get('sent_at', '')[:16]}).")
        else:
            st.session_state["rem_msg"] = ("success", f"Илгээсэн гэж тэмдэглэлээ · {row.get('phone') or ''}")


def reminder_row(r: dict, first: bool) -> None:
    stage = r.get("stage")
    fg, bg = logic.STAGE_COLORS.get(stage, logic.PENDING_COLORS)
    status = logic.stage_label(stage)
    meta = " · ".join(t.replace(" ", "\u00a0") for t in  # number + unit / phone never split
                      (logic.days_since_text(r.get("days_since")), logic.phone_text(r.get("phone")) or "утасгүй"))
    common.html_block(
        f'<div class="rem{"" if first else " sep"}"><span class="plate">{html.escape(r["identifier"])}</span>'
        f'<div class="who"><div class="n">{html.escape(r.get("driver_name") or r.get("company") or "—")}</div>'
        f'<div class="m">{html.escape(meta)}</div></div>'
        f'<span class="pill-st" style="color:{fg};background:{bg}">{html.escape(status)}</span></div>'
    )
    sid = r["service_id"]
    st.code(r.get("message_mn", ""), language=None, wrap_lines=True)  # copy button = desktop fallback
    viber_url = logic.viber_forward_url(r.get("message_mn"))
    if viber_url:
        st.link_button("Viber-ээр илгээх", viber_url, key=f"viber_{sid}", on_click=on_viber, args=(sid,),
                       type="primary", width="stretch", icon=":material/send:")
    asking = sid in viber_tapped()
    with st.container(horizontal=True, key=f"rem_act_{sid}"):
        if r.get("phone"):
            st.link_button("Залгах", f"tel:{r['phone']}", width="stretch", icon=":material/call:")
        if not asking:
            st.button("Илгээсэн", key=f"sent_{sid}", on_click=on_sent, args=(sid, stage),
                      width="stretch", icon=":material/check:")
    if asking:
        with st.container(horizontal=True, vertical_alignment="center", key=f"rem_ask_{sid}"):
            common.html_block('<span class="act-t">Илгээсэн үү?</span>')
            st.button("Тийм", key=f"yes_{sid}", on_click=on_sent, args=(sid, stage), type="primary",
                      icon=":material/check:")
            st.button("Үгүй", key=f"no_{sid}", on_click=on_not_sent, args=(sid,))
    phone = r.get("phone")
    if phone and sid in stop_asking():
        with st.container(horizontal=True, vertical_alignment="center", key=f"rem_stop_ask_{sid}"):
            common.html_block(f'<span class="act-t">{html.escape(logic.phone_text(phone))} утсанд дахиж '
                              'илгээхгүй юу?</span>')
            st.button("Тийм", key=f"stop_yes_{sid}", on_click=on_stop, args=(sid, phone), type="primary")
            st.button("Үгүй", key=f"stop_no_{sid}", on_click=on_stop_cancel, args=(sid,))
    elif phone:  # the driver said "stop" (9.5b)
        st.button("Дахиж илгээхгүй", key=f"stop_{sid}", on_click=on_stop_ask, args=(sid,), type="tertiary",
                  icon=":material/notifications_off:")


def upcoming(as_of: str, today_ids: set[int]) -> list[dict]:
    """Reminders due within UPCOMING_DAYS after the API's today, not in today's list."""
    start = date.fromisoformat(as_of) if as_of else date.today()
    try:
        later = api_client.reminders_due((start + timedelta(days=UPCOMING_DAYS)).isoformat())
    except api_client.ApiError:
        return []
    return [r for r in later.get("reminders") or [] if r["service_id"] not in today_ids]


common.header("Сануулга", back=common.HOME_PAGE)

msg = st.session_state.pop("rem_msg", None)
if msg:
    getattr(st, msg[0])(msg[1])

with st.container(key="card_how"):
    common.html_block(
        f'<div class="act"><span class="act-ic green">{common.icon("send")}</span><div>'
        '<div class="act-t">Гараар илгээнэ</div>'
        '<div class="act-s">«Viber-ээр илгээх» дарж чатаа сонгоод илгээнэ, дараа нь «Тийм» дарна. '
        'Компьютер дээр мессежийг хуулж илгээгээд «Илгээсэн» дарна.</div></div></div>'
    )

try:
    due = api_client.reminders_due()
except api_client.ApiError as exc:
    due = None
    common.show_api_error(exc)

if due is not None:
    reminders = due.get("reminders") or []
    counts = logic.reminder_counts(reminders)
    red = ' style="color:#B42318"'  # 3 months: time to change the oil
    common.html_block('<div class="tiles">' + "".join(
        f'<div><div class="v"{red if s == "3m" and counts[s] else ""}>{counts[s]}</div>'
        f'<div class="k">{logic.STAGE_LABELS[s]}</div></div>' for s in logic.STAGE_LABELS) + '</div>')
    if due.get("contact_is_placeholder"):
        common.html_block('<div class="note-line"><i class="dot" style="background:#A05A00"></i>'
                          'Мессеж дэх утас түр дугаар байна (API-д CONTACT_PHONE тохируулаагүй).</div>')
    to_send, at_risk = logic.split_reminders(reminders)
    for key, title, group, empty in (
        ("queue", "Өнөөдрийн дараалал", to_send, "Өнөөдөр илгээх сануулга алга."),
        ("risk", "Эрсдэлтэй", at_risk, "Эрсдэлтэй машин алга."),
    ):
        st.subheader(f"{title} ({len(group)})")
        with st.container(key=f"card_{key}"):
            if not group:
                common.html_block(f'<span class="muted">{empty}</span>')
            for i, r in enumerate(group):
                reminder_row(r, first=i == 0)

    soon = upcoming(due.get("as_of", ""), {r["service_id"] for r in reminders})
    if soon:
        st.subheader("Удахгүй")
        with st.container(key="card_soon"):
            rows = "".join(
                f'<div><span class="k"><span class="plate">{html.escape(r["identifier"])}</span>'
                f'&nbsp; {html.escape(logic.month_day_text(r.get("send_on")))}</span>'
                f'<span class="v muted" style="font-weight:400">{html.escape(logic.stage_label(r.get("stage")))}</span></div>'
                for r in soon
            )
            common.html_block(f'<div class="kv sm">{rows}</div>')

try:
    stops = api_client.reminder_stops()
except api_client.ApiError:
    stops = []
if stops:  # 9.5b: phones that asked for no more messages; «Буцаах» undoes a mistaken tap
    with st.expander(f"Мессеж хүсээгүй утас ({len(stops)})"):
        for s in stops:
            with st.container(horizontal=True, vertical_alignment="center", key=f"stop_row_{s['phone']}"):
                common.html_block(f'<span class="act-t">{html.escape(logic.phone_text(s["phone"]))}</span>')
                st.button("Буцаах", key=f"unstop_{s['phone']}", on_click=on_unstop, args=(s["phone"],),
                          type="tertiary")

with st.container(key="link_center", horizontal=True, horizontal_alignment="center"):
    if st.button("Машинуудын тойм харах", key="link_dashboard", type="tertiary"):
        st.switch_page(common.DASHBOARD_PAGE)
    st.button("Шинэчлэх", key="rem_refresh", type="tertiary")  # any click reruns -> reloads the list

common.logout_button()
