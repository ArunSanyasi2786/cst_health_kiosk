"""
screens/temperature_detail_screen.py

Premium temperature detail screen for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the public-facing temperature explanation screen opened from:
    - screens/results_screen.py
- It allows the user or operator to:
    - inspect the current body-temperature value in a premium detailed view
    - understand the category and severity of the temperature result
    - review the reference range bands used by the kiosk
    - see the active temperature band highlighted in a polished medical-kiosk style
    - navigate back to results or continue to QR / consult workflows
- It is designed specifically for:
    - Raspberry Pi 4B touchscreen kiosk deployment
    - 1024x600 kiosk resolution
    - laptop demo mode
- It provides:
    - glossy futuristic blue medical UI
    - resilient loading from session_service / diagnosis_service / threshold_service
    - threshold-aware temperature interpretation
    - safe Celsius normalization when source values are inconsistent
    - safe fallback behavior when services are still being integrated
    - maintainable self-contained drawing logic for the temperature scale

Linked project files this screen is intended to work with:
- config.py
- core/constants.py
- core/asset_paths.py
- core/logger.py
- core/app_state.py
- core/navigator.py
- core/theme_manager.py
- core/animation_manager.py
- services/session_service.py
- services/diagnosis_service.py
- services/threshold_service.py
- services/health_rules_service.py
- widgets/animated_button.py
- widgets/glow_label.py
- widgets/temperature_scale_widget.py

Navigation targets this screen is designed to link to:
- screens/results_screen.py
- screens/qr_screen.py
- screens/consult_screen.py

Design goals:
- glossy futuristic blue medical UI
- informative but calm patient-facing detail screen
- strong readability at 1024x600
- premium thermometer-style scale with active-band highlighting
- resilient integration while backend files continue evolving
"""

from __future__ import annotations

import math
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
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
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
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
        SCREEN_RESULTS,
        SCREEN_QR,
        SCREEN_CONSULT,
        METRIC_TEMPERATURE,
    )
except Exception:  # pragma: no cover
    SCREEN_RESULTS = "results"
    SCREEN_QR = "qr"
    SCREEN_CONSULT = "consult"
    METRIC_TEMPERATURE = "temperature"

try:
    from config import KIOSK_WIDTH, KIOSK_HEIGHT, IS_COMPACT_KIOSK
except Exception:  # pragma: no cover
    KIOSK_WIDTH = 800
    KIOSK_HEIGHT = 480
    IS_COMPACT_KIOSK = True

try:
    from widgets.animated_button import AnimatedButton
except Exception:  # pragma: no cover
    AnimatedButton = None  # type: ignore

try:
    from widgets.glow_label import GlowLabel
    _HAS_GLOW_LABEL = True
except Exception:  # pragma: no cover
    GlowLabel = QLabel  # type: ignore
    _HAS_GLOW_LABEL = False


logger = get_logger(__name__)


# =============================================================================
# Helpers / constants
# =============================================================================

TEMP_WARNING_LOW = 35.0
TEMP_NORMAL_LOW = 36.0
TEMP_NORMAL_HIGH = 37.5
TEMP_WARNING_HIGH = 39.0

TEMP_SCALE_MIN = 33.0
TEMP_SCALE_MAX = 41.0


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_asset(relative_path: str) -> str:
    """
    Resolve asset path using core.asset_paths if available, otherwise fallback
    to project-relative assets directory.
    """
    relative_clean = safe_str(relative_path, "").strip().replace("\\", "/").lstrip("/")
    if not relative_clean:
        return ""

    try:
        import core.asset_paths as asset_paths  # local import on purpose

        for name in (
            "get_asset_path",
            "asset_path",
            "resolve_asset_path",
            "resolve_asset",
            "asset",
        ):
            resolver = getattr(asset_paths, name, None)
            if callable(resolver):
                try:
                    resolved = resolver(relative_clean)
                    resolved_text = safe_str(resolved, "").strip()
                    if resolved_text:
                        return resolved_text
                except Exception:
                    continue
    except Exception:
        pass

    return str(_project_root().joinpath("assets", *relative_clean.split("/")))


def _pixmap_or_empty(path: str) -> QPixmap:
    text = safe_str(path, "").strip()
    if not text:
        return QPixmap()
    return QPixmap(text)


def _format_num(value: Any, decimals: int = 1, suffix: str = "") -> str:
    if value in (None, ""):
        return "--"
    try:
        num = float(value)
        return f"{num:.{decimals}f}{suffix}"
    except Exception:
        return "--"


def _normalize_temperature_celsius(value: Any) -> Optional[float]:
    """
    Accept temperature in:
    - Celsius directly
    - Fahrenheit if obviously outside Celsius body-temp range
    """
    if value in (None, ""):
        return None

    raw = safe_float(value, 0.0)
    if raw <= 0:
        return None

    # Handle Fahrenheit body-temp style values
    if 80.0 <= raw <= 120.0:
        celsius = (raw - 32.0) * 5.0 / 9.0
        return round(celsius, 1)

    # Already Celsius
    return round(raw, 1)


def _accent_for_state(state: str) -> str:
    text = safe_str(state, "").strip().lower()
    if text in {"critical", "high fever", "hypothermia"}:
        return "#FF6E88"
    if text in {"warning", "fever"}:
        return "#FFA14D"
    if text in {"attention", "below normal"}:
        return "#FFD25E"
    if text in {"normal", "healthy"}:
        return "#42E393"
    return "#39D8FF"


def _normalize_temperature_thresholds(raw: Optional[Mapping[str, Any]]) -> Dict[str, float]:
    base = {
        "warning_low": TEMP_WARNING_LOW,
        "normal_low": TEMP_NORMAL_LOW,
        "normal_high": TEMP_NORMAL_HIGH,
        "warning_high": TEMP_WARNING_HIGH,
    }

    if isinstance(raw, Mapping):
        base.update(
            {
                "warning_low": safe_float(raw.get("warning_low"), base["warning_low"]),
                "normal_low": safe_float(raw.get("normal_low"), base["normal_low"]),
                "normal_high": safe_float(raw.get("normal_high"), base["normal_high"]),
                "warning_high": safe_float(raw.get("warning_high"), base["warning_high"]),
            }
        )

    ordered = sorted(
        [
            float(base["warning_low"]),
            float(base["normal_low"]),
            float(base["normal_high"]),
            float(base["warning_high"]),
        ]
    )

    return {
        "warning_low": round(ordered[0], 1),
        "normal_low": round(ordered[1], 1),
        "normal_high": round(ordered[2], 1),
        "warning_high": round(ordered[3], 1),
    }


def _build_temperature_interpretation(
    temperature_c: Optional[float],
    thresholds: Mapping[str, float],
) -> Dict[str, Any]:
    if temperature_c is None:
        return {
            "label": "Unavailable",
            "severity": "unknown",
            "summary": "Temperature could not be interpreted because no valid reading is available.",
            "detail": "A missing or invalid temperature value prevents proper body-temperature classification.",
            "recommendation": "Repeat the temperature measurement and keep the sensor stable during capture.",
            "active_band": "unknown",
            "accent_hex": "#39D8FF",
        }

    warning_low = safe_float(thresholds.get("warning_low"), TEMP_WARNING_LOW)
    normal_low = safe_float(thresholds.get("normal_low"), TEMP_NORMAL_LOW)
    normal_high = safe_float(thresholds.get("normal_high"), TEMP_NORMAL_HIGH)
    warning_high = safe_float(thresholds.get("warning_high"), TEMP_WARNING_HIGH)

    if temperature_c < warning_low:
        return {
            "label": "Hypothermia",
            "severity": "critical",
            "summary": "Temperature is markedly below the preferred body-temperature range.",
            "detail": "This level is low enough to deserve prompt attention and should not be dismissed without context.",
            "recommendation": "Retake the reading to confirm it. Seek urgent professional review if the low value is persistent or symptoms are present.",
            "active_band": "very_low",
            "accent_hex": _accent_for_state("critical"),
        }

    if temperature_c < normal_low:
        return {
            "label": "Below Normal",
            "severity": "attention",
            "summary": "Temperature is below the normal reference band.",
            "detail": "This may reflect environmental conditions, measurement variability, or a low physiological temperature.",
            "recommendation": "Retest if needed and interpret together with symptoms and the broader clinical picture.",
            "active_band": "low",
            "accent_hex": _accent_for_state("attention"),
        }

    if temperature_c <= normal_high:
        return {
            "label": "Healthy",
            "severity": "normal",
            "summary": "Temperature falls within the normal body-temperature reference range.",
            "detail": "This result is generally reassuring when considered with the full session results.",
            "recommendation": "Routine handoff is usually sufficient unless other measurements raise concern.",
            "active_band": "normal",
            "accent_hex": _accent_for_state("normal"),
        }

    if temperature_c < warning_high:
        return {
            "label": "Fever",
            "severity": "warning",
            "summary": "Temperature is above the normal reference band.",
            "detail": "This pattern is consistent with an elevated body temperature or fever range.",
            "recommendation": "Review symptoms, repeat the reading if necessary, and consider professional follow-up.",
            "active_band": "high",
            "accent_hex": _accent_for_state("warning"),
        }

    return {
        "label": "High Fever",
        "severity": "critical",
        "summary": "Temperature is markedly elevated above the normal reference range.",
        "detail": "This result deserves careful attention and may require urgent follow-up depending on context.",
        "recommendation": "Retake to confirm accuracy and escalate according to approved clinical or supervisory workflow.",
        "active_band": "very_high",
        "accent_hex": _accent_for_state("critical"),
    }


# =============================================================================
# Internal widgets
# =============================================================================

class _TemperatureScaleFallbackWidget(QWidget):
    """
    Self-contained premium fallback temperature scale.

    The widget draws:
    - vertical thermometer tube and bulb
    - banded temperature ranges
    - glowing marker at the current value
    - center-side detail text
    - faint optional overlay from detail_graphics/thermometer_scale.png
    """

    def __init__(self, overlay_path: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._overlay_pixmap = _pixmap_or_empty(overlay_path)
        self._temp_c: Optional[float] = None
        self._thresholds = _normalize_temperature_thresholds(None)
        self._label = "Temperature"
        self._accent_hex = "#39D8FF"

        self.setMinimumHeight(250)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_payload(
        self,
        *,
        temperature_c: Optional[float],
        label: str,
        thresholds: Mapping[str, float],
        accent_hex: str,
    ) -> None:
        self._temp_c = temperature_c
        self._label = safe_str(label, "Temperature").strip() or "Temperature"
        self._thresholds = _normalize_temperature_thresholds(thresholds)
        self._accent_hex = safe_str(accent_hex, "#39D8FF").strip() or "#39D8FF"
        self.update()

    def _value_to_ratio(self, value: float) -> float:
        clamped = max(TEMP_SCALE_MIN, min(TEMP_SCALE_MAX, float(value)))
        return (clamped - TEMP_SCALE_MIN) / (TEMP_SCALE_MAX - TEMP_SCALE_MIN)

    def _segment_ratio(self, value: float) -> float:
        return 1.0 - self._value_to_ratio(value)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect = self.rect().adjusted(12, 10, -12, -10)
        compact_widget = bool(rect.width() <= 700 or rect.height() <= 220)

        if not self._overlay_pixmap.isNull():
            overlay = self._overlay_pixmap.scaled(
                rect.width(),
                rect.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.setOpacity(0.028 if compact_widget else 0.07)
            painter.drawPixmap(
                int(rect.center().x() - overlay.width() / 2),
                int(rect.center().y() - overlay.height() / 2),
                overlay,
            )
            painter.setOpacity(1.0)

        active_color = QColor(self._accent_hex)
        segments = [
            (TEMP_SCALE_MIN, self._thresholds["warning_low"], QColor("#FF6E88")),
            (self._thresholds["warning_low"], self._thresholds["normal_low"], QColor("#FFD25E")),
            (self._thresholds["normal_low"], self._thresholds["normal_high"], QColor("#42E393")),
            (self._thresholds["normal_high"], self._thresholds["warning_high"], QColor("#FFA14D")),
            (self._thresholds["warning_high"], TEMP_SCALE_MAX, QColor("#FF6E88")),
        ]

        if compact_widget:
            left_x = rect.left() + 22
            tube_top = rect.top() + 26
            tube_bottom = rect.bottom() - 34
            tube_height = tube_bottom - tube_top
            tube_width = 20
            bulb_radius = 22

            tube_outer = QRectF(left_x, tube_top, tube_width, tube_height)
            tube_inner = tube_outer.adjusted(4, 4, -4, -4)
            bulb_rect = QRectF(
                left_x - bulb_radius + tube_width / 2,
                tube_bottom - 2,
                bulb_radius * 2,
                bulb_radius * 2,
            )

            painter.setPen(QPen(QColor(170, 225, 255, 62), 1.6))
            painter.setBrush(QColor(9, 24, 44, 214))
            painter.drawRoundedRect(tube_outer, tube_width / 2, tube_width / 2)
            painter.setBrush(QColor(9, 24, 44, 220))
            painter.drawEllipse(bulb_rect)

            for start_v, end_v, color in segments:
                start_ratio = self._segment_ratio(start_v)
                end_ratio = self._segment_ratio(end_v)
                y_start = tube_top + (tube_height * start_ratio)
                y_end = tube_top + (tube_height * end_ratio)
                seg_top = min(y_start, y_end)
                seg_bottom = max(y_start, y_end)
                band_rect = QRectF(
                    tube_inner.left(),
                    seg_top,
                    tube_inner.width(),
                    max(8.0, seg_bottom - seg_top),
                )
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawRoundedRect(band_rect, tube_inner.width() / 2, tube_inner.width() / 2)

            painter.setBrush(active_color)
            painter.drawEllipse(
                QRectF(
                    bulb_rect.left() + 6,
                    bulb_rect.top() + 6,
                    bulb_rect.width() - 12,
                    bulb_rect.height() - 12,
                )
            )

            tick_x1 = tube_outer.right() + 16
            tick_x2 = tick_x1 + 10
            text_x = tick_x2 + 8

            painter.setFont(QFont("Inter", 8, QFont.Weight.Medium))
            painter.setPen(QColor(206, 230, 246, 188))
            for tick in [33, 34, 35, 36, 37, 38, 39, 40, 41]:
                y = tube_top + tube_height * self._segment_ratio(float(tick))
                painter.drawLine(int(tick_x1), int(y), int(tick_x2), int(y))
                painter.drawText(
                    QRectF(text_x, y - 8, 30, 16),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    str(tick),
                )

            value_text = "--" if self._temp_c is None else f"{self._temp_c:.1f}°C"
            value_box_width = min(228.0, max(178.0, rect.width() * 0.26))
            value_box_height = 68.0
            value_box = QRectF(
                rect.right() - value_box_width - 8,
                rect.center().y() - value_box_height / 2,
                value_box_width,
                value_box_height,
            )

            bar_left = text_x + 34
            bar_right = value_box.left() - 20
            bar_width = max(160.0, bar_right - bar_left)
            bar_height = 14.0
            bar_rect = QRectF(bar_left, rect.center().y() - bar_height / 2 - 2, bar_width, bar_height)

            track_path = QPainterPath()
            track_path.addRoundedRect(bar_rect, bar_height / 2, bar_height / 2)
            painter.setPen(QPen(QColor(120, 208, 255, 54), 1))
            painter.setBrush(QColor(8, 22, 40, 210))
            painter.drawPath(track_path)

            painter.save()
            painter.setClipPath(track_path)
            for start_v, end_v, color in segments:
                x1 = bar_rect.left() + bar_rect.width() * self._value_to_ratio(float(start_v))
                x2 = bar_rect.left() + bar_rect.width() * self._value_to_ratio(float(end_v))
                seg_rect = QRectF(x1, bar_rect.top(), max(10.0, x2 - x1), bar_rect.height())
                fill = QColor(color)
                fill.setAlpha(165)
                painter.fillRect(seg_rect, fill)
            painter.restore()

            gloss_rect = QRectF(bar_rect.left() + 1, bar_rect.top() + 1, bar_rect.width() - 2, max(3.0, bar_rect.height() * 0.42))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 18))
            painter.drawRoundedRect(gloss_rect, bar_height / 2, bar_height / 2)

            if self._temp_c is not None:
                marker_ratio = self._value_to_ratio(self._temp_c)
                marker_x = bar_rect.left() + bar_rect.width() * marker_ratio
                marker_y = bar_rect.center().y()
                tube_marker_y = tube_top + tube_height * self._segment_ratio(self._temp_c)

                connector_pen = QPen(QColor(active_color.red(), active_color.green(), active_color.blue(), 225), 3)
                connector_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(connector_pen)
                painter.drawLine(int(tube_outer.right() + 10), int(tube_marker_y), int(bar_rect.left() - 10), int(marker_y))

                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(active_color.red(), active_color.green(), active_color.blue(), 255))
                painter.drawEllipse(QRectF(tube_outer.right() + 3, tube_marker_y - 8, 16, 16))
                painter.setBrush(QColor("#F6FCFF"))
                painter.drawEllipse(QRectF(tube_outer.right() + 7, tube_marker_y - 4, 8, 8))

                painter.setBrush(QColor(active_color.red(), active_color.green(), active_color.blue(), 255))
                painter.drawEllipse(QRectF(marker_x - 8, marker_y - 8, 16, 16))
                painter.setBrush(QColor("#F6FCFF"))
                painter.drawEllipse(QRectF(marker_x - 4, marker_y - 4, 8, 8))

            value_path = QPainterPath()
            value_path.addRoundedRect(value_box, 18.0, 18.0)
            painter.setPen(QPen(QColor(active_color.red(), active_color.green(), active_color.blue(), 105), 1.2))
            painter.setBrush(QColor(10, 28, 50, 224))
            painter.drawPath(value_path)

            value_gloss = QRectF(value_box.left() + 1, value_box.top() + 1, value_box.width() - 2, max(4.0, value_box.height() * 0.34))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 16))
            painter.drawRoundedRect(value_gloss, 18.0, 18.0)

            painter.setPen(QColor("#F6FCFF"))
            painter.setFont(QFont("Inter", 22, QFont.Weight.Bold))
            painter.drawText(
                QRectF(value_box.left(), value_box.top() + 8, value_box.width(), 28),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                value_text,
            )
            painter.setPen(QColor(active_color.red(), active_color.green(), active_color.blue(), 230))
            painter.setFont(QFont("Inter", 11, QFont.Weight.DemiBold))
            painter.drawText(
                QRectF(value_box.left(), value_box.top() + 38, value_box.width(), 18),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                self._label,
            )
        else:
            left_x = rect.left() + 38
            tube_top = rect.top() + 14
            tube_bottom = rect.bottom() - 48
            tube_height = tube_bottom - tube_top
            tube_width = 28
            bulb_radius = 24

            tube_outer = QRectF(left_x, tube_top, tube_width, tube_height)
            tube_inner = tube_outer.adjusted(6, 6, -6, -6)
            bulb_rect = QRectF(
                left_x - bulb_radius + tube_width / 2,
                tube_bottom - 4,
                bulb_radius * 2,
                bulb_radius * 2,
            )

            painter.setPen(QPen(QColor(170, 225, 255, 76), 2))
            painter.setBrush(QColor(10, 25, 46, 210))
            painter.drawRoundedRect(tube_outer, tube_width / 2, tube_width / 2)

            painter.setBrush(QColor(10, 25, 46, 215))
            painter.drawEllipse(bulb_rect)

            for start_v, end_v, color in segments:
                start_ratio = self._segment_ratio(start_v)
                end_ratio = self._segment_ratio(end_v)
                y_start = tube_top + (tube_height * start_ratio)
                y_end = tube_top + (tube_height * end_ratio)
                seg_top = min(y_start, y_end)
                seg_bottom = max(y_start, y_end)
                band_rect = QRectF(
                    tube_inner.left(),
                    seg_top,
                    tube_inner.width(),
                    max(8.0, seg_bottom - seg_top),
                )
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawRoundedRect(band_rect, tube_inner.width() / 2, tube_inner.width() / 2)

            painter.setBrush(active_color)
            painter.drawEllipse(QRectF(bulb_rect.left() + 6, bulb_rect.top() + 6, bulb_rect.width() - 12, bulb_rect.height() - 12))

            if self._temp_c is not None:
                ratio = self._segment_ratio(self._temp_c)
                marker_y = tube_top + tube_height * ratio
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(active_color.red(), active_color.green(), active_color.blue(), 245))
                painter.drawEllipse(QRectF(tube_outer.right() + 8, marker_y - 9, 18, 18))
                painter.setBrush(QColor("#F6FCFF"))
                painter.drawEllipse(QRectF(tube_outer.right() + 13, marker_y - 4, 8, 8))
                painter.setPen(QPen(QColor(active_color.red(), active_color.green(), active_color.blue(), 150), 3))
                painter.drawLine(int(tube_outer.right() + 2), int(marker_y), int(rect.right() - 36), int(marker_y))

            tick_x1 = tube_outer.right() + 20
            tick_x2 = tick_x1 + 10
            text_x = tick_x2 + 8
            painter.setFont(QFont("Inter", 8, QFont.Weight.Medium))
            painter.setPen(QColor(206, 230, 246, 180))
            for tick in [33, 34, 35, 36, 37, 38, 39, 40, 41]:
                y = tube_top + tube_height * self._segment_ratio(float(tick))
                painter.drawLine(int(tick_x1), int(y), int(tick_x2), int(y))
                painter.drawText(
                    QRectF(text_x, y - 8, 38, 16),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    str(tick),
                )

            value_text = "--" if self._temp_c is None else f"{self._temp_c:.1f}°C"
            title_font = QFont("Inter", 22, QFont.Weight.Bold)
            subtitle_font = QFont("Inter", 10, QFont.Weight.DemiBold)
            right_text_rect = QRectF(rect.center().x() - 20, rect.top() + 42, rect.width() * 0.46, 140)
            painter.setPen(QColor("#F5FCFF"))
            painter.setFont(title_font)
            painter.drawText(
                right_text_rect,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                value_text,
            )
            painter.setPen(QColor(194, 232, 255, 220))
            painter.setFont(subtitle_font)
            painter.drawText(
                QRectF(right_text_rect.left(), right_text_rect.top() + 44, right_text_rect.width(), 22),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                self._label,
            )
            painter.setPen(QColor(183, 214, 233, 180))
            painter.setFont(QFont("Inter", 8, QFont.Weight.Medium))
            painter.drawText(
                QRectF(right_text_rect.left(), right_text_rect.top() + 78, right_text_rect.width(), 18),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                "Reference body-temperature scale",
            )

        painter.end()



class _InfoStatCard(QFrame):
    """
    Small premium stat card for temperature detail metrics.
    """

    def __init__(
        self,
        title: str,
        *,
        value: str = "--",
        subtitle: str = "",
        accent_hex: str = "#39D8FF",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self._accent_hex = accent_hex

        self.setObjectName("TemperatureInfoStatCard")
        self.setMinimumHeight(88)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(3)

        self.title_label = QLabel(title, self)
        self.value_label = QLabel(value, self)
        self.subtitle_label = QLabel(subtitle, self)
        self.subtitle_label.setWordWrap(True)

        root.addWidget(self.title_label)
        root.addWidget(self.value_label)
        root.addWidget(self.subtitle_label)
        root.addStretch(1)

        self._apply_style()

    def set_payload(self, *, value: str, subtitle: str, accent_hex: str) -> None:
        self._accent_hex = safe_str(accent_hex, "#39D8FF").strip() or "#39D8FF"
        self.value_label.setText(safe_str(value, "--").strip() or "--")
        clean_subtitle = safe_str(subtitle, "").strip()
        self.subtitle_label.setText(clean_subtitle)
        self.subtitle_label.setVisible(bool(clean_subtitle))
        self._apply_style()

    def _apply_style(self) -> None:
        accent = QColor(self._accent_hex)

        self.setStyleSheet(
            f"""
            QFrame#TemperatureInfoStatCard {{
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.20);
                border-radius: 18px;
                background: rgba(12, 31, 56, 0.90);
            }}
            """
        )
        self.title_label.setStyleSheet(
            """
            QLabel {
                color: rgba(219, 237, 249, 0.82);
                font-size: 10px;
                font-weight: 700;
                background: transparent;
            }
            """
        )
        self.value_label.setStyleSheet(
            """
            QLabel {
                color: #F6FCFF;
                font-size: 20px;
                font-weight: 900;
                background: transparent;
            }
            """
        )
        self.subtitle_label.setStyleSheet(
            """
            QLabel {
                color: rgba(191, 214, 232, 0.80);
                font-size: 9px;
                font-weight: 500;
                background: transparent;
            }
            """
        )


class _RangeBandCard(QFrame):
    """
    Premium temperature range band card with selectable highlight.
    """

    def __init__(
        self,
        title: str,
        range_text: str,
        *,
        accent_hex: str = "#39D8FF",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self._accent_hex = accent_hex
        self._active = False

        self.setObjectName("TemperatureRangeBandCard")
        self.setMinimumHeight(72)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(2)

        self.title_label = QLabel(title, self)
        self.range_label = QLabel(range_text, self)

        root.addWidget(self.title_label)
        root.addWidget(self.range_label)
        root.addStretch(1)

        self._apply_style()

    def set_active(self, active: bool, accent_hex: str) -> None:
        self._active = bool(active)
        self._accent_hex = safe_str(accent_hex, "#39D8FF").strip() or "#39D8FF"
        self._apply_style()

    def _apply_style(self) -> None:
        accent = QColor(self._accent_hex)
        border_alpha = 0.38 if self._active else 0.18
        fill_alpha = 0.18 if self._active else 0.07

        self.setStyleSheet(
            f"""
            QFrame#TemperatureRangeBandCard {{
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, {border_alpha:.3f});
                border-radius: 18px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, {fill_alpha:.3f});
            }}
            """
        )
        self.title_label.setStyleSheet(
            """
            QLabel {
                color: #F3FCFF;
                font-size: 10px;
                font-weight: 800;
                background: transparent;
            }
            """
        )
        self.range_label.setStyleSheet(
            """
            QLabel {
                color: rgba(205, 231, 246, 0.86);
                font-size: 9px;
                font-weight: 600;
                background: transparent;
            }
            """
        )


class _SummaryCard(QFrame):
    """
    Premium detail summary card.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._accent_hex = "#39D8FF"

        self.setObjectName("TemperatureSummaryCard")
        self.setMinimumHeight(214)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(8)

        top_row = QWidget(self)
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        self.title_label = QLabel("Temperature Interpretation", top_row)
        self.state_chip = QLabel("Pending", top_row)

        top_layout.addWidget(self.title_label)
        top_layout.addStretch(1)
        top_layout.addWidget(self.state_chip)

        self.summary_label = QLabel(
            "Temperature detail summary will appear here when a valid measurement is available.",
            self,
        )
        self.summary_label.setWordWrap(True)

        self.line_1 = QLabel("• Temperature bands help classify the current reading.", self)
        self.line_2 = QLabel("• The highlighted band shows the active status.", self)
        self.line_3 = QLabel("• Recommendations are supportive guidance, not a diagnosis.", self)
        self.line_4 = QLabel("• Final interpretation should consider symptoms and the full health context.", self)

        root.addWidget(top_row)
        root.addWidget(self.summary_label)
        root.addWidget(self.line_1)
        root.addWidget(self.line_2)
        root.addWidget(self.line_3)
        root.addWidget(self.line_4)
        root.addStretch(1)

        self._apply_style()

    def set_payload(
        self,
        *,
        title: str,
        state_text: str,
        summary: str,
        lines: Mapping[int, str],
        accent_hex: str,
    ) -> None:
        self._accent_hex = safe_str(accent_hex, "#39D8FF").strip() or "#39D8FF"
        self.title_label.setText(safe_str(title, "Temperature Interpretation").strip() or "Temperature Interpretation")
        self.state_chip.setText(safe_str(state_text, "Pending").strip() or "Pending")
        self.summary_label.setText(safe_str(summary, "").strip())

        self.line_1.setText(f"• {safe_str(lines.get(1), '').strip()}" if safe_str(lines.get(1), "").strip() else "")
        self.line_2.setText(f"• {safe_str(lines.get(2), '').strip()}" if safe_str(lines.get(2), "").strip() else "")
        self.line_3.setText(f"• {safe_str(lines.get(3), '').strip()}" if safe_str(lines.get(3), "").strip() else "")
        self.line_4.setText(f"• {safe_str(lines.get(4), '').strip()}" if safe_str(lines.get(4), "").strip() else "")

        self.line_1.setVisible(bool(safe_str(lines.get(1), "").strip()))
        self.line_2.setVisible(bool(safe_str(lines.get(2), "").strip()))
        self.line_3.setVisible(bool(safe_str(lines.get(3), "").strip()))
        self.line_4.setVisible(bool(safe_str(lines.get(4), "").strip()))

        self._apply_style()

    def _apply_style(self) -> None:
        accent = QColor(self._accent_hex)

        self.setStyleSheet(
            f"""
            QFrame#TemperatureSummaryCard {{
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.22);
                border-radius: 22px;
                background: rgba(12, 31, 56, 0.90);
            }}
            """
        )

        self.title_label.setStyleSheet(
            """
            QLabel {
                color: #F4FCFF;
                font-size: 12px;
                font-weight: 800;
                background: transparent;
            }
            """
        )

        self.state_chip.setStyleSheet(
            f"""
            QLabel {{
                color: #F4FCFF;
                font-size: 9px;
                font-weight: 800;
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.34);
                border-radius: 12px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.16);
                padding: 4px 9px;
            }}
            """
        )

        self.summary_label.setStyleSheet(
            """
            QLabel {
                color: rgba(221, 239, 250, 0.90);
                font-size: 10px;
                font-weight: 600;
                background: transparent;
            }
            """
        )

        bullet_style = """
            QLabel {
                color: rgba(197, 223, 241, 0.84);
                font-size: 9px;
                font-weight: 500;
                background: transparent;
            }
        """
        self.line_1.setStyleSheet(bullet_style)
        self.line_2.setStyleSheet(bullet_style)
        self.line_3.setStyleSheet(bullet_style)
        self.line_4.setStyleSheet(bullet_style)


# =============================================================================
# Main screen
# =============================================================================

class TemperatureDetailScreen(QFrame):
    """
    Premium temperature detail screen.

    Main responsibilities:
    - load temperature value from active runtime session
    - normalize into Celsius when needed
    - interpret temperature against threshold profiles
    - present a patient-facing premium detail screen
    """

    back_requested = pyqtSignal()
    qr_requested = pyqtSignal()
    consult_requested = pyqtSignal()
    detail_loaded = pyqtSignal(dict)
    detail_refreshed = pyqtSignal(dict)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        navigator: Optional[object] = None,
        app_state: Optional[object] = None,
        services: Optional[Mapping[str, Any]] = None,
        animation_manager: Optional[object] = None,
        theme_manager: Optional[object] = None,
    ) -> None:
        super().__init__(parent)

        self._logger = logger.bind(component="TemperatureDetailScreen")

        self.navigator = navigator
        self.app_state = app_state
        self.services = dict(services or {})
        self.animation_manager = animation_manager
        self.theme_manager = theme_manager

        self._payload: Dict[str, Any] = {}
        self._measurements: Dict[str, Any] = {}
        self._thresholds: Dict[str, float] = _normalize_temperature_thresholds(None)
        self._insight: Dict[str, Any] = {}
        self._status_message = "Temperature detail view is ready to load."

        self._is_compact = bool(IS_COMPACT_KIOSK or KIOSK_WIDTH <= 840 or KIOSK_HEIGHT <= 500)
        self._is_ultra_compact = bool(KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480)

        self._background_path = _resolve_asset("backgrounds/temperature_detail_bg.png")
        self._logo_small_path = _resolve_asset("logos/cst_logo_small.png")
        self._scale_overlay_path = _resolve_asset("detail_graphics/thermometer_scale.png")

        self._background_pixmap = _pixmap_or_empty(self._background_path)
        self._logo_pixmap = _pixmap_or_empty(self._logo_small_path)

        self.setObjectName("TemperatureDetailScreen")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._build_ui()
        self._setup_effects()
        self._apply_styles()
        self._update_compact_layout()

    # =========================================================================
    # UI
    # =========================================================================

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(9)

        # ---------------------------------------------------------------------
        # Top bar
        # ---------------------------------------------------------------------
        self.top_bar = QWidget(self)
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        self.back_button = self._create_button("Back", variant="secondary", min_width=96, parent=self.top_bar)
        self.back_button.clicked.connect(self._handle_back_clicked)

        self.logo_badge = QLabel(self.top_bar)
        self.logo_badge.setObjectName("LogoBadge")
        self.logo_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_label_pixmap(self.logo_badge, self._logo_pixmap, 26)

        self.top_title = QLabel("Temperature Detail", self.top_bar)
        self.top_title.setObjectName("TopTitle")

        self.category_pill = QLabel("Category", self.top_bar)
        self.category_pill.setObjectName("RuntimePill")

        self.value_pill = QLabel("Temp --", self.top_bar)
        self.value_pill.setObjectName("RuntimePill")

        self.status_pill = QLabel("Ready", self.top_bar)
        self.status_pill.setObjectName("RuntimePill")

        top_layout.addWidget(self.back_button)
        top_layout.addWidget(self.logo_badge)
        top_layout.addWidget(self.top_title)
        top_layout.addStretch(1)
        top_layout.addWidget(self.category_pill)
        top_layout.addWidget(self.value_pill)
        top_layout.addWidget(self.status_pill)

        # ---------------------------------------------------------------------
        # Header card
        # ---------------------------------------------------------------------
        self.header_card = QFrame(self)
        self.header_card.setObjectName("TemperatureHeaderCard")

        header_layout = QVBoxLayout(self.header_card)
        header_layout.setContentsMargins(14, 12, 14, 12)
        header_layout.setSpacing(6)

        if _HAS_GLOW_LABEL:
            self.hero_title = GlowLabel(
                role=getattr(GlowLabel, "ROLE_TITLE", getattr(GlowLabel, "ROLE_STATUS", 0)),
                align_center=True,
                use_outline=False,
                enable_paint_glow=True,
                initial_glow_strength=0.48,
                initial_glow_blur=18,
            )
        else:
            self.hero_title = QLabel(self.header_card)
            self.hero_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.hero_subtitle = QLabel(self.header_card)
        self.hero_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hero_subtitle.setWordWrap(True)

        self.header_chip_row = QWidget(self.header_card)
        chip_layout = QHBoxLayout(self.header_chip_row)
        chip_layout.setContentsMargins(0, 0, 0, 0)
        chip_layout.setSpacing(8)

        self.metric_chip = QLabel("Core Vital Sign", self.header_chip_row)
        self.metric_chip.setObjectName("HeaderChip")

        self.range_chip = QLabel("Reference Bands", self.header_chip_row)
        self.range_chip.setObjectName("HeaderChip")

        self.guidance_chip = QLabel("Supportive Guidance", self.header_chip_row)
        self.guidance_chip.setObjectName("HeaderChip")

        chip_layout.addStretch(1)
        chip_layout.addWidget(self.metric_chip)
        chip_layout.addWidget(self.range_chip)
        chip_layout.addWidget(self.guidance_chip)
        chip_layout.addStretch(1)

        self.summary_banner = QLabel(
            "Body temperature is a core vital sign used to flag low, normal, fever, and high-fever states within the kiosk interpretation workflow.",
            self.header_card,
        )
        self.summary_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.summary_banner.setWordWrap(True)

        header_layout.addWidget(self.hero_title)
        header_layout.addWidget(self.hero_subtitle)
        header_layout.addWidget(self.header_chip_row)
        header_layout.addWidget(self.summary_banner)

        # ---------------------------------------------------------------------
        # Stats row
        # ---------------------------------------------------------------------
        self.stats_row = QWidget(self)
        stats_layout = QHBoxLayout(self.stats_row)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(8)

        self.stat_temp = _InfoStatCard("Temperature", value="--", subtitle="Current normalized body temperature.")
        self.stat_range = _InfoStatCard("Healthy Band", value="--", subtitle="Preferred reference range used by the kiosk.")
        self.stat_alert = _InfoStatCard("Alert Zone", value="--", subtitle="Higher-risk threshold band.")
        self.stat_status = _InfoStatCard("Status", value="--", subtitle="Current interpretation category.")

        stats_layout.addWidget(self.stat_temp, 1)
        stats_layout.addWidget(self.stat_range, 1)
        stats_layout.addWidget(self.stat_alert, 1)
        stats_layout.addWidget(self.stat_status, 1)

        # ---------------------------------------------------------------------
        # Content row
        # ---------------------------------------------------------------------
        self.content_row = QWidget(self)
        content_layout = QHBoxLayout(self.content_row)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)

        # Left visual panel
        self.visual_panel = QFrame(self.content_row)
        self.visual_panel.setObjectName("VisualPanel")
        self.visual_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        visual_layout = QVBoxLayout(self.visual_panel)
        visual_layout.setContentsMargins(12, 10, 12, 10)
        visual_layout.setSpacing(8)

        self.visual_title = QLabel("Thermometer Scale and Range Bands", self.visual_panel)
        self.visual_title.setObjectName("SectionTitle")

        self.scale_widget = _TemperatureScaleFallbackWidget(self._scale_overlay_path, self.visual_panel)

        self.range_row_top = QWidget(self.visual_panel)
        self.range_top_layout = QHBoxLayout(self.range_row_top)
        self.range_top_layout.setContentsMargins(0, 0, 0, 0)
        self.range_top_layout.setSpacing(8)

        self.band_low = _RangeBandCard("Below Normal", f"{TEMP_WARNING_LOW:.1f} – {TEMP_NORMAL_LOW:.1f}°C")
        self.band_normal = _RangeBandCard("Healthy", f"{TEMP_NORMAL_LOW:.1f} – {TEMP_NORMAL_HIGH:.1f}°C")
        self.band_fever = _RangeBandCard("Fever", f"{TEMP_NORMAL_HIGH:.1f} – {TEMP_WARNING_HIGH:.1f}°C")

        self.range_top_layout.addWidget(self.band_low)
        self.range_top_layout.addWidget(self.band_normal)
        self.range_top_layout.addWidget(self.band_fever)

        self.range_row_bottom = QWidget(self.visual_panel)
        self.range_bottom_layout = QHBoxLayout(self.range_row_bottom)
        self.range_bottom_layout.setContentsMargins(0, 0, 0, 0)
        self.range_bottom_layout.setSpacing(8)

        self.band_hypo = _RangeBandCard("Hypothermia", f"< {TEMP_WARNING_LOW:.1f}°C")
        self.band_high_fever = _RangeBandCard("High Fever", f"≥ {TEMP_WARNING_HIGH:.1f}°C")

        self.range_bottom_layout.addWidget(self.band_hypo)
        self.range_bottom_layout.addWidget(self.band_high_fever)

        visual_layout.addWidget(self.visual_title)
        visual_layout.addWidget(self.scale_widget, 1)
        visual_layout.addWidget(self.range_row_top)
        visual_layout.addWidget(self.range_row_bottom)

        # Right insight panel
        self.side_panel = QWidget(self.content_row)
        side_layout = QVBoxLayout(self.side_panel)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(9)
        self.side_panel.setMinimumWidth(262)
        self.side_panel.setMaximumWidth(300)

        self.summary_card = _SummaryCard(self.side_panel)

        self.context_card = QFrame(self.side_panel)
        self.context_card.setObjectName("InfoCard")

        context_layout = QVBoxLayout(self.context_card)
        context_layout.setContentsMargins(12, 10, 12, 10)
        context_layout.setSpacing(6)

        self.context_title = QLabel("Measurement Context", self.context_card)
        self.context_title.setObjectName("SectionTitle")

        self.context_line_1 = QLabel("Preferred unit: Celsius", self.context_card)
        self.context_line_2 = QLabel("Scale normalization: active", self.context_card)
        self.context_line_3 = QLabel("Threshold source: pending", self.context_card)
        self.context_line_4 = QLabel("Status: pending", self.context_card)

        self.context_note = QLabel(
            "Temperature is only one part of the overall health picture. Symptoms, timing, environment, and other vital signs should also be considered.",
            self.context_card,
        )
        self.context_note.setWordWrap(True)

        context_layout.addWidget(self.context_title)
        context_layout.addWidget(self.context_line_1)
        context_layout.addWidget(self.context_line_2)
        context_layout.addWidget(self.context_line_3)
        context_layout.addWidget(self.context_line_4)
        context_layout.addWidget(self.context_note)

        self.quick_card = QFrame(self.side_panel)
        self.quick_card.setObjectName("InfoCard")

        quick_layout = QVBoxLayout(self.quick_card)
        quick_layout.setContentsMargins(12, 10, 12, 10)
        quick_layout.setSpacing(6)

        self.quick_title = QLabel("Next Actions", self.quick_card)
        self.quick_title.setObjectName("SectionTitle")

        self.quick_text = QLabel(
            "Return to the results dashboard, continue to QR handoff, or open the consult flow for a broader interpretation path.",
            self.quick_card,
        )
        self.quick_text.setWordWrap(True)

        self.refresh_button = self._create_button("Refresh Detail", variant="ghost", min_width=168, parent=self.quick_card)
        self.refresh_button.clicked.connect(self._handle_refresh_clicked)

        self.qr_button = self._create_button("Open QR Handoff", variant="secondary", min_width=168, parent=self.quick_card)
        self.qr_button.clicked.connect(self._handle_qr_clicked)

        self.consult_button = self._create_button("Open Consult", variant="primary", min_width=168, parent=self.quick_card)
        self.consult_button.clicked.connect(self._handle_consult_clicked)

        quick_layout.addWidget(self.quick_title)
        quick_layout.addWidget(self.quick_text)
        quick_layout.addWidget(self.refresh_button)
        quick_layout.addWidget(self.qr_button)
        quick_layout.addWidget(self.consult_button)

        side_layout.addWidget(self.summary_card)
        side_layout.addWidget(self.context_card)
        side_layout.addWidget(self.quick_card)

        content_layout.addWidget(self.visual_panel, 1)
        content_layout.addWidget(self.side_panel, 0)

        # ---------------------------------------------------------------------
        # Bottom action row
        # ---------------------------------------------------------------------
        self.action_row = QWidget(self)
        action_layout = QHBoxLayout(self.action_row)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(10)

        self.bottom_back_button = self._create_button("Back To Results", variant="secondary", min_width=160, parent=self.action_row)
        self.bottom_back_button.clicked.connect(self._handle_back_clicked)

        self.bottom_refresh_button = self._create_button("Refresh", variant="ghost", min_width=120, parent=self.action_row)
        self.bottom_refresh_button.clicked.connect(self._handle_refresh_clicked)

        self.bottom_qr_button = self._create_button("QR", variant="secondary", min_width=120, parent=self.action_row)
        self.bottom_qr_button.clicked.connect(self._handle_qr_clicked)

        self.bottom_consult_button = self._create_button("Consult", variant="primary", min_width=140, parent=self.action_row)
        self.bottom_consult_button.clicked.connect(self._handle_consult_clicked)

        action_layout.addWidget(self.bottom_back_button)
        action_layout.addStretch(1)
        action_layout.addWidget(self.bottom_refresh_button)
        action_layout.addWidget(self.bottom_qr_button)
        action_layout.addWidget(self.bottom_consult_button)

        root.addWidget(self.top_bar)
        root.addWidget(self.header_card)
        root.addWidget(self.stats_row)
        root.addWidget(self.content_row, 1)
        root.addWidget(self.action_row)

    def _create_button(self, text: str, *, variant: str, min_width: int, parent: QWidget) -> QWidget:
        if AnimatedButton is not None:
            try:
                variant_map = {
                    "primary": getattr(AnimatedButton, "VARIANT_PRIMARY", None),
                    "secondary": getattr(AnimatedButton, "VARIANT_SECONDARY", None),
                    "ghost": getattr(AnimatedButton, "VARIANT_GHOST", None),
                    "success": getattr(AnimatedButton, "VARIANT_SUCCESS", None),
                }
                btn = AnimatedButton(
                    text=text,
                    variant=variant_map.get(variant),
                    size=getattr(AnimatedButton, "SIZE_MD", None),
                    minimum_width=min_width,
                )
                return btn
            except Exception:
                pass

        button = QPushButton(text, parent)
        button.setMinimumWidth(min_width)
        button.setMinimumHeight(40)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            """
            QPushButton {
                color: #F6FCFF;
                border: 1px solid rgba(157, 220, 255, 0.26);
                border-radius: 14px;
                padding: 10px 16px;
                font-size: 12px;
                font-weight: 700;
                background: rgba(22, 47, 82, 0.78);
            }
            QPushButton:hover {
                background: rgba(34, 66, 110, 0.90);
                border-color: rgba(186, 233, 255, 0.40);
            }
            QPushButton:disabled {
                color: rgba(220, 236, 246, 0.48);
                background: rgba(20, 38, 62, 0.55);
            }
            """
        )
        return button

    def _set_label_pixmap(self, label: QLabel, pixmap: QPixmap, target_height: int) -> None:
        if pixmap.isNull():
            label.clear()
            return

        scaled = pixmap.scaledToHeight(
            target_height,
            Qt.TransformationMode.SmoothTransformation,
        )
        label.setPixmap(scaled)

    # =========================================================================
    # Effects / styles
    # =========================================================================

    def _setup_effects(self) -> None:
        self.header_opacity = QGraphicsOpacityEffect(self.header_card)
        self.header_card.setGraphicsEffect(self.header_opacity)
        self.header_opacity.setOpacity(0.0)

        self.stats_opacity = QGraphicsOpacityEffect(self.stats_row)
        self.stats_row.setGraphicsEffect(self.stats_opacity)
        self.stats_opacity.setOpacity(0.0)

        self.content_opacity = QGraphicsOpacityEffect(self.content_row)
        self.content_row.setGraphicsEffect(self.content_opacity)
        self.content_opacity.setOpacity(0.0)

        self.entry_group = QParallelAnimationGroup(self)

        self.header_fade = QPropertyAnimation(self.header_opacity, b"opacity", self)
        self.header_fade.setDuration(320)
        self.header_fade.setStartValue(0.0)
        self.header_fade.setEndValue(1.0)
        self.header_fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.stats_fade = QPropertyAnimation(self.stats_opacity, b"opacity", self)
        self.stats_fade.setDuration(420)
        self.stats_fade.setStartValue(0.0)
        self.stats_fade.setEndValue(1.0)
        self.stats_fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.content_fade = QPropertyAnimation(self.content_opacity, b"opacity", self)
        self.content_fade.setDuration(540)
        self.content_fade.setStartValue(0.0)
        self.content_fade.setEndValue(1.0)
        self.content_fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.entry_group.addAnimation(self.header_fade)
        self.entry_group.addAnimation(self.stats_fade)
        self.entry_group.addAnimation(self.content_fade)

        visual_shadow = QGraphicsDropShadowEffect(self.visual_panel)
        visual_shadow.setBlurRadius(26)
        visual_shadow.setOffset(0, 6)
        shadow_color = QColor("#39D8FF")
        shadow_color.setAlpha(60)
        visual_shadow.setColor(shadow_color)
        self.visual_panel.setGraphicsEffect(visual_shadow)

        if _HAS_GLOW_LABEL and isinstance(self.hero_title, GlowLabel):
            try:
                self.hero_title.set_glow_color("#43D9FF")
                self.hero_title.set_text_color("#F5FCFF")
            except Exception:
                pass

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QFrame#TemperatureDetailScreen {
                background: transparent;
            }

            QLabel#LogoBadge {
                min-width: 42px;
                max-width: 42px;
                min-height: 42px;
                max-height: 42px;
                border-radius: 14px;
                border: 1px solid rgba(157, 220, 255, 0.18);
                background: rgba(18, 39, 70, 0.58);
            }

            QLabel#TopTitle {
                color: #F6FCFF;
                font-size: 15px;
                font-weight: 900;
                background: transparent;
            }

            QLabel#RuntimePill {
                color: #EEF9FF;
                font-size: 10px;
                font-weight: 700;
                border: 1px solid rgba(157, 220, 255, 0.22);
                border-radius: 14px;
                background: rgba(18, 39, 70, 0.56);
                padding: 6px 10px;
            }

            QFrame#TemperatureHeaderCard {
                border: 1px solid rgba(170, 230, 255, 0.20);
                border-radius: 22px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(16, 34, 60, 0.80),
                    stop:1 rgba(8, 22, 44, 0.88)
                );
            }

            QLabel#HeaderChip {
                color: #EEF9FF;
                font-size: 9px;
                font-weight: 800;
                border: 1px solid rgba(157, 220, 255, 0.22);
                border-radius: 12px;
                background: rgba(28, 56, 91, 0.42);
                padding: 4px 9px;
            }

            QFrame#VisualPanel, QFrame#InfoCard {
                border: 1px solid rgba(170, 230, 255, 0.20);
                border-radius: 22px;
                background: rgba(12, 28, 50, 0.74);
            }

            QLabel#SectionTitle {
                color: #F4FCFF;
                font-size: 12px;
                font-weight: 800;
                background: transparent;
            }
            """
        )

        if _HAS_GLOW_LABEL and isinstance(self.hero_title, GlowLabel):
            try:
                self.hero_title.set_text("Body Temperature Detail")
            except Exception:
                self.hero_title.setText("Body Temperature Detail")
        else:
            self.hero_title.setText("Body Temperature Detail")

        self.hero_subtitle.setText(
            "Reference ranges and quick guidance for the active temperature reading."
        )
        self.summary_banner.setText(
            "This screen shows the current reading, the reference range, and the recommended next step."
        )

        self.hero_title.setStyleSheet(
            """
            QLabel {
                color: #F6FCFF;
                font-size: 24px;
                font-weight: 900;
                background: transparent;
            }
            """
        )

        self.hero_subtitle.setStyleSheet(
            """
            QLabel {
                color: rgba(219, 237, 249, 0.90);
                font-size: 11px;
                font-weight: 500;
                background: transparent;
            }
            """
        )

        self.summary_banner.setStyleSheet(
            """
            QLabel {
                color: rgba(207, 229, 244, 0.88);
                font-size: 10px;
                font-weight: 600;
                background: transparent;
            }
            """
        )

        context_style = """
            QLabel {
                color: rgba(214, 235, 248, 0.86);
                font-size: 10px;
                font-weight: 500;
                background: transparent;
            }
        """
        self.context_line_1.setStyleSheet(context_style)
        self.context_line_2.setStyleSheet(context_style)
        self.context_line_3.setStyleSheet(context_style)
        self.context_line_4.setStyleSheet(context_style)
        self.context_note.setStyleSheet(context_style)
        self.quick_text.setStyleSheet(context_style)

        self._set_button_accent(self.refresh_button, "#39D8FF")
        self._set_button_accent(self.bottom_refresh_button, "#39D8FF")
        self._set_button_accent(self.qr_button, "#67D8FF")
        self._set_button_accent(self.bottom_qr_button, "#67D8FF")
        self._set_button_accent(self.consult_button, "#42E393")
        self._set_button_accent(self.bottom_consult_button, "#42E393")
        self._set_button_accent(self.back_button, "#39D8FF")
        self._set_button_accent(self.bottom_back_button, "#39D8FF")

    def _play_entry_animation(self) -> None:
        try:
            self.entry_group.start()
        except Exception:
            pass

    # =========================================================================
    # Lifecycle
    # =========================================================================

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._play_entry_animation()
        self.reload_detail()

    # =========================================================================
    # Loading
    # =========================================================================

    def reload_detail(self) -> None:
        snapshot = self._load_detail_snapshot()

        self._payload = deepcopy(snapshot["payload"])
        self._measurements = deepcopy(snapshot["measurements"])
        self._thresholds = deepcopy(snapshot["thresholds"])
        self._insight = deepcopy(snapshot["insight"])
        self._status_message = safe_str(snapshot.get("status_message"), "Temperature detail loaded.").strip()

        self._apply_snapshot_to_ui()
        self._queue_scale_refresh()
        self.detail_loaded.emit(self.diagnostics())
        self.detail_refreshed.emit(self.diagnostics())

    def _load_detail_snapshot(self) -> Dict[str, Any]:
        payload = self._read_session_payload()
        measurements = self._normalize_measurements(payload)
        thresholds = self._read_temperature_thresholds()

        temperature_c = measurements.get(METRIC_TEMPERATURE)
        insight = _build_temperature_interpretation(
            temperature_c if isinstance(temperature_c, (float, int)) else None,
            thresholds,
        )

        diagnosis_item = self._read_temperature_diagnosis_item(payload)
        if diagnosis_item:
            merged = dict(insight)
            merged["label"] = safe_str(diagnosis_item.get("label"), merged["label"]).strip() or merged["label"]
            merged["severity"] = safe_str(diagnosis_item.get("severity"), merged["severity"]).strip().lower() or merged["severity"]
            merged["summary"] = safe_str(diagnosis_item.get("summary"), merged["summary"]).strip() or merged["summary"]
            merged["detail"] = safe_str(diagnosis_item.get("detail"), merged["detail"]).strip() or merged["detail"]
            merged["recommendation"] = safe_str(
                diagnosis_item.get("recommendation"),
                merged["recommendation"],
            ).strip() or merged["recommendation"]
            merged["accent_hex"] = _accent_for_state(merged["severity"])
            insight = merged

        return {
            "payload": payload,
            "measurements": measurements,
            "thresholds": thresholds,
            "insight": insight,
            "status_message": "Temperature detail snapshot loaded from active session data.",
        }

    def _read_session_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}

        try:
            session_service = self.services.get("session_service") or self.services.get("session")
            if session_service is not None:
                for method_name in (
                    "get_results_payload",
                    "get_current_session",
                    "get_session_payload",
                    "current_session_payload",
                    "get_latest_results_payload",
                    "snapshot",
                    "get_snapshot",
                ):
                    method = getattr(session_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method()
                            if isinstance(raw, Mapping):
                                payload = dict(raw)
                                if payload:
                                    break
                        except Exception:
                            continue
        except Exception:
            pass

        if not payload:
            try:
                if self.app_state is not None:
                    for attr_name in ("results_payload", "current_session_payload", "session_payload", "consult_payload"):
                        attr = getattr(self.app_state, attr_name, None)
                        if isinstance(attr, Mapping):
                            payload = dict(attr)
                            if payload:
                                break
            except Exception:
                pass

        return payload

    def _normalize_measurements(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        raw_measurements = payload.get("measurements", {})
        if not isinstance(raw_measurements, Mapping):
            raw_measurements = {}

        raw_temp = raw_measurements.get(
            METRIC_TEMPERATURE,
            raw_measurements.get("temp", raw_measurements.get("body_temperature", payload.get("temperature"))),
        )

        return {
            METRIC_TEMPERATURE: _normalize_temperature_celsius(raw_temp),
        }

    def _read_temperature_thresholds(self) -> Dict[str, float]:
        thresholds: Optional[Mapping[str, Any]] = None

        try:
            threshold_service = self.services.get("threshold_service") or self.services.get("thresholds")
            if threshold_service is not None:
                for method_name in (
                    "get_profiles",
                    "load_profiles",
                    "get_thresholds",
                    "snapshot",
                    "get_snapshot",
                ):
                    method = getattr(threshold_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method()
                            if isinstance(raw, Mapping):
                                if METRIC_TEMPERATURE in raw and isinstance(raw.get(METRIC_TEMPERATURE), Mapping):
                                    thresholds = raw.get(METRIC_TEMPERATURE)  # type: ignore[assignment]
                                    break
                                profiles = raw.get("profiles", {})
                                if isinstance(profiles, Mapping) and METRIC_TEMPERATURE in profiles and isinstance(profiles.get(METRIC_TEMPERATURE), Mapping):
                                    thresholds = profiles.get(METRIC_TEMPERATURE)  # type: ignore[assignment]
                                    break
                        except Exception:
                            continue
        except Exception:
            pass

        if thresholds is None:
            try:
                rules_service = self.services.get("health_rules_service") or self.services.get("health_rules")
                if rules_service is not None:
                    for method_name in ("get_profiles", "snapshot", "get_snapshot"):
                        method = getattr(rules_service, method_name, None)
                        if callable(method):
                            try:
                                raw = method()
                                if isinstance(raw, Mapping):
                                    if METRIC_TEMPERATURE in raw and isinstance(raw.get(METRIC_TEMPERATURE), Mapping):
                                        thresholds = raw.get(METRIC_TEMPERATURE)  # type: ignore[assignment]
                                        break
                                    profiles = raw.get("profiles", {})
                                    if isinstance(profiles, Mapping) and METRIC_TEMPERATURE in profiles and isinstance(profiles.get(METRIC_TEMPERATURE), Mapping):
                                        thresholds = profiles.get(METRIC_TEMPERATURE)  # type: ignore[assignment]
                                        break
                            except Exception:
                                continue
            except Exception:
                pass

        if thresholds is None:
            try:
                import config as project_config  # local import on purpose

                for attr_name in ("DEFAULT_THRESHOLD_PROFILES", "THRESHOLD_PROFILES"):
                    if hasattr(project_config, attr_name):
                        raw = getattr(project_config, attr_name)
                        if isinstance(raw, Mapping) and METRIC_TEMPERATURE in raw and isinstance(raw.get(METRIC_TEMPERATURE), Mapping):
                            thresholds = raw.get(METRIC_TEMPERATURE)  # type: ignore[assignment]
                            break
            except Exception:
                pass

        if thresholds is None:
            try:
                if self.app_state is not None:
                    for attr_name in ("threshold_profiles", "parameter_profiles", "health_rule_profiles"):
                        if hasattr(self.app_state, attr_name):
                            raw = getattr(self.app_state, attr_name)
                            if isinstance(raw, Mapping) and METRIC_TEMPERATURE in raw and isinstance(raw.get(METRIC_TEMPERATURE), Mapping):
                                thresholds = raw.get(METRIC_TEMPERATURE)  # type: ignore[assignment]
                                break
            except Exception:
                pass

        return _normalize_temperature_thresholds(thresholds)

    def _read_temperature_diagnosis_item(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        raw_classes = payload.get("classifications", {})
        if isinstance(raw_classes, Mapping):
            raw_temp = raw_classes.get(METRIC_TEMPERATURE)
            if isinstance(raw_temp, Mapping):
                return dict(raw_temp)

        try:
            diagnosis_service = self.services.get("diagnosis_service") or self.services.get("diagnosis")
            if diagnosis_service is not None:
                for method_name in ("get_diagnosis", "snapshot", "get_snapshot", "evaluate_payload", "run_diagnosis"):
                    method = getattr(diagnosis_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method(dict(payload))
                        except TypeError:
                            try:
                                raw = method()
                            except Exception:
                                continue
                        except Exception:
                            continue

                        if isinstance(raw, Mapping):
                            classifications = raw.get("classifications", raw.get("metrics", {}))
                            if isinstance(classifications, Mapping):
                                item = classifications.get(METRIC_TEMPERATURE)
                                if isinstance(item, Mapping):
                                    return dict(item)
            return {}
        except Exception:
            return {}

    # =========================================================================
    # UI binding
    # =========================================================================

    def _apply_snapshot_to_ui(self) -> None:
        temperature_c = self._measurements.get(METRIC_TEMPERATURE)
        severity = safe_str(self._insight.get("severity"), "unknown").strip().lower()
        label = safe_str(self._insight.get("label"), "Temperature").strip() or "Temperature"
        accent_hex = safe_str(self._insight.get("accent_hex"), _accent_for_state(severity)).strip() or _accent_for_state(severity)

        compact_now = bool(self._is_compact or self.width() <= 860 or self.height() <= 520)
        ultra_now = bool(self._is_ultra_compact or self.width() <= 800 or self.height() <= 480)
        value_text = _format_num(temperature_c, 1, "°C")

        # header copy
        if compact_now:
            self.hero_title.setText("Temperature Detail")
            self.hero_subtitle.setText("Clean overview of the current temperature reading and band.")
            self.summary_banner.setText(
                f"Current reading {value_text} • Status: {label} • Normal band: {self._thresholds['normal_low']:.1f}–{self._thresholds['normal_high']:.1f}°C"
            )
        else:
            self.hero_title.setText("Body Temperature Detail")
            self.hero_subtitle.setText(
                "Reference ranges and quick guidance for the active temperature reading."
            )
            self.summary_banner.setText(
                safe_str(self._insight.get("summary"), "").strip()
                or "This screen shows the current reading, the reference range, and the recommended next step."
            )

        # pills
        self.category_pill.setText(label)
        self._apply_pill_style(self.category_pill, accent_hex)

        self.value_pill.setText(f"Temperature {value_text}")
        self._apply_pill_style(self.value_pill, "#67D8FF")

        status_text = "Healthy" if severity in {"normal", "healthy"} else (severity.title() if severity else "Ready")
        self.status_pill.setText(status_text)
        self._apply_pill_style(self.status_pill, accent_hex)

        # chips
        self._apply_header_chip_style(self.metric_chip, "#67D8FF")
        self._apply_header_chip_style(self.range_chip, accent_hex)
        self._apply_header_chip_style(self.guidance_chip, "#39D8FF")

        # stats
        stat_temp_subtitle = "" if compact_now else "Current normalized temperature used by the kiosk."
        stat_range_subtitle = "" if compact_now else "Preferred reference band used for normal status."
        stat_alert_subtitle = "" if compact_now else "Higher-risk fever band requiring stronger attention."
        stat_status_subtitle = "" if compact_now else safe_str(self._insight.get("summary"), "").strip()

        self.stat_temp.set_payload(
            value=value_text,
            subtitle=stat_temp_subtitle,
            accent_hex=accent_hex,
        )
        self.stat_range.set_payload(
            value=f"{self._thresholds['normal_low']:.1f}–{self._thresholds['normal_high']:.1f}°C",
            subtitle=stat_range_subtitle,
            accent_hex="#42E393",
        )
        self.stat_alert.set_payload(
            value=f"≥ {self._thresholds['warning_high']:.1f}°C",
            subtitle=stat_alert_subtitle,
            accent_hex="#FFA14D",
        )
        self.stat_status.set_payload(
            value=label,
            subtitle=stat_status_subtitle,
            accent_hex=accent_hex,
        )

        # scale
        self.visual_title.setText("Temperature Scale" if compact_now else "Thermometer Scale and Range Bands")

        self.scale_widget.set_payload(
            temperature_c=None if temperature_c in (None, "") else safe_float(temperature_c, 0.0),
            label=label,
            thresholds=self._thresholds,
            accent_hex=accent_hex,
        )

        # range highlights
        active_band = safe_str(self._insight.get("active_band"), "").strip().lower()
        self.band_hypo.set_active(active_band == "very_low", "#FF6E88")
        self.band_low.set_active(active_band == "low", "#FFD25E")
        self.band_normal.set_active(active_band == "normal", "#42E393")
        self.band_fever.set_active(active_band == "high", "#FFA14D")
        self.band_high_fever.set_active(active_band == "very_high", "#FF6E88")

        # summary
        if compact_now:
            lines = {
                1: f"Current reading: {value_text}.",
                2: f"Recommendation: {safe_str(self._insight.get('recommendation'), '').strip()}",
                3: "",
                4: "",
            }
        else:
            lines = {
                1: f"Current reading: {value_text}.",
                2: safe_str(self._insight.get("detail"), "").strip(),
                3: f"Recommendation: {safe_str(self._insight.get('recommendation'), '').strip()}",
                4: (
                    f"Reference bands: low < {self._thresholds['warning_low']:.1f}, "
                    f"healthy {self._thresholds['normal_low']:.1f}–{self._thresholds['normal_high']:.1f}, "
                    f"fever {self._thresholds['normal_high']:.1f}–{self._thresholds['warning_high']:.1f}, "
                    f"high ≥ {self._thresholds['warning_high']:.1f}."
                ),
            }

        self.summary_card.set_payload(
            title="Temperature Interpretation",
            state_text=label,
            summary=safe_str(self._insight.get("summary"), "").strip() or "Temperature summary unavailable.",
            lines=lines,
            accent_hex=accent_hex,
        )

        # context
        self.context_line_1.setText("Preferred unit: Celsius")
        self.context_line_2.setText(
            "Automatic normalization is active for Fahrenheit-style inputs."
            if not compact_now
            else "Automatic normalization is active."
        )
        self.context_line_3.setText(
            f"Healthy band: {self._thresholds['normal_low']:.1f}–{self._thresholds['normal_high']:.1f}°C"
        )
        self.context_line_4.setText(
            f"Alert threshold: ≥ {self._thresholds['warning_high']:.1f}°C" if compact_now else f"Status: {self._status_message}"
        )
        self.context_note.setText(
            "Temperature should be reviewed together with symptoms and other vital signs."
        )

        self.context_line_3.setVisible(True)
        self.context_line_4.setVisible(not ultra_now)

        self.quick_text.setText(
            "Open QR or consult for the next step."
            if compact_now
            else "Return to the results dashboard, continue to QR handoff, or open the consult flow for a broader interpretation path."
        )

        # buttons
        self._set_button_accent(self.refresh_button, "#39D8FF")
        self._set_button_accent(self.bottom_refresh_button, "#39D8FF")
        self._set_button_accent(self.qr_button, "#67D8FF")
        self._set_button_accent(self.bottom_qr_button, "#67D8FF")
        self._set_button_accent(self.consult_button, accent_hex if severity in {"warning", "critical"} else "#42E393")
        self._set_button_accent(self.bottom_consult_button, accent_hex if severity in {"warning", "critical"} else "#42E393")

    # =========================================================================
    # Navigation / actions

    def _handle_back_clicked(self) -> None:
        if self._navigate_to(SCREEN_RESULTS):
            return
        self.back_requested.emit()

    def _handle_refresh_clicked(self) -> None:
        """
        Compact refresh handler.

        Uses queued repaint requests instead of synchronous repaint calls.
        This prevents the temperature scale widget from colliding with an
        active paint cycle, which was causing the blank visual panel after
        pressing Refresh.
        """
        self.reload_detail()
        try:
            self._update_compact_layout()
        except Exception:
            pass
        self._queue_scale_refresh()

    def _queue_scale_refresh(self) -> None:
        try:
            QTimer.singleShot(0, self._refresh_scale_visual)
        except Exception:
            self._refresh_scale_visual()

    def _refresh_scale_visual(self) -> None:
        try:
            self.scale_widget.update()
        except Exception:
            pass
        try:
            self.visual_panel.update()
        except Exception:
            pass
        try:
            self.update()
        except Exception:
            pass

    def _handle_qr_clicked(self) -> None:
        if self._navigate_to(SCREEN_QR):
            return
        self.qr_requested.emit()

    def _handle_consult_clicked(self) -> None:
        if self._navigate_to(SCREEN_CONSULT):
            return
        self.consult_requested.emit()

    def _navigate_to(self, screen_name: str) -> bool:
        navigator = self.navigator
        if navigator is None:
            return False

        for method_name in ("go_to", "navigate_to", "navigate", "show_screen", "set_current_screen"):
            method = getattr(navigator, method_name, None)
            if callable(method):
                try:
                    method(screen_name)
                    return True
                except Exception:
                    continue
        return False

    # =========================================================================
    # Styling helpers
    # =========================================================================

    def _apply_pill_style(self, label: QLabel, accent_hex: str) -> None:
        accent = QColor(accent_hex)
        label.setStyleSheet(
            f"""
            QLabel {{
                color: #EEF9FF;
                font-size: 10px;
                font-weight: 700;
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.34);
                border-radius: 14px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.15);
                padding: 6px 10px;
            }}
            """
        )

    def _apply_header_chip_style(self, label: QLabel, accent_hex: str) -> None:
        accent = QColor(accent_hex)
        label.setStyleSheet(
            f"""
            QLabel {{
                color: #EEF9FF;
                font-size: 9px;
                font-weight: 800;
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.34);
                border-radius: 12px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.16);
                padding: 4px 9px;
            }}
            """
        )

    def _set_button_accent(self, button: QWidget, accent_hex: str) -> None:
        if AnimatedButton is not None and hasattr(button, "set_accent_color"):
            try:
                button.set_accent_color(accent_hex)  # type: ignore[attr-defined]
                return
            except Exception:
                pass

        if isinstance(button, QPushButton):
            accent = QColor(accent_hex)
            button.setStyleSheet(
                f"""
                QPushButton {{
                    color: #F6FCFF;
                    border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.34);
                    border-radius: 14px;
                    padding: 10px 16px;
                    font-size: 12px;
                    font-weight: 700;
                    background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.16);
                }}
                QPushButton:hover {{
                    background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.24);
                    border-color: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.48);
                }}
                QPushButton:disabled {{
                    color: rgba(220, 236, 246, 0.48);
                    background: rgba(20, 38, 62, 0.55);
                }}
                """
            )


    # =========================================================================
    # Responsive layout
    # =========================================================================

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_compact_layout()

    def _update_compact_layout(self) -> None:
        width = max(1, self.width() or KIOSK_WIDTH)
        height = max(1, self.height() or KIOSK_HEIGHT)

        compact = bool(self._is_compact or width <= 860 or height <= 520)
        ultra = bool(self._is_ultra_compact or width <= 800 or height <= 480)

        self.layout().setContentsMargins(14 if compact else 18, 10 if compact else 14, 14 if compact else 18, 10 if compact else 14)
        self.layout().setSpacing(8 if compact else 11)

        if hasattr(self, 'header_card'):
            self.header_card.layout().setContentsMargins(12 if compact else 16, 10 if compact else 14, 12 if compact else 16, 10 if compact else 14)
            self.header_card.layout().setSpacing(5 if compact else 7)

        if hasattr(self, 'stats_row'):
            self.stats_row.layout().setSpacing(6 if compact else 9)

        if hasattr(self, 'content_row'):
            self.content_row.layout().setSpacing(8 if compact else 12)

        if hasattr(self, 'visual_panel'):
            self.visual_panel.layout().setContentsMargins(10 if compact else 14, 9 if compact else 12, 10 if compact else 14, 9 if compact else 12)
            self.visual_panel.layout().setSpacing(7 if compact else 9)

        if hasattr(self, 'side_panel'):
            self.side_panel.layout().setSpacing(8 if compact else 10)
            self.side_panel.setMinimumWidth(250 if ultra else (268 if compact else 300))
            self.side_panel.setMaximumWidth(286 if ultra else (304 if compact else 350))
            self.side_panel.setVisible(not compact)

        self.scale_widget.setMinimumHeight(176 if ultra else (208 if compact else 250))
        self.summary_card.setMinimumHeight(128 if ultra else (148 if compact else 214))
        self.context_card.setMinimumHeight(84 if ultra else (98 if compact else 156))
        self.quick_card.setMinimumHeight(92 if ultra else (106 if compact else 158))

        self.stat_temp.setMinimumHeight(74 if compact else 82)
        self.stat_range.setMinimumHeight(74 if compact else 82)
        self.stat_alert.setMinimumHeight(74 if compact else 82)
        self.stat_status.setMinimumHeight(74 if compact else 82)

        self.hero_title.setText('Temperature Detail' if compact else 'Body Temperature Detail')
        self.top_title.setText('Temperature Detail')
        self.hero_subtitle.setVisible(not compact)
        self.summary_banner.setVisible(True)
        self.header_chip_row.setVisible(not compact)
        self.quick_text.setVisible(not compact)
        self.context_note.setVisible(not compact)
        self.logo_badge.setVisible(not ultra)
        self.range_row_top.setVisible(not compact)
        self.range_row_bottom.setVisible(not compact)

        self.bottom_back_button.setText('Results')
        self.refresh_button.setText('Refresh')
        self.qr_button.setText('Open QR')
        self.consult_button.setText('Consult')

        self.back_button.setMinimumWidth(88 if compact else 96)
        for btn in (
            self.refresh_button,
            self.qr_button,
            self.consult_button,
            self.bottom_back_button,
            self.bottom_refresh_button,
            self.bottom_qr_button,
            self.bottom_consult_button,
        ):
            try:
                btn.setMinimumHeight(34 if compact else 38)
            except Exception:
                pass

        self.range_top_layout.setSpacing(6 if ultra else 8)
        self.range_bottom_layout.setSpacing(6 if ultra else 8)

        self._apply_compact_styles(compact=compact, ultra=ultra)

    def _apply_compact_styles(self, *, compact: bool, ultra: bool) -> None:
        top_title_px = 13 if compact else 15
        pill_px = 9 if compact else 10
        section_px = 11 if compact else 12
        hero_px = 19 if ultra else (21 if compact else 24)
        body_px = 9 if ultra else (10 if compact else 11)

        self.top_title.setStyleSheet(
            f"""
            QLabel {{
                color: #F6FCFF;
                font-size: {top_title_px}px;
                font-weight: 900;
                background: transparent;
            }}
            """
        )

        self.hero_title.setStyleSheet(
            f"""
            QLabel {{
                color: #F6FCFF;
                font-size: {hero_px}px;
                font-weight: 900;
                background: transparent;
            }}
            """
        )

        self.hero_subtitle.setStyleSheet(
            f"""
            QLabel {{
                color: rgba(219, 237, 249, 0.90);
                font-size: {body_px}px;
                font-weight: 500;
                background: transparent;
            }}
            """
        )
        self.summary_banner.setStyleSheet(
            f"""
            QLabel {{
                color: rgba(207, 229, 244, 0.88);
                font-size: {max(8, body_px-1)}px;
                font-weight: 600;
                background: transparent;
            }}
            """
        )
        self.visual_title.setStyleSheet(
            f"""QLabel {{ color: #F4FCFF; font-size: {section_px}px; font-weight: 800; background: transparent; }}"""
        )
        self.context_title.setStyleSheet(
            f"""QLabel {{ color: #F4FCFF; font-size: {section_px}px; font-weight: 800; background: transparent; }}"""
        )
        self.quick_title.setStyleSheet(
            f"""QLabel {{ color: #F4FCFF; font-size: {section_px}px; font-weight: 800; background: transparent; }}"""
        )

        context_style = f"""
            QLabel {{
                color: rgba(214, 235, 248, 0.86);
                font-size: {body_px}px;
                font-weight: 500;
                background: transparent;
            }}
        """
        self.context_line_1.setStyleSheet(context_style)
        self.context_line_2.setStyleSheet(context_style)
        self.context_line_3.setStyleSheet(context_style)
        self.context_line_4.setStyleSheet(context_style)
        self.context_note.setStyleSheet(context_style)
        self.quick_text.setStyleSheet(context_style)

        pill_style = f"""
            QLabel {{
                color: #EEF9FF;
                font-size: {pill_px}px;
                font-weight: 700;
                border: 1px solid rgba(157, 220, 255, 0.22);
                border-radius: 13px;
                background: rgba(18, 39, 70, 0.56);
                padding: {4 if compact else 6}px {8 if compact else 10}px;
            }}
        """
        for chip in (self.category_pill, self.value_pill, self.status_pill):
            chip.setStyleSheet(pill_style)

        header_chip_style = f"""
            QLabel {{
                color: #EEF9FF;
                font-size: {max(8, pill_px-1)}px;
                font-weight: 800;
                border: 1px solid rgba(157, 220, 255, 0.22);
                border-radius: 11px;
                background: rgba(28, 56, 91, 0.42);
                padding: {3 if compact else 4}px {7 if compact else 9}px;
            }}
        """
        for chip in (self.metric_chip, self.range_chip, self.guidance_chip):
            chip.setStyleSheet(header_chip_style)

    # =========================================================================
    # Paint
    # =========================================================================

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect = self.rect()

        if not self._background_pixmap.isNull():
            scaled = self._background_pixmap.scaled(
                rect.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            draw_x = int((rect.width() - scaled.width()) / 2)
            draw_y = int((rect.height() - scaled.height()) / 2)
            painter.drawPixmap(draw_x, draw_y, scaled)

        painter.fillRect(rect, QColor(4, 14, 28, 176))
        painter.fillRect(QRectF(0, 0, rect.width(), rect.height() * 0.38), QColor(53, 214, 255, 16))
        painter.fillRect(QRectF(0, rect.height() * 0.60, rect.width(), rect.height() * 0.40), QColor(20, 82, 128, 18))

        painter.end()

    # =========================================================================
    # Diagnostics
    # =========================================================================

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "payload": deepcopy(self._payload),
            "measurements": deepcopy(self._measurements),
            "thresholds": deepcopy(self._thresholds),
            "insight": deepcopy(self._insight),
            "status_message": self._status_message,
            "background_path": self._background_path,
            "logo_path": self._logo_small_path,
            "scale_overlay_path": self._scale_overlay_path,
        }