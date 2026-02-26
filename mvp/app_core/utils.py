"""
Helper functions for the URS MVP.
"""
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
import os


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
