"""
DQ - Design Qualification assignment and management.
"""
import streamlit as st
import pandas as pd
from pathlib import Path
import sys
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from app_core.data_io import (
    load_table, save_table, get_asset_traceability_entries, insert_row,
    get_asset_phase, set_asset_phase,
    get_asset_and_peripheral_ids, record_document_export, record_document_approval,
    get_pdf_base_context, get_document_version_snapshot, get_latest_document_version_info,
    get_peripherals, get_equipment_type_by_id,
    get_asset_media, set_asset_media, delete_asset_media, get_all_media,
    get_location_hierarchy, get_asset_location, get_location_display,
    get_before_mitigation_values, get_after_mitigation_values,
    update_traceability_dq, get_row_by_id,
)
from app_core.models import Tables, Phase, Subchapter, SUBCHAPTER_LABELS
from app_core.policy import (
    get_next_phase, is_phase_gates_enabled, get_soft_warning,
    is_editable, check_phase_gate
)
from app_core.pdf import render_document
from app_core.utils import safe_str, safe_int, excel_to_bool, calculate_quantification, calculate_risk_level
from app_core.style import apply_global_style, render_sticky_header

REQUIRED_EMPTY_BG = "#fff3bf"
REQUIRED_FILLED_BG = "#e6f4ea"

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


def _css_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _sanitize_filename(value: str) -> str:
    if not value:
        return "document"
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", value)
    return safe or "document"


def _save_uploaded_mitigation_doc(uploaded_file, asset_id: int) -> str:
    """Save uploaded mitigation document. Only saves once per asset - reuses existing file if already uploaded."""
    docs_dir = Path(__file__).parent.parent / "data" / "risk_mitigation_docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    raw_name = Path(uploaded_file.name).name
    safe_name = _sanitize_filename(raw_name)
    dest = docs_dir / f"asset_{asset_id}_{safe_name}"
    # Only save if file doesn't already exist (reuse for multiple entries)
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
            row_cells.append(f"<td class=\"cell-{cell_color}\">{value}</td>")
        body_rows.append(
            f"<tr><th>{label}</th>{''.join(row_cells)}</tr>"
        )

    table_html = f"""
<div class=\"risk-matrix-wrapper\">
  <div class=\"risk-matrix-title\">{title}</div>
  <div class=\"risk-matrix-axis\">Likelihood</div>
  <table class=\"risk-matrix\">
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


def _is_filled(value, empty_values=None) -> bool:
    if empty_values and value in empty_values:
        return False
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True


def _queue_required_style(style_rules, widget_type: str, label: str, is_filled: bool) -> None:
    color = REQUIRED_FILLED_BG if is_filled else REQUIRED_EMPTY_BG
    safe_label = _css_escape(label)
    if widget_type == "text":
        style_rules.append(
            f'div[data-testid="stTextInput"] input[aria-label="{safe_label}"] {{ background-color: {color} !important; }}'
        )
        return
    if widget_type == "textarea":
        style_rules.append(
            f'div[data-testid="stTextArea"] textarea[aria-label="{safe_label}"] {{ background-color: {color} !important; }}'
        )
        return
    if widget_type == "select":
        style_rules.append(
            f'div[data-testid="stSelectbox"]:has([aria-label="{safe_label}"]) div[data-baseweb="select"] > div {{ background-color: {color} !important; }}'
        )
        style_rules.append(
            f'div[data-testid="stSelectbox"] [aria-label="{safe_label}"] {{ background-color: {color} !important; }}'
        )
    return


def _apply_required_styles(style_rules) -> None:
    if not style_rules:
        return
    st.markdown("<style>\n" + "\n".join(style_rules) + "\n</style>", unsafe_allow_html=True)


required_styles = []

st.set_page_config(page_title="Design Qualification", page_icon="DQ", layout="wide")
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
/* DQ column headers - Green (#4CAF50) */
.dq-header {
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
/* Horizontal scroll for section 5 table */
div[data-testid="stVerticalBlock"] div[data-testid="stVerticalBlock"]:has(.dq-divider-scope) {
  overflow-x: auto;
  padding-bottom: 12px;
}
div[data-testid="stVerticalBlock"] div[data-testid="stVerticalBlock"]:has(.dq-divider-scope) div[data-testid="stHorizontalBlock"] {
  min-width: 2500px;
}
</style>
""",
    unsafe_allow_html=True,
)

page_name = "02_DQ"

render_sticky_header("Design Qualification (DQ)")
st.markdown("Assign Design Qualifications to requirements.")

# Get selected asset
if "selected_asset_id" not in st.session_state or st.session_state.selected_asset_id is None:
    st.warning("Please select an asset on the Dashboard first.")
    st.stop()

asset_id = st.session_state.selected_asset_id

# Load asset from 3NF schema
asset_row_dict = get_row_by_id(Tables.ASSET, asset_id)
if not asset_row_dict:
    st.error("The selected asset was not found.")
    st.stop()

asset_name = safe_str(asset_row_dict.get("name", ""))
equipment_type_id = _int_or_none(asset_row_dict.get("equipment_type_id"))
project_id = _int_or_none(asset_row_dict.get("project_id"))

asset_phase = get_asset_phase(asset_id)

if is_phase_gates_enabled():
    gate_check = check_phase_gate(asset_phase, page_name)
    if not gate_check["allowed"]:
        st.error(gate_check["message"])
        st.stop()

soft_warning = get_soft_warning(asset_phase, page_name)
if soft_warning:
    st.warning(soft_warning)

# Load catalogs from 3NF tables
requirement_catalog = load_table(Tables.REQUIREMENT)
dq_catalog = load_table(Tables.DQ)
risk_catalog = load_table(Tables.RISK)
subchapter_table = load_table(Tables.SUBCHAPTER)

# Build subchapter lookup: id -> name
subchapter_map = {}
if not subchapter_table.empty and "id" in subchapter_table.columns:
    for _, sc_row in subchapter_table.iterrows():
        subchapter_map[int(sc_row["id"])] = safe_str(sc_row.get("name", ""))

if requirement_catalog.empty:
    st.warning("No requirement catalog found. Please initialize data first.")

# Build DQ catalog lookup maps
dq_desc_map = {}
dq_ids = []
dq_catalog_sorted = pd.DataFrame()
if not dq_catalog.empty and "id" in dq_catalog.columns:
    dq_catalog_sorted = dq_catalog.sort_values("id")
    for _, row in dq_catalog_sorted.iterrows():
        dq_id_raw = row.get("id")
        if pd.isna(dq_id_raw):
            continue
        try:
            dq_id_int = int(dq_id_raw)
        except (TypeError, ValueError):
            continue
        dq_ids.append(dq_id_int)
        dq_desc_map[dq_id_int] = safe_str(row.get("description", ""))
    dq_ids = sorted(set(dq_ids))


def _get_dq_after_fields(dq_id: Optional[int]) -> dict:
    """Get after-mitigation values for a DQ entry."""
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
    fields = get_after_mitigation_values(dq_id_int, is_xq=False)
    sev = fields.get("severity_after_mitigation")
    occ = fields.get("likelihood_after_mitigation")
    det = fields.get("detectability_after_mitigation")
    quant = fields.get("quantification_after_mitigation")
    level = fields.get("risk_level_after_mitigation", "")
    if quant is None and sev and occ and det:
        quant = calculate_quantification(sev, occ, det)
    if not level and quant is not None:
        level = calculate_risk_level(quant)
    return {
        "severity_after_mitigation": sev,
        "likelihood_after_mitigation": occ,
        "detectability_after_mitigation": det,
        "quantification_after_mitigation": quant,
        "risk_level_after_mitigation": level,
    }


def _get_before_fields(risk_id_val) -> dict:
    """Get before-mitigation values for a risk entry."""
    rid = _int_or_none(risk_id_val)
    if rid is None:
        return {
            "severity_before_mitigation": None,
            "likelihood_before_mitigation": None,
            "detectability_before_mitigation": None,
            "quantification_before_mitigation": None,
            "risk_level_before_mitigation": "",
            "mitigation_required": False,
        }
    return get_before_mitigation_values(rid)


def _build_dq_export_requirements(asset_id_local: int, req_catalog_df: pd.DataFrame) -> list[dict]:
    """Build export data for DQ PDF: merge traceability entries with requirement catalog and risk/DQ lookups."""
    entries = get_asset_traceability_entries(asset_id_local)
    if entries.empty:
        return []

    # Merge requirement details
    if not req_catalog_df.empty and "id" in req_catalog_df.columns:
        req_cols = req_catalog_df.rename(columns={"id": "requirement_id"})
        merge_cols = ["requirement_id"]
        for col in ["description", "subchapter_id", "is_must", "is_gxp"]:
            if col in req_cols.columns:
                merge_cols.append(col)
        available_cols = [c for c in merge_cols if c in req_cols.columns]
        if available_cols:
            merged = entries.merge(
                req_cols[available_cols],
                on="requirement_id",
                how="left",
            )
        else:
            merged = entries.copy()
    else:
        merged = entries.copy()

    # Deduplicate
    if {"requirement_id", "risk_id"}.issubset(merged.columns):
        merged = merged.drop_duplicates(subset=["requirement_id", "risk_id"])
    elif "requirement_id" in merged.columns:
        merged = merged.drop_duplicates(subset=["requirement_id"])

    # Enrich with risk/DQ details for each row
    records = []
    for _, row in merged.iterrows():
        rec = row.to_dict()

        # Add before-mitigation from risk table
        rid = _int_or_none(rec.get("risk_id"))
        if rid is not None:
            before = get_before_mitigation_values(rid)
            rec.update(before)

            # Look up risk description
            risk_row = get_row_by_id(Tables.RISK, rid)
            if risk_row:
                rec["possible_error"] = safe_str(risk_row.get("possible_error", ""))

        # Add after-mitigation from DQ table
        did = _int_or_none(rec.get("dq_id"))
        if did is not None:
            after = get_after_mitigation_values(did, is_xq=False)
            rec.update(after)
            rec["dq_description"] = dq_desc_map.get(did, "")

        # Resolve subchapter name
        sc_id = _int_or_none(rec.get("subchapter_id"))
        if sc_id is not None:
            rec["subchapter_name"] = subchapter_map.get(sc_id, "")

        # Map mitigation info from mitigation table if mitigation_id is set
        mit_id = _int_or_none(rec.get("mitigation_id"))
        if mit_id is not None:
            mit_row = get_row_by_id(Tables.MITIGATION, mit_id)
            if mit_row:
                rec["mitigation_status"] = safe_str(mit_row.get("status", ""))
                rec["mitigation_file_path"] = safe_str(mit_row.get("file_path", ""))

        records.append(rec)

    return records


# ============================================================================
# SECTION 1: Project / Asset
# ============================================================================
st.header("1. Project / Asset")

equipment_type_info = get_equipment_type_by_id(equipment_type_id) if equipment_type_id else None
equipment_type_desc = safe_str(equipment_type_info.get("name", "")) if equipment_type_info else "Unknown"

# Load business process step and system owner via main_asset
main_asset_table = load_table(Tables.MAIN_ASSET)
bps_name = ""
system_owner_name = ""
if not main_asset_table.empty:
    ma_row = main_asset_table[main_asset_table["asset_id"] == asset_id]
    if not ma_row.empty:
        bps_id = _int_or_none(ma_row.iloc[0].get("business_process_step_id"))
        if bps_id:
            bps_row = get_row_by_id(Tables.BUSINESS_PROCESS_STEP, bps_id)
            if bps_row:
                bps_name = safe_str(bps_row.get("name", ""))
            # Get system owner via junction table
            bps_so = load_table(Tables.BUSINESS_PROCESS_STEP_SYSTEM_OWNER)
            if not bps_so.empty:
                so_match = bps_so[bps_so["business_process_step_id"] == bps_id]
                if not so_match.empty:
                    so_id = _int_or_none(so_match.iloc[0].get("system_owner_id"))
                    if so_id:
                        so_row = get_row_by_id(Tables.SYSTEM_OWNER, so_id)
                        if so_row:
                            system_owner_name = safe_str(so_row.get("role", ""))

# Load project info
project_info = get_row_by_id(Tables.PROJECT, project_id) if project_id else None
project_name = safe_str(project_info.get("name", "")) if project_info else ""

with st.expander(f"Selected Asset: {asset_name}", expanded=True):
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Equipment Type:** {equipment_type_desc}")
        st.markdown(f"**Description:** {asset_name}")
        st.markdown(f"**Business Process Step:** {bps_name}")
    with col2:
        st.markdown(f"**System Owner:** {system_owner_name}")
        st.markdown(f"**Project:** {project_name}")

# ============================================================================
# SECTION 2: Location
# ============================================================================
st.header("2. Location")

hierarchy = get_location_hierarchy()
current_location = get_asset_location(asset_id)

if hierarchy["countries"].empty:
    st.info("No location data available. Please import location data.")
else:
    if current_location is None:
        st.warning("No location assigned.")
    else:
        loc_path = get_location_display(project_id) if project_id else ""
        if loc_path:
            st.success(f"Current location: {loc_path}")
        else:
            st.warning("No location assigned.")

    if asset_phase != Phase.URS:
        st.info("Location changes are only possible in the URS phase.")

st.divider()

# ============================================================================
# SECTION 3: Peripherals
# ============================================================================
st.header("3. Peripherals")

peripheral_assets = get_peripherals(asset_id)

if peripheral_assets.empty:
    st.info("No peripheral devices assigned.")
else:
    st.markdown("**Assigned peripheral devices:**")
    for _, periph in peripheral_assets.iterrows():
        periph_eq_type = get_equipment_type_by_id(_int_or_none(periph.get("equipment_type_id")))
        periph_eq_type_desc = safe_str(periph_eq_type.get("name", "")) if periph_eq_type else "Unknown"
        periph_name = safe_str(periph.get("name", ""))
        st.markdown(f"- **{periph_name}** ({periph_eq_type_desc})")

st.divider()

# ============================================================================
# SECTION 4: Media (Utilities & Media Connections)
# ============================================================================
st.header("4. Media")

# Load all media types from media table
all_media_df = get_all_media()
MEDIA_COLUMNS = []
if not all_media_df.empty:
    for _, m_row in all_media_df.iterrows():
        MEDIA_COLUMNS.append({
            "media_id": int(m_row["id"]),
            "label": safe_str(m_row.get("name", "")),
        })

# Build list of all assets (main + peripherals)
media_assets = [
    {
        "asset_id": asset_id,
        "asset_name": asset_name,
        "asset_type": "Main Asset",
        "equipment_type_id": equipment_type_id,
        "equipment_type_desc": equipment_type_desc,
    }
]

peripheral_assets_media = peripheral_assets
if peripheral_assets_media.empty:
    peripheral_assets_media = get_peripherals(asset_id)

if not peripheral_assets_media.empty:
    for _, periph in peripheral_assets_media.iterrows():
        periph_eq_type = get_equipment_type_by_id(_int_or_none(periph.get("equipment_type_id")))
        periph_eq_type_desc = safe_str(periph_eq_type.get("name", "")) if periph_eq_type else "Unknown"
        media_assets.append({
            "asset_id": int(periph["id"]),
            "asset_name": safe_str(periph.get("name", "")),
            "asset_type": "Peripheral",
            "equipment_type_id": _int_or_none(periph.get("equipment_type_id")),
            "equipment_type_desc": periph_eq_type_desc,
        })

# Load current media assignments for all assets
asset_media_map = {}  # {asset_id: {media_id: media_value}}
for ma in media_assets:
    asset_media_df = get_asset_media(ma["asset_id"])
    asset_media_map[ma["asset_id"]] = {}
    if not asset_media_df.empty:
        for _, am_row in asset_media_df.iterrows():
            asset_media_map[ma["asset_id"]][int(am_row["media_id"])] = safe_str(am_row.get("media_value", ""))

# Check if in URS phase for editing
can_edit_media = asset_phase == Phase.URS

if MEDIA_COLUMNS:
    # Create header row
    header_cols = st.columns([2, 1.5] + [1.5] * len(MEDIA_COLUMNS))
    header_cols[0].markdown("**Equipment Type**")
    header_cols[1].markdown("**Asset Type**")
    for i, media_info in enumerate(MEDIA_COLUMNS):
        header_cols[i + 2].markdown(f"**{media_info['label']}**")

    # Track changes for saving
    media_changes = []

    # Create a row for each asset
    for ma in media_assets:
        row_cols = st.columns([2, 1.5] + [1.5] * len(MEDIA_COLUMNS))
        row_cols[0].markdown(ma["equipment_type_desc"])
        row_cols[1].markdown(ma["asset_type"])

        current_media = asset_media_map.get(ma["asset_id"], {})

        for i, media_info in enumerate(MEDIA_COLUMNS):
            media_id = media_info["media_id"]
            current_value = current_media.get(media_id, "")
            has_media = bool(current_value)

            with row_cols[i + 2]:
                # Create unique keys for this asset and media
                cb_key = f"media_cb_{ma['asset_id']}_{media_id}"
                input_key = f"media_val_{ma['asset_id']}_{media_id}"

                if can_edit_media:
                    # Checkbox to enable/disable
                    is_checked = st.checkbox(
                        "Active",
                        value=has_media,
                        key=cb_key,
                        label_visibility="collapsed"
                    )

                    # Input field (only show if checkbox is checked)
                    if is_checked:
                        new_value = st.text_input(
                            "Value",
                            value=current_value,
                            key=input_key,
                            label_visibility="collapsed",
                            placeholder="Enter value..."
                        )
                        # Track changes
                        if new_value != current_value or not has_media:
                            media_changes.append({
                                "action": "set",
                                "asset_id": ma["asset_id"],
                                "media_id": media_id,
                                "media_value": new_value,
                            })
                    else:
                        # If unchecked but previously had media, mark for deletion
                        if has_media:
                            media_changes.append({
                                "action": "delete",
                                "asset_id": ma["asset_id"],
                                "media_id": media_id,
                            })
                else:
                    # Read-only view
                    if has_media:
                        st.markdown(f"Active: {current_value}")
                    else:
                        st.markdown("---")

    # Save button for media changes
    if can_edit_media:
        if st.button("Save Media", type="primary", key="save_media"):
            saved_count = 0
            deleted_count = 0
            for change in media_changes:
                if change["action"] == "set":
                    success = set_asset_media(
                        asset_id=change["asset_id"],
                        media_id=change["media_id"],
                        media_value=change["media_value"],
                    )
                    if success:
                        saved_count += 1
                elif change["action"] == "delete":
                    success = delete_asset_media(
                        asset_id=change["asset_id"],
                        media_id=change["media_id"],
                    )
                    if success:
                        deleted_count += 1

            if saved_count > 0 or deleted_count > 0:
                st.success(f"Media saved: {saved_count} updated, {deleted_count} removed")
                st.rerun()
            else:
                st.info("No changes to save.")
    else:
        st.info("Media can only be edited in the URS phase.")
else:
    st.info("No media types defined.")

st.divider()

# ============================================================================
# SECTION 5: Requirements
# ============================================================================
st.header("5. Requirements")

with st.expander("Show DQ Catalog", expanded=False):
    if dq_catalog_sorted.empty:
        st.info("No DQ catalog available.")
    else:
        dq_search = st.text_input("Search DQ Catalog", key="dq_catalog_search")
        filtered_dq = dq_catalog_sorted
        if dq_search:
            dq_search_lower = dq_search.strip().lower()
            filtered_dq = dq_catalog_sorted[
                dq_catalog_sorted["description"].fillna("").astype(str).str.lower().str.contains(dq_search_lower)
                | dq_catalog_sorted["id"].astype(str).str.contains(dq_search_lower)
            ]
        for _, dq_row in filtered_dq.iterrows():
            dq_id_raw = dq_row.get("id")
            if pd.isna(dq_id_raw):
                continue
            try:
                dq_id_int = int(dq_id_raw)
            except (TypeError, ValueError):
                continue
            dq_desc = safe_str(dq_row.get("description", ""))
            st.markdown(f"**DQ-{dq_id_int}:** {dq_desc}")

with st.container():
    st.markdown('<div class="dq-divider-scope"></div>', unsafe_allow_html=True)
    assets_for_requirements = [
        {
            "asset_id": asset_id,
            "asset_name": asset_name,
            "asset_type": "main",
            "equipment_type_id": equipment_type_id,
            "label": f"{asset_name} ({equipment_type_desc})"
        }
    ]

    if not peripheral_assets.empty:
        for _, periph in peripheral_assets.iterrows():
            periph_eq_type = get_equipment_type_by_id(_int_or_none(periph.get("equipment_type_id")))
            periph_eq_type_desc = safe_str(periph_eq_type.get("name", "")) if periph_eq_type else "Unknown"
            periph_name = safe_str(periph.get("name", ""))
            assets_for_requirements.append({
                "asset_id": int(periph["id"]),
                "asset_name": periph_name,
                "asset_type": "peripheral",
                "equipment_type_id": _int_or_none(periph.get("equipment_type_id")),
                "label": f"{periph_name} ({periph_eq_type_desc})"
            })

    # Load traceability entries and enrich with requirement/risk/DQ details
    requirements_by_asset = {}
    for asset_info in assets_for_requirements:
        entries = get_asset_traceability_entries(asset_info["asset_id"])
        if entries.empty:
            requirements_by_asset[asset_info["asset_id"]] = pd.DataFrame()
            continue

        # Merge requirement catalog details
        if not requirement_catalog.empty and "id" in requirement_catalog.columns:
            req_for_merge = requirement_catalog.rename(columns={"id": "requirement_id"})
            merge_cols = ["requirement_id"]
            for col in ["description", "subchapter_id", "is_must", "is_gxp", "is_standard", "remark_enabled", "remark_required"]:
                if col in req_for_merge.columns:
                    merge_cols.append(col)
            available = [c for c in merge_cols if c in req_for_merge.columns]
            merged = entries.merge(req_for_merge[available], on="requirement_id", how="left", suffixes=("", "_catalog"))
        else:
            merged = entries.copy()

        requirements_by_asset[asset_info["asset_id"]] = merged

    if not any(not df.empty for df in requirements_by_asset.values()):
        st.info("No requirements assigned.")
        st.stop()

    can_edit_dq = (
        is_editable(asset_phase, Tables.ASSET_TRACEABILITY_MATRIX, "dq_id")
    )
    can_edit_dq_meta = is_editable(asset_phase, Tables.ASSET_TRACEABILITY_MATRIX, "dq_remark")
    can_edit_mitigation = (
        is_editable(asset_phase, Tables.MITIGATION, "file_path")
        and is_editable(asset_phase, Tables.MITIGATION, "status")
    )

    save_all_clicked = st.button("Save DQ Assignments", disabled=not can_edit_dq)

    if save_all_clicked:
        changed = 0
        missing_required = set()
        missing_mitigation = set()

        for asset_info in assets_for_requirements:
            asset_id_local = asset_info["asset_id"]
            asset_label = asset_info["label"]
            asset_reqs = requirements_by_asset.get(asset_id_local)
            if asset_reqs is None or asset_reqs.empty:
                continue

            for row_idx, entry in asset_reqs.iterrows():
                requirement_id_local = _int_or_none(entry.get("requirement_id"))
                if requirement_id_local is None:
                    continue
                row_key = f"{asset_id_local}_{requirement_id_local}_{row_idx}"
                risk_id_val = entry.get("risk_id")
                risk_id_int = _int_or_none(risk_id_val)

                # Current DQ assignment from traceability matrix
                current_dq_id = _int_or_none(entry.get("dq_id"))
                current_dq_desc = dq_desc_map.get(current_dq_id, "") if current_dq_id else ""
                has_dq = current_dq_id is not None and bool(current_dq_desc.strip())
                is_must = excel_to_bool(entry.get("is_must", False))

                # Check for pre-assigned DQ
                dq_is_auto = excel_to_bool(entry.get("dq_is_auto_assign", False))
                has_preassigned_dq = dq_is_auto and current_dq_id is not None

                # Check for XQ assignment
                xq_id_val = _int_or_none(entry.get("xq_id"))
                has_default_xq = xq_id_val is not None

                # Calculate before level to determine if DQ mitigation is applicable
                before_vals = _get_before_fields(risk_id_val)
                before_level = before_vals.get("risk_level_before_mitigation", "")
                can_use_dq = before_level in ("high", "medium")

                # Check if "Solved by DQ?" checkbox is checked for this row
                solved_by_dq_key_check = f"solved_by_dq_{row_key}"
                default_checked_check = has_preassigned_dq or has_dq
                solved_by_dq_checked = bool(st.session_state.get(solved_by_dq_key_check, default_checked_check)) if can_use_dq else False

                row_changed = False

                # Only process DQ assignment if "Solved by DQ?" checkbox is checked
                if solved_by_dq_checked and not has_dq and not has_preassigned_dq:
                    select_key = f"dq_select_{row_key}"
                    manual_key = f"dq_manual_{row_key}"
                    manual_desc_key = f"dq_manual_desc_{row_key}"

                    manual_enabled = bool(st.session_state.get(manual_key, False))
                    if manual_enabled:
                        manual_desc = safe_str(st.session_state.get(manual_desc_key, "")).strip()
                        if manual_desc:
                            new_dq_id = insert_row(Tables.DQ, {"description": manual_desc})
                            if risk_id_int is not None:
                                update_traceability_dq(
                                    asset_id=asset_id_local,
                                    requirement_id=requirement_id_local,
                                    risk_id=risk_id_int,
                                    dq_id=new_dq_id,
                                )
                            row_changed = True
                        else:
                            if is_must:
                                missing_required.add(f"{asset_label} / REQ-{requirement_id_local}")
                    else:
                        selected_dq_id = st.session_state.get(select_key)
                        if selected_dq_id is None:
                            if is_must:
                                missing_required.add(f"{asset_label} / REQ-{requirement_id_local}")
                        else:
                            dq_desc = safe_str(dq_desc_map.get(selected_dq_id, "")).strip()
                            if dq_desc or selected_dq_id:
                                if risk_id_int is not None:
                                    update_traceability_dq(
                                        asset_id=asset_id_local,
                                        requirement_id=requirement_id_local,
                                        risk_id=risk_id_int,
                                        dq_id=int(selected_dq_id),
                                    )
                                row_changed = True
                            else:
                                if is_must:
                                    missing_required.add(f"{asset_label} / REQ-{requirement_id_local}")
                elif solved_by_dq_checked and has_preassigned_dq and not has_dq:
                    # Pre-assigned DQ - already set on traceability row
                    pass

                # Handle DQ remark
                remark_key = f"dq_remark_{row_key}"
                current_dq_remark = safe_str(entry.get("dq_remark", ""))
                if remark_key in st.session_state:
                    new_dq_remark = safe_str(st.session_state.get(remark_key, current_dq_remark))
                else:
                    new_dq_remark = current_dq_remark

                if new_dq_remark != current_dq_remark:
                    # Update remark on traceability matrix
                    if risk_id_int is not None and (current_dq_id is not None or _int_or_none(entry.get("dq_id")) is not None):
                        effective_dq_id = current_dq_id or _int_or_none(entry.get("dq_id"))
                        if effective_dq_id is not None:
                            update_traceability_dq(
                                asset_id=asset_id_local,
                                requirement_id=requirement_id_local,
                                risk_id=risk_id_int,
                                dq_id=effective_dq_id,
                                dq_remark=new_dq_remark,
                            )
                    row_changed = True

                # Re-read current DQ state after potential updates
                current_dq_id_now = _int_or_none(entry.get("dq_id"))
                has_risk = pd.notna(risk_id_val) and risk_id_int is not None
                has_dq_now = current_dq_id_now is not None

                # Handle mitigation record (proof / status)
                if solved_by_dq_checked and has_dq_now and has_risk:
                    proof_path_key = f"risk_proof_path_{row_key}"
                    proof_path = safe_str(st.session_state.get(proof_path_key, ""))

                    # Get or create mitigation record
                    mit_id = _int_or_none(entry.get("mitigation_id"))
                    if mit_id is None and proof_path:
                        # Create new mitigation record
                        mit_row = {
                            "risk_id": risk_id_int,
                            "phase": "DQ",
                            "file_path": proof_path,
                            "status": "done" if proof_path else "open",
                            "passed": bool(proof_path),
                            "mitigation_category_id": 1,  # DQ category
                            "remark": new_dq_remark,
                        }
                        new_mit_id = insert_row(Tables.MITIGATION, mit_row)
                        # Update mitigation_id on traceability matrix
                        tm_df = load_table(Tables.ASSET_TRACEABILITY_MATRIX)
                        if not tm_df.empty:
                            from app_core.data_io import _risk_id_equals
                            mask = (tm_df["asset_id"] == asset_id_local) & (tm_df["requirement_id"] == requirement_id_local) & _risk_id_equals(tm_df["risk_id"], risk_id_int)
                            if mask.any():
                                tm_df.loc[mask, "mitigation_id"] = new_mit_id
                                save_table(Tables.ASSET_TRACEABILITY_MATRIX, tm_df)
                        row_changed = True
                    elif mit_id is not None and proof_path:
                        # Update existing mitigation
                        from app_core.data_io import update_row
                        update_row(Tables.MITIGATION, "id", mit_id, {
                            "file_path": proof_path,
                            "status": "done",
                            "passed": True,
                        })
                        row_changed = True

                    if not has_dq_now:
                        missing_mitigation.add(f"{asset_label} / REQ-{requirement_id_local} (DQ missing)")
                    elif not has_risk:
                        missing_mitigation.add(f"{asset_label} / REQ-{requirement_id_local} (Risk missing)")
                    elif not proof_path:
                        missing_mitigation.add(f"{asset_label} / REQ-{requirement_id_local} (Proof missing)")

                if row_changed:
                    changed += 1

        if changed:
            st.success(f"{changed} DQ assignment(s) saved.")
        else:
            st.info("No changes to save.")

        if missing_required:
            st.error("Missing required DQ for: " + ", ".join(sorted(missing_required)))
        if missing_mitigation:
            st.error("Missing risk mitigations/proof for: " + ", ".join(sorted(missing_mitigation)))

        st.rerun()

    missing_required_dq = set()

    for asset_info in assets_for_requirements:
        asset_id_local = asset_info["asset_id"]
        asset_label = asset_info["label"]
        section_title = "Main Asset" if asset_info["asset_type"] == "main" else "Peripheral"
        st.subheader(f"{section_title}: {asset_label}")

        asset_reqs = requirements_by_asset.get(asset_id_local)
        if asset_reqs is None or asset_reqs.empty:
            st.caption("No requirements assigned.")
            continue

        # Group by subchapter: map subchapter_id to Subchapter enum name
        # Build reverse map: subchapter name -> subchapter_id
        subchapter_name_to_id = {}
        for sc_id, sc_name in subchapter_map.items():
            subchapter_name_to_id[sc_name] = sc_id

        for subchapter in Subchapter:
            chapter_label = SUBCHAPTER_LABELS[subchapter]
            st.markdown(f"**{chapter_label}**")
            indent_cols = st.columns([0.04, 0.96], gap="small")
            with indent_cols[1]:
                # Filter by subchapter_id matching the Subchapter enum value
                sc_id_for_filter = subchapter_name_to_id.get(subchapter.value)
                if sc_id_for_filter is not None and "subchapter_id" in asset_reqs.columns:
                    sub_reqs = asset_reqs[asset_reqs["subchapter_id"] == sc_id_for_filter].copy()
                else:
                    sub_reqs = pd.DataFrame()

                if not sub_reqs.empty and "requirement_id" in sub_reqs.columns:
                    # Sort by requirement_id, then risk_id, then dq_id
                    sub_reqs["__risk_sort"] = sub_reqs.get("risk_id").apply(_int_or_none)
                    sub_reqs["__dq_sort"] = sub_reqs.get("dq_id").apply(_int_or_none)
                    sub_reqs = sub_reqs.sort_values(
                        ["requirement_id", "__risk_sort", "__dq_sort"],
                        na_position="last"
                    ).drop(columns=["__risk_sort", "__dq_sort"])

                if sub_reqs.empty:
                    st.caption("No requirements in this subchapter.")
                else:
                    # Column order: ID, Requirement, Remark, GxP, Must-Have, Risk-ID, Risk Title,
                    # S (before), O (before), D (before), RPN (before), Level (before), Mitigation?, Solved by DQ?,
                    # DQ-ID, DQ Description, Proof, S (after), O (after), D (after), RPN (after), Level (after), DQ Remark
                    column_widths = [
                        0.6, 2.2, 1.0, 0.5, 0.7,                                #blue
                        0.7, 1.2, 0.6, 0.6, 0.6, 0.65, 0.7, 0.75,               #yellow
                        0.95, 0.7, 1.4, 1.2, 0.6, 0.6, 0.6, 0.65, 0.75, 1.2     #green
                    ]
                    header_cols = st.columns(column_widths, gap="small")
                    # URS columns (0-4): Blue background
                    header_cols[0].markdown('<span class="urs-header">ID</span>', unsafe_allow_html=True)
                    header_cols[1].markdown('<span class="urs-header">Requirement</span>', unsafe_allow_html=True)
                    header_cols[2].markdown('<span class="urs-header">Remark</span>', unsafe_allow_html=True)
                    header_cols[3].markdown('<span class="urs-header">GxP</span>', unsafe_allow_html=True)
                    header_cols[4].markdown('<span class="urs-header">Must-Have</span>', unsafe_allow_html=True)
                    # Risk columns (5-12): Yellow background
                    header_cols[5].markdown('<span class="risk-header">Risk-ID</span>', unsafe_allow_html=True)
                    header_cols[6].markdown('<span class="risk-header">Risk Title</span>', unsafe_allow_html=True)
                    header_cols[7].markdown('<span class="risk-header">S (before)</span>', unsafe_allow_html=True)
                    header_cols[8].markdown('<span class="risk-header">O (before)</span>', unsafe_allow_html=True)
                    header_cols[9].markdown('<span class="risk-header">D (before)</span>', unsafe_allow_html=True)
                    header_cols[10].markdown('<span class="risk-header">RPN (before)</span>', unsafe_allow_html=True)
                    header_cols[11].markdown('<span class="risk-header">Level (before)</span>', unsafe_allow_html=True)
                    header_cols[12].markdown('<span class="risk-header">Mitigation?</span>', unsafe_allow_html=True)
                    # DQ columns (13-22): Green background
                    header_cols[13].markdown('<span class="dq-header">Solved by DQ?</span>', unsafe_allow_html=True)
                    header_cols[14].markdown('<span class="dq-header">DQ-ID</span>', unsafe_allow_html=True)
                    header_cols[15].markdown('<span class="dq-header">DQ Description</span>', unsafe_allow_html=True)
                    header_cols[16].markdown('<span class="dq-header">Proof</span>', unsafe_allow_html=True)
                    header_cols[17].markdown('<span class="dq-header">S (after)</span>', unsafe_allow_html=True)
                    header_cols[18].markdown('<span class="dq-header">O (after)</span>', unsafe_allow_html=True)
                    header_cols[19].markdown('<span class="dq-header">D (after)</span>', unsafe_allow_html=True)
                    header_cols[20].markdown('<span class="dq-header">RPN (after)</span>', unsafe_allow_html=True)
                    header_cols[21].markdown('<span class="dq-header">Level (after)</span>', unsafe_allow_html=True)
                    header_cols[22].markdown('<span class="dq-header">DQ Remark</span>', unsafe_allow_html=True)

                    grouped_reqs = sub_reqs.groupby("requirement_id", sort=False)
                    for group_idx, (requirement_id_local, group) in enumerate(grouped_reqs):
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
                            row_key = f"{asset_id_local}_{requirement_id_local}_{row_idx}"

                            row_cols = st.columns(column_widths, gap="small")

                            # Columns 0-4: ID, Requirement, Remark, GxP, Must-Have
                            if is_first_row:
                                row_cols[0].markdown(f"REQ-{requirement_id_local}")
                                row_cols[1].markdown(requirement_text)
                                row_cols[2].markdown(remark_text or "")
                                row_cols[3].markdown("Yes" if is_gxp else "No")
                                row_cols[4].markdown("Yes" if is_must else "No")
                            else:
                                row_cols[0].markdown("")
                                row_cols[1].markdown("")
                                row_cols[2].markdown("")
                                row_cols[3].markdown("")
                                row_cols[4].markdown("")

                            # Columns 5-6: Risk-ID, Risk Title
                            risk_id_val = entry.get("risk_id")
                            risk_id_int = _int_or_none(risk_id_val)
                            has_risk = risk_id_int is not None
                            risk_key = risk_id_int
                            show_risk = risk_key not in seen_risks
                            if show_risk:
                                seen_risks.add(risk_key)

                            # Look up risk details from risk catalog
                            risk_title_val = ""
                            if has_risk:
                                risk_row_data = get_row_by_id(Tables.RISK, risk_id_int)
                                if risk_row_data:
                                    risk_title_val = safe_str(risk_row_data.get("possible_error", ""))

                            if show_risk:
                                if has_risk:
                                    row_cols[5].markdown(f"Risk-{risk_id_int}")
                                else:
                                    row_cols[5].markdown("--")
                                row_cols[6].markdown(risk_title_val or "")
                            else:
                                row_cols[5].markdown("")
                                row_cols[6].markdown("")

                            # Columns 7-11: S (before), O (before), D (before), RPN (before), Level (before)
                            before_vals = _get_before_fields(risk_id_val)
                            before_sev = before_vals.get("severity_before_mitigation")
                            before_occ = before_vals.get("likelihood_before_mitigation")
                            before_det = before_vals.get("detectability_before_mitigation")
                            before_quant = before_vals.get("quantification_before_mitigation")
                            before_level = before_vals.get("risk_level_before_mitigation", "")

                            if show_risk:
                                row_cols[7].markdown(str(before_sev) if before_sev else "")
                                row_cols[8].markdown(str(before_occ) if before_occ else "")
                                row_cols[9].markdown(str(before_det) if before_det else "")
                                row_cols[10].markdown(str(before_quant) if before_quant else "")
                                before_icon = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(before_level, "⚪")
                                before_label = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH"}.get(before_level, "")
                                row_cols[11].markdown(f"{before_icon} {before_label}" if before_level else "")
                            else:
                                row_cols[7].markdown("")
                                row_cols[8].markdown("")
                                row_cols[9].markdown("")
                                row_cols[10].markdown("")
                                row_cols[11].markdown("")

                            # Column 12: Mitigation? (Y/N based on Level before)
                            mitigation_required_flag = before_level in ("high", "medium")
                            mitigation_icon = "Y" if mitigation_required_flag else "N"
                            if show_risk:
                                row_cols[12].markdown(mitigation_icon)
                            else:
                                row_cols[12].markdown("")

                            # Current DQ assignment from traceability matrix
                            current_dq_id = _int_or_none(entry.get("dq_id"))
                            current_dq_desc = dq_desc_map.get(current_dq_id, "") if current_dq_id else ""
                            has_dq = current_dq_id is not None and bool(current_dq_desc.strip())

                            # Check for pre-assigned DQ
                            dq_is_auto = excel_to_bool(entry.get("dq_is_auto_assign", False))
                            has_preassigned_dq = dq_is_auto and current_dq_id is not None

                            # Check for XQ assignment
                            xq_id_val = _int_or_none(entry.get("xq_id"))
                            has_default_xq = xq_id_val is not None

                            # Column 13: Solved by DQ? checkbox
                            solved_by_dq_key = f"solved_by_dq_{row_key}"
                            can_use_dq_mitigation = before_level in ("high", "medium")

                            if not can_use_dq_mitigation:
                                # LOW level - show n/a
                                row_cols[13].markdown("n/a")
                                solved_by_dq = False
                            else:
                                # MEDIUM or HIGH level - show checkbox
                                default_checked = has_preassigned_dq or has_dq
                                if solved_by_dq_key not in st.session_state:
                                    st.session_state[solved_by_dq_key] = default_checked
                                if has_preassigned_dq:
                                    st.session_state[solved_by_dq_key] = True
                                checkbox_disabled = not can_edit_dq or has_preassigned_dq
                                solved_by_dq = row_cols[13].checkbox(
                                    "DQ",
                                    key=solved_by_dq_key,
                                    disabled=checkbox_disabled,
                                    label_visibility="collapsed",
                                )
                                if has_default_xq:
                                    row_cols[13].caption("xQ pre-assigned")

                            # Columns 14-22: Only shown if "Solved by DQ?" is checked
                            if not can_use_dq_mitigation or not solved_by_dq:
                                # Show empty columns for DQ-ID through DQ Remark
                                row_cols[14].markdown("")  # DQ-ID
                                row_cols[15].markdown("")  # DQ Description
                                row_cols[16].markdown("")  # Proof
                                row_cols[17].markdown("")  # S (after)
                                row_cols[18].markdown("")  # O (after)
                                row_cols[19].markdown("")  # D (after)
                                row_cols[20].markdown("")  # RPN (after)
                                row_cols[21].markdown("")  # Level (after)
                                row_cols[22].markdown("")  # DQ Remark
                            else:
                                # Solved by DQ is checked - show DQ assignment fields
                                # Columns 14-15: DQ-ID, DQ Description
                                selected_dq_id = None
                                if has_dq:
                                    row_cols[14].markdown(f"DQ-{int(current_dq_id)}")
                                    row_cols[15].markdown(current_dq_desc)
                                elif has_preassigned_dq:
                                    # Pre-assigned - user cannot change
                                    row_cols[14].markdown(f"DQ-{int(current_dq_id)} (predefined)")
                                    row_cols[15].markdown(current_dq_desc or dq_desc_map.get(current_dq_id, ""))
                                else:
                                    if can_edit_dq:
                                        select_label = f"DQ Catalog [{row_key}]"
                                        select_key = f"dq_select_{row_key}"
                                        manual_key = f"dq_manual_{row_key}"
                                        manual_desc_key = f"dq_manual_desc_{row_key}"

                                        manual_enabled = bool(st.session_state.get(manual_key, False))
                                        fs_options = [None] + dq_ids
                                        default_dq_id = None
                                        if current_dq_id is not None:
                                            if current_dq_id in dq_desc_map:
                                                default_dq_id = current_dq_id
                                        default_index = fs_options.index(default_dq_id) if default_dq_id in fs_options else 0

                                        selected_dq_id = row_cols[14].selectbox(
                                            select_label,
                                            fs_options,
                                            index=default_index,
                                            key=select_key,
                                            disabled=manual_enabled or not can_edit_dq,
                                            label_visibility="collapsed",
                                            format_func=lambda x: "-- Please select --" if x is None else f"DQ-{x}: {dq_desc_map.get(x, '')}"
                                        )

                                        manual_enabled = row_cols[15].checkbox(
                                            "No matching entry in DQ catalog",
                                            key=manual_key,
                                            disabled=not can_edit_dq
                                        )

                                        if manual_enabled:
                                            manual_label = f"DQ Description (new) [{row_key}]"
                                            manual_desc = row_cols[15].text_area(
                                                manual_label,
                                                value=safe_str(st.session_state.get(manual_desc_key, "")),
                                                key=manual_desc_key,
                                                label_visibility="collapsed",
                                                placeholder="Enter DQ description...",
                                                height=80,
                                                disabled=not can_edit_dq
                                            )
                                            if is_must:
                                                _queue_required_style(required_styles, "textarea", manual_label, _is_filled(manual_desc))
                                                if not _is_filled(manual_desc):
                                                    missing_required_dq.add(f"{asset_label} / REQ-{requirement_id_local}")
                                                    row_cols[15].error("Required field")
                                        else:
                                            selected_desc = safe_str(dq_desc_map.get(selected_dq_id, ""))
                                            if selected_desc:
                                                row_cols[15].markdown(selected_desc)
                                            if is_must:
                                                _queue_required_style(required_styles, "select", select_label, selected_dq_id is not None)
                                                if selected_dq_id is None:
                                                    missing_required_dq.add(f"{asset_label} / REQ-{requirement_id_local}")
                                                    row_cols[14].error("Required field")
                                    else:
                                        row_cols[14].markdown("")
                                        row_cols[15].markdown("")

                                # Column 16: Proof
                                # Read proof from mitigation table if mitigation_id exists
                                current_proof = ""
                                mit_id = _int_or_none(entry.get("mitigation_id"))
                                if mit_id is not None:
                                    mit_row = get_row_by_id(Tables.MITIGATION, mit_id)
                                    if mit_row:
                                        current_proof = safe_str(mit_row.get("file_path", ""))

                                proof_upload_key = f"risk_proof_upload_{row_key}"
                                proof_path_key = f"risk_proof_path_{row_key}"
                                proof_sig_key = f"risk_proof_sig_{row_key}"

                                if can_edit_mitigation and has_risk:
                                    proof_label = f"Proof [{row_key}]"
                                    uploaded_file = row_cols[16].file_uploader(
                                        proof_label,
                                        key=proof_upload_key,
                                        label_visibility="collapsed",
                                        disabled=not can_edit_mitigation,
                                    )
                                    if uploaded_file is not None:
                                        upload_sig = (uploaded_file.name, uploaded_file.size)
                                        if st.session_state.get(proof_sig_key) != upload_sig:
                                            saved_path = _save_uploaded_mitigation_doc(uploaded_file, asset_id_local)
                                            st.session_state[proof_path_key] = saved_path
                                            st.session_state[proof_sig_key] = upload_sig
                                    proof_display = st.session_state.get(proof_path_key, current_proof)
                                    if proof_display:
                                        row_cols[16].caption(proof_display)
                                    else:
                                        row_cols[16].caption("Proof required")
                                else:
                                    proof_display = st.session_state.get(proof_path_key, current_proof)
                                    if proof_display:
                                        row_cols[16].caption(proof_display)
                                    else:
                                        row_cols[16].markdown("")

                                # Columns 17-21: S (after), O (after), D (after), RPN (after), Level (after)
                                dq_id_for_after = None
                                if has_dq or has_preassigned_dq:
                                    dq_id_for_after = current_dq_id
                                elif selected_dq_id is not None:
                                    dq_id_for_after = selected_dq_id

                                after_fields = _get_dq_after_fields(dq_id_for_after)
                                disp_sev = after_fields.get("severity_after_mitigation")
                                disp_occ = after_fields.get("likelihood_after_mitigation")
                                disp_det = after_fields.get("detectability_after_mitigation")
                                disp_quant = after_fields.get("quantification_after_mitigation")
                                disp_level = after_fields.get("risk_level_after_mitigation", "")

                                row_cols[17].markdown(str(disp_sev) if disp_sev else "")
                                row_cols[18].markdown(str(disp_occ) if disp_occ else "")
                                row_cols[19].markdown(str(disp_det) if disp_det else "")

                                if disp_quant is None and disp_sev and disp_occ and disp_det:
                                    disp_quant = calculate_quantification(disp_sev, disp_occ, disp_det)
                                if not disp_level and disp_quant is not None:
                                    disp_level = calculate_risk_level(disp_quant)

                                if disp_quant is not None:
                                    level_icon = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(disp_level, "⚪")
                                    level_display = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH"}.get(disp_level, "")
                                    row_cols[20].markdown(str(disp_quant))
                                    row_cols[21].markdown(f"{level_icon} {level_display}" if disp_level else "")
                                else:
                                    row_cols[20].markdown("")
                                    row_cols[21].markdown("")

                                # Column 22: DQ Remark
                                current_dq_remark = safe_str(entry.get("dq_remark", ""))
                                remark_key = f"dq_remark_{row_key}"

                                if can_edit_dq_meta:
                                    remark_label = f"DQ Remark [{row_key}]"
                                    row_cols[22].text_area(
                                        remark_label,
                                        value=safe_str(st.session_state.get(remark_key, current_dq_remark)),
                                        key=remark_key,
                                        label_visibility="collapsed",
                                        placeholder="Optional remark...",
                                        height=80,
                                        disabled=not can_edit_dq_meta
                                    )
                                else:
                                    row_cols[22].markdown(current_dq_remark or "")

if can_edit_dq and missing_required_dq:
    st.error("Missing required DQ for: " + ", ".join(sorted(missing_required_dq)))

st.divider()

# ============================================================================
# SECTION 6: Risk Matrix
# ============================================================================
st.header("6. Risk Matrix")

all_entries = []
for asset_info in assets_for_requirements:
    asset_reqs = requirements_by_asset.get(asset_info["asset_id"])
    if asset_reqs is not None and not asset_reqs.empty:
        all_entries.append(asset_reqs)

combined_entries = pd.concat(all_entries, ignore_index=True) if all_entries else pd.DataFrame()

before_rows = []
after_rows = []
if not combined_entries.empty:
    assigned = combined_entries[combined_entries["risk_id"].notna()]
    if {"requirement_id", "risk_id"}.issubset(assigned.columns):
        dedupe_cols = ["requirement_id", "risk_id"]
        if "asset_id" in assigned.columns:
            dedupe_cols.insert(0, "asset_id")
        assigned = assigned.drop_duplicates(subset=dedupe_cols)
    for _, entry in assigned.iterrows():
        risk_id_val = _int_or_none(entry.get("risk_id"))
        before_vals = _get_before_fields(risk_id_val)
        sev_before = before_vals.get("severity_before_mitigation")
        occ_before = before_vals.get("likelihood_before_mitigation")
        det_before = before_vals.get("detectability_before_mitigation")
        before_rows.append((sev_before, occ_before, det_before))

        # Check if this risk has a DQ mitigation
        dq_id_val = _int_or_none(entry.get("dq_id"))

        if dq_id_val is not None:
            after_vals = _get_dq_after_fields(dq_id_val)
            sev_after = after_vals.get("severity_after_mitigation")
            occ_after = after_vals.get("likelihood_after_mitigation")
            det_after = after_vals.get("detectability_after_mitigation")
            if sev_after is not None and occ_after is not None and det_after is not None:
                after_rows.append((sev_after, occ_after, det_after))
            else:
                after_rows.append((sev_before, occ_before, det_before))
        else:
            after_rows.append((sev_before, occ_before, det_before))

before_counts = _build_matrix_counts(before_rows)
after_counts = _build_matrix_counts(after_rows)

st.markdown(MATRIX_STYLE, unsafe_allow_html=True)
col_left, col_right = st.columns(2)
with col_left:
    _render_risk_matrix("Before Mitigation", before_counts)
with col_right:
    _render_risk_matrix("After DQ Mitigation", after_counts)

st.divider()

# ============================================================================
# SECTION 7: PDF Export
# ============================================================================
st.header("7. Export DQ Document")

# Validate DQ mitigations
missing_dq_for_checked = []  # Checked but no DQ-ID
high_level_after = []  # Level (after) is HIGH
missing_proof = []  # No proof attached

for asset_info in assets_for_requirements:
    asset_id_local = asset_info["asset_id"]
    asset_label = asset_info["label"]
    entries = get_asset_traceability_entries(asset_id_local)
    if entries.empty:
        continue

    for row_idx, entry in entries.iterrows():
        requirement_id_local = _int_or_none(entry.get("requirement_id"))
        risk_id_val = entry.get("risk_id")
        row_key = f"{asset_id_local}_{requirement_id_local}_{row_idx}"

        # Current DQ assignment
        current_dq_id = _int_or_none(entry.get("dq_id"))
        current_dq_desc = dq_desc_map.get(current_dq_id, "") if current_dq_id else ""
        has_dq = current_dq_id is not None and bool(current_dq_desc.strip())

        # Check for pre-assigned DQ
        dq_is_auto = excel_to_bool(entry.get("dq_is_auto_assign", False))
        has_preassigned_dq = dq_is_auto and current_dq_id is not None

        # Calculate before level
        before_vals = _get_before_fields(risk_id_val)
        before_level = before_vals.get("risk_level_before_mitigation", "")

        # Skip LOW level risks
        can_use_dq_mitigation = before_level in ("high", "medium")
        if not can_use_dq_mitigation:
            continue

        solved_by_dq_key = f"solved_by_dq_{row_key}"
        default_checked = has_preassigned_dq or has_dq
        is_solved_by_dq = bool(st.session_state.get(solved_by_dq_key, default_checked))

        if not is_solved_by_dq:
            continue

        # Validation 1: Must have DQ-ID if checkbox is checked
        if not has_dq and not has_preassigned_dq:
            missing_dq_for_checked.append(f"REQ-{requirement_id_local} ({asset_label})")

        # Validation 2: Level (after) must not be HIGH
        if current_dq_id is not None:
            after_vals = _get_dq_after_fields(current_dq_id)
            after_sev = after_vals.get("severity_after_mitigation")
            after_occ = after_vals.get("likelihood_after_mitigation")
            after_det = after_vals.get("detectability_after_mitigation")
            if after_sev and after_occ and after_det:
                after_quant = calculate_quantification(after_sev, after_occ, after_det)
                after_level = calculate_risk_level(after_quant)
                if after_level == "high":
                    high_level_after.append(f"REQ-{requirement_id_local} ({asset_label})")

        # Validation 3: Must have proof attached
        current_proof = ""
        mit_id = _int_or_none(entry.get("mitigation_id"))
        if mit_id is not None:
            mit_row = get_row_by_id(Tables.MITIGATION, mit_id)
            if mit_row:
                current_proof = safe_str(mit_row.get("file_path", ""))
        proof_path_key = f"risk_proof_path_{row_key}"
        proof_display = st.session_state.get(proof_path_key, current_proof)
        if not proof_display:
            missing_proof.append(f"REQ-{requirement_id_local} ({asset_label})")

# Display validation errors/warnings
if missing_dq_for_checked:
    st.error(f"Missing DQ assignment for checked risks: {', '.join(missing_dq_for_checked)}")

if high_level_after:
    st.warning(f"Risk level after mitigation is HIGH - not acceptable: {', '.join(high_level_after)}. The risk level after mitigation must not be HIGH.")

if missing_proof:
    st.error(f"Missing proof for checked risks: {', '.join(missing_proof)}")

# Determine if export/approve buttons should be enabled
has_validation_errors = bool(missing_dq_for_checked) or bool(high_level_after) or bool(missing_proof)

col_export, col_approve = st.columns([1, 1])

with col_export:
    export_disabled = asset_phase != Phase.DQ or has_validation_errors
    export_btn = st.button(
        "Create DQ (PDF)",
        type="primary",
        disabled=export_disabled
    )

with col_approve:
    approve_disabled = asset_phase != Phase.DQ or has_validation_errors
    approve_btn = st.button("Approve DQ", disabled=approve_disabled)

if approve_btn:
    doc_type = asset_phase.value
    target_phase = get_next_phase(Phase.DQ)
    asset_ids = get_asset_and_peripheral_ids(asset_id)
    if target_phase and set_asset_phase(asset_ids, Phase.DQ):
        record_document_approval(asset_id, doc_type)

        # Mark DQ mitigations as done
        for aid in asset_ids:
            tm_entries = get_asset_traceability_entries(aid)
            if not tm_entries.empty:
                for _, tm_entry in tm_entries.iterrows():
                    mit_id = _int_or_none(tm_entry.get("mitigation_id"))
                    dq_id_check = _int_or_none(tm_entry.get("dq_id"))
                    if mit_id is not None and dq_id_check is not None:
                        from app_core.data_io import update_row
                        update_row(Tables.MITIGATION, "id", mit_id, {"status": "done"})

        approved_version = get_latest_document_version_info(asset_id, doc_type)
        if not approved_version:
            st.error("Could not create approved PDF: No document version found. Please export first.")
        else:
            peripheral_assets_export = get_peripherals(asset_id)
            main_reqs = _build_dq_export_requirements(asset_id, requirement_catalog)

            peripherals_data = []
            if not peripheral_assets_export.empty:
                for _, periph in peripheral_assets_export.iterrows():
                    periph_reqs = _build_dq_export_requirements(int(periph["id"]), requirement_catalog)
                    periph_eq_type = get_equipment_type_by_id(_int_or_none(periph.get("equipment_type_id")))
                    periph_eq_type_desc = (
                        safe_str(periph_eq_type.get("name", ""))
                        if periph_eq_type else "Unknown"
                    )
                    peripherals_data.append({
                        "name": safe_str(periph.get("name", "")),
                        "equipment_type": periph_eq_type_desc,
                        "requirements": periph_reqs,
                    })

            base_context = get_pdf_base_context(asset_id)
            context = {
                **base_context,
                **approved_version,
                "version": approved_version["document_version"],
                "main_requirements": main_reqs,
                "peripherals": peripherals_data,
                "appendix_urls": [],
            }

            try:
                out_path = render_document("DQ", context, approved=True)
                st.success(f"Approved PDF created: {out_path}")
            except Exception as e:
                st.error(f"Error during approved export: {e}")

        st.success("Phase set to xQ Plan.")
        st.rerun()

if export_btn and not export_disabled:
    peripheral_assets_export = get_peripherals(asset_id)
    main_reqs = _build_dq_export_requirements(asset_id, requirement_catalog)

    peripherals_data = []
    if not peripheral_assets_export.empty:
        for _, periph in peripheral_assets_export.iterrows():
            periph_reqs = _build_dq_export_requirements(int(periph["id"]), requirement_catalog)
            periph_eq_type = get_equipment_type_by_id(_int_or_none(periph.get("equipment_type_id")))
            periph_eq_type_desc = (
                safe_str(periph_eq_type.get("name", ""))
                if periph_eq_type else "Unknown"
            )
            peripherals_data.append({
                "name": safe_str(periph.get("name", "")),
                "equipment_type": periph_eq_type_desc,
                "requirements": periph_reqs,
            })

    base_context = get_pdf_base_context(asset_id)
    record_document_export(asset_id, asset_phase.value)
    version_info = get_document_version_snapshot(asset_id, asset_phase.value)
    context = {
        **base_context,
        **version_info,
        "version": version_info["document_version"],
        "main_requirements": main_reqs,
        "peripherals": peripherals_data,
        "appendix_urls": [],
    }

    try:
        out_path = render_document("DQ", context)
        st.success(f"PDF created: {out_path}")
    except Exception as e:
        st.error(f"Error during export: {e}")

_apply_required_styles(required_styles)
