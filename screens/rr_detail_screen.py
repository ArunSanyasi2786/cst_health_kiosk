"""
screens/rr_detail_screen.py

Premium respiratory-rate detail screen for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the public-facing respiratory-rate explanation screen opened from:
    - screens/results_screen.py
- It allows the user or operator to:
    - inspect the current respiratory-rate value in a premium detailed view
    - understand the category and severity of the RR result
    - review the reference bands used by the kiosk
    - see the active respiratory band highlighted in a polished medical-kiosk style
    - navigate back to results or continue to QR / consult workflows
- It is designed specifically for:
    - Raspberry Pi 4B touchscreen kiosk deployment
    - 1024x600 kiosk resolution
    - laptop demo mode
- It provides:
    - glossy futuristic blue medical UI
    - resilient loading from session_service / diagnosis_service / threshold_service
    - threshold-aware respiratory-rate interpretation
    - safe normalization for inconsistent RR values
    - safe fallback behavior when services are still being integrated
    - maintainable self-contained drawing logic for the RR reference chart

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
- widgets/rr_chart_widget.py

Navigation targets this screen is designed to link to:
- screens/results_screen.py
- screens/qr_screen.py
- screens/consult_screen.py

Design goals:
- glossy futuristic blue medical UI
- informative but calm patient-facing detail screen
- strong readability at 1024x600
- premium respiratory-band visualization with active-band highlighting
- resilient integration while backend files continue evolving
"""

from __future__ import annotations

import math
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from PyQt6.QtCore import (
    QEasingCurve,
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
        SCREEN_RESULTS,
        SCREEN_QR,
        SCREEN_CONSULT,
        METRIC_RESPIRATORY_RATE,
    )
except Exception:  # pragma: no cover
    SCREEN_RESULTS = "results"
    SCREEN_QR = "qr"
    SCREEN_CONSULT = "consult"
    METRIC_RESPIRATORY_RATE = "respiratory_rate"

try:
    from config import KIOSK_WIDTH, KIOSK_HEIGHT, IS_COMPACT_KIOSK
except Exception:  # pragma: no cover
    KIOSK_WIDTH = 800
    KIOSK_HEIGHT = 480
    IS_COMPACT_KIOSK = KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480

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

RR_WARNING_LOW = 8.0
RR_NORMAL_LOW = 12.0
RR_NORMAL_HIGH = 20.0
RR_WARNING_HIGH = 30.0

RR_SCALE_MIN = 4.0
RR_SCALE_MAX = 40.0


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


def _format_num(value: Any, decimals: int = 0, suffix: str = "") -> str:
    if value in (None, ""):
        return "--"
    try:
        num = float(value)
        if decimals <= 0:
            text = f"{int(round(num))}"
        else:
            text = f"{num:.{decimals}f}"
        return f"{text}{suffix}"
    except Exception:
        return "--"


def _normalize_rr(value: Any) -> Optional[int]:
    """
    Normalize respiratory-rate input into an integer breaths-per-minute value.

    Accepts:
    - direct RR values like 16, 22.4
    - slightly noisy sensor outputs that still fall within realistic ranges
    """
    if value in (None, ""):
        return None

    raw = safe_float(value, -1.0)
    if raw <= 0:
        return None

    # Values below 2 are not meaningful for breaths per minute.
    if raw < 2.0:
        return None

    # Cap outliers into a safe visible range.
    raw = max(0.0, min(80.0, raw))
    return int(round(raw))


def _accent_for_state(state: str) -> str:
    text = safe_str(state, "").strip().lower()
    if text in {"critical", "critical low", "very high rr", "bradypnea", "tachypnea"}:
        return "#FF6E88"
    if text in {"warning", "elevated rr"}:
        return "#FFA14D"
    if text in {"attention", "low rr", "borderline low"}:
        return "#FFD25E"
    if text in {"normal", "healthy"}:
        return "#42E393"
    return "#39D8FF"


def _normalize_rr_thresholds(raw: Optional[Mapping[str, Any]]) -> Dict[str, float]:
    base = {
        "warning_low": RR_WARNING_LOW,
        "normal_low": RR_NORMAL_LOW,
        "normal_high": RR_NORMAL_HIGH,
        "warning_high": RR_WARNING_HIGH,
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
        "warning_low": round(max(2.0, ordered[0]), 1),
        "normal_low": round(max(3.0, ordered[1]), 1),
        "normal_high": round(min(80.0, ordered[2]), 1),
        "warning_high": round(min(80.0, ordered[3]), 1),
    }


def _build_rr_interpretation(
    rr_value: Optional[int],
    thresholds: Mapping[str, float],
) -> Dict[str, Any]:
    if rr_value is None:
        return {
            "label": "Unavailable",
            "severity": "unknown",
            "summary": "Respiratory rate could not be interpreted because no valid RR reading is available.",
            "detail": "A missing or invalid respiratory-rate value prevents proper breathing-pattern classification.",
            "recommendation": "Repeat the respiratory measurement with stable acquisition conditions.",
            "active_band": "unknown",
            "accent_hex": "#39D8FF",
        }

    warning_low = safe_float(thresholds.get("warning_low"), RR_WARNING_LOW)
    normal_low = safe_float(thresholds.get("normal_low"), RR_NORMAL_LOW)
    normal_high = safe_float(thresholds.get("normal_high"), RR_NORMAL_HIGH)
    warning_high = safe_float(thresholds.get("warning_high"), RR_WARNING_HIGH)

    if rr_value < warning_low:
        return {
            "label": "Critical Low",
            "severity": "critical",
            "summary": "Respiratory rate is markedly below the typical adult resting range.",
            "detail": "A very low breathing rate may require prompt attention depending on symptoms, consciousness, medication effects, and the wider clinical situation.",
            "recommendation": "Retake the reading to confirm stability and seek professional review if symptoms or concerning context are present.",
            "active_band": "critical_low",
            "accent_hex": _accent_for_state("critical"),
        }

    if rr_value < normal_low:
        return {
            "label": "Low RR",
            "severity": "attention",
            "summary": "Respiratory rate is below the common adult resting reference band.",
            "detail": "This may be normal in some situations but can also reflect reduced breathing activity or measurement conditions.",
            "recommendation": "Review together with symptoms, oxygen saturation, pulse, and the wider health context. Repeat if needed.",
            "active_band": "low",
            "accent_hex": _accent_for_state("attention"),
        }

    if rr_value <= normal_high:
        return {
            "label": "Healthy",
            "severity": "normal",
            "summary": "Respiratory rate falls within the common adult resting reference range used by the kiosk.",
            "detail": "This result is generally reassuring when interpreted alongside oxygen saturation, pulse, and the full session results.",
            "recommendation": "Routine handoff is usually sufficient unless other measurements raise concern.",
            "active_band": "normal",
            "accent_hex": _accent_for_state("normal"),
        }

    if rr_value < warning_high:
        return {
            "label": "Elevated RR",
            "severity": "warning",
            "summary": "Respiratory rate is above the common adult resting reference band.",
            "detail": "This may reflect exertion, anxiety, fever, discomfort, respiratory strain, or a sustained elevated breathing rate that deserves review.",
            "recommendation": "Allow rest if appropriate, repeat the reading, and review with symptoms and other vital signs.",
            "active_band": "high",
            "accent_hex": _accent_for_state("warning"),
        }

    return {
        "label": "Very High RR",
        "severity": "critical",
        "summary": "Respiratory rate is markedly elevated above the common resting reference band.",
        "detail": "A very high breathing rate may require prompt attention depending on the clinical situation and associated symptoms.",
        "recommendation": "Retake to confirm accuracy and escalate according to approved clinical or supervisory workflow.",
        "active_band": "critical_high",
        "accent_hex": _accent_for_state("critical"),
    }


# =============================================================================
# Internal widgets
# =============================================================================

class _RrChartFallbackWidget(QWidget):
    """
    Clean full-width respiratory-rate reference scale tuned for the compact
    800x480 kiosk layout.

    Compared with the original fallback widget, this version intentionally
    reduces clutter:
    - one clean shell card
    - subtle waveform at the top
    - a single colored respiratory band
    - one marker with guide line
    - a reserved value badge on the right
    - no overlapping text blocks
    """

    def __init__(self, overlay_path: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._overlay_pixmap = _pixmap_or_empty(overlay_path)
        self._rr_value: Optional[int] = None
        self._thresholds = _normalize_rr_thresholds(None)
        self._label = "Healthy"
        self._accent_hex = "#42E393"
        self.setMinimumHeight(190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_payload(
        self,
        *,
        rr_value: Optional[int],
        label: str,
        thresholds: Mapping[str, float],
        accent_hex: str,
    ) -> None:
        self._rr_value = rr_value
        self._label = safe_str(label, "Healthy").strip() or "Healthy"
        self._thresholds = _normalize_rr_thresholds(thresholds)
        self._accent_hex = safe_str(accent_hex, "#42E393").strip() or "#42E393"
        self.update()

    def _value_to_ratio(self, value: float) -> float:
        clamped = max(RR_SCALE_MIN, min(RR_SCALE_MAX, float(value)))
        return (clamped - RR_SCALE_MIN) / (RR_SCALE_MAX - RR_SCALE_MIN)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect = self.rect().adjusted(14, 12, -14, -12)
        if rect.width() <= 60 or rect.height() <= 60:
            painter.end()
            return

        shell = QRectF(rect)
        painter.setPen(QPen(QColor(120, 196, 255, 44), 1.5))
        painter.setBrush(QColor(8, 25, 48, 146))
        painter.drawRoundedRect(shell, 24, 24)

        if not self._overlay_pixmap.isNull():
            overlay = self._overlay_pixmap.scaled(
                max(80, rect.width() - 120),
                max(80, rect.height() - 28),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.setOpacity(0.055)
            painter.drawPixmap(
                int(rect.center().x() - overlay.width() / 2),
                int(rect.center().y() - overlay.height() / 2) - 4,
                overlay,
            )
            painter.setOpacity(1.0)

        # Decorative respiratory waveform
        wave_rect = QRectF(rect.left() + 26, rect.top() + 20, rect.width() - 52, 30)
        path = QPainterPath()
        y_mid = wave_rect.center().y()
        path.moveTo(wave_rect.left(), y_mid)
        steps = 120
        for i in range(1, steps + 1):
            t = i / steps
            x = wave_rect.left() + wave_rect.width() * t
            y = y_mid + math.sin(t * 5.8 * math.pi) * 4.8
            if 0.20 < t < 0.28 or 0.53 < t < 0.61 or 0.79 < t < 0.86:
                y = y_mid + math.sin(t * 5.8 * math.pi) * 8.0
            path.lineTo(x, y)
        painter.setPen(QPen(QColor(67, 217, 255, 38), 4))
        painter.drawPath(path)
        painter.setPen(QPen(QColor(72, 235, 180, 210), 1.6))
        painter.drawPath(path)

        warning_low = self._thresholds["warning_low"]
        normal_low = self._thresholds["normal_low"]
        normal_high = self._thresholds["normal_high"]
        warning_high = self._thresholds["warning_high"]

        badge_width = min(232.0, max(170.0, rect.width() * 0.26))
        badge_height = 76.0
        badge_margin_right = 18.0
        gap_before_badge = 12.0

        band_left = rect.left() + 34
        band_top = rect.center().y() + 16
        available_width = rect.width() - 68 - badge_width - badge_margin_right - gap_before_badge
        band_width = max(280.0, available_width)
        band_height = 22
        band_rect = QRectF(band_left, band_top, band_width, band_height)

        painter.setPen(QPen(QColor(181, 232, 255, 52), 1.5))
        painter.setBrush(QColor(9, 21, 40, 220))
        painter.drawRoundedRect(band_rect, 11, 11)

        inner = band_rect.adjusted(3, 3, -3, -3)
        segments = [
            (RR_SCALE_MIN, warning_low, QColor("#FF6E88")),
            (warning_low, normal_low, QColor("#FFD25E")),
            (normal_low, normal_high, QColor("#42E393")),
            (normal_high, warning_high, QColor("#FFA14D")),
            (warning_high, RR_SCALE_MAX, QColor("#FF6E88")),
        ]
        for start_v, end_v, color in segments:
            x1 = inner.left() + inner.width() * self._value_to_ratio(start_v)
            x2 = inner.left() + inner.width() * self._value_to_ratio(end_v)
            seg = QRectF(min(x1, x2), inner.top(), max(6.0, abs(x2 - x1)), inner.height())
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(seg, inner.height() / 2, inner.height() / 2)

        if self._rr_value is not None:
            ratio = self._value_to_ratio(float(self._rr_value))
            marker_x = inner.left() + inner.width() * ratio
            accent = QColor(self._accent_hex)
            painter.setPen(QPen(accent, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(int(marker_x), int(inner.top() - 24), int(marker_x), int(inner.bottom() + 26))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawEllipse(QRectF(marker_x - 12, inner.top() - 36, 24, 24))
            painter.setBrush(QColor("#F7FCFF"))
            painter.drawEllipse(QRectF(marker_x - 5, inner.top() - 29, 10, 10))

        tick_values = [4, 8, 12, 16, 20, 24, 30, 40]
        painter.setFont(QFont("Inter", 8, QFont.Weight.Medium))
        painter.setPen(QColor(206, 230, 246, 190))
        for tick in tick_values:
            tick_x = inner.left() + inner.width() * self._value_to_ratio(float(tick))
            painter.drawLine(int(tick_x), int(inner.bottom() + 6), int(tick_x), int(inner.bottom() + 14))
            painter.drawText(QRectF(tick_x - 16, inner.bottom() + 16, 32, 15), Qt.AlignmentFlag.AlignCenter, str(tick))

        zone_y = band_rect.top() - 28
        painter.setFont(QFont("Inter", 8, QFont.Weight.Bold))
        zone_labels = [
            (RR_SCALE_MIN, warning_low, "Critical Low", QColor("#FF6E88")),
            (warning_low, normal_low, "Low", QColor("#FFD25E")),
            (normal_low, normal_high, "Healthy", QColor("#42E393")),
            (normal_high, warning_high, "High", QColor("#FFA14D")),
        ]
        for start_v, end_v, label, color in zone_labels:
            x1 = inner.left() + inner.width() * self._value_to_ratio(start_v)
            x2 = inner.left() + inner.width() * self._value_to_ratio(end_v)
            label_rect = QRectF(min(x1, x2), zone_y, max(32.0, abs(x2 - x1)), 18)
            painter.setPen(color)
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, label)

        badge_rect = QRectF(
            band_rect.right() + gap_before_badge,
            band_rect.center().y() - badge_height / 2,
            badge_width,
            badge_height,
        )
        accent = QColor(self._accent_hex)
        painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 120), 1.6))
        painter.setBrush(QColor(9, 27, 49, 238))
        painter.drawRoundedRect(badge_rect, 20, 20)
        painter.setPen(QColor("#F7FCFF"))
        painter.setFont(QFont("Inter", 18, QFont.Weight.Bold))
        value_text = "--" if self._rr_value is None else f"{int(self._rr_value)} bpm"
        painter.drawText(QRectF(badge_rect.left(), badge_rect.top() + 8, badge_rect.width(), 28), Qt.AlignmentFlag.AlignCenter, value_text)
        painter.setPen(QColor(accent))
        painter.setFont(QFont("Inter", 10, QFont.Weight.DemiBold))
        painter.drawText(QRectF(badge_rect.left(), badge_rect.top() + 40, badge_rect.width(), 18), Qt.AlignmentFlag.AlignCenter, self._label)

        painter.end()


class _InfoStatCard(QFrame):
    """
    Small premium stat card for RR detail metrics.
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

        self.setObjectName("RrInfoStatCard")
        self.setMinimumHeight(88)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._root_layout = QVBoxLayout(self)
        root = self._root_layout
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
        self.subtitle_label.setText(safe_str(subtitle, "").strip())
        self._apply_style()

    def _apply_style(self) -> None:
        accent = QColor(self._accent_hex)

        self.setStyleSheet(
            f"""
            QFrame#RrInfoStatCard {{
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
    Premium RR range band card with selectable highlight.
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

        self.setObjectName("RrRangeBandCard")
        self.setMinimumHeight(72)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._root_layout = QVBoxLayout(self)
        root = self._root_layout
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
            QFrame#RrRangeBandCard {{
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

        self.setObjectName("RrSummaryCard")
        self.setMinimumHeight(214)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._root_layout = QVBoxLayout(self)
        root = self._root_layout
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(8)

        top_row = QWidget(self)
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        self.title_label = QLabel("Respiratory Interpretation", top_row)
        self.state_chip = QLabel("Pending", top_row)

        top_layout.addWidget(self.title_label)
        top_layout.addStretch(1)
        top_layout.addWidget(self.state_chip)

        self.summary_label = QLabel(
            "Respiratory-rate detail summary will appear here when a valid measurement is available.",
            self,
        )
        self.summary_label.setWordWrap(True)

        self.line_1 = QLabel("• Breathing-rate bands help classify the current reading.", self)
        self.line_2 = QLabel("• The highlighted band shows the active status.", self)
        self.line_3 = QLabel("• Recommendations are supportive guidance, not a diagnosis.", self)
        self.line_4 = QLabel("• Final interpretation should consider oxygen saturation, symptoms, and the full health context.", self)

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
        self.title_label.setText(safe_str(title, "Respiratory Interpretation").strip() or "Respiratory Interpretation")
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
            QFrame#RrSummaryCard {{
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

class RrDetailScreen(QFrame):
    """
    Premium respiratory-rate detail screen.

    Main responsibilities:
    - load RR value from active runtime session
    - normalize to a clean breaths-per-minute display
    - interpret RR against threshold profiles
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

        self._logger = logger.bind(component="RrDetailScreen")

        self.navigator = navigator
        self.app_state = app_state
        self.services = dict(services or {})
        self.animation_manager = animation_manager
        self.theme_manager = theme_manager

        self._payload: Dict[str, Any] = {}
        self._measurements: Dict[str, Any] = {}
        self._thresholds: Dict[str, float] = _normalize_rr_thresholds(None)
        self._insight: Dict[str, Any] = {}
        self._status_message = "Respiratory detail view is ready to load."

        self._background_path = _resolve_asset("backgrounds/rr_detail_bg.png")
        self._logo_small_path = _resolve_asset("logos/cst_logo_small.png")
        self._chart_overlay_path = _resolve_asset("detail_graphics/rr_reference_chart.png")

        self._background_pixmap = _pixmap_or_empty(self._background_path)
        self._logo_pixmap = _pixmap_or_empty(self._logo_small_path)

        self.setObjectName("RrDetailScreen")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._compact_mode = bool(IS_COMPACT_KIOSK)
        self._ultra_compact_mode = bool(KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480)

        self._build_ui()
        self._setup_effects()
        self._apply_styles()
        self._apply_responsive_layout(force=True)

    # =========================================================================
    # UI
    # =========================================================================

    def _build_ui(self) -> None:
        self._root_layout = QVBoxLayout(self)
        root = self._root_layout
        root.setContentsMargins(22, 16, 22, 16)
        root.setSpacing(12)

        # ---------------------------------------------------------------------
        # Top bar
        # ---------------------------------------------------------------------
        self.top_bar = QWidget(self)
        self._top_layout = QHBoxLayout(self.top_bar)
        top_layout = self._top_layout
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(10)

        self.back_button = self._create_button("Back", variant="secondary", min_width=96, parent=self.top_bar)
        self.back_button.clicked.connect(self._handle_back_clicked)

        self.logo_badge = QLabel(self.top_bar)
        self.logo_badge.setObjectName("LogoBadge")
        self.logo_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_label_pixmap(self.logo_badge, self._logo_pixmap, 26)

        self.top_title = QLabel("Respiratory Detail", self.top_bar)
        self.top_title.setObjectName("TopTitle")

        self.category_pill = QLabel("Category", self.top_bar)
        self.category_pill.setObjectName("RuntimePill")

        self.value_pill = QLabel("RR --", self.top_bar)
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
        self.header_card.setObjectName("RrHeaderCard")

        self._header_layout = QVBoxLayout(self.header_card)
        header_layout = self._header_layout
        header_layout.setContentsMargins(18, 16, 18, 16)
        header_layout.setSpacing(8)

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

        self.metric_chip = QLabel("Core Breathing Metric", self.header_chip_row)
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
            "Respiratory rate reflects breathing frequency and becomes more meaningful when interpreted together with oxygen saturation, pulse, temperature, and symptoms.",
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
        self._stats_layout = QHBoxLayout(self.stats_row)
        stats_layout = self._stats_layout
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(10)

        self.stat_rr = _InfoStatCard("Respiratory Rate", value="--", subtitle="Current normalized breathing-rate reading.")
        self.stat_range = _InfoStatCard("Healthy Band", value="--", subtitle="Preferred resting range used by the kiosk.")
        self.stat_alert = _InfoStatCard("High Threshold", value="--", subtitle="Elevated respiratory-rate attention threshold.")
        self.stat_status = _InfoStatCard("Status", value="--", subtitle="Current interpretation category.")

        stats_layout.addWidget(self.stat_rr, 1)
        stats_layout.addWidget(self.stat_range, 1)
        stats_layout.addWidget(self.stat_alert, 1)
        stats_layout.addWidget(self.stat_status, 1)

        # ---------------------------------------------------------------------
        # Content row
        # ---------------------------------------------------------------------
        self.content_row = QWidget(self)
        self._content_layout = QHBoxLayout(self.content_row)
        content_layout = self._content_layout
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(14)

        # Left visual panel
        self.visual_panel = QFrame(self.content_row)
        self.visual_panel.setObjectName("VisualPanel")
        self.visual_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        visual_layout = QVBoxLayout(self.visual_panel)
        visual_layout.setContentsMargins(14, 12, 14, 12)
        visual_layout.setSpacing(8)

        self.visual_title = QLabel("Respiratory Reference Band and Range Cards", self.visual_panel)
        self.visual_title.setObjectName("SectionTitle")

        self.chart_widget = _RrChartFallbackWidget(self._chart_overlay_path, self.visual_panel)

        self.range_row_top = QWidget(self.visual_panel)
        self.range_top_layout = QHBoxLayout(self.range_row_top)
        self.range_top_layout.setContentsMargins(0, 0, 0, 0)
        self.range_top_layout.setSpacing(8)

        self.band_critical_low = _RangeBandCard("Critical Low", f"< {RR_WARNING_LOW:.0f} bpm")
        self.band_low = _RangeBandCard("Low RR", f"{RR_WARNING_LOW:.0f}–{RR_NORMAL_LOW - 1:.0f} bpm")
        self.band_normal = _RangeBandCard("Healthy", f"{RR_NORMAL_LOW:.0f}–{RR_NORMAL_HIGH:.0f} bpm")

        self.range_top_layout.addWidget(self.band_critical_low)
        self.range_top_layout.addWidget(self.band_low)
        self.range_top_layout.addWidget(self.band_normal)

        self.range_row_bottom = QWidget(self.visual_panel)
        self.range_bottom_layout = QHBoxLayout(self.range_row_bottom)
        self.range_bottom_layout.setContentsMargins(0, 0, 0, 0)
        self.range_bottom_layout.setSpacing(8)

        self.band_high = _RangeBandCard("Elevated RR", f"{RR_NORMAL_HIGH + 1:.0f}–{RR_WARNING_HIGH - 1:.0f} bpm")
        self.band_critical_high = _RangeBandCard("Very High RR", f"≥ {RR_WARNING_HIGH:.0f} bpm")

        self.range_bottom_layout.addWidget(self.band_high)
        self.range_bottom_layout.addWidget(self.band_critical_high)

        visual_layout.addWidget(self.visual_title)
        visual_layout.addWidget(self.chart_widget, 1)
        visual_layout.addWidget(self.range_row_top)
        visual_layout.addWidget(self.range_row_bottom)

        # Right insight panel
        self.side_panel = QWidget(self.content_row)
        self._side_layout = QVBoxLayout(self.side_panel)
        side_layout = self._side_layout
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(12)
        self.side_panel.setMinimumWidth(320)
        self.side_panel.setMaximumWidth(350)

        self.summary_card = _SummaryCard(self.side_panel)

        self.context_card = QFrame(self.side_panel)
        self.context_card.setObjectName("InfoCard")

        context_layout = QVBoxLayout(self.context_card)
        context_layout.setContentsMargins(16, 14, 16, 14)
        context_layout.setSpacing(8)

        self.context_title = QLabel("Measurement Context", self.context_card)
        self.context_title.setObjectName("SectionTitle")

        self.context_line_1 = QLabel("Preferred unit: breaths per minute", self.context_card)
        self.context_line_2 = QLabel("Input normalization: active", self.context_card)
        self.context_line_3 = QLabel("Threshold source: pending", self.context_card)
        self.context_line_4 = QLabel("Status: pending", self.context_card)

        self.context_note = QLabel(
            "Respiratory rate can change due to movement, exertion, anxiety, pain, fever, respiratory effort, or measurement noise, so context matters.",
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
        quick_layout.setContentsMargins(16, 14, 16, 14)
        quick_layout.setSpacing(8)

        self.quick_title = QLabel("Next Actions", self.quick_card)
        self.quick_title.setObjectName("SectionTitle")

        self.quick_text = QLabel(
            "Return to the results dashboard, continue to QR handoff, or open the consult flow for broader interpretation support.",
            self.quick_card,
        )
        self.quick_text.setWordWrap(True)

        self.refresh_button = self._create_button("Refresh Detail", variant="ghost", min_width=168, parent=self.quick_card)
        self.refresh_button.clicked.connect(self.reload_detail)

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
        self._action_layout = QHBoxLayout(self.action_row)
        action_layout = self._action_layout
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(10)

        self.bottom_back_button = self._create_button("Back To Results", variant="secondary", min_width=160, parent=self.action_row)
        self.bottom_back_button.clicked.connect(self._handle_back_clicked)

        self.bottom_refresh_button = self._create_button("Refresh", variant="ghost", min_width=120, parent=self.action_row)
        self.bottom_refresh_button.clicked.connect(self.reload_detail)

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
            QFrame#RrDetailScreen {
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

            QFrame#RrHeaderCard {
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
                self.hero_title.set_text("Respiratory Detail")
            except Exception:
                self.hero_title.setText("Respiratory Detail")
        else:
            self.hero_title.setText("Respiratory Detail")

        self.hero_subtitle.setText(
            "Respiratory rate reflects how often breathing occurs and can change with exertion, anxiety, fever, respiratory effort, discomfort, or the need for closer review."
        )
        self.summary_banner.setText(
            "This screen highlights the current respiratory-rate band, the reference thresholds, and supportive next-step guidance."
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


    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_responsive_layout()

    def _apply_responsive_layout(self, force: bool = False) -> None:
        width = max(1, self.width() or int(KIOSK_WIDTH))
        height = max(1, self.height() or int(KIOSK_HEIGHT))

        compact = width <= 860 or height <= 520 or bool(IS_COMPACT_KIOSK)
        ultra = width <= 800 or height <= 480

        if (not force and compact == getattr(self, "_compact_mode", False)
                and ultra == getattr(self, "_ultra_compact_mode", False)):
            return

        self._compact_mode = compact
        self._ultra_compact_mode = ultra

        if ultra:
            self._root_layout.setContentsMargins(10, 8, 10, 8)
            self._root_layout.setSpacing(6)
            self._top_layout.setSpacing(6)
            self._header_layout.setContentsMargins(12, 10, 12, 10)
            self._header_layout.setSpacing(4)
            self._stats_layout.setSpacing(6)
            self._content_layout.setSpacing(6)
            self._side_layout.setSpacing(6)
            self._action_layout.setSpacing(8)

            self.top_title.setText("Respiratory Detail")
            self.hero_title.setText("Respiratory Detail")
            self.hero_subtitle.setVisible(False)
            self.header_chip_row.setVisible(False)
            self.summary_banner.setVisible(True)
            self.summary_banner.setText("Current reading and healthy breathing range are shown below.")

            self.context_note.setVisible(False)
            self.quick_text.setVisible(False)
            self.visual_title.setVisible(True)
            self.visual_title.setText("Respiratory Rate Scale")

            self.side_panel.hide()
            self.range_row_top.hide()
            self.range_row_bottom.hide()
            self.stat_rr.subtitle_label.setVisible(False)
            self.stat_range.subtitle_label.setVisible(False)
            self.stat_alert.subtitle_label.setVisible(False)
            self.stat_status.subtitle_label.setVisible(False)

            self.header_card.setMinimumHeight(86)
            self.header_card.setMaximumHeight(96)
            self.top_bar.setMinimumHeight(42)
            self.top_bar.setMaximumHeight(44)
            self.stats_row.setMinimumHeight(76)
            self.stats_row.setMaximumHeight(84)
            self.visual_panel.setMinimumHeight(0)
            self.visual_panel.setMaximumHeight(10000)
            self.chart_widget.setMinimumHeight(146)
            self.chart_widget.setMaximumHeight(152)
            self.summary_card.setMinimumHeight(120)

            self.stat_rr.setMinimumHeight(72)
            self.stat_range.setMinimumHeight(72)
            self.stat_alert.setMinimumHeight(72)
            self.stat_status.setMinimumHeight(72)
            self.stat_rr.setMaximumHeight(80)
            self.stat_range.setMaximumHeight(80)
            self.stat_alert.setMaximumHeight(80)
            self.stat_status.setMaximumHeight(80)

            self.refresh_button.setText("Refresh")
            self.qr_button.setText("Open QR")
            self.consult_button.setText("Consult")
            self.bottom_back_button.setText("Results")
            self.bottom_refresh_button.setText("Refresh")
            self.bottom_qr_button.setText("QR")
            self.bottom_consult_button.setText("Consult")
        elif compact:
            self._root_layout.setContentsMargins(16, 12, 16, 12)
            self._root_layout.setSpacing(10)
            self._top_layout.setSpacing(8)
            self._header_layout.setContentsMargins(16, 14, 16, 14)
            self._header_layout.setSpacing(7)
            self._stats_layout.setSpacing(8)
            self._content_layout.setSpacing(10)
            self._side_layout.setSpacing(10)
            self._action_layout.setSpacing(8)

            self.top_title.setText("Respiratory Detail")
            self.hero_title.setText("Respiratory Detail")
            self.hero_subtitle.setVisible(False)
            self.header_chip_row.setVisible(False)
            self.summary_banner.setVisible(True)
            self.summary_banner.setText("Current reading and healthy breathing range are shown below.")

            self.context_note.setVisible(False)
            self.quick_text.setVisible(False)
            self.visual_title.setVisible(True)
            self.visual_title.setText("Respiratory Rate Scale")

            self.side_panel.hide()
            self.range_row_top.hide()
            self.range_row_bottom.hide()
            self.stat_rr.subtitle_label.setVisible(False)
            self.stat_range.subtitle_label.setVisible(False)
            self.stat_alert.subtitle_label.setVisible(False)
            self.stat_status.subtitle_label.setVisible(False)
            self.chart_widget.setMinimumHeight(226)
            self.summary_card.setMinimumHeight(180)

            self.refresh_button.setText("Refresh")
            self.qr_button.setText("Open QR")
            self.consult_button.setText("Consult")
            self.bottom_back_button.setText("Results")
            self.bottom_refresh_button.setText("Refresh")
            self.bottom_qr_button.setText("QR")
            self.bottom_consult_button.setText("Consult")
        else:
            self._root_layout.setContentsMargins(22, 16, 22, 16)
            self._root_layout.setSpacing(12)
            self._top_layout.setSpacing(10)
            self._header_layout.setContentsMargins(18, 16, 18, 16)
            self._header_layout.setSpacing(8)
            self._stats_layout.setSpacing(10)
            self._content_layout.setSpacing(14)
            self._side_layout.setSpacing(12)
            self._action_layout.setSpacing(10)

            self.top_title.setText("Respiratory Detail")
            self.hero_title.setText("Respiratory Detail")
            self.hero_subtitle.setVisible(True)
            self.header_chip_row.setVisible(True)
            self.summary_banner.setVisible(True)

            self.context_note.setVisible(True)
            self.quick_text.setVisible(True)
            self.visual_title.setVisible(True)
            self.visual_title.setText("Respiratory Reference Band and Range Cards")

            self.side_panel.show()
            self.range_row_top.show()
            self.range_row_bottom.show()
            self.stat_rr.subtitle_label.setVisible(True)
            self.stat_range.subtitle_label.setVisible(True)
            self.stat_alert.subtitle_label.setVisible(True)
            self.stat_status.subtitle_label.setVisible(True)
            self.side_panel.setMinimumWidth(320)
            self.side_panel.setMaximumWidth(350)
            self.chart_widget.setMinimumHeight(250)
            self.summary_card.setMinimumHeight(214)

            self.refresh_button.setText("Refresh Detail")
            self.qr_button.setText("Open QR Handoff")
            self.consult_button.setText("Open Consult")
            self.bottom_back_button.setText("Back To Results")
            self.bottom_refresh_button.setText("Refresh")
            self.bottom_qr_button.setText("QR")
            self.bottom_consult_button.setText("Consult")

        runtime_pill_style = "QLabel { color: #EEF9FF; font-size: %dpx; font-weight: 700; border: 1px solid rgba(157, 220, 255, 0.22); border-radius: 14px; background: rgba(18, 39, 70, 0.56); padding: %dpx %dpx; }" % (
            9 if ultra else 10,
            4 if ultra else 6,
            8 if ultra else 10,
        )
        for pill in (self.category_pill, self.value_pill, self.status_pill):
            pill.setStyleSheet(runtime_pill_style)
        self.category_pill.setVisible(not ultra or width > 760)

        header_chip_style = "QLabel { color: #EEF9FF; font-size: %dpx; font-weight: 800; border: 1px solid rgba(157, 220, 255, 0.22); border-radius: 12px; background: rgba(28, 56, 91, 0.42); padding: %dpx %dpx; }" % (
            8 if ultra else 9,
            3 if ultra else 4,
            7 if ultra else 9,
        )
        for chip in (self.metric_chip, self.range_chip, self.guidance_chip):
            chip.setStyleSheet(header_chip_style)

        self.top_title.setStyleSheet(
            "QLabel { color: #F6FCFF; font-size: %dpx; font-weight: 900; background: transparent; }"
            % (13 if ultra else 14 if compact else 15)
        )
        self.hero_title.setStyleSheet(
            "QLabel { color: #F6FCFF; font-size: %dpx; font-weight: 900; background: transparent; }"
            % (18 if ultra else 21 if compact else 24)
        )
        self.hero_subtitle.setStyleSheet(
            "QLabel { color: rgba(219, 237, 249, 0.90); font-size: %dpx; font-weight: 500; background: transparent; }"
            % (9 if ultra else 10 if compact else 11)
        )
        self.summary_banner.setStyleSheet(
            "QLabel { color: rgba(207, 229, 244, 0.88); font-size: %dpx; font-weight: 600; background: transparent; }"
            % (9 if ultra else 10)
        )

        section_style = "QLabel#SectionTitle { color: #F4FCFF; font-size: %dpx; font-weight: 800; background: transparent; }" % (
            10 if ultra else 11 if compact else 12
        )
        self.visual_title.setStyleSheet(section_style)
        self.context_title.setStyleSheet(section_style)
        self.quick_title.setStyleSheet(section_style)

        info_style = "QLabel { color: rgba(214, 235, 248, 0.86); font-size: %dpx; font-weight: 500; background: transparent; }" % (
            9 if ultra else 10
        )
        for label in (self.context_line_1, self.context_line_2, self.context_line_3, self.context_line_4, self.context_note, self.quick_text):
            label.setStyleSheet(info_style)

        for button, width_value, height_value in (
            (self.back_button, 84 if ultra else 92 if compact else 96, 34 if ultra else 38 if compact else 40),
            (self.refresh_button, 124 if ultra else 148 if compact else 168, 34 if ultra else 38 if compact else 40),
            (self.qr_button, 124 if ultra else 148 if compact else 168, 34 if ultra else 38 if compact else 40),
            (self.consult_button, 124 if ultra else 148 if compact else 168, 34 if ultra else 38 if compact else 40),
            (self.bottom_back_button, 114 if ultra else 142 if compact else 160, 34 if ultra else 38 if compact else 40),
            (self.bottom_refresh_button, 96 if ultra else 112 if compact else 120, 34 if ultra else 38 if compact else 40),
            (self.bottom_qr_button, 96 if ultra else 112 if compact else 120, 34 if ultra else 38 if compact else 40),
            (self.bottom_consult_button, 96 if ultra else 112 if compact else 120, 34 if ultra else 38 if compact else 40),
        ):
            button.setMinimumWidth(width_value)
            button.setMaximumHeight(height_value)
            button.setMinimumHeight(height_value)

    # =========================================================================
    # Lifecycle
    # =========================================================================

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_responsive_layout(force=True)
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
        self._status_message = safe_str(snapshot.get("status_message"), "Respiratory detail loaded.").strip()

        self._apply_snapshot_to_ui()
        self.detail_loaded.emit(self.diagnostics())
        self.detail_refreshed.emit(self.diagnostics())

    def _load_detail_snapshot(self) -> Dict[str, Any]:
        payload = self._read_session_payload()
        measurements = self._normalize_measurements(payload)
        thresholds = self._read_rr_thresholds()

        rr_value = measurements.get(METRIC_RESPIRATORY_RATE)
        insight = _build_rr_interpretation(
            rr_value if isinstance(rr_value, int) else None,
            thresholds,
        )

        diagnosis_item = self._read_rr_diagnosis_item(payload)
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
            "status_message": "Respiratory detail snapshot loaded from active session data.",
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

        raw_rr = raw_measurements.get(
            METRIC_RESPIRATORY_RATE,
            raw_measurements.get(
                "rr",
                raw_measurements.get(
                    "resp_rate",
                    raw_measurements.get("breaths_per_minute", payload.get("respiratory_rate")),
                ),
            ),
        )

        return {
            METRIC_RESPIRATORY_RATE: _normalize_rr(raw_rr),
        }

    def _read_rr_thresholds(self) -> Dict[str, float]:
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
                                if METRIC_RESPIRATORY_RATE in raw and isinstance(raw.get(METRIC_RESPIRATORY_RATE), Mapping):
                                    thresholds = raw.get(METRIC_RESPIRATORY_RATE)  # type: ignore[assignment]
                                    break
                                profiles = raw.get("profiles", {})
                                if isinstance(profiles, Mapping) and METRIC_RESPIRATORY_RATE in profiles and isinstance(profiles.get(METRIC_RESPIRATORY_RATE), Mapping):
                                    thresholds = profiles.get(METRIC_RESPIRATORY_RATE)  # type: ignore[assignment]
                                    break
                                if "rr" in raw and isinstance(raw.get("rr"), Mapping):
                                    thresholds = raw.get("rr")  # type: ignore[assignment]
                                    break
                                if "respiratory_rate" in raw and isinstance(raw.get("respiratory_rate"), Mapping):
                                    thresholds = raw.get("respiratory_rate")  # type: ignore[assignment]
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
                                    if METRIC_RESPIRATORY_RATE in raw and isinstance(raw.get(METRIC_RESPIRATORY_RATE), Mapping):
                                        thresholds = raw.get(METRIC_RESPIRATORY_RATE)  # type: ignore[assignment]
                                        break
                                    profiles = raw.get("profiles", {})
                                    if isinstance(profiles, Mapping) and METRIC_RESPIRATORY_RATE in profiles and isinstance(profiles.get(METRIC_RESPIRATORY_RATE), Mapping):
                                        thresholds = profiles.get(METRIC_RESPIRATORY_RATE)  # type: ignore[assignment]
                                        break
                                    if "rr" in raw and isinstance(raw.get("rr"), Mapping):
                                        thresholds = raw.get("rr")  # type: ignore[assignment]
                                        break
                                    if "respiratory_rate" in raw and isinstance(raw.get("respiratory_rate"), Mapping):
                                        thresholds = raw.get("respiratory_rate")  # type: ignore[assignment]
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
                        if isinstance(raw, Mapping):
                            if METRIC_RESPIRATORY_RATE in raw and isinstance(raw.get(METRIC_RESPIRATORY_RATE), Mapping):
                                thresholds = raw.get(METRIC_RESPIRATORY_RATE)  # type: ignore[assignment]
                                break
                            if "rr" in raw and isinstance(raw.get("rr"), Mapping):
                                thresholds = raw.get("rr")  # type: ignore[assignment]
                                break
                            if "respiratory_rate" in raw and isinstance(raw.get("respiratory_rate"), Mapping):
                                thresholds = raw.get("respiratory_rate")  # type: ignore[assignment]
                                break
            except Exception:
                pass

        if thresholds is None:
            try:
                if self.app_state is not None:
                    for attr_name in ("threshold_profiles", "parameter_profiles", "health_rule_profiles"):
                        if hasattr(self.app_state, attr_name):
                            raw = getattr(self.app_state, attr_name)
                            if isinstance(raw, Mapping):
                                if METRIC_RESPIRATORY_RATE in raw and isinstance(raw.get(METRIC_RESPIRATORY_RATE), Mapping):
                                    thresholds = raw.get(METRIC_RESPIRATORY_RATE)  # type: ignore[assignment]
                                    break
                                if "rr" in raw and isinstance(raw.get("rr"), Mapping):
                                    thresholds = raw.get("rr")  # type: ignore[assignment]
                                    break
                                if "respiratory_rate" in raw and isinstance(raw.get("respiratory_rate"), Mapping):
                                    thresholds = raw.get("respiratory_rate")  # type: ignore[assignment]
                                    break
            except Exception:
                pass

        return _normalize_rr_thresholds(thresholds)

    def _read_rr_diagnosis_item(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        raw_classes = payload.get("classifications", {})
        if isinstance(raw_classes, Mapping):
            raw_item = raw_classes.get(
                METRIC_RESPIRATORY_RATE,
                raw_classes.get("rr", raw_classes.get("respiratory_rate")),
            )
            if isinstance(raw_item, Mapping):
                return dict(raw_item)

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
                                item = classifications.get(
                                    METRIC_RESPIRATORY_RATE,
                                    classifications.get("rr", classifications.get("respiratory_rate")),
                                )
                                if isinstance(item, Mapping):
                                    return dict(item)
            return {}
        except Exception:
            return {}

    # =========================================================================
    # UI binding
    # =========================================================================

    def _apply_snapshot_to_ui(self) -> None:
        rr_value = self._measurements.get(METRIC_RESPIRATORY_RATE)
        severity = safe_str(self._insight.get("severity"), "unknown").strip().lower()
        label = safe_str(self._insight.get("label"), "Respiratory Rate").strip() or "Respiratory Rate"
        accent_hex = safe_str(self._insight.get("accent_hex"), _accent_for_state(severity)).strip() or _accent_for_state(severity)

        # pills
        self.category_pill.setText(label)
        self._apply_pill_style(self.category_pill, accent_hex)

        self.value_pill.setText(f"RR { _format_num(rr_value, 0, ' bpm') }")
        self._apply_pill_style(self.value_pill, "#67D8FF")

        self.status_pill.setText(severity.title() if severity else "Ready")
        self._apply_pill_style(self.status_pill, accent_hex)

        # chips
        self._apply_header_chip_style(self.metric_chip, "#67D8FF")
        self._apply_header_chip_style(self.range_chip, accent_hex)
        self._apply_header_chip_style(self.guidance_chip, "#39D8FF")

        # stats
        self.stat_rr.set_payload(
            value=_format_num(rr_value, 0, " bpm"),
            subtitle="Current normalized breathing-rate reading used by the kiosk.",
            accent_hex=accent_hex,
        )
        self.stat_range.set_payload(
            value=f"{self._thresholds['normal_low']:.0f}–{self._thresholds['normal_high']:.0f} bpm",
            subtitle="Preferred resting reference band used for normal status.",
            accent_hex="#42E393",
        )
        self.stat_alert.set_payload(
            value=f"≥ {self._thresholds['warning_high']:.0f} bpm",
            subtitle="Higher respiratory-rate band requiring greater attention.",
            accent_hex="#FFA14D",
        )
        self.stat_status.set_payload(
            value=label,
            subtitle=safe_str(self._insight.get("summary"), "").strip(),
            accent_hex=accent_hex,
        )

        # chart widget
        self.chart_widget.set_payload(
            rr_value=None if rr_value in (None, "") else safe_int(rr_value, 0),
            label=label,
            thresholds=self._thresholds,
            accent_hex=accent_hex,
        )

        # range highlights
        active_band = safe_str(self._insight.get("active_band"), "").strip().lower()
        self.band_critical_low.set_active(active_band == "critical_low", "#FF6E88")
        self.band_low.set_active(active_band == "low", "#FFD25E")
        self.band_normal.set_active(active_band == "normal", "#42E393")
        self.band_high.set_active(active_band == "high", "#FFA14D")
        self.band_critical_high.set_active(active_band == "critical_high", "#FF6E88")

        # summary
        lines = {
            1: f"Current reading: {_format_num(rr_value, 0, ' bpm')}.",
            2: safe_str(self._insight.get("detail"), "").strip(),
            3: f"Recommendation: {safe_str(self._insight.get('recommendation'), '').strip()}",
            4: (
                f"Reference bands: critical low < {self._thresholds['warning_low']:.0f}, "
                f"healthy {self._thresholds['normal_low']:.0f}–{self._thresholds['normal_high']:.0f}, "
                f"elevated {self._thresholds['normal_high'] + 1:.0f}–{self._thresholds['warning_high'] - 1:.0f}, "
                f"very high ≥ {self._thresholds['warning_high']:.0f}."
            ),
        }

        self.summary_card.set_payload(
            title="Respiratory Interpretation",
            state_text=label,
            summary=safe_str(self._insight.get("summary"), "").strip() or "Respiratory summary unavailable.",
            lines=lines,
            accent_hex=accent_hex,
        )

        # context
        self.context_line_1.setText("Preferred unit: breaths per minute")
        self.context_line_2.setText("Input normalization: values are cleaned into an integer bpm display")
        self.context_line_3.setText(
            f"Threshold source: low {self._thresholds['warning_low']:.0f}, healthy {self._thresholds['normal_low']:.0f}–{self._thresholds['normal_high']:.0f}, high {self._thresholds['warning_high']:.0f}+"
        )
        self.context_line_4.setText(f"Status: {self._status_message}")

        # buttons
        self._set_button_accent(self.refresh_button, "#39D8FF")
        self._set_button_accent(self.bottom_refresh_button, "#39D8FF")
        self._set_button_accent(self.qr_button, "#67D8FF")
        self._set_button_accent(self.bottom_qr_button, "#67D8FF")
        self._set_button_accent(self.consult_button, accent_hex if severity in {"attention", "warning", "critical"} else "#42E393")
        self._set_button_accent(self.bottom_consult_button, accent_hex if severity in {"attention", "warning", "critical"} else "#42E393")

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
            "chart_overlay_path": self._chart_overlay_path,
        }