"""Record screen (task 5.2, DESIGN v5 / T9 mockup): camera -> form -> saved.

Steps (st.session_state["rec_step"]):
- capture: camera (or upload) -> POST /plates/recognize. Clear read -> lookup -> form.
  needs_manual / recognizer down -> manual. «Дугаарыг гараар оруулах» -> manual;
  «Дугааргүй машин» -> manual in fleet-number mode (D-005).
- manual:  type the plate (or fleet number) -> «Шалгах» -> lookup -> form.
- confirm: only for a fleet number that exists in one or more companies (D-005): «Аль компанийн
  машин бэ?» -> «Зөв, үргэлжлүүлэх». A plate goes straight to the form (T9: the form header
  shows the plate + «Бүртгэлтэй / Шинэ машин» + «Буруу»/«Засах» back to typing).
- form, two layouts (mockup):
  * «Машин танигдлаа» — an EXISTING truck read from a photo: plate strip, truck line, arrival
    block (how this visit compares with the last prediction), «Өмнөх удаа», then odometer +
    destination pills (always fresh, D-033) and oil/driver rows from the last service with
    «Тос, жолооч өөрчлөх».
  * «Үйлчилгээ бүртгэх» — everything else (typed plate, from the card/search, new truck): header
    card, [new truck: company only for fleet numbers (T8, D-042) + model], «Энэ удаа» = odometer,
    destination pills («Бусад» -> text + route, D-039), oil grade (15W-40 · 10W-40 · 20W-50 ·
    «Бусад»; default = last service, else 15W-40), liters stepper; «Жолооч» = name + phone.
  «Хадгалах» -> POST /services; 409 duplicate -> «Ингээд хадгалах» (force=true).
- success: «Хадгалагдлаа» -> «Дараагийн машин» / «Машины карт үзэх».

The photo is kept only in this browser session (st.session_state) for the preview; it is
never stored and never sent anywhere except POST /plates/recognize (D-070).
Buttons use on_click callbacks: a callback runs BEFORE the screen is redrawn,
so it may change widget values (pre-fill, reset) and the step.
"""

import html

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
    for key in ("rec_checked", "rec_choice", "rec_dup", "rec_saved", "rec_manual", "rec_photo", "rec_photo_name",
                "rec_box", "rec_recognized"):
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


def _lookup(identifier_type: str, identifier: str, from_photo: bool = False) -> None:
    """GET /vehicles/lookup -> form (fleet number found in a company -> confirm), or a message and stay."""
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
    if identifier_type == "fleet_no" and matches:
        _goto("confirm")  # which company's truck? (fleet numbers are unique per company, D-005)
        return
    _open_form(recognized=from_photo and bool(matches))


def _open_form(recognized: bool = False) -> None:
    """Pre-fill from the chosen truck's last service and show the form («Машин танигдлаа» layout
    for an existing truck read from a photo)."""
    _apply_form(logic.prefill_from_card(_selected_card()))
    st.session_state["rec_recognized"] = recognized
    _goto("form")


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
    plate, needs_manual, message, box = common.recognize_photo_box(photo)
    st.session_state["rec_box"] = box
    st.session_state["rec_type"] = "plate"
    if needs_manual:
        st.session_state["rec_manual"] = plate
        _say("warning", message)
        _goto("manual")
    else:
        _lookup("plate", plate, from_photo=True)
        if st.session_state.get(STEP) not in ("confirm", "form"):  # lookup failed -> let him type
            st.session_state["rec_manual"] = plate
            _goto("manual")


def on_manual_open(identifier_type: str = "plate") -> None:
    st.session_state.pop("rec_photo", None)
    st.session_state.pop("rec_box", None)
    st.session_state["rec_manual"] = ""
    st.session_state["rec_type"] = identifier_type
    _goto("manual")


def on_toggle_fleet() -> None:
    """«Дугааргүй машин» <-> «Улсын дугаартай машин» (fleet number mode, D-005)."""
    st.session_state["rec_type"] = "plate" if st.session_state.get("rec_type") == "fleet_no" else "fleet_no"


def on_manual_check() -> None:
    _lookup(st.session_state.get("rec_type", "plate"), st.session_state.get("rec_manual") or "")


def on_confirm() -> None:
    """«Зөв, үргэлжлүүлэх» (fleet number): pre-fill from the chosen truck's last service."""
    _open_form()


def on_wrong() -> None:
    """«Буруу» / «Засах»: back to typing, with the plate kept for editing."""
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
    for key in ("rec_saved", "rec_photo", "rec_box"):
        st.session_state.pop(key, None)
    st.session_state["rec_recognized"] = False
    _goto("form")

step = st.session_state.get(STEP, "capture")
# Widget values are dropped when the user visits another screen mid-form; restore them.
if step == "form" and "f_oil_choice" not in st.session_state:
    _apply_form(logic.prefill_from_card(_selected_card()))

recognized = step == "form" and bool(st.session_state.get("rec_recognized")) and _selected_card() is not None
common.header("Машин танигдлаа" if recognized else "Үйлчилгээ бүртгэх", back=common.HOME_PAGE)
for level, text in st.session_state.pop("rec_msgs", []):
    getattr(st, level)(text)

checked = st.session_state.get("rec_checked")


# --- form parts (shared widget keys, so both layouts save the same way) ------------------

def _meter_inputs(is_fleet: bool, last: dict, label: str, show_prev: bool) -> None:
    st.number_input(label, min_value=0, step=1000, key="f_odometer_km", placeholder="Одоогийн км")
    if show_prev and last.get("odometer_km") is not None:
        common.html_block(f'<div class="sub-note">Өмнөх: {logic.format_number(last["odometer_km"], "км")}</div>')
    if is_fleet or last.get("engine_hours") is not None:
        st.number_input("Моторын цаг", min_value=0.0, step=0.1, format="%.1f", key="f_engine_hours",
                        placeholder="мото цаг")


def _destination_inputs(label: str, last: dict) -> None:
    """Destination pills (GET /destinations) + «Бусад» -> place + route; note when it changed."""
    try:
        destinations = common.cached_destinations()
    except api_client.ApiError:
        destinations = []
        st.warning("Газрын жагсаалт ачаалагдсангүй — «Бусад» сонгож бичнэ үү.")
    dest_by_id = {d["id"]: d for d in logic.picker_destinations(destinations)}
    st.pills(
        label,
        options=list(dest_by_id) + [logic.OTHER_DESTINATION],
        format_func=lambda i: logic.OTHER_CHOICE if i == logic.OTHER_DESTINATION
        else logic.destination_label(dest_by_id[i]),
        key="f_destination_id",
    )
    chosen = st.session_state.get("f_destination_id")
    if chosen == logic.OTHER_DESTINATION:
        st.text_input("Газрын нэр", key="f_destination_raw")
        st.pills("Маршрут", options=list(logic.ROUTE_LABELS), format_func=logic.ROUTE_LABELS.get, key="f_route")
    note = logic.destination_change_note(last, chosen)
    if note:
        common.html_block(f'<div class="warn-note">{html.escape(note)}</div>')


def _oil_inputs() -> None:
    st.segmented_control("Тос", options=[*logic.OIL_GRADES, logic.OTHER_CHOICE], key="f_oil_choice")
    if st.session_state.get("f_oil_choice") == logic.OTHER_CHOICE:
        st.text_input("Тосны төрөл (бичих)", key="f_oil_other", placeholder="5W-30")


def _liters_input(card: dict | None) -> None:
    """«Литр» left (+ «Ердийн: 30 л»), stepper right."""
    usual = (card or {}).get("usual_liters")
    sub = f'<div class="s">Ердийн: {logic.format_number(usual, "л")}</div>' if usual else ""
    with st.container(key="liters_row", horizontal=True, vertical_alignment="center",
                      horizontal_alignment="distribute"):
        common.html_block(f'<div><div class="k">Литр</div>{sub}</div>')
        st.number_input("Литр", min_value=0.0, step=1.0, format="%g", key="f_liters",
                        label_visibility="collapsed", width=170)


def _driver_inputs() -> None:
    st.text_input("Нэр", key="f_driver_name")
    st.text_input("Утас", key="f_driver_phone", placeholder="9911 2233")


def _save_buttons() -> None:
    dup = st.session_state.get("rec_dup")
    if dup:
        ref = f" (№{dup['existing_id']})" if dup.get("existing_id") else ""
        st.warning(f"Энэ машинд өнөөдөр үйлчилгээ аль хэдийн бүртгэгдсэн байна{ref}. Дахин хадгалах уу?")
        st.button("Ингээд хадгалах", key="btn_save_force", on_click=on_force, type="primary", width="stretch")
        st.button("Болих", on_click=on_cancel_dup, width="stretch")
    else:
        st.button("Хадгалах", key="btn_save", on_click=on_save, type="primary", width="stretch")


def form_recognized(card: dict, checked: dict) -> None:
    """Mockup «Машин танигдлаа»: existing truck read from a photo."""
    last = card.get("last_service") or {}
    common.plate_strip(st.session_state.get("rec_photo"), st.session_state.get("rec_box"))
    with st.container(key="card_truck"):
        seg = card.get("segment")
        sub = " · ".join(p for p in (logic.segment_label(seg) if seg else None,
                                     f"{card.get('service_count', 0)} удаа",
                                     (card.get("company") or {}).get("name")) if p)
        with st.container(key="vh_row", horizontal=True, vertical_alignment="center",
                          horizontal_alignment="distribute"):
            common.html_block(
                f'<div><div class="vh-big">{html.escape(checked["identifier"])}</div>'
                f'<div class="vh-sub" style="color:#4B5563">{common._dot(logic.SEGMENT_DOTS.get(seg))}'
                f'{html.escape(sub)}</div></div>')
            st.button("Буруу", key="btn_wrong", on_click=on_wrong, type="tertiary")
        common.render_arrival(card.get("prediction"))
        common.html_block(common.kv_rows([("Өмнөх удаа", logic.prev_visit_text(last))], "sm"))

    common.section("Энэ удаагийн мэдээлэл", hint="Чиглэл өөрчлөгдвөл таамаглал шинээр бодогдоно.")
    with st.container(key="card_fresh"):
        _meter_inputs(checked["identifier_type"] == "fleet_no", last, "Одоогийн гүйлт (км)", show_prev=False)
        _destination_inputs("Одоо хаашаа явах вэ?", last)
        form = _form_values()
        oil = f"{form['oil_grade'] or logic.NOT_GIVEN} · {logic.format_number(form['liters'], 'л')}"
        common.html_block(common.kv_rows([("Тос", oil),
                                          ("Жолооч", logic.driver_text(form["driver_name"], form["driver_phone"]))],
                                         "sm top"))
        with st.expander("Тос, жолооч өөрчлөх"):
            _oil_inputs()
            _liters_input(card)
            _driver_inputs()
    _save_buttons()
    if st.button("Машины карт бүтэн харах", key="link_card", type="tertiary", width="stretch"):
        common.go_card(card["id"])


def form_full(card: dict | None, checked: dict) -> None:
    """Mockup «Үйлчилгээ бүртгэх»: header card, [new truck], «Энэ удаа», «Жолооч»."""
    is_new = card is None
    is_fleet = checked["identifier_type"] == "fleet_no"
    last = (card or {}).get("last_service") or {}
    if is_new:
        status = f'<span style="color:#1F4E9D">{common._dot("#1F4E9D")}Шинэ машин</span>'
    else:
        status = (f'<span style="color:#1E7A4C">{common._dot("#1E7A4C")}'
                  f'Бүртгэлтэй · {card.get("service_count", 0)} удаа ирсэн</span>')
    with st.container(key="card_truck"):
        with st.container(key="vh_row", horizontal=True, vertical_alignment="center",
                          horizontal_alignment="distribute"):
            common.html_block(
                f'<div class="vh"><span class="vh-tile"><i></i></span><div>'
                f'<div class="vh-id">{html.escape(checked["identifier"])}</div>'
                f'<div class="vh-sub">{status}</div></div></div>')
            st.button("Засах", key="btn_wrong", on_click=on_wrong, type="tertiary")
    _photo_preview()

    if is_new:
        st.subheader("Машин")
        with st.container(key="card_vehicle_new"):
            if is_fleet:  # T8: only fleet numbers need a company (unique per company); plates get the default
                st.text_input("Компани / эзэмшигч", key="f_company_name", help="Хувь хүн бол эзэмшигчийн нэр")
            st.selectbox("Машины загвар", options=logic.model_options(st.session_state.get("rec_model_seed")),
                         index=None, placeholder="Хайх эсвэл сонгох", key="f_model_choice")
            if st.session_state.get("f_model_choice") == logic.OTHER_CHOICE:
                st.text_input("Машины загвар (бичих)", key="f_model_other")

    st.subheader("Энэ удаа")
    with st.container(key="card_fresh"):
        _meter_inputs(is_fleet, last, "Гүйлт (км)", show_prev=True)
        _destination_inputs("Дараа нь хаашаа явах вэ?", last)
        _oil_inputs()
        _liters_input(card)

    st.subheader("Жолооч")
    with st.container(key="card_driver"):
        _driver_inputs()
        if not is_new and (last.get("driver_name") or last.get("driver_phone")):
            common.html_block('<div class="sub-note" style="margin-top:0">Өмнөх үйлчилгээнээс бөглөгдсөн. '
                              'Өөрчлөгдсөн бол засна уу.</div>')
    _save_buttons()


# --- steps ------------------------------------------------------------------------------

if step == "capture":
    with st.container(key="card_capture"):
        st.camera_input("Машины дугаарын зураг авна уу", key="rec_cam", on_change=on_photo, args=("rec_cam",))
        st.file_uploader("Эсвэл зураг оруулах", type=logic.UPLOAD_TYPES,
                         key="rec_upload", on_change=on_photo, args=("rec_upload",))
        common.html_block('<span class="muted">Зураг хадгалагдахгүй.</span>')
    st.button("Дугаарыг гараар оруулах", on_click=on_manual_open, width="stretch", icon=":material/keyboard:")
    with st.container(key="link_center"):
        st.button("Дугааргүй машин", key="link_fleet_capture", on_click=on_manual_open, args=("fleet_no",),
                  type="tertiary")

elif step == "manual":
    is_fleet = st.session_state.get("rec_type") == "fleet_no"
    _photo_preview()
    with st.container(key="card_manual"):
        st.text_input("Парк дугаар" if is_fleet else "Улсын дугаар", key="rec_manual",
                      placeholder="HT-12" if is_fleet else "1234 УБА")
    st.button("Шалгах", on_click=on_manual_check, type="primary", width="stretch")
    with st.container(key="link_center", horizontal=True, horizontal_alignment="center"):
        st.button("Улсын дугаартай машин" if is_fleet else "Дугааргүй машин", key="link_fleet_toggle",
                  on_click=on_toggle_fleet, type="tertiary")
        st.button("Зураг авах", key="link_capture", on_click=_goto, args=("capture",), type="tertiary",
                  icon=":material/photo_camera:")

elif step == "confirm" and checked:
    matches = checked["matches"]
    _photo_preview()
    with st.container(key="card_confirm"):
        st.radio(
            "Аль компанийн машин бэ?",
            options=list(range(len(matches))) + [NEW_VEHICLE],
            format_func=lambda i: "Өөр компанийн шинэ машин" if i == NEW_VEHICLE
            else (matches[i].get("company") or {}).get("name", "?"),
            key="rec_choice",
        )
        card = _selected_card()
        common.plate_box(checked["identifier"], common.known_chip_html(card))
        if card:
            facts = [(card.get("company") or {}).get("name"), card.get("vehicle_model")]
            common.html_block(f'<div class="muted">{html.escape(" · ".join(f for f in facts if f))}</div>')
    st.button("Зөв, үргэлжлүүлэх", on_click=on_confirm, type="primary", width="stretch")
    st.button("Буруу байна — засах", on_click=on_wrong, width="stretch")

elif step == "form" and checked:
    if recognized:
        form_recognized(_selected_card(), checked)
    else:
        form_full(_selected_card(), checked)

elif step == "success" and st.session_state.get("rec_saved"):
    saved = st.session_state["rec_saved"]
    with st.container(key="card_success"):
        common.html_block('<div class="done">✓</div><div class="done-title">Хадгалагдлаа</div>')
        common.html_block(f'<div class="center"><span class="plate lg">{html.escape(saved["identifier"])}</span></div>')
        if saved["vehicle_created"]:
            common.html_block('<div class="muted" style="text-align:center">Шинэ машин бүртгэгдлээ</div>')
    st.button("Дараагийн машин", on_click=_reset, type="primary", width="stretch", icon=":material/photo_camera:")
    if saved.get("vehicle_id") and st.button("Машины карт үзэх", width="stretch"):
        common.go_card(saved["vehicle_id"])

else:  # unknown/stale step (e.g. state lost) -> start over
    _reset()
    st.rerun()

common.logout_button()
