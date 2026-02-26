"""
PDF generation using ReportLab for the URS MVP.
"""
from typing import Dict, Any, List, Literal, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path
from io import BytesIO
from datetime import datetime
import re

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, A3, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, ListFlowable, ListItem, Image as RLImage, Flowable
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.pdfgen import canvas

try:
    import fitz
except Exception:
    import pymupdf as fitz
from PIL import Image as PilImage, ImageDraw, ImageFont

from .utils import (
    ensure_output_dir,
    generate_pdf_filename,
    safe_str,
    excel_to_bool,
    get_data_path,
    calculate_quantification,
    calculate_risk_level,
)
from .models import SUBCHAPTER_LABELS, Subchapter, Tables
from .data_io import (
    load_site_coordinates,
    load_table,
    get_row_by_id,
    get_asset_media,
    is_main_asset,
    get_main_asset_id_for,
    get_asset_traceability_entries,
    get_location_display,
    get_before_mitigation_values,
    get_after_mitigation_values,
    get_main_assets,
    get_peripherals,
    get_all_media,
    get_equipment_type_by_id,
    get_pdf_base_context,
    get_project_location,
    get_latest_document_version_info,
)


# Document types
DocType = Literal["URS", "FS", "DQ", "FMEA", "XQ_PLAN", "QUAL_REPORT"]

COMPANY_NAME = "COMPANY"
FOOTER_TEXT = "Created with MEng Qualification App"

DOC_TYPE_TITLES = {
    "URS": "User Requirement Specification",
    "FS": "Functional Specification",
    "DQ": "Design Qualification",
    "FMEA": "Risk Assignment",
    "XQ_PLAN": "Qualification Plan",
    "QUAL_REPORT": "Qualification Execution",
}

DOC_TYPE_FILENAMES = {
    "URS": "URS",
    "FS": "FS",
    "DQ": "DQ",
    "FMEA": "Risk_Assignment",
    "XQ_PLAN": "XQ_Plan",
    "QUAL_REPORT": "Qualification_Report",
}


@dataclass(frozen=True)
class LayoutSpec:
    pagesize: tuple = landscape(A3)
    left_margin: float = 1.5 * cm
    right_margin: float = 1.5 * cm
    top_margin: float = 2.2 * cm
    bottom_margin: float = 1.8 * cm

    @property
    def content_width(self) -> float:
        return self.pagesize[0] - self.left_margin - self.right_margin


class PDFFormTextField(Flowable):
    """An AcroForm text-input field rendered inside a Platypus Table cell."""

    def __init__(self, name: str, height: float = 14):
        super().__init__()
        self.field_name = name
        self.height = height
        self._field_width: float = 0

    def wrap(self, availWidth: float, availHeight: float):
        self._field_width = availWidth
        return availWidth, self.height

    def draw(self) -> None:
        self.canv.acroForm.textfield(
            name=self.field_name,
            tooltip=self.field_name,
            value="",
            x=0,
            y=0,
            width=self._field_width,
            height=self.height,
            fontName="Helvetica",
            fontSize=8,
            borderStyle="inset",
            borderColor=colors.grey,
            fillColor=colors.white,
            relative=True,
        )


class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, header_context=None, footer_context=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []
        self._header_context = header_context or {}
        self._footer_context = footer_context or {}

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        page_count = max(len(self._saved_page_states), 1)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_header_footer(page_count)
            super().showPage()
        super().save()

    def _draw_header_footer(self, page_count: int) -> None:
        width, height = self._pagesize
        layout = self._header_context.get("layout")
        left_margin = layout.left_margin if layout else 1.5 * cm
        right_margin = layout.right_margin if layout else 1.5 * cm

        header_y = height - 10 * mm
        footer_y = 10 * mm
        content_width = width - left_margin - right_margin

        file_name = safe_str(self._header_context.get("file_name"))
        file_path = safe_str(self._header_context.get("file_path"))
        company = safe_str(self._header_context.get("company_name", COMPANY_NAME))

        font_name = "Helvetica"
        header_size = 8
        footer_size = 7

        max_left = content_width * 0.3
        max_center = content_width * 0.4
        max_right = content_width * 0.3

        file_name = _fit_text(file_name, max_left, self, font_name, header_size)
        file_path = _fit_text(file_path, max_center, self, font_name, header_size)
        company = _fit_text(company, max_right, self, font_name, header_size)

        self.setFillColor(colors.grey)
        self.setFont(font_name, header_size)
        self.drawString(left_margin, header_y, file_name)
        self.drawCentredString(width / 2, header_y, file_path)
        self.drawRightString(width - right_margin, header_y, company)

        footer_text = safe_str(self._footer_context.get("footer_text", FOOTER_TEXT))
        page_label = f"{self._pageNumber}/{page_count}"
        export_timestamp = safe_str(self._footer_context.get("export_timestamp", ""))
        export_timestamp = _fit_text(export_timestamp, max_center, self, font_name, footer_size)

        self.setFont(font_name, footer_size)
        self.drawString(left_margin, footer_y, footer_text)
        if export_timestamp:
            self.drawCentredString(width / 2, footer_y, export_timestamp)
        self.drawRightString(width - right_margin, footer_y, page_label)


def _fit_text(text: str, max_width: float, canvas_obj, font_name: str, font_size: int) -> str:
    if not text:
        return ""
    if canvas_obj.stringWidth(text, font_name, font_size) <= max_width:
        return text
    ellipsis = "..."
    trimmed = text
    while trimmed and canvas_obj.stringWidth(trimmed + ellipsis, font_name, font_size) > max_width:
        trimmed = trimmed[:-1]
    return (trimmed + ellipsis) if trimmed else ellipsis


def _build_subchapter_id_map() -> Dict[str, int]:
    """Build mapping from Subchapter enum value (name string) to subchapter table ID."""
    sc_df = load_table(Tables.SUBCHAPTER)
    if sc_df.empty:
        return {}
    result: Dict[str, int] = {}
    for _, row in sc_df.iterrows():
        name = safe_str(row.get("name")).strip()
        sc_id = _int_or_none(row.get("id"))
        if name and sc_id is not None:
            result[name] = sc_id
    return result


def _format_timestamp(value: Any) -> str:
    text = safe_str(value).strip()
    if not text:
        return "-"
    return text.replace("T", " ")[:19]


def _build_system_owner_label(context: Dict[str, Any]) -> str:
    role = safe_str(context.get("system_owner_role")).strip()
    name = safe_str(context.get("system_owner_name")).strip()
    if role and name:
        return f"{role} ({name})"
    return role or name or "-"


def _build_location_label(location: Dict[str, Any]) -> str:
    # New schema: location dict may have a "display" key from get_pdf_base_context
    display = safe_str(location.get("display")).strip()
    if display:
        return display
    # Fallback: try individual parts
    parts = [
        safe_str(location.get("country_iso_code")),
        safe_str(location.get("site_iso_code")),
        safe_str(location.get("level_iso_code")),
        safe_str(location.get("location_code")),
    ]
    parts = [part for part in parts if part.strip()]
    return " - ".join(parts) if parts else "-"


def _parse_location_code(location_code: str) -> Optional[Tuple[str, str, str, str]]:
    if not location_code or "-" not in location_code:
        return None
    start_part, end_part = location_code.split("-", 1)
    if len(start_part) < 3 or len(end_part) < 3:
        return None
    return (
        start_part[0].upper(),
        start_part[1:3],
        end_part[0].upper(),
        end_part[1:3],
    )


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

    font_size = max(10, int(min(max_width, max_height) * 0.4))
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
    label_text: Optional[str],
) -> bytes:
    site_coords = load_site_coordinates()
    coords = site_coords.get(site_id, {}) if site_id else {}
    if not coords:
        return png_bytes

    try:
        x1_pct = float(coords["numbers"][start_number])
        x2_pct = float(coords["numbers"][end_number])
        y1_pct = float(coords["letters"][start_letter])
        y2_pct = float(coords["letters"][end_letter])
    except KeyError:
        return png_bytes

    image = PilImage.open(BytesIO(png_bytes)).convert("RGBA")
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

    overlay = PilImage.new("RGBA", image.size, (0, 0, 0, 0))
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
    combined = PilImage.alpha_composite(image, overlay)
    out = BytesIO()
    combined.save(out, format="PNG")
    return out.getvalue()


def _build_location_plan_png(context: Dict[str, Any]) -> Optional[bytes]:
    location = context.get("location") or {}
    country_iso = safe_str(location.get("country_iso_code")).strip()
    site_iso = safe_str(location.get("site_iso_code")).strip()
    site_id = _int_or_none(location.get("site_id"))
    level_iso = safe_str(location.get("level_iso_code")).strip()
    location_code = safe_str(location.get("location_code")).strip()
    if not country_iso or not site_iso or not level_iso or not location_code:
        return None

    parsed = _parse_location_code(location_code)
    if not parsed:
        return None
    start_letter, start_number, end_letter, end_number = parsed

    plan_path = get_data_path() / "Grundrisse" / f"Grundriss_{country_iso}_{site_iso}_{level_iso}.pdf"
    if not plan_path.exists():
        return None

    try:
        with fitz.open(plan_path) as doc:
            page = doc.load_page(0)
            pix = page.get_pixmap(dpi=150, alpha=False)
            png_bytes = pix.tobytes("png")
    except Exception:
        return None

    return _apply_quadrant_overlay(
        png_bytes,
        site_id if site_id is not None else 0,
        start_letter,
        start_number,
        end_letter,
        end_number,
        label_text=safe_str(context.get("project_name")),
    )


def create_location_plan_section(context: Dict[str, Any], styles, layout: LayoutSpec) -> List[Any]:
    elements: List[Any] = []
    png_bytes = _build_location_plan_png(context)
    if not png_bytes:
        return elements

    elements.append(Paragraph("Floor Plan", styles["ChapterTitle"]))
    elements.append(Spacer(1, 0.3 * cm))

    with PilImage.open(BytesIO(png_bytes)) as image:
        img_width, img_height = image.size
    target_width = layout.content_width
    target_height = target_width * (img_height / img_width)
    max_height = layout.pagesize[1] - layout.top_margin - layout.bottom_margin - (2.5 * cm)
    if target_height > max_height:
        target_height = max_height
        target_width = target_height * (img_width / img_height)

    elements.append(RLImage(BytesIO(png_bytes), width=target_width, height=target_height))
    elements.append(PageBreak())
    return elements


def create_medien_section(context: Dict[str, Any], styles, layout: LayoutSpec) -> List[Any]:
    """Create Media (utilities & media connections) table section."""
    elements: List[Any] = []
    asset_overview_rows = context.get("asset_overview_rows") or []
    if not asset_overview_rows:
        return elements

    # Load all media types dynamically from the MEDIA table
    import pandas as pd
    media_df = load_table(Tables.MEDIA)
    if media_df.empty:
        return elements

    media_columns: List[Dict[str, Any]] = []
    for _, m_row in media_df.iterrows():
        media_columns.append({
            "media_id": int(m_row["id"]),
            "label": safe_str(m_row.get("name", m_row.get("media_type", ""))),
        })

    if not media_columns:
        return elements

    elements.append(Paragraph("Media", styles["ChapterTitle"]))
    elements.append(Spacer(1, 0.3 * cm))

    # Build header row
    header = ["Equipment Type", "Asset Type"]
    for media_info in media_columns:
        header.append(media_info["label"])

    table_data = [header]

    for row in asset_overview_rows:
        row_asset_id = row.get("asset_id")
        if row_asset_id is None:
            continue

        # Load media for this asset
        asset_media_df = get_asset_media(int(row_asset_id))
        media_map: Dict[int, str] = {}
        if not asset_media_df.empty:
            for _, am_row in asset_media_df.iterrows():
                media_map[int(am_row["media_id"])] = safe_str(am_row.get("media_value", ""))

        data_row = [
            _cell(row.get("equipment_type", ""), styles, "TableCellTiny"),
            _cell(row.get("asset_type", ""), styles, "TableCellTiny"),
        ]
        for media_info in media_columns:
            value = media_map.get(media_info["media_id"], "")
            data_row.append(_cell(value if value else "-", styles, "TableCellTiny"))

        table_data.append(data_row)

    num_media = len(media_columns)
    media_frac = 0.7 / num_media if num_media > 0 else 0.7
    fractions = [0.18, 0.12] + [media_frac] * num_media
    col_widths = _widths_from_fractions(layout, fractions)

    table = Table(table_data, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2E86AB")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("FONTSIZE", (0, 0), (-1, 0), 7),
        ("FONTSIZE", (0, 1), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
        ("TOPPADDING", (0, 0), (-1, 0), 4),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
    ]))

    elements.append(table)
    elements.append(PageBreak())
    return elements


def _widths_from_fractions(layout: LayoutSpec, fractions: List[float]) -> List[float]:
    return [layout.content_width * fraction for fraction in fractions]


def _cell(text: Any, styles, style_name: str = "TableCell") -> Paragraph:
    content = safe_str(text).strip() or "-"
    return Paragraph(content, styles[style_name])


def get_styles():
    """Get custom paragraph styles."""
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name="DocTitle",
        parent=styles["Heading1"],
        fontSize=22,
        alignment=TA_CENTER,
        spaceAfter=12,
    ))

    styles.add(ParagraphStyle(
        name="SubTitle",
        parent=styles["Normal"],
        fontSize=12,
        alignment=TA_CENTER,
        spaceAfter=10,
    ))

    styles.add(ParagraphStyle(
        name="ChapterTitle",
        parent=styles["Heading2"],
        fontSize=14,
        spaceBefore=14,
        spaceAfter=6,
        keepWithNext=True,
    ))

    styles.add(ParagraphStyle(
        name="SectionTitle",
        parent=styles["Heading3"],
        fontSize=12,
        spaceBefore=10,
        spaceAfter=4,
        keepWithNext=True,
    ))

    styles.add(ParagraphStyle(
        name="TableHeader",
        parent=styles["Normal"],
        fontSize=8,
        alignment=TA_CENTER,
        textColor=colors.white,
    ))

    styles.add(ParagraphStyle(
        name="TableHeaderSmall",
        parent=styles["TableHeader"],
        fontSize=7,
        leading=8,
        alignment=TA_CENTER,
        textColor=colors.white,
    ))

    styles.add(ParagraphStyle(
        name="TableHeaderTiny",
        parent=styles["TableHeader"],
        fontSize=6,
        leading=7,
        alignment=TA_CENTER,
        textColor=colors.white,
    ))

    styles.add(ParagraphStyle(
        name="TableCell",
        parent=styles["Normal"],
        fontSize=9,
        alignment=TA_LEFT,
    ))

    styles.add(ParagraphStyle(
        name="TableCellSmall",
        parent=styles["TableCell"],
        fontSize=7,
        leading=8,
        alignment=TA_LEFT,
    ))

    styles.add(ParagraphStyle(
        name="TableCellTiny",
        parent=styles["TableCell"],
        fontSize=6,
        leading=7,
        alignment=TA_LEFT,
    ))

    return styles


def create_title_page(context: Dict[str, Any], doc_type: DocType, styles, layout: LayoutSpec) -> List:
    """Create a title page for the document."""
    elements: List[Any] = []

    doc_title = DOC_TYPE_TITLES.get(doc_type, doc_type)
    version = safe_str(context.get("document_version") or context.get("version") or "V01")

    elements.append(Spacer(1, 0.8 * cm))
    elements.append(Paragraph(doc_title, styles["DocTitle"]))
    elements.append(Paragraph(f"Version: {version}", styles["SubTitle"]))
    elements.append(Spacer(1, 0.4 * cm))

    info_rows = [
        ["Company:", _cell(COMPANY_NAME, styles)],
        ["Asset:", _cell(context.get("asset_name"), styles)],
        ["Business Process Step:", _cell(context.get("business_process_step"), styles)],
        ["System Owner:", _cell(_build_system_owner_label(context), styles)],
        ["Project:", _cell(context.get("project_name"), styles)],
        ["Location:", _cell(_build_location_label(context.get("location") or {}), styles)],
    ]

    info_table = Table(
        info_rows,
        colWidths=[5 * cm, layout.content_width - 5 * cm],
        hAlign="LEFT",
    )
    info_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 0.4 * cm))

    asset_rows = context.get("asset_overview_rows") or []
    if asset_rows:
        table_data = [["Equipment Type", "Asset Type", "Asset Name"]]
        for row in asset_rows:
            table_data.append([
                _cell(row.get("equipment_type"), styles),
                _cell(row.get("asset_type"), styles),
                _cell(row.get("asset_name"), styles),
            ])

        overview_table = Table(
            table_data,
            colWidths=_widths_from_fractions(layout, [0.28, 0.18, 0.54]),
            repeatRows=1,
            hAlign="LEFT",
        )
        overview_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2E86AB")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        elements.append(overview_table)
        elements.append(Spacer(1, 0.4 * cm))


    created = _format_timestamp(context.get("document_creation_timestamp"))
    approved = _format_timestamp(context.get("document_approval_timestamp"))
    meta_table = Table(
        [["Created:", _cell(created, styles)], ["Approved:", _cell(approved, styles)]],
        colWidths=[5 * cm, layout.content_width - 5 * cm],
        hAlign="LEFT",
    )
    meta_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(meta_table)

    asset_id = context.get("asset_id")
    if asset_id:
        elements.append(Spacer(1, 0.4 * cm))
        _hist_doc_type = "URS" if doc_type == "FS" else doc_type
        elements.extend(create_document_history_table(asset_id, _hist_doc_type, styles, layout))

    elements.append(PageBreak())
    return elements


def create_toc(sections: List[str], styles) -> List:
    """Create a simple table of contents."""
    elements = []
    elements.append(Paragraph("Table of Contents", styles["ChapterTitle"]))
    elements.append(Spacer(1, 0.4 * cm))

    for i, section in enumerate(sections, 1):
        elements.append(Paragraph(f"{i}. {section}", styles["Normal"]))

    elements.append(PageBreak())
    return elements


def create_terms_and_conditions_page(context: Dict[str, Any], styles) -> List:
    """Create the general terms and conditions page for URS."""
    elements = []
    elements.append(Paragraph("General Terms and Conditions", styles["ChapterTitle"]))

    terms = context.get("terms_and_conditions")
    if terms:
        if isinstance(terms, list):
            for entry in terms:
                elements.append(Paragraph(safe_str(entry), styles["Normal"]))
        else:
            elements.append(Paragraph(safe_str(terms), styles["Normal"]))

    elements.append(PageBreak())
    return elements


def create_urs_requirements_table(requirements: List[Dict[str, Any]], styles, layout: LayoutSpec) -> List:
    """Create the URS requirements table with remarks and flags."""
    elements: List[Any] = []

    if not requirements:
        elements.append(Paragraph("No requirements found.", styles["Normal"]))
        return elements

    headers = ["ID", "Requirement", "Remark", "GxP", "Must-Have"]
    col_widths = _widths_from_fractions(layout, [0.08, 0.42, 0.32, 0.09, 0.09])

    table_data = [headers]

    for req in requirements:
        req_id = safe_str(req.get("requirement_id"))
        urs_label = f"URS-{req_id}" if req_id else "-"
        requirement_text = safe_str(req.get("description"))
        remark_text = safe_str(req.get("requirement_remark"))
        table_data.append([
            urs_label,
            _cell(requirement_text, styles),
            _cell(remark_text, styles),
            "Yes" if excel_to_bool(req.get("is_gxp")) else "No",
            "MUST" if excel_to_bool(req.get("is_must")) else "CAN",
        ])

    table = Table(table_data, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2E86AB")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("ALIGN", (0, 1), (0, -1), "CENTER"),
        ("ALIGN", (3, 1), (4, -1), "CENTER"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
    ]))

    elements.append(table)
    return elements


def create_fs_requirements_table(requirements: List[Dict[str, Any]], styles, layout: LayoutSpec) -> List:
    """Create the FS requirements table -- same as URS but with an extra empty 'FS' column after Must-Have."""
    elements: List[Any] = []

    if not requirements:
        elements.append(Paragraph("No requirements found.", styles["Normal"]))
        return elements

    headers = ["ID", "Requirement", "Remark", "GxP", "Must-Have", "FS"]
    col_widths = _widths_from_fractions(layout, [0.05, 0.38, 0.20, 0.07, 0.07, 0.23])

    table_data = [headers]

    for i, req in enumerate(requirements):
        req_id = safe_str(req.get("requirement_id"))
        urs_label = f"URS-{req_id}" if req_id else "-"
        requirement_text = safe_str(req.get("description"))
        remark_text = safe_str(req.get("requirement_remark"))
        field_name = f"fs_{req_id}" if req_id else f"fs_row_{i}"
        table_data.append([
            urs_label,
            _cell(requirement_text, styles),
            _cell(remark_text, styles),
            "Yes" if excel_to_bool(req.get("is_gxp")) else "No",
            "MUST" if excel_to_bool(req.get("is_must")) else "CAN",
            PDFFormTextField(field_name),
        ])

    table = Table(table_data, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2E86AB")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("ALIGN", (0, 1), (0, -1), "CENTER"),
        ("ALIGN", (3, 1), (4, -1), "CENTER"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
        # Remove cell padding for the FS form-field column so the field fills the cell
        ("LEFTPADDING", (5, 1), (5, -1), 2),
        ("RIGHTPADDING", (5, 1), (5, -1), 2),
        ("TOPPADDING", (5, 1), (5, -1), 2),
        ("BOTTOMPADDING", (5, 1), (5, -1), 2),
    ]))

    elements.append(table)
    return elements


def create_requirements_table(
    requirements: List[Dict[str, Any]],
    styles,
    layout: LayoutSpec,
    include_dq: bool = False,
    include_risk: bool = False,
) -> List:
    """Create a table of requirements."""
    elements: List[Any] = []

    if not requirements:
        elements.append(Paragraph("No requirements found.", styles["Normal"]))
        return elements

    headers = ["ID", "Requirement", "Type", "GxP"]
    fractions = [0.08, 0.62, 0.18, 0.12]

    if include_dq and include_risk:
        headers.extend(["DQ", "Risk Level", "Mitigation"])
        fractions = [0.07, 0.30, 0.12, 0.07, 0.18, 0.10, 0.16]
    elif include_dq:
        headers.append("DQ")
        fractions = [0.08, 0.44, 0.16, 0.10, 0.22]
    elif include_risk:
        headers.extend(["Risk Level", "Mitigation"])
        fractions = [0.08, 0.38, 0.14, 0.08, 0.12, 0.20]

    col_widths = _widths_from_fractions(layout, fractions)

    table_data = [headers]

    for req in requirements:
        row = [
            safe_str(req.get("requirement_id")),
            _cell(req.get("description"), styles),
            "MUST" if excel_to_bool(req.get("is_must")) else "CAN",
            "Yes" if excel_to_bool(req.get("is_gxp")) else "No",
        ]

        if include_dq:
            # Look up DQ description from catalog
            dq_id = _int_or_none(req.get("dq_id"))
            dq_row = get_row_by_id(Tables.DQ, dq_id) if dq_id else None
            dq_desc = safe_str((dq_row or {}).get("description", req.get("dq_description", "")))
            row.append(_cell(dq_desc, styles))

        if include_risk:
            _, _, _, _, level_after = _risk_after_values(req)
            row.append(level_after.upper() if level_after else "")
            row.append(_cell(req.get("mitigation_status", ""), styles))

        table_data.append(row)

    table = Table(table_data, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2E86AB")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
    ]))

    elements.append(table)
    return elements


def create_fmea_table(risks: List[Dict[str, Any]], styles, layout: LayoutSpec) -> List:
    """Create an FMEA table."""
    elements: List[Any] = []

    if not risks:
        elements.append(Paragraph("No risk assessments found.", styles["Normal"]))
        return elements

    headers = ["URS", "Error", "Harm", "S", "O", "D", "RPN", "Level", "Status"]
    col_widths = _widths_from_fractions(layout, [0.07, 0.20, 0.20, 0.05, 0.05, 0.05, 0.07, 0.08, 0.23])

    table_data = [headers]

    for risk in risks:
        # Look up risk details from catalog
        risk_id = _int_or_none(risk.get("risk_id"))
        risk_row = get_row_by_id(Tables.RISK, risk_id) if risk_id else None
        possible_error = safe_str((risk_row or {}).get("possible_error", risk.get("possible_error", "")))[:60]
        harm = safe_str((risk_row or {}).get("harm", risk.get("harm", "")))[:60]

        # Get after-mitigation values via lookup
        sev_after, occ_after, det_after, quant_after, level_after = _risk_after_values(risk)

        row = [
            safe_str(risk.get("requirement_id")),
            possible_error,
            harm,
            safe_str(sev_after),
            safe_str(occ_after),
            safe_str(det_after),
            safe_str(quant_after),
            level_after.upper() if level_after else "",
            safe_str(risk.get("mitigation_status", "")),
        ]
        table_data.append(row)

    table = Table(table_data, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#C73E1D")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FFF5F5")]),
    ]))

    elements.append(table)
    return elements


RISK_MATRIX_LIKELIHOOD_LEVELS = [
    (1, "Very unlikely (1)"),
    (2, "Unlikely (2)"),
    (3, "Possible (3)"),
    (4, "Likely (4)"),
    (6, "Very likely (6)"),
]

RISK_MATRIX_SEVERITY_LEVELS = [
    (3, "High (3)"),
    (2, "Medium (2)"),
    (1, "Low (1)"),
]

RISK_MATRIX_COLOR_MAP = {
    (1, 1): colors.HexColor("#CDECCD"),
    (1, 2): colors.HexColor("#CDECCD"),
    (1, 3): colors.HexColor("#CDECCD"),
    (1, 4): colors.HexColor("#CDECCD"),
    (1, 6): colors.HexColor("#FFF1A8"),
    (2, 1): colors.HexColor("#CDECCD"),
    (2, 2): colors.HexColor("#FFF1A8"),
    (2, 3): colors.HexColor("#FFF1A8"),
    (2, 4): colors.HexColor("#FFF1A8"),
    (2, 6): colors.HexColor("#F7B5B5"),
    (3, 1): colors.HexColor("#FFF1A8"),
    (3, 2): colors.HexColor("#FFF1A8"),
    (3, 3): colors.HexColor("#F7B5B5"),
    (3, 4): colors.HexColor("#F7B5B5"),
    (3, 6): colors.HexColor("#F7B5B5"),
}


def _int_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, float):
        if str(value) == "nan":
            return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _likelihood_bucket(value: int) -> Optional[int]:
    if value <= 1:
        return 1
    if value <= 2:
        return 2
    if value <= 3:
        return 3
    if value <= 4:
        return 4
    return 6


def _risk_before_values(entry: Dict[str, Any]) -> tuple[Optional[int], Optional[int], Optional[int], Optional[int], str]:
    """Get before-mitigation values. Uses get_before_mitigation_values() from data_io
    when a risk_id is available, otherwise falls back to entry dict keys."""
    risk_id = _int_or_none(entry.get("risk_id"))
    if risk_id is not None:
        vals = get_before_mitigation_values(risk_id)
        sev = _int_or_none(vals.get("severity_before_mitigation"))
        occ = _int_or_none(vals.get("likelihood_before_mitigation"))
        det = _int_or_none(vals.get("detectability_before_mitigation"))
        quant = _int_or_none(vals.get("quantification_before_mitigation"))
        level = safe_str(vals.get("risk_level_before_mitigation")).lower().strip()
        return sev, occ, det, quant, level

    # Fallback for pre-built context dicts
    sev = _int_or_none(entry.get("severity_before_mitigation"))
    occ = _int_or_none(entry.get("likelihood_before_mitigation"))
    det = _int_or_none(entry.get("detectability_before_mitigation"))
    quant = _int_or_none(entry.get("quantification_before_mitigation"))
    level = safe_str(entry.get("risk_level_before_mitigation")).lower().strip()

    if quant is None and sev and occ and det:
        quant = calculate_quantification(sev, occ, det)
    if not level and quant is not None:
        level = calculate_risk_level(quant)

    return sev, occ, det, quant, level


def _risk_after_values(entry: Dict[str, Any]) -> tuple[Optional[int], Optional[int], Optional[int], Optional[int], str]:
    """Get after-mitigation values. Uses get_after_mitigation_values() from data_io
    when a dq_id or xq_id is available, otherwise falls back to entry dict keys."""
    dq_id = _int_or_none(entry.get("dq_id"))
    xq_id = _int_or_none(entry.get("xq_id"))

    if dq_id is not None or xq_id is not None:
        if xq_id is not None:
            vals = get_after_mitigation_values(xq_id, is_xq=True)
        else:
            vals = get_after_mitigation_values(dq_id, is_xq=False)
        sev = _int_or_none(vals.get("severity_after_mitigation"))
        occ = _int_or_none(vals.get("likelihood_after_mitigation"))
        det = _int_or_none(vals.get("detectability_after_mitigation"))
        quant = _int_or_none(vals.get("quantification_after_mitigation"))
        level = safe_str(vals.get("risk_level_after_mitigation")).lower().strip()
        return sev, occ, det, quant, level

    # Fallback for pre-built context dicts
    sev = _int_or_none(entry.get("severity_after_mitigation"))
    occ = _int_or_none(entry.get("likelihood_after_mitigation"))
    det = _int_or_none(entry.get("detectability_after_mitigation"))
    quant = _int_or_none(entry.get("quantification_after_mitigation"))
    level = safe_str(entry.get("risk_level_after_mitigation")).lower().strip()

    if quant is None and sev and occ and det:
        quant = calculate_quantification(sev, occ, det)
    if not level and quant is not None:
        level = calculate_risk_level(quant)

    return sev, occ, det, quant, level


def _build_risk_matrix_counts(rows: List[tuple[Optional[int], Optional[int], Optional[int]]]) -> Dict[int, Dict[int, int]]:
    counts = {
        severity: {likelihood: 0 for likelihood, _ in RISK_MATRIX_LIKELIHOOD_LEVELS}
        for severity, _ in RISK_MATRIX_SEVERITY_LEVELS
    }

    for sev, occ, det in rows:
        if sev not in (1, 2, 3) or occ is None or det is None:
            continue
        likelihood_score = occ * det
        bucket = _likelihood_bucket(likelihood_score)
        if bucket is None:
            continue
        counts[sev][bucket] += 1

    return counts


def _build_risk_matrix_table(counts: Dict[int, Dict[int, int]], styles, layout: LayoutSpec) -> Table:
    header = ["Impact"] + [label for _, label in RISK_MATRIX_LIKELIHOOD_LEVELS]
    table_data = [header]
    for severity, label in RISK_MATRIX_SEVERITY_LEVELS:
        row = [label]
        for likelihood, _ in RISK_MATRIX_LIKELIHOOD_LEVELS:
            row.append(str(counts.get(severity, {}).get(likelihood, 0)))
        table_data.append(row)

    col_widths = _widths_from_fractions(layout, [0.22] + [0.156] * 5)
    table = Table(table_data, colWidths=col_widths, hAlign="LEFT")
    style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2E86AB")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ])

    for row_idx, (severity, _) in enumerate(RISK_MATRIX_SEVERITY_LEVELS, start=1):
        for col_idx, (likelihood, _) in enumerate(RISK_MATRIX_LIKELIHOOD_LEVELS, start=1):
            color = RISK_MATRIX_COLOR_MAP.get((severity, likelihood), colors.white)
            style.add("BACKGROUND", (col_idx, row_idx), (col_idx, row_idx), color)
            style.add("TEXTCOLOR", (col_idx, row_idx), (col_idx, row_idx), colors.black)

    table.setStyle(style)
    return table


def create_risk_matrix_section(risks: List[Dict[str, Any]], styles, layout: LayoutSpec) -> List:
    elements: List[Any] = []
    elements.append(Paragraph("Risk Matrix (Before Mitigation)", styles["ChapterTitle"]))
    elements.append(Spacer(1, 0.3 * cm))

    if not risks:
        elements.append(Paragraph("No risk assignments found.", styles["Normal"]))
        elements.append(PageBreak())
        return elements

    rows: List[tuple[Optional[int], Optional[int], Optional[int]]] = []
    for entry in risks:
        sev, occ, det, _, _ = _risk_before_values(entry)
        rows.append((sev, occ, det))

    counts = _build_risk_matrix_counts(rows)
    elements.append(_build_risk_matrix_table(counts, styles, layout))
    elements.append(PageBreak())
    return elements


def create_dq_risk_matrix_section(requirements: List[Dict[str, Any]], styles, layout: LayoutSpec) -> List:
    elements: List[Any] = []
    elements.append(Paragraph("Risk Matrix", styles["ChapterTitle"]))
    elements.append(Spacer(1, 0.2 * cm))

    if not requirements:
        elements.append(Paragraph("No risk assignments found.", styles["Normal"]))
        elements.append(PageBreak())
        return elements

    seen: set = set()
    deduped: List[Dict[str, Any]] = []
    for entry in requirements:
        urs_id = _int_or_none(entry.get("requirement_id"))
        risk_id = _int_or_none(entry.get("risk_id"))
        if urs_id is None or risk_id is None:
            continue
        asset_id = _int_or_none(entry.get("asset_id"))
        key = (asset_id, urs_id, risk_id) if asset_id is not None else (urs_id, risk_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)

    before_rows: List[tuple[Optional[int], Optional[int], Optional[int]]] = []
    after_rows: List[tuple[Optional[int], Optional[int], Optional[int]]] = []

    for entry in deduped:
        sev_before, occ_before, det_before, _, _ = _risk_before_values(entry)
        before_rows.append((sev_before, occ_before, det_before))

        # After DQ -- use DQ after-values whenever a DQ is assigned
        dq_id = _int_or_none(entry.get("dq_id"))

        if dq_id is not None:
            vals = get_after_mitigation_values(dq_id, is_xq=False)
            sev_after = _int_or_none(vals.get("severity_after_mitigation"))
            occ_after = _int_or_none(vals.get("likelihood_after_mitigation"))
            det_after = _int_or_none(vals.get("detectability_after_mitigation"))
            if sev_after is not None and occ_after is not None and det_after is not None:
                after_rows.append((sev_after, occ_after, det_after))
            else:
                after_rows.append((sev_before, occ_before, det_before))
        else:
            after_rows.append((sev_before, occ_before, det_before))

    before_counts = _build_risk_matrix_counts(before_rows)
    after_counts = _build_risk_matrix_counts(after_rows)

    elements.append(Paragraph("Before Mitigation", styles["SectionTitle"]))
    elements.append(Spacer(1, 0.2 * cm))
    elements.append(_build_risk_matrix_table(before_counts, styles, layout))
    elements.append(Spacer(1, 0.5 * cm))
    elements.append(Paragraph("After DQ Mitigation", styles["SectionTitle"]))
    elements.append(Spacer(1, 0.2 * cm))
    elements.append(_build_risk_matrix_table(after_counts, styles, layout))
    elements.append(PageBreak())
    return elements


def create_risk_assignment_table(requirements: List[Dict[str, Any]], styles, layout: LayoutSpec) -> List:
    elements: List[Any] = []

    if not requirements:
        elements.append(Paragraph("No risk assignments found.", styles["Normal"]))
        return elements

    # Sort requirements by requirement_id
    sorted_requirements = sorted(requirements, key=lambda r: int(r.get("requirement_id", 0)) if r.get("requirement_id") else 0)

    # Headers with "(before)" on separate line using <br/> tag
    headers = [
        Paragraph("ID", styles["TableHeaderSmall"]),
        Paragraph("Requirement", styles["TableHeaderSmall"]),
        Paragraph("Remark", styles["TableHeaderSmall"]),
        Paragraph("GxP", styles["TableHeaderSmall"]),
        Paragraph("Must-<br/>Have", styles["TableHeaderSmall"]),
        Paragraph("Risk-ID", styles["TableHeaderSmall"]),
        Paragraph("Risk Title", styles["TableHeaderSmall"]),
        Paragraph("S<br/>(before)", styles["TableHeaderSmall"]),
        Paragraph("O<br/>(before)", styles["TableHeaderSmall"]),
        Paragraph("D<br/>(before)", styles["TableHeaderSmall"]),
        Paragraph("RPN<br/>(before)", styles["TableHeaderSmall"]),
        Paragraph("Level<br/>(before)", styles["TableHeaderSmall"]),
        Paragraph("Miti-<br/>gation", styles["TableHeaderSmall"]),
    ]
    col_widths = _widths_from_fractions(
        layout,
        [0.05, 0.18, 0.14, 0.05, 0.06, 0.06, 0.14, 0.05, 0.05, 0.05, 0.06, 0.06, 0.05],
    )

    table_data = [headers]

    for req in sorted_requirements:
        req_id = safe_str(req.get("requirement_id"))
        urs_label = f"URS-{req_id}" if req_id else "-"
        requirement_text = safe_str(req.get("description"))
        remark_text = safe_str(req.get("requirement_remark"))
        risk_id = _int_or_none(req.get("risk_id"))
        risk_id_label = f"Risk-{risk_id}" if risk_id is not None else "-"
        risk_title = safe_str(req.get("possible_error"))

        sev, occ, det, quant, level = _risk_before_values(req)
        level_display = level.upper() if level else ""

        mitigation_required = False
        if level:
            mitigation_required = level in ("high", "medium")
        elif "mitigation_required" in req:
            mitigation_required = excel_to_bool(req.get("mitigation_required"))

        table_data.append([
            urs_label,
            _cell(requirement_text, styles, "TableCellSmall"),
            _cell(remark_text, styles, "TableCellSmall"),
            "Yes" if excel_to_bool(req.get("is_gxp")) else "No",
            "MUST" if excel_to_bool(req.get("is_must")) else "CAN",
            risk_id_label,
            _cell(risk_title, styles, "TableCellSmall"),
            safe_str(sev),
            safe_str(occ),
            safe_str(det),
            safe_str(quant),
            level_display,
            "YES" if mitigation_required else "NO",
        ])

    table = Table(table_data, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        # URS-related columns (0-4): blue background
        ("BACKGROUND", (0, 0), (4, 0), colors.HexColor("#2E86AB")),
        # Risk-related columns (5-12): yellow/orange background
        ("BACKGROUND", (5, 0), (12, 0), colors.HexColor("#E8A838")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE", (0, 0), (-1, 0), 7),
        ("FONTSIZE", (0, 1), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
    ]))

    elements.append(table)
    return elements


def create_dq_table(requirements: List[Dict[str, Any]], styles, layout: LayoutSpec) -> List:
    elements: List[Any] = []

    if not requirements:
        elements.append(Paragraph("No DQ assignments found.", styles["Normal"]))
        return elements

    def _dq_sort_key(entry: Dict[str, Any]) -> tuple[int, int, int]:
        urs_id = _int_or_none(entry.get("requirement_id")) or 0
        risk_id = _int_or_none(entry.get("risk_id")) or 0
        dq_id = _int_or_none(entry.get("dq_id")) or 0
        return (urs_id, risk_id, dq_id)

    sorted_requirements = sorted(requirements, key=_dq_sort_key)

    headers = [
        Paragraph("ID", styles["TableHeaderTiny"]),
        Paragraph("Requirement", styles["TableHeaderTiny"]),
        Paragraph("Remark", styles["TableHeaderTiny"]),
        Paragraph("GxP", styles["TableHeaderTiny"]),
        Paragraph("Must-<br/>Have", styles["TableHeaderTiny"]),
        Paragraph("Risk-ID", styles["TableHeaderTiny"]),
        Paragraph("Risk Title", styles["TableHeaderTiny"]),
        Paragraph("S<br/>(before)", styles["TableHeaderTiny"]),
        Paragraph("O<br/>(before)", styles["TableHeaderTiny"]),
        Paragraph("D<br/>(before)", styles["TableHeaderTiny"]),
        Paragraph("RPN<br/>(before)", styles["TableHeaderTiny"]),
        Paragraph("Level<br/>(before)", styles["TableHeaderTiny"]),
        Paragraph("Miti-<br/>gation?", styles["TableHeaderTiny"]),
        Paragraph("Solved<br/>by DQ?", styles["TableHeaderTiny"]),
        Paragraph("DQ-ID", styles["TableHeaderTiny"]),
        Paragraph("DQ Description", styles["TableHeaderTiny"]),
        Paragraph("Evidence", styles["TableHeaderTiny"]),
        Paragraph("S<br/>(after)", styles["TableHeaderTiny"]),
        Paragraph("O<br/>(after)", styles["TableHeaderTiny"]),
        Paragraph("D<br/>(after)", styles["TableHeaderTiny"]),
        Paragraph("RPN<br/>(after)", styles["TableHeaderTiny"]),
        Paragraph("Level<br/>(after)", styles["TableHeaderTiny"]),
        Paragraph("DQ Remark", styles["TableHeaderTiny"]),
    ]

    weights = [
        1, 3.5, 2, 1.5, 2,
        1.5, 2.5, 1.3, 1.3, 1.3, 1.3, 1.5, 1.5,
        1.6, 1.1, 2.5, 2.5, 1.6, 1.6, 1.6, 1.6, 1.6, 1.8,
    ]
    total_weight = sum(weights)
    fractions = [w / total_weight for w in weights]
    col_widths = _widths_from_fractions(layout, fractions)

    table_data = [headers]

    for req in sorted_requirements:
        urs_id = _int_or_none(req.get("requirement_id"))
        risk_id = _int_or_none(req.get("risk_id"))

        # Look up requirement details from catalog
        req_row = get_row_by_id(Tables.REQUIREMENT, urs_id) if urs_id else None
        requirement_text = safe_str((req_row or {}).get("description", req.get("description", "")))
        remark_text = safe_str(req.get("requirement_remark", ""))
        is_gxp = excel_to_bool((req_row or {}).get("is_gxp", req.get("is_gxp")))
        is_must = excel_to_bool((req_row or {}).get("is_must", req.get("is_must")))

        # Look up risk details from catalog
        risk_row = get_row_by_id(Tables.RISK, risk_id) if risk_id else None
        risk_title = safe_str((risk_row or {}).get("possible_error", req.get("possible_error", "")))

        sev, occ, det, quant, level = _risk_before_values(req)
        level_display = level.upper() if level else ""
        mitigation_required = level in ("high", "medium")

        can_use_dq = mitigation_required
        if not level and "mitigation_required" in req:
            can_use_dq = excel_to_bool(req.get("mitigation_required"))

        dq_id = _int_or_none(req.get("dq_id"))
        xq_id = _int_or_none(req.get("xq_id"))
        solved_by_dq = dq_id is not None
        solved_display = "n/a" if not can_use_dq else ("YES" if solved_by_dq else "NO")

        dq_id_display = ""
        if dq_id is not None:
            dq_id_display = f"DQ-{dq_id}"

        urs_label = f"URS-{urs_id}" if urs_id is not None else "-"
        risk_id_label = f"Risk-{risk_id}" if risk_id is not None else "-"

        row = [
            urs_label,
            _cell(requirement_text, styles, "TableCellTiny"),
            _cell(remark_text, styles, "TableCellTiny"),
            "Yes" if is_gxp else "No",
            "MUST" if is_must else "CAN",
            risk_id_label,
            _cell(risk_title, styles, "TableCellTiny"),
            safe_str(sev),
            safe_str(occ),
            safe_str(det),
            safe_str(quant),
            level_display,
            "Y" if mitigation_required else "N",
            solved_display,
        ]

        if solved_display != "YES":
            row.extend(["n/a"] * 9)
        else:
            # Look up DQ details from catalog
            dq_row = get_row_by_id(Tables.DQ, dq_id) if dq_id else None
            dq_description = safe_str((dq_row or {}).get("description", ""))

            # Get mitigation proof (file_path from mitigation table)
            mitigation_id = _int_or_none(req.get("mitigation_id"))
            mitigation_row = get_row_by_id(Tables.MITIGATION, mitigation_id) if mitigation_id else None
            mitigation_proof = safe_str((mitigation_row or {}).get("file_path", ""))

            sev_after, occ_after, det_after, quant_after, level_after = _risk_after_values(req)
            level_after_display = level_after.upper() if level_after else ""
            row.extend([
                dq_id_display,
                _cell(dq_description, styles, "TableCellTiny"),
                _cell(mitigation_proof, styles, "TableCellTiny"),
                safe_str(sev_after),
                safe_str(occ_after),
                safe_str(det_after),
                safe_str(quant_after),
                level_after_display,
                _cell(req.get("dq_remark", ""), styles, "TableCellTiny"),
            ])

        table_data.append(row)

    table = Table(table_data, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (4, 0), colors.HexColor("#2E86AB")),
        ("BACKGROUND", (5, 0), (12, 0), colors.HexColor("#E8A838")),
        ("BACKGROUND", (13, 0), (22, 0), colors.HexColor("#4CAF50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE", (0, 0), (-1, 0), 6),
        ("FONTSIZE", (0, 1), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
        ("TOPPADDING", (0, 0), (-1, 0), 4),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
    ]))

    elements.append(table)
    return elements


def create_xq_plan_risk_matrix_section(
    requirements: List[Dict[str, Any]],
    styles,
    layout: LayoutSpec,
) -> List:
    """Create risk matrix section with 3 matrices: Before / After DQ / After xQ."""
    elements: List[Any] = []
    elements.append(Paragraph("Risk Matrix", styles["ChapterTitle"]))
    elements.append(Spacer(1, 0.2 * cm))

    if not requirements:
        elements.append(Paragraph("No risk assignments found.", styles["Normal"]))
        elements.append(PageBreak())
        return elements

    # Deduplicate
    seen: set = set()
    deduped: List[Dict[str, Any]] = []
    for entry in requirements:
        urs_id = _int_or_none(entry.get("requirement_id"))
        risk_id = _int_or_none(entry.get("risk_id"))
        if urs_id is None or risk_id is None:
            continue
        asset_id = _int_or_none(entry.get("asset_id"))
        key = (asset_id, urs_id, risk_id) if asset_id is not None else (urs_id, risk_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)

    before_rows: List[tuple[Optional[int], Optional[int], Optional[int]]] = []
    after_dq_rows: List[tuple[Optional[int], Optional[int], Optional[int]]] = []
    after_xq_rows: List[tuple[Optional[int], Optional[int], Optional[int]]] = []

    for entry in deduped:
        sev_before, occ_before, det_before, _, _ = _risk_before_values(entry)
        before_rows.append((sev_before, occ_before, det_before))

        dq_id = _int_or_none(entry.get("dq_id"))
        xq_id = _int_or_none(entry.get("xq_id"))

        # After DQ -- use DQ after-values whenever a DQ is assigned
        if dq_id is not None:
            dq_vals = get_after_mitigation_values(dq_id, is_xq=False)
            sev_dq = _int_or_none(dq_vals.get("severity_after_mitigation"))
            occ_dq = _int_or_none(dq_vals.get("likelihood_after_mitigation"))
            det_dq = _int_or_none(dq_vals.get("detectability_after_mitigation"))
            if sev_dq is not None and occ_dq is not None and det_dq is not None:
                after_dq_rows.append((sev_dq, occ_dq, det_dq))
            else:
                after_dq_rows.append((sev_before, occ_before, det_before))
        else:
            after_dq_rows.append((sev_before, occ_before, det_before))

        # After xQ -- use the full after-values (DQ or XQ, whichever applies)
        sev_after, occ_after, det_after, _, _ = _risk_after_values(entry)
        has_after = sev_after is not None and occ_after is not None and det_after is not None
        has_mitigation = dq_id is not None or xq_id is not None
        if has_mitigation and has_after:
            after_xq_rows.append((sev_after, occ_after, det_after))
        else:
            after_xq_rows.append((sev_before, occ_before, det_before))

    before_counts = _build_risk_matrix_counts(before_rows)
    after_dq_counts = _build_risk_matrix_counts(after_dq_rows)
    after_xq_counts = _build_risk_matrix_counts(after_xq_rows)

    elements.append(Paragraph("Before Mitigation", styles["SectionTitle"]))
    elements.append(Spacer(1, 0.2 * cm))
    elements.append(_build_risk_matrix_table(before_counts, styles, layout))
    elements.append(Spacer(1, 0.5 * cm))
    elements.append(Paragraph("After DQ Mitigation", styles["SectionTitle"]))
    elements.append(Spacer(1, 0.2 * cm))
    elements.append(_build_risk_matrix_table(after_dq_counts, styles, layout))
    elements.append(Spacer(1, 0.5 * cm))
    elements.append(Paragraph("After xQ Mitigation", styles["SectionTitle"]))
    elements.append(Spacer(1, 0.2 * cm))
    elements.append(_build_risk_matrix_table(after_xq_counts, styles, layout))
    elements.append(PageBreak())
    return elements


def create_xq_plan_table(
    requirements: List[Dict[str, Any]],
    xq_catalog_map: Dict[int, Dict[str, Any]],
    xq_after_map: Dict[int, Dict[str, Any]],
    styles,
    layout: LayoutSpec,
) -> List:
    """Create full 26-column xQ Plan table matching the Qualification Plan page layout."""
    elements: List[Any] = []

    if not requirements:
        elements.append(Paragraph("No xQ assignments found.", styles["Normal"]))
        return elements

    def _sort_key(entry: Dict[str, Any]) -> tuple[int, int]:
        urs_id = _int_or_none(entry.get("requirement_id")) or 0
        risk_id = _int_or_none(entry.get("risk_id")) or 0
        return (urs_id, risk_id)

    sorted_requirements = sorted(requirements, key=_sort_key)

    headers = [
        Paragraph("ID", styles["TableHeaderTiny"]),
        Paragraph("Requirement", styles["TableHeaderTiny"]),
        Paragraph("Remark", styles["TableHeaderTiny"]),
        Paragraph("GxP", styles["TableHeaderTiny"]),
        Paragraph("Must-<br/>Have", styles["TableHeaderTiny"]),
        Paragraph("Risk-ID", styles["TableHeaderTiny"]),
        Paragraph("Risk Title", styles["TableHeaderTiny"]),
        Paragraph("S<br/>(before)", styles["TableHeaderTiny"]),
        Paragraph("O<br/>(before)", styles["TableHeaderTiny"]),
        Paragraph("D<br/>(before)", styles["TableHeaderTiny"]),
        Paragraph("RPN<br/>(before)", styles["TableHeaderTiny"]),
        Paragraph("Level<br/>(before)", styles["TableHeaderTiny"]),
        Paragraph("Miti-<br/>gation", styles["TableHeaderTiny"]),
        Paragraph("Solved<br/>by DQ", styles["TableHeaderTiny"]),
        Paragraph("Solved<br/>by xQ?", styles["TableHeaderTiny"]),
        Paragraph("xQ-ID", styles["TableHeaderTiny"]),
        Paragraph("xQ Desc.", styles["TableHeaderTiny"]),
        Paragraph("xQ Purpose", styles["TableHeaderTiny"]),
        Paragraph("xQ Input", styles["TableHeaderTiny"]),
        Paragraph("xQ Exp.<br/>Output", styles["TableHeaderTiny"]),
        Paragraph("S<br/>(after)", styles["TableHeaderTiny"]),
        Paragraph("O<br/>(after)", styles["TableHeaderTiny"]),
        Paragraph("D<br/>(after)", styles["TableHeaderTiny"]),
        Paragraph("RPN<br/>(after)", styles["TableHeaderTiny"]),
        Paragraph("Level<br/>(after)", styles["TableHeaderTiny"]),
        Paragraph("xQ Rem.", styles["TableHeaderTiny"]),
    ]

    weights = [
        1, 3.5, 1.5, 1, 1.5,
        1.5, 2.5, 1, 1, 1, 1, 1.5, 1.2,
        1.4,
        1.2, 1.1, 2.5, 2, 2, 2, 1, 1, 1, 1, 1.5, 1.5,
    ]
    total_weight = sum(weights)
    fractions = [w / total_weight for w in weights]
    col_widths = _widths_from_fractions(layout, fractions)

    table_data = [headers]

    for req in sorted_requirements:
        urs_id = _int_or_none(req.get("requirement_id"))
        risk_id = _int_or_none(req.get("risk_id"))

        # Look up requirement details from catalog
        req_row = get_row_by_id(Tables.REQUIREMENT, urs_id) if urs_id else None
        requirement_text = safe_str((req_row or {}).get("description", req.get("description", "")))
        remark_text = safe_str(req.get("requirement_remark", ""))
        is_gxp = excel_to_bool((req_row or {}).get("is_gxp", req.get("is_gxp")))
        is_must = excel_to_bool((req_row or {}).get("is_must", req.get("is_must")))

        # Look up risk details from catalog
        risk_row = get_row_by_id(Tables.RISK, risk_id) if risk_id else None
        risk_title = safe_str((risk_row or {}).get("possible_error", req.get("possible_error", "")))

        sev, occ, det, quant, level = _risk_before_values(req)
        level_display = level.upper() if level else ""
        mitigation_required = level in ("high", "medium")
        if not level and "mitigation_required" in req:
            mitigation_required = excel_to_bool(req.get("mitigation_required"))

        # Solved by DQ? Check dq_id directly (new schema: FK integer)
        dq_id = _int_or_none(req.get("dq_id"))
        solved_by_dq = dq_id is not None

        if not mitigation_required:
            solved_display = "n/a"
        elif solved_by_dq:
            solved_display = f"DQ-{dq_id}" if dq_id else "YES"
        else:
            solved_display = "NO"

        urs_label = f"URS-{urs_id}" if urs_id is not None else "-"
        risk_id_label = f"Risk-{risk_id}" if risk_id is not None else "-"

        # Solved by xQ?
        xq_id = _int_or_none(req.get("xq_id"))
        has_xq = xq_id is not None

        if not mitigation_required:
            solved_by_xq_display = "n/a"
        elif has_xq:
            solved_by_xq_display = "YES"
        else:
            solved_by_xq_display = "NO"

        row = [
            urs_label,
            _cell(requirement_text, styles, "TableCellTiny"),
            _cell(remark_text, styles, "TableCellTiny"),
            "Yes" if is_gxp else "No",
            "MUST" if is_must else "CAN",
            risk_id_label,
            _cell(risk_title, styles, "TableCellTiny"),
            safe_str(sev),
            safe_str(occ),
            safe_str(det),
            safe_str(quant),
            level_display,
            "Y" if mitigation_required else "N",
            solved_display,
            solved_by_xq_display,
        ]

        # xQ columns (15-25): filled whenever xQ is assigned (regardless of DQ)
        if not mitigation_required or not has_xq:
            row.extend(["n/a"] * 11)
        else:
            # Look up XQ details from catalog or xq_catalog_map
            xq_data = xq_catalog_map.get(xq_id, {})
            if not xq_data:
                xq_data = get_row_by_id(Tables.XQ, xq_id) or {}
            xq_id_label = f"xQ-{xq_id}"
            xq_desc = safe_str(xq_data.get("description", ""))
            xq_purpose = safe_str(xq_data.get("purpose", ""))
            xq_input_val = safe_str(xq_data.get("input", ""))
            xq_expected = safe_str(xq_data.get("expected_output", ""))

            # After xQ values from xq_after_map or via lookup
            after_fields = xq_after_map.get(xq_id, {})
            if not after_fields:
                after_fields = get_after_mitigation_values(xq_id, is_xq=True)
            sev_after = after_fields.get("severity_after_mitigation")
            occ_after = after_fields.get("likelihood_after_mitigation")
            det_after = after_fields.get("detectability_after_mitigation")
            quant_after = after_fields.get("quantification_after_mitigation")
            level_after = safe_str(after_fields.get("risk_level_after_mitigation", ""))

            if quant_after is None and sev_after and occ_after and det_after:
                quant_after = calculate_quantification(sev_after, occ_after, det_after)
            if not level_after and quant_after is not None:
                level_after = calculate_risk_level(quant_after)

            row.extend([
                xq_id_label,
                _cell(xq_desc, styles, "TableCellTiny"),
                _cell(xq_purpose, styles, "TableCellTiny"),
                _cell(xq_input_val, styles, "TableCellTiny"),
                _cell(xq_expected, styles, "TableCellTiny"),
                safe_str(sev_after),
                safe_str(occ_after),
                safe_str(det_after),
                safe_str(quant_after),
                level_after.upper() if level_after else "",
                _cell(safe_str(req.get("xq_remark", "")), styles, "TableCellTiny"),
            ])

        table_data.append(row)

    table = Table(table_data, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        # URS columns (0-4): blue
        ("BACKGROUND", (0, 0), (4, 0), colors.HexColor("#2E86AB")),
        # Risk columns (5-12): yellow/orange
        ("BACKGROUND", (5, 0), (12, 0), colors.HexColor("#E8A838")),
        # Solved by DQ (13): green
        ("BACKGROUND", (13, 0), (13, 0), colors.HexColor("#4CAF50")),
        # xQ columns (14-25): purple
        ("BACKGROUND", (14, 0), (25, 0), colors.HexColor("#7B1FA2")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE", (0, 0), (-1, 0), 6),
        ("FONTSIZE", (0, 1), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
        ("TOPPADDING", (0, 0), (-1, 0), 4),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
    ]))

    elements.append(table)
    return elements


def create_xq_table(xq_items: List[Dict[str, Any]], styles, layout: LayoutSpec, include_results: bool = False) -> List:
    """Create a qualification plan/execution table."""
    elements: List[Any] = []

    if not xq_items:
        elements.append(Paragraph("No qualification tests found.", styles["Normal"]))
        return elements

    headers = ["URS", "Test", "Input", "Expected Output"]
    fractions = [0.08, 0.30, 0.25, 0.37]

    if include_results:
        headers.extend(["Output", "Status"])
        fractions = [0.07, 0.25, 0.20, 0.23, 0.15, 0.10]

    col_widths = _widths_from_fractions(layout, fractions)

    table_data = [headers]

    for item in xq_items:
        # Look up XQ details from catalog
        xq_id = _int_or_none(item.get("xq_id"))
        xq_row = get_row_by_id(Tables.XQ, xq_id) if xq_id else None
        xq_desc = safe_str((xq_row or {}).get("description", item.get("description", "")))[:60]
        xq_input_val = safe_str((xq_row or {}).get("input", item.get("input", "")))[:60]
        xq_expected = safe_str((xq_row or {}).get("expected_output", item.get("expected_output", "")))[:60]

        row = [
            safe_str(item.get("requirement_id", "")),
            xq_desc,
            xq_input_val,
            xq_expected,
        ]

        if include_results:
            row.append(safe_str(item.get("xq_output", ""))[:60])
            passed = item.get("passed", item.get("xq_passed"))
            if passed == "TRUE" or passed is True:
                row.append("PASS")
            elif passed == "FALSE" or passed is False:
                row.append("FAIL")
            else:
                row.append("-")

        table_data.append(row)

    table = Table(table_data, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3A7D44")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5FFF5")]),
    ]))

    elements.append(table)
    return elements


def create_appendix_urls(urls: List[str], styles) -> List:
    """Create appendix section with URL list."""
    elements: List[Any] = []

    if not urls:
        elements.append(Paragraph("No appendices found.", styles["Normal"]))
        return elements

    elements.append(Paragraph("Appendices / References:", styles["SectionTitle"]))

    url_items = []
    for i, url in enumerate(urls, 1):
        url_items.append(ListItem(Paragraph(f"{i}. {url}", styles["Normal"])))

    elements.append(ListFlowable(url_items, bulletType="bullet"))

    return elements


def create_document_history_table(
    asset_id: int,
    current_doc_type: str,
    styles,
    layout: "LayoutSpec",
) -> List:
    """
    Create a document history table for the appendix showing all document versions.

    Args:
        asset_id: The asset ID to get document history for
        current_doc_type: The current document type being generated
        styles: ReportLab styles
        layout: Layout specification for column widths

    Returns:
        List of ReportLab elements for the document history table
    """
    import pandas as pd

    elements: List[Any] = []

    # Phase order and display names
    PHASE_ORDER = ["URS", "FMEA", "DQ", "XQ_PLAN", "QUAL_REPORT"]
    PHASE_DISPLAY_NAMES = {
        "URS": "URS",
        "FMEA": "Risk Assignment",
        "DQ": "DQ",
        "XQ_PLAN": "XQ Plan",
        "QUAL_REPORT": "XQ Execution",
    }

    PHASE_DOC_ALIASES = {
        "FMEA": ["FMEA", "RISK"],
        "QUAL_REPORT": ["QUAL_REPORT", "XQ_EXECUTION"],
    }

    # Color coding for each phase header (matching the app styling)
    PHASE_COLORS = {
        "URS": colors.HexColor("#2E86AB"),        # Blue
        "FMEA": colors.HexColor("#E8A838"),       # Yellow/Orange
        "DQ": colors.HexColor("#4CAF50"),         # Green
        "XQ_PLAN": colors.HexColor("#7B1FA2"),    # Purple
        "QUAL_REPORT": colors.HexColor("#F44336"), # Red
    }

    # Resolve main asset ID and project ID
    main_asset_id = get_main_asset_id_for(asset_id)
    main_asset = get_row_by_id(Tables.ASSET, main_asset_id)
    project_id = _int_or_none((main_asset or {}).get("project_id"))
    if project_id is None:
        elements.append(Paragraph("No document history found.", styles["Normal"]))
        return elements

    # Load document and document_version data
    doc_df = load_table(Tables.DOCUMENT)
    ver_df = load_table(Tables.DOCUMENT_VERSION)
    if doc_df.empty or ver_df.empty:
        elements.append(Paragraph("No document history found.", styles["Normal"]))
        return elements

    # Filter documents for this project
    asset_docs = doc_df[doc_df["project_id"] == project_id].copy()
    if asset_docs.empty:
        elements.append(Paragraph("No document history found.", styles["Normal"]))
        return elements

    # Join document with document_version (do NOT include document-level approved_at
    # as it applies to the whole document, not individual versions)
    doc_cols = ["id", "document_type_id", "status"]
    merged = ver_df.merge(asset_docs[doc_cols], left_on="document_id", right_on="id", how="inner", suffixes=("", "_doc"))
    if merged.empty:
        elements.append(Paragraph("No document history found.", styles["Normal"]))
        return elements

    # Resolve document_type names
    doc_type_df = load_table(Tables.DOCUMENT_TYPE)
    if not doc_type_df.empty:
        doc_type_map = {}
        for _, dt_row in doc_type_df.iterrows():
            doc_type_map[int(dt_row["id"])] = safe_str(dt_row.get("name", "")).strip().upper()
        merged["document_type_norm"] = merged["document_type_id"].apply(
            lambda v: doc_type_map.get(_int_or_none(v), "")
        )
    else:
        merged["document_type_norm"] = ""

    # Get all unique versions and sort them
    def parse_version(v):
        if pd.isna(v) or not v:
            return 0
        try:
            return int(v)
        except (TypeError, ValueError):
            v_str = str(v).strip().upper()
            if v_str.startswith("V"):
                try:
                    return int(v_str[1:])
                except ValueError:
                    return 0
            return 0

    # Use version_no from document_version table
    version_col = "version_no" if "version_no" in merged.columns else "version"
    merged["version_num"] = merged[version_col].apply(parse_version)
    versions = sorted(merged["version_num"].unique())
    versions = [v for v in versions if v > 0]

    if not versions:
        elements.append(Paragraph("No document history found.", styles["Normal"]))
        return elements

    # Build the table data
    # Headers: Version, URS, Risk Assignment, DQ, XQ Plan, XQ Execution
    headers = ["Version"] + [PHASE_DISPLAY_NAMES[p] for p in PHASE_ORDER]

    # Column widths: Version column + 5 phase columns
    col_fractions = [0.10, 0.18, 0.18, 0.18, 0.18, 0.18]
    col_widths = [layout.content_width * f for f in col_fractions]

    table_data = [headers]

    # Build rows for each version
    for version_num in versions:
        version_str = f"V{version_num:02d}"
        row = [version_str]

        for phase in PHASE_ORDER:
            # Find the document entry for this version and phase
            phase_docs = merged[
                (merged["version_num"] == version_num) &
                merged["document_type_norm"].isin(PHASE_DOC_ALIASES.get(phase, [phase]))
            ]

            if phase_docs.empty:
                row.append("")
            else:
                # Get the latest entry for this version/phase combination
                doc = phase_docs.iloc[-1]
                created = safe_str(doc.get("created_at", doc.get("document_creation_timestamp", "")))

                approved = safe_str(doc.get("approved_at", ""))
                rejected = safe_str(doc.get("rejected_at", ""))

                def _clean_ts(ts: str) -> str:
                    if ts and "T" in ts:
                        return ts.split(".")[0]
                    return ts

                # Format timestamps
                cell_content = ""
                if created:
                    cell_content = f"created: {_clean_ts(created)}"

                # If rejected, show "rejected" and never show "approved"
                if rejected:
                    if cell_content:
                        cell_content += f"\nrejected: {_clean_ts(rejected)}"
                    else:
                        cell_content = f"rejected: {_clean_ts(rejected)}"
                elif approved:
                    if cell_content:
                        cell_content += f"\napproved: {_clean_ts(approved)}"
                    else:
                        cell_content = f"approved: {_clean_ts(approved)}"

                row.append(cell_content)

        table_data.append(row)

    # Create the table
    table = Table(table_data, colWidths=col_widths, repeatRows=1, hAlign="LEFT")

    # Build style commands
    style_commands = [
        # Header row styling - Version column (no background, just bold)
        ("FONTNAME", (0, 0), (0, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (0, 0), 7),
        ("TEXTCOLOR", (0, 0), (0, 0), colors.black),
        ("ALIGN", (0, 0), (0, 0), "CENTER"),

        # Phase column headers with colors
        ("FONTNAME", (1, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (1, 0), (-1, 0), 7),
        ("TEXTCOLOR", (1, 0), (-1, 0), colors.white),
        ("ALIGN", (1, 0), (-1, 0), "CENTER"),

        # Individual phase header backgrounds
        ("BACKGROUND", (1, 0), (1, 0), PHASE_COLORS["URS"]),
        ("BACKGROUND", (2, 0), (2, 0), PHASE_COLORS["FMEA"]),
        ("BACKGROUND", (3, 0), (3, 0), PHASE_COLORS["DQ"]),
        ("BACKGROUND", (4, 0), (4, 0), PHASE_COLORS["XQ_PLAN"]),
        ("BACKGROUND", (5, 0), (5, 0), PHASE_COLORS["QUAL_REPORT"]),

        # Data cells styling
        ("FONTSIZE", (0, 1), (-1, -1), 7),
        ("ALIGN", (0, 1), (0, -1), "CENTER"),  # Version column centered
        ("ALIGN", (1, 1), (-1, -1), "LEFT"),   # Data columns left-aligned
        ("VALIGN", (0, 0), (-1, -1), "TOP"),

        # Grid and padding
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),

        # White background for data rows
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
    ]

    # Add horizontal lines between version rows (thicker line after each row)
    for row_idx in range(1, len(table_data)):
        style_commands.append(("LINEBELOW", (0, row_idx), (-1, row_idx), 1, colors.black))

    table.setStyle(TableStyle(style_commands))

    elements.append(Paragraph("Document History:", styles["SectionTitle"]))
    elements.append(Spacer(1, 0.3 * cm))
    elements.append(table)

    return elements


def render_document(
    doc_type: DocType,
    context: Dict[str, Any],
    out_path: Optional[str] = None,
    approved: bool = False,
) -> str:
    """
    Render a PDF document.

    Args:
        doc_type: Type of document (URS, FS, FMEA, XQ_PLAN, QUAL_REPORT)
        context: Dictionary with document data
        out_path: Optional output path. If None, generates automatically.
        approved: If True, append _approved to the filename when auto-generating.

    Returns:
        Path to the generated PDF file.
    """
    styles = get_styles()
    layout = LayoutSpec()

    if out_path is None:
        output_dir = ensure_output_dir()
        filename_prefix = DOC_TYPE_FILENAMES.get(doc_type, doc_type)
        filename = generate_pdf_filename(
            filename_prefix,
            context.get("asset_name", "Unknown"),
            context.get("document_version") or context.get("version", "V01"),
            approved=approved,
        )
        out_path = str(output_dir / filename)

    doc = SimpleDocTemplate(
        out_path,
        pagesize=layout.pagesize,
        rightMargin=layout.right_margin,
        leftMargin=layout.left_margin,
        topMargin=layout.top_margin,
        bottomMargin=layout.bottom_margin,
    )

    elements: List[Any] = []
    elements.extend(create_title_page(context, doc_type, styles, layout))

    if doc_type == "URS":
        elements.extend(_build_urs_document(context, styles, layout))
    elif doc_type == "FS":
        elements.extend(_build_fs_document(context, styles, layout))
    elif doc_type == "DQ":
        elements.extend(_build_dq_document(context, styles, layout))
    elif doc_type == "FMEA":
        elements.extend(_build_fmea_document(context, styles, layout))
    elif doc_type == "XQ_PLAN":
        elements.extend(_build_xq_plan_document(context, styles, layout))
    elif doc_type == "QUAL_REPORT":
        elements.extend(_build_qual_report_document(context, styles, layout))

    header_context = {
        "file_name": Path(out_path).name,
        "file_path": str(Path(out_path).parent),
        "company_name": COMPANY_NAME,
        "layout": layout,
    }
    export_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    footer_context = {"footer_text": FOOTER_TEXT, "export_timestamp": f"Exported: {export_timestamp}"}

    def canvas_maker(*args, **kwargs):
        return NumberedCanvas(*args, header_context=header_context, footer_context=footer_context, **kwargs)

    doc.build(elements, canvasmaker=canvas_maker)

    return out_path


def _build_urs_document(context: Dict[str, Any], styles, layout: LayoutSpec) -> List:
    """Build URS document content."""
    elements: List[Any] = []

    main_reqs = context.get("main_requirements", [])
    peripherals = context.get("peripherals", [])
    overview_rows = context.get("asset_overview_rows") or []

    main_equipment_type = ""
    peripheral_equipment_types: Dict[str, str] = {}
    for row in overview_rows:
        asset_type = safe_str(row.get("asset_type")).strip().lower()
        asset_name = safe_str(row.get("asset_name")).strip()
        equipment_type = safe_str(row.get("equipment_type")).strip()
        if asset_type == "main" and not main_equipment_type:
            main_equipment_type = equipment_type
        if asset_type == "peripheral" and asset_name and equipment_type:
            peripheral_equipment_types[asset_name] = equipment_type

    main_description = safe_str(context.get("asset_name")).strip() or "N/A"
    main_equipment_type = safe_str(context.get("equipment_type") or main_equipment_type).strip() or "N/A"
    main_title = f"Main Asset Requirements: {main_description} ({main_equipment_type})"

    peripheral_chapters = []
    for peripheral in peripherals:
        peripheral_name_raw = safe_str(peripheral.get("name")).strip()
        peripheral_name = peripheral_name_raw or "N/A"
        peripheral_equipment_type = safe_str(
            peripheral.get("equipment_type") or peripheral_equipment_types.get(peripheral_name_raw)
        ).strip() or "N/A"
        peripheral_title = f"Peripheral Asset Requirements: {peripheral_name} ({peripheral_equipment_type})"
        peripheral_chapters.append({
            "title": peripheral_title,
            "requirements": peripheral.get("requirements", []),
        })

    sections = ["General Terms and Conditions", main_title]
    sections.extend([chapter["title"] for chapter in peripheral_chapters])
    sections.append("Appendices")
    elements.extend(create_toc(sections, styles))
    elements.extend(create_location_plan_section(context, styles, layout))
    elements.extend(create_medien_section(context, styles, layout))
    elements.extend(create_terms_and_conditions_page(context, styles))

    elements.append(Paragraph(main_title, styles["ChapterTitle"]))

    _sc_id_map = _build_subchapter_id_map()

    def append_subchapters(requirements: List[Dict[str, Any]]) -> None:
        for subchapter in Subchapter:
            chapter_reqs = [r for r in requirements if _int_or_none(r.get("subchapter_id")) == _sc_id_map.get(subchapter.value)]
            if chapter_reqs:
                label = SUBCHAPTER_LABELS.get(subchapter, subchapter.value)
                elements.append(Paragraph(label, styles["SectionTitle"]))
                elements.extend(create_urs_requirements_table(chapter_reqs, styles, layout))
                elements.append(Spacer(1, 0.4 * cm))

    append_subchapters(main_reqs)

    if peripheral_chapters:
        elements.append(PageBreak())
        for idx, chapter in enumerate(peripheral_chapters):
            if idx > 0:
                elements.append(PageBreak())
            elements.append(Paragraph(chapter["title"], styles["ChapterTitle"]))
            append_subchapters(chapter["requirements"])

    elements.append(PageBreak())
    elements.append(Paragraph("Appendices", styles["ChapterTitle"]))
    elements.extend(create_appendix_urls(context.get("appendix_urls", []), styles))

    return elements


def _build_fs_document(context: Dict[str, Any], styles, layout: LayoutSpec) -> List:
    """Build FS document -- same as URS but with an extra empty 'FS' column in requirement tables."""
    elements: List[Any] = []

    main_reqs = context.get("main_requirements", [])
    peripherals = context.get("peripherals", [])
    overview_rows = context.get("asset_overview_rows") or []

    main_equipment_type = ""
    peripheral_equipment_types: Dict[str, str] = {}
    for row in overview_rows:
        asset_type = safe_str(row.get("asset_type")).strip().lower()
        asset_name = safe_str(row.get("asset_name")).strip()
        equipment_type = safe_str(row.get("equipment_type")).strip()
        if asset_type == "main" and not main_equipment_type:
            main_equipment_type = equipment_type
        if asset_type == "peripheral" and asset_name and equipment_type:
            peripheral_equipment_types[asset_name] = equipment_type

    main_description = safe_str(context.get("asset_name")).strip() or "N/A"
    main_equipment_type = safe_str(context.get("equipment_type") or main_equipment_type).strip() or "N/A"
    main_title = f"Main Asset Requirements: {main_description} ({main_equipment_type})"

    peripheral_chapters = []
    for peripheral in peripherals:
        peripheral_name_raw = safe_str(peripheral.get("name")).strip()
        peripheral_name = peripheral_name_raw or "N/A"
        peripheral_equipment_type = safe_str(
            peripheral.get("equipment_type") or peripheral_equipment_types.get(peripheral_name_raw)
        ).strip() or "N/A"
        peripheral_title = f"Peripheral Asset Requirements: {peripheral_name} ({peripheral_equipment_type})"
        peripheral_chapters.append({
            "title": peripheral_title,
            "requirements": peripheral.get("requirements", []),
        })

    sections = ["General Terms and Conditions", main_title]
    sections.extend([chapter["title"] for chapter in peripheral_chapters])
    sections.append("Appendices")
    elements.extend(create_toc(sections, styles))
    elements.extend(create_location_plan_section(context, styles, layout))
    elements.extend(create_medien_section(context, styles, layout))
    elements.extend(create_terms_and_conditions_page(context, styles))

    elements.append(Paragraph(main_title, styles["ChapterTitle"]))

    _sc_id_map = _build_subchapter_id_map()

    def append_subchapters(requirements: List[Dict[str, Any]]) -> None:
        for subchapter in Subchapter:
            chapter_reqs = [r for r in requirements if _int_or_none(r.get("subchapter_id")) == _sc_id_map.get(subchapter.value)]
            if chapter_reqs:
                label = SUBCHAPTER_LABELS.get(subchapter, subchapter.value)
                elements.append(Paragraph(label, styles["SectionTitle"]))
                elements.extend(create_fs_requirements_table(chapter_reqs, styles, layout))
                elements.append(Spacer(1, 0.4 * cm))

    append_subchapters(main_reqs)

    if peripheral_chapters:
        elements.append(PageBreak())
        for idx, chapter in enumerate(peripheral_chapters):
            if idx > 0:
                elements.append(PageBreak())
            elements.append(Paragraph(chapter["title"], styles["ChapterTitle"]))
            append_subchapters(chapter["requirements"])

    elements.append(PageBreak())
    elements.append(Paragraph("Appendices", styles["ChapterTitle"]))
    elements.extend(create_appendix_urls(context.get("appendix_urls", []), styles))

    return elements


def _build_dq_document(context: Dict[str, Any], styles, layout: LayoutSpec) -> List:
    """Build DQ document content."""
    elements: List[Any] = []

    main_reqs = context.get("main_requirements", []) or []
    peripherals = context.get("peripherals", []) or []
    if not main_reqs and not peripherals:
        main_reqs = context.get("requirements", []) or []

    overview_rows = context.get("asset_overview_rows") or []
    main_equipment_type = ""
    peripheral_equipment_types: Dict[str, str] = {}
    for row in overview_rows:
        asset_type = safe_str(row.get("asset_type")).strip().lower()
        asset_name = safe_str(row.get("asset_name")).strip()
        equipment_type = safe_str(row.get("equipment_type")).strip()
        if asset_type == "main" and not main_equipment_type:
            main_equipment_type = equipment_type
        if asset_type == "peripheral" and asset_name and equipment_type:
            peripheral_equipment_types[asset_name] = equipment_type

    main_description = safe_str(context.get("asset_name")).strip() or "N/A"
    main_equipment_type = safe_str(context.get("equipment_type") or main_equipment_type).strip() or "N/A"
    main_title = f"Main Asset Design Qualification: {main_description} ({main_equipment_type})"

    peripheral_chapters = []
    for peripheral in peripherals:
        peripheral_name_raw = safe_str(peripheral.get("name")).strip()
        peripheral_name = peripheral_name_raw or "N/A"
        peripheral_equipment_type = safe_str(
            peripheral.get("equipment_type") or peripheral_equipment_types.get(peripheral_name_raw)
        ).strip() or "N/A"
        peripheral_title = f"Peripheral Asset Design Qualification: {peripheral_name} ({peripheral_equipment_type})"
        peripheral_chapters.append({
            "title": peripheral_title,
            "requirements": peripheral.get("requirements", []),
        })

    all_requirements = list(main_reqs)
    for peripheral in peripherals:
        all_requirements.extend(peripheral.get("requirements", []))

    sections = ["Risk Matrix (Before/After DQ Mitigation)", main_title]
    sections.extend([chapter["title"] for chapter in peripheral_chapters])
    sections.append("Appendices")
    elements.extend(create_toc(sections, styles))
    elements.extend(create_location_plan_section(context, styles, layout))
    elements.extend(create_medien_section(context, styles, layout))
    elements.extend(create_dq_risk_matrix_section(all_requirements, styles, layout))

    elements.append(Paragraph(main_title, styles["ChapterTitle"]))

    _sc_id_map = _build_subchapter_id_map()

    def append_subchapters(requirements: List[Dict[str, Any]]) -> None:
        for subchapter in Subchapter:
            chapter_reqs = [r for r in requirements if _int_or_none(r.get("subchapter_id")) == _sc_id_map.get(subchapter.value)]
            if chapter_reqs:
                label = SUBCHAPTER_LABELS.get(subchapter, subchapter.value)
                elements.append(Paragraph(label, styles["SectionTitle"]))
                elements.extend(create_dq_table(chapter_reqs, styles, layout))
                elements.append(Spacer(1, 0.4 * cm))

    append_subchapters(main_reqs)

    if peripheral_chapters:
        elements.append(PageBreak())
        for idx, chapter in enumerate(peripheral_chapters):
            if idx > 0:
                elements.append(PageBreak())
            elements.append(Paragraph(chapter["title"], styles["ChapterTitle"]))
            append_subchapters(chapter["requirements"])

    elements.append(PageBreak())
    elements.append(Paragraph("Appendices", styles["ChapterTitle"]))
    elements.extend(create_appendix_urls(context.get("appendix_urls", []), styles))

    return elements


def _build_fmea_document(context: Dict[str, Any], styles, layout: LayoutSpec) -> List:
    """Build Risk Assignment document content."""
    elements: List[Any] = []

    main_risks = context.get("main_risks", [])
    peripherals = context.get("peripherals", [])
    overview_rows = context.get("asset_overview_rows") or []

    # Build all risks for the risk matrix
    all_risks = list(main_risks)
    for peripheral in peripherals:
        all_risks.extend(peripheral.get("risks", []))

    # Determine main equipment type from overview rows
    main_equipment_type = ""
    peripheral_equipment_types: Dict[str, str] = {}
    for row in overview_rows:
        asset_type = safe_str(row.get("asset_type")).strip().lower()
        asset_name = safe_str(row.get("asset_name")).strip()
        equipment_type = safe_str(row.get("equipment_type")).strip()
        if asset_type == "main" and not main_equipment_type:
            main_equipment_type = equipment_type
        if asset_type == "peripheral" and asset_name and equipment_type:
            peripheral_equipment_types[asset_name] = equipment_type

    main_description = safe_str(context.get("asset_name")).strip() or "N/A"
    main_equipment_type = safe_str(context.get("equipment_type") or main_equipment_type).strip() or "N/A"
    main_title = f"Main Asset Risk Assignment: {main_description} ({main_equipment_type})"

    # Build peripheral chapter titles
    peripheral_chapters = []
    for peripheral in peripherals:
        peripheral_name_raw = safe_str(peripheral.get("name")).strip()
        peripheral_name = peripheral_name_raw or "N/A"
        peripheral_equipment_type = safe_str(
            peripheral.get("equipment_type") or peripheral_equipment_types.get(peripheral_name_raw)
        ).strip() or "N/A"
        peripheral_title = f"Peripheral Asset Risk Assignment: {peripheral_name} ({peripheral_equipment_type})"
        peripheral_chapters.append({
            "title": peripheral_title,
            "risks": peripheral.get("risks", []),
        })

    # Build TOC
    sections = ["Risk Matrix (Before Mitigation)", main_title]
    sections.extend([chapter["title"] for chapter in peripheral_chapters])
    sections.append("Appendices")
    elements.extend(create_toc(sections, styles))
    elements.extend(create_location_plan_section(context, styles, layout))
    elements.extend(create_medien_section(context, styles, layout))

    # Risk Matrix section
    elements.extend(create_risk_matrix_section(all_risks, styles, layout))

    # Main Asset Risk Assignment section
    elements.append(Paragraph(main_title, styles["ChapterTitle"]))

    _sc_id_map = _build_subchapter_id_map()

    def append_subchapters(risks_list: List[Dict[str, Any]]) -> None:
        for subchapter in Subchapter:
            chapter_reqs = [r for r in risks_list if _int_or_none(r.get("subchapter_id")) == _sc_id_map.get(subchapter.value)]
            if chapter_reqs:
                label = SUBCHAPTER_LABELS.get(subchapter, subchapter.value)
                elements.append(Paragraph(label, styles["SectionTitle"]))
                elements.extend(create_risk_assignment_table(chapter_reqs, styles, layout))
                elements.append(Spacer(1, 0.4 * cm))

    append_subchapters(main_risks)

    # Peripheral Asset Risk Assignment sections
    if peripheral_chapters:
        elements.append(PageBreak())
        for idx, chapter in enumerate(peripheral_chapters):
            if idx > 0:
                elements.append(PageBreak())
            elements.append(Paragraph(chapter["title"], styles["ChapterTitle"]))
            append_subchapters(chapter["risks"])

    elements.append(PageBreak())
    elements.append(Paragraph("Appendices", styles["ChapterTitle"]))
    elements.extend(create_appendix_urls(context.get("appendix_urls", []), styles))

    return elements


def _build_xq_plan_document(context: Dict[str, Any], styles, layout: LayoutSpec) -> List:
    """Build Qualification Plan document content."""
    elements: List[Any] = []

    main_reqs = context.get("main_requirements", []) or []
    peripherals = context.get("peripherals", []) or []
    if not main_reqs and not peripherals:
        main_reqs = context.get("requirements", []) or []

    xq_catalog_map = context.get("xq_catalog_map", {})
    xq_after_map = context.get("xq_after_map", {})

    overview_rows = context.get("asset_overview_rows") or []
    main_equipment_type = ""
    peripheral_equipment_types: Dict[str, str] = {}
    for row in overview_rows:
        asset_type = safe_str(row.get("asset_type")).strip().lower()
        asset_name = safe_str(row.get("asset_name")).strip()
        equipment_type = safe_str(row.get("equipment_type")).strip()
        if asset_type == "main" and not main_equipment_type:
            main_equipment_type = equipment_type
        if asset_type == "peripheral" and asset_name and equipment_type:
            peripheral_equipment_types[asset_name] = equipment_type

    main_description = safe_str(context.get("asset_name")).strip() or "N/A"
    main_equipment_type = safe_str(context.get("equipment_type") or main_equipment_type).strip() or "N/A"
    main_title = f"Main Asset Qualification Plan: {main_description} ({main_equipment_type})"

    peripheral_chapters = []
    for peripheral in peripherals:
        peripheral_name_raw = safe_str(peripheral.get("name")).strip()
        peripheral_name = peripheral_name_raw or "N/A"
        peripheral_equipment_type = safe_str(
            peripheral.get("equipment_type") or peripheral_equipment_types.get(peripheral_name_raw)
        ).strip() or "N/A"
        peripheral_title = f"Peripheral Asset Qualification Plan: {peripheral_name} ({peripheral_equipment_type})"
        peripheral_chapters.append({
            "title": peripheral_title,
            "requirements": peripheral.get("requirements", []),
        })

    all_requirements = list(main_reqs)
    for peripheral in peripherals:
        all_requirements.extend(peripheral.get("requirements", []))

    sections = ["Risk Matrix (Before/After DQ/After xQ Mitigation)", main_title]
    sections.extend([chapter["title"] for chapter in peripheral_chapters])
    sections.append("Appendices")
    elements.extend(create_toc(sections, styles))
    elements.extend(create_location_plan_section(context, styles, layout))
    elements.extend(create_medien_section(context, styles, layout))

    # Risk Matrix section with 3 matrices
    elements.extend(create_xq_plan_risk_matrix_section(
        all_requirements, styles, layout
    ))

    # Main Asset section with subchapters
    elements.append(Paragraph(main_title, styles["ChapterTitle"]))

    _sc_id_map = _build_subchapter_id_map()

    def append_subchapters(requirements: List[Dict[str, Any]]) -> None:
        for subchapter in Subchapter:
            chapter_reqs = [r for r in requirements if _int_or_none(r.get("subchapter_id")) == _sc_id_map.get(subchapter.value)]
            if chapter_reqs:
                label = SUBCHAPTER_LABELS.get(subchapter, subchapter.value)
                elements.append(Paragraph(label, styles["SectionTitle"]))
                elements.extend(create_xq_plan_table(
                    chapter_reqs, xq_catalog_map, xq_after_map, styles, layout
                ))
                elements.append(Spacer(1, 0.4 * cm))

    append_subchapters(main_reqs)

    # Peripheral Asset sections
    if peripheral_chapters:
        elements.append(PageBreak())
        for idx, chapter in enumerate(peripheral_chapters):
            if idx > 0:
                elements.append(PageBreak())
            elements.append(Paragraph(chapter["title"], styles["ChapterTitle"]))
            append_subchapters(chapter["requirements"])

    elements.append(PageBreak())
    elements.append(Paragraph("Appendices", styles["ChapterTitle"]))
    elements.extend(create_appendix_urls(context.get("appendix_urls", []), styles))

    return elements


def create_traceability_matrix_section(context: Dict[str, Any], styles, layout: LayoutSpec) -> List:
    """Create Traceability Matrix chapter with one subchapter per asset (main + peripherals)."""
    elements: List[Any] = []
    elements.append(Paragraph("Traceability Matrix", styles["ChapterTitle"]))
    elements.append(Spacer(1, 0.3 * cm))

    def _asset_table(requirements: List[Dict[str, Any]]) -> List:
        sub: List[Any] = []
        if not requirements:
            sub.append(Paragraph("No requirements found.", styles["Normal"]))
            return sub

        headers = [
            Paragraph("URS-ID", styles["TableHeader"]),
            Paragraph("Risk-ID", styles["TableHeader"]),
            Paragraph("Mitigation-ID", styles["TableHeader"]),
        ]
        col_widths = _widths_from_fractions(layout, [0.33, 0.34, 0.33])
        table_data = [headers]

        for req in requirements:
            urs_id = _int_or_none(req.get("requirement_id"))
            risk_id = _int_or_none(req.get("risk_id"))

            # Build mitigation label from dq_id or xq_id
            dq_id = _int_or_none(req.get("dq_id"))
            xq_id = _int_or_none(req.get("xq_id"))
            if dq_id is not None:
                mitigation_label = f"DQ-{dq_id}"
            elif xq_id is not None:
                mitigation_label = f"xQ-{xq_id}"
            else:
                mitigation_label = "-"

            urs_label = f"URS-{urs_id}" if urs_id is not None else "-"
            risk_label = f"Risk-{risk_id}" if risk_id is not None else "-"

            table_data.append([urs_label, risk_label, mitigation_label])

        tbl = Table(table_data, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F44336")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
        ]))
        sub.append(tbl)
        return sub

    # Main asset
    main_name = safe_str(
        context.get("asset_name") or "Main Asset"
    )
    elements.append(Paragraph(main_name, styles["SectionTitle"]))
    elements.append(Spacer(1, 0.2 * cm))
    elements.extend(_asset_table(context.get("main_requirements", [])))
    elements.append(Spacer(1, 0.5 * cm))

    # Peripheral assets
    for periph in context.get("peripherals", []):
        periph_name = safe_str(
            periph.get("name") or periph.get("asset_name") or "Peripheral"
        )
        elements.append(Paragraph(periph_name, styles["SectionTitle"]))
        elements.append(Spacer(1, 0.2 * cm))
        elements.extend(_asset_table(periph.get("requirements", [])))
        elements.append(Spacer(1, 0.5 * cm))

    elements.append(PageBreak())
    return elements


def _build_qual_report_document(context: Dict[str, Any], styles, layout: LayoutSpec) -> List:
    """Build Qualification Report document content."""
    elements: List[Any] = []

    sections = [
        "Summary", "Test Results", "Deviations",
        "Risk Matrix", "Traceability Matrix", "Appendices",
    ]
    elements.extend(create_toc(sections, styles))
    elements.extend(create_location_plan_section(context, styles, layout))
    elements.extend(create_medien_section(context, styles, layout))

    elements.append(Paragraph("Summary", styles["ChapterTitle"]))

    xq_items = context.get("xq_items", [])
    total = len(xq_items)
    passed = len([x for x in xq_items if x.get("passed") == "TRUE" or x.get("passed") is True])
    failed = len([x for x in xq_items if x.get("passed") == "FALSE" or x.get("passed") is False])

    summary_data = [
        ["Total Tests:", str(total)],
        ["Passed:", str(passed)],
        ["Failed:", str(failed)],
        ["Success Rate:", f"{(passed / total * 100) if total > 0 else 0:.1f}%"],
    ]

    summary_table = Table(summary_data, colWidths=[5 * cm, layout.content_width - 5 * cm], hAlign="LEFT")
    summary_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(summary_table)

    elements.append(PageBreak())
    elements.append(Paragraph("Test Results", styles["ChapterTitle"]))
    elements.extend(create_xq_table(xq_items, styles, layout, include_results=True))

    elements.append(PageBreak())
    elements.append(Paragraph("Deviations", styles["ChapterTitle"]))

    failed_items = [x for x in xq_items if x.get("passed") == "FALSE" or x.get("passed") is False]
    if failed_items:
        for item in failed_items:
            elements.append(Paragraph(
                f"URS {item.get('requirement_id')}: {safe_str(item.get('failed_description', 'N/A'))}",
                styles["Normal"],
            ))
            if item.get("corrective_action"):
                elements.append(Paragraph(
                    f"Corrective Action: {safe_str(item.get('corrective_action'))}",
                    styles["Normal"],
                ))
            elements.append(Spacer(1, 0.3 * cm))
    else:
        elements.append(Paragraph("No deviations.", styles["Normal"]))

    # Risk Matrix from all requirements (main + peripherals)
    elements.append(PageBreak())
    all_reqs: List[Dict[str, Any]] = list(context.get("main_requirements", []))
    for periph in context.get("peripherals", []):
        all_reqs.extend(periph.get("requirements", []))
    elements.extend(create_risk_matrix_section(all_reqs, styles, layout))  # ends with PageBreak

    # Traceability Matrix (one subchapter per asset)
    elements.extend(create_traceability_matrix_section(context, styles, layout))  # ends with PageBreak

    elements.append(Paragraph("Appendices", styles["ChapterTitle"]))
    elements.extend(create_appendix_urls(context.get("appendix_urls", []), styles))

    return elements
