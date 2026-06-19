"""
widgets/status_card.py

Premium status/diagnosis card widget for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is one of the most important summary widgets in the kiosk UI
- It is designed for:
    - results screen overall health summary
    - diagnosis screen headline card
    - consult screen guidance banner
    - admin dashboard status overview
    - publish screen trend interpretation summary
- It provides a polished, reusable way to show:
    - status title
    - severity state
    - summary message
    - issue labels
    - recommendations
    - emergency guidance
    - action buttons
- It builds on the same premium visual language already established in:
    - widgets/glass_card.py
    - widgets/glow_label.py
    - widgets/animated_button.py

Design goals:
- premium futuristic medical dashboard feel
- clear at-a-glance health interpretation
- reusable across many screens without duplicated logic
- safe defaults even when diagnosis payload is partial
- lightweight enough for Raspberry Pi kiosk deployment
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
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
    from core.utils import safe_str
except Exception:  # pragma: no cover
    def safe_str(value: Any, default: str = "") -> str:
        try:
            if value is None:
                return default
            return str(value)
        except Exception:
            return default

try:
    from core.constants import (
        HEALTH_STATUS_CRITICAL,
        HEALTH_STATUS_NEEDS_ATTENTION,
        HEALTH_STATUS_NORMAL,
        SEVERITY_ATTENTION,
        SEVERITY_CRITICAL,
        SEVERITY_NORMAL,
        SEVERITY_UNKNOWN,
        SEVERITY_WARNING,
    )
except Exception:  # pragma: no cover
    HEALTH_STATUS_NORMAL = "Normal"
    HEALTH_STATUS_NEEDS_ATTENTION = "Needs Attention"
    HEALTH_STATUS_CRITICAL = "Critical"

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
# Theme dataclass
# ============================================================

@dataclass(frozen=True)
class StatusCardTheme:
    """
    Theme container for StatusCard.
    """
    headline_color: str = "#F6FCFF"
    summary_color: str = "rgba(222, 238, 249, 0.92)"
    section_title_color: str = "rgba(211, 231, 245, 0.86)"
    bullet_color: str = "rgba(228, 242, 252, 0.88)"
    subtle_text: str = "rgba(188, 212, 231, 0.82)"

    neutral_chip_bg: str = "rgba(45, 72, 106, 0.22)"
    neutral_chip_border: str = "rgba(149, 214, 255, 0.24)"
    neutral_chip_text: str = "#ECF8FF"

    normal_color: str = "#3CE28D"
    attention_color: str = "#FFD15E"
    warning_color: str = "#FFA14B"
    critical_color: str = "#FF6A86"
    primary_color: str = "#39D8FF"


DEFAULT_STATUS_CARD_THEME = StatusCardTheme()


# ============================================================
# Main widget
# ============================================================

class StatusCard(GlassCard):
    """
    Premium diagnosis/status summary card.

    Main features:
    - headline label with severity glow
    - summary description
    - issue chips
    - recommendations list
    - emergency info strip
    - primary / secondary action buttons
    - apply_diagnosis_payload() convenience for direct service integration
    """

    primary_action_clicked = pyqtSignal()
    secondary_action_clicked = pyqtSignal()
    emergency_action_clicked = pyqtSignal()

    severity_changed = pyqtSignal(str)
    headline_changed = pyqtSignal(str)
    summary_changed = pyqtSignal(str)
    diagnosis_applied = pyqtSignal(dict)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        title: str = "Health Status",
        subtitle: str = "Session diagnosis overview",
        headline: str = "",
        summary: str = "",
        severity: str = SEVERITY_UNKNOWN,
        icon_path: str = "",
        footer: str = "",
        compact: bool = False,
        clickable: bool = False,
        show_issue_section: bool = True,
        show_recommendation_section: bool = True,
        show_action_row: bool = True,
        show_emergency_strip: bool = True,
        primary_button_text: str = "View Details",
        secondary_button_text: str = "Consult",
        theme: Optional[StatusCardTheme] = None,
    ) -> None:
        self._logger = logger.bind(component="StatusCard")

        self._theme = theme or DEFAULT_STATUS_CARD_THEME
        self._compact = bool(compact)
        self._severity = safe_str(severity, SEVERITY_UNKNOWN).strip().lower() or SEVERITY_UNKNOWN

        self._headline = safe_str(headline, "").strip()
        self._summary = safe_str(summary, "").strip()
        self._issue_labels: List[str] = []
        self._recommendations: List[str] = []
        self._consult_tips: List[str] = []
        self._status_title = ""
        self._emergency_recommended = False
        self._emergency_number = ""
        self._primary_button_text = safe_str(primary_button_text, "View Details").strip() or "View Details"
        self._secondary_button_text = safe_str(secondary_button_text, "Consult").strip() or "Consult"

        self._show_issue_section = bool(show_issue_section)
        self._show_recommendation_section = bool(show_recommendation_section)
        self._show_action_row = bool(show_action_row)
        self._show_emergency_strip = bool(show_emergency_strip)

        super().__init__(
            title=title,
            subtitle=subtitle,
            body="",
            footer=footer,
            icon_path=icon_path,
            parent=parent,
            accent_color=self._accent_for_severity(self._severity),
            minimum_height=176 if not self._compact else (132 if self._ultra_compact else 150),
            clickable=clickable,
            enable_hover_effect=True,
            show_accent_bar=True,
            compact=self._compact,
        )

        self._build_status_content()
        self.set_content_widget(self._content_root)
        self._apply_status_style()

        self.set_headline(self._headline or self._default_headline_for_severity(self._severity))
        self.set_summary(self._summary)
        self.set_severity(self._severity)
        self.set_primary_button_text(self._primary_button_text)
        self.set_secondary_button_text(self._secondary_button_text)
        self._refresh_visibility()

    # ========================================================
    # UI building
    # ========================================================

    def _build_status_content(self) -> None:
        self._content_root = QWidget(self)
        self._content_root.setObjectName("StatusCardContentRoot")

        root = QVBoxLayout(self._content_root)
        root.setContentsMargins(0, 2 if self._compact else 4, 0, 0)
        root.setSpacing(8 if not self._compact else 6)

        # ----------------------------------------------------
        # Headline / summary
        # ----------------------------------------------------
        self._headline_label = self._create_headline_label()
        self._summary_label = QLabel(self._content_root)
        self._summary_label.setWordWrap(True)
        self._summary_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        # ----------------------------------------------------
        # Emergency strip
        # ----------------------------------------------------
        self._emergency_strip = QFrame(self._content_root)
        self._emergency_strip.setObjectName("StatusCardEmergencyStrip")
        emergency_layout = QHBoxLayout(self._emergency_strip)
        emergency_layout.setContentsMargins(10 if not self._compact else 8, 6 if not self._compact else 5, 10 if not self._compact else 8, 6 if not self._compact else 5)
        emergency_layout.setSpacing(8 if not self._compact else 6)

        self._emergency_dot = QLabel(self._emergency_strip)
        self._emergency_dot.setFixedSize(10 if not self._compact else 8, 10 if not self._compact else 8)

        self._emergency_text = QLabel(self._emergency_strip)
        self._emergency_text.setWordWrap(True)

        self._emergency_button = AnimatedButton(
            text="Emergency",
            variant=AnimatedButton.VARIANT_DANGER,
            size=AnimatedButton.SIZE_SM,
            minimum_width=88 if not self._compact else (64 if self._ultra_compact else 74),
        )
        self._emergency_button.clicked.connect(self.emergency_action_clicked.emit)

        emergency_layout.addWidget(self._emergency_dot, 0, alignment=Qt.AlignmentFlag.AlignVCenter)
        emergency_layout.addWidget(self._emergency_text, 1, alignment=Qt.AlignmentFlag.AlignVCenter)
        emergency_layout.addWidget(self._emergency_button, 0, alignment=Qt.AlignmentFlag.AlignVCenter)

        # ----------------------------------------------------
        # Issues section
        # ----------------------------------------------------
        self._issues_section = QWidget(self._content_root)
        issues_layout = QVBoxLayout(self._issues_section)
        issues_layout.setContentsMargins(0, 0, 0, 0)
        issues_layout.setSpacing(5 if not self._compact else (3 if self._ultra_compact else 4))

        self._issues_title = QLabel("Detected Issues", self._issues_section)

        self._issues_chip_wrap = QWidget(self._issues_section)
        self._issues_chip_layout = QHBoxLayout(self._issues_chip_wrap)
        self._issues_chip_layout.setContentsMargins(0, 0, 0, 0)
        self._issues_chip_layout.setSpacing(6 if not self._compact else (3 if self._ultra_compact else 4))

        issues_layout.addWidget(self._issues_title)
        issues_layout.addWidget(self._issues_chip_wrap)

        # ----------------------------------------------------
        # Recommendations section
        # ----------------------------------------------------
        self._recommendation_section = QWidget(self._content_root)
        rec_layout = QVBoxLayout(self._recommendation_section)
        rec_layout.setContentsMargins(0, 0, 0, 0)
        rec_layout.setSpacing(4 if not self._compact else (2 if self._ultra_compact else 3))

        self._recommendation_title = QLabel("Recommendations", self._recommendation_section)

        self._recommendation_wrap = QWidget(self._recommendation_section)
        self._recommendation_layout = QVBoxLayout(self._recommendation_wrap)
        self._recommendation_layout.setContentsMargins(0, 0, 0, 0)
        self._recommendation_layout.setSpacing(3 if not self._compact else (1 if self._ultra_compact else 2))

        rec_layout.addWidget(self._recommendation_title)
        rec_layout.addWidget(self._recommendation_wrap)

        # ----------------------------------------------------
        # Action row
        # ----------------------------------------------------
        self._action_row = QWidget(self._content_root)
        action_layout = QHBoxLayout(self._action_row)
        action_layout.setContentsMargins(0, 1 if self._ultra_compact else (2 if not self._compact else 0), 0, 0)
        action_layout.setSpacing(8 if not self._compact else (4 if self._ultra_compact else 6))

        self._primary_button = AnimatedButton(
            text=self._primary_button_text,
            variant=AnimatedButton.VARIANT_PRIMARY,
            size=AnimatedButton.SIZE_MD if not self._compact else AnimatedButton.SIZE_SM,
            expand=False,
            minimum_width=108 if not self._compact else (76 if self._ultra_compact else 86),
        )
        self._primary_button.clicked.connect(self.primary_action_clicked.emit)

        self._secondary_button = AnimatedButton(
            text=self._secondary_button_text,
            variant=AnimatedButton.VARIANT_SECONDARY,
            size=AnimatedButton.SIZE_MD if not self._compact else AnimatedButton.SIZE_SM,
            expand=False,
            minimum_width=96 if not self._compact else (70 if self._ultra_compact else 78),
        )
        self._secondary_button.clicked.connect(self.secondary_action_clicked.emit)

        action_layout.addWidget(self._primary_button)
        action_layout.addWidget(self._secondary_button)
        action_layout.addStretch(1)

        # ----------------------------------------------------
        # Assemble
        # ----------------------------------------------------
        root.addWidget(self._headline_label)
        root.addWidget(self._summary_label)
        root.addWidget(self._emergency_strip)
        root.addWidget(self._issues_section)
        root.addWidget(self._recommendation_section)
        root.addWidget(self._action_row)

    def _create_headline_label(self) -> QWidget:
        if _HAS_GLOW_LABEL:
            label = GlowLabel(
                role=GlowLabel.ROLE_STATUS if not self._compact else GlowLabel.ROLE_SUBTITLE,
                align_center=False,
                use_outline=False,
                enable_paint_glow=True,
                initial_glow_strength=0.52,
                initial_glow_blur=18 if not self._compact else (11 if self._ultra_compact else 14),
            )
            label.setWordWrap(True)
            return label

        label = QLabel()
        label.setWordWrap(True)
        return label

    # ========================================================
    # Styling helpers
    # ========================================================

    def _accent_for_severity(self, severity: str) -> str:
        severity = safe_str(severity, SEVERITY_UNKNOWN).strip().lower()
        if severity == SEVERITY_NORMAL:
            return self._theme.normal_color
        if severity == SEVERITY_ATTENTION:
            return self._theme.attention_color
        if severity == SEVERITY_WARNING:
            return self._theme.warning_color
        if severity == SEVERITY_CRITICAL:
            return self._theme.critical_color
        return self._theme.primary_color

    def _chip_colors(self, severity: str) -> tuple[str, str, str]:
        severity = safe_str(severity, SEVERITY_UNKNOWN).strip().lower()
        accent = QColor(self._accent_for_severity(severity))
        chip_bg = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.16)"
        chip_border = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.34)"
        chip_text = "#F7FDFF"
        return chip_bg, chip_border, chip_text

    def _apply_status_style(self) -> None:
        accent = self._accent_for_severity(self._severity)
        chip_bg, chip_border, chip_text = self._chip_colors(self._severity)

        headline_size = 17 if not self._compact else 14
        summary_size = 11 if not self._compact else 10
        section_title_size = 10 if not self._compact else 9
        bullet_size = 10 if not self._compact else 9
        strip_radius = 14 if not self._compact else 12

        if _HAS_GLOW_LABEL and isinstance(self._headline_label, GlowLabel):
            self._headline_label.set_glow_color(accent)
            self._headline_label.set_text_color(self._theme.headline_color)
            self._headline_label.set_role(GlowLabel.ROLE_STATUS if not self._compact else GlowLabel.ROLE_SUBTITLE)
        else:
            self._headline_label.setStyleSheet(
                f"""
                QLabel {{
                    color: {self._theme.headline_color};
                    font-size: {headline_size}px;
                    font-weight: 800;
                    background: transparent;
                }}
                """
            )

        self._summary_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.summary_color};
                font-size: {summary_size}px;
                font-weight: 500;
                background: transparent;
            }}
            """
        )

        section_style = f"""
        QLabel {{
            color: {self._theme.section_title_color};
            font-size: {section_title_size}px;
            font-weight: 700;
            background: transparent;
        }}
        """
        self._issues_title.setStyleSheet(section_style)
        self._recommendation_title.setStyleSheet(section_style)

        self._emergency_strip.setStyleSheet(
            f"""
            QFrame#StatusCardEmergencyStrip {{
                border: 1px solid {chip_border};
                border-radius: {strip_radius}px;
                background: {chip_bg};
            }}
            """
        )

        dot_color = QColor(accent)
        dot_radius = self._emergency_dot.width() // 2
        self._emergency_dot.setStyleSheet(
            f"""
            QLabel {{
                min-width: {self._emergency_dot.width()}px;
                min-height: {self._emergency_dot.height()}px;
                max-width: {self._emergency_dot.width()}px;
                max-height: {self._emergency_dot.height()}px;
                border-radius: {dot_radius}px;
                background: {dot_color.name()};
                border: 1px solid rgba(255, 255, 255, 0.18);
            }}
            """
        )

        self._emergency_text.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.bullet_color};
                font-size: {bullet_size}px;
                font-weight: 600;
                background: transparent;
            }}
            """
        )

        self.set_accent_color(accent)

    def _make_chip(self, text: str) -> QLabel:
        chip_bg, chip_border, chip_text = self._chip_colors(self._severity)
        chip = QLabel(safe_str(text, "").strip(), self._issues_chip_wrap)
        chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chip.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        chip.setStyleSheet(
            f"""
            QLabel {{
                color: {chip_text};
                font-size: {'10px' if not self._compact else ('8px' if self._ultra_compact else '9px')};
                font-weight: 700;
                border: 1px solid {chip_border};
                border-radius: {12 if not self._compact else (9 if self._ultra_compact else 10)}px;
                background: {chip_bg};
                padding: {4 if not self._compact else (2 if self._ultra_compact else 3)}px {8 if not self._compact else (5 if self._ultra_compact else 6)}px;
            }}
            """
        )
        return chip

    def _make_bullet_label(self, text: str) -> QLabel:
        label = QLabel(f"• {safe_str(text, '').strip()}", self._recommendation_wrap)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.bullet_color};
                font-size: {'10px' if not self._compact else ('8px' if self._ultra_compact else '9px')};
                font-weight: 500;
                background: transparent;
            }}
            """
        )
        return label

    # ========================================================
    # Utility helpers
    # ========================================================

    def _default_headline_for_severity(self, severity: str) -> str:
        severity = safe_str(severity, SEVERITY_UNKNOWN).strip().lower()
        if severity == SEVERITY_NORMAL:
            return HEALTH_STATUS_NORMAL
        if severity in {SEVERITY_ATTENTION, SEVERITY_WARNING}:
            return HEALTH_STATUS_NEEDS_ATTENTION
        if severity == SEVERITY_CRITICAL:
            return HEALTH_STATUS_CRITICAL
        return "Status Unavailable"

    def _clear_layout_widgets(self, layout: QVBoxLayout | QHBoxLayout) -> None:
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

    def _refresh_visibility(self) -> None:
        self._headline_label.setVisible(bool(self.headline()))
        self._summary_label.setVisible(bool(self.summary()))

        issues_visible = self._show_issue_section and len(self._issue_labels) > 0
        recommendations_visible = self._show_recommendation_section and len(self._recommendations) > 0
        emergency_visible = self._show_emergency_strip and (self._emergency_recommended or bool(self._emergency_number.strip()))
        action_visible = self._show_action_row

        self._issues_section.setVisible(issues_visible)
        self._recommendation_section.setVisible(recommendations_visible)
        self._emergency_strip.setVisible(emergency_visible)
        self._action_row.setVisible(action_visible)

    # ========================================================
    # Public getters
    # ========================================================

    def severity(self) -> str:
        return self._severity

    def headline(self) -> str:
        return safe_str(self._headline, "").strip()

    def summary(self) -> str:
        return safe_str(self._summary, "").strip()

    def issue_labels(self) -> List[str]:
        return list(self._issue_labels)

    def recommendations(self) -> List[str]:
        return list(self._recommendations)

    # ========================================================
    # Public setters
    # ========================================================

    def set_severity(self, severity: str) -> None:
        normalized = safe_str(severity, SEVERITY_UNKNOWN).strip().lower() or SEVERITY_UNKNOWN
        self._severity = normalized
        self._apply_status_style()
        self.severity_changed.emit(normalized)

        if not self.headline():
            self.set_headline(self._default_headline_for_severity(normalized))

    def set_headline(self, headline: str) -> None:
        self._headline = safe_str(headline, "").strip()
        if _HAS_GLOW_LABEL and isinstance(self._headline_label, GlowLabel):
            self._headline_label.set_text(self._headline)
        else:
            self._headline_label.setText(self._headline)
        self.headline_changed.emit(self._headline)
        self._refresh_visibility()

    def set_summary(self, summary: str) -> None:
        self._summary = safe_str(summary, "").strip()
        self._summary_label.setText(self._summary)
        self.summary_changed.emit(self._summary)
        self._refresh_visibility()

    def set_issue_labels(self, issue_labels: Iterable[str]) -> None:
        labels = [safe_str(item, "").strip() for item in issue_labels if safe_str(item, "").strip()]
        self._issue_labels = labels

        self._clear_layout_widgets(self._issues_chip_layout)
        for label in labels:
            self._issues_chip_layout.addWidget(self._make_chip(label), 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._issues_chip_layout.addStretch(1)

        self._refresh_visibility()

    def set_recommendations(self, recommendations: Iterable[str]) -> None:
        recs = [safe_str(item, "").strip() for item in recommendations if safe_str(item, "").strip()]
        self._recommendations = recs

        self._clear_layout_widgets(self._recommendation_layout)
        for rec in recs:
            self._recommendation_layout.addWidget(self._make_bullet_label(rec))
        self._refresh_visibility()

    def set_consult_tips(self, tips: Iterable[str]) -> None:
        self._consult_tips = [safe_str(item, "").strip() for item in tips if safe_str(item, "").strip()]

    def set_emergency_state(self, recommended: bool, number: str = "") -> None:
        self._emergency_recommended = bool(recommended)
        self._emergency_number = safe_str(number, "").strip()

        if self._emergency_recommended and self._emergency_number:
            text = f"Emergency support recommended • Call {self._emergency_number}"
        elif self._emergency_recommended:
            text = "Emergency support recommended."
        elif self._emergency_number:
            text = f"Emergency contact available • {self._emergency_number}"
        else:
            text = ""

        self._emergency_text.setText(text)
        self._emergency_button.setVisible(self._emergency_recommended)
        self._refresh_visibility()

    def set_primary_button_text(self, text: str) -> None:
        self._primary_button_text = safe_str(text, "View Details").strip() or "View Details"
        self._primary_button.setText(self._primary_button_text)

    def set_secondary_button_text(self, text: str) -> None:
        self._secondary_button_text = safe_str(text, "Consult").strip() or "Consult"
        self._secondary_button.setText(self._secondary_button_text)

    def set_show_issue_section(self, visible: bool) -> None:
        self._show_issue_section = bool(visible)
        self._refresh_visibility()

    def set_show_recommendation_section(self, visible: bool) -> None:
        self._show_recommendation_section = bool(visible)
        self._refresh_visibility()

    def set_show_action_row(self, visible: bool) -> None:
        self._show_action_row = bool(visible)
        self._refresh_visibility()

    def set_show_emergency_strip(self, visible: bool) -> None:
        self._show_emergency_strip = bool(visible)
        self._refresh_visibility()

    # ========================================================
    # Diagnosis integration
    # ========================================================

    def apply_diagnosis_payload(self, payload: Mapping[str, Any]) -> None:
        """
        Apply diagnosis payload from DiagnosisService / HealthRulesService.

        Expected payload shape:
        {
            "overall_severity": "warning",
            "status_title": "Needs Attention",
            "summary": "...",
            "issue_labels": [...],
            "recommendations": [...],
            "consult_tips": [...],
            "emergency_recommended": True/False,
            "emergency_number": "112"
        }
        """
        diagnosis = dict(payload or {})

        severity = safe_str(diagnosis.get("overall_severity"), SEVERITY_UNKNOWN).strip().lower() or SEVERITY_UNKNOWN
        status_title = safe_str(diagnosis.get("status_title"), "").strip()
        summary = safe_str(diagnosis.get("summary"), "").strip()

        issue_labels = self._coerce_list(diagnosis.get("issue_labels"))
        recommendations = self._coerce_list(diagnosis.get("recommendations"))
        consult_tips = self._coerce_list(diagnosis.get("consult_tips"))

        # Prefer recommendations first, but use consult tips as a fallback
        if not recommendations and consult_tips:
            recommendations = consult_tips

        emergency_recommended = bool(diagnosis.get("emergency_recommended", False))
        emergency_number = safe_str(diagnosis.get("emergency_number"), "").strip()

        self.set_severity(severity)
        self.set_headline(status_title or self._default_headline_for_severity(severity))
        self.set_summary(summary)
        self.set_issue_labels(issue_labels)
        self.set_recommendations(recommendations)
        self.set_consult_tips(consult_tips)
        self.set_emergency_state(emergency_recommended, emergency_number)

        self._status_title = status_title
        self.diagnosis_applied.emit(dict(diagnosis))

    def apply_status_payload(self, payload: Mapping[str, Any]) -> None:
        """
        Apply compact status payload such as:
        {
            "title": "Needs Attention",
            "summary": "...",
            "severity": "attention",
            "issue_labels": [...]
        }
        """
        data = dict(payload or {})
        self.set_headline(safe_str(data.get("title"), self.headline()))
        self.set_summary(safe_str(data.get("summary"), self.summary()))
        self.set_severity(safe_str(data.get("severity"), self.severity()))
        issue_labels = self._coerce_list(data.get("issue_labels"))
        if issue_labels:
            self.set_issue_labels(issue_labels)

    # ========================================================
    # Convenience presets
    # ========================================================

    def mark_normal(
        self,
        summary: str = "All measured parameters are within acceptable range.",
    ) -> None:
        self.set_severity(SEVERITY_NORMAL)
        self.set_headline(HEALTH_STATUS_NORMAL)
        self.set_summary(summary)
        self.set_issue_labels([])
        self.set_recommendations([])
        self.set_emergency_state(False, "")

    def mark_attention(
        self,
        summary: str = "Some parameters need attention. Please review advice.",
    ) -> None:
        self.set_severity(SEVERITY_ATTENTION)
        self.set_headline(HEALTH_STATUS_NEEDS_ATTENTION)
        self.set_summary(summary)

    def mark_warning(
        self,
        summary: str = "Important abnormal values were detected. Please review recommendations.",
    ) -> None:
        self.set_severity(SEVERITY_WARNING)
        self.set_headline(HEALTH_STATUS_NEEDS_ATTENTION)
        self.set_summary(summary)

    def mark_critical(
        self,
        summary: str = "Critical condition detected. Seek immediate help.",
        emergency_number: str = "",
    ) -> None:
        self.set_severity(SEVERITY_CRITICAL)
        self.set_headline(HEALTH_STATUS_CRITICAL)
        self.set_summary(summary)
        self.set_emergency_state(True, emergency_number)

    # ========================================================
    # Diagnostics
    # ========================================================

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "title": self.title(),
            "subtitle": self.subtitle(),
            "headline": self.headline(),
            "summary": self.summary(),
            "severity": self._severity,
            "issue_labels": list(self._issue_labels),
            "recommendations": list(self._recommendations),
            "consult_tips": list(self._consult_tips),
            "emergency_recommended": self._emergency_recommended,
            "emergency_number": self._emergency_number,
            "show_issue_section": self._show_issue_section,
            "show_recommendation_section": self._show_recommendation_section,
            "show_action_row": self._show_action_row,
            "show_emergency_strip": self._show_emergency_strip,
            "compact": self._compact,
        }