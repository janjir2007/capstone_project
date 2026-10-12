"""Record screen (task 5.2, DESIGN v2): camera -> confirm plate -> form -> saved.

Steps (st.session_state["rec_step"]):
- capture: camera (or upload) -> POST /plates/recognize. Clear read -> lookup ->
  confirm. needs_manual / recognizer down -> manual. «Дугаарыг гараар оруулах» -> manual.
- manual:  type plate or fleet number -> «Шалгах» -> lookup -> confirm.
- confirm: plate in a big box + chip «Бүртгэлтэй · N удаа ирсэн» / «Шинэ машин»
  -> «Зөв, үргэлжлүүлэх» (form) or «Буруу байна — засах» (manual).
- form:    card 1 = odometer (+ engine hours for fleet numbers) + destination pills
  (GET /destinations, «Бусад» -> text + route, D-039) — always fresh (D-033);
  card 2 = «Өмнөхөөс авсан» summary + «Засах» (existing) / full fields (new).
  «Хадгалах» -> POST /services; 409 duplicate -> «Ингээд хадгалах» (force=true).
- success: ✓ «Хадгалагдлаа» -> «Дараагийн машин» / «Машины карт үзэх».

Buttons use on_click callbacks: a callback runs BEFORE the screen is redrawn,
so it may change widget values (pre-fill, reset) and the step.
"""

import streamlit as st

from src.ui import api_client, common, logic

NEW_VEHICLE = -1  # option in the "which company?" radio for fleet numbers
STEP = "rec_step"


# --- state helpers -------------------------------------------------------------------

def _say(level: str, text: str) -> None:
    """Queue a message (success/info/warning/error) for the next draw."""
    st.session_state.setdefault("rec_msgs", []).append((level, text))


def _goto(step: str) -> None:
    st.session_state[STEP] = step


def _apply_form(values: dict) -> None:
    """Write form values into the widget keys (f_<field>)."""
    for name in logic.FORM_FIELDS:
        st.session_state[f"f_{name}"] = values.get(name)
    st.session_state["f_oil_changer"] = st.session_state.get(common.OIL_CHANGER)


def _reset() -> None:
    """Forget the current truck; start again at the camera."""
    for key in ("rec_checked", "rec_choice", "rec_dup", "rec_saved", "rec_manual"):
        st.session_state.pop(key, None)
    _apply_form(logic.empty_form())
    _goto("capture")


def _selected_card() -> dict | None:
    """The existing vehicle chosen for this service, or None (new vehicle)."""
    checked = st.session_state.get("rec_checked")
    if not checked or not checked["matches"]:
        return None
    choice = st.session_state.get("rec_choice", 0)
    if choice is None or choice == NEW_VEHICLE or choice >= len(checked["matches"]):
        return None
    return checked["matches"][choice]


def _set_checked(identifier_type: str, identifier: str, matches: list[dict]) -> None:
    st.session_state["rec_checked"] = {"identifier_type": identifier_type, "identifier": identifier,
                                       "matches": matches}
    st.session_state["rec_choice"] = 0 if matches else NEW_VEHICLE
    st.session_state.pop("rec_dup", None)


def _lookup(identifier_type: str, identifier: str) -> None:
    """GET /vehicles/lookup -> confirm step (or a message and stay)."""
    identifier = identifier.strip()
    if not identifier:
        _say("error", "Дугаараа оруулна уу.")
        return
    try:
        result = api_client.lookup(identifier)
    except api_client.ApiError as exc:
        for message in logic.error_messages(exc.status, exc.detail):
            _say("error", message)
        return
    if result.get("match_type") == "phone":
        _say("warning", "Энэ утасны дугаар байна. Машины дугаараа оруулна уу (утсаар хайх бол «Хайх»).")
        return
    matches = [v for v in result.get("vehicles", []) if v.get("identifier_type") == identifier_type]
    _set_checked(identifier_type, identifier, matches)
    _goto("confirm")


# --- callbacks -------------------------------------------------------------------------

def on_photo(key: str) -> None:
    """New photo -> recognize. Clear read -> lookup; needs_manual -> manual step."""
    photo = st.session_state.get(key)
    if photo is None:
        return
    plate, needs_manual, message = common.recognize_photo(photo)
    st.session_state["rec_type"] = "plate"
    if needs_manual:
        st.session_state["rec_manual"] = plate
        _say("warning", message)
        _goto("manual")
    else:
        _say("info", message)
        _lookup("plate", plate)
        if st.session_state.get(STEP) != "confirm":  # lookup failed -> let him type
            st.session_state["rec_manual"] = plate
            _goto("manual")


def on_manual_open() -> None:
    st.session_state["rec_manual"] = ""
    _goto("manual")


def on_manual_check() -> None:
    _lookup(st.session_state.get("rec_type", "plate"), st.session_state.get("rec_manual") or "")


def on_confirm() -> None:
    """«Зөв, үргэлжлүүлэх»: pre-fill from the chosen truck's last service."""
    _apply_form(logic.prefill_from_card(_selected_card()))
    _goto("form")


def on_wrong() -> None:
    """«Буруу байна — засах»: back to typing, with the plate kept for editing."""
    checked = st.session_state.get("rec_checked") or {}
    st.session_state["rec_manual"] = checked.get("identifier", "")
    st.session_state["rec_type"] = checked.get("identifier_type", "plate")
    _goto("manual")


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
    saved = {"identifier": payload["identifier"], "vehicle_id": result.get("vehicle_id"),
             "vehicle_created": result.get("vehicle_created", False)}
    _reset()
    st.session_state["rec_saved"] = saved
    _goto("success")


def on_save() -> None:
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
    dup = st.session_state.get("rec_dup")
    if dup:
        _send(dup["payload"], force=True)


def on_cancel_dup() -> None:
    st.session_state.pop("rec_dup", None)


# --- arrival -----------------------------------------------------------------------------

if st.session_state.pop(common.REC_RESET, False):
    _reset()

# From the card («Тос солилт бүртгэх») or search («Шинэ машин бүртгэх»): straight to the form.
pending = st.session_state.pop(common.REC_PENDING, None)
if pending:
    card = pending["card"]
    _set_checked(pending["identifier_type"], pending["identifier"], [card] if card else [])
    _apply_form(logic.prefill_from_card(card))
    st.session_state.pop("rec_saved", None)
    _goto("form")

step = st.session_state.get(STEP, "capture")
# Widget values are dropped when the user visits another screen mid-form; restore them.
if step == "form" and "f_oil_grade" not in st.session_state:
    _apply_form(logic.prefill_from_card(_selected_card()))

common.header("Бүртгэх", back=common.HOME_PAGE)
for level, text in st.session_state.pop("rec_msgs", []):
    getattr(st, level)(text)

checked = st.session_state.get("rec_checked")

# --- steps ------------------------------------------------------------------------------

if step == "capture":
    with st.container(key="card_capture"):
        st.camera_input("Машины дугаарын зураг авна уу", key="rec_cam", on_change=on_photo, args=("rec_cam",))
        st.file_uploader("Эсвэл зураг оруулах", type=["jpg", "jpeg", "png", "heic", "heif"],
                         key="rec_upload", on_change=on_photo, args=("rec_upload",))
        st.markdown('<span class="muted">Зураг хадгалагдахгүй.</span>', unsafe_allow_html=True)
    st.button("Дугаарыг гараар оруулах", on_click=on_manual_open, width="stretch")

elif step == "manual":
    with st.container(key="card_manual"):
        st.radio("Төрөл", options=["plate", "fleet_no"], format_func=logic.IDENTIFIER_TYPE_LABELS.get,
                 key="rec_type", horizontal=True)
        st.text_input("Дугаар", key="rec_manual", placeholder="1234 УБА")
    st.button("Шалгах", on_click=on_manual_check, type="primary", width="stretch")
    st.button("‹ Зураг авах", on_click=_goto, args=("capture",), type="tertiary")

elif step == "confirm" and checked:
    matches = checked["matches"]
    with st.container(key="card_confirm"):
        common.plate_box(checked["identifier"])
        if checked["identifier_type"] == "fleet_no" and matches:
            st.radio(
                "Аль компанийн машин бэ?",
                options=list(range(len(matches))) + [NEW_VEHICLE],
                format_func=lambda i: "Өөр компанийн шинэ машин" if i == NEW_VEHICLE
                else (matches[i].get("company") or {}).get("name", "?"),
                key="rec_choice",
            )
        card = _selected_card()
        common.known_chip(card)
        if card:
            facts = [(card.get("company") or {}).get("name"), card.get("vehicle_model")]
            st.markdown(f'<div class="muted">{" · ".join(f for f in facts if f)}</div>', unsafe_allow_html=True)
    st.button("Зөв, үргэлжлүүлэх", on_click=on_confirm, type="primary", width="stretch")
    st.button("Буруу байна — засах", on_click=on_wrong, width="stretch")

elif step == "form" and checked:
    card = _selected_card()
    is_new = card is None
    is_fleet = checked["identifier_type"] == "fleet_no"
    last = (card or {}).get("last_service") or {}

    common.plate_box(checked["identifier"], small=True)
    common.known_chip(card)

    with st.container(key="card_fresh"):
        st.number_input("Гүйлт (км)", min_value=0, step=1000, key="f_odometer_km", placeholder="одоогийн км",
                        help=f"Өмнөх: {logic.format_number(last.get('odometer_km'), 'км')}"
                        if last.get("odometer_km") is not None else None)
        if is_fleet or last.get("engine_hours") is not None:
            st.number_input("Моторын цаг", min_value=0.0, step=0.1, format="%.1f", key="f_engine_hours",
                            placeholder="мото цаг")

        try:
            destinations = common.cached_destinations()
        except api_client.ApiError:
            destinations = []
            st.warning("Газрын жагсаалт ачаалагдсангүй — «Бусад» сонгож бичнэ үү.")
        dest_by_id = {d["id"]: d for d in destinations}
        st.pills(
            "Дараа нь хаашаа явах вэ?",
            options=list(dest_by_id) + [logic.OTHER_DESTINATION],
            format_func=lambda i: "Бусад" if i == logic.OTHER_DESTINATION else logic.destination_label(dest_by_id[i]),
            key="f_destination_id",
        )
        if st.session_state.get("f_destination_id") == logic.OTHER_DESTINATION:
            st.text_input("Газрын нэр", key="f_destination_raw")
            st.pills("Маршрут", options=list(logic.ROUTE_LABELS), format_func=logic.ROUTE_LABELS.get, key="f_route")

    with st.container(key="card_prev"):
        if is_new:
            st.markdown("**Машины мэдээлэл**")
            st.text_input("Компани / эзэмшигч", key="f_company_name")
            st.text_input("Машины загвар", key="f_vehicle_model", placeholder="Howo A7")
            st.text_input("Тосны төрөл", key="f_oil_grade", placeholder="15W-40")
            st.number_input("Литр", min_value=0.0, step=0.5, format="%.1f", key="f_liters")
            st.text_input("Жолоочийн нэр", key="f_driver_name")
            st.text_input("Жолоочийн утас", key="f_driver_phone", placeholder="99112233")
            st.text_input("Тос солигч", key="f_oil_changer")
        else:
            st.markdown("**Өмнөхөөс авсан**")
            current = {name: st.session_state.get(f"f_{name}") for name in logic.FORM_FIELDS}
            st.markdown(f'<div class="muted">{logic.prev_summary(current)}</div>', unsafe_allow_html=True)
            with st.expander("Засах"):
                st.text_input("Тосны төрөл", key="f_oil_grade")
                st.number_input("Литр", min_value=0.0, step=0.5, format="%.1f", key="f_liters")
                st.text_input("Жолоочийн нэр", key="f_driver_name")
                st.text_input("Жолоочийн утас", key="f_driver_phone")
                st.text_input("Тос солигч", key="f_oil_changer")

    dup = st.session_state.get("rec_dup")
    if dup:
        ref = f" (№{dup['existing_id']})" if dup.get("existing_id") else ""
        st.warning(f"Энэ машинд өнөөдөр үйлчилгээ аль хэдийн бүртгэгдсэн байна{ref}. Дахин хадгалах уу?")
        st.button("Ингээд хадгалах", on_click=on_force, type="primary", width="stretch")
        st.button("Болих", on_click=on_cancel_dup, width="stretch")
    else:
        st.button("Хадгалах", on_click=on_save, type="primary", width="stretch")

elif step == "success" and st.session_state.get("rec_saved"):
    saved = st.session_state["rec_saved"]
    with st.container(key="card_success"):
        st.markdown('<div class="done">✓</div><div class="done-title">Хадгалагдлаа</div>', unsafe_allow_html=True)
        common.plate_box(saved["identifier"], small=True)
        if saved["vehicle_created"]:
            st.markdown('<div class="muted" style="text-align:center">Шинэ машин бүртгэгдлээ</div>',
                        unsafe_allow_html=True)
    st.button("Дараагийн машин", on_click=_reset, type="primary", width="stretch")
    if saved.get("vehicle_id") and st.button("Машины карт үзэх", width="stretch"):
        common.go_card(saved["vehicle_id"])

else:  # unknown/stale step (e.g. state lost) -> start over
    _reset()
    st.rerun()

common.logout_button()
