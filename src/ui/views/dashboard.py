"""«Хяналтын самбар» (8.1; was «Тойм») — manager overview, view only (tasks 5.4, 9.1, 9.12).

9.12 (approved plan + mockup docs/design/9.12/): top to bottom
- «Ажил»: Өнөөдөр / Энэ 7 хоног / Энэ сар (default Өнөөдөр) + 4 KPI tiles from GET /stats/period
  (2×2 on a phone, 4 across on a computer).
- «Машинууд»: 4 segment cards (Бүгд · Байнгын · Шинэ · Эргэж ирээгүй). A tap filters the table
  (?segment=, the same value as the «Сегмент» filter, where «Давтан» also is); the picked card has
  a blue outline. Under «Бүгд»: how many came twice.
- Computer layout from 768 px (was 1024). The truck's history opens BELOW the list at every width and
  is scrolled into view; 768-1180 px the table scrolls sideways inside its own box, never the page.
- One spacing scale 4/8/12/16/24/32; cards 16 px padding on a phone, 24 on a computer; «Хайх» and
  the search field both 48 px, bottom-aligned.

9.1: the only screen that uses a computer's full width (≥ 768 px since 9.12); every other screen keeps
the 480 px phone column (common.CSS). Below 768 px this screen is one column too.
- Search the database: any part of a plate, fleet number, company or driver phone
  (GET /vehicles/search, blank = every truck, newest service first). Results: a table on a
  computer (click a row), tappable cards on a phone.
- 9.5a: target km of the next change (odometer at the last change + OIL_INTERVAL_KM, from the API)
  instead of the prediction status: a table column, the phone cards' second line, a history column
  and an Excel column. Mine trucks (engine hours only) have none («—» / empty cell).
- Selected truck: every service (date, odometer, target, oil, liters, driver, phone) from GET /vehicles/{id},
  below the list («Хаах» closes it).
- Filters (step 2): date range, company, route, oil grade, sent with the search. «Excel татах»
  downloads one row per matching service (src/ui/export.py, built in memory, nothing stored).
- Due list from GET /reminders/due, read only (sending stays on «Сануулга»).
- 9.6b-5 (Artlab payments, only once payments are connected — before that the screen is exactly as
  in 9.5c): «Сүүлд шинэчилсэн HH:MM» (red if the last run failed or is older than 2 h), the
  «Төлөөгүй» list (total, days waiting, receipt phone + «Залгах»), a «Төлбөр» filter, and a payment
  pill on each service in the history. Phones of the unpaid list are on screen only, never in Excel.
Nothing here writes to the API.
"""

import html
from datetime import date, datetime
from functools import partial

import streamlit as st

from src.ui import api_client, common, export, logic

DASH_QUERY = "dash_q"          # search text (form field)
DASH_OPTIONS = "dash_options"  # last filter choices from the API (companies, oil grades)
FILTER_WIDGETS = {name: f"dash_f_{name}" for name in logic.FILTER_KEYS}  # API param -> widget key
DASH_VEHICLE = "dash_vid"      # truck whose history is open
DASH_IDS = "dash_ids"          # vehicle ids in table order (the table selection gives a row number)
DASH_PERIOD = "dash_period"    # «Ажил» switch: today | week | month (GET /stats/period)
DASH_SCROLL = "dash_scroll"    # True -> scroll the just-opened history into view on this run
DASH_SCROLLS = "dash_scrolls"  # counter: makes each scroll script new, so the browser runs it again
SEGMENT_KEY = FILTER_WIDGETS["segment"]  # a card tap writes the «Сегмент» filter widget
TABLE_KEY = "dash_table"
WIDE_PX = 768                  # computer layout from this viewport width (9.12; was 1024)
PHONE_CARDS_MAX = 50           # tappable rows on a phone; the table shows up to the API limit
SEARCH_LIMIT = 1000            # API maximum: the table and the Excel file hold the whole filtered list
ROW_PX = 35                    # table row (and header) height, so the table is exactly as tall as its rows

# Screen-only CSS: it is part of this page's output, so it disappears when another screen opens.
# 9.12 spacing scale: 4 / 8 / 12 / 16 / 24 / 32 only. Cards: 16 px padding on a phone, 24 on a computer.
WIDE_CSS = f"""
<style>
.block-container {{padding: 12px 16px 32px !important; --card-pad: 16px;}}
/* section title: flush with the cards' outer edge, 24 px above (12 + the 12 px gap), 12 px to its content */
.block-container [data-testid="stElementContainer"]:has(> .stHeading h3) {{margin: 12px 0 0 0;}}
.block-container [class*="st-key-card_"] {{padding: var(--card-pad); margin-top: 0;}}
.block-container [class*="st-key-grp_"] {{margin-top: 0;}}
.st-key-grp_dash_cards [class*="st-key-act_"] {{padding: 16px var(--card-pad);}}
/* «Ажил»: period switch = segmented control (grey track, picked one white), full width on a phone */
.st-key-dash_period, .st-key-dash_period [data-testid="stButtonGroup"], .st-key-dash_period div:has(> button) {{width: 100% !important; max-width: none !important;}}
.st-key-dash_period div:has(> button) {{display: flex; background: #E9ECF1; border-radius: 12px; padding: 4px; gap: 4px !important;}}
.st-key-dash_period button {{flex: 1 1 0; min-width: 0; min-height: 40px; padding: 4px 8px !important; border-radius: 8px !important;
  background: transparent !important; color: var(--muted) !important; border: none !important;}}
.st-key-dash_period button[aria-checked="true"] {{background: #fff !important; color: var(--ink) !important; box-shadow: 0 1px 2px rgba(16,24,40,.08);}}
.st-key-dash_period button p {{font-size: 14px !important; font-weight: 500; white-space: nowrap;}}
@media (min-width: {WIDE_PX}px) {{
  .block-container {{max-width: 1360px !important; padding: 24px 32px 32px !important;}}
  .block-container {{--card-pad: 24px;}}
  .tiles.kpi, .st-key-dash_segs {{grid-template-columns: repeat(4, minmax(0, 1fr)) !important;}}
  .st-key-grp_dash_cards, [data-testid="stLayoutWrapper"]:has(> .st-key-grp_dash_cards) {{display: none !important;}}
  /* computer: the switch is as wide as its 3 words, not the whole page */
  .st-key-dash_period [data-testid="stButtonGroup"] {{width: auto !important;}}
  .st-key-dash_period div:has(> button) {{display: inline-flex; width: auto !important;}}
  .st-key-dash_period button {{flex: none; padding: 4px 24px !important;}}
}}
@media (max-width: {WIDE_PX - 0.02}px) {{
  /* 9.12-3: the example placeholder fits the ~206 px phone field only at 14 px; typed text stays 16 px
     (iOS zooms on focus by the input's own size, not the placeholder's) */
  .st-key-card_dash_search input::placeholder {{font-size: 14px;}}
  .st-key-dash_table_wrap, [data-testid="stLayoutWrapper"]:has(> .st-key-dash_table_wrap) {{display: none !important;}}
}}
/* KPI tiles + segment cards: 2×2 on a phone, 4 across on a computer, 12 px apart */
.tiles.kpi {{grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 0;}}
.tiles.kpi > div {{padding: var(--card-pad);}}
.tiles.kpi .v small {{font-size: 15px; font-weight: 500; color: var(--muted); margin-left: 4px;}}
.st-key-dash_segs {{display: grid !important; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px !important;}}
.st-key-dash_segs [class*="st-key-act_seg_"] {{margin: 0; padding: var(--card-pad); height: 100%;}}
.st-key-dash_segs [data-testid="stLayoutWrapper"] {{min-width: 0; width: auto !important;}}
.segc .v {{font-size: 26px; font-weight: 600; line-height: 1.2;}}
.segc .k {{display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 500; margin-top: 4px;}}
.segc .d {{font-size: 13px; color: var(--muted); margin-top: 4px;}}
/* search: field and «Хайх» both 48 px, bottom edges in line; «Шүүлтүүр» starts at the field's left edge */
.st-key-card_dash_search [data-baseweb="input"], .st-key-card_dash_search [data-testid="stTextInputRootElement"] {{
  min-height: 48px !important; height: 48px !important; box-sizing: border-box;}}
.st-key-card_dash_search .stFormSubmitButton button {{min-height: 48px !important; height: 48px; border-radius: 12px; padding: 0 24px;}}
/* the field and «Хайх» stay in ONE row on a phone too (Streamlit stacks columns below 640 px) */
.st-key-dash_search_row [data-testid="stHorizontalBlock"] {{flex-wrap: nowrap !important; gap: 12px !important;}}
.st-key-dash_search_row [data-testid="stColumn"]:first-child {{flex: 1 1 auto !important; width: auto !important; min-width: 0 !important;}}
.st-key-dash_search_row [data-testid="stColumn"]:last-child {{flex: none !important; width: auto !important; min-width: 0 !important;}}
/* the hidden expander icon still kept a 15 px slot + gap: drop it, so «Шүүлтүүр» starts at the field's edge */
.st-key-card_dash_search [data-testid="stExpander"] summary > span > span:has([data-testid="stIconMaterial"]) {{display: none;}}
/* history below the list: no table inside a table's box; scrolled to with 16 px air above it */
.st-key-card_dash_history {{scroll-margin-top: 16px;}}
/* the scroll script's box is 0 px tall but would still take a 12 px gap (it has already run) */
[data-testid="stElementContainer"]:has(script) {{display: none;}}
/* no table toolbar (CSV download, search, fullscreen): export only via the Excel button (9.1 step 2) */
.st-key-dash_table_wrap [data-testid="stElementToolbar"] {{display: none !important;}}
/* history: a table on a computer, one small card per service on a phone */
.hist-wrap {{overflow-x: auto;}}  /* a narrow history panel scrolls sideways inside its card */
.hist {{width: 100%; border-collapse: collapse; font-size: 13px;}}
.hist th {{text-align: left; font-size: 12px; color: var(--muted); font-weight: 600; padding: 0 12px 8px 0;
  border-bottom: 1px solid var(--line); white-space: nowrap;}}
.hist td {{padding: 10px 12px 10px 0; border-bottom: 1px solid var(--line); vertical-align: top;}}
/* 9.5a: numbers, dates and the phone stay on one line; oil and driver name may wrap, so the whole
   phone is visible in the narrow panel beside the table */
.hist td.n, .hist .ph {{white-space: nowrap;}}
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
.st-key-dash_summary {{justify-content: space-between; flex-wrap: wrap; gap: 8px !important;}}
.st-key-dash_excel button {{min-height: 40px; border-radius: 12px;}}
.st-key-dash_excel button p {{font-size: 14px;}}
.dash-due {{display: grid; grid-template-columns: minmax(0, 1fr); gap: 0;}}
.dash-due .rem .who {{min-width: 0;}}  /* long company names wrap; the status pill keeps its size */
.dash-due .pill-st {{flex: none;}}
@media (max-width: {WIDE_PX - 0.02}px) {{  /* phone: pill under the text, so words never break mid-word */
  .dash-due .rem {{display: grid; grid-template-columns: auto minmax(0, 1fr); column-gap: 12px; row-gap: 6px;}}
  .dash-due .pill-st {{grid-column: 2; justify-self: start;}}
}}
.st-key-dash_hist_top {{flex-wrap: nowrap !important; justify-content: space-between;}}
/* 9.6b-5: payments */
.sync {{font-size: 13px; color: var(--muted);}} .sync.red {{color: #B42318; font-weight: 500;}}
.unpaid-sum {{font-size: 15px;}} .unpaid-sum b {{font-weight: 600;}}
/* one stacked block per receipt (phone first): plate + amount, who + how long, «Залгах» */
.unpaid .pay {{padding: 0;}} .unpaid .pay.sep {{border-top: 1px solid var(--line); padding-top: 16px; margin-top: 16px;}}
.unpaid .top {{display: flex; align-items: center; justify-content: space-between; gap: 12px;}}
.unpaid .noplate {{font-size: 15px; font-weight: 500; color: var(--muted);}}
.unpaid .amt {{font-size: 16px; font-weight: 600; white-space: nowrap; font-variant-numeric: tabular-nums;}}
.unpaid .n {{font-size: 15px; margin-top: 8px;}} .unpaid .m {{font-size: 13px; color: var(--muted); margin-top: 2px;}}
.unpaid .call {{display: inline-flex; align-items: center; justify-content: center; min-height: 44px; margin-top: 10px;
  padding: 0 20px; border-radius: 12px; background: var(--fill); color: var(--ink) !important; text-decoration: none;
  font-size: 15px; font-weight: 500; white-space: nowrap; touch-action: manipulation;}}
.st-key-dash_hist_top > [data-testid="stElementContainer"]:first-child {{flex: 1 1 auto; min-width: 0; width: auto !important;}}
</style>
"""


def on_table_select(key: str) -> None:
    """Table clicked (any cell of a row, or its row marker): open that truck's history
    (row number -> id of the table just shown). Nothing picked any more -> the history closes."""
    selection = st.session_state[key].selection
    row = logic.picked_row(selection.rows, selection.cells)
    ids = st.session_state.get(DASH_IDS, [])
    open_history(ids[row] if row is not None and row < len(ids) else None)


def open_history(vehicle_id: int | None) -> None:
    st.session_state[DASH_VEHICLE] = vehicle_id
    st.session_state[DASH_SCROLL] = vehicle_id is not None  # the panel opens below the list: bring it into view


def pick_segment(segment: str | None) -> None:
    """Segment card tapped: the table shows that segment (None = «Бүгд»); an open history closes,
    its truck may not be in the new list."""
    st.session_state[SEGMENT_KEY] = segment
    st.session_state[DASH_VEHICLE] = None


def period_section() -> None:
    """«Ажил»: Өнөөдөр / Энэ 7 хоног / Энэ сар + services, first-ever trucks, liters, reminders sent."""
    period = st.segmented_control("Хугацаа", list(logic.PERIOD_LABELS), format_func=logic.PERIOD_LABELS.get,
                                  default="today", required=True, key=DASH_PERIOD, label_visibility="collapsed")
    try:
        stats = api_client.period_stats(period or "today")
    except api_client.ApiError as exc:
        common.show_api_error(exc)
        return
    tiles = "".join(
        f'<div><div class="v">{html.escape(value)}{f"<small>{unit}</small>" if unit else ""}</div>'
        f'<div class="k">{html.escape(label)}</div></div>'
        for value, unit, label in logic.period_tiles(stats)
    )
    common.html_block(f'<div class="tiles kpi">{tiles}</div>')
    common.html_block(f'<span class="muted">{html.escape(logic.period_range_text(stats))}</span>')


def segment_cards() -> None:
    """«Машинууд»: 4 tappable cards; the picked one (None = «Бүгд») has a blue outline."""
    try:
        stats = api_client.segment_stats()
    except api_client.ApiError as exc:
        common.show_api_error(exc)
        return
    picked = st.session_state.get(SEGMENT_KEY)
    with st.container(key="dash_segs"):
        for card in logic.segment_cards(stats):
            name = card["segment"] or "all"
            with st.container(key=f"act_seg_{name}"):
                common.html_block(
                    f'<div class="segc"><div class="v">{card["count"]}</div>'
                    f'<div class="k">{common.segment_mark_html(card["segment"])}{html.escape(card["label"])}</div>'
                    f'<div class="d">{html.escape(card["hint"])}</div></div>')
                # the label is what a screen reader says: count, and whether this card is the one shown
                chosen = " · сонгосон" if card["segment"] == picked else ""
                st.button(f'{card["label"]} · {card["count"]}{chosen}', key=f"dash_seg_{name}", width="stretch",
                          on_click=pick_segment, args=(card["segment"],))
    if picked in logic.SEGMENT_CARDS:  # «Давтан» (filter only) outlines no card
        common.html_block(f'<style>.st-key-act_seg_{picked or "all"} {{outline: 2px solid var(--pri); '
                          f'outline-offset: -2px;}}</style>')
    common.html_block(f'<span class="muted">Дарж хүснэгтийг шүүнэ · {html.escape(stats.get("as_of", ""))}</span>')


def scroll_to_history() -> None:
    """Bring the history panel (below the list) into view once, right after a truck was picked.
    A new counter in the script each time: the browser runs a changed script again."""
    n = st.session_state[DASH_SCROLLS] = st.session_state.get(DASH_SCROLLS, 0) + 1
    st.html(f"""<script>/* {n} */
(() => {{
  const smooth = !matchMedia('(prefers-reduced-motion: reduce)').matches;
  let tries = 0;
  const go = () => {{
    const panel = document.querySelector('.st-key-card_dash_history');
    if (panel) panel.scrollIntoView({{behavior: smooth ? 'smooth' : 'auto', block: 'start'}});
    else if (tries++ < 40) setTimeout(go, 50);
  }};
  go();
}})();
</script>""", unsafe_allow_javascript=True)


def load_sync_view() -> dict | None:
    """«Сүүлд шинэчилсэн» view, or None = payments not connected (or the call failed): then every
    payment element stays hidden and the dashboard looks exactly as before 9.6b-5."""
    try:
        return logic.sync_view(api_client.payments_sync_status(), datetime.now(logic.UB))
    except api_client.ApiError:
        return None


def payments_section(sync: dict) -> None:
    """«Төлбөр»: freshness line + «Төлөөгүй» list, oldest receipt first (view only)."""
    st.subheader("Төлбөр")
    common.html_block(f'<span class="sync{" red" if sync["red"] else ""}">{html.escape(sync["text"])}</span>')
    try:
        unpaid = api_client.payments_unpaid()
    except api_client.ApiError as exc:
        common.show_api_error(exc)
        return
    rows = logic.unpaid_rows(unpaid.get("items") or [])
    with st.container(key="card_dash_unpaid"):
        common.html_block(f'<div class="unpaid-sum">Төлөөгүй ({unpaid.get("total", 0)}) · '
                          f'нийт <b>{html.escape(logic.money_text(unpaid.get("total_due", 0)))}</b></div>')
        if not rows:
            common.html_block('<span class="muted">Төлөөгүй баримт алга.</span>')
            return
        items = []
        for i, r in enumerate(rows):
            call = f'<a class="call" href="{html.escape(r["tel"])}">Залгах</a>' if r["tel"] else ""
            meta = " · ".join(p for p in (r["waiting"], r["date"], r["phone"]) if p)
            title_cls = "plate" if r["has_plate"] else "noplate"  # «Дугааргүй баримт» is text, not a plate
            items.append(
                f'<div class="pay{"" if i == 0 else " sep"}"><div class="top">'
                f'<span class="{title_cls}">{html.escape(r["title"])}</span>'
                f'<span class="amt">{html.escape(r["amount"])}</span></div>'
                f'<div class="n">{html.escape(r["who"])}</div><div class="m">{html.escape(meta)}</div>{call}</div>'
            )
        common.html_block(f'<div class="unpaid">{"".join(items)}</div>')
        if unpaid.get("total", 0) > len(rows):
            common.html_block(f'<span class="muted">Эхний {len(rows)} баримт.</span>')


def current_filters(payments_on: bool = False) -> dict:
    """Filter values as the API wants them (None = not used), from the form's widgets.
    The payment filter only counts while payments are connected (its widget is shown)."""
    values = {name: st.session_state.get(key) for name, key in FILTER_WIDGETS.items()}
    if not payments_on:
        values["payment_status"] = None
    return values


def clear_filters() -> None:
    for key in FILTER_WIDGETS.values():
        st.session_state[key] = None


def search_form(options: dict, active: int, payments_on: bool = False, expand: bool = False) -> None:
    """Search field + «Хайх»; filters in «Шүүлтүүр» (open while ``expand``). One submit applies all.
    «Төлбөр» (9.6b-5) only while payments are connected. «Сегмент» (9.12) is also set by a card tap."""
    companies = {c["id"]: c["name"] for c in options.get("companies") or []}
    with st.container(key="card_dash_search"):
        with st.form("dash_search_form", border=False):  # Enter in the field searches too
            with st.container(key="dash_search_row"):  # CSS keeps this row unwrapped on a phone
                cols = st.columns([4, 1], vertical_alignment="bottom")
            cols[0].text_input("Улсын дугаар, утас эсвэл компани", key=DASH_QUERY,
                               placeholder="1234 УБА · 9911 · Говь Тээвэр")  # 9.12-3: an example of each kind
            cols[1].form_submit_button("Хайх", type="primary", width="stretch")
            with st.expander(f"Шүүлтүүр ({active})" if active else "Шүүлтүүр", expanded=expand):
                f = [*st.columns(4), *st.columns(4)]  # two rows: 4 fields each fit from 768 px
                f[0].date_input("Хэднээс", key=FILTER_WIDGETS["date_from"], value=None, format="YYYY-MM-DD")
                f[1].date_input("Хэдийг хүртэл", key=FILTER_WIDGETS["date_to"], value=None, format="YYYY-MM-DD")
                f[2].selectbox("Компани", list(companies), key=FILTER_WIDGETS["company_id"], index=None,
                               format_func=lambda cid: companies.get(cid, str(cid)), placeholder="Бүгд")
                f[3].selectbox("Маршрут", list(logic.ROUTE_LABELS), key=FILTER_WIDGETS["route"], index=None,
                               format_func=logic.route_label, placeholder="Бүгд")
                f[4].selectbox("Тос", options.get("oil_grades") or [], key=FILTER_WIDGETS["oil_grade"], index=None,
                               placeholder="Бүгд")
                f[5].selectbox("Сегмент", list(logic.SEGMENT_ORDER), key=SEGMENT_KEY, index=None,
                               format_func=logic.segment_label, placeholder="Бүгд")
                if payments_on:
                    f[6].selectbox("Төлбөр", list(logic.PAYMENT_LABELS), key=FILTER_WIDGETS["payment_status"],
                                   index=None, format_func=logic.PAYMENT_LABELS.get, placeholder="Бүгд")
                common.html_block('<span class="muted">Огноо, маршрут, тос нэг үйлчилгээнд хамт таарах ёстой. '
                                  'Мөрөнд машины хамгийн сүүлийн үйлчилгээ харагдана.</span>')
    if active:
        st.button("Шүүлтүүр арилгах", key="dash_clear", type="tertiary", on_click=clear_filters,
                  icon=":material/close:")


def results_table(vehicles: list[dict], search_key: str) -> None:
    """Computer view: sortable table; a click anywhere in a row opens the history (no editing).

    The widget key includes the query + filters, so a new search starts with no row highlighted
    (a kept selection would point at a row number of the OLD results)."""
    st.session_state[DASH_IDS] = [v["id"] for v in vehicles]
    key = f"{TABLE_KEY}:{search_key}"
    with st.container(key="dash_table_wrap"):
        st.dataframe(
            logic.search_table_rows(vehicles), key=key, on_select=partial(on_table_select, key),  # no args= here
            # 9.12-3: "single-cell" too, so a click on ANY cell reports its row (not only the row marker)
            selection_mode=["single-row", "single-cell"], hide_index=True, width="stretch", row_height=ROW_PX,
            height=min(ROW_PX * (len(vehicles) + 1) + 3, 16 * ROW_PX),  # header + rows; scrolls after 15 rows
            placeholder=logic.NOT_GIVEN,  # 9.5a: an empty cell shows «—», not "None" (mine trucks have no km)
            column_config={
                "Гүйлт (км)": st.column_config.NumberColumn(format="localized"),
                logic.TARGET_COLUMN: st.column_config.NumberColumn(format="localized"),
                "Литр": st.column_config.NumberColumn(format="%.1f"),
            },
        )


def results_cards(vehicles: list[dict]) -> None:
    """Phone view: one tappable row per truck (plate · company, then target km · last service)."""
    with st.container(key="grp_dash_cards"):
        for v in vehicles[:PHONE_CARDS_MAX]:
            last = v.get("last_service") or {}
            target = f"Дараагийн: {logic.target_text(last)}" if last.get("target_km") is not None else None
            sub = " · ".join(p for p in (target, last.get("service_date"), logic.driver_text(
                last.get("driver_name"), last.get("driver_phone"))) if p and p != logic.NOT_GIVEN)
            with st.container(key=f"act_dash_{v['id']}"):
                common.html_block(
                    f'<div class="vrow"><span class="plate">{html.escape(v["identifier"])}</span>'
                    f'<span class="co">{html.escape((v.get("company") or {}).get("name", ""))}</span></div>'
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
        # 7 values in 4 cells so the panel fits beside the table: «Гүйлт» = odometer with the target
        # under it (9.5a), «Тос» = grade · liters, «Жолооч» = name with the phone under it.
        head = "".join(f"<th>{c}</th>" for c in ("Огноо", "Гүйлт → дараагийн", "Тос", "Жолооч"))
        body = "".join(
            f'<tr><td data-l="Огноо" class="n">{html.escape(day)}{common.payment_pill_html(service)}</td>'
            f'<td data-l="Гүйлт → дараагийн" class="n">{html.escape(meter)}'
            f'{"" if target == logic.NOT_GIVEN else f"<div class=ph>→ {html.escape(target)}</div>"}</td>'
            f'<td data-l="Тос">{html.escape(oil)} · {html.escape(liters)}</td>'
            f'<td data-l="Жолооч">{html.escape(driver)}<div class="ph">{html.escape(phone)}</div></td></tr>'
            for service, (day, meter, target, oil, liters, driver, phone)
            in zip(history, logic.history_table_rows(history))
        )
        common.html_block(f'<div class="hist-wrap"><table class="hist"><thead><tr>{head}</tr></thead>'
                          f'<tbody>{body}</tbody></table></div>')


def due_list() -> None:
    """Read-only copy of today's due reminders (send / mark sent stays on «Сануулга»)."""
    try:
        due = api_client.reminders_due()
    except api_client.ApiError as exc:
        common.show_api_error(exc)
        return
    reminders = due.get("reminders") or []
    common.section(f"Сануулах машин ({len(reminders)})", right=due.get("as_of", ""))
    with st.container(key="card_dash_due"):
        if not reminders:
            common.html_block('<span class="muted">Өнөөдөр сануулах машин алга.</span>')
            return
        rows = []
        for i, r in enumerate(reminders):  # 9.5c: «Сануулах» / «Эргэж ирээгүй» pill, days since the latest change
            label, fg, bg = logic.reminder_pill(r)
            meta = " · ".join(t.replace(" ", " ") for t in
                              (logic.days_since_text(r.get("days_since")), logic.phone_text(r.get("phone")) or "утасгүй"))
            rows.append(
                f'<div class="rem{"" if i == 0 else " sep"}"><span class="plate">{html.escape(r["identifier"])}</span>'
                f'<div class="who"><div class="n">{html.escape(r.get("company") or r.get("driver_name") or "—")}</div>'
                f'<div class="m">{html.escape(meta)}</div></div>'
                f'<span class="pill-st" style="color:{fg};background:{bg}">{html.escape(label)}</span></div>'
            )
        common.html_block(f'<div class="dash-due">{"".join(rows)}</div>')


common.header("Хяналтын самбар", back=common.HOME_PAGE)  # 8.1: opened from home
common.html_block(WIDE_CSS)

st.subheader("Ажил")
period_section()

st.subheader("Машинууд")
segment_cards()

sync = load_sync_view()  # 9.6b-5: None -> no payment element anywhere on this screen
if sync is not None:
    payments_section(sync)

st.subheader("Машин хайх")
# Search BEFORE drawing the form: the form's values are already in session_state (last submit),
# and the answer brings the filter choices (companies, oil grades) the form needs.
query = (st.session_state.get(DASH_QUERY) or "").strip()
filters = current_filters(payments_on=sync is not None)
problems = logic.filter_errors(filters)
found, error = None, None
if not problems:
    try:
        # with_services: the Excel file has one row per matching service (the screen stays per truck)
        found = api_client.search_vehicles(query, limit=SEARCH_LIMIT, filters=filters, with_services=True)
    except api_client.ApiError as exc:
        error = exc
# «Шүүлтүүр» opens for the filters inside it; a segment picked by a card tap keeps it closed
# (only «Давтан», which has no card, opens it).
in_panel = {k: v for k, v in filters.items() if k != "segment" or v not in logic.SEGMENT_CARDS}
search_form((found or {}).get("options") or st.session_state.get(DASH_OPTIONS) or {},
            logic.active_filter_count(filters), payments_on=sync is not None,
            expand=logic.active_filter_count(in_panel) > 0)
if found is not None:
    st.session_state[DASH_OPTIONS] = found.get("options")  # keeps the lists while a filter is invalid
for message in problems:
    st.warning(message)
if error is not None:
    common.show_api_error(error)

if found is not None:
    vehicles = found.get("vehicles") or []
    hint = " · машин дээр дарж бүх түүхийг харна" if vehicles else ""
    with st.container(horizontal=True, vertical_alignment="center", key="dash_summary"):
        summary = logic.search_summary(query, found.get("total", 0), len(vehicles),
                                       filtered=logic.active_filter_count(filters) > 0)
        common.html_block(f'<span class="muted">{html.escape(summary + hint)}</span>')
        if vehicles:
            names = {c["id"]: c["name"] for c in (found.get("options") or {}).get("companies") or []}
            today = date.today()
            st.download_button(
                "Excel татах", export.search_workbook(vehicles, today, logic.filters_text(query, filters, names)),
                file_name=export.file_name(today), key="dash_excel", on_click="ignore", icon=":material/download:",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    selected = st.session_state.get(DASH_VEHICLE)
    # 9.12: the list always gets the whole width; the picked truck's history opens below it, at every
    # width (beside the table it clipped both), and is scrolled into view.
    with st.container(key="dash_list"):
        if not vehicles:
            with st.container(key="card_dash_none"):
                common.html_block('<span class="muted">Олдсонгүй.</span>')
        else:
            results_table(vehicles, f"{query}|{sorted(filters.items(), key=lambda kv: kv[0])}")
            results_cards(vehicles)
    if selected is not None:
        history_panel(selected)
        if st.session_state.pop(DASH_SCROLL, False):
            scroll_to_history()

due_list()

common.logout_button()
