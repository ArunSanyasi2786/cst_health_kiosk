"""
screens/bmi_detail_screen.py

Premium BMI detail screen for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the public-facing BMI explanation screen opened from:
    - screens/results_screen.py
- It allows the user or operator to:
    - inspect the current BMI value in a premium detailed view
    - understand the category and severity of the BMI result
    - review the weight and height values used for BMI calculation
    - see the BMI range bands in a polished medical-kiosk style
    - navigate back to results or continue to QR / consult workflows
- It is designed specifically for:
    - Raspberry Pi 4B touchscreen kiosk deployment
    - 1024x600 kiosk resolution
    - laptop demo mode
- It provides:
    - glossy futuristic blue medical UI
    - resilient loading from session_service / diagnosis_service / threshold_service
    - threshold-aware BMI interpretation
    - derived BMI computation when only height and weight are available
    - safe fallback behavior when services are still being integrated
    - maintainable self-contained drawing logic for the BMI gauge

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
- widgets/bmi_gauge_widget.py

Navigation targets this screen is designed to link to:
- screens/results_screen.py
- screens/qr_screen.py
- screens/consult_screen.py

Design goals:
- glossy futuristic blue medical UI
- informative but calm patient-facing detail screen
- strong readability at 1024x600
- premium radial BMI gauge with active-category highlighting
- resilient integration while backend files continue evolving
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QRectF,
    Qt,
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
    from core.utils import safe_bool, safe_float, safe_int, safe_str
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

    def safe_bool(value: Any, default: bool = False) -> bool:
        try:
            if isinstance(value, bool):
                return value
            if value is None:
                return default
            text = str(value).strip().lower()
            if text in {"1", "true", "yes", "y", "on"}:
                return True
            if text in {"0", "false", "no", "n", "off"}:
                return False
            return default
        except Exception:
            return default

try:
    from core.constants import (
        SCREEN_RESULTS,
        SCREEN_QR,
        SCREEN_CONSULT,
        METRIC_BMI,
        METRIC_WEIGHT,
        METRIC_HEIGHT,
    )
except Exception:  # pragma: no cover
    SCREEN_RESULTS = "results"
    SCREEN_QR = "qr"
    SCREEN_CONSULT = "consult"
    METRIC_BMI = "bmi"
    METRIC_WEIGHT = "weight"
    METRIC_HEIGHT = "height"

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

BMI_LOW_CRITICAL = 16.0
BMI_NORMAL_LOW = 18.5
BMI_NORMAL_HIGH = 24.9
BMI_WARNING_HIGH = 30.0
BMI_GAUGE_MIN = 10.0
BMI_GAUGE_MAX = 40.0


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
        text = f"{num:.{decimals}f}"
        return f"{text}{suffix}"
    except Exception:
        return "--"


def _format_height_cm(height_value: Any) -> Optional[float]:
    if height_value in (None, ""):
        return None

    raw = safe_float(height_value, 0.0)
    if raw <= 0:
        return None

    # meters -> cm
    if 0 < raw < 3.5:
        return round(raw * 100.0, 1)

    # mm -> cm
    if raw > 300.0:
        return round(raw / 10.0, 1)

    # already cm
    return round(raw, 1)


def _compute_bmi(weight_kg: Any, height_any: Any) -> Optional[float]:
    if weight_kg in (None, "") or height_any in (None, ""):
        return None

    weight = safe_float(weight_kg, 0.0)
    height_cm = _format_height_cm(height_any)

    if weight <= 0 or height_cm is None or height_cm <= 0:
        return None

    height_m = height_cm / 100.0
    if height_m <= 0:
        return None

    bmi = weight / (height_m * height_m)
    if bmi <= 0:
        return None

    return round(bmi, 1)


def _accent_for_state(state: str) -> str:
    text = safe_str(state, "").strip().lower()
    if text in {"critical", "obese", "severely underweight"}:
        return "#FF6E88"
    if text in {"warning", "overweight"}:
        return "#FFA14D"
    if text in {"attention", "underweight"}:
        return "#FFD25E"
    if text in {"normal", "healthy"}:
        return "#42E393"
    return "#39D8FF"


def _normalize_bmi_thresholds(raw: Optional[Mapping[str, Any]]) -> Dict[str, float]:
    base = {
        "warning_low": BMI_LOW_CRITICAL,
        "normal_low": BMI_NORMAL_LOW,
        "normal_high": BMI_NORMAL_HIGH,
        "warning_high": BMI_WARNING_HIGH,
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


def _build_bmi_interpretation(
    bmi_value: Optional[float],
    thresholds: Mapping[str, float],
) -> Dict[str, Any]:
    if bmi_value is None:
        return {
            "label": "Unavailable",
            "severity": "unknown",
            "summary": "BMI could not be calculated because the required weight or height data is missing.",
            "detail": "BMI needs both weight and height values. Please complete or repeat the anthropometric measurement step.",
            "recommendation": "Capture a valid weight and height reading before relying on this detail view.",
            "active_band": "unknown",
            "accent_hex": "#39D8FF",
        }

    low_critical = safe_float(thresholds.get("warning_low"), BMI_LOW_CRITICAL)
    normal_low = safe_float(thresholds.get("normal_low"), BMI_NORMAL_LOW)
    normal_high = safe_float(thresholds.get("normal_high"), BMI_NORMAL_HIGH)
    high_warning = safe_float(thresholds.get("warning_high"), BMI_WARNING_HIGH)

    if bmi_value < low_critical:
        return {
            "label": "Severely Underweight",
            "severity": "critical",
            "summary": "The BMI is far below the healthy reference band.",
            "detail": "A severely low BMI can indicate nutritional or health concerns and should not be ignored.",
            "recommendation": "Professional evaluation is strongly recommended, especially if there are symptoms, weakness, or unexpected weight loss.",
            "active_band": "very_low",
            "accent_hex": _accent_for_state("critical"),
        }

    if bmi_value < normal_low:
        return {
            "label": "Underweight",
            "severity": "attention",
            "summary": "The BMI is below the healthy reference range.",
            "detail": "This result suggests lower-than-preferred body mass relative to height.",
            "recommendation": "Review diet, recent weight trend, and context. Follow-up may be helpful depending on the broader health picture.",
            "active_band": "low",
            "accent_hex": _accent_for_state("attention"),
        }

    if bmi_value <= normal_high:
        return {
            "label": "Healthy",
            "severity": "normal",
            "summary": "The BMI falls within the commonly accepted healthy reference range.",
            "detail": "This result is generally reassuring when interpreted alongside the full health profile.",
            "recommendation": "Maintain balanced nutrition, activity, and routine health monitoring habits.",
            "active_band": "normal",
            "accent_hex": _accent_for_state("normal"),
        }

    if bmi_value < high_warning:
        return {
            "label": "Overweight",
            "severity": "warning",
            "summary": "The BMI is above the healthy reference range.",
            "detail": "This result indicates increased body mass relative to height and may benefit from lifestyle review.",
            "recommendation": "Consider activity, nutrition, and long-term weight trend. Preventive follow-up may be useful.",
            "active_band": "high",
            "accent_hex": _accent_for_state("warning"),
        }

    return {
        "label": "Obesity",
        "severity": "critical",
        "summary": "The BMI is significantly above the healthy reference range.",
        "detail": "This result may be associated with increased long-term health risk and deserves proper follow-up.",
        "recommendation": "Professional consultation is advisable for a broader assessment and next-step guidance.",
        "active_band": "very_high",
        "accent_hex": _accent_for_state("critical"),
    }


# =============================================================================
# Internal widgets
# =============================================================================

class _BmiGaugeFallbackWidget(QWidget):
    """
    Self-contained premium fallback BMI gauge.

    The widget draws:
    - multi-band semicircular gauge
    - glowing indicator needle
    - center BMI value and category
    - faint optional overlay from detail_graphics/bmi_gauge.png
    """

    def __init__(self, overlay_path: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._overlay_pixmap = _pixmap_or_empty(overlay_path)
        self._bmi_value: Optional[float] = None
        self._thresholds = _normalize_bmi_thresholds(None)
        self._label = "BMI"
        self._accent_hex = "#39D8FF"

        self.setMinimumHeight(250)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_payload(
        self,
        *,
        bmi_value: Optional[float],
        label: str,
        thresholds: Mapping[str, float],
        accent_hex: str,
    ) -> None:
        self._bmi_value = bmi_value
        self._label = safe_str(label, "BMI").strip() or "BMI"
        self._thresholds = _normalize_bmi_thresholds(thresholds)
        self._accent_hex = safe_str(accent_hex, "#39D8FF").strip() or "#39D8FF"
        self.update()

    def _value_to_ratio(self, value: float) -> float:
        clamped = max(BMI_GAUGE_MIN, min(BMI_GAUGE_MAX, float(value)))
        return (clamped - BMI_GAUGE_MIN) / (BMI_GAUGE_MAX - BMI_GAUGE_MIN)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect = self.rect().adjusted(8, 8, -8, -8)
        center_x = rect.center().x()
        center_y = rect.bottom() - 22
        radius = min(rect.width() * 0.43, rect.height() * 0.62)

        # Optional overlay
        if not self._overlay_pixmap.isNull():
            overlay = self._overlay_pixmap.scaled(
                rect.width(),
                rect.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.setOpacity(0.12)
            painter.drawPixmap(
                int(rect.center().x() - overlay.width() / 2),
                int(rect.center().y() - overlay.height() / 2) - 8,
                overlay,
            )
            painter.setOpacity(1.0)

        # Background arcs
        arc_rect = QRectF(center_x - radius, center_y - radius, radius * 2, radius * 2)

        band_pen_width = max(16, int(radius * 0.12))

        # Qt uses 1/16 degree units, 0 at 3 o'clock, positive counterclockwise.
        # We use a 240-degree gauge from 210° to -30°.
        start_deg = 210.0
        span_deg = -240.0

        def map_value(v: float) -> float:
            ratio = self._value_to_ratio(v)
            return start_deg + (span_deg * ratio)

        segments = [
            (BMI_GAUGE_MIN, self._thresholds["warning_low"], QColor("#FF6E88")),
            (self._thresholds["warning_low"], self._thresholds["normal_low"], QColor("#FFD25E")),
            (self._thresholds["normal_low"], self._thresholds["normal_high"], QColor("#42E393")),
            (self._thresholds["normal_high"], self._thresholds["warning_high"], QColor("#FFA14D")),
            (self._thresholds["warning_high"], BMI_GAUGE_MAX, QColor("#FF6E88")),
        ]

        background_pen = QPen(QColor(36, 76, 118, 90), band_pen_width)
        background_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(background_pen)
        painter.drawArc(arc_rect, int(start_deg * 16), int(span_deg * 16))

        for start_v, end_v, color in segments:
            s_deg = map_value(start_v)
            e_deg = map_value(end_v)
            band_pen = QPen(color, band_pen_width)
            band_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(band_pen)
            painter.drawArc(arc_rect, int(s_deg * 16), int((e_deg - s_deg) * 16))

        # Inner subtle ring
        inner_pen = QPen(QColor(195, 233, 255, 46), 2)
        painter.setPen(inner_pen)
        painter.drawArc(arc_rect.adjusted(18, 18, -18, -18), int(start_deg * 16), int(span_deg * 16))

        # Needle / pointer
        if self._bmi_value is not None:
            value_angle_deg = map_value(self._bmi_value)
            angle_rad = (value_angle_deg / 180.0) * 3.141592653589793
            tip_radius = radius - band_pen_width * 0.40
            tip_x = center_x + tip_radius * __import__("math").cos(angle_rad)
            tip_y = center_y - tip_radius * __import__("math").sin(angle_rad)

            painter.setPen(Qt.PenStyle.NoPen)
            glow_color = QColor(self._accent_hex)
            glow_color.setAlpha(70)
            painter.setBrush(glow_color)
            painter.drawEllipse(QRectF(tip_x - 10, tip_y - 10, 20, 20))

            painter.setBrush(QColor("#F7FCFF"))
            painter.drawEllipse(QRectF(tip_x - 5.6, tip_y - 5.6, 11.2, 11.2))

            needle_pen = QPen(QColor("#E9FAFF"), 3)
            needle_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(needle_pen)
            painter.drawLine(
                int(center_x),
                int(center_y),
                int(tip_x),
                int(tip_y),
            )

        # Center hub
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(12, 28, 52, 225))
        painter.drawEllipse(QRectF(center_x - 52, center_y - 52, 104, 104))
        painter.setBrush(QColor(67, 217, 255, 34))
        painter.drawEllipse(QRectF(center_x - 42, center_y - 42, 84, 84))

        # Center text
        value_text = "--" if self._bmi_value is None else f"{self._bmi_value:.1f}"
        title_font = QFont("Inter", 22, QFont.Weight.Bold)
        label_font = QFont("Inter", 10, QFont.Weight.DemiBold)

        painter.setPen(QColor("#F5FCFF"))
        painter.setFont(title_font)
        painter.drawText(
            QRectF(center_x - 60, center_y - 28, 120, 30),
            Qt.AlignmentFlag.AlignCenter,
            value_text,
        )

        painter.setPen(QColor(195, 233, 255, 215))
        painter.setFont(label_font)
        painter.drawText(
            QRectF(center_x - 82, center_y + 2, 164, 22),
            Qt.AlignmentFlag.AlignCenter,
            self._label,
        )

        # Band labels
        painter.setFont(QFont("Inter", 8, QFont.Weight.Medium))
        painter.setPen(QColor(205, 231, 246, 190))
        painter.drawText(QRectF(rect.left() + 8, rect.bottom() - 60, 90, 18), Qt.AlignmentFlag.AlignLeft, "Under")
        painter.drawText(QRectF(center_x - 42, rect.top() + 24, 84, 18), Qt.AlignmentFlag.AlignCenter, "Healthy")
        painter.drawText(QRectF(rect.right() - 98, rect.bottom() - 60, 90, 18), Qt.AlignmentFlag.AlignRight, "High")

        painter.end()


class _InfoStatCard(QFrame):
    """
    Small premium stat card for BMI detail metrics.
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

        self.setObjectName("BmiInfoStatCard")
        self.setMinimumHeight(88)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(3)

        self.title_label = QLabel(title, self)
        self.value_label = QLabel(value, self)
        self.subtitle_label = QLabel(subtitle, self)
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setVisible(bool(safe_str(subtitle, '').strip()))

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
            QFrame#BmiInfoStatCard {{
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.20);
                border-radius: 18px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.08);
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
    Premium BMI range band card with selectable highlight.
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

        self.setObjectName("BmiRangeBandCard")
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
            QFrame#BmiRangeBandCard {{
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

        self.setObjectName("BmiSummaryCard")
        self.setMinimumHeight(214)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(8)

        top_row = QWidget(self)
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        self.title_label = QLabel("BMI Interpretation", top_row)
        self.state_chip = QLabel("Pending", top_row)

        top_layout.addWidget(self.title_label)
        top_layout.addStretch(1)
        top_layout.addWidget(self.state_chip)

        self.summary_label = QLabel(
            "BMI detail summary will appear here when a valid measurement is available.",
            self,
        )
        self.summary_label.setWordWrap(True)

        self.line_1 = QLabel("• Weight and height are used to compute BMI.", self)
        self.line_2 = QLabel("• The highlighted band shows the current category.", self)
        self.line_3 = QLabel("• Recommendations are provided as supportive guidance.", self)
        self.line_4 = QLabel("• Final interpretation should consider the broader health context.", self)

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
        self.title_label.setText(safe_str(title, "BMI Interpretation").strip() or "BMI Interpretation")
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
            QFrame#BmiSummaryCard {{
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.22);
                border-radius: 22px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.08);
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

class BmiDetailScreen(QFrame):
    """
    Premium BMI detail screen.

    Main responsibilities:
    - load weight / height / BMI values from active runtime session
    - compute BMI if not explicitly present
    - interpret BMI against threshold profiles
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

        self._logger = logger.bind(component="BmiDetailScreen")

        self.navigator = navigator
        self.app_state = app_state
        self.services = dict(services or {})
        self.animation_manager = animation_manager
        self.theme_manager = theme_manager

        self._payload: Dict[str, Any] = {}
        self._measurements: Dict[str, Any] = {}
        self._thresholds: Dict[str, float] = _normalize_bmi_thresholds(None)
        self._insight: Dict[str, Any] = {}
        self._status_message = "BMI detail view is ready to load."

        self._is_compact = bool(IS_COMPACT_KIOSK or KIOSK_WIDTH <= 840 or KIOSK_HEIGHT <= 500)
        self._is_ultra_compact = bool(KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480)

        self._background_path = _resolve_asset("backgrounds/bmi_detail_bg.png")
        self._logo_small_path = _resolve_asset("logos/cst_logo_small.png")
        self._gauge_overlay_path = _resolve_asset("detail_graphics/bmi_gauge.png")

        self._background_pixmap = _pixmap_or_empty(self._background_path)
        self._logo_pixmap = _pixmap_or_empty(self._logo_small_path)

        self.setObjectName("BmiDetailScreen")
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

        self.top_title = QLabel("BMI Detail", self.top_bar)
        self.top_title.setObjectName("TopTitle")

        self.category_pill = QLabel("Category", self.top_bar)
        self.category_pill.setObjectName("RuntimePill")

        self.value_pill = QLabel("BMI --", self.top_bar)
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
        self.header_card.setObjectName("BmiHeaderCard")

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

        self.derived_chip = QLabel("Derived Metric", self.header_chip_row)
        self.derived_chip.setObjectName("HeaderChip")

        self.range_chip = QLabel("Reference Bands", self.header_chip_row)
        self.range_chip.setObjectName("HeaderChip")

        self.guidance_chip = QLabel("Supportive Guidance", self.header_chip_row)
        self.guidance_chip.setObjectName("HeaderChip")

        chip_layout.addStretch(1)
        chip_layout.addWidget(self.derived_chip)
        chip_layout.addWidget(self.range_chip)
        chip_layout.addWidget(self.guidance_chip)
        chip_layout.addStretch(1)

        self.summary_banner = QLabel(
            "BMI is calculated from weight and height and helps place body mass into reference categories used for supportive health interpretation.",
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

        self.stat_weight = _InfoStatCard("Weight", value="--", subtitle="Weight used for BMI calculation.")
        self.stat_height = _InfoStatCard("Height", value="--", subtitle="Height used for BMI calculation.")
        self.stat_bmi = _InfoStatCard("BMI", value="--", subtitle="Derived body mass index value.")
        self.stat_severity = _InfoStatCard("Status", value="--", subtitle="Current BMI category severity.")

        stats_layout.addWidget(self.stat_weight, 1)
        stats_layout.addWidget(self.stat_height, 1)
        stats_layout.addWidget(self.stat_bmi, 1)
        stats_layout.addWidget(self.stat_severity, 1)

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

        self.visual_title = QLabel("BMI Gauge and Range Bands", self.visual_panel)
        self.visual_title.setObjectName("SectionTitle")

        self.gauge_widget = _BmiGaugeFallbackWidget(self._gauge_overlay_path, self.visual_panel)

        self.range_row_top = QWidget(self.visual_panel)
        self.range_top_layout = QHBoxLayout(self.range_row_top)
        self.range_top_layout.setContentsMargins(0, 0, 0, 0)
        self.range_top_layout.setSpacing(8)

        self.band_under = _RangeBandCard("Underweight", f"< {BMI_NORMAL_LOW:.1f}")
        self.band_normal = _RangeBandCard("Healthy", f"{BMI_NORMAL_LOW:.1f} – {BMI_NORMAL_HIGH:.1f}")
        self.band_over = _RangeBandCard("Overweight", f"{BMI_NORMAL_HIGH:.1f} – {BMI_WARNING_HIGH:.1f}")

        self.range_top_layout.addWidget(self.band_under)
        self.range_top_layout.addWidget(self.band_normal)
        self.range_top_layout.addWidget(self.band_over)

        self.range_row_bottom = QWidget(self.visual_panel)
        self.range_bottom_layout = QHBoxLayout(self.range_row_bottom)
        self.range_bottom_layout.setContentsMargins(0, 0, 0, 0)
        self.range_bottom_layout.setSpacing(8)

        self.band_very_low = _RangeBandCard("Severely Low", f"< {BMI_LOW_CRITICAL:.1f}")
        self.band_obese = _RangeBandCard("Obesity", f"≥ {BMI_WARNING_HIGH:.1f}")

        self.range_bottom_layout.addWidget(self.band_very_low)
        self.range_bottom_layout.addWidget(self.band_obese)

        visual_layout.addWidget(self.visual_title)
        visual_layout.addWidget(self.gauge_widget, 1)
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

        self.context_title = QLabel("Calculation Context", self.context_card)
        self.context_title.setObjectName("SectionTitle")

        self.context_line_1 = QLabel("Formula: weight / height²", self.context_card)
        self.context_line_2 = QLabel("Height unit: normalized to meters", self.context_card)
        self.context_line_3 = QLabel("Threshold source: pending", self.context_card)
        self.context_line_4 = QLabel("Status: pending", self.context_card)

        self.context_note = QLabel(
            "BMI is useful for broad screening, but it should be interpreted alongside clinical context, body composition, age, and other health factors.",
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

        self.refresh_button = self._create_button("Refresh Detail", variant="ghost", min_width=144, parent=self.quick_card)
        self.refresh_button.clicked.connect(self.reload_detail)

        self.qr_button = self._create_button("Open QR Handoff", variant="secondary", min_width=148, parent=self.quick_card)
        self.qr_button.clicked.connect(self._handle_qr_clicked)

        self.consult_button = self._create_button("Open Consult", variant="primary", min_width=148, parent=self.quick_card)
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
        action_layout.setSpacing(8)

        self.bottom_back_button = self._create_button("Back To Results", variant="secondary", min_width=132, parent=self.action_row)
        self.bottom_back_button.clicked.connect(self._handle_back_clicked)

        self.bottom_refresh_button = self._create_button("Refresh", variant="ghost", min_width=104, parent=self.action_row)
        self.bottom_refresh_button.clicked.connect(self.reload_detail)

        self.bottom_qr_button = self._create_button("QR", variant="secondary", min_width=96, parent=self.action_row)
        self.bottom_qr_button.clicked.connect(self._handle_qr_clicked)

        self.bottom_consult_button = self._create_button("Consult", variant="primary", min_width=118, parent=self.action_row)
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
        button.setMinimumHeight(36)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            """
            QPushButton {
                color: #F6FCFF;
                border: 1px solid rgba(157, 220, 255, 0.26);
                border-radius: 14px;
                padding: 8px 12px;
                font-size: 11px;
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
            QFrame#BmiDetailScreen {
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

            QFrame#BmiHeaderCard {
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
                self.hero_title.set_text("Body mass index detail")
            except Exception:
                self.hero_title.setText("Body mass index detail")
        else:
            self.hero_title.setText("Body mass index detail")

        self.hero_subtitle.setText(
            "BMI is a derived screening metric based on weight and height and is best interpreted with broader health context rather than in isolation."
        )
        self.summary_banner.setText(
            "This screen highlights the BMI category, active range band, and the supporting weight and height used in the calculation."
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
        self._status_message = safe_str(snapshot.get("status_message"), "BMI detail loaded.").strip()

        self._apply_snapshot_to_ui()
        self.detail_loaded.emit(self.diagnostics())
        self.detail_refreshed.emit(self.diagnostics())

    def _load_detail_snapshot(self) -> Dict[str, Any]:
        payload = self._read_session_payload()
        measurements = self._normalize_measurements(payload)
        thresholds = self._read_bmi_thresholds()

        bmi_value = measurements.get(METRIC_BMI)
        insight = _build_bmi_interpretation(
            bmi_value if isinstance(bmi_value, (float, int)) else None,
            thresholds,
        )

        # If diagnosis payload already has BMI-specific interpretation, merge it.
        diagnosis_item = self._read_bmi_diagnosis_item(payload)
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
            "status_message": "BMI detail snapshot loaded from active session data.",
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

        weight = raw_measurements.get(METRIC_WEIGHT, raw_measurements.get("weight_kg", payload.get("weight")))
        height = raw_measurements.get(METRIC_HEIGHT, raw_measurements.get("height_cm", payload.get("height")))
        bmi = raw_measurements.get(METRIC_BMI, payload.get("bmi"))

        height_cm = _format_height_cm(height)
        if bmi in (None, ""):
            bmi = _compute_bmi(weight, height_cm)

        return {
            METRIC_WEIGHT: None if weight in (None, "") else round(safe_float(weight, 0.0), 1),
            METRIC_HEIGHT: height_cm,
            METRIC_BMI: None if bmi in (None, "") else round(safe_float(bmi, 0.0), 1),
        }

    def _read_bmi_thresholds(self) -> Dict[str, float]:
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
                                if METRIC_BMI in raw and isinstance(raw.get(METRIC_BMI), Mapping):
                                    thresholds = raw.get(METRIC_BMI)  # type: ignore[assignment]
                                    break
                                profiles = raw.get("profiles", {})
                                if isinstance(profiles, Mapping) and METRIC_BMI in profiles and isinstance(profiles.get(METRIC_BMI), Mapping):
                                    thresholds = profiles.get(METRIC_BMI)  # type: ignore[assignment]
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
                                    if METRIC_BMI in raw and isinstance(raw.get(METRIC_BMI), Mapping):
                                        thresholds = raw.get(METRIC_BMI)  # type: ignore[assignment]
                                        break
                                    profiles = raw.get("profiles", {})
                                    if isinstance(profiles, Mapping) and METRIC_BMI in profiles and isinstance(profiles.get(METRIC_BMI), Mapping):
                                        thresholds = profiles.get(METRIC_BMI)  # type: ignore[assignment]
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
                        if isinstance(raw, Mapping) and METRIC_BMI in raw and isinstance(raw.get(METRIC_BMI), Mapping):
                            thresholds = raw.get(METRIC_BMI)  # type: ignore[assignment]
                            break
            except Exception:
                pass

        if thresholds is None:
            try:
                if self.app_state is not None:
                    for attr_name in ("threshold_profiles", "parameter_profiles", "health_rule_profiles"):
                        if hasattr(self.app_state, attr_name):
                            raw = getattr(self.app_state, attr_name)
                            if isinstance(raw, Mapping) and METRIC_BMI in raw and isinstance(raw.get(METRIC_BMI), Mapping):
                                thresholds = raw.get(METRIC_BMI)  # type: ignore[assignment]
                                break
            except Exception:
                pass

        return _normalize_bmi_thresholds(thresholds)

    def _read_bmi_diagnosis_item(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        raw_classes = payload.get("classifications", {})
        if isinstance(raw_classes, Mapping):
            raw_bmi = raw_classes.get(METRIC_BMI)
            if isinstance(raw_bmi, Mapping):
                return dict(raw_bmi)

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
                                bmi_item = classifications.get(METRIC_BMI)
                                if isinstance(bmi_item, Mapping):
                                    return dict(bmi_item)
            return {}
        except Exception:
            return {}

    # =========================================================================
    # UI binding
    # =========================================================================

    def _apply_snapshot_to_ui(self) -> None:
        bmi_value = self._measurements.get(METRIC_BMI)
        weight_value = self._measurements.get(METRIC_WEIGHT)
        height_value = self._measurements.get(METRIC_HEIGHT)

        severity = safe_str(self._insight.get("severity"), "unknown").strip().lower()
        label = safe_str(self._insight.get("label"), "BMI").strip() or "BMI"
        accent_hex = safe_str(self._insight.get("accent_hex"), _accent_for_state(severity)).strip() or _accent_for_state(severity)

        # pills
        self.category_pill.setText(label)
        self._apply_pill_style(self.category_pill, accent_hex)

        self.value_pill.setText(f"BMI { _format_num(bmi_value, 1) }")
        self._apply_pill_style(self.value_pill, "#67D8FF")

        self.status_pill.setText(severity.title() if severity else "Ready")
        self._apply_pill_style(self.status_pill, accent_hex)

        # chips
        self._apply_header_chip_style(self.derived_chip, "#67D8FF")
        self._apply_header_chip_style(self.range_chip, accent_hex)
        self._apply_header_chip_style(self.guidance_chip, "#39D8FF")

        # stats
        compact_card_text = bool(self._is_compact or self.width() <= 860 or self.height() <= 520)

        self.stat_weight.set_payload(
            value=_format_num(weight_value, 1, " kg"),
            subtitle="" if compact_card_text else "Measured body weight used in the BMI formula.",
            accent_hex="#67D8FF",
        )
        self.stat_height.set_payload(
            value=_format_num(height_value, 1, " cm"),
            subtitle="" if compact_card_text else "Measured body height normalized for BMI calculation.",
            accent_hex="#39D8FF",
        )
        self.stat_bmi.set_payload(
            value=_format_num(bmi_value, 1),
            subtitle="" if compact_card_text else "Derived body mass index value for this session.",
            accent_hex=accent_hex,
        )
        self.stat_severity.set_payload(
            value=label,
            subtitle="" if compact_card_text else safe_str(self._insight.get("summary"), "").strip(),
            accent_hex=accent_hex,
        )

        # gauge
        self.gauge_widget.set_payload(
            bmi_value=None if bmi_value in (None, "") else safe_float(bmi_value, 0.0),
            label=label,
            thresholds=self._thresholds,
            accent_hex=accent_hex,
        )

        # range band highlights
        active_band = safe_str(self._insight.get("active_band"), "").strip().lower()
        self.band_very_low.set_active(active_band == "very_low", "#FF6E88")
        self.band_under.set_active(active_band == "low", "#FFD25E")
        self.band_normal.set_active(active_band == "normal", "#42E393")
        self.band_over.set_active(active_band == "high", "#FFA14D")
        self.band_obese.set_active(active_band == "very_high", "#FF6E88")

        # summary
        lines = {
            1: f"Weight: {_format_num(weight_value, 1, ' kg')} and height: {_format_num(height_value, 1, ' cm')}.",
            2: safe_str(self._insight.get("detail"), "").strip(),
            3: f"Recommendation: {safe_str(self._insight.get('recommendation'), '').strip()}",
            4: (
                f"Reference bands: severe < {self._thresholds['warning_low']:.1f}, "
                f"healthy {self._thresholds['normal_low']:.1f}–{self._thresholds['normal_high']:.1f}, "
                f"high ≥ {self._thresholds['warning_high']:.1f}."
            ),
        }

        self.summary_card.set_payload(
            title="BMI Interpretation",
            state_text=label,
            summary=safe_str(self._insight.get("summary"), "").strip() or "BMI summary unavailable.",
            lines=lines,
            accent_hex=accent_hex,
        )

        # context
        self.context_line_1.setText("Formula: BMI = weight (kg) / [height (m)]²")
        self.context_line_2.setText("Height unit: converted to meters before calculation")
        self.context_line_3.setText(
            f"Threshold source: low {self._thresholds['warning_low']:.1f}, "
            f"healthy {self._thresholds['normal_low']:.1f}–{self._thresholds['normal_high']:.1f}, "
            f"high {self._thresholds['warning_high']:.1f}+"
        )
        self.context_line_4.setText(f"Status: {self._status_message}")

        # buttons
        self._set_button_accent(self.refresh_button, "#39D8FF")
        self._set_button_accent(self.bottom_refresh_button, "#39D8FF")
        self._set_button_accent(self.qr_button, "#67D8FF")
        self._set_button_accent(self.bottom_qr_button, "#67D8FF")
        self._set_button_accent(self.consult_button, accent_hex if severity in {"warning", "critical"} else "#42E393")
        self._set_button_accent(self.bottom_consult_button, accent_hex if severity in {"warning", "critical"} else "#42E393")

    # =========================================================================
    # Navigation / actions
    # =========================================================================

    def _handle_back_clicked(self) -> None:
        if self._navigate_to(SCREEN_RESULTS):
            return
        self.back_requested.emit()

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
            self.side_panel.setMinimumWidth(242 if ultra else (252 if compact else 300))
            self.side_panel.setMaximumWidth(278 if ultra else (290 if compact else 350))

        self.gauge_widget.setMinimumHeight(168 if ultra else (190 if compact else 250))
        self.summary_card.setMinimumHeight(150 if ultra else (176 if compact else 214))
        self.context_card.setMinimumHeight(118 if ultra else (132 if compact else 156))
        self.quick_card.setMinimumHeight(120 if ultra else (136 if compact else 158))

        self.stat_weight.setMinimumHeight(66 if compact else 82)
        self.stat_height.setMinimumHeight(66 if compact else 82)
        self.stat_bmi.setMinimumHeight(66 if compact else 82)
        self.stat_severity.setMinimumHeight(66 if compact else 82)

        self.hero_title.setText('BMI Detail' if compact else 'Body Mass Index Detail')
        self.top_title.setText('BMI Detail')

        if compact:
            self.hero_subtitle.setVisible(False)
            self.summary_banner.setVisible(True)
            self.summary_banner.setText('Current BMI, healthy range, and supporting measurements are shown below.')
            self.header_chip_row.setVisible(False)
            self.quick_text.setVisible(False)
            self.context_note.setVisible(False)
            self.logo_badge.setVisible(False)
            self.side_panel.setVisible(False)
            self.range_row_top.setVisible(False)
            self.range_row_bottom.setVisible(False)
            self.visual_title.setText('BMI Gauge')
            self.gauge_widget.setMinimumHeight(220 if ultra else 236)
            self.content_row.layout().setSpacing(0)
        else:
            self.hero_subtitle.setVisible(True)
            self.summary_banner.setVisible(True)
            self.summary_banner.setText('This screen highlights the BMI category, active range band, and the supporting weight and height used in the calculation.')
            self.header_chip_row.setVisible(True)
            self.quick_text.setVisible(True)
            self.context_note.setVisible(True)
            self.logo_badge.setVisible(True)
            self.side_panel.setVisible(True)
            self.range_row_top.setVisible(True)
            self.range_row_bottom.setVisible(True)
            self.visual_title.setText('BMI Gauge and Range Bands')
            self.content_row.layout().setSpacing(8 if compact else 12)

        for stat_card in (self.stat_weight, self.stat_height, self.stat_bmi, self.stat_severity):
            try:
                stat_card.subtitle_label.setVisible(not compact and bool(stat_card.subtitle_label.text().strip()))
            except Exception:
                pass

        self.bottom_back_button.setText('Results' if compact else 'Back To Results')
        self.refresh_button.setText('Reload' if compact else 'Refresh Detail')
        self.qr_button.setText('QR' if compact else 'Open QR Handoff')
        self.consult_button.setText('Consult')

        self.back_button.setMinimumWidth(76 if compact else 96)
        for btn in (self.refresh_button, self.qr_button, self.consult_button, self.bottom_back_button, self.bottom_refresh_button, self.bottom_qr_button, self.bottom_consult_button):
            try:
                btn.setMinimumHeight(34 if compact else 38)
            except Exception:
                pass

        self._apply_compact_styles(compact=compact, ultra=ultra)

    def _apply_compact_styles(self, *, compact: bool, ultra: bool) -> None:
        top_title_px = 13 if compact else 15
        pill_px = 9 if compact else 10
        section_px = 11 if compact else 12
        hero_px = 18 if ultra else (20 if compact else 24)
        body_px = 8 if ultra else (10 if compact else 11)

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
        for chip in (self.derived_chip, self.range_chip, self.guidance_chip):
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
            "gauge_overlay_path": self._gauge_overlay_path,
        }