# Backlog (not scheduled)

Small items the PM asked to record without fixing yet. The PM may move them into
PROJECT_STATE §9 «Later list».

- **Dashboard table: open a truck by clicking anywhere in its row** (from 9.12-2 review, 2026-11-02).
  Today, on a computer (≥ 768 px), the truck's history opens only when the row's selection
  marker (the box at the left end of the row) is clicked; a click on any other cell selects that
  cell and opens nothing. Expected: a click anywhere in the row opens the history below the table.
  Code: `src/ui/views/dashboard.py` (`results_table`, `on_table_select`; `st.dataframe` with
  `selection_mode="single-row"`). Browser check to update: `tests/test_ui_browser.py`
  (`test_dashboard_history_below_list_and_in_view` clicks the marker).
