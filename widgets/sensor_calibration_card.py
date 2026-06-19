"""
widgets/sensor_calibration_card.py

Premium sensor calibration card widget for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the reusable calibration-focused widget used by the Calibration screen
- It provides a polished, self-contained card for each calibratable sensor
- It is designed for:
    - temperature sensor calibration
    - SpO2 / pulse sensor calibration
    - weight/load-cell calibration
    - height sensor calibration
    - future sensor-specific calibration panels
- It keeps the visual language consistent with:
    - widgets/glass_card.py
    - widgets/animated_button.py
    - widgets/glow_label.py
- It is intentionally low-coupling so the screen/service layer can drive it with
  simple payload dictionaries and signals

Main capabilities:
- large live-value display
- reference-value input
- sample-progress display
- stability / connection / state chips
- offset / scale / adjusted preview values
- instruction and note area
- capture / save / reset actions
- direct application of calibration payloads

Design goals:
- premium futuristic medical dashboard feel
- calibration-specific readability
- safe defaults when partial data is provided
- lightweight enough for Raspberry Pi kiosk deployment
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from PyQt6.QtCore import QEvent, QPropertyAnimation, QPoint, QEasingCurve, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QDoubleValidator, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
class SensorCalibrationCardTheme:
    """
    Theme container for SensorCalibrationCard.
    """
    title_color: str = "#F4FCFF"
    subtitle_color: str = "rgba(209, 232, 248, 0.82)"
    body_color: str = "rgba(225, 240, 251, 0.92)"
    note_color: str = "rgba(188, 213, 232, 0.82)"

    value_color: str = "#F8FDFF"
    unit_color: str = "rgba(203, 225, 240, 0.86)"
    field_text: str = "#F5FCFF"
    field_placeholder: str = "rgba(188, 210, 230, 0.55)"
    field_bg: str = "rgba(17, 37, 64, 0.58)"
    field_border: str = "rgba(145, 214, 255, 0.22)"
    field_focus_border: str = "rgba(179, 231, 255, 0.44)"

    strip_bg: str = "rgba(39, 66, 99, 0.16)"
    strip_border: str = "rgba(153, 216, 255, 0.18)"

    chip_text: str = "#F3FBFF"
    chip_bg_alpha: float = 0.16
    chip_border_alpha: float = 0.35

    primary_accent: str = "#39D8FF"
    success_accent: str = "#3FE28F"
    warning_accent: str = "#FFD15E"
    danger_accent: str = "#FF6E87"
    neutral_accent: str = "#7FD2FF"
    offline_accent: str = "#FF7B90"

    shadow_hex: str = "#35D6FF"


DEFAULT_SENSOR_CALIBRATION_CARD_THEME = SensorCalibrationCardTheme()


# ============================================================
# Main widget
# ============================================================

class SensorCalibrationCard(GlassCard):
    """
    Premium calibration card for one sensor.

    Supported workflow:
    - show current live value
    - accept/reference external known value
    - show progress/stability
    - display computed offset/scale/preview
    - allow capture/save/reset via explicit buttons
    """

    card_clicked = pyqtSignal(str)

    capture_requested = pyqtSignal(str)
    save_requested = pyqtSignal(str)
    reset_requested = pyqtSignal(str)
    apply_requested = pyqtSignal(str)
    use_live_requested = pyqtSignal(str)

    reference_submitted = pyqtSignal(str, float)
    reference_text_changed = pyqtSignal(str, str)

    state_changed = pyqtSignal(str, str)
    live_value_changed = pyqtSignal(str, object)
    payload_applied = pyqtSignal(dict)

    STATE_IDLE = "idle"
    STATE_WAITING = "waiting"
    STATE_COLLECTING = "collecting"
    STATE_STABLE = "stable"
    STATE_SUCCESS = "success"
    STATE_WARNING = "warning"
    STATE_ERROR = "error"
    STATE_OFFLINE = "offline"

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        sensor_key: str = "",
        title: str = "",
        subtitle: str = "",
        unit: str = "",
        icon_path: str = "",
        footer: str = "",
        state: str = STATE_IDLE,
        compact: bool = False,
        clickable: bool = True,
        show_reference_editor: bool = True,
        show_action_row: bool = True,
        show_result_row: bool = True,
        theme: Optional[SensorCalibrationCardTheme] = None,
        minimum_height: int = 214,
    ) -> None:
        self._logger = logger.bind(component="SensorCalibrationCard")

        self._theme = theme or DEFAULT_SENSOR_CALIBRATION_CARD_THEME
        self._base_minimum_height = int(minimum_height)
        self._compact = bool(compact or IS_COMPACT_KIOSK)
        self._ultra_compact = bool(KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480)
        self._sensor_key = safe_str(sensor_key, "").strip().lower()
        self._state = safe_str(state, self.STATE_IDLE).strip().lower() or self.STATE_IDLE

        self._unit = safe_str(unit, "").strip()
        self._live_value: Any = None
        self._reference_value: Optional[float] = None
        self._adjusted_preview_value: Any = None
        self._offset_value: Any = None
        self._scale_value: Any = None

        self._sample_count = 0
        self._target_samples = 0
        self._connected = False
        self._stable = False

        self._instruction_text = ""
        self._status_label = ""
        self._status_detail = ""
        self._last_updated_text = ""

        self._show_reference_editor = bool(show_reference_editor)
        self._show_action_row = bool(show_action_row)
        self._show_result_row = bool(show_result_row)

        self._pulse_alpha = 0.72
        self._pulse_direction = 1
        self._hovered = False
        self._base_pos: Optional[QPoint] = None
        self._hover_anim: Optional[QPropertyAnimation] = None

        resolved_title = safe_str(title, "").strip() or "Sensor Calibration"
        resolved_subtitle = safe_str(subtitle, "").strip() or "Calibration controls and live sensor status"

        super().__init__(
            title=resolved_title,
            subtitle=resolved_subtitle,
            body="",
            footer=footer,
            icon_path=icon_path,
            parent=parent,
            accent_color=self._accent_for_state(self._state),
            minimum_height=self._base_minimum_height if not self._compact else max(172 if self._ultra_compact else 184, self._base_minimum_height - (38 if self._ultra_compact else 24)),
            clickable=clickable,
            enable_hover_effect=True,
            show_accent_bar=True,
            compact=self._compact,
        )

        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(90)
        self._pulse_timer.timeout.connect(self._tick_pulse)

        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.setInterval(250)
        self._flash_timer.timeout.connect(self._restore_live_value_style)

        self._build_content()
        self.set_content_widget(self._content_root)

        self.clicked.connect(self._on_card_clicked)
        self._reference_input.editingFinished.connect(self._emit_reference_submitted)
        self._reference_input.textChanged.connect(self._on_reference_text_changed)

        self._capture_button.clicked.connect(lambda: self.capture_requested.emit(self._sensor_key))
        self._save_button.clicked.connect(lambda: self.save_requested.emit(self._sensor_key))
        self._reset_button.clicked.connect(lambda: self.reset_requested.emit(self._sensor_key))
        self._apply_button.clicked.connect(lambda: self.apply_requested.emit(self._sensor_key))
        self._use_live_button.clicked.connect(lambda: self.use_live_requested.emit(self._sensor_key))

        self._apply_style()
        self.set_sensor_key(self._sensor_key)
        self.set_unit(self._unit)
        self.set_state(self._state)
        self.set_live_value(None, flash=False)
        self.set_reference_value(None)
        self.set_adjusted_preview_value(None)
        self.set_offset_value(None)
        self.set_scale_value(None)
        self.set_sample_progress(0, 0)
        self.set_connected(False)
        self.set_stable(False)
        self.set_instruction_text("")
        self.set_status_text("")
        self.set_last_updated_text("")
        self._refresh_visibility()
        self._sync_compact_mode(force=True)

    # ========================================================
    # UI
    # ========================================================

    def _build_content(self) -> None:
        self._content_root = QWidget(self)
        self._content_root.setObjectName("SensorCalibrationCardContentRoot")

        root = QVBoxLayout(self._content_root)
        self._root_layout = root
        root.setContentsMargins(0, 3 if not self._compact else 1, 0, 0)
        root.setSpacing(8 if not self._compact else 6)

        # ----------------------------------------------------
        # Top meta row
        # ----------------------------------------------------
        self._top_row = QWidget(self._content_root)
        top_layout = QHBoxLayout(self._top_row)
        self._top_layout = top_layout
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(7 if not self._compact else 5)

        self._sensor_chip = QLabel(self._top_row)
        self._sensor_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._status_chip = QLabel(self._top_row)
        self._status_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._connection_chip = QLabel(self._top_row)
        self._connection_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)

        top_layout.addWidget(self._sensor_chip, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        top_layout.addWidget(self._status_chip, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        top_layout.addStretch(1)
        top_layout.addWidget(self._connection_chip, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # ----------------------------------------------------
        # Live value row
        # ----------------------------------------------------
        self._value_row = QWidget(self._content_root)
        value_layout = QHBoxLayout(self._value_row)
        self._value_layout = value_layout
        value_layout.setContentsMargins(0, 0, 0, 0)
        value_layout.setSpacing(8 if not self._compact else 6)

        self._state_dot = QLabel(self._value_row)
        self._state_dot.setFixedSize(12 if not self._compact else 10, 12 if not self._compact else 10)

        if _HAS_GLOW_LABEL:
            self._live_value_label = GlowLabel(
                role=GlowLabel.ROLE_TITLE if not self._compact else GlowLabel.ROLE_STATUS,
                align_center=False,
                use_outline=False,
                enable_paint_glow=True,
                initial_glow_strength=0.44,
                initial_glow_blur=18 if not self._compact else 14,
            )
        else:
            self._live_value_label = QLabel(self._value_row)

        self._live_unit_label = QLabel(self._value_row)

        self._sample_chip = QLabel(self._value_row)
        self._sample_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._stable_chip = QLabel(self._value_row)
        self._stable_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)

        value_layout.addWidget(self._state_dot, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        value_layout.addWidget(self._live_value_label, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        value_layout.addWidget(self._live_unit_label, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        value_layout.addStretch(1)
        value_layout.addWidget(self._sample_chip, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        value_layout.addWidget(self._stable_chip, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # ----------------------------------------------------
        # Reference row
        # ----------------------------------------------------
        self._reference_strip = QFrame(self._content_root)
        self._reference_strip.setObjectName("SensorCalibrationReferenceStrip")
        ref_layout = QHBoxLayout(self._reference_strip)
        self._ref_layout = ref_layout
        ref_layout.setContentsMargins(9 if not self._compact else 7, 7 if not self._compact else 5, 9 if not self._compact else 7, 7 if not self._compact else 5)
        ref_layout.setSpacing(7 if not self._compact else 5)

        self._reference_title = QLabel("Reference", self._reference_strip)

        self._reference_input = QLineEdit(self._reference_strip)
        self._reference_input.setPlaceholderText("Enter known reference value")
        self._reference_input.setClearButtonEnabled(True)
        self._reference_input.setMaximumWidth(140 if not self._compact else 118)
        validator = QDoubleValidator(self)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self._reference_input.setValidator(validator)

        self._reference_unit_label = QLabel(self._reference_strip)

        self._use_live_button = AnimatedButton(
            text="Use Live",
            variant=AnimatedButton.VARIANT_GHOST,
            size=AnimatedButton.SIZE_SM,
            minimum_width=74 if not self._compact else 66,
        )

        ref_layout.addWidget(self._reference_title, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        ref_layout.addWidget(self._reference_input, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        ref_layout.addWidget(self._reference_unit_label, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        ref_layout.addStretch(1)
        ref_layout.addWidget(self._use_live_button, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # ----------------------------------------------------
        # Result row
        # ----------------------------------------------------
        self._result_row = QWidget(self._content_root)
        result_layout = QHBoxLayout(self._result_row)
        self._result_layout = result_layout
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.setSpacing(7 if not self._compact else 5)

        self._offset_chip = QLabel(self._result_row)
        self._offset_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._scale_chip = QLabel(self._result_row)
        self._scale_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._adjusted_chip = QLabel(self._result_row)
        self._adjusted_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)

        result_layout.addWidget(self._offset_chip, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        result_layout.addWidget(self._scale_chip, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        result_layout.addWidget(self._adjusted_chip, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        result_layout.addStretch(1)

        # ----------------------------------------------------
        # Instruction / detail text
        # ----------------------------------------------------
        self._instruction_label = QLabel(self._content_root)
        self._instruction_label.setWordWrap(True)
        self._instruction_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        self._status_detail_label = QLabel(self._content_root)
        self._status_detail_label.setWordWrap(True)
        self._status_detail_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        self._last_updated_label = QLabel(self._content_root)
        self._last_updated_label.setWordWrap(False)
        self._last_updated_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # ----------------------------------------------------
        # Actions
        # ----------------------------------------------------
        self._action_row = QWidget(self._content_root)
        action_layout = QHBoxLayout(self._action_row)
        self._action_layout = action_layout
        action_layout.setContentsMargins(0, 2 if not self._compact else 0, 0, 0)
        action_layout.setSpacing(7 if not self._compact else 5)

        self._capture_button = AnimatedButton(
            text="Capture",
            variant=AnimatedButton.VARIANT_PRIMARY,
            size=AnimatedButton.SIZE_MD if not self._compact else AnimatedButton.SIZE_SM,
            minimum_width=92 if not self._compact else 78,
        )

        self._save_button = AnimatedButton(
            text="Save",
            variant=AnimatedButton.VARIANT_SUCCESS,
            size=AnimatedButton.SIZE_MD if not self._compact else AnimatedButton.SIZE_SM,
            minimum_width=80 if not self._compact else 70,
        )

        self._apply_button = AnimatedButton(
            text="Apply",
            variant=AnimatedButton.VARIANT_SECONDARY,
            size=AnimatedButton.SIZE_MD if not self._compact else AnimatedButton.SIZE_SM,
            minimum_width=80 if not self._compact else 68,
        )

        self._reset_button = AnimatedButton(
            text="Reset",
            variant=AnimatedButton.VARIANT_GHOST,
            size=AnimatedButton.SIZE_MD if not self._compact else AnimatedButton.SIZE_SM,
            minimum_width=82 if not self._compact else 70,
        )

        action_layout.addWidget(self._capture_button)
        action_layout.addWidget(self._save_button)
        action_layout.addWidget(self._apply_button)
        action_layout.addWidget(self._reset_button)
        action_layout.addStretch(1)

        root.addWidget(self._top_row)
        root.addWidget(self._value_row)
        root.addWidget(self._reference_strip)
        root.addWidget(self._result_row)
        root.addWidget(self._instruction_label)
        root.addWidget(self._status_detail_label)
        root.addWidget(self._last_updated_label)
        root.addWidget(self._action_row)

    # ========================================================
    # Styling
    # ========================================================

    def _accent_for_state(self, state: str) -> str:
        state = safe_str(state, self.STATE_IDLE).strip().lower()
        if state in {self.STATE_SUCCESS, self.STATE_STABLE}:
            return self._theme.success_accent
        if state in {self.STATE_WAITING, self.STATE_WARNING, self.STATE_COLLECTING}:
            return self._theme.warning_accent if state != self.STATE_COLLECTING else self._theme.primary_accent
        if state in {self.STATE_ERROR, self.STATE_OFFLINE}:
            return self._theme.danger_accent if state != self.STATE_OFFLINE else self._theme.offline_accent
        return self._theme.primary_accent

    def _chip_colors(self, accent_hex: str) -> tuple[str, str, str]:
        accent = QColor(accent_hex)
        bg = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, {self._theme.chip_bg_alpha:.3f})"
        border = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, {self._theme.chip_border_alpha:.3f})"
        return bg, border, self._theme.chip_text

    def _set_chip_style(self, label: QLabel, accent_hex: str, *, dense: bool = False) -> None:
        bg, border, text = self._chip_colors(accent_hex)
        label.setStyleSheet(
            f"""
            QLabel {{
                color: {text};
                font-size: {'8px' if self._ultra_compact or dense else ('9px' if self._compact else '10px')};
                font-weight: 700;
                border: 1px solid {border};
                border-radius: {8 if self._ultra_compact or dense else (10 if self._compact else 12)}px;
                background: {bg};
                padding: {2 if self._ultra_compact or dense else (3 if self._compact else 4)}px {5 if self._ultra_compact or dense else (6 if self._compact else 8)}px;
            }}
            """
        )

    def _apply_style(self) -> None:
        accent = self._accent_for_state(self._state)
        field_radius = 12 if not self._compact else (10 if not self._ultra_compact else 9)
        strip_radius = 14 if not self._compact else (12 if not self._ultra_compact else 10)

        self.set_accent_color(accent)

        self._title_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.title_color};
            }}
            """
        )
        self._subtitle_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.subtitle_color};
            }}
            """
        )

        if _HAS_GLOW_LABEL and isinstance(self._live_value_label, GlowLabel):
            self._live_value_label.set_glow_color(accent)
            self._live_value_label.set_text_color(self._theme.value_color)
            self._live_value_label.set_role(GlowLabel.ROLE_TITLE if not self._compact else GlowLabel.ROLE_STATUS)
        else:
            self._live_value_label.setStyleSheet(
                f"""
                QLabel {{
                    color: {self._theme.value_color};
                    font-size: {'28px' if not self._compact else ('22px' if not self._ultra_compact else '19px')};
                    font-weight: 800;
                    background: transparent;
                }}
                """
            )

        self._live_unit_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.unit_color};
                font-size: {'12px' if not self._compact else ('10px' if not self._ultra_compact else '9px')};
                font-weight: 600;
                background: transparent;
                padding-bottom: 3px;
            }}
            """
        )

        self._reference_strip.setStyleSheet(
            f"""
            QFrame#SensorCalibrationReferenceStrip {{
                border: 1px solid {self._theme.strip_border};
                border-radius: {strip_radius}px;
                background: {self._theme.strip_bg};
            }}
            """
        )

        self._reference_title.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.body_color};
                font-size: {'10px' if not self._compact else ('9px' if not self._ultra_compact else '8px')};
                font-weight: 700;
                background: transparent;
            }}
            """
        )

        self._reference_input.setStyleSheet(
            f"""
            QLineEdit {{
                color: {self._theme.field_text};
                background: {self._theme.field_bg};
                border: 1px solid {self._theme.field_border};
                border-radius: {field_radius}px;
                padding: {6 if not self._compact else 5}px {8 if not self._compact else 6}px;
                font-size: {'10px' if not self._compact else ('9px' if not self._ultra_compact else '8px')};
                font-weight: 600;
                selection-background-color: rgba(57, 216, 255, 0.34);
            }}

            QLineEdit:focus {{
                border: 1px solid {self._theme.field_focus_border};
            }}
            """
        )
        self._reference_input.setPlaceholderText(self._reference_input.placeholderText())
        self._reference_unit_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.value_subtle if hasattr(self._theme, 'value_subtle') else self._theme.note_color};
                font-size: {'10px' if not self._compact else ('9px' if not self._ultra_compact else '8px')};
                font-weight: 600;
                background: transparent;
            }}
            """
        )

        self._instruction_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.body_color};
                font-size: {'10px' if not self._compact else ('9px' if not self._ultra_compact else '8px')};
                font-weight: 500;
                background: transparent;
            }}
            """
        )
        self._status_detail_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.body_color};
                font-size: {'10px' if not self._compact else ('9px' if not self._ultra_compact else '8px')};
                font-weight: 500;
                background: transparent;
            }}
            """
        )
        self._last_updated_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.note_color};
                font-size: {'9px' if not self._compact else '8px'};
                font-weight: 500;
                background: transparent;
            }}
            """
        )

        self._set_chip_style(self._sensor_chip, self._theme.neutral_accent)
        self._set_chip_style(self._status_chip, accent)
        self._set_chip_style(self._connection_chip, self._theme.success_accent if self._connected else self._theme.offline_accent)
        self._set_chip_style(self._sample_chip, self._theme.primary_accent, dense=True)
        self._set_chip_style(self._stable_chip, self._theme.success_accent if self._stable else self._theme.warning_accent, dense=True)
        self._set_chip_style(self._offset_chip, self._theme.primary_accent, dense=True)
        self._set_chip_style(self._scale_chip, self._theme.primary_accent, dense=True)
        self._set_chip_style(self._adjusted_chip, accent, dense=True)

        dot_radius = self._state_dot.width() // 2
        dot_color = QColor(accent)
        self._state_dot.setStyleSheet(
            f"""
            QLabel {{
                min-width: {self._state_dot.width()}px;
                min-height: {self._state_dot.height()}px;
                max-width: {self._state_dot.width()}px;
                max-height: {self._state_dot.height()}px;
                border-radius: {dot_radius}px;
                background: rgba({dot_color.red()}, {dot_color.green()}, {dot_color.blue()}, {self._pulse_alpha:.3f});
                border: 1px solid rgba(255, 255, 255, 0.18);
            }}
            """
        )

        self._capture_button.set_accent_color(self._theme.primary_accent)
        self._save_button.set_accent_color(self._theme.success_accent)
        self._apply_button.set_accent_color(accent)

        self._refresh_pulse_state()

    # ========================================================
    # Helpers
    # ========================================================

    def _format_numeric(self, value: Any, *, decimals: int = 2, fallback: str = "--") -> str:
        if value is None or value == "":
            return fallback
        numeric = safe_float(value, 0.0)
        if abs(numeric - round(numeric)) < 1e-9 and decimals > 0:
            return f"{numeric:.{min(1, decimals)}f}" if decimals == 1 else f"{numeric:.{decimals}f}".rstrip("0").rstrip(".")
        return f"{numeric:.{decimals}f}" if decimals > 0 else str(int(round(numeric)))

    def _format_live_value(self, value: Any) -> str:
        if value is None or value == "":
            return "--"

        unit = self._unit.lower()
        if unit in {"%", "bpm", "mm", "cm", "kg"}:
            numeric = safe_float(value, 0.0)
            if abs(numeric - round(numeric)) < 1e-9:
                return str(int(round(numeric)))
            return f"{numeric:.1f}"

        return self._format_numeric(value, decimals=2)

    def _display_on_label(self, label: QLabel, text: str) -> None:
        if _HAS_GLOW_LABEL and isinstance(label, GlowLabel):
            label.set_text(text)
        else:
            label.setText(text)

    def _refresh_visibility(self) -> None:
        narrow = self.width() <= 720 if self.width() > 0 else bool(self._compact)
        short = self.height() <= 230 if self.height() > 0 else bool(self._ultra_compact)

        self._reference_strip.setVisible(self._show_reference_editor)
        self._result_row.setVisible(self._show_result_row and not (self._ultra_compact and narrow))
        self._action_row.setVisible(self._show_action_row)

        self._instruction_label.setVisible(bool(self._instruction_text.strip()) and not (self._ultra_compact and short))
        self._status_detail_label.setVisible(bool(self._status_detail.strip()) and not (self._ultra_compact and short))
        self._last_updated_label.setVisible(bool(self._last_updated_text.strip()) and not (self._compact and short))

        self._sensor_chip.setVisible(bool(self._sensor_chip.text().strip()))
        self._status_chip.setVisible(bool(self._status_chip.text().strip()))
        self._connection_chip.setVisible(not (self._ultra_compact and narrow))
        self._reference_unit_label.setVisible(bool(self._unit.strip()))
        self._live_unit_label.setVisible(bool(self._unit.strip()))

    def set_compact(self, compact: bool) -> None:
        self._compact = bool(compact)
        self._ultra_compact = bool(self._compact and (self.width() <= 760 or self.height() <= 220 or KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480))
        self._sync_compact_mode(force=True)

    def compact(self) -> bool:
        return bool(self._compact)

    def _sync_compact_mode(self, *, force: bool = False) -> None:
        width = self.width() if self.width() > 0 else KIOSK_WIDTH
        height = self.height() if self.height() > 0 else max(220, self.minimumHeight())
        compact_now = bool(IS_COMPACT_KIOSK or width <= 860 or height <= 260 or self._compact)
        ultra_now = bool(width <= 760 or height <= 220 or (KIOSK_WIDTH <= 800 and KIOSK_HEIGHT <= 480))

        changed = (compact_now != self._compact) or (ultra_now != self._ultra_compact)
        self._compact = compact_now
        self._ultra_compact = ultra_now

        try:
            self.setMinimumHeight(self._base_minimum_height if not self._compact else max(168 if self._ultra_compact else 184, self._base_minimum_height - (42 if self._ultra_compact else 24)))
        except Exception:
            pass

        try:
            self._root_layout.setContentsMargins(0, 2 if not self._compact else (1 if not self._ultra_compact else 0), 0, 0)
            self._root_layout.setSpacing(8 if not self._compact else (6 if not self._ultra_compact else 4))
            self._top_layout.setSpacing(7 if not self._compact else (5 if not self._ultra_compact else 4))
            self._value_layout.setSpacing(8 if not self._compact else (6 if not self._ultra_compact else 4))
            self._ref_layout.setContentsMargins(9 if not self._compact else (7 if not self._ultra_compact else 6), 7 if not self._compact else (5 if not self._ultra_compact else 4), 9 if not self._compact else (7 if not self._ultra_compact else 6), 7 if not self._compact else (5 if not self._ultra_compact else 4))
            self._ref_layout.setSpacing(7 if not self._compact else (5 if not self._ultra_compact else 4))
            self._result_layout.setSpacing(7 if not self._compact else (5 if not self._ultra_compact else 4))
            self._action_layout.setContentsMargins(0, 2 if not self._compact else 0, 0, 0)
            self._action_layout.setSpacing(7 if not self._compact else (5 if not self._ultra_compact else 4))
        except Exception:
            pass

        try:
            dot = 12 if not self._compact else (10 if not self._ultra_compact else 9)
            self._state_dot.setFixedSize(dot, dot)
            self._reference_input.setMaximumWidth(140 if not self._compact else (118 if not self._ultra_compact else 96))
            self._use_live_button.setMinimumWidth(74 if not self._compact else (66 if not self._ultra_compact else 56))
            self._capture_button.setMinimumWidth(92 if not self._compact else (78 if not self._ultra_compact else 64))
            self._save_button.setMinimumWidth(80 if not self._compact else (70 if not self._ultra_compact else 60))
            self._apply_button.setMinimumWidth(80 if not self._compact else (68 if not self._ultra_compact else 58))
            self._reset_button.setMinimumWidth(82 if not self._compact else (70 if not self._ultra_compact else 60))
        except Exception:
            pass

        if self._ultra_compact:
            self._use_live_button.setText("Live")
            self._capture_button.setText("Cap")
            self._last_updated_label.setMaximumHeight(14)
        else:
            self._use_live_button.setText("Use Live")
            self._capture_button.setText("Capture")
            self._last_updated_label.setMaximumHeight(16777215)

        self._apply_style()
        self._refresh_visibility()
        if force or changed:
            self.updateGeometry()
            self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_compact_mode()

    def _refresh_pulse_state(self) -> None:
        should_pulse = self._state in {self.STATE_COLLECTING, self.STATE_WAITING, self.STATE_STABLE}
        if should_pulse:
            if not self._pulse_timer.isActive():
                self._pulse_timer.start()
        else:
            self._pulse_timer.stop()
            self._pulse_alpha = 0.82 if self._state == self.STATE_SUCCESS else 0.70
            self._apply_style()

    def _tick_pulse(self) -> None:
        if self._pulse_direction > 0:
            self._pulse_alpha += 0.07
            if self._pulse_alpha >= 1.0:
                self._pulse_alpha = 1.0
                self._pulse_direction = -1
        else:
            self._pulse_alpha -= 0.07
            floor = 0.40 if self._state == self.STATE_WAITING else 0.52
            if self._pulse_alpha <= floor:
                self._pulse_alpha = floor
                self._pulse_direction = 1

        self._apply_style()

    def _flash_live_value(self) -> None:
        accent = self._accent_for_state(self._state)

        if _HAS_GLOW_LABEL and isinstance(self._live_value_label, GlowLabel):
            try:
                self._live_value_label.flash_once(duration_ms=650, peak_strength=1.0, end_strength=0.46)
            except Exception:
                pass
        else:
            self._live_value_label.setStyleSheet(
                f"""
                QLabel {{
                    color: {accent};
                    font-size: {'28px' if not self._compact else ('22px' if not self._ultra_compact else '19px')};
                    font-weight: 900;
                    background: transparent;
                }}
                """
            )

        self._flash_timer.start()

    def _restore_live_value_style(self) -> None:
        self._apply_style()

    # ========================================================
    # Public setters
    # ========================================================

    def set_sensor_key(self, sensor_key: str) -> None:
        self._sensor_key = safe_str(sensor_key, "").strip().lower()
        chip_text = self._sensor_key.replace("_", " ").title() if self._sensor_key else "Sensor"
        self._sensor_chip.setText(chip_text)
        self._refresh_visibility()

    def sensor_key(self) -> str:
        return self._sensor_key

    def set_state(self, state: str, *, label: str = "", detail: str = "") -> None:
        normalized = safe_str(state, self.STATE_IDLE).strip().lower() or self.STATE_IDLE
        if normalized not in {
            self.STATE_IDLE,
            self.STATE_WAITING,
            self.STATE_COLLECTING,
            self.STATE_STABLE,
            self.STATE_SUCCESS,
            self.STATE_WARNING,
            self.STATE_ERROR,
            self.STATE_OFFLINE,
        }:
            normalized = self.STATE_IDLE

        self._state = normalized
        default_label = {
            self.STATE_IDLE: "Idle",
            self.STATE_WAITING: "Waiting",
            self.STATE_COLLECTING: "Collecting",
            self.STATE_STABLE: "Stable",
            self.STATE_SUCCESS: "Saved",
            self.STATE_WARNING: "Review",
            self.STATE_ERROR: "Error",
            self.STATE_OFFLINE: "Offline",
        }.get(normalized, "Idle")

        self._status_label = safe_str(label, default_label).strip() or default_label
        if detail:
            self._status_detail = safe_str(detail, "").strip()

        self._status_chip.setText(self._status_label)
        self._apply_style()
        self._refresh_visibility()
        self.state_changed.emit(self._sensor_key, self._state)

    def state(self) -> str:
        return self._state

    def set_status_text(self, label: str, *, detail: str = "") -> None:
        self._status_label = safe_str(label, "").strip()
        self._status_detail = safe_str(detail, "").strip()
        self._status_chip.setText(self._status_label or "Status")
        self._status_detail_label.setText(self._status_detail)
        self._refresh_visibility()

    def set_connected(self, connected: bool, *, detail: str = "") -> None:
        self._connected = bool(connected)
        self._connection_chip.setText("Connected" if self._connected else "Offline")
        if detail and not self._status_detail:
            self._status_detail = safe_str(detail, "").strip()
            self._status_detail_label.setText(self._status_detail)
        self._apply_style()
        self._refresh_visibility()

    def set_stable(self, stable: bool) -> None:
        self._stable = bool(stable)
        self._stable_chip.setText("Stable" if self._stable else "Unstable")
        self._apply_style()
        self._refresh_visibility()

    def set_live_value(self, value: Any, *, flash: bool = True) -> None:
        self._live_value = value
        display = self._format_live_value(value)
        self._display_on_label(self._live_value_label, display)
        self._live_unit_label.setText(self._unit)
        if flash and value not in (None, ""):
            self._flash_live_value()
        self.live_value_changed.emit(self._sensor_key, value)

    def live_value(self) -> Any:
        return self._live_value

    def set_unit(self, unit: str) -> None:
        self._unit = safe_str(unit, "").strip()
        self._live_unit_label.setText(self._unit)
        self._reference_unit_label.setText(self._unit)
        self._refresh_visibility()

    def unit(self) -> str:
        return self._unit

    def set_reference_value(self, value: Optional[float]) -> None:
        self._reference_value = None if value in (None, "") else safe_float(value, 0.0)
        text = "" if self._reference_value is None else self._format_numeric(self._reference_value, decimals=3)
        self._reference_input.setText(text)

    def reference_value(self) -> Optional[float]:
        text = self._reference_input.text().strip()
        if not text:
            return None
        return safe_float(text, 0.0)

    def set_reference_placeholder(self, text: str) -> None:
        self._reference_input.setPlaceholderText(safe_str(text, "Enter reference value"))

    def set_adjusted_preview_value(self, value: Any) -> None:
        self._adjusted_preview_value = value
        text = self._format_live_value(value)
        self._adjusted_chip.setText(f"Adjusted {text}")

    def set_offset_value(self, value: Any) -> None:
        self._offset_value = value
        text = self._format_numeric(value, decimals=4)
        self._offset_chip.setText(f"Offset {text}")

    def set_scale_value(self, value: Any) -> None:
        self._scale_value = value
        text = self._format_numeric(value, decimals=4)
        self._scale_chip.setText(f"Scale {text}")

    def set_sample_progress(self, current: int, target: int) -> None:
        self._sample_count = max(0, safe_int(current, 0))
        self._target_samples = max(0, safe_int(target, 0))
        if self._target_samples > 0:
            self._sample_chip.setText(f"{self._sample_count}/{self._target_samples} Samples")
        else:
            self._sample_chip.setText(f"{self._sample_count} Samples")

    def set_instruction_text(self, text: str) -> None:
        self._instruction_text = safe_str(text, "").strip()
        self._instruction_label.setText(self._instruction_text)
        self._refresh_visibility()

    def set_last_updated_text(self, text: str) -> None:
        self._last_updated_text = safe_str(text, "").strip()
        self._last_updated_label.setText(self._last_updated_text)
        self._refresh_visibility()

    def set_reference_editable(self, editable: bool) -> None:
        self._reference_input.setReadOnly(not bool(editable))
        self._reference_input.setEnabled(bool(editable))

    def set_actions_enabled(
        self,
        *,
        capture_enabled: bool = True,
        save_enabled: bool = True,
        apply_enabled: bool = True,
        reset_enabled: bool = True,
        use_live_enabled: bool = True,
    ) -> None:
        self._capture_button.setEnabled(bool(capture_enabled))
        self._save_button.setEnabled(bool(save_enabled))
        self._apply_button.setEnabled(bool(apply_enabled))
        self._reset_button.setEnabled(bool(reset_enabled))
        self._use_live_button.setEnabled(bool(use_live_enabled))

    def set_show_reference_editor(self, visible: bool) -> None:
        self._show_reference_editor = bool(visible)
        self._refresh_visibility()

    def set_show_action_row(self, visible: bool) -> None:
        self._show_action_row = bool(visible)
        self._refresh_visibility()

    def set_show_result_row(self, visible: bool) -> None:
        self._show_result_row = bool(visible)
        self._refresh_visibility()

    def set_primary_button_text(self, text: str) -> None:
        self._capture_button.setText(safe_str(text, "Capture").strip() or "Capture")

    # ========================================================
    # Payload integration
    # ========================================================

    def apply_calibration_payload(self, payload: Mapping[str, Any]) -> None:
        """
        Apply a flexible calibration payload.

        Supported keys include:
        {
            "sensor_key": "temperature",
            "title": "Temperature Sensor",
            "subtitle": "Body temperature calibration",
            "unit": "°C",
            "state": "collecting",
            "status_label": "Collecting",
            "status_detail": "Place the reference sensor and wait for stable data.",
            "connected": True,
            "stable": False,
            "live_value": 36.8,
            "reference_value": 37.0,
            "adjusted_preview_value": 36.9,
            "offset": 0.12,
            "scale": 1.0000,
            "sample_count": 3,
            "target_samples": 5,
            "instruction_text": "Keep the sensor steady for 8 seconds.",
            "last_updated_text": "Updated just now",
            "capture_enabled": True,
            "save_enabled": False,
            "apply_enabled": False,
            "reset_enabled": True,
            "use_live_enabled": True,
        }
        """
        data = dict(payload or {})

        if "sensor_key" in data:
            self.set_sensor_key(safe_str(data.get("sensor_key"), ""))
        if "title" in data:
            self.set_title(safe_str(data.get("title"), ""))
        if "subtitle" in data:
            self.set_subtitle(safe_str(data.get("subtitle"), ""))
        if "unit" in data:
            self.set_unit(safe_str(data.get("unit"), ""))
        if "state" in data or "status_label" in data or "status_detail" in data:
            self.set_state(
                safe_str(data.get("state"), self._state),
                label=safe_str(data.get("status_label"), self._status_label),
                detail=safe_str(data.get("status_detail"), self._status_detail),
            )
        if "connected" in data:
            self.set_connected(bool(data.get("connected", False)), detail=safe_str(data.get("connection_detail"), ""))
        if "stable" in data:
            self.set_stable(bool(data.get("stable", False)))
        if "live_value" in data:
            self.set_live_value(data.get("live_value"), flash=False)
        if "reference_value" in data:
            self.set_reference_value(data.get("reference_value"))
        if "adjusted_preview_value" in data:
            self.set_adjusted_preview_value(data.get("adjusted_preview_value"))
        if "offset" in data:
            self.set_offset_value(data.get("offset"))
        if "scale" in data:
            self.set_scale_value(data.get("scale"))
        if "sample_count" in data or "target_samples" in data:
            self.set_sample_progress(
                safe_int(data.get("sample_count"), self._sample_count),
                safe_int(data.get("target_samples"), self._target_samples),
            )
        if "instruction_text" in data:
            self.set_instruction_text(safe_str(data.get("instruction_text"), ""))
        if "last_updated_text" in data:
            self.set_last_updated_text(safe_str(data.get("last_updated_text"), ""))

        self.set_actions_enabled(
            capture_enabled=bool(data.get("capture_enabled", True)),
            save_enabled=bool(data.get("save_enabled", True)),
            apply_enabled=bool(data.get("apply_enabled", True)),
            reset_enabled=bool(data.get("reset_enabled", True)),
            use_live_enabled=bool(data.get("use_live_enabled", True)),
        )

        if "show_reference_editor" in data:
            self.set_show_reference_editor(bool(data.get("show_reference_editor", True)))
        if "show_action_row" in data:
            self.set_show_action_row(bool(data.get("show_action_row", True)))
        if "show_result_row" in data:
            self.set_show_result_row(bool(data.get("show_result_row", True)))

        self.payload_applied.emit(dict(data))

    # ========================================================
    # Signals/helpers
    # ========================================================

    def _on_reference_text_changed(self, text: str) -> None:
        self.reference_text_changed.emit(self._sensor_key, safe_str(text, ""))

    def _emit_reference_submitted(self) -> None:
        value = self.reference_value()
        if value is None:
            return
        self.reference_submitted.emit(self._sensor_key, value)

    def _on_card_clicked(self) -> None:
        self.card_clicked.emit(self._sensor_key)

    # ========================================================
    # Hover / animation
    # ========================================================

    def enterEvent(self, event: QEvent) -> None:
        super().enterEvent(event)
        self._hovered = True

    def leaveEvent(self, event: QEvent) -> None:
        super().leaveEvent(event)
        self._hovered = False

    # ========================================================
    # Diagnostics
    # ========================================================

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "sensor_key": self._sensor_key,
            "state": self._state,
            "unit": self._unit,
            "live_value": self._live_value,
            "reference_value": self.reference_value(),
            "adjusted_preview_value": self._adjusted_preview_value,
            "offset_value": self._offset_value,
            "scale_value": self._scale_value,
            "sample_count": self._sample_count,
            "target_samples": self._target_samples,
            "connected": self._connected,
            "stable": self._stable,
            "instruction_text": self._instruction_text,
            "status_label": self._status_label,
            "status_detail": self._status_detail,
            "last_updated_text": self._last_updated_text,
            "compact": self._compact,
            "show_reference_editor": self._show_reference_editor,
            "show_action_row": self._show_action_row,
            "show_result_row": self._show_result_row,
        }