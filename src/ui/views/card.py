"""Vehicle card (task 5.3, DESIGN v5 / T9 mockup), fresh from GET /vehicles/{id}.

Order: big plate + grey segment chip («Байнгын · 3 удаа»), one line company · model, blue target
block («Дараагийн тос солилт · 165 000 км», task 9.5a — replaces the predicted-date block; none for
mine trucks), fact rows (last change, oil, driver), «Км бүртгэл», «Түүх» timeline, primary
«Үйлчилгээ бүртгэх». No route / «Чиглэл» anywhere on the card (D-111, 9.14a-3b).

Task 9.14a-3 (contract v0.18/v0.19; every number comes from the API, src/api/pace.py), simplified in
9.14a-3b after Ari's review:
- target block: the target km big, the due day small next to it («574 255 км  ~2026-11-17»).
- «Км бүртгэл · 350 км/өдөр» (mine trucks «цаг/өдөр», «· Мэдээлэл алга» without a pace): the 5 newest
  readings; a flagged one says why in Mongolian; a typed-in one has «Буцаах» (DELETE /readings/{id}).
- the km form (the driver's reply) has no button on the card: «Км шалгах» -> «Хариу бүртгэх» on
  «Сануулга» opens the card with it open. km + date (default today) -> «Үргэлжлүүлэх» -> confirm step with
  the new km/day, due day and reminder day from POST .../readings/preview (nothing stored yet) ->
  «Хадгалах» = POST /vehicles/{id}/readings.
"""

import html
from datetime import datetime

import streamlit as st

from src.ui import api_client, common, logic

KM_VALUE, KM_DATE = "km_value", "km_date"  # form widgets
KM_DRAFT = "km_draft"                      # (value, day) kept while the confirm step hides the form
KM_MSG = "km_msg"                          # (kind, text) shown once above «Км бүртгэл»


def km_form_open(vehicle_id: int) -> bool:
    return st.session_state.get(common.KM_FORM) == vehicle_id


def on_km_close() -> None:
    for key in (common.KM_FORM, common.KM_PREVIEW, KM_VALUE, KM_DATE, KM_DRAFT):
        st.session_state.pop(key, None)


def _api_error(exc: api_client.ApiError) -> None:
    st.session_state[KM_MSG] = ("error", " ".join(logic.error_messages(exc.status, exc.detail)))


def on_km_preview(vehicle_id: int) -> None:
    """«Үргэлжлүүлэх»: ask the API what this reading would give (stores nothing)."""
    value, day = st.session_state.get(KM_VALUE), st.session_state.get(KM_DATE)
    if not value or value <= 0:
        st.session_state[KM_MSG] = ("error", "Одоогийн км-ийг оруулна уу.")
        return
    try:
        preview = api_client.preview_reading(vehicle_id, value, day.isoformat() if day else None)
    except api_client.ApiError as exc:
        _api_error(exc)
        return
    st.session_state[common.KM_PREVIEW] = {"vehicle_id": vehicle_id, **preview}
    st.session_state[KM_DRAFT] = (value, day)  # Streamlit drops a widget's value while it is not drawn


def on_km_edit() -> None:
    """«Засах»: back to the form with the typed values (put back before the widgets are drawn)."""
    st.session_state.pop(common.KM_PREVIEW, None)
    draft = st.session_state.get(KM_DRAFT)
    if draft:
        st.session_state[KM_VALUE], st.session_state[KM_DATE] = draft


def on_km_save(vehicle_id: int) -> None:
    """«Хадгалах»: store the reading the confirm step showed."""
    preview = st.session_state.get(common.KM_PREVIEW) or {}
    try:
        saved = api_client.add_reading(vehicle_id, preview["value"], preview["reading_date"])
    except api_client.ApiError as exc:
        _api_error(exc)
        return
    reading = saved.get("reading") or {}
    if reading.get("status") == "flagged":
        st.session_state[KM_MSG] = ("warning", "Хадгаллаа: " + logic.flag_text(reading.get("flag_reason"),
                                                                              reading.get("unit", "km")))
    else:
        pace = saved.get("pace") or {}
        st.session_state[KM_MSG] = ("success", f"Хадгаллаа · {logic.pace_label(pace)}: "
                                               f"{logic.rate_text(pace.get('rate_per_day'), pace.get('unit', 'km'))}")
    on_km_close()


def on_km_undo(reading_id: int) -> None:
    """«Буцаах» on a typed-in reading."""
    try:
        api_client.delete_reading(reading_id)
    except api_client.ApiError as exc:
        _api_error(exc)
    else:
        st.session_state[KM_MSG] = ("success", "Бүртгэлийг буцаалаа.")


def readings_section(card: dict) -> None:
    """«Км бүртгэл · 350 км/өдөр»: newest readings, then the km form when «Хариу бүртгэх» opened it."""
    st.subheader(f"Км бүртгэл · {logic.pace_title_text(card.get('pace'))}")
    msg = st.session_state.pop(KM_MSG, None)
    if msg:
        getattr(st, msg[0])(msg[1])
    with st.container(key="card_km"):
        readings = card.get("readings") or []
        if not readings:
            common.html_block('<span class="muted">Бүртгэл алга.</span>')
        for r in readings:
            why = logic.flag_text(r.get("flag_reason"), r.get("unit", "km"))
            with st.container(horizontal=True, vertical_alignment="center", key=f"km_row_{r['id']}"):
                common.html_block(
                    f'<div class="km-r"><div class="t">{html.escape(logic.reading_text(r))}</div>'
                    + (f'<div class="why">{html.escape(why)}</div>' if why else "") + "</div>")
                if r.get("source") == "manual":
                    st.button("Буцаах", key=f"km_undo_{r['id']}", on_click=on_km_undo, args=(r["id"],),
                              type="tertiary")
    vid = card["id"]
    preview = st.session_state.get(common.KM_PREVIEW)
    if preview and preview.get("vehicle_id") == vid:
        km_confirm(vid, preview)
    elif km_form_open(vid):
        km_form(vid, (card.get("pace") or {}).get("unit", "km"))


def km_form(vehicle_id: int, unit: str) -> None:
    """The driver's reply: km (mine trucks: engine hours) + the day he gave it."""
    today = datetime.now(logic.UB).date()
    # a default only when the value is not already in session_state («Засах»), or Streamlit warns
    value = {} if KM_VALUE in st.session_state else {"value": None}
    day = {} if KM_DATE in st.session_state else {"value": today}
    with st.container(key="card_km_form"):
        if unit == "km":
            st.number_input("Одоогийн км", key=KM_VALUE, min_value=0, step=1, format="%d",
                            placeholder="Жишээ нь 116000", **value)
        else:
            st.number_input("Одоогийн мото цаг", key=KM_VALUE, min_value=0.0, step=0.1, format="%.1f", **value)
        st.date_input("Огноо", key=KM_DATE, max_value=today, format="YYYY-MM-DD", **day)
        with st.container(horizontal=True, key="km_form_btns"):
            st.button("Болих", key="km_cancel", on_click=on_km_close, width="stretch")
            st.button("Үргэлжлүүлэх", key="km_next", type="primary", on_click=on_km_preview, args=(vehicle_id,),
                      width="stretch")


def km_confirm(vehicle_id: int, preview: dict) -> None:
    """Confirm step: what saving gives (from the API), then «Хадгалах» or «Засах»."""
    with st.container(key="card_km_confirm"):
        unit = "км" if preview.get("unit", "km") == "km" else "мц"
        common.html_block(f'<div class="act-t">{html.escape(preview.get("reading_date", ""))} · '
                          f'{html.escape(logic.format_number(preview.get("value"), unit))}</div>')
        common.html_block(common.kv_rows(logic.preview_rows(preview), "sm"))
        if preview.get("status") == "flagged":
            st.warning(logic.flag_text(preview.get("flag_reason"), preview.get("unit", "km"))
                       + ". Хадгалж болно, гэхдээ сануулгын огноог өөрчлөхгүй.")
        with st.container(horizontal=True, key="km_confirm_btns"):
            st.button("Засах", key="km_edit", on_click=on_km_edit, width="stretch")
            st.button("Хадгалах", key="km_save", type="primary", on_click=on_km_save, args=(vehicle_id,),
                      width="stretch", icon=":material/check:")


common.header("Машины карт", back=common.SEARCH_PAGE)

vehicle_id = st.session_state.get(common.CARD_ID)
card = None
if vehicle_id is None:
    st.info("Машин сонгоогүй байна.")
else:
    try:
        card = api_client.get_vehicle(vehicle_id)
    except api_client.ApiError as exc:
        common.show_api_error(exc)

if card:
    common.remember_viewed(card)
    common.plate_box(card["identifier"], common.segment_chip_html(card.get("segment"), card.get("service_count")),
                     large=True)
    facts = [(card.get("company") or {}).get("name"), card.get("vehicle_model")]
    common.html_block(f'<div class="line">{html.escape(" · ".join(f for f in facts if f))}</div>')
    common.render_target(card)
    common.render_tiles(card)
    if card.get("last_service"):  # a reading counts from the latest service (9.14a)
        readings_section(card)
    common.render_history(card.get("history") or [])
    if st.button("Үйлчилгээ бүртгэх", type="primary", width="stretch", key="btn_record_service",
                 icon=":material/add:"):
        common.go_record(card["identifier_type"], card["identifier"], card)
else:
    if st.button("Хайх руу буцах", width="stretch"):
        st.switch_page(common.SEARCH_PAGE)

common.logout_button()
