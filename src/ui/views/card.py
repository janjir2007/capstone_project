"""Vehicle card (task 5.3, DESIGN v5 / T9 mockup), fresh from GET /vehicles/{id}.

Order: big plate + grey segment chip («Байнгын · 3 удаа»), one line company · model, tinted
status block (dot + word, «5 хоног хоцорсон», «Солих ёстой байсан: …», method note), fact rows
(last change, oil, destination, driver), «Түүх» timeline, primary «Үйлчилгээ бүртгэх».
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
    common.plate_box(card["identifier"], common.segment_chip_html(card.get("segment"), card.get("service_count")),
                     large=True)
    facts = [(card.get("company") or {}).get("name"), card.get("vehicle_model")]
    common.html_block(f'<div class="line">{html.escape(" · ".join(f for f in facts if f))}</div>')
    common.render_prediction(card.get("prediction"))
    common.render_tiles(card)
    common.render_history(card.get("history") or [])
    if st.button("Үйлчилгээ бүртгэх", type="primary", width="stretch", key="btn_record_service",
                 icon=":material/add:"):
        common.go_record(card["identifier_type"], card["identifier"], card)
else:
    if st.button("Хайх руу буцах", width="stretch"):
        st.switch_page(common.SEARCH_PAGE)

common.logout_button()
