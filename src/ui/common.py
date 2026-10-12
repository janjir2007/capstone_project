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
import io

import streamlit as st
from PIL import Image, UnidentifiedImageError  # pillow: installed with streamlit

from src.ui import api_client, auth, logic

# Folder is "views", NOT "pages": Streamlit auto-runs a folder named pages/
# in legacy mode, which skips app.py (sys.path setup and the login gate) when
# a page URL is opened directly.
HOME_PAGE = "views/home.py"
RECORD_PAGE = "views/record.py"
SEARCH_PAGE = "views/search.py"
CARD_PAGE = "views/card.py"
REMINDERS_PAGE = "views/reminders.py"

REC_PENDING = "rec_pending"        # {"identifier_type", "identifier", "card" | None}
REC_RESET = "rec_reset"            # True -> record screen starts at the camera step
CARD_ID = "card_id"                # vehicle shown on the card screen
SEARCH_PENDING = "search_pending"  # query to search on arrival
RECENT = "recent_vehicles"         # "Сүүлд үзсэн": [{id, identifier, company}], this session only
RECENT_MAX = 5

# DESIGN v3 (T6). Spacing scale 4/8/12/16/24/32 px · type: title 28/800, section 18/700,
# body 16/500, small 14/500 (nothing smaller outdoors) · tap targets >= 56 px · colors
# checked for WCAG contrast (text/buttons AAA, status chips AAA). Font = Montserrat (theme).
CSS = """
<style>
.block-container {padding-top: 64px; padding-bottom: 48px; padding-left: 16px; padding-right: 16px; max-width: 560px;}
h1 {font-size: 28px !important; font-weight: 800 !important; letter-spacing: -.01em; padding: 4px 0 12px !important;}
h3 {font-size: 18px !important; font-weight: 700 !important;}
p, li, label, .stMarkdown {font-weight: 500;}
.stButton button, .stFormSubmitButton button {min-height: 56px; border-radius: 16px; padding: 8px 16px;}
.stButton button p, .stFormSubmitButton button p {font-size: 17px; font-weight: 700;}
.stButton button[kind="secondary"], .stFormSubmitButton button[kind="secondaryFormSubmit"] {
  background: #fff; border: 1.5px solid #DADDE2;}
[class*="st-key-card_"] {background: #fff; border-radius: 20px; padding: 16px;
  box-shadow: 0 1px 2px rgba(20,23,28,.06), 0 4px 16px rgba(20,23,28,.06);}
/* keyed buttons must beat the generic secondary-button rule above (same specificity, later + !important) */
[class*="st-key-btn_dark"] .stButton button {background: #14171C !important; color: #fff !important; border-color: #14171C !important;}
[class*="st-key-btn_dark"] .stButton button:hover {background: #2B3039 !important;}
[class*="st-key-link_"] button {min-height: 44px;}
.st-key-back button {min-height: 44px; padding: 0 4px;}
.st-key-home_record button {min-height: 152px; border-radius: 20px;}
.st-key-home_search .stButton button {min-height: 104px; border-radius: 20px; background: #fff; border: none !important;
  box-shadow: 0 1px 2px rgba(20,23,28,.06), 0 4px 16px rgba(20,23,28,.06);}
.st-key-home_record button p {font-size: 26px !important; font-weight: 800 !important;}
.st-key-home_search button p {font-size: 22px !important; font-weight: 800 !important;}
[data-testid="stPills"] button, [data-testid="stButtonGroup"] button {min-height: 48px; padding: 8px 16px; font-size: 16px; font-weight: 600;}
.geo-pill {display: inline-block; font-size: 13px; font-weight: 700; padding: 4px 12px; border-radius: 999px;
  background: #E6ECF7; color: #1F4E9D;}
.plate-box {font-size: 34px; font-weight: 800; font-variant-numeric: tabular-nums; letter-spacing: .04em;
  text-align: center; border: 3px solid #14171C; border-radius: 12px; padding: 8px 12px; background: #fff;
  margin: 4px 0 12px; overflow-wrap: anywhere; line-height: 1.2;}
.plate-box.small {font-size: 24px; border-width: 2px; padding: 4px 8px; margin-bottom: 8px;}
.chip {display: inline-block; padding: 4px 12px; border-radius: 999px; font-size: 14px; font-weight: 700;}
.chip.known {background: #E3F1E7; color: #14532D;} .chip.new {background: #E6ECF7; color: #1F4E9D;}
.muted {color: #4A5160; font-size: 14px;}
.photo-preview img {border-radius: 12px;}
.tiles {display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 12px 0 8px;}
.tile {background: #F4F5F7; border-radius: 12px; padding: 8px 12px;}
.tile .k {font-size: 13px; font-weight: 600; color: #4A5160;}
.tile .v {font-size: 16px; font-weight: 700; overflow-wrap: anywhere;}
.pc {border-radius: 16px; padding: 16px; margin: 0 0 4px;}
.pc-label {font-size: 15px; font-weight: 800; text-transform: none;}
.pc-big {font-size: 34px; font-weight: 800; line-height: 1.1; margin: 4px 0;}
.pc-sub {font-size: 18px; font-weight: 700;}
.pc-date {font-size: 17px; font-weight: 700;}
.pc-bar {height: 8px; border-radius: 4px; background: rgba(20,23,28,.10); margin: 12px 0 8px;}
.pc-bar > div {height: 100%; border-radius: 4px;}
.pc-note {font-size: 13px; font-weight: 600;}
.hist {font-size: 14px; padding: 8px 0; border-bottom: 1px solid #DADDE2;}
.done {width: 72px; height: 72px; margin: 4px auto 8px; border-radius: 50%; background: #E3F1E7; color: #14532D;
  display: flex; align-items: center; justify-content: center; font-size: 40px; font-weight: 800;}
.done-title {text-align: center; font-size: 24px; font-weight: 800; margin: 0 0 12px;}
.seg-k {font-size: 14px;}
/* ui-ux-pro-max checklist: visible focus ring (keyboard / switch users), reduced motion */
button:focus-visible, input:focus-visible, [role="radio"]:focus-visible {outline: 3px solid #1F4E9D !important; outline-offset: 2px;}
@media (prefers-reduced-motion: reduce) {* {transition: none !important; animation: none !important;}}
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
        result = api_client.recognize_plate(photo.getvalue(), photo.name or "photo.jpg",
                                            logic.photo_content_type(photo.name, photo.type))
    except api_client.ApiError as exc:
        return "", True, logic.recognize_error_message(exc.status)
    return logic.recognize_outcome(result)


def photo_preview(data: bytes | None, name: str | None = None) -> None:
    """Small preview of the photo just taken/uploaded. Never crashes the flow: a photo the
    browser-side decoder cannot read (e.g. iPhone HEIC — the API converts it, the UI has no
    HEIC decoder) shows a text line instead."""
    if not data:
        return
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
    except (UnidentifiedImageError, OSError, ValueError):
        st.markdown(f'<span class="muted">Зураг: {html.escape(name or "")} (урьдчилж харах боломжгүй)</span>',
                    unsafe_allow_html=True)
        return
    with st.container(key="photo_preview"):
        st.image(data, width=200)


# --- vehicle card parts ------------------------------------------------------------------

def render_prediction(prediction: dict | None) -> None:
    """Status block = the biggest colored block on the card: status word (text, never color
    alone), big «N хоног үлдсэн/хэтэрсэн», next change date, progress bar; grey when null."""
    v = logic.prediction_view(prediction)
    if v["pending"]:
        body = f'<div class="pc-label">{html.escape(v["big"])}</div>'
    else:
        bar = ""
        if v["progress"] is not None:
            bar = (f'<div class="pc-bar"><div style="width:{v["progress"] * 100:.0f}%;'
                   f'background:{v["fg"]}"></div></div>')
        body = (
            f'<div class="pc-label">{html.escape(v["status_label"])}</div>'
            f'<div class="pc-big">{html.escape(v["big"])} <span class="pc-sub">{html.escape(v["sub"])}</span></div>'
            f'<div class="pc-date">Дараагийн солилт: {html.escape(v["date"] or "")}</div>'
            f'{bar}<div class="pc-note">{html.escape(v["note"])}</div>'
        )
    st.markdown(f'<div class="pc" style="color:{v["fg"]};background:{v["bg"]}">{body}</div>',
                unsafe_allow_html=True)


def _tile(label: str, value: str) -> str:
    return f'<div class="tile"><div class="k">{html.escape(label)}</div><div class="v">{html.escape(value)}</div></div>'


def render_tiles(card: dict) -> None:
    """4 tiles (2×2, readable at 390 px): last change, oil · liters, destination, driver."""
    last = card.get("last_service") or {}
    oil = f"{last.get('oil_grade', '')} · {logic.format_number(last.get('liters'), 'л')}" if last else logic.NOT_GIVEN
    driver = " · ".join(x for x in (last.get("driver_name"), last.get("driver_phone")) if x) or logic.NOT_GIVEN
    tiles = [
        _tile("Сүүлд солисон", last.get("service_date") or logic.NOT_GIVEN),
        _tile("Тос", oil),
        _tile("Чиглэл", logic.service_destination_text(last) if last else logic.NOT_GIVEN),
        _tile("Жолооч", driver),
    ]
    st.markdown(f'<div class="tiles">{"".join(tiles)}</div>', unsafe_allow_html=True)


def render_history(history: list[dict]) -> None:
    with st.expander(f"Түүх ({len(history)})"):
        if not history:
            st.write("Түүх алга.")
        st.markdown("".join(f'<div class="hist">{html.escape(logic.service_line(s))}</div>' for s in history),
                    unsafe_allow_html=True)
