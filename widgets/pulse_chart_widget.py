"""
widgets/pulse_chart_widget.py

Premium pulse-rate reference chart widget for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the reusable pulse-rate detail visualization widget used by:
    - screens/pulse_detail_screen.py
    - screens/results_screen.py
    - screens/diagnosis_screen.py
- It is designed to work with the uploaded pulse reference artwork:
    - assets/detail_graphics/pulse_reference_chart.png
- It supports both:
    - image-backed mode, where the premium chart asset is shown and PyQt
      overlays the current pulse marker / active state / recent trend
    - painted fallback mode, where the chart, zones, and trend line are drawn
      directly in code when the asset is missing or unavailable
- It is intentionally linked to the project architecture and can consume data
  from:
    - services/session_service.py
    - services/diagnosis_service.py
    - services/health_rules_service.py
    - core/app_state.py

Main capabilities:
- animated current pulse marker
- active pulse-range/category detection
- optional recent-history trend line
- current value display
- category/status chip
- summary interpretation strip
- configurable pulse ranges
- asset-backed or pure-painted rendering
- compact and full layouts
- direct payload application from measurement/classification dictionaries

Design goals:
- premium futuristic medical UI
- polished blue/cyan dashboard styling
- safe fallback behavior
- lightweight enough for Raspberry Pi 4B kiosk deployment
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRectF,
    Qt,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
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
    from core.utils import safe_float, safe_str
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

try:
    from core.constants import (
        METRIC_PULSE,
        SEVERITY_ATTENTION,
        SEVERITY_CRITICAL,
        SEVERITY_NORMAL,
        SEVERITY_UNKNOWN,
        SEVERITY_WARNING,
    )
except Exception:  # pragma: no cover
    METRIC_PULSE = "pulse_rate"
    SEVERITY_NORMAL = "normal"
    SEVERITY_ATTENTION = "attention"
    SEVERITY_WARNING = "warning"
    SEVERITY_CRITICAL = "critical"
    SEVERITY_UNKNOWN = "unknown"


logger = get_logger(__name__)


# ============================================================
# Theme models
# ============================================================

@dataclass
class PulseRangeDefinition:
    """
    Normalized pulse-rate range definition.

    The range is interpreted as:
        minimum <= value < maximum
    when both bounds exist.
    """
    label: str
    minimum: Optional[float]
    maximum: Optional[float]
    severity: str
    description: str
    color_hex: str
    short_label: str = ""

    def contains(self, value: float) -> bool:
        if self.minimum is not None and value < self.minimum:
            return False
        if self.maximum is not None and value >= self.maximum:
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


DEFAULT_PULSE_RANGES: List[PulseRangeDefinition] = [
    PulseRangeDefinition(
        label="Low Pulse",
        minimum=None,
        maximum=60.0,
        severity=SEVERITY_ATTENTION,
        description="Resting pulse is below the common adult reference range.",
        color_hex="#FFD25E",
        short_label="Low",
    ),
    PulseRangeDefinition(
        label="Normal",
        minimum=60.0,
        maximum=100.0,
        severity=SEVERITY_NORMAL,
        description="Resting pulse is within the common adult reference range.",
        color_hex="#3FE28F",
        short_label="Normal",
    ),
    PulseRangeDefinition(
        label="Elevated",
        minimum=100.0,
        maximum=120.0,
        severity=SEVERITY_WARNING,
        description="Pulse is above the typical resting range and should be reviewed.",
        color_hex="#FFA14D",
        short_label="High",
    ),
    PulseRangeDefinition(
        label="Very High",
        minimum=120.0,
        maximum=None,
        severity=SEVERITY_CRITICAL,
        description="Pulse is very high and may require urgent attention.",
        color_hex="#FF6E88",
        short_label="Critical",
    ),
]


@dataclass(frozen=True)
class PulseChartTheme:
    """
    Theme container for PulseChartWidget and canvas rendering.
    """
    shell_top: str = "rgba(14, 33, 60, 0.86)"
    shell_bottom: str = "rgba(9, 22, 42, 0.92)"
    shell_hover_top: str = "rgba(20, 43, 75, 0.90)"
    shell_hover_bottom: str = "rgba(10, 27, 51, 0.95)"
    border_color: str = "rgba(151, 217, 255, 0.22)"
    border_hover: str = "rgba(181, 231, 255, 0.38)"
    shadow_hex: str = "#35D6FF"

    title_color: str = "#F5FCFF"
    subtitle_color: str = "rgba(209, 232, 247, 0.82)"
    summary_color: str = "rgba(220, 239, 250, 0.90)"
    subtle_text: str = "rgba(187, 212, 231, 0.82)"
    value_color: str = "#F8FDFF"
    unit_color: str = "rgba(203, 226, 242, 0.84)"

    neutral_accent: str = "#7FD2FF"
    normal_accent: str = "#3FE28F"
    attention_accent: str = "#FFD25E"
    warning_accent: str = "#FFA14D"
    critical_accent: str = "#FF6F89"

    plot_bg: str = "rgba(20, 39, 66, 0.24)"
    plot_border: str = "rgba(149, 213, 255, 0.18)"
    band_border: str = "rgba(151, 216, 255, 0.14)"
    grid_color: str = "rgba(181, 214, 235, 0.16)"
    axis_tick_color: str = "rgba(190, 217, 236, 0.42)"
    trend_fill_alpha: float = 0.16
    marker_bg_alpha: float = 0.18

    summary_strip_bg: str = "rgba(38, 65, 98, 0.16)"
    summary_strip_border: str = "rgba(153, 216, 255, 0.18)"


DEFAULT_PULSE_CHART_THEME = PulseChartTheme()


# ============================================================
# Internal canvas
# ============================================================

class _PulseChartCanvas(QWidget):
    """
    Internal canvas that paints:
    - optional artwork asset
    - fallback pulse reference chart
    - animated current pulse marker
    - active range highlighting
    - optional recent pulse trend
    """

    active_range_changed = pyqtSignal(dict)
    display_value_changed = pyqtSignal(float)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        compact: bool = False,
        theme: PulseChartTheme = DEFAULT_PULSE_CHART_THEME,
    ) -> None:
        super().__init__(parent)

        self._compact = bool(compact)
        self._theme = theme

        self._asset_path = ""
        self._asset_pixmap = QPixmap()

        self._ranges: List[PulseRangeDefinition] = list(DEFAULT_PULSE_RANGES)
        self._scale_min = 40.0
        self._scale_max = 140.0

        self._target_value: Optional[float] = None
        self._display_value: float = 0.0
        self._active_index: int = -1
        self._recent_values: List[float] = []
        self._unit = "bpm"

        self._value_anim = QPropertyAnimation(self, b"displayValue", self)
        self._value_anim.setDuration(650)
        self._value_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.setMinimumHeight(230 if not compact else 190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    # --------------------------------------------------------
    # Helpers
    # --------------------------------------------------------

    def _format_value(self, value: Optional[float]) -> str:
        if value is None:
            return "--"
        if abs(value - round(value)) < 1e-9:
            return str(int(round(value)))
        return f"{value:.1f}"

    def _normalize_ratio(self, value: float) -> float:
        clamped = max(self._scale_min, min(self._scale_max, value))
        span = max(1e-9, self._scale_max - self._scale_min)
        return (clamped - self._scale_min) / span

    def _value_to_y(self, value: float, top_y: float, bottom_y: float) -> float:
        ratio = self._normalize_ratio(value)
        return bottom_y - ((bottom_y - top_y) * ratio)

    def _severity_accent(self, severity: str) -> str:
        severity = safe_str(severity, SEVERITY_UNKNOWN).strip().lower()
        if severity == SEVERITY_NORMAL:
            return self._theme.normal_accent
        if severity == SEVERITY_ATTENTION:
            return self._theme.attention_accent
        if severity == SEVERITY_WARNING:
            return self._theme.warning_accent
        if severity == SEVERITY_CRITICAL:
            return self._theme.critical_accent
        return self._theme.neutral_accent

    def _current_range(self) -> Optional[PulseRangeDefinition]:
        if 0 <= self._active_index < len(self._ranges):
            return self._ranges[self._active_index]
        return None

    def _find_active_index(self, value: Optional[float]) -> int:
        if value is None:
            return -1
        for idx, definition in enumerate(self._ranges):
            if definition.contains(value):
                return idx
        return -1

    def _emit_active_range(self) -> None:
        current = self._current_range()
        self.active_range_changed.emit(current.to_dict() if current else {})

    def _trend_direction(self) -> str:
        if len(self._recent_values) < 2:
            return "stable"
        delta = self._recent_values[-1] - self._recent_values[0]
        if delta > 3:
            return "up"
        if delta < -3:
            return "down"
        return "stable"

    # --------------------------------------------------------
    # Public API
    # --------------------------------------------------------

    def set_asset_path(self, asset_path: str) -> None:
        self._asset_path = safe_str(asset_path, "").strip()
        self._asset_pixmap = QPixmap()

        if self._asset_path:
            path = Path(self._asset_path).expanduser()
            if path.exists() and path.is_file():
                self._asset_pixmap = QPixmap(str(path))

        self.update()

    def set_ranges(self, ranges: Iterable[PulseRangeDefinition]) -> None:
        normalized = [item for item in ranges if isinstance(item, PulseRangeDefinition)]
        if normalized:
            self._ranges = normalized

        self._active_index = self._find_active_index(self._target_value)
        self._emit_active_range()
        self.update()

    def ranges(self) -> List[Dict[str, Any]]:
        return [item.to_dict() for item in self._ranges]

    def set_unit(self, unit: str) -> None:
        self._unit = safe_str(unit, "bpm").strip() or "bpm"
        self.update()

    def unit(self) -> str:
        return self._unit

    def set_scale_limits(self, minimum: float, maximum: float) -> None:
        minimum = float(minimum)
        maximum = float(maximum)
        if maximum <= minimum:
            maximum = minimum + 1.0
        self._scale_min = minimum
        self._scale_max = maximum
        self.update()

    def set_recent_values(self, values: Iterable[Any]) -> None:
        cleaned: List[float] = []
        for item in values:
            if item in (None, ""):
                continue
            cleaned.append(float(safe_float(item, 0.0)))
        self._recent_values = cleaned[-24:]
        self.update()

    def recent_values(self) -> List[float]:
        return list(self._recent_values)

    def set_value(self, value: Optional[float], *, animated: bool = True) -> None:
        self._target_value = None if value is None else float(value)
        self._active_index = self._find_active_index(self._target_value)
        self._emit_active_range()

        if value is None:
            self._value_anim.stop()
            self._display_value = 0.0
            self.update()
            return

        if animated:
            self._value_anim.stop()
            self._value_anim.setStartValue(float(self._display_value))
            self._value_anim.setEndValue(float(value))
            self._value_anim.start()
        else:
            self._display_value = float(value)
            self.display_value_changed.emit(self._display_value)
            self.update()

    def value(self) -> Optional[float]:
        return self._target_value

    def active_range_payload(self) -> Dict[str, Any]:
        current = self._current_range()
        return current.to_dict() if current else {}

    # --------------------------------------------------------
    # Qt property for animation
    # --------------------------------------------------------

    def get_display_value(self) -> float:
        return self._display_value

    def set_display_value(self, value: float) -> None:
        self._display_value = float(value)
        self.display_value_changed.emit(self._display_value)
        self.update()

    displayValue = pyqtProperty(float, fget=get_display_value, fset=set_display_value)

    # --------------------------------------------------------
    # Paint helpers
    # --------------------------------------------------------

    def _draw_asset_background(self, painter: QPainter, rect: QRectF) -> None:
        if self._asset_pixmap.isNull():
            return

        scaled = self._asset_pixmap.scaled(
            int(rect.width()),
            int(rect.height()),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        draw_x = int(rect.center().x() - scaled.width() / 2)
        draw_y = int(rect.center().y() - scaled.height() / 2)
        painter.setOpacity(0.94)
        painter.drawPixmap(draw_x, draw_y, scaled)
        painter.setOpacity(1.0)

    def _draw_plot_shell(self, painter: QPainter, plot_rect: QRectF) -> None:
        painter.setPen(QPen(QColor(self._theme.plot_border), 1.0))
        painter.setBrush(QColor(self._theme.plot_bg))
        painter.drawRoundedRect(plot_rect, 16.0, 16.0)

        gloss = QColor(255, 255, 255, 12)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gloss)
        painter.drawRoundedRect(
            QRectF(
                plot_rect.left() + 1.0,
                plot_rect.top() + 1.0,
                plot_rect.width() - 2.0,
                max(10.0, plot_rect.height() * 0.20),
            ),
            15.0,
            15.0,
        )

    def _draw_range_bands(self, painter: QPainter, plot_rect: QRectF) -> None:
        for idx, definition in enumerate(self._ranges):
            low = self._scale_min if definition.minimum is None else definition.minimum
            high = self._scale_max if definition.maximum is None else definition.maximum

            y_top = self._value_to_y(high, plot_rect.top(), plot_rect.bottom())
            y_bottom = self._value_to_y(low, plot_rect.top(), plot_rect.bottom())
            band_rect = QRectF(
                plot_rect.left(),
                y_top,
                plot_rect.width(),
                max(8.0, y_bottom - y_top),
            )

            fill = QColor(definition.color_hex)
            fill.setAlpha(56 if idx == self._active_index else 24)

            painter.setPen(QPen(QColor(self._theme.band_border), 1.0))
            painter.setBrush(fill)
            painter.drawRoundedRect(band_rect, 12.0, 12.0)

    def _draw_grid(self, painter: QPainter, plot_rect: QRectF) -> None:
        grid_pen = QPen(QColor(self._theme.grid_color))
        grid_pen.setWidthF(1.0)
        painter.setPen(grid_pen)

        y_ticks = [40, 60, 80, 100, 120, 140]
        for val in y_ticks:
            y = self._value_to_y(float(val), plot_rect.top(), plot_rect.bottom())
            painter.drawLine(int(plot_rect.left()), int(y), int(plot_rect.right()), int(y))

        divisions = 6
        for i in range(divisions + 1):
            x = plot_rect.left() + (plot_rect.width() * i / divisions)
            painter.drawLine(int(x), int(plot_rect.top()), int(x), int(plot_rect.bottom()))

    def _draw_axes_labels(self, painter: QPainter, plot_rect: QRectF, label_area_left: float) -> None:
        tick_pen = QPen(QColor(self._theme.axis_tick_color))
        tick_pen.setWidthF(1.1 if not self._compact else 1.0)
        painter.setPen(tick_pen)

        font = QFont()
        font.setPointSize(8 if not self._compact else 7)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)

        y_ticks = [40, 60, 80, 100, 120, 140]
        for val in y_ticks:
            y = self._value_to_y(float(val), plot_rect.top(), plot_rect.bottom())
            painter.drawLine(int(plot_rect.left() - 6), int(y), int(plot_rect.left()), int(y))
            painter.setPen(QColor(self._theme.subtle_text))
            painter.drawText(
                QRectF(label_area_left, y - 8.0, plot_rect.left() - label_area_left - 8.0, 16.0),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                str(val),
            )
            painter.setPen(tick_pen)

    def _draw_trend_line(self, painter: QPainter, plot_rect: QRectF) -> Optional[QPoint]:
        if not self._recent_values:
            return None

        values = self._recent_values[-24:]
        if len(values) == 1:
            x = plot_rect.center().x()
            y = self._value_to_y(values[0], plot_rect.top(), plot_rect.bottom())
            return QPoint(int(x), int(y))

        coords: List[QPoint] = []
        for idx, value in enumerate(values):
            x = plot_rect.left() + (plot_rect.width() * idx / max(1, len(values) - 1))
            y = self._value_to_y(value, plot_rect.top(), plot_rect.bottom())
            coords.append(QPoint(int(x), int(y)))

        accent_hex = self._current_range().color_hex if self._current_range() else self._theme.neutral_accent
        accent = QColor(accent_hex)

        fill_color = QColor(accent)
        fill_color.setAlpha(int(255 * self._theme.trend_fill_alpha))
        fill_path = QPainterPath()
        fill_path.moveTo(float(coords[0].x()), plot_rect.bottom())
        for point in coords:
            fill_path.lineTo(float(point.x()), float(point.y()))
        fill_path.lineTo(float(coords[-1].x()), plot_rect.bottom())
        fill_path.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill_color)
        painter.drawPath(fill_path)

        glow = QColor(accent)
        glow.setAlpha(78)
        glow_pen = QPen(glow)
        glow_pen.setWidthF(6.0 if not self._compact else 5.0)
        glow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        glow_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(glow_pen)
        for i in range(len(coords) - 1):
            painter.drawLine(coords[i], coords[i + 1])

        line_pen = QPen(accent)
        line_pen.setWidthF(2.0 if not self._compact else 1.7)
        line_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        line_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(line_pen)
        for i in range(len(coords) - 1):
            painter.drawLine(coords[i], coords[i + 1])

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(accent))
        for point in coords[:-1]:
            painter.drawEllipse(QRectF(point.x() - 2.0, point.y() - 2.0, 4.0, 4.0))

        latest = coords[-1]
        painter.drawEllipse(QRectF(latest.x() - 4.0, latest.y() - 4.0, 8.0, 8.0))
        return latest

    def _draw_current_marker(self, painter: QPainter, plot_rect: QRectF, latest_point: Optional[QPoint]) -> None:
        if self._target_value is None:
            return

        current = self._current_range()
        accent_hex = current.color_hex if current else self._theme.neutral_accent
        accent = QColor(accent_hex)

        y = self._value_to_y(self._display_value, plot_rect.top(), plot_rect.bottom())
        x = float(latest_point.x()) if latest_point is not None else plot_rect.center().x()

        glow = QColor(accent)
        glow.setAlpha(80)
        glow_pen = QPen(glow)
        glow_pen.setWidthF(7.0 if not self._compact else 5.0)
        glow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(glow_pen)
        painter.drawLine(QPoint(int(plot_rect.left()), int(y)), QPoint(int(plot_rect.right()), int(y)))

        pen = QPen(accent)
        pen.setWidthF(1.9 if not self._compact else 1.6)
        painter.setPen(pen)
        painter.drawLine(QPoint(int(plot_rect.left()), int(y)), QPoint(int(plot_rect.right()), int(y)))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawEllipse(QRectF(x - 5.0, y - 5.0, 10.0, 10.0))

        value_text = f"{self._format_value(self._display_value)} {self._unit}"
        pill_w = 88.0 if not self._compact else 74.0
        pill_rect = QRectF(
            plot_rect.right() - pill_w - 8.0,
            y - 13.0,
            pill_w,
            26.0 if not self._compact else 22.0,
        )

        fill = QColor(accent_hex)
        fill.setAlpha(int(255 * self._theme.marker_bg_alpha))
        painter.setBrush(fill)
        painter.setPen(QPen(QColor(accent_hex), 1.0))
        painter.drawRoundedRect(pill_rect, 12.0, 12.0)

        font = QFont()
        font.setPointSize(8 if not self._compact else 7)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor("#F5FCFF"))
        painter.drawText(pill_rect, int(Qt.AlignmentFlag.AlignCenter), value_text)

    def _draw_header_readout(self, painter: QPainter, rect: QRectF) -> None:
        current = self._current_range()
        accent_hex = current.color_hex if current else self._theme.neutral_accent

        value_text = "--" if self._target_value is None else self._format_value(self._display_value)
        label_text = current.label if current is not None else "No Data"

        value_font = QFont()
        value_font.setPointSize(24 if not self._compact else 18)
        value_font.setWeight(QFont.Weight.Bold)
        painter.setFont(value_font)
        painter.setPen(QColor(self._theme.value_color))
        painter.drawText(
            QRectF(rect.right() - 126.0, rect.top() + 4.0, 116.0, 28.0),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            value_text,
        )

        unit_font = QFont()
        unit_font.setPointSize(9 if not self._compact else 8)
        unit_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(unit_font)
        painter.setPen(QColor(self._theme.unit_color))
        painter.drawText(
            QRectF(rect.right() - 122.0, rect.top() + 29.0, 112.0, 16.0),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            self._unit,
        )

        chip_rect = QRectF(rect.right() - 118.0, rect.top() + 50.0, 108.0, 22.0 if not self._compact else 20.0)
        accent = QColor(accent_hex)
        fill = QColor(accent_hex)
        fill.setAlpha(48)
        painter.setPen(QPen(accent, 1.0))
        painter.setBrush(fill)
        painter.drawRoundedRect(chip_rect, 10.0, 10.0)

        chip_font = QFont()
        chip_font.setPointSize(8 if not self._compact else 7)
        chip_font.setWeight(QFont.Weight.Bold)
        painter.setFont(chip_font)
        painter.setPen(QColor("#F5FCFF"))
        painter.drawText(chip_rect, int(Qt.AlignmentFlag.AlignCenter), label_text)

        trend_text = {
            "up": "▲ Rising",
            "down": "▼ Falling",
            "stable": "● Stable",
        }.get(self._trend_direction(), "● Stable")

        trend_rect = QRectF(rect.right() - 118.0, rect.top() + 76.0, 108.0, 20.0 if not self._compact else 18.0)
        trend_color = QColor(accent_hex)
        trend_fill = QColor(accent_hex)
        trend_fill.setAlpha(36)
        painter.setPen(QPen(trend_color, 1.0))
        painter.setBrush(trend_fill)
        painter.drawRoundedRect(trend_rect, 10.0, 10.0)

        trend_font = QFont()
        trend_font.setPointSize(7 if not self._compact else 7)
        trend_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(trend_font)
        painter.setPen(QColor("#F5FCFF"))
        painter.drawText(trend_rect, int(Qt.AlignmentFlag.AlignCenter), trend_text)

    # --------------------------------------------------------
    # Paint event
    # --------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

            rect = QRectF(self.rect().adjusted(6, 6, -6, -6))
            if rect.width() <= 10.0 or rect.height() <= 10.0:
                return

            self._draw_asset_background(painter, rect)
            self._draw_header_readout(painter, rect)

            label_area_left = rect.left() + 2.0
            plot_rect = QRectF(
                rect.left() + 42.0,
                rect.top() + 102.0,
                rect.width() - 54.0,
                rect.height() - 126.0,
            ).normalized()

            self._draw_plot_shell(painter, plot_rect)
            self._draw_range_bands(painter, plot_rect)
            self._draw_grid(painter, plot_rect)
            self._draw_axes_labels(painter, plot_rect, label_area_left)
            latest_point = self._draw_trend_line(painter, plot_rect)
            self._draw_current_marker(painter, plot_rect, latest_point)
        finally:
            painter.end()


# ============================================================
# Main widget
# ============================================================

class PulseChartWidget(QFrame):
    """
    Premium pulse-rate chart widget.

    Main capabilities:
    - polished frame container
    - title / subtitle
    - animated pulse reference chart
    - active category summary
    - optional recent trend overlay
    - image-backed chart artwork or painted fallback
    """

    value_changed = pyqtSignal(object)
    active_category_changed = pyqtSignal(dict)
    payload_applied = pyqtSignal(dict)
    clicked = pyqtSignal()
    history_changed = pyqtSignal(list)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        title: str = "Pulse Reference Chart",
        subtitle: str = "Resting pulse range visualization",
        unit: str = "bpm",
        asset_path: str = "",
        compact: bool = False,
        clickable: bool = False,
        show_header: bool = True,
        show_summary: bool = True,
        theme: Optional[PulseChartTheme] = None,
        minimum_height: int = 360,
    ) -> None:
        super().__init__(parent)

        self._logger = logger.bind(component="PulseChartWidget")
        self._theme = theme or DEFAULT_PULSE_CHART_THEME
        self._compact = bool(compact)
        self._clickable = bool(clickable)
        self._show_header = bool(show_header)
        self._show_summary = bool(show_summary)

        self._title = safe_str(title, "").strip()
        self._subtitle = safe_str(subtitle, "").strip()
        self._unit = safe_str(unit, "bpm").strip() or "bpm"
        self._asset_path = safe_str(asset_path, "").strip()
        self._summary_override = ""

        self._hovered = False
        self._base_pos: Optional[QPoint] = None
        self._hover_anim: Optional[QPropertyAnimation] = None
        self._shadow_effect: Optional[QGraphicsDropShadowEffect] = None

        self.setObjectName("PulseChartWidget")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor if self._clickable else Qt.CursorShape.ArrowCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setMinimumHeight(max(260, int(minimum_height if not compact else minimum_height - 48)))

        self._build_ui()
        self._apply_shadow()
        self._apply_style()

        self._canvas.active_range_changed.connect(self._on_active_range_changed)
        self._canvas.display_value_changed.connect(self._on_canvas_display_value_changed)

        self.set_title(self._title)
        self.set_subtitle(self._subtitle)
        self.set_unit(self._unit)
        self.set_asset_path(self._asset_path)
        self.set_ranges(DEFAULT_PULSE_RANGES)
        self.set_value(None, animated=False, emit_signal=False)
        self.set_recent_values([], emit_signal=False)

    # --------------------------------------------------------
    # UI
    # --------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(
            12 if not self._compact else 10,
            10 if not self._compact else 8,
            12 if not self._compact else 10,
            10 if not self._compact else 8,
        )
        root.setSpacing(8 if not self._compact else 6)

        self._header = QWidget(self)
        header_layout = QVBoxLayout(self._header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(1)

        self._title_label = QLabel(self._header)
        self._subtitle_label = QLabel(self._header)

        header_layout.addWidget(self._title_label)
        header_layout.addWidget(self._subtitle_label)

        self._canvas = _PulseChartCanvas(self, compact=self._compact, theme=self._theme)

        self._summary_strip = QFrame(self)
        self._summary_strip.setObjectName("PulseChartSummaryStrip")

        summary_layout = QHBoxLayout(self._summary_strip)
        summary_layout.setContentsMargins(
            9 if not self._compact else 7,
            6 if not self._compact else 5,
            9 if not self._compact else 7,
            6 if not self._compact else 5,
        )
        summary_layout.setSpacing(7 if not self._compact else 5)

        self._summary_dot = QLabel(self._summary_strip)
        self._summary_dot.setFixedSize(10 if not self._compact else 8, 10 if not self._compact else 8)

        self._summary_label = QLabel(self._summary_strip)
        self._summary_label.setWordWrap(True)

        summary_layout.addWidget(self._summary_dot, 0, alignment=Qt.AlignmentFlag.AlignTop)
        summary_layout.addWidget(self._summary_label, 1)

        root.addWidget(self._header)
        root.addWidget(self._canvas, 1)
        root.addWidget(self._summary_strip)

    # --------------------------------------------------------
    # Styling
    # --------------------------------------------------------

    def _apply_shadow(self) -> None:
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24 if not self._compact else 18)
        shadow.setOffset(0, 6 if not self._compact else 4)

        color = QColor(self._theme.shadow_hex)
        color.setAlpha(58)
        shadow.setColor(color)

        self.setGraphicsEffect(shadow)
        self._shadow_effect = shadow

    def _active_accent_hex(self) -> str:
        current = self.active_range_definition()
        if current is None:
            return self._theme.neutral_accent
        return current.color_hex

    def _apply_style(self) -> None:
        bg_top = self._theme.shell_hover_top if self._hovered else self._theme.shell_top
        bg_bottom = self._theme.shell_hover_bottom if self._hovered else self._theme.shell_bottom
        border = self._theme.border_hover if self._hovered else self._theme.border_color
        radius = 24 if not self._compact else 18

        self.setStyleSheet(
            f"""
            QFrame#PulseChartWidget {{
                border: 1px solid {border};
                border-radius: {radius}px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 {bg_top},
                    stop:1 {bg_bottom}
                );
            }}

            QFrame#PulseChartSummaryStrip {{
                border: 1px solid {self._theme.summary_strip_border};
                border-radius: {14 if not self._compact else 12}px;
                background: {self._theme.summary_strip_bg};
            }}
            """
        )

        self._title_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.title_color};
                font-size: {'13px' if not self._compact else '11px'};
                font-weight: 800;
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
        self._summary_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.summary_color};
                font-size: {'10px' if not self._compact else '9px'};
                font-weight: 600;
                background: transparent;
            }}
            """
        )

        accent = QColor(self._active_accent_hex())
        dot_radius = self._summary_dot.width() // 2
        self._summary_dot.setStyleSheet(
            f"""
            QLabel {{
                min-width: {self._summary_dot.width()}px;
                min-height: {self._summary_dot.height()}px;
                max-width: {self._summary_dot.width()}px;
                max-height: {self._summary_dot.height()}px;
                border-radius: {dot_radius}px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.92);
                border: 1px solid rgba(255,255,255,0.18);
            }}
            """
        )

        if self._shadow_effect is not None:
            shadow_color = QColor(self._active_accent_hex())
            shadow_color.setAlpha(72 if self._hovered else 56)
            self._shadow_effect.setColor(shadow_color)
            self._shadow_effect.setBlurRadius(28 if self._hovered else 24)

    # --------------------------------------------------------
    # Public API
    # --------------------------------------------------------

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

    def set_unit(self, unit: str) -> None:
        self._unit = safe_str(unit, "bpm").strip() or "bpm"
        self._canvas.set_unit(self._unit)
        self._update_summary_text()

    def unit(self) -> str:
        return self._unit

    def set_asset_path(self, asset_path: str) -> None:
        self._asset_path = safe_str(asset_path, "").strip()
        self._canvas.set_asset_path(self._asset_path)

    def asset_path(self) -> str:
        return self._asset_path

    def set_ranges(self, ranges: Iterable[PulseRangeDefinition]) -> None:
        normalized = [item for item in ranges if isinstance(item, PulseRangeDefinition)]
        if not normalized:
            normalized = list(DEFAULT_PULSE_RANGES)

        self._canvas.set_ranges(normalized)

        mins = [r.minimum for r in normalized if r.minimum is not None]
        maxs = [r.maximum for r in normalized if r.maximum is not None]

        inferred_min = min(mins) if mins else 40.0
        inferred_max = max(maxs) if maxs else 140.0

        inferred_min = min(40.0, inferred_min - 10.0)
        inferred_max = max(140.0, inferred_max + 10.0)

        self._canvas.set_scale_limits(inferred_min, inferred_max)
        self._update_summary_text()

    def ranges(self) -> List[Dict[str, Any]]:
        return self._canvas.ranges()

    def set_value(self, value: Any, *, animated: bool = True, emit_signal: bool = True) -> None:
        numeric: Optional[float]
        if value in (None, ""):
            numeric = None
        else:
            numeric = safe_float(value, 0.0)

        self._canvas.set_value(numeric, animated=animated)
        self._update_summary_text()

        if emit_signal:
            self.value_changed.emit(numeric)

    def value(self) -> Optional[float]:
        return self._canvas.value()

    def set_recent_values(self, values: Iterable[Any], *, emit_signal: bool = True) -> None:
        self._canvas.set_recent_values(values)
        self._update_summary_text()

        if emit_signal:
            self.history_changed.emit(self._canvas.recent_values())

    def recent_values(self) -> List[float]:
        return self._canvas.recent_values()

    def clear_recent_values(self) -> None:
        self.set_recent_values([])

    def active_range_definition(self) -> Optional[PulseRangeDefinition]:
        payload = self._canvas.active_range_payload()
        if not payload:
            return None
        return PulseRangeDefinition(
            label=safe_str(payload.get("label"), ""),
            minimum=payload.get("minimum"),
            maximum=payload.get("maximum"),
            severity=safe_str(payload.get("severity"), SEVERITY_UNKNOWN),
            description=safe_str(payload.get("description"), ""),
            color_hex=safe_str(payload.get("color_hex"), self._theme.neutral_accent),
            short_label=safe_str(payload.get("short_label"), ""),
        )

    def set_summary_override(self, text: str) -> None:
        self._summary_override = safe_str(text, "").strip()
        self._update_summary_text()

    def clear_summary_override(self) -> None:
        self._summary_override = ""
        self._update_summary_text()

    def set_show_header(self, visible: bool) -> None:
        self._show_header = bool(visible)
        self._refresh_visibility()

    def set_show_summary(self, visible: bool) -> None:
        self._show_summary = bool(visible)
        self._refresh_visibility()

    def set_clickable(self, clickable: bool) -> None:
        self._clickable = bool(clickable)
        self.setCursor(Qt.CursorShape.PointingHandCursor if self._clickable else Qt.CursorShape.ArrowCursor)

    # --------------------------------------------------------
    # Payload integration
    # --------------------------------------------------------

    def apply_measurement_payload(
        self,
        measurements: Mapping[str, Any],
        classifications: Optional[Mapping[str, Any]] = None,
        *,
        animated: bool = False,
    ) -> None:
        """
        Apply measurement/classification payloads.

        Example:
        measurements = {"pulse_rate": 88}
        classifications = {
            "pulse_rate": {
                "label": "Normal",
                "severity": "normal",
                "summary": "Resting pulse is within the common adult reference range."
            }
        }
        """
        pulse_value = None
        if isinstance(measurements, Mapping):
            pulse_value = measurements.get(
                METRIC_PULSE,
                measurements.get("pulse_rate", measurements.get("pulse")),
            )

        self.set_value(pulse_value, animated=animated, emit_signal=False)

        history = []
        if isinstance(measurements, Mapping):
            raw_history = measurements.get("pulse_history", measurements.get("recent_pulse_values", []))
            if isinstance(raw_history, list):
                history = raw_history
        self.set_recent_values(history, emit_signal=False)

        classification = {}
        if isinstance(classifications, Mapping):
            raw = classifications.get(
                METRIC_PULSE,
                classifications.get("pulse_rate", classifications.get("pulse", {})),
            )
            if isinstance(raw, Mapping):
                classification = dict(raw)

        if classification:
            summary = safe_str(classification.get("summary"), "").strip()
            if summary:
                self.set_summary_override(summary)
            else:
                self.clear_summary_override()
        else:
            self.clear_summary_override()

        payload = {
            "measurements": dict(measurements or {}),
            "classifications": dict(classifications or {}),
        }
        self.payload_applied.emit(payload)

    def apply_pulse_payload(self, payload: Mapping[str, Any], *, animated: bool = False) -> None:
        """
        Apply a direct pulse widget payload.

        Supported structure:
        {
            "title": "Pulse Reference Chart",
            "subtitle": "Resting pulse interpretation",
            "unit": "bpm",
            "value": 88,
            "recent_values": [80, 82, 84, 88],
            "summary": "Resting pulse is within the common adult reference range.",
            "asset_path": ".../pulse_reference_chart.png",
            "ranges": [...]
        }
        """
        data = dict(payload or {})

        if "title" in data:
            self.set_title(safe_str(data.get("title"), ""))
        if "subtitle" in data:
            self.set_subtitle(safe_str(data.get("subtitle"), ""))
        if "unit" in data:
            self.set_unit(safe_str(data.get("unit"), "bpm"))
        if "asset_path" in data:
            self.set_asset_path(safe_str(data.get("asset_path"), ""))

        raw_ranges = data.get("ranges", None)
        if isinstance(raw_ranges, list) and raw_ranges:
            normalized_ranges: List[PulseRangeDefinition] = []
            for item in raw_ranges:
                if isinstance(item, PulseRangeDefinition):
                    normalized_ranges.append(item)
                    continue
                if not isinstance(item, Mapping):
                    continue

                normalized_ranges.append(
                    PulseRangeDefinition(
                        label=safe_str(item.get("label"), ""),
                        minimum=None if item.get("minimum", item.get("min")) in (None, "") else safe_float(item.get("minimum", item.get("min")), 0.0),
                        maximum=None if item.get("maximum", item.get("max")) in (None, "") else safe_float(item.get("maximum", item.get("max")), 0.0),
                        severity=safe_str(item.get("severity"), SEVERITY_UNKNOWN),
                        description=safe_str(item.get("description"), item.get("summary", "")),
                        color_hex=safe_str(item.get("color_hex"), self._theme.neutral_accent),
                        short_label=safe_str(item.get("short_label"), item.get("badge", "")),
                    )
                )
            if normalized_ranges:
                self.set_ranges(normalized_ranges)

        if "summary" in data:
            self.set_summary_override(safe_str(data.get("summary"), ""))

        if "recent_values" in data and isinstance(data.get("recent_values"), list):
            self.set_recent_values(data.get("recent_values", []), emit_signal=False)

        if "value" in data:
            self.set_value(data.get("value"), animated=animated, emit_signal=False)

        self.payload_applied.emit(dict(data))

    # --------------------------------------------------------
    # Summary handling
    # --------------------------------------------------------

    def _update_summary_text(self) -> None:
        if self._summary_override.strip():
            self._summary_label.setText(self._summary_override.strip())
            self._apply_style()
            self._refresh_visibility()
            return

        current = self.active_range_definition()
        value = self.value()
        trend = self._canvas._trend_direction()

        if value is None:
            self._summary_label.setText("Pulse value is not available yet.")
        elif current is None:
            self._summary_label.setText(
                f"Pulse {self._canvas._format_value(value)} {self._unit} does not match a configured range."
            )
        else:
            value_text = self._canvas._format_value(value)
            trend_text = {
                "up": "The recent trend is rising.",
                "down": "The recent trend is falling.",
                "stable": "The recent trend is stable.",
            }.get(trend, "The recent trend is stable.")

            if current.description.strip():
                self._summary_label.setText(
                    f"Pulse {value_text} {self._unit} falls in the “{current.label}” range. "
                    f"{current.description} {trend_text}"
                )
            else:
                self._summary_label.setText(
                    f"Pulse {value_text} {self._unit} falls in the “{current.label}” range. {trend_text}"
                )

        self._apply_style()
        self._refresh_visibility()

    # --------------------------------------------------------
    # Visibility / signals
    # --------------------------------------------------------

    def _refresh_visibility(self) -> None:
        self._header.setVisible(self._show_header)
        self._title_label.setVisible(bool(self._title.strip()))
        self._subtitle_label.setVisible(bool(self._subtitle.strip()))
        self._summary_strip.setVisible(self._show_summary)
        self._summary_label.setVisible(self._show_summary)

    def _on_active_range_changed(self, payload: Dict[str, Any]) -> None:
        self._update_summary_text()
        self._apply_style()
        self.active_category_changed.emit(dict(payload))

    def _on_canvas_display_value_changed(self, _: float) -> None:
        self._update_summary_text()

    # --------------------------------------------------------
    # Hover / interaction
    # --------------------------------------------------------

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

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if self._clickable and event is not None and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def _is_layout_managed(self) -> bool:
        parent = self.parentWidget()
        if parent is None:
            return False
        return parent.layout() is not None

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

    # --------------------------------------------------------
    # Paint
    # --------------------------------------------------------

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            rect = QRectF(self.rect().adjusted(1, 1, -1, -1))
            if rect.width() > 4.0 and rect.height() > 4.0:
                radius = float(24 if not self._compact else 18)
                path = QPainterPath()
                path.addRoundedRect(rect, radius, radius)

                painter.save()
                painter.setClipPath(path)
                gloss_rect = QRectF(
                    rect.left() + 2.0,
                    rect.top() + 2.0,
                    max(0.0, rect.width() - 4.0),
                    max(0.0, rect.height() * 0.30),
                )
                painter.fillRect(gloss_rect, QColor(255, 255, 255, 12 if not self._hovered else 18))
                painter.restore()
        finally:
            painter.end()

    # --------------------------------------------------------
    # Diagnostics
    # --------------------------------------------------------

    def diagnostics(self) -> Dict[str, Any]:
        active = self.active_range_definition()
        return {
            "title": self._title,
            "subtitle": self._subtitle,
            "unit": self._unit,
            "asset_path": self._asset_path,
            "value": self.value(),
            "recent_values_count": len(self.recent_values()),
            "active_range": active.to_dict() if active else {},
            "show_header": self._show_header,
            "show_summary": self._show_summary,
            "compact": self._compact,
            "clickable": self._clickable,
            "range_count": len(self._canvas._ranges),
        }
