"""
Enums and dataclasses for the URS MVP.
"""
from enum import Enum
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime


class AssetType(str, Enum):
    MAIN = "main"
    PERIPHERAL = "peripheral"


class Subchapter(str, Enum):
    SAFETY_CONTROL = "safety_control"
    COMPONENTS = "components"
    UTILITIES_MEDIA = "utilities_media"
    ENVIRONMENT = "environment"
    SOFTWARE = "software"
    DOCUMENTATION = "documentation"
    TRAINING = "training"
    MAINTENANCE = "maintenance"
    DELIVERY_ACCEPTANCE = "delivery_acceptance"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class MitigationStatus(str, Enum):
    OPEN = "open"
    DONE = "done"
    NA = "n/a"


class Permission(str, Enum):
    CAN = "CAN"
    MUST = "MUST"
    CANNOT = "CANNOT"


class Phase(str, Enum):
    URS = "URS"
    RISK = "RISK"
    DQ = "DQ"
    XQ_PLAN = "XQ_PLAN"
    XQ_EXECUTION = "XQ_EXECUTION"
    DONE = "DONE"


# Table name constants (map to Excel file names without .xlsx)
class Tables:
    # Core catalogs & master data
    COUNTRY = "country"
    SITE = "site"
    LEVEL = "level"
    COORDINATE = "coordinate"
    COORDINATE_Y = "coordinate_y"
    COORDINATE_X = "coordinate_x"
    SITE_COORDINATE_VALUE = "site_coordinate_value"

    # Project + location
    PROJECT = "project"
    PROJECT_LOCATION = "project_location"

    # Requirements + risk + mitigations (templates)
    SUBCHAPTER = "subchapter"
    REQUIREMENT = "requirement"
    RISK = "risk"
    DQ = "dq"
    XQ = "xq"

    # Template relationships (admin-managed defaults, read-only in app)
    REQUIREMENT_RISK = "requirement_risk"
    DQ_RISK = "dq_risk"
    XQ_RISK = "xq_risk"

    # Equipment types + asset types
    ASSET_TYPE = "asset_type"
    EQUIPMENT_TYPE = "equipment_type"
    EQUIPMENT_TYPE_REQUIREMENT = "equipment_type_requirement"

    # Asset supertype + subtypes
    ASSET = "asset"
    MAIN_ASSET = "main_asset"
    PERIPHERAL_ASSET = "peripheral_asset"

    # Process + responsibilities
    BUSINESS_PROCESS_STEP = "business_process_step"
    SYSTEM_OWNER = "system_owner"
    BUSINESS_PROCESS_STEP_SYSTEM_OWNER = "business_process_step_system_owner"

    # Project phase gating
    PROJECT_PHASE = "project_phase"

    # Document control + versioning
    DOCUMENT_TYPE = "document_type"
    DOCUMENT = "document"
    DOCUMENT_VERSION = "document_version"

    # Risk mitigation execution
    MITIGATION_CATEGORY = "mitigation_category"
    CORRECTIVE_ACTION = "corrective_action"
    MITIGATION = "mitigation"

    # Risk phase decision
    ASSET_RISK_PHASE_DECISION = "asset_risk_phase_decision"

    # Media
    MEDIA = "media"
    EQUIPMENT_TYPE_MEDIA = "equipment_type_media"
    ASSET_MEDIA = "asset_media"

    # Unified traceability matrix
    ASSET_TRACEABILITY_MATRIX = "asset_traceability_matrix"


# Subchapter display names (English)
SUBCHAPTER_LABELS = {
    Subchapter.SAFETY_CONTROL: "Safety & Control",
    Subchapter.COMPONENTS: "Components",
    Subchapter.UTILITIES_MEDIA: "Utilities & Media",
    Subchapter.ENVIRONMENT: "Environment",
    Subchapter.SOFTWARE: "Software",
    Subchapter.DOCUMENTATION: "Documentation",
    Subchapter.TRAINING: "Training",
    Subchapter.MAINTENANCE: "Maintenance",
    Subchapter.DELIVERY_ACCEPTANCE: "Delivery & Acceptance",
}


# Phase display names (English)
PHASE_LABELS = {
    Phase.URS: "1. URS (Requirements)",
    Phase.RISK: "2. Risk Assignment",
    Phase.DQ: "3. DQ (Design Qualification)",
    Phase.XQ_PLAN: "4. xQ Plan",
    Phase.XQ_EXECUTION: "5. xQ Execution",
    Phase.DONE: "6. Completed",
}
