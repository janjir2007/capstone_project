"""Streamlit pieces shared by the screens — DESIGN v4 (task T7).

Design: background #F6F7F9 (theme, .streamlit/config.toml), white cards (radius 16,
soft shadow, no borders), buttons 52 px, primary #1F4E9D only for main actions and
selected chips, one column, Mongolian only. CSS is kept minimal and hooks onto Streamlit's `st-key-<key>`
classes: any container whose key starts with "card_" becomes a white card.

Hand-off between screens: a screen stores a plain value in st.session_state
(REC_PENDING, CARD_ID, SEARCH_PENDING) and calls st.switch_page. The target
screen reads it at the top of its run. Widget keys are not written from another
screen, because Streamlit drops the state of widgets not drawn in the last run.
"""

import html
import io
from contextlib import contextmanager

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

# DESIGN v4 (T7: calm, modern, light — "less ink, more space"). Spacing 8/16/24/32 · type:
# title 22/600, section 15/600, body 15/400, labels 13/500 grey #6B7280, big numbers 28/600;
# max weight 600 · no borders: white cards radius 16 + soft shadow, inputs grey fill (primary
# border only on focus) · primary #1F4E9D only for main buttons + selected chips · buttons 52 px.
CSS = """
<style>
/* T8 spacing (exact values): no Streamlit top bar; page 16/20/32 px; max 480 px centered */
[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"] {display: none !important;}
.block-container {padding: 16px 20px 32px !important; max-width: 480px;}
/* CSS-only markdown blocks are 0 px tall but still take a gap -> remove them from the layout */
[data-testid="stElementContainer"]:has(style) {display: none;}
[data-testid="stVerticalBlock"] {gap: 12px;}                  /* element -> element */
[class*="st-key-card_"], [class*="st-key-act_"] {margin-top: 8px;}  /* 12 + 8 = 20 px before a card */
[class*="st-key-card_"] {gap: 14px;}                          /* field -> field inside a card */
.st-key-topbar {height: 44px; min-height: 44px;}             /* «‹ Буцах» + «Гео-Эксперт» */
[data-testid="stElementContainer"]:has(> .stHeading h1) {margin: -4px 0 4px;}  /* 8 px above, 16 px below */
[data-testid="stElementContainer"]:has(> .stHeading h2, > .stHeading h3) {margin-top: 8px;}  /* section: 20 px */
.stHeading h1, .stHeading h2, .stHeading h3 {margin: 0 !important; padding: 0 !important;}
/* right under the title the 16 px title gap wins (no extra card/section margin) */
[data-testid="stElementContainer"]:has(> .stHeading h1) + [data-testid="stLayoutWrapper"] > [class*="st-key-card_"],
[data-testid="stElementContainer"]:has(> .stHeading h1) + [data-testid="stElementContainer"] {margin-top: 0;}
/* whatever follows a card (button, link, text) also starts 20 px below it */
[data-testid="stLayoutWrapper"]:has(> [class*="st-key-card_"], > [class*="st-key-act_"])
  + :not([data-testid="stLayoutWrapper"]:has(> [class*="st-key-card_"], > [class*="st-key-act_"])) {margin-top: 8px;}
.st-key-btn_save, .st-key-btn_save_force {margin-top: 8px;}                        /* «Хадгалах»: 20 px above */
b, strong, th {font-weight: 600 !important;}
h1 {font-size: 22px !important; font-weight: 600 !important; letter-spacing: -.01em; line-height: 30px !important;}
h2, h3 {font-size: 15px !important; font-weight: 600 !important; line-height: 22px !important;}
[data-testid="stWidgetLabel"] {margin-bottom: 6px !important; min-height: 0 !important;}  /* label -> input */
[data-testid="stWidgetLabel"] p {font-size: 13px !important; font-weight: 500 !important; color: #6B7280;}
.stButton button, .stFormSubmitButton button {min-height: 52px; border-radius: 14px; padding: 8px 16px;}
.stButton button p, .stFormSubmitButton button p {font-size: 16px; font-weight: 600;}
.stButton button[kind="secondary"], .stFormSubmitButton button[kind="secondaryFormSubmit"] {
  background: #fff; border: none; box-shadow: 0 1px 3px rgba(0,0,0,.06);}
[class*="st-key-card_"] .stButton button[kind="secondary"] {background: #F3F4F6; box-shadow: none;}
.stButton button[kind="tertiary"] {min-height: 44px; padding: 0 4px; color: #1F4E9D;}
.stButton button[kind="tertiary"] p {font-size: 14px; font-weight: 600;}
.stButton button[kind="tertiary"]:hover {color: #173B78;}
[class*="st-key-card_"] {background: #fff; border-radius: 16px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,.06);}
/* inputs: grey fill, no border; 1px primary border only on focus */
[data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"] {border: 1px solid transparent !important;}
[data-baseweb="input"]:focus-within, [data-baseweb="select"] > div:focus-within, [data-baseweb="textarea"]:focus-within {
  border-color: #1F4E9D !important;}
/* chips (pills): 14 px, 36 px tall, wrap; selected = primary */
[data-testid="stButtonGroup"] button {min-height: 36px; padding: 4px 14px; border: none; background: #F3F4F6;}
[data-testid="stButtonGroup"] button p {font-size: 14px; font-weight: 500;}
[data-testid="stButtonGroup"] button[aria-checked="true"] {background: #1F4E9D !important; color: #fff !important;}
[data-testid="stExpander"] details {border: none; background: transparent;}
[data-testid="stExpander"] summary {padding-left: 0;}
[data-testid="stExpander"] summary p {font-size: 15px; font-weight: 600;}
[data-testid="stFileUploaderDropzone"] {border: none; background: #F3F4F6;}
[data-testid="stCameraInputButton"] {border: none !important; background: #F3F4F6;}
.geo-pill {display: inline-block; font-size: 12px; font-weight: 600; letter-spacing: .02em; color: #1F4E9D;}
.greet {font-size: 13px; font-weight: 500; color: #6B7280; margin: -4px 0 8px;}
.plate-row {display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 0 0 4px;}
.plate {display: inline-block; font-size: 19px; font-weight: 600; letter-spacing: .05em; font-variant-numeric: tabular-nums;
  background: #F3F4F6; border: 1px solid #E5E7EB; border-radius: 10px; padding: 4px 12px; line-height: 1.3; overflow-wrap: anywhere;}
.chip {display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 999px; font-size: 13px; font-weight: 500;
  background: #F3F4F6; color: #4B5563;}
.chip.known {background: #E8F5EE; color: #1E7A4C;} .chip.new {background: #EAF0FA; color: #1F4E9D;}
.dot {display: inline-block; width: 8px; height: 8px; border-radius: 50%; flex: none;}
.muted {color: #6B7280; font-size: 13px;}
.sec {font-size: 15px; font-weight: 600; margin: 0 0 4px;}
.line {color: #4B5563; font-size: 15px; margin: 4px 0 0;}
[class*="st-key-photo_preview"] img {border-radius: 12px; object-fit: cover;}
.pairs {display: grid; grid-template-columns: 1fr 1fr; gap: 16px 16px; margin: 16px 0 8px;}
.pairs .k, .seg .k {font-size: 13px; font-weight: 500; color: #6B7280;}
.pairs .v {font-size: 15px; font-weight: 500; overflow-wrap: anywhere; margin-top: 2px;}
.pc {border-radius: 12px; padding: 16px; margin: 16px 0 0;}
.pc-top {display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 600;}
.pc-big {font-size: 28px; font-weight: 600; line-height: 1.15; margin: 8px 0 2px; color: #111827;}
.pc-sub {font-size: 15px; font-weight: 500; color: #4B5563;}
.pc-date {font-size: 13px; font-weight: 500; color: #4B5563;}
.pc-bar {height: 4px; border-radius: 2px; background: rgba(17,24,39,.08); margin: 12px 0 8px;}
.pc-bar > div {height: 100%; border-radius: 2px;}
.pc-note {font-size: 12px; font-weight: 500; color: #4B5563;}
.pc-pending {font-size: 15px; font-weight: 500; color: #4B5563;}
.hist {font-size: 14px; padding: 8px 0; color: #374151;}
.hist + .hist {border-top: 1px solid #F0F1F3;}
.done {width: 64px; height: 64px; margin: 8px auto; border-radius: 50%; background: #E8F5EE; color: #1E7A4C;
  display: flex; align-items: center; justify-content: center; font-size: 32px; font-weight: 600;}
.done-title {text-align: center; font-size: 22px; font-weight: 600; margin: 0 0 16px;}
.center {display: flex; justify-content: center;}
/* home action cards: HTML card + the real button/link stretched over it (one tap target) */
[class*="st-key-act_"] {position: relative; background: #fff; border-radius: 16px; padding: 16px;
  box-shadow: 0 1px 3px rgba(0,0,0,.06); gap: 0 !important;}
.st-key-act_record {background: #1F4E9D;}
[class*="st-key-act_"] [data-testid="stElementContainer"]:has(.stButton, .stPageLink) {
  position: absolute; inset: 0; margin: 0; z-index: 2; height: 100%;}
[class*="st-key-act_"] .stButton, [class*="st-key-act_"] .stPageLink {height: 100%;}
[class*="st-key-act_"] .stButton button, [class*="st-key-act_"] .stPageLink a {width: 100%; height: 100%; min-height: 0;
  background: transparent !important; border: none !important; box-shadow: none !important; border-radius: 16px;}
[class*="st-key-act_"] .stButton button *, [class*="st-key-act_"] .stPageLink a * {opacity: 0;}
.act {display: flex; align-items: center; gap: 16px; min-height: 48px;}
.act-ic {width: 44px; height: 44px; border-radius: 12px; display: flex; align-items: center; justify-content: center;
  background: #EAF0FA; color: #1F4E9D; flex: none;}
.act-ic svg {width: 24px; height: 24px; fill: currentColor;}
.act-t {font-size: 16px; font-weight: 600; color: #111827;}
.act-s {font-size: 13px; font-weight: 400; color: #6B7280; margin-top: 2px;}
.act-go {margin-left: auto; color: #9CA3AF;} .act-go svg {width: 20px; height: 20px; fill: currentColor;}
.st-key-act_record .act-ic {background: rgba(255,255,255,.16); color: #fff;}
.st-key-act_record .act-t {color: #fff;} .st-key-act_record .act-s {color: #DCE5F5;}
.st-key-act_record .act-go {color: #DCE5F5;}
/* ui-ux-pro-max checklist: visible focus ring (keyboard / switch users), reduced motion */
button:focus-visible, input:focus-visible, a:focus-visible, [role="radio"]:focus-visible {outline: 3px solid #1F4E9D !important; outline-offset: 2px;}
@media (prefers-reduced-motion: reduce) {* {transition: none !important; animation: none !important;}}
</style>
"""

# Material Symbols paths (Apache 2.0), inline so no icon font/class is needed in HTML blocks.
ICONS = {
    "camera": "M12 15.2a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4zM9 2 7.17 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 "
              "2-.9 2-2V6c0-1.1-.9-2-2-2h-3.17L15 2H9zm3 15c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5z",
    "search": "M15.5 14h-.79l-.28-.27A6.47 6.47 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 "
              "4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z",
    "bell": "M12 22c1.1 0 2-.9 2-2h-4c0 1.1.89 2 2 2zm6-6v-5c0-3.07-1.64-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 "
            "1.5v.68C7.63 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z",
    "chevron": "M10 6 8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z",
}


def icon(name: str) -> str:
    return f'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="{ICONS[name]}"/></svg>'


def inject_css() -> None:
    """DESIGN v4 tweaks on top of the theme (.streamlit/config.toml)."""
    st.markdown(CSS, unsafe_allow_html=True)


# --- layout ------------------------------------------------------------------------

def header(title: str, back: str | None = None) -> None:
    """Screen header: back link (inner screens) + small "Гео-Эксперт" + title (22/600)."""
    with st.container(key="topbar", horizontal=True, vertical_alignment="center", horizontal_alignment="distribute"):
        if back:
            if st.button("‹ Буцах", key="back", type="tertiary"):
                st.switch_page(back)
        st.markdown('<span class="geo-pill">Гео-Эксперт</span>', unsafe_allow_html=True)
    st.title(title)


def known_chip_html(card: dict | None) -> str:
    """«Бүртгэлтэй · N удаа ирсэн» or «Шинэ машин» (small tinted chip)."""
    if card:
        text, cls = f"Бүртгэлтэй · {card.get('service_count', 0)} удаа ирсэн", "known"
    else:
        text, cls = "Шинэ машин", "new"
    return f'<span class="chip {cls}">{html.escape(text)}</span>'


def segment_chip_html(segment: str | None, service_count: int | None = None) -> str:
    """Small grey chip next to the plate: colored dot + «Давтан · 5 удаа» (word, never color alone)."""
    parts = [logic.segment_label(segment)] if segment else []
    if service_count:
        parts.append(f"{service_count} удаа")
    if not parts:
        return ""
    dot = f'<i class="dot" style="background:{logic.SEGMENT_DOTS[segment]}"></i>' if segment in logic.SEGMENT_DOTS else ""
    return f'<span class="chip">{dot}{html.escape(" · ".join(parts))}</span>'


def plate_box(identifier: str, *chips: str) -> None:
    """Plate chip (light grey, 1px border, 19/600, spaced letters) + optional small chips beside it."""
    plate = f'<span class="plate">{html.escape(identifier or "")}</span>'
    st.markdown(f'<div class="plate-row">{plate}{"".join(chips)}</div>', unsafe_allow_html=True)


@contextmanager
def action_card(key: str, icon_name: str, title: str, subtitle: str):
    """Home row card: icon + title + 1-line subtitle + chevron. The caller puts the real
    st.button / st.page_link inside; CSS stretches it over the whole card (one tap target,
    keeps its accessible label)."""
    with st.container(key=key):
        st.markdown(
            f'<div class="act"><span class="act-ic">{icon(icon_name)}</span>'
            f'<div><div class="act-t">{html.escape(title)}</div><div class="act-s">{html.escape(subtitle)}</div></div>'
            f'<span class="act-go">{icon("chevron")}</span></div>',
            unsafe_allow_html=True,
        )
        yield


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
        st.image(data, width=120)  # thumbnail


# --- vehicle card parts ------------------------------------------------------------------

def render_prediction(prediction: dict | None) -> None:
    """Compact status block on a soft tint: dot + status word (never color alone), days left
    28/600, next change date, thin 4 px bar, method note 12 px grey; grey when null."""
    v = logic.prediction_view(prediction)
    if v["pending"]:
        body = f'<div class="pc-pending">{html.escape(v["big"])}</div>'
    else:
        bar = ""
        if v["progress"] is not None:
            bar = (f'<div class="pc-bar"><div style="width:{v["progress"] * 100:.0f}%;'
                   f'background:{v["fg"]}"></div></div>')
        body = (
            f'<div class="pc-top" style="color:{v["fg"]}"><i class="dot" style="background:{v["fg"]}"></i>'
            f'{html.escape(v["status_label"])}</div>'
            f'<div class="pc-big">{html.escape(v["big"])} <span class="pc-sub">{html.escape(v["sub"])}</span></div>'
            f'<div class="pc-date">Дараагийн солилт: {html.escape(v["date"] or "")}</div>'
            f'{bar}<div class="pc-note">{html.escape(v["note"])}</div>'
        )
    st.markdown(f'<div class="pc" style="background:{v["bg"]}">{body}</div>', unsafe_allow_html=True)


def _pair(label: str, value: str) -> str:
    return f'<div><div class="k">{html.escape(label)}</div><div class="v">{html.escape(value)}</div></div>'


def render_tiles(card: dict) -> None:
    """4 info pairs (label + value, 2 columns, no boxes): last change, «15W-40 · ердийн 30 л», destination, driver."""
    last = card.get("last_service") or {}
    oil = logic.oil_pair_text(last, card.get("usual_liters"))
    driver = " · ".join(x for x in (last.get("driver_name"), last.get("driver_phone")) if x) or logic.NOT_GIVEN
    pairs = [
        _pair("Сүүлд солисон", last.get("service_date") or logic.NOT_GIVEN),
        _pair("Тос", oil),
        _pair("Чиглэл", logic.service_destination_text(last) if last else logic.NOT_GIVEN),
        _pair("Жолооч", driver),
    ]
    st.markdown(f'<div class="pairs">{"".join(pairs)}</div>', unsafe_allow_html=True)


def render_history(history: list[dict]) -> None:
    with st.expander(f"Түүх ({len(history)})"):
        if not history:
            st.write("Түүх алга.")
        st.markdown("".join(f'<div class="hist">{html.escape(logic.service_line(s))}</div>' for s in history),
                    unsafe_allow_html=True)
