"""
Initialize Excel data files with schemas and sample data.
Run this script once to set up the data directory.
All text is in English.
"""
import pandas as pd
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def save_excel(name: str, df: pd.DataFrame):
    """Save DataFrame to Excel file."""
    path = DATA_DIR / f"{name}.xlsx"
    df.to_excel(path, index=False, engine="openpyxl")
    print(f"Created: {path}")


# ──────────────────────────────────────────────
# 1a. Core reference tables (no FKs)
# ──────────────────────────────────────────────

def init_country():
    data = [
        {"id": 1, "name": "Switzerland", "iso_code": "CH"},
        {"id": 2, "name": "United States", "iso_code": "US"},
    ]
    save_excel("country", pd.DataFrame(data))


def init_coordinate():
    """Supertype table for coordinates (Y=letters, X=numbers)."""
    data = [{"id": i} for i in range(1, 26)]  # 8 Y + 17 X = 25
    save_excel("coordinate", pd.DataFrame(data))


def init_coordinate_y():
    """Subtype: Y-axis coordinates (letters A-H)."""
    letters = list("ABCDEFGH")
    data = [{"coordinate_id": i + 1, "code": c} for i, c in enumerate(letters)]
    save_excel("coordinate_y", pd.DataFrame(data))


def init_coordinate_x():
    """Subtype: X-axis coordinates (numbers 01-17)."""
    data = [{"coordinate_id": 9 + i, "code": f"{i + 1:02d}"} for i in range(17)]
    save_excel("coordinate_x", pd.DataFrame(data))


def init_asset_type():
    data = [
        {"id": 1, "name": "main"},
        {"id": 2, "name": "peripheral"},
    ]
    save_excel("asset_type", pd.DataFrame(data))


def init_subchapter():
    data = [
        {"id": 1, "name": "safety_control"},
        {"id": 2, "name": "components"},
        {"id": 3, "name": "utilities_media"},
        {"id": 4, "name": "environment"},
        {"id": 5, "name": "software"},
        {"id": 6, "name": "documentation"},
        {"id": 7, "name": "training"},
        {"id": 8, "name": "maintenance"},
        {"id": 9, "name": "delivery_acceptance"},
    ]
    save_excel("subchapter", pd.DataFrame(data))


def init_document_type():
    data = [
        {"id": 1, "name": "URS"},
        {"id": 2, "name": "RISK"},
        {"id": 3, "name": "DQ"},
        {"id": 4, "name": "XQ_PLAN"},
        {"id": 5, "name": "XQ_EXECUTION"},
    ]
    save_excel("document_type", pd.DataFrame(data))


def init_mitigation_category():
    data = [
        {"id": 1, "name": "DQ"},
        {"id": 2, "name": "XQ"},
    ]
    save_excel("mitigation_category", pd.DataFrame(data))


def init_media():
    data = [
        {"id": 1, "name": "Electricity"},
        {"id": 2, "name": "Compressed Air"},
        {"id": 3, "name": "Purified Water"},
        {"id": 4, "name": "Cooling Water"},
        {"id": 5, "name": "Ethernet"},
    ]
    save_excel("media", pd.DataFrame(data))


def init_business_process_step():
    data = [
        {"id": 1, "name": "D - Long Turning"},
        {"id": 2, "name": "F1 - Anatomical Manufacturing"},
        {"id": 3, "name": "F2 - Flat Manufacturing"},
        {"id": 4, "name": "F3 - Curved Manufacturing"},
        {"id": 5, "name": "L - Laser Marking"},
        {"id": 6, "name": "P - Packaging & Labeling"},
    ]
    save_excel("business_process_step", pd.DataFrame(data))


# ──────────────────────────────────────────────
# 1b. Tables with single FK dependency
# ──────────────────────────────────────────────

def init_site():
    data = [
        {"id": 1, "name": "HQ Basel", "iso_code": "BS", "address": "Hochbergerstrasse 60E", "postal_code": "4057", "city": "Basel", "country_id": 1},
        {"id": 2, "name": "Warsaw", "iso_code": "WA", "address": "1195 Polk Drive", "postal_code": "46582", "city": "Warsaw IN", "country_id": 2},
    ]
    save_excel("site", pd.DataFrame(data))


def init_system_owner():
    data = [
        {"id": 1, "name": "John Smith", "role": "Production Manager"},
        {"id": 2, "name": "Jane Doe", "role": "Quality Manager"},
    ]
    save_excel("system_owner", pd.DataFrame(data))


def init_equipment_type():
    data = [
        {"id": 1, "name": "Bioreactor", "asset_type_id": 1},
        {"id": 2, "name": "Chromatography System", "asset_type_id": 1},
        {"id": 3, "name": "Filtration System", "asset_type_id": 1},
        {"id": 4, "name": "Mixing Vessel", "asset_type_id": 1},
        {"id": 5, "name": "Pump", "asset_type_id": 2},
        {"id": 6, "name": "Valve", "asset_type_id": 2},
        {"id": 7, "name": "Sensor", "asset_type_id": 2},
        {"id": 8, "name": "Control Unit", "asset_type_id": 2},
    ]
    save_excel("equipment_type", pd.DataFrame(data))


def init_requirement():
    data = [
        # Safety & Control (subchapter_id=1)
        {"id": 1, "description": "The system must have an emergency stop switch that immediately stops all movements", "purpose": "", "is_standard": True, "is_gxp": True, "is_must": True, "remark_enabled": True, "remark_required": False, "subchapter_id": 1},
        {"id": 2, "description": "Safety interlocks must prevent access to moving parts during operation", "purpose": "", "is_standard": True, "is_gxp": True, "is_must": True, "remark_enabled": True, "remark_required": False, "subchapter_id": 1},
        {"id": 3, "description": "The system should provide access control with at least 3 permission levels", "purpose": "", "is_standard": True, "is_gxp": True, "is_must": False, "remark_enabled": True, "remark_required": False, "subchapter_id": 1},
        # Components (subchapter_id=2)
        {"id": 4, "description": "All product-contact parts must be made of stainless steel 316L", "purpose": "", "is_standard": True, "is_gxp": True, "is_must": True, "remark_enabled": True, "remark_required": False, "subchapter_id": 2},
        {"id": 5, "description": "Seals must be FDA-compliant and suitable for CIP/SIP", "purpose": "", "is_standard": True, "is_gxp": True, "is_must": True, "remark_enabled": True, "remark_required": False, "subchapter_id": 2},
        {"id": 6, "description": "The system should be modularly expandable", "purpose": "", "is_standard": False, "is_gxp": False, "is_must": False, "remark_enabled": True, "remark_required": True, "subchapter_id": 2},
        # Utilities & Media (subchapter_id=3)
        {"id": 7, "description": "The system must be connectable to compressed air 6-8 bar", "purpose": "", "is_standard": True, "is_gxp": False, "is_must": True, "remark_enabled": True, "remark_required": False, "subchapter_id": 3},
        {"id": 8, "description": "Electrical supply: 400V/50Hz three-phase", "purpose": "", "is_standard": True, "is_gxp": False, "is_must": True, "remark_enabled": True, "remark_required": False, "subchapter_id": 3},
        {"id": 9, "description": "The system should be secured by UPS", "purpose": "", "is_standard": False, "is_gxp": False, "is_must": False, "remark_enabled": True, "remark_required": False, "subchapter_id": 3},
        {"id": 10, "description": "Purified water connection according to Ph. Eur. requirements", "purpose": "", "is_standard": True, "is_gxp": True, "is_must": True, "remark_enabled": True, "remark_required": False, "subchapter_id": 3},
        # Environment (subchapter_id=4)
        {"id": 11, "description": "The system must be suitable for cleanroom class ISO 7", "purpose": "", "is_standard": True, "is_gxp": True, "is_must": True, "remark_enabled": True, "remark_required": False, "subchapter_id": 4},
        {"id": 12, "description": "Operating temperature: 15-25 C", "purpose": "", "is_standard": True, "is_gxp": False, "is_must": True, "remark_enabled": True, "remark_required": False, "subchapter_id": 4},
        {"id": 13, "description": "Relative humidity: 30-65%", "purpose": "", "is_standard": True, "is_gxp": False, "is_must": False, "remark_enabled": True, "remark_required": False, "subchapter_id": 4},
        # Software (subchapter_id=5)
        {"id": 14, "description": "The software must be 21 CFR Part 11 compliant", "purpose": "", "is_standard": True, "is_gxp": True, "is_must": True, "remark_enabled": True, "remark_required": False, "subchapter_id": 5},
        {"id": 15, "description": "Audit trail for all GxP-relevant changes", "purpose": "", "is_standard": True, "is_gxp": True, "is_must": True, "remark_enabled": True, "remark_required": False, "subchapter_id": 5},
        {"id": 16, "description": "Electronic signatures with username and password", "purpose": "", "is_standard": True, "is_gxp": True, "is_must": True, "remark_enabled": True, "remark_required": False, "subchapter_id": 5},
        {"id": 17, "description": "Recipe management with versioning", "purpose": "", "is_standard": True, "is_gxp": True, "is_must": False, "remark_enabled": True, "remark_required": False, "subchapter_id": 5},
        {"id": 18, "description": "OPC-UA interface for MES integration", "purpose": "", "is_standard": False, "is_gxp": False, "is_must": False, "remark_enabled": True, "remark_required": True, "subchapter_id": 5},
        # Documentation (subchapter_id=6)
        {"id": 19, "description": "Complete technical documentation in English", "purpose": "", "is_standard": True, "is_gxp": False, "is_must": True, "remark_enabled": True, "remark_required": False, "subchapter_id": 6},
        {"id": 20, "description": "CE Declaration of Conformity", "purpose": "", "is_standard": True, "is_gxp": False, "is_must": True, "remark_enabled": True, "remark_required": False, "subchapter_id": 6},
        {"id": 21, "description": "P&ID and electrical schematics", "purpose": "", "is_standard": True, "is_gxp": False, "is_must": True, "remark_enabled": True, "remark_required": False, "subchapter_id": 6},
        # Training (subchapter_id=7)
        {"id": 22, "description": "On-site operator training (min. 2 days)", "purpose": "", "is_standard": True, "is_gxp": False, "is_must": True, "remark_enabled": True, "remark_required": False, "subchapter_id": 7},
        {"id": 23, "description": "Maintenance training for technicians", "purpose": "", "is_standard": True, "is_gxp": False, "is_must": False, "remark_enabled": True, "remark_required": False, "subchapter_id": 7},
        {"id": 24, "description": "Training materials in English", "purpose": "", "is_standard": True, "is_gxp": False, "is_must": True, "remark_enabled": True, "remark_required": False, "subchapter_id": 7},
        # Maintenance (subchapter_id=8)
        {"id": 25, "description": "Maintenance intervals max. 6 months", "purpose": "", "is_standard": True, "is_gxp": False, "is_must": False, "remark_enabled": True, "remark_required": False, "subchapter_id": 8},
        {"id": 26, "description": "Spare parts availability min. 10 years", "purpose": "", "is_standard": True, "is_gxp": False, "is_must": True, "remark_enabled": True, "remark_required": False, "subchapter_id": 8},
        {"id": 27, "description": "Remote support capability", "purpose": "", "is_standard": False, "is_gxp": False, "is_must": False, "remark_enabled": True, "remark_required": True, "subchapter_id": 8},
        # Delivery & Acceptance (subchapter_id=9)
        {"id": 28, "description": "FAT at supplier before delivery", "purpose": "", "is_standard": True, "is_gxp": False, "is_must": True, "remark_enabled": True, "remark_required": False, "subchapter_id": 9},
        {"id": 29, "description": "SAT at installation site", "purpose": "", "is_standard": True, "is_gxp": False, "is_must": True, "remark_enabled": True, "remark_required": False, "subchapter_id": 9},
        {"id": 30, "description": "Delivery time max. 16 weeks after order", "purpose": "", "is_standard": False, "is_gxp": False, "is_must": False, "remark_enabled": True, "remark_required": True, "subchapter_id": 9},
    ]
    save_excel("requirement", pd.DataFrame(data))


def init_risk():
    data = [
        {"id": 1, "possible_error": "Overtemperature", "harm": "Product damage", "cause": "Heating failure", "severity_before_mitigation": 3, "likelihood_before_mitigation": 2, "detectability_before_mitigation": 1},
        {"id": 2, "possible_error": "Contamination", "harm": "Patient endangerment", "cause": "Leaking vessel", "severity_before_mitigation": 3, "likelihood_before_mitigation": 2, "detectability_before_mitigation": 2},
        {"id": 3, "possible_error": "Dosing error", "harm": "Incorrect dosage", "cause": "Sensor failure", "severity_before_mitigation": 3, "likelihood_before_mitigation": 2, "detectability_before_mitigation": 1},
        {"id": 4, "possible_error": "Power failure", "harm": "Production stop", "cause": "Grid failure", "severity_before_mitigation": 2, "likelihood_before_mitigation": 1, "detectability_before_mitigation": 1},
        {"id": 5, "possible_error": "Data integrity", "harm": "Compliance violation", "cause": "Software error", "severity_before_mitigation": 3, "likelihood_before_mitigation": 1, "detectability_before_mitigation": 2},
        {"id": 6, "possible_error": "Unauthorized access", "harm": "Manipulation", "cause": "Missing access control", "severity_before_mitigation": 3, "likelihood_before_mitigation": 2, "detectability_before_mitigation": 2},
        {"id": 7, "possible_error": "Mechanical defect", "harm": "Injury", "cause": "Wear", "severity_before_mitigation": 3, "likelihood_before_mitigation": 2, "detectability_before_mitigation": 1},
        {"id": 8, "possible_error": "Cross-contamination", "harm": "Product contamination", "cause": "Insufficient cleaning", "severity_before_mitigation": 3, "likelihood_before_mitigation": 2, "detectability_before_mitigation": 2},
        {"id": 9, "possible_error": "Overpressure", "harm": "Vessel rupture", "cause": "Valve failure", "severity_before_mitigation": 3, "likelihood_before_mitigation": 1, "detectability_before_mitigation": 1},
        {"id": 10, "possible_error": "Communication error", "harm": "Data loss", "cause": "Network failure", "severity_before_mitigation": 2, "likelihood_before_mitigation": 2, "detectability_before_mitigation": 1},
        {"id": 11, "possible_error": "False alarm", "harm": "Production loss", "cause": "Sensor drift", "severity_before_mitigation": 2, "likelihood_before_mitigation": 2, "detectability_before_mitigation": 2},
        {"id": 12, "possible_error": "Wrong recipe selection", "harm": "Product defect", "cause": "Operator error", "severity_before_mitigation": 3, "likelihood_before_mitigation": 2, "detectability_before_mitigation": 1},
    ]
    save_excel("risk", pd.DataFrame(data))


def init_dq():
    data = [
        {"id": 1, "description": "System starts within 60 seconds after power on", "severity_after_mitigation": 2, "likelihood_after_mitigation": 1, "detectability_after_mitigation": 1},
        {"id": 2, "description": "Emergency stop function stops all movements within 500ms", "severity_after_mitigation": 3, "likelihood_after_mitigation": 1, "detectability_after_mitigation": 1},
        {"id": 3, "description": "Temperature control maintains setpoint +/-0.5 C", "severity_after_mitigation": 2, "likelihood_after_mitigation": 1, "detectability_after_mitigation": 1},
        {"id": 4, "description": "Pressure control maintains setpoint +/-0.1 bar", "severity_after_mitigation": 2, "likelihood_after_mitigation": 1, "detectability_after_mitigation": 1},
        {"id": 5, "description": "Fill level is measured with accuracy +/-1%", "severity_after_mitigation": 2, "likelihood_after_mitigation": 1, "detectability_after_mitigation": 1},
        {"id": 6, "description": "Alarm is triggered within 1s when limit value is exceeded", "severity_after_mitigation": 2, "likelihood_after_mitigation": 1, "detectability_after_mitigation": 1},
        {"id": 7, "description": "Audit trail records all changes with timestamp", "severity_after_mitigation": 3, "likelihood_after_mitigation": 1, "detectability_after_mitigation": 1},
        {"id": 8, "description": "User management supports 3 permission levels", "severity_after_mitigation": 3, "likelihood_after_mitigation": 1, "detectability_after_mitigation": 1},
        {"id": 9, "description": "Recipe management stores up to 100 recipes", "severity_after_mitigation": 2, "likelihood_after_mitigation": 1, "detectability_after_mitigation": 1},
        {"id": 10, "description": "Data export in CSV format", "severity_after_mitigation": 2, "likelihood_after_mitigation": 1, "detectability_after_mitigation": 1},
        {"id": 11, "description": "CIP cleaning program runs fully automatically", "severity_after_mitigation": 3, "likelihood_after_mitigation": 1, "detectability_after_mitigation": 1},
        {"id": 12, "description": "SIP sterilization program reaches 121 C for 20 min", "severity_after_mitigation": 3, "likelihood_after_mitigation": 1, "detectability_after_mitigation": 1},
        {"id": 13, "description": "Communication via OPC-UA interface", "severity_after_mitigation": 2, "likelihood_after_mitigation": 1, "detectability_after_mitigation": 1},
        {"id": 14, "description": "Visualization shows current process status", "severity_after_mitigation": 2, "likelihood_after_mitigation": 1, "detectability_after_mitigation": 1},
        {"id": 15, "description": "Historical data is archived for 10 years", "severity_after_mitigation": 2, "likelihood_after_mitigation": 1, "detectability_after_mitigation": 1},
    ]
    save_excel("dq", pd.DataFrame(data))


def init_xq():
    data = [
        {"id": 1, "description": "Temperature alarm test", "purpose": "Verify alarm function for overtemperature", "severity_after_mitigation": 2, "likelihood_after_mitigation": 1, "detectability_after_mitigation": 1, "input": "Simulate temperature above limit", "expected_output": "Alarm active within 1s"},
        {"id": 2, "description": "Tightness test", "purpose": "Check vessel tightness", "severity_after_mitigation": 3, "likelihood_after_mitigation": 1, "detectability_after_mitigation": 1, "input": "Pressurize to 1.5 bar", "expected_output": "No pressure drop after 30 min"},
        {"id": 3, "description": "Calibration test", "purpose": "Verify sensor accuracy", "severity_after_mitigation": 2, "likelihood_after_mitigation": 1, "detectability_after_mitigation": 1, "input": "Reference measurement with calibrated instruments", "expected_output": "Deviation < +/-1%"},
        {"id": 4, "description": "UPS test", "purpose": "Check uninterruptible power supply", "severity_after_mitigation": 2, "likelihood_after_mitigation": 1, "detectability_after_mitigation": 1, "input": "Simulate grid disconnection", "expected_output": "System runs 30 min on UPS"},
        {"id": 5, "description": "Audit trail test", "purpose": "Verify audit trail function", "severity_after_mitigation": 3, "likelihood_after_mitigation": 1, "detectability_after_mitigation": 1, "input": "Perform parameter change", "expected_output": "Change logged with timestamp and user"},
        {"id": 6, "description": "Access control test", "purpose": "Check user management", "severity_after_mitigation": 3, "likelihood_after_mitigation": 1, "detectability_after_mitigation": 1, "input": "Login attempts with different roles", "expected_output": "Access according to permission level"},
        {"id": 7, "description": "Safety inspection", "purpose": "Check mechanical safety devices", "severity_after_mitigation": 3, "likelihood_after_mitigation": 1, "detectability_after_mitigation": 1, "input": "Visual inspection and function test", "expected_output": "All safety devices functional"},
        {"id": 8, "description": "CIP validation", "purpose": "Verify cleaning effectiveness", "severity_after_mitigation": 3, "likelihood_after_mitigation": 1, "detectability_after_mitigation": 1, "input": "Perform CIP cycle", "expected_output": "TOC < 10 ppm after cleaning"},
        {"id": 9, "description": "Pressure safety test", "purpose": "Check overpressure protection", "severity_after_mitigation": 3, "likelihood_after_mitigation": 1, "detectability_after_mitigation": 1, "input": "Build pressure until safety valve triggers", "expected_output": "Valve opens at set pressure +/-5%"},
        {"id": 10, "description": "Network redundancy test", "purpose": "Check network failover", "severity_after_mitigation": 2, "likelihood_after_mitigation": 1, "detectability_after_mitigation": 1, "input": "Disconnect primary connection", "expected_output": "Switchover to backup within 5s"},
        {"id": 11, "description": "Alarm test", "purpose": "Verify all alarm messages", "severity_after_mitigation": 2, "likelihood_after_mitigation": 1, "detectability_after_mitigation": 1, "input": "Simulate all alarm conditions", "expected_output": "Correct alarm message and logging"},
        {"id": 12, "description": "Recipe locking test", "purpose": "Check recipe change lock", "severity_after_mitigation": 2, "likelihood_after_mitigation": 1, "detectability_after_mitigation": 1, "input": "Attempt recipe change during batch", "expected_output": "Change is prevented"},
        {"id": 13, "description": "SIP validation", "purpose": "Verify sterilization", "severity_after_mitigation": 3, "likelihood_after_mitigation": 1, "detectability_after_mitigation": 1, "input": "SIP cycle with bioindicators", "expected_output": "All bioindicators negative"},
        {"id": 14, "description": "Document review", "purpose": "Completeness check of documentation", "severity_after_mitigation": 2, "likelihood_after_mitigation": 1, "detectability_after_mitigation": 1, "input": "Review all documents", "expected_output": "All required documents present"},
        {"id": 15, "description": "Performance test", "purpose": "Check production performance", "severity_after_mitigation": 2, "likelihood_after_mitigation": 1, "detectability_after_mitigation": 1, "input": "3 consecutive production runs", "expected_output": "All batches within specification"},
    ]
    save_excel("xq", pd.DataFrame(data))


# ──────────────────────────────────────────────
# 1c. Site coordinate values
# ──────────────────────────────────────────────

def init_site_coordinate_value():
    """Pixel-percentage mappings per site for coordinate grid overlay.
    Same values apply to all levels of a site."""
    data = []
    # Basel (site_id=1) - Y coordinates (coordinate_id 1-8 = A-H)
    y_pcts = [12.5, 25.0, 37.5, 50.0, 62.5, 75.0, 87.5, 100.0]
    for i, pct in enumerate(y_pcts):
        data.append({"site_id": 1, "coordinate_id": i + 1, "percentage_value": pct})
    # Basel (site_id=1) - X coordinates (coordinate_id 9-25 = 01-17)
    for i in range(17):
        pct = (i + 1) / 17.0 * 100.0
        data.append({"site_id": 1, "coordinate_id": 9 + i, "percentage_value": round(pct, 2)})
    # Warsaw (site_id=2) - same grid
    for i, pct in enumerate(y_pcts):
        data.append({"site_id": 2, "coordinate_id": i + 1, "percentage_value": pct})
    for i in range(17):
        pct = (i + 1) / 17.0 * 100.0
        data.append({"site_id": 2, "coordinate_id": 9 + i, "percentage_value": round(pct, 2)})
    save_excel("site_coordinate_value", pd.DataFrame(data))


# ──────────────────────────────────────────────
# 1d. Tables with deeper FK dependencies
# ──────────────────────────────────────────────

def init_level():
    data = [
        {"id": 1, "name": "Level 0", "name_short": "L0", "site_id": 1},
        {"id": 2, "name": "Level 1", "name_short": "L1", "site_id": 1},
        {"id": 3, "name": "Level 3", "name_short": "L3", "site_id": 1},
        {"id": 4, "name": "Level 4", "name_short": "L4", "site_id": 1},
        {"id": 5, "name": "Production Hall", "name_short": "PH", "site_id": 2},
    ]
    save_excel("level", pd.DataFrame(data))


def init_project():
    data = [
        {"id": 1, "name": "Bioreactor Installation Basel"},
    ]
    save_excel("project", pd.DataFrame(data))


def init_project_location():
    """Empty initially - populated when assets are created."""
    columns = ["id", "project_id", "level_id", "y_start_id", "y_end_id", "x_start_id", "x_end_id"]
    save_excel("project_location", pd.DataFrame(columns=columns))


# ──────────────────────────────────────────────
# 1e. Junction/relationship tables (admin-managed defaults)
# ──────────────────────────────────────────────

def init_requirement_risk():
    """Default requirement-to-risk relationships (read-only in app)."""
    data = [
        {"requirement_id": 1, "risk_id": 7},   # Emergency stop -> Mechanical defect
        {"requirement_id": 2, "risk_id": 7},   # Safety interlocks -> Mechanical defect
        {"requirement_id": 3, "risk_id": 6},   # Access control -> Unauthorized access
        {"requirement_id": 4, "risk_id": 2},   # Stainless steel -> Contamination
        {"requirement_id": 5, "risk_id": 2},   # FDA seals -> Contamination
        {"requirement_id": 7, "risk_id": 9},   # Compressed air -> Overpressure
        {"requirement_id": 8, "risk_id": 4},   # Electrical -> Power failure
        {"requirement_id": 9, "risk_id": 4},   # UPS -> Power failure
        {"requirement_id": 10, "risk_id": 2},  # Purified water -> Contamination
        {"requirement_id": 11, "risk_id": 2},  # Cleanroom -> Contamination
        {"requirement_id": 12, "risk_id": 1},  # Operating temp -> Overtemperature
        {"requirement_id": 14, "risk_id": 5},  # CFR Part 11 -> Data integrity
        {"requirement_id": 15, "risk_id": 5},  # Audit trail -> Data integrity
        {"requirement_id": 16, "risk_id": 6},  # E-signatures -> Unauthorized access
        {"requirement_id": 17, "risk_id": 12}, # Recipe mgmt -> Wrong recipe
        {"requirement_id": 18, "risk_id": 10}, # OPC-UA -> Communication error
        {"requirement_id": 25, "risk_id": 7},  # Maintenance -> Mechanical defect
    ]
    save_excel("requirement_risk", pd.DataFrame(data))


def init_dq_risk():
    """Default DQ-to-risk relationships (read-only in app)."""
    data = [
        {"dq_id": 2, "risk_id": 7},   # Emergency stop DQ -> Mechanical defect
        {"dq_id": 7, "risk_id": 5},   # Audit trail DQ -> Data integrity
        {"dq_id": 3, "risk_id": 1},   # Temperature control DQ -> Overtemperature
        {"dq_id": 8, "risk_id": 6},   # User management DQ -> Unauthorized access
    ]
    save_excel("dq_risk", pd.DataFrame(data))


def init_xq_risk():
    """Default XQ-to-risk relationships (read-only in app)."""
    data = [
        {"xq_id": 1, "risk_id": 1},   # Temperature alarm -> Overtemperature
        {"xq_id": 2, "risk_id": 2},   # Tightness test -> Contamination
        {"xq_id": 3, "risk_id": 3},   # Calibration -> Dosing error
        {"xq_id": 4, "risk_id": 4},   # UPS test -> Power failure
        {"xq_id": 5, "risk_id": 5},   # Audit trail test -> Data integrity
        {"xq_id": 6, "risk_id": 6},   # Access control test -> Unauthorized access
        {"xq_id": 7, "risk_id": 7},   # Safety inspection -> Mechanical defect
        {"xq_id": 8, "risk_id": 8},   # CIP validation -> Cross-contamination
        {"xq_id": 9, "risk_id": 9},   # Pressure safety -> Overpressure
        {"xq_id": 10, "risk_id": 10}, # Network redundancy -> Communication error
        {"xq_id": 11, "risk_id": 11}, # Alarm test -> False alarm
        {"xq_id": 12, "risk_id": 12}, # Recipe locking -> Wrong recipe
    ]
    save_excel("xq_risk", pd.DataFrame(data))


def init_equipment_type_requirement():
    """Which requirements apply to which equipment types (read-only in app).
    All standard requirements apply to ALL equipment types."""
    data = []
    # All 8 equipment types get all 30 requirements that are standard
    standard_req_ids = [1, 2, 3, 4, 5, 7, 8, 10, 11, 12, 13, 14, 15, 16, 17, 19, 20, 21, 22, 23, 24, 25, 26, 28, 29]
    for eq_id in range(1, 9):
        for req_id in standard_req_ids:
            data.append({"equipment_type_id": eq_id, "requirement_id": req_id})
    save_excel("equipment_type_requirement", pd.DataFrame(data))


def init_equipment_type_media():
    """Default media assignments per equipment type (read-only in app)."""
    data = [
        # Bioreactor (1) - Electricity, Compressed Air, Purified Water, Cooling Water
        {"equipment_type_id": 1, "media_id": 1, "default_value": "400V/32A"},
        {"equipment_type_id": 1, "media_id": 2, "default_value": "6 bar"},
        {"equipment_type_id": 1, "media_id": 3, "default_value": "WFI"},
        {"equipment_type_id": 1, "media_id": 4, "default_value": "10 C"},
        # Chromatography System (2)
        {"equipment_type_id": 2, "media_id": 1, "default_value": "400V/16A"},
        {"equipment_type_id": 2, "media_id": 2, "default_value": "6 bar"},
        {"equipment_type_id": 2, "media_id": 3, "default_value": "WFI"},
        {"equipment_type_id": 2, "media_id": 4, "default_value": "10 C"},
        {"equipment_type_id": 2, "media_id": 5, "default_value": "1 Gbit/s"},
        # Filtration System (3)
        {"equipment_type_id": 3, "media_id": 1, "default_value": "400V/16A"},
        {"equipment_type_id": 3, "media_id": 2, "default_value": "6 bar"},
        {"equipment_type_id": 3, "media_id": 3, "default_value": "WFI"},
        # Mixing Vessel (4)
        {"equipment_type_id": 4, "media_id": 1, "default_value": "400V/16A"},
        {"equipment_type_id": 4, "media_id": 2, "default_value": "4 bar"},
        {"equipment_type_id": 4, "media_id": 3, "default_value": "WFI"},
        # Pump (5)
        {"equipment_type_id": 5, "media_id": 1, "default_value": "230V/16A"},
        # Valve (6)
        {"equipment_type_id": 6, "media_id": 2, "default_value": "6 bar"},
        # Sensor (7)
        {"equipment_type_id": 7, "media_id": 1, "default_value": "24V DC"},
        # Control Unit (8)
        {"equipment_type_id": 8, "media_id": 1, "default_value": "230V/10A"},
        {"equipment_type_id": 8, "media_id": 5, "default_value": "1 Gbit/s"},
    ]
    save_excel("equipment_type_media", pd.DataFrame(data))


def init_business_process_step_system_owner():
    """Responsibility mapping (read-only in app)."""
    data = [
        {"business_process_step_id": 1, "system_owner_id": 1},
        {"business_process_step_id": 2, "system_owner_id": 1},
        {"business_process_step_id": 3, "system_owner_id": 1},
        {"business_process_step_id": 4, "system_owner_id": 1},
        {"business_process_step_id": 5, "system_owner_id": 2},
        {"business_process_step_id": 6, "system_owner_id": 2},
    ]
    save_excel("business_process_step_system_owner", pd.DataFrame(data))


# ──────────────────────────────────────────────
# 1f. Asset & operational tables (empty initially)
# ──────────────────────────────────────────────

def init_asset():
    columns = ["id", "name", "equipment_type_id", "project_id"]
    save_excel("asset", pd.DataFrame(columns=columns))


def init_main_asset():
    columns = ["asset_id", "business_process_step_id"]
    save_excel("main_asset", pd.DataFrame(columns=columns))


def init_peripheral_asset():
    columns = ["asset_id", "main_asset_id"]
    save_excel("peripheral_asset", pd.DataFrame(columns=columns))


def init_asset_media():
    columns = ["asset_id", "media_id", "media_value"]
    save_excel("asset_media", pd.DataFrame(columns=columns))


def init_project_phase():
    columns = ["project_id", "phase_id", "status", "approved_at", "approved_by"]
    save_excel("project_phase", pd.DataFrame(columns=columns))


def init_document():
    columns = ["id", "project_id", "document_type_id", "status", "is_active", "created_at", "created_by", "approved_at"]
    save_excel("document", pd.DataFrame(columns=columns))


def init_document_version():
    columns = ["id", "document_id", "version_no", "file_path", "created_at", "created_by", "change_note", "approved_at", "rejected_at"]
    save_excel("document_version", pd.DataFrame(columns=columns))


def init_corrective_action():
    columns = ["id", "name", "responsible", "status", "proof_file_path"]
    save_excel("corrective_action", pd.DataFrame(columns=columns))


def init_mitigation():
    columns = ["id", "risk_id", "phase", "file_path", "status", "passed", "failed_description",
               "mitigation_category_id", "remark", "need_correction", "justification", "corrective_action_id",
               "xq_output"]
    save_excel("mitigation", pd.DataFrame(columns=columns))


def init_asset_risk_phase_decision():
    columns = ["asset_id", "risk_id", "chosen_phase", "decided_by", "decided_at"]
    save_excel("asset_risk_phase_decision", pd.DataFrame(columns=columns))


def init_asset_traceability_matrix():
    columns = [
        "asset_id", "requirement_id", "risk_id",
        "requirement_is_auto_assign", "requirement_remark",
        "risk_is_auto_assign", "risk_remark",
        "dq_id", "dq_is_auto_assign", "dq_remark",
        "xq_id", "xq_is_auto_assign", "xq_remark",
        "mitigation_id",
    ]
    save_excel("asset_traceability_matrix", pd.DataFrame(columns=columns))


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main():
    """Initialize all data files."""
    print("Initializing data files...")
    print("=" * 50)

    # 1a. Core reference tables
    init_country()
    init_coordinate()
    init_coordinate_y()
    init_coordinate_x()
    init_asset_type()
    init_subchapter()
    init_document_type()
    init_mitigation_category()
    init_media()
    init_business_process_step()

    # 1b. Tables with single FK dependency
    init_site()
    init_system_owner()
    init_equipment_type()
    init_requirement()
    init_risk()
    init_dq()
    init_xq()

    # 1c. Site coordinate values
    init_site_coordinate_value()

    # 1d. Tables with deeper FK dependencies
    init_level()
    init_project()
    init_project_location()

    # 1e. Junction/relationship tables (admin-managed defaults)
    init_requirement_risk()
    init_dq_risk()
    init_xq_risk()
    init_equipment_type_requirement()
    init_equipment_type_media()
    init_business_process_step_system_owner()

    # 1f. Asset & operational tables (empty initially)
    init_asset()
    init_main_asset()
    init_peripheral_asset()
    init_asset_media()
    init_project_phase()
    init_document()
    init_document_version()
    init_corrective_action()
    init_mitigation()
    init_asset_risk_phase_decision()
    init_asset_traceability_matrix()

    print("=" * 50)
    print("Data initialization complete!")
    print(f"Files created in: {DATA_DIR}")


if __name__ == "__main__":
    main()
