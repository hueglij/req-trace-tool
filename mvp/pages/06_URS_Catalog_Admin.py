"""
Requirements Catalog Administration - Manage equipment type assignments for standard requirements.
"""
import streamlit as st
import pandas as pd
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app_core.data_io import (
    load_table, get_equipment_types,
    update_equipment_type_requirements
)
from app_core.models import Tables, Subchapter, SUBCHAPTER_LABELS
from app_core.utils import excel_to_bool
from app_core.style import apply_global_style

st.set_page_config(page_title="Requirements Catalog Admin", page_icon="⚙️", layout="wide")
apply_global_style()

st.title("⚙️ Requirements Catalog Administration")
st.caption("Manage equipment type assignments for standard requirements.")

# Load data
requirements = load_table(Tables.REQUIREMENT)
equipment_types = get_equipment_types()
eq_req_junction = load_table(Tables.EQUIPMENT_TYPE_REQUIREMENT)

if requirements.empty:
    st.warning("No requirements catalog found. Please initialize the data first.")
    st.stop()

# Filter for standard requirements only
standard_mask = requirements["is_standard"].apply(
    lambda x: excel_to_bool(x) if pd.notna(x) else False
)
standard_reqs = requirements[standard_mask].copy()

if standard_reqs.empty:
    st.info("No standard requirements in the catalog.")
    st.stop()

# Build equipment type options
equipment_options = {}
if not equipment_types.empty:
    for _, eq in equipment_types.iterrows():
        eq_id = int(eq["id"])
        eq_name = eq["name"]
        equipment_options[str(eq_id)] = eq_name

st.markdown("---")
st.subheader("Standard Requirement Equipment Type Assignment")
st.caption(
    "Select the equipment types for each standard requirement. "
    "If no specific types are selected, the requirement applies to all new projects."
)

# Group by subchapter for better organization
subchapter_table = load_table(Tables.SUBCHAPTER)
for subchapter in Subchapter:
    # Find subchapter ID from subchapter table
    sc_id = None
    if not subchapter_table.empty:
        sc_match = subchapter_table[subchapter_table["name"] == subchapter.value]
        if not sc_match.empty:
            sc_id = int(sc_match.iloc[0]["id"])

    if sc_id is None:
        continue

    subchapter_reqs = standard_reqs[standard_reqs["subchapter_id"] == sc_id]
    if subchapter_reqs.empty:
        continue

    with st.expander(f"📂 {SUBCHAPTER_LABELS[subchapter]} ({len(subchapter_reqs)} requirements)", expanded=False):
        for _, req in subchapter_reqs.iterrows():
            req_id = int(req["id"])
            description = req["description"]

            # Get current equipment type assignments from junction table
            current_eq_ids = []
            if not eq_req_junction.empty:
                matched = eq_req_junction[eq_req_junction["requirement_id"] == req_id]
                current_eq_ids = [str(int(x)) for x in matched["equipment_type_id"].tolist()]

            col1, col2 = st.columns([2, 1])

            with col1:
                st.markdown(f"**REQ-{req_id}:** {str(description)[:100]}{'...' if len(str(description)) > 100 else ''}")

            with col2:
                # Multi-select for equipment types
                selected = st.multiselect(
                    "Equipment Types",
                    options=list(equipment_options.keys()),
                    default=current_eq_ids if current_eq_ids else list(equipment_options.keys()),
                    format_func=lambda x: equipment_options.get(x, x),
                    key=f"eq_select_{req_id}",
                    label_visibility="collapsed"
                )

                # Save button
                if st.button("💾 Save", key=f"save_{req_id}"):
                    new_ids = [int(x) for x in selected] if selected else []
                    success = update_equipment_type_requirements(req_id, new_ids)
                    if success:
                        st.success(f"REQ-{req_id} updated!")
                        st.rerun()
                    else:
                        st.error("Error saving.")

            st.divider()

# Info section
st.markdown("---")
st.subheader("ℹ️ Notes")
st.markdown("""
- **All Equipment Types**: If all types are selected, the requirement is automatically assigned to all new assets
- **Specific Types**: The requirement is only assigned to assets of the selected type
- **Multi-Select**: A requirement can be assigned to multiple equipment types
- **Standard Requirements**: Only standard requirements (is_standard=TRUE) can be edited here
- **Delete Protection**: Standard requirements that were auto-assigned cannot be removed from projects
""")
