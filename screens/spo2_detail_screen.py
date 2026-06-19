"""
screens/spo2_detail_screen.py

Premium SpO₂ detail screen for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the public-facing SpO₂ explanation screen opened from:
    - screens/results_screen.py
- It allows the user or operator to:
    - inspect the current oxygen saturation value in a premium detailed view
    - understand the category and severity of the SpO₂ result
    - review the reference bands used by the kiosk
    - see the active oxygen band highlighted in a polished medical-kiosk style
    - navigate back to results or continue to QR / consult workflows
- It is designed specifically for:
    - Raspberry Pi 4B touchscreen kiosk deployment
    - 1024x600 kiosk resolution
    - laptop demo mode
- It provides:
    - glossy futuristic blue medical UI
    - resilient loading from session_service / diagnosis_service / threshold_service
    - threshold-aware SpO₂ interpretation
    - safe normalization for inconsistent oxygen saturation values
    - safe fallback behavior when services are still being integrated
    - maintainable self-contained drawing logic for the SpO₂ band widget

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
- widgets/spo2_band_widget.py

Navigation targets this screen is designed to link to:
- screens/results_screen.py
- screens/qr_screen.py
- screens/consult_screen.py

Design goals:
- glossy futuristic blue medical UI
- informative but calm patient-facing detail screen
- strong readability at 1024x600
- premium oxygen-band visualization with active-band highlighting
- resilient integration while backend files continue evolving
"""

from __future__ import annotations

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
        METRIC_SPO2,
    )
except Exception:  # pragma: no cover
    SCREEN_RESULTS = "results"
    SCREEN_QR = "qr"
    SCREEN_CONSULT = "consult"
    METRIC_SPO2 = "spo2"

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

SPO2_WARNING_LOW = 90.0
SPO2_NORMAL_LOW = 96.0
SPO2_NORMAL_HIGH = 100.0
SPO2_WARNING_HIGH = 100.0

SPO2_SCALE_MIN = 70.0
SPO2_SCALE_MAX = 100.0


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


def _normalize_spo2(value: Any) -> Optional[int]:
    """
    Normalize a SpO₂ reading into an integer percentage.

    Accepts:
    - direct percentages like 97, 98.2
    - fractional style values like 0.97 or 0.985
    """
    if value in (None, ""):
        return None

    raw = safe_float(value, -1.0)
    if raw < 0:
        return None

    # Fractional saturation input
    if 0.0 <= raw <= 1.0:
        raw *= 100.0

    # Very small accidental scaled values remain invalid
    if raw < 40.0:
        return None

    # Cap sensor overrange to a safe display maximum
    raw = max(0.0, min(100.0, raw))
    return int(round(raw))


def _accent_for_state(state: str) -> str:
    text = safe_str(state, "").strip().lower()
    if text in {"critical", "critical low", "severe desaturation"}:
        return "#FF6E88"
    if text in {"warning", "low saturation"}:
        return "#FFA14D"
    if text in {"attention", "borderline"}:
        return "#FFD25E"
    if text in {"normal", "healthy"}:
        return "#42E393"
    return "#39D8FF"


def _normalize_spo2_thresholds(raw: Optional[Mapping[str, Any]]) -> Dict[str, float]:
    base = {
        "warning_low": SPO2_WARNING_LOW,
        "normal_low": SPO2_NORMAL_LOW,
        "normal_high": SPO2_NORMAL_HIGH,
        "warning_high": SPO2_WARNING_HIGH,
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

    # Keep practical SpO₂ upper limits sane
    warning_low = max(50.0, min(100.0, ordered[0]))
    normal_low = max(warning_low, min(100.0, ordered[1]))
    normal_high = max(normal_low, min(100.0, ordered[2]))
    warning_high = max(normal_high, min(100.0, ordered[3]))

    return {
        "warning_low": round(warning_low, 1),
        "normal_low": round(normal_low, 1),
        "normal_high": round(normal_high, 1),
        "warning_high": round(warning_high, 1),
    }


def _build_spo2_interpretation(
    spo2_value: Optional[int],
    thresholds: Mapping[str, float],
) -> Dict[str, Any]:
    if spo2_value is None:
        return {
            "label": "Unavailable",
            "severity": "unknown",
            "summary": "Oxygen saturation could not be interpreted because no valid SpO₂ reading is available.",
            "detail": "A missing or invalid SpO₂ value prevents proper oxygen saturation classification.",
            "recommendation": "Repeat the SpO₂ measurement with stable finger placement and reduced motion.",
            "active_band": "unknown",
            "accent_hex": "#39D8FF",
        }

    warning_low = safe_float(thresholds.get("warning_low"), SPO2_WARNING_LOW)
    normal_low = safe_float(thresholds.get("normal_low"), SPO2_NORMAL_LOW)
    normal_high = safe_float(thresholds.get("normal_high"), SPO2_NORMAL_HIGH)

    if spo2_value < warning_low:
        return {
            "label": "Critical Low",
            "severity": "critical",
            "summary": "Oxygen saturation is critically below the preferred healthy range.",
            "detail": "This level suggests marked desaturation and deserves urgent attention if the reading is real and persistent.",
            "recommendation": "Retake immediately to confirm stability. Seek urgent professional review if symptoms or a persistent low reading are present.",
            "active_band": "critical_low",
            "accent_hex": _accent_for_state("critical"),
        }

    if spo2_value < normal_low:
        return {
            "label": "Borderline Low",
            "severity": "attention",
            "summary": "Oxygen saturation is below the ideal reference band but not in the most critical category.",
            "detail": "This result may reflect measurement instability, peripheral circulation issues, or a true mild reduction in oxygen saturation.",
            "recommendation": "Repeat under stable conditions and review together with pulse, respiratory rate, and symptoms.",
            "active_band": "borderline",
            "accent_hex": _accent_for_state("attention"),
        }

    if spo2_value <= normal_high:
        return {
            "label": "Healthy",
            "severity": "normal",
            "summary": "Oxygen saturation falls within the healthy reference range used by the kiosk.",
            "detail": "This result is generally reassuring when considered with the full session results and symptoms.",
            "recommendation": "Routine handoff is usually sufficient unless other measurements raise concern.",
            "active_band": "healthy",
            "accent_hex": _accent_for_state("normal"),
        }

    return {
        "label": "Sensor High",
        "severity": "warning",
        "summary": "The reading exceeds the expected display ceiling and may reflect sensor overrange or inconsistent input scaling.",
        "detail": "SpO₂ values above 100 percent are not physiologically expected and usually point to scaling or acquisition issues.",
        "recommendation": "Review sensor normalization and repeat the measurement if necessary.",
        "active_band": "overrange",
        "accent_hex": _accent_for_state("warning"),
    }


# =============================================================================
# Internal widgets
# =============================================================================

class _Spo2BandFallbackWidget(QWidget):
    """
    Clean SpO₂ bar widget tuned for the compact 800x480 kiosk layout.
    """

    def __init__(self, overlay_path: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._overlay_pixmap = _pixmap_or_empty(overlay_path)
        self._spo2_value: Optional[int] = None
        self._thresholds = _normalize_spo2_thresholds(None)
        self._label = "SpO₂"
        self._accent_hex = "#39D8FF"
        self._compact = bool(IS_COMPACT_KIOSK or KIOSK_WIDTH <= 840 or KIOSK_HEIGHT <= 500)
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_payload(
        self,
        *,
        spo2_value: Optional[int],
        label: str,
        thresholds: Mapping[str, float],
        accent_hex: str,
    ) -> None:
        self._spo2_value = spo2_value
        self._label = safe_str(label, "SpO₂").strip() or "SpO₂"
        self._thresholds = _normalize_spo2_thresholds(thresholds)
        self._accent_hex = safe_str(accent_hex, "#39D8FF").strip() or "#39D8FF"
        self.update()

    def _value_to_ratio(self, value: float) -> float:
        clamped = max(SPO2_SCALE_MIN, min(SPO2_SCALE_MAX, float(value)))
        return (clamped - SPO2_SCALE_MIN) / (SPO2_SCALE_MAX - SPO2_SCALE_MIN)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect = QRectF(self.rect()).adjusted(10, 10, -10, -10)
        panel_path = QPainterPath()
        panel_path.addRoundedRect(rect, 24, 24)

        painter.save()
        painter.setClipPath(panel_path)
        painter.fillRect(rect, QColor(7, 22, 40, 226 if self._compact else 214))
        if (not self._compact) and (not self._overlay_pixmap.isNull()) and rect.width() > 220:
            overlay = self._overlay_pixmap.scaled(
                int(rect.width() * 0.58),
                int(rect.height() * 0.78),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.setOpacity(0.04)
            painter.drawPixmap(
                int(rect.left() + 18),
                int(rect.top() + max(10.0, (rect.height() - overlay.height()) / 2.0) - 4),
                overlay,
            )
            painter.setOpacity(1.0)
        painter.restore()

        painter.setPen(QPen(QColor(130, 215, 255, 48), 1.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 24, 24)

        warning_low = self._thresholds["warning_low"]
        normal_low = self._thresholds["normal_low"]
        normal_high = self._thresholds["normal_high"]

        bar_left = rect.left() + (72 if self._compact else 44)
        bar_right = rect.right() - (164 if self._compact else 168)
        if bar_right <= bar_left + 80:
            bar_right = rect.right() - 32
        bar_width = bar_right - bar_left
        bar_y = rect.center().y() + (8 if self._compact else 2)
        bar_height = 18 if self._compact else 16

        track_rect = QRectF(bar_left, bar_y - bar_height / 2.0, bar_width, bar_height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(12, 28, 48, 235))
        painter.drawRoundedRect(track_rect.adjusted(-3, -3, 3, 3), 12, 12)

        segments = [
            (SPO2_SCALE_MIN, warning_low, QColor("#FF6E88")),
            (warning_low, normal_low, QColor("#FFD25E")),
            (normal_low, normal_high, QColor("#42E393")),
        ]
        for start_v, end_v, color in segments:
            x1 = track_rect.left() + track_rect.width() * self._value_to_ratio(start_v)
            x2 = track_rect.left() + track_rect.width() * self._value_to_ratio(end_v)
            seg_rect = QRectF(min(x1, x2), track_rect.top(), max(10.0, abs(x2 - x1)), track_rect.height())
            painter.setBrush(color)
            painter.drawRoundedRect(seg_rect, track_rect.height() / 2.0, track_rect.height() / 2.0)

        painter.setBrush(QColor(255, 255, 255, 16))
        painter.drawRoundedRect(QRectF(track_rect.left(), track_rect.top(), track_rect.width(), track_rect.height() * 0.42), 8, 8)

        if not self._compact:
            painter.setFont(QFont("Inter", 9, QFont.Weight.DemiBold))
            painter.setPen(QColor(214, 234, 246, 192))
            label_y = track_rect.bottom() + 14
            ranges = [
                (SPO2_SCALE_MIN, warning_low, "Low"),
                (warning_low, normal_low, "Monitor"),
                (normal_low, normal_high, "Healthy"),
            ]
            for start_v, end_v, text_label in ranges:
                x1 = track_rect.left() + track_rect.width() * self._value_to_ratio(start_v)
                x2 = track_rect.left() + track_rect.width() * self._value_to_ratio(end_v)
                painter.drawText(QRectF(min(x1, x2) - 12, label_y, max(28.0, abs(x2 - x1)) + 24, 18), Qt.AlignmentFlag.AlignCenter, text_label)

        painter.setFont(QFont("Inter", 8, QFont.Weight.Medium))
        painter.setPen(QColor(190, 214, 232, 154))
        tick_values = [70, 80, 90, 100] if self._compact else [70, 75, 80, 85, 90, 95, 100]
        for tick in tick_values:
            tick_x = track_rect.left() + track_rect.width() * self._value_to_ratio(float(tick))
            painter.drawLine(int(tick_x), int(track_rect.bottom() + 2), int(tick_x), int(track_rect.bottom() + 9))
            painter.drawText(QRectF(tick_x - 18, track_rect.bottom() + 10, 36, 14), Qt.AlignmentFlag.AlignCenter, str(tick))

        display_value = self._spo2_value if self._spo2_value is not None else safe_int(normal_low, 96)
        marker_x = track_rect.left() + track_rect.width() * self._value_to_ratio(float(display_value))
        accent = QColor(self._accent_hex)
        painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 220), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(int(marker_x), int(track_rect.top() - 18), int(marker_x), int(track_rect.bottom() + 30))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 255))
        painter.drawEllipse(QRectF(marker_x - 15, track_rect.top() - 26, 30, 30))
        painter.setBrush(QColor("#F7FCFF"))
        painter.drawEllipse(QRectF(marker_x - 6, track_rect.top() - 17, 12, 12))

        callout_rect = QRectF(rect.right() - (138 if self._compact else 144), rect.center().y() - (36 if self._compact else 42), 116 if self._compact else 122, 72 if self._compact else 82)
        painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 78), 1.3))
        painter.setBrush(QColor(10, 25, 45, 234))
        painter.drawRoundedRect(callout_rect, 20, 20)

        painter.setPen(QColor("#F6FCFF"))
        painter.setFont(QFont("Inter", 20 if self._compact else 22, QFont.Weight.Bold))
        painter.drawText(QRectF(callout_rect.left(), callout_rect.top() + 8, callout_rect.width(), 26), Qt.AlignmentFlag.AlignCenter, f"{display_value}%")
        painter.setFont(QFont("Inter", 10 if self._compact else 11, QFont.Weight.DemiBold))
        painter.setPen(QColor(215, 235, 247, 224))
        painter.drawText(QRectF(callout_rect.left(), callout_rect.top() + (36 if self._compact else 42), callout_rect.width(), 18), Qt.AlignmentFlag.AlignCenter, self._label)

        painter.end()


class _InfoStatCard(QFrame):
    """
    Small premium stat card for SpO₂ detail metrics.
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
        self._compact_mode = False

        self.setObjectName("Spo2InfoStatCard")
        self.setMinimumHeight(82)
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
        self.subtitle_label.setText(safe_str(subtitle, "").strip())
        self.subtitle_label.setVisible(not self._compact_mode and bool(self.subtitle_label.text().strip()))
        self._apply_style()

    def set_compact_mode(self, compact: bool) -> None:
        self._compact_mode = bool(compact)
        self.subtitle_label.setVisible(not self._compact_mode and bool(self.subtitle_label.text().strip()))
        self.setMinimumHeight(72 if self._compact_mode else 82)
        try:
            layout = self.layout()
            if layout is not None:
                layout.setContentsMargins(12 if self._compact_mode else 12, 10 if self._compact_mode else 10, 12, 10 if self._compact_mode else 10)
                layout.setSpacing(2 if self._compact_mode else 3)
        except Exception:
            pass
        self._apply_style()

    def _apply_style(self) -> None:
        accent = QColor(self._accent_hex)

        self.setStyleSheet(
            f"""
            QFrame#Spo2InfoStatCard {{
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.20);
                border-radius: 18px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(8, 26, 48, 0.96),
                    stop:1 rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.16)
                );
            }}
            """
        )
        title_px = 9 if self._compact_mode else 10
        value_px = 18 if self._compact_mode else 24
        subtitle_px = 8 if self._compact_mode else 9

        self.title_label.setStyleSheet(
            f"""
            QLabel {{
                color: rgba(219, 237, 249, 0.82);
                font-size: {title_px}px;
                font-weight: 700;
                background: transparent;
            }}
            """
        )
        self.value_label.setStyleSheet(
            f"""
            QLabel {{
                color: #F6FCFF;
                font-size: {value_px}px;
                font-weight: 900;
                background: transparent;
            }}
            """
        )
        self.subtitle_label.setStyleSheet(
            f"""
            QLabel {{
                color: rgba(191, 214, 232, 0.80);
                font-size: {subtitle_px}px;
                font-weight: 500;
                background: transparent;
            }}
            """
        )


class _RangeBandCard(QFrame):
    """
    Premium SpO₂ range band card with selectable highlight.
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

        self.setObjectName("Spo2RangeBandCard")
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
            QFrame#Spo2RangeBandCard {{
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

        self.setObjectName("Spo2SummaryCard")
        self.setMinimumHeight(214)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(8)

        top_row = QWidget(self)
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        self.title_label = QLabel("SpO₂ Interpretation", top_row)
        self.state_chip = QLabel("Pending", top_row)

        top_layout.addWidget(self.title_label)
        top_layout.addStretch(1)
        top_layout.addWidget(self.state_chip)

        self.summary_label = QLabel(
            "SpO₂ detail summary will appear here when a valid measurement is available.",
            self,
        )
        self.summary_label.setWordWrap(True)

        self.line_1 = QLabel("• Oxygen saturation bands help classify the reading.", self)
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
        self.title_label.setText(safe_str(title, "SpO₂ Interpretation").strip() or "SpO₂ Interpretation")
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
            QFrame#Spo2SummaryCard {{
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

class Spo2DetailScreen(QFrame):
    """
    Premium SpO₂ detail screen.

    Main responsibilities:
    - load oxygen saturation value from active runtime session
    - normalize to a clean percentage display
    - interpret SpO₂ against threshold profiles
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

        self._logger = logger.bind(component="Spo2DetailScreen")

        self.navigator = navigator
        self.app_state = app_state
        self.services = dict(services or {})
        self.animation_manager = animation_manager
        self.theme_manager = theme_manager

        self._payload: Dict[str, Any] = {}
        self._measurements: Dict[str, Any] = {}
        self._thresholds: Dict[str, float] = _normalize_spo2_thresholds(None)
        self._insight: Dict[str, Any] = {}
        self._status_message = "SpO₂ detail view is ready to load."

        self._is_compact = bool(IS_COMPACT_KIOSK or KIOSK_WIDTH <= 840 or KIOSK_HEIGHT <= 500)
        self._is_ultra_compact = bool(KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480)

        self._background_path = _resolve_asset("backgrounds/spo2_detail_bg.png")
        self._logo_small_path = _resolve_asset("logos/cst_logo_small.png")
        self._bands_overlay_path = _resolve_asset("detail_graphics/spo2_bands.png")

        self._background_pixmap = _pixmap_or_empty(self._background_path)
        self._logo_pixmap = _pixmap_or_empty(self._logo_small_path)

        self.setObjectName("Spo2DetailScreen")
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
        root.setContentsMargins(18, 12, 18, 12)
        root.setSpacing(10)

        # ---------------------------------------------------------------------
        # Top bar
        # ---------------------------------------------------------------------
        self.top_bar = QWidget(self)
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(10)

        self.back_button = self._create_button("Back", variant="secondary", min_width=96, parent=self.top_bar)
        self.back_button.clicked.connect(self._handle_back_clicked)

        self.logo_badge = QLabel(self.top_bar)
        self.logo_badge.setObjectName("LogoBadge")
        self.logo_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_label_pixmap(self.logo_badge, self._logo_pixmap, 24)

        self.top_title = QLabel("Blood Oxygen Detail", self.top_bar)
        self.top_title.setObjectName("TopTitle")

        self.category_pill = QLabel("Category", self.top_bar)
        self.category_pill.setObjectName("RuntimePill")

        self.value_pill = QLabel("SpO₂ --", self.top_bar)
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
        self.header_card.setObjectName("Spo2HeaderCard")

        header_layout = QVBoxLayout(self.header_card)
        header_layout.setContentsMargins(16, 14, 16, 14)
        header_layout.setSpacing(6)

        self.hero_title = QLabel(self.header_card)
        self.hero_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.hero_subtitle = QLabel(self.header_card)
        self.hero_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hero_subtitle.setWordWrap(True)

        self.header_chip_row = QWidget(self.header_card)
        chip_layout = QHBoxLayout(self.header_chip_row)
        chip_layout.setContentsMargins(0, 0, 0, 0)
        chip_layout.setSpacing(8)

        self.metric_chip = QLabel("Oxygen Saturation", self.header_chip_row)
        self.metric_chip.setObjectName("HeaderChip")

        self.range_chip = QLabel("Reference Range", self.header_chip_row)
        self.range_chip.setObjectName("HeaderChip")

        self.guidance_chip = QLabel("Status Review", self.header_chip_row)
        self.guidance_chip.setObjectName("HeaderChip")

        chip_layout.addStretch(1)
        chip_layout.addWidget(self.metric_chip)
        chip_layout.addWidget(self.range_chip)
        chip_layout.addWidget(self.guidance_chip)
        chip_layout.addStretch(1)

        self.summary_banner = QLabel(
            "Peripheral oxygen saturation should be reviewed together with pulse, breathing, and symptoms.",
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
        stats_layout.setSpacing(10)

        self.stat_spo2 = _InfoStatCard("SpO₂", value="--", subtitle="Current oxygen saturation.")
        self.stat_range = _InfoStatCard("Healthy Band", value="--", subtitle="Preferred healthy band.")
        self.stat_alert = _InfoStatCard("Low Threshold", value="--", subtitle="Review threshold.")
        self.stat_status = _InfoStatCard("Status", value="--", subtitle="Active interpretation.")

        stats_layout.addWidget(self.stat_spo2, 1)
        stats_layout.addWidget(self.stat_range, 1)
        stats_layout.addWidget(self.stat_alert, 1)
        stats_layout.addWidget(self.stat_status, 1)

        # ---------------------------------------------------------------------
        # Content row
        # ---------------------------------------------------------------------
        self.content_row = QWidget(self)
        content_layout = QHBoxLayout(self.content_row)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)

        self.visual_panel = QFrame(self.content_row)
        self.visual_panel.setObjectName("VisualPanel")
        self.visual_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        visual_layout = QVBoxLayout(self.visual_panel)
        visual_layout.setContentsMargins(14, 12, 14, 12)
        visual_layout.setSpacing(8)

        self.visual_title = QLabel("Oxygen Saturation Scale", self.visual_panel)
        self.visual_title.setObjectName("SectionTitle")

        self.band_widget = _Spo2BandFallbackWidget(self._bands_overlay_path, self.visual_panel)

        self.range_row_top = QWidget(self.visual_panel)
        self.range_top_layout = QHBoxLayout(self.range_row_top)
        self.range_top_layout.setContentsMargins(0, 0, 0, 0)
        self.range_top_layout.setSpacing(8)

        self.band_critical = _RangeBandCard("Critical Low", f"< {SPO2_WARNING_LOW:.0f}%")
        self.band_borderline = _RangeBandCard("Borderline", f"{SPO2_WARNING_LOW:.0f}–{SPO2_NORMAL_LOW - 1:.0f}%")
        self.band_healthy = _RangeBandCard("Healthy", f"{SPO2_NORMAL_LOW:.0f}–{SPO2_NORMAL_HIGH:.0f}%")

        self.range_top_layout.addWidget(self.band_critical)
        self.range_top_layout.addWidget(self.band_borderline)
        self.range_top_layout.addWidget(self.band_healthy)

        self.range_row_bottom = QWidget(self.visual_panel)
        self.range_bottom_layout = QHBoxLayout(self.range_row_bottom)
        self.range_bottom_layout.setContentsMargins(0, 0, 0, 0)
        self.range_bottom_layout.setSpacing(8)

        self.band_support = _RangeBandCard("Reference Note", "Read with pulse and symptoms")
        self.band_overrange = _RangeBandCard("Sensor High", "> 100%")

        self.range_bottom_layout.addWidget(self.band_support)
        self.range_bottom_layout.addWidget(self.band_overrange)

        visual_layout.addWidget(self.visual_title)
        visual_layout.addWidget(self.band_widget, 1)
        visual_layout.addWidget(self.range_row_top)
        visual_layout.addWidget(self.range_row_bottom)

        self.side_panel = QWidget(self.content_row)
        side_layout = QVBoxLayout(self.side_panel)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(10)
        self.side_panel.setMinimumWidth(300)
        self.side_panel.setMaximumWidth(340)

        self.summary_card = _SummaryCard(self.side_panel)

        self.context_card = QFrame(self.side_panel)
        self.context_card.setObjectName("InfoCard")
        context_layout = QVBoxLayout(self.context_card)
        context_layout.setContentsMargins(16, 14, 16, 14)
        context_layout.setSpacing(7)

        self.context_title = QLabel("Measurement Context", self.context_card)
        self.context_title.setObjectName("SectionTitle")
        self.context_line_1 = QLabel("Preferred unit: percentage saturation", self.context_card)
        self.context_line_2 = QLabel("Input normalization: active", self.context_card)
        self.context_line_3 = QLabel("Threshold source: pending", self.context_card)
        self.context_line_4 = QLabel("Status: pending", self.context_card)
        self.context_note = QLabel(
            "Low readings can be affected by motion, finger placement, cold extremities, or weak circulation.",
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
            "Open the QR handoff or consult screen after reviewing the oxygen saturation status.",
            self.quick_card,
        )
        self.quick_text.setWordWrap(True)

        self.refresh_button = self._create_button("Refresh Detail", variant="ghost", min_width=160, parent=self.quick_card)
        self.refresh_button.clicked.connect(self.reload_detail)

        self.qr_button = self._create_button("Open QR", variant="secondary", min_width=160, parent=self.quick_card)
        self.qr_button.clicked.connect(self._handle_qr_clicked)

        self.consult_button = self._create_button("Consult", variant="primary", min_width=160, parent=self.quick_card)
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

        self.bottom_back_button = self._create_button("Results", variant="secondary", min_width=150, parent=self.action_row)
        self.bottom_back_button.clicked.connect(self._handle_back_clicked)

        self.bottom_refresh_button = self._create_button("Refresh", variant="ghost", min_width=120, parent=self.action_row)
        self.bottom_refresh_button.clicked.connect(self.reload_detail)

        self.bottom_qr_button = self._create_button("QR", variant="secondary", min_width=110, parent=self.action_row)
        self.bottom_qr_button.clicked.connect(self._handle_qr_clicked)

        self.bottom_consult_button = self._create_button("Consult", variant="primary", min_width=130, parent=self.action_row)
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
            QFrame#Spo2DetailScreen {
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

            QFrame#Spo2HeaderCard {
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
                self.hero_title.set_text("Oxygen saturation detail")
            except Exception:
                self.hero_title.setText("Blood Oxygen Detail")
        else:
            self.hero_title.setText("Blood Oxygen Detail")

        self.hero_subtitle.setText(
            "SpO₂ reflects peripheral oxygen saturation and is one of the most important supportive indicators when reviewing respiratory well-being."
        )
        self.summary_banner.setText(
            "This screen highlights the current SpO₂ band, the reference thresholds, and supportive next-step guidance."
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
        self._status_message = safe_str(snapshot.get("status_message"), "SpO₂ detail loaded.").strip()

        self._apply_snapshot_to_ui()
        self.detail_loaded.emit(self.diagnostics())
        self.detail_refreshed.emit(self.diagnostics())

    def _load_detail_snapshot(self) -> Dict[str, Any]:
        payload = self._read_session_payload()
        measurements = self._normalize_measurements(payload)
        thresholds = self._read_spo2_thresholds()

        spo2_value = measurements.get(METRIC_SPO2)
        insight = _build_spo2_interpretation(
            spo2_value if isinstance(spo2_value, int) else None,
            thresholds,
        )

        diagnosis_item = self._read_spo2_diagnosis_item(payload)
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
            "status_message": "SpO₂ detail snapshot loaded from active session data.",
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

        raw_spo2 = raw_measurements.get(
            METRIC_SPO2,
            raw_measurements.get("oxygen_saturation", payload.get("spo2")),
        )

        return {
            METRIC_SPO2: _normalize_spo2(raw_spo2),
        }

    def _read_spo2_thresholds(self) -> Dict[str, float]:
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
                                if METRIC_SPO2 in raw and isinstance(raw.get(METRIC_SPO2), Mapping):
                                    thresholds = raw.get(METRIC_SPO2)  # type: ignore[assignment]
                                    break
                                profiles = raw.get("profiles", {})
                                if isinstance(profiles, Mapping) and METRIC_SPO2 in profiles and isinstance(profiles.get(METRIC_SPO2), Mapping):
                                    thresholds = profiles.get(METRIC_SPO2)  # type: ignore[assignment]
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
                                    if METRIC_SPO2 in raw and isinstance(raw.get(METRIC_SPO2), Mapping):
                                        thresholds = raw.get(METRIC_SPO2)  # type: ignore[assignment]
                                        break
                                    profiles = raw.get("profiles", {})
                                    if isinstance(profiles, Mapping) and METRIC_SPO2 in profiles and isinstance(profiles.get(METRIC_SPO2), Mapping):
                                        thresholds = profiles.get(METRIC_SPO2)  # type: ignore[assignment]
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
                        if isinstance(raw, Mapping) and METRIC_SPO2 in raw and isinstance(raw.get(METRIC_SPO2), Mapping):
                            thresholds = raw.get(METRIC_SPO2)  # type: ignore[assignment]
                            break
            except Exception:
                pass

        if thresholds is None:
            try:
                if self.app_state is not None:
                    for attr_name in ("threshold_profiles", "parameter_profiles", "health_rule_profiles"):
                        if hasattr(self.app_state, attr_name):
                            raw = getattr(self.app_state, attr_name)
                            if isinstance(raw, Mapping) and METRIC_SPO2 in raw and isinstance(raw.get(METRIC_SPO2), Mapping):
                                thresholds = raw.get(METRIC_SPO2)  # type: ignore[assignment]
                                break
            except Exception:
                pass

        return _normalize_spo2_thresholds(thresholds)

    def _read_spo2_diagnosis_item(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        raw_classes = payload.get("classifications", {})
        if isinstance(raw_classes, Mapping):
            raw_item = raw_classes.get(METRIC_SPO2)
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
                                item = classifications.get(METRIC_SPO2)
                                if isinstance(item, Mapping):
                                    return dict(item)
            return {}
        except Exception:
            return {}

    # =========================================================================
    # UI binding
    # =========================================================================

    def _apply_snapshot_to_ui(self) -> None:
        spo2_value = self._measurements.get(METRIC_SPO2)
        severity = safe_str(self._insight.get("severity"), "unknown").strip().lower()
        label = safe_str(self._insight.get("label"), "SpO₂").strip() or "SpO₂"
        accent_hex = safe_str(self._insight.get("accent_hex"), _accent_for_state(severity)).strip() or _accent_for_state(severity)

        # pills
        self.category_pill.setText(label)
        self._apply_pill_style(self.category_pill, accent_hex)

        self.value_pill.setText(f"SpO₂ {_format_num(spo2_value, 0, '%')}")
        self._apply_pill_style(self.value_pill, "#67D8FF")

        self.status_pill.setText(severity.title() if severity else "Ready")
        self._apply_pill_style(self.status_pill, accent_hex)

        # chips
        self._apply_header_chip_style(self.metric_chip, "#67D8FF")
        self._apply_header_chip_style(self.range_chip, accent_hex)
        self._apply_header_chip_style(self.guidance_chip, "#39D8FF")

        # stats
        self.stat_spo2.set_payload(
            value=_format_num(spo2_value, 0, "%"),
            subtitle="Current normalized oxygen saturation used by the kiosk.",
            accent_hex=accent_hex,
        )
        self.stat_range.set_payload(
            value=f"{self._thresholds['normal_low']:.0f}–{self._thresholds['normal_high']:.0f}%",
            subtitle="Preferred healthy saturation band used for normal status.",
            accent_hex="#42E393",
        )
        self.stat_alert.set_payload(
            value=f"< {self._thresholds['warning_low']:.0f}%",
            subtitle="Lower saturation band requiring greater attention.",
            accent_hex="#FFA14D",
        )
        self.stat_status.set_payload(
            value=label,
            subtitle=safe_str(self._insight.get("summary"), "").strip(),
            accent_hex=accent_hex,
        )

        # band widget
        self.band_widget.set_payload(
            spo2_value=None if spo2_value in (None, "") else safe_int(spo2_value, 0),
            label=label,
            thresholds=self._thresholds,
            accent_hex=accent_hex,
        )

        # range highlights
        active_band = safe_str(self._insight.get("active_band"), "").strip().lower()
        self.band_critical.set_active(active_band == "critical_low", "#FF6E88")
        self.band_borderline.set_active(active_band == "borderline", "#FFD25E")
        self.band_healthy.set_active(active_band == "healthy", "#42E393")
        self.band_overrange.set_active(active_band == "overrange", "#FFA14D")
        self.band_support.set_active(active_band not in {"critical_low", "borderline", "healthy", "overrange"}, "#39D8FF")

        # summary
        lines = {
            1: f"Current reading: {_format_num(spo2_value, 0, '%')}.",
            2: safe_str(self._insight.get("detail"), "").strip(),
            3: f"Recommendation: {safe_str(self._insight.get('recommendation'), '').strip()}",
            4: (
                f"Reference bands: critical < {self._thresholds['warning_low']:.0f}, "
                f"borderline {self._thresholds['warning_low']:.0f}–{self._thresholds['normal_low'] - 1:.0f}, "
                f"healthy {self._thresholds['normal_low']:.0f}–{self._thresholds['normal_high']:.0f}."
            ),
        }

        self.summary_card.set_payload(
            title="SpO₂ Interpretation",
            state_text=label,
            summary=safe_str(self._insight.get("summary"), "").strip() or "SpO₂ summary unavailable.",
            lines=lines,
            accent_hex=accent_hex,
        )

        # context
        self.context_line_1.setText("Preferred unit: percentage saturation")
        self.context_line_2.setText("Input normalization: fractional inputs are converted to percentage when needed")
        self.context_line_3.setText(
            f"Threshold source: low {self._thresholds['warning_low']:.0f}, healthy {self._thresholds['normal_low']:.0f}–{self._thresholds['normal_high']:.0f}"
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
            self.content_row.layout().setSpacing(0 if compact else 12)

        if hasattr(self, 'visual_panel'):
            self.visual_panel.layout().setContentsMargins(10 if compact else 14, 9 if compact else 12, 10 if compact else 14, 9 if compact else 12)
            self.visual_panel.layout().setSpacing(7 if compact else 9)

        if hasattr(self, 'side_panel'):
            self.side_panel.layout().setSpacing(8 if compact else 10)
            self.side_panel.setMinimumWidth(242 if ultra else (252 if compact else 300))
            self.side_panel.setMaximumWidth(278 if ultra else (290 if compact else 350))
            self.side_panel.setVisible(not compact)

        self.band_widget.setMinimumHeight(180 if ultra else (196 if compact else 250))
        self.summary_card.setMinimumHeight(150 if ultra else (176 if compact else 214))
        self.context_card.setMinimumHeight(118 if ultra else (132 if compact else 156))
        self.quick_card.setMinimumHeight(120 if ultra else (136 if compact else 158))

        self.stat_spo2.set_compact_mode(compact)
        self.stat_range.set_compact_mode(compact)
        self.stat_alert.set_compact_mode(compact)
        self.stat_status.set_compact_mode(compact)

        self.range_row_top.setVisible(not compact)
        self.range_row_bottom.setVisible(not compact)

        self.hero_title.setText('Blood Oxygen Detail')
        self.hero_subtitle.setVisible(not compact)
        self.summary_banner.setVisible(True)
        self.header_chip_row.setVisible(not compact)
        self.quick_text.setVisible(not compact)
        self.context_note.setVisible(not compact)
        self.logo_badge.setVisible(not ultra)

        if compact:
            self.summary_banner.setText('Current reading is shown with the highlighted oxygen range and status.')
        else:
            self.summary_banner.setText('This screen highlights the current SpO₂ band, the reference thresholds, and supportive next-step guidance.')

        self.top_title.setText('Blood Oxygen Detail')
        self.bottom_back_button.setText('Results' if ultra else 'Back To Results')
        self.refresh_button.setText('Refresh')
        self.qr_button.setText('Open QR' if compact else 'Open QR Handoff')
        self.consult_button.setText('Consult')

        self.back_button.setMinimumWidth(76 if compact else 96)
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

        if ultra:
            self.range_top_layout.setSpacing(6)
            self.range_bottom_layout.setSpacing(6)
        else:
            self.range_top_layout.setSpacing(8)
            self.range_bottom_layout.setSpacing(8)

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
                color: rgba(226, 244, 255, 0.88);
                font-size: {body_px}px;
                font-weight: 500;
                background: transparent;
            }}
            """
        )

        self.summary_banner.setStyleSheet(
            f"""
            QLabel {{
                color: rgba(220, 239, 250, 0.80);
                font-size: {body_px}px;
                font-weight: 500;
                background: transparent;
            }}
            """
        )

        for lbl in (self.category_pill, self.value_pill, self.status_pill):
            lbl.setStyleSheet(lbl.styleSheet() + f"\nQLabel {{ font-size: {pill_px}px; }}")

        for lbl in (self.metric_chip, self.range_chip, self.guidance_chip):
            lbl.setStyleSheet(lbl.styleSheet() + f"\nQLabel {{ font-size: {pill_px}px; }}")

        for lbl in (self.visual_title, self.context_title, self.quick_title):
            lbl.setStyleSheet(
                f"""
                QLabel {{
                    color: #F5FBFF;
                    font-size: {section_px}px;
                    font-weight: 800;
                    background: transparent;
                }}
                """
            )

        for lbl in (
            self.context_line_1,
            self.context_line_2,
            self.context_line_3,
            self.context_line_4,
            self.context_note,
            self.quick_text,
        ):
            lbl.setStyleSheet(
                f"""
                QLabel {{
                    color: rgba(226, 240, 249, 0.86);
                    font-size: {body_px}px;
                    font-weight: 500;
                    background: transparent;
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
            "bands_overlay_path": self._bands_overlay_path,
        }