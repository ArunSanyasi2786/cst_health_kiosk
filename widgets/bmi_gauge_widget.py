"""
widgets/bmi_gauge_widget.py

Premium BMI gauge widget for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the reusable BMI detail-visualization widget used by:
    - screens/bmi_detail_screen.py
    - screens/results_screen.py
    - screens/diagnosis_screen.py
- It is designed to work with the uploaded BMI graphic asset:
    - assets/detail_graphics/bmi_gauge.png
- It supports both:
    - image-backed mode, where the premium asset is shown and PyQt overlays
      the moving needle / value / active state
    - painted fallback mode, where the gauge is drawn directly in code if the
      asset is missing or not available
- It is intentionally linked to the project architecture and can consume data
  from:
    - services/session_service.py
    - services/diagnosis_service.py
    - services/health_rules_service.py
    - core/app_state.py

Main capabilities:
- animated BMI needle
- active range/category detection
- center BMI value display
- category/status chip
- summary interpretation text
- configurable BMI ranges
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
    QSize,
    Qt,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
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
    from config import KIOSK_WIDTH, KIOSK_HEIGHT, IS_COMPACT_KIOSK, UI_SCALE
except Exception:  # pragma: no cover
    KIOSK_WIDTH = 800
    KIOSK_HEIGHT = 480
    IS_COMPACT_KIOSK = KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480
    UI_SCALE = 0.80

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
            return default if value is None else int(float(value))
        except Exception:
            return default

try:
    from core.constants import (
        METRIC_BMI,
        SEVERITY_ATTENTION,
        SEVERITY_CRITICAL,
        SEVERITY_NORMAL,
        SEVERITY_UNKNOWN,
        SEVERITY_WARNING,
    )
except Exception:  # pragma: no cover
    METRIC_BMI = "bmi"
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
class BMIRangeDefinition:
    """
    Normalized BMI range definition.
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


DEFAULT_BMI_RANGES: List[BMIRangeDefinition] = [
    BMIRangeDefinition(
        label="Underweight",
        minimum=None,
        maximum=18.5,
        severity=SEVERITY_ATTENTION,
        description="BMI below the healthy reference range.",
        color_hex="#FFD25E",
        short_label="Low",
    ),
    BMIRangeDefinition(
        label="Normal",
        minimum=18.5,
        maximum=25.0,
        severity=SEVERITY_NORMAL,
        description="Healthy BMI reference range.",
        color_hex="#3FE28F",
        short_label="Healthy",
    ),
    BMIRangeDefinition(
        label="Overweight",
        minimum=25.0,
        maximum=30.0,
        severity=SEVERITY_WARNING,
        description="BMI above the recommended range.",
        color_hex="#FFA14D",
        short_label="High",
    ),
    BMIRangeDefinition(
        label="Obese",
        minimum=30.0,
        maximum=None,
        severity=SEVERITY_CRITICAL,
        description="BMI far above the recommended range.",
        color_hex="#FF6E88",
        short_label="Critical",
    ),
]


@dataclass(frozen=True)
class BMIGaugeTheme:
    """
    Theme container for BMIGaugeWidget and canvas rendering.
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

    gauge_track: str = "rgba(90, 128, 170, 0.16)"
    gauge_track_border: str = "rgba(149, 213, 255, 0.16)"
    gauge_tick: str = "rgba(190, 217, 236, 0.42)"
    needle_base: str = "#DFF7FF"
    center_disc_bg: str = "rgba(15, 31, 57, 0.92)"
    center_disc_border: str = "rgba(173, 229, 255, 0.22)"
    summary_strip_bg: str = "rgba(38, 65, 98, 0.16)"
    summary_strip_border: str = "rgba(153, 216, 255, 0.18)"


DEFAULT_BMI_GAUGE_THEME = BMIGaugeTheme()


# ============================================================
# Internal canvas
# ============================================================

class _BMIGaugeCanvas(QWidget):
    """
    Internal gauge canvas that paints:
    - optional asset artwork
    - fallback painted semicircular ranges
    - animated needle
    - center BMI value
    """

    active_range_changed = pyqtSignal(dict)
    display_value_changed = pyqtSignal(float)

    START_ANGLE_DEG = 210.0
    SWEEP_DEG = 240.0

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        compact: bool = False,
        theme: BMIGaugeTheme = DEFAULT_BMI_GAUGE_THEME,
    ) -> None:
        super().__init__(parent)

        self._compact = bool(compact) or bool(IS_COMPACT_KIOSK)
        self._ultra_compact = bool(KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480)
        self._theme = theme

        self._asset_path = ""
        self._asset_pixmap = QPixmap()

        self._ranges: List[BMIRangeDefinition] = list(DEFAULT_BMI_RANGES)
        self._gauge_min = 10.0
        self._gauge_max = 40.0

        self._target_value: Optional[float] = None
        self._display_value: float = 0.0
        self._active_index: int = -1
        self._unit = "kg/m²"

        self._value_anim = QPropertyAnimation(self, b"displayValue", self)
        self._value_anim.setDuration(650)
        self._value_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        base_height = 240 if not self._compact else 188
        if self._ultra_compact:
            base_height = min(base_height, 176)
        self.setMinimumHeight(base_height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    # --------------------------------------------------------
    # Basic helpers
    # --------------------------------------------------------

    def _format_value(self, value: Optional[float]) -> str:
        if value is None:
            return "--"
        if abs(value - round(value)) < 1e-9:
            return str(int(round(value)))
        return f"{value:.1f}"

    def _normalize_ratio(self, value: float) -> float:
        clamped = max(self._gauge_min, min(self._gauge_max, value))
        span = max(1e-9, self._gauge_max - self._gauge_min)
        return (clamped - self._gauge_min) / span

    def _ratio_to_angle(self, ratio: float) -> float:
        ratio = max(0.0, min(1.0, ratio))
        return self.START_ANGLE_DEG - (self.SWEEP_DEG * ratio)

    def _value_to_angle(self, value: float) -> float:
        return self._ratio_to_angle(self._normalize_ratio(value))

    def _angle_to_point(self, center_x: float, center_y: float, radius: float, angle_deg: float) -> QPoint:
        rad = math.radians(angle_deg)
        x = center_x + math.cos(rad) * radius
        y = center_y - math.sin(rad) * radius
        return QPoint(int(round(x)), int(round(y)))

    def _current_range(self) -> Optional[BMIRangeDefinition]:
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

    def set_ranges(self, ranges: Iterable[BMIRangeDefinition]) -> None:
        normalized = [item for item in ranges if isinstance(item, BMIRangeDefinition)]
        if normalized:
            self._ranges = normalized
        self._active_index = self._find_active_index(self._target_value)
        self._emit_active_range()
        self.update()

    def ranges(self) -> List[Dict[str, Any]]:
        return [item.to_dict() for item in self._ranges]

    def set_unit(self, unit: str) -> None:
        self._unit = safe_str(unit, "kg/m²").strip() or "kg/m²"
        self.update()

    def unit(self) -> str:
        return self._unit

    def set_gauge_limits(self, minimum: float, maximum: float) -> None:
        minimum = float(minimum)
        maximum = float(maximum)
        if maximum <= minimum:
            maximum = minimum + 1.0
        self._gauge_min = minimum
        self._gauge_max = maximum
        self.update()

    def set_value(self, value: Optional[float], *, animated: bool = True) -> None:
        self._target_value = None if value is None else float(value)
        self._active_index = self._find_active_index(self._target_value)
        self._emit_active_range()

        if value is None:
            self._value_anim.stop()
            self._display_value = 0.0
            self.display_value_changed.emit(self._display_value)
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
    # Emission helper
    # --------------------------------------------------------

    def _emit_active_range(self) -> None:
        current = self._current_range()
        self.active_range_changed.emit(current.to_dict() if current else {})

    # --------------------------------------------------------
    # Paint helpers
    # --------------------------------------------------------

    def _draw_asset_or_fallback_gauge(
        self,
        painter: QPainter,
        gauge_rect: QRectF,
        center_x: float,
        center_y: float,
        radius: float,
    ) -> None:
        if not self._asset_pixmap.isNull():
            scaled = self._asset_pixmap.scaled(
                int(gauge_rect.width()),
                int(gauge_rect.height()),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            draw_x = int(gauge_rect.center().x() - scaled.width() / 2.0)
            draw_y = int(gauge_rect.center().y() - scaled.height() / 2.0)
            painter.drawPixmap(draw_x, draw_y, scaled)

            current = self._current_range()
            if current is not None:
                self._draw_active_arc_overlay(painter, gauge_rect, current)
            return

        self._draw_fallback_ranges(painter, gauge_rect)
        self._draw_ticks(painter, center_x, center_y, radius)

    def _draw_fallback_ranges(self, painter: QPainter, gauge_rect: QRectF) -> None:
        track_pen = QPen(QColor(self._theme.gauge_track_border))
        track_pen.setWidthF(18.0 if not self._compact else (12.5 if not self._ultra_compact else 11.0))
        track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track_pen)
        painter.drawArc(
            int(gauge_rect.x()),
            int(gauge_rect.y()),
            int(gauge_rect.width()),
            int(gauge_rect.height()),
            int(-30 * 16),
            int(-240 * 16),
        )

        for idx, definition in enumerate(self._ranges):
            minimum = self._gauge_min if definition.minimum is None else definition.minimum
            maximum = self._gauge_max if definition.maximum is None else definition.maximum

            start_ratio = self._normalize_ratio(minimum)
            end_ratio = self._normalize_ratio(maximum)
            start_angle = self._ratio_to_angle(start_ratio)
            end_angle = self._ratio_to_angle(end_ratio)

            accent = QColor(definition.color_hex)
            if idx == self._active_index:
                pen_width = 18.0 if not self._compact else (12.5 if not self._ultra_compact else 11.0)
                accent.setAlpha(255)
            else:
                pen_width = 14.0 if not self._compact else (10.0 if not self._ultra_compact else 9.0)
                accent.setAlpha(220)

            pen = QPen(accent)
            pen.setWidthF(pen_width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)

            qt_start_deg = -start_angle
            qt_span_deg = -(end_angle - start_angle)
            painter.drawArc(
                int(gauge_rect.x()),
                int(gauge_rect.y()),
                int(gauge_rect.width()),
                int(gauge_rect.height()),
                int(qt_start_deg * 16),
                int(qt_span_deg * 16),
            )

    def _draw_active_arc_overlay(self, painter: QPainter, gauge_rect: QRectF, definition: BMIRangeDefinition) -> None:
        minimum = self._gauge_min if definition.minimum is None else definition.minimum
        maximum = self._gauge_max if definition.maximum is None else definition.maximum

        start_ratio = self._normalize_ratio(minimum)
        end_ratio = self._normalize_ratio(maximum)
        start_angle = self._ratio_to_angle(start_ratio)
        end_angle = self._ratio_to_angle(end_ratio)

        accent = QColor(definition.color_hex)
        accent.setAlpha(170)

        pen = QPen(accent)
        pen.setWidthF(8.0 if not self._compact else (5.5 if not self._ultra_compact else 4.8))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        qt_start_deg = -start_angle
        qt_span_deg = -(end_angle - start_angle)
        painter.drawArc(
            int(gauge_rect.x()),
            int(gauge_rect.y()),
            int(gauge_rect.width()),
            int(gauge_rect.height()),
            int(qt_start_deg * 16),
            int(qt_span_deg * 16),
        )

    def _draw_ticks(self, painter: QPainter, center_x: float, center_y: float, radius: float) -> None:
        tick_color = QColor(self._theme.gauge_tick)
        pen = QPen(tick_color)
        pen.setWidthF(1.6 if not self._compact else 1.3)
        painter.setPen(pen)

        for marker in [10.0, 18.5, 25.0, 30.0, 40.0]:
            angle = self._value_to_angle(marker)
            inner = self._angle_to_point(center_x, center_y, radius * 0.82, angle)
            outer = self._angle_to_point(center_x, center_y, radius * 0.94, angle)
            painter.drawLine(inner, outer)

            label_pt = self._angle_to_point(center_x, center_y, radius * 1.06, angle)
            font = QFont()
            font.setPointSize(8 if not self._compact else (7 if not self._ultra_compact else 6))
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            painter.setPen(QColor(self._theme.subtle_text))

            text = str(int(marker)) if abs(marker - round(marker)) < 1e-9 else f"{marker:.1f}"
            text_rect = QRectF(label_pt.x() - 18.0, label_pt.y() - 8.0, 36.0, 16.0)
            painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignCenter), text)

    def _draw_needle(self, painter: QPainter, center_x: float, center_y: float, radius: float) -> None:
        if self._target_value is None:
            return

        angle = self._value_to_angle(self._display_value)
        needle_tip = self._angle_to_point(center_x, center_y, radius * 0.77, angle)
        current = self._current_range()
        accent_hex = current.color_hex if current is not None else self._theme.neutral_accent

        glow_pen = QPen(QColor(accent_hex))
        glow_pen.setWidthF(7.0 if not self._compact else (4.6 if not self._ultra_compact else 4.0))
        glow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        glow_color = QColor(accent_hex)
        glow_color.setAlpha(75)
        glow_pen.setColor(glow_color)
        painter.setPen(glow_pen)
        painter.drawLine(QPoint(int(center_x), int(center_y)), needle_tip)

        needle_pen = QPen(QColor(accent_hex))
        needle_pen.setWidthF(2.4 if not self._compact else (1.9 if not self._ultra_compact else 1.7))
        needle_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(needle_pen)
        painter.drawLine(QPoint(int(center_x), int(center_y)), needle_tip)

        disc_radius = 14 if not self._compact else (10 if not self._ultra_compact else 9)
        painter.setPen(QPen(QColor(self._theme.center_disc_border), 1.0))
        painter.setBrush(QColor(self._theme.center_disc_bg))
        painter.drawEllipse(QPoint(int(center_x), int(center_y)), disc_radius, disc_radius)

        inner_radius = 5 if not self._compact else (4 if not self._ultra_compact else 3)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._theme.needle_base))
        painter.drawEllipse(QPoint(int(center_x), int(center_y)), inner_radius, inner_radius)

    def _draw_center_labels(self, painter: QPainter, center_x: float, center_y: float, gauge_rect: QRectF) -> None:
        current = self._current_range()
        accent_hex = current.color_hex if current is not None else self._theme.neutral_accent

        value_text = "--" if self._target_value is None else self._format_value(self._display_value)
        category_text = current.label if current is not None else "No Data"

        value_font = QFont()
        value_font.setPointSize(22 if not self._compact else (17 if not self._ultra_compact else 15))
        value_font.setWeight(QFont.Weight.Bold)
        painter.setFont(value_font)
        painter.setPen(QColor(self._theme.value_color))
        painter.drawText(
            QRectF(center_x - 56.0, center_y + 18.0, 112.0, 30.0),
            int(Qt.AlignmentFlag.AlignCenter),
            value_text,
        )

        unit_font = QFont()
        unit_font.setPointSize(9 if not self._compact else (8 if not self._ultra_compact else 7))
        unit_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(unit_font)
        painter.setPen(QColor(self._theme.unit_color))
        painter.drawText(
            QRectF(center_x - 44.0, center_y + 44.0, 88.0, 18.0),
            int(Qt.AlignmentFlag.AlignCenter),
            self._unit,
        )

        chip_rect = QRectF(center_x - (50.0 if not self._ultra_compact else 44.0), center_y + (66.0 if not self._ultra_compact else 60.0), (100.0 if not self._ultra_compact else 88.0), 22.0 if not self._compact else (19.0 if not self._ultra_compact else 18.0))
        accent = QColor(accent_hex)
        accent_bg = QColor(accent_hex)
        accent_bg.setAlpha(48)
        painter.setPen(QPen(accent, 1.0))
        painter.setBrush(accent_bg)
        painter.drawRoundedRect(chip_rect, 10.0, 10.0)

        chip_font = QFont()
        chip_font.setPointSize(8 if not self._compact else (7 if not self._ultra_compact else 6))
        chip_font.setWeight(QFont.Weight.Bold)
        painter.setFont(chip_font)
        painter.setPen(QColor("#F5FCFF"))
        painter.drawText(chip_rect, int(Qt.AlignmentFlag.AlignCenter), category_text)

        title_rect = QRectF(gauge_rect.left(), gauge_rect.bottom() - (24.0 if not self._ultra_compact else 20.0), gauge_rect.width(), 18.0)
        painter.setPen(QColor(self._theme.subtle_text))
        painter.setFont(unit_font)
        painter.drawText(title_rect, int(Qt.AlignmentFlag.AlignCenter), "Body Mass Index")

    def set_compact(self, compact: bool) -> None:
        compact = bool(compact)
        if self._compact == compact and self._ultra_compact == bool(self.width() <= 360 or self.height() <= 220):
            return
        self._compact = compact
        self._ultra_compact = bool(compact and (self.width() <= 360 or self.height() <= 220 or KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480))
        base_height = 240 if not self._compact else 188
        if self._ultra_compact:
            base_height = min(base_height, 176)
        self.setMinimumHeight(base_height)
        self.updateGeometry()
        self.update()

    def compact(self) -> bool:
        return self._compact

    def _sync_compact_mode(self, width: int, height: int) -> None:
        width = int(width or self.width())
        height = int(height or self.height())
        desired_compact = bool(IS_COMPACT_KIOSK or width <= 520 or height <= 250)
        desired_ultra = bool(desired_compact and (width <= 360 or height <= 220 or KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480))
        if desired_compact != self._compact or desired_ultra != self._ultra_compact:
            self._compact = desired_compact
            self._ultra_compact = desired_ultra
            base_height = 240 if not self._compact else 188
            if self._ultra_compact:
                base_height = min(base_height, 176)
            self.setMinimumHeight(base_height)
            self.updateGeometry()
            self.update()

    # --------------------------------------------------------
    # Paint event
    # --------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

            rect = QRectF(self.rect().adjusted(2, 2, -2, -2))
            if rect.width() <= 10.0 or rect.height() <= 10.0:
                return

            self._sync_compact_mode(int(rect.width()), int(rect.height()))

            size = min(rect.width(), rect.height())
            gauge_w = min(size * (0.96 if not self._ultra_compact else 0.92), rect.width() - 8.0)
            gauge_h = min(size * (0.90 if not self._ultra_compact else 0.86), rect.height() - 8.0)

            gauge_rect = QRectF(
                rect.center().x() - gauge_w / 2.0,
                rect.top() + 2.0,
                gauge_w,
                gauge_h,
            )

            center_x = gauge_rect.center().x()
            center_y = gauge_rect.top() + gauge_rect.height() * 0.64
            radius = min(gauge_rect.width() * 0.43, gauge_rect.height() * 0.56)

            self._draw_asset_or_fallback_gauge(painter, gauge_rect, center_x, center_y, radius)
            self._draw_needle(painter, center_x, center_y, radius)
            self._draw_center_labels(painter, center_x, center_y, gauge_rect)

        finally:
            painter.end()


# ============================================================
# Main widget
# ============================================================

class BMIGaugeWidget(QFrame):
    """
    Premium BMI gauge widget.

    Main capabilities:
    - polished frame container
    - title / subtitle
    - animated BMI gauge
    - active category chip
    - summary strip
    - image-backed artwork or painted fallback
    """

    value_changed = pyqtSignal(object)
    active_category_changed = pyqtSignal(dict)
    payload_applied = pyqtSignal(dict)
    clicked = pyqtSignal()

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        title: str = "BMI Gauge",
        subtitle: str = "Body mass index category visualization",
        unit: str = "kg/m²",
        asset_path: str = "",
        compact: bool = False,
        clickable: bool = False,
        show_header: bool = True,
        show_summary: bool = True,
        theme: Optional[BMIGaugeTheme] = None,
        minimum_height: int = 360,
    ) -> None:
        super().__init__(parent)

        self._logger = logger.bind(component="BMIGaugeWidget")
        self._theme = theme or DEFAULT_BMI_GAUGE_THEME
        self._compact = bool(compact) or bool(IS_COMPACT_KIOSK)
        self._ultra_compact = bool(KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480)
        self._clickable = bool(clickable)
        self._show_header = bool(show_header)
        self._show_summary = bool(show_summary)

        self._title = safe_str(title, "").strip()
        self._subtitle = safe_str(subtitle, "").strip()
        self._unit = safe_str(unit, "kg/m²").strip() or "kg/m²"
        self._asset_path = safe_str(asset_path, "").strip()
        self._summary_override = ""
        self._hovered = False
        self._base_pos: Optional[QPoint] = None
        self._hover_anim: Optional[QPropertyAnimation] = None
        self._shadow_effect: Optional[QGraphicsDropShadowEffect] = None

        self.setObjectName("BMIGaugeWidget")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor if self._clickable else Qt.CursorShape.ArrowCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        desired_min_height = int(minimum_height if not self._compact else max(250, minimum_height - 70))
        if self._ultra_compact:
            desired_min_height = min(desired_min_height, 232)
        self.setMinimumHeight(max(220, desired_min_height))

        self._build_ui()
        self._build_runtime_spacing()
        self._apply_shadow()
        self._apply_style()

        self._canvas.active_range_changed.connect(self._on_active_range_changed)
        self._canvas.display_value_changed.connect(self._on_canvas_display_value_changed)

        self.set_title(self._title)
        self.set_subtitle(self._subtitle)
        self.set_unit(self._unit)
        self.set_asset_path(self._asset_path)
        self.set_ranges(DEFAULT_BMI_RANGES)
        self.set_value(None, animated=False, emit_signal=False)

    # --------------------------------------------------------
    # UI
    # --------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(
            12 if not self._compact else (10 if not self._ultra_compact else 8),
            10 if not self._compact else (8 if not self._ultra_compact else 6),
            12 if not self._compact else (10 if not self._ultra_compact else 8),
            10 if not self._compact else (8 if not self._ultra_compact else 6),
        )
        root.setSpacing(8 if not self._compact else (6 if not self._ultra_compact else 5))

        self._header = QWidget(self)
        header_layout = QVBoxLayout(self._header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(1)

        self._title_label = QLabel(self._header)
        self._subtitle_label = QLabel(self._header)

        header_layout.addWidget(self._title_label)
        header_layout.addWidget(self._subtitle_label)

        self._canvas = _BMIGaugeCanvas(self, compact=self._compact, theme=self._theme)

        self._summary_strip = QFrame(self)
        self._summary_strip.setObjectName("BMIGaugeSummaryStrip")

        summary_layout = QHBoxLayout(self._summary_strip)
        summary_layout.setContentsMargins(
            9 if not self._compact else (7 if not self._ultra_compact else 6),
            6 if not self._compact else (5 if not self._ultra_compact else 4),
            9 if not self._compact else (7 if not self._ultra_compact else 6),
            6 if not self._compact else (5 if not self._ultra_compact else 4),
        )
        summary_layout.setSpacing(7 if not self._compact else (5 if not self._ultra_compact else 4))

        self._summary_dot = QLabel(self._summary_strip)
        dot_size = 10 if not self._compact else (8 if not self._ultra_compact else 7)
        self._summary_dot.setFixedSize(dot_size, dot_size)

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
        shadow.setBlurRadius(24 if not self._compact else (18 if not self._ultra_compact else 15))
        shadow.setOffset(0, 6 if not self._compact else (4 if not self._ultra_compact else 3))

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
        radius = 24 if not self._compact else (18 if not self._ultra_compact else 16)

        self.setStyleSheet(
            f"""
            QFrame#BMIGaugeWidget {{
                border: 1px solid {border};
                border-radius: {radius}px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 {bg_top},
                    stop:1 {bg_bottom}
                );
            }}

            QFrame#BMIGaugeSummaryStrip {{
                border: 1px solid {self._theme.summary_strip_border};
                border-radius: {14 if not self._compact else (12 if not self._ultra_compact else 10)}px;
                background: {self._theme.summary_strip_bg};
            }}
            """
        )

        self._title_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.title_color};
                font-size: {'13px' if not self._compact else ('11px' if not self._ultra_compact else '10px')};
                font-weight: 800;
                background: transparent;
            }}
            """
        )
        self._subtitle_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.subtitle_color};
                font-size: {'10px' if not self._compact else ('9px' if not self._ultra_compact else '8px')};
                font-weight: 500;
                background: transparent;
            }}
            """
        )
        self._summary_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.summary_color};
                font-size: {'10px' if not self._compact else ('9px' if not self._ultra_compact else '8px')};
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
            self._shadow_effect.setBlurRadius((28 if self._hovered else 24) if not self._compact else ((22 if self._hovered else 18) if not self._ultra_compact else (18 if self._hovered else 15)))

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
        self._unit = safe_str(unit, "kg/m²").strip() or "kg/m²"
        self._canvas.set_unit(self._unit)
        self._update_summary_text()

    def unit(self) -> str:
        return self._unit

    def set_asset_path(self, asset_path: str) -> None:
        self._asset_path = safe_str(asset_path, "").strip()
        self._canvas.set_asset_path(self._asset_path)

    def asset_path(self) -> str:
        return self._asset_path

    def set_ranges(self, ranges: Iterable[BMIRangeDefinition]) -> None:
        normalized = [item for item in ranges if isinstance(item, BMIRangeDefinition)]
        if not normalized:
            normalized = list(DEFAULT_BMI_RANGES)

        self._canvas.set_ranges(normalized)

        mins = [r.minimum for r in normalized if r.minimum is not None]
        maxs = [r.maximum for r in normalized if r.maximum is not None]

        inferred_min = min(mins) if mins else 10.0
        inferred_max = max(maxs) if maxs else 40.0

        inferred_min = min(10.0, inferred_min - 3.0)
        inferred_max = max(40.0, inferred_max + 5.0)

        self._canvas.set_gauge_limits(inferred_min, inferred_max)
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

    def active_range_definition(self) -> Optional[BMIRangeDefinition]:
        payload = self._canvas.active_range_payload()
        if not payload:
            return None
        return BMIRangeDefinition(
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

    def set_compact(self, compact: bool) -> None:
        compact = bool(compact)
        desired_ultra = bool(compact and (self.width() <= 420 or self.height() <= 260 or KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480))
        if self._compact == compact and self._ultra_compact == desired_ultra:
            return
        self._compact = compact
        self._ultra_compact = desired_ultra
        desired_min_height = int(360 if not self._compact else 280)
        if self._ultra_compact:
            desired_min_height = 232
        self.setMinimumHeight(max(220, desired_min_height))
        self._canvas.set_compact(self._compact)
        self._apply_shadow()
        self._apply_style()
        self._refresh_visibility()
        self.updateGeometry()
        self.update()

    def compact(self) -> bool:
        return self._compact

    def _sync_compact_mode(self, width: int, height: int) -> None:
        width = int(width or self.width())
        height = int(height or self.height())
        desired_compact = bool(IS_COMPACT_KIOSK or width <= 520 or height <= 300)
        desired_ultra = bool(desired_compact and (width <= 420 or height <= 260 or KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480))
        if desired_compact != self._compact or desired_ultra != self._ultra_compact:
            self._compact = desired_compact
            self._ultra_compact = desired_ultra
            desired_min_height = 360 if not self._compact else 280
            if self._ultra_compact:
                desired_min_height = 232
            self.setMinimumHeight(max(220, desired_min_height))
            self._canvas.set_compact(self._compact)
            self._build_runtime_spacing()
            self._apply_shadow()
            self._apply_style()
            self._refresh_visibility()
            self.updateGeometry()
            self.update()

    def _build_runtime_spacing(self) -> None:
        layout = self.layout()
        if isinstance(layout, QVBoxLayout):
            layout.setContentsMargins(
                12 if not self._compact else (10 if not self._ultra_compact else 8),
                10 if not self._compact else (8 if not self._ultra_compact else 6),
                12 if not self._compact else (10 if not self._ultra_compact else 8),
                10 if not self._compact else (8 if not self._ultra_compact else 6),
            )
            layout.setSpacing(8 if not self._compact else (6 if not self._ultra_compact else 5))
        summary_layout = self._summary_strip.layout()
        if isinstance(summary_layout, QHBoxLayout):
            summary_layout.setContentsMargins(
                9 if not self._compact else (7 if not self._ultra_compact else 6),
                6 if not self._compact else (5 if not self._ultra_compact else 4),
                9 if not self._compact else (7 if not self._ultra_compact else 6),
                6 if not self._compact else (5 if not self._ultra_compact else 4),
            )
            summary_layout.setSpacing(7 if not self._compact else (5 if not self._ultra_compact else 4))
        dot_size = 10 if not self._compact else (8 if not self._ultra_compact else 7)
        self._summary_dot.setFixedSize(dot_size, dot_size)

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
        bmi_value = None
        if isinstance(measurements, Mapping):
            bmi_value = measurements.get(METRIC_BMI, measurements.get("bmi"))

        self.set_value(bmi_value, animated=animated, emit_signal=False)

        classification = {}
        if isinstance(classifications, Mapping):
            raw = classifications.get(METRIC_BMI, classifications.get("bmi", {}))
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

    def apply_bmi_payload(self, payload: Mapping[str, Any], *, animated: bool = False) -> None:
        data = dict(payload or {})

        if "title" in data:
            self.set_title(safe_str(data.get("title"), ""))
        if "subtitle" in data:
            self.set_subtitle(safe_str(data.get("subtitle"), ""))
        if "unit" in data:
            self.set_unit(safe_str(data.get("unit"), "kg/m²"))
        if "asset_path" in data:
            self.set_asset_path(safe_str(data.get("asset_path"), ""))

        raw_ranges = data.get("ranges", None)
        if isinstance(raw_ranges, list) and raw_ranges:
            normalized_ranges: List[BMIRangeDefinition] = []
            for item in raw_ranges:
                if isinstance(item, BMIRangeDefinition):
                    normalized_ranges.append(item)
                    continue
                if not isinstance(item, Mapping):
                    continue

                normalized_ranges.append(
                    BMIRangeDefinition(
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
            self._summary_label.setText("BMI value is not available yet.")
        elif current is None:
            self._summary_label.setText(
                f"BMI {self._canvas._format_value(value)} {self._unit} does not match a configured range."
            )
        else:
            value_text = self._canvas._format_value(value)
            if current.description.strip():
                self._summary_label.setText(
                    f"BMI {value_text} {self._unit} falls in the “{current.label}” category. {current.description}"
                )
            else:
                self._summary_label.setText(
                    f"BMI {value_text} {self._unit} falls in the “{current.label}” category."
                )

        self._apply_style()
        self._refresh_visibility()

    # --------------------------------------------------------
    # Visibility / signals
    # --------------------------------------------------------

    def _refresh_visibility(self) -> None:
        has_header = bool(self._title.strip()) or bool(self._subtitle.strip())
        self._header.setVisible(self._show_header and has_header)
        self._title_label.setVisible(bool(self._title.strip()))
        show_subtitle = bool(self._subtitle.strip()) and not (self._ultra_compact and (self.width() <= 420 or self.height() <= 240))
        self._subtitle_label.setVisible(show_subtitle)

        has_summary = bool(self._summary_label.text().strip())
        if self._ultra_compact and self.height() <= 250:
            has_summary = False
        self._summary_strip.setVisible(self._show_summary and has_summary)
        self._summary_label.setVisible(self._show_summary and has_summary)

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

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_compact_mode(self.width(), self.height())

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
