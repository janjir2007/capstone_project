"""Home screen (DESIGN v3): big «Бүртгэх» card (opens the camera), white «Хайх» card, «Сануулга» link (manager dashboard)."""

import streamlit as st

from src.ui import common

common.header("Тос солилт")

if st.button("Бүртгэх", key="home_record", type="primary", width="stretch", icon=":material/photo_camera:"):
    common.go_record_start()
if st.button("Хайх", key="home_search", width="stretch", icon=":material/search:"):
    st.switch_page(common.SEARCH_PAGE)
st.page_link(common.REMINDERS_PAGE, label="Сануулга", icon=":material/notifications:")

common.logout_button()
