"""
Helper functions for the URS MVP.
"""
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
import os
import pandas as pd


# ---------------------------------------------------------------------------
# Risk matrix constants – single source of truth for all pages
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Shared risk-matrix helper functions
# ---------------------------------------------------------------------------

def int_or_none(value):
    """Safely convert a value to int, returning None on failure or NaN."""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def likelihood_bucket(value) -> Optional[int]:
    """Map a raw likelihood score to one of the defined bucket values."""
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


def build_matrix_counts(rows):
    """Build a {severity: {likelihood: count}} dict from (severity, occurrence, detection) tuples."""
    counts = {
        severity: {lh: 0 for lh, _ in LIKELIHOOD_LEVELS}
        for severity, _ in SEVERITY_LEVELS
    }
    for severity, occurrence, detection in rows:
        if severity is None or occurrence is None or detection is None:
            continue
        severity_val = int_or_none(severity)
        occurrence_val = int_or_none(occurrence)
        detection_val = int_or_none(detection)
        if severity_val not in (1, 2, 3):
            continue
        if occurrence_val is None or detection_val is None:
            continue
        likelihood_score = occurrence_val * detection_val
        lh_bucket = likelihood_bucket(likelihood_score)
        if lh_bucket is None:
            continue
        counts[severity_val][lh_bucket] += 1
    return counts


def render_risk_matrix(title: str, counts: dict) -> None:
    """Render an HTML risk matrix into the Streamlit page."""
    import streamlit as st

    header_cells = "".join(
        f"<th>{label}</th>" for _, label in LIKELIHOOD_LEVELS
    )
    body_rows = []
    for severity, label in SEVERITY_LEVELS:
        row_cells = []
        for lh, _ in LIKELIHOOD_LEVELS:
            cell_color = CELL_COLOR_MAP.get((severity, lh), "green")
            value = counts.get(severity, {}).get(lh, 0)
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


def now_iso() -> str:
    """Return current timestamp in ISO format."""
    return datetime.now().isoformat(timespec="seconds")


def validate_required_fields(row: Dict[str, Any], required: List[str]) -> List[str]:
    """
    Validate that required fields are present and not empty.
    Returns list of missing/empty field names.
    """
    missing = []
    for field in required:
        if field not in row or row[field] is None or str(row[field]).strip() == "":
            missing.append(field)
    return missing


def get_data_path() -> Path:
    """Get the path to the data directory."""
    return Path(__file__).parent.parent / "data"


def get_output_path() -> Path:
    """Get the path to the output directory."""
    return Path(__file__).parent.parent / "output"


def ensure_output_dir() -> Path:
    """Ensure output directory exists and return path."""
    output_path = get_output_path()
    output_path.mkdir(parents=True, exist_ok=True)
    return output_path


def calculate_quantification(severity: int, occurrence: int, detection: int) -> int:
    """Calculate risk quantification (RPN) as S × O × D."""
    return severity * occurrence * detection


def calculate_risk_level(quantification: int) -> str:
    """
    Determine risk level based on quantification.
    - <=4: low
    - >4 to <=8: medium
    - >=9: high
    """
    if quantification < 4:
        return "low"
    elif quantification <= 8:
        return "medium"
    else:
        return "high"


def bool_to_excel(value: bool) -> str:
    """Convert Python bool to Excel TRUE/FALSE string."""
    return "TRUE" if value else "FALSE"


def excel_to_bool(value: Any) -> bool:
    """Convert Excel TRUE/FALSE string to Python bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.upper() == "TRUE"
    return bool(value)


def safe_int(value: Any, default: int = 0) -> int:
    """Safely convert value to int."""
    if value is None or (isinstance(value, float) and str(value) == "nan"):
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def safe_str(value: Any, default: str = "") -> str:
    """Safely convert value to string."""
    if value is None or (isinstance(value, float) and str(value) == "nan"):
        return default
    return str(value)


def generate_pdf_filename(doc_type: str, asset_name: str, version: str = "1.0", approved: bool = False) -> str:
    """Generate a standardized PDF filename."""
    # timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in asset_name)
    version_str = str(version).strip()
    if version_str.upper().startswith("V"):
        version_label = version_str
    else:
        version_label = f"V{version_str}"
    suffix = "_approved" if approved else ""
    return f"{doc_type}_{safe_name}_{version_label}{suffix}.pdf"
