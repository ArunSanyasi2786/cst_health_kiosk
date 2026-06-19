"""
services/report_service.py

PDF report generation service for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the main backend for session-specific PDF health reports
- It generates user/session-specific PDF files under data/reports/
- It works for both demo mode and hardware mode
- It keeps the generated report path synchronized with AppState
- It can persist the updated session record to the database after report generation
- It provides reusable helpers for:
    - current session report generation
    - report generation for a saved session from the database
    - report listing / deletion
    - compact report context building for QR and results flows

Linked files:
- config.py
- core/app_state.py
- core/constants.py
- core/asset_paths.py
- core/utils.py
- services/diagnosis_service.py
- services/database_service.py
- services/session_service.py (optional consumer)
- services/export_service.py (indirectly related)

Design goals:
- clean professional PDF
- stable for Raspberry Pi and laptop demo
- safe even if optional images are missing
- readable structure with metadata, measurements, diagnosis, and recommendations
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from PyQt6.QtCore import QObject, pyqtSignal
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, StyleSheet1, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from config import APP_NAME, APP_VERSION, EMERGENCY_NUMBER, PATHS
from core.app_state import AppState, get_app_state
from core.asset_paths import get_main_logo_path
from core.constants import (
    METRIC_BMI,
    METRIC_HEIGHT,
    METRIC_LABELS,
    METRIC_PULSE,
    METRIC_RR,
    METRIC_SPO2,
    METRIC_TEMPERATURE,
    METRIC_UNITS,
    METRIC_WEIGHT,
    REPORT_ADVICE_SECTION_TITLE,
    REPORT_ANONYMOUS_USER_LABEL,
    REPORT_DATE_LABEL,
    REPORT_DIAGNOSIS_SECTION_TITLE,
    REPORT_EMERGENCY_LABEL,
    REPORT_METRIC_SECTION_TITLE,
    REPORT_MODE_LABEL,
    REPORT_QR_NOTE,
    REPORT_SESSION_ID_LABEL,
    REPORT_STATUS_LABEL,
    REPORT_SUBTITLE,
    REPORT_TIME_LABEL,
    REPORT_TITLE,
    ROUTE_QR,
    SEVERITY_ATTENTION,
    SEVERITY_CRITICAL,
    SEVERITY_NORMAL,
    SEVERITY_UNKNOWN,
    SEVERITY_WARNING,
)
from core.logger import get_logger, log_exception
from core.utils import (
    build_report_path,
    deep_copy,
    ensure_directory,
    file_size_bytes,
    format_bytes,
    format_metric_value,
    humanize_datetime,
    normalize_measurement_payload,
    now_iso,
    safe_str,
)
from services.database_service import DatabaseService, get_database_service
from services.diagnosis_service import DiagnosisService, get_diagnosis_service

logger = get_logger(__name__)


# ============================================================
# Dataclasses
# ============================================================

@dataclass
class ReportResult:
    success: bool
    session_id: str
    report_path: str
    size_bytes: int
    size_human: str
    message: str
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "session_id": self.session_id,
            "report_path": self.report_path,
            "size_bytes": self.size_bytes,
            "size_human": self.size_human,
            "message": self.message,
            "metadata": deep_copy(self.metadata),
        }


# ============================================================
# Report service
# ============================================================

class ReportService(QObject):
    """
    Central PDF report generation service.

    Main responsibilities:
    - build clean report context from session / diagnosis data
    - generate report PDFs to data/reports/
    - attach generated report path to AppState
    - optionally persist updated session into the database
    - support regeneration for saved sessions
    """

    report_generated = pyqtSignal(dict)
    report_saved = pyqtSignal(str)
    report_deleted = pyqtSignal(str)
    report_error = pyqtSignal(str)

    def __init__(
        self,
        app_state: Optional[AppState] = None,
        diagnosis_service: Optional[DiagnosisService] = None,
        database_service: Optional[DatabaseService] = None,
        session_service: Optional[object] = None,
    ) -> None:
        super().__init__()

        self._logger = logger.bind(component="ReportService")
        self._app_state: AppState = app_state or get_app_state()
        self._diagnosis_service: DiagnosisService = diagnosis_service or get_diagnosis_service()
        self._database_service: DatabaseService = database_service or get_database_service()
        self._session_service: Optional[object] = session_service

        self._ensure_reports_dir()

    # ========================================================
    # Dependency setters
    # ========================================================

    def set_session_service(self, session_service: object) -> None:
        self._session_service = session_service

    # ========================================================
    # Basic helpers
    # ========================================================

    def _ensure_reports_dir(self) -> None:
        ensure_directory(PATHS.reports_dir)

    def _status_color(self, severity: str) -> colors.Color:
        normalized = safe_str(severity, SEVERITY_UNKNOWN).strip().lower()
        if normalized == SEVERITY_CRITICAL:
            return colors.HexColor("#D62839")
        if normalized == SEVERITY_WARNING:
            return colors.HexColor("#F77F00")
        if normalized == SEVERITY_ATTENTION:
            return colors.HexColor("#F4B400")
        if normalized == SEVERITY_NORMAL:
            return colors.HexColor("#2EAD67")
        return colors.HexColor("#607D8B")

    def _styles(self) -> StyleSheet1:
        base = getSampleStyleSheet()

        base.add(
            ParagraphStyle(
                name="KioskTitle",
                parent=base["Title"],
                fontName="Helvetica-Bold",
                fontSize=20,
                leading=24,
                alignment=TA_CENTER,
                textColor=colors.HexColor("#0E4F8A"),
                spaceAfter=6,
            )
        )
        base.add(
            ParagraphStyle(
                name="KioskSubtitle",
                parent=base["BodyText"],
                fontName="Helvetica",
                fontSize=11,
                leading=14,
                alignment=TA_CENTER,
                textColor=colors.HexColor("#406A8E"),
                spaceAfter=10,
            )
        )
        base.add(
            ParagraphStyle(
                name="KioskSection",
                parent=base["Heading2"],
                fontName="Helvetica-Bold",
                fontSize=12,
                leading=14,
                alignment=TA_LEFT,
                textColor=colors.HexColor("#123C66"),
                spaceBefore=8,
                spaceAfter=6,
            )
        )
        base.add(
            ParagraphStyle(
                name="KioskBody",
                parent=base["BodyText"],
                fontName="Helvetica",
                fontSize=10,
                leading=14,
                alignment=TA_LEFT,
                textColor=colors.black,
                spaceAfter=4,
            )
        )
        base.add(
            ParagraphStyle(
                name="KioskSmall",
                parent=base["BodyText"],
                fontName="Helvetica",
                fontSize=8.5,
                leading=11,
                alignment=TA_LEFT,
                textColor=colors.HexColor("#5C6B7A"),
                spaceAfter=2,
            )
        )
        base.add(
            ParagraphStyle(
                name="KioskRightSmall",
                parent=base["BodyText"],
                fontName="Helvetica",
                fontSize=8.5,
                leading=11,
                alignment=TA_RIGHT,
                textColor=colors.HexColor("#5C6B7A"),
                spaceAfter=2,
            )
        )
        base.add(
            ParagraphStyle(
                name="KioskStatus",
                parent=base["BodyText"],
                fontName="Helvetica-Bold",
                fontSize=11,
                leading=14,
                alignment=TA_LEFT,
                textColor=colors.HexColor("#0E4F8A"),
                spaceAfter=4,
            )
        )
        return base

    def _footer_canvas(self, canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#6B7785"))
        page_w, _ = A4

        canvas.drawString(18 * mm, 10 * mm, f"{APP_NAME} • {APP_VERSION}")
        canvas.drawRightString(page_w - 18 * mm, 10 * mm, f"Generated: {now_iso()}")
        canvas.restoreState()

    def _safe_logo(self) -> Optional[Path]:
        try:
            logo_path = get_main_logo_path()
            if logo_path.exists() and logo_path.is_file():
                return logo_path
        except Exception:
            pass
        return None

    def _safe_qr_image_path(self, qr_path: str) -> Optional[Path]:
        if not qr_path:
            return None
        path = Path(qr_path)
        if path.exists() and path.is_file():
            return path
        return None

    def _default_report_path(self, session_id: str) -> Path:
        return build_report_path(session_id, extension="pdf")

    def _current_session_id(self) -> str:
        snapshot = self._app_state.session_snapshot()
        return safe_str(snapshot.get("session_id"), "").strip()

    # ========================================================
    # Context building
    # ========================================================

    def build_report_context(
        self,
        *,
        session_payload: Optional[Mapping[str, Any]] = None,
        measurements: Optional[Mapping[str, Any]] = None,
        diagnosis_payload: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Build a complete report context dictionary from current or supplied data.
        """
        if session_payload is None:
            session_payload = self._app_state.session_snapshot()

        session = dict(session_payload or {})
        session_id = safe_str(session.get("session_id"), "").strip()
        if not session_id:
            session_id = self._app_state.ensure_active_session()

        measurement_payload = normalize_measurement_payload(
            measurements if measurements is not None else session.get("measurements", self._app_state.current_measurements())
        )

        if diagnosis_payload is None:
            diagnosis_payload = session.get("diagnosis", {})
            if not isinstance(diagnosis_payload, Mapping) or not diagnosis_payload:
                diagnosis_payload = self._diagnosis_service.build_diagnosis(
                    measurement_payload,
                    store_in_app_state=False,
                )

        diagnosis = self._diagnosis_service.build_diagnosis(
            measurement_payload,
            store_in_app_state=False,
        )
        if diagnosis_payload:
            diagnosis.update(dict(diagnosis_payload))
        diagnosis = self._diagnosis_service._normalize_existing_diagnosis(diagnosis)

        mode = safe_str(session.get("mode"), self._app_state.runtime_mode()).strip()
        status = safe_str(session.get("status"), "").strip()
        started_at = safe_str(session.get("started_at"), "")
        completed_at = safe_str(session.get("completed_at"), "")
        report_path = safe_str(session.get("report_path"), "")
        qr_path = safe_str(session.get("qr_path"), "")
        generated_at = now_iso()

        context = {
            "session_id": session_id,
            "mode": mode,
            "status": status,
            "started_at": started_at,
            "completed_at": completed_at,
            "generated_at": generated_at,
            "measurements": deep_copy(measurement_payload),
            "diagnosis": deep_copy(diagnosis),
            "report_path": report_path,
            "qr_path": qr_path,
            "status_payload": self._diagnosis_service.results_status_payload(
                measurements=measurement_payload,
                diagnosis_payload=diagnosis,
            ),
            "consult_payload": self._diagnosis_service.consult_payload(
                measurements=measurement_payload,
                diagnosis_payload=diagnosis,
            ),
            "health_index": self._diagnosis_service.health_index_payload(diagnosis),
        }
        return context

    # ========================================================
    # Story builders
    # ========================================================

    def _metadata_table(self, context: Mapping[str, Any], styles: StyleSheet1) -> Table:
        diagnosis = dict(context.get("diagnosis", {}) or {})
        status_title = safe_str(diagnosis.get("status_title"), "No Data")
        severity = safe_str(diagnosis.get("overall_severity"), SEVERITY_UNKNOWN)

        rows = [
            [REPORT_SESSION_ID_LABEL, safe_str(context.get("session_id"), "")],
            [REPORT_MODE_LABEL, safe_str(context.get("mode"), "")],
            [REPORT_STATUS_LABEL, status_title],
            [REPORT_DATE_LABEL, humanize_datetime(context.get("generated_at")).split(",")[0] if context.get("generated_at") else "-"],
            [REPORT_TIME_LABEL, humanize_datetime(context.get("generated_at")).split(",")[-1].strip() if context.get("generated_at") else "-"],
        ]

        table = Table(rows, colWidths=[45 * mm, 120 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF4FA")),
                    ("BACKGROUND", (1, 0), (1, -1), colors.white),
                    ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#223344")),
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C8D6E5")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ROWBACKGROUNDS", (1, 0), (1, -1), [colors.white, colors.HexColor("#FAFCFE")]),
                    ("TEXTCOLOR", (1, 2), (1, 2), self._status_color(severity)),
                    ("FONTNAME", (1, 2), (1, 2), "Helvetica-Bold"),
                ]
            )
        )
        return table

    def _measurements_table(self, context: Mapping[str, Any]) -> Table:
        measurements = dict(context.get("measurements", {}) or {})
        diagnosis = dict(context.get("diagnosis", {}) or {})
        metric_categories = dict(diagnosis.get("metric_categories", {}) or {})

        metric_keys = [
            METRIC_WEIGHT,
            METRIC_HEIGHT,
            METRIC_BMI,
            METRIC_TEMPERATURE,
            METRIC_SPO2,
            METRIC_PULSE,
            METRIC_RR,
        ]

        rows: List[List[Any]] = [["Metric", "Value", "Category / Interpretation"]]

        for metric_key in metric_keys:
            label = METRIC_LABELS.get(metric_key, metric_key.replace("_", " ").title())
            value = format_metric_value(metric_key, measurements.get(metric_key), show_unit=True, fallback="--")
            category_payload = metric_categories.get(metric_key, {})
            category_label = safe_str(category_payload.get("label"), "")
            summary = safe_str(category_payload.get("summary"), "")
            interpretation = category_label or summary or "-"
            if category_label and summary and category_label.lower() not in summary.lower():
                interpretation = f"{category_label} — {summary}"
            rows.append([label, value, interpretation])

        table = Table(rows, colWidths=[42 * mm, 38 * mm, 95 * mm], repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0E4F8A")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7FBFF")]),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C7D5E2")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        return table

    def _issue_paragraphs(self, diagnosis: Mapping[str, Any], styles: StyleSheet1) -> List[Any]:
        issue_labels = list(diagnosis.get("issue_labels", []) or [])
        if not issue_labels:
            return [Paragraph("No major issues were flagged in the current session.", styles["KioskBody"])]

        flow: List[Any] = []
        for label in issue_labels:
            flow.append(Paragraph(f"• {safe_str(label, '')}", styles["KioskBody"]))
        return flow

    def _combination_paragraphs(self, diagnosis: Mapping[str, Any], styles: StyleSheet1) -> List[Any]:
        combination = dict(diagnosis.get("combination_diagnosis", {}) or {})
        label = safe_str(combination.get("likely_condition") or combination.get("label"), "").strip()
        remark = safe_str(combination.get("care_note") or combination.get("remark"), "").strip()
        parameter_status_text = safe_str(combination.get("parameter_status_text"), "").strip()
        tips = list(combination.get("tips", []) or [])

        if not label and not remark and not parameter_status_text and not tips:
            return []

        flow: List[Any] = []
        if label:
            flow.append(Paragraph(f"<b>Likely health remark:</b> {label}", styles["KioskBody"]))
        if parameter_status_text:
            flow.append(Paragraph(parameter_status_text, styles["KioskBody"]))
        if remark:
            flow.append(Paragraph(remark, styles["KioskBody"]))
        for tip in tips[:3]:
            flow.append(Paragraph(f"• {safe_str(tip, '')}", styles["KioskBody"]))
        return flow

    def _recommendation_paragraphs(self, diagnosis: Mapping[str, Any], styles: StyleSheet1) -> List[Any]:
        recommendations = list(diagnosis.get("recommendations", []) or [])
        consult_tips = list(diagnosis.get("consult_tips", []) or [])

        flow: List[Any] = []
        source_items = recommendations if recommendations else consult_tips

        if not source_items:
            flow.append(Paragraph("Maintain healthy daily habits and continue routine health monitoring.", styles["KioskBody"]))
            return flow

        for text in source_items:
            flow.append(Paragraph(f"• {safe_str(text, '')}", styles["KioskBody"]))
        return flow

    def _header_block(self, context: Mapping[str, Any], styles: StyleSheet1) -> List[Any]:
        flow: List[Any] = []

        logo_path = self._safe_logo()
        if logo_path is not None:
            try:
                logo = Image(str(logo_path), width=28 * mm, height=28 * mm)
                logo.hAlign = "CENTER"
                flow.append(logo)
                flow.append(Spacer(1, 4))
            except Exception:
                pass

        flow.append(Paragraph(REPORT_TITLE, styles["KioskTitle"]))
        flow.append(Paragraph(REPORT_SUBTITLE, styles["KioskSubtitle"]))
        flow.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#C8D6E5")))
        flow.append(Spacer(1, 4))
        return flow

    def _qr_block(self, context: Mapping[str, Any], styles: StyleSheet1) -> List[Any]:
        flow: List[Any] = []
        qr_path = self._safe_qr_image_path(safe_str(context.get("qr_path"), ""))

        if qr_path is None:
            return flow

        try:
            flow.append(Spacer(1, 6))
            flow.append(Paragraph("QR Access", styles["KioskSection"]))
            qr_img = Image(str(qr_path), width=28 * mm, height=28 * mm)
            qr_img.hAlign = "LEFT"
            flow.append(qr_img)
            flow.append(Spacer(1, 3))
            flow.append(Paragraph(REPORT_QR_NOTE, styles["KioskSmall"]))
        except Exception as exc:
            self._logger.warning("Failed to include QR image in PDF: %s", exc)

        return flow

    def _story(self, context: Mapping[str, Any]) -> List[Any]:
        styles = self._styles()
        diagnosis = dict(context.get("diagnosis", {}) or {})
        status_payload = dict(context.get("status_payload", {}) or {})
        consult_payload = dict(context.get("consult_payload", {}) or {})
        health_index = dict(context.get("health_index", {}) or {})

        story: List[Any] = []

        story.extend(self._header_block(context, styles))

        # Summary strip
        severity = safe_str(diagnosis.get("overall_severity"), SEVERITY_UNKNOWN)
        status_title = safe_str(status_payload.get("title"), diagnosis.get("status_title", "No Data"))
        summary_text = safe_str(status_payload.get("summary"), diagnosis.get("summary", "No diagnosis summary available."))

        summary_table = Table(
            [
                [
                    Paragraph("<b>Overall Status</b>", styles["KioskBody"]),
                    Paragraph(f"<b>{status_title}</b>", styles["KioskStatus"]),
                    Paragraph(f"<b>Health Index:</b> {health_index.get('score', '-')}", styles["KioskBody"]),
                ],
                [
                    Paragraph("Summary", styles["KioskBody"]),
                    Paragraph(summary_text, styles["KioskBody"]),
                    Paragraph(
                        f"{health_index.get('label', '')}",
                        styles["KioskBody"],
                    ),
                ],
            ],
            colWidths=[34 * mm, 98 * mm, 45 * mm],
        )
        summary_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 1), colors.white),
                    ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#BFD0DF")),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D4E0EC")),
                    ("TEXTCOLOR", (1, 0), (1, 0), self._status_color(severity)),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )

        story.append(summary_table)
        story.append(Spacer(1, 8))

        # Metadata
        story.append(Paragraph("Session Information", styles["KioskSection"]))
        story.append(self._metadata_table(context, styles))
        story.append(Spacer(1, 8))

        # Measurements
        story.append(Paragraph(REPORT_METRIC_SECTION_TITLE, styles["KioskSection"]))
        story.append(self._measurements_table(context))
        story.append(Spacer(1, 8))

        # Diagnosis
        story.append(Paragraph(REPORT_DIAGNOSIS_SECTION_TITLE, styles["KioskSection"]))
        story.append(Paragraph(summary_text, styles["KioskBody"]))
        story.extend(self._issue_paragraphs(diagnosis, styles))
        combination_flow = self._combination_paragraphs(diagnosis, styles)
        if combination_flow:
            story.append(Spacer(1, 4))
            story.append(Paragraph("Combined Diagnosis Impression", styles["KioskSection"]))
            story.extend(combination_flow)
        story.append(Spacer(1, 6))

        # Recommendations
        story.append(Paragraph(REPORT_ADVICE_SECTION_TITLE, styles["KioskSection"]))
        story.extend(self._recommendation_paragraphs(diagnosis, styles))
        story.append(Spacer(1, 6))

        # Emergency / consult
        emergency_number = safe_str(
            consult_payload.get("emergency_number"),
            diagnosis.get("emergency_number", EMERGENCY_NUMBER),
        )
        emergency_flag = bool(consult_payload.get("emergency_recommended", diagnosis.get("emergency_recommended", False)))

        emergency_rows = [
            [REPORT_EMERGENCY_LABEL, emergency_number or EMERGENCY_NUMBER],
            ["Emergency Recommended", "Yes" if emergency_flag else "No"],
        ]
        emergency_table = Table(emergency_rows, colWidths=[48 * mm, 50 * mm])
        emergency_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF4FA")),
                    ("BACKGROUND", (1, 0), (1, -1), colors.white),
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C7D5E2")),
                    ("TEXTCOLOR", (1, 1), (1, 1), colors.HexColor("#C0392B") if emergency_flag else colors.HexColor("#2EAD67")),
                    ("FONTNAME", (1, 1), (1, 1), "Helvetica-Bold"),
                ]
            )
        )

        story.append(Paragraph("Consult / Emergency Guidance", styles["KioskSection"]))
        story.append(emergency_table)
        story.append(Spacer(1, 6))

        consult_tips = list(consult_payload.get("consult_tips", []) or [])
        if consult_tips:
            for tip in consult_tips:
                story.append(Paragraph(f"• {safe_str(tip, '')}", styles["KioskBody"]))

        story.extend(self._qr_block(context, styles))
        story.append(Spacer(1, 8))
        story.append(HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#D3DEE8")))
        story.append(Spacer(1, 4))
        story.append(
            Paragraph(
                "This report is a kiosk-generated health summary for screening and awareness purposes. "
                "It does not replace professional medical evaluation.",
                styles["KioskSmall"],
            )
        )

        return story

    # ========================================================
    # Public report generation
    # ========================================================

    def generate_report(
        self,
        *,
        session_payload: Optional[Mapping[str, Any]] = None,
        measurements: Optional[Mapping[str, Any]] = None,
        diagnosis_payload: Optional[Mapping[str, Any]] = None,
        output_path: Optional[str | Path] = None,
        attach_to_app_state: bool = True,
        persist_to_database: bool = True,
    ) -> Dict[str, Any]:
        """
        Generic report generation entry point.
        """
        try:
            context = self.build_report_context(
                session_payload=session_payload,
                measurements=measurements,
                diagnosis_payload=diagnosis_payload,
            )
            session_id = safe_str(context.get("session_id"), "").strip()
            if not session_id:
                raise ValueError("Cannot generate report without a session_id.")

            report_path = Path(output_path) if output_path is not None else self._default_report_path(session_id)
            ensure_directory(report_path.parent)

            doc = SimpleDocTemplate(
                str(report_path),
                pagesize=A4,
                leftMargin=18 * mm,
                rightMargin=18 * mm,
                topMargin=16 * mm,
                bottomMargin=16 * mm,
                title=REPORT_TITLE,
                author=APP_NAME,
                subject=f"Health Report - {session_id}",
            )

            story = self._story(context)
            doc.build(story, onFirstPage=self._footer_canvas, onLaterPages=self._footer_canvas)

            if attach_to_app_state:
                self._app_state.set_report_path(str(report_path))

            if persist_to_database:
                try:
                    self._database_service.save_current_app_state_session()
                except Exception as exc:
                    self._logger.warning("Report generated but DB persistence failed: %s", exc)

            size_bytes = file_size_bytes(report_path)
            result = ReportResult(
                success=True,
                session_id=session_id,
                report_path=str(report_path),
                size_bytes=size_bytes,
                size_human=format_bytes(size_bytes),
                message="PDF report generated successfully.",
                metadata={
                    "generated_at": now_iso(),
                    "mode": safe_str(context.get("mode"), ""),
                    "status": safe_str(context.get("status"), ""),
                },
            ).to_dict()

            self._logger.info(
                "PDF report generated.",
                extra={
                    "session_id": session_id,
                    "mode": safe_str(context.get("mode"), "-"),
                    "route": self._app_state.current_route(),
                },
            )

            self.report_generated.emit(deep_copy(result))
            self.report_saved.emit(str(report_path))
            return result

        except Exception as exc:
            log_exception(self._logger, "Failed to generate PDF report", exc)
            self.report_error.emit(str(exc))
            return ReportResult(
                success=False,
                session_id=safe_str((session_payload or {}).get("session_id"), ""),
                report_path=str(output_path or ""),
                size_bytes=0,
                size_human=format_bytes(0),
                message=str(exc),
                metadata={},
            ).to_dict()

    def generate_current_session_report(
        self,
        *,
        output_path: Optional[str | Path] = None,
        persist_to_database: bool = True,
    ) -> Dict[str, Any]:
        """
        Generate PDF for the current active session.
        """
        return self.generate_report(
            session_payload=self._app_state.session_snapshot(),
            measurements=self._app_state.current_measurements(),
            diagnosis_payload=self._diagnosis_service.current_diagnosis(),
            output_path=output_path,
            attach_to_app_state=True,
            persist_to_database=persist_to_database,
        )

    def generate_report_for_session_id(
        self,
        session_id: str,
        *,
        output_path: Optional[str | Path] = None,
        attach_to_app_state: bool = False,
    ) -> Dict[str, Any]:
        """
        Generate a report for a saved database session.
        """
        record = self._database_service.get_session_by_session_id(session_id)
        if not record:
            message = f"Session not found: {session_id}"
            self.report_error.emit(message)
            return ReportResult(
                success=False,
                session_id=session_id,
                report_path=str(output_path or ""),
                size_bytes=0,
                size_human=format_bytes(0),
                message=message,
                metadata={},
            ).to_dict()

        session_payload = {
            "session_id": record.get("session_id", ""),
            "mode": record.get("mode", ""),
            "status": record.get("status", ""),
            "started_at": record.get("started_at", ""),
            "completed_at": record.get("completed_at", ""),
            "report_path": record.get("report_path", ""),
            "qr_path": record.get("qr_path", ""),
            "measurements": record.get("measurements", {}),
            "diagnosis": record.get("diagnosis", {}),
        }

        return self.generate_report(
            session_payload=session_payload,
            measurements=record.get("measurements", {}),
            diagnosis_payload=record.get("diagnosis", {}),
            output_path=output_path,
            attach_to_app_state=attach_to_app_state,
            persist_to_database=False,
        )

    # ========================================================
    # Report listing / deletion
    # ========================================================

    def list_reports(self, limit: int = 100) -> List[Dict[str, Any]]:
        self._ensure_reports_dir()
        limit = max(1, int(limit))

        files = [
            p for p in PATHS.reports_dir.glob("*.pdf")
            if p.is_file() and not p.name.startswith(".")
        ]
        files.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)

        result: List[Dict[str, Any]] = []
        for path in files[:limit]:
            stat = path.stat()
            result.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "size_bytes": stat.st_size,
                    "size_human": format_bytes(stat.st_size),
                    "modified_at_epoch": stat.st_mtime,
                }
            )
        return result

    def delete_report(self, report_name_or_path: str) -> bool:
        target = Path(report_name_or_path)
        if not target.is_absolute():
            target = PATHS.reports_dir / target.name

        try:
            if target.exists() and target.is_file():
                target.unlink(missing_ok=True)
                self._logger.info("Report deleted: %s", target)
                self.report_deleted.emit(str(target))
                return True
            return False
        except Exception as exc:
            log_exception(self._logger, "Failed to delete report", exc)
            self.report_error.emit(str(exc))
            return False

    # ========================================================
    # Convenience payload helpers
    # ========================================================

    def current_report_path(self) -> str:
        session = self._app_state.session_snapshot()
        return safe_str(session.get("report_path"), "").strip()

    def report_exists(self, report_path: Optional[str] = None) -> bool:
        path = Path(report_path or self.current_report_path())
        return path.exists() and path.is_file()

    def current_report_summary(self) -> Dict[str, Any]:
        """
        Compact info useful for QR screen or results quick actions.
        """
        report_path = self.current_report_path()
        path_obj = Path(report_path) if report_path else None
        exists = bool(path_obj and path_obj.exists() and path_obj.is_file())
        size_bytes = file_size_bytes(path_obj) if exists else 0

        return {
            "report_path": report_path,
            "exists": exists,
            "size_bytes": size_bytes,
            "size_human": format_bytes(size_bytes),
        }

    # ========================================================
    # Diagnostics
    # ========================================================

    def diagnostics(self) -> Dict[str, Any]:
        reports = self.list_reports(limit=50)
        return {
            "reports_dir": str(PATHS.reports_dir),
            "report_count": len(reports),
            "current_report_path": self.current_report_path(),
            "current_report_exists": self.report_exists(),
            "latest_reports": reports[:5],
        }


# ============================================================
# Singleton accessor
# ============================================================

_REPORT_SERVICE_SINGLETON: Optional[ReportService] = None


def get_report_service(
    app_state: Optional[AppState] = None,
    diagnosis_service: Optional[DiagnosisService] = None,
    database_service: Optional[DatabaseService] = None,
    session_service: Optional[object] = None,
) -> ReportService:
    global _REPORT_SERVICE_SINGLETON
    if _REPORT_SERVICE_SINGLETON is None:
        _REPORT_SERVICE_SINGLETON = ReportService(
            app_state=app_state,
            diagnosis_service=diagnosis_service,
            database_service=database_service,
            session_service=session_service,
        )
    else:
        if session_service is not None:
            _REPORT_SERVICE_SINGLETON.set_session_service(session_service)
    return _REPORT_SERVICE_SINGLETON