"""
widgets/temperature_scale_widget.py

Premium temperature scale widget for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the reusable body-temperature detail visualization widget used by:
    - screens/temperature_detail_screen.py
    - screens/results_screen.py
    - screens/diagnosis_screen.py
- It is designed to work with the uploaded thermometer artwork:
    - assets/detail_graphics/thermometer_scale.png
- It supports both:
    - image-backed mode, where the premium thermometer asset is shown and PyQt
      overlays the animated marker / value / current state
    - painted fallback mode, where the thermometer and band ranges are drawn
      directly in code if the asset is missing
- It is intentionally linked to the project architecture and can consume data
  from:
    - services/session_service.py
    - services/diagnosis_service.py
    - services/health_rules_service.py
    - core/app_state.py

Main capabilities:
- animated temperature marker
- active temperature band detection
- current value display
- range/category chip
- summary interpretation strip
- configurable temperature ranges
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

import math
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
    from core.utils import safe_float, safe_int, safe_str
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

try:
    from core.constants import (
        METRIC_TEMPERATURE,
        SEVERITY_ATTENTION,
        SEVERITY_CRITICAL,
        SEVERITY_NORMAL,
        SEVERITY_UNKNOWN,
        SEVERITY_WARNING,
    )
except Exception:  # pragma: no cover
    METRIC_TEMPERATURE = "temperature"
    SEVERITY_NORMAL = "normal"
    SEVERITY_ATTENTION = "attention"
    SEVERITY_WARNING = "warning"
    SEVERITY_CRITICAL = "critical"
    SEVERITY_UNKNOWN = "unknown"

try:
    from widgets.glow_label import GlowLabel
    _HAS_GLOW_LABEL = True
except Exception:  # pragma: no cover
    GlowLabel = QLabel  # type: ignore
    _HAS_GLOW_LABEL = False


logger = get_logger(__name__)


# ============================================================
# Theme models
# ============================================================

@dataclass
class TemperatureRangeDefinition:
    """
    Normalized temperature range definition.
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


DEFAULT_TEMPERATURE_RANGES: List[TemperatureRangeDefinition] = [
    TemperatureRangeDefinition(
        label="Low",
        minimum=None,
        maximum=36.0,
        severity=SEVERITY_ATTENTION,
        description="Body temperature is below the usual reference range.",
        color_hex="#FFD25E",
        short_label="Low",
    ),
    TemperatureRangeDefinition(
        label="Normal",
        minimum=36.0,
        maximum=37.5,
        severity=SEVERITY_NORMAL,
        description="Body temperature is within the normal reference band.",
        color_hex="#3FE28F",
        short_label="Normal",
    ),
    TemperatureRangeDefinition(
        label="Elevated",
        minimum=37.5,
        maximum=38.3,
        severity=SEVERITY_ATTENTION,
        description="Temperature is slightly above the normal reference band.",
        color_hex="#67D8FF",
        short_label="Elevated",
    ),
    TemperatureRangeDefinition(
        label="Fever",
        minimum=38.3,
        maximum=39.5,
        severity=SEVERITY_WARNING,
        description="Temperature is in the fever range.",
        color_hex="#FFA14D",
        short_label="Fever",
    ),
    TemperatureRangeDefinition(
        label="High Fever",
        minimum=39.5,
        maximum=None,
        severity=SEVERITY_CRITICAL,
        description="Temperature is in a high fever range and needs urgent attention.",
        color_hex="#FF6E88",
        short_label="High",
    ),
]


@dataclass(frozen=True)
class TemperatureScaleTheme:
    """
    Theme container for TemperatureScaleWidget and canvas rendering.
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

    chip_text: str = "#F4FCFF"
    chip_bg_alpha: float = 0.16
    chip_border_alpha: float = 0.36

    neutral_accent: str = "#7FD2FF"
    normal_accent: str = "#3FE28F"
    attention_accent: str = "#FFD25E"
    warning_accent: str = "#FFA14D"
    critical_accent: str = "#FF6F89"

    thermometer_outline: str = "rgba(198, 226, 244, 0.55)"
    thermometer_inner: str = "rgba(13, 28, 52, 0.90)"
    thermometer_glass: str = "rgba(255, 255, 255, 0.06)"
    scale_tick: str = "rgba(190, 217, 236, 0.42)"
    summary_strip_bg: str = "rgba(38, 65, 98, 0.16)"
    summary_strip_border: str = "rgba(153, 216, 255, 0.18)"
    band_bg: str = "rgba(26, 46, 76, 0.22)"
    band_border: str = "rgba(151, 216, 255, 0.14)"
    marker_text_color: str = "#F5FCFF"
    marker_bg_alpha: float = 0.18


DEFAULT_TEMPERATURE_SCALE_THEME = TemperatureScaleTheme()


# ============================================================
# Internal canvas
# ============================================================

class _TemperatureScaleCanvas(QWidget):
    """
    Internal canvas that paints:
    - optional artwork asset
    - fallback thermometer scale
    - animated current-temperature marker
    - active band highlighting
    """

    active_range_changed = pyqtSignal(dict)
    display_value_changed = pyqtSignal(float)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        compact: bool = False,
        theme: TemperatureScaleTheme = DEFAULT_TEMPERATURE_SCALE_THEME,
    ) -> None:
        super().__init__(parent)

        self._compact = bool(compact)
        self._theme = theme

        self._asset_path = ""
        self._asset_pixmap = QPixmap()

        self._ranges: List[TemperatureRangeDefinition] = list(DEFAULT_TEMPERATURE_RANGES)
        self._scale_min = 34.0
        self._scale_max = 41.0

        self._target_value: Optional[float] = None
        self._display_value: float = 0.0
        self._active_index: int = -1
        self._unit = "°C"

        self._value_anim = QPropertyAnimation(self, b"displayValue", self)
        self._value_anim.setDuration(650)
        self._value_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.setMinimumHeight(240 if not compact else 190)
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

    def _current_range(self) -> Optional[TemperatureRangeDefinition]:
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

    def set_ranges(self, ranges: Iterable[TemperatureRangeDefinition]) -> None:
        normalized = [item for item in ranges if isinstance(item, TemperatureRangeDefinition)]
        if normalized:
            self._ranges = normalized

        self._active_index = self._find_active_index(self._target_value)
        self._emit_active_range()
        self.update()

    def ranges(self) -> List[Dict[str, Any]]:
        return [item.to_dict() for item in self._ranges]

    def set_unit(self, unit: str) -> None:
        self._unit = safe_str(unit, "°C").strip() or "°C"
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

    def _draw_asset_background(self, painter: QPainter, rect: QRectF) -> bool:
        if self._asset_pixmap.isNull():
            return False

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
        return True

    def _draw_fallback_bands(
        self,
        painter: QPainter,
        band_rect: QRectF,
        scale_top: float,
        scale_bottom: float,
    ) -> None:
        painter.setPen(Qt.PenStyle.NoPen)

        for idx, definition in enumerate(self._ranges):
            minimum = self._scale_min if definition.minimum is None else definition.minimum
            maximum = self._scale_max if definition.maximum is None else definition.maximum

            y1 = self._value_to_y(maximum, scale_top, scale_bottom)
            y2 = self._value_to_y(minimum, scale_top, scale_bottom)
            height = max(8.0, y2 - y1)

            fill = QColor(definition.color_hex)
            fill.setAlpha(52 if idx == self._active_index else 26)

            row_rect = QRectF(band_rect.left(), y1, band_rect.width(), height)
            painter.setBrush(fill)
            painter.setPen(QPen(QColor(self._theme.band_border), 1.0))
            painter.drawRoundedRect(row_rect, 12.0, 12.0)

            label_font = QFont()
            label_font.setPointSize(9 if not self._compact else 8)
            label_font.setWeight(QFont.Weight.Bold if idx == self._active_index else QFont.Weight.DemiBold)
            painter.setFont(label_font)
            painter.setPen(QColor("#F4FCFF"))
            label_rect = QRectF(row_rect.left() + 8.0, row_rect.top(), row_rect.width() - 16.0, row_rect.height() / 2.0)
            painter.drawText(label_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), definition.label)

            interval_font = QFont()
            interval_font.setPointSize(7 if not self._compact else 7)
            interval_font.setWeight(QFont.Weight.Medium)
            painter.setFont(interval_font)
            painter.setPen(QColor(self._theme.subtle_text))
            painter.drawText(
                QRectF(
                    row_rect.left() + 8.0,
                    row_rect.top() + row_rect.height() / 2.0 - 1.0,
                    row_rect.width() - 16.0,
                    row_rect.height() / 2.0,
                ),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                self._interval_text(definition),
            )

    def _interval_text(self, definition: TemperatureRangeDefinition) -> str:
        lo = definition.minimum
        hi = definition.maximum
        if lo is None and hi is None:
            return "Any"
        if lo is None:
            return f"< {self._format_value(hi)}"
        if hi is None:
            return f"≥ {self._format_value(lo)}"
        return f"{self._format_value(lo)} – {self._format_value(hi)}"

    def _draw_thermometer(
        self,
        painter: QPainter,
        center_x: float,
        top_y: float,
        bottom_y: float,
        tube_width: float,
        bulb_radius: float,
    ) -> None:
        outline_pen = QPen(QColor(self._theme.thermometer_outline))
        outline_pen.setWidthF(2.0 if not self._compact else 1.6)
        painter.setPen(outline_pen)

        outer_tube = QRectF(center_x - tube_width / 2.0, top_y, tube_width, bottom_y - top_y)
        painter.setBrush(QColor(self._theme.thermometer_glass))
        painter.drawRoundedRect(outer_tube, tube_width / 2.0, tube_width / 2.0)

        painter.drawEllipse(QRectF(center_x - bulb_radius, bottom_y - bulb_radius, bulb_radius * 2.0, bulb_radius * 2.0))

        inner_margin = 4.0 if not self._compact else 3.0
        inner_tube = outer_tube.adjusted(inner_margin, inner_margin, -inner_margin, -inner_margin)
        bulb_inner_radius = bulb_radius - inner_margin
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._theme.thermometer_inner))
        painter.drawRoundedRect(inner_tube, inner_tube.width() / 2.0, inner_tube.width() / 2.0)
        painter.drawEllipse(
            QRectF(
                center_x - bulb_inner_radius,
                bottom_y - bulb_inner_radius,
                bulb_inner_radius * 2.0,
                bulb_inner_radius * 2.0,
            )
        )

        current = self._current_range()
        fill_color = QColor(current.color_hex if current else self._theme.neutral_accent)
        fill_color.setAlpha(232)

        fill_y = self._value_to_y(self._display_value, inner_tube.top(), inner_tube.bottom()) if self._target_value is not None else inner_tube.bottom()

        fill_rect = QRectF(inner_tube.left(), fill_y, inner_tube.width(), inner_tube.bottom() - fill_y)
        painter.setBrush(fill_color)
        painter.drawRoundedRect(fill_rect, inner_tube.width() / 2.0, inner_tube.width() / 2.0)
        painter.drawEllipse(
            QRectF(
                center_x - bulb_inner_radius,
                bottom_y - bulb_inner_radius,
                bulb_inner_radius * 2.0,
                bulb_inner_radius * 2.0,
            )
        )

        highlight = QColor(255, 255, 255, 40)
        painter.setBrush(highlight)
        painter.drawRoundedRect(
            QRectF(inner_tube.left() + 2.0, inner_tube.top(), max(2.0, inner_tube.width() * 0.22), inner_tube.height()),
            4.0,
            4.0,
        )

    def _draw_scale_ticks(
        self,
        painter: QPainter,
        center_x: float,
        top_y: float,
        bottom_y: float,
        tube_width: float,
    ) -> None:
        tick_pen = QPen(QColor(self._theme.scale_tick))
        tick_pen.setWidthF(1.2 if not self._compact else 1.0)
        painter.setPen(tick_pen)

        min_tick = int(math.floor(self._scale_min))
        max_tick = int(math.ceil(self._scale_max))
        font = QFont()
        font.setPointSize(8 if not self._compact else 7)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)

        for mark in range(min_tick, max_tick + 1):
            y = self._value_to_y(float(mark), top_y, bottom_y)
            x1 = center_x + tube_width / 2.0 + 8.0
            x2 = x1 + (16.0 if mark % 2 == 0 else 10.0)
            painter.drawLine(int(x1), int(y), int(x2), int(y))
            painter.setPen(QColor(self._theme.subtle_text))
            painter.drawText(
                QRectF(x2 + 4.0, y - 8.0, 26.0, 16.0),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                str(mark),
            )
            painter.setPen(tick_pen)

    def _draw_current_marker(
        self,
        painter: QPainter,
        center_x: float,
        top_y: float,
        bottom_y: float,
        tube_width: float,
        band_rect: QRectF,
    ) -> None:
        if self._target_value is None:
            return

        current = self._current_range()
        accent_hex = current.color_hex if current else self._theme.neutral_accent
        accent = QColor(accent_hex)
        y = self._value_to_y(self._display_value, top_y, bottom_y)

        glow = QColor(accent)
        glow.setAlpha(75)
        glow_pen = QPen(glow)
        glow_pen.setWidthF(6.0 if not self._compact else 5.0)
        glow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(glow_pen)
        painter.drawLine(
            QPoint(int(center_x + tube_width / 2.0 + 4.0), int(y)),
            QPoint(int(band_rect.left() - 8.0), int(y)),
        )

        pen = QPen(accent)
        pen.setWidthF(2.2 if not self._compact else 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(
            QPoint(int(center_x + tube_width / 2.0 + 4.0), int(y)),
            QPoint(int(band_rect.left() - 8.0), int(y)),
        )

        painter.setBrush(QColor(accent_hex))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(center_x - 5.0, y - 5.0, 10.0, 10.0))

        value_text = f"{self._format_value(self._display_value)} {self._unit}"
        pill_rect = QRectF(
            band_rect.left() + 8.0,
            y - 14.0,
            86.0 if not self._compact else 74.0,
            28.0 if not self._compact else 24.0,
        )
        bg = QColor(accent_hex)
        bg.setAlpha(int(255 * self._theme.marker_bg_alpha))
        painter.setBrush(bg)
        painter.setPen(QPen(QColor(accent_hex), 1.0))
        painter.drawRoundedRect(pill_rect, 12.0, 12.0)

        font = QFont()
        font.setPointSize(8 if not self._compact else 7)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor(self._theme.marker_text_color))
        painter.drawText(pill_rect, int(Qt.AlignmentFlag.AlignCenter), value_text)

    def _draw_top_right_readout(self, painter: QPainter, rect: QRectF) -> None:
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
            QRectF(rect.right() - 130.0, rect.top() + 8.0, 120.0, 30.0),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            value_text,
        )

        unit_font = QFont()
        unit_font.setPointSize(9 if not self._compact else 8)
        unit_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(unit_font)
        painter.setPen(QColor(self._theme.unit_color))
        painter.drawText(
            QRectF(rect.right() - 126.0, rect.top() + 35.0, 116.0, 18.0),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            self._unit,
        )

        chip_rect = QRectF(rect.right() - 118.0, rect.top() + 60.0, 108.0, 22.0 if not self._compact else 20.0)
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

            has_asset = self._draw_asset_background(painter, rect)

            left_area = QRectF(rect.left() + 8.0, rect.top() + 12.0, rect.width() * 0.34, rect.height() - 24.0)
            band_rect = QRectF(rect.left() + rect.width() * 0.43, rect.top() + 26.0, rect.width() * 0.46, rect.height() - 58.0)

            center_x = left_area.center().x()
            top_y = left_area.top() + 10.0
            bottom_y = left_area.bottom() - 18.0
            tube_width = 22.0 if not self._compact else 18.0
            bulb_radius = 22.0 if not self._compact else 18.0

            if not has_asset:
                self._draw_fallback_bands(painter, band_rect, top_y, bottom_y)
                self._draw_thermometer(painter, center_x, top_y, bottom_y, tube_width, bulb_radius)

            self._draw_scale_ticks(painter, center_x, top_y, bottom_y, tube_width)
            self._draw_current_marker(painter, center_x, top_y, bottom_y, tube_width, band_rect)
            self._draw_top_right_readout(painter, rect)
        finally:
            painter.end()


# ============================================================
# Main widget
# ============================================================

class TemperatureScaleWidget(QFrame):
    """
    Premium temperature scale widget.

    Main capabilities:
    - polished frame container
    - title / subtitle
    - animated temperature scale
    - active category summary
    - image-backed thermometer artwork or painted fallback
    """

    value_changed = pyqtSignal(object)
    active_category_changed = pyqtSignal(dict)
    payload_applied = pyqtSignal(dict)
    clicked = pyqtSignal()

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        title: str = "Temperature Scale",
        subtitle: str = "Body temperature range visualization",
        unit: str = "°C",
        asset_path: str = "",
        compact: bool = False,
        clickable: bool = False,
        show_header: bool = True,
        show_summary: bool = True,
        theme: Optional[TemperatureScaleTheme] = None,
        minimum_height: int = 360,
    ) -> None:
        super().__init__(parent)

        self._logger = logger.bind(component="TemperatureScaleWidget")
        self._theme = theme or DEFAULT_TEMPERATURE_SCALE_THEME
        self._compact = bool(compact)
        self._clickable = bool(clickable)
        self._show_header = bool(show_header)
        self._show_summary = bool(show_summary)

        self._title = safe_str(title, "").strip()
        self._subtitle = safe_str(subtitle, "").strip()
        self._unit = safe_str(unit, "°C").strip() or "°C"
        self._asset_path = safe_str(asset_path, "").strip()
        self._summary_override = ""

        self._hovered = False
        self._base_pos: Optional[QPoint] = None
        self._hover_anim: Optional[QPropertyAnimation] = None
        self._shadow_effect: Optional[QGraphicsDropShadowEffect] = None

        self.setObjectName("TemperatureScaleWidget")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor if self._clickable else Qt.CursorShape.ArrowCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setMinimumHeight(max(260, int(minimum_height if not compact else minimum_height - 50)))

        self._build_ui()
        self._apply_shadow()
        self._apply_style()

        self._canvas.active_range_changed.connect(self._on_active_range_changed)
        self._canvas.display_value_changed.connect(self._on_canvas_display_value_changed)

        self.set_title(self._title)
        self.set_subtitle(self._subtitle)
        self.set_unit(self._unit)
        self.set_asset_path(self._asset_path)
        self.set_ranges(DEFAULT_TEMPERATURE_RANGES)
        self.set_value(None, animated=False, emit_signal=False)

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

        self._canvas = _TemperatureScaleCanvas(self, compact=self._compact, theme=self._theme)

        self._summary_strip = QFrame(self)
        self._summary_strip.setObjectName("TemperatureScaleSummaryStrip")

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
            QFrame#TemperatureScaleWidget {{
                border: 1px solid {border};
                border-radius: {radius}px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 {bg_top},
                    stop:1 {bg_bottom}
                );
            }}

            QFrame#TemperatureScaleSummaryStrip {{
                border: 1px solid {self._theme.summary_strip_border};
                border-radius: {14 if not self._compact else (10 if self._ultra_compact else 12)}px;
                background: {self._theme.summary_strip_bg};
            }}
            """
        )

        self._title_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.title_color};
                font-size: {'13px' if not self._compact else ('10px' if self._ultra_compact else '11px')};
                font-weight: 800;
                background: transparent;
            }}
            """
        )
        self._subtitle_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.subtitle_color};
                font-size: {'10px' if not self._compact else ('8px' if self._ultra_compact else '9px')};
                font-weight: 500;
                background: transparent;
            }}
            """
        )
        self._summary_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.summary_color};
                font-size: {'10px' if not self._compact else ('8px' if self._ultra_compact else '9px')};
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
        self._unit = safe_str(unit, "°C").strip() or "°C"
        self._canvas.set_unit(self._unit)
        self._update_summary_text()

    def unit(self) -> str:
        return self._unit

    def set_asset_path(self, asset_path: str) -> None:
        self._asset_path = safe_str(asset_path, "").strip()
        self._canvas.set_asset_path(self._asset_path)

    def asset_path(self) -> str:
        return self._asset_path

    def set_ranges(self, ranges: Iterable[TemperatureRangeDefinition]) -> None:
        normalized = [item for item in ranges if isinstance(item, TemperatureRangeDefinition)]
        if not normalized:
            normalized = list(DEFAULT_TEMPERATURE_RANGES)

        self._canvas.set_ranges(normalized)

        mins = [r.minimum for r in normalized if r.minimum is not None]
        maxs = [r.maximum for r in normalized if r.maximum is not None]

        inferred_min = min(mins) if mins else 34.0
        inferred_max = max(maxs) if maxs else 41.0

        inferred_min = min(34.0, inferred_min - 1.0)
        inferred_max = max(41.0, inferred_max + 0.8)

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

    def active_range_definition(self) -> Optional[TemperatureRangeDefinition]:
        payload = self._canvas.active_range_payload()
        if not payload:
            return None
        return TemperatureRangeDefinition(
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
        measurements = {"temperature": 37.9}
        classifications = {
            "temperature": {
                "label": "Elevated",
                "severity": "attention",
                "summary": "Temperature is slightly above normal."
            }
        }
        """
        temp_value = None
        if isinstance(measurements, Mapping):
            temp_value = measurements.get(METRIC_TEMPERATURE, measurements.get("temperature"))

        self.set_value(temp_value, animated=animated, emit_signal=False)

        classification = {}
        if isinstance(classifications, Mapping):
            raw = classifications.get(METRIC_TEMPERATURE, classifications.get("temperature", {}))
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

    def apply_temperature_payload(self, payload: Mapping[str, Any], *, animated: bool = False) -> None:
        """
        Apply a direct temperature widget payload.

        Supported structure:
        {
            "title": "Temperature Scale",
            "subtitle": "Body temperature interpretation",
            "unit": "°C",
            "value": 38.2,
            "summary": "Temperature is elevated.",
            "asset_path": ".../thermometer_scale.png",
            "ranges": [...]
        }
        """
        data = dict(payload or {})

        if "title" in data:
            self.set_title(safe_str(data.get("title"), ""))
        if "subtitle" in data:
            self.set_subtitle(safe_str(data.get("subtitle"), ""))
        if "unit" in data:
            self.set_unit(safe_str(data.get("unit"), "°C"))
        if "asset_path" in data:
            self.set_asset_path(safe_str(data.get("asset_path"), ""))

        raw_ranges = data.get("ranges", None)
        if isinstance(raw_ranges, list) and raw_ranges:
            normalized_ranges: List[TemperatureRangeDefinition] = []
            for item in raw_ranges:
                if isinstance(item, TemperatureRangeDefinition):
                    normalized_ranges.append(item)
                    continue
                if not isinstance(item, Mapping):
                    continue

                normalized_ranges.append(
                    TemperatureRangeDefinition(
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

        if value is None:
            self._summary_label.setText("Temperature value is not available yet.")
        elif current is None:
            self._summary_label.setText(
                f"Temperature {self._canvas._format_value(value)} {self._unit} does not match a configured range."
            )
        else:
            value_text = self._canvas._format_value(value)
            if current.description.strip():
                self._summary_label.setText(
                    f"Temperature {value_text} {self._unit} falls in the “{current.label}” range. {current.description}"
                )
            else:
                self._summary_label.setText(
                    f"Temperature {value_text} {self._unit} falls in the “{current.label}” range."
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
            "active_range": active.to_dict() if active else {},
            "show_header": self._show_header,
            "show_summary": self._show_summary,
            "compact": self._compact,
            "clickable": self._clickable,
            "range_count": len(self._canvas._ranges),
        }
