"""
widgets/diagnosis_panel.py

Premium diagnosis summary panel for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the reusable diagnosis-focused composite widget used in:
    - diagnosis screen
    - results screen summary area
    - consult screen pre-summary
    - admin dashboard health-overview blocks
- It transforms diagnosis payloads into a polished, readable medical UI panel
- It is designed to work directly with outputs from:
    - services/diagnosis_service.py
    - services/health_rules_service.py
    - services/session_service.py
    - services/publish_service.py trend interpretation payloads
- It keeps the design language consistent with:
    - widgets/glass_card.py
    - widgets/animated_button.py
    - widgets/glow_label.py
    - widgets/status_card.py

Typical payloads supported:
1) Diagnosis payload
   {
       "status_title": "Needs Attention",
       "overall_severity": "warning",
       "summary": "Some measured parameters are outside the normal range.",
       "issue_labels": ["Low SpO₂", "Elevated Temperature"],
       "recommendations": ["Rest", "Retake measurement", "Consult clinician"],
       "consult_tips": ["Seek help if symptoms worsen"],
       "emergency_recommended": False,
       "emergency_number": "112",
       "health_index": {"score": 74, "label": "Moderate"},
       "metric_categories": {
           "spo2": {"label": "Low", "severity": "warning"},
           "temperature": {"label": "Mild Fever", "severity": "attention"}
       }
   }

2) Trend/status payload
   {
       "title": "Stable Trend",
       "summary": "...",
       "severity": "normal",
       "trend_issue_labels": [...]
   }

Design goals:
- premium futuristic blue medical presentation
- clear at-a-glance interpretation
- compact enough for 1024x600 kiosk layout
- safe defaults with partial payloads
- reusable without forcing a particular screen layout
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional

from PyQt6.QtCore import QEvent, QPoint, QPropertyAnimation, QEasingCurve, Qt, pyqtSignal, QRectF
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.logger import get_logger

try:
    from config import KIOSK_WIDTH, KIOSK_HEIGHT, IS_COMPACT_KIOSK
except Exception:  # pragma: no cover
    KIOSK_WIDTH = 800
    KIOSK_HEIGHT = 480
    IS_COMPACT_KIOSK = True


try:
    from core.utils import safe_float, safe_int, safe_str
except Exception:  # pragma: no cover
    def safe_str(value: Any, default: str = "") -> str:
        try:
            if value is None:
                return default
            return str(value)
        except Exception:
            return default

    def safe_int(value: Any, default: int = 0) -> int:
        try:
            if value is None or value == "":
                return default
            return int(float(value))
        except Exception:
            return default

    def safe_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None or value == "":
                return default
            return float(value)
        except Exception:
            return default

try:
    from core.constants import (
        SEVERITY_ATTENTION,
        SEVERITY_CRITICAL,
        SEVERITY_NORMAL,
        SEVERITY_UNKNOWN,
        SEVERITY_WARNING,
    )
except Exception:  # pragma: no cover
    SEVERITY_NORMAL = "normal"
    SEVERITY_ATTENTION = "attention"
    SEVERITY_WARNING = "warning"
    SEVERITY_CRITICAL = "critical"
    SEVERITY_UNKNOWN = "unknown"

from widgets.animated_button import AnimatedButton
from widgets.glass_card import GlassCard

try:
    from widgets.glow_label import GlowLabel
    _HAS_GLOW_LABEL = True
except Exception:  # pragma: no cover
    GlowLabel = QLabel  # type: ignore
    _HAS_GLOW_LABEL = False


logger = get_logger(__name__)


# ============================================================
# Theme
# ============================================================

@dataclass(frozen=True)
class DiagnosisPanelTheme:
    """
    Theme container for DiagnosisPanel.
    """
    headline_color: str = "#F6FCFF"
    summary_color: str = "rgba(220, 238, 250, 0.92)"
    section_title_color: str = "rgba(207, 229, 244, 0.86)"
    body_color: str = "rgba(226, 241, 251, 0.90)"
    subtle_text: str = "rgba(188, 212, 231, 0.82)"

    stat_value_color: str = "#F8FDFF"
    stat_label_color: str = "rgba(200, 224, 242, 0.82)"

    chip_text: str = "#F4FCFF"
    chip_bg_alpha: float = 0.16
    chip_border_alpha: float = 0.36

    strip_bg: str = "rgba(38, 65, 98, 0.16)"
    strip_border: str = "rgba(150, 214, 255, 0.18)"

    primary_accent: str = "#39D8FF"
    normal_accent: str = "#3FE28F"
    attention_accent: str = "#FFD25E"
    warning_accent: str = "#FFA14D"
    critical_accent: str = "#FF6E88"

    health_good_accent: str = "#43E39A"
    health_mid_accent: str = "#FFD35E"
    health_low_accent: str = "#FF7B92"


DEFAULT_DIAGNOSIS_PANEL_THEME = DiagnosisPanelTheme()


# ============================================================
# Main widget
# ============================================================

class DiagnosisPanel(GlassCard):
    """
    Premium composite diagnosis panel.

    Main capabilities:
    - status headline + severity chip
    - summary paragraph
    - health index score block
    - issue chips
    - recommendations and consult tips
    - top flagged metrics list
    - emergency strip
    - details / consult / report action buttons

    The widget is intentionally flexible so it can render both:
    - session diagnosis payloads
    - trend / interpretation payloads
    """

    details_requested = pyqtSignal()
    consult_requested = pyqtSignal()
    report_requested = pyqtSignal()
    emergency_requested = pyqtSignal()

    severity_changed = pyqtSignal(str)
    diagnosis_applied = pyqtSignal(dict)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        title: str = "Diagnosis Overview",
        subtitle: str = "Health interpretation and recommended actions",
        headline: str = "",
        summary: str = "",
        severity: str = SEVERITY_UNKNOWN,
        icon_path: str = "",
        footer: str = "",
        compact: bool = False,
        clickable: bool = False,
        show_metrics_section: bool = True,
        show_issue_section: bool = True,
        show_recommendation_section: bool = True,
        show_consult_section: bool = True,
        show_action_row: bool = True,
        show_health_index: bool = True,
        theme: Optional[DiagnosisPanelTheme] = None,
        minimum_height: int = 260,
    ) -> None:
        self._logger = logger.bind(component="DiagnosisPanel")

        self._theme = theme or DEFAULT_DIAGNOSIS_PANEL_THEME
        self._compact = bool(compact or IS_COMPACT_KIOSK)
        self._ultra_compact = bool(KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480)
        self._severity = safe_str(severity, SEVERITY_UNKNOWN).strip().lower() or SEVERITY_UNKNOWN

        self._headline = safe_str(headline, "").strip()
        self._summary = safe_str(summary, "").strip()

        self._issue_labels: List[str] = []
        self._recommendations: List[str] = []
        self._consult_tips: List[str] = []
        self._flagged_metrics: List[Dict[str, str]] = []

        self._health_index_score: Optional[int] = None
        self._health_index_label: str = ""
        self._emergency_recommended: bool = False
        self._emergency_number: str = ""

        self._show_metrics_section = bool(show_metrics_section)
        self._show_issue_section = bool(show_issue_section)
        self._show_recommendation_section = bool(show_recommendation_section)
        self._show_consult_section = bool(show_consult_section)
        self._show_action_row = bool(show_action_row)
        self._show_health_index = bool(show_health_index)

        self._hovered = False
        self._hover_anim: Optional[QPropertyAnimation] = None
        self._base_pos: Optional[QPoint] = None

        super().__init__(
            title=title,
            subtitle=subtitle,
            body="",
            footer=footer,
            icon_path=icon_path,
            parent=parent,
            accent_color=self._accent_for_severity(self._severity),
            minimum_height=(minimum_height if not self._compact else max(220 if not self._ultra_compact else 190, minimum_height - (32 if not self._ultra_compact else 58))),
            clickable=clickable,
            enable_hover_effect=True,
            show_accent_bar=True,
            compact=compact,
        )

        self._build_content()
        self.set_content_widget(self._content_root)

        self.clicked.connect(lambda: self.details_requested.emit())
        self._details_button.clicked.connect(self.details_requested.emit)
        self._consult_button.clicked.connect(self.consult_requested.emit)
        self._report_button.clicked.connect(self.report_requested.emit)
        self._emergency_button.clicked.connect(self.emergency_requested.emit)

        self._apply_style()
        self.set_headline(self._headline or self._default_headline_for_severity(self._severity))
        self.set_summary(self._summary)
        self.set_severity(self._severity)
        self._refresh_visibility()
        self._sync_compact_mode()

    # ========================================================
    # UI
    # ========================================================

    def _build_content(self) -> None:
        self._content_root = QWidget(self)
        self._content_root.setObjectName("DiagnosisPanelContentRoot")

        root = QVBoxLayout(self._content_root)
        root.setContentsMargins(0, 2 if not self._compact else (1 if not self._ultra_compact else 0), 0, 0)
        root.setSpacing(8 if not self._compact else (6 if not self._ultra_compact else 4))

        # ----------------------------------------------------
        # Top row: headline + severity chip + health index block
        # ----------------------------------------------------
        self._top_row = QWidget(self._content_root)
        top_layout = QHBoxLayout(self._top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(10 if not self._compact else (8 if not self._ultra_compact else 6))

        # Left headline column
        self._headline_column = QWidget(self._top_row)
        headline_layout = QVBoxLayout(self._headline_column)
        headline_layout.setContentsMargins(0, 0, 0, 0)
        headline_layout.setSpacing(4 if not self._compact else (3 if not self._ultra_compact else 2))

        self._headline_row = QWidget(self._headline_column)
        headline_row_layout = QHBoxLayout(self._headline_row)
        headline_row_layout.setContentsMargins(0, 0, 0, 0)
        headline_row_layout.setSpacing(8 if not self._compact else (6 if not self._ultra_compact else 4))

        if _HAS_GLOW_LABEL:
            self._headline_label = GlowLabel(
                role=GlowLabel.ROLE_STATUS if not self._compact else GlowLabel.ROLE_SUBTITLE,
                align_center=False,
                use_outline=False,
                enable_paint_glow=True,
                initial_glow_strength=0.52,
                initial_glow_blur=18 if not self._compact else (14 if not self._ultra_compact else 11),
            )
        else:
            self._headline_label = QLabel(self._headline_row)
            self._headline_label.setWordWrap(True)

        self._severity_chip = QLabel(self._headline_row)
        self._severity_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)

        headline_row_layout.addWidget(
            self._headline_label,
            1,
            alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        headline_row_layout.addWidget(
            self._severity_chip,
            0,
            alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )

        self._summary_label = QLabel(self._headline_column)
        self._summary_label.setWordWrap(True)
        self._summary_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        headline_layout.addWidget(self._headline_row)
        headline_layout.addWidget(self._summary_label)

        # Health index block
        self._health_block = QFrame(self._top_row)
        self._health_block.setObjectName("DiagnosisPanelHealthBlock")

        health_layout = QVBoxLayout(self._health_block)
        health_layout.setContentsMargins(
            10 if not self._compact else (8 if not self._ultra_compact else 6),
            8 if not self._compact else (6 if not self._ultra_compact else 5),
            10 if not self._compact else (8 if not self._ultra_compact else 6),
            8 if not self._compact else (6 if not self._ultra_compact else 5),
        )
        health_layout.setSpacing(1 if not self._compact else 0)

        if _HAS_GLOW_LABEL:
            self._health_score_label = GlowLabel(
                role=GlowLabel.ROLE_TITLE if not self._compact else GlowLabel.ROLE_STATUS,
                align_center=True,
                use_outline=False,
                enable_paint_glow=True,
                initial_glow_strength=0.46,
                initial_glow_blur=16 if not self._compact else (12 if not self._ultra_compact else 10),
            )
        else:
            self._health_score_label = QLabel(self._health_block)
            self._health_score_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._health_text_label = QLabel(self._health_block)
        self._health_text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        health_layout.addWidget(self._health_score_label)
        health_layout.addWidget(self._health_text_label)

        top_layout.addWidget(self._headline_column, 1)
        top_layout.addWidget(self._health_block, 0, alignment=Qt.AlignmentFlag.AlignTop)

        # ----------------------------------------------------
        # Metrics section
        # ----------------------------------------------------
        self._metrics_section = QWidget(self._content_root)
        metrics_layout = QVBoxLayout(self._metrics_section)
        metrics_layout.setContentsMargins(0, 0, 0, 0)
        metrics_layout.setSpacing(4 if not self._compact else (3 if not self._ultra_compact else 2))

        self._metrics_title = QLabel("Flagged Metrics", self._metrics_section)

        self._metrics_wrap = QWidget(self._metrics_section)
        self._metrics_layout = QHBoxLayout(self._metrics_wrap)
        self._metrics_layout.setContentsMargins(0, 0, 0, 0)
        self._metrics_layout.setSpacing(6 if not self._compact else (4 if not self._ultra_compact else 3))

        metrics_layout.addWidget(self._metrics_title)
        metrics_layout.addWidget(self._metrics_wrap)

        # ----------------------------------------------------
        # Issue section
        # ----------------------------------------------------
        self._issues_section = QWidget(self._content_root)
        issues_layout = QVBoxLayout(self._issues_section)
        issues_layout.setContentsMargins(0, 0, 0, 0)
        issues_layout.setSpacing(4 if not self._compact else (3 if not self._ultra_compact else 2))

        self._issues_title = QLabel("Detected Issues", self._issues_section)

        self._issues_wrap = QWidget(self._issues_section)
        self._issues_layout = QHBoxLayout(self._issues_wrap)
        self._issues_layout.setContentsMargins(0, 0, 0, 0)
        self._issues_layout.setSpacing(6 if not self._compact else (4 if not self._ultra_compact else 3))

        issues_layout.addWidget(self._issues_title)
        issues_layout.addWidget(self._issues_wrap)

        # ----------------------------------------------------
        # Recommendations section
        # ----------------------------------------------------
        self._recommendation_section = QWidget(self._content_root)
        rec_layout = QVBoxLayout(self._recommendation_section)
        rec_layout.setContentsMargins(0, 0, 0, 0)
        rec_layout.setSpacing(4 if not self._compact else (3 if not self._ultra_compact else 2))

        self._recommendation_title = QLabel("Recommendations", self._recommendation_section)

        self._recommendation_wrap = QWidget(self._recommendation_section)
        self._recommendation_layout = QVBoxLayout(self._recommendation_wrap)
        self._recommendation_layout.setContentsMargins(0, 0, 0, 0)
        self._recommendation_layout.setSpacing(3 if not self._compact else (2 if not self._ultra_compact else 1))

        rec_layout.addWidget(self._recommendation_title)
        rec_layout.addWidget(self._recommendation_wrap)

        # ----------------------------------------------------
        # Consult strip
        # ----------------------------------------------------
        self._consult_strip = QFrame(self._content_root)
        self._consult_strip.setObjectName("DiagnosisPanelConsultStrip")

        consult_layout = QHBoxLayout(self._consult_strip)
        consult_layout.setContentsMargins(
            10 if not self._compact else (8 if not self._ultra_compact else 6),
            7 if not self._compact else (6 if not self._ultra_compact else 5),
            10 if not self._compact else (8 if not self._ultra_compact else 6),
            7 if not self._compact else (6 if not self._ultra_compact else 5),
        )
        consult_layout.setSpacing(8 if not self._compact else (6 if not self._ultra_compact else 4))

        self._consult_dot = QLabel(self._consult_strip)
        self._consult_dot.setFixedSize(10 if not self._compact else (8 if not self._ultra_compact else 7), 10 if not self._compact else (8 if not self._ultra_compact else 7))

        self._consult_label = QLabel(self._consult_strip)
        self._consult_label.setWordWrap(True)

        self._emergency_button = AnimatedButton(
            text="Emergency",
            variant=AnimatedButton.VARIANT_DANGER,
            size=AnimatedButton.SIZE_SM,
            minimum_width=88 if not self._compact else (74 if not self._ultra_compact else 64),
        )

        consult_layout.addWidget(
            self._consult_dot,
            0,
            alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        consult_layout.addWidget(
            self._consult_label,
            1,
            alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        consult_layout.addWidget(
            self._emergency_button,
            0,
            alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )

        # ----------------------------------------------------
        # Actions
        # ----------------------------------------------------
        self._action_row = QWidget(self._content_root)
        action_layout = QHBoxLayout(self._action_row)
        action_layout.setContentsMargins(0, 2 if not self._compact else 0, 0, 0)
        action_layout.setSpacing(8 if not self._compact else (6 if not self._ultra_compact else 4))

        self._details_button = AnimatedButton(
            text=("View Details" if not self._ultra_compact else "Details"),
            variant=AnimatedButton.VARIANT_PRIMARY,
            size=AnimatedButton.SIZE_MD if not self._compact else AnimatedButton.SIZE_SM,
            minimum_width=108 if not self._compact else (88 if not self._ultra_compact else 74),
        )
        self._consult_button = AnimatedButton(
            text="Consult",
            variant=AnimatedButton.VARIANT_SECONDARY,
            size=AnimatedButton.SIZE_MD if not self._compact else AnimatedButton.SIZE_SM,
            minimum_width=94 if not self._compact else (76 if not self._ultra_compact else 64),
        )
        self._report_button = AnimatedButton(
            text="Report",
            variant=AnimatedButton.VARIANT_GHOST,
            size=AnimatedButton.SIZE_MD if not self._compact else AnimatedButton.SIZE_SM,
            minimum_width=86 if not self._compact else (72 if not self._ultra_compact else 60),
        )

        action_layout.addWidget(self._details_button)
        action_layout.addWidget(self._consult_button)
        action_layout.addWidget(self._report_button)
        action_layout.addStretch(1)

        root.addWidget(self._top_row)
        root.addWidget(self._metrics_section)
        root.addWidget(self._issues_section)
        root.addWidget(self._recommendation_section)
        root.addWidget(self._consult_strip)
        root.addWidget(self._action_row)

    # ========================================================
    # Styling
    # ========================================================

    def _accent_for_severity(self, severity: str) -> str:
        severity = safe_str(severity, SEVERITY_UNKNOWN).strip().lower()
        if severity == SEVERITY_NORMAL:
            return self._theme.normal_accent
        if severity == SEVERITY_ATTENTION:
            return self._theme.attention_accent
        if severity == SEVERITY_WARNING:
            return self._theme.warning_accent
        if severity == SEVERITY_CRITICAL:
            return self._theme.critical_accent
        return self._theme.primary_accent

    def _health_accent(self, score: Optional[int]) -> str:
        if score is None:
            return self._theme.primary_accent
        if score >= 85:
            return self._theme.health_good_accent
        if score >= 60:
            return self._theme.health_mid_accent
        return self._theme.health_low_accent

    def _chip_colors(self, accent_hex: str) -> tuple[str, str, str]:
        accent = QColor(accent_hex)
        bg = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, {self._theme.chip_bg_alpha:.3f})"
        border = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, {self._theme.chip_border_alpha:.3f})"
        return bg, border, self._theme.chip_text

    def _apply_style(self) -> None:
        accent = self._accent_for_severity(self._severity)
        chip_bg, chip_border, chip_text = self._chip_colors(accent)
        health_accent = self._health_accent(self._health_index_score)
        health_bg, health_border, _ = self._chip_colors(health_accent)

        section_title_style = f"""
        QLabel {{
            color: {self._theme.section_title_color};
            font-size: {'10px' if not self._compact else ('9px' if not self._ultra_compact else '8px')};
            font-weight: 700;
            background: transparent;
        }}
        """
        self._metrics_title.setStyleSheet(section_title_style)
        self._issues_title.setStyleSheet(section_title_style)
        self._recommendation_title.setStyleSheet(section_title_style)

        if _HAS_GLOW_LABEL and isinstance(self._headline_label, GlowLabel):
            self._headline_label.set_glow_color(accent)
            self._headline_label.set_text_color(self._theme.headline_color)
            self._headline_label.set_role(
                GlowLabel.ROLE_STATUS if not self._compact else GlowLabel.ROLE_SUBTITLE
            )
        else:
            self._headline_label.setStyleSheet(
                f"""
                QLabel {{
                    color: {self._theme.headline_color};
                    font-size: {'17px' if not self._compact else ('14px' if not self._ultra_compact else '12px')};
                    font-weight: 800;
                    background: transparent;
                }}
                """
            )

        self._summary_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.summary_color};
                font-size: {'11px' if not self._compact else ('10px' if not self._ultra_compact else '9px')};
                font-weight: 500;
                background: transparent;
            }}
            """
        )

        self._severity_chip.setStyleSheet(
            f"""
            QLabel {{
                color: {chip_text};
                font-size: {'10px' if not self._compact else ('9px' if not self._ultra_compact else '8px')};
                font-weight: 700;
                border: 1px solid {chip_border};
                border-radius: {12 if not self._compact else (10 if not self._ultra_compact else 9)}px;
                background: {chip_bg};
                padding: {4 if not self._compact else (3 if not self._ultra_compact else 2)}px {8 if not self._compact else (6 if not self._ultra_compact else 5)}px;
            }}
            """
        )

        self._health_block.setStyleSheet(
            f"""
            QFrame#DiagnosisPanelHealthBlock {{
                border: 1px solid {health_border};
                border-radius: {16 if not self._compact else (13 if not self._ultra_compact else 11)}px;
                background: {health_bg};
            }}
            """
        )

        if _HAS_GLOW_LABEL and isinstance(self._health_score_label, GlowLabel):
            self._health_score_label.set_glow_color(health_accent)
            self._health_score_label.set_text_color(self._theme.stat_value_color)
            self._health_score_label.set_role(
                GlowLabel.ROLE_TITLE if not self._compact else GlowLabel.ROLE_STATUS
            )
        else:
            self._health_score_label.setStyleSheet(
                f"""
                QLabel {{
                    color: {self._theme.stat_value_color};
                    font-size: {'24px' if not self._compact else ('19px' if not self._ultra_compact else '16px')};
                    font-weight: 800;
                    background: transparent;
                }}
                """
            )

        self._health_text_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.stat_label_color};
                font-size: {'9px' if not self._compact else ('8px' if not self._ultra_compact else '7px')};
                font-weight: 600;
                background: transparent;
            }}
            """
        )

        self._consult_strip.setStyleSheet(
            f"""
            QFrame#DiagnosisPanelConsultStrip {{
                border: 1px solid {self._theme.strip_border};
                border-radius: {14 if not self._compact else (12 if not self._ultra_compact else 10)}px;
                background: {self._theme.strip_bg};
            }}
            """
        )

        consult_accent = self._theme.critical_accent if self._emergency_recommended else self._theme.primary_accent
        consult_dot = QColor(consult_accent)
        dot_radius = self._consult_dot.width() // 2
        self._consult_dot.setStyleSheet(
            f"""
            QLabel {{
                min-width: {self._consult_dot.width()}px;
                min-height: {self._consult_dot.height()}px;
                max-width: {self._consult_dot.width()}px;
                max-height: {self._consult_dot.height()}px;
                border-radius: {dot_radius}px;
                background: rgba({consult_dot.red()}, {consult_dot.green()}, {consult_dot.blue()}, 0.92);
                border: 1px solid rgba(255,255,255,0.18);
            }}
            """
        )

        self._consult_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.body_color};
                font-size: {'10px' if not self._compact else ('9px' if not self._ultra_compact else '8px')};
                font-weight: 600;
                background: transparent;
            }}
            """
        )

        self.set_accent_color(accent)
        self._details_button.set_accent_color(accent)
        self._consult_button.set_accent_color(self._theme.primary_accent)

    def _make_chip(self, text: str, accent_hex: str) -> QLabel:
        bg, border, chip_text = self._chip_colors(accent_hex)
        chip = QLabel(safe_str(text, "").strip(), self._content_root)
        chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chip.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        chip.setStyleSheet(
            f"""
            QLabel {{
                color: {chip_text};
                font-size: {'10px' if not self._compact else ('9px' if not self._ultra_compact else '8px')};
                font-weight: 700;
                border: 1px solid {border};
                border-radius: {12 if not self._compact else (10 if not self._ultra_compact else 9)}px;
                background: {bg};
                padding: {4 if not self._compact else (3 if not self._ultra_compact else 2)}px {8 if not self._compact else (6 if not self._ultra_compact else 5)}px;
            }}
            """
        )
        return chip

    def _make_metric_chip(self, metric_label: str, category_label: str, severity: str) -> QLabel:
        accent = self._accent_for_severity(severity)
        text = f"{metric_label}: {category_label}" if category_label else metric_label
        return self._make_chip(text, accent)

    def _make_bullet_label(self, text: str) -> QLabel:
        label = QLabel(f"• {safe_str(text, '').strip()}", self._content_root)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.body_color};
                font-size: {'10px' if not self._compact else ('9px' if not self._ultra_compact else '8px')};
                font-weight: 500;
                background: transparent;
            }}
            """
        )
        return label

    # ========================================================
    # Helpers
    # ========================================================

    def _default_headline_for_severity(self, severity: str) -> str:
        severity = safe_str(severity, SEVERITY_UNKNOWN).strip().lower()
        if severity == SEVERITY_NORMAL:
            return "Normal"
        if severity in {SEVERITY_ATTENTION, SEVERITY_WARNING}:
            return "Needs Attention"
        if severity == SEVERITY_CRITICAL:
            return "Critical"
        return "Status Unavailable"

    def _clear_layout(self, layout: QHBoxLayout | QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

    def _coerce_list(self, value: Any) -> List[str]:
        if isinstance(value, list):
            return [safe_str(item, "").strip() for item in value if safe_str(item, "").strip()]
        if value is None:
            return []
        text = safe_str(value, "").strip()
        return [text] if text else []

    def _normalize_metric_name(self, metric_key: str) -> str:
        cleaned = safe_str(metric_key, "").strip().lower()
        mapping = {
            "spo2": "SpO₂",
            "pulse": "Pulse",
            "pulse_rate": "Pulse",
            "temperature": "Temperature",
            "rr": "Respiratory Rate",
            "respiratory_rate": "Respiratory Rate",
            "weight": "Weight",
            "height": "Height",
            "bmi": "BMI",
        }
        return mapping.get(cleaned, cleaned.replace("_", " ").title())

    def _build_flagged_metrics_from_categories(self, metric_categories: Mapping[str, Any]) -> List[Dict[str, str]]:
        result: List[Dict[str, str]] = []
        for metric_key, payload in dict(metric_categories or {}).items():
            if not isinstance(payload, Mapping):
                continue
            label = safe_str(payload.get("label"), "").strip()
            severity = safe_str(payload.get("severity"), SEVERITY_UNKNOWN).strip().lower() or SEVERITY_UNKNOWN
            summary = safe_str(payload.get("summary"), "").strip()

            if severity == SEVERITY_NORMAL and not label:
                continue

            if severity in {SEVERITY_ATTENTION, SEVERITY_WARNING, SEVERITY_CRITICAL} or label:
                result.append(
                    {
                        "metric_key": safe_str(metric_key, ""),
                        "metric_label": self._normalize_metric_name(metric_key),
                        "category_label": label or summary or "Flagged",
                        "severity": severity,
                    }
                )
        return result

    def _refresh_visibility(self) -> None:
        self._top_row.setVisible(
            bool(self._headline.strip())
            or bool(self._summary.strip())
            or (self._show_health_index and self._health_index_score is not None)
            or (self._show_health_index and bool(self._health_index_label.strip()))
        )

        self._metrics_section.setVisible(self._show_metrics_section and len(self._flagged_metrics) > 0 and not self._ultra_compact)
        self._issues_section.setVisible(self._show_issue_section and len(self._issue_labels) > 0)
        self._recommendation_section.setVisible(
            self._show_recommendation_section and len(self._recommendations) > 0
        )

        consult_visible = self._show_consult_section and (
            self._emergency_recommended
            or bool(self._emergency_number.strip())
            or len(self._consult_tips) > 0
        )
        self._consult_strip.setVisible(consult_visible)
        self._emergency_button.setVisible(self._emergency_recommended)

        self._health_block.setVisible(
            self._show_health_index
            and (self._health_index_score is not None or bool(self._health_index_label.strip()))
        )
        self._action_row.setVisible(self._show_action_row)
        try:
            self._severity_chip.setVisible(not self._ultra_compact and bool(self._severity_chip.text().strip()))
            self._health_text_label.setVisible(not self._ultra_compact and self._health_block.isVisible())
        except Exception:
            pass

    def _is_layout_managed(self) -> bool:
        parent = self.parentWidget()
        if parent is None:
            return False
        return parent.layout() is not None

    # ========================================================
    # Public getters
    # ========================================================

    def severity(self) -> str:
        return self._severity

    def headline(self) -> str:
        return self._headline

    def summary(self) -> str:
        return self._summary

    def health_index_score(self) -> Optional[int]:
        return self._health_index_score

    # ========================================================
    # Public setters
    # ========================================================

    def set_severity(self, severity: str) -> None:
        normalized = safe_str(severity, SEVERITY_UNKNOWN).strip().lower() or SEVERITY_UNKNOWN
        self._severity = normalized

        if not self._headline.strip():
            self._headline = self._default_headline_for_severity(normalized)

        self._severity_chip.setText(self._default_headline_for_severity(normalized))
        self._apply_style()
        self._refresh_visibility()
        self.severity_changed.emit(normalized)

    def set_headline(self, headline: str) -> None:
        self._headline = safe_str(headline, "").strip()
        if _HAS_GLOW_LABEL and isinstance(self._headline_label, GlowLabel):
            self._headline_label.set_text(self._headline)
        else:
            self._headline_label.setText(self._headline)
        self._refresh_visibility()

    def set_summary(self, summary: str) -> None:
        self._summary = safe_str(summary, "").strip()
        self._summary_label.setText(self._summary)
        self._refresh_visibility()

    def set_health_index(self, score: Optional[int], label: str = "") -> None:
        self._health_index_score = None if score in (None, "") else max(0, min(100, safe_int(score, 0)))
        self._health_index_label = safe_str(label, "").strip()

        score_text = "--" if self._health_index_score is None else str(self._health_index_score)
        if _HAS_GLOW_LABEL and isinstance(self._health_score_label, GlowLabel):
            self._health_score_label.set_text(score_text)
        else:
            self._health_score_label.setText(score_text)

        self._health_text_label.setText(self._health_index_label or "Health Index")
        self._apply_style()
        self._refresh_visibility()

    def set_issue_labels(self, issue_labels: Iterable[str]) -> None:
        self._issue_labels = [safe_str(item, "").strip() for item in issue_labels if safe_str(item, "").strip()]

        self._clear_layout(self._issues_layout)
        for label in self._issue_labels:
            self._issues_layout.addWidget(
                self._make_chip(label, self._accent_for_severity(self._severity)),
                0,
                alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            )
        self._issues_layout.addStretch(1)
        self._refresh_visibility()

    def set_recommendations(self, recommendations: Iterable[str]) -> None:
        self._recommendations = [safe_str(item, "").strip() for item in recommendations if safe_str(item, "").strip()]

        self._clear_layout(self._recommendation_layout)
        for item in self._recommendations:
            self._recommendation_layout.addWidget(self._make_bullet_label(item))
        self._refresh_visibility()

    def set_consult_tips(self, consult_tips: Iterable[str]) -> None:
        self._consult_tips = [safe_str(item, "").strip() for item in consult_tips if safe_str(item, "").strip()]
        self._update_consult_text()
        self._refresh_visibility()

    def set_flagged_metrics(self, flagged_metrics: Iterable[Mapping[str, Any]]) -> None:
        normalized: List[Dict[str, str]] = []
        for item in flagged_metrics:
            if not isinstance(item, Mapping):
                continue
            normalized.append(
                {
                    "metric_key": safe_str(item.get("metric_key"), ""),
                    "metric_label": safe_str(item.get("metric_label"), ""),
                    "category_label": safe_str(item.get("category_label"), ""),
                    "severity": safe_str(item.get("severity"), SEVERITY_UNKNOWN).strip().lower() or SEVERITY_UNKNOWN,
                }
            )
        self._flagged_metrics = normalized

        self._clear_layout(self._metrics_layout)
        for item in self._flagged_metrics:
            self._metrics_layout.addWidget(
                self._make_metric_chip(
                    safe_str(item.get("metric_label"), ""),
                    safe_str(item.get("category_label"), ""),
                    safe_str(item.get("severity"), SEVERITY_UNKNOWN),
                ),
                0,
                alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            )
        self._metrics_layout.addStretch(1)
        self._refresh_visibility()

    def set_emergency_state(self, recommended: bool, number: str = "") -> None:
        self._emergency_recommended = bool(recommended)
        self._emergency_number = safe_str(number, "").strip()
        self._update_consult_text()
        self._apply_style()
        self._refresh_visibility()

    def _update_consult_text(self) -> None:
        if self._emergency_recommended and self._emergency_number:
            text = f"Emergency support recommended • Call {self._emergency_number}"
        elif self._emergency_recommended:
            text = "Emergency support recommended."
        elif self._consult_tips:
            text = self._consult_tips[0]
        elif self._emergency_number:
            text = f"Emergency contact available • {self._emergency_number}"
        else:
            text = ""
        if self._ultra_compact and len(text) > 56:
            text = text[:53].rstrip() + "..."
        self._consult_label.setText(text)

    def set_show_metrics_section(self, visible: bool) -> None:
        self._show_metrics_section = bool(visible)
        self._refresh_visibility()

    def set_show_issue_section(self, visible: bool) -> None:
        self._show_issue_section = bool(visible)
        self._refresh_visibility()

    def set_show_recommendation_section(self, visible: bool) -> None:
        self._show_recommendation_section = bool(visible)
        self._refresh_visibility()

    def set_show_consult_section(self, visible: bool) -> None:
        self._show_consult_section = bool(visible)
        self._refresh_visibility()

    def set_show_action_row(self, visible: bool) -> None:
        self._show_action_row = bool(visible)
        self._refresh_visibility()

    def set_show_health_index(self, visible: bool) -> None:
        self._show_health_index = bool(visible)
        self._refresh_visibility()

    def _sync_compact_mode(self, width: Optional[int] = None) -> None:
        width = width or max(0, self.width())
        new_compact = bool(self._compact or IS_COMPACT_KIOSK or (width and width <= 760))
        new_ultra = bool((width and width <= 620) or KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480)

        changed = (new_compact != self._compact) or (new_ultra != self._ultra_compact)
        self._compact = new_compact
        self._ultra_compact = new_ultra

        if self._ultra_compact:
            try:
                self._details_button.setText("Details")
                self._emergency_button.setText("Call")
            except Exception:
                pass
        else:
            try:
                self._details_button.setText("View Details")
                self._emergency_button.setText("Emergency")
            except Exception:
                pass

        try:
            self._severity_chip.setVisible(not self._ultra_compact)
            self._health_text_label.setVisible(not self._ultra_compact)
        except Exception:
            pass

        if changed:
            self._apply_style()
            self._refresh_visibility()
            self.updateGeometry()
            self.update()

    def set_compact(self, compact: bool) -> None:
        self._compact = bool(compact)
        self._sync_compact_mode(self.width())

    def compact(self) -> bool:
        return bool(self._compact)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_compact_mode(self.width())

    # ========================================================
    # Payload integration
    # ========================================================

    def apply_diagnosis_payload(self, payload: Mapping[str, Any]) -> None:
        """
        Apply a diagnosis payload from DiagnosisService or HealthRulesService.
        """
        data = dict(payload or {})

        severity = safe_str(
            data.get("overall_severity"),
            data.get("severity", self._severity),
        ).strip().lower() or self._severity
        headline = safe_str(data.get("status_title"), data.get("title", self._headline)).strip()
        summary = safe_str(data.get("summary"), self._summary).strip()

        issue_labels = self._coerce_list(data.get("issue_labels"))
        recommendations = self._coerce_list(data.get("recommendations"))
        consult_tips = self._coerce_list(data.get("consult_tips"))

        health_index_payload = data.get("health_index", {})
        health_index_score = None
        health_index_label = ""

        if isinstance(health_index_payload, Mapping):
            health_index_score = (
                safe_int(health_index_payload.get("score"), 0)
                if health_index_payload.get("score") not in (None, "")
                else None
            )
            health_index_label = safe_str(health_index_payload.get("label"), "").strip()
        else:
            if data.get("health_index_score") not in (None, ""):
                health_index_score = safe_int(data.get("health_index_score"), 0)
            health_index_label = safe_str(data.get("health_index_label"), "").strip()

        metric_categories = data.get("metric_categories", {})
        flagged_metrics = (
            self._build_flagged_metrics_from_categories(metric_categories)
            if isinstance(metric_categories, Mapping)
            else []
        )

        if not flagged_metrics:
            trend_issue_labels = self._coerce_list(data.get("trend_issue_labels"))
            if trend_issue_labels:
                flagged_metrics = [
                    {
                        "metric_key": "",
                        "metric_label": item,
                        "category_label": "",
                        "severity": severity,
                    }
                    for item in trend_issue_labels
                ]

        emergency_recommended = bool(data.get("emergency_recommended", False))
        emergency_number = safe_str(data.get("emergency_number"), "").strip()

        self.set_severity(severity)
        self.set_headline(headline or self._default_headline_for_severity(severity))
        self.set_summary(summary)
        self.set_health_index(health_index_score, health_index_label)
        self.set_issue_labels(issue_labels)
        self.set_recommendations(recommendations if recommendations else consult_tips)
        self.set_consult_tips(consult_tips)
        self.set_flagged_metrics(flagged_metrics)
        self.set_emergency_state(emergency_recommended, emergency_number)

        if data.get("footer"):
            super().set_footer(safe_str(data.get("footer"), ""))

        self.diagnosis_applied.emit(dict(data))

    def apply_status_payload(self, payload: Mapping[str, Any]) -> None:
        """
        Apply a lighter-weight status or trend payload.
        """
        data = dict(payload or {})
        severity = safe_str(data.get("severity"), self._severity).strip().lower() or self._severity
        title = safe_str(data.get("title"), self._headline).strip()
        summary = safe_str(data.get("summary"), self._summary).strip()
        issues = self._coerce_list(data.get("issue_labels")) or self._coerce_list(data.get("trend_issue_labels"))

        self.set_severity(severity)
        self.set_headline(title or self._default_headline_for_severity(severity))
        self.set_summary(summary)
        if issues:
            self.set_issue_labels(issues)

        self.diagnosis_applied.emit(dict(data))

    # ========================================================
    # Convenience presets
    # ========================================================

    def mark_normal(self, summary: str = "All measured parameters are within acceptable range.") -> None:
        self.set_severity(SEVERITY_NORMAL)
        self.set_headline("Normal")
        self.set_summary(summary)
        self.set_issue_labels([])
        self.set_flagged_metrics([])
        self.set_recommendations([])
        self.set_consult_tips([])
        self.set_emergency_state(False, "")

    def mark_attention(self, summary: str = "Some values need attention. Please review the recommendations.") -> None:
        self.set_severity(SEVERITY_ATTENTION)
        self.set_headline("Needs Attention")
        self.set_summary(summary)

    def mark_warning(self, summary: str = "Important abnormal values were detected.") -> None:
        self.set_severity(SEVERITY_WARNING)
        self.set_headline("Needs Attention")
        self.set_summary(summary)

    def mark_critical(self, summary: str = "Critical condition detected. Seek immediate help.", emergency_number: str = "") -> None:
        self.set_severity(SEVERITY_CRITICAL)
        self.set_headline("Critical")
        self.set_summary(summary)
        self.set_emergency_state(True, emergency_number)

    # ========================================================
    # Hover / layout-safe lift
    # ========================================================

    def enterEvent(self, event: QEvent) -> None:
        super().enterEvent(event)
        self._hovered = True
        self._apply_style()
        self._animate_lift(True)

    def leaveEvent(self, event: QEvent) -> None:
        super().leaveEvent(event)
        self._hovered = False
        self._apply_style()
        self._animate_lift(False)

    def _animate_lift(self, hovered: bool) -> None:
        if self._is_layout_managed():
            return

        if self._base_pos is None:
            self._base_pos = self.pos()

        target = self._base_pos if not hovered else QPoint(self._base_pos.x(), self._base_pos.y() - 1)

        if self._hover_anim is not None:
            try:
                self._hover_anim.stop()
            except Exception:
                pass

        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(120)
        anim.setStartValue(self.pos())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        self._hover_anim = anim

    # ========================================================
    # Paint extra gloss
    # ========================================================

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            rect = QRectF(self.rect().adjusted(1, 1, -1, -1))
            if rect.width() > 6.0 and rect.height() > 6.0:
                radius = float(24 if not self._compact else (18 if not self._ultra_compact else 15))
                path = QPainterPath()
                path.addRoundedRect(rect, radius, radius)

                painter.save()
                painter.setClipPath(path)
                gloss_rect = QRectF(
                    rect.left() + 2.0,
                    rect.top() + 2.0,
                    max(0.0, rect.width() - 4.0),
                    max(0.0, rect.height() * 0.36),
                )
                painter.fillRect(gloss_rect, QColor(255, 255, 255, 10))
                painter.restore()
        finally:
            painter.end()

    # ========================================================
    # Diagnostics
    # ========================================================

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "headline": self._headline,
            "summary": self._summary,
            "severity": self._severity,
            "issue_labels": list(self._issue_labels),
            "recommendations": list(self._recommendations),
            "consult_tips": list(self._consult_tips),
            "flagged_metrics": list(self._flagged_metrics),
            "health_index_score": self._health_index_score,
            "health_index_label": self._health_index_label,
            "emergency_recommended": self._emergency_recommended,
            "emergency_number": self._emergency_number,
            "show_metrics_section": self._show_metrics_section,
            "show_issue_section": self._show_issue_section,
            "show_recommendation_section": self._show_recommendation_section,
            "show_consult_section": self._show_consult_section,
            "show_action_row": self._show_action_row,
            "show_health_index": self._show_health_index,
            "compact": self._compact,
        }
