"""
URS MVP - Project Overview (Landing Page)
Main entry point for the Streamlit application.
"""
import streamlit as st
import pandas as pd
from pathlib import Path
import sys

# Add app_core to path
sys.path.insert(0, str(Path(__file__).parent))

from app_core.data_io import (
    load_table, get_main_assets, get_asset_phase,
)
from app_core.models import Tables, Phase
from app_core.policy import set_phase_gates_enabled
from app_core.style import apply_global_style

# Page config
st.set_page_config(
    page_title="URS MVP",
    page_icon="URS",
    layout="wide",
    initial_sidebar_state="expanded"
)
apply_global_style()

# Initialize session state
if "selected_asset_id" not in st.session_state:
    st.session_state.selected_asset_id = None
if "phase_gates_enabled" not in st.session_state:
    st.session_state.phase_gates_enabled = False
if "overview_sort_col" not in st.session_state:
    st.session_state.overview_sort_col = None
if "overview_sort_asc" not in st.session_state:
    st.session_state.overview_sort_asc = True


def sync_policy_config() -> None:
    """Sync session state with policy config."""
    set_phase_gates_enabled(st.session_state.phase_gates_enabled)


# Sidebar - Settings
with st.sidebar:
    st.header("Settings")

    # Phase-gates toggle
    phase_gates = st.checkbox(
        "Enable Phase Gates",
        value=st.session_state.phase_gates_enabled,
        help="When enabled, edits outside the current phase are blocked"
    )
    if phase_gates != st.session_state.phase_gates_enabled:
        st.session_state.phase_gates_enabled = phase_gates
        sync_policy_config()

    st.divider()

# ── Title row with "Create new Project" button ──────────────────────────
st.markdown(
    """<style>
.overview-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.5rem;
}
.overview-title-row h1 {
  margin: 0;
  padding: 0;
}

</style>""",
    unsafe_allow_html=True,
)

title_left, title_right = st.columns([4, 1])
with title_left:
    st.title("Project Overview")
with title_right:
    st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)
    if st.button("Create new Project", type="primary"):
        st.switch_page("pages/00_URS_Composer_New.py")

st.markdown("Select a main asset and jump directly to the desired phase.")

# ── Data ─────────────────────────────────────────────────────────────────
main_assets = get_main_assets()
asset_media_all = load_table(Tables.ASSET_MEDIA)
media_catalog = load_table(Tables.MEDIA)

# Build media name lookup
media_names = {}
if not media_catalog.empty and "id" in media_catalog.columns and "name" in media_catalog.columns:
    media_names = dict(zip(media_catalog["id"], media_catalog["name"]))

PHASE_ORDER = [Phase.URS, Phase.RISK, Phase.DQ, Phase.XQ_PLAN, Phase.XQ_EXECUTION, Phase.DONE]

# Collect all unique media names for columns
MEDIA_COLS = sorted(set(media_names.values())) if media_names else []


def _phase_state(current_phase: Phase, column_phase: Phase) -> str:
    if current_phase == column_phase:
        return "edit"
    if PHASE_ORDER.index(current_phase) > PHASE_ORDER.index(column_phase):
        return "lock"
    return "empty"


def _render_action(col, state: str, key: str, page: str, asset_id: int) -> None:
    if state == "edit":
        if col.button("✏️", key=key, help="Edit", type="tertiary"):
            st.session_state.selected_asset_id = asset_id
            st.switch_page(page)
        return
    if state == "lock":
        if col.button("🔒", key=key, help="View (read-only)", type="tertiary"):
            st.session_state.selected_asset_id = asset_id
            st.switch_page(page)
        return
    col.write("")


if main_assets.empty:
    st.info("No main assets found.")
    st.stop()

# ── Build display dataframe (all sortable values pre-computed) ────────────
_rows = []
for _, asset in main_assets.iterrows():
    _aid = int(asset["id"])

    # Get location info via project
    _country = _site = _level = _location = "-"
    project_id = asset.get("project_id")
    if project_id and pd.notna(project_id):
        from app_core.data_io import get_location_display
        _location_str = get_location_display(int(project_id))
        if _location_str:
            _location = _location_str

    _media: dict = {}
    if not asset_media_all.empty and "asset_id" in asset_media_all.columns:
        for _, _mr in asset_media_all[asset_media_all["asset_id"] == _aid].iterrows():
            mid = _mr.get("media_id")
            mname = media_names.get(mid, str(mid))
            _media[mname] = str(_mr.get("media_value", "") or "")

    _row = {
        "asset_id": _aid,
        "name": str(asset.get("name", "")),
        "location": _location,
    }
    for _mc in MEDIA_COLS:
        _row[_mc] = _media.get(_mc, "-")
    _rows.append(_row)

display_df = pd.DataFrame(_rows) if _rows else pd.DataFrame()

# Apply sort
_sc = st.session_state.overview_sort_col
if not display_df.empty and _sc and _sc in display_df.columns:
    display_df = display_df.sort_values(
        _sc,
        ascending=st.session_state.overview_sort_asc,
        key=lambda s: s.str.lower() if s.dtype == object else s,
    ).reset_index(drop=True)


# ── Header row ────────────────────────────────────────────────────────────
base_cols = 8  # name, URS, RISK, DQ, xQ Plan, xQ Exec, location + at least 1 extra
COL_WIDTHS = [3, 1, 1, 1, 1, 1, 2] + [1] * len(MEDIA_COLS)


def _sort_header(col, label: str, sort_key: str) -> None:
    arrow = ""
    if st.session_state.overview_sort_col == sort_key:
        arrow = " ↑" if st.session_state.overview_sort_asc else " ↓"
    if col.button(f"{label}{arrow}", key=f"hdr_{sort_key}", use_container_width=True, type="tertiary"):
        if st.session_state.overview_sort_col == sort_key:
            st.session_state.overview_sort_asc = not st.session_state.overview_sort_asc
        else:
            st.session_state.overview_sort_col = sort_key
            st.session_state.overview_sort_asc = True
        st.rerun()


header_cols = st.columns(COL_WIDTHS, gap="small")
_sort_header(header_cols[0], "Main Asset", "name")
header_cols[1].markdown("**URS**")
header_cols[2].markdown("**RISK**")
header_cols[3].markdown("**DQ**")
header_cols[4].markdown("**xQ Plan**")
header_cols[5].markdown("**xQ Execution**")
_sort_header(header_cols[6], "Location", "location")
for _i, _mc in enumerate(MEDIA_COLS):
    _sort_header(header_cols[7 + _i], _mc, _mc)

# ── Data rows ─────────────────────────────────────────────────────────────
for _, row_data in display_df.iterrows():
    asset_id = int(row_data["asset_id"])
    phase = get_asset_phase(asset_id)

    row_cols = st.columns(COL_WIDTHS, gap="small")
    row_cols[0].write(row_data["name"])

    urs_state = _phase_state(phase, Phase.URS)
    risk_state = _phase_state(phase, Phase.RISK)
    dq_state = _phase_state(phase, Phase.DQ)
    xq_plan_state = _phase_state(phase, Phase.XQ_PLAN)
    xq_exec_state = _phase_state(phase, Phase.XQ_EXECUTION)

    _render_action(row_cols[1], urs_state, f"urs_{asset_id}", "pages/01_URS_Composer.py", asset_id)
    _render_action(row_cols[2], risk_state, f"risk_{asset_id}", "pages/02_Risk_Assessment.py", asset_id)
    _render_action(row_cols[3], dq_state, f"dq_{asset_id}", "pages/03_DQ.py", asset_id)
    _render_action(row_cols[4], xq_plan_state, f"xq_plan_{asset_id}", "pages/04_Qualification_Plan.py", asset_id)
    _render_action(row_cols[5], xq_exec_state, f"xq_exec_{asset_id}", "pages/05_Qualification_Execution.py", asset_id)

    row_cols[6].markdown(f"<div style='text-align:center'>{row_data['location']}</div>", unsafe_allow_html=True)

    for _i, _mc in enumerate(MEDIA_COLS):
        row_cols[7 + _i].markdown(f"<div style='text-align:center'>{row_data[_mc]}</div>", unsafe_allow_html=True)
