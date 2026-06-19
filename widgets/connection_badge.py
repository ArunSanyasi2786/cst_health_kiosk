"""
widgets/connection_badge.py

Premium connection badge / connection status card for the
CST Health Monitoring Station kiosk.

Why this file matters:
- It is the reusable UI widget that represents runtime connectivity state
- It is designed for:
    - mode selection screen hardware readiness display
    - measuring screen serial/ESP32 status banner
    - admin panel hardware diagnostics block
    - settings screen connection preview
    - any screen that needs a compact but polished connection summary
- It keeps the kiosk visually consistent with the rest of the custom UI by
  building on the same design language used in:
    - widgets/glass_card.py
    - widgets/animated_button.py
    - widgets/glow_label.py
- It is designed to work directly with:
    - services/connection_service.py snapshot payloads
    - services/connection_service.py connection_badge_payload()
    - optional AppState connection snapshots

Typical payloads supported:
1) connection_service.snapshot()
   {
       "mode": "hardware",
       "network_connected": True,
       "serial_connected": True,
       "esp32_connected": True,
       "selected_port": "COM4",
       "available_ports": [...],
       "connection_label": "Hardware Connected",
       "connection_detail": "ESP32 is connected and sending data.",
       ...
   }

2) connection_service.connection_badge_payload()
   {
       "connected": True,
       "waiting": False,
       "label": "Hardware Connected",
       "detail": "ESP32 is connected and sending data."
   }

Design goals:
- premium glossy medical look
- very readable at a glance
- safe fallbacks when payloads are incomplete
- reusable and low-coupling
- lightweight enough for Raspberry Pi kiosk deployment

IMPORTANT FIXES IN THIS VERSION:
- prevents hidden duplicate GlassCard title/subtitle/body spacing
- keeps the badge compact inside measuring_screen right panel
- safer fallback if AnimatedButton import/creation fails
- avoids extra vertical gap caused by duplicated detail/body rendering
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.logger import get_logger

try:
    from core.utils import safe_str, safe_int
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
            return int(value)
        except Exception:
            return default

try:
    from core.constants import MODE_DEMO, MODE_HARDWARE
except Exception:  # pragma: no cover
    MODE_DEMO = "demo"
    MODE_HARDWARE = "hardware"

try:
    from widgets.animated_button import AnimatedButton
    _HAS_ANIMATED_BUTTON = True
except Exception:  # pragma: no cover
    AnimatedButton = None  # type: ignore
    _HAS_ANIMATED_BUTTON = False

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
class ConnectionBadgeTheme:
    """
    Visual theme for the connection badge.
    """
    headline_color: str = "#F4FCFF"
    detail_color: str = "rgba(214, 234, 247, 0.88)"
    meta_text_color: str = "#EAF7FF"
    meta_subtle_color: str = "rgba(196, 220, 240, 0.82)"

    chip_text: str = "#F4FCFF"

    primary_accent: str = "#39D8FF"
    demo_accent: str = "#68D8FF"
    online_accent: str = "#3DE28F"
    waiting_accent: str = "#FFD15E"
    offline_accent: str = "#FF6E87"
    serial_accent: str = "#FFAA54"
    neutral_accent: str = "#7FD1FF"

    chip_bg_alpha: float = 0.16
    chip_border_alpha: float = 0.35

    dot_border: str = "rgba(255, 255, 255, 0.20)"
    strip_bg: str = "rgba(36, 63, 97, 0.16)"
    strip_border: str = "rgba(153, 216, 255, 0.18)"


DEFAULT_CONNECTION_BADGE_THEME = ConnectionBadgeTheme()


# ============================================================
# Widget
# ============================================================

class ConnectionBadge(GlassCard):
    """
    Premium reusable connection status card.

    Main capabilities:
    - headline status label
    - detail text
    - animated state dot
    - mode / port / network chips
    - optional reconnect button
    - direct application of connection_service snapshots or compact badge payloads

    FIX NOTE:
    This widget intentionally keeps GlassCard title/subtitle/body blank so that
    only the custom internal content controls the height. That removes the extra
    hidden spacing that was creating the stubborn gap in measuring_screen.
    """

    clicked_badge = pyqtSignal()
    reconnect_requested = pyqtSignal()
    details_requested = pyqtSignal()

    role_changed = pyqtSignal(str)
    connection_payload_applied = pyqtSignal(dict)

    ROLE_DEMO = "demo"
    ROLE_ONLINE = "online"
    ROLE_WAITING = "waiting"
    ROLE_OFFLINE = "offline"
    ROLE_SERIAL_ONLY = "serial_only"
    ROLE_NEUTRAL = "neutral"

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        title: str = "Connection Status",
        subtitle: str = "Serial / ESP32 / network readiness",
        detail: str = "",
        icon_path: str = "",
        footer: str = "",
        role: str = ROLE_NEUTRAL,
        compact: bool = False,
        clickable: bool = True,
        show_meta_row: bool = True,
        show_action_button: bool = True,
        action_button_text: str = "Reconnect",
        theme: Optional[ConnectionBadgeTheme] = None,
        minimum_height: int = 148,
    ) -> None:
        try:
            self._logger = logger.bind(component="ConnectionBadge")
        except Exception:
            self._logger = logger

        self._theme = theme or DEFAULT_CONNECTION_BADGE_THEME
        self._compact = bool(compact)
        self._role = safe_str(role, self.ROLE_NEUTRAL).strip().lower() or self.ROLE_NEUTRAL

        self._card_title = safe_str(title, "Connection Status").strip() or "Connection Status"
        self._card_subtitle = safe_str(subtitle, "").strip()
        self._base_footer = safe_str(footer, "").strip()

        self._headline = ""
        self._detail = safe_str(detail, "").strip()

        self._mode = MODE_DEMO
        self._network_connected = False
        self._serial_connected = False
        self._esp32_connected = False
        self._selected_port = ""
        self._available_ports_count = 0
        self._last_error = ""

        self._show_meta_row = bool(show_meta_row)
        self._show_action_button = bool(show_action_button)
        self._action_button_text = safe_str(action_button_text, "Reconnect").strip() or "Reconnect"

        self._pulse_alpha = 0.70
        self._pulse_direction = 1

        # IMPORTANT:
        # Keep GlassCard text fields empty so it does NOT reserve hidden height
        # through title/subtitle/body duplication.
        super().__init__(
            title="",
            subtitle="",
            body="",
            footer="",
            icon_path=icon_path,
            parent=parent,
            accent_color=self._accent_for_role(self._role),
            minimum_height=minimum_height if not compact else max(108, minimum_height - 40),
            clickable=clickable,
            enable_hover_effect=True,
            show_accent_bar=True,
            compact=compact,
        )

        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(85)
        self._pulse_timer.timeout.connect(self._tick_pulse)

        self._build_content()
        self.set_content_widget(self._content_root)
        self.clicked.connect(self._on_card_clicked)

        self._apply_style()
        self.set_headline(self._default_headline_for_role(self._role))
        self.set_detail_text(self._detail)
        self.set_action_button_text(self._action_button_text)
        self.set_role(self._role)
        self._apply_footer_text()
        self._refresh_visibility()

    # ========================================================
    # UI
    # ========================================================

    def _build_content(self) -> None:
        self._content_root = QWidget(self)
        self._content_root.setObjectName("ConnectionBadgeContentRoot")
        self._content_root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self._content_root.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        root = QVBoxLayout(self._content_root)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4 if self._ultra_compact else (5 if not self._compact else 4))

        # ----------------------------------------------------
        # Headline row
        # ----------------------------------------------------
        self._headline_row = QWidget(self._content_root)
        self._headline_row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        headline_layout = QHBoxLayout(self._headline_row)
        headline_layout.setContentsMargins(0, 0, 0, 0)
        headline_layout.setSpacing(5 if self._ultra_compact else (8 if not self._compact else 6))

        self._state_dot = QLabel(self._headline_row)
        self._state_dot.setFixedSize(9 if self._ultra_compact else (12 if not self._compact else 10), 9 if self._ultra_compact else (12 if not self._compact else 10))
        self._state_dot.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        if _HAS_GLOW_LABEL:
            try:
                self._headline_label = GlowLabel(
                    role=getattr(GlowLabel, "ROLE_STATUS", 0) if not self._compact else getattr(GlowLabel, "ROLE_SUBTITLE", 0),
                    align_center=False,
                    use_outline=False,
                    enable_paint_glow=True,
                    initial_glow_strength=0.48,
                    initial_glow_blur=16 if not self._compact else 12,
                )
            except Exception:
                self._headline_label = QLabel(self._headline_row)
                self._headline_label.setWordWrap(True)
        else:
            self._headline_label = QLabel(self._headline_row)
            self._headline_label.setWordWrap(True)

        self._headline_label.setWordWrap(True)
        self._headline_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self._state_chip = QLabel(self._headline_row)
        self._state_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._state_chip.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        headline_layout.addWidget(
            self._state_dot,
            0,
            alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        headline_layout.addWidget(
            self._headline_label,
            1,
            alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        headline_layout.addWidget(
            self._state_chip,
            0,
            alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )

        # ----------------------------------------------------
        # Detail text
        # ----------------------------------------------------
        self._detail_label = QLabel(self._content_root)
        self._detail_label.setWordWrap(True)
        self._detail_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._detail_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        # ----------------------------------------------------
        # Meta strip
        # ----------------------------------------------------
        self._meta_strip = QFrame(self._content_root)
        self._meta_strip.setObjectName("ConnectionBadgeMetaStrip")
        self._meta_strip.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        meta_layout = QHBoxLayout(self._meta_strip)
        meta_layout.setContentsMargins(
            8 if not self._compact else 6,
            5 if not self._compact else 4,
            8 if not self._compact else 6,
            5 if not self._compact else 4,
        )
        meta_layout.setSpacing(6 if not self._compact else 4)

        self._mode_chip = self._make_meta_chip(self._meta_strip)
        self._port_chip = self._make_meta_chip(self._meta_strip)
        self._network_chip = self._make_meta_chip(self._meta_strip)

        meta_layout.addWidget(
            self._mode_chip,
            0,
            alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        meta_layout.addWidget(
            self._port_chip,
            0,
            alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        meta_layout.addWidget(
            self._network_chip,
            0,
            alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        meta_layout.addStretch(1)

        # ----------------------------------------------------
        # Action row
        # ----------------------------------------------------
        self._action_row = QWidget(self._content_root)
        self._action_row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        action_layout = QHBoxLayout(self._action_row)
        action_layout.setContentsMargins(0, 1 if not self._compact else 0, 0, 0)
        action_layout.setSpacing(5 if self._ultra_compact else (8 if not self._compact else 6))

        self._reconnect_button = self._create_action_button(
            text=self._action_button_text,
            variant="secondary",
            min_width=104 if not self._compact else 84,
        )
        self._reconnect_button.clicked.connect(self.reconnect_requested.emit)

        self._details_button = self._create_action_button(
            text="Details",
            variant="ghost",
            min_width=92 if not self._compact else 74,
        )
        self._details_button.clicked.connect(self.details_requested.emit)

        action_layout.addWidget(self._reconnect_button, 0, alignment=Qt.AlignmentFlag.AlignLeft)
        action_layout.addWidget(self._details_button, 0, alignment=Qt.AlignmentFlag.AlignLeft)
        action_layout.addStretch(1)

        root.addWidget(self._headline_row)
        root.addWidget(self._detail_label)
        root.addWidget(self._meta_strip)
        root.addWidget(self._action_row)

    def _make_meta_chip(self, parent: QWidget) -> QLabel:
        chip = QLabel(parent)
        chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chip.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        chip.setWordWrap(False)
        return chip

    def _create_action_button(self, *, text: str, variant: str, min_width: int) -> QWidget:
        if _HAS_ANIMATED_BUTTON and AnimatedButton is not None:
            try:
                variant_map = {
                    "primary": getattr(AnimatedButton, "VARIANT_PRIMARY", None),
                    "secondary": getattr(AnimatedButton, "VARIANT_SECONDARY", None),
                    "ghost": getattr(AnimatedButton, "VARIANT_GHOST", None),
                    "success": getattr(AnimatedButton, "VARIANT_SUCCESS", None),
                }
                size_value = getattr(
                    AnimatedButton,
                    "SIZE_MD" if not self._compact else "SIZE_SM",
                    None,
                )
                button = AnimatedButton(
                    text=text,
                    parent=self._action_row,
                    variant=variant_map.get(variant),
                    size=size_value,
                    minimum_width=min_width,
                )
                try:
                    if hasattr(button, "set_accent_color"):
                        if variant == "secondary":
                            button.set_accent_color(self._theme.primary_accent)
                        elif variant == "ghost":
                            button.set_accent_color(self._theme.neutral_accent)
                except Exception:
                    pass
                return button
            except Exception:
                pass

        button = QPushButton(text, self._action_row)
        button.setMinimumWidth(min_width)
        button.setMinimumHeight(34 if not self._compact else 28)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            """
            QPushButton {
                color: #F6FCFF;
                border: 1px solid rgba(157, 220, 255, 0.28);
                border-radius: 12px;
                padding: 6px 12px;
                font-size: 10px;
                font-weight: 700;
                background: rgba(22, 47, 82, 0.72);
            }
            QPushButton:hover {
                background: rgba(34, 66, 110, 0.90);
                border-color: rgba(186, 233, 255, 0.40);
            }
            """
        )
        return button

    # ========================================================
    # Styling
    # ========================================================

    def _accent_for_role(self, role: str) -> str:
        role = safe_str(role, self.ROLE_NEUTRAL).strip().lower()
        if role == self.ROLE_DEMO:
            return self._theme.demo_accent
        if role == self.ROLE_ONLINE:
            return self._theme.online_accent
        if role == self.ROLE_WAITING:
            return self._theme.waiting_accent
        if role == self.ROLE_SERIAL_ONLY:
            return self._theme.serial_accent
        if role == self.ROLE_OFFLINE:
            return self._theme.offline_accent
        return self._theme.neutral_accent

    def _chip_colors(self, role: str) -> tuple[str, str, str]:
        accent = QColor(self._accent_for_role(role))
        bg = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, {self._theme.chip_bg_alpha:.3f})"
        border = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, {self._theme.chip_border_alpha:.3f})"
        text = self._theme.chip_text
        return bg, border, text

    def _apply_style(self) -> None:
        accent = self._accent_for_role(self._role)
        chip_bg, chip_border, chip_text = self._chip_colors(self._role)

        detail_size = 10 if self._compact else 11
        chip_size = 9 if self._compact else 10
        strip_radius = 13 if not self._compact else 11

        self.set_accent_color(accent)

        if _HAS_GLOW_LABEL and isinstance(self._headline_label, GlowLabel):
            try:
                self._headline_label.set_glow_color(accent)
                self._headline_label.set_text_color(self._theme.headline_color)
                role_value = getattr(GlowLabel, "ROLE_STATUS", 0) if not self._compact else getattr(GlowLabel, "ROLE_SUBTITLE", 0)
                if hasattr(self._headline_label, "set_role"):
                    self._headline_label.set_role(role_value)
            except Exception:
                pass
        else:
            self._headline_label.setStyleSheet(
                f"""
                QLabel {{
                    color: {self._theme.headline_color};
                    font-size: {'12px' if self._ultra_compact else ('16px' if not self._compact else '13px')};
                    font-weight: 800;
                    background: transparent;
                }}
                """
            )

        self._detail_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.detail_color};
                font-size: {detail_size}px;
                font-weight: 500;
                background: transparent;
            }}
            """
        )

        self._state_chip.setStyleSheet(
            f"""
            QLabel {{
                color: {chip_text};
                font-size: {chip_size}px;
                font-weight: 700;
                border: 1px solid {chip_border};
                border-radius: {8 if self._ultra_compact else (11 if not self._compact else 9)}px;
                background: {chip_bg};
                padding: {2 if self._ultra_compact else (3 if not self._compact else 2)}px {5 if self._ultra_compact else (8 if not self._compact else 6)}px;
            }}
            """
        )

        self._meta_strip.setStyleSheet(
            f"""
            QFrame#ConnectionBadgeMetaStrip {{
                border: 1px solid {self._theme.strip_border};
                border-radius: {strip_radius}px;
                background: {self._theme.strip_bg};
            }}
            """
        )

        meta_chip_style = f"""
        QLabel {{
            color: {self._theme.meta_text_color};
            font-size: {'8px' if self._ultra_compact else ('9px' if self._compact else '10px')};
            font-weight: 700;
            border: 1px solid rgba(149, 213, 255, 0.20);
            border-radius: {7 if self._ultra_compact else (9 if not self._compact else 8)}px;
            background: rgba(53, 86, 122, 0.18);
            padding: 2px {4 if self._ultra_compact else (7 if not self._compact else 5)}px;
        }}
        """
        self._mode_chip.setStyleSheet(meta_chip_style)
        self._port_chip.setStyleSheet(meta_chip_style)
        self._network_chip.setStyleSheet(meta_chip_style)

        self._apply_dot_style()
        self._refresh_pulse_state()

    def _apply_dot_style(self) -> None:
        accent = QColor(self._accent_for_role(self._role))
        alpha = max(0.18, min(1.0, self._pulse_alpha))
        bg = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, {alpha:.3f})"
        radius = self._state_dot.width() // 2

        self._state_dot.setStyleSheet(
            f"""
            QLabel {{
                min-width: {self._state_dot.width()}px;
                min-height: {self._state_dot.height()}px;
                max-width: {self._state_dot.width()}px;
                max-height: {self._state_dot.height()}px;
                border-radius: {radius}px;
                background: {bg};
                border: 1px solid {self._theme.dot_border};
            }}
            """
        )

    def _refresh_pulse_state(self) -> None:
        pulsing = self._role in {self.ROLE_ONLINE, self.ROLE_WAITING, self.ROLE_SERIAL_ONLY}
        if pulsing:
            if not self._pulse_timer.isActive():
                self._pulse_timer.start()
        else:
            self._pulse_timer.stop()
            self._pulse_alpha = 0.80 if self._role == self.ROLE_DEMO else 0.70
            self._apply_dot_style()

    # ========================================================
    # Pulse animation
    # ========================================================

    def _tick_pulse(self) -> None:
        if self._pulse_direction > 0:
            self._pulse_alpha += 0.07
            if self._pulse_alpha >= 1.0:
                self._pulse_alpha = 1.0
                self._pulse_direction = -1
        else:
            self._pulse_alpha -= 0.07
            floor = 0.35 if self._role == self.ROLE_WAITING else 0.48
            if self._pulse_alpha <= floor:
                self._pulse_alpha = floor
                self._pulse_direction = 1

        self._apply_dot_style()

    # ========================================================
    # Visibility
    # ========================================================

    def _refresh_visibility(self) -> None:
        self._headline_row.setVisible(bool(self._headline.strip()))
        self._detail_label.setVisible(bool(self._detail.strip()))

        self._meta_strip.setVisible(
            self._show_meta_row and (
                bool(self._mode_chip.text().strip())
                or bool(self._port_chip.text().strip())
                or bool(self._network_chip.text().strip())
            )
        )

        show_reconnect = self._show_action_button and self._role in {
            self.ROLE_WAITING,
            self.ROLE_OFFLINE,
            self.ROLE_SERIAL_ONLY,
        }
        show_details = True

        self._reconnect_button.setVisible(show_reconnect)
        self._details_button.setVisible(show_details)
        self._action_row.setVisible(self._show_action_button and (show_reconnect or show_details))

    # ========================================================
    # Footer helper
    # ========================================================

    def _apply_footer_text(self) -> None:
        footer_text = self._last_error or self._base_footer
        super().set_footer(footer_text)

    # ========================================================
    # Headline / detail / meta setters
    # ========================================================

    def _default_headline_for_role(self, role: str) -> str:
        role = safe_str(role, self.ROLE_NEUTRAL).strip().lower()
        if role == self.ROLE_DEMO:
            return "Demo Mode Active"
        if role == self.ROLE_ONLINE:
            return "Hardware Connected"
        if role == self.ROLE_SERIAL_ONLY:
            return "Serial Connected"
        if role == self.ROLE_WAITING:
            return "Hardware Waiting"
        if role == self.ROLE_OFFLINE:
            return "Disconnected"
        return "Connection Status"

    def set_headline(self, headline: str) -> None:
        self._headline = safe_str(headline, "").strip()
        if _HAS_GLOW_LABEL and isinstance(self._headline_label, GlowLabel):
            try:
                if hasattr(self._headline_label, "set_text"):
                    self._headline_label.set_text(self._headline)
                else:
                    self._headline_label.setText(self._headline)
            except Exception:
                self._headline_label.setText(self._headline)
        else:
            self._headline_label.setText(self._headline)
        self._refresh_visibility()

    def headline(self) -> str:
        return self._headline

    def set_detail_text(self, detail: str) -> None:
        self._detail = safe_str(detail, "").strip()
        self._detail_label.setText(self._detail)
        self._refresh_visibility()

    def detail_text(self) -> str:
        return self._detail

    def set_state_chip_text(self, text: str) -> None:
        self._state_chip.setText(safe_str(text, "").strip())
        self._refresh_visibility()

    def set_mode_chip_text(self, text: str) -> None:
        self._mode_chip.setText(safe_str(text, "").strip())
        self._refresh_visibility()

    def set_port_chip_text(self, text: str) -> None:
        self._port_chip.setText(safe_str(text, "").strip())
        self._refresh_visibility()

    def set_network_chip_text(self, text: str) -> None:
        self._network_chip.setText(safe_str(text, "").strip())
        self._refresh_visibility()

    def set_action_button_text(self, text: str) -> None:
        self._action_button_text = safe_str(text, "Reconnect").strip() or "Reconnect"

        try:
            if hasattr(self._reconnect_button, "setText"):
                self._reconnect_button.setText(self._action_button_text)
        except Exception:
            pass

    # ========================================================
    # Role / state setters
    # ========================================================

    def set_role(self, role: str) -> None:
        normalized = safe_str(role, self.ROLE_NEUTRAL).strip().lower() or self.ROLE_NEUTRAL
        if normalized not in {
            self.ROLE_DEMO,
            self.ROLE_ONLINE,
            self.ROLE_WAITING,
            self.ROLE_OFFLINE,
            self.ROLE_SERIAL_ONLY,
            self.ROLE_NEUTRAL,
        }:
            normalized = self.ROLE_NEUTRAL

        self._role = normalized
        self.set_accent_color(self._accent_for_role(self._role))
        self._apply_style()
        self.role_changed.emit(self._role)
        self._refresh_visibility()

    def role(self) -> str:
        return self._role

    # ========================================================
    # Snapshot / payload interpretation
    # ========================================================

    def _infer_role_from_connection_snapshot(self, snapshot: Mapping[str, Any]) -> str:
        mode = safe_str(snapshot.get("mode"), MODE_DEMO).strip().lower()
        demo_mode_active = bool(snapshot.get("demo_mode_active", mode == MODE_DEMO))
        serial_connected = bool(snapshot.get("serial_connected", False))
        esp32_connected = bool(snapshot.get("esp32_connected", False))
        available_ports = snapshot.get("available_ports", [])
        available_port_count = len(available_ports) if isinstance(available_ports, list) else safe_int(snapshot.get("available_ports_count"), 0)

        if demo_mode_active or mode == MODE_DEMO:
            return self.ROLE_DEMO
        if esp32_connected:
            return self.ROLE_ONLINE
        if serial_connected:
            return self.ROLE_SERIAL_ONLY
        if available_port_count > 0:
            return self.ROLE_WAITING
        return self.ROLE_OFFLINE

    def _infer_role_from_badge_payload(self, payload: Mapping[str, Any]) -> str:
        connected = bool(payload.get("connected", False))
        waiting = bool(payload.get("waiting", False))

        if connected:
            return self.ROLE_ONLINE
        if waiting:
            return self.ROLE_WAITING
        return self.ROLE_OFFLINE

    def apply_connection_snapshot(self, snapshot: Mapping[str, Any]) -> None:
        """
        Apply a full snapshot payload from services/connection_service.py.
        """
        data = dict(snapshot or {})

        self._mode = safe_str(data.get("mode"), MODE_DEMO).strip().lower() or MODE_DEMO
        self._network_connected = bool(data.get("network_connected", False))
        self._serial_connected = bool(data.get("serial_connected", False))
        self._esp32_connected = bool(data.get("esp32_connected", False))
        self._selected_port = safe_str(data.get("selected_port"), "").strip()
        self._last_error = safe_str(data.get("last_error"), "").strip()

        available_ports = data.get("available_ports", [])
        self._available_ports_count = len(available_ports) if isinstance(available_ports, list) else safe_int(data.get("available_ports_count"), 0)

        role = self._infer_role_from_connection_snapshot(data)
        self.set_role(role)

        label = safe_str(data.get("connection_label"), "").strip() or self._default_headline_for_role(role)
        detail = safe_str(data.get("connection_detail"), "").strip()

        if not detail:
            if role == self.ROLE_DEMO:
                detail = "Using simulated measurements. Hardware connection is optional."
            elif role == self.ROLE_ONLINE:
                detail = "ESP32 is connected and sending data."
            elif role == self.ROLE_SERIAL_ONLY:
                detail = "Serial link is connected, waiting for reliable device heartbeat."
            elif role == self.ROLE_WAITING:
                detail = "Hardware is available but not connected yet."
            else:
                detail = "No serial hardware connection detected."

        self.set_headline(label)
        self.set_detail_text(detail)
        self.set_state_chip_text(label)

        mode_chip = "Demo" if self._mode == MODE_DEMO else "Hardware"
        self.set_mode_chip_text(mode_chip)

        if self._selected_port:
            self.set_port_chip_text(self._selected_port)
        elif self._available_ports_count > 0:
            self.set_port_chip_text(f"{self._available_ports_count} Ports")
        else:
            self.set_port_chip_text("No Port")

        self.set_network_chip_text("Network Online" if self._network_connected else "Network Offline")

        self._apply_footer_text()
        self._refresh_visibility()
        self.connection_payload_applied.emit(dict(data))

    def apply_badge_payload(self, payload: Mapping[str, Any], *, mode: str = MODE_DEMO) -> None:
        """
        Apply a compact payload from connection_service.connection_badge_payload().
        """
        data = dict(payload or {})

        self._mode = safe_str(mode, MODE_DEMO).strip().lower() or MODE_DEMO
        role = self._infer_role_from_badge_payload(data)

        if self._mode == MODE_DEMO:
            role = self.ROLE_DEMO

        self.set_role(role)

        label = safe_str(data.get("label"), "").strip() or self._default_headline_for_role(role)
        detail = safe_str(data.get("detail"), "").strip()

        self.set_headline(label)
        self.set_detail_text(detail)
        self.set_state_chip_text(label)

        self.set_mode_chip_text("Demo" if self._mode == MODE_DEMO else "Hardware")
        self.set_port_chip_text(self._selected_port or ("Optional" if self._mode == MODE_DEMO else "No Port"))
        self.set_network_chip_text(
            "Ready" if bool(data.get("connected", False))
            else "Waiting" if bool(data.get("waiting", False))
            else "Offline"
        )

        self._apply_footer_text()
        self._refresh_visibility()
        self.connection_payload_applied.emit(dict(data))

    def refresh_from_app_state(self, app_state: Optional[object] = None) -> None:
        """
        Best-effort refresh from AppState if it exposes connection_snapshot().
        """
        source = app_state if app_state is not None else None
        if source is None:
            try:
                parent_state = getattr(self, "_app_state", None)
                if parent_state is not None:
                    source = parent_state
            except Exception:
                source = None

        if source is None:
            try:
                from core.app_state import get_app_state  # local safe import
                source = get_app_state()
            except Exception:
                source = None

        if source is None:
            return

        try:
            snapshot_method = getattr(source, "connection_snapshot", None)
            if callable(snapshot_method):
                snapshot = snapshot_method()
                if isinstance(snapshot, Mapping):
                    self.apply_connection_snapshot(snapshot)
        except Exception as exc:
            try:
                self._logger.debug("ConnectionBadge refresh_from_app_state failed: %s", exc)
            except Exception:
                pass

    # ========================================================
    # Convenience setters
    # ========================================================

    def set_demo_mode(self, detail: str = "Using simulated measurements. Hardware connection is optional.") -> None:
        self._mode = MODE_DEMO
        self._last_error = ""
        self.set_role(self.ROLE_DEMO)
        self.set_headline("Demo Mode Active")
        self.set_detail_text(detail)
        self.set_state_chip_text("Demo Mode")
        self.set_mode_chip_text("Demo")
        self.set_port_chip_text("Optional")
        self.set_network_chip_text("Simulated")
        self._apply_footer_text()
        self._refresh_visibility()

    def set_online(
        self,
        *,
        label: str = "Hardware Connected",
        detail: str = "ESP32 is connected and sending data.",
        port: str = "",
        network_connected: bool = True,
    ) -> None:
        self._mode = MODE_HARDWARE
        self._selected_port = safe_str(port, "").strip()
        self._network_connected = bool(network_connected)
        self._last_error = ""
        self.set_role(self.ROLE_ONLINE)
        self.set_headline(label)
        self.set_detail_text(detail)
        self.set_state_chip_text("Connected")
        self.set_mode_chip_text("Hardware")
        self.set_port_chip_text(self._selected_port or "Connected")
        self.set_network_chip_text("Network Online" if self._network_connected else "Network Offline")
        self._apply_footer_text()
        self._refresh_visibility()

    def set_waiting(
        self,
        *,
        label: str = "Hardware Waiting",
        detail: str = "Waiting for serial / ESP32 connection.",
        port_hint: str = "",
    ) -> None:
        self._mode = MODE_HARDWARE
        self._selected_port = safe_str(port_hint, "").strip()
        self._last_error = ""
        self.set_role(self.ROLE_WAITING)
        self.set_headline(label)
        self.set_detail_text(detail)
        self.set_state_chip_text("Waiting")
        self.set_mode_chip_text("Hardware")
        self.set_port_chip_text(self._selected_port or "No Port")
        self.set_network_chip_text("Waiting")
        self._apply_footer_text()
        self._refresh_visibility()

    def set_offline(
        self,
        *,
        label: str = "Disconnected",
        detail: str = "No hardware connection detected.",
    ) -> None:
        self._mode = MODE_HARDWARE
        self._last_error = ""
        self.set_role(self.ROLE_OFFLINE)
        self.set_headline(label)
        self.set_detail_text(detail)
        self.set_state_chip_text("Offline")
        self.set_mode_chip_text("Hardware")
        self.set_port_chip_text("No Port")
        self.set_network_chip_text("Offline")
        self._apply_footer_text()
        self._refresh_visibility()

    # ========================================================
    # Misc controls
    # ========================================================

    def set_show_meta_row(self, visible: bool) -> None:
        self._show_meta_row = bool(visible)
        self._refresh_visibility()

    def set_show_action_button(self, visible: bool) -> None:
        self._show_action_button = bool(visible)
        self._refresh_visibility()

    def set_card_click_enabled(self, enabled: bool) -> None:
        self.set_clickable(bool(enabled))

    # ========================================================
    # Clicks
    # ========================================================

    def _on_card_clicked(self) -> None:
        self.clicked_badge.emit()

    # ========================================================
    # Diagnostics
    # ========================================================

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "role": self._role,
            "headline": self._headline,
            "detail": self._detail,
            "mode": self._mode,
            "network_connected": self._network_connected,
            "serial_connected": self._serial_connected,
            "esp32_connected": self._esp32_connected,
            "selected_port": self._selected_port,
            "available_ports_count": self._available_ports_count,
            "last_error": self._last_error,
            "show_meta_row": self._show_meta_row,
            "show_action_button": self._show_action_button,
            "compact": self._compact,
            "base_footer": self._base_footer,
            "card_title": self._card_title,
            "card_subtitle": self._card_subtitle,
        }