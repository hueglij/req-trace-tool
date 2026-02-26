"""
URS Composer - Create a new project.
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

sys.path.insert(0, str(Path(__file__).parent.parent))

from app_core.data_io import (
    insert_row, create_asset, get_location_hierarchy,
    set_project_location, get_equipment_types, get_business_process_steps,
    auto_assign_standard_requirements,
    load_site_coordinates, auto_assign_media_for_asset,
)
from app_core.models import Tables, Phase
from app_core.policy import (
    is_phase_gates_enabled,
    get_soft_warning,
    check_phase_gate,
)
from app_core.style import apply_global_style, render_sticky_header
from app_core.utils import get_data_path

st.set_page_config(page_title="URS Composer - New Project", page_icon="URS", layout="wide")
apply_global_style()

current_phase = Phase.URS
page_name = "00_URS_Composer_New"

if is_phase_gates_enabled():
    gate_check = check_phase_gate(current_phase, page_name)
    if not gate_check["allowed"]:
        st.error(gate_check["message"])
        st.stop()

soft_warning = get_soft_warning(current_phase, page_name)
if soft_warning:
    st.warning(soft_warning)

render_sticky_header("URS Composer - New Project")
st.markdown("Create a new main asset and then proceed to the requirements.")

if "pending_peripherals" not in st.session_state:
    st.session_state.pending_peripherals = []

if "reset_new_periph_desc" not in st.session_state:
    st.session_state.reset_new_periph_desc = False


def _is_filled(value) -> bool:
    return value is not None and str(value).strip() != ""


@st.cache_data(show_spinner=False)
def _load_site_coordinates(modified_at: float):
    return load_site_coordinates()


def _get_site_coords(site_id: int):
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

    font_size = max(8, int(min(max_width, max_height) * 0.2))
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


# =============================================================================
# 1. Main Asset
# =============================================================================
st.header("1. Main Asset")

main_equipment_types = get_equipment_types(asset_type_id=1)  # 1 = main
if main_equipment_types.empty:
    st.warning("No equipment types for main assets found. Please import equipment types.")
    st.stop()

col1, col2 = st.columns(2)

with col1:
    eq_type_options = {
        int(row["id"]): row["name"]
        for _, row in main_equipment_types.iterrows()
    }
    selected_eq_type_label = st.selectbox(
        "Equipment Type *",
        list(eq_type_options.values()),
        key="new_main_eq_type"
    )
    selected_eq_type_id = [k for k, v in eq_type_options.items() if v == selected_eq_type_label][0]

    new_asset_name = st.text_input(
        "Asset Name *",
        placeholder="e.g. 2000L Single-Use Bioreactor",
        key="new_main_desc"
    )

    business_process_steps = get_business_process_steps()
    step_options = []
    step_placeholder = "-- Select --"
    if business_process_steps.empty or "name" not in business_process_steps.columns:
        st.warning("No business process steps found. Please import data.")
        step_options = [step_placeholder]
    else:
        step_options = [step_placeholder] + business_process_steps["name"].dropna().tolist()

    selected_step = st.selectbox(
        "Business Process Step *",
        step_options,
        key="new_main_bps"
    )
    new_business_process_step = "" if selected_step == step_placeholder else selected_step

with col2:
    new_project_name = st.text_input(
        "Project Name *",
        placeholder="e.g. Bioreactor Installation Building A",
        key="new_main_title"
    )

st.divider()

# =============================================================================
# 2. Location
# =============================================================================
st.header("2. Location")

hierarchy = get_location_hierarchy()
location_valid = False
selected_country_row = None
selected_site_row = None
selected_level_row = None
level_iso = ""

countries = hierarchy["countries"]
sites = hierarchy["sites"]
levels = hierarchy["levels"]

if countries.empty:
    st.info("No location data found. Please import location data.")
else:
    col1, col2, col3 = st.columns(3)

    with col1:
        country_options = ["-- Select --"] + countries["name"].tolist()
        selected_country = st.selectbox("Country *", country_options, key="new_loc_country")
        country_placeholder = country_options[0]

    filtered_sites = pd.DataFrame()
    if selected_country != country_placeholder:
        selected_country_row = countries[countries["name"] == selected_country].iloc[0]
        country_id = selected_country_row["id"]
        filtered_sites = sites[sites["country_id"] == country_id] if not sites.empty else pd.DataFrame()

    with col2:
        site_options = ["-- Select --"] + filtered_sites["name"].tolist() if not filtered_sites.empty else ["-- Select country first --"]
        selected_site = st.selectbox("Site *", site_options, key="new_loc_site")
        site_placeholder = site_options[0]

    filtered_levels = pd.DataFrame()
    if selected_site != site_placeholder and not filtered_sites.empty:
        selected_site_row = filtered_sites[filtered_sites["name"] == selected_site].iloc[0]
        site_id = int(selected_site_row["id"])
        filtered_levels = levels[levels["site_id"] == site_id] if not levels.empty else pd.DataFrame()

    with col3:
        level_options = ["-- Select --"] + filtered_levels["name"].tolist() if not filtered_levels.empty else ["-- Select site first --"]
        selected_level = st.selectbox("Level *", level_options, key="new_loc_level")
        level_placeholder = level_options[0]

    st.markdown("**Area (Quadrant Selection):**")
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
    level_selected = selected_level != level_placeholder
    selected_level_row = None
    level_iso = ""
    if level_selected and not filtered_levels.empty:
        selected_level_row = filtered_levels[filtered_levels["name"] == selected_level].iloc[0]
        level_iso = selected_level_row.get("name_short", "")
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
        start_letter = st.selectbox("From (Letter) *", start_letter_options, key="new_q_start_l")
    with col_q2:
        start_number = st.selectbox("From (Number) *", start_number_options, key="new_q_start_n")
    with col_q3:
        end_letter = st.selectbox("To (Letter) *", end_letter_options, key="new_q_end_l")
    with col_q4:
        end_number = st.selectbox("To (Number) *", end_number_options, key="new_q_end_n")

    quadrant_valid = (
        level_selected
        and start_letter != start_letter_options[0]
        and start_number != start_number_options[0]
        and end_letter != end_letter_options[0]
        and end_number != end_number_options[0]
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
                "label_text": new_project_name,
            }
        _render_floorplan_preview(
            country_iso,
            site_iso,
            level_iso,
            site_id=site_id_for_coords,
            **selection,
        )

    if quadrant_valid:
        st.info(f"Selected area: **{start_letter}{start_number}-{end_letter}{end_number}**")
        selected_level_row = filtered_levels[filtered_levels["name"] == selected_level].iloc[0]
        level_iso = selected_level_row.get("name_short", "")
        location_valid = True

st.divider()

# =============================================================================
# 3. Peripherals (optional)
# =============================================================================
st.header("3. Peripherals")
st.markdown("Optional: Add peripheral devices to the main asset.")

peripheral_equipment_types = get_equipment_types(asset_type_id=2)  # 2 = peripheral
if peripheral_equipment_types.empty:
    st.info("No equipment types for peripherals found.")
else:
    if st.session_state.pending_peripherals:
        st.markdown("**Planned Peripherals:**")
        for idx, periph in enumerate(list(st.session_state.pending_peripherals)):
            col_p1, col_p2 = st.columns([4, 1])
            with col_p1:
                st.markdown(f"- {periph['name']} ({periph['equipment_type_name']})")
            with col_p2:
                if st.button("Remove", key=f"remove_pending_{idx}"):
                    st.session_state.pending_peripherals.pop(idx)
                    st.rerun()
    else:
        st.info("No peripherals added yet.")

    if st.session_state.get("reset_new_periph_desc"):
        st.session_state["new_periph_desc"] = ""
        st.session_state["reset_new_periph_desc"] = False

    with st.form("add_pending_peripheral_form"):
        periph_eq_type_options = {
            int(row["id"]): row["name"]
            for _, row in peripheral_equipment_types.iterrows()
        }
        periph_selected_eq_type_label = st.selectbox(
            "Peripheral Equipment Type *",
            list(periph_eq_type_options.values()),
            key="new_periph_eq_type"
        )
        periph_selected_eq_type_id = [
            k for k, v in periph_eq_type_options.items() if v == periph_selected_eq_type_label
        ][0]

        periph_name = st.text_input(
            "Name *",
            placeholder="e.g. Dosing pump for media supply",
            key="new_periph_desc"
        )

        periph_submitted = st.form_submit_button("Add Peripheral")

        if periph_submitted:
            if not periph_selected_eq_type_id or not periph_name:
                st.error("Please fill in all required fields.")
            else:
                st.session_state.pending_peripherals.append({
                    "equipment_type_id": periph_selected_eq_type_id,
                    "equipment_type_name": periph_selected_eq_type_label,
                    "name": periph_name
                })
                st.session_state["reset_new_periph_desc"] = True
                st.rerun()

st.divider()

# =============================================================================
# 4. Continue to Requirements
# =============================================================================

# Find business_process_step_id from name
bps_id = None
if new_business_process_step and not business_process_steps.empty:
    bps_match = business_process_steps[business_process_steps["name"] == new_business_process_step]
    if not bps_match.empty:
        bps_id = int(bps_match.iloc[0]["id"])

main_fields_ok = all([
    _is_filled(selected_eq_type_id),
    _is_filled(new_asset_name),
    _is_filled(new_business_process_step),
    _is_filled(new_project_name),
])
can_continue = main_fields_ok and location_valid

if st.button("Continue to Requirements", type="primary", disabled=not can_continue):
    # Create project first
    project_id = insert_row(Tables.PROJECT, {
        "name": new_project_name,
    })

    # Create main asset
    new_asset_id = create_asset(
        equipment_type_id=selected_eq_type_id,
        name=new_asset_name,
        project_id=project_id,
        asset_type="main",
        business_process_step_id=bps_id,
    )

    # Set project location
    if location_valid and selected_level_row is not None:
        # Lookup coordinate IDs for the selected letters/numbers
        from app_core.data_io import load_table
        coord_y = load_table(Tables.COORDINATE_Y)
        coord_x = load_table(Tables.COORDINATE_X)

        y_start_id = None
        y_end_id = None
        x_start_id = None
        x_end_id = None

        if not coord_y.empty:
            # Normalize: table stores e.g. "A", dropdown also provides "A"
            y_codes = coord_y["code"].astype(str).str.strip().str.upper()
            y_start_match = coord_y[y_codes == start_letter.strip().upper()]
            y_end_match = coord_y[y_codes == end_letter.strip().upper()]
            if not y_start_match.empty:
                y_start_id = int(y_start_match.iloc[0]["coordinate_id"])
            if not y_end_match.empty:
                y_end_id = int(y_end_match.iloc[0]["coordinate_id"])

        if not coord_x.empty:
            # Normalize: table stores e.g. "1", dropdown provides "01" (zero-padded)
            x_codes = coord_x["code"].astype(str).str.strip().str.zfill(2)
            x_start_match = coord_x[x_codes == start_number.strip().zfill(2)]
            x_end_match = coord_x[x_codes == end_number.strip().zfill(2)]
            if not x_start_match.empty:
                x_start_id = int(x_start_match.iloc[0]["coordinate_id"])
            if not x_end_match.empty:
                x_end_id = int(x_end_match.iloc[0]["coordinate_id"])

        if all([y_start_id, y_end_id, x_start_id, x_end_id]):
            set_project_location(
                project_id=project_id,
                level_id=int(selected_level_row["id"]),
                y_start_id=y_start_id,
                y_end_id=y_end_id,
                x_start_id=x_start_id,
                x_end_id=x_end_id,
            )

    # Auto-assign standard requirements
    auto_assign_standard_requirements(
        asset_id=new_asset_id,
        equipment_type_id=selected_eq_type_id
    )

    # Auto-assign default media for main asset
    try:
        auto_assign_media_for_asset(
            asset_id=new_asset_id,
            equipment_type_id=selected_eq_type_id
        )
    except Exception:
        pass

    # Create peripherals
    for periph in st.session_state.pending_peripherals:
        periph_asset_id = create_asset(
            equipment_type_id=periph["equipment_type_id"],
            name=periph["name"],
            project_id=project_id,
            asset_type="peripheral",
            main_asset_id=new_asset_id,
        )

        auto_assign_standard_requirements(
            asset_id=periph_asset_id,
            equipment_type_id=periph["equipment_type_id"]
        )

        try:
            auto_assign_media_for_asset(
                asset_id=periph_asset_id,
                equipment_type_id=periph["equipment_type_id"]
            )
        except Exception:
            pass

    st.session_state.selected_asset_id = new_asset_id
    st.session_state.pending_peripherals = []
    st.switch_page("pages/01_URS_Composer.py")
