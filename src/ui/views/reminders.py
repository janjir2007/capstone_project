"""«Сануулга» (task 5.4, DESIGN v5 / T9 mockup; one reminder per service since task 9.5c), contract v0.15.

- How it works card: the API sends nothing; the manager sends the text and taps «Илгээсэн».
- Messages are built by the API: one reminder REMINDER_DAYS (75) after the truck's latest service,
  once; a new service starts a new cycle.
- «Viber-ээр илгээх» (task 5.5, D-091): viber://forward link with the text pre-filled; the tap also
  reruns the app, so that row then asks «Илгээсэн үү?» -> «Тийм» marks it sent. No Viber API / auto send.
- «SMS илгээх» (task 9.5d, main button above Viber): sms: link with the driver's number and the text;
  opens the phone's SMS app, nothing is sent by the app; the manager then taps «Илгээсэн».
- 2 numbers: «Илгээх» (queue) and «Эргэж ирээгүй» (red when > 0; 9.12, was «Эрсдэлтэй»).
- «Өнөөдрийн дараалал» and «Эргэж ирээгүй» (API `segment` = at_risk = AT_RISK_DAYS (150)+ days, stays
  until sent or a new service): a row per truck = plate, driver, days since the change · phone,
  «Сануулах» / «Эргэж ирээгүй» pill; the message text (st.code has a copy button = desktop fallback);
  «Залгах» (tel:) and «Илгээсэн» -> POST /reminders/{id}/sent. Oldest first (API order).
- «Дахиж илгээхгүй» (the driver said stop) -> «Тийм» -> POST /reminders/stops: no more messages to
  that phone. «Мессеж хүсээгүй утас» lists them; «Буцаах» = DELETE (a mistaken tap).
- «Удахгүй»: GET /reminders/due?as_of=<API today + 7> minus today's list = reminders due this week.
- Link to «Хяналтын самбар» (segment counts, views/dashboard.py).
- 9.14a-3: switch «Сануулга (N) | Км шалгах (M)». «Км шалгах» (GET /km-checks/due): trucks without a
  km/day, 34+ days after their service — asks the driver for his km (not a reminder). A row like a
  reminder: plate, driver, days since · phone, «SMS илгээх» (sms: link with the km-check text) ->
  «Илгээсэн» (POST /km-checks/{id}/sent), «Залгах», «Дахиж илгээхгүй» (the same stop list), and
  «Хариу бүртгэх» = the truck's card with the km form open (the reply moves the reminder).
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


def on_sent(service_id: int) -> None:
    """«Илгээсэн» / «Тийм»: mark it sent in the API, keep the answer for the message, reload the list."""
    viber_tapped().discard(service_id)
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


def reminder_row(r: dict, first: bool) -> None:
    status, fg, bg = logic.reminder_pill(r)
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
    sms = logic.sms_url(r.get("phone"), r.get("message_mn"))
    if sms:  # 9.5d: main button; no rerun on tap, the manager then taps «Илгээсэн»
        st.link_button("SMS илгээх", sms, type="primary", width="stretch", icon=":material/sms:")
    viber_url = logic.viber_forward_url(r.get("message_mn"))
    if viber_url:
        st.link_button("Viber-ээр илгээх", viber_url, key=f"viber_{sid}", on_click=on_viber, args=(sid,),
                       type="secondary" if sms else "primary", width="stretch", icon=":material/send:")
    asking = sid in viber_tapped()
    with st.container(horizontal=True, key=f"rem_act_{sid}"):
        if r.get("phone"):
            st.link_button("Залгах", f"tel:{r['phone']}", width="stretch", icon=":material/call:")
        if not asking:
            st.button("Илгээсэн", key=f"sent_{sid}", on_click=on_sent, args=(sid,),
                      width="stretch", icon=":material/check:")
    if asking:
        with st.container(horizontal=True, vertical_alignment="center", key=f"rem_ask_{sid}"):
            common.html_block('<span class="act-t">Илгээсэн үү?</span>')
            st.button("Тийм", key=f"yes_{sid}", on_click=on_sent, args=(sid,), type="primary",
                      icon=":material/check:")
            st.button("Үгүй", key=f"no_{sid}", on_click=on_not_sent, args=(sid,))
    stop_controls(sid, r.get("phone"))


def stop_controls(sid: int, phone: str | None, prefix: str = "") -> None:
    """«Дахиж илгээхгүй» -> «… утсанд дахиж илгээхгүй юу?» «Тийм» / «Үгүй» (one stop list for reminders
    and km checks). ``prefix`` keeps the km-check widgets apart from the reminder ones."""
    if phone and sid in stop_asking():
        with st.container(horizontal=True, vertical_alignment="center", key=f"{prefix or 'rem_'}stop_ask_{sid}"):
            common.html_block(f'<span class="act-t">{html.escape(logic.phone_text(phone))} утсанд дахиж '
                              'илгээхгүй юу?</span>')
            st.button("Тийм", key=f"{prefix}stop_yes_{sid}", on_click=on_stop, args=(sid, phone), type="primary")
            st.button("Үгүй", key=f"{prefix}stop_no_{sid}", on_click=on_stop_cancel, args=(sid,))
    elif phone:  # the driver said "stop" (9.5b)
        st.button("Дахиж илгээхгүй", key=f"{prefix}stop_{sid}", on_click=on_stop_ask, args=(sid,), type="tertiary",
                  icon=":material/notifications_off:")


def on_km_sent(service_id: int) -> None:
    """Km check «Илгээсэн»: log it in the API (not a reminder), keep the answer for the message."""
    try:
        row = api_client.mark_km_check_sent(service_id)
    except api_client.NotLatestService:
        st.session_state["rem_msg"] = ("warning", "Энэ машин шинэ үйлчилгээтэй болсон — жагсаалтыг шинэчиллээ.")
    except api_client.ApiError as exc:
        st.session_state["rem_msg"] = ("error", " ".join(logic.error_messages(exc.status, exc.detail)))
    else:
        if row.get("already_sent"):
            st.session_state["rem_msg"] = ("info", f"Өмнө нь илгээсэн гэж тэмдэглэгдсэн ({row.get('sent_at', '')[:16]}).")
        else:
            st.session_state["rem_msg"] = ("success", f"Км асуусан гэж тэмдэглэлээ · {row.get('phone') or ''}")


def km_check_row(c: dict, first: bool) -> None:
    """One truck to ask for its km: like a reminder row, «Км асуух» pill, no Viber (9.14a-3)."""
    label, fg, bg = logic.KM_CHECK_PILL
    meta = " · ".join(t.replace(" ", "\u00a0") for t in
                      (logic.days_since_text(c.get("days_since")), logic.phone_text(c.get("phone")) or "утасгүй"))
    common.html_block(
        f'<div class="rem{"" if first else " sep"}"><span class="plate">{html.escape(c["identifier"])}</span>'
        f'<div class="who"><div class="n">{html.escape(c.get("driver_name") or c.get("company") or "—")}</div>'
        f'<div class="m">{html.escape(meta)}</div></div>'
        f'<span class="pill-st" style="color:{fg};background:{bg}">{html.escape(label)}</span></div>'
    )
    sid = c["service_id"]
    st.code(c.get("message_mn", ""), language=None, wrap_lines=True)  # copy button = desktop fallback
    sms = logic.sms_url(c.get("phone"), c.get("message_mn"))
    if sms:
        st.link_button("SMS илгээх", sms, type="primary", width="stretch", icon=":material/sms:")
    with st.container(horizontal=True, key=f"km_act_{sid}"):
        if c.get("phone"):
            st.link_button("Залгах", f"tel:{c['phone']}", width="stretch", icon=":material/call:")
        st.button("Илгээсэн", key=f"km_sent_{sid}", on_click=on_km_sent, args=(sid,),
                  width="stretch", icon=":material/check:")
    if st.button("Хариу бүртгэх", key=f"km_reply_{sid}", type="tertiary", icon=":material/speed:"):
        st.session_state[common.KM_FORM] = c["vehicle_id"]  # the card opens with the km form open
        st.session_state.pop(common.KM_PREVIEW, None)
        common.go_card(c["vehicle_id"])
    stop_controls(sid, c.get("phone"), prefix="km_")


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

# 9.14a-3: «Сануулга» page CSS (only while this screen is open): the list switch = segmented control
# (grey track, picked one white), full width, like the dashboard's period switch.
common.html_block("""<style>
.st-key-rem_tab, .st-key-rem_tab [data-testid="stButtonGroup"], .st-key-rem_tab div:has(> button) {width: 100% !important; max-width: none !important;}
.st-key-rem_tab div:has(> button) {display: flex; background: #E9ECF1; border-radius: 12px; padding: 4px; gap: 4px !important;}
.st-key-rem_tab button {flex: 1 1 0; min-width: 0; min-height: 44px; padding: 4px 8px !important; border-radius: 8px !important;
  background: transparent !important; color: var(--muted) !important; border: none !important; touch-action: manipulation;}
.st-key-rem_tab button[aria-checked="true"] {background: #fff !important; color: var(--ink) !important; box-shadow: 0 1px 2px rgba(16,24,40,.08);}
.st-key-rem_tab button p {font-size: 15px !important; font-weight: 500; white-space: nowrap;}
/* the pill goes under the driver line (as on the dashboard, 9.12): beside it the 390 px row broke
   «97 хоногийн өмнө» mid-word */
.rem {display: grid; grid-template-columns: auto minmax(0, 1fr); column-gap: 12px; row-gap: 6px;}
.rem .who {min-width: 0;} .rem .pill-st {grid-column: 2; justify-self: start;}
</style>""")

try:
    due = api_client.reminders_due()
except api_client.ApiError as exc:
    due = None
    common.show_api_error(exc)
try:
    km = api_client.km_checks_due()
except api_client.ApiError as exc:
    km = None
    common.show_api_error(exc)

reminders = (due or {}).get("reminders") or []
checks = (km or {}).get("checks") or []
tabs = {"rem": f"Сануулга ({len(reminders)})", "km": f"Км шалгах ({len(checks)})"}
tab = st.segmented_control("Жагсаалт", list(tabs), format_func=tabs.get, default="rem", required=True,
                           key="rem_tab", label_visibility="collapsed") or "rem"


def show_reminders(due: dict) -> None:
    """The reminder list (9.5c), unchanged by 9.14a-3 apart from sitting under the switch."""
    with st.container(key="card_how"):
        common.html_block(
            f'<div class="act"><span class="act-ic green">{common.icon("send")}</span><div>'
            '<div class="act-t">Гараар илгээнэ</div>'
            '<div class="act-s">«SMS илгээх» дарж мессежээ илгээгээд «Илгээсэн» дарна. '
            '«Viber-ээр илгээх» дарвал чатаа сонгоод илгээнэ, дараа нь «Тийм» дарна. '
            'Компьютер дээр мессежийг хуулж илгээгээд «Илгээсэн» дарна.</div></div></div>'
        )

    reminders = due.get("reminders") or []
    counts = logic.reminder_counts(reminders)
    red = ' style="color:#B42318"' if counts["at_risk"] else ""  # at risk: the customer may be lost
    common.html_block(
        '<div class="tiles two">'
        f'<div><div class="v">{counts["queue"]}</div><div class="k">Илгээх</div></div>'
        f'<div><div class="v"{red}>{counts["at_risk"]}</div><div class="k">{logic.SEGMENT_LABELS["at_risk"]}</div></div></div>')
    if due.get("contact_is_placeholder"):
        common.html_block('<div class="note-line"><i class="dot" style="background:#A05A00"></i>'
                          'Мессеж дэх утас түр дугаар байна (API-д CONTACT_PHONE тохируулаагүй).</div>')
    to_send, at_risk = logic.split_reminders(reminders)
    for key, title, group, empty in (
        ("queue", "Өнөөдрийн дараалал", to_send, "Өнөөдөр илгээх сануулга алга."),
        ("risk", logic.SEGMENT_LABELS["at_risk"], at_risk, "Эргэж ирээгүй машин алга."),
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
                f'<span class="v muted" style="font-weight:400">{html.escape(logic.reminder_pill(r)[0])}</span></div>'
                for r in soon
            )
            common.html_block(f'<div class="kv sm">{rows}</div>')


def show_km_checks(km: dict) -> None:
    """«Км шалгах»: how it works, then one row per truck (oldest check day first, API order)."""
    with st.container(key="card_km_how"):
        common.html_block(
            f'<div class="act"><span class="act-ic green">{common.icon("send")}</span><div>'
            '<div class="act-t">Жолоочоос км асууна</div>'
            '<div class="act-s">«SMS илгээх» дарж асуугаад «Илгээсэн» дарна. Жолооч хариу бичвэл '
            '«Хариу бүртгэх» дарж км-ийг оруулна: сануулгын огноо түүний гүйлтээр тооцогдоно.</div></div></div>'
        )
    if km.get("contact_is_placeholder"):
        common.html_block('<div class="note-line"><i class="dot" style="background:#A05A00"></i>'
                          'Мессеж дэх утас түр дугаар байна (API-д CONTACT_PHONE тохируулаагүй).</div>')
    checks = km.get("checks") or []
    st.subheader(f"Км асуух ({len(checks)})")
    with st.container(key="card_km_checks"):
        if not checks:
            common.html_block('<span class="muted">Өнөөдөр км асуух машин алга.</span>')
        for i, c in enumerate(checks):
            km_check_row(c, first=i == 0)


if tab == "km":
    if km is not None:
        show_km_checks(km)
elif due is not None:
    show_reminders(due)

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
