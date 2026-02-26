"""
Excel I/O operations for the URS MVP (3NF normalized schema).
Handles reading, writing, and CRUD operations on Excel data files.
"""
import pandas as pd
from pathlib import Path
from typing import Dict, Any, Optional, List
import tempfile
import shutil
import os

from .utils import get_data_path, now_iso, calculate_quantification, calculate_risk_level, excel_to_bool
from .models import Tables, Phase


# Primary key column names for each table
PK_COLUMNS = {
    # Core catalogs
    Tables.COUNTRY: "id",
    Tables.SITE: "id",
    Tables.LEVEL: "id",
    Tables.COORDINATE: "id",
    Tables.SUBCHAPTER: "id",
    Tables.DOCUMENT_TYPE: "id",
    Tables.MITIGATION_CATEGORY: "id",
    Tables.MEDIA: "id",
    Tables.BUSINESS_PROCESS_STEP: "id",
    Tables.SYSTEM_OWNER: "id",
    Tables.ASSET_TYPE: "id",
    Tables.EQUIPMENT_TYPE: "id",
    Tables.REQUIREMENT: "id",
    Tables.RISK: "id",
    Tables.DQ: "id",
    Tables.XQ: "id",
    Tables.PROJECT: "id",
    Tables.PROJECT_LOCATION: "id",
    Tables.ASSET: "id",
    Tables.DOCUMENT: "id",
    Tables.DOCUMENT_VERSION: "id",
    Tables.CORRECTIVE_ACTION: "id",
    Tables.MITIGATION: "id",
    # Subtype tables (PK is FK to supertype)
    Tables.COORDINATE_X: None,
    Tables.COORDINATE_Y: None,
    Tables.MAIN_ASSET: None,
    Tables.PERIPHERAL_ASSET: None,
    # Junction / composite PK tables
    Tables.SITE_COORDINATE_VALUE: None,
    Tables.REQUIREMENT_RISK: None,
    Tables.DQ_RISK: None,
    Tables.XQ_RISK: None,
    Tables.EQUIPMENT_TYPE_REQUIREMENT: None,
    Tables.EQUIPMENT_TYPE_MEDIA: None,
    Tables.BUSINESS_PROCESS_STEP_SYSTEM_OWNER: None,
    Tables.PROJECT_PHASE: None,
    Tables.ASSET_RISK_PHASE_DECISION: None,
    Tables.ASSET_MEDIA: None,
    Tables.ASSET_TRACEABILITY_MATRIX: None,
}


def get_table_path(table_name: str) -> Path:
    """Get the file path for a table."""
    return get_data_path() / f"{table_name}.xlsx"


def load_table(table_name: str) -> pd.DataFrame:
    """Load a table from Excel file. Returns empty DataFrame if file doesn't exist."""
    file_path = get_table_path(table_name)
    if not file_path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_excel(file_path, engine="openpyxl")
        return df
    except Exception as e:
        print(f"Error loading {table_name}: {e}")
        return pd.DataFrame()


def save_table(table_name: str, df: pd.DataFrame) -> bool:
    """Save a DataFrame to Excel file with atomic write."""
    file_path = get_table_path(table_name)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd, temp_path = tempfile.mkstemp(suffix=".xlsx")
        os.close(fd)
        df.to_excel(temp_path, index=False, engine="openpyxl")
        shutil.move(temp_path, file_path)
        return True
    except Exception as e:
        print(f"Error saving {table_name}: {e}")
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.remove(temp_path)
        return False


# ─────────────────────────────────────────────────────
# Helper utilities
# ─────────────────────────────────────────────────────

def _normalize_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value)


def _int_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    return str(value).strip() == ""


def _risk_id_equals(series: pd.Series, value: Any) -> pd.Series:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return series.isna()
    target = _int_or_none(value)
    return series.apply(_int_or_none).eq(target)


def _parse_version(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, float) and pd.isna(value):
        return 0
    text = str(value).strip().upper()
    if text.startswith("V"):
        text = text[1:]
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return 0
    try:
        return int(digits)
    except ValueError:
        return 0


def _format_version(version_num: int) -> str:
    return f"V{version_num:02d}"


def _normalize_document_type(document_type: Any) -> str:
    if hasattr(document_type, "value"):
        document_type = document_type.value
    return _normalize_str(document_type).strip()


# ─────────────────────────────────────────────────────
# Generic CRUD
# ─────────────────────────────────────────────────────

def get_next_id(table_name: str) -> int:
    """Get the next available ID for a table."""
    pk_col = PK_COLUMNS.get(table_name)
    if pk_col is None:
        return 1
    df = load_table(table_name)
    if df.empty or pk_col not in df.columns:
        return 1
    max_id = df[pk_col].max()
    if pd.isna(max_id):
        return 1
    return int(max_id) + 1


def insert_row(table_name: str, row: Dict[str, Any]) -> int:
    """Insert a new row. Auto-assigns ID if table has a primary key. Returns new ID or -1."""
    df = load_table(table_name)
    pk_col = PK_COLUMNS.get(table_name)
    new_id = -1
    if pk_col is not None:
        new_id = get_next_id(table_name)
        row[pk_col] = new_id
    new_row = pd.DataFrame([row])
    df = pd.concat([df, new_row], ignore_index=True)
    save_table(table_name, df)
    return new_id


def update_row(table_name: str, filter_col: str, filter_val: Any, updates: Dict[str, Any]) -> bool:
    """Update rows matching a filter condition."""
    df = load_table(table_name)
    if df.empty:
        return False
    mask = df[filter_col] == filter_val
    if not mask.any():
        return False
    for col, val in updates.items():
        df.loc[mask, col] = val
    return save_table(table_name, df)


def delete_row(table_name: str, filter_col: str, filter_val: Any) -> bool:
    """Delete rows matching a filter condition."""
    df = load_table(table_name)
    if df.empty:
        return False
    mask = df[filter_col] != filter_val
    df = df[mask]
    return save_table(table_name, df)


def get_row_by_id(table_name: str, row_id: int) -> Optional[Dict[str, Any]]:
    """Get a single row by its primary key ID."""
    pk_col = PK_COLUMNS.get(table_name)
    if pk_col is None:
        return None
    df = load_table(table_name)
    if df.empty:
        return None
    row = df[df[pk_col] == row_id]
    if row.empty:
        return None
    return row.iloc[0].to_dict()


# ─────────────────────────────────────────────────────
# Site coordinate loading
# ─────────────────────────────────────────────────────

def load_site_coordinates() -> Dict[int, Dict[str, Dict[str, float]]]:
    """
    Load site coordinate percentage mappings.
    Returns: {site_id: {"letters": {code: pct}, "numbers": {code: pct}}}
    """
    coords = load_table(Tables.SITE_COORDINATE_VALUE)
    coord_y = load_table(Tables.COORDINATE_Y)
    coord_x = load_table(Tables.COORDINATE_X)

    if coords.empty:
        return {}

    # Build lookup: coordinate_id -> (axis, code)
    coord_lookup: Dict[int, tuple] = {}
    if not coord_y.empty:
        for _, r in coord_y.iterrows():
            coord_lookup[int(r["coordinate_id"])] = ("letters", str(r["code"]).strip().upper())
    if not coord_x.empty:
        for _, r in coord_x.iterrows():
            coord_lookup[int(r["coordinate_id"])] = ("numbers", str(r["code"]).strip().zfill(2))

    mapping: Dict[int, Dict[str, Dict[str, float]]] = {}
    for _, row in coords.iterrows():
        site_id = _int_or_none(row.get("site_id"))
        coord_id = _int_or_none(row.get("coordinate_id"))
        pct = row.get("percentage_value")
        if site_id is None or coord_id is None or pd.isna(pct):
            continue
        axis_info = coord_lookup.get(coord_id)
        if not axis_info:
            continue
        axis_key, code = axis_info
        entry = mapping.setdefault(site_id, {"letters": {}, "numbers": {}})
        try:
            entry[axis_key][code] = float(pct)
        except (TypeError, ValueError):
            continue

    return mapping


# ─────────────────────────────────────────────────────
# Asset CRUD (supertype/subtype pattern)
# ─────────────────────────────────────────────────────

def get_main_assets() -> pd.DataFrame:
    """Get all main assets (joined asset + main_asset)."""
    assets = load_table(Tables.ASSET)
    main = load_table(Tables.MAIN_ASSET)
    if assets.empty or main.empty:
        return pd.DataFrame()
    return assets[assets["id"].isin(main["asset_id"])]


def get_peripherals(main_asset_id: int) -> pd.DataFrame:
    """Get peripheral assets for a main asset."""
    assets = load_table(Tables.ASSET)
    periph = load_table(Tables.PERIPHERAL_ASSET)
    if assets.empty or periph.empty:
        return pd.DataFrame()
    periph_ids = periph[periph["main_asset_id"] == main_asset_id]["asset_id"]
    return assets[assets["id"].isin(periph_ids)]


def get_asset_and_peripheral_ids(asset_id: int) -> List[int]:
    """Return asset_id plus any peripherals if the asset is a main asset."""
    asset_ids = [asset_id]
    main = load_table(Tables.MAIN_ASSET)
    if not main.empty and asset_id in main["asset_id"].values:
        peripherals = get_peripherals(asset_id)
        if not peripherals.empty:
            asset_ids.extend(peripherals["id"].tolist())
    return asset_ids


def is_main_asset(asset_id: int) -> bool:
    """Check if an asset is a main asset."""
    main = load_table(Tables.MAIN_ASSET)
    if main.empty:
        return False
    return asset_id in main["asset_id"].values


def get_main_asset_id_for(asset_id: int) -> int:
    """Get the main asset ID for any asset (returns self if already main)."""
    if is_main_asset(asset_id):
        return asset_id
    periph = load_table(Tables.PERIPHERAL_ASSET)
    if not periph.empty:
        row = periph[periph["asset_id"] == asset_id]
        if not row.empty:
            return int(row.iloc[0]["main_asset_id"])
    return asset_id


def create_asset(
    equipment_type_id: int,
    name: str,
    project_id: int,
    asset_type: str = "main",
    business_process_step_id: Optional[int] = None,
    main_asset_id: Optional[int] = None
) -> int:
    """Create a new asset with supertype/subtype pattern. Returns asset ID."""
    row = {
        "name": name,
        "equipment_type_id": equipment_type_id,
        "project_id": project_id,
    }
    new_id = insert_row(Tables.ASSET, row)

    if asset_type == "main":
        subtype_row = {
            "asset_id": new_id,
            "business_process_step_id": business_process_step_id or 1,
        }
        df = load_table(Tables.MAIN_ASSET)
        df = pd.concat([df, pd.DataFrame([subtype_row])], ignore_index=True)
        save_table(Tables.MAIN_ASSET, df)
    elif asset_type == "peripheral" and main_asset_id is not None:
        subtype_row = {
            "asset_id": new_id,
            "main_asset_id": main_asset_id,
        }
        df = load_table(Tables.PERIPHERAL_ASSET)
        df = pd.concat([df, pd.DataFrame([subtype_row])], ignore_index=True)
        save_table(Tables.PERIPHERAL_ASSET, df)

    return new_id


# ─────────────────────────────────────────────────────
# Phase management (via project_phase table)
# ─────────────────────────────────────────────────────

def get_asset_phase(asset_id: int) -> Phase:
    """Get the current phase for an asset (via its project)."""
    asset = get_row_by_id(Tables.ASSET, asset_id)
    if not asset:
        return Phase.URS
    project_id = _int_or_none(asset.get("project_id"))
    if project_id is None:
        return Phase.URS
    return get_project_phase(project_id)


def get_project_phase(project_id: int) -> Phase:
    """Get the current phase for a project."""
    df = load_table(Tables.PROJECT_PHASE)
    if df.empty:
        return Phase.URS
    proj_phases = df[df["project_id"] == project_id]
    if proj_phases.empty:
        return Phase.URS

    # Find the latest approved phase
    from .policy import PHASE_SEQUENCE
    approved = proj_phases[proj_phases["status"] == "Approved"]
    if approved.empty:
        return Phase.URS

    # Map phase_id to Phase enum via document_type
    doc_types = load_table(Tables.DOCUMENT_TYPE)
    phase_map = {}
    if not doc_types.empty:
        for _, r in doc_types.iterrows():
            try:
                phase_map[int(r["id"])] = Phase(str(r["name"]))
            except (ValueError, KeyError):
                pass

    latest_idx = -1
    for _, r in approved.iterrows():
        phase_id = _int_or_none(r.get("phase_id"))
        if phase_id and phase_id in phase_map:
            phase = phase_map[phase_id]
            try:
                idx = PHASE_SEQUENCE.index(phase)
                if idx > latest_idx:
                    latest_idx = idx
            except ValueError:
                pass

    if latest_idx >= 0 and latest_idx + 1 < len(PHASE_SEQUENCE):
        return PHASE_SEQUENCE[latest_idx + 1]
    elif latest_idx >= 0:
        return Phase.DONE
    return Phase.URS


def set_asset_phase(asset_ids: List[int], phase: Phase) -> bool:
    """Set the phase for assets by updating project_phase for their project(s)."""
    if not asset_ids:
        return False

    # Find project IDs for these assets
    assets = load_table(Tables.ASSET)
    if assets.empty:
        return False

    project_ids = set()
    for aid in asset_ids:
        row = assets[assets["id"] == aid]
        if not row.empty:
            pid = _int_or_none(row.iloc[0].get("project_id"))
            if pid is not None:
                project_ids.add(pid)

    if not project_ids:
        return False

    # Get document_type_id for this phase
    doc_types = load_table(Tables.DOCUMENT_TYPE)
    phase_id = None
    if not doc_types.empty:
        match = doc_types[doc_types["name"] == phase.value]
        if not match.empty:
            phase_id = int(match.iloc[0]["id"])

    if phase_id is None:
        return False

    # Build set of phase_ids that come AFTER this phase in the sequence
    from .policy import PHASE_SEQUENCE
    later_phase_ids = set()
    try:
        phase_idx = PHASE_SEQUENCE.index(phase)
        for later_phase in PHASE_SEQUENCE[phase_idx + 1:]:
            if not doc_types.empty:
                later_match = doc_types[doc_types["name"] == later_phase.value]
                if not later_match.empty:
                    later_phase_ids.add(int(later_match.iloc[0]["id"]))
    except ValueError:
        pass

    df = load_table(Tables.PROJECT_PHASE)
    for pid in project_ids:
        # Remove any approvals for phases after this one (ensure clean state)
        if later_phase_ids and not df.empty:
            stale_mask = (df["project_id"] == pid) & (df["phase_id"].isin(later_phase_ids))
            if stale_mask.any():
                df = df[~stale_mask].reset_index(drop=True)

        mask = (df["project_id"] == pid) & (df["phase_id"] == phase_id) if not df.empty else pd.Series(dtype=bool)
        if not df.empty and mask.any():
            df.loc[mask, "status"] = "Approved"
            df.loc[mask, "approved_at"] = now_iso()
        else:
            new_row = {
                "project_id": pid,
                "phase_id": phase_id,
                "status": "Approved",
                "approved_at": now_iso(),
                "approved_by": "",
            }
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)

    return save_table(Tables.PROJECT_PHASE, df)


# ─────────────────────────────────────────────────────
# Location management
# ─────────────────────────────────────────────────────

def get_location_hierarchy() -> Dict[str, pd.DataFrame]:
    """Load the location hierarchy (countries -> sites -> levels)."""
    return {
        "countries": load_table(Tables.COUNTRY),
        "sites": load_table(Tables.SITE),
        "levels": load_table(Tables.LEVEL),
    }


def get_project_location(project_id: int) -> Optional[Dict[str, Any]]:
    """Get location for a project."""
    df = load_table(Tables.PROJECT_LOCATION)
    if df.empty:
        return None
    row = df[df["project_id"] == project_id]
    if row.empty:
        return None
    return row.iloc[0].to_dict()


def get_asset_location(asset_id: int) -> Optional[Dict[str, Any]]:
    """Get location for an asset (via its project)."""
    asset = get_row_by_id(Tables.ASSET, asset_id)
    if not asset:
        return None
    project_id = _int_or_none(asset.get("project_id"))
    if project_id is None:
        return None
    return get_project_location(project_id)


def set_project_location(
    project_id: int,
    level_id: int,
    y_start_id: int,
    y_end_id: int,
    x_start_id: int,
    x_end_id: int
) -> bool:
    """Set or update the location for a project."""
    df = load_table(Tables.PROJECT_LOCATION)

    new_data = {
        "project_id": project_id,
        "level_id": level_id,
        "y_start_id": y_start_id,
        "y_end_id": y_end_id,
        "x_start_id": x_start_id,
        "x_end_id": x_end_id,
    }

    if not df.empty and "project_id" in df.columns:
        mask = df["project_id"] == project_id
        if mask.any():
            for col, val in new_data.items():
                df.loc[mask, col] = val
            return save_table(Tables.PROJECT_LOCATION, df)

    # Insert new with auto-ID
    new_data["id"] = get_next_id(Tables.PROJECT_LOCATION)
    df = pd.concat([df, pd.DataFrame([new_data])], ignore_index=True)
    return save_table(Tables.PROJECT_LOCATION, df)


def get_location_display(project_id: int) -> str:
    """Get human-readable location path for a project."""
    loc = get_project_location(project_id)
    if not loc:
        return ""

    hierarchy = get_location_hierarchy()
    levels = hierarchy["levels"]
    sites = hierarchy["sites"]
    countries = hierarchy["countries"]

    parts = []
    level_id = _int_or_none(loc.get("level_id"))
    if level_id is not None and not levels.empty:
        level_row = levels[levels["id"] == level_id]
        if not level_row.empty:
            level = level_row.iloc[0]
            parts.append(_normalize_str(level.get("name_short", level.get("name"))))

            site_id = _int_or_none(level.get("site_id"))
            if site_id is not None and not sites.empty:
                site_row = sites[sites["id"] == site_id]
                if not site_row.empty:
                    site = site_row.iloc[0]
                    parts.insert(0, _normalize_str(site.get("iso_code")))

                    country_id = _int_or_none(site.get("country_id"))
                    if country_id is not None and not countries.empty:
                        country_row = countries[countries["id"] == country_id]
                        if not country_row.empty:
                            parts.insert(0, _normalize_str(country_row.iloc[0].get("iso_code")))

    # Add coordinate range
    coord_y = load_table(Tables.COORDINATE_Y)
    coord_x = load_table(Tables.COORDINATE_X)
    coord_parts = []
    for key, coord_table in [("y_start_id", coord_y), ("y_end_id", coord_y),
                              ("x_start_id", coord_x), ("x_end_id", coord_x)]:
        cid = _int_or_none(loc.get(key))
        if cid is not None and not coord_table.empty:
            match = coord_table[coord_table["coordinate_id"] == cid]
            if not match.empty:
                coord_parts.append(str(match.iloc[0]["code"]))

    if len(coord_parts) == 4:
        parts.append(f"{coord_parts[0]}{coord_parts[2]}-{coord_parts[1]}{coord_parts[3]}")

    return " > ".join(parts) if parts else ""


# ─────────────────────────────────────────────────────
# Risk / DQ / XQ catalog lookups
# ─────────────────────────────────────────────────────

def _get_risk_row(risk_id: Any) -> Optional[Dict[str, Any]]:
    """Get a risk catalog row by ID."""
    rid = _int_or_none(risk_id)
    if rid is None:
        return None
    df = load_table(Tables.RISK)
    if df.empty:
        return None
    row = df[df["id"] == rid]
    if row.empty:
        return None
    return row.iloc[0].to_dict()


def _get_dq_row(dq_id: Any) -> Optional[Dict[str, Any]]:
    """Get a DQ catalog row by ID."""
    did = _int_or_none(dq_id)
    if did is None:
        return None
    df = load_table(Tables.DQ)
    if df.empty:
        return None
    row = df[df["id"] == did]
    if row.empty:
        return None
    return row.iloc[0].to_dict()


def _get_xq_row(xq_id: Any) -> Optional[Dict[str, Any]]:
    """Get an XQ catalog row by ID."""
    xid = _int_or_none(xq_id)
    if xid is None:
        return None
    df = load_table(Tables.XQ)
    if df.empty:
        return None
    row = df[df["id"] == xid]
    if row.empty:
        return None
    return row.iloc[0].to_dict()


def get_before_mitigation_values(risk_id: Any) -> Dict[str, Any]:
    """Look up before-mitigation values from the risk table."""
    risk_row = _get_risk_row(risk_id)
    if not risk_row:
        return {
            "severity_before_mitigation": None,
            "likelihood_before_mitigation": None,
            "detectability_before_mitigation": None,
            "quantification_before_mitigation": None,
            "risk_level_before_mitigation": "",
            "mitigation_required": False,
        }

    s = _int_or_none(risk_row.get("severity_before_mitigation"))
    o = _int_or_none(risk_row.get("likelihood_before_mitigation"))
    d = _int_or_none(risk_row.get("detectability_before_mitigation"))

    quant = None
    level = ""
    if s and o and d:
        quant = calculate_quantification(s, o, d)
        level = calculate_risk_level(quant)

    return {
        "severity_before_mitigation": s,
        "likelihood_before_mitigation": o,
        "detectability_before_mitigation": d,
        "quantification_before_mitigation": quant,
        "risk_level_before_mitigation": level,
        "mitigation_required": level in ("high", "medium"),
    }


def get_after_mitigation_values(dq_or_xq_id: Any, is_xq: bool = False) -> Dict[str, Any]:
    """Look up after-mitigation values from DQ or XQ table."""
    row = _get_xq_row(dq_or_xq_id) if is_xq else _get_dq_row(dq_or_xq_id)
    if not row:
        return {
            "severity_after_mitigation": None,
            "likelihood_after_mitigation": None,
            "detectability_after_mitigation": None,
            "quantification_after_mitigation": None,
            "risk_level_after_mitigation": "",
        }

    s = _int_or_none(row.get("severity_after_mitigation"))
    o = _int_or_none(row.get("likelihood_after_mitigation"))
    d = _int_or_none(row.get("detectability_after_mitigation"))

    quant = None
    level = ""
    if s and o and d:
        quant = calculate_quantification(s, o, d)
        level = calculate_risk_level(quant)

    return {
        "severity_after_mitigation": s,
        "likelihood_after_mitigation": o,
        "detectability_after_mitigation": d,
        "quantification_after_mitigation": quant,
        "risk_level_after_mitigation": level,
    }


# ─────────────────────────────────────────────────────
# Default relationship lookups (read-only from admin tables)
# ─────────────────────────────────────────────────────

def get_default_risks_for_requirement(requirement_id: Any) -> List[Dict[str, Any]]:
    """Return default risks for a requirement from the relationship table."""
    target_id = _int_or_none(requirement_id)
    if target_id is None:
        return []
    rel_df = load_table(Tables.REQUIREMENT_RISK)
    if rel_df.empty:
        return []

    matches = rel_df[rel_df["requirement_id"] == target_id]
    if matches.empty:
        return []

    risk_catalog = load_table(Tables.RISK)
    out: List[Dict[str, Any]] = []
    for _, row in matches.iterrows():
        risk_id = _int_or_none(row.get("risk_id"))
        if risk_id is None:
            continue
        desc = ""
        if not risk_catalog.empty:
            rr = risk_catalog[risk_catalog["id"] == risk_id]
            if not rr.empty:
                desc = _normalize_str(rr.iloc[0].get("possible_error"))
        out.append({"risk_id": risk_id, "risk_description": desc})

    return out


def get_default_dq_for_risk(risk_id: Any) -> List[Dict[str, Any]]:
    """Return default DQ mitigations for a risk."""
    target_id = _int_or_none(risk_id)
    if target_id is None:
        return []
    rel_df = load_table(Tables.DQ_RISK)
    if rel_df.empty:
        return []
    matches = rel_df[rel_df["risk_id"] == target_id]
    if matches.empty:
        return []

    dq_catalog = load_table(Tables.DQ)
    out = []
    for _, row in matches.iterrows():
        dq_id = _int_or_none(row.get("dq_id"))
        if dq_id is None:
            continue
        desc = ""
        if not dq_catalog.empty:
            dr = dq_catalog[dq_catalog["id"] == dq_id]
            if not dr.empty:
                desc = _normalize_str(dr.iloc[0].get("description"))
        out.append({"dq_id": dq_id, "description": desc, "type": "DQ"})
    return out


def get_default_xq_for_risk(risk_id: Any) -> List[Dict[str, Any]]:
    """Return default XQ mitigations for a risk."""
    target_id = _int_or_none(risk_id)
    if target_id is None:
        return []
    rel_df = load_table(Tables.XQ_RISK)
    if rel_df.empty:
        return []
    matches = rel_df[rel_df["risk_id"] == target_id]
    if matches.empty:
        return []

    xq_catalog = load_table(Tables.XQ)
    out = []
    for _, row in matches.iterrows():
        xq_id = _int_or_none(row.get("xq_id"))
        if xq_id is None:
            continue
        desc = ""
        if not xq_catalog.empty:
            xr = xq_catalog[xq_catalog["id"] == xq_id]
            if not xr.empty:
                desc = _normalize_str(xr.iloc[0].get("description"))
        out.append({"xq_id": xq_id, "description": desc, "type": "XQ"})
    return out


def get_default_mitigations_for_risk(risk_id: Any) -> List[Dict[str, Any]]:
    """Return all default mitigations (DQ + XQ) for a risk."""
    return get_default_dq_for_risk(risk_id) + get_default_xq_for_risk(risk_id)


# ─────────────────────────────────────────────────────
# Traceability matrix
# ─────────────────────────────────────────────────────

def get_asset_traceability_entries(asset_id: int) -> pd.DataFrame:
    """Get all traceability matrix entries for an asset."""
    df = load_table(Tables.ASSET_TRACEABILITY_MATRIX)
    if df.empty:
        return df
    return df[df["asset_id"] == asset_id]


def add_requirement_to_asset(
    asset_id: int,
    requirement_id: int,
    risk_id: Optional[int] = None,
    requirement_is_auto_assign: bool = False,
    requirement_remark: str = "",
    risk_is_auto_assign: bool = False,
    dq_id: Optional[int] = None,
    dq_is_auto_assign: bool = False,
    xq_id: Optional[int] = None,
    xq_is_auto_assign: bool = False,
) -> bool:
    """Add a requirement-risk row to the traceability matrix."""
    df = load_table(Tables.ASSET_TRACEABILITY_MATRIX)

    # Check for duplicate
    if not df.empty:
        dup_mask = (df["asset_id"] == asset_id) & (df["requirement_id"] == requirement_id)
        if "risk_id" in df.columns:
            dup_mask = dup_mask & _risk_id_equals(df["risk_id"], risk_id)
        if dup_mask.any():
            return False

    row = {
        "asset_id": asset_id,
        "requirement_id": requirement_id,
        "risk_id": risk_id,
        "requirement_is_auto_assign": requirement_is_auto_assign,
        "requirement_remark": requirement_remark,
        "risk_is_auto_assign": risk_is_auto_assign,
        "risk_remark": "",
        "dq_id": dq_id,
        "dq_is_auto_assign": dq_is_auto_assign,
        "dq_remark": "",
        "xq_id": xq_id,
        "xq_is_auto_assign": xq_is_auto_assign,
        "xq_remark": "",
        "mitigation_id": None,
    }

    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    return save_table(Tables.ASSET_TRACEABILITY_MATRIX, df)


def update_traceability_risk(
    asset_id: int,
    requirement_id: int,
    new_risk_id: int,
    current_risk_id: Optional[int] = None,
    risk_is_auto_assign: bool = False,
    risk_remark: Optional[str] = None,
) -> bool:
    """Update risk assignment on a traceability matrix row."""
    df = load_table(Tables.ASSET_TRACEABILITY_MATRIX)
    if df.empty:
        return False

    base_mask = (df["asset_id"] == asset_id) & (df["requirement_id"] == requirement_id)
    if current_risk_id is not None:
        mask = base_mask & _risk_id_equals(df["risk_id"], current_risk_id)
    else:
        mask = base_mask & df["risk_id"].isna()

    if not mask.any():
        mask = base_mask

    if not mask.any():
        return False

    risk_changed = _int_or_none(current_risk_id) != _int_or_none(new_risk_id)

    if risk_changed:
        # Delete old row and create new
        source = df[mask].iloc[0].to_dict()
        df = df[~mask].reset_index(drop=True)
        save_table(Tables.ASSET_TRACEABILITY_MATRIX, df)

        return add_requirement_to_asset(
            asset_id=asset_id,
            requirement_id=requirement_id,
            risk_id=new_risk_id,
            requirement_is_auto_assign=source.get("requirement_is_auto_assign", False),
            requirement_remark=_normalize_str(source.get("requirement_remark", "")),
            risk_is_auto_assign=risk_is_auto_assign,
        )

    df.loc[mask, "risk_id"] = new_risk_id
    df.loc[mask, "risk_is_auto_assign"] = risk_is_auto_assign
    if risk_remark is not None:
        df.loc[mask, "risk_remark"] = risk_remark

    return save_table(Tables.ASSET_TRACEABILITY_MATRIX, df)


def update_traceability_dq(
    asset_id: int,
    requirement_id: int,
    risk_id: int,
    dq_id: int,
    dq_is_auto_assign: bool = False,
    dq_remark: str = "",
) -> bool:
    """Update DQ assignment on a traceability matrix row."""
    df = load_table(Tables.ASSET_TRACEABILITY_MATRIX)
    if df.empty:
        return False

    mask = (df["asset_id"] == asset_id) & (df["requirement_id"] == requirement_id) & _risk_id_equals(df["risk_id"], risk_id)
    if not mask.any():
        return False

    df.loc[mask, "dq_id"] = dq_id
    df.loc[mask, "dq_is_auto_assign"] = dq_is_auto_assign
    df.loc[mask, "dq_remark"] = dq_remark

    return save_table(Tables.ASSET_TRACEABILITY_MATRIX, df)


def update_traceability_xq(
    asset_id: int,
    requirement_id: int,
    risk_id: int,
    xq_id: int,
    xq_is_auto_assign: bool = False,
    xq_remark: str = "",
) -> bool:
    """Update XQ assignment on a traceability matrix row."""
    df = load_table(Tables.ASSET_TRACEABILITY_MATRIX)
    if df.empty:
        return False

    mask = (df["asset_id"] == asset_id) & (df["requirement_id"] == requirement_id) & _risk_id_equals(df["risk_id"], risk_id)
    if not mask.any():
        return False

    df.loc[mask, "xq_id"] = xq_id
    df.loc[mask, "xq_is_auto_assign"] = xq_is_auto_assign
    df.loc[mask, "xq_remark"] = xq_remark

    return save_table(Tables.ASSET_TRACEABILITY_MATRIX, df)


def clear_traceability_xq(
    asset_id: int,
    requirement_id: int,
    risk_id: int,
) -> bool:
    """Clear XQ assignment on a traceability matrix row."""
    df = load_table(Tables.ASSET_TRACEABILITY_MATRIX)
    if df.empty:
        return False

    mask = (df["asset_id"] == asset_id) & (df["requirement_id"] == requirement_id) & _risk_id_equals(df["risk_id"], risk_id)
    if not mask.any():
        return False

    df.loc[mask, "xq_id"] = None
    df.loc[mask, "xq_is_auto_assign"] = False
    df.loc[mask, "xq_remark"] = ""

    return save_table(Tables.ASSET_TRACEABILITY_MATRIX, df)


def add_additional_risk_to_asset(
    asset_id: int,
    requirement_id: int,
    risk_id: int,
    risk_is_auto_assign: bool = False,
) -> bool:
    """Add an additional risk row for an existing requirement."""
    df = load_table(Tables.ASSET_TRACEABILITY_MATRIX)

    # Verify requirement exists for this asset
    if df.empty:
        return False
    base_mask = (df["asset_id"] == asset_id) & (df["requirement_id"] == requirement_id)
    if not base_mask.any():
        return False

    # Check for duplicate risk
    if _risk_id_equals(df[base_mask]["risk_id"], risk_id).any():
        return False

    source = df[base_mask].iloc[0].to_dict()

    # Get default DQ/XQ for this risk
    dq_defaults = get_default_dq_for_risk(risk_id)
    xq_defaults = get_default_xq_for_risk(risk_id)
    dq_id = dq_defaults[0]["dq_id"] if dq_defaults else None
    xq_id = xq_defaults[0]["xq_id"] if xq_defaults else None

    return add_requirement_to_asset(
        asset_id=asset_id,
        requirement_id=requirement_id,
        risk_id=risk_id,
        requirement_is_auto_assign=source.get("requirement_is_auto_assign", False),
        requirement_remark=_normalize_str(source.get("requirement_remark", "")),
        risk_is_auto_assign=risk_is_auto_assign,
        dq_id=dq_id,
        dq_is_auto_assign=bool(dq_id),
        xq_id=xq_id,
        xq_is_auto_assign=bool(xq_id),
    )


def record_xq_execution(
    asset_id: int,
    requirement_id: int,
    risk_id: int,
    xq_output: str,
    passed: bool,
    need_correction: bool = False,
    failed_description: str = "",
    failed_justification: str = "",
    file_path: str = "",
    corrective_action_name: str = "",
    corrective_action_responsible: str = "",
    corrective_action_status: str = "",
    corrective_action_proof: str = "",
) -> bool:
    """Record xQ execution results in mitigation + corrective_action tables."""
    # Create or update corrective action if needed
    corrective_action_id = None
    if not passed and need_correction and corrective_action_name:
        ca_row = {
            "name": corrective_action_name,
            "responsible": corrective_action_responsible,
            "status": corrective_action_status,
            "proof_file_path": corrective_action_proof,
        }
        corrective_action_id = insert_row(Tables.CORRECTIVE_ACTION, ca_row)

    # Check if a mitigation record already exists for this row
    tm_df = load_table(Tables.ASSET_TRACEABILITY_MATRIX)
    if tm_df.empty:
        return False

    tm_mask = (tm_df["asset_id"] == asset_id) & (tm_df["requirement_id"] == requirement_id) & _risk_id_equals(tm_df["risk_id"], risk_id)
    if not tm_mask.any():
        return False

    existing_mit_id = _int_or_none(tm_df.loc[tm_mask, "mitigation_id"].iloc[0])

    mitigation_data = {
        "risk_id": risk_id,
        "phase": "XQ_EXECUTION",
        "file_path": file_path,
        "status": "done" if passed else "open",
        "passed": passed,
        "failed_description": failed_description if not passed else "",
        "mitigation_category_id": 2,  # XQ
        "remark": "",
        "need_correction": need_correction,
        "justification": failed_justification if not passed and not need_correction else "",
        "corrective_action_id": corrective_action_id,
        "xq_output": xq_output,
    }

    if existing_mit_id is not None:
        # Update existing mitigation record
        mit_df = load_table(Tables.MITIGATION)
        mit_mask = mit_df["id"] == existing_mit_id
        if mit_mask.any():
            for col, val in mitigation_data.items():
                mit_df.loc[mit_mask, col] = val
            save_table(Tables.MITIGATION, mit_df)
            return True

    # No existing record — insert new mitigation
    mitigation_id = insert_row(Tables.MITIGATION, mitigation_data)

    # Update traceability matrix with new mitigation_id
    tm_df = load_table(Tables.ASSET_TRACEABILITY_MATRIX)
    tm_mask = (tm_df["asset_id"] == asset_id) & (tm_df["requirement_id"] == requirement_id) & _risk_id_equals(tm_df["risk_id"], risk_id)
    tm_df.loc[tm_mask, "mitigation_id"] = mitigation_id

    return save_table(Tables.ASSET_TRACEABILITY_MATRIX, tm_df)


def can_delete_requirement(asset_id: int, requirement_id: int) -> tuple:
    """Check if a requirement can be deleted from an asset."""
    df = load_table(Tables.ASSET_TRACEABILITY_MATRIX)
    if df.empty:
        return (True, "")

    mask = (df["asset_id"] == asset_id) & (df["requirement_id"] == requirement_id)
    if not mask.any():
        return (True, "")

    req = get_row_by_id(Tables.REQUIREMENT, requirement_id)
    if req and excel_to_bool(req.get("is_standard", False)):
        return (False, "Standard requirements cannot be deleted")

    return (True, "")


# ─────────────────────────────────────────────────────
# Auto-assign standard requirements
# ─────────────────────────────────────────────────────

def auto_assign_standard_requirements(asset_id: int, equipment_type_id: int) -> int:
    """Auto-assign standard requirements for an equipment type. Returns count assigned."""
    # Get which requirements apply to this equipment type
    eq_req = load_table(Tables.EQUIPMENT_TYPE_REQUIREMENT)
    if eq_req.empty:
        return 0

    applicable_req_ids = eq_req[eq_req["equipment_type_id"] == equipment_type_id]["requirement_id"].tolist()
    if not applicable_req_ids:
        return 0

    # Get already assigned requirement IDs
    existing = get_asset_traceability_entries(asset_id)
    assigned_req_ids = set()
    if not existing.empty:
        assigned_req_ids = set(existing["requirement_id"].tolist())

    requirements = load_table(Tables.REQUIREMENT)
    if requirements.empty:
        return 0

    count = 0
    for req_id in applicable_req_ids:
        if req_id in assigned_req_ids:
            continue

        req_row = requirements[requirements["id"] == req_id]
        if req_row.empty:
            continue

        if not excel_to_bool(req_row.iloc[0].get("is_standard", False)):
            continue

        # Get default risks for this requirement
        default_risks = get_default_risks_for_requirement(req_id)

        if not default_risks:
            # No default risk - add with no risk
            if add_requirement_to_asset(
                asset_id=asset_id,
                requirement_id=req_id,
                requirement_is_auto_assign=True,
            ):
                count += 1
        else:
            for risk in default_risks:
                rid = risk.get("risk_id")
                # Get default DQ/XQ for this risk
                dq_defaults = get_default_dq_for_risk(rid)
                xq_defaults = get_default_xq_for_risk(rid)
                dq_id = dq_defaults[0]["dq_id"] if dq_defaults else None
                xq_id = xq_defaults[0]["xq_id"] if xq_defaults else None

                if add_requirement_to_asset(
                    asset_id=asset_id,
                    requirement_id=req_id,
                    risk_id=rid,
                    requirement_is_auto_assign=True,
                    risk_is_auto_assign=True,
                    dq_id=dq_id,
                    dq_is_auto_assign=bool(dq_id),
                    xq_id=xq_id,
                    xq_is_auto_assign=bool(xq_id),
                ):
                    count += 1

    return count


# ─────────────────────────────────────────────────────
# Equipment type functions
# ─────────────────────────────────────────────────────

def get_equipment_types(asset_type_id: Optional[int] = None) -> pd.DataFrame:
    """Get equipment types, optionally filtered by asset_type_id."""
    df = load_table(Tables.EQUIPMENT_TYPE)
    if df.empty:
        return df
    if asset_type_id is not None:
        return df[df["asset_type_id"] == asset_type_id]
    return df


def get_business_process_steps() -> pd.DataFrame:
    """Get business process steps lookup table."""
    df = load_table(Tables.BUSINESS_PROCESS_STEP)
    if df.empty:
        return df
    if "id" in df.columns:
        df = df.sort_values("id")
    return df


def get_equipment_type_by_id(equipment_type_id: int) -> Optional[Dict[str, Any]]:
    """Get equipment type by ID."""
    return get_row_by_id(Tables.EQUIPMENT_TYPE, equipment_type_id)


# ─────────────────────────────────────────────────────
# Requirement catalog functions
# ─────────────────────────────────────────────────────

def get_requirements_by_subchapter(subchapter: str) -> pd.DataFrame:
    """Get requirement catalog entries by subchapter name."""
    subchapters = load_table(Tables.SUBCHAPTER)
    if subchapters.empty:
        return pd.DataFrame()
    sc_row = subchapters[subchapters["name"] == subchapter]
    if sc_row.empty:
        return pd.DataFrame()
    sc_id = int(sc_row.iloc[0]["id"])

    df = load_table(Tables.REQUIREMENT)
    if df.empty:
        return df
    return df[df["subchapter_id"] == sc_id]


def create_custom_requirement(
    description: str,
    subchapter_id: int,
    is_must: bool = False,
    is_gxp: bool = False,
    remark_enabled: bool = True,
    remark_required: bool = False,
) -> int:
    """Create a custom (non-standard) requirement in the catalog."""
    row = {
        "description": description,
        "purpose": "",
        "is_standard": False,
        "is_gxp": is_gxp,
        "is_must": is_must,
        "remark_enabled": remark_enabled,
        "remark_required": remark_required,
        "subchapter_id": subchapter_id,
    }
    return insert_row(Tables.REQUIREMENT, row)


def search_requirement_catalog(search_term: str) -> pd.DataFrame:
    """Search requirement catalog by description text."""
    df = load_table(Tables.REQUIREMENT)
    if df.empty or not search_term:
        return df
    mask = df["description"].str.contains(search_term, case=False, na=False)
    return df[mask]


# ─────────────────────────────────────────────────────
# Document versioning
# ─────────────────────────────────────────────────────

def _get_project_id_for_asset(asset_id: int) -> Optional[int]:
    """Get project_id for an asset, resolving peripheral -> main if needed."""
    main_id = get_main_asset_id_for(asset_id)
    asset = get_row_by_id(Tables.ASSET, main_id)
    if not asset:
        return None
    return _int_or_none(asset.get("project_id"))


def _get_document_type_id(doc_type_str: str) -> Optional[int]:
    """Get document_type_id from string name."""
    dt = load_table(Tables.DOCUMENT_TYPE)
    if dt.empty:
        return None
    match = dt[dt["name"] == doc_type_str]
    if match.empty:
        return None
    return int(match.iloc[0]["id"])


def record_document_export(asset_id: int, document_type: Any) -> bool:
    """Record a document export by creating a document_version record."""
    doc_type_str = _normalize_document_type(document_type)
    if not doc_type_str:
        return False

    project_id = _get_project_id_for_asset(asset_id)
    if project_id is None:
        return False

    doc_type_id = _get_document_type_id(doc_type_str)
    if doc_type_id is None:
        return False

    # Find or create document record
    docs = load_table(Tables.DOCUMENT)
    doc_id = None
    if not docs.empty:
        match = docs[(docs["project_id"] == project_id) & (docs["document_type_id"] == doc_type_id) & (docs["is_active"] == True)]
        if not match.empty:
            doc_id = int(match.iloc[0]["id"])

    if doc_id is None:
        doc_row = {
            "project_id": project_id,
            "document_type_id": doc_type_id,
            "status": "Draft",
            "is_active": True,
            "created_at": now_iso(),
            "created_by": "",
        }
        doc_id = insert_row(Tables.DOCUMENT, doc_row)

    # Find latest version number
    versions = load_table(Tables.DOCUMENT_VERSION)
    latest_version = 0
    now = now_iso()
    if not versions.empty:
        doc_versions = versions[versions["document_id"] == doc_id]
        if not doc_versions.empty:
            latest_version = int(doc_versions["version_no"].max())

            # Mark the previous version as "rejected" — it is being superseded
            # by the new version being created now.
            latest_mask = (versions["document_id"] == doc_id) & (versions["version_no"] == latest_version)
            if "rejected_at" not in versions.columns:
                versions["rejected_at"] = ""
            versions.loc[latest_mask, "rejected_at"] = now
            save_table(Tables.DOCUMENT_VERSION, versions)

            # Reset document status back to Draft for the new version
            docs.loc[docs["id"] == doc_id, "status"] = "Draft"
            save_table(Tables.DOCUMENT, docs)

    next_version = latest_version + 1
    version_row = {
        "document_id": doc_id,
        "version_no": next_version,
        "file_path": "",
        "created_at": now,
        "created_by": "",
        "change_note": "",
    }
    insert_row(Tables.DOCUMENT_VERSION, version_row)
    return True


def record_document_approval(asset_id: int, document_type: Any) -> bool:
    """Approve the latest document version."""
    doc_type_str = _normalize_document_type(document_type)
    if not doc_type_str:
        return False

    project_id = _get_project_id_for_asset(asset_id)
    if project_id is None:
        return False

    doc_type_id = _get_document_type_id(doc_type_str)
    if doc_type_id is None:
        return False

    docs = load_table(Tables.DOCUMENT)
    if docs.empty:
        return False

    match = docs[(docs["project_id"] == project_id) & (docs["document_type_id"] == doc_type_id) & (docs["is_active"] == True)]
    if match.empty:
        return False

    doc_id = int(match.iloc[0]["id"])
    now = now_iso()

    # Update document status and approval timestamp
    docs.loc[docs["id"] == doc_id, "status"] = "Approved"
    docs.loc[docs["id"] == doc_id, "approved_at"] = now
    save_table(Tables.DOCUMENT, docs)

    # Also set approved_at on the latest version record (only if not rejected)
    versions = load_table(Tables.DOCUMENT_VERSION)
    if not versions.empty:
        doc_versions = versions[versions["document_id"] == doc_id]
        if not doc_versions.empty:
            latest_v = int(doc_versions["version_no"].max())
            latest_mask = (versions["document_id"] == doc_id) & (versions["version_no"] == latest_v)
            # Only approve if not already rejected
            if "rejected_at" not in versions.columns:
                versions["rejected_at"] = ""
            if "approved_at" not in versions.columns:
                versions["approved_at"] = ""
            rejected_val = _normalize_str(versions.loc[latest_mask, "rejected_at"].iloc[0]) if latest_mask.any() else ""
            if not rejected_val:
                versions.loc[latest_mask, "approved_at"] = now
                save_table(Tables.DOCUMENT_VERSION, versions)

    return True


def get_document_version_snapshot(asset_id: int, document_type: Any) -> Dict[str, str]:
    """Return document version info for PDF title page."""
    doc_type_str = _normalize_document_type(document_type)
    now = now_iso()

    project_id = _get_project_id_for_asset(asset_id)
    if project_id is None:
        return {"document_version": _format_version(1), "document_creation_timestamp": now, "document_approval_timestamp": ""}

    doc_type_id = _get_document_type_id(doc_type_str) if doc_type_str else None

    if doc_type_id is not None:
        docs = load_table(Tables.DOCUMENT)
        if not docs.empty:
            match = docs[(docs["project_id"] == project_id) & (docs["document_type_id"] == doc_type_id) & (docs["is_active"] == True)]
            if not match.empty:
                doc_id = int(match.iloc[0]["id"])
                versions = load_table(Tables.DOCUMENT_VERSION)
                if not versions.empty:
                    doc_versions = versions[versions["document_id"] == doc_id]
                    if not doc_versions.empty:
                        latest_v = int(doc_versions["version_no"].max())
                        latest = doc_versions[doc_versions["version_no"] == latest_v].iloc[0]
                        doc_status = _normalize_str(match.iloc[0].get("status"))
                        created = _normalize_str(latest.get("created_at"))

                        if doc_status != "Approved":
                            return {
                                "document_version": _format_version(latest_v),
                                "document_creation_timestamp": created or now,
                                "document_approval_timestamp": "",
                            }
                        else:
                            return {
                                "document_version": _format_version(latest_v + 1),
                                "document_creation_timestamp": now,
                                "document_approval_timestamp": "",
                            }

    return {"document_version": _format_version(1), "document_creation_timestamp": now, "document_approval_timestamp": ""}


def get_latest_document_version_info(asset_id: int, document_type: Any) -> Optional[Dict[str, str]]:
    """Return the latest stored document version info."""
    doc_type_str = _normalize_document_type(document_type)
    if not doc_type_str:
        return None

    project_id = _get_project_id_for_asset(asset_id)
    if project_id is None:
        return None

    doc_type_id = _get_document_type_id(doc_type_str)
    if doc_type_id is None:
        return None

    docs = load_table(Tables.DOCUMENT)
    if docs.empty:
        return None

    match = docs[(docs["project_id"] == project_id) & (docs["document_type_id"] == doc_type_id)]
    if match.empty:
        return None

    doc_id = int(match.iloc[0]["id"])
    doc_status = _normalize_str(match.iloc[0].get("status"))

    versions = load_table(Tables.DOCUMENT_VERSION)
    if versions.empty:
        return None

    doc_versions = versions[versions["document_id"] == doc_id]
    if doc_versions.empty:
        return None

    latest_v = int(doc_versions["version_no"].max())
    latest = doc_versions[doc_versions["version_no"] == latest_v].iloc[0]

    # Read approved_at from the version record (per-version tracking)
    version_approved = _normalize_str(latest.get("approved_at")) if "approved_at" in doc_versions.columns else ""
    return {
        "document_version": _format_version(latest_v),
        "document_creation_timestamp": _normalize_str(latest.get("created_at")),
        "document_approval_timestamp": version_approved,
    }


# ─────────────────────────────────────────────────────
# Asset overview and PDF context
# ─────────────────────────────────────────────────────

def get_asset_overview_rows(asset_id: int) -> List[Dict[str, str]]:
    """Build rows for the asset overview table."""
    asset = get_row_by_id(Tables.ASSET, asset_id)
    if not asset:
        return []

    main_id = get_main_asset_id_for(asset_id)
    main_asset = get_row_by_id(Tables.ASSET, main_id) or asset
    peripherals = get_peripherals(main_id)
    equipment_types = load_table(Tables.EQUIPMENT_TYPE)

    def resolve_eq_type(a: Dict[str, Any]) -> str:
        eq_id = _int_or_none(a.get("equipment_type_id"))
        if eq_id is not None and not equipment_types.empty:
            match = equipment_types[equipment_types["id"] == eq_id]
            if not match.empty:
                return _normalize_str(match.iloc[0].get("name"))
        return ""

    asset_type_str = "main" if is_main_asset(main_id) else "peripheral"
    rows = [{
        "asset_id": int(main_id),
        "equipment_type": resolve_eq_type(main_asset),
        "asset_type": asset_type_str,
        "name": _normalize_str(main_asset.get("name")),
    }]

    if not peripherals.empty:
        for _, row in peripherals.iterrows():
            rows.append({
                "asset_id": int(row["id"]),
                "equipment_type": resolve_eq_type(row.to_dict()),
                "asset_type": "peripheral",
                "name": _normalize_str(row.get("name")),
            })

    return rows


def get_pdf_base_context(asset_id: int) -> Dict[str, Any]:
    """Build base PDF context shared by all document types."""
    asset = get_row_by_id(Tables.ASSET, asset_id)
    if not asset:
        return {}

    main_id = get_main_asset_id_for(asset_id)
    main_asset = get_row_by_id(Tables.ASSET, main_id) or asset
    project_id = _int_or_none(main_asset.get("project_id"))

    # Get project info
    project = get_row_by_id(Tables.PROJECT, project_id) if project_id else None
    project_name = _normalize_str(project.get("name")) if project else ""

    # Get BPS name
    bps_name = ""
    main_row = load_table(Tables.MAIN_ASSET)
    if not main_row.empty:
        m = main_row[main_row["asset_id"] == main_id]
        if not m.empty:
            bps_id = _int_or_none(m.iloc[0].get("business_process_step_id"))
            if bps_id:
                bps = get_row_by_id(Tables.BUSINESS_PROCESS_STEP, bps_id)
                if bps:
                    bps_name = _normalize_str(bps.get("name"))

    # Get system owner
    system_owner_role = ""
    system_owner_person = ""
    if bps_id:
        bps_so = load_table(Tables.BUSINESS_PROCESS_STEP_SYSTEM_OWNER)
        if not bps_so.empty:
            so_match = bps_so[bps_so["business_process_step_id"] == bps_id]
            if not so_match.empty:
                so_id = _int_or_none(so_match.iloc[0].get("system_owner_id"))
                if so_id:
                    so = get_row_by_id(Tables.SYSTEM_OWNER, so_id)
                    if so:
                        system_owner_role = _normalize_str(so.get("role"))
                        system_owner_person = _normalize_str(so.get("name"))

    location_display = get_location_display(project_id) if project_id else ""

    return {
        "asset_id": int(main_id),
        "asset_name": _normalize_str(main_asset.get("name")),
        "name": _normalize_str(main_asset.get("name")),
        "business_process_step": bps_name,
        "system_owner_role": system_owner_role,
        "system_owner_name": system_owner_person,
        "project_name": project_name,
        "project_title": project_name,
        "asset_overview_rows": get_asset_overview_rows(main_id),
        "location": {"display": location_display},
    }


# ─────────────────────────────────────────────────────
# Equipment Media and Asset Media
# ─────────────────────────────────────────────────────

def get_equipment_media(equipment_type_id: int) -> pd.DataFrame:
    """Get default media assignments for an equipment type."""
    df = load_table(Tables.EQUIPMENT_TYPE_MEDIA)
    if df.empty:
        return df
    return df[df["equipment_type_id"] == equipment_type_id]


def get_asset_media(asset_id: int) -> pd.DataFrame:
    """Get all media assignments for an asset."""
    df = load_table(Tables.ASSET_MEDIA)
    if df.empty:
        return df
    return df[df["asset_id"] == asset_id]


def get_all_media() -> pd.DataFrame:
    """Get all media types."""
    return load_table(Tables.MEDIA)


def set_asset_media(
    asset_id: int,
    media_id: int,
    media_value: str
) -> bool:
    """Add or update a media assignment for an asset."""
    df = load_table(Tables.ASSET_MEDIA)

    new_data = {
        "asset_id": asset_id,
        "media_id": media_id,
        "media_value": media_value,
    }

    if not df.empty and "asset_id" in df.columns and "media_id" in df.columns:
        mask = (df["asset_id"] == asset_id) & (df["media_id"] == media_id)
        if mask.any():
            for col, val in new_data.items():
                df.loc[mask, col] = val
            return save_table(Tables.ASSET_MEDIA, df)

    df = pd.concat([df, pd.DataFrame([new_data])], ignore_index=True)
    return save_table(Tables.ASSET_MEDIA, df)


def delete_asset_media(asset_id: int, media_id: int) -> bool:
    """Delete a media assignment for an asset."""
    df = load_table(Tables.ASSET_MEDIA)
    if df.empty:
        return True
    mask = (df["asset_id"] == asset_id) & (df["media_id"] == media_id)
    if not mask.any():
        return True
    df = df[~mask]
    return save_table(Tables.ASSET_MEDIA, df)


def auto_assign_media_for_asset(asset_id: int, equipment_type_id: int) -> int:
    """Auto-assign default media for an asset based on equipment type. Returns count."""
    eq_media = get_equipment_media(equipment_type_id)
    if eq_media.empty:
        return 0

    count = 0
    for _, row in eq_media.iterrows():
        if set_asset_media(
            asset_id=asset_id,
            media_id=int(row["media_id"]),
            media_value=_normalize_str(row["default_value"]),
        ):
            count += 1
    return count


# ─────────────────────────────────────────────────────
# Equipment type requirement management
# ─────────────────────────────────────────────────────

def get_equipment_type_requirements(equipment_type_id: int) -> List[int]:
    """Get requirement IDs assigned to an equipment type."""
    df = load_table(Tables.EQUIPMENT_TYPE_REQUIREMENT)
    if df.empty:
        return []
    matches = df[df["equipment_type_id"] == equipment_type_id]
    return matches["requirement_id"].tolist()


def update_equipment_type_requirements(requirement_id: int, equipment_type_ids: List[int]) -> bool:
    """Update which equipment types a requirement applies to."""
    df = load_table(Tables.EQUIPMENT_TYPE_REQUIREMENT)

    # Remove existing entries for this requirement
    if not df.empty:
        df = df[df["requirement_id"] != requirement_id]

    # Add new entries
    new_rows = [{"equipment_type_id": eid, "requirement_id": requirement_id} for eid in equipment_type_ids]
    if new_rows:
        df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)

    return save_table(Tables.EQUIPMENT_TYPE_REQUIREMENT, df)


# ─────────────────────────────────────────────────────
# Qualification approval
# ─────────────────────────────────────────────────────

def stamp_initial_qualification_approved(asset_ids: List[int]) -> bool:
    """Mark initial qualification as approved by creating project_phase entry for DONE."""
    if not asset_ids:
        return False
    return set_asset_phase(asset_ids, Phase.DONE)
