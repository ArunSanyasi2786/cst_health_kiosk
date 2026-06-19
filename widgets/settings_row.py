"""
widgets/settings_row.py

Premium settings row widget for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the reusable configuration-row building block for the Settings screen
- It is designed for rows such as:
    - brightness
    - timeout
    - theme mode (light / dark)
    - volume
    - network status
    - admin lock
    - serial port selection
    - save / reset / update actions
- It keeps the visual language consistent with the rest of the kiosk UI by
  matching the premium blue/cyan medical dashboard style used in:
    - widgets/glass_card.py
    - widgets/animated_button.py
    - widgets/glow_label.py
- It supports multiple right-side control patterns in one reusable widget:
    - value display
    - toggle switch
    - single action button
    - dual buttons
    - numeric stepper
    - choice selector
- It is intentionally low-coupling so SettingsScreen can use it even when other
  services are not fully wired yet

Typical use cases:
1) Toggle row
   "Auto-connect hardware" [ON/OFF]

2) Numeric step row
   "Brightness" [-] 80% [+]

3) Choice row
   "Appearance" [<] Dark [>]

4) Action row
   "Backup Data" [Create Backup]

5) Dual action row
   "Storage" [Export] [Clear]

Design goals:
- polished futuristic medical look
- easy to wire to service settings
- compact enough for Raspberry Pi 1024x600 kiosk layout
- safe defaults when some data is not yet available
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from PyQt6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.logger import get_logger

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

from widgets.animated_button import AnimatedButton

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
class SettingsRowTheme:
    """
    Theme container for SettingsRow.
    """
    shell_top: str = "rgba(15, 35, 64, 0.86)"
    shell_bottom: str = "rgba(10, 25, 48, 0.90)"
    hover_top: str = "rgba(22, 47, 82, 0.90)"
    hover_bottom: str = "rgba(12, 30, 56, 0.94)"
    border: str = "rgba(145, 214, 255, 0.22)"
    border_hover: str = "rgba(169, 227, 255, 0.42)"
    inner_gloss: str = "rgba(255, 255, 255, 0.05)"

    title_color: str = "#F3FBFF"
    subtitle_color: str = "rgba(213, 235, 248, 0.84)"
    note_color: str = "rgba(186, 212, 232, 0.82)"
    value_color: str = "#F8FDFF"
    value_subtle: str = "rgba(203, 225, 242, 0.84)"

    chip_text: str = "#F2FBFF"
    chip_bg_alpha: float = 0.16
    chip_border_alpha: float = 0.35

    neutral_accent: str = "#79CFFF"
    primary_accent: str = "#39D8FF"
    success_accent: str = "#3EE18F"
    warning_accent: str = "#FFD05E"
    danger_accent: str = "#FF6E87"

    shadow_hex: str = "#34D5FF"


DEFAULT_SETTINGS_ROW_THEME = SettingsRowTheme()


# ============================================================
# Internal helper widgets
# ============================================================

class _ToggleSwitch(QCheckBox):
    """
    Small custom-styled toggle switch based on QCheckBox.
    """

    toggled_value = pyqtSignal(bool)

    def __init__(self, parent: Optional[QWidget] = None, *, compact: bool = False, accent: str = "#39D8FF") -> None:
        super().__init__(parent)
        self._compact = bool(compact)
        self._accent = accent
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setText("")
        self.setTristate(False)
        self.stateChanged.connect(lambda _: self.toggled_value.emit(self.isChecked()))
        self._apply_style()

    def _apply_style(self) -> None:
        w = 46 if not self._compact else 38
        h = 24 if not self._compact else 20
        knob = 18 if not self._compact else 14
        radius = h // 2
        travel = w - knob - 4

        accent = QColor(self._accent)
        on_bg = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.82)"
        off_bg = "rgba(86, 110, 140, 0.42)"

        self.setFixedSize(w, h)
        self.setStyleSheet(
            f"""
            QCheckBox {{
                background: transparent;
                spacing: 0px;
            }}

            QCheckBox::indicator {{
                width: {w}px;
                height: {h}px;
                border-radius: {radius}px;
                border: 1px solid rgba(182, 225, 255, 0.30);
                background: {off_bg};
            }}

            QCheckBox::indicator:checked {{
                background: {on_bg};
                border: 1px solid rgba(220, 244, 255, 0.52);
            }}
            """
        )
        self._knob_size = knob
        self._travel = travel

    def set_accent(self, accent: str) -> None:
        self._accent = accent
        self._apply_style()
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            knob = self._knob_size
            x = 2 + (self._travel if self.isChecked() else 0)
            y = (self.height() - knob) / 2

            glow_color = QColor(self._accent if self.isChecked() else "#F8FDFF")
            glow_color.setAlpha(70 if self.isChecked() else 36)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow_color)
            painter.drawEllipse(int(x), int(y), knob, knob)

            inner = QColor("#FFFFFF")
            inner.setAlpha(250 if self.isChecked() else 220)
            painter.setBrush(inner)
            painter.drawEllipse(int(x + 1), int(y + 1), knob - 2, knob - 2)
        finally:
            painter.end()


# ============================================================
# Main widget
# ============================================================

class SettingsRow(QFrame):
    """
    Premium reusable settings row.

    Supported control modes:
    - MODE_VALUE: right-side value chip only
    - MODE_TOGGLE: switch control
    - MODE_BUTTON: primary action button
    - MODE_DUAL_BUTTON: two action buttons
    - MODE_STEPPER: minus/value/plus stepper
    - MODE_CHOICE: previous/current/next selector

    Typical behavior:
    - The whole row can be clickable for navigation
    - The right-side control can also be independently interactive
    - Row emits signals for parent screens/services to act upon
    """

    clicked = pyqtSignal()
    value_changed = pyqtSignal(object)
    toggled = pyqtSignal(bool)
    action_clicked = pyqtSignal()
    secondary_action_clicked = pyqtSignal()
    increment_clicked = pyqtSignal()
    decrement_clicked = pyqtSignal()
    option_changed = pyqtSignal(str)

    MODE_VALUE = "value"
    MODE_TOGGLE = "toggle"
    MODE_BUTTON = "button"
    MODE_DUAL_BUTTON = "dual_button"
    MODE_STEPPER = "stepper"
    MODE_CHOICE = "choice"

    STATE_NEUTRAL = "neutral"
    STATE_PRIMARY = "primary"
    STATE_SUCCESS = "success"
    STATE_WARNING = "warning"
    STATE_DANGER = "danger"

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        title: str = "",
        subtitle: str = "",
        note_text: str = "",
        icon_path: str = "",
        mode: str = MODE_VALUE,
        value: Any = None,
        value_text: str = "",
        unit: str = "",
        badge_text: str = "",
        primary_button_text: str = "Change",
        secondary_button_text: str = "",
        choices: Optional[Iterable[str]] = None,
        current_choice: str = "",
        state: str = STATE_NEUTRAL,
        compact: bool = False,
        clickable: bool = False,
        theme: Optional[SettingsRowTheme] = None,
        minimum_height: int = 84,
    ) -> None:
        super().__init__(parent)

        self._logger = logger.bind(component="SettingsRow")
        self._theme = theme or DEFAULT_SETTINGS_ROW_THEME
        self._compact = bool(compact)
        self._clickable = bool(clickable)
        self._hovered = False
        self._pressed = False
        self._base_pos: Optional[QPoint] = None

        self._mode = safe_str(mode, self.MODE_VALUE).strip().lower() or self.MODE_VALUE
        self._state = safe_str(state, self.STATE_NEUTRAL).strip().lower() or self.STATE_NEUTRAL

        self._title = safe_str(title, "").strip()
        self._subtitle = safe_str(subtitle, "").strip()
        self._note_text = safe_str(note_text, "").strip()
        self._icon_path = safe_str(icon_path, "").strip()

        self._raw_value: Any = value
        self._value_text = safe_str(value_text, "").strip()
        self._unit = safe_str(unit, "").strip()
        self._badge_text = safe_str(badge_text, "").strip()

        self._primary_button_text = safe_str(primary_button_text, "Change").strip() or "Change"
        self._secondary_button_text = safe_str(secondary_button_text, "").strip()

        self._step_min = 0.0
        self._step_max = 100.0
        self._step_step = 1.0
        self._step_decimals = 0

        self._choices: List[str] = [safe_str(item, "").strip() for item in (choices or []) if safe_str(item, "").strip()]
        self._current_choice_index = 0

        self._shadow_effect: Optional[QGraphicsDropShadowEffect] = None
        self._hover_anim: Optional[QPropertyAnimation] = None

        self._build_ui()
        self._apply_shadow()
        self._apply_style()

        self.setMinimumHeight(max(64, int(minimum_height if not compact else minimum_height - 12)))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.set_title(self._title)
        self.set_subtitle(self._subtitle)
        self.set_note_text(self._note_text)
        self.set_icon(self._icon_path)
        self.set_state(self._state)
        self.set_mode(self._mode)

        self.set_primary_button_text(self._primary_button_text)
        self.set_secondary_button_text(self._secondary_button_text)

        if self._choices:
            self.set_choices(self._choices, current_choice=current_choice or self._choices[0])
        else:
            self.set_choice("")

        if value is not None:
            self.set_value(value, emit_signal=False)
        else:
            self.set_value_text(self._value_text or "--")

        if self._badge_text:
            self.set_badge_text(self._badge_text)

        self._refresh_visibility()

    # ========================================================
    # UI
    # ========================================================

    def _build_ui(self) -> None:
        self.setObjectName("SettingsRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor if self._clickable else Qt.CursorShape.ArrowCursor)

        root = QHBoxLayout(self)
        root.setContentsMargins(
            12 if not self._compact else 9,
            10 if not self._compact else 8,
            12 if not self._compact else 9,
            10 if not self._compact else 8,
        )
        root.setSpacing(12 if not self._compact else 8)

        # ----------------------------------------------------
        # Left: icon
        # ----------------------------------------------------
        self._icon_wrap = QFrame(self)
        self._icon_wrap.setObjectName("SettingsRowIconWrap")
        self._icon_wrap.setFixedSize(48 if not self._compact else 40, 48 if not self._compact else 40)

        icon_layout = QVBoxLayout(self._icon_wrap)
        icon_layout.setContentsMargins(6, 6, 6, 6)
        icon_layout.setSpacing(0)

        self._icon_label = QLabel(self._icon_wrap)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_layout.addStretch(1)
        icon_layout.addWidget(self._icon_label, alignment=Qt.AlignmentFlag.AlignCenter)
        icon_layout.addStretch(1)

        # ----------------------------------------------------
        # Center: text stack
        # ----------------------------------------------------
        self._text_wrap = QWidget(self)
        text_layout = QVBoxLayout(self._text_wrap)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2 if not self._compact else 1)

        self._title_label = QLabel(self._text_wrap)
        self._title_label.setWordWrap(True)

        self._subtitle_label = QLabel(self._text_wrap)
        self._subtitle_label.setWordWrap(True)

        self._note_label = QLabel(self._text_wrap)
        self._note_label.setWordWrap(True)

        text_layout.addWidget(self._title_label)
        text_layout.addWidget(self._subtitle_label)
        text_layout.addWidget(self._note_label)

        # ----------------------------------------------------
        # Right: control stack
        # ----------------------------------------------------
        self._control_wrap = QWidget(self)
        self._control_wrap.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)

        control_layout = QVBoxLayout(self._control_wrap)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(4 if not self._compact else 3)

        # Value mode
        self._value_row = QWidget(self._control_wrap)
        value_layout = QHBoxLayout(self._value_row)
        value_layout.setContentsMargins(0, 0, 0, 0)
        value_layout.setSpacing(6 if not self._compact else 4)

        self._badge_label = QLabel(self._value_row)
        self._badge_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if _HAS_GLOW_LABEL:
            self._value_label = GlowLabel(
                role=GlowLabel.ROLE_STATUS if not self._compact else GlowLabel.ROLE_SUBTITLE,
                align_center=False,
                use_outline=False,
                enable_paint_glow=True,
                initial_glow_strength=0.34,
                initial_glow_blur=14 if not self._compact else 11,
            )
        else:
            self._value_label = QLabel(self._value_row)

        self._unit_label = QLabel(self._value_row)

        value_layout.addWidget(self._badge_label, 0, alignment=Qt.AlignmentFlag.AlignVCenter)
        value_layout.addWidget(self._value_label, 0, alignment=Qt.AlignmentFlag.AlignVCenter)
        value_layout.addWidget(self._unit_label, 0, alignment=Qt.AlignmentFlag.AlignBottom)
        value_layout.addStretch(1)

        # Toggle mode
        self._toggle_row = QWidget(self._control_wrap)
        toggle_layout = QHBoxLayout(self._toggle_row)
        toggle_layout.setContentsMargins(0, 0, 0, 0)
        toggle_layout.setSpacing(8 if not self._compact else 6)

        self._toggle_value_label = QLabel(self._toggle_row)
        self._toggle_switch = _ToggleSwitch(self._toggle_row, compact=self._compact, accent=self._accent_for_state(self._state))
        self._toggle_switch.toggled_value.connect(self._on_toggle_changed)

        toggle_layout.addWidget(self._toggle_value_label, 0, alignment=Qt.AlignmentFlag.AlignVCenter)
        toggle_layout.addWidget(self._toggle_switch, 0, alignment=Qt.AlignmentFlag.AlignVCenter)

        # Button mode
        self._button_row = QWidget(self._control_wrap)
        button_layout = QHBoxLayout(self._button_row)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(6 if not self._compact else 5)

        self._primary_button = AnimatedButton(
            text=self._primary_button_text,
            variant=AnimatedButton.VARIANT_SECONDARY,
            size=AnimatedButton.SIZE_MD if not self._compact else AnimatedButton.SIZE_SM,
            minimum_width=96 if not self._compact else 80,
        )
        self._primary_button.clicked.connect(self.action_clicked.emit)

        self._secondary_button = AnimatedButton(
            text=self._secondary_button_text or "More",
            variant=AnimatedButton.VARIANT_GHOST,
            size=AnimatedButton.SIZE_MD if not self._compact else AnimatedButton.SIZE_SM,
            minimum_width=86 if not self._compact else 72,
        )
        self._secondary_button.clicked.connect(self.secondary_action_clicked.emit)

        button_layout.addWidget(self._primary_button)
        button_layout.addWidget(self._secondary_button)

        # Stepper mode
        self._stepper_row = QWidget(self._control_wrap)
        stepper_layout = QHBoxLayout(self._stepper_row)
        stepper_layout.setContentsMargins(0, 0, 0, 0)
        stepper_layout.setSpacing(5 if not self._compact else 4)

        self._decrement_button = AnimatedButton(
            text="-",
            variant=AnimatedButton.VARIANT_GHOST,
            size=AnimatedButton.SIZE_SM,
            minimum_width=34 if not self._compact else 30,
        )
        self._decrement_button.clicked.connect(self._on_decrement_clicked)

        self._step_value_chip = QLabel(self._stepper_row)
        self._step_value_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._increment_button = AnimatedButton(
            text="+",
            variant=AnimatedButton.VARIANT_GHOST,
            size=AnimatedButton.SIZE_SM,
            minimum_width=34 if not self._compact else 30,
        )
        self._increment_button.clicked.connect(self._on_increment_clicked)

        stepper_layout.addWidget(self._decrement_button)
        stepper_layout.addWidget(self._step_value_chip)
        stepper_layout.addWidget(self._increment_button)

        # Choice mode
        self._choice_row = QWidget(self._control_wrap)
        choice_layout = QHBoxLayout(self._choice_row)
        choice_layout.setContentsMargins(0, 0, 0, 0)
        choice_layout.setSpacing(5 if not self._compact else 4)

        self._choice_prev_button = AnimatedButton(
            text="‹",
            variant=AnimatedButton.VARIANT_GHOST,
            size=AnimatedButton.SIZE_SM,
            minimum_width=34 if not self._compact else 30,
        )
        self._choice_prev_button.clicked.connect(self._select_previous_choice)

        self._choice_value_chip = QLabel(self._choice_row)
        self._choice_value_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._choice_next_button = AnimatedButton(
            text="›",
            variant=AnimatedButton.VARIANT_GHOST,
            size=AnimatedButton.SIZE_SM,
            minimum_width=34 if not self._compact else 30,
        )
        self._choice_next_button.clicked.connect(self._select_next_choice)

        choice_layout.addWidget(self._choice_prev_button)
        choice_layout.addWidget(self._choice_value_chip)
        choice_layout.addWidget(self._choice_next_button)

        control_layout.addWidget(self._value_row, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        control_layout.addWidget(self._toggle_row, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        control_layout.addWidget(self._button_row, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        control_layout.addWidget(self._stepper_row, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        control_layout.addWidget(self._choice_row, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        root.addWidget(self._icon_wrap, 0, alignment=Qt.AlignmentFlag.AlignTop)
        root.addWidget(self._text_wrap, 1, alignment=Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(self._control_wrap, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    # ========================================================
    # Style
    # ========================================================

    def _accent_for_state(self, state: str) -> str:
        state = safe_str(state, self.STATE_NEUTRAL).strip().lower()
        if state == self.STATE_PRIMARY:
            return self._theme.primary_accent
        if state == self.STATE_SUCCESS:
            return self._theme.success_accent
        if state == self.STATE_WARNING:
            return self._theme.warning_accent
        if state == self.STATE_DANGER:
            return self._theme.danger_accent
        return self._theme.neutral_accent

    def _chip_colors(self, state: str) -> tuple[str, str, str]:
        accent = QColor(self._accent_for_state(state))
        bg = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, {self._theme.chip_bg_alpha:.3f})"
        border = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, {self._theme.chip_border_alpha:.3f})"
        return bg, border, self._theme.chip_text

    def _apply_shadow(self) -> None:
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(22 if not self._compact else 18)
        shadow.setOffset(0, 5 if not self._compact else 4)

        color = QColor(self._theme.shadow_hex)
        color.setAlpha(55)
        shadow.setColor(color)

        self.setGraphicsEffect(shadow)
        self._shadow_effect = shadow

    def _apply_style(self) -> None:
        accent = self._accent_for_state(self._state)
        border = self._theme.border_hover if self._hovered else self._theme.border
        bg_top = self._theme.hover_top if self._hovered else self._theme.shell_top
        bg_bottom = self._theme.hover_bottom if self._hovered else self._theme.shell_bottom

        radius = 20 if not self._compact else 16
        icon_radius = self._icon_wrap.width() // 2
        icon_bg = self._rgba(accent, 0.12)
        icon_border = self._rgba(accent, 0.24)

        self.setStyleSheet(
            f"""
            QFrame#SettingsRow {{
                border: 1px solid {border};
                border-radius: {radius}px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 {bg_top},
                    stop:1 {bg_bottom}
                );
            }}

            QFrame#SettingsRowIconWrap {{
                border: 1px solid {icon_border};
                border-radius: {icon_radius}px;
                background: {icon_bg};
            }}
            """
        )

        self._title_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.title_color};
                font-size: {'14px' if not self._compact else ('11px' if self._ultra_compact else '12px')};
                font-weight: 700;
                background: transparent;
            }}
            """
        )
        self._subtitle_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.subtitle_color};
                font-size: {'10px' if not self._compact else '9px'};
                font-weight: 500;
                background: transparent;
            }}
            """
        )
        self._note_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.note_color};
                font-size: {'9px' if not self._compact else ('7px' if self._ultra_compact else '8px')};
                font-weight: 500;
                background: transparent;
            }}
            """
        )

        badge_bg, badge_border, badge_text = self._chip_colors(self._state)
        chip_style = f"""
        QLabel {{
            color: {badge_text};
            font-size: {'10px' if not self._compact else '9px'};
            font-weight: 700;
            border: 1px solid {badge_border};
            border-radius: {11 if not self._compact else (8 if self._ultra_compact else 9)}px;
            background: {badge_bg};
            padding: {3 if self._ultra_compact else (4 if not self._compact else 3)}px {5 if self._ultra_compact else (8 if not self._compact else 6)}px;
        }}
        """

        self._badge_label.setStyleSheet(chip_style)
        self._step_value_chip.setStyleSheet(chip_style)
        self._choice_value_chip.setStyleSheet(chip_style)

        value_size = 18 if not self._compact else 15
        unit_size = 10 if not self._compact else 9

        if _HAS_GLOW_LABEL and isinstance(self._value_label, GlowLabel):
            self._value_label.set_glow_color(accent)
            self._value_label.set_text_color(self._theme.value_color)
            self._value_label.set_role(GlowLabel.ROLE_STATUS if not self._compact else GlowLabel.ROLE_SUBTITLE)
        else:
            self._value_label.setStyleSheet(
                f"""
                QLabel {{
                    color: {self._theme.value_color};
                    font-size: {value_size}px;
                    font-weight: 800;
                    background: transparent;
                }}
                """
            )

        self._toggle_value_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.value_subtle};
                font-size: {'10px' if not self._compact else '9px'};
                font-weight: 700;
                background: transparent;
            }}
            """
        )

        self._unit_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.value_subtle};
                font-size: {unit_size}px;
                font-weight: 600;
                background: transparent;
                padding-bottom: 2px;
            }}
            """
        )

        self._toggle_switch.set_accent(accent)
        self._primary_button.set_accent_color(accent)

        if self._shadow_effect is not None:
            shadow_color = QColor(accent)
            shadow_color.setAlpha(70 if self._hovered else 52)
            self._shadow_effect.setColor(shadow_color)
            self._shadow_effect.setBlurRadius(26 if self._hovered else 22)

    def _rgba(self, color_hex: str, alpha: float) -> str:
        color = QColor(color_hex)
        alpha = max(0.0, min(float(alpha), 1.0))
        return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha:.3f})"

    # ========================================================
    # Visibility
    # ========================================================

    def _refresh_visibility(self) -> None:
        self._title_label.setVisible(bool(self._title))
        self._subtitle_label.setVisible(bool(self._subtitle))
        self._note_label.setVisible(bool(self._note_text))

        pixmap = self._icon_label.pixmap()
        has_icon = pixmap is not None and not pixmap.isNull()
        self._icon_wrap.setVisible(has_icon)

        self._value_row.setVisible(self._mode == self.MODE_VALUE)
        self._toggle_row.setVisible(self._mode == self.MODE_TOGGLE)
        self._button_row.setVisible(self._mode in {self.MODE_BUTTON, self.MODE_DUAL_BUTTON})
        self._stepper_row.setVisible(self._mode == self.MODE_STEPPER)
        self._choice_row.setVisible(self._mode == self.MODE_CHOICE)

        self._secondary_button.setVisible(
            self._mode == self.MODE_DUAL_BUTTON and bool(self._secondary_button_text)
        )

        self._badge_label.setVisible(bool(self._badge_text))
        self._unit_label.setVisible(bool(self._unit))
        self._toggle_value_label.setVisible(bool(self._toggle_value_label.text().strip()))

    # ========================================================
    # Text/icon setters
    # ========================================================

    def set_title(self, title: str) -> None:
        self._title = safe_str(title, "").strip()
        self._title_label.setText(self._title)
        self._refresh_visibility()

    def title(self) -> str:
        return self._title

    def set_subtitle(self, subtitle: str) -> None:
        self._subtitle = safe_str(subtitle, "").strip()
        self._subtitle_label.setText(self._subtitle)
        self._refresh_visibility()

    def subtitle(self) -> str:
        return self._subtitle

    def set_note_text(self, note_text: str) -> None:
        self._note_text = safe_str(note_text, "").strip()
        self._note_label.setText(self._note_text)
        self._refresh_visibility()

    def note_text(self) -> str:
        return self._note_text

    def set_icon(self, icon_path: str | Path) -> None:
        self._icon_path = safe_str(icon_path, "").strip()
        pixmap = QPixmap()

        if self._icon_path:
            path = Path(self._icon_path).expanduser()
            if path.exists() and path.is_file():
                pixmap = QPixmap(str(path))

        if pixmap.isNull():
            self._icon_label.clear()
            self._refresh_visibility()
            return

        target = 24 if not self._compact else 18
        scaled = pixmap.scaled(
            QSize(target, target),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._icon_label.setPixmap(scaled)
        self._refresh_visibility()

    # ========================================================
    # Mode/state setters
    # ========================================================

    def set_mode(self, mode: str) -> None:
        cleaned = safe_str(mode, self.MODE_VALUE).strip().lower()
        if cleaned not in {
            self.MODE_VALUE,
            self.MODE_TOGGLE,
            self.MODE_BUTTON,
            self.MODE_DUAL_BUTTON,
            self.MODE_STEPPER,
            self.MODE_CHOICE,
        }:
            cleaned = self.MODE_VALUE

        self._mode = cleaned
        self._refresh_visibility()

    def mode(self) -> str:
        return self._mode

    def set_state(self, state: str) -> None:
        cleaned = safe_str(state, self.STATE_NEUTRAL).strip().lower()
        if cleaned not in {
            self.STATE_NEUTRAL,
            self.STATE_PRIMARY,
            self.STATE_SUCCESS,
            self.STATE_WARNING,
            self.STATE_DANGER,
        }:
            cleaned = self.STATE_NEUTRAL

        self._state = cleaned
        self._apply_style()

    def state(self) -> str:
        return self._state

    # ========================================================
    # Value / badge setters
    # ========================================================

    def set_badge_text(self, badge_text: str) -> None:
        self._badge_text = safe_str(badge_text, "").strip()
        self._badge_label.setText(self._badge_text)
        self._refresh_visibility()

    def badge_text(self) -> str:
        return self._badge_text

    def _display_value_text(self) -> str:
        if self._value_text:
            return self._value_text

        if self._raw_value is None or self._raw_value == "":
            return "--"

        if self._mode == self.MODE_STEPPER:
            return self._format_step_value(self._raw_value)

        if isinstance(self._raw_value, bool):
            return "On" if self._raw_value else "Off"

        if isinstance(self._raw_value, float):
            if abs(self._raw_value - round(self._raw_value)) < 1e-9:
                return str(int(round(self._raw_value)))
            return f"{self._raw_value:.1f}"

        return safe_str(self._raw_value, "--")

    def set_value_text(self, value_text: str, *, emit_signal: bool = True) -> None:
        self._value_text = safe_str(value_text, "").strip()

        display = self._display_value_text()
        if _HAS_GLOW_LABEL and isinstance(self._value_label, GlowLabel):
            self._value_label.set_text(display)
        else:
            self._value_label.setText(display)

        self._step_value_chip.setText(display)
        self._toggle_value_label.setText(display if self._mode == self.MODE_TOGGLE else "")

        if emit_signal:
            self.value_changed.emit(self._raw_value)

    def set_value(self, value: Any, *, emit_signal: bool = True) -> None:
        self._raw_value = value
        self._value_text = ""

        display = self._display_value_text()
        if _HAS_GLOW_LABEL and isinstance(self._value_label, GlowLabel):
            self._value_label.set_text(display)
        else:
            self._value_label.setText(display)

        self._step_value_chip.setText(display)
        self._toggle_value_label.setText(display if self._mode == self.MODE_TOGGLE else "")

        if emit_signal:
            self.value_changed.emit(value)

    def value(self) -> Any:
        return self._raw_value

    def set_unit(self, unit: str) -> None:
        self._unit = safe_str(unit, "").strip()
        self._unit_label.setText(self._unit)
        self._refresh_visibility()

    def unit(self) -> str:
        return self._unit

    # ========================================================
    # Toggle helpers
    # ========================================================

    def _on_toggle_changed(self, checked: bool) -> None:
        self._raw_value = bool(checked)
        self._toggle_value_label.setText("On" if checked else "Off")
        self.toggled.emit(checked)
        self.value_changed.emit(checked)

    def set_checked(self, checked: bool, *, emit_signal: bool = False) -> None:
        previous = self._toggle_switch.blockSignals(not emit_signal)
        self._toggle_switch.setChecked(bool(checked))
        self._toggle_switch.blockSignals(previous)

        self._raw_value = bool(checked)
        self._toggle_value_label.setText("On" if checked else "Off")
        if emit_signal:
            self.toggled.emit(bool(checked))
            self.value_changed.emit(bool(checked))

    def is_checked(self) -> bool:
        return self._toggle_switch.isChecked()

    # ========================================================
    # Button setters
    # ========================================================

    def set_primary_button_text(self, text: str) -> None:
        self._primary_button_text = safe_str(text, "Change").strip() or "Change"
        self._primary_button.setText(self._primary_button_text)

    def set_secondary_button_text(self, text: str) -> None:
        self._secondary_button_text = safe_str(text, "").strip()
        self._secondary_button.setText(self._secondary_button_text or "More")
        self._refresh_visibility()

    # ========================================================
    # Stepper helpers
    # ========================================================

    def configure_stepper(
        self,
        *,
        minimum: float = 0.0,
        maximum: float = 100.0,
        step: float = 1.0,
        decimals: int = 0,
        unit: str = "",
    ) -> None:
        self._step_min = float(minimum)
        self._step_max = float(maximum)
        self._step_step = max(0.000001, float(step))
        self._step_decimals = max(0, int(decimals))
        if unit:
            self.set_unit(unit)

        if self._raw_value in (None, ""):
            self._raw_value = self._step_min
        else:
            self._raw_value = self._clamp_step_value(float(safe_float(self._raw_value, self._step_min)))

        self.set_value(self._raw_value, emit_signal=False)

    def _clamp_step_value(self, value: float) -> float:
        return max(self._step_min, min(self._step_max, value))

    def _format_step_value(self, value: Any) -> str:
        numeric = self._clamp_step_value(safe_float(value, self._step_min))
        if self._step_decimals <= 0:
            return str(int(round(numeric)))
        return f"{numeric:.{self._step_decimals}f}"

    def _on_increment_clicked(self) -> None:
        current = safe_float(self._raw_value, self._step_min)
        new_value = self._clamp_step_value(current + self._step_step)
        self.set_value(new_value, emit_signal=True)
        self.increment_clicked.emit()

    def _on_decrement_clicked(self) -> None:
        current = safe_float(self._raw_value, self._step_min)
        new_value = self._clamp_step_value(current - self._step_step)
        self.set_value(new_value, emit_signal=True)
        self.decrement_clicked.emit()

    # ========================================================
    # Choice helpers
    # ========================================================

    def set_choices(self, choices: Iterable[str], *, current_choice: str = "") -> None:
        self._choices = [safe_str(item, "").strip() for item in choices if safe_str(item, "").strip()]
        if not self._choices:
            self._current_choice_index = 0
            self._choice_value_chip.setText("--")
            return

        if current_choice and current_choice in self._choices:
            self._current_choice_index = self._choices.index(current_choice)
        else:
            self._current_choice_index = 0

        self._apply_current_choice()

    def set_choice(self, choice: str, *, emit_signal: bool = False) -> None:
        cleaned = safe_str(choice, "").strip()
        if cleaned and cleaned in self._choices:
            self._current_choice_index = self._choices.index(cleaned)
        elif cleaned and not self._choices:
            self._choices = [cleaned]
            self._current_choice_index = 0
        self._apply_current_choice(emit_signal=emit_signal)

    def current_choice(self) -> str:
        if not self._choices:
            return ""
        return self._choices[self._current_choice_index]

    def _apply_current_choice(self, *, emit_signal: bool = False) -> None:
        choice = self.current_choice() if self._choices else "--"
        self._choice_value_chip.setText(choice)
        self._raw_value = choice if choice != "--" else ""
        if emit_signal and choice and choice != "--":
            self.option_changed.emit(choice)
            self.value_changed.emit(choice)

    def _select_previous_choice(self) -> None:
        if not self._choices:
            return
        self._current_choice_index = (self._current_choice_index - 1) % len(self._choices)
        self._apply_current_choice(emit_signal=True)

    def _select_next_choice(self) -> None:
        if not self._choices:
            return
        self._current_choice_index = (self._current_choice_index + 1) % len(self._choices)
        self._apply_current_choice(emit_signal=True)

    # ========================================================
    # Composite payload helper
    # ========================================================

    def apply_setting_payload(self, payload: Dict[str, Any]) -> None:
        """
        Apply a flexible payload for easy SettingsScreen integration.

        Supported keys:
        {
            "title": "...",
            "subtitle": "...",
            "note_text": "...",
            "icon_path": "...",
            "mode": "toggle" | "value" | "button" | "dual_button" | "stepper" | "choice",
            "value": 80,
            "value_text": "80",
            "unit": "%",
            "badge_text": "Recommended",
            "primary_button_text": "Save",
            "secondary_button_text": "Reset",
            "choices": ["Light", "Dark"],
            "current_choice": "Dark",
            "checked": True,
            "state": "success",
        }
        """
        if "title" in payload:
            self.set_title(safe_str(payload.get("title"), ""))
        if "subtitle" in payload:
            self.set_subtitle(safe_str(payload.get("subtitle"), ""))
        if "note_text" in payload:
            self.set_note_text(safe_str(payload.get("note_text"), ""))
        if "icon_path" in payload:
            self.set_icon(safe_str(payload.get("icon_path"), ""))
        if "mode" in payload:
            self.set_mode(safe_str(payload.get("mode"), self.MODE_VALUE))
        if "state" in payload:
            self.set_state(safe_str(payload.get("state"), self.STATE_NEUTRAL))
        if "badge_text" in payload:
            self.set_badge_text(safe_str(payload.get("badge_text"), ""))
        if "unit" in payload:
            self.set_unit(safe_str(payload.get("unit"), ""))
        if "primary_button_text" in payload:
            self.set_primary_button_text(safe_str(payload.get("primary_button_text"), "Change"))
        if "secondary_button_text" in payload:
            self.set_secondary_button_text(safe_str(payload.get("secondary_button_text"), ""))
        if "choices" in payload:
            self.set_choices(payload.get("choices", []), current_choice=safe_str(payload.get("current_choice"), ""))
        elif "current_choice" in payload:
            self.set_choice(safe_str(payload.get("current_choice"), ""), emit_signal=False)
        if "checked" in payload:
            self.set_checked(bool(payload.get("checked")), emit_signal=False)
        if "value_text" in payload:
            self._raw_value = payload.get("value", self._raw_value)
            self.set_value_text(safe_str(payload.get("value_text"), ""), emit_signal=False)
        elif "value" in payload:
            self.set_value(payload.get("value"), emit_signal=False)

    # ========================================================
    # Interaction / hover
    # ========================================================

    def enterEvent(self, event: QEvent) -> None:
        super().enterEvent(event)
        self._hovered = True
        self._apply_style()
        self._animate_hover(True)

    def leaveEvent(self, event: QEvent) -> None:
        super().leaveEvent(event)
        self._hovered = False
        self._apply_style()
        self._animate_hover(False)

    def mousePressEvent(self, event: Optional[QMouseEvent]) -> None:
        super().mousePressEvent(event)
        if not self._clickable:
            return
        if event is not None and event.button() != Qt.MouseButton.LeftButton:
            return
        self._pressed = True

    def mouseReleaseEvent(self, event: Optional[QMouseEvent]) -> None:
        super().mouseReleaseEvent(event)
        if not self._clickable:
            return

        was_pressed = self._pressed
        self._pressed = False

        if (
            was_pressed
            and event is not None
            and event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self.clicked.emit()

    def _is_layout_managed(self) -> bool:
        parent = self.parentWidget()
        if parent is None:
            return False
        return parent.layout() is not None

    def _animate_hover(self, hovered: bool) -> None:
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
    # Enabled state
    # ========================================================

    def set_controls_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        self._toggle_switch.setEnabled(enabled)
        self._primary_button.setEnabled(enabled)
        self._secondary_button.setEnabled(enabled)
        self._increment_button.setEnabled(enabled)
        self._decrement_button.setEnabled(enabled)
        self._choice_prev_button.setEnabled(enabled)
        self._choice_next_button.setEnabled(enabled)

    # ========================================================
    # Paint
    # ========================================================

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            rect = QPainterPath()
            draw_rect = self.rect().adjusted(1, 1, -1, -1)
            if draw_rect.width() > 4 and draw_rect.height() > 4:
                radius = float(20 if not self._compact else 16)
                rect.addRoundedRect(QRectF(draw_rect), radius, radius)

                painter.save()
                painter.setClipPath(rect)
                gloss_rect = QRectF(
                    draw_rect.left() + 2.0,
                    draw_rect.top() + 2.0,
                    max(0.0, draw_rect.width() - 4.0),
                    max(0.0, draw_rect.height() * 0.42),
                )
                painter.fillRect(gloss_rect, QColor(255, 255, 255, 12 if not self._hovered else 18))
                painter.restore()
        finally:
            painter.end()

    # ========================================================
    # Diagnostics
    # ========================================================

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "title": self._title,
            "subtitle": self._subtitle,
            "note_text": self._note_text,
            "mode": self._mode,
            "state": self._state,
            "value": self._raw_value,
            "display_value": self._display_value_text(),
            "unit": self._unit,
            "badge_text": self._badge_text,
            "checked": self.is_checked() if self._mode == self.MODE_TOGGLE else None,
            "current_choice": self.current_choice() if self._mode == self.MODE_CHOICE else "",
            "choices": list(self._choices),
            "compact": self._compact,
            "clickable": self._clickable,
        }
