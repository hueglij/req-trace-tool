"""
Qualification Plan - xQ-Test assignment for traceability matrix entries.

Goal: All traceability entries with risk_level (before) medium/high require mitigation.
- If solved by DQ, xQ is voluntary; otherwise xQ is mandatory.
- Pre-defined xQ from xq_risk defaults are not removable
- Manually added xQ can be changed or removed
- xQ after-mitigation values come from the XQ catalog via get_after_mitigation_values()
- Layout: 26-column table with "Solved by xQ?" checkbox
"""
import streamlit as st
import pandas as pd
from pathlib import Path
import sys
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from app_core.data_io import (
    load_table, get_asset_traceability_entries,
    get_asset_phase, set_asset_phase,
    get_asset_and_peripheral_ids, record_document_export, record_document_approval,
    get_pdf_base_context, get_document_version_snapshot, get_latest_document_version_info,
    get_peripherals, get_equipment_type_by_id, get_row_by_id,
    get_asset_media, set_asset_media, delete_asset_media,
    get_location_hierarchy, get_asset_location, get_location_display,
    get_default_xq_for_risk,
    get_before_mitigation_values, get_after_mitigation_values,
    update_traceability_xq, clear_traceability_xq,
    insert_row,
)
from app_core.models import Tables, Phase, Subchapter, SUBCHAPTER_LABELS
from app_core.policy import (
    get_next_phase, is_phase_gates_enabled, get_soft_warning,
    is_editable, check_phase_gate
)
from app_core.pdf import render_document
from app_core.utils import (
    safe_str, safe_int, excel_to_bool, calculate_quantification, calculate_risk_level,
    LIKELIHOOD_LEVELS, SEVERITY_LEVELS, CELL_COLOR_MAP, MATRIX_STYLE,
    int_or_none, likelihood_bucket, build_matrix_counts, render_risk_matrix,
)
from app_core.style import (
    apply_global_style, render_sticky_header,
    REQUIRED_EMPTY_BG, REQUIRED_FILLED_BG,
    css_escape, queue_required_style, apply_required_styles,
)

# ============================================================================
# Helper functions
# ============================================================================

# Aliases for call-sites that use the old underscore-prefixed names
_css_escape = css_escape
_int_or_none = int_or_none
_likelihood_bucket = likelihood_bucket
_build_matrix_counts = build_matrix_counts
_render_risk_matrix = render_risk_matrix
_queue_required_style = queue_required_style
_apply_required_styles = apply_required_styles


def _get_xq_after_fields(xq_id: Optional[int]) -> dict:
    """Get after-mitigation values from XQ catalog for a given xQ ID."""
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


def _build_qp_export_requirements(asset_id_local: int, req_df: pd.DataFrame, risk_df: pd.DataFrame,
                                   xq_df: pd.DataFrame, dq_df: pd.DataFrame, subchapter_df: pd.DataFrame) -> list[dict]:
    """Build export-ready requirement list for an asset by joining traceability entries with catalog data."""
    entries = get_asset_traceability_entries(asset_id_local)
    if entries.empty:
        return []

    records = []
    for _, entry in entries.iterrows():
        row = entry.to_dict()

        # Join requirement details
        req_id = _int_or_none(entry.get("requirement_id"))
        if req_id is not None and not req_df.empty:
            req_match = req_df[req_df["id"] == req_id]
            if not req_match.empty:
                req_data = req_match.iloc[0]
                row["requirement_description"] = safe_str(req_data.get("description", ""))
                row["subchapter_id"] = _int_or_none(req_data.get("subchapter_id"))
                row["is_must"] = excel_to_bool(req_data.get("is_must", False))
                row["is_gxp"] = excel_to_bool(req_data.get("is_gxp", False))

        # Join risk details
        risk_id = _int_or_none(entry.get("risk_id"))
        if risk_id is not None and not risk_df.empty:
            risk_match = risk_df[risk_df["id"] == risk_id]
            if not risk_match.empty:
                risk_data = risk_match.iloc[0]
                row["possible_error"] = safe_str(risk_data.get("possible_error", ""))

        # Join XQ details
        xq_id = _int_or_none(entry.get("xq_id"))
        if xq_id is not None and not xq_df.empty:
            xq_match = xq_df[xq_df["id"] == xq_id]
            if not xq_match.empty:
                xq_data = xq_match.iloc[0]
                row["xq_description"] = safe_str(xq_data.get("description", ""))
                row["xq_purpose"] = safe_str(xq_data.get("purpose", ""))
                row["xq_input"] = safe_str(xq_data.get("input", ""))
                row["xq_expected_output"] = safe_str(xq_data.get("expected_output", ""))

        # Join DQ details
        dq_id = _int_or_none(entry.get("dq_id"))
        if dq_id is not None and not dq_df.empty:
            dq_match = dq_df[dq_df["id"] == dq_id]
            if not dq_match.empty:
                dq_data = dq_match.iloc[0]
                row["dq_description"] = safe_str(dq_data.get("description", ""))

        # Join subchapter name
        sc_id = row.get("subchapter_id")
        if sc_id is not None and not subchapter_df.empty:
            sc_match = subchapter_df[subchapter_df["id"] == sc_id]
            if not sc_match.empty:
                row["subchapter_name"] = safe_str(sc_match.iloc[0].get("name", ""))

        records.append(row)

    return records


required_styles = []

# ============================================================================
# Page config and CSS
# ============================================================================

st.set_page_config(page_title="Qualification Plan", page_icon="📋", layout="wide")
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
/* Horizontal scroll for section 5 table */
div[data-testid="stVerticalBlock"] div[data-testid="stVerticalBlock"]:has(.qp-divider-scope) {
  overflow-x: auto;
  padding-bottom: 12px;
}
div[data-testid="stVerticalBlock"] div[data-testid="stVerticalBlock"]:has(.qp-divider-scope) div[data-testid="stHorizontalBlock"] {
  min-width: 3000px;
}
</style>
""",
    unsafe_allow_html=True,
)

page_name = "04_Qualification_Plan"

_save_container = render_sticky_header("Qualification Plan (xQ)", with_save=True)
st.markdown("Assign xQ tests to requirements.")

# Get selected asset
if "selected_asset_id" not in st.session_state or st.session_state.selected_asset_id is None:
    st.warning("Please select an asset on the Dashboard first.")
    st.stop()

asset_id = st.session_state.selected_asset_id

asset_row = get_row_by_id(Tables.ASSET, asset_id)
if not asset_row:
    st.error("The selected asset was not found.")
    st.stop()

asset_name = safe_str(asset_row.get("name", ""))

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
req_catalog = load_table(Tables.REQUIREMENT)
xq_catalog = load_table(Tables.XQ)
dq_catalog = load_table(Tables.DQ)
risk_catalog = load_table(Tables.RISK)
subchapter_catalog = load_table(Tables.SUBCHAPTER)

if req_catalog.empty:
    st.warning("No requirement catalog found. Please initialize the data first.")

# Build xQ catalog maps
xq_desc_map = {}
xq_ids = []
xq_catalog_sorted = pd.DataFrame()
if not xq_catalog.empty and "id" in xq_catalog.columns:
    xq_catalog_sorted = xq_catalog.sort_values("id")
    for _, row in xq_catalog_sorted.iterrows():
        xq_id_raw = row.get("id")
        if pd.isna(xq_id_raw):
            continue
        try:
            xq_id_int = int(xq_id_raw)
        except (TypeError, ValueError):
            continue
        xq_ids.append(xq_id_int)
        xq_desc_map[xq_id_int] = safe_str(row.get("description", ""))
    xq_ids = sorted(set(xq_ids))

# Peripheral assets
peripheral_assets = get_peripherals(asset_id)
equipment_type_info = get_equipment_type_by_id(asset_row.get("equipment_type_id"))
equipment_type_desc = equipment_type_info["name"] if equipment_type_info else "Unknown"

# ============================================================================
# SECTION 1: Project / Asset
# ============================================================================
st.header("1. Project / Asset")

# Get project info for display
project_id = _int_or_none(asset_row.get("project_id"))
project_info = get_row_by_id(Tables.PROJECT, project_id) if project_id else None
base_context = get_pdf_base_context(asset_id)

with st.expander(f"Selected Asset: {asset_name}", expanded=True):
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Equipment Type:** {equipment_type_desc}")
        st.markdown(f"**Description:** {asset_name}")
        st.markdown(f"**Process Step:** {base_context.get('business_process_step', '')}")
    with col2:
        st.markdown(f"**System Owner:** {base_context.get('system_owner_role', '')}")
        st.markdown(f"**Project Name:** {base_context.get('project_name', '')}")

# ============================================================================
# SECTION 2: Location
# ============================================================================
st.header("2. Location")

hierarchy = get_location_hierarchy()

if hierarchy["countries"].empty:
    st.info("No location data available. Please import location data.")
else:
    if project_id:
        loc_display = get_location_display(project_id)
        if loc_display:
            st.success(f"Current Location: {loc_display}")
        else:
            st.warning("No location assigned.")
    else:
        st.warning("No project assigned to this asset.")

    if asset_phase != Phase.URS:
        st.info("Location changes are only possible in URS phase.")

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
        periph_eq_type_desc = periph_eq_type["name"] if periph_eq_type else "Unknown"
        st.markdown(f"- **{periph['name']}** ({periph_eq_type_desc})")

st.divider()

# ============================================================================
# SECTION 4: Media (Utilities & Media Connections)
# ============================================================================
st.header("4. Media")

# Load media types from catalog
all_media = load_table(Tables.MEDIA)
MEDIA_COLUMNS = []
if not all_media.empty:
    for _, m_row in all_media.iterrows():
        MEDIA_COLUMNS.append({
            "media_id": int(m_row["id"]),
            "label": safe_str(m_row.get("name", f"Media-{m_row['id']}")),
        })

media_assets = [
    {
        "asset_id": asset_id,
        "asset_name": asset_name,
        "asset_type": "Main Asset",
        "equipment_type_id": asset_row.get("equipment_type_id"),
        "equipment_type_desc": equipment_type_desc,
    }
]

peripheral_assets_media = peripheral_assets
if peripheral_assets_media.empty:
    peripheral_assets_media = get_peripherals(asset_id)

if not peripheral_assets_media.empty:
    for _, periph in peripheral_assets_media.iterrows():
        periph_eq_type = get_equipment_type_by_id(periph.get("equipment_type_id"))
        periph_eq_type_desc = periph_eq_type["name"] if periph_eq_type else "Unknown"
        media_assets.append({
            "asset_id": int(periph["id"]),
            "asset_name": periph["name"],
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

can_edit_media = asset_phase == Phase.URS

if MEDIA_COLUMNS:
    header_cols = st.columns([2, 1.5] + [1.5] * len(MEDIA_COLUMNS))
    header_cols[0].markdown("**Equipment Type**")
    header_cols[1].markdown("**Asset Type**")
    for i, media_info in enumerate(MEDIA_COLUMNS):
        header_cols[i + 2].markdown(f"**{media_info['label']}**")

    media_changes = []

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
                cb_key = f"media_cb_{ma['asset_id']}_{media_id}"
                input_key = f"media_val_{ma['asset_id']}_{media_id}"

                if can_edit_media:
                    is_checked = st.checkbox(
                        "Active",
                        value=has_media,
                        key=cb_key,
                        label_visibility="collapsed"
                    )
                    if is_checked:
                        new_value = st.text_input(
                            "Value",
                            value=current_value,
                            key=input_key,
                            label_visibility="collapsed",
                            placeholder="Enter value..."
                        )
                        if new_value != current_value or not has_media:
                            media_changes.append({
                                "action": "set",
                                "asset_id": ma["asset_id"],
                                "media_id": media_id,
                                "media_value": new_value,
                            })
                    else:
                        if has_media:
                            media_changes.append({
                                "action": "delete",
                                "asset_id": ma["asset_id"],
                                "media_id": media_id,
                            })
                else:
                    if has_media:
                        st.markdown(f"✅ {current_value}")
                    else:
                        st.markdown("—")

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
        st.info("Media can only be edited in URS phase.")
else:
    st.info("No media types defined in the catalog.")

st.divider()

# ============================================================================
# SECTION 5: Requirements
# ============================================================================
st.header("5. Requirements")

with st.expander("Show xQ Catalog", expanded=False):
    if xq_catalog_sorted.empty:
        st.info("No xQ catalog available.")
    else:
        xq_search = st.text_input("Search xQ Catalog", key="xq_catalog_search")
        filtered_xq = xq_catalog_sorted
        if xq_search:
            xq_search_lower = xq_search.strip().lower()
            filtered_xq = xq_catalog_sorted[
                xq_catalog_sorted["description"].fillna("").astype(str).str.lower().str.contains(xq_search_lower)
                | xq_catalog_sorted["id"].astype(str).str.contains(xq_search_lower)
            ]
        for _, xq_row in filtered_xq.iterrows():
            xq_id_raw = xq_row.get("id")
            if pd.isna(xq_id_raw):
                continue
            try:
                xq_id_int = int(xq_id_raw)
            except (TypeError, ValueError):
                continue
            xq_desc = safe_str(xq_row.get("description", ""))
            xq_purpose = safe_str(xq_row.get("purpose", ""))
            xq_input = safe_str(xq_row.get("input", ""))
            xq_expected = safe_str(xq_row.get("expected_output", ""))
            st.markdown(f"**xQ-{xq_id_int}:** {xq_desc}")
            if xq_purpose:
                st.caption(f"Purpose: {xq_purpose}")

with st.container():
    # Scope marker for vertical dividers
    st.markdown('<div class="qp-divider-scope"></div>', unsafe_allow_html=True)

    assets_for_requirements = [
        {
            "asset_id": asset_id,
            "asset_name": asset_name,
            "asset_type": "main",
            "equipment_type_id": asset_row.get("equipment_type_id"),
            "label": f"{asset_name} ({equipment_type_desc})"
        }
    ]

    if not peripheral_assets.empty:
        for _, periph in peripheral_assets.iterrows():
            periph_eq_type = get_equipment_type_by_id(periph.get("equipment_type_id"))
            periph_eq_type_desc = periph_eq_type["name"] if periph_eq_type else "Unknown"
            assets_for_requirements.append({
                "asset_id": int(periph["id"]),
                "asset_name": periph["name"],
                "asset_type": "peripheral",
                "equipment_type_id": periph.get("equipment_type_id"),
                "label": f"{periph['name']} ({periph_eq_type_desc})"
            })

    # Build enriched requirement data per asset
    requirements_by_asset = {}
    for asset_info in assets_for_requirements:
        entries = get_asset_traceability_entries(asset_info["asset_id"])
        if entries.empty:
            requirements_by_asset[asset_info["asset_id"]] = pd.DataFrame()
            continue

        # Enrich with requirement catalog data
        if not req_catalog.empty:
            req_cols = ["id", "description", "subchapter_id", "is_must", "is_gxp"]
            available = [c for c in req_cols if c in req_catalog.columns]
            entries = entries.merge(
                req_catalog[available].rename(columns={"id": "requirement_id", "description": "requirement_description"}),
                on="requirement_id",
                how="left",
                suffixes=("", "_req")
            )

        # Enrich with risk catalog data
        if not risk_catalog.empty:
            risk_cols = ["id", "possible_error", "severity_before_mitigation", "likelihood_before_mitigation", "detectability_before_mitigation"]
            available_risk = [c for c in risk_cols if c in risk_catalog.columns]
            entries = entries.merge(
                risk_catalog[available_risk].rename(columns={"id": "risk_id"}),
                on="risk_id",
                how="left",
                suffixes=("", "_risk")
            )

        # Enrich with subchapter name
        if not subchapter_catalog.empty and "subchapter_id" in entries.columns:
            entries = entries.merge(
                subchapter_catalog[["id", "name"]].rename(columns={"id": "subchapter_id", "name": "subchapter_name"}),
                on="subchapter_id",
                how="left",
                suffixes=("", "_sc")
            )

        requirements_by_asset[asset_info["asset_id"]] = entries

    if not any(not df.empty for df in requirements_by_asset.values()):
        st.info("No requirements assigned.")
        st.stop()

    can_edit_xq = is_editable(asset_phase, Tables.ASSET_TRACEABILITY_MATRIX, "xq_id")
    can_edit_xq_meta = is_editable(asset_phase, Tables.ASSET_TRACEABILITY_MATRIX, "xq_remark")

    save_all_clicked = _save_container.button("Save xQ Assignments", disabled=not can_edit_xq)

    # ---- SAVE LOGIC ----
    if save_all_clicked:
        changed = 0

        for asset_info in assets_for_requirements:
            asset_id_local = asset_info["asset_id"]
            asset_label = asset_info["label"]
            asset_reqs = requirements_by_asset.get(asset_id_local)
            if asset_reqs is None or asset_reqs.empty:
                continue

            for row_idx, entry in asset_reqs.iterrows():
                requirement_id = _int_or_none(entry.get("requirement_id"))
                risk_id_val = _int_or_none(entry.get("risk_id"))
                row_key = f"{asset_id_local}_{requirement_id}_{risk_id_val}_{row_idx}"

                if risk_id_val is None:
                    continue

                # Get before-mitigation values from risk catalog
                before_vals = get_before_mitigation_values(risk_id_val)
                before_level = before_vals.get("risk_level_before_mitigation", "")

                can_use_xq = before_level in ("high", "medium")
                if not can_use_xq:
                    continue

                # Check "Solved by xQ?" checkbox
                solved_by_xq_key = f"solved_by_xq_{row_key}"
                current_xq_id = _int_or_none(entry.get("xq_id"))
                has_xq = current_xq_id is not None
                xq_auto_assign = excel_to_bool(entry.get("xq_is_auto_assign", False))
                has_predefined_xq = xq_auto_assign and has_xq
                current_dq_id = _int_or_none(entry.get("dq_id"))
                solved_by_dq = current_dq_id is not None

                default_checked = has_predefined_xq or has_xq or (not solved_by_dq)
                solved_by_xq_checked = bool(st.session_state.get(solved_by_xq_key, default_checked))

                # If checkbox unchecked and has manually-assigned xQ → clear it
                if not solved_by_xq_checked and has_xq and not has_predefined_xq:
                    clear_traceability_xq(asset_id_local, requirement_id, risk_id_val)
                    changed += 1
                    continue

                if not solved_by_xq_checked:
                    continue

                # Auto-assign predefined xQ from defaults
                if xq_auto_assign and not has_xq:
                    default_xqs = get_default_xq_for_risk(risk_id_val)
                    if default_xqs:
                        predefined_xq_id = _int_or_none(default_xqs[0].get("xq_id"))
                        if predefined_xq_id is not None:
                            success = update_traceability_xq(
                                asset_id=asset_id_local,
                                requirement_id=requirement_id,
                                risk_id=risk_id_val,
                                xq_id=predefined_xq_id,
                                xq_is_auto_assign=True,
                            )
                            if success:
                                changed += 1

                # Manual or catalog selection for new/editable assignments
                elif not has_predefined_xq:
                    manual_key = f"xq_manual_{row_key}"
                    manual_enabled = bool(st.session_state.get(manual_key, False))

                    if manual_enabled:
                        # Manual entry: create new xQ catalog entry
                        manual_desc = safe_str(st.session_state.get(f"xq_manual_desc_{row_key}", "")).strip()
                        manual_purpose = safe_str(st.session_state.get(f"xq_manual_purpose_{row_key}", "")).strip()
                        manual_input = safe_str(st.session_state.get(f"xq_manual_input_{row_key}", "")).strip()
                        manual_output = safe_str(st.session_state.get(f"xq_manual_output_{row_key}", "")).strip()

                        if manual_desc:
                            new_xq_id = insert_row(Tables.XQ, {
                                "description": manual_desc,
                                "purpose": manual_purpose,
                                "input": manual_input,
                                "expected_output": manual_output,
                            })
                            if new_xq_id and new_xq_id > 0:
                                remark_key = f"xq_remark_{row_key}"
                                xq_remark = safe_str(st.session_state.get(remark_key, ""))
                                update_traceability_xq(
                                    asset_id=asset_id_local,
                                    requirement_id=requirement_id,
                                    risk_id=risk_id_val,
                                    xq_id=new_xq_id,
                                    xq_remark=xq_remark,
                                )
                                changed += 1
                    else:
                        # Catalog selection
                        select_key = f"xq_select_{row_key}"
                        selected_xq_id = st.session_state.get(select_key)

                        if selected_xq_id is not None:
                            if not has_xq or int(selected_xq_id) != current_xq_id:
                                remark_key = f"xq_remark_{row_key}"
                                xq_remark = safe_str(st.session_state.get(remark_key, ""))
                                success = update_traceability_xq(
                                    asset_id=asset_id_local,
                                    requirement_id=requirement_id,
                                    risk_id=risk_id_val,
                                    xq_id=selected_xq_id,
                                    xq_remark=xq_remark,
                                )
                                if success:
                                    changed += 1

                # Save xQ remark for existing assignments
                if has_xq:
                    remark_key = f"xq_remark_{row_key}"
                    current_xq_remark = safe_str(entry.get("xq_remark", ""))
                    if remark_key in st.session_state:
                        new_xq_remark = safe_str(st.session_state.get(remark_key, current_xq_remark))
                        if new_xq_remark != current_xq_remark:
                            update_traceability_xq(
                                asset_id=asset_id_local,
                                requirement_id=requirement_id,
                                risk_id=risk_id_val,
                                xq_id=current_xq_id,
                                xq_remark=new_xq_remark,
                            )
                            changed += 1

        if changed:
            st.success(f"{changed} xQ assignment(s) saved.")
        else:
            st.info("No changes to save.")

        st.rerun()

    # ---- RENDER TABLE ----
    missing_required_xq = set()

    for asset_info in assets_for_requirements:
        asset_id_local = asset_info["asset_id"]
        asset_label = asset_info["label"]
        section_title = "Main Asset" if asset_info["asset_type"] == "main" else "Peripheral"
        st.subheader(f"{section_title}: {asset_label}")

        asset_reqs = requirements_by_asset.get(asset_id_local)
        if asset_reqs is None or asset_reqs.empty:
            st.caption("No requirements assigned.")
            continue

        # Map subchapter names to Subchapter enum values for grouping
        subchapter_name_map = {}
        if not subchapter_catalog.empty:
            for _, sc_row in subchapter_catalog.iterrows():
                subchapter_name_map[_int_or_none(sc_row["id"])] = safe_str(sc_row.get("name", ""))

        for subchapter in Subchapter:
            chapter_label = SUBCHAPTER_LABELS[subchapter]
            st.markdown(f"**{chapter_label}**")
            indent_cols = st.columns([0.04, 0.96], gap="small")
            with indent_cols[1]:
                # Filter by subchapter: match subchapter enum value to subchapter name from catalog
                if "subchapter_name" in asset_reqs.columns:
                    sub_reqs = asset_reqs[asset_reqs["subchapter_name"] == subchapter.value].copy()
                elif "subchapter_id" in asset_reqs.columns:
                    # Fallback: find subchapter_id from catalog by name
                    sc_id = None
                    for sid, sname in subchapter_name_map.items():
                        if sname == subchapter.value:
                            sc_id = sid
                            break
                    if sc_id is not None:
                        sub_reqs = asset_reqs[asset_reqs["subchapter_id"] == sc_id].copy()
                    else:
                        sub_reqs = pd.DataFrame()
                else:
                    sub_reqs = pd.DataFrame()

                if not sub_reqs.empty and "requirement_id" in sub_reqs.columns:
                    sub_reqs["__risk_sort"] = sub_reqs["risk_id"].apply(_int_or_none)
                    sub_reqs = sub_reqs.sort_values(
                        ["requirement_id", "__risk_sort"],
                        na_position="last"
                    ).drop(columns=["__risk_sort"])

                if sub_reqs.empty:
                    st.caption("No requirements in this subchapter.")
                else:
                    # 26-column layout (added "Solved by xQ?" column at index 14)
                    column_widths = [
                        # Blue (URS) 0-4
                        0.6, 2.0, 1.0, 0.5, 0.5,
                        # Yellow (Risk) 5-12
                        0.6, 1.0, 0.5, 0.5, 0.5, 0.55, 0.6, 0.6,
                        # Green 13
                        0.8,
                        # Purple (xQ) 14-25
                        0.6, 0.7, 1.2, 1.0, 1.0, 1.0, 0.5, 0.5, 0.5, 0.55, 0.65, 1.0
                    ]

                    header_cols = st.columns(column_widths, gap="small")
                    # Blue URS headers (0-4)
                    header_cols[0].markdown('<span class="urs-header">ID</span>', unsafe_allow_html=True)
                    header_cols[1].markdown('<span class="urs-header">Requirement</span>', unsafe_allow_html=True)
                    header_cols[2].markdown('<span class="urs-header">Remark</span>', unsafe_allow_html=True)
                    header_cols[3].markdown('<span class="urs-header">GxP</span>', unsafe_allow_html=True)
                    header_cols[4].markdown('<span class="urs-header">Must-Have</span>', unsafe_allow_html=True)
                    # Yellow Risk headers (5-12)
                    header_cols[5].markdown('<span class="risk-header">Risk-ID</span>', unsafe_allow_html=True)
                    header_cols[6].markdown('<span class="risk-header">Risk Title</span>', unsafe_allow_html=True)
                    header_cols[7].markdown('<span class="risk-header">S (before)</span>', unsafe_allow_html=True)
                    header_cols[8].markdown('<span class="risk-header">O (before)</span>', unsafe_allow_html=True)
                    header_cols[9].markdown('<span class="risk-header">D (before)</span>', unsafe_allow_html=True)
                    header_cols[10].markdown('<span class="risk-header">RPN (before)</span>', unsafe_allow_html=True)
                    header_cols[11].markdown('<span class="risk-header">Level (before)</span>', unsafe_allow_html=True)
                    header_cols[12].markdown('<span class="risk-header">Mitigation</span>', unsafe_allow_html=True)
                    # Green header (13)
                    header_cols[13].markdown('<span class="solved-dq-header">Solved by DQ</span>', unsafe_allow_html=True)
                    # Purple xQ headers (14-25)
                    header_cols[14].markdown('<span class="xq-header">Solved by xQ?</span>', unsafe_allow_html=True)
                    header_cols[15].markdown('<span class="xq-header">xQ-ID</span>', unsafe_allow_html=True)
                    header_cols[16].markdown('<span class="xq-header">xQ Description</span>', unsafe_allow_html=True)
                    header_cols[17].markdown('<span class="xq-header">xQ Purpose</span>', unsafe_allow_html=True)
                    header_cols[18].markdown('<span class="xq-header">xQ Input</span>', unsafe_allow_html=True)
                    header_cols[19].markdown('<span class="xq-header">xQ Expected Output</span>', unsafe_allow_html=True)
                    header_cols[20].markdown('<span class="xq-header">S (after)</span>', unsafe_allow_html=True)
                    header_cols[21].markdown('<span class="xq-header">O (after)</span>', unsafe_allow_html=True)
                    header_cols[22].markdown('<span class="xq-header">D (after)</span>', unsafe_allow_html=True)
                    header_cols[23].markdown('<span class="xq-header">RPN (after)</span>', unsafe_allow_html=True)
                    header_cols[24].markdown('<span class="xq-header">Level (after)</span>', unsafe_allow_html=True)
                    header_cols[25].markdown('<span class="xq-header">xQ Remark</span>', unsafe_allow_html=True)

                    grouped_reqs = sub_reqs.groupby("requirement_id", sort=False)
                    for group_idx, (req_id_local, group) in enumerate(grouped_reqs):
                        if group_idx > 0:
                            st.markdown("---")

                        group_first = group.iloc[0]
                        requirement_text = safe_str(group_first.get("requirement_description", ""))
                        remark_text = safe_str(group_first.get("requirement_remark", ""))
                        is_gxp = excel_to_bool(group_first.get("is_gxp", False))
                        is_must = excel_to_bool(group_first.get("is_must", False))
                        seen_risks = set()

                        for row_pos, (row_idx, entry) in enumerate(group.iterrows()):
                            is_first_row = row_pos == 0
                            risk_id_val = _int_or_none(entry.get("risk_id"))
                            row_key = f"{asset_id_local}_{req_id_local}_{risk_id_val}_{row_idx}"

                            row_cols = st.columns(column_widths, gap="small")

                            # Columns 0-4: Requirement info (blue, not editable)
                            if is_first_row:
                                row_cols[0].markdown(f"REQ-{req_id_local}")
                                row_cols[1].markdown(requirement_text)
                                row_cols[2].markdown(remark_text or "")
                                row_cols[3].markdown("✅" if is_gxp else "❌")
                                row_cols[4].markdown("✅" if is_must else "❌")
                            else:
                                for ci in range(5):
                                    row_cols[ci].markdown("")

                            # Columns 5-6: Risk-ID, Risk Title
                            risk_title_val = safe_str(entry.get("possible_error", ""))
                            has_risk = risk_id_val is not None
                            show_risk = has_risk and risk_id_val not in seen_risks
                            if show_risk:
                                seen_risks.add(risk_id_val)

                            if show_risk:
                                row_cols[5].markdown(f"Risk-{risk_id_val}")
                                row_cols[6].markdown(risk_title_val or "")
                            else:
                                row_cols[5].markdown("" if has_risk else "⚠️" if is_first_row else "")
                                row_cols[6].markdown("")

                            # Columns 7-11: S (before), O (before), D (before), RPN (before), Level (before)
                            if has_risk:
                                before_vals = get_before_mitigation_values(risk_id_val)
                                before_sev = _int_or_none(before_vals.get("severity_before_mitigation"))
                                before_occ = _int_or_none(before_vals.get("likelihood_before_mitigation"))
                                before_det = _int_or_none(before_vals.get("detectability_before_mitigation"))
                                before_quant = _int_or_none(before_vals.get("quantification_before_mitigation"))
                                before_level = safe_str(before_vals.get("risk_level_before_mitigation", ""))
                            else:
                                before_sev = before_occ = before_det = before_quant = None
                                before_level = ""

                            if show_risk:
                                row_cols[7].markdown(str(before_sev) if before_sev else "")
                                row_cols[8].markdown(str(before_occ) if before_occ else "")
                                row_cols[9].markdown(str(before_det) if before_det else "")
                                row_cols[10].markdown(str(before_quant) if before_quant else "")
                                before_color = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(before_level, "⚪")
                                row_cols[11].markdown(f"{before_color} {before_level.upper()}" if before_level else "")
                            else:
                                for ci in range(7, 12):
                                    row_cols[ci].markdown("")

                            # Column 12: Mitigation required? (Y/N based on Level before)
                            mitigation_required_flag = before_level in ("high", "medium")
                            if show_risk:
                                row_cols[12].markdown("Y" if mitigation_required_flag else "N")
                            else:
                                row_cols[12].markdown("")

                            # Column 13: Solved by DQ (green, not editable)
                            current_dq_id = _int_or_none(entry.get("dq_id"))
                            solved_by_dq = current_dq_id is not None

                            if not mitigation_required_flag:
                                row_cols[13].markdown("n/a")
                            elif solved_by_dq:
                                row_cols[13].markdown(f"DQ-{current_dq_id}")
                            else:
                                row_cols[13].markdown("")

                            # ── xQ section (columns 14-25) ──
                            can_use_xq_mitigation = before_level in ("high", "medium")
                            current_xq_id = _int_or_none(entry.get("xq_id"))
                            has_xq = current_xq_id is not None
                            xq_auto_assign = excel_to_bool(entry.get("xq_is_auto_assign", False))
                            has_predefined_xq = xq_auto_assign and has_xq

                            # Column 14: Solved by xQ? checkbox
                            if not can_use_xq_mitigation:
                                row_cols[14].markdown("n/a")
                                solved_by_xq = False
                            else:
                                solved_by_xq_key = f"solved_by_xq_{row_key}"
                                # Default: checked if has xQ already, or mandatory (no DQ)
                                default_checked = has_predefined_xq or has_xq or (not solved_by_dq)
                                if solved_by_xq_key not in st.session_state:
                                    st.session_state[solved_by_xq_key] = default_checked
                                if has_predefined_xq:
                                    st.session_state[solved_by_xq_key] = True
                                checkbox_disabled = not can_edit_xq or has_predefined_xq
                                solved_by_xq = row_cols[14].checkbox(
                                    "xQ", key=solved_by_xq_key,
                                    disabled=checkbox_disabled,
                                    label_visibility="collapsed",
                                )
                                if solved_by_dq:
                                    row_cols[14].caption("DQ assigned")

                            if not can_use_xq_mitigation or not solved_by_xq:
                                # Empty purple columns 15-25
                                for ci in range(15, 26):
                                    row_cols[ci].markdown("")
                            else:
                                # Purple columns: xQ assignment

                                # Check default xQ from risk defaults
                                suggested_xq = None
                                if risk_id_val is not None:
                                    default_xqs = get_default_xq_for_risk(risk_id_val)
                                    if default_xqs:
                                        suggested_xq = _int_or_none(default_xqs[0].get("xq_id"))

                                selected_xq_id = None
                                manual_key = f"xq_manual_{row_key}"
                                manual_desc_key = f"xq_manual_desc_{row_key}"
                                manual_purpose_key = f"xq_manual_purpose_{row_key}"
                                manual_input_key = f"xq_manual_input_{row_key}"
                                manual_output_key = f"xq_manual_output_{row_key}"

                                # Column 15: xQ-ID
                                if has_predefined_xq:
                                    # Pre-defined, not removable
                                    row_cols[15].markdown(f"xQ-{current_xq_id} (predefined)")
                                elif has_xq and not can_edit_xq:
                                    # Already assigned, read-only
                                    row_cols[15].markdown(f"xQ-{current_xq_id}")
                                else:
                                    # Editable: selectbox + manual option
                                    if can_edit_xq:
                                        manual_enabled = bool(st.session_state.get(manual_key, False))
                                        select_key = f"xq_select_{row_key}"
                                        xq_options = [None] + xq_ids

                                        # Default to current or suggestion
                                        default_xq = current_xq_id if has_xq and current_xq_id in xq_ids else (suggested_xq if suggested_xq in xq_ids else None)
                                        default_index = xq_options.index(default_xq) if default_xq in xq_options else 0

                                        select_label = f"xQ [{row_key}]"
                                        selected_xq_id = row_cols[15].selectbox(
                                            select_label,
                                            xq_options,
                                            index=default_index,
                                            key=select_key,
                                            disabled=manual_enabled or not can_edit_xq,
                                            label_visibility="collapsed",
                                            format_func=lambda x: "-- Please select --" if x is None else f"xQ-{x}: {xq_desc_map.get(x, '')}"
                                        )

                                        # "No matching entry" checkbox for manual creation
                                        manual_enabled = row_cols[16].checkbox(
                                            "No matching entry in xQ catalog",
                                            key=manual_key,
                                            disabled=not can_edit_xq,
                                        )

                                        if not solved_by_dq and is_must:
                                            if manual_enabled:
                                                manual_desc_val = safe_str(st.session_state.get(manual_desc_key, ""))
                                                if not manual_desc_val.strip():
                                                    missing_required_xq.add(f"{asset_label} / REQ-{req_id_local}")
                                            else:
                                                _queue_required_style(required_styles, "select", select_label, selected_xq_id is not None)
                                                if selected_xq_id is None and not has_xq:
                                                    missing_required_xq.add(f"{asset_label} / REQ-{req_id_local}")
                                    else:
                                        row_cols[15].markdown(f"xQ-{current_xq_id}" if has_xq else "")

                                # Determine which xQ to display details for
                                manual_enabled_now = bool(st.session_state.get(manual_key, False)) if can_edit_xq else False
                                xq_id_for_display = current_xq_id if (has_xq and not (can_edit_xq and not has_predefined_xq)) else selected_xq_id

                                # Columns 16-19: xQ Description, Purpose, Input, Expected Output
                                if manual_enabled_now and can_edit_xq:
                                    # Manual entry fields
                                    row_cols[16].text_area(
                                        f"xQ Description (new) [{row_key}]",
                                        value=safe_str(st.session_state.get(manual_desc_key, "")),
                                        key=manual_desc_key,
                                        label_visibility="collapsed",
                                        placeholder="Enter xQ description...",
                                        height=80,
                                        disabled=not can_edit_xq,
                                    )
                                    row_cols[17].text_area(
                                        f"xQ Purpose (new) [{row_key}]",
                                        value=safe_str(st.session_state.get(manual_purpose_key, "")),
                                        key=manual_purpose_key,
                                        label_visibility="collapsed",
                                        placeholder="Enter purpose...",
                                        height=80,
                                        disabled=not can_edit_xq,
                                    )
                                    row_cols[18].text_area(
                                        f"xQ Input (new) [{row_key}]",
                                        value=safe_str(st.session_state.get(manual_input_key, "")),
                                        key=manual_input_key,
                                        label_visibility="collapsed",
                                        placeholder="Enter input...",
                                        height=80,
                                        disabled=not can_edit_xq,
                                    )
                                    row_cols[19].text_area(
                                        f"xQ Expected Output (new) [{row_key}]",
                                        value=safe_str(st.session_state.get(manual_output_key, "")),
                                        key=manual_output_key,
                                        label_visibility="collapsed",
                                        placeholder="Enter expected output...",
                                        height=80,
                                        disabled=not can_edit_xq,
                                    )
                                    # No after-mitigation values for manual (not yet in catalog)
                                    for ci in range(20, 25):
                                        row_cols[ci].markdown("")
                                else:
                                    if xq_id_for_display is not None:
                                        xq_info = get_row_by_id(Tables.XQ, xq_id_for_display)
                                        if xq_info:
                                            row_cols[16].markdown(safe_str(xq_info.get("description", "")))
                                            row_cols[17].markdown(safe_str(xq_info.get("purpose", "")))
                                            row_cols[18].markdown(safe_str(xq_info.get("input", "")))
                                            row_cols[19].markdown(safe_str(xq_info.get("expected_output", "")))
                                        else:
                                            for ci in range(16, 20):
                                                row_cols[ci].markdown("")
                                    else:
                                        for ci in range(16, 20):
                                            row_cols[ci].markdown("")

                                    # Columns 20-24: S (after), O (after), D (after), RPN (after), Level (after)
                                    after_fields = _get_xq_after_fields(xq_id_for_display)
                                    disp_sev = after_fields.get("severity_after_mitigation")
                                    disp_occ = after_fields.get("likelihood_after_mitigation")
                                    disp_det = after_fields.get("detectability_after_mitigation")
                                    disp_quant = after_fields.get("quantification_after_mitigation")
                                    disp_level = after_fields.get("risk_level_after_mitigation", "")

                                    row_cols[20].markdown(str(disp_sev) if disp_sev else "")
                                    row_cols[21].markdown(str(disp_occ) if disp_occ else "")
                                    row_cols[22].markdown(str(disp_det) if disp_det else "")

                                    if disp_quant is None and disp_sev and disp_occ and disp_det:
                                        disp_quant = calculate_quantification(disp_sev, disp_occ, disp_det)
                                    if not disp_level and disp_quant is not None:
                                        disp_level = calculate_risk_level(disp_quant)

                                    if disp_quant is not None:
                                        level_color = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(disp_level, "⚪")
                                        row_cols[23].markdown(str(disp_quant))
                                        row_cols[24].markdown(f"{level_color} {disp_level.upper()}" if disp_level else "")
                                    else:
                                        row_cols[23].markdown("")
                                        row_cols[24].markdown("")

                                # Column 25: xQ Remark
                                current_xq_remark = safe_str(entry.get("xq_remark", ""))
                                remark_key = f"xq_remark_{row_key}"

                                if can_edit_xq_meta:
                                    remark_label = f"xQ Remark [{row_key}]"
                                    row_cols[25].text_area(
                                        remark_label,
                                        value=safe_str(st.session_state.get(remark_key, current_xq_remark)),
                                        key=remark_key,
                                        label_visibility="collapsed",
                                        placeholder="Optional remark...",
                                        height=80,
                                        disabled=not can_edit_xq_meta
                                    )
                                else:
                                    row_cols[25].markdown(current_xq_remark or "")

    if can_edit_xq and missing_required_xq:
        st.error("Required xQ missing for: " + ", ".join(sorted(missing_required_xq)))

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
        risk_id_val = _int_or_none(entry.get("risk_id"))
        if risk_id_val is None:
            continue

        # Get before values from risk catalog
        before_vals = get_before_mitigation_values(risk_id_val)
        sev_before = _int_or_none(before_vals.get("severity_before_mitigation"))
        occ_before = _int_or_none(before_vals.get("likelihood_before_mitigation"))
        det_before = _int_or_none(before_vals.get("detectability_before_mitigation"))
        before_rows.append((sev_before, occ_before, det_before))

        # Check DQ assignment
        dq_id = _int_or_none(entry.get("dq_id"))
        xq_id = _int_or_none(entry.get("xq_id"))

        # Matrix 2: After DQ - replace before with DQ after values where DQ is assigned
        if dq_id is not None:
            dq_after = get_after_mitigation_values(dq_id, is_xq=False)
            sev_after_dq = _int_or_none(dq_after.get("severity_after_mitigation"))
            occ_after_dq = _int_or_none(dq_after.get("likelihood_after_mitigation"))
            det_after_dq = _int_or_none(dq_after.get("detectability_after_mitigation"))
            if sev_after_dq is not None and occ_after_dq is not None and det_after_dq is not None:
                after_dq_rows.append((sev_after_dq, occ_after_dq, det_after_dq))
            else:
                after_dq_rows.append((sev_before, occ_before, det_before))
        else:
            after_dq_rows.append((sev_before, occ_before, det_before))

        # Matrix 3: After xQ - replace with XQ after values if XQ is assigned, else DQ if available
        if xq_id is not None:
            xq_after = get_after_mitigation_values(xq_id, is_xq=True)
            sev_after_xq = _int_or_none(xq_after.get("severity_after_mitigation"))
            occ_after_xq = _int_or_none(xq_after.get("likelihood_after_mitigation"))
            det_after_xq = _int_or_none(xq_after.get("detectability_after_mitigation"))
            if sev_after_xq is not None and occ_after_xq is not None and det_after_xq is not None:
                after_xq_rows.append((sev_after_xq, occ_after_xq, det_after_xq))
            else:
                after_xq_rows.append((sev_before, occ_before, det_before))
        elif dq_id is not None:
            dq_after = get_after_mitigation_values(dq_id, is_xq=False)
            sev_after_dq = _int_or_none(dq_after.get("severity_after_mitigation"))
            occ_after_dq = _int_or_none(dq_after.get("likelihood_after_mitigation"))
            det_after_dq = _int_or_none(dq_after.get("detectability_after_mitigation"))
            if sev_after_dq is not None and occ_after_dq is not None and det_after_dq is not None:
                after_xq_rows.append((sev_after_dq, occ_after_dq, det_after_dq))
            else:
                after_xq_rows.append((sev_before, occ_before, det_before))
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
# SECTION 7: Export Qualification Plan Document
# ============================================================================
st.header("7. Export Qualification Plan Document")

# Validation: All medium/high risk rows NOT solved by DQ MUST have xQ assigned
missing_xq_for_export = []
high_level_after_xq = []

for asset_info in assets_for_requirements:
    asset_id_local = asset_info["asset_id"]
    asset_label = asset_info["label"]
    entries = get_asset_traceability_entries(asset_id_local)
    if entries.empty:
        continue

    for row_idx, entry in entries.iterrows():
        requirement_id = _int_or_none(entry.get("requirement_id"))
        risk_id_val = _int_or_none(entry.get("risk_id"))

        if risk_id_val is None:
            continue

        # Calculate before level from risk catalog
        before_vals = get_before_mitigation_values(risk_id_val)
        before_level = safe_str(before_vals.get("risk_level_before_mitigation", ""))

        if before_level not in ("medium", "high"):
            continue

        # Check if solved by DQ
        current_dq_id = _int_or_none(entry.get("dq_id"))
        solved_by_dq = current_dq_id is not None

        current_xq_id = _int_or_none(entry.get("xq_id"))

        # xQ is mandatory only when no DQ mitigation exists
        if not solved_by_dq and current_xq_id is None:
            missing_xq_for_export.append(f"REQ-{requirement_id} ({asset_label})")

        # Check level after is not HIGH (for all assigned xQ, regardless of DQ)
        if current_xq_id is not None:
            after_vals = get_after_mitigation_values(current_xq_id, is_xq=True)
            after_level = safe_str(after_vals.get("risk_level_after_mitigation", ""))
            if after_level == "high":
                high_level_after_xq.append(f"REQ-{requirement_id} ({asset_label})")

if missing_xq_for_export:
    st.error(f"Missing xQ assignment for risks: {', '.join(missing_xq_for_export)}")

if high_level_after_xq:
    st.warning(f"⚠️ Risk level after xQ mitigation is HIGH: {', '.join(high_level_after_xq)}")

has_validation_errors = bool(missing_xq_for_export) or bool(high_level_after_xq)

col_export, col_approve = st.columns([1, 1])

with col_export:
    export_disabled = asset_phase != Phase.XQ_PLAN or has_validation_errors
    export_btn = st.button(
        "Create xQ Plan (PDF)",
        type="primary",
        disabled=export_disabled
    )

with col_approve:
    approve_disabled = asset_phase != Phase.XQ_PLAN or has_validation_errors
    approve_btn = st.button("Approve xQ Plan", disabled=approve_disabled)

if approve_btn:
    doc_type = asset_phase.value
    target_phase = get_next_phase(Phase.XQ_PLAN)
    asset_ids = get_asset_and_peripheral_ids(asset_id)
    if target_phase and set_asset_phase(asset_ids, Phase.XQ_PLAN):
        record_document_approval(asset_id, doc_type)

        approved_version = get_latest_document_version_info(asset_id, doc_type)
        if not approved_version:
            st.error("Could not create approved PDF: No document version found. Please export first.")
        else:
            peripheral_assets_export = get_peripherals(asset_id)
            main_reqs = _build_qp_export_requirements(asset_id, req_catalog, risk_catalog, xq_catalog, dq_catalog, subchapter_catalog)

            peripherals_data = []
            if not peripheral_assets_export.empty:
                for _, periph in peripheral_assets_export.iterrows():
                    periph_reqs = _build_qp_export_requirements(int(periph["id"]), req_catalog, risk_catalog, xq_catalog, dq_catalog, subchapter_catalog)
                    periph_eq_type = get_equipment_type_by_id(periph.get("equipment_type_id"))
                    periph_eq_type_desc = periph_eq_type["name"] if periph_eq_type else "Unknown"
                    peripherals_data.append({
                        "name": periph["name"],
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

            pdf_base_context = get_pdf_base_context(asset_id)
            context = {
                **pdf_base_context,
                **approved_version,
                "version": approved_version["document_version"],
                "main_requirements": main_reqs,
                "peripherals": peripherals_data,
                "xq_catalog_map": xq_catalog_map_approve,
                "appendix_urls": [],
            }

            try:
                out_path = render_document("XQ_PLAN", context, approved=True)
                st.success(f"Approved PDF created: {out_path}")
            except Exception as e:
                st.error(f"Error during approved export: {e}")

        st.success("Phase set to xQ Execution.")
        st.rerun()

if export_btn and not export_disabled:
    peripheral_assets_export = get_peripherals(asset_id)
    main_reqs = _build_qp_export_requirements(asset_id, req_catalog, risk_catalog, xq_catalog, dq_catalog, subchapter_catalog)

    peripherals_data = []
    if not peripheral_assets_export.empty:
        for _, periph in peripheral_assets_export.iterrows():
            periph_reqs = _build_qp_export_requirements(int(periph["id"]), req_catalog, risk_catalog, xq_catalog, dq_catalog, subchapter_catalog)
            periph_eq_type = get_equipment_type_by_id(periph.get("equipment_type_id"))
            periph_eq_type_desc = periph_eq_type["name"] if periph_eq_type else "Unknown"
            peripherals_data.append({
                "name": periph["name"],
                "equipment_type": periph_eq_type_desc,
                "requirements": periph_reqs,
            })

    # Build xQ catalog map for PDF (xq_id -> full catalog row)
    xq_catalog_map_export = {}
    if not xq_catalog.empty and "id" in xq_catalog.columns:
        for _, xq_row in xq_catalog.iterrows():
            xq_id_raw = xq_row.get("id")
            if pd.notna(xq_id_raw):
                try:
                    xq_catalog_map_export[int(xq_id_raw)] = xq_row.to_dict()
                except (TypeError, ValueError):
                    pass

    # Record export BEFORE rendering so the timestamp appears in document history
    record_document_export(asset_id, asset_phase.value)

    pdf_base_context = get_pdf_base_context(asset_id)
    version_info = get_document_version_snapshot(asset_id, asset_phase.value)
    context = {
        **pdf_base_context,
        **version_info,
        "version": version_info["document_version"],
        "main_requirements": main_reqs,
        "peripherals": peripherals_data,
        "xq_catalog_map": xq_catalog_map_export,
        "appendix_urls": [],
    }

    try:
        out_path = render_document("XQ_PLAN", context)
        st.success(f"PDF created: {out_path}")
    except Exception as e:
        st.error(f"Error during export: {e}")

_apply_required_styles(required_styles)
