
"""
Risk Assignment - initial risk assignment and evaluation.
"""
import streamlit as st
import pandas as pd
from pathlib import Path
import sys
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from app_core.data_io import (
    load_table, save_table, get_asset_traceability_entries, insert_row,
    add_additional_risk_to_asset, update_traceability_risk,
    get_default_risks_for_requirement, get_asset_phase, set_asset_phase,
    get_asset_and_peripheral_ids, record_document_export, record_document_approval,
    get_pdf_base_context, get_document_version_snapshot, get_latest_document_version_info,
    get_peripherals, get_equipment_type_by_id,
    get_asset_media, set_asset_media, delete_asset_media,
    get_location_hierarchy, get_location_display,
    get_before_mitigation_values,
)
from app_core.models import Tables, Phase, Subchapter, SUBCHAPTER_LABELS
from app_core.policy import (
    get_next_phase, is_phase_gates_enabled, get_soft_warning,
    is_editable, check_phase_gate
)
from app_core.pdf import render_document
from app_core.utils import safe_str, safe_int, calculate_quantification, calculate_risk_level, excel_to_bool
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



def get_suggested_risk_id(requirement_id: int) -> tuple:
    """
    Get suggested risk_id for a requirement entry.
    Returns (risk_id, source) where source is 'default' or None.
    """
    default_risks = get_default_risks_for_requirement(requirement_id)
    if default_risks:
        return (int(default_risks[0].get("risk_id")), "default")

    return (None, None)


def _int_or_none(value):
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _risk_id_equals(value, target) -> bool:
    if target is None or (isinstance(target, float) and pd.isna(target)):
        return value is None or (isinstance(value, float) and pd.isna(value))
    try:
        return int(value) == int(target)
    except (TypeError, ValueError):
        return False


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


st.set_page_config(page_title="Risk Assignment", page_icon="⚠️", layout="wide")
apply_global_style()

# CSS for colored column headers and vertical divider (matching PDF color scheme)
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
</style>
""",
    unsafe_allow_html=True,
)

page_name = "03_Risk_Assessment"

render_sticky_header("Risk Assignment")
st.markdown("Assign risks and record before-mitigation assessments.")

# Get selected asset
if "selected_asset_id" not in st.session_state or st.session_state.selected_asset_id is None:
    st.warning("Please select an asset on the Dashboard first.")
    st.stop()

asset_id = st.session_state.selected_asset_id

assets_df = load_table(Tables.ASSET)
asset_row = assets_df[assets_df["id"] == asset_id]
if asset_row.empty:
    st.error("The selected asset was not found.")
    st.stop()

asset = asset_row.iloc[0]
asset_name = asset["name"]

asset_phase = get_asset_phase(asset_id)

if is_phase_gates_enabled():
    gate_check = check_phase_gate(asset_phase, page_name)
    if not gate_check["allowed"]:
        st.error(gate_check["message"])
        st.stop()

soft_warning = get_soft_warning(asset_phase, page_name)
if soft_warning:
    st.warning(soft_warning)

# Load catalogs
risk_catalog = load_table(Tables.RISK)
requirement_catalog = load_table(Tables.REQUIREMENT)
subchapter_df = load_table(Tables.SUBCHAPTER)

# Build subchapter ID -> name map
subchapter_id_map = {}
if not subchapter_df.empty:
    for _, sc_row in subchapter_df.iterrows():
        subchapter_id_map[int(sc_row["id"])] = safe_str(sc_row.get("name", ""))

st.subheader(f"Asset: {asset_name}")

# ============================================================================
# SECTION 1: Project / Asset
# ============================================================================
st.header("1. Project / Asset")

equipment_type_info = get_equipment_type_by_id(asset.get("equipment_type_id"))
equipment_type_desc = (
    equipment_type_info.get("name", "Unknown")
    if equipment_type_info
    else "Unknown"
)

# Get project info for display
project_id = _int_or_none(asset.get("project_id"))
base_context = get_pdf_base_context(asset_id)

with st.expander(f"Selected Asset: {asset_name}", expanded=True):
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Equipment Type:** {equipment_type_desc}")
        st.markdown(f"**Description:** {asset_name}")
        st.markdown(f"**Business Process Step:** {base_context.get('business_process_step', '')}")
    with col2:
        st.markdown(f"**System Owner:** {base_context.get('system_owner_role', '')}")
        st.markdown(f"**Project:** {base_context.get('project_name', '')}")

# ============================================================================
# SECTION 2: Location
# ============================================================================
st.header("2. Location")

hierarchy = get_location_hierarchy()

if hierarchy["countries"].empty:
    st.info("No location data available. Please import location data.")
else:
    if project_id is None:
        st.warning("No location assigned.")
    else:
        loc_path = get_location_display(project_id)
        if loc_path:
            st.success(f"Current Location: {loc_path}")
        else:
            st.warning("No location assigned.")

    if asset_phase != Phase.URS:
        st.info("Location changes are only allowed in the URS phase.")

st.divider()

# ============================================================================
# SECTION 3: Peripherals
# ============================================================================
st.header("3. Peripherals")

peripheral_assets = get_peripherals(asset_id)

if peripheral_assets.empty:
    st.info("No peripheral devices assigned.")
else:
    st.markdown("**Assigned Peripheral Devices:**")
    for _, periph in peripheral_assets.iterrows():
        periph_eq_type = get_equipment_type_by_id(periph.get("equipment_type_id"))
        periph_eq_type_desc = (
            periph_eq_type.get("name", "Unknown") if periph_eq_type else "Unknown"
        )
        st.markdown(f"- **{periph['name']}** ({periph_eq_type_desc})")

st.divider()

# ============================================================================
# SECTION 4: Media (Utilities & Media Connections)
# ============================================================================
st.header("4. Media")

# Load media types from the media table
media_table = load_table(Tables.MEDIA)
MEDIA_COLUMNS = []
if not media_table.empty:
    for _, m_row in media_table.iterrows():
        MEDIA_COLUMNS.append({
            "media_id": int(m_row["id"]),
            "label": safe_str(m_row.get("name", f"Media {m_row['id']}")),
        })
else:
    # Fallback: define known media types
    MEDIA_COLUMNS = [
        {"media_id": 1, "label": "Power"},
        {"media_id": 2, "label": "Compressed Air"},
        {"media_id": 4, "label": "Cooling Water"},
        {"media_id": 5, "label": "Ethernet"},
        {"media_id": 3, "label": "Purified Water"},
    ]

# Build list of all assets (main + peripherals)
media_assets = [
    {
        "asset_id": asset_id,
        "asset_name": asset_name,
        "asset_type": "Main Asset",
        "equipment_type_id": asset.get("equipment_type_id"),
        "equipment_type_desc": equipment_type_desc,
    }
]

peripheral_assets_media = peripheral_assets
if peripheral_assets_media.empty:
    peripheral_assets_media = get_peripherals(asset_id)

if not peripheral_assets_media.empty:
    for _, periph in peripheral_assets_media.iterrows():
        periph_eq_type = get_equipment_type_by_id(periph.get("equipment_type_id"))
        periph_eq_type_desc = (
            periph_eq_type.get("name", "Unknown") if periph_eq_type else "Unknown"
        )
        media_assets.append({
            "asset_id": int(periph["id"]),
            "asset_name": periph["name"],
            "asset_type": "Peripheral",
            "equipment_type_id": periph.get("equipment_type_id"),
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
                    st.markdown(f"[x] {current_value}")
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

st.divider()

# ============================================================================
# SECTION 5: Requirements
# ============================================================================
st.header("5. Requirements")

with st.expander("Show Risk Catalog", expanded=False):
    can_create = is_editable(asset_phase, Tables.RISK, "*")

    if can_create:
        st.caption("New risks can be created per requirement via the checkbox in the table.")
    else:
        st.caption("Risk catalog is read-only.")

    st.markdown("---")

    search_term = st.text_input("Search Risk Catalog", key="risk_catalog_search", placeholder="Error or harm...")

    risk_catalog = load_table(Tables.RISK)

    filtered_catalog = risk_catalog
    if search_term:
        mask = (
            risk_catalog["possible_error"].str.contains(search_term, case=False, na=False)
            | risk_catalog["harm"].str.contains(search_term, case=False, na=False)
        )
        filtered_catalog = risk_catalog[mask]

    if filtered_catalog.empty:
        st.info("No risk catalog entries available.")
    else:
        for _, risk in filtered_catalog.iterrows():
            before_vals = get_before_mitigation_values(risk["id"])
            level = before_vals.get("risk_level_before_mitigation", "")
            level_icon = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(level, "⚪")
            level_label = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH"}.get(level, "?")
            mitigation_req = "(!)" if before_vals.get("mitigation_required", False) else "(ok)"
            st.markdown(f"[{level_icon} {level_label}] **Risk-{risk['id']}:** {safe_str(risk.get('possible_error', ''))[:40]} {mitigation_req}")
            st.caption(
                f"S={before_vals.get('severity_before_mitigation', '')} "
                f"O={before_vals.get('likelihood_before_mitigation', '')} "
                f"D={before_vals.get('detectability_before_mitigation', '')} "
                f"-> Q={before_vals.get('quantification_before_mitigation', '')}"
            )

risk_catalog = load_table(Tables.RISK)

risk_catalog_sorted = pd.DataFrame()
risk_desc_map = {}
risk_before_map = {}  # risk_id -> before-mitigation values dict
risk_ids = []
if not risk_catalog.empty and "id" in risk_catalog.columns:
    risk_catalog_sorted = risk_catalog.sort_values("id")
    for _, row in risk_catalog_sorted.iterrows():
        risk_id_raw = row.get("id")
        if pd.isna(risk_id_raw):
            continue
        try:
            risk_id_int = int(risk_id_raw)
        except (TypeError, ValueError):
            continue
        risk_ids.append(risk_id_int)
        risk_desc_map[risk_id_int] = safe_str(row.get("possible_error", ""))
    risk_ids = sorted(set(risk_ids))

# Pre-load before-mitigation values for all risks
for rid in risk_ids:
    risk_before_map[rid] = get_before_mitigation_values(rid)

with st.container():
    assets_for_requirements = [
        {
            "asset_id": asset_id,
            "asset_name": asset_name,
            "asset_type": "main",
            "equipment_type_id": asset.get("equipment_type_id"),
            "label": f"{asset_name} ({equipment_type_desc})",
        }
    ]

    if not peripheral_assets.empty:
        for _, periph in peripheral_assets.iterrows():
            periph_eq_type = get_equipment_type_by_id(periph.get("equipment_type_id"))
            periph_eq_type_desc = (
                periph_eq_type.get("name", "Unknown") if periph_eq_type else "Unknown"
            )
            assets_for_requirements.append(
                {
                    "asset_id": int(periph["id"]),
                    "asset_name": periph["name"],
                    "asset_type": "peripheral",
                    "equipment_type_id": periph.get("equipment_type_id"),
                    "label": f"{periph['name']} ({periph_eq_type_desc})",
                }
            )

    # Load traceability entries and join with requirement catalog
    requirements_by_asset = {}
    traceability_by_asset = {}
    for asset_info in assets_for_requirements:
        trace_entries = get_asset_traceability_entries(asset_info["asset_id"])
        traceability_by_asset[asset_info["asset_id"]] = trace_entries
        if trace_entries.empty:
            requirements_by_asset[asset_info["asset_id"]] = pd.DataFrame()
            continue

        # Join with requirement catalog to get description, subchapter_id, etc.
        if not requirement_catalog.empty and "id" in requirement_catalog.columns:
            req_cols = requirement_catalog.rename(columns={"id": "requirement_id"})
            merged = trace_entries.merge(
                req_cols,
                on="requirement_id",
                how="left",
                suffixes=("", "_req"),
            )
        else:
            merged = trace_entries
        requirements_by_asset[asset_info["asset_id"]] = merged

    if not any(not df.empty for df in requirements_by_asset.values()):
        st.info("No requirements assigned.")
        st.stop()

    can_edit_risk = is_editable(asset_phase, Tables.ASSET_TRACEABILITY_MATRIX, "risk_id")

    save_all_clicked = st.button("Save Risk Assessments", disabled=not can_edit_risk)

    if save_all_clicked:
        changed = 0
        missing_manual = []
        missing_risks = []
        for asset_info in assets_for_requirements:
            asset_id_local = asset_info["asset_id"]
            asset_label = asset_info["label"]
            asset_reqs = requirements_by_asset.get(asset_id_local)
            if asset_reqs is None or asset_reqs.empty:
                continue

            for row_idx, entry in asset_reqs.iterrows():
                requirement_id_local = entry["requirement_id"]
                row_key = f"{asset_id_local}_{requirement_id_local}_{row_idx}"
                current_risk_id = entry.get("risk_id")
                risk_already_assigned = pd.notna(current_risk_id)

                if risk_already_assigned:
                    continue

                select_key = f"risk_select_{row_key}"
                manual_key = f"risk_manual_{row_key}"

                manual_enabled = bool(st.session_state.get(manual_key, False)) and can_edit_risk and not risk_already_assigned
                selected_risk_id = current_risk_id if risk_already_assigned else st.session_state.get(select_key)

                manual_error_key = f"risk_manual_error_{row_key}"
                manual_harm_key = f"risk_manual_harm_{row_key}"
                manual_cause_key = f"risk_manual_cause_{row_key}"
                manual_sev_key = f"risk_manual_sev_{row_key}"
                manual_occ_key = f"risk_manual_occ_{row_key}"
                manual_det_key = f"risk_manual_det_{row_key}"

                if manual_enabled:
                    manual_error = safe_str(st.session_state.get(manual_error_key, "")).strip()
                    manual_harm = safe_str(st.session_state.get(manual_harm_key, "")).strip()
                    manual_cause = safe_str(st.session_state.get(manual_cause_key, "")).strip()
                    manual_sev = safe_int(st.session_state.get(manual_sev_key), 1)
                    manual_occ = safe_int(st.session_state.get(manual_occ_key), 1)
                    manual_det = safe_int(st.session_state.get(manual_det_key), 1)

                    if not manual_error:
                        missing_manual.append(f"{asset_label} / REQ-{requirement_id_local}")
                        continue

                    quant = calculate_quantification(manual_sev, manual_occ, manual_det)
                    level = calculate_risk_level(quant)

                    new_risk = {
                        "possible_error": manual_error,
                        "harm": manual_harm,
                        "cause": manual_cause,
                        "severity_before_mitigation": manual_sev,
                        "likelihood_before_mitigation": manual_occ,
                        "detectability_before_mitigation": manual_det,
                    }
                    selected_risk_id = insert_row(Tables.RISK, new_risk)
                else:
                    if selected_risk_id is None or selected_risk_id == "":
                        missing_risks.append(f"{asset_label} / REQ-{requirement_id_local}")
                        continue
                    try:
                        selected_risk_id = int(selected_risk_id)
                    except (TypeError, ValueError):
                        continue

                if update_traceability_risk(
                    asset_id=asset_id_local,
                    requirement_id=requirement_id_local,
                    new_risk_id=selected_risk_id,
                    current_risk_id=None,
                    risk_is_auto_assign=False,
                ):
                    changed += 1

        if changed:
            st.success(f"{changed} risk assessment(s) saved.")
        else:
            st.info("No changes to save.")
        if missing_manual:
            st.error("Manual risks missing for: " + ", ".join(sorted(missing_manual)))
        if missing_risks:
            st.error("Missing risk assignments for: " + ", ".join(sorted(missing_risks)))
        st.rerun()

    risk_options = [None] + risk_ids

    for asset_info in assets_for_requirements:
        asset_id_local = asset_info["asset_id"]
        asset_label = asset_info["label"]
        section_title = "Main Asset" if asset_info["asset_type"] == "main" else "Peripheral"
        st.subheader(f"{section_title}: {asset_label}")

        asset_reqs = requirements_by_asset.get(asset_id_local)
        if asset_reqs is None or asset_reqs.empty:
            st.caption("No requirements assigned.")
            continue

        # Group by subchapter (via subchapter_id)
        for subchapter in Subchapter:
            chapter_label = SUBCHAPTER_LABELS[subchapter]
            st.markdown(f"**{chapter_label}**")
            indent_cols = st.columns([0.04, 0.96], gap="small")
            with indent_cols[1]:
                # Match by subchapter name -> subchapter_id
                matching_sc_ids = [
                    sc_id for sc_id, sc_name in subchapter_id_map.items()
                    if sc_name == subchapter.value
                ]

                if matching_sc_ids and "subchapter_id" in asset_reqs.columns:
                    sub_reqs = asset_reqs[asset_reqs["subchapter_id"].isin(matching_sc_ids)].copy()
                else:
                    sub_reqs = pd.DataFrame()

                if not sub_reqs.empty and "requirement_id" in sub_reqs.columns:
                    sub_reqs = sub_reqs.sort_values("requirement_id")

                if sub_reqs.empty:
                    st.caption("No requirements in this subchapter.")
                    continue

                column_widths = [
                    0.6, 2.1, 1.1, 0.4, 0.5, 0.8, 1.6,
                    0.45, 0.45, 0.45, 0.55, 0.7, 0.6,
                    0.3, 0.3, 0.3,
                ]
                header_cols = st.columns(column_widths, gap="small")
                # Requirement columns (0-4): Blue background
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
                header_cols[13].markdown("➕")
                header_cols[14].markdown("✏️")
                header_cols[15].markdown("🗑️")

                grouped_reqs = sub_reqs.groupby("requirement_id", sort=False)
                for group_idx, (requirement_id_local, group) in enumerate(grouped_reqs):
                    if group_idx > 0:
                        st.markdown("---")

                    group_first = group.iloc[0]
                    requirement_text = safe_str(group_first.get("description", ""))
                    remark_text = safe_str(group_first.get("requirement_remark", ""))
                    is_gxp = excel_to_bool(group_first.get("is_gxp", False))
                    is_must = excel_to_bool(group_first.get("is_must", False))

                    risk_groups = group.groupby(group["risk_id"].apply(_int_or_none), sort=False, dropna=False)
                    for row_pos, (_, risk_group) in enumerate(risk_groups):
                        entry = risk_group.iloc[0]
                        row_idx = risk_group.index[0]
                        is_first_row = row_pos == 0
                        row_key = f"{asset_id_local}_{requirement_id_local}_{row_idx}"

                        row_cols = st.columns(column_widths, gap="small")
                        if is_first_row:
                            row_cols[0].markdown(f"REQ-{requirement_id_local}")
                            row_cols[1].markdown(requirement_text)
                            row_cols[2].markdown(remark_text or "")
                            row_cols[3].markdown("Y" if is_gxp else "N")
                            row_cols[4].markdown("Y" if is_must else "N")
                        else:
                            row_cols[0].markdown("")
                            row_cols[1].markdown("")
                            row_cols[2].markdown("")
                            row_cols[3].markdown("")
                            row_cols[4].markdown("")

                        current_risk_id = entry.get("risk_id")
                        risk_already_assigned = pd.notna(current_risk_id)
                        suggested_risk_id, _ = get_suggested_risk_id(requirement_id_local)

                        select_label = f"Risk-ID [{row_key}]"
                        select_key = f"risk_select_{row_key}"
                        manual_key = f"risk_manual_{row_key}"

                        default_risk_id = None
                        if risk_already_assigned:
                            try:
                                default_risk_id = int(current_risk_id)
                            except (TypeError, ValueError):
                                default_risk_id = None
                        elif suggested_risk_id:
                            default_risk_id = suggested_risk_id

                        default_index = risk_options.index(default_risk_id) if default_risk_id in risk_options else 0

                        manual_enabled = bool(st.session_state.get(manual_key, False))
                        selected_risk_id = None
                        if risk_already_assigned:
                            selected_risk_id = default_risk_id
                            row_cols[5].markdown(f"Risk-{selected_risk_id}" if selected_risk_id else "")
                        elif can_edit_risk:
                            selected_risk_id = row_cols[5].selectbox(
                                select_label,
                                risk_options,
                                index=default_index,
                                key=select_key,
                                disabled=not can_edit_risk or manual_enabled,
                                label_visibility="collapsed",
                                format_func=lambda x: "-- Please select --" if x is None else f"Risk-{x}: {risk_desc_map.get(x, '')}",
                            )
                            manual_enabled = row_cols[6].checkbox(
                                "No matching entry in risk catalog",
                                key=manual_key,
                                disabled=not can_edit_risk,
                            )
                        else:
                            row_cols[5].markdown("")

                        manual_error_key = f"risk_manual_error_{row_key}"
                        manual_harm_key = f"risk_manual_harm_{row_key}"
                        manual_cause_key = f"risk_manual_cause_{row_key}"
                        manual_sev_key = f"risk_manual_sev_{row_key}"
                        manual_occ_key = f"risk_manual_occ_{row_key}"
                        manual_det_key = f"risk_manual_det_{row_key}"

                        manual_error = safe_str(st.session_state.get(manual_error_key, "")).strip()
                        manual_harm = safe_str(st.session_state.get(manual_harm_key, "")).strip()
                        manual_cause = safe_str(st.session_state.get(manual_cause_key, "")).strip()
                        manual_sev = safe_int(st.session_state.get(manual_sev_key), 0)
                        manual_occ = safe_int(st.session_state.get(manual_occ_key), 0)
                        manual_det = safe_int(st.session_state.get(manual_det_key), 0)

                        if manual_enabled and can_edit_risk:
                            row_cols[6].markdown("**Manual Risk**")
                        elif selected_risk_id is not None:
                            try:
                                selected_risk_id = int(selected_risk_id)
                            except (TypeError, ValueError):
                                selected_risk_id = None

                        # Get before-mitigation values from the risk table
                        before_sev = None
                        before_occ = None
                        before_det = None
                        before_quant = None
                        before_level = ""

                        if manual_enabled and can_edit_risk:
                            with st.container():
                                st.caption("Enter manual risk")
                                m_col1, m_col2, m_col3 = st.columns(3)
                                m_col1.text_input(
                                    "Possible Error",
                                    value=manual_error,
                                    key=manual_error_key,
                                )
                                m_col2.text_input(
                                    "Harm",
                                    value=manual_harm,
                                    key=manual_harm_key,
                                )
                                m_col3.text_input(
                                    "Cause",
                                    value=manual_cause,
                                    key=manual_cause_key,
                                )
                                m_col4, m_col5, m_col6 = st.columns(3)
                                m_col4.selectbox(
                                    "Severity (1-3)",
                                    [1, 2, 3],
                                    index=max(manual_sev - 1, 0) if manual_sev in (1, 2, 3) else 0,
                                    key=manual_sev_key,
                                )
                                m_col5.selectbox(
                                    "Occurrence (1-3)",
                                    [1, 2, 3],
                                    index=max(manual_occ - 1, 0) if manual_occ in (1, 2, 3) else 0,
                                    key=manual_occ_key,
                                )
                                m_col6.selectbox(
                                    "Detection (1-3)",
                                    [1, 2, 3],
                                    index=max(manual_det - 1, 0) if manual_det in (1, 2, 3) else 0,
                                    key=manual_det_key,
                                )

                            before_sev = manual_sev if manual_sev in (1, 2, 3) else None
                            before_occ = manual_occ if manual_occ in (1, 2, 3) else None
                            before_det = manual_det if manual_det in (1, 2, 3) else None
                            if before_sev and before_occ and before_det:
                                before_quant = calculate_quantification(before_sev, before_occ, before_det)
                                before_level = calculate_risk_level(before_quant)

                        elif selected_risk_id is not None:
                            # Get values from risk table via get_before_mitigation_values
                            before_vals = risk_before_map.get(selected_risk_id)
                            if before_vals is None:
                                before_vals = get_before_mitigation_values(selected_risk_id)
                            before_sev = before_vals.get("severity_before_mitigation")
                            before_occ = before_vals.get("likelihood_before_mitigation")
                            before_det = before_vals.get("detectability_before_mitigation")
                            before_quant = before_vals.get("quantification_before_mitigation")
                            before_level = before_vals.get("risk_level_before_mitigation", "")

                        risk_title = manual_error if manual_enabled else risk_desc_map.get(selected_risk_id, "") if selected_risk_id else ""
                        row_cols[6].markdown(risk_title)

                        mitigation_required_flag = before_level in ("high", "medium")
                        mitigation_icon = "Y" if mitigation_required_flag else "N"
                        row_cols[12].markdown(mitigation_icon)

                        row_cols[7].markdown(str(before_sev) if before_sev else "")
                        row_cols[8].markdown(str(before_occ) if before_occ else "")
                        row_cols[9].markdown(str(before_det) if before_det else "")
                        row_cols[10].markdown(str(before_quant) if before_quant is not None else "")
                        before_icon = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(before_level, "⚪")
                        before_label = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH"}.get(before_level, "?")
                        row_cols[11].markdown(f"{before_icon} {before_label}" if before_level else "")

                        risk_auto_assign_flag = excel_to_bool(entry.get("risk_is_auto_assign", True))
                        is_editable_risk = (not risk_auto_assign_flag) and risk_already_assigned

                        add_target_key = f"add_risk_target_{asset_id_local}"
                        edit_target_key = f"edit_risk_target_{asset_id_local}"

                        if is_first_row:
                            if row_cols[13].button("➕", key=f"risk_add_{row_key}", disabled=not can_edit_risk, type="tertiary"):
                                st.session_state[add_target_key] = row_key
                                st.session_state[edit_target_key] = None
                                st.rerun()
                        else:
                            row_cols[13].markdown("")

                        if is_editable_risk:
                            if row_cols[14].button("✏️", key=f"risk_edit_{row_key}", disabled=not can_edit_risk, type="tertiary"):
                                st.session_state[edit_target_key] = row_key
                                st.session_state[add_target_key] = None
                                st.rerun()
                            if row_cols[15].button("🗑️", key=f"risk_delete_{row_key}", disabled=not can_edit_risk, type="tertiary"):
                                trace_rows = traceability_by_asset.get(asset_id_local)
                                if trace_rows is not None and not trace_rows.empty:
                                    req_rows = trace_rows[trace_rows["requirement_id"] == requirement_id_local]
                                    if len(req_rows) <= 1:
                                        st.warning("At least one risk must remain per requirement.")
                                    else:
                                        df = load_table(Tables.ASSET_TRACEABILITY_MATRIX)
                                        mask = (
                                            (df["asset_id"] == asset_id_local)
                                            & (df["requirement_id"] == requirement_id_local)
                                            & df["risk_id"].apply(lambda x: _risk_id_equals(x, current_risk_id))
                                        )
                                        if mask.any():
                                            df = df.drop(df[mask].index)
                                            save_table(Tables.ASSET_TRACEABILITY_MATRIX, df)
                                            st.success("Risk assignment deleted.")
                                            st.rerun()
                        else:
                            row_cols[14].markdown("")
                            row_cols[15].markdown("")

                        trace_rows = traceability_by_asset.get(asset_id_local)
                        req_rows = trace_rows[trace_rows["requirement_id"] == requirement_id_local] if trace_rows is not None else pd.DataFrame()
                        existing_risk_ids = set()
                        if not req_rows.empty and "risk_id" in req_rows.columns:
                            existing_risk_ids = {
                                _int_or_none(value)
                                for value in req_rows["risk_id"].tolist()
                                if _int_or_none(value) is not None
                            }

                        if st.session_state.get(add_target_key) == row_key:
                            with st.container():
                                st.caption("Add additional risk")
                                add_select_key = f"risk_add_select_{row_key}"
                                add_manual_key = f"risk_add_manual_{row_key}"

                                available_risk_ids = [rid for rid in risk_ids if rid not in existing_risk_ids]
                                add_options = [None] + available_risk_ids

                                add_selected_risk = st.selectbox(
                                    "Select Risk",
                                    add_options,
                                    key=add_select_key,
                                    format_func=lambda x: "-- Please select --" if x is None else f"Risk-{x}: {risk_desc_map.get(x, '')}",
                                )

                                add_manual_enabled = st.checkbox(
                                    "No matching entry in risk catalog",
                                    key=add_manual_key,
                                )

                                add_manual_error_key = f"risk_add_error_{row_key}"
                                add_manual_harm_key = f"risk_add_harm_{row_key}"
                                add_manual_cause_key = f"risk_add_cause_{row_key}"
                                add_manual_sev_key = f"risk_add_sev_{row_key}"
                                add_manual_occ_key = f"risk_add_occ_{row_key}"
                                add_manual_det_key = f"risk_add_det_{row_key}"

                                if add_manual_enabled:
                                    m_col1, m_col2, m_col3 = st.columns(3)
                                    m_col1.text_input("Possible Error", key=add_manual_error_key)
                                    m_col2.text_input("Harm", key=add_manual_harm_key)
                                    m_col3.text_input("Cause", key=add_manual_cause_key)
                                    m_col4, m_col5, m_col6 = st.columns(3)
                                    m_col4.selectbox("Severity (1-3)", [1, 2, 3], key=add_manual_sev_key)
                                    m_col5.selectbox("Occurrence (1-3)", [1, 2, 3], key=add_manual_occ_key)
                                    m_col6.selectbox("Detection (1-3)", [1, 2, 3], key=add_manual_det_key)

                                if st.button("Add Risk", key=f"risk_add_save_{row_key}"):
                                    if add_manual_enabled:
                                        manual_error = safe_str(st.session_state.get(add_manual_error_key, "")).strip()
                                        if not manual_error:
                                            st.error("Please enter a possible error.")
                                        else:
                                            manual_harm = safe_str(st.session_state.get(add_manual_harm_key, "")).strip()
                                            manual_cause = safe_str(st.session_state.get(add_manual_cause_key, "")).strip()
                                            manual_sev = safe_int(st.session_state.get(add_manual_sev_key), 1)
                                            manual_occ = safe_int(st.session_state.get(add_manual_occ_key), 1)
                                            manual_det = safe_int(st.session_state.get(add_manual_det_key), 1)
                                            new_risk = {
                                                "possible_error": manual_error,
                                                "harm": manual_harm,
                                                "cause": manual_cause,
                                                "severity_before_mitigation": manual_sev,
                                                "likelihood_before_mitigation": manual_occ,
                                                "detectability_before_mitigation": manual_det,
                                            }
                                            new_risk_id = insert_row(Tables.RISK, new_risk)
                                            if add_additional_risk_to_asset(
                                                asset_id=asset_id_local,
                                                requirement_id=requirement_id_local,
                                                risk_id=new_risk_id,
                                                risk_is_auto_assign=False,
                                            ):
                                                st.success("Additional risk added.")
                                                st.session_state[add_target_key] = None
                                                st.rerun()
                                    else:
                                        if add_selected_risk is None:
                                            st.error("Please select a risk.")
                                        else:
                                            try:
                                                add_selected_risk = int(add_selected_risk)
                                            except (TypeError, ValueError):
                                                add_selected_risk = None
                                            if add_selected_risk is None:
                                                st.error("Invalid Risk ID.")
                                            else:
                                                if add_additional_risk_to_asset(
                                                    asset_id=asset_id_local,
                                                    requirement_id=requirement_id_local,
                                                    risk_id=add_selected_risk,
                                                    risk_is_auto_assign=False,
                                                ):
                                                    st.success("Additional risk added.")
                                                    st.session_state[add_target_key] = None
                                                    st.rerun()

                                if st.button("Cancel", key=f"risk_add_cancel_{row_key}"):
                                    st.session_state[add_target_key] = None
                                    st.rerun()

                        if st.session_state.get(edit_target_key) == row_key and is_editable_risk:
                            with st.container():
                                st.caption("Change risk")
                                edit_select_key = f"risk_edit_select_{row_key}"
                                available_edit_ids = [rid for rid in risk_ids if rid not in existing_risk_ids or rid == _int_or_none(current_risk_id)]
                                current_risk_int = _int_or_none(current_risk_id)
                                if current_risk_int in available_edit_ids:
                                    default_index = available_edit_ids.index(current_risk_int)
                                else:
                                    default_index = 0
                                edit_selected_risk = st.selectbox(
                                    "Select new risk",
                                    available_edit_ids,
                                    index=default_index,
                                    key=edit_select_key,
                                    format_func=lambda x: f"Risk-{x}: {risk_desc_map.get(x, '')}",
                                )

                                if st.button("Save Risk", key=f"risk_edit_save_{row_key}"):
                                    if update_traceability_risk(
                                        asset_id=asset_id_local,
                                        requirement_id=requirement_id_local,
                                        new_risk_id=edit_selected_risk,
                                        current_risk_id=current_risk_id,
                                        risk_is_auto_assign=False,
                                    ):
                                        st.success("Risk updated.")
                                        st.session_state[edit_target_key] = None
                                        st.rerun()

                                if st.button("Cancel", key=f"risk_edit_cancel_{row_key}"):
                                    st.session_state[edit_target_key] = None
                                    st.rerun()

# ============================================================================
# SECTION 6: Risk Matrix
# ============================================================================
st.divider()
st.header("6. Risk Matrix")

all_trace_entries = []
for asset_info in assets_for_requirements:
    trace_entries = traceability_by_asset.get(asset_info["asset_id"])
    if trace_entries is not None and not trace_entries.empty:
        all_trace_entries.append(trace_entries)

combined_trace = pd.concat(all_trace_entries, ignore_index=True) if all_trace_entries else pd.DataFrame()

before_rows = []
if not combined_trace.empty:
    assigned = combined_trace[combined_trace["risk_id"].notna()]
    if {"requirement_id", "risk_id"}.issubset(assigned.columns):
        dedupe_cols = ["requirement_id", "risk_id"]
        if "asset_id" in assigned.columns:
            dedupe_cols.insert(0, "asset_id")
        assigned = assigned.drop_duplicates(subset=dedupe_cols)
    for _, entry in assigned.iterrows():
        risk_id_val = entry.get("risk_id")
        if pd.isna(risk_id_val):
            continue
        try:
            risk_id_val = int(risk_id_val)
        except (TypeError, ValueError):
            continue
        # Get before-mitigation values from risk table
        before_vals = risk_before_map.get(risk_id_val)
        if before_vals is None:
            before_vals = get_before_mitigation_values(risk_id_val)

        sev_before = before_vals.get("severity_before_mitigation")
        occ_before = before_vals.get("likelihood_before_mitigation")
        det_before = before_vals.get("detectability_before_mitigation")

        before_rows.append((sev_before, occ_before, det_before))

before_counts = _build_matrix_counts(before_rows)

st.markdown(MATRIX_STYLE, unsafe_allow_html=True)
_render_risk_matrix("Before Mitigation", before_counts)

# ============================================================================
# SECTION 7: Export Risk Assignment Document
# ============================================================================
st.divider()
st.header("7. Export Risk Assignment Document")

asset_ids = get_asset_and_peripheral_ids(asset_id)

missing_risk_rows = []
for asset_id_local in asset_ids:
    trace_local = get_asset_traceability_entries(asset_id_local)
    if trace_local.empty:
        continue
    missing_mask = trace_local["risk_id"].isna()
    if missing_mask.any():
        missing_risk_rows.append(trace_local[missing_mask])

missing_risk = pd.concat(missing_risk_rows) if missing_risk_rows else pd.DataFrame()

col_export, col_approve = st.columns([1, 1])

with col_export:
    export_disabled = asset_phase != Phase.RISK or not missing_risk.empty
    export_btn = st.button(
        "Export Risk Assignment (PDF)",
        type="primary",
        disabled=export_disabled,
    )

with col_approve:
    approve_disabled = asset_phase != Phase.RISK or not missing_risk.empty
    approve_btn = st.button("Approve RISK", disabled=approve_disabled)


def _build_risks_for_asset(target_asset_id):
    """Build risk data list for PDF context from traceability entries."""
    trace = get_asset_traceability_entries(target_asset_id)
    risks_list = []
    if trace.empty:
        return risks_list

    # Join with requirement catalog
    if not requirement_catalog.empty and "id" in requirement_catalog.columns:
        req_cols = requirement_catalog.rename(columns={"id": "requirement_id"})
        merged = trace.merge(req_cols, on="requirement_id", how="left", suffixes=("", "_req"))
    else:
        merged = trace

    if {"requirement_id", "risk_id"}.issubset(merged.columns):
        merged = merged.drop_duplicates(subset=["requirement_id", "risk_id"])

    for _, entry in merged.iterrows():
        if pd.notna(entry.get("risk_id")):
            risk_id_val = _int_or_none(entry["risk_id"])
            if risk_id_val is None:
                continue
            # Get risk catalog details
            risk_info_rows = risk_catalog[risk_catalog["id"] == risk_id_val]
            if not risk_info_rows.empty:
                row_data = risk_info_rows.iloc[0].to_dict()
                row_data.update(entry.to_dict())
                # Add computed before-mitigation values
                before_vals = risk_before_map.get(risk_id_val)
                if before_vals is None:
                    before_vals = get_before_mitigation_values(risk_id_val)
                row_data["severity_before_mitigation"] = before_vals.get("severity_before_mitigation")
                row_data["likelihood_before_mitigation"] = before_vals.get("likelihood_before_mitigation")
                row_data["detectability_before_mitigation"] = before_vals.get("detectability_before_mitigation")
                row_data["quantification_before_mitigation"] = before_vals.get("quantification_before_mitigation")
                row_data["risk_level_before_mitigation"] = before_vals.get("risk_level_before_mitigation")
                row_data["mitigation_required"] = before_vals.get("mitigation_required", False)
                risks_list.append(row_data)

    return risks_list


def _build_peripherals_data():
    """Build peripheral data list for PDF context."""
    peripherals_data = []
    peripheral_assets_export = get_peripherals(asset_id)
    if not peripheral_assets_export.empty:
        for _, periph in peripheral_assets_export.iterrows():
            periph_risks = _build_risks_for_asset(int(periph["id"]))
            periph_eq_type = get_equipment_type_by_id(periph.get("equipment_type_id"))
            periph_eq_type_desc = (
                periph_eq_type.get("name", "Unknown") if periph_eq_type else "Unknown"
            )
            peripherals_data.append({
                "name": periph["name"],
                "equipment_type": periph_eq_type_desc,
                "risks": periph_risks
            })
    return peripherals_data


if approve_btn:
    doc_type = asset_phase.value
    pdf_doc_type = "FMEA"
    target_phase = get_next_phase(Phase.RISK)
    asset_ids = get_asset_and_peripheral_ids(asset_id)
    if target_phase and set_asset_phase(asset_ids, Phase.RISK):
        record_document_approval(asset_id, doc_type)
        approved_version = get_latest_document_version_info(asset_id, doc_type)
        if not approved_version:
            st.error("Could not create approved PDF: No document version found. Please export first.")
        else:
            main_risks_approve = _build_risks_for_asset(asset_id)
            peripherals_data_approve = _build_peripherals_data()

            base_context = get_pdf_base_context(asset_id)
            context = {
                **base_context,
                **approved_version,
                "version": approved_version["document_version"],
                "main_risks": main_risks_approve,
                "peripherals": peripherals_data_approve,
                "appendix_urls": [],
            }

            try:
                out_path = render_document(pdf_doc_type, context, approved=True)
                st.success(f"Approved PDF created: {out_path}")
            except Exception as e:
                st.error(f"Error during approved export: {e}")

        st.success("Phase set to DQ.")
        st.rerun()

if export_btn and not export_disabled:
    main_risks = _build_risks_for_asset(asset_id)
    peripherals_data = _build_peripherals_data()

    base_context = get_pdf_base_context(asset_id)
    record_document_export(asset_id, asset_phase.value)
    version_info = get_document_version_snapshot(asset_id, asset_phase.value)
    context = {
        **base_context,
        **version_info,
        "version": version_info["document_version"],
        "main_risks": main_risks,
        "peripherals": peripherals_data,
        "appendix_urls": [],
    }

    try:
        out_path = render_document("FMEA", context)
        st.success(f"PDF created: {out_path}")
    except Exception as e:
        st.error(f"Error during export: {e}")
