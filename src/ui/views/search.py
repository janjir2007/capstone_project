"""Search screen (task 5.3 / DESIGN v2): plate, phone or fleet number -> vehicle card.

GET /vehicles/lookup returns a LIST (a phone can match several trucks, a fleet
number several companies). Exactly one match opens the card at once; several
show a short list; none offers the new-vehicle form. «Камераар хайх» reads the
plate from a photo. «Сүүлд үзсэн» = cards opened in this session.
"""

import streamlit as st

from src.ui import api_client, common, logic


def on_photo(key: str) -> None:
    """Photo -> recognize. Clear read -> search; needs_manual -> fill the field, wait."""
    photo = st.session_state.get(key)
    if photo is None:
        return
    plate, needs_manual, message = common.recognize_photo(photo)
    st.session_state["search_photo_msg"] = ("warning" if needs_manual else "info", message)
    if needs_manual:
        st.session_state["search_q"] = plate
    else:
        st.session_state[common.SEARCH_PENDING] = plate


def on_toggle_camera() -> None:
    st.session_state["search_cam_open"] = not st.session_state.get("search_cam_open", False)


common.header("Хайх", back=common.HOME_PAGE)

pending = st.session_state.pop(common.SEARCH_PENDING, None)
if pending:
    st.session_state["search_q"] = pending

with st.container(key="card_search"):
    with st.form("search_form", border=False):
        # The API still matches fleet numbers too; the label names the two common cases (T6).
        st.text_input("Улсын дугаар эсвэл утас", key="search_q", placeholder="1234 УБА · 99112233")
        searched = st.form_submit_button("Хайх", type="primary", width="stretch")
    st.button("Камераар хайх", key="btn_dark_cam", width="stretch", on_click=on_toggle_camera,
              icon=":material/photo_camera:")
    if st.session_state.get("search_cam_open"):
        st.camera_input("Дугаарын зураг", key="search_cam", on_change=on_photo, args=("search_cam",),
                        label_visibility="collapsed")
        st.file_uploader("Эсвэл зураг оруулах", type=logic.UPLOAD_TYPES,
                         key="search_upload", on_change=on_photo, args=("search_upload",))

photo_msg = st.session_state.pop("search_photo_msg", None)
if photo_msg:
    getattr(st, photo_msg[0])(photo_msg[1])

query = (st.session_state.get("search_q") or "").strip()
if (searched or pending) and query:
    try:
        result = api_client.lookup(query)
    except api_client.ApiError as exc:
        st.session_state.pop("search_result", None)
        common.show_api_error(exc)
    else:
        st.session_state["search_result"] = result
        if len(result.get("vehicles") or []) == 1:  # only right after a search, not on every redraw
            common.go_card(result["vehicles"][0]["id"])
elif searched:
    st.warning("Хайх утгаа оруулна уу.")

result = st.session_state.get("search_result")
if result:
    vehicles = result.get("vehicles") or []
    with st.container(key="card_results"):
        if not vehicles:
            if result.get("match_type") == "phone":
                st.markdown("**Олдсонгүй.** Энэ утасны дугаартай үйлчилгээ бүртгэгдээгүй байна.")
            else:
                st.markdown("**Олдсонгүй.** Энэ машин бүртгэлгүй байна.")
            if result.get("match_type") != "phone" and st.button("Шинэ машин бүртгэх", type="primary",
                                                                  width="stretch"):
                common.go_record("plate", result.get("query", ""), None)
        else:
            by = {"phone": "утасны дугаараар", "fleet_no": "парк дугаараар"}.get(
                result.get("match_type"), "улсын дугаараар")
            st.markdown(f'<span class="muted">«{result.get("query", "")}» — {by} · {len(vehicles)} машин</span>',
                        unsafe_allow_html=True)
            for v in vehicles:
                label = f"{v['identifier']} · {(v.get('company') or {}).get('name', '')} · {logic.segment_label(v.get('segment'))}"
                if st.button(label, key=f"res_{v['id']}", width="stretch"):
                    common.go_card(v["id"])

recent = st.session_state.get(common.RECENT, [])
if recent:
    st.subheader("Сүүлд үзсэн")
    for item in recent:
        if st.button(f"{item['identifier']} · {item['company']}", key=f"recent_{item['id']}", width="stretch"):
            common.go_card(item["id"])

common.logout_button()
