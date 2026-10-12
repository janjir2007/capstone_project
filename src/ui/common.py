"""Streamlit pieces shared by the screens — DESIGN v2 (task 5.3c).

Design: grey background #F4F5F7 (theme, .streamlit/config.toml), white cards
(radius 24, soft shadow), buttons >= 56 px high, primary #1F4E9D, one column,
Mongolian only. CSS is kept minimal and hooks onto Streamlit's `st-key-<key>`
classes: any container whose key starts with "card_" becomes a white card.

Hand-off between screens: a screen stores a plain value in st.session_state
(REC_PENDING, CARD_ID, SEARCH_PENDING) and calls st.switch_page. The target
screen reads it at the top of its run. Widget keys are not written from another
screen, because Streamlit drops the state of widgets not drawn in the last run.
"""

import html

import streamlit as st

from src.ui import api_client, auth, logic

# Folder is "views", NOT "pages": Streamlit auto-runs a folder named pages/
# in legacy mode, which skips app.py (sys.path setup and the login gate) when
# a page URL is opened directly.
HOME_PAGE = "views/home.py"
RECORD_PAGE = "views/record.py"
SEARCH_PAGE = "views/search.py"
CARD_PAGE = "views/card.py"

REC_PENDING = "rec_pending"        # {"identifier_type", "identifier", "card" | None}
REC_RESET = "rec_reset"            # True -> record screen starts at the camera step
CARD_ID = "card_id"                # vehicle shown on the card screen
SEARCH_PENDING = "search_pending"  # query to search on arrival
RECENT = "recent_vehicles"         # "Сүүлд үзсэн": [{id, identifier, company}], this session only
OIL_CHANGER = "oil_changer_saved"  # remembered between saves (same person all day)
RECENT_MAX = 5

CSS = """
<style>
.block-container {padding-top: 1.25rem; padding-bottom: 3rem; padding-left: 1rem; padding-right: 1rem; max-width: 560px;}
h1 {font-size: 2rem !important; font-weight: 800 !important; padding: .25rem 0 .5rem !important;}
.stButton button, .stFormSubmitButton button {min-height: 56px; border-radius: 18px; font-size: 1.05rem; font-weight: 600;}
[class*="st-key-card_"] {background: #fff; border-radius: 24px; padding: 1.1rem 1rem;
  box-shadow: 0 1px 2px rgba(16,24,40,.05), 0 6px 18px rgba(16,24,40,.06);}
[class*="st-key-btn_black"] button {background: #111; color: #fff; border-color: #111;}
[class*="st-key-btn_black"] button:hover {background: #333; color: #fff; border-color: #333;}
.st-key-back button {min-height: 40px; padding: 0 .25rem; font-size: 1rem;}
.st-key-home_record button {min-height: 150px; border-radius: 24px; font-size: 1.6rem;}
.st-key-home_search button {min-height: 110px; border-radius: 24px; font-size: 1.4rem; background: #fff; border: none;
  box-shadow: 0 1px 2px rgba(16,24,40,.05), 0 6px 18px rgba(16,24,40,.06);}
.st-key-home_record button p {font-size: 1.7rem !important; font-weight: 800 !important;}
.st-key-home_search button p {font-size: 1.45rem !important; font-weight: 800 !important;}
.stButton button p, .stFormSubmitButton button p {font-size: 1.05rem; font-weight: 600;}
.geo-pill {display: inline-block; font-size: .75rem; font-weight: 700; padding: .25rem .7rem; border-radius: 999px;
  background: #E6ECF7; color: #1F4E9D;}
.plate-box {font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: 2.1rem; font-weight: 700;
  letter-spacing: .06em; text-align: center; border: 3px solid #111; border-radius: 12px; padding: .45rem .5rem;
  background: #fff; margin: .25rem 0 .6rem; overflow-wrap: anywhere;}
.plate-box.small {font-size: 1.5rem; border-width: 2px; padding: .3rem .4rem;}
.chip {display: inline-block; padding: .3rem .8rem; border-radius: 999px; font-size: .9rem; font-weight: 600;}
.chip.known {background: #e3f1e7; color: #1e6b34;} .chip.new {background: #E6ECF7; color: #1F4E9D;}
.muted {color: #5f6368; font-size: .9rem;}
.tiles {display: grid; grid-template-columns: repeat(3, 1fr); gap: .5rem; margin: .5rem 0;}
.tile {background: #F4F5F7; border-radius: 14px; padding: .55rem .6rem;}
.tile .k {font-size: .72rem; color: #5f6368;} .tile .v {font-size: .95rem; font-weight: 700; overflow-wrap: anywhere;}
.call-row {display: flex; justify-content: space-between; align-items: center; gap: .5rem;
  background: #F4F5F7; border-radius: 14px; padding: .55rem .6rem .55rem .8rem; margin: .5rem 0;}
.call-row .who {font-size: .95rem; overflow-wrap: anywhere;}
.call-row a {background: #1F4E9D; color: #fff !important; text-decoration: none; font-weight: 700;
  border-radius: 14px; padding: .7rem 1rem; white-space: nowrap;}
.pc {border-radius: 18px; padding: .85rem 1rem; margin: .25rem 0 .5rem;}
.pc-top {display: flex; justify-content: space-between; font-size: .85rem; font-weight: 700;}
.pc-big {font-size: 2.2rem; font-weight: 800; line-height: 1.15; margin: .15rem 0;}
.pc-sub {font-size: 1rem; font-weight: 600;}
.pc-bar {height: 8px; border-radius: 4px; background: rgba(0,0,0,.08); margin: .4rem 0;}
.pc-bar > div {height: 100%; border-radius: 4px;}
.pc-note {font-size: .78rem;}
.hist {font-size: .9rem; padding: .35rem 0; border-bottom: 1px solid #E3E5E9;}
.done {text-align: center; font-size: 4rem; line-height: 1; color: #1e6b34;}
.done-title {text-align: center; font-size: 1.6rem; font-weight: 800; margin: .25rem 0 .5rem;}
</style>
"""


def inject_css() -> None:
    """DESIGN v2 tweaks on top of the theme (kept minimal on purpose)."""
    st.markdown(CSS, unsafe_allow_html=True)


# --- layout ------------------------------------------------------------------------

def header(title: str, back: str | None = None) -> None:
    """Screen header: back button (inner screens) + "Гео-Эксперт" pill + big title."""
    with st.container(horizontal=True, vertical_alignment="center", horizontal_alignment="distribute"):
        if back:
            if st.button("‹ Буцах", key="back", type="tertiary"):
                st.switch_page(back)
        st.markdown('<span class="geo-pill">Гео-Эксперт</span>', unsafe_allow_html=True)
    st.title(title)


def plate_box(identifier: str, small: bool = False) -> None:
    """The plate in large monospace inside a bordered box (like the real plate)."""
    cls = "plate-box small" if small else "plate-box"
    st.markdown(f'<div class="{cls}">{html.escape(identifier or "")}</div>', unsafe_allow_html=True)


def known_chip(card: dict | None) -> None:
    """Chip under the plate: «Бүртгэлтэй · N удаа ирсэн» or «Шинэ машин»."""
    if card:
        text, cls = f"Бүртгэлтэй · {card.get('service_count', 0)} удаа ирсэн", "known"
    else:
        text, cls = "Шинэ машин", "new"
    st.markdown(f'<span class="chip {cls}">{html.escape(text)}</span>', unsafe_allow_html=True)


def segment_badge(segment: str | None) -> None:
    if segment:
        st.badge(logic.segment_label(segment), color=logic.SEGMENT_COLORS.get(segment, "gray"))


def logout_button() -> None:
    """«Гарах» at the bottom of a screen (only when login is on)."""
    if auth.login_required():
        if st.button("Гарах", key="logout", type="tertiary"):
            st.session_state["authed"] = False
            st.rerun()


# --- navigation ----------------------------------------------------------------------

def go_record(identifier_type: str, identifier: str, card: dict | None) -> None:
    """Open the service form for this vehicle (card=None -> new vehicle)."""
    st.session_state[REC_PENDING] = {"identifier_type": identifier_type, "identifier": identifier, "card": card}
    st.switch_page(RECORD_PAGE)


def go_record_start() -> None:
    """Open the record screen at the camera step (a new truck)."""
    st.session_state[REC_RESET] = True
    st.switch_page(RECORD_PAGE)


def go_card(vehicle_id: int) -> None:
    st.session_state[CARD_ID] = vehicle_id
    st.switch_page(CARD_PAGE)


def remember_viewed(card: dict) -> None:
    """Put this vehicle first in «Сүүлд үзсэн» (session only, max RECENT_MAX)."""
    item = {"id": card["id"], "identifier": card["identifier"],
            "company": (card.get("company") or {}).get("name", "")}
    recent = [r for r in st.session_state.get(RECENT, []) if r["id"] != item["id"]]
    st.session_state[RECENT] = [item, *recent][:RECENT_MAX]


# --- API helpers ---------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def cached_destinations() -> list[dict]:
    """GET /destinations, cached 5 minutes (the list rarely changes)."""
    return api_client.destinations()


def show_api_error(exc: api_client.ApiError) -> None:
    for message in logic.error_messages(exc.status, exc.detail):
        st.error(message)


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


# --- vehicle card parts ------------------------------------------------------------------

def render_prediction(prediction: dict | None) -> None:
    """Status card: tinted by status, big 'N хоног', date, progress bar; grey if null."""
    v = logic.prediction_view(prediction)
    if v["pending"]:
        body = f'<div class="pc-big" style="font-size:1.1rem">{html.escape(v["big"])}</div>'
    else:
        bar = ""
        if v["progress"] is not None:
            bar = (f'<div class="pc-bar"><div style="width:{v["progress"] * 100:.0f}%;'
                   f'background:{v["fg"]}"></div></div>')
        body = (
            f'<div class="pc-top"><span>{html.escape(v["status_label"])}</span>'
            f'<span>{html.escape(v["date"] or "")}</span></div>'
            f'<div class="pc-big">{html.escape(v["big"])} <span class="pc-sub">{html.escape(v["sub"])}</span></div>'
            f'{bar}<div class="pc-note">{html.escape(v["note"])}</div>'
        )
    st.markdown(f'<div class="pc" style="color:{v["fg"]};background:{v["bg"]}">{body}</div>',
                unsafe_allow_html=True)


def _tile(label: str, value: str) -> str:
    return f'<div class="tile"><div class="k">{html.escape(label)}</div><div class="v">{html.escape(value)}</div></div>'


def render_tiles(card: dict) -> None:
    """3 small tiles: last change, oil · liters, destination."""
    last = card.get("last_service") or {}
    oil = f"{last.get('oil_grade', '')} · {logic.format_number(last.get('liters'), 'л')}" if last else logic.NOT_GIVEN
    tiles = [
        _tile("Сүүлд солисон", last.get("service_date") or logic.NOT_GIVEN),
        _tile("Тос", oil),
        _tile("Чиглэл", logic.service_destination_text(last) if last else logic.NOT_GIVEN),
    ]
    st.markdown(f'<div class="tiles">{"".join(tiles)}</div>', unsafe_allow_html=True)


def render_call_row(service: dict | None) -> None:
    """«Жолооч · утас — Залгах» with a tel: link (opens the phone's dialer)."""
    service = service or {}
    phone = service.get("driver_phone")
    if not phone and not service.get("driver_name"):
        return
    who = " · ".join(x for x in (service.get("driver_name") or "Жолооч", phone) if x)
    link = f'<a href="tel:{html.escape(phone)}">Залгах</a>' if phone else ""
    st.markdown(f'<div class="call-row"><span class="who">{html.escape(who)}</span>{link}</div>',
                unsafe_allow_html=True)


def render_history(history: list[dict]) -> None:
    with st.expander(f"Түүх ({len(history)})"):
        if not history:
            st.write("Түүх алга.")
        st.markdown("".join(f'<div class="hist">{html.escape(logic.service_line(s))}</div>' for s in history),
                    unsafe_allow_html=True)
