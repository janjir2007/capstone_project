"""Recording mode (task 5.2): photo -> plate -> check -> pre-filled form -> save.

Flow:
1. Photo (camera or upload) -> POST /plates/recognize. A clear read is looked up
   at once; needs_manual (or recognizer down) -> the oil changer checks/types it.
2. "Шалгах" looks the plate up. Existing vehicle -> form pre-filled from the last
   service; new vehicle -> empty form + company/model fields.
3. Odometer / engine hours and destination are always entered fresh (D-033).
4. Save -> POST /services. 409 duplicate_service -> warning + "Ингээд хадгалах"
   (resend with force=true).

Buttons use on_click callbacks: a callback runs BEFORE the page is redrawn, so
it may change widget values (pre-fill, reset). Messages for the next draw are
kept in st.session_state["rec_msgs"].
"""

import streamlit as st

from src.ui import api_client, common, logic

NEW_VEHICLE = -1  # option in the "which truck?" radio for fleet numbers


# --- state helpers -----------------------------------------------------------

def _say(level: str, text: str) -> None:
    """Queue a message (level: success/info/warning/error) for the next draw."""
    st.session_state.setdefault("rec_msgs", []).append((level, text))


def _apply_form(values: dict) -> None:
    """Write form values into the widget keys (f_<field>)."""
    for name in logic.FORM_FIELDS:
        st.session_state[f"f_{name}"] = values.get(name)
    st.session_state["f_oil_changer"] = st.session_state.get(common.OIL_CHANGER)


def _selected_card() -> dict | None:
    """The existing vehicle chosen for this service, or None (new vehicle)."""
    checked = st.session_state.get("rec_checked")
    if not checked or not checked["matches"]:
        return None
    choice = st.session_state.get("rec_choice", 0)
    if choice is None or choice == NEW_VEHICLE or choice >= len(checked["matches"]):
        return None
    return checked["matches"][choice]


def _set_checked(identifier_type: str, identifier: str, matches: list[dict], card: dict | None) -> None:
    """Remember the checked vehicle and pre-fill the form for it."""
    st.session_state["rec_checked"] = {
        "identifier_type": identifier_type,
        "identifier": identifier,
        "matches": matches,
    }
    st.session_state["rec_choice"] = matches.index(card) if card in matches else (0 if matches else NEW_VEHICLE)
    st.session_state.pop("rec_dup", None)
    _apply_form(logic.prefill_from_card(card))


# --- callbacks -----------------------------------------------------------------

def on_check() -> None:
    """Look the typed plate / fleet number up and pre-fill the form."""
    identifier_type = st.session_state.get("rec_identifier_type", "plate")
    identifier = (st.session_state.get("rec_identifier") or "").strip()
    st.session_state.pop("rec_saved", None)
    if not identifier:
        _say("error", "Дугаараа оруулна уу.")
        return
    try:
        result = api_client.lookup(identifier)
    except api_client.ApiError as exc:
        st.session_state.pop("rec_checked", None)
        for message in logic.error_messages(exc.status, exc.detail):
            _say("error", message)
        return
    if result.get("match_type") == "phone":
        st.session_state.pop("rec_checked", None)
        _say("warning", "Энэ утасны дугаар байна. Машины дугаараа оруулна уу (утсаар хайх бол «Хайлт»).")
        return
    matches = [v for v in result.get("vehicles", []) if v.get("identifier_type") == identifier_type]
    _set_checked(identifier_type, identifier, matches, matches[0] if matches else None)


def on_choice() -> None:
    """Another truck picked in the fleet-number radio -> pre-fill for it."""
    st.session_state.pop("rec_dup", None)
    _apply_form(logic.prefill_from_card(_selected_card()))


def _send(payload: dict, force: bool) -> None:
    """POST /services and turn the answer into state + messages."""
    try:
        result = api_client.create_service(payload, force=force)
    except api_client.DuplicateService as exc:
        st.session_state["rec_dup"] = {"payload": payload, "existing_id": exc.existing_service_id}
        return
    except api_client.ApiError as exc:
        for message in logic.error_messages(exc.status, exc.detail):
            _say("error", message)
        return
    st.session_state[common.OIL_CHANGER] = payload.get("oil_changer")
    st.session_state["rec_saved"] = {
        "identifier": payload["identifier"],
        "vehicle_created": result.get("vehicle_created", False),
    }
    # Reset for the next truck.
    for key in ("rec_checked", "rec_dup", "rec_choice"):
        st.session_state.pop(key, None)
    st.session_state["rec_identifier"] = ""
    _apply_form(logic.empty_form())


def on_save() -> None:
    """Validate the form and send it."""
    checked = st.session_state.get("rec_checked") or {}
    form = {name: st.session_state.get(f"f_{name}") for name in logic.FORM_FIELDS}
    payload, errors = logic.build_service_payload(
        identifier_type=checked.get("identifier_type", "plate"),
        identifier=checked.get("identifier"),
        is_new_vehicle=_selected_card() is None,
        form=form,
        oil_changer=st.session_state.get("f_oil_changer"),
    )
    if errors:
        for message in errors:
            _say("error", message)
        return
    _send(payload, force=False)


def on_force() -> None:
    """'Ингээд хадгалах': resend the duplicate with force=true."""
    dup = st.session_state.get("rec_dup")
    if dup:
        _send(dup["payload"], force=True)


def on_cancel_dup() -> None:
    st.session_state.pop("rec_dup", None)


def on_photo(key: str) -> None:
    """New photo -> POST /plates/recognize. Clear read -> fill + look up;
    needs_manual -> fill what was read and ask to check (contract v0.5)."""
    photo = st.session_state.get(key)
    if photo is None:
        return
    plate, needs_manual, message = common.recognize_photo(photo)
    st.session_state["rec_identifier_type"] = "plate"
    st.session_state["rec_identifier"] = plate
    if needs_manual:
        st.session_state.pop("rec_checked", None)
        _say("warning", message)
    else:
        _say("info", message)
        on_check()


# --- page ----------------------------------------------------------------------

st.title("🛢️ Үйлчилгээ бүртгэх")
common.nav_link(to_lookup=True)

# Arrived from the lookup page ("➕ Үйлчилгээ бүртгэх" / "Шинэ машин бүртгэх").
pending = st.session_state.pop(common.REC_PENDING, None)
if pending:
    st.session_state.pop("rec_saved", None)
    st.session_state["rec_identifier_type"] = pending["identifier_type"]
    st.session_state["rec_identifier"] = pending["identifier"]
    card = pending["card"]
    _set_checked(pending["identifier_type"], pending["identifier"], [card] if card else [], card)

# Widget values are dropped when the user visits another page; restore them.
checked = st.session_state.get("rec_checked")
if "f_oil_grade" not in st.session_state:
    _apply_form(logic.prefill_from_card(_selected_card()))
if checked and "rec_identifier" not in st.session_state:
    st.session_state["rec_identifier_type"] = checked["identifier_type"]
    st.session_state["rec_identifier"] = checked["identifier"]

for level, text in st.session_state.pop("rec_msgs", []):
    getattr(st, level)(text)

saved = st.session_state.get("rec_saved")
if saved:
    note = " (шинэ машин)" if saved["vehicle_created"] else ""
    st.success(f"✅ Хадгалагдлаа: {saved['identifier']}{note}")
    if st.button("Картыг харах", width="stretch"):
        common.go_lookup(saved["identifier"])

# 1. Photo -> automatic plate reading ---------------------------------------------
with st.expander("📷 Зургаар таних", expanded=False):
    if st.toggle("Камер нээх", key="rec_camera_on"):
        st.camera_input("Дугаарын зураг авах", key="rec_cam", on_change=on_photo, args=("rec_cam",))
    st.file_uploader(
        "Эсвэл зураг оруулах", type=["jpg", "jpeg", "png", "heic", "heif"],
        key="rec_upload", on_change=on_photo, args=("rec_upload",),
    )
    st.caption("Зураг хадгалагдахгүй. Уншигдсан дугаарыг доор шалгана уу.")

# 2. Plate / fleet number -----------------------------------------------------------
st.radio(
    "Төрөл",
    options=["plate", "fleet_no"],
    format_func=logic.IDENTIFIER_TYPE_LABELS.get,
    key="rec_identifier_type",
    horizontal=True,
)
st.text_input("Дугаар", key="rec_identifier", placeholder="1234 УБА")
st.button("Шалгах", on_click=on_check, width="stretch", type="primary")

identifier_type = st.session_state.get("rec_identifier_type", "plate")
identifier = (st.session_state.get("rec_identifier") or "").strip()
checked = st.session_state.get("rec_checked")

if checked and (checked["identifier"] != identifier or checked["identifier_type"] != identifier_type):
    st.info("Дугаар өөрчлөгдсөн — «Шалгах» дарна уу.")
    checked = None

# 3. Form --------------------------------------------------------------------------
if checked:
    matches = checked["matches"]
    if identifier_type == "fleet_no" and matches:
        st.radio(
            "Аль компанийн машин бэ?",
            options=list(range(len(matches))) + [NEW_VEHICLE],
            format_func=lambda i: "Өөр компанийн шинэ машин"
            if i == NEW_VEHICLE
            else (matches[i].get("company") or {}).get("name", "?"),
            key="rec_choice",
            on_change=on_choice,
        )
    card = _selected_card()
    is_new = card is None
    last = (card or {}).get("last_service") or {}

    if is_new:
        st.info("🆕 Шинэ машин — мэдээллийг бүрэн бөглөнө үү.")
    else:
        st.success(
            f"Бүртгэлтэй машин · {card['service_count']} удаа · {logic.segment_label(card.get('segment'))}"
        )
        with st.expander("Машины карт"):
            common.render_vehicle_card(card, key="rec_card", show_record_button=False)

    company_locked = not is_new
    st.text_input(
        "Компани / эзэмшигч" + (" *" if not company_locked else ""),
        key="f_company_name",
        disabled=company_locked,
    )
    if is_new:
        st.text_input("Машины загвар", key="f_vehicle_model", placeholder="Howo A7")

    st.number_input(
        "Гүйлт (км)",
        min_value=0,
        step=1000,
        key="f_odometer_km",
        placeholder="одоогийн км",
        help=f"Өмнөх: {logic.format_number(last.get('odometer_km'), 'км')}" if last else None,
    )
    st.number_input(
        "Моторын цаг (уурхайн машин)",
        min_value=0.0,
        step=0.1,
        format="%.1f",
        key="f_engine_hours",
        placeholder="заавал биш",
    )
    st.caption("Гүйлт эсвэл моторын цагийн аль нэг заавал.")

    st.text_input("Тосны төрөл *", key="f_oil_grade", placeholder="15W-40")
    st.number_input("Литр *", min_value=0.0, step=0.5, format="%.1f", key="f_liters")

    try:
        destinations = common.cached_destinations()
    except api_client.ApiError:
        destinations = []
        st.warning("Газрын жагсаалт ачаалагдсангүй — газрын нэрийг гараар бичнэ үү.")
    dest_by_id = {d["id"]: d for d in destinations}
    st.selectbox(
        "Дараа нь хаашаа явах вэ? *",
        options=list(dest_by_id) + [logic.OTHER_DESTINATION],
        format_func=lambda i: "Жагсаалтад байхгүй…"
        if i == logic.OTHER_DESTINATION
        else logic.destination_label(dest_by_id[i]),
        index=None,
        placeholder="Сонгоно уу",
        key="f_destination_id",
    )
    if st.session_state.get("f_destination_id") == logic.OTHER_DESTINATION:
        st.text_input("Газрын нэр *", key="f_destination_raw")
        st.selectbox(
            "Маршрутын төрөл *",
            options=list(logic.ROUTE_LABELS),
            format_func=logic.ROUTE_LABELS.get,
            index=None,
            placeholder="Сонгоно уу",
            key="f_route",
        )

    st.text_input("Жолоочийн нэр", key="f_driver_name")
    st.text_input("Жолоочийн утас", key="f_driver_phone", placeholder="99112233")
    st.text_input("Тос солигч", key="f_oil_changer")

    dup = st.session_state.get("rec_dup")
    if dup:
        ref = f" (№{dup['existing_id']})" if dup.get("existing_id") else ""
        st.warning(
            f"Энэ машинд өнөөдөр үйлчилгээ аль хэдийн бүртгэгдсэн байна{ref}. Дахин хадгалах уу?"
        )
        left, right = st.columns(2)
        left.button("Ингээд хадгалах", on_click=on_force, width="stretch", type="primary")
        right.button("Болих", on_click=on_cancel_dup, width="stretch")
    else:
        st.button("💾 Хадгалах", on_click=on_save, width="stretch", type="primary")

common.logout_button()
