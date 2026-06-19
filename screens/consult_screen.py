"""
screens/consult_screen.py

Premium consultation / follow-up guidance screen for the
CST Health Monitoring Station kiosk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from PyQt6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QRectF,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.logger import get_logger

try:
    from core.utils import safe_bool, safe_float, safe_int, safe_str
except Exception:  # pragma: no cover
    def safe_str(value: Any, default: str = "") -> str:
        try:
            if value is None:
                return default
            return str(value)
        except Exception:
            return default

    def safe_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None or value == "":
                return default
            return float(value)
        except Exception:
            return default

    def safe_int(value: Any, default: int = 0) -> int:
        try:
            if value is None or value == "":
                return default
            return int(float(value))
        except Exception:
            return default

    def safe_bool(value: Any, default: bool = False) -> bool:
        try:
            if isinstance(value, bool):
                return value
            if value is None:
                return default
            text = str(value).strip().lower()
            if text in {"1", "true", "yes", "y", "on"}:
                return True
            if text in {"0", "false", "no", "n", "off"}:
                return False
            return default
        except Exception:
            return default

try:
    from core.constants import (
        MODE_DEMO,
        MODE_HARDWARE,
        METRIC_BMI,
        METRIC_HEIGHT,
        METRIC_PULSE,
        METRIC_RR,
        METRIC_SPO2,
        METRIC_TEMPERATURE,
        METRIC_WEIGHT,
        SCREEN_MEASURING,
        SCREEN_QR,
        SCREEN_RESULTS,
    )
except Exception:  # pragma: no cover
    MODE_DEMO = "demo"
    MODE_HARDWARE = "hardware"

    METRIC_TEMPERATURE = "temperature"
    METRIC_SPO2 = "spo2"
    METRIC_PULSE = "pulse_rate"
    METRIC_RR = "respiratory_rate"
    METRIC_WEIGHT = "weight"
    METRIC_HEIGHT = "height"
    METRIC_BMI = "bmi"

    SCREEN_RESULTS = "results"
    SCREEN_QR = "qr"
    SCREEN_MEASURING = "measuring"

try:
    from widgets.animated_button import AnimatedButton
except Exception:  # pragma: no cover
    AnimatedButton = None  # type: ignore

try:
    from widgets.glow_label import GlowLabel
    _HAS_GLOW_LABEL = True
except Exception:  # pragma: no cover
    GlowLabel = QLabel  # type: ignore
    _HAS_GLOW_LABEL = False


logger = get_logger(__name__)

try:
    from config import KIOSK_WIDTH, KIOSK_HEIGHT, IS_COMPACT_KIOSK
except Exception:  # pragma: no cover
    KIOSK_WIDTH = 1024
    KIOSK_HEIGHT = 600
    IS_COMPACT_KIOSK = False


# =============================================================================
# Helpers
# =============================================================================

def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_asset(relative_path: str) -> str:
    relative_clean = safe_str(relative_path, "").strip().replace("\\", "/").lstrip("/")
    if not relative_clean:
        return ""

    try:
        import core.asset_paths as asset_paths

        for name in (
            "get_asset_path",
            "asset_path",
            "resolve_asset_path",
            "resolve_asset",
            "asset",
        ):
            resolver = getattr(asset_paths, name, None)
            if callable(resolver):
                try:
                    resolved = resolver(relative_clean)
                    resolved_text = safe_str(resolved, "").strip()
                    if resolved_text:
                        return resolved_text
                except Exception:
                    continue
    except Exception:
        pass

    return str(_project_root().joinpath("assets", *relative_clean.split("/")))


def _pixmap_or_empty(path: str) -> QPixmap:
    text = safe_str(path, "").strip()
    if not text:
        return QPixmap()
    return QPixmap(text)


def _compute_bmi(weight_kg: Optional[float], height_value: Optional[float]) -> Optional[float]:
    if weight_kg in (None, "") or height_value in (None, ""):
        return None

    weight = safe_float(weight_kg, 0.0)
    raw_height = safe_float(height_value, 0.0)

    if weight <= 0 or raw_height <= 0:
        return None

    height_m = raw_height / 100.0 if raw_height > 3.5 else raw_height
    if height_m <= 0:
        return None

    bmi = weight / (height_m * height_m)
    if bmi <= 0:
        return None
    return round(bmi, 1)


def _severity_rank(severity: str) -> int:
    sev = safe_str(severity, "").strip().lower()
    if sev == "critical":
        return 4
    if sev == "warning":
        return 3
    if sev == "attention":
        return 2
    if sev == "normal":
        return 1
    return 0


def _severity_accent(severity: str) -> str:
    sev = safe_str(severity, "").strip().lower()
    if sev == "critical":
        return "#FF6E88"
    if sev == "warning":
        return "#FFA14D"
    if sev == "attention":
        return "#FFD25E"
    if sev == "normal":
        return "#42E393"
    return "#39D8FF"


def _metric_title(metric_key: str) -> str:
    return {
        METRIC_TEMPERATURE: "Temperature",
        METRIC_SPO2: "SpO₂",
        METRIC_PULSE: "Pulse",
        METRIC_RR: "Respiratory Rate",
        METRIC_WEIGHT: "Weight",
        METRIC_HEIGHT: "Height",
        METRIC_BMI: "BMI",
    }.get(metric_key, metric_key.replace("_", " ").title())


def _default_metric_classification(metric_key: str, value: Any) -> Dict[str, Any]:
    if value in (None, ""):
        return {
            "label": "Unavailable",
            "severity": "unknown",
            "summary": "No value is available for this metric yet.",
            "accent_hex": "#39D8FF",
        }

    numeric = safe_float(value, 0.0)

    if metric_key == METRIC_TEMPERATURE:
        if numeric < 36.0:
            label = "Low"
            severity = "attention"
            summary = "Body temperature is below the usual reference range."
        elif numeric < 37.5:
            label = "Normal"
            severity = "normal"
            summary = "Body temperature is within a normal reference range."
        elif numeric < 39.0:
            label = "Elevated"
            severity = "warning"
            summary = "Body temperature is above the normal range and should be reviewed."
        else:
            label = "High Fever"
            severity = "critical"
            summary = "Body temperature is in a high fever range and may need urgent attention."
        return {"label": label, "severity": severity, "summary": summary, "accent_hex": _severity_accent(severity)}

    if metric_key == METRIC_SPO2:
        if numeric < 90:
            label = "Critical"
            severity = "critical"
            summary = "Blood oxygen saturation is critically low."
        elif numeric < 94:
            label = "Low"
            severity = "warning"
            summary = "Blood oxygen saturation is below a recommended healthy range."
        elif numeric < 96:
            label = "Borderline"
            severity = "attention"
            summary = "Blood oxygen saturation is slightly reduced and should be monitored."
        else:
            label = "Healthy"
            severity = "normal"
            summary = "Blood oxygen saturation is within a healthy range."
        return {"label": label, "severity": severity, "summary": summary, "accent_hex": _severity_accent(severity)}

    if metric_key == METRIC_PULSE:
        if numeric < 60:
            label = "Low Pulse"
            severity = "attention"
            summary = "Pulse rate is below the common adult resting range."
        elif numeric < 100:
            label = "Normal"
            severity = "normal"
            summary = "Pulse rate is within the common adult resting range."
        elif numeric < 120:
            label = "Elevated"
            severity = "warning"
            summary = "Pulse rate is above the typical resting range."
        else:
            label = "Very High"
            severity = "critical"
            summary = "Pulse rate is very high and may require urgent attention."
        return {"label": label, "severity": severity, "summary": summary, "accent_hex": _severity_accent(severity)}

    if metric_key == METRIC_RR:
        if numeric < 12:
            label = "Low"
            severity = "attention"
            summary = "Respiratory rate is below the common adult resting range."
        elif numeric < 20:
            label = "Normal"
            severity = "normal"
            summary = "Respiratory rate is within the common adult resting range."
        elif numeric < 24:
            label = "Elevated"
            severity = "warning"
            summary = "Respiratory rate is above the typical resting range."
        else:
            label = "High"
            severity = "critical"
            summary = "Respiratory rate is significantly elevated."
        return {"label": label, "severity": severity, "summary": summary, "accent_hex": _severity_accent(severity)}

    if metric_key == METRIC_BMI:
        if numeric < 18.5:
            label = "Underweight"
            severity = "attention"
            summary = "BMI is below the recommended healthy range."
        elif numeric < 25.0:
            label = "Normal"
            severity = "normal"
            summary = "BMI is within a healthy reference range."
        elif numeric < 30.0:
            label = "Overweight"
            severity = "warning"
            summary = "BMI is above the recommended healthy range."
        else:
            label = "Obese"
            severity = "critical"
            summary = "BMI is significantly above the recommended range."
        return {"label": label, "severity": severity, "summary": summary, "accent_hex": _severity_accent(severity)}

    if metric_key in {METRIC_WEIGHT, METRIC_HEIGHT}:
        return {
            "label": "Captured",
            "severity": "normal",
            "summary": "The supporting anthropometric measurement was captured successfully.",
            "accent_hex": "#39D8FF",
        }

    return {
        "label": "Available",
        "severity": "normal",
        "summary": "This metric was captured successfully.",
        "accent_hex": "#39D8FF",
    }


# =============================================================================
# Internal widgets
# =============================================================================

class _ConsultSummaryCard(QFrame):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._accent_hex = "#39D8FF"
        self._compact = bool(IS_COMPACT_KIOSK or KIOSK_WIDTH <= 860 or KIOSK_HEIGHT <= 520)

        self.setObjectName("ConsultSummaryCard")
        self.setMinimumHeight(106 if self._compact else 250)
        self.setMaximumHeight(118 if self._compact else 320)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QVBoxLayout(self)
        root.setContentsMargins(
            14 if self._compact else 18,
            11 if self._compact else 16,
            14 if self._compact else 18,
            11 if self._compact else 16,
        )
        root.setSpacing(5 if self._compact else 8)

        top_row = QWidget(self)
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        self.title_label = QLabel("Consulting Advice", top_row)
        self.status_chip = QLabel("Review", top_row)

        top_layout.addWidget(self.title_label)
        top_layout.addStretch(1)
        self.status_chip.hide()

        self.summary_label = QLabel(
            "The active session consultation guidance will appear here.",
            self,
        )
        self.summary_label.setWordWrap(True)
        self.summary_label.setMaximumHeight(36 if self._compact else 64)

        self.line_1 = QLabel("• Waiting for a completed result payload.", self)
        self.line_1.setWordWrap(False)
        self.line_1.setMaximumHeight(18 if self._compact else 24)
        self.line_2 = QLabel("• Findings will be summarized by urgency.", self)
        self.line_2.setWordWrap(False)
        self.line_2.setMaximumHeight(18 if self._compact else 24)
        self.line_3 = QLabel("• Use QR or report options for handoff.", self)
        self.line_3.setWordWrap(False)
        self.line_3.setMaximumHeight(18 if self._compact else 24)

        self.footer_note = QLabel(
            "This kiosk screen supports workflow guidance and triage-style follow-up presentation. Final clinical decisions should always rely on approved medical practice and professional judgment.",
            self,
        )
        self.footer_note.setWordWrap(True)

        root.addWidget(top_row)
        root.addWidget(self.summary_label)
        root.addWidget(self.line_1)
        root.addWidget(self.line_2)
        root.addWidget(self.line_3)
        root.addStretch(1)
        root.addWidget(self.footer_note)

        self.footer_note.setVisible(not self._compact)
        if self._compact:
            self.line_3.hide()

        self._apply_style()

    def set_payload(
        self,
        *,
        title: str,
        status_text: str,
        summary: str,
        bullets: Iterable[str],
        accent_hex: str,
    ) -> None:
        self._accent_hex = safe_str(accent_hex, "#39D8FF").strip() or "#39D8FF"
        self.title_label.setText(safe_str(title, "Consulting Advice").strip() or "Consulting Advice")
        self.status_chip.setText(safe_str(status_text, "Review").strip() or "Review")
        self.summary_label.setText(safe_str(summary, "").strip() or "No consultation summary is available.")

        bullet_list = [safe_str(item, "").strip() for item in bullets if safe_str(item, "").strip()]
        while len(bullet_list) < 3:
            bullet_list.append("")

        self.line_1.setText(f"• {bullet_list[0]}" if bullet_list[0] else "")
        self.line_2.setText(f"• {bullet_list[1]}" if bullet_list[1] else "")
        self.line_3.setText(f"• {bullet_list[2]}" if bullet_list[2] else "")

        self.line_1.setVisible(bool(bullet_list[0]))
        self.line_2.setVisible(bool(bullet_list[1]))
        if self._compact:
            self.line_3.setVisible(False)
        else:
            self.line_3.setVisible(bool(bullet_list[2]))

        self._apply_style()

    def _apply_style(self) -> None:
        accent = QColor(self._accent_hex)

        self.setStyleSheet(
            f"""
            QFrame#ConsultSummaryCard {{
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.22);
                border-radius: 24px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.08);
            }}
            """
        )

        self.title_label.setStyleSheet(
            f"""
            QLabel {{
                color: #F4FCFF;
                font-size: {14 if self._compact else 15}px;
                font-weight: 800;
                background: transparent;
            }}
            """
        )
        self.status_chip.setStyleSheet(
            f"""
            QLabel {{
                color: #F4FCFF;
                font-size: 9px;
                font-weight: 800;
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.34);
                border-radius: 12px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.16);
                padding: 4px 9px;
            }}
            """
        )
        self.summary_label.setStyleSheet(
            f"""
            QLabel {{
                color: rgba(221, 239, 250, 0.92);
                font-size: {11 if self._compact else 12}px;
                font-weight: 600;
                background: transparent;
            }}
            """
        )
        bullet_style = f"""
            QLabel {{
                color: rgba(197, 223, 241, 0.84);
                font-size: {10 if self._compact else 11}px;
                font-weight: 500;
                background: transparent;
            }}
        """
        self.line_1.setStyleSheet(bullet_style)
        self.line_2.setStyleSheet(bullet_style)
        self.line_3.setStyleSheet(bullet_style)

        self.footer_note.setStyleSheet(
            f"""
            QLabel {{
                color: rgba(177, 204, 224, 0.76);
                font-size: {8 if self._compact else 9}px;
                font-weight: 500;
                background: transparent;
            }}
            """
        )


# =============================================================================
# Main screen
# =============================================================================

class ConsultScreen(QFrame):
    back_requested = pyqtSignal()
    refresh_requested = pyqtSignal()
    consult_loaded = pyqtSignal(dict)
    qr_requested = pyqtSignal(dict)
    report_requested = pyqtSignal(dict)
    retake_requested = pyqtSignal()
    emergency_requested = pyqtSignal(dict)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        navigator: Optional[object] = None,
        app_state: Optional[object] = None,
        services: Optional[Mapping[str, Any]] = None,
        animation_manager: Optional[object] = None,
        theme_manager: Optional[object] = None,
    ) -> None:
        super().__init__(parent)

        self._logger = logger.bind(component="ConsultScreen")

        self.navigator = navigator
        self.app_state = app_state
        self.services = dict(services or {})
        self.animation_manager = animation_manager
        self.theme_manager = theme_manager

        self._mode = self._read_current_mode()
        self._payload: Dict[str, Any] = {}
        self._report_path = ""
        self._qr_path = ""

        self._background_path = _resolve_asset("backgrounds/consult_bg.png")
        self._logo_small_path = _resolve_asset("logos/wmremove-transformed-removebg-preview (1).png")
        self._consult_art_path = _resolve_asset("illustrations/consult_panel_art.png")

        self._background_pixmap = _pixmap_or_empty(self._background_path)
        self._logo_pixmap = _pixmap_or_empty(self._logo_small_path)
        self._consult_pixmap = _pixmap_or_empty(self._consult_art_path)

        self.setObjectName("ConsultScreen")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._compact = bool(IS_COMPACT_KIOSK or KIOSK_WIDTH <= 860 or KIOSK_HEIGHT <= 520)
        self._ultra_compact = bool(KIOSK_WIDTH <= 820 or KIOSK_HEIGHT <= 490)
        self._guidance_page_active = False

        self._build_ui()
        self._setup_effects()
        self._apply_styles()

    # =========================================================================
    # UI
    # =========================================================================

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(
            14 if self._compact else 22,
            10 if self._compact else 16,
            14 if self._compact else 22,
            10 if self._compact else 16,
        )
        root.setSpacing(8 if self._compact else 12)

        self.top_bar = QWidget(self)
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8 if self._compact else 10)

        self.back_button = self._create_button(
            "Back",
            variant="secondary",
            min_width=78 if self._compact else 96,
            parent=self.top_bar,
        )
        self.back_button.setObjectName("BackButton")
        self.back_button.clicked.connect(self._handle_back_clicked)
        try:
            self.back_button.setFixedSize(88 if self._compact else 100, 38)
        except Exception:
            pass

        self.logo_label = QLabel(self.top_bar)
        self.logo_label.setObjectName("LogoLabel")
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_label.setFixedSize(36 if self._compact else 42, 36 if self._compact else 42)
        self._set_label_pixmap(self.logo_label, self._logo_pixmap, 36 if self._compact else 42)

        self.top_title = QLabel("Consult Guidance", self.top_bar)
        self.top_title.setObjectName("TopTitle")

        self.mode_pill = QLabel("Mode Unknown", self.top_bar)
        self.mode_pill.setObjectName("RuntimePill")

        self.urgency_pill = QLabel("Urgency Pending", self.top_bar)
        self.urgency_pill.setObjectName("RuntimePill")

        self.report_pill = QLabel("Report Pending", self.top_bar)
        self.report_pill.setObjectName("RuntimePill")

        top_layout.addWidget(self.back_button)
        top_layout.addWidget(self.logo_label)
        top_layout.addWidget(self.top_title)
        top_layout.addStretch(1)
        top_layout.addWidget(self.mode_pill)
        top_layout.addWidget(self.urgency_pill)
        top_layout.addWidget(self.report_pill)

        self.header_card = QFrame(self)
        self.header_card.setObjectName("ConsultHeaderCard")

        header_layout = QVBoxLayout(self.header_card)
        header_layout.setContentsMargins(
            14 if self._compact else 18,
            12 if self._compact else 16,
            14 if self._compact else 18,
            12 if self._compact else 16,
        )
        header_layout.setSpacing(6 if self._compact else 8)

        if _HAS_GLOW_LABEL:
            self.hero_title = GlowLabel(
                role=getattr(GlowLabel, "ROLE_TITLE", getattr(GlowLabel, "ROLE_STATUS", 0)),
                align_center=True,
                use_outline=False,
                enable_paint_glow=True,
                initial_glow_strength=0.48,
                initial_glow_blur=18,
            )
        else:
            self.hero_title = QLabel(self.header_card)
            self.hero_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.hero_subtitle = QLabel(self.header_card)
        self.hero_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hero_subtitle.setWordWrap(True)

        self.header_chip_row = QWidget(self.header_card)
        chip_layout = QHBoxLayout(self.header_chip_row)
        chip_layout.setContentsMargins(0, 0, 0, 0)
        chip_layout.setSpacing(6 if self._compact else 8)

        self.overall_chip = QLabel("Consult Status", self.header_chip_row)
        self.overall_chip.setObjectName("HeaderChip")

        self.source_chip = QLabel("Session Source", self.header_chip_row)
        self.source_chip.setObjectName("HeaderChip")

        self.followup_chip = QLabel("Follow-up Guidance", self.header_chip_row)
        self.followup_chip.setObjectName("HeaderChip")

        chip_layout.addStretch(1)
        chip_layout.addWidget(self.overall_chip)
        chip_layout.addWidget(self.source_chip)
        chip_layout.addWidget(self.followup_chip)
        chip_layout.addStretch(1)

        # Hide the internal green chips as requested
        self.header_chip_row.hide()
        self.overall_chip.hide()
        self.source_chip.hide()
        self.followup_chip.hide()

        self.summary_banner = QLabel(
            "This screen helps the operator decide the appropriate next step after reviewing the active session.",
            self.header_card,
        )
        self.summary_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.summary_banner.setWordWrap(True)

        header_layout.addWidget(self.hero_title)
        header_layout.addWidget(self.hero_subtitle)
        header_layout.addWidget(self.header_chip_row)
        header_layout.addWidget(self.summary_banner)

        self.content_row = QWidget(self)
        content_layout = QHBoxLayout(self.content_row)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10 if self._compact else 14)

        self.left_column = QWidget(self.content_row)
        left_layout = QVBoxLayout(self.left_column)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(14)

        self.summary_card = _ConsultSummaryCard(self.left_column)

        self.findings_card = QFrame(self.left_column)
        self.findings_card.setObjectName("InfoCard")
        self.findings_card.setMinimumHeight(96 if self._compact else 168)
        self.findings_card.setMaximumHeight(108 if self._compact else 220)
        self.findings_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        findings_layout = QVBoxLayout(self.findings_card)
        findings_layout.setContentsMargins(
            12 if self._compact else 16,
            10 if self._compact else 14,
            12 if self._compact else 16,
            10 if self._compact else 14,
        )
        findings_layout.setSpacing(5 if self._compact else 8)

        self.findings_title = QLabel("Key Findings", self.findings_card)
        self.findings_title.setObjectName("SectionTitle")

        self.finding_1 = QLabel("• Waiting for session findings.", self.findings_card)
        self.finding_1.setWordWrap(False)
        self.finding_2 = QLabel("• Urgent findings will appear first.", self.findings_card)
        self.finding_2.setWordWrap(False)
        self.finding_3 = QLabel("• Open QR or report for handoff when ready.", self.findings_card)
        self.finding_3.setWordWrap(False)
        self.finding_4 = QLabel("• Start a new checkup to replace the active session.", self.findings_card)
        self.finding_4.setWordWrap(False)
        self.finding_5 = QLabel("• Guidance will be updated from the measured values.", self.findings_card)
        self.finding_5.setWordWrap(False)
        self.finding_6 = QLabel("• Open QR or report after reviewing the guidance.", self.findings_card)
        self.finding_6.setWordWrap(False)

        self.findings_note = QLabel(
            "The recommendations shown here are generated from the active kiosk session payload and should be reviewed in context.",
            self.findings_card,
        )
        self.findings_note.setWordWrap(True)

        findings_layout.addWidget(self.findings_title)
        findings_layout.addWidget(self.finding_1)
        findings_layout.addWidget(self.finding_2)
        findings_layout.addWidget(self.finding_3)
        findings_layout.addWidget(self.finding_4)
        findings_layout.addWidget(self.finding_5)
        findings_layout.addWidget(self.finding_6)
        findings_layout.addWidget(self.findings_note)

        left_layout.addWidget(self.summary_card, 0)
        left_layout.addWidget(self.findings_card, 0)
        left_layout.addStretch(1)

        self.right_column = QWidget(self.content_row)
        right_layout = QVBoxLayout(self.right_column)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8 if self._compact else 12)
        self.right_column.setMinimumWidth(238 if self._compact else 286)
        self.right_column.setMaximumWidth(262 if self._compact else 314)

        self.context_card = QFrame(self.right_column)
        self.context_card.setObjectName("InfoCard")

        context_layout = QVBoxLayout(self.context_card)
        context_layout.setContentsMargins(
            13 if self._compact else 16,
            11 if self._compact else 14,
            13 if self._compact else 16,
            11 if self._compact else 14,
        )
        context_layout.setSpacing(6 if self._compact else 8)

        self.context_art = QLabel(self.context_card)
        self.context_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_label_pixmap(self.context_art, self._consult_pixmap, 88 if self._compact else 118)

        self.context_title = QLabel("Session Context", self.context_card)
        self.context_title.setObjectName("SectionTitle")

        self.context_mode_line = QLabel("Mode: pending", self.context_card)
        self.context_metrics_line = QLabel("Metrics: pending", self.context_card)
        self.context_report_line = QLabel("Report path: pending", self.context_card)
        self.context_qr_line = QLabel("QR path: pending", self.context_card)
        self.context_note = QLabel(
            "This consultation view uses the active session payload currently stored by the kiosk workflow.",
            self.context_card,
        )
        self.context_note.setWordWrap(True)

        context_layout.addWidget(self.context_art, 0, alignment=Qt.AlignmentFlag.AlignHCenter)
        context_layout.addWidget(self.context_title)
        context_layout.addWidget(self.context_mode_line)
        context_layout.addWidget(self.context_metrics_line)
        context_layout.addWidget(self.context_report_line)
        context_layout.addWidget(self.context_qr_line)
        context_layout.addWidget(self.context_note)

        self.actions_card = QFrame(self.right_column)
        self.actions_card.setObjectName("InfoCard")

        actions_layout = QVBoxLayout(self.actions_card)
        actions_layout.setContentsMargins(
            13 if self._compact else 16,
            11 if self._compact else 14,
            13 if self._compact else 16,
            11 if self._compact else 14,
        )
        actions_layout.setSpacing(6 if self._compact else 8)

        self.actions_title = QLabel("Next Actions", self.actions_card)
        self.actions_title.setObjectName("SectionTitle")

        self.actions_text = QLabel(
            "Prepare a report, open the QR handoff screen, or start a new checkup workflow.",
            self.actions_card,
        )
        self.actions_text.setWordWrap(True)

        self.qr_button = self._create_button("Open QR Screen", variant="secondary", min_width=126 if self._compact else 154, parent=self.actions_card)
        self.qr_button.clicked.connect(self._handle_qr_clicked)

        self.report_button = self._create_button("Prepare PDF", variant="ghost", min_width=126 if self._compact else 154, parent=self.actions_card)
        self.report_button.clicked.connect(self._handle_report_clicked)

        self.retake_button = self._create_button("New Checkup", variant="secondary", min_width=126 if self._compact else 154, parent=self.actions_card)
        self.retake_button.clicked.connect(self._handle_new_checkup_clicked)

        actions_layout.addWidget(self.actions_title)
        actions_layout.addWidget(self.actions_text)
        actions_layout.addWidget(self.qr_button)
        actions_layout.addWidget(self.report_button)
        actions_layout.addWidget(self.retake_button)

        self.urgent_card = QFrame(self.right_column)
        self.urgent_card.setObjectName("InfoCard")

        urgent_layout = QVBoxLayout(self.urgent_card)
        urgent_layout.setContentsMargins(
            13 if self._compact else 16,
            11 if self._compact else 14,
            13 if self._compact else 16,
            11 if self._compact else 14,
        )
        urgent_layout.setSpacing(6 if self._compact else 8)

        self.urgent_title = QLabel("Urgency Guidance", self.urgent_card)
        self.urgent_title.setObjectName("SectionTitle")

        self.urgent_text = QLabel(
            "If the session includes concerning values, escalate according to your approved workflow and direct the user to professional review.",
            self.urgent_card,
        )
        self.urgent_text.setWordWrap(True)

        self.urgent_button = self._create_button("Escalation Guidance", variant="primary", min_width=126 if self._compact else 154, parent=self.urgent_card)
        self.urgent_button.clicked.connect(self._handle_emergency_clicked)

        urgent_layout.addWidget(self.urgent_title)
        urgent_layout.addWidget(self.urgent_text)
        urgent_layout.addWidget(self.urgent_button)

        right_layout.addWidget(self.context_card)
        right_layout.addWidget(self.actions_card)
        right_layout.addWidget(self.urgent_card)
        right_layout.addStretch(1)

        content_layout.addWidget(self.left_column, 1)
        content_layout.addWidget(self.right_column, 0)
        content_layout.setStretch(0, 1)
        content_layout.setStretch(1, 0)

        self.action_row = QWidget(self)
        self.action_grid = QGridLayout(self.action_row)
        self.action_grid.setContentsMargins(0, 0, 0, 0)
        self.action_grid.setHorizontalSpacing(6 if self._compact else 10)
        self.action_grid.setVerticalSpacing(8 if self._compact else 10)

        self.refresh_button = self._create_button("Refresh Consult", variant="ghost", min_width=112 if self._compact else 140, parent=self.action_row)
        self.refresh_button.clicked.connect(self.reload_consult)

        self.results_button = self._create_button("Back to Results", variant="secondary", min_width=118 if self._compact else 146, parent=self.action_row)
        self.results_button.clicked.connect(self._handle_back_clicked)

        self.bottom_qr_button = self._create_button("QR Handoff", variant="secondary", min_width=112 if self._compact else 140, parent=self.action_row)
        self.bottom_qr_button.clicked.connect(self._handle_qr_clicked)

        self.bottom_report_button = self._create_button("Prepare PDF", variant="ghost", min_width=112 if self._compact else 140, parent=self.action_row)
        self.bottom_report_button.clicked.connect(self._handle_report_clicked)

        self.bottom_urgent_button = self._create_button("Urgency Guidance", variant="primary", min_width=126 if self._compact else 156, parent=self.action_row)
        self.bottom_urgent_button.clicked.connect(self._handle_guidance_clicked)

        self._bottom_buttons = [
            self.refresh_button,
            self.results_button,
            self.bottom_qr_button,
            self.bottom_report_button,
            self.bottom_urgent_button,
        ]

        for button in self._bottom_buttons:
            try:
                button.setMinimumHeight(32 if self._compact else 42)
                button.setMaximumHeight(32 if self._compact else 42)
                button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            except Exception:
                pass

        self._layout_action_buttons()

        self.guidance_page = QWidget(self)
        self.guidance_page.hide()

        guidance_root = QVBoxLayout(self.guidance_page)
        guidance_root.setContentsMargins(0, 0, 0, 0)
        guidance_root.setSpacing(8 if self._compact else 12)

        self.guidance_card = QFrame(self.guidance_page)
        self.guidance_card.setObjectName("InfoCard")
        self.guidance_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        guidance_card_layout = QVBoxLayout(self.guidance_card)
        guidance_card_layout.setContentsMargins(
            12 if self._compact else 20,
            10 if self._compact else 18,
            12 if self._compact else 20,
            10 if self._compact else 18,
        )
        guidance_card_layout.setSpacing(8 if self._compact else 14)

        guidance_top = QWidget(self.guidance_card)
        guidance_top_layout = QHBoxLayout(guidance_top)
        guidance_top_layout.setContentsMargins(0, 0, 0, 0)
        guidance_top_layout.setSpacing(10 if self._compact else 12)

        self.guidance_section_title = QLabel("Wellness Guidance", guidance_top)
        self.guidance_section_title.setObjectName("SectionTitle")
        self.guidance_status_chip = QLabel("Wellness Guidance", guidance_top)
        self.guidance_status_chip.setObjectName("HeaderChip")
        self.guidance_status_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.guidance_status_chip.hide()

        guidance_top_layout.addWidget(self.guidance_section_title)
        guidance_top_layout.addStretch(1)
        guidance_top_layout.addWidget(self.guidance_status_chip)

        self.guidance_intro = QLabel("A clear next-step summary for the active session will appear here.", self.guidance_card)
        self.guidance_intro.setWordWrap(True)
        self.guidance_intro.setMaximumHeight(40 if self._compact else 72)

        self.guidance_primary_card = QFrame(self.guidance_card)
        self.guidance_primary_card.setObjectName("GuidanceBlock")
        self.guidance_primary_card.setMinimumHeight(54 if self._compact else 84)
        self.guidance_primary_card.setMaximumHeight(64 if self._compact else 104)

        gp_layout = QVBoxLayout(self.guidance_primary_card)
        gp_layout.setContentsMargins(14 if self._compact else 16, 12 if self._compact else 14, 14 if self._compact else 16, 12 if self._compact else 14)
        gp_layout.setSpacing(6 if self._compact else 8)

        self.guidance_primary_title = QLabel("Top Priority", self.guidance_primary_card)
        self.guidance_primary_title.setObjectName("SectionTitle")
        self.guidance_primary_text = QLabel("Awaiting active session guidance.", self.guidance_primary_card)
        self.guidance_primary_text.setWordWrap(True)
        gp_layout.addWidget(self.guidance_primary_title)
        gp_layout.addWidget(self.guidance_primary_text)

        self.guidance_steps_card = QFrame(self.guidance_card)
        self.guidance_steps_card.setObjectName("GuidanceBlock")
        self.guidance_steps_card.setMinimumHeight(72 if self._compact else 118)
        self.guidance_steps_card.setMaximumHeight(82 if self._compact else 142)

        gs_layout = QVBoxLayout(self.guidance_steps_card)
        gs_layout.setContentsMargins(14 if self._compact else 16, 12 if self._compact else 14, 14 if self._compact else 16, 12 if self._compact else 14)
        gs_layout.setSpacing(4 if self._compact else 6)

        self.guidance_steps_title = QLabel("Recommended Steps", self.guidance_steps_card)
        self.guidance_steps_title.setObjectName("SectionTitle")
        self.guidance_step_1 = QLabel("1. Review the active finding.", self.guidance_steps_card)
        self.guidance_step_2 = QLabel("2. Choose the appropriate handoff path.", self.guidance_steps_card)
        self.guidance_step_3 = QLabel("3. Save or share the result if needed.", self.guidance_steps_card)
        for _step in (self.guidance_step_1, self.guidance_step_2, self.guidance_step_3):
            _step.setWordWrap(False)

        gs_layout.addWidget(self.guidance_steps_title)
        gs_layout.addWidget(self.guidance_step_1)
        gs_layout.addWidget(self.guidance_step_2)
        gs_layout.addWidget(self.guidance_step_3)

        guidance_card_layout.addWidget(guidance_top)
        guidance_card_layout.addWidget(self.guidance_intro)
        guidance_card_layout.addWidget(self.guidance_primary_card)
        guidance_card_layout.addWidget(self.guidance_steps_card)

        self.guidance_action_row = QWidget(self.guidance_page)
        self.guidance_action_grid = QGridLayout(self.guidance_action_row)
        self.guidance_action_grid.setContentsMargins(0, 0, 0, 0)
        self.guidance_action_grid.setHorizontalSpacing(6 if self._compact else 10)
        self.guidance_action_grid.setVerticalSpacing(8 if self._compact else 10)

        self.guidance_back_button = self._create_button("Back", variant="secondary", min_width=112 if self._compact else 140, parent=self.guidance_action_row)
        self.guidance_back_button.setObjectName("BackButton")
        self.guidance_back_button.clicked.connect(self._exit_guidance_page)

        self.guidance_results_button = self._create_button("Results", variant="secondary", min_width=112 if self._compact else 140, parent=self.guidance_action_row)
        self.guidance_results_button.clicked.connect(self._handle_back_clicked)

        self.guidance_qr_button = self._create_button("QR", variant="ghost", min_width=112 if self._compact else 140, parent=self.guidance_action_row)
        self.guidance_qr_button.clicked.connect(self._handle_qr_clicked)

        self.guidance_report_button = self._create_button("Report", variant="ghost", min_width=112 if self._compact else 140, parent=self.guidance_action_row)
        self.guidance_report_button.clicked.connect(self._handle_report_clicked)

        for _btn in (self.guidance_back_button, self.guidance_results_button, self.guidance_qr_button, self.guidance_report_button):
            try:
                _btn.setMinimumHeight(32 if self._compact else 42)
                _btn.setMaximumHeight(32 if self._compact else 42)
                _btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            except Exception:
                pass

        self.guidance_action_grid.addWidget(self.guidance_back_button, 0, 0, 1, 1)
        self.guidance_action_grid.addWidget(self.guidance_results_button, 0, 1, 1, 1)
        self.guidance_action_grid.addWidget(self.guidance_qr_button, 0, 2, 1, 1)
        self.guidance_action_grid.addWidget(self.guidance_report_button, 0, 3, 1, 1)

        for _col in range(4):
            self.guidance_action_grid.setColumnStretch(_col, 1)

        guidance_root.addWidget(self.guidance_card, 1)
        guidance_root.addWidget(self.guidance_action_row, 0)

        root.addWidget(self.top_bar)
        root.addWidget(self.header_card)
        root.addWidget(self.content_row, 1)
        root.addWidget(self.action_row)
        root.addWidget(self.guidance_page, 1)

    def _layout_action_buttons(self) -> None:
        while self.action_grid.count():
            item = self.action_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(self.action_row)

        placements = [
            (0, 0, 1, 1),
            (0, 1, 1, 1),
            (0, 2, 1, 1),
            (0, 3, 1, 1),
            (0, 4, 1, 1),
        ]

        for col in range(5):
            self.action_grid.setColumnStretch(col, 1)

        for button, (row, col, row_span, col_span) in zip(self._bottom_buttons, placements):
            self.action_grid.addWidget(button, row, col, row_span, col_span)

    def _create_button(self, text: str, *, variant: str, min_width: int, parent: QWidget) -> QWidget:
        if AnimatedButton is not None:
            try:
                variant_map = {
                    "primary": getattr(AnimatedButton, "VARIANT_PRIMARY", None),
                    "secondary": getattr(AnimatedButton, "VARIANT_SECONDARY", None),
                    "ghost": getattr(AnimatedButton, "VARIANT_GHOST", None),
                    "success": getattr(AnimatedButton, "VARIANT_SUCCESS", None),
                }
                btn = AnimatedButton(
                    text=text,
                    variant=variant_map.get(variant),
                    size=getattr(AnimatedButton, "SIZE_MD", None),
                    minimum_width=min_width,
                )
                return btn
            except Exception:
                pass

        button = QPushButton(text, parent)
        button.setMinimumWidth(min_width)
        button.setMinimumHeight(34 if self._compact else 40)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            """
            QPushButton {
                color: #F6FCFF;
                border: 1px solid rgba(157, 220, 255, 0.26);
                border-radius: 14px;
                padding: 8px 12px;
                font-size: 11px;
                font-weight: 700;
                background: rgba(22, 47, 82, 0.78);
            }
            QPushButton:hover {
                background: rgba(34, 66, 110, 0.90);
                border-color: rgba(186, 233, 255, 0.40);
            }
            QPushButton:disabled {
                color: rgba(220, 236, 246, 0.48);
                background: rgba(20, 38, 62, 0.55);
            }
            """
        )
        return button

    def _set_label_pixmap(self, label: QLabel, pixmap: QPixmap, target_height: int) -> None:
        if pixmap.isNull():
            label.clear()
            return

        scaled = pixmap.scaledToHeight(
            target_height,
            Qt.TransformationMode.SmoothTransformation,
        )
        label.setPixmap(scaled)

    # =========================================================================
    # Effects / styles
    # =========================================================================

    def _setup_effects(self) -> None:
        self.header_opacity = QGraphicsOpacityEffect(self.header_card)
        self.header_card.setGraphicsEffect(self.header_opacity)
        self.header_opacity.setOpacity(0.0)

        self.content_opacity = QGraphicsOpacityEffect(self.content_row)
        self.content_row.setGraphicsEffect(self.content_opacity)
        self.content_opacity.setOpacity(0.0)

        self.entry_group = QParallelAnimationGroup(self)

        self.header_fade = QPropertyAnimation(self.header_opacity, b"opacity", self)
        self.header_fade.setDuration(360)
        self.header_fade.setStartValue(0.0)
        self.header_fade.setEndValue(1.0)
        self.header_fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.content_fade = QPropertyAnimation(self.content_opacity, b"opacity", self)
        self.content_fade.setDuration(520)
        self.content_fade.setStartValue(0.0)
        self.content_fade.setEndValue(1.0)
        self.content_fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.entry_group.addAnimation(self.header_fade)
        self.entry_group.addAnimation(self.content_fade)

        if _HAS_GLOW_LABEL and isinstance(self.hero_title, GlowLabel):
            try:
                self.hero_title.set_glow_color("#43D9FF")
                self.hero_title.set_text_color("#F5FCFF")
            except Exception:
                pass

    def _apply_styles(self) -> None:
        top_title_size = 14 if self._compact else 15
        pill_font_size = 10
        chip_font_size = 9
        section_title_size = 12
        hero_title_size = 20 if self._compact else 24
        hero_subtitle_size = 11
        summary_banner_size = 10

        self.setStyleSheet(
            f"""
            QFrame#ConsultScreen {{
                background: transparent;
            }}

            QPushButton#BackButton {{
                color: #F6FCFF;
                font-size: 14px;
                font-weight: 800;
                border-radius: 18px;
                border: 1px solid rgba(157, 220, 255, 0.34);
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(74, 160, 255, 0.98),
                    stop:1 rgba(34, 118, 236, 0.98)
                );
                padding: 10px 16px;
            }}
            QPushButton#BackButton:hover {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(90, 176, 255, 1.0),
                    stop:1 rgba(43, 128, 245, 1.0)
                );
            }}

            QLabel#LogoLabel {{
                min-width: {36 if self._compact else 42}px;
                max-width: {36 if self._compact else 42}px;
                min-height: {36 if self._compact else 42}px;
                max-height: {36 if self._compact else 42}px;
                background: transparent;
                border: none;
            }}

            QLabel#TopTitle {{
                color: #F6FCFF;
                font-size: {top_title_size}px;
                font-weight: 900;
                background: transparent;
            }}

            QLabel#RuntimePill {{
                color: #EEF9FF;
                font-size: {pill_font_size}px;
                font-weight: 700;
                border: 1px solid rgba(157, 220, 255, 0.22);
                border-radius: {12 if self._compact else 14}px;
                background: rgba(18, 39, 70, 0.56);
                padding: {5 if self._compact else 6}px {8 if self._compact else 10}px;
            }}

            QFrame#ConsultHeaderCard {{
                border: 1px solid rgba(170, 230, 255, 0.20);
                border-radius: {18 if self._compact else 22}px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(16, 34, 60, 0.80),
                    stop:1 rgba(8, 22, 44, 0.88)
                );
            }}

            QLabel#HeaderChip {{
                color: #EEF9FF;
                font-size: {chip_font_size}px;
                font-weight: 800;
                border: 1px solid rgba(157, 220, 255, 0.22);
                border-radius: {11 if self._compact else 12}px;
                background: rgba(28, 56, 91, 0.42);
                padding: 4px 9px;
            }}

            QFrame#InfoCard {{
                border: 1px solid rgba(170, 230, 255, 0.20);
                border-radius: {18 if self._compact else 22}px;
                background: rgba(12, 28, 50, 0.74);
            }}

            QFrame#GuidanceBlock {{
                border: 1px solid rgba(170, 230, 255, 0.18);
                border-radius: {16 if self._compact else 18}px;
                background: rgba(14, 30, 54, 0.70);
            }}

            QLabel#SectionTitle {{
                color: #F4FCFF;
                font-size: {section_title_size}px;
                font-weight: 800;
                background: transparent;
            }}
            """
        )

        if _HAS_GLOW_LABEL and isinstance(self.hero_title, GlowLabel):
            try:
                self.hero_title.set_text("Consultation and next-step guidance")
            except Exception:
                self.hero_title.setText("Consultation and next-step guidance")
        else:
            self.hero_title.setText("Consultation and next-step guidance")

        self.hero_subtitle.setText(
            "Review the active parameters and provide simple consultation advice for the next step."
        )
        self.summary_banner.setText(
            "Use the measured values below to give general follow-up guidance for the current session."
        )

        self.hero_title.setStyleSheet(
            f"""
            QLabel {{
                color: #F6FCFF;
                font-size: {hero_title_size}px;
                font-weight: 900;
                background: transparent;
            }}
            """
        )
        self.hero_subtitle.setStyleSheet(
            f"""
            QLabel {{
                color: rgba(219, 237, 249, 0.90);
                font-size: {hero_subtitle_size}px;
                font-weight: 500;
                background: transparent;
            }}
            """
        )
        self.summary_banner.setStyleSheet(
            f"""
            QLabel {{
                color: rgba(207, 229, 244, 0.88);
                font-size: {summary_banner_size}px;
                font-weight: 600;
                background: transparent;
            }}
            """
        )

        info_text_style = f"""
            QLabel {{
                color: rgba(214, 235, 248, 0.86);
                font-size: {9 if self._compact else 10}px;
                font-weight: 500;
                background: transparent;
            }}
        """
        for widget in (
            self.finding_1,
            self.finding_2,
            self.finding_3,
            self.finding_4,
            self.finding_5,
            self.finding_6,
            self.findings_note,
            self.context_mode_line,
            self.context_metrics_line,
            self.context_report_line,
            self.context_qr_line,
            self.context_note,
            self.actions_text,
            self.urgent_text,
        ):
            widget.setStyleSheet(info_text_style)

        guidance_body_style = f"""
            QLabel {{
                color: rgba(229, 242, 252, 0.96);
                font-size: {11 if self._compact else 12}px;
                font-weight: 600;
                background: transparent;
            }}
        """
        guidance_step_style = f"""
            QLabel {{
                color: rgba(224, 239, 250, 0.94);
                font-size: {10 if self._compact else 11}px;
                font-weight: 500;
                background: transparent;
            }}
        """
        self.guidance_intro.setStyleSheet(guidance_body_style)
        self.guidance_primary_text.setStyleSheet(guidance_body_style)
        self.guidance_step_1.setStyleSheet(guidance_step_style)
        self.guidance_step_2.setStyleSheet(guidance_step_style)
        self.guidance_step_3.setStyleSheet(guidance_step_style)

        self._set_button_accent(self.back_button, "#39D8FF")
        self._set_button_accent(self.guidance_back_button, "#39D8FF")

        self._apply_compact_layout_state()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        try:
            self._layout_action_buttons()
        except Exception:
            pass

    def _apply_compact_layout_state(self) -> None:
        self.top_title.setText("Consult Guidance")
        self.report_pill.setVisible(not self._ultra_compact)
        self.hero_subtitle.setVisible(not self._ultra_compact)

        self.header_chip_row.hide()
        self.overall_chip.hide()
        self.source_chip.hide()
        self.followup_chip.hide()
        self.guidance_status_chip.hide()

        self.findings_note.setVisible(not self._ultra_compact)
        self.context_note.setVisible(not self._ultra_compact)
        self.context_report_line.setVisible(not self._ultra_compact)
        self.context_qr_line.setVisible(not self._ultra_compact)

        if self._compact:
            self.right_column.hide()
            self.context_card.hide()
            self.actions_card.hide()
            self.urgent_card.hide()
            self.findings_note.setVisible(False)
            self.context_note.setVisible(False)
            self.context_report_line.setVisible(False)
            self.context_qr_line.setVisible(False)
            self.summary_card.footer_note.setVisible(False)
            self.summary_card.setMinimumHeight(106)
            self.summary_card.setMaximumHeight(118)
            self.findings_card.setMinimumHeight(96)
            self.findings_card.setMaximumHeight(108)
            self.finding_4.setVisible(False)
            self.guidance_intro.setMaximumHeight(36)
            self.guidance_primary_card.setMinimumHeight(54)
            self.guidance_primary_card.setMaximumHeight(64)
            self.guidance_steps_card.setMinimumHeight(72)
            self.guidance_steps_card.setMaximumHeight(82)
        else:
            self.right_column.show()
            self.context_card.show()
            self.actions_card.show()
            self.urgent_card.show()
            self.summary_card.footer_note.setVisible(True)
            self.summary_card.setMinimumHeight(176)
            self.summary_card.setMaximumHeight(214)
            self.findings_card.setMinimumHeight(168)
            self.findings_card.setMaximumHeight(220)
            self.finding_4.setVisible(True)
            self.guidance_intro.setMaximumHeight(72)
            self.guidance_primary_card.setMinimumHeight(70)
            self.guidance_primary_card.setMaximumHeight(86)
            self.guidance_steps_card.setMinimumHeight(100)
            self.guidance_steps_card.setMaximumHeight(118)

        try:
            self.qr_button.setText("Open QR" if self._compact else "Open QR Screen")
            self.report_button.setText("PDF Report" if self._compact else "Prepare PDF")
            self.retake_button.setText("Retake" if self._compact else "New Checkup")
            self.refresh_button.setText("Refresh" if self._compact else "Refresh Consult")
            self.results_button.setText("Results" if self._compact else "Back to Results")
            self.bottom_qr_button.setText("QR" if self._compact else "QR Handoff")
            self.bottom_report_button.setText("Report" if self._compact else "Prepare PDF")
            self.bottom_urgent_button.setText("Guidance" if self._compact else self.bottom_urgent_button.text())
        except Exception:
            pass

        self._layout_action_buttons()

    def _sync_header_for_current_page(self) -> None:
        if self._guidance_page_active:
            self.top_title.setText("Guidance")
            if _HAS_GLOW_LABEL and isinstance(self.hero_title, GlowLabel):
                try:
                    self.hero_title.set_text("Wellness Guidance")
                except Exception:
                    self.hero_title.setText("Wellness Guidance")
            else:
                self.hero_title.setText("Wellness Guidance")
            self.hero_subtitle.setText("Clear follow-up steps based on the current measured parameters.")
            self.summary_banner.setText("Use these parameter-based steps as a simple follow-up guide for the current session.")
            if self._compact:
                self.header_card.setMinimumHeight(104)
                self.header_card.setMaximumHeight(116)
        else:
            self.top_title.setText("Consult Guidance")
            if _HAS_GLOW_LABEL and isinstance(self.hero_title, GlowLabel):
                try:
                    self.hero_title.set_text("Consultation and next-step guidance")
                except Exception:
                    self.hero_title.setText("Consultation and next-step guidance")
            else:
                self.hero_title.setText("Consultation and next-step guidance")
            self.hero_subtitle.setText("Review the active parameters and provide simple consultation advice for the next step.")
            self.summary_banner.setText(
                safe_str(dict(self._payload or {}).get("consult_guidance", {}).get("highlighted_finding"), "").strip()
                or "Review the active session and choose the most appropriate follow-up step."
            )
            if self._compact:
                self.header_card.setMinimumHeight(116)
                self.header_card.setMaximumHeight(128)

    def _update_page_visibility(self) -> None:
        self.content_row.setVisible(not self._guidance_page_active)
        self.action_row.setVisible(not self._guidance_page_active)
        self.guidance_page.setVisible(self._guidance_page_active)
        self._sync_header_for_current_page()

    def _handle_guidance_clicked(self) -> None:
        self._guidance_page_active = True
        self._update_page_visibility()

    def _exit_guidance_page(self) -> None:
        self._guidance_page_active = False
        self._update_page_visibility()

    # =========================================================================
    # Lifecycle
    # =========================================================================

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._play_entry_animation()
        self.reload_consult()

    def _play_entry_animation(self) -> None:
        try:
            self.entry_group.start()
        except Exception:
            pass

    # =========================================================================
    # Loading / integration
    # =========================================================================

    def reload_consult(self) -> None:
        payload = self._load_payload()
        guidance = self._build_consult_guidance(payload)

        self._payload = dict(payload)
        self._payload["consult_guidance"] = dict(guidance)
        self._mode = safe_str(self._payload.get("mode"), self._read_current_mode()).strip().lower() or self._read_current_mode()
        self._qr_path = safe_str(self._payload.get("qr_path"), "").strip()
        self._report_path = safe_str(self._payload.get("report_path"), "").strip()

        self._persist_payload()
        self._apply_payload_to_ui()
        self.consult_loaded.emit(dict(self._payload))
        self.refresh_requested.emit()

    def set_payload(self, payload: Mapping[str, Any]) -> None:
        loaded = dict(payload or {})
        guidance = self._build_consult_guidance(loaded)

        self._payload = dict(loaded)
        self._payload["consult_guidance"] = dict(guidance)
        self._mode = safe_str(self._payload.get("mode"), self._read_current_mode()).strip().lower() or self._read_current_mode()
        self._qr_path = safe_str(self._payload.get("qr_path"), "").strip()
        self._report_path = safe_str(self._payload.get("report_path"), "").strip()

        self._persist_payload()
        self._apply_payload_to_ui()

    def _read_current_mode(self) -> str:
        mode = MODE_DEMO

        try:
            if self.app_state is not None:
                for attr_name in ("current_mode", "mode", "selected_mode"):
                    attr = getattr(self.app_state, attr_name, None)
                    if isinstance(attr, str) and attr.strip():
                        mode = attr.strip().lower()
                        break
                    if callable(attr):
                        result = attr()
                        if isinstance(result, str) and result.strip():
                            mode = result.strip().lower()
                            break
        except Exception:
            pass

        try:
            mode_service = self.services.get("mode_service") or self.services.get("mode")
            if mode_service is not None:
                for method_name in ("current_mode", "get_mode", "mode"):
                    method = getattr(mode_service, method_name, None)
                    if callable(method):
                        result = method()
                        result_text = safe_str(result, "").strip().lower()
                        if result_text:
                            mode = result_text
                            break
        except Exception:
            pass

        if mode not in {MODE_DEMO, MODE_HARDWARE}:
            mode = MODE_DEMO
        return mode

    def _load_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}

        try:
            session_service = self.services.get("session_service") or self.services.get("session")
            if session_service is not None:
                for method_name in (
                    "get_results_payload",
                    "get_current_session",
                    "get_session_payload",
                    "current_session_payload",
                    "get_latest_results_payload",
                    "get_consult_payload",
                ):
                    method = getattr(session_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method()
                            if isinstance(raw, Mapping):
                                payload = dict(raw)
                                if payload:
                                    break
                        except Exception:
                            continue
        except Exception:
            pass

        if not payload:
            try:
                if self.app_state is not None:
                    for attr_name in ("results_payload", "current_session_payload", "session_payload", "consult_payload"):
                        attr = getattr(self.app_state, attr_name, None)
                        if isinstance(attr, Mapping):
                            payload = dict(attr)
                            if payload:
                                break
            except Exception:
                pass

        measurements = payload.get("measurements", {})
        if not isinstance(measurements, Mapping):
            measurements = {}

        normalized_measurements = {
            METRIC_TEMPERATURE: measurements.get(METRIC_TEMPERATURE, measurements.get("temp", measurements.get("body_temperature"))),
            METRIC_SPO2: measurements.get(METRIC_SPO2, measurements.get("oxygen_saturation")),
            METRIC_PULSE: measurements.get(METRIC_PULSE, measurements.get("pulse", measurements.get("heart_rate", measurements.get("bpm")))),
            METRIC_RR: measurements.get(METRIC_RR, measurements.get("rr", measurements.get("respiration_rate"))),
            METRIC_WEIGHT: measurements.get(METRIC_WEIGHT, measurements.get("weight_kg")),
            METRIC_HEIGHT: measurements.get(METRIC_HEIGHT, measurements.get("height_cm", measurements.get("height_mm", measurements.get("height_m")))),
            METRIC_BMI: measurements.get(METRIC_BMI),
        }

        raw_height = normalized_measurements.get(METRIC_HEIGHT)
        if raw_height not in (None, ""):
            height_numeric = safe_float(raw_height, 0.0)
            if height_numeric > 300:
                normalized_measurements[METRIC_HEIGHT] = round(height_numeric / 10.0, 1)
            elif 0 < height_numeric < 3.5:
                normalized_measurements[METRIC_HEIGHT] = round(height_numeric * 100.0, 1)

        if normalized_measurements.get(METRIC_BMI) in (None, ""):
            normalized_measurements[METRIC_BMI] = _compute_bmi(
                None if normalized_measurements.get(METRIC_WEIGHT) in (None, "") else safe_float(normalized_measurements.get(METRIC_WEIGHT), 0.0),
                None if normalized_measurements.get(METRIC_HEIGHT) in (None, "") else safe_float(normalized_measurements.get(METRIC_HEIGHT), 0.0),
            )

        payload.setdefault("mode", self._read_current_mode())
        payload["measurements"] = normalized_measurements
        payload.setdefault("classifications", {})
        payload.setdefault("summary", {})
        payload.setdefault("qr_path", self._load_qr_path_from_services())
        payload.setdefault("report_path", self._load_report_path_from_services())

        classifications = payload.get("classifications", {})
        if not isinstance(classifications, Mapping) or not classifications:
            fallback_classifications = {}
            for metric_key, value in normalized_measurements.items():
                fallback_classifications[metric_key] = _default_metric_classification(metric_key, value)
            payload["classifications"] = fallback_classifications
        else:
            normalized_classifications: Dict[str, Dict[str, Any]] = {}
            for key, value in dict(classifications).items():
                if isinstance(value, Mapping):
                    item = dict(value)
                    severity = safe_str(item.get("severity"), "unknown").strip().lower() or "unknown"
                    item.setdefault("accent_hex", _severity_accent(severity))
                    item.setdefault("label", "Review")
                    item.setdefault("summary", "Result interpreted.")
                    normalized_classifications[safe_str(key, "")] = item
            payload["classifications"] = normalized_classifications

        return payload

    def _load_qr_path_from_services(self) -> str:
        qr_path = ""

        try:
            session_service = self.services.get("session_service") or self.services.get("session")
            if session_service is not None:
                for method_name in ("get_qr_path", "qr_path", "current_qr_path"):
                    method = getattr(session_service, method_name, None)
                    if callable(method):
                        try:
                            result = method()
                            qr_path = safe_str(result, "").strip()
                            if qr_path:
                                return qr_path
                        except Exception:
                            continue
        except Exception:
            pass

        try:
            if self.app_state is not None:
                attr = getattr(self.app_state, "qr_path", None)
                if isinstance(attr, str) and attr.strip():
                    qr_path = attr.strip()
        except Exception:
            pass

        return qr_path

    def _load_report_path_from_services(self) -> str:
        report_path = ""

        try:
            session_service = self.services.get("session_service") or self.services.get("session")
            if session_service is not None:
                for method_name in ("get_report_path", "report_path", "current_report_path"):
                    method = getattr(session_service, method_name, None)
                    if callable(method):
                        try:
                            result = method()
                            report_path = safe_str(result, "").strip()
                            if report_path:
                                return report_path
                        except Exception:
                            continue
        except Exception:
            pass

        try:
            if self.app_state is not None:
                attr = getattr(self.app_state, "report_path", None)
                if isinstance(attr, str) and attr.strip():
                    report_path = attr.strip()
        except Exception:
            pass

        return report_path

    def _prepare_report(self) -> str:
        report_path = ""

        try:
            report_service = self.services.get("report_service") or self.services.get("report")
            if report_service is not None:
                for method_name in (
                    "generate_report",
                    "create_report",
                    "build_report",
                    "generate_pdf_report",
                    "create_pdf_report",
                    "export_report",
                ):
                    method = getattr(report_service, method_name, None)
                    if callable(method):
                        try:
                            result = method(dict(self._payload))
                            if isinstance(result, Mapping):
                                report_path = safe_str(result.get("path", result.get("file_path", "")), "").strip()
                            else:
                                report_path = safe_str(result, "").strip()
                            if report_path:
                                break
                        except Exception:
                            continue
        except Exception:
            pass

        self._report_path = report_path
        self._payload["report_path"] = self._report_path
        self._persist_payload()
        return self._report_path

    def _generate_qr_from_payload(self, payload: Mapping[str, Any]) -> str:
        qr_path = ""

        try:
            qr_service = self.services.get("qr_service") or self.services.get("qr")
            if qr_service is not None:
                for method_name in (
                    "generate_qr",
                    "create_qr",
                    "build_qr",
                    "generate_session_qr",
                    "create_session_qr",
                ):
                    method = getattr(qr_service, method_name, None)
                    if callable(method):
                        try:
                            result = method(dict(payload))
                            if isinstance(result, Mapping):
                                qr_path = safe_str(result.get("path", result.get("file_path", "")), "").strip()
                            else:
                                qr_path = safe_str(result, "").strip()
                            if qr_path:
                                break
                        except Exception:
                            continue
        except Exception:
            pass

        return qr_path

    def _persist_payload(self) -> None:
        try:
            session_service = self.services.get("session_service") or self.services.get("session")
            if session_service is not None:
                for method_name in (
                    "set_consult_payload",
                    "update_consult_payload",
                    "set_results_payload",
                    "update_results_payload",
                    "set_qr_path",
                    "update_qr_path",
                    "set_report_path",
                    "update_report_path",
                ):
                    method = getattr(session_service, method_name, None)
                    if callable(method):
                        try:
                            if "consult_payload" in method_name:
                                method(dict(self._payload))
                            elif "results_payload" in method_name:
                                method(dict(self._payload))
                            elif "qr_path" in method_name and self._qr_path:
                                method(self._qr_path)
                            elif "report_path" in method_name and self._report_path:
                                method(self._report_path)
                        except Exception:
                            continue
        except Exception:
            pass

        try:
            if self.app_state is not None:
                if hasattr(self.app_state, "consult_payload"):
                    setattr(self.app_state, "consult_payload", dict(self._payload))
                if hasattr(self.app_state, "results_payload"):
                    setattr(self.app_state, "results_payload", dict(self._payload))
                if self._qr_path and hasattr(self.app_state, "qr_path"):
                    setattr(self.app_state, "qr_path", self._qr_path)
                if self._report_path and hasattr(self.app_state, "report_path"):
                    setattr(self.app_state, "report_path", self._report_path)
        except Exception:
            pass

    # =========================================================================
    # Guidance construction
    # =========================================================================

    def _build_consult_guidance(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        measurements = payload.get("measurements", {})
        if not isinstance(measurements, Mapping):
            measurements = {}

        classifications = payload.get("classifications", {})
        if not isinstance(classifications, Mapping):
            classifications = {}

        ranked_items: List[Tuple[int, str, Dict[str, Any]]] = []
        for metric_key in (
            METRIC_TEMPERATURE,
            METRIC_SPO2,
            METRIC_PULSE,
            METRIC_RR,
            METRIC_BMI,
        ):
            item = classifications.get(metric_key, {})
            if not isinstance(item, Mapping):
                item = _default_metric_classification(metric_key, measurements.get(metric_key))
            severity = safe_str(item.get("severity"), "unknown").strip().lower()
            ranked_items.append((_severity_rank(severity), metric_key, dict(item)))

        ranked_items.sort(key=lambda x: x[0], reverse=True)

        def has(metric: str) -> bool:
            return measurements.get(metric) not in (None, "")

        temp = safe_float(measurements.get(METRIC_TEMPERATURE), 0.0)
        spo2 = safe_float(measurements.get(METRIC_SPO2), 0.0)
        pulse = safe_float(measurements.get(METRIC_PULSE), 0.0)
        rr = safe_float(measurements.get(METRIC_RR), 0.0)
        bmi = safe_float(measurements.get(METRIC_BMI), 0.0)

        highest_rank = ranked_items[0][0] if ranked_items else 0
        highest_metric = ranked_items[0][1] if ranked_items else ""
        highest_item = ranked_items[0][2] if ranked_items else {}

        generic_steps: List[str] = []
        findings: List[str] = []

        if has(METRIC_TEMPERATURE):
            if temp >= 39.0:
                findings.append("Temperature is very high and should be escalated quickly.")
                generic_steps.append("Keep the user at rest, encourage fluids if appropriate, and seek prompt professional review.")
            elif temp >= 37.5:
                findings.append("Temperature is above the normal range.")
                generic_steps.append("Advise rest, hydration, and a repeat check if the user had just been active.")
            elif temp < 36.0:
                findings.append("Temperature is below the normal range.")
                generic_steps.append("Repeat the temperature check and keep the user warm and still before reassessment.")
            else:
                findings.append("Body temperature is within a normal reference range.")

        if has(METRIC_SPO2):
            if spo2 < 90:
                findings.append("Blood oxygen saturation is critically low.")
                generic_steps.append("Limit exertion and move to urgent medical review without delay.")
            elif spo2 < 94:
                findings.append("Blood oxygen saturation is below the preferred healthy range.")
                generic_steps.append("Ask the user to rest, breathe calmly, and repeat the reading before deciding the next step.")
            elif spo2 < 96:
                findings.append("Blood oxygen saturation is slightly reduced.")
                generic_steps.append("Monitor the reading and repeat the scan if finger placement or motion could have affected the result.")
            else:
                findings.append("Blood oxygen saturation is within a healthy range.")

        if has(METRIC_PULSE):
            if pulse >= 120:
                findings.append("Pulse rate is very high.")
                generic_steps.append("Allow the user to sit quietly and arrange prompt review if the pulse remains high.")
            elif pulse >= 100:
                findings.append("Pulse rate is above the common resting range.")
                generic_steps.append("Repeat the pulse check after a short rest and avoid movement during measurement.")
            elif 0 < pulse < 60:
                findings.append("Pulse rate is below the common resting range.")
                generic_steps.append("Repeat the scan after the user rests and consider follow-up if the same pattern remains.")
            else:
                findings.append("Pulse rate is within the common adult resting range.")

        if has(METRIC_RR):
            if rr >= 24:
                findings.append("Respiratory rate is significantly elevated.")
                generic_steps.append("Encourage calm breathing, minimize activity, and use a higher-priority review path.")
            elif rr >= 20:
                findings.append("Respiratory rate is above the usual resting range.")
                generic_steps.append("Repeat the reading after the user rests and breathes normally.")
            elif 0 < rr < 12:
                findings.append("Respiratory rate is below the common resting range.")
                generic_steps.append("Repeat the check under calm conditions and observe for consistency.")
            else:
                findings.append("Respiratory rate is within the common adult resting range.")

        if has(METRIC_BMI):
            if bmi >= 30.0:
                findings.append("BMI is in the obese range.")
                generic_steps.append("Provide general advice on regular activity, healthy food choices, and routine wellness follow-up.")
            elif bmi >= 25.0:
                findings.append("BMI is in the overweight range.")
                generic_steps.append("Suggest healthy eating habits, daily movement, and later wellness review when appropriate.")
            elif 0 < bmi < 18.5:
                findings.append("BMI is below the healthy range.")
                generic_steps.append("Encourage balanced nutrition and routine follow-up if low BMI is a persistent pattern.")
            else:
                findings.append("BMI is within a healthy reference range.")

        clean_steps: List[str] = []
        seen = set()
        for step in generic_steps:
            key = step.strip().lower()
            if key and key not in seen:
                clean_steps.append(step.strip())
                seen.add(key)

        if highest_rank >= 4:
            overall_label = "Urgent Review"
            overall_severity = "critical"
            consult_title = "Immediate professional review is advised"
            consult_summary = (
                "One or more measured values are in a critical range. Keep the user calm, avoid delay, and use the urgent review path based on your approved workflow."
            )
            bullets = clean_steps[:3] or [
                "Keep the user seated and calm while you prepare the next step.",
                "Use QR or PDF handoff so the session can be reviewed quickly.",
                "Escalate according to the approved clinical or supervisory workflow.",
            ]
            emergency_text = (
                "This session includes a critical result. Treat the kiosk output as a prompt for urgent human review, not as a final diagnosis."
            )
        elif highest_rank >= 3:
            overall_label = "Professional Review Recommended"
            overall_severity = "warning"
            consult_title = "Follow-up review is recommended"
            consult_summary = (
                "Some values are outside a comfortable reference range. A prompt follow-up discussion or professional review is recommended, especially if symptoms are present."
            )
            bullets = clean_steps[:3] or [
                "Repeat the scan if movement or poor placement may have affected the reading.",
                "Review the abnormal metric on its detail screen before ending the session.",
                "Share the result by QR or PDF if follow-up review is needed.",
            ]
            emergency_text = (
                "This session is not automatically critical, but the flagged value should not be ignored if the same reading persists."
            )
        elif highest_rank >= 2:
            overall_label = "Monitor and Follow Up"
            overall_severity = "attention"
            consult_title = "Monitoring and repeat guidance"
            consult_summary = (
                "The session shows mild variation from preferred ranges. A calm repeat check and simple follow-up guidance are appropriate for most users."
            )
            bullets = clean_steps[:3] or [
                "Repeat the check after the user rests and remains still.",
                "Use the report or QR screen if a record is needed.",
                "Escalate only if the same pattern remains or symptoms are concerning.",
            ]
            emergency_text = (
                "Attention-level findings usually support repeat measurement and routine follow-up unless the user also has concerning symptoms."
            )
        elif measurements:
            overall_label = "Routine Wellness Guidance"
            overall_severity = "normal"
            consult_title = "General consultation advice"
            consult_summary = (
                "The captured values are generally reassuring. Provide simple wellness guidance, share the result if needed, and repeat the check only when the session conditions were not ideal."
            )
            bullets = clean_steps[:3] or [
                "Maintain hydration, regular sleep, and a balanced daily routine.",
                "Use the QR or PDF option if the user needs a record of the session.",
                "Retake the checkup later only if the first session was affected by movement or poor placement.",
            ]
            emergency_text = (
                "No strong urgency is suggested by the available measurements. Routine wellness guidance is appropriate for this session."
            )
        else:
            overall_label = "Limited Guidance"
            overall_severity = "unknown"
            consult_title = "No completed consultation guidance is available yet"
            consult_summary = (
                "The screen does not yet have enough completed session data to provide meaningful consultation guidance."
            )
            bullets = [
                "Complete a valid measurement session first.",
                "Refresh this screen after results are available.",
                "Generate QR or PDF only after the session has been captured properly.",
            ]
            emergency_text = (
                "Without a completed session, this screen should be treated as informational only."
            )

        accent_hex = _severity_accent(overall_severity)

        if not findings and measurements:
            findings.append("The session does not show a strongly concerning interpreted metric.")
        elif not findings:
            findings.append("No interpreted findings are available yet.")

        if highest_metric and highest_item and highest_rank > 0:
            highlighted = (
                f"Highest-priority finding: {_metric_title(highest_metric)} — "
                f"{safe_str(highest_item.get('summary'), '').strip()}"
            )
        else:
            highlighted = "No high-priority finding is currently available."

        available_count = 0
        for key in (
            METRIC_TEMPERATURE,
            METRIC_SPO2,
            METRIC_PULSE,
            METRIC_RR,
            METRIC_WEIGHT,
            METRIC_HEIGHT,
            METRIC_BMI,
        ):
            if measurements.get(key) not in (None, ""):
                available_count += 1

        return {
            "overall_label": overall_label,
            "overall_severity": overall_severity,
            "accent_hex": accent_hex,
            "consult_title": consult_title,
            "consult_summary": consult_summary,
            "bullets": bullets[:3],
            "findings": findings[:6],
            "highlighted_finding": highlighted,
            "emergency_text": emergency_text,
            "available_count": available_count,
        }

    # =========================================================================
    # UI application
    # =========================================================================

    def _apply_payload_to_ui(self) -> None:
        payload = dict(self._payload or {})
        measurements = payload.get("measurements", {})
        if not isinstance(measurements, Mapping):
            measurements = {}

        guidance = payload.get("consult_guidance", {})
        if not isinstance(guidance, Mapping):
            guidance = {}

        overall_label = safe_str(guidance.get("overall_label"), "Consult Review").strip() or "Consult Review"
        overall_severity = safe_str(guidance.get("overall_severity"), "unknown").strip().lower() or "unknown"
        accent_hex = safe_str(guidance.get("accent_hex"), _severity_accent(overall_severity)).strip() or _severity_accent(overall_severity)
        available_count = safe_int(guidance.get("available_count"), 0)

        qr_ready = bool(self._qr_path and Path(self._qr_path).exists())
        report_ready = bool(self._report_path and Path(self._report_path).exists())

        self._apply_mode_pill()

        self.urgency_pill.setText(overall_label)
        self.report_pill.setText("Report Ready" if report_ready else "Report Pending")
        self._apply_pill_style(self.urgency_pill, accent_hex)
        self._apply_pill_style(self.report_pill, "#42E393" if report_ready else "#FFD25E")

        # Hidden chips kept in sync but not shown
        self.overall_chip.setText(overall_label)
        self.source_chip.setText("Demo Session" if self._mode == MODE_DEMO else "Hardware Session")
        self.followup_chip.setText("QR and report handoff available")
        self._apply_header_chip_style(self.overall_chip, accent_hex)
        self._apply_header_chip_style(self.source_chip, "#67D8FF" if self._mode == MODE_DEMO else "#39D8FF")
        self._apply_header_chip_style(self.followup_chip, "#42E393" if qr_ready or report_ready else "#39D8FF")

        self.summary_banner.setText(
            safe_str(guidance.get("highlighted_finding"), "").strip()
            or "Review the active session and choose the most appropriate follow-up step."
        )

        self.summary_card.set_payload(
            title=safe_str(guidance.get("consult_title"), "Consultation Advice"),
            status_text=overall_label,
            summary=safe_str(guidance.get("consult_summary"), ""),
            bullets=guidance.get("bullets", []),
            accent_hex=accent_hex,
        )

        findings = guidance.get("findings", [])
        if not isinstance(findings, list):
            findings = []

        line_values = [safe_str(item, "").strip() for item in findings if safe_str(item, "").strip()]
        while len(line_values) < 6:
            line_values.append("")

        self.finding_1.setText(f"• {line_values[0]}" if line_values[0] else "")
        self.finding_2.setText(f"• {line_values[1]}" if line_values[1] else "")
        self.finding_3.setText(f"• {line_values[2]}" if line_values[2] else "")
        self.finding_4.setText(f"• {line_values[3]}" if line_values[3] else "")
        self.finding_5.setText(f"• {line_values[4]}" if line_values[4] else "")
        self.finding_6.setText(f"• {line_values[5]}" if line_values[5] else "")

        self.finding_1.setVisible(bool(line_values[0]))
        self.finding_2.setVisible(bool(line_values[1]))
        self.finding_3.setVisible(bool(line_values[2]))
        self.finding_4.setVisible(bool(line_values[3]))
        self.finding_5.setVisible(bool(line_values[4]))
        self.finding_6.setVisible(bool(line_values[5]))

        self.findings_note.setText(
            "These are general consultation findings generated from the current measured values and should be used as supportive guidance only."
        )

        self.context_mode_line.setText(f"Mode: {'Demo' if self._mode == MODE_DEMO else 'Hardware'}")
        self.context_metrics_line.setText(f"Captured metrics: {available_count}")
        self.context_report_line.setText(f"Report path: {self._report_path if self._report_path else 'Not prepared'}")
        self.context_qr_line.setText(f"QR path: {self._qr_path if self._qr_path else 'Not prepared'}")
        self.context_note.setText(
            "Refresh this screen after results, QR generation, or PDF generation changes."
        )

        self.urgent_text.setText(
            safe_str(guidance.get("emergency_text"), "").strip()
            or "Use your approved workflow for escalation or normal follow-up."
        )

        if overall_severity in {"critical", "warning"}:
            urgent_button_text = "Escalation Guidance"
        elif overall_severity == "attention":
            urgent_button_text = "Monitoring Guidance"
        else:
            urgent_button_text = "Wellness Guidance"

        try:
            self.urgent_button.setText(urgent_button_text)
            self.bottom_urgent_button.setText(urgent_button_text)
        except Exception:
            pass

        guidance_steps = guidance.get("bullets", [])
        if not isinstance(guidance_steps, list):
            guidance_steps = []
        guidance_steps = [safe_str(item, "").strip() for item in guidance_steps if safe_str(item, "").strip()]
        while len(guidance_steps) < 3:
            guidance_steps.append("")

        self.guidance_status_chip.setText(overall_label if overall_label else "Wellness Guidance")
        self._apply_header_chip_style(self.guidance_status_chip, accent_hex)
        self.guidance_intro.setText(
            safe_str(guidance.get("consult_summary"), "").strip()
            or "A clear next-step summary for the active session will appear here."
        )
        self.guidance_primary_text.setText(
            safe_str(guidance.get("highlighted_finding"), "").strip()
            or "No high-priority finding is currently available."
        )
        self.guidance_step_1.setText(f"1. {guidance_steps[0]}" if guidance_steps[0] else "1. Share the result using QR or PDF if a record is needed.")
        self.guidance_step_2.setText(f"2. {guidance_steps[1]}" if guidance_steps[1] else "2. Retake the checkup only if the session conditions were poor.")
        self.guidance_step_3.setText(f"3. {guidance_steps[2]}" if guidance_steps[2] else "3. Use detail screens for a metric-by-metric review when helpful.")

        self._set_button_accent(self.refresh_button, "#39D8FF")
        self._set_button_accent(self.results_button, "#67D8FF")
        self._set_button_accent(self.bottom_qr_button, "#39D8FF" if qr_ready else "#FFD25E")
        self._set_button_accent(self.qr_button, "#39D8FF" if qr_ready else "#FFD25E")
        self._set_button_accent(self.report_button, "#42E393" if report_ready else "#FFD25E")
        self._set_button_accent(self.bottom_report_button, "#42E393" if report_ready else "#FFD25E")
        self._set_button_accent(self.retake_button, "#67D8FF")
        self._set_button_accent(self.urgent_button, accent_hex)
        self._set_button_accent(self.bottom_urgent_button, accent_hex)
        self._set_button_accent(self.guidance_back_button, "#39D8FF")
        self._set_button_accent(self.guidance_results_button, "#67D8FF")
        self._set_button_accent(self.guidance_qr_button, "#39D8FF" if qr_ready else "#FFD25E")
        self._set_button_accent(self.guidance_report_button, "#42E393" if report_ready else "#FFD25E")

        self._apply_compact_layout_state()

    def _apply_mode_pill(self) -> None:
        if self._mode == MODE_DEMO:
            self.mode_pill.setText("Demo Mode")
            self._apply_pill_style(self.mode_pill, "#67D8FF")
        else:
            self.mode_pill.setText("Hardware Mode")
            self._apply_pill_style(self.mode_pill, "#39D8FF")

    def _apply_pill_style(self, label: QLabel, accent_hex: str) -> None:
        accent = QColor(accent_hex)
        label.setStyleSheet(
            f"""
            QLabel {{
                color: #EEF9FF;
                font-size: 10px;
                font-weight: 700;
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.34);
                border-radius: 14px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.15);
                padding: 6px 10px;
            }}
            """
        )

    def _apply_header_chip_style(self, label: QLabel, accent_hex: str) -> None:
        accent = QColor(accent_hex)
        label.setStyleSheet(
            f"""
            QLabel {{
                color: #EEF9FF;
                font-size: 9px;
                font-weight: 800;
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.34);
                border-radius: 12px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.16);
                padding: 4px 9px;
            }}
            """
        )

    def _set_button_accent(self, button: QWidget, accent_hex: str) -> None:
        if AnimatedButton is not None and hasattr(button, "set_accent_color"):
            try:
                button.set_accent_color(accent_hex)  # type: ignore[attr-defined]
                return
            except Exception:
                pass

        if isinstance(button, QPushButton):
            accent = QColor(accent_hex)
            button.setStyleSheet(
                f"""
                QPushButton {{
                    color: #F6FCFF;
                    border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.34);
                    border-radius: 14px;
                    padding: 10px 16px;
                    font-size: 12px;
                    font-weight: 700;
                    background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.16);
                }}
                QPushButton:hover {{
                    background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.24);
                    border-color: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.48);
                }}
                QPushButton:disabled {{
                    color: rgba(220, 236, 246, 0.48);
                    background: rgba(20, 38, 62, 0.55);
                }}
                """
            )

    # =========================================================================
    # Actions / navigation
    # =========================================================================

    def _handle_back_clicked(self) -> None:
        if self._guidance_page_active:
            self._exit_guidance_page()
            return
        if self._navigate_to(SCREEN_RESULTS):
            return
        self.back_requested.emit()

    def _handle_qr_clicked(self) -> None:
        if not self._qr_path:
            self._qr_path = self._generate_qr_from_payload(self._payload)
            self._payload["qr_path"] = self._qr_path
            self._persist_payload()
            self._apply_payload_to_ui()

        payload = dict(self._payload)
        payload["qr_path"] = self._qr_path

        if self._navigate_to(SCREEN_QR):
            self.qr_requested.emit(payload)
            return
        self.qr_requested.emit(payload)

    def _handle_report_clicked(self) -> None:
        self._prepare_report()
        self._apply_payload_to_ui()

        payload = dict(self._payload)
        payload["report_path"] = self._report_path
        self.report_requested.emit(payload)

    def _handle_new_checkup_clicked(self) -> None:
        if self._navigate_to(SCREEN_MEASURING):
            self.retake_requested.emit()
            return
        self.retake_requested.emit()

    def _handle_emergency_clicked(self) -> None:
        self.emergency_requested.emit(dict(self._payload))

    def _navigate_to(self, screen_name: str) -> bool:
        navigator = self.navigator
        if navigator is None:
            return False

        for method_name in ("go_to", "navigate_to", "navigate", "show_screen", "set_current_screen"):
            method = getattr(navigator, method_name, None)
            if callable(method):
                try:
                    method(screen_name)
                    return True
                except Exception:
                    continue
        return False

    # =========================================================================
    # Paint
    # =========================================================================

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect = self.rect()

        if not self._background_pixmap.isNull():
            scaled = self._background_pixmap.scaled(
                rect.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            draw_x = int((rect.width() - scaled.width()) / 2)
            draw_y = int((rect.height() - scaled.height()) / 2)
            painter.drawPixmap(draw_x, draw_y, scaled)

        painter.fillRect(rect, QColor(4, 14, 28, 176))
        painter.fillRect(QRectF(0, 0, rect.width(), rect.height() * 0.38), QColor(53, 214, 255, 16))
        painter.fillRect(QRectF(0, rect.height() * 0.60, rect.width(), rect.height() * 0.40), QColor(20, 82, 128, 18))

        painter.end()

    # =========================================================================
    # Diagnostics
    # =========================================================================

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "mode": self._mode,
            "qr_path": self._qr_path,
            "report_path": self._report_path,
            "payload_keys": list(self._payload.keys()),
            "background_path": self._background_path,
        }