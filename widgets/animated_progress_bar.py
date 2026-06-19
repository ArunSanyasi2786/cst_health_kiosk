"""
widgets/animated_progress_bar.py

Premium animated progress bar widget for the CST Health Monitoring Station kiosk.

800x480 compact update:
- keeps the existing public API intact
- adds compact-aware sizing for small kiosk resolutions
- preserves glossy medical styling while reducing vertical footprint
- avoids crowding on measuring / storage screens for 800x480 displays
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt6.QtWidgets import (
    QFrame,
    QSizePolicy,
    QWidget,
)

from core.logger import get_logger

logger = get_logger(__name__)

try:
    from config import (
        KIOSK_WIDTH,
        KIOSK_HEIGHT,
        UI_SCALE,
        IS_COMPACT_KIOSK,
    )
except Exception:  # pragma: no cover
    KIOSK_WIDTH = 800
    KIOSK_HEIGHT = 480
    UI_SCALE = min(KIOSK_WIDTH / 1024.0, KIOSK_HEIGHT / 600.0)
    IS_COMPACT_KIOSK = KIOSK_WIDTH <= 820 or KIOSK_HEIGHT <= 500

try:
    from core.animation_manager import get_animation_manager
except Exception:  # pragma: no cover
    get_animation_manager = None  # type: ignore


# =============================================================================
# Theme container
# =============================================================================

@dataclass(frozen=True)
class AnimatedProgressBarTheme:
    track_top: str
    track_bottom: str
    track_border: str
    track_mid_glow: str
    fill_start: str
    fill_mid: str
    fill_end: str
    fill_edge: str
    glow_hex: str
    text_color: str
    secondary_text_color: str
    percentage_color: str
    shimmer_color: str
    danger_color: str
    success_color: str
    warning_color: str


def _primary_theme() -> AnimatedProgressBarTheme:
    return AnimatedProgressBarTheme(
        track_top="rgba(30, 86, 142, 0.98)",
        track_bottom="rgba(12, 42, 78, 0.99)",
        track_border="rgba(128, 228, 255, 0.78)",
        track_mid_glow="rgba(78, 210, 255, 0.18)",
        fill_start="rgba(36, 126, 255, 1.0)",
        fill_mid="rgba(62, 200, 255, 1.0)",
        fill_end="rgba(130, 238, 255, 1.0)",
        fill_edge="rgba(220, 250, 255, 0.28)",
        glow_hex="#38D8FF",
        text_color="#F8FDFF",
        secondary_text_color="rgba(228, 244, 252, 0.94)",
        percentage_color="#F7FDFF",
        shimmer_color="rgba(255, 255, 255, 0.82)",
        danger_color="#F25F74",
        success_color="#38D98D",
        warning_color="#FFC857",
    )


class AnimatedProgressBar(QFrame):
    value_changed = pyqtSignal(int)
    range_changed = pyqtSignal(int, int)
    progress_completed = pyqtSignal()
    indeterminate_started = pyqtSignal()
    indeterminate_stopped = pyqtSignal()
    status_text_changed = pyqtSignal(str)
    caption_changed = pyqtSignal(str)
    mode_changed = pyqtSignal(str)

    MODE_DETERMINATE = "determinate"
    MODE_INDETERMINATE = "indeterminate"

    STATE_PRIMARY = "primary"
    STATE_SUCCESS = "success"
    STATE_WARNING = "warning"
    STATE_DANGER = "danger"

    SIZE_SM = "sm"
    SIZE_MD = "md"
    SIZE_LG = "lg"

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        caption: str = "",
        status_text: str = "",
        minimum: int = 0,
        maximum: int = 100,
        value: int = 0,
        show_percentage: bool = True,
        show_status_inside_bar: bool = True,
        show_caption: bool = True,
        size: str = SIZE_MD,
        height: Optional[int] = None,
        corner_radius: Optional[int] = None,
        theme: Optional[AnimatedProgressBarTheme] = None,
        accent_color: str = "",
        enable_shimmer: bool = True,
        animate_changes: bool = True,
        compact: Optional[bool] = None,
    ) -> None:
        super().__init__(parent)

        self._logger = logger
        self._theme = theme or _primary_theme()
        self._state = self.STATE_PRIMARY
        self._size = str(size or self.SIZE_MD).strip().lower()

        if self._size not in {self.SIZE_SM, self.SIZE_MD, self.SIZE_LG}:
            self._size = self.SIZE_MD

        self._minimum = int(minimum)
        self._maximum = max(self._minimum + 1, int(maximum))
        self._value = max(self._minimum, min(int(value), self._maximum))
        self._display_value = float(self._value)

        self._caption = str(caption or "").strip()
        self._status_text = str(status_text or "").strip()

        self._show_percentage = bool(show_percentage)
        self._show_status_inside_bar = bool(show_status_inside_bar)
        self._show_caption = bool(show_caption)
        self._enable_shimmer = bool(enable_shimmer)
        self._animate_changes = bool(animate_changes)

        self._mode = self.MODE_DETERMINATE
        self._indeterminate_offset = 0.0
        self._pulse_glow_strength = 0.0
        self._glow_direction = 1
        self._shimmer_phase = 0.0

        self._custom_height = height
        self._custom_corner_radius = corner_radius
        self._graphics_effect_glow_enabled = False
        self._compact_override = compact

        self._value_anim: Optional[QPropertyAnimation] = None

        self._indeterminate_timer = QTimer(self)
        self._indeterminate_timer.setInterval(30 if self._is_compact_context() else 26)
        self._indeterminate_timer.timeout.connect(self._advance_indeterminate)

        self._shimmer_timer = QTimer(self)
        self._shimmer_timer.setInterval(42 if self._is_compact_context() else 34)
        self._shimmer_timer.timeout.connect(self._tick_shimmer)

        self._glow_timer = QTimer(self)
        self._glow_timer.setInterval(48 if self._is_compact_context() else 42)
        self._glow_timer.timeout.connect(self._tick_glow)

        self._animation_manager = None
        if get_animation_manager is not None:
            try:
                self._animation_manager = get_animation_manager()
            except Exception:
                self._animation_manager = None

        self.setObjectName("AnimatedProgressBar")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

        if accent_color:
            self.set_accent_color(accent_color)

        self._apply_height()
        self._start_background_effects()

    # -------------------------------------------------------------------------
    # Compact / sizing helpers
    # -------------------------------------------------------------------------

    def _is_compact_context(self) -> bool:
        if self._compact_override is not None:
            return bool(self._compact_override)

        width = 0
        try:
            width = int(self.width())
        except Exception:
            width = 0

        if width <= 0 and self.parentWidget() is not None:
            try:
                width = int(self.parentWidget().width())
            except Exception:
                width = 0

        if width > 0:
            return width <= 760

        return bool(IS_COMPACT_KIOSK)

    def set_compact(self, compact: bool) -> None:
        self._compact_override = bool(compact)
        self._indeterminate_timer.setInterval(30 if self._is_compact_context() else 26)
        self._shimmer_timer.setInterval(42 if self._is_compact_context() else 34)
        self._glow_timer.setInterval(48 if self._is_compact_context() else 42)
        self._apply_height()
        self.updateGeometry()
        self.update()

    def compact(self) -> bool:
        return self._is_compact_context()

    def _scaled(self, value: int) -> int:
        scale = UI_SCALE if self._is_compact_context() else 1.0
        return max(1, int(round(value * scale)))

    def _bar_height(self) -> int:
        if self._custom_height is not None:
            return max(20, int(self._custom_height))

        compact = self._is_compact_context()
        if self._size == self.SIZE_SM:
            return 34 if compact else 42
        if self._size == self.SIZE_LG:
            return 52 if compact else 68
        return 42 if compact else 54

    def _caption_space(self) -> int:
        if not (self._show_caption and self._caption):
            return 0
        return 14 if self._is_compact_context() else 20

    def _total_height(self) -> int:
        return self._bar_height() + self._caption_space()

    def _radius(self) -> int:
        if self._custom_corner_radius is not None:
            return max(8, int(self._custom_corner_radius))

        compact = self._is_compact_context()
        if self._size == self.SIZE_SM:
            return 12 if compact else 15
        if self._size == self.SIZE_LG:
            return 18 if compact else 22
        return 15 if compact else 18

    def _caption_font(self) -> QFont:
        compact = self._is_compact_context()
        font = QFont()
        if self._size == self.SIZE_SM:
            font.setPointSize(8 if compact else 9)
            font.setWeight(QFont.Weight.Medium)
        elif self._size == self.SIZE_LG:
            font.setPointSize(10 if compact else 12)
            font.setWeight(QFont.Weight.DemiBold)
        else:
            font.setPointSize(9 if compact else 10)
            font.setWeight(QFont.Weight.Medium)
        return font

    def _status_font(self) -> QFont:
        compact = self._is_compact_context()
        font = QFont()
        if self._size == self.SIZE_SM:
            font.setPointSize(8 if compact else 9)
            font.setWeight(QFont.Weight.Bold)
        elif self._size == self.SIZE_LG:
            font.setPointSize(10 if compact else 12)
            font.setWeight(QFont.Weight.Bold)
        else:
            font.setPointSize(9 if compact else 10)
            font.setWeight(QFont.Weight.Bold)
        return font

    def _percent_font(self) -> QFont:
        compact = self._is_compact_context()
        font = QFont()
        if self._size == self.SIZE_SM:
            font.setPointSize(8 if compact else 9)
            font.setWeight(QFont.Weight.Bold)
        elif self._size == self.SIZE_LG:
            font.setPointSize(11 if compact else 13)
            font.setWeight(QFont.Weight.Bold)
        else:
            font.setPointSize(9 if compact else 10)
            font.setWeight(QFont.Weight.Bold)
        return font

    def _apply_height(self) -> None:
        self.setMinimumHeight(self._total_height())
        self.setMaximumHeight(self._total_height())
        self.updateGeometry()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(260 if self._is_compact_context() else 320, self._total_height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(130 if self._is_compact_context() else 160, self._total_height())

    # -------------------------------------------------------------------------
    # Compatibility helpers
    # -------------------------------------------------------------------------

    def disable_graphics_effect_glow(self) -> None:
        self._graphics_effect_glow_enabled = False

    def enable_graphics_effect_glow(self) -> None:
        self._graphics_effect_glow_enabled = True

    # -------------------------------------------------------------------------
    # Background timers
    # -------------------------------------------------------------------------

    def _start_background_effects(self) -> None:
        if self._enable_shimmer:
            self._shimmer_timer.start()
        self._glow_timer.start()

    def _tick_shimmer(self) -> None:
        self._shimmer_phase += 0.025 if self._is_compact_context() else 0.03
        if self._shimmer_phase > 1.0:
            self._shimmer_phase = 0.0
        self.update()

    def _tick_glow(self) -> None:
        step = 0.030 if self._is_compact_context() else 0.040
        floor = 0.18 if self._is_compact_context() else 0.16

        if self._glow_direction > 0:
            self._pulse_glow_strength += step
            if self._pulse_glow_strength >= 1.0:
                self._pulse_glow_strength = 1.0
                self._glow_direction = -1
        else:
            self._pulse_glow_strength -= step
            if self._pulse_glow_strength <= floor:
                self._pulse_glow_strength = floor
                self._glow_direction = 1

        self.update()

    # -------------------------------------------------------------------------
    # Color helpers
    # -------------------------------------------------------------------------

    def _rgba(self, color_hex: str, alpha: float) -> str:
        c = QColor(color_hex)
        return f"rgba({c.red()}, {c.green()}, {c.blue()}, {max(0.0, min(alpha, 1.0)):.3f})"

    def _to_qcolor(self, value: str | QColor, fallback: str = "#000000") -> QColor:
        if isinstance(value, QColor):
            return QColor(value)

        text = str(value or "").strip()
        if not text:
            return QColor(fallback)

        if text.lower().startswith("rgba(") and text.endswith(")"):
            inner = text[text.find("(") + 1 : -1]
            parts = [p.strip() for p in inner.split(",")]
            if len(parts) == 4:
                try:
                    r = int(float(parts[0]))
                    g = int(float(parts[1]))
                    b = int(float(parts[2]))
                    a_raw = float(parts[3])
                    a = int(round(a_raw * 255.0)) if a_raw <= 1.0 else int(round(a_raw))
                    return QColor(max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)), max(0, min(255, a)))
                except Exception:
                    pass

        if text.lower().startswith("rgb(") and text.endswith(")"):
            inner = text[text.find("(") + 1 : -1]
            parts = [p.strip() for p in inner.split(",")]
            if len(parts) == 3:
                try:
                    r = int(float(parts[0]))
                    g = int(float(parts[1]))
                    b = int(float(parts[2]))
                    return QColor(max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))
                except Exception:
                    pass

        color = QColor(text)
        if color.isValid():
            return color
        return QColor(fallback)

    def _active_glow_hex(self) -> str:
        if self._state == self.STATE_SUCCESS:
            return self._theme.success_color
        if self._state == self.STATE_WARNING:
            return self._theme.warning_color
        if self._state == self.STATE_DANGER:
            return self._theme.danger_color
        return self._theme.glow_hex

    def _active_fill_colors(self) -> tuple[str, str, str]:
        if self._state == self.STATE_SUCCESS:
            return (
                self._rgba(self._theme.success_color, 1.0),
                self._rgba("#52F1A7", 1.0),
                self._rgba("#A2FFD4", 1.0),
            )
        if self._state == self.STATE_WARNING:
            return (
                self._rgba(self._theme.warning_color, 1.0),
                self._rgba("#FFD56E", 1.0),
                self._rgba("#FFF0B7", 1.0),
            )
        if self._state == self.STATE_DANGER:
            return (
                self._rgba(self._theme.danger_color, 1.0),
                self._rgba("#FF8798", 1.0),
                self._rgba("#FFD0D6", 1.0),
            )
        return (self._theme.fill_start, self._theme.fill_mid, self._theme.fill_end)

    # -------------------------------------------------------------------------
    # Theme / state
    # -------------------------------------------------------------------------

    def set_state(self, state: str) -> None:
        cleaned = str(state or self.STATE_PRIMARY).strip().lower()
        if cleaned not in {self.STATE_PRIMARY, self.STATE_SUCCESS, self.STATE_WARNING, self.STATE_DANGER}:
            cleaned = self.STATE_PRIMARY

        self._state = cleaned
        self.update()

        if self._animation_manager is not None:
            try:
                self._animation_manager.animate_glow_once(
                    self,
                    duration_ms=220 if self._is_compact_context() else 260,
                    color=self._to_qcolor(self._active_glow_hex(), "#38D8FF"),
                    tag="progress_bar_state_change",
                )
            except Exception:
                pass

    def state(self) -> str:
        return self._state

    def set_theme(self, theme: AnimatedProgressBarTheme) -> None:
        self._theme = theme
        self.update()

    def set_accent_color(self, color_hex: str) -> None:
        color = QColor(str(color_hex or "").strip())
        if not color.isValid():
            return

        lighter = color.lighter(138)
        lighter_2 = color.lighter(176)
        border_color = color.lighter(195)

        self._theme = AnimatedProgressBarTheme(
            track_top="rgba(34, 82, 132, 0.96)",
            track_bottom="rgba(14, 40, 72, 0.98)",
            track_border=self._rgba(border_color.name(), 0.76),
            track_mid_glow="rgba(78, 210, 255, 0.18)",
            fill_start=self._rgba(color.name(), 1.0),
            fill_mid=self._rgba(lighter.name(), 1.0),
            fill_end=self._rgba(lighter_2.name(), 1.0),
            fill_edge="rgba(220, 250, 255, 0.30)",
            glow_hex=color.name(),
            text_color="#F8FDFF",
            secondary_text_color="rgba(228, 244, 252, 0.94)",
            percentage_color="#F7FDFF",
            shimmer_color="rgba(255, 255, 255, 0.82)",
            danger_color=self._theme.danger_color,
            success_color=self._theme.success_color,
            warning_color=self._theme.warning_color,
        )
        self.update()

    # -------------------------------------------------------------------------
    # Range / value
    # -------------------------------------------------------------------------

    def minimum(self) -> int:
        return self._minimum

    def maximum(self) -> int:
        return self._maximum

    def setRange(self, minimum: int, maximum: int) -> None:  # noqa: N802
        minimum = int(minimum)
        maximum = int(maximum)
        if maximum <= minimum:
            maximum = minimum + 1

        self._minimum = minimum
        self._maximum = maximum
        self._value = max(self._minimum, min(self._value, self._maximum))
        self._display_value = max(float(self._minimum), min(float(self._display_value), float(self._maximum)))

        self.range_changed.emit(self._minimum, self._maximum)
        self.update()

    def value(self) -> int:
        return self._value

    def percent(self) -> int:
        span = self._maximum - self._minimum
        if span <= 0:
            return 0
        return int(round(((self._value - self._minimum) / span) * 100.0))

    def setValue(self, value: int) -> None:  # noqa: N802
        self.set_value(value)

    def set_value(self, value: int, *, animated: Optional[bool] = None) -> None:
        target = max(self._minimum, min(int(value), self._maximum))
        self._value = target

        if self._mode == self.MODE_INDETERMINATE:
            self.stop_indeterminate()

        use_animation = self._animate_changes if animated is None else bool(animated)
        if use_animation:
            self._animate_to_display_value(float(target))
        else:
            self._display_value = float(target)
            self.update()

        self.value_changed.emit(target)
        if target >= self._maximum:
            self.progress_completed.emit()

    def _animate_to_display_value(self, target: float) -> None:
        if self._value_anim is not None:
            try:
                self._value_anim.stop()
            except Exception:
                pass

        anim = QPropertyAnimation(self, b"displayValue", self)
        if self._is_compact_context():
            duration = 240 if self._size == self.SIZE_SM else 300
        else:
            duration = 280 if self._size == self.SIZE_SM else 360
        anim.setDuration(duration)
        anim.setStartValue(float(self._display_value))
        anim.setEndValue(float(target))
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        self._value_anim = anim

    def get_display_value(self) -> float:
        return self._display_value

    def set_display_value(self, value: float) -> None:
        self._display_value = max(float(self._minimum), min(float(value), float(self._maximum)))
        self.update()

    displayValue = pyqtProperty(float, fget=get_display_value, fset=set_display_value)

    # -------------------------------------------------------------------------
    # Caption / text options
    # -------------------------------------------------------------------------

    def set_caption(self, caption: str) -> None:
        self._caption = str(caption or "").strip()
        self._apply_height()
        self.caption_changed.emit(self._caption)
        self.update()

    def caption(self) -> str:
        return self._caption

    def set_status_text(self, text: str) -> None:
        self._status_text = str(text or "").strip()
        self.status_text_changed.emit(self._status_text)
        self.update()

    def status_text(self) -> str:
        return self._status_text

    def set_show_percentage(self, visible: bool) -> None:
        self._show_percentage = bool(visible)
        self.update()

    def set_show_status_inside_bar(self, visible: bool) -> None:
        self._show_status_inside_bar = bool(visible)
        self.update()

    def set_show_caption(self, visible: bool) -> None:
        self._show_caption = bool(visible)
        self._apply_height()
        self.update()

    # -------------------------------------------------------------------------
    # Indeterminate mode
    # -------------------------------------------------------------------------

    def mode(self) -> str:
        return self._mode

    def start_indeterminate(self, status_text: Optional[str] = None) -> None:
        if status_text is not None:
            self.set_status_text(status_text)

        self._mode = self.MODE_INDETERMINATE
        self._indeterminate_offset = 0.0
        if not self._indeterminate_timer.isActive():
            self._indeterminate_timer.start()

        self.mode_changed.emit(self._mode)
        self.indeterminate_started.emit()
        self.update()

    def stop_indeterminate(self) -> None:
        if self._indeterminate_timer.isActive():
            self._indeterminate_timer.stop()

        was_indeterminate = self._mode == self.MODE_INDETERMINATE
        self._mode = self.MODE_DETERMINATE
        self.mode_changed.emit(self._mode)

        if was_indeterminate:
            self.indeterminate_stopped.emit()

        self.update()

    def is_indeterminate(self) -> bool:
        return self._mode == self.MODE_INDETERMINATE

    def _advance_indeterminate(self) -> None:
        self._indeterminate_offset += 0.032 if self._is_compact_context() else 0.038
        if self._indeterminate_offset > 1.25:
            self._indeterminate_offset = -0.35
        self.update()

    # -------------------------------------------------------------------------
    # Convenience helpers
    # -------------------------------------------------------------------------

    def reset(self) -> None:
        self.stop_indeterminate()
        self.set_state(self.STATE_PRIMARY)
        self._value = self._minimum
        self._display_value = float(self._minimum)
        self._status_text = ""
        self.update()

    def mark_success(self, status_text: str = "Completed") -> None:
        self.stop_indeterminate()
        self.set_state(self.STATE_SUCCESS)
        self.set_value(self._maximum)
        if status_text:
            self.set_status_text(status_text)

    def mark_warning(self, status_text: str = "Needs Attention") -> None:
        self.stop_indeterminate()
        self.set_state(self.STATE_WARNING)
        if status_text:
            self.set_status_text(status_text)

    def mark_error(self, status_text: str = "Error") -> None:
        self.stop_indeterminate()
        self.set_state(self.STATE_DANGER)
        if status_text:
            self.set_status_text(status_text)

    # -------------------------------------------------------------------------
    # Painting helpers
    # -------------------------------------------------------------------------

    def _paint_track(self, painter: QPainter, bar_rect: QRectF, radius: float) -> QPainterPath:
        compact = self._is_compact_context()
        track_path = QPainterPath()
        track_path.addRoundedRect(bar_rect, radius, radius)

        track_gradient = QLinearGradient(bar_rect.topLeft(), bar_rect.bottomLeft())
        track_gradient.setColorAt(0.0, self._to_qcolor(self._theme.track_top, "#245A90"))
        track_gradient.setColorAt(1.0, self._to_qcolor(self._theme.track_bottom, "#0E2E52"))
        painter.fillPath(track_path, track_gradient)

        wash_grad = QLinearGradient(bar_rect.topLeft(), bar_rect.topRight())
        wash_grad.setColorAt(0.0, QColor(92, 225, 255, 28 if compact else 34))
        wash_grad.setColorAt(0.5, QColor(74, 195, 255, 18 if compact else 24))
        wash_grad.setColorAt(1.0, QColor(92, 225, 255, 28 if compact else 34))
        painter.fillPath(track_path, wash_grad)

        mid_grad = QLinearGradient(bar_rect.topLeft(), bar_rect.topRight())
        mid_grad.setColorAt(0.0, QColor(0, 0, 0, 0))
        mid_grad.setColorAt(0.5, self._to_qcolor(self._theme.track_mid_glow, "#55D9FF"))
        mid_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillPath(track_path, mid_grad)

        border_pen = QPen(self._to_qcolor(self._theme.track_border, "#8BE8FF"))
        border_pen.setWidthF(1.2 if compact else 1.4)
        painter.setPen(border_pen)
        painter.drawPath(track_path)

        outer_glow_pen = QPen(QColor(255, 255, 255, 20 if compact else 28))
        outer_glow_pen.setWidthF(0.8 if compact else 0.9)
        painter.setPen(outer_glow_pen)
        painter.drawRoundedRect(bar_rect.adjusted(0.8, 0.8, -0.8, -0.8), radius - 0.8, radius - 0.8)

        gloss_rect = QRectF(
            bar_rect.left() + 2.0,
            bar_rect.top() + 2.0,
            max(0.0, bar_rect.width() - 4.0),
            max(8.0 if compact else 10.0, bar_rect.height() * 0.42),
        )
        gloss_gradient = QLinearGradient(gloss_rect.topLeft(), gloss_rect.bottomLeft())
        gloss_gradient.setColorAt(0.0, QColor(255, 255, 255, 56 if compact else (68 if self._mode == self.MODE_DETERMINATE else 78)))
        gloss_gradient.setColorAt(1.0, QColor(255, 255, 255, 8 if compact else 10))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gloss_gradient)
        gloss_path = QPainterPath()
        gloss_path.addRoundedRect(gloss_rect, max(7.0, radius - 3.0), max(7.0, radius - 3.0))
        painter.drawPath(gloss_path)

        inner_shadow_rect = QRectF(
            bar_rect.left() + 2.0,
            bar_rect.bottom() - max(5.0 if compact else 7.0, bar_rect.height() * 0.20),
            max(0.0, bar_rect.width() - 4.0),
            max(4.0 if compact else 5.0, bar_rect.height() * 0.16),
        )
        inner_shadow_grad = QLinearGradient(inner_shadow_rect.topLeft(), inner_shadow_rect.bottomLeft())
        inner_shadow_grad.setColorAt(0.0, QColor(0, 0, 0, 0))
        inner_shadow_grad.setColorAt(1.0, QColor(0, 0, 0, 18 if compact else 22))
        painter.setBrush(inner_shadow_grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(inner_shadow_rect, radius - 5.0, radius - 5.0)

        return track_path

    def _paint_determinate_fill(self, painter: QPainter, bar_rect: QRectF, radius: float) -> None:
        compact = self._is_compact_context()
        span = float(self._maximum - self._minimum)
        ratio = 0.0 if span <= 0 else (float(self._display_value) - float(self._minimum)) / span
        ratio = max(0.0, min(1.0, ratio))
        if ratio <= 0.0:
            return

        usable_width = max(0.0, bar_rect.width() - 4.0)
        fill_w = usable_width * ratio
        if ratio > 0.0:
            fill_w = max(16.0 if compact else 22.0, fill_w)
        fill_w = min(fill_w, usable_width)

        fill_rect = QRectF(bar_rect.left() + 2.0, bar_rect.top() + 2.0, fill_w, bar_rect.height() - 4.0)
        if fill_rect.width() <= 2.0:
            return

        fill_path = QPainterPath()
        fill_path.addRoundedRect(fill_rect, max(7.0, radius - 3.0), max(7.0, radius - 3.0))

        c1, c2, c3 = self._active_fill_colors()
        fill_gradient = QLinearGradient(fill_rect.topLeft(), fill_rect.topRight())
        fill_gradient.setColorAt(0.0, self._to_qcolor(c1, "#2484FF"))
        fill_gradient.setColorAt(0.38, self._to_qcolor(c2, "#4CD3FF"))
        fill_gradient.setColorAt(1.0, self._to_qcolor(c3, "#9AF4FF"))
        painter.fillPath(fill_path, fill_gradient)

        blue_overlay = QLinearGradient(fill_rect.topLeft(), fill_rect.topRight())
        blue_overlay.setColorAt(0.0, QColor(0, 98, 255, 12 if compact else 18))
        blue_overlay.setColorAt(0.5, QColor(0, 170, 255, 0))
        blue_overlay.setColorAt(1.0, QColor(0, 225, 255, 8 if compact else 12))
        painter.fillPath(fill_path, blue_overlay)

        fill_border_pen = QPen(self._to_qcolor(self._theme.fill_edge, "#DFFAFF"))
        fill_border_pen.setWidthF(0.8 if compact else 1.0)
        painter.setPen(fill_border_pen)
        painter.drawPath(fill_path)

        shine_rect = QRectF(
            fill_rect.left() + 1.0,
            fill_rect.top() + 1.0,
            max(0.0, fill_rect.width() - 2.0),
            max(7.0 if compact else 8.0, fill_rect.height() * 0.38),
        )
        shine_grad = QLinearGradient(shine_rect.topLeft(), shine_rect.bottomLeft())
        shine_grad.setColorAt(0.0, QColor(255, 255, 255, 78 if compact else 92))
        shine_grad.setColorAt(1.0, QColor(255, 255, 255, 10 if compact else 12))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(shine_grad)
        shine_path = QPainterPath()
        shine_path.addRoundedRect(shine_rect, max(6.0, radius - 5.0), max(6.0, radius - 5.0))
        painter.drawPath(shine_path)

        if self._enable_shimmer and fill_rect.width() > (28.0 if compact else 34.0):
            shimmer_width = 30.0 if compact else 44.0
            shimmer_x = fill_rect.left() + (fill_rect.width() * self._shimmer_phase)
            shimmer_rect = QRectF(shimmer_x - shimmer_width * 0.7, fill_rect.top(), shimmer_width, fill_rect.height())
            shimmer_grad = QLinearGradient(shimmer_rect.topLeft(), shimmer_rect.topRight())
            shimmer_grad.setColorAt(0.0, QColor(255, 255, 255, 0))
            shimmer_grad.setColorAt(0.45, QColor(255, 255, 255, 28 if compact else 42))
            shimmer_grad.setColorAt(0.5, self._to_qcolor(self._theme.shimmer_color, "#FFFFFF"))
            shimmer_grad.setColorAt(0.55, QColor(255, 255, 255, 28 if compact else 42))
            shimmer_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.save()
            painter.setClipPath(fill_path)
            painter.fillRect(shimmer_rect, shimmer_grad)
            painter.restore()

    def _paint_indeterminate_fill(self, painter: QPainter, bar_rect: QRectF, radius: float) -> None:
        compact = self._is_compact_context()
        segment_w = max(48.0 if compact else 64.0, bar_rect.width() * (0.22 if compact else 0.26))
        x = bar_rect.left() + (bar_rect.width() * self._indeterminate_offset)

        fill_rect = QRectF(x, bar_rect.top() + 2.0, segment_w, bar_rect.height() - 4.0)
        fill_path = QPainterPath()
        fill_path.addRoundedRect(fill_rect, max(7.0, radius - 3.0), max(7.0, radius - 3.0))

        c1, c2, c3 = self._active_fill_colors()
        fill_gradient = QLinearGradient(fill_rect.topLeft(), fill_rect.topRight())
        fill_gradient.setColorAt(0.0, self._to_qcolor(c1, "#2484FF"))
        fill_gradient.setColorAt(0.5, self._to_qcolor(c2, "#4CD3FF"))
        fill_gradient.setColorAt(1.0, self._to_qcolor(c3, "#9AF4FF"))

        painter.save()
        track_clip = QPainterPath()
        clip_rect = QRectF(bar_rect.left() + 2.0, bar_rect.top() + 2.0, bar_rect.width() - 4.0, bar_rect.height() - 4.0)
        track_clip.addRoundedRect(clip_rect, max(7.0, radius - 3.0), max(7.0, radius - 3.0))
        painter.setClipPath(track_clip)
        painter.fillPath(fill_path, fill_gradient)

        shine_rect = QRectF(
            fill_rect.left() + 1.0,
            fill_rect.top() + 1.0,
            max(0.0, fill_rect.width() - 2.0),
            max(7.0 if compact else 8.0, fill_rect.height() * 0.38),
        )
        shine_grad = QLinearGradient(shine_rect.topLeft(), shine_rect.bottomLeft())
        shine_grad.setColorAt(0.0, QColor(255, 255, 255, 78 if compact else 92))
        shine_grad.setColorAt(1.0, QColor(255, 255, 255, 8 if compact else 10))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(shine_grad)
        painter.drawRoundedRect(shine_rect, radius - 5.0, radius - 5.0)

        shimmer_rect = QRectF(fill_rect.left() + fill_rect.width() * 0.34, fill_rect.top(), 24.0 if compact else 34.0, fill_rect.height())
        shimmer_grad = QLinearGradient(shimmer_rect.topLeft(), shimmer_rect.topRight())
        shimmer_grad.setColorAt(0.0, QColor(255, 255, 255, 0))
        shimmer_grad.setColorAt(0.5, self._to_qcolor(self._theme.shimmer_color, "#FFFFFF"))
        shimmer_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillRect(shimmer_rect, shimmer_grad)
        painter.restore()

    def _paint_text_overlays(self, painter: QPainter, bar_rect: QRectF) -> None:
        compact = self._is_compact_context()
        side_padding = 10.0 if compact else 14.0
        inner_rect = QRectF(
            bar_rect.left() + side_padding,
            bar_rect.top(),
            max(10.0, bar_rect.width() - side_padding * 2),
            bar_rect.height(),
        )

        status = self._status_text or ""
        percent_text = f"{self.percent()}%" if self._show_percentage and self._mode == self.MODE_DETERMINATE else ""
        if self._show_percentage and self._mode == self.MODE_INDETERMINATE:
            percent_text = "..."

        width = self.width()
        hide_status = compact and width > 0 and width < 210
        percent_width = 56.0 if compact else 78.0
        gap = 6.0 if compact else 10.0

        if self._show_status_inside_bar and status and not hide_status:
            painter.setFont(self._status_font())
            painter.setPen(self._to_qcolor(self._theme.text_color, "#F8FDFF"))
            status_rect = QRectF(
                inner_rect.left(),
                inner_rect.top(),
                max(20.0, inner_rect.width() - (percent_width if self._show_percentage else 0.0) - (gap if self._show_percentage else 0.0)),
                inner_rect.height(),
            )
            fm = QFontMetrics(self._status_font())
            elided = fm.elidedText(status, Qt.TextElideMode.ElideRight, int(status_rect.width()))
            painter.drawText(status_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), elided)

        if self._show_percentage:
            painter.setFont(self._percent_font())
            painter.setPen(self._to_qcolor(self._theme.percentage_color, "#F7FDFF"))
            percent_rect = QRectF(inner_rect.right() - percent_width, inner_rect.top(), percent_width, inner_rect.height())
            painter.drawText(percent_rect, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), percent_text)

    # -------------------------------------------------------------------------
    # Main paint
    # -------------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

            rect = QRectF(self.rect().adjusted(1, 1, -1, -1))
            if rect.width() <= 4.0 or rect.height() <= 4.0:
                return

            caption_h = float(self._caption_space())
            bar_rect = QRectF(rect.left(), rect.top() + caption_h, rect.width(), float(self._bar_height()))
            radius = float(self._radius())

            if self._show_caption and self._caption:
                cap_rect = QRectF(rect.left() + 2.0, rect.top(), rect.width() - 4.0, caption_h)
                painter.setFont(self._caption_font())
                painter.setPen(self._to_qcolor(self._theme.secondary_text_color, "#DDF4FF"))
                painter.drawText(cap_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), self._caption)

            self._paint_track(painter, bar_rect, radius)
            if self._mode == self.MODE_INDETERMINATE:
                self._paint_indeterminate_fill(painter, bar_rect, radius)
            else:
                self._paint_determinate_fill(painter, bar_rect, radius)

            self._paint_text_overlays(painter, bar_rect)
        finally:
            painter.end()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_height()

    # -------------------------------------------------------------------------
    # Diagnostics
    # -------------------------------------------------------------------------

    def diagnostics(self) -> dict:
        return {
            "mode": self._mode,
            "state": self._state,
            "minimum": self._minimum,
            "maximum": self._maximum,
            "value": self._value,
            "display_value": round(self._display_value, 2),
            "percent": self.percent(),
            "caption": self._caption,
            "status_text": self._status_text,
            "size": self._size,
            "compact": self._is_compact_context(),
            "kiosk_width": KIOSK_WIDTH,
            "kiosk_height": KIOSK_HEIGHT,
            "indeterminate_active": self._indeterminate_timer.isActive(),
            "shimmer_active": self._shimmer_timer.isActive(),
            "glow_active": self._glow_timer.isActive(),
        }
