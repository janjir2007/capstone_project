"""Record screen (task 5.2, DESIGN v3 / T6): camera -> confirm plate -> form -> saved.

Steps (st.session_state["rec_step"]):
- capture: camera (or upload) -> POST /plates/recognize. Clear read -> lookup ->
  confirm. needs_manual / recognizer down -> manual. «Дугаарыг гараар оруулах» -> manual;
  «Дугааргүй машин» -> manual in fleet-number mode (D-005).
- manual:  type the plate (or fleet number) -> «Шалгах» -> lookup -> confirm.
- confirm: photo preview + plate in a big box + chip «Бүртгэлтэй · N удаа ирсэн» /
  «Шинэ машин» -> «Зөв, үргэлжлүүлэх» (form) or «Буруу байна — засах» (manual).
- form:    photo preview; card 1 = odometer (+ engine hours for fleet numbers),
  destination pills (GET /destinations, «Бусад» -> text + route, D-039) — always fresh
  (D-033) — and oil grade as 3 tap options + «Бусад» (default = last service, else 15W-40);
  card 2 = existing truck: «Өмнөхөөс авсан» (liters · driver · phone) + «Засах»;
  new truck: company (required, D-042), model (list + «Бусад»), liters, driver, phone.
  «Хадгалах» -> POST /services; 409 duplicate -> «Ингээд хадгалах» (force=true).
- success: «Хадгалагдлаа» -> «Дараагийн машин» / «Машины карт үзэх».

The photo is kept only in this browser session (st.session_state) for the preview; it is
never stored and never sent anywhere except POST /plates/recognize (D-070).
Buttons use on_click callbacks: a callback runs BEFORE the screen is redrawn,
so it may change widget values (pre-fill, reset) and the step.
"""

import streamlit as st

from src.ui import api_client, common, logic

NEW_VEHICLE = -1  # option in the "which company?" radio for fleet numbers
STEP = "rec_step"
# Fields typed/kept as they are; oil grade and model go through a choice widget (T6).
PLAIN_FIELDS = tuple(f for f in logic.FORM_FIELDS if f not in ("oil_grade", "vehicle_model"))


# --- state helpers -------------------------------------------------------------------

def _say(level: str, text: str) -> None:
    """Queue a message (success/info/warning/error) for the next draw."""
    st.session_state.setdefault("rec_msgs", []).append((level, text))


def _goto(step: str) -> None:
    st.session_state[STEP] = step


def _apply_form(values: dict) -> None:
    """Write form values into the widget keys (f_<field>, oil/model choice widgets)."""
    for name in PLAIN_FIELDS:
        st.session_state[f"f_{name}"] = values.get(name)
    oil_choice, oil_other = logic.split_choice(values.get("oil_grade"), logic.OIL_GRADES, logic.DEFAULT_OIL_GRADE)
    st.session_state["f_oil_choice"], st.session_state["f_oil_other"] = oil_choice, oil_other
    model = (values.get("vehicle_model") or "").strip() or None
    st.session_state["rec_model_seed"] = model  # an old value not in the list still shows
    st.session_state["f_model_choice"], st.session_state["f_model_other"] = model, None


def _form_values() -> dict:
    """Current form values, with oil grade and model resolved from their choice widgets."""
    form = {name: st.session_state.get(f"f_{name}") for name in PLAIN_FIELDS}
    form["oil_grade"] = logic.resolve_choice(st.session_state.get("f_oil_choice"), st.session_state.get("f_oil_other"))
    form["vehicle_model"] = logic.resolve_choice(st.session_state.get("f_model_choice"),
                                                 st.session_state.get("f_model_other"))
    return form


def _reset() -> None:
    """Forget the current truck (and its photo); start again at the camera."""
    for key in ("rec_checked", "rec_choice", "rec_dup", "rec_saved", "rec_manual", "rec_photo", "rec_photo_name"):
        st.session_state.pop(key, None)
    st.session_state["rec_type"] = "plate"
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


def _photo_preview() -> None:
    """The photo just taken/uploaded (session memory only, D-070)."""
    common.photo_preview(st.session_state.get("rec_photo"), st.session_state.get("rec_photo_name"))


# --- callbacks -------------------------------------------------------------------------

def on_photo(key: str) -> None:
    """New photo -> recognize. Clear read -> lookup; needs_manual -> manual step."""
    photo = st.session_state.get(key)
    if photo is None:
        return
    st.session_state["rec_photo"] = photo.getvalue()  # preview only; never stored or re-sent
    st.session_state["rec_photo_name"] = photo.name
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


def on_manual_open(identifier_type: str = "plate") -> None:
    st.session_state.pop("rec_photo", None)
    st.session_state["rec_manual"] = ""
    st.session_state["rec_type"] = identifier_type
    _goto("manual")


def on_toggle_fleet() -> None:
    """«Дугааргүй машин» <-> «Улсын дугаартай машин» (fleet number mode, D-005)."""
    st.session_state["rec_type"] = "plate" if st.session_state.get("rec_type") == "fleet_no" else "fleet_no"


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
    saved = {"identifier": payload["identifier"], "vehicle_id": result.get("vehicle_id"),
             "vehicle_created": result.get("vehicle_created", False)}
    _reset()
    st.session_state["rec_saved"] = saved
    _goto("success")


def on_save() -> None:
    checked = st.session_state.get("rec_checked") or {}
    card = _selected_card()
    form = _form_values()
    if card:  # company is hidden for existing trucks; a fleet number still needs it (D-042)
        form["company_name"] = (card.get("company") or {}).get("name")
    payload, errors = logic.build_service_payload(
        identifier_type=checked.get("identifier_type", "plate"),
        identifier=checked.get("identifier"),
        is_new_vehicle=card is None,
        form=form,
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
    for key in ("rec_saved", "rec_photo"):
        st.session_state.pop(key, None)
    _goto("form")

step = st.session_state.get(STEP, "capture")
# Widget values are dropped when the user visits another screen mid-form; restore them.
if step == "form" and "f_oil_choice" not in st.session_state:
    _apply_form(logic.prefill_from_card(_selected_card()))

common.header("Бүртгэх", back=common.HOME_PAGE)
for level, text in st.session_state.pop("rec_msgs", []):
    getattr(st, level)(text)

checked = st.session_state.get("rec_checked")

# --- steps ------------------------------------------------------------------------------

if step == "capture":
    with st.container(key="card_capture"):
        st.camera_input("Машины дугаарын зураг авна уу", key="rec_cam", on_change=on_photo, args=("rec_cam",))
        st.file_uploader("Эсвэл зураг оруулах", type=logic.UPLOAD_TYPES,
                         key="rec_upload", on_change=on_photo, args=("rec_upload",))
        st.markdown('<span class="muted">Зураг хадгалагдахгүй.</span>', unsafe_allow_html=True)
    st.button("Дугаарыг гараар оруулах", on_click=on_manual_open, width="stretch", icon=":material/keyboard:")
    st.button("Дугааргүй машин", key="link_fleet_capture", on_click=on_manual_open, args=("fleet_no",),
              type="tertiary")

elif step == "manual":
    is_fleet = st.session_state.get("rec_type") == "fleet_no"
    _photo_preview()
    with st.container(key="card_manual"):
        st.text_input("Парк дугаар" if is_fleet else "Улсын дугаар", key="rec_manual",
                      placeholder="HT-12" if is_fleet else "1234 УБА")
    st.button("Шалгах", on_click=on_manual_check, type="primary", width="stretch")
    st.button("Улсын дугаартай машин" if is_fleet else "Дугааргүй машин", key="link_fleet_toggle",
              on_click=on_toggle_fleet, type="tertiary")
    st.button("Зураг авах", key="link_capture", on_click=_goto, args=("capture",), type="tertiary",
              icon=":material/photo_camera:")

elif step == "confirm" and checked:
    matches = checked["matches"]
    _photo_preview()
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

    _photo_preview()
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
            format_func=lambda i: logic.OTHER_CHOICE if i == logic.OTHER_DESTINATION
            else logic.destination_label(dest_by_id[i]),
            key="f_destination_id",
        )
        if st.session_state.get("f_destination_id") == logic.OTHER_DESTINATION:
            st.text_input("Газрын нэр", key="f_destination_raw")
            st.pills("Маршрут", options=list(logic.ROUTE_LABELS), format_func=logic.ROUTE_LABELS.get, key="f_route")

        st.pills("Тосны төрөл", options=[*logic.OIL_GRADES, logic.OTHER_CHOICE], key="f_oil_choice")
        if st.session_state.get("f_oil_choice") == logic.OTHER_CHOICE:
            st.text_input("Тосны төрөл (бичих)", key="f_oil_other", placeholder="5W-30")

    with st.container(key="card_prev"):
        if is_new:
            st.markdown("**Шинэ машин**")
            st.text_input("Компани / эзэмшигч", key="f_company_name",
                          help="Хувь хүн бол эзэмшигчийн нэр")
            st.selectbox("Машины загвар", options=logic.model_options(st.session_state.get("rec_model_seed")),
                         index=None, placeholder="Хайх эсвэл сонгох", key="f_model_choice")
            if st.session_state.get("f_model_choice") == logic.OTHER_CHOICE:
                st.text_input("Машины загвар (бичих)", key="f_model_other")
            st.number_input("Литр", min_value=0.0, step=0.5, format="%.1f", key="f_liters")
            st.text_input("Жолоочийн нэр", key="f_driver_name")
            st.text_input("Жолоочийн утас", key="f_driver_phone", placeholder="99112233")
        else:
            st.markdown("**Өмнөхөөс авсан**")
            st.markdown(f'<div class="muted">{logic.prev_summary(_form_values())}</div>', unsafe_allow_html=True)
            with st.expander("Засах"):
                st.number_input("Литр", min_value=0.0, step=0.5, format="%.1f", key="f_liters")
                st.text_input("Жолоочийн нэр", key="f_driver_name")
                st.text_input("Жолоочийн утас", key="f_driver_phone")

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
    st.button("Дараагийн машин", on_click=_reset, type="primary", width="stretch", icon=":material/photo_camera:")
    if saved.get("vehicle_id") and st.button("Машины карт үзэх", width="stretch"):
        common.go_card(saved["vehicle_id"])

else:  # unknown/stale step (e.g. state lost) -> start over
    _reset()
    st.rerun()

common.logout_button()
