"""Vehicle card (task 5.3, DESIGN v3 / T6), fresh from GET /vehicles/{id}.

Order = importance at a glance: large plate + segment badge, then the status block
(biggest colored block: status word, «N хоног», next change date), 4 tiles, history
collapsed, primary «Тос солилт бүртгэх».
"""

import streamlit as st

from src.ui import api_client, common, logic

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
    with st.container(key="card_vehicle"):
        common.plate_box(card["identifier"])
        common.render_prediction(card.get("prediction"))
        common.segment_badge(card.get("segment"))
        facts = [
            (card.get("company") or {}).get("name"),
            card.get("vehicle_model"),
            f"{card.get('service_count', 0)} удаа",
            f"ердийн {logic.format_number(card['usual_liters'], 'л')}" if card.get("usual_liters") else None,
        ]
        st.markdown(f'<span class="muted">{" · ".join(f for f in facts if f)}</span>', unsafe_allow_html=True)
        common.render_tiles(card)
        common.render_history(card.get("history") or [])
    if st.button("Тос солилт бүртгэх", type="primary", width="stretch", key="btn_record_service"):
        common.go_record(card["identifier_type"], card["identifier"], card)
else:
    if st.button("Хайх руу буцах", width="stretch"):
        st.switch_page(common.SEARCH_PAGE)

common.logout_button()
