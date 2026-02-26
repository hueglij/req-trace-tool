"""
URS Composer - Manage URS requirements and generate URS documents.
"""
import streamlit as st
import pandas as pd
from io import BytesIO
from pathlib import Path
import sys
from typing import Optional
try:
    import fitz
except Exception:
    import pymupdf as fitz
from PIL import Image, ImageDraw, ImageFont
import html

sys.path.insert(0, str(Path(__file__).parent.parent))

from app_core.data_io import (
    load_table, save_table, get_asset_traceability_entries,
    add_requirement_to_asset, get_default_risks_for_requirement, get_main_assets, get_peripherals,
    create_asset, get_location_hierarchy, get_asset_location, set_project_location,
    get_location_display,
    create_custom_requirement, insert_row, get_equipment_types, get_equipment_type_by_id,
    auto_assign_standard_requirements, can_delete_requirement,
    get_asset_phase, set_asset_phase, get_asset_and_peripheral_ids,
    record_document_export, record_document_approval,
    get_pdf_base_context, get_document_version_snapshot, get_latest_document_version_info,
    load_site_coordinates, get_row_by_id,
    get_all_media, get_asset_media, set_asset_media, delete_asset_media,
    auto_assign_media_for_asset,
)
from app_core.models import Tables, Phase, Subchapter, SUBCHAPTER_LABELS
from app_core.policy import (
    get_next_phase, is_phase_gates_enabled, get_soft_warning,
    is_editable, check_phase_gate
)
from app_core.pdf import render_document
from app_core.utils import ensure_output_dir, safe_str, excel_to_bool, calculate_quantification, calculate_risk_level, get_data_path
from app_core.style import apply_global_style, render_sticky_header

REQUIRED_EMPTY_BG = "#fff3bf"
REQUIRED_FILLED_BG = "#e6f4ea"


def _css_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')

@st.cache_data(show_spinner=False)
def _load_site_coordinates(modified_at: float):
    return load_site_coordinates()


def _get_site_coords(site_id: int):
    """Get site coordinates by site_id (new schema uses site_id as key)."""
    if not site_id:
        return None
    coords = load_site_coordinates()
    return coords.get(site_id)


def _load_overlay_font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()


def _draw_centered_label(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[float, float, float, float],
    label_text: str,
) -> None:
    if not label_text:
        return
    left, top, right, bottom = bounds
    max_width = right - left
    max_height = bottom - top
    if max_width <= 0 or max_height <= 0:
        return

    font_size = max(10, int(min(max_width, max_height) * 0.2))
    font = _load_overlay_font(font_size)
    while font_size > 8:
        text_box = draw.textbbox((0, 0), label_text, font=font)
        text_width = text_box[2] - text_box[0]
        text_height = text_box[3] - text_box[1]
        if text_width <= max_width * 0.9 and text_height <= max_height * 0.9:
            break
        font_size -= 1
        font = _load_overlay_font(font_size)

    text_box = draw.textbbox((0, 0), label_text, font=font)
    text_width = text_box[2] - text_box[0]
    text_height = text_box[3] - text_box[1]
    text_x = left + (max_width - text_width) / 2
    text_y = top + (max_height - text_height) / 2
    draw.text((text_x, text_y), label_text, font=font, fill=(255, 0, 0, 255))


def _apply_quadrant_overlay(
    png_bytes: bytes,
    site_id: int,
    start_letter: str,
    start_number: str,
    end_letter: str,
    end_number: str,
    label_text: Optional[str] = None,
) -> bytes:
    coords = _get_site_coords(site_id)
    if not coords:
        return png_bytes

    try:
        x1_pct = float(coords["numbers"][start_number])
        x2_pct = float(coords["numbers"][end_number])
        y1_pct = float(coords["letters"][start_letter])
        y2_pct = float(coords["letters"][end_letter])
    except KeyError:
        return png_bytes

    image = Image.open(BytesIO(png_bytes)).convert("RGBA")
    width, height = image.size

    def pct_to_x(pct: float) -> float:
        return width * pct / 100.0

    def pct_to_y(pct: float) -> float:
        return height * (1 - pct / 100.0)

    left = min(pct_to_x(x1_pct), pct_to_x(x2_pct))
    right = max(pct_to_x(x1_pct), pct_to_x(x2_pct))
    top = min(pct_to_y(y1_pct), pct_to_y(y2_pct))
    bottom = max(pct_to_y(y1_pct), pct_to_y(y2_pct))

    left = max(0, min(left, width))
    right = max(0, min(right, width))
    top = max(0, min(top, height))
    bottom = max(0, min(bottom, height))

    if right <= left or bottom <= top:
        return png_bytes

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")
    bounds = (left, top, right, bottom)
    draw.rectangle(
        [left, top, right, bottom],
        fill=(255, 0, 0, 51),
        outline=(255, 0, 0, 255),
        width=3,
    )
    if label_text:
        _draw_centered_label(draw, bounds, label_text.strip())
    combined = Image.alpha_composite(image, overlay)
    out = BytesIO()
    combined.save(out, format="PNG")
    return out.getvalue()



@st.cache_data(show_spinner=False)
def _load_floorplan_png(plan_path: Path, modified_at: float) -> bytes:
    with fitz.open(plan_path) as doc:
        page = doc.load_page(0)
        pix = page.get_pixmap(dpi=150, alpha=False)
        return pix.tobytes("png")


def _render_floorplan_preview(
    country_iso: str,
    site_iso: str,
    level_iso: str,
    site_id: int = 0,
    start_letter: Optional[str] = None,
    start_number: Optional[str] = None,
    end_letter: Optional[str] = None,
    end_number: Optional[str] = None,
    label_text: Optional[str] = None,
) -> None:
    if not country_iso or not site_iso or not level_iso:
        st.info("Floor plan preview not available: location codes missing.")
        return
    plan_path = get_data_path() / "Grundrisse" / f"Grundriss_{country_iso}_{site_iso}_{level_iso}.pdf"
    if not plan_path.exists():
        st.info(f"No floor plan PDF found: {plan_path.name}")
        return
    try:
        png_bytes = _load_floorplan_png(plan_path, plan_path.stat().st_mtime)
    except Exception as exc:
        st.error(f"Could not load floor plan as image: {exc}")
        return
    if all([start_letter, start_number, end_letter, end_number]) and site_id:
        png_bytes = _apply_quadrant_overlay(
            png_bytes,
            site_id,
            start_letter,
            start_number,
            end_letter,
            end_number,
            label_text=label_text,
        )
    st.image(png_bytes, width="stretch")


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


def _render_req_label(text: str) -> None:
    st.markdown(f"<div class=\"req-label\">{html.escape(text)}</div>", unsafe_allow_html=True)


def _apply_required_styles(style_rules) -> None:
    if not style_rules:
        return
    base_styles = ".req-label { display: block; font-size: 0.875rem; color: #31333f; margin-bottom: 0.2rem; }"
    st.markdown(
        "<style>\n" + base_styles + "\n" + "\n".join(style_rules) + "\n</style>",
        unsafe_allow_html=True,
    )


def _apply_optional_remark_defaults(asset_ids, requirement_catalog) -> int:
    """Set 'n/a' for optional (non-required) remarks that are currently empty."""
    if not asset_ids or requirement_catalog is None or requirement_catalog.empty:
        return 0
    df = load_table(Tables.ASSET_TRACEABILITY_MATRIX)
    if df.empty or "requirement_remark" not in df.columns:
        return 0

    flags = {}
    for _, row in requirement_catalog.iterrows():
        req_id = row.get("id")
        if pd.isna(req_id):
            continue
        flags[int(req_id)] = (
            excel_to_bool(row.get("remark_enabled", True)),
            excel_to_bool(row.get("remark_required", False)),
        )

    mask = df["asset_id"].isin(asset_ids)
    if not mask.any():
        return 0

    changed = 0
    for idx in df.index[mask]:
        req_id = df.at[idx, "requirement_id"]
        try:
            req_id_int = int(req_id)
        except (TypeError, ValueError):
            continue
        remark_flags = flags.get(req_id_int)
        if not remark_flags:
            continue
        remark_enabled, remark_required = remark_flags
        if not remark_enabled or remark_required:
            continue
        current_remark = safe_str(df.at[idx, "requirement_remark"])
        if not current_remark.strip():
            df.at[idx, "requirement_remark"] = "n/a"
            changed += 1

    if changed:
        save_table(Tables.ASSET_TRACEABILITY_MATRIX, df)

    return changed


def _get_subchapter_map():
    """Load subchapter table and build id->name and name->id maps."""
    sc_df = load_table(Tables.SUBCHAPTER)
    id_to_name = {}
    name_to_id = {}
    if not sc_df.empty:
        for _, row in sc_df.iterrows():
            sc_id = int(row["id"])
            sc_name = str(row["name"])
            id_to_name[sc_id] = sc_name
            name_to_id[sc_name] = sc_id
    return id_to_name, name_to_id


required_styles = []

st.set_page_config(page_title="URS Composer - Existing Project", page_icon="URS", layout="wide")
apply_global_style()

# CSS for colored column headers (matching PDF color scheme)
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
</style>
""",
    unsafe_allow_html=True,
)

page_name = "01_URS_Composer"

render_sticky_header("URS Composer - Existing Project")
st.markdown("Manage requirements and generate URS documents for an existing project.")

# ============================================================================
# SECTION 1: Project Selection
# ============================================================================
st.header("1. Project / Asset")

st.markdown("**Select an existing main asset:**")

main_assets = get_main_assets()

if main_assets.empty:
    st.info("No main assets found. Please create a new project first.")
    st.stop()

# Check if asset is selected
if "selected_asset_id" not in st.session_state or st.session_state.selected_asset_id is None:
    st.warning("Please select an asset in the Project Overview first.")
    st.stop()

asset_id = st.session_state.selected_asset_id
assets_df = load_table(Tables.ASSET)
asset_row = assets_df[assets_df["id"] == asset_id]

if asset_row.empty:
    st.error("The selected asset was not found.")
    st.stop()

asset = asset_row.iloc[0]
asset_name = asset["name"]

# Get project info
project_id = int(asset["project_id"]) if pd.notna(asset.get("project_id")) else None
project = get_row_by_id(Tables.PROJECT, project_id) if project_id else None
project_name = safe_str(project.get("name")) if project else ""

# Get business process step name
bps_name = ""
main_asset_df = load_table(Tables.MAIN_ASSET)
if not main_asset_df.empty:
    ma_row = main_asset_df[main_asset_df["asset_id"] == asset_id]
    if not ma_row.empty:
        bps_id = ma_row.iloc[0].get("business_process_step_id")
        if pd.notna(bps_id):
            bps = get_row_by_id(Tables.BUSINESS_PROCESS_STEP, int(bps_id))
            if bps:
                bps_name = safe_str(bps.get("name"))

# Get system owner name
system_owner_name = ""
if bps_id and pd.notna(bps_id):
    bps_so = load_table(Tables.BUSINESS_PROCESS_STEP_SYSTEM_OWNER)
    if not bps_so.empty:
        so_match = bps_so[bps_so["business_process_step_id"] == int(bps_id)]
        if not so_match.empty:
            so_id = so_match.iloc[0].get("system_owner_id")
            if pd.notna(so_id):
                so = get_row_by_id(Tables.SYSTEM_OWNER, int(so_id))
                if so:
                    system_owner_name = safe_str(so.get("role"))

asset_phase = get_asset_phase(asset_id)

if is_phase_gates_enabled():
    gate_check = check_phase_gate(asset_phase, page_name)
    if not gate_check["allowed"]:
        st.error(gate_check["message"])
        st.stop()

soft_warning = get_soft_warning(asset_phase, page_name)
if soft_warning:
    st.warning(soft_warning)

# Display selected asset info
# Get equipment type description
equipment_type_info = get_equipment_type_by_id(asset.get("equipment_type_id"))
equipment_type_desc = equipment_type_info["name"] if equipment_type_info else "Unknown"

with st.expander(f"Selected Asset: {asset_name}", expanded=True):
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Equipment Type:** {equipment_type_desc}")
        st.markdown(f"**Name:** {asset_name}")
        st.markdown(f"**Business Process Step:** {bps_name}")
    with col2:
        st.markdown(f"**System Owner:** {system_owner_name}")
        st.markdown(f"**Project Name:** {project_name}")

# ============================================================================
# SECTION 2: Location Assignment
# ============================================================================
st.header("2. Location")

hierarchy = get_location_hierarchy()
current_location = get_asset_location(asset_id)

# Check if location data exists
if hierarchy["countries"].empty:
    st.info("No location data available. Please import location data.")
else:
    # Soft warning if no location assigned
    if current_location is None:
        st.warning("No location assigned. Please select a location for the asset.")

    # Show current location if assigned
    if current_location is not None and project_id:
        location_display = get_location_display(project_id)
        if location_display:
            st.success(f"Current location: {location_display}")

    # Location selection cascade
    if asset_phase == Phase.URS:
        with st.expander("Change Location", expanded=current_location is None):
            countries = hierarchy["countries"]
            sites = hierarchy["sites"]
            levels = hierarchy["levels"]

            # Determine default indices based on current location
            default_country_idx = 0
            default_site_idx = 0
            default_level_idx = 0

            # Pre-filter sites and levels if current location exists
            prefiltered_sites = pd.DataFrame()
            prefiltered_levels = pd.DataFrame()

            if current_location is not None and not countries.empty:
                # Current location has level_id; look up site and country from there
                current_level_id = current_location.get("level_id")
                if current_level_id is not None and not levels.empty:
                    level_match = levels[levels["id"] == current_level_id]
                    if not level_match.empty:
                        current_site_id = level_match.iloc[0].get("site_id")
                        if current_site_id is not None and not sites.empty:
                            site_match = sites[sites["id"] == current_site_id]
                            if not site_match.empty:
                                current_country_id = site_match.iloc[0].get("country_id")

                                # Find country index
                                if current_country_id is not None:
                                    country_match = countries[countries["id"] == current_country_id]
                                    if not country_match.empty:
                                        country_name = country_match.iloc[0]["name"]
                                        country_list = countries["name"].tolist()
                                        if country_name in country_list:
                                            default_country_idx = country_list.index(country_name) + 1

                                        prefiltered_sites = sites[sites["country_id"] == current_country_id]

                                        if not prefiltered_sites.empty:
                                            site_name = site_match.iloc[0]["name"]
                                            site_list = prefiltered_sites["name"].tolist()
                                            if site_name in site_list:
                                                default_site_idx = site_list.index(site_name) + 1

                                            prefiltered_levels = levels[levels["site_id"] == current_site_id]
                                            if not prefiltered_levels.empty:
                                                level_name = level_match.iloc[0]["name"]
                                                level_list = prefiltered_levels["name"].tolist()
                                                if level_name in level_list:
                                                    default_level_idx = level_list.index(level_name) + 1

            col1, col2, col3 = st.columns(3)

            with col1:
                country_options = ["-- Select --"] + countries["name"].tolist() if not countries.empty else ["-- No data --"]
                selected_country = st.selectbox("Country", country_options, index=default_country_idx, key="loc_country")

            # Filter sites by country
            filtered_sites = pd.DataFrame()
            selected_country_row = None
            if selected_country != "-- Select --" and selected_country != "-- No data --":
                selected_country_row = countries[countries["name"] == selected_country].iloc[0]
                country_id = selected_country_row["id"]
                filtered_sites = sites[sites["country_id"] == country_id] if not sites.empty else pd.DataFrame()

            with col2:
                site_options = ["-- Select --"] + filtered_sites["name"].tolist() if not filtered_sites.empty else ["-- Select country first --"]
                # Use precomputed index only if country selection matches current location
                site_idx = default_site_idx if (not filtered_sites.empty and current_location and
                                                selected_country_row is not None and
                                                default_site_idx < len(site_options)) else 0
                selected_site = st.selectbox("Site", site_options, index=site_idx, key="loc_site")

            # Filter levels by site
            filtered_levels = pd.DataFrame()
            selected_site_row = None
            if selected_site not in ["-- Select --", "-- Select country first --"] and not filtered_sites.empty:
                selected_site_row = filtered_sites[filtered_sites["name"] == selected_site].iloc[0]
                site_id = int(selected_site_row["id"])
                filtered_levels = levels[levels["site_id"] == site_id] if not levels.empty else pd.DataFrame()

            with col3:
                level_options = ["-- Select --"] + filtered_levels["name"].tolist() if not filtered_levels.empty else ["-- Select site first --"]
                # Use precomputed index only if site selection matches current location
                level_idx = default_level_idx if (not filtered_levels.empty and current_location and
                                                  selected_site_row is not None and
                                                  default_level_idx < len(level_options)) else 0
                selected_level = st.selectbox("Level", level_options, index=level_idx, key="loc_level")

            # Quadrant-based location selection
            st.markdown("---")
            st.markdown("**Area (Quadrant Selection):**")

            # Define quadrant options
            site_id_for_coords = int(selected_site_row["id"]) if selected_site_row is not None else 0
            site_coords = _get_site_coords(site_id_for_coords) if site_id_for_coords else None
            quadrant_letters = []
            quadrant_numbers = []
            if site_coords:
                quadrant_letters = sorted(site_coords.get("letters", {}).keys())
                quadrant_numbers = sorted(
                    site_coords.get("numbers", {}).keys(),
                    key=lambda value: (0, int(value)) if str(value).isdigit() else (1, str(value)),
                )
            # Check if level is selected to enable quadrant selection
            level_selected = selected_level not in ["-- Select --", "-- Select site first --"]
            selected_level_row = None
            level_iso = ""
            if level_selected and not filtered_levels.empty:
                selected_level_row = filtered_levels[filtered_levels["name"] == selected_level].iloc[0]
                level_iso = safe_str(selected_level_row.get("name_short", ""))


            # Parse current location to pre-select quadrant values
            default_start_letter_idx = 0
            default_start_number_idx = 0
            default_end_letter_idx = 0
            default_end_number_idx = 0

            # Pre-compute quadrant defaults if current location matches selected level
            if current_location is not None and level_selected:
                # Look up coordinate codes from current location's y_start_id, y_end_id, x_start_id, x_end_id
                coord_y_df = load_table(Tables.COORDINATE_Y)
                coord_x_df = load_table(Tables.COORDINATE_X)

                def _get_coord_code(coord_table, coord_id):
                    if coord_id is None or pd.isna(coord_id):
                        return None
                    if coord_table.empty:
                        return None
                    match = coord_table[coord_table["coordinate_id"] == int(coord_id)]
                    if match.empty:
                        return None
                    return str(match.iloc[0]["code"]).strip()

                cur_start_letter = _get_coord_code(coord_y_df, current_location.get("y_start_id"))
                cur_end_letter = _get_coord_code(coord_y_df, current_location.get("y_end_id"))
                cur_start_number = _get_coord_code(coord_x_df, current_location.get("x_start_id"))
                cur_end_number = _get_coord_code(coord_x_df, current_location.get("x_end_id"))

                if cur_start_letter and cur_start_letter.upper() in quadrant_letters:
                    default_start_letter_idx = quadrant_letters.index(cur_start_letter.upper()) + 1
                if cur_end_letter and cur_end_letter.upper() in quadrant_letters:
                    default_end_letter_idx = quadrant_letters.index(cur_end_letter.upper()) + 1
                if cur_start_number and cur_start_number.zfill(2) in quadrant_numbers:
                    default_start_number_idx = quadrant_numbers.index(cur_start_number.zfill(2)) + 1
                if cur_end_number and cur_end_number.zfill(2) in quadrant_numbers:
                    default_end_number_idx = quadrant_numbers.index(cur_end_number.zfill(2)) + 1

            if level_selected:
                start_letter_options = ["--"] + quadrant_letters if quadrant_letters else ["-- No coordinates --"]
                start_number_options = ["--"] + quadrant_numbers if quadrant_numbers else ["-- No coordinates --"]
                end_letter_options = ["--"] + quadrant_letters if quadrant_letters else ["-- No coordinates --"]
                end_number_options = ["--"] + quadrant_numbers if quadrant_numbers else ["-- No coordinates --"]
            else:
                start_letter_options = ["-- Select level first --"]
                start_number_options = ["-- Select level first --"]
                end_letter_options = ["-- Select level first --"]
                end_number_options = ["-- Select level first --"]

            col_q1, col_q2, col_q3, col_q4 = st.columns(4)

            with col_q1:
                start_letter = st.selectbox(
                    "From (Letter)",
                    start_letter_options,
                    index=default_start_letter_idx if default_start_letter_idx < len(start_letter_options) else 0,
                    key="quadrant_start_letter"
                )

            with col_q2:
                start_number = st.selectbox(
                    "From (Number)",
                    start_number_options,
                    index=default_start_number_idx if default_start_number_idx < len(start_number_options) else 0,
                    key="quadrant_start_number"
                )

            with col_q3:
                end_letter = st.selectbox(
                    "To (Letter)",
                    end_letter_options,
                    index=default_end_letter_idx if default_end_letter_idx < len(end_letter_options) else 0,
                    key="quadrant_end_letter"
                )

            with col_q4:
                end_number = st.selectbox(
                    "To (Number)",
                    end_number_options,
                    index=default_end_number_idx if default_end_number_idx < len(end_number_options) else 0,
                    key="quadrant_end_number"
                )

            # Validate and display selected quadrant range
            quadrant_valid = (
                level_selected and
                start_letter != "--" and start_number != "--" and
                end_letter != "--" and end_number != "--"
            )
            if level_selected:
                country_iso = selected_country_row.get("iso_code", "") if selected_country_row is not None else ""
                site_iso = selected_site_row.get("iso_code", "") if selected_site_row is not None else ""
                selection = {}
                if quadrant_valid:
                    selection = {
                        "start_letter": start_letter,
                        "start_number": start_number,
                        "end_letter": end_letter,
                        "end_number": end_number,
                        "label_text": project_name,
                    }
                _render_floorplan_preview(
                    country_iso,
                    site_iso,
                    level_iso,
                    site_id=site_id_for_coords,
                    **selection,
                )

            if quadrant_valid:
                location_code = f"{start_letter}{start_number}-{end_letter}{end_number}"
                st.info(f"Selected area: **{location_code}**")

                # Get the selected level row
                selected_level_row = filtered_levels[filtered_levels["name"] == selected_level].iloc[0]
                level_id = int(selected_level_row["id"])

                if st.button("Save Location", type="primary"):
                    if project_id is None:
                        st.error("No project associated with this asset.")
                    else:
                        # Lookup coordinate IDs for the selected letters/numbers
                        coord_y_df = load_table(Tables.COORDINATE_Y)
                        coord_x_df = load_table(Tables.COORDINATE_X)

                        y_start_id = None
                        y_end_id = None
                        x_start_id = None
                        x_end_id = None

                        if not coord_y_df.empty:
                            y_start_match = coord_y_df[coord_y_df["code"].astype(str).str.strip().str.upper() == start_letter.upper()]
                            if not y_start_match.empty:
                                y_start_id = int(y_start_match.iloc[0]["coordinate_id"])
                            y_end_match = coord_y_df[coord_y_df["code"].astype(str).str.strip().str.upper() == end_letter.upper()]
                            if not y_end_match.empty:
                                y_end_id = int(y_end_match.iloc[0]["coordinate_id"])

                        if not coord_x_df.empty:
                            x_start_match = coord_x_df[coord_x_df["code"].astype(str).str.strip().str.zfill(2) == start_number]
                            if not x_start_match.empty:
                                x_start_id = int(x_start_match.iloc[0]["coordinate_id"])
                            x_end_match = coord_x_df[coord_x_df["code"].astype(str).str.strip().str.zfill(2) == end_number]
                            if not x_end_match.empty:
                                x_end_id = int(x_end_match.iloc[0]["coordinate_id"])

                        if all([y_start_id, y_end_id, x_start_id, x_end_id]):
                            set_project_location(
                                project_id=project_id,
                                level_id=level_id,
                                y_start_id=y_start_id,
                                y_end_id=y_end_id,
                                x_start_id=x_start_id,
                                x_end_id=x_end_id,
                            )
                            st.success(f"Location saved: {location_code}")
                            st.rerun()
                        else:
                            st.error("Could not resolve coordinate IDs. Please check coordinate data.")

    else:
        st.info("Location changes are only possible in URS phase.")
st.divider()

# ============================================================================
# SECTION 3: Peripherals (Existing Project)
# ============================================================================
st.header("3. Peripherals")

# Show list of assigned peripheral assets
peripheral_assets = get_peripherals(asset_id)

if peripheral_assets.empty:
    st.info("No peripheral devices assigned.")
else:
    st.markdown("**Assigned Peripheral Devices:**")
    for _, periph in peripheral_assets.iterrows():
        periph_eq_type = get_equipment_type_by_id(periph.get("equipment_type_id"))
        periph_eq_type_desc = periph_eq_type["name"] if periph_eq_type else "Unknown"
        st.markdown(f"- **{periph['name']}** ({periph_eq_type_desc})")

# Add new peripheral section
if asset_phase == Phase.URS:
    with st.expander("Add New Peripheral", expanded=False):
        peripheral_equipment_types = get_equipment_types(asset_type_id=2)  # 2 = peripheral

        if peripheral_equipment_types.empty:
            st.info("No equipment types for peripherals found.")
        else:
            with st.form("add_peripheral_existing_form"):
                periph_eq_type_options = {
                    int(row["id"]): row["name"]
                    for _, row in peripheral_equipment_types.iterrows()
                }
                periph_selected_eq_type_label = st.selectbox(
                    "Peripheral Equipment Type *",
                    list(periph_eq_type_options.values()),
                    key="existing_periph_eq_type"
                )
                periph_selected_eq_type_id = [k for k, v in periph_eq_type_options.items() if v == periph_selected_eq_type_label][0] if periph_selected_eq_type_label else None

                periph_name = st.text_input(
                    "Name *",
                    placeholder="e.g. Dosing pump for media supply",
                    key="existing_periph_desc"
                )

                periph_submitted = st.form_submit_button("Add Peripheral")

                if periph_submitted:
                    if not periph_selected_eq_type_id or not periph_name:
                        st.error("Please fill in all required fields.")
                    else:
                        periph_asset_id = create_asset(
                            equipment_type_id=periph_selected_eq_type_id,
                            name=periph_name,
                            project_id=project_id,
                            asset_type="peripheral",
                            main_asset_id=asset_id
                        )

                        # Auto-assign standard requirements for this peripheral equipment type
                        req_count = auto_assign_standard_requirements(
                            asset_id=periph_asset_id,
                            equipment_type_id=periph_selected_eq_type_id
                        )

                        # Auto-assign default media
                        media_count = auto_assign_media_for_asset(
                            asset_id=periph_asset_id,
                            equipment_type_id=periph_selected_eq_type_id
                        )

                        st.success(f"Peripheral added (ID: {periph_asset_id}) | {req_count} standard requirements assigned | {media_count} media assigned")
                        st.rerun()

st.divider()

# ============================================================================
# SECTION 4: Media (Utilities & Media Connections)
# ============================================================================
st.header("4. Media")

# Load media types from database
all_media = get_all_media()
if all_media.empty:
    MEDIA_COLUMNS = []
else:
    MEDIA_COLUMNS = [
        {"media_id": int(row["id"]), "label": row["name"]}
        for _, row in all_media.iterrows()
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
                        st.markdown(f"[x] {current_value}")
                    else:
                        st.markdown("--")

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
        st.info("Media can only be edited in URS phase.")
else:
    st.info("No media types configured.")

st.divider()

# ============================================================================
# SECTION 5: Requirements
# ============================================================================
st.header("5. Requirements")

# Load requirement catalog and current assignments
requirement_catalog = load_table(Tables.REQUIREMENT)
risk_catalog = load_table(Tables.RISK)

# Build subchapter maps
subchapter_id_to_name, subchapter_name_to_id = _get_subchapter_map()

if requirement_catalog.empty:
    st.warning("No requirement catalog found. Please initialize the data first.")

risk_desc_map = {}
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

# Build equipment_type_requirement lookup for checking if a requirement is standard for a given equipment type
eq_req_df = load_table(Tables.EQUIPMENT_TYPE_REQUIREMENT)

def is_standard_for_equipment(req_id, equipment_type_id) -> bool:
    """Check if a requirement is a standard requirement for this equipment type."""
    if equipment_type_id is None or pd.isna(equipment_type_id):
        return False
    try:
        equipment_type_id = int(equipment_type_id)
        req_id = int(req_id)
    except (TypeError, ValueError):
        return False
    if eq_req_df.empty:
        return False
    match = eq_req_df[(eq_req_df["equipment_type_id"] == equipment_type_id) & (eq_req_df["requirement_id"] == req_id)]
    return not match.empty


assets_for_requirements = [
    {
        "asset_id": asset_id,
        "asset_name": asset_name,
        "asset_type": "main",
        "equipment_type_id": asset.get("equipment_type_id"),
        "label": f"{asset_name} ({equipment_type_desc})"
    }
]

peripheral_assets = get_peripherals(asset_id)
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

asset_label_map = {asset_info["asset_id"]: asset_info["label"] for asset_info in assets_for_requirements}
asset_name_map = {asset_info["asset_id"]: asset_info["asset_name"] for asset_info in assets_for_requirements}
asset_eq_type_map = {asset_info["asset_id"]: asset_info.get("equipment_type_id") for asset_info in assets_for_requirements}

requirements_by_asset = {}
for asset_info in assets_for_requirements:
    traceability_entries = get_asset_traceability_entries(asset_info["asset_id"])
    if traceability_entries.empty:
        requirements_by_asset[asset_info["asset_id"]] = pd.DataFrame()
        continue

    # Merge with requirement catalog to get description, subchapter_id, etc.
    if not requirement_catalog.empty:
        merged = traceability_entries.merge(
            requirement_catalog,
            left_on="requirement_id",
            right_on="id",
            how="left",
            suffixes=("", "_catalog")
        )
    else:
        merged = traceability_entries
    requirements_by_asset[asset_info["asset_id"]] = merged


can_edit_remark = is_editable(asset_phase, Tables.ASSET_TRACEABILITY_MATRIX, "requirement_remark")
SUBCHAPTER_ICONS = {
    Subchapter.SAFETY_CONTROL: "shield",
    Subchapter.COMPONENTS: "gear",
    Subchapter.UTILITIES_MEDIA: "droplet",
    Subchapter.ENVIRONMENT: "leaf",
    Subchapter.SOFTWARE: "computer",
    Subchapter.DOCUMENTATION: "page_facing_up",
    Subchapter.TRAINING: "mortar_board",
    Subchapter.MAINTENANCE: "wrench",
    Subchapter.DELIVERY_ACCEPTANCE: "package",
}

if asset_phase == Phase.URS:
    save_all_clicked = st.button("Save Remarks", disabled=not can_edit_remark)
else:
    save_all_clicked = False
if save_all_clicked:
    df = load_table(Tables.ASSET_TRACEABILITY_MATRIX)
    changed = 0
    missing_required = []

    for asset_info in assets_for_requirements:
        asset_id_local = asset_info["asset_id"]
        asset_reqs = requirements_by_asset.get(asset_id_local)
        if asset_reqs is None or asset_reqs.empty:
            continue

        asset_reqs_unique = asset_reqs.drop_duplicates(subset=["requirement_id"])
        for _, entry in asset_reqs_unique.iterrows():
            remark_enabled = excel_to_bool(entry.get("remark_enabled", True))
            if not remark_enabled:
                continue

            req_id_local = entry["requirement_id"]
            key = f"remark_{asset_id_local}_{int(req_id_local)}"
            if key not in st.session_state:
                continue

            new_remark = safe_str(st.session_state.get(key, ""))
            if excel_to_bool(entry.get("remark_required", False)) and not new_remark.strip():
                missing_required.append(f"{asset_label_map.get(asset_id_local, asset_id_local)} / REQ-{int(req_id_local)}")

            mask = (df["asset_id"] == asset_id_local) & (df["requirement_id"] == int(req_id_local))
            if mask.any():
                current_remark = safe_str(df.loc[mask, "requirement_remark"].iloc[0])
                if new_remark != current_remark:
                    df.loc[mask, "requirement_remark"] = new_remark
                    changed += 1

    if changed:
        save_table(Tables.ASSET_TRACEABILITY_MATRIX, df)
        st.success(f"{changed} remark(s) saved.")
    else:
        st.info("No changes to save.")

    if missing_required:
        st.error("Missing required remarks: " + ", ".join(missing_required))

    st.rerun()

missing_required_remarks = []

for asset_info in assets_for_requirements:
    asset_id_local = asset_info["asset_id"]
    asset_label = asset_info["label"]
    section_title = "Main Asset" if asset_info["asset_type"] == "main" else "Peripheral"
    st.subheader(f"{section_title}: {asset_label}")

    asset_reqs = requirements_by_asset.get(asset_id_local)
    assigned_req_ids = set()
    if asset_reqs is not None and not asset_reqs.empty and "requirement_id" in asset_reqs.columns:
        assigned_req_ids = set(asset_reqs["requirement_id"].dropna().astype(int).tolist())
    asset_equipment_type_id = asset_eq_type_map.get(asset_id_local)

    for subchapter in Subchapter:
        chapter_label = SUBCHAPTER_LABELS[subchapter]
        chapter_title = chapter_label
        st.markdown(f"**{chapter_title}**")
        indent_cols = st.columns([0.04, 0.96], gap="small")
        with indent_cols[1]:
            sub_reqs = pd.DataFrame()
            # Filter by subchapter_id
            sc_id = subchapter_name_to_id.get(subchapter.value)
            if asset_reqs is not None and not asset_reqs.empty and sc_id is not None:
                sub_reqs = asset_reqs[asset_reqs["subchapter_id"] == sc_id].copy()
                if not sub_reqs.empty and "requirement_id" in sub_reqs.columns:
                    sub_reqs = sub_reqs.sort_values("requirement_id").drop_duplicates(subset=["requirement_id"])

            if sub_reqs.empty:
                st.caption("No requirements in this subchapter.")
            else:
                header_cols = st.columns([0.8, 3.2, 2.2, 0.6, 0.8, 0.5], gap="small")
                header_cols[0].markdown('<span class="urs-header">ID</span>', unsafe_allow_html=True)
                header_cols[1].markdown('<span class="urs-header">Requirement</span>', unsafe_allow_html=True)
                header_cols[2].markdown('<span class="urs-header">Remark</span>', unsafe_allow_html=True)
                header_cols[3].markdown('<span class="urs-header">GxP</span>', unsafe_allow_html=True)
                header_cols[4].markdown('<span class="urs-header">Must-Have</span>', unsafe_allow_html=True)
                header_cols[5].markdown("", unsafe_allow_html=True)

                for _, entry in sub_reqs.iterrows():
                    req_id_local = int(entry["requirement_id"])
                    requirement_text = safe_str(entry.get("description", ""))
                    is_std_for_asset = is_standard_for_equipment(req_id_local, asset_equipment_type_id)
                    is_manual_entry = not excel_to_bool(entry.get("requirement_is_auto_assign", False))
                    remark_enabled = excel_to_bool(entry.get("remark_enabled", True))
                    remark_required = excel_to_bool(entry.get("remark_required", False))
                    is_gxp = excel_to_bool(entry.get("is_gxp", False))
                    is_must = excel_to_bool(entry.get("is_must", False))

                    row_cols = st.columns([0.8, 3.2, 2.2, 0.6, 0.8, 0.5], gap="small")
                    row_cols[0].markdown(f"REQ-{req_id_local}")
                    row_cols[1].markdown(requirement_text)

                    current_remark = safe_str(entry.get("requirement_remark", ""))
                    new_remark = current_remark
                    if remark_enabled:
                        if can_edit_remark and asset_phase == Phase.URS:
                            remark_label = "Remark (REQUIRED) *" if remark_required else "Remark"
                            if remark_required:
                                remark_label = f"{remark_label} [{asset_id_local}-{req_id_local}]"
                            new_remark = row_cols[2].text_input(
                                remark_label,
                                value=current_remark,
                                key=f"remark_{asset_id_local}_{req_id_local}",
                                label_visibility="collapsed",
                                placeholder="Enter a remark..."
                            )
                            if remark_required:
                                _queue_required_style(
                                    required_styles,
                                    "text",
                                    remark_label,
                                    _is_filled(new_remark),
                                )
                        else:
                            row_cols[2].markdown(current_remark or "")

                        if remark_required and not new_remark.strip():
                            missing_required_remarks.append(f"{asset_label} / REQ-{req_id_local}")
                            row_cols[2].error("Required field")
                    else:
                        row_cols[2].markdown("")

                    row_cols[3].markdown("Yes" if is_gxp else "No")
                    row_cols[4].markdown("Yes" if is_must else "No")

                    can_delete = is_editable(asset_phase, Tables.ASSET_TRACEABILITY_MATRIX, "requirement_id")
                    if is_manual_entry and not is_std_for_asset and can_delete:
                        if row_cols[5].button("X", key=f"delete_{asset_id_local}_{req_id_local}"):
                            st.session_state["pending_delete"] = {
                                "asset_id": asset_id_local,
                                "requirement_id": req_id_local,
                                "asset_label": asset_label,
                                "requirement": requirement_text
                            }
                    else:
                        row_cols[5].markdown("")

                    pending = st.session_state.get("pending_delete")
                    if pending and pending.get("asset_id") == asset_id_local and pending.get("requirement_id") == req_id_local:
                        st.warning(f"REQ-{req_id_local} ({requirement_text}) - Remove from {asset_label}?")
                        col_confirm, col_cancel = st.columns(2)
                        if col_confirm.button("Yes, remove", key=f"confirm_delete_{asset_id_local}_{req_id_local}"):
                            df = load_table(Tables.ASSET_TRACEABILITY_MATRIX)
                            df = df[~((df["asset_id"] == asset_id_local) & (df["requirement_id"] == req_id_local))]
                            save_table(Tables.ASSET_TRACEABILITY_MATRIX, df)
                            st.session_state.pop("pending_delete", None)
                            st.success("Removed!")
                            st.rerun()
                        if col_cancel.button("Cancel", key=f"cancel_delete_{asset_id_local}_{req_id_local}"):
                            st.session_state.pop("pending_delete", None)
                            st.rerun()

            if asset_phase == Phase.URS:
                add_open_key = f"show_add_{asset_id_local}_{subchapter.value}"
                if st.button("+ Add Requirement", key=f"add_btn_{asset_id_local}_{subchapter.value}"):
                    st.session_state[add_open_key] = not st.session_state.get(add_open_key, False)

                if st.session_state.get(add_open_key):
                    st.markdown("**Add Requirement**")

                    can_add_asset = is_editable(asset_phase, Tables.ASSET_TRACEABILITY_MATRIX, "requirement_id")
                    can_add_catalog = is_editable(asset_phase, Tables.REQUIREMENT, "*")

                    search_term = st.text_input("Search Catalog", key=f"search_{asset_id_local}_{subchapter.value}")

                    # Filter requirement catalog by subchapter
                    filtered_catalog = pd.DataFrame()
                    if not requirement_catalog.empty and sc_id is not None:
                        filtered_catalog = requirement_catalog[requirement_catalog["subchapter_id"] == sc_id]

                    if not filtered_catalog.empty and assigned_req_ids:
                        filtered_catalog = filtered_catalog[~filtered_catalog["id"].isin(assigned_req_ids)]

                    if search_term and not filtered_catalog.empty:
                        filtered_catalog = filtered_catalog[
                            filtered_catalog["description"].str.contains(search_term, case=False, na=False)
                        ]

                    if filtered_catalog.empty:
                        st.info("No entries found.")
                    else:
                        for _, req in filtered_catalog.sort_values("id").iterrows():
                            req_id_local = int(req["id"])
                            is_std_for_asset = is_standard_for_equipment(req_id_local, asset_equipment_type_id)
                            is_must = excel_to_bool(req.get("is_must", False))
                            is_gxp = excel_to_bool(req.get("is_gxp", False))

                            col_a1, col_a2 = st.columns([4, 1])
                            with col_a1:
                                status = "Standard" if is_std_for_asset else "Custom"
                                must_label = "MUST" if is_must else "CAN"
                                gxp_label = " | GxP" if is_gxp else ""
                                st.markdown(f"**REQ-{req_id_local}** | {status} | {must_label}{gxp_label}")
                                st.markdown(safe_str(req.get("description", "")))

                            with col_a2:
                                if st.button("Add", key=f"add_existing_{asset_id_local}_{subchapter.value}_{req_id_local}", disabled=not can_add_asset):
                                    default_risks = get_default_risks_for_requirement(req_id_local)
                                    if not default_risks:
                                        add_requirement_to_asset(
                                            asset_id=asset_id_local,
                                            requirement_id=req_id_local,
                                            requirement_is_auto_assign=False,
                                        )
                                    else:
                                        for risk in default_risks:
                                            add_requirement_to_asset(
                                                asset_id=asset_id_local,
                                                requirement_id=req_id_local,
                                                risk_id=risk.get("risk_id"),
                                                requirement_is_auto_assign=False,
                                                risk_is_auto_assign=False,
                                            )
                                    st.rerun()

                    manual_key = f"manual_add_{asset_id_local}_{subchapter.value}"
                    if st.button("No match? Add manually", key=f"manual_btn_{asset_id_local}_{subchapter.value}"):
                        st.session_state[manual_key] = True

                    if st.session_state.get(manual_key):
                        subchapter_labels = [SUBCHAPTER_LABELS[s] for s in Subchapter]
                        default_sub_idx = subchapter_labels.index(SUBCHAPTER_LABELS[subchapter])

                        asset_ids_list = list(asset_label_map.keys())
                        default_asset_idx = asset_ids_list.index(asset_id_local) if asset_id_local in asset_ids_list else 0

                        with st.form(f"manual_form_{asset_id_local}_{subchapter.value}"):
                            manual_label_suffix = f"{asset_id_local}-{subchapter.value}"
                            manual_req_label = "Requirement text *"
                            manual_req_label_key = f"{manual_req_label} [{manual_label_suffix}]"
                            _render_req_label(manual_req_label)
                            new_requirement = st.text_area(
                                manual_req_label_key,
                                placeholder="Describe the requirement...",
                                height=100,
                                key=f"manual_req_{asset_id_local}_{subchapter.value}",
                                label_visibility="collapsed",
                            )
                            _queue_required_style(
                                required_styles,
                                "textarea",
                                manual_req_label_key,
                                _is_filled(new_requirement),
                            )
                            manual_sub_label = "Chapter *"
                            manual_sub_label_key = f"{manual_sub_label} [{manual_label_suffix}]"
                            _render_req_label(manual_sub_label)
                            selected_subchapter_label = st.selectbox(
                                manual_sub_label_key,
                                subchapter_labels,
                                index=default_sub_idx,
                                key=f"manual_sub_{asset_id_local}_{subchapter.value}",
                                label_visibility="collapsed",
                            )
                            _queue_required_style(
                                required_styles,
                                "select",
                                manual_sub_label_key,
                                _is_filled(selected_subchapter_label),
                            )
                            manual_asset_label = "Asset *"
                            manual_asset_label_key = f"{manual_asset_label} [{manual_label_suffix}]"
                            _render_req_label(manual_asset_label)
                            selected_asset_id = st.selectbox(
                                manual_asset_label_key,
                                asset_ids_list,
                                index=default_asset_idx,
                                format_func=lambda x: asset_label_map.get(x, str(x)),
                                key=f"manual_asset_{asset_id_local}_{subchapter.value}",
                                label_visibility="collapsed",
                            )
                            _queue_required_style(
                                required_styles,
                                "select",
                                manual_asset_label_key,
                                _is_filled(selected_asset_id),
                            )

                            col_flags1, col_flags2 = st.columns(2)
                            with col_flags1:
                                new_is_must = st.checkbox("Must-Have Requirement", key=f"manual_must_{asset_id_local}_{subchapter.value}")
                            with col_flags2:
                                new_is_gxp = st.checkbox("GxP Relevant", key=f"manual_gxp_{asset_id_local}_{subchapter.value}")

                            risk_new_key = f"manual_risk_new_{asset_id_local}_{subchapter.value}"
                            create_new_risk = st.checkbox("Create new risk", key=risk_new_key)

                            selected_risk_id = None
                            manual_risk_error = ""
                            manual_risk_harm = ""
                            manual_risk_cause = ""
                            manual_risk_sev = 1
                            manual_risk_occ = 1
                            manual_risk_det = 1

                            if create_new_risk:
                                st.caption("Enter new risk")
                                risk_error_label = "Possible Error *"
                                risk_error_label_key = f"{risk_error_label} [{manual_label_suffix}]"
                                _render_req_label(risk_error_label)
                                manual_risk_error = st.text_input(
                                    risk_error_label_key,
                                    value="",
                                    key=f"manual_risk_error_{asset_id_local}_{subchapter.value}",
                                    label_visibility="collapsed",
                                )
                                _queue_required_style(
                                    required_styles,
                                    "text",
                                    risk_error_label_key,
                                    _is_filled(manual_risk_error),
                                )
                                manual_risk_harm = st.text_input(
                                    "Harm",
                                    value="",
                                    key=f"manual_risk_harm_{asset_id_local}_{subchapter.value}",
                                )
                                manual_risk_cause = st.text_input(
                                    "Cause",
                                    value="",
                                    key=f"manual_risk_cause_{asset_id_local}_{subchapter.value}",
                                )
                                m_col1, m_col2, m_col3 = st.columns(3)
                                manual_risk_sev = m_col1.selectbox(
                                    "Severity (1-3)",
                                    [1, 2, 3],
                                    key=f"manual_risk_sev_{asset_id_local}_{subchapter.value}",
                                )
                                manual_risk_occ = m_col2.selectbox(
                                    "Occurrence (1-3)",
                                    [1, 2, 3],
                                    key=f"manual_risk_occ_{asset_id_local}_{subchapter.value}",
                                )
                                manual_risk_det = m_col3.selectbox(
                                    "Detection (1-3)",
                                    [1, 2, 3],
                                    key=f"manual_risk_det_{asset_id_local}_{subchapter.value}",
                                )
                            else:
                                risk_label = "Risk *"
                                risk_label_key = f"{risk_label} [{manual_label_suffix}]"
                                _render_req_label(risk_label)
                                risk_options = [None] + risk_ids
                                selected_risk_id = st.selectbox(
                                    risk_label_key,
                                    risk_options,
                                    key=f"manual_risk_select_{asset_id_local}_{subchapter.value}",
                                    label_visibility="collapsed",
                                    format_func=lambda x: "-- Please select --" if x is None else f"Risk-{x}: {risk_desc_map.get(x, '')}",
                                )
                                _queue_required_style(
                                    required_styles,
                                    "select",
                                    risk_label_key,
                                    selected_risk_id is not None,
                                )

                            submit_manual = st.form_submit_button("Add requirement", disabled=not (can_add_asset and can_add_catalog))

                            if submit_manual:
                                if not new_requirement:
                                    st.error("Please enter a requirement text.")
                                else:
                                    risk_error = False
                                    if create_new_risk:
                                        if not manual_risk_error.strip():
                                            st.error("Please enter a possible error for the risk.")
                                            risk_error = True
                                        if not risk_error:
                                            quant = calculate_quantification(manual_risk_sev, manual_risk_occ, manual_risk_det)
                                            level = calculate_risk_level(quant)
                                            new_risk = {
                                                "possible_error": manual_risk_error.strip(),
                                                "harm": manual_risk_harm.strip(),
                                                "cause": manual_risk_cause.strip(),
                                                "severity_before_mitigation": manual_risk_sev,
                                                "likelihood_before_mitigation": manual_risk_occ,
                                                "detectability_before_mitigation": manual_risk_det,
                                            }
                                            selected_risk_id = insert_row(Tables.RISK, new_risk)
                                    else:
                                        if selected_risk_id is None:
                                            st.error("Please select a risk.")
                                            risk_error = True

                                    if not risk_error:
                                        selected_subchapter_enum = [s for s in Subchapter if SUBCHAPTER_LABELS[s] == selected_subchapter_label][0]
                                        target_asset_id = selected_asset_id

                                        # Get subchapter_id for the selected subchapter
                                        target_sc_id = subchapter_name_to_id.get(selected_subchapter_enum.value)

                                        new_req_id = create_custom_requirement(
                                            description=new_requirement,
                                            subchapter_id=target_sc_id,
                                            is_must=new_is_must,
                                            is_gxp=new_is_gxp,
                                            remark_enabled=True,
                                            remark_required=False,
                                        )

                                        add_requirement_to_asset(
                                            asset_id=target_asset_id,
                                            requirement_id=new_req_id,
                                            risk_id=selected_risk_id,
                                            requirement_is_auto_assign=False,
                                        )

                                        st.session_state[manual_key] = False
                                        st.success(f"REQ-{new_req_id} created and added!")
                                        st.rerun()

    st.divider()

# Summary warning for missing required remarks
if missing_required_remarks:
    st.error("Missing required remarks for: " + ", ".join(missing_required_remarks))
# ============================================================================
# SECTION 6: PDF Export
# ============================================================================
st.divider()
st.header("6. Export URS Document")

# Pre-export checks
traceability_fresh = get_asset_traceability_entries(asset_id)
current_location = get_asset_location(asset_id)

# Check for issues
export_warnings = []
export_errors = []

if traceability_fresh.empty:
    export_warnings.append("No requirements assigned.")

if current_location is None:
    export_warnings.append("No location assigned.")

# Check for missing required remarks
if not traceability_fresh.empty and not requirement_catalog.empty:
    for _, entry in traceability_fresh.iterrows():
        req_id = entry["requirement_id"]
        req_info = requirement_catalog[requirement_catalog["id"] == req_id]
        if not req_info.empty:
            remark_required = excel_to_bool(req_info.iloc[0].get("remark_required", False))
            current_remark = safe_str(entry.get("requirement_remark", ""))
            if remark_required and not current_remark.strip():
                export_errors.append(f"REQ-{int(req_id)}: Required remark missing")

# Display warnings and errors
if export_warnings:
    for w in export_warnings:
        st.warning(w)

if export_errors:
    for e in export_errors:
        st.error(e)
    st.error("PDF export not possible: Please fix the errors above.")

# Export button
col_export, col_approve, col_info = st.columns([1, 1, 2])

with col_export:
    export_disabled = len(export_errors) > 0 or asset_phase != Phase.URS
    export_btn = st.button(
        "Generate URS (PDF)",
        type="primary",
        disabled=export_disabled
    )

with col_approve:
    approve_disabled = asset_phase != Phase.URS or export_disabled
    approve_btn = st.button("Approve URS", disabled=approve_disabled)

with col_info:
    if current_location and project_id:
        loc_display = get_location_display(project_id)
        st.caption(f"Location: {loc_display}")
    st.caption(f"Number of requirements: {len(traceability_fresh)}")

if approve_btn:
    doc_type = asset_phase.value
    target_phase = get_next_phase(Phase.URS)
    all_asset_ids = get_asset_and_peripheral_ids(asset_id)
    if target_phase and set_asset_phase(all_asset_ids, Phase.URS):
        record_document_approval(asset_id, doc_type)
        approved_version = get_latest_document_version_info(asset_id, doc_type)
        if not approved_version:
            st.error("Could not create approved PDF: No document version found. Please export first.")
        else:
            peripheral_assets = get_peripherals(asset_id)
            asset_ids_for_export = [asset_id]
            if not peripheral_assets.empty:
                asset_ids_for_export.extend(peripheral_assets["id"].tolist())
            _apply_optional_remark_defaults(asset_ids_for_export, requirement_catalog)
            traceability_fresh = get_asset_traceability_entries(asset_id)

            if not traceability_fresh.empty and not requirement_catalog.empty:
                merged = traceability_fresh.merge(
                    requirement_catalog[["id", "subchapter_id", "is_must", "is_gxp", "description"]],
                    left_on="requirement_id",
                    right_on="id",
                    how="left",
                    suffixes=("", "_cat"),
                )
                # Map subchapter_id to subchapter name
                merged["subchapter"] = merged["subchapter_id"].map(subchapter_id_to_name)
                if "requirement_id" in merged.columns:
                    merged = merged.drop_duplicates(subset=["requirement_id"])
                main_reqs = merged.to_dict("records")
            else:
                main_reqs = []

            peripherals_data = []
            if not peripheral_assets.empty:
                for _, periph in peripheral_assets.iterrows():
                    periph_trace = get_asset_traceability_entries(int(periph["id"]))
                    if not periph_trace.empty and not requirement_catalog.empty:
                        periph_merged = periph_trace.merge(
                            requirement_catalog[["id", "subchapter_id", "is_must", "is_gxp", "description"]],
                            left_on="requirement_id",
                            right_on="id",
                            how="left",
                            suffixes=("", "_cat"),
                        )
                        periph_merged["subchapter"] = periph_merged["subchapter_id"].map(subchapter_id_to_name)
                        if "requirement_id" in periph_merged.columns:
                            periph_merged = periph_merged.drop_duplicates(subset=["requirement_id"])
                        peripherals_data.append({
                            "name": periph["name"],
                            "requirements": periph_merged.to_dict("records")
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
                out_path = render_document("URS", context, approved=True)
                st.success(f"Approved URS PDF created: {out_path}")
            except Exception as e:
                st.error(f"Error during approved export: {e}")

        st.success("Phase set to RISK.")
        st.rerun()

if export_btn and not export_disabled:
    peripheral_assets = get_peripherals(asset_id)
    asset_ids_for_export = [asset_id]
    if not peripheral_assets.empty:
        asset_ids_for_export.extend(peripheral_assets["id"].tolist())
    _apply_optional_remark_defaults(asset_ids_for_export, requirement_catalog)
    traceability_fresh = get_asset_traceability_entries(asset_id)

    # Prepare context for PDF
    if not traceability_fresh.empty and not requirement_catalog.empty:
        merged = traceability_fresh.merge(
            requirement_catalog[["id", "subchapter_id", "is_must", "is_gxp", "description"]],
            left_on="requirement_id",
            right_on="id",
            how="left",
            suffixes=("", "_cat"),
        )
        merged["subchapter"] = merged["subchapter_id"].map(subchapter_id_to_name)
        if "requirement_id" in merged.columns:
            merged = merged.drop_duplicates(subset=["requirement_id"])
        main_reqs = merged.to_dict("records")
    else:
        main_reqs = []

    # Get peripheral requirements
    peripherals_data = []
    if not peripheral_assets.empty:
        for _, periph in peripheral_assets.iterrows():
            periph_trace = get_asset_traceability_entries(int(periph["id"]))
            if not periph_trace.empty and not requirement_catalog.empty:
                periph_merged = periph_trace.merge(
                    requirement_catalog[["id", "subchapter_id", "is_must", "is_gxp", "description"]],
                    left_on="requirement_id",
                    right_on="id",
                    how="left",
                    suffixes=("", "_cat"),
                )
                periph_merged["subchapter"] = periph_merged["subchapter_id"].map(subchapter_id_to_name)
                if "requirement_id" in periph_merged.columns:
                    periph_merged = periph_merged.drop_duplicates(subset=["requirement_id"])
                peripherals_data.append({
                    "name": periph["name"],
                    "requirements": periph_merged.to_dict("records")
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
        out_path = render_document("URS", context)
        st.success(f"URS PDF created: {out_path}")

        fs_path = render_document("FS", context)
        st.success(f"FS PDF created: {fs_path}")

    except Exception as e:
        st.error(f"Error during export: {e}")

_apply_required_styles(required_styles)
