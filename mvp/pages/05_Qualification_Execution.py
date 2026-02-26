"""
Qualification Execution - Execute tests and record results.

Mirrors 04_Qualification_Plan.py structure with 7 sections.
Extends the 24-column xQ Plan table with 9 RED execution columns.

Uses the 3NF normalized schema:
- asset_traceability_matrix for requirement/risk/xq assignments
- requirement, risk, xq, dq, subchapter tables for catalog data
- mitigation + corrective_action tables for execution results
- record_xq_execution() to persist test outcomes
"""
import streamlit as st
import pandas as pd
import re
from pathlib import Path
import sys
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from app_core.data_io import (
    load_table, get_asset_traceability_entries,
    get_asset_phase, set_asset_phase,
    get_asset_and_peripheral_ids, record_document_export, record_document_approval,
    get_pdf_base_context, get_document_version_snapshot, get_latest_document_version_info,
    get_peripherals, get_equipment_type_by_id,
    get_asset_media, get_all_media,
    get_location_hierarchy, get_location_display,
    get_before_mitigation_values, get_after_mitigation_values,
    stamp_initial_qualification_approved,
    record_xq_execution, get_row_by_id,
)
from app_core.models import Tables, Phase, Subchapter, SUBCHAPTER_LABELS
from app_core.policy import (
    get_next_phase, is_phase_gates_enabled, get_soft_warning,
    is_editable, check_phase_gate
)
from app_core.pdf import render_document
from app_core.utils import safe_str, safe_int, excel_to_bool, calculate_quantification, calculate_risk_level
from app_core.style import apply_global_style, render_sticky_header

LIKELIHOOD_LEVELS = [
    (1, "Very unlikely (1)"),
    (2, "Unlikely (2)"),
    (3, "Possible (3)"),
    (4, "Likely (4)"),
    (6, "Very likely (6)"),
]

SEVERITY_LEVELS = [
    (3, "High (3)"),
    (2, "Medium (2)"),
    (1, "Low (1)"),
]

CELL_COLOR_MAP = {
    (1, 1): "green",
    (1, 2): "green",
    (1, 3): "green",
    (1, 4): "yellow",
    (1, 6): "yellow",
    (2, 1): "green",
    (2, 2): "yellow",
    (2, 3): "yellow",
    (2, 4): "yellow",
    (2, 6): "red",
    (3, 1): "yellow",
    (3, 2): "yellow",
    (3, 3): "red",
    (3, 4): "red",
    (3, 6): "red",
}

MATRIX_STYLE = """
<style>
.risk-matrix-wrapper {
  width: 100%;
}
.risk-matrix-title {
  font-weight: 600;
  margin-bottom: 0.25rem;
}
.risk-matrix-axis {
  text-align: center;
  font-size: 0.85rem;
  color: #444;
  margin-bottom: 0.35rem;
}
.risk-matrix {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  font-size: 0.85rem;
}
.risk-matrix th,
.risk-matrix td {
  border: 1px solid #d0d4da;
  padding: 0.4rem;
  text-align: center;
}
.risk-matrix th {
  background: #f6f7f9;
  font-weight: 600;
}
.risk-matrix .cell-green {
  background: #cdeccd;
}
.risk-matrix .cell-yellow {
  background: #fff1a8;
}
.risk-matrix .cell-red {
  background: #f7b5b5;
}
.risk-matrix .cell-green,
.risk-matrix .cell-yellow,
.risk-matrix .cell-red {
  font-weight: 700;
}
</style>
"""

# ============================================================================
# Helper functions
# ============================================================================

def _css_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _sanitize_filename(value: str) -> str:
    if not value:
        return "document"
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", value)
    return safe or "document"


def _save_uploaded_doc(uploaded_file, asset_id: int, subfolder: str = "risk_mitigation_docs") -> str:
    """Save uploaded document and return the file path."""
    docs_dir = Path(__file__).parent.parent / "data" / subfolder
    docs_dir.mkdir(parents=True, exist_ok=True)
    raw_name = Path(uploaded_file.name).name
    safe_name = _sanitize_filename(raw_name)
    dest = docs_dir / f"asset_{asset_id}_{safe_name}"
    if not dest.exists():
        with open(dest, "wb") as handle:
            handle.write(uploaded_file.getbuffer())
    return str(dest)


def _int_or_none(value):
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _likelihood_bucket(value) -> Optional[int]:
    if value is None:
        return None
    if value <= 1:
        return 1
    if value <= 2:
        return 2
    if value <= 3:
        return 3
    if value <= 4:
        return 4
    return 6


def _build_matrix_counts(rows):
    counts = {
        severity: {likelihood: 0 for likelihood, _ in LIKELIHOOD_LEVELS}
        for severity, _ in SEVERITY_LEVELS
    }
    for severity, occurrence, detection in rows:
        if severity is None or occurrence is None or detection is None:
            continue
        severity_val = _int_or_none(severity)
        occurrence_val = _int_or_none(occurrence)
        detection_val = _int_or_none(detection)
        if severity_val not in (1, 2, 3):
            continue
        if occurrence_val is None or detection_val is None:
            continue
        likelihood_score = occurrence_val * detection_val
        likelihood_bucket = _likelihood_bucket(likelihood_score)
        if likelihood_bucket is None:
            continue
        counts[severity_val][likelihood_bucket] += 1
    return counts


def _render_risk_matrix(title: str, counts: dict) -> None:
    header_cells = "".join(
        f"<th>{label}</th>" for _, label in LIKELIHOOD_LEVELS
    )
    body_rows = []
    for severity, label in SEVERITY_LEVELS:
        row_cells = []
        for likelihood, _ in LIKELIHOOD_LEVELS:
            cell_color = CELL_COLOR_MAP.get((severity, likelihood), "green")
            value = counts.get(severity, {}).get(likelihood, 0)
            row_cells.append(f'<td class="cell-{cell_color}">{value}</td>')
        body_rows.append(
            f"<tr><th>{label}</th>{''.join(row_cells)}</tr>"
        )
    table_html = f"""
<div class="risk-matrix-wrapper">
  <div class="risk-matrix-title">{title}</div>
  <div class="risk-matrix-axis">Likelihood</div>
  <table class="risk-matrix">
    <thead>
      <tr>
        <th>Impact</th>
        {header_cells}
      </tr>
    </thead>
    <tbody>
      {''.join(body_rows)}
    </tbody>
  </table>
</div>
"""
    st.markdown(table_html, unsafe_allow_html=True)


def _get_xq_after_fields(xq_id: Optional[int]) -> dict:
    """Get after-mitigation risk values from the XQ table."""
    empty = {
        "severity_after_mitigation": None,
        "likelihood_after_mitigation": None,
        "detectability_after_mitigation": None,
        "quantification_after_mitigation": None,
        "risk_level_after_mitigation": "",
    }
    if xq_id is None:
        return empty
    try:
        xq_id_int = int(xq_id)
    except (TypeError, ValueError):
        return empty
    return get_after_mitigation_values(xq_id_int, is_xq=True)


def _get_dq_after_fields(dq_id: Optional[int]) -> dict:
    """Get after-mitigation risk values from the DQ table."""
    empty = {
        "severity_after_mitigation": None,
        "likelihood_after_mitigation": None,
        "detectability_after_mitigation": None,
        "quantification_after_mitigation": None,
        "risk_level_after_mitigation": "",
    }
    if dq_id is None:
        return empty
    try:
        dq_id_int = int(dq_id)
    except (TypeError, ValueError):
        return empty
    return get_after_mitigation_values(dq_id_int, is_xq=False)


def _build_enriched_traceability(asset_id_local: int,
                                  requirement_df: pd.DataFrame,
                                  risk_df: pd.DataFrame,
                                  xq_df: pd.DataFrame,
                                  dq_df: pd.DataFrame,
                                  subchapter_df: pd.DataFrame,
                                  mitigation_df: pd.DataFrame,
                                  corrective_action_df: pd.DataFrame) -> pd.DataFrame:
    """Load traceability entries for an asset and enrich with joined catalog data."""
    entries = get_asset_traceability_entries(asset_id_local)
    if entries.empty:
        return pd.DataFrame()

    # Join requirement details
    if not requirement_df.empty and "requirement_id" in entries.columns:
        req_cols = ["id"]
        for c in ["description", "subchapter_id", "is_must_have", "is_gxp_relevant"]:
            if c in requirement_df.columns:
                req_cols.append(c)
        merged = entries.merge(
            requirement_df[req_cols].rename(columns={"id": "requirement_id"}),
            on="requirement_id",
            how="left",
            suffixes=("", "_req")
        )
    else:
        merged = entries.copy()

    # Join subchapter name
    if not subchapter_df.empty and "subchapter_id" in merged.columns:
        sc_cols = ["id"]
        if "name" in subchapter_df.columns:
            sc_cols.append("name")
        merged = merged.merge(
            subchapter_df[sc_cols].rename(columns={"id": "subchapter_id", "name": "subchapter_name"}),
            on="subchapter_id",
            how="left",
            suffixes=("", "_sc")
        )

    # Join risk details
    if not risk_df.empty and "risk_id" in merged.columns:
        risk_cols = ["id"]
        for c in ["possible_error", "severity_before_mitigation", "likelihood_before_mitigation",
                   "detectability_before_mitigation"]:
            if c in risk_df.columns:
                risk_cols.append(c)
        merged = merged.merge(
            risk_df[risk_cols].rename(columns={"id": "risk_id"}),
            on="risk_id",
            how="left",
            suffixes=("", "_risk")
        )

    # Join XQ details
    if not xq_df.empty and "xq_id" in merged.columns:
        xq_cols = ["id"]
        for c in ["description", "input", "expected_output",
                   "severity_after_mitigation", "likelihood_after_mitigation",
                   "detectability_after_mitigation"]:
            if c in xq_df.columns:
                xq_cols.append(c)
        merged = merged.merge(
            xq_df[xq_cols].rename(columns={
                "id": "xq_id",
                "description": "xq_description",
                "input": "xq_input",
                "expected_output": "xq_expected_output",
                "severity_after_mitigation": "xq_severity_after",
                "likelihood_after_mitigation": "xq_likelihood_after",
                "detectability_after_mitigation": "xq_detectability_after",
            }),
            on="xq_id",
            how="left",
            suffixes=("", "_xq")
        )

    # Join DQ details
    if not dq_df.empty and "dq_id" in merged.columns:
        dq_cols = ["id"]
        for c in ["severity_after_mitigation", "likelihood_after_mitigation",
                   "detectability_after_mitigation"]:
            if c in dq_df.columns:
                dq_cols.append(c)
        merged = merged.merge(
            dq_df[dq_cols].rename(columns={
                "id": "dq_id",
                "severity_after_mitigation": "dq_severity_after",
                "likelihood_after_mitigation": "dq_likelihood_after",
                "detectability_after_mitigation": "dq_detectability_after",
            }),
            on="dq_id",
            how="left",
            suffixes=("", "_dq")
        )

    # Join mitigation details
    if not mitigation_df.empty and "mitigation_id" in merged.columns:
        mit_cols = ["id"]
        for c in ["passed", "failed_description", "mitigation_category_id",
                   "remark", "need_correction", "justification", "corrective_action_id",
                   "status", "file_path", "xq_output"]:
            if c in mitigation_df.columns:
                mit_cols.append(c)
        merged = merged.merge(
            mitigation_df[mit_cols].rename(columns={
                "id": "mitigation_id",
                "passed": "mit_passed",
                "failed_description": "mit_failed_description",
                "mitigation_category_id": "mit_category_id",
                "remark": "mit_remark",
                "need_correction": "mit_need_correction",
                "justification": "mit_justification",
                "corrective_action_id": "mit_corrective_action_id",
                "status": "mit_status",
                "file_path": "mit_file_path",
                "xq_output": "mit_xq_output",
            }),
            on="mitigation_id",
            how="left",
            suffixes=("", "_mit")
        )

    # Join corrective action details
    if not corrective_action_df.empty and "mit_corrective_action_id" in merged.columns:
        ca_cols = ["id"]
        for c in ["name", "responsible", "status", "proof_file_path"]:
            if c in corrective_action_df.columns:
                ca_cols.append(c)
        merged = merged.merge(
            corrective_action_df[ca_cols].rename(columns={
                "id": "mit_corrective_action_id",
                "name": "ca_name",
                "responsible": "ca_responsible",
                "status": "ca_status",
                "proof_file_path": "ca_proof_file_path",
            }),
            on="mit_corrective_action_id",
            how="left",
            suffixes=("", "_ca")
        )

    return merged


def _build_exec_export_requirements(asset_id_local: int,
                                     requirement_df: pd.DataFrame,
                                     risk_df: pd.DataFrame,
                                     xq_df: pd.DataFrame,
                                     dq_df: pd.DataFrame,
                                     subchapter_df: pd.DataFrame,
                                     mitigation_df: pd.DataFrame,
                                     corrective_action_df: pd.DataFrame) -> list[dict]:
    """Build enriched requirement list for PDF export."""
    merged = _build_enriched_traceability(
        asset_id_local, requirement_df, risk_df, xq_df, dq_df,
        subchapter_df, mitigation_df, corrective_action_df
    )
    if merged.empty:
        return []
    if {"requirement_id", "risk_id"}.issubset(merged.columns):
        merged = merged.drop_duplicates(subset=["requirement_id", "risk_id"])
    elif "requirement_id" in merged.columns:
        merged = merged.drop_duplicates(subset=["requirement_id"])
    return merged.to_dict("records")


# ============================================================================
# Page config and CSS
# ============================================================================

st.set_page_config(page_title="Qualification Execution", page_icon="", layout="wide")
apply_global_style()

st.markdown(
    """
<style>
/* URS column headers - Blue (#2E86AB) */
.urs-header {
    background-color: #2E86AB;
    color: white;
    padding: 4px 8px;
    border-radius: 4px;
    font-weight: 600;
    display: inline-block;
    width: 100%;
    text-align: center;
    box-sizing: border-box;
}
/* Risk column headers - Yellow/Orange (#E8A838) */
.risk-header {
    background-color: #E8A838;
    color: white;
    padding: 4px 8px;
    border-radius: 4px;
    font-weight: 600;
    display: inline-block;
    width: 100%;
    text-align: center;
    box-sizing: border-box;
}
/* Solved by DQ column header - Green (#4CAF50) */
.solved-dq-header {
    background-color: #4CAF50;
    color: white;
    padding: 4px 8px;
    border-radius: 4px;
    font-weight: 600;
    display: inline-block;
    width: 100%;
    text-align: center;
    box-sizing: border-box;
}
/* xQ column headers - Purple (#7B1FA2) */
.xq-header {
    background-color: #7B1FA2;
    color: white;
    padding: 4px 8px;
    border-radius: 4px;
    font-weight: 600;
    display: inline-block;
    width: 100%;
    text-align: center;
    box-sizing: border-box;
}
/* xQ Execution column headers - Red (#C62828) */
.xq-exec-header {
    background-color: #C62828;
    color: white;
    padding: 4px 8px;
    border-radius: 4px;
    font-weight: 600;
    display: inline-block;
    width: 100%;
    text-align: center;
    box-sizing: border-box;
}
/* Horizontal scroll for section 5 table via marker - nested selector targets container, not page */
div[data-testid="stVerticalBlock"] div[data-testid="stVerticalBlock"]:has(.exec-table-marker) {
    overflow-x: auto;
    padding-bottom: 12px;
}
div[data-testid="stVerticalBlock"] div[data-testid="stVerticalBlock"]:has(.exec-table-marker) div[data-testid="stHorizontalBlock"] {
    min-width: 3700px;
}
</style>
""",
    unsafe_allow_html=True,
)

page_name = "05_Qualification_Execution"

render_sticky_header("Qualification Execution (xQ)")
st.markdown("Execute tests and document the results.")

# Get selected asset
if "selected_asset_id" not in st.session_state or st.session_state.selected_asset_id is None:
    st.warning("Please select an asset in the Dashboard first.")
    st.stop()

asset_id = st.session_state.selected_asset_id

assets_df = load_table(Tables.ASSET)
asset_row = assets_df[assets_df["id"] == asset_id]
if asset_row.empty:
    st.error("The selected asset was not found.")
    st.stop()

asset = asset_row.iloc[0]
asset_name = safe_str(asset.get("name", ""))

asset_phase = get_asset_phase(asset_id)

if is_phase_gates_enabled():
    gate_check = check_phase_gate(asset_phase, page_name)
    if not gate_check["allowed"]:
        st.error(gate_check["message"])
        st.stop()

soft_warning = get_soft_warning(asset_phase, page_name)
if soft_warning:
    st.warning(soft_warning)

# Load catalog tables (3NF)
requirement_catalog = load_table(Tables.REQUIREMENT)
risk_catalog = load_table(Tables.RISK)
xq_catalog = load_table(Tables.XQ)
dq_catalog = load_table(Tables.DQ)
subchapter_catalog = load_table(Tables.SUBCHAPTER)
mitigation_table = load_table(Tables.MITIGATION)
corrective_action_table = load_table(Tables.CORRECTIVE_ACTION)

# Load mitigation categories for fail category dropdown
mitigation_category_df = load_table(Tables.MITIGATION_CATEGORY)
fail_categories = [""]
if not mitigation_category_df.empty and "id" in mitigation_category_df.columns:
    for _, mc_row in mitigation_category_df.iterrows():
        cat_name = safe_str(mc_row.get("name", ""))
        if cat_name:
            fail_categories.append(cat_name)

# Build mitigation_category id <-> name maps
mitigation_cat_name_to_id = {}
mitigation_cat_id_to_name = {}
if not mitigation_category_df.empty:
    for _, mc_row in mitigation_category_df.iterrows():
        mc_id = _int_or_none(mc_row.get("id"))
        mc_name = safe_str(mc_row.get("name", ""))
        if mc_id is not None and mc_name:
            mitigation_cat_name_to_id[mc_name] = mc_id
            mitigation_cat_id_to_name[mc_id] = mc_name

if requirement_catalog.empty:
    st.warning("No requirement catalog found. Please initialize the data first.")

# Build subchapter id -> Subchapter enum mapping
subchapter_id_to_enum = {}
if not subchapter_catalog.empty:
    for _, sc_row in subchapter_catalog.iterrows():
        sc_id = _int_or_none(sc_row.get("id"))
        sc_name = safe_str(sc_row.get("name", ""))
        if sc_id is not None and sc_name:
            for sc_enum in Subchapter:
                if sc_enum.value == sc_name:
                    subchapter_id_to_enum[sc_id] = sc_enum
                    break

# Peripheral assets
peripheral_assets = get_peripherals(asset_id)
equipment_type_info = get_equipment_type_by_id(asset.get("equipment_type_id"))
equipment_type_desc = safe_str(equipment_type_info.get("name", "")) if equipment_type_info else "Unknown"

# ============================================================================
# SECTION 1: Project / Asset
# ============================================================================
st.header("1. Project / Asset")

# Get project info for display
project_id = _int_or_none(asset.get("project_id"))
project_info = get_row_by_id(Tables.PROJECT, project_id) if project_id else None
project_name = safe_str(project_info.get("name", "")) if project_info else ""

# Get business process step and system owner from main_asset
main_asset_table = load_table(Tables.MAIN_ASSET)
bps_name = ""
system_owner_name = ""
main_row = main_asset_table[main_asset_table["asset_id"] == asset_id] if not main_asset_table.empty else pd.DataFrame()
if not main_row.empty:
    bps_id = _int_or_none(main_row.iloc[0].get("business_process_step_id"))
    if bps_id:
        bps = get_row_by_id(Tables.BUSINESS_PROCESS_STEP, bps_id)
        if bps:
            bps_name = safe_str(bps.get("name", ""))
        # Get system owner via junction table
        bps_so = load_table(Tables.BUSINESS_PROCESS_STEP_SYSTEM_OWNER)
        if not bps_so.empty:
            so_match = bps_so[bps_so["business_process_step_id"] == bps_id]
            if not so_match.empty:
                so_id = _int_or_none(so_match.iloc[0].get("system_owner_id"))
                if so_id:
                    so = get_row_by_id(Tables.SYSTEM_OWNER, so_id)
                    if so:
                        system_owner_name = safe_str(so.get("role", ""))

with st.expander(f"Selected Asset: {asset_name}", expanded=True):
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Equipment Type:** {equipment_type_desc}")
        st.markdown(f"**Description:** {asset_name}")
        st.markdown(f"**Process Step:** {bps_name}")
    with col2:
        st.markdown(f"**System Owner:** {system_owner_name}")
        st.markdown(f"**Project:** {project_name}")

# ============================================================================
# SECTION 2: Location
# ============================================================================
st.header("2. Location")

if project_id:
    location_path = get_location_display(project_id)
    if location_path:
        st.success(f"Current Location: {location_path}")
    else:
        st.warning("No location assigned.")
else:
    st.warning("No project assigned to this asset.")

st.info("Location changes are only possible in the URS phase.")

st.divider()

# ============================================================================
# SECTION 3: Peripherals
# ============================================================================
st.header("3. Peripherals")

if peripheral_assets.empty:
    st.info("No peripheral devices assigned.")
else:
    st.markdown("**Assigned Peripheral Devices:**")
    for _, periph in peripheral_assets.iterrows():
        periph_eq_type = get_equipment_type_by_id(periph.get("equipment_type_id"))
        periph_eq_type_desc = safe_str(periph_eq_type.get("name", "")) if periph_eq_type else "Unknown"
        periph_name = safe_str(periph.get("name", ""))
        st.markdown(f"- **{periph_name}** ({periph_eq_type_desc})")

st.divider()

# ============================================================================
# SECTION 4: Media (Utilities & Media Connections) - read-only
# ============================================================================
st.header("4. Media")

# Load media types from catalog
all_media = get_all_media()
MEDIA_COLUMNS = []
if not all_media.empty:
    for _, m_row in all_media.iterrows():
        MEDIA_COLUMNS.append({
            "media_id": int(m_row["id"]),
            "label": safe_str(m_row.get("name", "")),
        })

media_assets = [
    {
        "asset_id": asset_id,
        "asset_name": asset_name,
        "asset_type": "Main Asset",
        "equipment_type_id": asset.get("equipment_type_id"),
        "equipment_type_desc": equipment_type_desc,
    }
]

if not peripheral_assets.empty:
    for _, periph in peripheral_assets.iterrows():
        periph_eq_type = get_equipment_type_by_id(periph.get("equipment_type_id"))
        periph_eq_type_desc = safe_str(periph_eq_type.get("name", "")) if periph_eq_type else "Unknown"
        media_assets.append({
            "asset_id": int(periph["id"]),
            "asset_name": safe_str(periph.get("name", "")),
            "asset_type": "Peripheral",
            "equipment_type_id": periph.get("equipment_type_id"),
            "equipment_type_desc": periph_eq_type_desc,
        })

asset_media_map = {}
for ma in media_assets:
    asset_media_df = get_asset_media(ma["asset_id"])
    asset_media_map[ma["asset_id"]] = {}
    if not asset_media_df.empty:
        for _, am_row in asset_media_df.iterrows():
            asset_media_map[ma["asset_id"]][int(am_row["media_id"])] = safe_str(am_row.get("media_value", ""))

if MEDIA_COLUMNS:
    header_cols = st.columns([2, 1.5] + [1.5] * len(MEDIA_COLUMNS))
    header_cols[0].markdown("**Equipment Type**")
    header_cols[1].markdown("**Asset Type**")
    for i, media_info in enumerate(MEDIA_COLUMNS):
        header_cols[i + 2].markdown(f"**{media_info['label']}**")

    for ma in media_assets:
        row_cols = st.columns([2, 1.5] + [1.5] * len(MEDIA_COLUMNS))
        row_cols[0].markdown(ma["equipment_type_desc"])
        row_cols[1].markdown(ma["asset_type"])

        current_media = asset_media_map.get(ma["asset_id"], {})
        for i, media_info in enumerate(MEDIA_COLUMNS):
            media_id = media_info["media_id"]
            current_value = current_media.get(media_id, "")
            with row_cols[i + 2]:
                if current_value:
                    st.markdown(f"{current_value}")
                else:
                    st.markdown("--")
else:
    st.info("No media types configured.")

st.info("Media can only be edited in the URS phase.")

st.divider()

# ============================================================================
# SECTION 5: Requirements (with Execution columns)
# ============================================================================
st.header("5. Requirements")

with st.container():
    # Marker for CSS :has() selector to enable horizontal scrolling
    st.markdown('<div class="exec-table-marker"></div>', unsafe_allow_html=True)

    assets_for_requirements = [
        {
            "asset_id": asset_id,
            "asset_name": asset_name,
            "asset_type": "main",
            "equipment_type_id": asset.get("equipment_type_id"),
            "label": f"{asset_name} ({equipment_type_desc})"
        }
    ]

    if not peripheral_assets.empty:
        for _, periph in peripheral_assets.iterrows():
            periph_eq_type = get_equipment_type_by_id(periph.get("equipment_type_id"))
            periph_eq_type_desc = safe_str(periph_eq_type.get("name", "")) if periph_eq_type else "Unknown"
            periph_name = safe_str(periph.get("name", ""))
            assets_for_requirements.append({
                "asset_id": int(periph["id"]),
                "asset_name": periph_name,
                "asset_type": "peripheral",
                "equipment_type_id": periph.get("equipment_type_id"),
                "label": f"{periph_name} ({periph_eq_type_desc})"
            })

    # Load enriched traceability data per asset
    requirements_by_asset = {}
    for asset_info in assets_for_requirements:
        merged = _build_enriched_traceability(
            asset_info["asset_id"],
            requirement_catalog, risk_catalog, xq_catalog, dq_catalog,
            subchapter_catalog, mitigation_table, corrective_action_table
        )
        requirements_by_asset[asset_info["asset_id"]] = merged

    if not any(not df.empty for df in requirements_by_asset.values()):
        st.info("No requirements assigned.")
        st.stop()

    can_edit_exec = is_editable(asset_phase, Tables.MITIGATION, "passed")

    save_exec_clicked = st.button("Save Results", disabled=not can_edit_exec, type="primary")

    # ---- SAVE LOGIC ----
    if save_exec_clicked:
        changed = 0

        for asset_info in assets_for_requirements:
            asset_id_local = asset_info["asset_id"]
            asset_reqs = requirements_by_asset.get(asset_id_local)
            if asset_reqs is None or asset_reqs.empty:
                continue

            for row_idx, entry in asset_reqs.iterrows():
                requirement_id_val = _int_or_none(entry.get("requirement_id"))
                risk_id_val = _int_or_none(entry.get("risk_id"))
                row_key = f"{asset_id_local}_{requirement_id_val}_{row_idx}"

                # Only process rows with xQ assigned
                xq_id_val = _int_or_none(entry.get("xq_id"))
                if xq_id_val is None:
                    continue

                # Check if this row needs xQ execution (has before-mitigation risk)
                before_vals = get_before_mitigation_values(risk_id_val) if risk_id_val else {}
                before_level = safe_str(before_vals.get("risk_level_before_mitigation", ""))

                # Only process rows that have an xQ assigned
                xq_id_check = _int_or_none(entry.get("xq_id"))
                has_xq = xq_id_check is not None
                if not has_xq:
                    continue

                # Read widget values from session state
                output_key = f"exec_output_{row_key}"
                proof_path_key = f"exec_proof_path_{row_key}"
                passed_key = f"exec_passed_{row_key}"
                fail_desc_key = f"exec_fail_desc_{row_key}"
                need_corr_key = f"exec_need_corr_{row_key}"
                fail_just_key = f"exec_fail_just_{row_key}"
                corr_action_key = f"exec_corr_action_{row_key}"
                corr_resp_key = f"exec_corr_resp_{row_key}"
                corr_proof_path_key = f"exec_corr_proof_path_{row_key}"

                new_output = safe_str(st.session_state.get(output_key, ""))
                new_passed_str = st.session_state.get(passed_key, "")

                if not new_passed_str:
                    # No pass/fail selection yet - skip
                    continue

                passed_bool = new_passed_str == "Pass"

                # Read proof file path (always saved, regardless of pass/fail)
                current_proof_saved = safe_str(entry.get("mit_file_path", ""))
                new_proof_path = safe_str(st.session_state.get(proof_path_key, current_proof_saved))

                # Gather failure details
                new_fail_desc = ""
                new_fail_just = ""
                need_correction = False
                new_corr_action = ""
                new_corr_resp = ""
                new_corr_proof = ""

                if not passed_bool:
                    new_fail_desc = safe_str(st.session_state.get(fail_desc_key, ""))
                    need_correction = bool(st.session_state.get(need_corr_key, False))

                    if not need_correction:
                        # No correction needed → justification is mandatory
                        new_fail_just = safe_str(st.session_state.get(fail_just_key, ""))
                    else:
                        # Correction needed → corrective action fields
                        new_corr_action = safe_str(st.session_state.get(corr_action_key, ""))
                        new_corr_resp = safe_str(st.session_state.get(corr_resp_key, ""))
                        current_corr_proof_saved = safe_str(entry.get("ca_proof_file_path", ""))
                        new_corr_proof = safe_str(st.session_state.get(corr_proof_path_key, current_corr_proof_saved))

                # Compute corrective action status
                corr_status = "done" if new_corr_proof.strip() else "open"

                success = record_xq_execution(
                    asset_id=asset_id_local,
                    requirement_id=requirement_id_val,
                    risk_id=risk_id_val,
                    xq_output=new_output,
                    passed=passed_bool,
                    need_correction=need_correction,
                    failed_description=new_fail_desc,
                    failed_justification=new_fail_just,
                    file_path=new_proof_path,
                    corrective_action_name=new_corr_action,
                    corrective_action_responsible=new_corr_resp,
                    corrective_action_status=corr_status,
                    corrective_action_proof=new_corr_proof,
                )
                if success:
                    changed += 1

        if changed:
            st.success(f"{changed} result(s) saved.")
        else:
            st.info("No changes to save.")

        st.rerun()

    # ---- RENDER TABLE ----
    for asset_info in assets_for_requirements:
        asset_id_local = asset_info["asset_id"]
        asset_label = asset_info["label"]
        section_title = "Main Asset" if asset_info["asset_type"] == "main" else "Peripheral"
        st.subheader(f"{section_title}: {asset_label}")

        asset_reqs = requirements_by_asset.get(asset_id_local)
        if asset_reqs is None or asset_reqs.empty:
            st.caption("No requirements assigned.")
            continue

        # Map subchapter_id to Subchapter enum for grouping
        for subchapter in Subchapter:
            chapter_label = SUBCHAPTER_LABELS[subchapter]
            st.markdown(f"**{chapter_label}**")
            indent_cols = st.columns([0.04, 0.96], gap="small")
            with indent_cols[1]:
                # Filter by subchapter
                matching_sc_ids = [
                    sc_id for sc_id, sc_enum in subchapter_id_to_enum.items()
                    if sc_enum == subchapter
                ]
                if matching_sc_ids and "subchapter_id" in asset_reqs.columns:
                    sub_reqs = asset_reqs[asset_reqs["subchapter_id"].isin(matching_sc_ids)].copy()
                else:
                    sub_reqs = pd.DataFrame()

                if not sub_reqs.empty and "requirement_id" in sub_reqs.columns:
                    sub_reqs["__risk_sort"] = sub_reqs.get("risk_id").apply(_int_or_none)
                    sub_reqs = sub_reqs.sort_values(
                        ["requirement_id", "__risk_sort"],
                        na_position="last"
                    ).drop(columns=["__risk_sort"])

                if sub_reqs.empty:
                    st.caption("No requirements in this subchapter.")
                else:
                    # 34-column layout: 24 read-only xQ Plan cols + 10 RED execution cols
                    column_widths = [
                        # Blue (URS) 0-4
                        0.5, 1.5, 0.8, 0.4, 0.4,
                        # Yellow (Risk) 5-12
                        0.5, 0.8, 0.4, 0.4, 0.4, 0.45, 0.5, 0.5,
                        # Green 13
                        0.6,
                        # Purple (xQ) 14-23
                        0.5, 0.9, 0.7, 0.7, 0.4, 0.4, 0.4, 0.5, 0.5, 0.7,
                        # RED (xQ Execution) 24-33
                        1.0,  # 24: Actual Output
                        0.7,  # 25: Proof
                        0.5,  # 26: Pass/Fail
                        0.8,  # 27: Deviation
                        0.5,  # 28: Need Correction?
                        0.7,  # 29: Justification (only when no correction needed)
                        0.7,  # 30: Corr. Action (only when correction needed)
                        0.6,  # 31: Responsible (only when correction needed)
                        0.5,  # 32: Status (only when correction needed)
                        0.7,  # 33: Corr. Proof (only when correction needed)
                    ]

                    header_cols = st.columns(column_widths, gap="small")
                    # Blue URS headers (0-4)
                    header_cols[0].markdown('<span class="urs-header">ID</span>', unsafe_allow_html=True)
                    header_cols[1].markdown('<span class="urs-header">Requirement</span>', unsafe_allow_html=True)
                    header_cols[2].markdown('<span class="urs-header">Remark</span>', unsafe_allow_html=True)
                    header_cols[3].markdown('<span class="urs-header">GxP</span>', unsafe_allow_html=True)
                    header_cols[4].markdown('<span class="urs-header">Must</span>', unsafe_allow_html=True)
                    # Yellow Risk headers (5-12)
                    header_cols[5].markdown('<span class="risk-header">Risk-ID</span>', unsafe_allow_html=True)
                    header_cols[6].markdown('<span class="risk-header">Risk Title</span>', unsafe_allow_html=True)
                    header_cols[7].markdown('<span class="risk-header">S (before)</span>', unsafe_allow_html=True)
                    header_cols[8].markdown('<span class="risk-header">O (before)</span>', unsafe_allow_html=True)
                    header_cols[9].markdown('<span class="risk-header">D (before)</span>', unsafe_allow_html=True)
                    header_cols[10].markdown('<span class="risk-header">RPN (before)</span>', unsafe_allow_html=True)
                    header_cols[11].markdown('<span class="risk-header">Level (before)</span>', unsafe_allow_html=True)
                    header_cols[12].markdown('<span class="risk-header">Mitig.</span>', unsafe_allow_html=True)
                    # Green header (13)
                    header_cols[13].markdown('<span class="solved-dq-header">DQ?</span>', unsafe_allow_html=True)
                    # Purple xQ headers (14-23)
                    header_cols[14].markdown('<span class="xq-header">xQ-ID</span>', unsafe_allow_html=True)
                    header_cols[15].markdown('<span class="xq-header">xQ Desc</span>', unsafe_allow_html=True)
                    header_cols[16].markdown('<span class="xq-header">Input</span>', unsafe_allow_html=True)
                    header_cols[17].markdown('<span class="xq-header">Expected Output</span>', unsafe_allow_html=True)
                    header_cols[18].markdown('<span class="xq-header">S (after)</span>', unsafe_allow_html=True)
                    header_cols[19].markdown('<span class="xq-header">O (after)</span>', unsafe_allow_html=True)
                    header_cols[20].markdown('<span class="xq-header">D (after)</span>', unsafe_allow_html=True)
                    header_cols[21].markdown('<span class="xq-header">RPN (after)</span>', unsafe_allow_html=True)
                    header_cols[22].markdown('<span class="xq-header">Level (after)</span>', unsafe_allow_html=True)
                    header_cols[23].markdown('<span class="xq-header">xQ Remark</span>', unsafe_allow_html=True)
                    # RED xQ Execution headers (24-33)
                    header_cols[24].markdown('<span class="xq-exec-header">Actual Output</span>', unsafe_allow_html=True)
                    header_cols[25].markdown('<span class="xq-exec-header">Proof</span>', unsafe_allow_html=True)
                    header_cols[26].markdown('<span class="xq-exec-header">Pass/Fail</span>', unsafe_allow_html=True)
                    header_cols[27].markdown('<span class="xq-exec-header">Deviation</span>', unsafe_allow_html=True)
                    header_cols[28].markdown('<span class="xq-exec-header">Need Corr.?</span>', unsafe_allow_html=True)
                    header_cols[29].markdown('<span class="xq-exec-header">Justification</span>', unsafe_allow_html=True)
                    header_cols[30].markdown('<span class="xq-exec-header">Corr. Action</span>', unsafe_allow_html=True)
                    header_cols[31].markdown('<span class="xq-exec-header">Responsible</span>', unsafe_allow_html=True)
                    header_cols[32].markdown('<span class="xq-exec-header">Status</span>', unsafe_allow_html=True)
                    header_cols[33].markdown('<span class="xq-exec-header">Corr. Proof</span>', unsafe_allow_html=True)

                    grouped_reqs = sub_reqs.groupby("requirement_id", sort=False)
                    for group_idx, (req_id_local, group) in enumerate(grouped_reqs):
                        if group_idx > 0:
                            st.markdown("---")

                        group_first = group.iloc[0]
                        requirement_text = safe_str(group_first.get("description", ""))
                        remark_text = safe_str(group_first.get("requirement_remark", ""))
                        is_gxp = excel_to_bool(group_first.get("is_gxp", False))
                        is_must = excel_to_bool(group_first.get("is_must", False))
                        seen_risks = set()

                        for row_pos, (row_idx, entry) in enumerate(group.iterrows()):
                            is_first_row = row_pos == 0
                            row_key = f"{asset_id_local}_{req_id_local}_{row_idx}"

                            row_cols = st.columns(column_widths, gap="small")

                            # ---- Columns 0-4: URS info (blue, read-only) ----
                            if is_first_row:
                                row_cols[0].markdown(f"REQ-{req_id_local}")
                                row_cols[1].markdown(requirement_text)
                                row_cols[2].markdown(remark_text or "")
                                row_cols[3].markdown("Y" if is_gxp else "N")
                                row_cols[4].markdown("Y" if is_must else "N")
                            else:
                                for ci in range(5):
                                    row_cols[ci].markdown("")

                            # ---- Columns 5-6: Risk-ID, Risk Title (read-only) ----
                            risk_id_val = entry.get("risk_id")
                            risk_title_val = safe_str(entry.get("possible_error", ""))
                            has_risk = pd.notna(risk_id_val) if risk_id_val is not None else False
                            risk_key = _int_or_none(risk_id_val)
                            show_risk = risk_key not in seen_risks
                            if show_risk:
                                seen_risks.add(risk_key)

                            if show_risk:
                                if has_risk:
                                    row_cols[5].markdown(f"R-{int(risk_id_val)}")
                                else:
                                    row_cols[5].markdown("")
                                row_cols[6].markdown(risk_title_val or "")
                            else:
                                row_cols[5].markdown("")
                                row_cols[6].markdown("")

                            # ---- Columns 7-11: S/O/D/RPN/Level (before) (read-only) ----
                            before_sev = _int_or_none(entry.get("severity_before_mitigation"))
                            before_occ = _int_or_none(entry.get("likelihood_before_mitigation"))
                            before_det = _int_or_none(entry.get("detectability_before_mitigation"))
                            before_quant = None
                            before_level = ""

                            if before_sev and before_occ and before_det:
                                before_quant = calculate_quantification(before_sev, before_occ, before_det)
                                before_level = calculate_risk_level(before_quant)

                            if show_risk:
                                row_cols[7].markdown(str(before_sev) if before_sev else "")
                                row_cols[8].markdown(str(before_occ) if before_occ else "")
                                row_cols[9].markdown(str(before_det) if before_det else "")
                                row_cols[10].markdown(str(before_quant) if before_quant else "")
                                before_icon = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(before_level, "⚪")
                                before_label = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH"}.get(before_level, "")
                                row_cols[11].markdown(f"{before_icon} {before_label}" if before_level else "")
                            else:
                                for ci in range(7, 12):
                                    row_cols[ci].markdown("")

                            # ---- Column 12: Mitigation required? (read-only) ----
                            mitigation_required_flag = before_level in ("high", "medium")
                            if show_risk:
                                row_cols[12].markdown("Y" if mitigation_required_flag else "N")
                            else:
                                row_cols[12].markdown("")

                            # ---- Column 13: Solved by DQ (read-only) ----
                            dq_id_val = _int_or_none(entry.get("dq_id"))
                            solved_by_dq = dq_id_val is not None

                            if not mitigation_required_flag:
                                row_cols[13].markdown("n/a")
                            elif solved_by_dq:
                                row_cols[13].markdown(f"DQ-{dq_id_val}")
                            else:
                                row_cols[13].markdown("NO")

                            # Determine if this row has xQ assigned
                            xq_id_val = _int_or_none(entry.get("xq_id"))
                            has_xq = xq_id_val is not None

                            if not has_xq:
                                # Empty purple + red columns
                                for ci in range(14, 34):
                                    row_cols[ci].markdown("n/a" if ci < 24 else "")
                            else:
                                # ---- Purple columns 14-23: xQ Plan info (ALL read-only) ----

                                # Column 14: xQ-ID
                                row_cols[14].markdown(f"xQ-{xq_id_val}")

                                # Column 15: xQ Description
                                xq_description = safe_str(entry.get("xq_description", ""))
                                row_cols[15].markdown(xq_description)

                                # Column 16: xQ Input
                                xq_input = safe_str(entry.get("xq_input", ""))
                                row_cols[16].markdown(xq_input)

                                # Column 17: xQ Expected Output
                                xq_expected = safe_str(entry.get("xq_expected_output", ""))
                                row_cols[17].markdown(xq_expected)

                                # Columns 18-22: S/O/D/RPN/Level (after)
                                after_fields = _get_xq_after_fields(xq_id_val)
                                disp_sev = after_fields.get("severity_after_mitigation")
                                disp_occ = after_fields.get("likelihood_after_mitigation")
                                disp_det = after_fields.get("detectability_after_mitigation")
                                disp_quant = after_fields.get("quantification_after_mitigation")
                                disp_level = after_fields.get("risk_level_after_mitigation", "")

                                row_cols[18].markdown(str(disp_sev) if disp_sev else "")
                                row_cols[19].markdown(str(disp_occ) if disp_occ else "")
                                row_cols[20].markdown(str(disp_det) if disp_det else "")

                                if disp_quant is None and disp_sev and disp_occ and disp_det:
                                    disp_quant = calculate_quantification(disp_sev, disp_occ, disp_det)
                                if not disp_level and disp_quant is not None:
                                    disp_level = calculate_risk_level(disp_quant)

                                if disp_quant is not None:
                                    row_cols[21].markdown(str(disp_quant))
                                    level_icon = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(disp_level, "⚪")
                                    level_label = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH"}.get(disp_level, "")
                                    row_cols[22].markdown(f"{level_icon} {level_label}" if disp_level else "")
                                else:
                                    row_cols[21].markdown("")
                                    row_cols[22].markdown("")

                                # Column 23: xQ Remark (read-only, from traceability matrix)
                                row_cols[23].markdown(safe_str(entry.get("xq_remark", "")))

                                # ---- RED columns 24-33: Execution (editable if xQ assigned) ----
                                # Read existing mitigation/corrective action data
                                mit_passed_raw = entry.get("mit_passed")
                                mit_failed_desc = safe_str(entry.get("mit_failed_description", ""))
                                mit_justification = safe_str(entry.get("mit_justification", ""))
                                mit_need_correction_raw = entry.get("mit_need_correction")
                                ca_name_val = safe_str(entry.get("ca_name", ""))
                                ca_responsible_val = safe_str(entry.get("ca_responsible", ""))
                                ca_status_val = safe_str(entry.get("ca_status", ""))
                                ca_proof_val = safe_str(entry.get("ca_proof_file_path", ""))
                                mit_file_path = safe_str(entry.get("mit_file_path", ""))

                                # Determine current pass/fail index
                                pass_options = ["", "Pass", "Fail"]
                                if mit_passed_raw is not None and not (isinstance(mit_passed_raw, float) and pd.isna(mit_passed_raw)):
                                    if excel_to_bool(mit_passed_raw) and safe_str(mit_passed_raw).strip() != "":
                                        pass_idx = 1
                                    elif safe_str(mit_passed_raw).strip() != "":
                                        pass_idx = 2
                                    else:
                                        pass_idx = 0
                                else:
                                    pass_idx = 0

                                # Determine existing need_correction value
                                if mit_need_correction_raw is not None and not (isinstance(mit_need_correction_raw, float) and pd.isna(mit_need_correction_raw)):
                                    need_correction_default = excel_to_bool(mit_need_correction_raw)
                                else:
                                    need_correction_default = False

                                # Column 24: Actual Output (xq_output from mitigation table)
                                current_output = safe_str(entry.get("mit_xq_output", ""))
                                output_key = f"exec_output_{row_key}"
                                if can_edit_exec:
                                    row_cols[24].text_area(
                                        f"Actual Output [{row_key}]",
                                        value=current_output,
                                        key=output_key,
                                        label_visibility="collapsed",
                                        height=80,
                                    )
                                else:
                                    row_cols[24].markdown(current_output or "")

                                # Column 25: Proof (file_path on mitigation) - file upload
                                proof_upload_key = f"exec_proof_upload_{row_key}"
                                proof_path_key = f"exec_proof_path_{row_key}"
                                proof_sig_key = f"exec_proof_sig_{row_key}"

                                if can_edit_exec:
                                    proof_label = f"Proof [{row_key}]"
                                    uploaded_proof = row_cols[25].file_uploader(
                                        proof_label,
                                        key=proof_upload_key,
                                        label_visibility="collapsed",
                                    )
                                    if uploaded_proof is not None:
                                        upload_sig = (uploaded_proof.name, uploaded_proof.size)
                                        if st.session_state.get(proof_sig_key) != upload_sig:
                                            saved_path = _save_uploaded_doc(uploaded_proof, asset_id_local)
                                            st.session_state[proof_path_key] = saved_path
                                            st.session_state[proof_sig_key] = upload_sig
                                    proof_display = st.session_state.get(proof_path_key, mit_file_path)
                                    if proof_display:
                                        row_cols[25].caption(proof_display)
                                else:
                                    if mit_file_path:
                                        row_cols[25].caption(mit_file_path)
                                    else:
                                        row_cols[25].markdown("")

                                # Column 26: Pass/Fail
                                passed_key = f"exec_passed_{row_key}"
                                if can_edit_exec:
                                    selected_pass = row_cols[26].selectbox(
                                        f"Pass/Fail [{row_key}]",
                                        pass_options,
                                        index=pass_idx,
                                        key=passed_key,
                                        label_visibility="collapsed",
                                    )
                                else:
                                    selected_pass = pass_options[pass_idx]
                                    row_cols[26].markdown(selected_pass or "")

                                # Columns 27-33: Fail columns (only visible when Fail)
                                is_fail = selected_pass == "Fail"

                                if is_fail:
                                    # Column 27: Deviation (failed_description on mitigation)
                                    fail_desc_key = f"exec_fail_desc_{row_key}"
                                    if can_edit_exec:
                                        row_cols[27].text_area(
                                            f"Deviation [{row_key}]",
                                            value=mit_failed_desc,
                                            key=fail_desc_key,
                                            label_visibility="collapsed",
                                            height=80,
                                        )
                                    else:
                                        row_cols[27].markdown(mit_failed_desc or "")

                                    # Column 28: Need Correction? (checkbox)
                                    need_corr_key = f"exec_need_corr_{row_key}"
                                    if can_edit_exec:
                                        need_correction = row_cols[28].checkbox(
                                            "Corr.",
                                            value=need_correction_default,
                                            key=need_corr_key,
                                            label_visibility="collapsed",
                                        )
                                    else:
                                        need_correction = need_correction_default
                                        row_cols[28].markdown("Yes" if need_correction else "No")

                                    if not need_correction:
                                        # No correction needed → Justification mandatory, corr. fields hidden
                                        # Column 29: Justification
                                        fail_just_key = f"exec_fail_just_{row_key}"
                                        if can_edit_exec:
                                            row_cols[29].text_area(
                                                f"Justification [{row_key}]",
                                                value=mit_justification,
                                                key=fail_just_key,
                                                label_visibility="collapsed",
                                                height=80,
                                            )
                                        else:
                                            row_cols[29].markdown(mit_justification or "")
                                        # Columns 30-33: hidden (no correction)
                                        for ci in range(30, 34):
                                            row_cols[ci].markdown("")
                                    else:
                                        # Correction needed → corr. fields mandatory, justification hidden
                                        # Column 29: hidden (justification not needed)
                                        row_cols[29].markdown("")

                                        # Column 30: Corrective Action (name on corrective_action)
                                        corr_action_key = f"exec_corr_action_{row_key}"
                                        if can_edit_exec:
                                            row_cols[30].text_area(
                                                f"Corrective Action [{row_key}]",
                                                value=ca_name_val,
                                                key=corr_action_key,
                                                label_visibility="collapsed",
                                                height=80,
                                            )
                                        else:
                                            row_cols[30].markdown(ca_name_val or "")

                                        # Column 31: Responsible (responsible on corrective_action)
                                        corr_resp_key = f"exec_corr_resp_{row_key}"
                                        if can_edit_exec:
                                            row_cols[31].text_input(
                                                f"Responsible [{row_key}]",
                                                value=ca_responsible_val,
                                                key=corr_resp_key,
                                                label_visibility="collapsed",
                                            )
                                        else:
                                            row_cols[31].markdown(ca_responsible_val or "")

                                        # Column 32: Status (auto-computed, read-only)
                                        current_corr_status = ca_status_val if ca_status_val else ("done" if ca_proof_val.strip() else "open")
                                        status_icon = "done" if current_corr_status == "done" else "open"
                                        row_cols[32].markdown(f"{status_icon}")

                                        # Column 33: Correction Proof (proof_file_path on corrective_action) - file upload
                                        corr_proof_upload_key = f"exec_corr_proof_upload_{row_key}"
                                        corr_proof_path_key = f"exec_corr_proof_path_{row_key}"
                                        corr_proof_sig_key = f"exec_corr_proof_sig_{row_key}"

                                        if can_edit_exec:
                                            corr_proof_label = f"Corr. Proof [{row_key}]"
                                            uploaded_corr_proof = row_cols[33].file_uploader(
                                                corr_proof_label,
                                                key=corr_proof_upload_key,
                                                label_visibility="collapsed",
                                            )
                                            if uploaded_corr_proof is not None:
                                                corr_upload_sig = (uploaded_corr_proof.name, uploaded_corr_proof.size)
                                                if st.session_state.get(corr_proof_sig_key) != corr_upload_sig:
                                                    saved_corr_path = _save_uploaded_doc(uploaded_corr_proof, asset_id_local, "corrective_action_docs")
                                                    st.session_state[corr_proof_path_key] = saved_corr_path
                                                    st.session_state[corr_proof_sig_key] = corr_upload_sig
                                            corr_proof_display = st.session_state.get(corr_proof_path_key, ca_proof_val)
                                            if corr_proof_display:
                                                row_cols[33].caption(corr_proof_display)
                                        else:
                                            if ca_proof_val:
                                                row_cols[33].caption(ca_proof_val)
                                            else:
                                                row_cols[33].markdown("")
                                else:
                                    # Pass or not yet decided - hide fail columns
                                    for ci in range(27, 34):
                                        row_cols[ci].markdown("")

st.divider()

# ============================================================================
# SECTION 6: Risk Matrix
# ============================================================================
st.header("6. Risk Matrix")

all_asset_entries = []
for asset_info in assets_for_requirements:
    asset_reqs = requirements_by_asset.get(asset_info["asset_id"])
    if asset_reqs is not None and not asset_reqs.empty:
        all_asset_entries.append(asset_reqs)

combined_entries = pd.concat(all_asset_entries, ignore_index=True) if all_asset_entries else pd.DataFrame()

before_rows = []
after_dq_rows = []
after_xq_rows = []

if not combined_entries.empty:
    assigned = combined_entries[combined_entries["risk_id"].notna()]
    if {"requirement_id", "risk_id"}.issubset(assigned.columns):
        dedupe_cols = ["requirement_id", "risk_id"]
        if "asset_id" in assigned.columns:
            dedupe_cols.insert(0, "asset_id")
        assigned = assigned.drop_duplicates(subset=dedupe_cols)

    for _, entry in assigned.iterrows():
        sev_before = _int_or_none(entry.get("severity_before_mitigation"))
        occ_before = _int_or_none(entry.get("likelihood_before_mitigation"))
        det_before = _int_or_none(entry.get("detectability_before_mitigation"))
        before_rows.append((sev_before, occ_before, det_before))

        # Determine after-DQ values
        dq_id_entry = _int_or_none(entry.get("dq_id"))
        has_dq = dq_id_entry is not None

        sev_after_dq = _int_or_none(entry.get("dq_severity_after"))
        occ_after_dq = _int_or_none(entry.get("dq_likelihood_after"))
        det_after_dq = _int_or_none(entry.get("dq_detectability_after"))
        has_dq_after = sev_after_dq is not None and occ_after_dq is not None and det_after_dq is not None

        # Matrix 2: After DQ - replace before with after only where DQ is assigned
        if has_dq and has_dq_after:
            after_dq_rows.append((sev_after_dq, occ_after_dq, det_after_dq))
        else:
            after_dq_rows.append((sev_before, occ_before, det_before))

        # Determine after-XQ values
        xq_id_entry = _int_or_none(entry.get("xq_id"))
        has_xq_entry = xq_id_entry is not None

        sev_after_xq = _int_or_none(entry.get("xq_severity_after"))
        occ_after_xq = _int_or_none(entry.get("xq_likelihood_after"))
        det_after_xq = _int_or_none(entry.get("xq_detectability_after"))
        has_xq_after = sev_after_xq is not None and occ_after_xq is not None and det_after_xq is not None

        # Matrix 3: After xQ - use XQ after values where available, else DQ, else before
        if has_xq_entry and has_xq_after:
            after_xq_rows.append((sev_after_xq, occ_after_xq, det_after_xq))
        elif has_dq and has_dq_after:
            after_xq_rows.append((sev_after_dq, occ_after_dq, det_after_dq))
        else:
            after_xq_rows.append((sev_before, occ_before, det_before))

before_counts = _build_matrix_counts(before_rows)
after_dq_counts = _build_matrix_counts(after_dq_rows)
after_xq_counts = _build_matrix_counts(after_xq_rows)

st.markdown(MATRIX_STYLE, unsafe_allow_html=True)
col_m1, col_m2, col_m3 = st.columns(3)
with col_m1:
    _render_risk_matrix("Before Mitigation", before_counts)
with col_m2:
    _render_risk_matrix("After DQ Mitigation", after_dq_counts)
with col_m3:
    _render_risk_matrix("After xQ Mitigation", after_xq_counts)

st.divider()

# ============================================================================
# SECTION 7: Qualification Execution Document Export
# ============================================================================
st.header("7. Qualification Execution Document Export")

# Validation for export and approve
missing_results = []       # blocks export + approve
missing_fail_fields = []   # blocks export + approve
missing_approve_fields = []  # blocks approve only

for asset_info in assets_for_requirements:
    asset_id_local = asset_info["asset_id"]
    asset_label = asset_info["label"]
    entries = get_asset_traceability_entries(asset_id_local)
    if entries.empty:
        continue

    for row_idx, entry in entries.iterrows():
        xq_id_val = _int_or_none(entry.get("xq_id"))
        if xq_id_val is None:
            continue

        risk_id_val = _int_or_none(entry.get("risk_id"))
        req_id_val = _int_or_none(entry.get("requirement_id"))
        row_label = f"REQ-{req_id_val} / xQ-{xq_id_val} ({asset_label})"

        # Check mitigation record for pass/fail
        mitigation_id = _int_or_none(entry.get("mitigation_id"))
        if mitigation_id is not None:
            mit_row = get_row_by_id(Tables.MITIGATION, mitigation_id)
        else:
            mit_row = None

        if mit_row is None:
            missing_results.append(row_label)
            continue

        passed_raw = mit_row.get("passed")
        if passed_raw is not None and not (isinstance(passed_raw, float) and pd.isna(passed_raw)):
            if excel_to_bool(passed_raw) and safe_str(passed_raw).strip() != "":
                passed_val = "TRUE"
            elif safe_str(passed_raw).strip() != "":
                passed_val = "FALSE"
            else:
                passed_val = ""
        else:
            passed_val = ""

        # 1) Pass/Fail must be set
        if passed_val not in ("TRUE", "FALSE"):
            missing_results.append(row_label)

        # 2) If Fail: required fail fields must be filled
        if passed_val == "FALSE":
            missing_fields = []
            if not safe_str(mit_row.get("failed_description", "")).strip():
                missing_fields.append("Deviation")

            need_corr_raw = mit_row.get("need_correction")
            need_corr = excel_to_bool(need_corr_raw) if need_corr_raw is not None and not (isinstance(need_corr_raw, float) and pd.isna(need_corr_raw)) else False

            if not need_corr:
                # No correction → justification is mandatory
                if not safe_str(mit_row.get("justification", "")).strip():
                    missing_fields.append("Justification")
            else:
                # Correction needed → corrective action fields mandatory
                ca_id = _int_or_none(mit_row.get("corrective_action_id"))
                ca_row = get_row_by_id(Tables.CORRECTIVE_ACTION, ca_id) if ca_id else None
                if ca_row is None:
                    missing_fields.append("Corrective Action")
                else:
                    if not safe_str(ca_row.get("name", "")).strip():
                        missing_fields.append("Corrective Action")
                    if not safe_str(ca_row.get("responsible", "")).strip():
                        missing_fields.append("Responsible")

            if missing_fields:
                missing_fail_fields.append(f"{row_label}: {', '.join(missing_fields)}")

            # 3) For approve only: if correction needed, status + proof must be filled
            approve_missing = []
            if need_corr:
                ca_id = _int_or_none(mit_row.get("corrective_action_id"))
                ca_row = get_row_by_id(Tables.CORRECTIVE_ACTION, ca_id) if ca_id else None
                if ca_row:
                    corr_status = safe_str(ca_row.get("status", "")).strip().lower()
                    corr_proof = safe_str(ca_row.get("proof_file_path", "")).strip()
                    if corr_status != "done":
                        approve_missing.append("Status")
                    if not corr_proof:
                        approve_missing.append("Correction Proof")
                else:
                    approve_missing.append("Status")
                    approve_missing.append("Correction Proof")
            if approve_missing:
                missing_approve_fields.append(f"{row_label}: {', '.join(approve_missing)}")

if missing_results:
    st.error(f"Missing test results (Pass/Fail): {', '.join(missing_results)}")
if missing_fail_fields:
    st.error("Missing fail fields:")
    for item in missing_fail_fields:
        st.markdown(f"- {item}")

has_export_errors = bool(missing_results or missing_fail_fields)
has_approve_errors = has_export_errors or bool(missing_approve_fields)

if not has_export_errors and missing_approve_fields:
    st.warning("The following fields must be filled for approval:")
    for item in missing_approve_fields:
        st.markdown(f"- {item}")

col_export, col_approve = st.columns([1, 1])

with col_export:
    export_disabled = asset_phase != Phase.XQ_EXECUTION or has_export_errors
    export_btn = st.button(
        "Create xQ Execution (PDF)",
        type="primary",
        disabled=export_disabled
    )

with col_approve:
    approve_disabled = asset_phase != Phase.XQ_EXECUTION or has_approve_errors
    approve_btn = st.button("Approve xQ Execution", disabled=approve_disabled)

if approve_btn:
    doc_type = asset_phase.value
    target_phase = get_next_phase(Phase.XQ_EXECUTION)
    asset_ids = get_asset_and_peripheral_ids(asset_id)
    if target_phase and set_asset_phase(asset_ids, Phase.XQ_EXECUTION):
        stamp_initial_qualification_approved(asset_ids)
        record_document_approval(asset_id, doc_type)

        approved_version = get_latest_document_version_info(asset_id, doc_type)
        if not approved_version:
            st.error("Could not create approved PDF: No document version found. Please export first.")
        else:
            peripheral_assets_export = get_peripherals(asset_id)
            main_reqs = _build_exec_export_requirements(
                asset_id, requirement_catalog, risk_catalog, xq_catalog,
                dq_catalog, subchapter_catalog, mitigation_table, corrective_action_table
            )

            peripherals_data = []
            if not peripheral_assets_export.empty:
                for _, periph in peripheral_assets_export.iterrows():
                    periph_reqs = _build_exec_export_requirements(
                        int(periph["id"]), requirement_catalog, risk_catalog, xq_catalog,
                        dq_catalog, subchapter_catalog, mitigation_table, corrective_action_table
                    )
                    periph_eq_type = get_equipment_type_by_id(periph.get("equipment_type_id"))
                    periph_eq_type_desc = (
                        safe_str(periph_eq_type.get("name", ""))
                        if periph_eq_type else "Unknown"
                    )
                    peripherals_data.append({
                        "name": safe_str(periph.get("name", "")),
                        "equipment_type": periph_eq_type_desc,
                        "requirements": periph_reqs,
                    })

            # Build xQ catalog map for PDF
            xq_catalog_map_approve = {}
            if not xq_catalog.empty and "id" in xq_catalog.columns:
                for _, xq_row in xq_catalog.iterrows():
                    xq_id_raw = xq_row.get("id")
                    if pd.notna(xq_id_raw):
                        try:
                            xq_catalog_map_approve[int(xq_id_raw)] = xq_row.to_dict()
                        except (TypeError, ValueError):
                            pass

            # Build xQ items for QUAL_REPORT
            entries_fresh = get_asset_traceability_entries(asset_id)
            mit_fresh = load_table(Tables.MITIGATION)
            entries_with_xq_fresh = entries_fresh[
                entries_fresh["xq_id"].notna()
            ] if not entries_fresh.empty and "xq_id" in entries_fresh.columns else pd.DataFrame()
            xq_items = []
            for _, xq_entry in entries_with_xq_fresh.iterrows():
                xq_id_parsed = _int_or_none(xq_entry.get("xq_id"))
                if xq_id_parsed is not None:
                    xq_info_row = get_row_by_id(Tables.XQ, xq_id_parsed)
                    if xq_info_row:
                        item = dict(xq_info_row)
                        item.update(xq_entry.to_dict())
                        # Get xq_output from mitigation table
                        mit_id = _int_or_none(xq_entry.get("mitigation_id"))
                        if mit_id is not None and not mit_fresh.empty:
                            mit_row = mit_fresh[mit_fresh["id"] == mit_id]
                            if not mit_row.empty:
                                item["xq_output"] = safe_str(mit_row.iloc[0].get("xq_output", ""))
                                item["passed"] = mit_row.iloc[0].get("passed")
                        xq_items.append(item)

            base_context = get_pdf_base_context(asset_id)
            context = {
                **base_context,
                **approved_version,
                "version": approved_version["document_version"],
                "main_requirements": main_reqs,
                "peripherals": peripherals_data,
                "xq_catalog_map": xq_catalog_map_approve,
                "xq_items": xq_items,
                "appendix_urls": [],
            }

            try:
                out_path = render_document("QUAL_REPORT", context, approved=True)
                st.success(f"Approved PDF created: {out_path}")
            except Exception as e:
                st.error(f"Error during approved export: {e}")

        st.success("Phase set to Done.")
        st.rerun()

if export_btn and not export_disabled:
    peripheral_assets_export = get_peripherals(asset_id)
    main_reqs = _build_exec_export_requirements(
        asset_id, requirement_catalog, risk_catalog, xq_catalog,
        dq_catalog, subchapter_catalog, mitigation_table, corrective_action_table
    )

    peripherals_data = []
    if not peripheral_assets_export.empty:
        for _, periph in peripheral_assets_export.iterrows():
            periph_reqs = _build_exec_export_requirements(
                int(periph["id"]), requirement_catalog, risk_catalog, xq_catalog,
                dq_catalog, subchapter_catalog, mitigation_table, corrective_action_table
            )
            periph_eq_type = get_equipment_type_by_id(periph.get("equipment_type_id"))
            periph_eq_type_desc = (
                safe_str(periph_eq_type.get("name", ""))
                if periph_eq_type else "Unknown"
            )
            peripherals_data.append({
                "name": safe_str(periph.get("name", "")),
                "equipment_type": periph_eq_type_desc,
                "requirements": periph_reqs,
            })

    # Build xQ catalog map for PDF
    xq_catalog_map_export = {}
    if not xq_catalog.empty and "id" in xq_catalog.columns:
        for _, xq_row in xq_catalog.iterrows():
            xq_id_raw = xq_row.get("id")
            if pd.notna(xq_id_raw):
                try:
                    xq_catalog_map_export[int(xq_id_raw)] = xq_row.to_dict()
                except (TypeError, ValueError):
                    pass

    # Build xQ items for QUAL_REPORT
    entries_fresh = get_asset_traceability_entries(asset_id)
    mit_fresh = load_table(Tables.MITIGATION)
    entries_with_xq_fresh = entries_fresh[
        entries_fresh["xq_id"].notna()
    ] if not entries_fresh.empty and "xq_id" in entries_fresh.columns else pd.DataFrame()
    xq_items = []
    for _, xq_entry in entries_with_xq_fresh.iterrows():
        xq_id_parsed = _int_or_none(xq_entry.get("xq_id"))
        if xq_id_parsed is not None:
            xq_info_row = get_row_by_id(Tables.XQ, xq_id_parsed)
            if xq_info_row:
                item = dict(xq_info_row)
                item.update(xq_entry.to_dict())
                # Get xq_output from mitigation table
                mit_id = _int_or_none(xq_entry.get("mitigation_id"))
                if mit_id is not None and not mit_fresh.empty:
                    mit_row = mit_fresh[mit_fresh["id"] == mit_id]
                    if not mit_row.empty:
                        item["xq_output"] = safe_str(mit_row.iloc[0].get("xq_output", ""))
                        item["passed"] = mit_row.iloc[0].get("passed")
                xq_items.append(item)

    # Record export BEFORE rendering so timestamp appears in document history
    record_document_export(asset_id, asset_phase.value)

    base_context = get_pdf_base_context(asset_id)
    version_info = get_document_version_snapshot(asset_id, asset_phase.value)
    context = {
        **base_context,
        **version_info,
        "version": version_info["document_version"],
        "main_requirements": main_reqs,
        "peripherals": peripherals_data,
        "xq_catalog_map": xq_catalog_map_export,
        "xq_items": xq_items,
        "appendix_urls": [],
    }

    try:
        out_path = render_document("QUAL_REPORT", context)
        st.success(f"PDF created: {out_path}")
    except Exception as e:
        st.error(f"Error during export: {e}")
