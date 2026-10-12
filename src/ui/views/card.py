"""Vehicle card (task 5.3, DESIGN v4 / T7), fresh from GET /vehicles/{id}.

Order: plate chip + small grey segment chip («Давтан · 5 удаа»), one line company · model,
compact status block (dot + word, days left, date, thin bar, method note), 4 info pairs,
history collapsed, primary «Тос солилт бүртгэх».
"""

import html

import streamlit as st

from src.ui import api_client, common

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
        common.plate_box(card["identifier"], common.segment_chip_html(card.get("segment"), card.get("service_count")))
        facts = [(card.get("company") or {}).get("name"), card.get("vehicle_model")]
        st.markdown(f'<div class="line">{html.escape(" · ".join(f for f in facts if f))}</div>', unsafe_allow_html=True)
        common.render_prediction(card.get("prediction"))
        common.render_tiles(card)
        common.render_history(card.get("history") or [])
    if st.button("Тос солилт бүртгэх", type="primary", width="stretch", key="btn_record_service"):
        common.go_record(card["identifier_type"], card["identifier"], card)
else:
    if st.button("Хайх руу буцах", width="stretch"):
        st.switch_page(common.SEARCH_PAGE)

common.logout_button()
