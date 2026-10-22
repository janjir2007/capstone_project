"""«Хяналтын самбар» (8.1; was «Тойм») — manager overview (task 5.4, DESIGN v5 / T9): segment counts from GET /stats/segments
as 2×2 tiles (colored dot + word + number), total and as_of. Opened from «Сануулга»."""

import streamlit as st

from src.ui import api_client, common, logic

common.header("Хяналтын самбар", back=common.HOME_PAGE)  # 8.1: opened from home

st.subheader("Сегмент")
try:
    stats = api_client.segment_stats()
except api_client.ApiError as exc:
    common.show_api_error(exc)
else:
    counts = stats.get("counts") or {}
    tiles = "".join(
        f'<div><div class="v">{counts.get(s, 0)}</div><div class="k"><i class="dot" '
        f'style="background:{logic.SEGMENT_DOTS[s]}"></i>{logic.SEGMENT_LABELS[s]}</div></div>'
        for s in logic.SEGMENT_ORDER
    )
    common.html_block(f'<div class="tiles two">{tiles}</div>')
    common.html_block(f'<span class="muted">Нийт {stats.get("total", 0)} машин · {stats.get("as_of", "")}</span>')

common.logout_button()
