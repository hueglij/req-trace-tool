"""
Policy engine for the URS MVP.
Handles CAN/MUST/CANNOT permissions and Phase-Gates.
"""
from typing import Dict, Any, Literal, Optional
from .models import Phase, Permission, Tables, PHASE_LABELS


# Global configuration
class Config:
    phase_gates_enabled: bool = False  # Default: soft enforcement only
    current_phase: Phase = Phase.URS


PHASE_SEQUENCE = [Phase.URS, Phase.RISK, Phase.DQ, Phase.XQ_PLAN, Phase.XQ_EXECUTION, Phase.DONE]


# Permission matrix: phase -> table -> fields -> permission
# Default is CANNOT (read-only)
PERMISSION_MATRIX: Dict[Phase, Dict[str, Dict[str, Permission]]] = {
    Phase.URS: {
        Tables.ASSET_TRACEABILITY_MATRIX: {
            "requirement_remark": Permission.CAN,
            "requirement_id": Permission.CAN,  # Can add requirements
            "risk_id": Permission.CANNOT,
        },
        Tables.REQUIREMENT: {
            "*": Permission.CAN,  # Can create new catalog entries
        },
    },
    Phase.RISK: {
        Tables.ASSET_TRACEABILITY_MATRIX: {
            "risk_id": Permission.CAN,
            "risk_remark": Permission.CAN,
        },
        Tables.RISK: {
            "*": Permission.CAN,
        },
    },
    Phase.DQ: {
        Tables.ASSET_TRACEABILITY_MATRIX: {
            "requirement_remark": Permission.CAN,
            "dq_id": Permission.CAN,
            "dq_remark": Permission.CAN,
            "risk_id": Permission.CANNOT,
        },
        Tables.MITIGATION: {
            "status": Permission.CAN,
            "file_path": Permission.CAN,
            "passed": Permission.CAN,
            "failed_description": Permission.CAN,
            "mitigation_category_id": Permission.CAN,
            "remark": Permission.CAN,
            "need_correction": Permission.CAN,
            "justification": Permission.CAN,
            "corrective_action_id": Permission.CAN,
        },
        Tables.DQ: {
            "*": Permission.CAN,  # Can create new DQ entries
        },
    },
    Phase.XQ_PLAN: {
        Tables.ASSET_TRACEABILITY_MATRIX: {
            "xq_id": Permission.CAN,
            "xq_remark": Permission.CAN,
        },
        Tables.XQ: {
            "*": Permission.CAN,
        },
    },
    Phase.XQ_EXECUTION: {
        Tables.ASSET_TRACEABILITY_MATRIX: {
            "xq_remark": Permission.CAN,
        },
        Tables.MITIGATION: {
            "status": Permission.CAN,
            "passed": Permission.CAN,
            "failed_description": Permission.CAN,
            "file_path": Permission.CAN,
            "remark": Permission.CAN,
            "need_correction": Permission.CAN,
            "justification": Permission.CAN,
            "xq_output": Permission.CAN,
        },
        Tables.CORRECTIVE_ACTION: {
            "*": Permission.CAN,
        },
    },
    Phase.DONE: {
        # Everything is CANNOT in DONE phase
    },
}

# Fields that are always read-only after initial creation
IMMUTABLE_AFTER_CREATE = {
    Tables.ASSET_TRACEABILITY_MATRIX: ["asset_id", "requirement_id", "risk_id"],
    Tables.DQ: ["id"],
    Tables.RISK: ["id"],
    Tables.XQ: ["id"],
}

# Required fields (MUST) per table
REQUIRED_FIELDS = {
    Tables.ASSET_TRACEABILITY_MATRIX: {
        Phase.URS: ["requirement_remark"],  # Remark MUST if remark_required
    },
}


def get_permissions(
    phase: Phase,
    table: str,
    field: str,
    row_ctx: Optional[Dict[str, Any]] = None
) -> Literal["CAN", "MUST", "CANNOT"]:
    """
    Get the permission for a specific field in a table during a phase.

    Args:
        phase: Current workflow phase
        table: Table name
        field: Field/column name
        row_ctx: Optional row context for conditional permissions

    Returns:
        "CAN", "MUST", or "CANNOT"
    """
    # Check if field is immutable after creation
    if table in IMMUTABLE_AFTER_CREATE:
        if field in IMMUTABLE_AFTER_CREATE[table]:
            # Check if row exists (has ID)
            if row_ctx and row_ctx.get(field) is not None:
                return "CANNOT"

    # Check permission matrix
    phase_perms = PERMISSION_MATRIX.get(phase, {})
    table_perms = phase_perms.get(table, {})

    # Check specific field
    if field in table_perms:
        return table_perms[field].value

    # Check wildcard
    if "*" in table_perms:
        return table_perms["*"].value

    # Default: CANNOT
    return "CANNOT"


def is_editable(
    phase: Phase,
    table: str,
    field: str,
    row_ctx: Optional[Dict[str, Any]] = None
) -> bool:
    """Check if a field is editable (CAN or MUST)."""
    perm = get_permissions(phase, table, field, row_ctx)
    return perm in ("CAN", "MUST")


def is_required(
    phase: Phase,
    table: str,
    field: str,
    row_ctx: Optional[Dict[str, Any]] = None
) -> bool:
    """Check if a field is required (MUST)."""
    perm = get_permissions(phase, table, field, row_ctx)
    return perm == "MUST"


def check_phase_gate(current_phase: Phase, target_page: str) -> Dict[str, Any]:
    """
    Check if access to a page is allowed in the current phase.
    Returns dict with 'allowed' bool and 'message' string.
    """
    # Page to required phase mapping
    page_phases = {
        "01_URS_Composer": Phase.URS,
        "00_URS_Composer_New": Phase.URS,
        "02_DQ": Phase.DQ,
        "03_Risk_Assessment": Phase.RISK,
        "04_Qualification_Plan": Phase.XQ_PLAN,
        "05_Qualification_Execution": Phase.XQ_EXECUTION,
    }

    required_phase = page_phases.get(target_page)
    if required_phase is None:
        return {"allowed": True, "message": ""}

    # Phase order
    current_idx = PHASE_SEQUENCE.index(current_phase)
    required_idx = PHASE_SEQUENCE.index(required_phase)

    if current_idx < required_idx:
        required_label = PHASE_LABELS.get(required_phase, required_phase.value)
        current_label = PHASE_LABELS.get(current_phase, current_phase.value)
        return {
            "allowed": False,
            "message": f"This page requires phase '{required_label}'. "
                       f"Current phase: '{current_label}'."
        }

    return {"allowed": True, "message": ""}


def get_soft_warning(current_phase: Phase, target_page: str) -> Optional[str]:
    """
    Get a soft warning message if editing outside the recommended phase.
    Only returns warning if phase_gates_enabled is False.
    """
    if Config.phase_gates_enabled:
        return None

    check = check_phase_gate(current_phase, target_page)
    if not check["allowed"]:
        return f"Note: {check['message']} (Phase gates disabled)"
    return None


def get_next_phase(phase: Phase) -> Optional[Phase]:
    """Return the next phase in the workflow sequence, or None if already DONE."""
    try:
        idx = PHASE_SEQUENCE.index(phase)
    except ValueError:
        return None
    if idx + 1 < len(PHASE_SEQUENCE):
        return PHASE_SEQUENCE[idx + 1]
    return None


def set_phase(phase: Phase) -> None:
    """Set the current workflow phase."""
    Config.current_phase = phase


def get_current_phase() -> Phase:
    """Get the current workflow phase."""
    return Config.current_phase


def set_phase_gates_enabled(enabled: bool) -> None:
    """Enable or disable phase gates."""
    Config.phase_gates_enabled = enabled


def is_phase_gates_enabled() -> bool:
    """Check if phase gates are enabled."""
    return Config.phase_gates_enabled


def get_phase_indicator(phase: Phase) -> str:
    """Get a visual indicator for the phase status."""
    current_idx = PHASE_SEQUENCE.index(phase)

    indicators = []
    for i, p in enumerate(PHASE_SEQUENCE):
        if i < current_idx:
            indicators.append(f"[x] {p.value}")
        elif i == current_idx:
            indicators.append(f"[>] {p.value}")
        else:
            indicators.append(f"[ ] {p.value}")

    return " -> ".join(indicators)
