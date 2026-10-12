"""Streamlit pieces shared by the pages: mobile CSS, cached API reads, the
vehicle card, and hand-off of state between pages.

Hand-off pattern: a page that sends the user elsewhere stores a plain dict in
st.session_state (e.g. REC_PENDING) and calls st.switch_page. The target page
copies it into its widget keys at the very top of its run. Widget keys are not
written directly from another page, because Streamlit drops widget state of
widgets that were not drawn in the last run.
"""

import html

import streamlit as st

from src.ui import api_client, auth, logic

# Folder is "views", NOT "pages": Streamlit auto-runs a folder named pages/
# in legacy mode, which skips app.py (sys.path setup and the login gate) when
# a page URL like /lookup is opened directly.
RECORD_PAGE = "views/record.py"
LOOKUP_PAGE = "views/lookup.py"

REC_PENDING = "rec_pending"        # {"identifier_type", "identifier", "card" | None}
LOOKUP_PENDING = "lookup_pending"  # query string to search on arrival
OIL_CHANGER = "oil_changer_saved"  # remembered between saves (same person all day)

MOBILE_CSS = """
<style>
.block-container {padding-top: 2.5rem; padding-left: 1rem; padding-right: 1rem; max-width: 760px;}
h1 {font-size: 1.9rem !important;}
@media (max-width: 480px) {h1 {font-size: 1.55rem !important;}}
.vc-grid {display: grid; grid-template-columns: 1fr 1fr; gap: .5rem; margin: .5rem 0 .75rem;}
.vc-tile {border: 1px solid rgba(128,128,128,.3); border-radius: .5rem; padding: .45rem .6rem;}
.vc-tile .k {font-size: .78rem; opacity: .7;}
.vc-tile .v {font-size: 1.05rem; font-weight: 600; overflow-wrap: anywhere;}
.pc {border-radius: 1rem; padding: .8rem 1rem; margin: .25rem 0 .75rem;}
.pc-top {display: flex; justify-content: space-between; font-size: .85rem; font-weight: 600;}
.pc-big {font-size: 1.9rem; font-weight: 700; line-height: 1.2; margin: .15rem 0;}
.pc-sub {font-size: 1rem; font-weight: 500;}
.pc-bar {height: 6px; border-radius: 3px; background: rgba(0,0,0,.08); margin: .35rem 0;}
.pc-bar > div {height: 100%; border-radius: 3px;}
.pc-note {font-size: .78rem; opacity: .85;}
.vc-line {font-size: .9rem; padding: .3rem 0; border-bottom: 1px solid rgba(128,128,128,.2);}
</style>
"""


def inject_css() -> None:
    """Small CSS tweaks so screens read well at ~390 px phone width."""
    st.markdown(MOBILE_CSS, unsafe_allow_html=True)


def nav_link(to_lookup: bool) -> None:
    """One-tap link to the other screen (on phones the top menu is folded away)."""
    if to_lookup:
        st.page_link(LOOKUP_PAGE, label="Машин хайх", icon=":material/search:")
    else:
        st.page_link(RECORD_PAGE, label="Үйлчилгээ бүртгэх", icon=":material/add_circle:")


def recognize_photo(photo) -> tuple[str, bool, str]:
    """Send an uploaded/camera photo to POST /plates/recognize.

    Returns (plate, needs_manual, message). Any API failure -> ("", True, message):
    the oil changer types the plate, so recognition can never block the flow.
    """
    try:
        result = api_client.recognize_plate(photo.getvalue(), photo.name or "photo.jpg", photo.type or "image/jpeg")
    except api_client.ApiError as exc:
        return "", True, logic.recognize_error_message(exc.status)
    return logic.recognize_outcome(result)


def render_prediction(prediction: dict | None) -> None:
    """Status card: tinted by status, big 'N хоног', date, progress bar; grey if null."""
    v = logic.prediction_view(prediction)
    if v["pending"]:
        body = f'<div class="pc-big" style="font-size:1.05rem">{html.escape(v["big"])}</div>'
    else:
        bar = ""
        if v["progress"] is not None:
            bar = (f'<div class="pc-bar"><div style="width:{v["progress"] * 100:.0f}%;'
                   f'background:{v["fg"]}"></div></div>')
        body = (
            f'<div class="pc-top"><span class="pc-label">{html.escape(v["status_label"])}</span>'
            f'<span class="pc-date">{html.escape(v["date"] or "")}</span></div>'
            f'<div class="pc-big">{html.escape(v["big"])} <span class="pc-sub">{html.escape(v["sub"])}</span></div>'
            f'{bar}<div class="pc-note">{html.escape(v["note"])}</div>'
        )
    st.markdown(
        f'<div class="pc" style="color:{v["fg"]};background:{v["bg"]}">{body}</div>',
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=300, show_spinner=False)
def cached_destinations() -> list[dict]:
    """GET /destinations, cached 5 minutes (the list rarely changes)."""
    return api_client.destinations()


def show_api_error(exc: api_client.ApiError) -> None:
    """Show an API error as Mongolian message(s)."""
    for message in logic.error_messages(exc.status, exc.detail):
        st.error(message)


def go_record(identifier_type: str, identifier: str, card: dict | None) -> None:
    """Open the recording screen for this vehicle (card=None -> new vehicle)."""
    st.session_state[REC_PENDING] = {
        "identifier_type": identifier_type,
        "identifier": identifier,
        "card": card,
    }
    st.switch_page(RECORD_PAGE)


def go_lookup(query: str) -> None:
    """Open the lookup screen and search for `query` right away."""
    st.session_state[LOOKUP_PENDING] = query
    st.switch_page(LOOKUP_PAGE)


def _tile(label: str, value: str) -> str:
    return f'<div class="vc-tile"><div class="k">{html.escape(label)}</div><div class="v">{html.escape(value)}</div></div>'


def render_vehicle_card(card: dict, key: str, show_record_button: bool = True) -> None:
    """Draw one vehicle card: header, key numbers, prediction, history.

    `key` makes widget keys unique when several cards are on one screen.
    """
    last = card.get("last_service") or {}
    with st.container(border=True):
        st.markdown(f"#### {card['identifier']}")
        if card.get("segment"):
            st.badge(
                logic.segment_label(card["segment"]),
                color=logic.SEGMENT_COLORS.get(card["segment"], "gray"),
            )
        details = [
            (card.get("company") or {}).get("name") or logic.NOT_GIVEN,
            card.get("vehicle_model") or "",
            logic.IDENTIFIER_TYPE_LABELS.get(card.get("identifier_type", ""), ""),
        ]
        st.caption(" · ".join(d for d in details if d))

        tiles = [
            _tile("Үйлчилгээ", f"{card.get('service_count', 0)} удаа"),
            _tile("Ердийн литр", logic.format_number(card.get("usual_liters"), "л")),
            _tile("Сүүлийн огноо", last.get("service_date") or logic.NOT_GIVEN),
            _tile("Сүүлийн гүйлт", logic.service_meter_text(last) if last else logic.NOT_GIVEN),
            _tile("Тос", last.get("oil_grade") or logic.NOT_GIVEN),
            _tile("Чиглэл", logic.service_destination_text(last) if last else logic.NOT_GIVEN),
        ]
        st.markdown(f'<div class="vc-grid">{"".join(tiles)}</div>', unsafe_allow_html=True)

        if last.get("driver_name") or last.get("driver_phone"):
            driver = " · ".join(x for x in (last.get("driver_name"), last.get("driver_phone")) if x)
            st.markdown(f"**Жолооч:** {driver}")

        render_prediction(card.get("prediction"))

        history = card.get("history") or []
        with st.expander(f"Түүх ({len(history)})"):
            if not history:
                st.write("Түүх алга.")
            lines = "".join(
                f'<div class="vc-line">{html.escape(logic.service_line(s))}</div>' for s in history
            )
            st.markdown(lines, unsafe_allow_html=True)

        if show_record_button and st.button(
            "➕ Үйлчилгээ бүртгэх", key=f"rec_{key}", width="stretch", type="primary"
        ):
            go_record(card["identifier_type"], card["identifier"], card)


def logout_button() -> None:
    """'Log out' at the bottom of a page (only when login is on)."""
    if auth.login_required():
        st.divider()
        if st.button("Гарах", key="logout"):
            st.session_state["authed"] = False
            st.rerun()
