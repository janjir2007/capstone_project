"""Home screen (DESIGN v2): big «Бүртгэх» card (opens the camera), white «Хайх» card."""

import streamlit as st

from src.ui import common

common.header("Тос солилт")

if st.button("📷  Бүртгэх", key="home_record", type="primary", width="stretch"):
    common.go_record_start()
if st.button("🔍  Хайх", key="home_search", width="stretch"):
    st.switch_page(common.SEARCH_PAGE)

common.logout_button()
