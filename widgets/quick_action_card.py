"""
widgets/quick_action_card.py

Premium quick action card widget for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is a reusable action-first card used throughout the kiosk UI
- It is designed for:
    - results screen quick actions (QR, PDF, Consult, Details)
    - admin panel shortcuts
    - settings / storage / publish shortcuts
    - navigation tiles on dashboard-style screens
- It combines:
    - glass-card visual foundation
    - headline + subtitle + description
    - primary action button
    - optional secondary button
    - optional badge/state chip
    - optional metric/count highlight
- It keeps the overall futuristic blue medical style consistent with:
    - widgets/glass_card.py
    - widgets/animated_button.py
    - widgets/glow_label.py

Design goals:
- premium polished kiosk action card
- very reusable across many screens
- easy to wire to navigation callbacks
- lightweight enough for Raspberry Pi
- safe defaults if only minimal info is supplied
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
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
class QuickActionCardTheme:
    """
    Theme container for QuickActionCard.
    """
    title_color: str = "#F3FBFF"
    subtitle_color: str = "rgba(211, 232, 247, 0.80)"
    body_color: str = "rgba(225, 240, 250, 0.92)"
    badge_text: str = "#EEF9FF"
    badge_bg: str = "rgba(58, 97, 142, 0.24)"
    badge_border: str = "rgba(149, 213, 255, 0.28)"
    count_text: str = "#F8FDFF"
    count_subtle: str = "rgba(196, 220, 238, 0.82)"
    primary_accent: str = "#39D8FF"
    success_accent: str = "#40E594"
    warning_accent: str = "#FFC95A"
    danger_accent: str = "#FF6D86"
    neutral_accent: str = "#7CCFFF"


DEFAULT_QUICK_ACTION_THEME = QuickActionCardTheme()


# ============================================================
# Main widget
# ============================================================

class QuickActionCard(GlassCard):
    """
    Premium action card built on top of GlassCard.

    Main features:
    - title/subtitle inherited from GlassCard
    - optional description/body section
    - badge/state chip
    - count/value block
    - primary and secondary action buttons
    - card click support for navigation
    """

    primary_action_clicked = pyqtSignal()
    secondary_action_clicked = pyqtSignal()
    card_action_clicked = pyqtSignal()

    badge_changed = pyqtSignal(str)
    count_changed = pyqtSignal(str)
    description_changed = pyqtSignal(str)

    STATE_PRIMARY = "primary"
    STATE_SUCCESS = "success"
    STATE_WARNING = "warning"
    STATE_DANGER = "danger"
    STATE_NEUTRAL = "neutral"

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        title: str = "",
        subtitle: str = "",
        description: str = "",
        icon_path: str = "",
        footer: str = "",
        primary_button_text: str = "Open",
        secondary_button_text: str = "",
        badge_text: str = "",
        count_text: str = "",
        count_label: str = "",
        state: str = STATE_PRIMARY,
        compact: bool = False,
        clickable: bool = True,
        show_badge: bool = True,
        show_count_block: bool = False,
        show_secondary_button: bool = False,
        show_action_row: bool = True,
        theme: Optional[QuickActionCardTheme] = None,
        minimum_height: int = 168,
    ) -> None:
        self._logger = logger.bind(component="QuickActionCard")

        self._theme = theme or DEFAULT_QUICK_ACTION_THEME
        self._compact = bool(compact)

        self._state = safe_str(state, self.STATE_PRIMARY).strip().lower() or self.STATE_PRIMARY
        self._description = safe_str(description, "").strip()
        self._badge_text = safe_str(badge_text, "").strip()
        self._count_text = safe_str(count_text, "").strip()
        self._count_label = safe_str(count_label, "").strip()
        self._primary_button_text = safe_str(primary_button_text, "Open").strip() or "Open"
        self._secondary_button_text = safe_str(secondary_button_text, "").strip()

        self._show_badge = bool(show_badge)
        self._show_count_block = bool(show_count_block)
        self._show_secondary_button = bool(show_secondary_button)
        self._show_action_row = bool(show_action_row)

        super().__init__(
            title=title,
            subtitle=subtitle,
            body="",
            footer=footer,
            icon_path=icon_path,
            parent=parent,
            accent_color=self._accent_for_state(self._state),
            minimum_height=minimum_height if not compact else max(142, minimum_height - 18),
            clickable=clickable,
            enable_hover_effect=True,
            show_accent_bar=True,
            compact=compact,
        )

        self._build_action_content()
        self.set_content_widget(self._content_root)
        self.clicked.connect(self._on_card_clicked)

        self._apply_action_style()
        self.set_description(self._description)
        self.set_badge_text(self._badge_text)
        self.set_count_block(self._count_text, self._count_label)
        self.set_primary_button_text(self._primary_button_text)
        self.set_secondary_button_text(self._secondary_button_text)
        self.set_show_secondary_button(self._show_secondary_button)
        self.set_show_action_row(self._show_action_row)
        self._refresh_visibility()

    # ========================================================
    # UI building
    # ========================================================

    def _build_action_content(self) -> None:
        self._content_root = QWidget(self)
        self._content_root.setObjectName("QuickActionCardContentRoot")

        root = QVBoxLayout(self._content_root)
        root.setContentsMargins(0, 3 if not self._compact else 1, 0, 0)
        root.setSpacing(8 if not self._compact else 6)

        # ----------------------------------------------------
        # Top meta row: badge + count block
        # ----------------------------------------------------
        self._top_row = QWidget(self._content_root)
        top_layout = QHBoxLayout(self._top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8 if not self._compact else 6)

        self._badge_label = QLabel(self._top_row)
        self._badge_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._count_block = QWidget(self._top_row)
        count_layout = QVBoxLayout(self._count_block)
        count_layout.setContentsMargins(0, 0, 0, 0)
        count_layout.setSpacing(0)

        if _HAS_GLOW_LABEL:
            self._count_value_label = GlowLabel(
                role=GlowLabel.ROLE_STATUS if not self._compact else GlowLabel.ROLE_SUBTITLE,
                align_center=False,
                use_outline=False,
                enable_paint_glow=True,
                initial_glow_strength=0.40,
                initial_glow_blur=16 if not self._compact else 12,
            )
        else:
            self._count_value_label = QLabel(self._count_block)

        self._count_text_label = QLabel(self._count_block)

        count_layout.addWidget(self._count_value_label)
        count_layout.addWidget(self._count_text_label)

        top_layout.addWidget(self._badge_label, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        top_layout.addStretch(1)
        top_layout.addWidget(self._count_block, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)

        # ----------------------------------------------------
        # Description
        # ----------------------------------------------------
        self._description_label = QLabel(self._content_root)
        self._description_label.setWordWrap(True)
        self._description_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        # ----------------------------------------------------
        # Buttons
        # ----------------------------------------------------
        self._action_row = QWidget(self._content_root)
        action_layout = QHBoxLayout(self._action_row)
        action_layout.setContentsMargins(0, 2 if not self._compact else 0, 0, 0)
        action_layout.setSpacing(8 if not self._compact else 6)

        self._primary_button = AnimatedButton(
            text=self._primary_button_text,
            variant=AnimatedButton.VARIANT_PRIMARY,
            size=AnimatedButton.SIZE_MD if not self._compact else AnimatedButton.SIZE_SM,
            minimum_width=96 if not self._compact else 80,
        )
        self._primary_button.clicked.connect(self.primary_action_clicked.emit)

        self._secondary_button = AnimatedButton(
            text=self._secondary_button_text or "More",
            variant=AnimatedButton.VARIANT_SECONDARY,
            size=AnimatedButton.SIZE_MD if not self._compact else AnimatedButton.SIZE_SM,
            minimum_width=88 if not self._compact else 74,
        )
        self._secondary_button.clicked.connect(self.secondary_action_clicked.emit)

        action_layout.addWidget(self._primary_button)
        action_layout.addWidget(self._secondary_button)
        action_layout.addStretch(1)

        # ----------------------------------------------------
        # Assemble
        # ----------------------------------------------------
        root.addWidget(self._top_row)
        root.addWidget(self._description_label)
        root.addWidget(self._action_row)

    # ========================================================
    # Styling
    # ========================================================

    def _accent_for_state(self, state: str) -> str:
        state = safe_str(state, self.STATE_PRIMARY).strip().lower()
        if state == self.STATE_SUCCESS:
            return self._theme.success_accent
        if state == self.STATE_WARNING:
            return self._theme.warning_accent
        if state == self.STATE_DANGER:
            return self._theme.danger_accent
        if state == self.STATE_NEUTRAL:
            return self._theme.neutral_accent
        return self._theme.primary_accent

    def _badge_colors(self, state: str) -> tuple[str, str, str]:
        accent = QColor(self._accent_for_state(state))
        bg = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.16)"
        border = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.34)"
        text = self._theme.badge_text
        return bg, border, text

    def _apply_action_style(self) -> None:
        accent = self._accent_for_state(self._state)
        badge_bg, badge_border, badge_text = self._badge_colors(self._state)

        desc_size = 11 if not self._compact else 10
        badge_size = 10 if not self._compact else 9
        count_size = 20 if not self._compact else 16
        count_label_size = 9 if not self._compact else 8

        self._description_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.body_color};
                font-size: {desc_size}px;
                font-weight: 500;
                background: transparent;
            }}
            """
        )

        self._badge_label.setStyleSheet(
            f"""
            QLabel {{
                color: {badge_text};
                font-size: {badge_size}px;
                font-weight: 700;
                border: 1px solid {badge_border};
                border-radius: {12 if not self._compact else 10}px;
                background: {badge_bg};
                padding: {4 if not self._compact else 3}px {8 if not self._compact else 6}px;
            }}
            """
        )

        if _HAS_GLOW_LABEL and isinstance(self._count_value_label, GlowLabel):
            self._count_value_label.set_glow_color(accent)
            self._count_value_label.set_text_color(self._theme.count_text)
            self._count_value_label.set_role(GlowLabel.ROLE_STATUS if not self._compact else GlowLabel.ROLE_SUBTITLE)
        else:
            self._count_value_label.setStyleSheet(
                f"""
                QLabel {{
                    color: {self._theme.count_text};
                    font-size: {count_size}px;
                    font-weight: 800;
                    background: transparent;
                }}
                """
            )

        self._count_text_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.count_subtle};
                font-size: {count_label_size}px;
                font-weight: 600;
                background: transparent;
            }}
            """
        )

        self.set_accent_color(accent)

    # ========================================================
    # Visibility
    # ========================================================

    def _refresh_visibility(self) -> None:
        self._badge_label.setVisible(self._show_badge and bool(self._badge_text))
        has_count = bool(self._count_text) or bool(self._count_label)
        self._count_block.setVisible(self._show_count_block and has_count)
        self._top_row.setVisible(self._badge_label.isVisible() or self._count_block.isVisible())

        self._description_label.setVisible(bool(self._description))
        self._secondary_button.setVisible(self._show_secondary_button and bool(self._secondary_button_text))
        self._action_row.setVisible(self._show_action_row)

    # ========================================================
    # Public getters
    # ========================================================

    def state(self) -> str:
        return self._state

    def description(self) -> str:
        return self._description

    def badge_text(self) -> str:
        return self._badge_text

    def count_text(self) -> str:
        return self._count_text

    def count_label(self) -> str:
        return self._count_label

    # ========================================================
    # Public setters
    # ========================================================

    def set_state(self, state: str) -> None:
        self._state = safe_str(state, self.STATE_PRIMARY).strip().lower() or self.STATE_PRIMARY
        self._apply_action_style()

    def set_description(self, description: str) -> None:
        self._description = safe_str(description, "").strip()
        self._description_label.setText(self._description)
        self.description_changed.emit(self._description)
        self._refresh_visibility()

    def set_badge_text(self, badge_text: str) -> None:
        self._badge_text = safe_str(badge_text, "").strip()
        self._badge_label.setText(self._badge_text)
        self.badge_changed.emit(self._badge_text)
        self._refresh_visibility()

    def set_count_block(self, count_text: str, count_label: str = "") -> None:
        self._count_text = safe_str(count_text, "").strip()
        self._count_label = safe_str(count_label, "").strip()

        if _HAS_GLOW_LABEL and isinstance(self._count_value_label, GlowLabel):
            self._count_value_label.set_text(self._count_text)
        else:
            self._count_value_label.setText(self._count_text)

        self._count_text_label.setText(self._count_label)
        self.count_changed.emit(self._count_text)
        self._refresh_visibility()

    def set_primary_button_text(self, text: str) -> None:
        self._primary_button_text = safe_str(text, "Open").strip() or "Open"
        self._primary_button.setText(self._primary_button_text)

    def set_secondary_button_text(self, text: str) -> None:
        self._secondary_button_text = safe_str(text, "").strip()
        self._secondary_button.setText(self._secondary_button_text or "More")
        self._refresh_visibility()

    def set_show_badge(self, visible: bool) -> None:
        self._show_badge = bool(visible)
        self._refresh_visibility()

    def set_show_count_block(self, visible: bool) -> None:
        self._show_count_block = bool(visible)
        self._refresh_visibility()

    def set_show_secondary_button(self, visible: bool) -> None:
        self._show_secondary_button = bool(visible)
        self._refresh_visibility()

    def set_show_action_row(self, visible: bool) -> None:
        self._show_action_row = bool(visible)
        self._refresh_visibility()

    def set_card_click_enabled(self, enabled: bool) -> None:
        self.set_clickable(bool(enabled))

    # ========================================================
    # Convenience state presets
    # ========================================================

    def mark_primary(self, badge_text: str = "") -> None:
        self.set_state(self.STATE_PRIMARY)
        if badge_text:
            self.set_badge_text(badge_text)

    def mark_success(self, badge_text: str = "Ready") -> None:
        self.set_state(self.STATE_SUCCESS)
        self.set_badge_text(badge_text)

    def mark_warning(self, badge_text: str = "Pending") -> None:
        self.set_state(self.STATE_WARNING)
        self.set_badge_text(badge_text)

    def mark_danger(self, badge_text: str = "Attention") -> None:
        self.set_state(self.STATE_DANGER)
        self.set_badge_text(badge_text)

    # ========================================================
    # Composite payload application
    # ========================================================

    def apply_action_payload(self, payload: Dict[str, Any]) -> None:
        """
        Convenience method for dashboard/admin use.

        Accepted payload example:
        {
            "title": "Storage",
            "subtitle": "View storage usage",
            "description": "Database, exports, QR, reports, and backups.",
            "badge_text": "Admin",
            "count_text": "142",
            "count_label": "Records",
            "state": "primary",
            "primary_button_text": "Open",
            "secondary_button_text": "Export"
        }
        """
        if "title" in payload:
            self.set_title(safe_str(payload.get("title"), ""))
        if "subtitle" in payload:
            self.set_subtitle(safe_str(payload.get("subtitle"), ""))
        if "description" in payload:
            self.set_description(safe_str(payload.get("description"), ""))
        if "badge_text" in payload:
            self.set_badge_text(safe_str(payload.get("badge_text"), ""))
        if "count_text" in payload or "count_label" in payload:
            self.set_count_block(
                safe_str(payload.get("count_text"), self._count_text),
                safe_str(payload.get("count_label"), self._count_label),
            )
        if "state" in payload:
            self.set_state(safe_str(payload.get("state"), self.STATE_PRIMARY))
        if "primary_button_text" in payload:
            self.set_primary_button_text(safe_str(payload.get("primary_button_text"), "Open"))
        if "secondary_button_text" in payload:
            self.set_secondary_button_text(safe_str(payload.get("secondary_button_text"), ""))

    # ========================================================
    # Click behavior
    # ========================================================

    def _on_card_clicked(self) -> None:
        self.card_action_clicked.emit()

    # ========================================================
    # Diagnostics
    # ========================================================

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "title": self.title(),
            "subtitle": self.subtitle(),
            "description": self._description,
            "badge_text": self._badge_text,
            "count_text": self._count_text,
            "count_label": self._count_label,
            "state": self._state,
            "primary_button_text": self._primary_button_text,
            "secondary_button_text": self._secondary_button_text,
            "show_badge": self._show_badge,
            "show_count_block": self._show_count_block,
            "show_secondary_button": self._show_secondary_button,
            "show_action_row": self._show_action_row,
            "compact": self._compact,
        }