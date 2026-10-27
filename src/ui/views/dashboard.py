"""«Хяналтын самбар» (8.1; was «Тойм») — manager overview, view only (tasks 5.4, 9.1).

9.1: the only screen that uses a computer's full width (≥ 1024 px); every other screen keeps the
480 px phone column (common.CSS). Below 1024 px this screen is one column too.
- Segment tiles from GET /stats/segments (2×2 on a phone, 4 in a row on a computer).
- Search the database: any part of a plate, fleet number, company or driver phone
  (GET /vehicles/search, blank = every truck, newest service first). Results: a table on a
  computer (click a row), tappable cards on a phone.
- Selected truck: every service (date, odometer, oil, liters, driver, phone) from GET /vehicles/{id};
  beside the table on a computer, in place of the cards on a phone («Хаах» = back to the list).
- Due list from GET /reminders/due, read only (sending stays on «Сануулга»).
Nothing here writes to the API.
"""

import html
from functools import partial

import streamlit as st

from src.ui import api_client, common, logic

DASH_QUERY = "dash_q"          # search text (form field)
DASH_VEHICLE = "dash_vid"      # truck whose history is open
DASH_IDS = "dash_ids"          # vehicle ids in table order (the table selection gives a row number)
TABLE_KEY = "dash_table"
WIDE_PX = 1024                 # computer layout from this viewport width
PHONE_CARDS_MAX = 50           # tappable rows on a phone; the table shows up to the API limit
SEARCH_LIMIT = 200
ROW_PX = 35                    # table row (and header) height, so the table is exactly as tall as its rows

# Screen-only CSS: it is part of this page's output, so it disappears when another screen opens.
WIDE_CSS = f"""
<style>
@media (min-width: {WIDE_PX}px) {{
  .block-container {{max-width: 1360px !important; padding: 24px 40px 48px !important;}}
  .tiles.seg {{grid-template-columns: repeat(4, 1fr);}}
  .st-key-dash_split {{flex-direction: row !important; align-items: flex-start !important; gap: 24px !important;}}
  /* the flex items are Streamlit's stLayoutWrapper around each keyed container */
  [data-testid="stLayoutWrapper"]:has(> .st-key-dash_list) {{flex: 2 1 0 !important; min-width: 0;}}
  [data-testid="stLayoutWrapper"]:has(> .st-key-dash_hist) {{flex: 1 1 0 !important; min-width: 0;
    position: sticky; top: 16px;}}
  .st-key-grp_dash_cards, [data-testid="stLayoutWrapper"]:has(> .st-key-grp_dash_cards) {{display: none !important;}}
}}
@media (max-width: {WIDE_PX - 0.02}px) {{
  .st-key-dash_split {{flex-direction: column !important;}}
  .st-key-dash_split > * {{width: 100% !important;}}
  .st-key-dash_hist, [data-testid="stLayoutWrapper"]:has(> .st-key-dash_hist) {{order: -1;}}
  /* phone: an open history replaces the list (else it opens above, out of sight); «Хаах» brings it back */
  .st-key-dash_split:has(.st-key-dash_hist) .st-key-dash_list,
  .st-key-dash_split:has(.st-key-dash_hist) [data-testid="stLayoutWrapper"]:has(> .st-key-dash_list) {{display: none !important;}}
  .st-key-dash_table_wrap, [data-testid="stLayoutWrapper"]:has(> .st-key-dash_table_wrap) {{display: none !important;}}
}}
/* no table toolbar (CSV download, search, fullscreen): export only via the Excel button (9.1 step 2) */
.st-key-dash_table_wrap [data-testid="stElementToolbar"] {{display: none !important;}}
/* history: a table on a computer, one small card per service on a phone */
.hist-wrap {{overflow-x: auto;}}  /* a narrow history panel scrolls sideways inside its card */
.hist {{width: 100%; border-collapse: collapse; font-size: 13px;}}
.hist th {{text-align: left; font-size: 12px; color: var(--muted); font-weight: 600; padding: 0 12px 8px 0;
  border-bottom: 1px solid var(--line); white-space: nowrap;}}
.hist td {{padding: 10px 12px 10px 0; border-bottom: 1px solid var(--line); vertical-align: top; white-space: nowrap;}}
.hist tr:last-child td {{border-bottom: none;}}
.hist td.n, .hist .ph {{font-variant-numeric: tabular-nums;}}
.hist .ph {{color: var(--muted); margin-top: 2px;}}
@media (max-width: {WIDE_PX - 0.02}px) {{
  .hist thead {{display: none;}}
  .hist, .hist tbody, .hist tr, .hist td {{display: block; width: 100%;}}
  .hist tr {{display: grid; grid-template-columns: 1fr 1fr; gap: 4px 12px; padding: 12px 0; border-bottom: 1px solid var(--line);}}
  .hist tr:first-child {{padding-top: 0;}} .hist tr:last-child {{border-bottom: none; padding-bottom: 0;}}
  .hist td {{padding: 0; border: none; white-space: normal; font-size: 14px;}}
  .hist td::before {{content: attr(data-l); display: block; font-size: 12px; color: var(--muted);}}
}}
.dash-due {{display: grid; grid-template-columns: minmax(0, 1fr); gap: 0;}}
.dash-due .rem .who {{min-width: 0;}}  /* long company names wrap; the status pill keeps its size */
.dash-due .pill-st {{flex: none;}}
.st-key-dash_hist_top {{flex-wrap: nowrap !important; justify-content: space-between;}}
.st-key-dash_hist_top > [data-testid="stElementContainer"]:first-child {{flex: 1 1 auto; min-width: 0; width: auto !important;}}
</style>
"""


def on_table_select(key: str) -> None:
    """Table row clicked: open that truck's history (row number -> id of the table just shown)."""
    rows = st.session_state[key].selection.rows
    ids = st.session_state.get(DASH_IDS, [])
    st.session_state[DASH_VEHICLE] = ids[rows[0]] if rows and rows[0] < len(ids) else None


def open_history(vehicle_id: int | None) -> None:
    st.session_state[DASH_VEHICLE] = vehicle_id


def segment_tiles() -> None:
    try:
        stats = api_client.segment_stats()
    except api_client.ApiError as exc:
        common.show_api_error(exc)
        return
    counts = stats.get("counts") or {}
    tiles = "".join(
        f'<div><div class="v">{counts.get(s, 0)}</div><div class="k"><i class="dot" '
        f'style="background:{logic.SEGMENT_DOTS[s]}"></i>{logic.SEGMENT_LABELS[s]}</div></div>'
        for s in logic.SEGMENT_ORDER
    )
    common.html_block(f'<div class="tiles two seg">{tiles}</div>')
    common.html_block(f'<span class="muted">Нийт {stats.get("total", 0)} машин · {stats.get("as_of", "")}</span>')


def search_form() -> None:
    with st.container(key="card_dash_search"):
        with st.form("dash_search_form", border=False):  # Enter in the field searches too
            cols = st.columns([4, 1], vertical_alignment="bottom")
            cols[0].text_input("Улсын дугаар, утас эсвэл компани", key=DASH_QUERY,
                               placeholder="1234 УБА · 9911 · Говь Тээвэр")
            cols[1].form_submit_button("Хайх", type="primary", width="stretch")


def results_table(vehicles: list[dict], query: str) -> None:
    """Computer view: sortable table; clicking a row opens the history (no editing).

    The widget key includes the query, so a new search starts with no row highlighted
    (a kept selection would point at a row number of the OLD results)."""
    st.session_state[DASH_IDS] = [v["id"] for v in vehicles]
    key = f"{TABLE_KEY}:{query}"
    with st.container(key="dash_table_wrap"):
        st.dataframe(
            logic.search_table_rows(vehicles), key=key, on_select=partial(on_table_select, key),  # no args= here
            selection_mode="single-row", hide_index=True, width="stretch", row_height=ROW_PX,
            height=min(ROW_PX * (len(vehicles) + 1) + 3, 16 * ROW_PX),  # header + rows; scrolls after 15 rows
            column_config={
                "Гүйлт (км)": st.column_config.NumberColumn(format="localized"),
                "Литр": st.column_config.NumberColumn(format="%.1f"),
            },
        )


def results_cards(vehicles: list[dict]) -> None:
    """Phone view: one tappable row per truck (plate · company · status, then last service)."""
    with st.container(key="grp_dash_cards"):
        for v in vehicles[:PHONE_CARDS_MAX]:
            last = v.get("last_service") or {}
            sub = " · ".join(p for p in (last.get("service_date"), logic.driver_text(
                last.get("driver_name"), last.get("driver_phone"))) if p and p != logic.NOT_GIVEN)
            with st.container(key=f"act_dash_{v['id']}"):
                common.html_block(
                    f'<div class="vrow"><span class="plate">{html.escape(v["identifier"])}</span>'
                    f'<span class="co">{html.escape((v.get("company") or {}).get("name", ""))}</span>'
                    f'{common.status_html(v.get("status"))}</div>'
                    f'<div class="act-s">{html.escape(sub or logic.NOT_GIVEN)}</div>'
                )
                st.button(f"{v['identifier']} · түүх", key=f"dash_open_{v['id']}", width="stretch",
                          on_click=open_history, args=(v["id"],))
    if len(vehicles) > PHONE_CARDS_MAX:
        common.html_block(f'<span class="muted">Эхний {PHONE_CARDS_MAX} машин. Хайлтаа нарийсгана уу.</span>')


def history_panel(vehicle_id: int) -> None:
    """The selected truck's every service, newest first."""
    try:
        card = api_client.get_vehicle(vehicle_id)
    except api_client.ApiError as exc:
        common.show_api_error(exc)
        return
    with st.container(key="card_dash_history"):
        with st.container(horizontal=True, vertical_alignment="center", key="dash_hist_top"):
            common.plate_box(card["identifier"], common.segment_chip_html(card.get("segment"), card.get("service_count")))
            st.button("Хаах", key="dash_close", type="tertiary", on_click=open_history, args=(None,))
        facts = [(card.get("company") or {}).get("name"), card.get("vehicle_model")]
        common.html_block(f'<div class="line">{html.escape(" · ".join(f for f in facts if f))}</div>')
        history = card.get("history") or []
        if not history:
            common.html_block('<span class="muted">Түүх алга.</span>')
            return
        # 6 values in 4 cells so the panel fits beside the table: «Тос» = grade · liters,
        # «Жолооч» = name with the phone under it.
        head = "".join(f"<th>{c}</th>" for c in ("Огноо", "Гүйлт", "Тос", "Жолооч"))
        body = "".join(
            f'<tr><td data-l="Огноо" class="n">{html.escape(day)}</td>'
            f'<td data-l="Гүйлт" class="n">{html.escape(meter)}</td>'
            f'<td data-l="Тос">{html.escape(oil)} · {html.escape(liters)}</td>'
            f'<td data-l="Жолооч">{html.escape(driver)}<div class="ph">{html.escape(phone)}</div></td></tr>'
            for day, meter, oil, liters, driver, phone in logic.history_table_rows(history)
        )
        common.html_block(f'<div class="hist-wrap"><table class="hist"><thead><tr>{head}</tr></thead>'
                          f'<tbody>{body}</tbody></table></div>')


def due_list() -> None:
    """Read-only copy of today's due reminders (send / mark sent stays on «Сануулга»)."""
    try:
        due = api_client.reminders_due()
    except api_client.ApiError as exc:
        if exc.status == 503:
            st.info("Таамаглалын загвар ачаалагдаагүй — сануулгын жагсаалт гарахгүй.")
        else:
            common.show_api_error(exc)
        return
    reminders = due.get("reminders") or []
    common.section(f"Сануулах машин ({len(reminders)})", right=due.get("as_of", ""))
    with st.container(key="card_dash_due"):
        if not reminders:
            common.html_block('<span class="muted">Өнөөдөр сануулах машин алга.</span>')
            return
        rows = []
        for i, r in enumerate(reminders):
            fg, bg = logic.STATUS_COLORS.get(r.get("status"), logic.PENDING_COLORS)
            label = logic.SEGMENT_LABELS["at_risk"] if logic.is_at_risk(r) else \
                logic.PREDICTION_STATUS_LABELS.get(r.get("status"), r.get("status") or "")
            meta = " · ".join(t.replace(" ", " ") for t in
                              (logic.days_left_text(r.get("days_left")), logic.phone_text(r.get("phone")) or "утасгүй"))
            rows.append(
                f'<div class="rem{"" if i == 0 else " sep"}"><span class="plate">{html.escape(r["identifier"])}</span>'
                f'<div class="who"><div class="n">{html.escape(r.get("company") or r.get("driver_name") or "—")}</div>'
                f'<div class="m">{html.escape(meta)}</div></div>'
                f'<span class="pill-st" style="color:{fg};background:{bg}">{html.escape(label)}</span></div>'
            )
        common.html_block(f'<div class="dash-due">{"".join(rows)}</div>')


common.header("Хяналтын самбар", back=common.HOME_PAGE)  # 8.1: opened from home
common.html_block(WIDE_CSS)

st.subheader("Сегмент")
segment_tiles()

st.subheader("Машин хайх")
search_form()
query = (st.session_state.get(DASH_QUERY) or "").strip()
try:
    found = api_client.search_vehicles(query, limit=SEARCH_LIMIT)
except api_client.ApiError as exc:
    found = None
    common.show_api_error(exc)

if found is not None:
    vehicles = found.get("vehicles") or []
    hint = " · машин дээр дарж бүх түүхийг харна" if vehicles else ""
    common.html_block(f'<span class="muted">{html.escape(logic.search_summary(query, found.get("total", 0), len(vehicles)) + hint)}</span>')
    selected = st.session_state.get(DASH_VEHICLE)
    # Nothing selected -> the table gets the whole width; selected -> table 2/3 + history 1/3 (computer).
    with st.container(horizontal=True, key="dash_split"):
        with st.container(key="dash_list"):
            if not vehicles:
                with st.container(key="card_dash_none"):
                    common.html_block('<span class="muted">Олдсонгүй.</span>')
            else:
                results_table(vehicles, query)
                results_cards(vehicles)
        if selected is not None:
            with st.container(key="dash_hist"):
                history_panel(selected)

due_list()

common.logout_button()
