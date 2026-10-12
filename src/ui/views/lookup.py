"""Lookup mode (task 5.3): search by plate, phone or fleet number -> vehicle card(s).

GET /vehicles/lookup?q= returns a LIST: a phone can match several trucks, a
fleet number can exist in several companies. Unknown -> empty list -> offer
the new-vehicle form.
"""

import streamlit as st

from src.ui import api_client, common

st.title("🔍 Машин хайх")
common.nav_link(to_lookup=False)

# Arrived from another page with a query (e.g. "view card" after saving).
pending = st.session_state.pop(common.LOOKUP_PENDING, None)
if pending:
    st.session_state["lookup_q"] = pending

with st.form("lookup_form", border=False):
    st.text_input(
        "Улсын дугаар, утас эсвэл парк дугаар",
        key="lookup_q",
        placeholder="1234 УБА · 99112233 · HT-12",
    )
    searched = st.form_submit_button("Хайх", width="stretch", type="primary")

query = (st.session_state.get("lookup_q") or "").strip()
if (searched or pending) and query:
    try:
        st.session_state["lookup_result"] = api_client.lookup(query)
    except api_client.ApiError as exc:
        st.session_state.pop("lookup_result", None)
        common.show_api_error(exc)
elif searched:
    st.warning("Хайх утгаа оруулна уу.")

result = st.session_state.get("lookup_result")
if result:
    vehicles = result.get("vehicles") or []
    match_type = result.get("match_type")
    by = {"phone": "утасны дугаараар", "fleet_no": "парк дугаараар"}.get(match_type, "улсын дугаараар")
    st.caption(f"«{result.get('query', '')}» — {by} хайсан · {len(vehicles)} машин олдлоо")

    if not vehicles:
        st.info("Олдсонгүй. Энэ машин бүртгэлгүй байна.")
        if match_type != "phone" and st.button("➕ Шинэ машин бүртгэх", width="stretch"):
            common.go_record("plate", result.get("query", ""), None)
    for i, card in enumerate(vehicles):
        common.render_vehicle_card(card, key=f"lookup_{card['id']}_{i}")

common.logout_button()
