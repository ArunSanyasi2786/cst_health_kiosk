"""
screens/results_screen.py

Premium results screen for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the first full review screen after measurement completes
- It presents:
    - all captured metric values
    - overall interpretation status
    - summary guidance for the operator / user
    - quick access to detail screens
    - QR / report / consult workflow handoff
- It is designed specifically for:
    - Raspberry Pi 4B touchscreen kiosk deployment
    - 1024x600 kiosk resolution
    - laptop demo mode
- It supports both:
    - Demo Mode simulated results
    - Hardware Mode live sensor results

Linked project files this screen is intended to work with:
- core/constants.py
- core/asset_paths.py
- core/logger.py
- core/app_state.py
- core/navigator.py
- core/theme_manager.py
- core/animation_manager.py
- services/session_service.py
- services/diagnosis_service.py
- services/health_rules_service.py
- services/report_service.py
- services/qr_service.py
- services/mode_service.py
- widgets/animated_button.py
- widgets/glow_label.py

Navigation targets this screen is designed to link to:
- screens/measuring_screen.py
- screens/qr_screen.py
- screens/consult_screen.py
- screens/bmi_detail_screen.py
- screens/temperature_detail_screen.py
- screens/spo2_detail_screen.py
- screens/pulse_detail_screen.py
- screens/rr_detail_screen.py

Design goals:
- glossy futuristic blue medical UI
- strong readability for 1024x600
- very clear “at a glance” health result presentation
- resilient service integration with safe fallbacks
- maintainable structure while backend files continue to be integrated
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

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
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
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
        MODE_DEMO,
        MODE_HARDWARE,
        METRIC_BMI,
        METRIC_HEIGHT,
        METRIC_PULSE,
        METRIC_RR,
        METRIC_SPO2,
        METRIC_TEMPERATURE,
        METRIC_WEIGHT,
        SCREEN_BMI_DETAIL,
        SCREEN_CONSULT,
        SCREEN_DIAGNOSIS,
        SCREEN_MEASURING,
        SCREEN_PULSE_DETAIL,
        SCREEN_QR,
        SCREEN_RR_DETAIL,
        SCREEN_SPO2_DETAIL,
        SCREEN_TEMPERATURE_DETAIL,
    )
except Exception:  # pragma: no cover
    MODE_DEMO = "demo"
    MODE_HARDWARE = "hardware"
    METRIC_TEMPERATURE = "temperature"
    METRIC_SPO2 = "spo2"
    METRIC_PULSE = "pulse_rate"
    METRIC_RR = "respiratory_rate"
    METRIC_WEIGHT = "weight"
    METRIC_HEIGHT = "height"
    METRIC_BMI = "bmi"

    SCREEN_MEASURING = "measuring"
    SCREEN_QR = "qr"
    SCREEN_CONSULT = "consult"
    SCREEN_DIAGNOSIS = "diagnosis"
    SCREEN_TEMPERATURE_DETAIL = "temperature_detail"
    SCREEN_SPO2_DETAIL = "spo2_detail"
    SCREEN_PULSE_DETAIL = "pulse_detail"
    SCREEN_RR_DETAIL = "rr_detail"
    SCREEN_BMI_DETAIL = "bmi_detail"

SCREEN_RESULTS_DIAGNOSIS = "results_diagnosis"

try:
    from config import (
        HEIGHT_SCALE,
        IS_COMPACT_KIOSK,
        KIOSK_HEIGHT,
        KIOSK_WIDTH,
        UI_SCALE,
        WIDTH_SCALE,
    )
except Exception:  # pragma: no cover
    KIOSK_WIDTH = 1024
    KIOSK_HEIGHT = 600
    WIDTH_SCALE = 1.0
    HEIGHT_SCALE = 1.0
    UI_SCALE = 1.0
    IS_COMPACT_KIOSK = False

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

_COMPACT_RESULTS = bool(IS_COMPACT_KIOSK or KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480)


def _ui(value: float) -> int:
    try:
        scale = float(UI_SCALE) if float(UI_SCALE) > 0 else 1.0
    except Exception:
        scale = 1.0
    return max(1, int(round(float(value) * scale)))


def _w(value: float) -> int:
    try:
        scale = float(WIDTH_SCALE) if float(WIDTH_SCALE) > 0 else 1.0
    except Exception:
        scale = 1.0
    return max(1, int(round(float(value) * scale)))


def _h(value: float) -> int:
    try:
        scale = float(HEIGHT_SCALE) if float(HEIGHT_SCALE) > 0 else 1.0
    except Exception:
        scale = 1.0
    return max(1, int(round(float(value) * scale)))


# =============================================================================
# Helpers
# =============================================================================

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


def _format_number(value: Any, decimals: int = 1, fallback: str = "--") -> str:
    if value in (None, ""):
        return fallback

    if isinstance(value, str):
        text = value.strip()
        return text or fallback

    numeric = safe_float(value, 0.0)
    if abs(numeric - round(numeric)) < 1e-9:
        return str(int(round(numeric)))
    return f"{numeric:.{decimals}f}"


def _compute_bmi(weight_kg: Optional[float], height_value: Optional[float]) -> Optional[float]:
    if weight_kg in (None, "") or height_value in (None, ""):
        return None

    weight = safe_float(weight_kg, 0.0)
    raw_height = safe_float(height_value, 0.0)

    if weight <= 0 or raw_height <= 0:
        return None

    height_m = raw_height / 100.0 if raw_height > 3.5 else raw_height
    if height_m <= 0:
        return None

    bmi = weight / (height_m * height_m)
    if bmi <= 0:
        return None
    return round(bmi, 1)


def _severity_rank(severity: str) -> int:
    sev = safe_str(severity, "").strip().lower()
    if sev == "critical":
        return 4
    if sev == "warning":
        return 3
    if sev == "attention":
        return 2
    if sev == "normal":
        return 1
    return 0


def _severity_accent(severity: str) -> str:
    sev = safe_str(severity, "").strip().lower()
    if sev == "critical":
        return "#FF6E88"
    if sev == "warning":
        return "#FFA14D"
    if sev == "attention":
        return "#FFD25E"
    if sev == "normal":
        # Slightly darker teal accent for normal-state tiles so the results
        # screen stays premium and medical instead of drifting into a light
        # green consumer-app look.
        return "#2EA89B"
    return "#39D8FF"


def _default_metric_classification(metric_key: str, value: Any) -> Dict[str, Any]:
    """
    Fallback metric interpretation logic used if diagnosis/health rules
    services are not ready yet.
    """
    if value in (None, ""):
        return {
            "label": "Unavailable",
            "severity": "unknown",
            "summary": "No value is available for this metric yet.",
            "accent_hex": "#39D8FF",
        }

    numeric = safe_float(value, 0.0)

    if metric_key == METRIC_TEMPERATURE:
        if numeric < 36.0:
            label = "Low"
            severity = "attention"
            summary = "Body temperature is below the usual reference range."
        elif numeric < 37.5:
            label = "Normal"
            severity = "normal"
            summary = "Body temperature is within a normal reference range."
        elif numeric < 39.0:
            label = "Elevated"
            severity = "warning"
            summary = "Body temperature is above the normal range and should be reviewed."
        else:
            label = "High Fever"
            severity = "critical"
            summary = "Body temperature is in a high fever range and may need urgent attention."
        return {"label": label, "severity": severity, "summary": summary, "accent_hex": _severity_accent(severity)}

    if metric_key == METRIC_SPO2:
        if numeric < 90:
            label = "Critical"
            severity = "critical"
            summary = "Blood oxygen saturation is critically low."
        elif numeric < 94:
            label = "Low"
            severity = "warning"
            summary = "Blood oxygen saturation is below a recommended healthy range."
        elif numeric < 96:
            label = "Borderline"
            severity = "attention"
            summary = "Blood oxygen saturation is slightly reduced and should be monitored."
        else:
            label = "Healthy"
            severity = "normal"
            summary = "Blood oxygen saturation is within a healthy range."
        return {"label": label, "severity": severity, "summary": summary, "accent_hex": _severity_accent(severity)}

    if metric_key == METRIC_PULSE:
        if numeric < 60:
            label = "Low Pulse"
            severity = "attention"
            summary = "Pulse rate is below the common adult resting range."
        elif numeric < 100:
            label = "Normal"
            severity = "normal"
            summary = "Pulse rate is within the common adult resting range."
        elif numeric < 120:
            label = "Elevated"
            severity = "warning"
            summary = "Pulse rate is above the typical resting range."
        else:
            label = "Very High"
            severity = "critical"
            summary = "Pulse rate is very high and may require urgent attention."
        return {"label": label, "severity": severity, "summary": summary, "accent_hex": _severity_accent(severity)}

    if metric_key == METRIC_RR:
        if numeric < 12:
            label = "Low"
            severity = "attention"
            summary = "Respiratory rate is below the common adult resting range."
        elif numeric < 20:
            label = "Normal"
            severity = "normal"
            summary = "Respiratory rate is within the common adult resting range."
        elif numeric < 24:
            label = "Elevated"
            severity = "warning"
            summary = "Respiratory rate is above the typical resting range."
        else:
            label = "High"
            severity = "critical"
            summary = "Respiratory rate is significantly elevated."
        return {"label": label, "severity": severity, "summary": summary, "accent_hex": _severity_accent(severity)}

    if metric_key == METRIC_BMI:
        if numeric < 18.5:
            label = "Underweight"
            severity = "attention"
            summary = "BMI is below the recommended healthy range."
        elif numeric < 25.0:
            label = "Normal"
            severity = "normal"
            summary = "BMI is within a healthy reference range."
        elif numeric < 30.0:
            label = "Overweight"
            severity = "warning"
            summary = "BMI is above the recommended healthy range."
        else:
            label = "Obese"
            severity = "critical"
            summary = "BMI is significantly above the recommended range."
        return {"label": label, "severity": severity, "summary": summary, "accent_hex": _severity_accent(severity)}

    if metric_key in {METRIC_WEIGHT, METRIC_HEIGHT}:
        return {
            "label": "Captured",
            "severity": "normal",
            "summary": "The supporting anthropometric measurement was captured successfully.",
            "accent_hex": "#39D8FF",
        }

    return {
        "label": "Available",
        "severity": "normal",
        "summary": "This metric was captured successfully.",
        "accent_hex": "#39D8FF",
    }


# =============================================================================
# Internal widgets
# =============================================================================

class _ResultMetricCard(QFrame):
    """
    Premium clickable result metric card.

    Used because the screen needs reliable click handling for detail navigation
    and strong visual control even when external widgets are still evolving.

    This compact revision is tuned specifically for the 800x480 kiosk layout:
    - removes the long descriptive sentence inside each card
    - increases title/value legibility
    - keeps card heights tighter and more consistent
    - uses a darker medical blue surface with accent highlights instead of a
      brighter green-tinted fill
    - keeps the status chip aligned so the tile grid looks cleaner
    - avoids extra internal overlay rectangles so the tile body stays clean
    """

    clicked = pyqtSignal(str)

    def __init__(
        self,
        metric_key: str,
        *,
        title: str,
        unit: str,
        clickable: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self.metric_key = safe_str(metric_key, "").strip()
        self._unit = safe_str(unit, "").strip()
        self._clickable = bool(clickable)
        self._hovered = False
        self._accent_hex = "#39D8FF"
        self._tile_hex = "#2D79D8"
        self._chip_hex = "#20C97D"
        self._compact = _COMPACT_RESULTS
        self._show_subtitle = False

        self.setObjectName("ResultMetricCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor if self._clickable else Qt.CursorShape.ArrowCursor)
        self.setMinimumHeight(_h(76 if self._compact else 106))
        self.setMaximumHeight(_h(90 if self._compact else 124))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QVBoxLayout(self)
        root.setContentsMargins(
            _w(12 if self._compact else 15),
            _h(9 if self._compact else 12),
            _w(12 if self._compact else 15),
            _h(9 if self._compact else 12),
        )
        root.setSpacing(_h(3 if self._compact else 5))

        self.top_row = QWidget(self)
        self.top_row.setObjectName("MetricCardTopRow")
        self.top_row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        top_layout = QHBoxLayout(self.top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(_w(6 if self._compact else 8))

        self.title_label = QLabel(title, self.top_row)
        self.title_label.setWordWrap(False)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.title_label.setMinimumHeight(_h(16 if self._compact else 20))

        self.status_chip = QLabel("Waiting", self.top_row)
        self.status_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_chip.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.status_chip.setMinimumHeight(_h(18 if self._compact else 22))
        self.status_chip.setMinimumWidth(_w(72 if self._compact else 86))
        self.status_chip.setMaximumWidth(_w(92 if self._compact else 108))

        top_layout.addWidget(self.title_label, 1, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        top_layout.addWidget(self.status_chip, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.value_row = QWidget(self)
        self.value_row.setObjectName("MetricCardValueRow")
        self.value_row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        value_layout = QHBoxLayout(self.value_row)
        value_layout.setContentsMargins(0, 0, 0, 0)
        value_layout.setSpacing(_w(5 if self._compact else 6))

        self.value_label = QLabel("--", self.value_row)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.value_label.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        self.unit_label = QLabel(self._unit, self.value_row)
        self.unit_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        self.unit_label.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        value_layout.addWidget(self.value_label, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        value_layout.addWidget(self.unit_label, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        value_layout.addStretch(1)

        self.subtitle_label = QLabel("", self)
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setVisible(False)
        self.subtitle_label.setMaximumHeight(0)
        self.subtitle_label.setMinimumHeight(0)

        root.addWidget(self.top_row)
        root.addWidget(self.value_row)
        root.addStretch(1)

        self._apply_style()

    def set_payload(
        self,
        *,
        value: Any,
        status_text: str,
        subtitle: str,
        accent_hex: str,
        unit: Optional[str] = None,
    ) -> None:
        self._accent_hex = safe_str(accent_hex, "#39D8FF").strip() or "#39D8FF"

        if value in (None, ""):
            self.value_label.setText("--")
        else:
            decimals = 0 if self.metric_key in {METRIC_SPO2, METRIC_PULSE, METRIC_RR, METRIC_HEIGHT} else 1
            self.value_label.setText(_format_number(value, decimals))

        if unit is not None:
            self._unit = safe_str(unit, "").strip()
        self.unit_label.setText(self._unit)

        clean_status = safe_str(status_text, "").strip() or "Ready"
        clean_subtitle = safe_str(subtitle, "").strip() or "Captured."

        self.status_chip.setText(clean_status)
        self.status_chip.setToolTip(clean_subtitle)
        self.subtitle_label.setText("")
        self.subtitle_label.setVisible(False)
        self._tile_hex = self._resolve_tile_hex()
        self._chip_hex = self._resolve_chip_hex(clean_status)
        self._apply_style()

    def set_clickable(self, clickable: bool) -> None:
        self._clickable = bool(clickable)
        self.setCursor(Qt.CursorShape.PointingHandCursor if self._clickable else Qt.CursorShape.ArrowCursor)

    def _resolve_tile_hex(self) -> str:
        metric_key = safe_str(self.metric_key, "").strip().lower()
        if metric_key in {METRIC_WEIGHT, METRIC_HEIGHT}:
            return "#0F7B63"
        return "#1A5FAE"

    def _resolve_chip_hex(self, status_text: str) -> str:
        text = safe_str(status_text, "").strip().lower()

        green_keywords = (
            "normal",
            "healthy",
            "captured",
            "ready",
            "stable",
            "good",
            "within",
        )
        red_keywords = (
            "unhealthy",
            "critical",
            "danger",
            "very high",
            "severe",
            "very low",
        )
        amber_keywords = (
            "attention",
            "warning",
            "concerning",
            "review",
            "monitor",
            "elevated",
            "low",
            "high",
            "mild",
            "alert",
        )

        if any(word in text for word in red_keywords):
            return "#FF5D73"
        if any(word in text for word in green_keywords):
            return "#20C97D"
        if any(word in text for word in amber_keywords):
            return "#FFB84D"
        return "#39D8FF"

    def _apply_style(self) -> None:
        tile_accent = QColor(self._tile_hex)
        chip_accent = QColor(self._chip_hex)

        border_alpha = 0.64 if self._hovered and self._clickable else 0.52
        fill_alpha = 0.88 if self._hovered and self._clickable else 0.78
        fill_alpha_end = 0.82 if self._hovered and self._clickable else 0.72
        chip_border_alpha = 0.44 if self._hovered and self._clickable else 0.36
        chip_fill_alpha = 0.26 if self._hovered and self._clickable else 0.22

        dark_r = max(0, tile_accent.red() - 48)
        dark_g = max(0, tile_accent.green() - 48)
        dark_b = max(0, tile_accent.blue() - 48)

        self.setStyleSheet(
            f"""
            QFrame#ResultMetricCard {{
                border: 1px solid rgba({tile_accent.red()}, {tile_accent.green()}, {tile_accent.blue()}, {border_alpha:.3f});
                border-radius: 18px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba({tile_accent.red()}, {tile_accent.green()}, {tile_accent.blue()}, {fill_alpha:.3f}),
                    stop:0.58 rgba({max(0, tile_accent.red()-20)}, {max(0, tile_accent.green()-20)}, {max(0, tile_accent.blue()-20)}, {fill_alpha:.3f}),
                    stop:1 rgba({dark_r}, {dark_g}, {dark_b}, {fill_alpha_end:.3f})
                );
            }}
            QWidget#MetricCardTopRow,
            QWidget#MetricCardValueRow {{
                background: transparent;
                border: none;
            }}
            """
        )

        self.title_label.setStyleSheet(
            f"""
            QLabel {{
                color: rgba(236, 246, 252, 0.98);
                font-size: {11 if self._compact else 13}px;
                font-weight: 800;
                background: transparent;
            }}
            """
        )
        self.value_label.setStyleSheet(
            f"""
            QLabel {{
                color: #F8FDFF;
                font-size: {22 if self._compact else 25}px;
                font-weight: 900;
                background: transparent;
            }}
            """
        )
        self.unit_label.setStyleSheet(
            f"""
            QLabel {{
                color: rgba(220, 235, 246, 0.96);
                font-size: {10 if self._compact else 11}px;
                font-weight: 700;
                background: transparent;
                padding-bottom: {2 if self._compact else 3}px;
            }}
            """
        )
        self.subtitle_label.setStyleSheet(
            f"""
            QLabel {{
                color: rgba(198, 218, 233, 0.86);
                font-size: {8 if self._compact else 9}px;
                font-weight: 500;
                background: transparent;
            }}
            """
        )

        self.status_chip.setStyleSheet(
            f"""
            QLabel {{
                color: #F7FCFF;
                font-size: {8 if self._compact else 9}px;
                font-weight: 800;
                border: 1px solid rgba({chip_accent.red()}, {chip_accent.green()}, {chip_accent.blue()}, {chip_border_alpha:.3f});
                border-radius: {10 if self._compact else 12}px;
                background: rgba({chip_accent.red()}, {chip_accent.green()}, {chip_accent.blue()}, {chip_fill_alpha:.3f});
                padding: {3 if self._compact else 4}px {8 if self._compact else 10}px;
            }}
            """
        )

    def enterEvent(self, event: QEvent) -> None:
        super().enterEvent(event)
        if not self._clickable:
            return
        self._hovered = True
        self._apply_style()

    def leaveEvent(self, event: QEvent) -> None:
        super().leaveEvent(event)
        self._hovered = False
        self._apply_style()

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if self._clickable and event is not None and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.metric_key)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            rect = QRectF(self.rect().adjusted(1, 1, -1, -1))
            if rect.width() > 8 and rect.height() > 8:
                radius = 18.0
                path = QPainterPath()
                path.addRoundedRect(rect, float(radius), float(radius))
                painter.save()
                painter.setClipPath(path)

                soft_glow = QRectF(
                    rect.left() + 2.0,
                    rect.top() + 2.0,
                    rect.width() - 4.0,
                    max(2.0, rect.height() * 0.12),
                )
                painter.fillRect(soft_glow, QColor(255, 255, 255, 7 if not self._hovered else 12))
                painter.restore()
        finally:
            painter.end()


class _DiagnosisSummaryCard(QFrame):
    """
    Internal premium summary card for overall diagnosis / interpretation.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._accent_hex = "#39D8FF"

        self.setObjectName("DiagnosisSummaryCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(_h(92 if _COMPACT_RESULTS else 108))
        self.setMaximumHeight(_h(122 if _COMPACT_RESULTS else 136))

        root = QVBoxLayout(self)
        root.setContentsMargins(_w(14 if _COMPACT_RESULTS else 16), _h(10 if _COMPACT_RESULTS else 12), _w(14 if _COMPACT_RESULTS else 16), _h(10 if _COMPACT_RESULTS else 12))
        root.setSpacing(_h(5 if _COMPACT_RESULTS else 6))

        top_row = QWidget(self)
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        self.title_label = QLabel("Overall Interpretation", top_row)
        self.status_chip = QLabel("Review", top_row)

        top_layout.addWidget(self.title_label)
        top_layout.addStretch(1)
        top_layout.addWidget(self.status_chip)

        self.summary_label = QLabel(
            "Session results will be interpreted here once data is available.",
            self,
        )
        self.summary_label.setWordWrap(True)

        self.line_1 = QLabel("• Awaiting completed session measurements.", self)
        self.line_2 = QLabel("• The screen will summarize major findings.", self)
        self.line_3 = QLabel("• Detail screens provide metric-by-metric review.", self)

        root.addWidget(top_row)
        root.addWidget(self.summary_label)
        root.addWidget(self.line_1)
        root.addWidget(self.line_2)
        root.addWidget(self.line_3)

        self._apply_style()

    def set_payload(
        self,
        *,
        title: str,
        status_text: str,
        summary: str,
        bullets: Iterable[str],
        accent_hex: str,
    ) -> None:
        self._accent_hex = safe_str(accent_hex, "#39D8FF").strip() or "#39D8FF"
        self.title_label.setText(safe_str(title, "Overall Interpretation").strip() or "Overall Interpretation")
        self.status_chip.setText(safe_str(status_text, "Review").strip() or "Review")
        self.summary_label.setText(safe_str(summary, "").strip())

        bullet_list = [safe_str(item, "").strip() for item in bullets if safe_str(item, "").strip()]
        while len(bullet_list) < 3:
            bullet_list.append("")

        self.line_1.setText(f"• {bullet_list[0]}" if bullet_list[0] else "")
        self.line_2.setText(f"• {bullet_list[1]}" if bullet_list[1] else "")
        self.line_3.setText(f"• {bullet_list[2]}" if bullet_list[2] else "")

        self.line_1.setVisible(bool(bullet_list[0]))
        self.line_2.setVisible(bool(bullet_list[1]))
        self.line_3.setVisible(bool(bullet_list[2]))

        self._apply_style()

    def _apply_style(self) -> None:
        accent = QColor(self._accent_hex)

        self.setStyleSheet(
            f"""
            QFrame#DiagnosisSummaryCard {{
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.22);
                border-radius: 20px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.09);
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
        self.status_chip.setStyleSheet(
            f"""
            QLabel {{
                color: #F4FCFF;
                font-size: 8px;
                font-weight: 800;
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.36);
                border-radius: 12px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.16);
                padding: 4px 9px;
            }}
            """
        )
        self.summary_label.setStyleSheet(
            """
            QLabel {
                color: rgba(221, 239, 250, 0.92);
                font-size: 9px;
                font-weight: 600;
                background: transparent;
            }
            """
        )
        bullet_style = """
            QLabel {
                color: rgba(197, 223, 241, 0.86);
                font-size: 9px;
                font-weight: 500;
                background: transparent;
            }
        """
        self.line_1.setStyleSheet(bullet_style)
        self.line_2.setStyleSheet(bullet_style)
        self.line_3.setStyleSheet(bullet_style)


# =============================================================================
# Main screen
# =============================================================================

class ResultsScreen(QFrame):
    """
    Premium result presentation screen.

    Main responsibilities:
    - load latest session measurements
    - classify and summarize health results
    - present all captured metrics
    - provide navigation to detail / QR / consult / retake flow
    """

    back_requested = pyqtSignal()
    refresh_requested = pyqtSignal()
    retake_requested = pyqtSignal()
    qr_requested = pyqtSignal(dict)
    consult_requested = pyqtSignal(dict)
    diagnosis_requested = pyqtSignal(dict)
    report_requested = pyqtSignal(dict)
    metric_detail_requested = pyqtSignal(str)
    results_loaded = pyqtSignal(dict)

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

        try:
            self._logger = logger.bind(component="ResultsScreen")
        except Exception:
            self._logger = logger

        self.navigator = navigator
        self.app_state = app_state
        self.services = dict(services or {})
        self.animation_manager = animation_manager
        self.theme_manager = theme_manager

        self._mode = self._read_current_mode()
        self._results_payload: Dict[str, Any] = {}
        self._report_path = ""
        self._qr_path = ""
        self._compact_results = _COMPACT_RESULTS

        self._background_path = _resolve_asset("backgrounds/results_bg.png")
        self._logo_small_path = _resolve_asset("logos/2720920.png")
        self._background_pixmap = _pixmap_or_empty(self._background_path)
        self._logo_pixmap = _pixmap_or_empty(self._logo_small_path)

        self.setObjectName("ResultsScreen")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._build_ui()
        self._setup_effects()
        self._apply_styles()

    # =========================================================================
    # UI
    # =========================================================================

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(_w(14 if _COMPACT_RESULTS else 22), _h(10 if _COMPACT_RESULTS else 16), _w(14 if _COMPACT_RESULTS else 22), _h(10 if _COMPACT_RESULTS else 16))
        root.setSpacing(_h(8 if _COMPACT_RESULTS else 10))

        # ---------------------------------------------------------------------
        # Top bar
        # ---------------------------------------------------------------------
        self.top_bar = QWidget(self)
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(_w(8 if _COMPACT_RESULTS else 10))

        self.back_button = self._create_button("Back", variant="secondary", min_width=96, parent=self.top_bar)
        self.back_button.setMinimumHeight(40)
        self.back_button.setMaximumHeight(40)
        self.back_button.clicked.connect(self._handle_back_clicked)

        self.logo_label = QLabel(self.top_bar)
        self.logo_label.setObjectName("LogoLabel")
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_label.setFixedSize(42, 42)
        self._set_label_pixmap(self.logo_label, self._logo_pixmap, 42)

        self.top_title = QLabel("Measurement Results", self.top_bar)
        self.top_title.setObjectName("TopTitle")

        self.mode_pill = QLabel("Mode Unknown", self.top_bar)
        self.mode_pill.setObjectName("RuntimePill")

        self.metrics_pill = QLabel("0 Metrics", self.top_bar)
        self.metrics_pill.setObjectName("RuntimePill")

        self.report_pill = QLabel("Report Pending", self.top_bar)
        self.report_pill.setObjectName("RuntimePill")

        top_layout.addWidget(self.back_button)
        top_layout.addWidget(self.logo_label)
        top_layout.addWidget(self.top_title)
        top_layout.addStretch(1)
        top_layout.addWidget(self.mode_pill)
        top_layout.addWidget(self.metrics_pill)
        top_layout.addWidget(self.report_pill)

        # ---------------------------------------------------------------------
        # Header summary card
        # ---------------------------------------------------------------------
        self.header_card = QFrame(self)
        self.header_card.setObjectName("ResultsHeaderCard")
        self.header_card.setMinimumHeight(_h(100 if _COMPACT_RESULTS else 132))
        self.header_card.setMaximumHeight(_h(128 if _COMPACT_RESULTS else 168))

        header_layout = QVBoxLayout(self.header_card)
        header_layout.setContentsMargins(_w(14 if _COMPACT_RESULTS else 18), _h(10 if _COMPACT_RESULTS else 14), _w(14 if _COMPACT_RESULTS else 18), _h(10 if _COMPACT_RESULTS else 14))
        header_layout.setSpacing(_h(6 if _COMPACT_RESULTS else 8))

        if _HAS_GLOW_LABEL:
            try:
                self.hero_title = GlowLabel(
                    role=getattr(GlowLabel, "ROLE_TITLE", getattr(GlowLabel, "ROLE_STATUS", 0)),
                    align_center=True,
                    use_outline=False,
                    enable_paint_glow=True,
                    initial_glow_strength=0.48,
                    initial_glow_blur=18,
                )
            except Exception:
                self.hero_title = QLabel(self.header_card)
                self.hero_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            self.hero_title = QLabel(self.header_card)
            self.hero_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.hero_subtitle = QLabel(self.header_card)
        self.hero_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hero_subtitle.setWordWrap(True)

        self.header_chip_row = QWidget(self.header_card)
        chip_layout = QHBoxLayout(self.header_chip_row)
        chip_layout.setContentsMargins(0, 0, 0, 0)
        chip_layout.setSpacing(_w(6 if _COMPACT_RESULTS else 8))

        self.overall_chip = QLabel("Review", self.header_chip_row)
        self.overall_chip.setObjectName("HeaderChip")

        self.source_chip = QLabel("Session Source", self.header_chip_row)
        self.source_chip.setObjectName("HeaderChip")

        self.detail_hint_chip = QLabel("Tap metric cards for details", self.header_chip_row)
        self.detail_hint_chip.setObjectName("HeaderChip")

        chip_layout.addStretch(1)
        chip_layout.addWidget(self.overall_chip)
        chip_layout.addWidget(self.source_chip)
        chip_layout.addWidget(self.detail_hint_chip)
        chip_layout.addStretch(1)

        self.summary_banner = QLabel(
            "This screen summarizes the most recent completed measurement session.",
            self.header_card,
        )
        self.summary_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.summary_banner.setWordWrap(True)

        header_layout.addWidget(self.hero_title)
        header_layout.addWidget(self.hero_subtitle)
        header_layout.addWidget(self.header_chip_row)
        header_layout.addWidget(self.summary_banner)

        # ---------------------------------------------------------------------
        # Main metric panel only (full width)
        # ---------------------------------------------------------------------
        self.content_row = QWidget(self)
        content_layout = QHBoxLayout(self.content_row)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.metric_panel = QFrame(self.content_row)
        self.metric_panel.setObjectName("MetricPanel")
        self.metric_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        metric_layout = QVBoxLayout(self.metric_panel)
        metric_layout.setContentsMargins(_w(12 if _COMPACT_RESULTS else 16), _h(10 if _COMPACT_RESULTS else 14), _w(12 if _COMPACT_RESULTS else 16), _h(10 if _COMPACT_RESULTS else 14))
        metric_layout.setSpacing(_h(6 if _COMPACT_RESULTS else 8))

        self.metric_panel_title = QLabel("Session Metrics", self.metric_panel)
        self.metric_panel_title.setObjectName("SectionTitle")

        self.metric_panel_subtitle = QLabel(
            "All captured health values are shown below. Tap a tile to open its detail screen.",
            self.metric_panel,
        )
        self.metric_panel_subtitle.setObjectName("MetricPanelSubtitle")
        self.metric_panel_subtitle.setWordWrap(True)

        self.diagnosis_card = _DiagnosisSummaryCard(self.metric_panel)
        self.diagnosis_card.hide()

        self.metric_grid_widget = QWidget(self.metric_panel)
        self.metric_grid = QGridLayout(self.metric_grid_widget)
        self.metric_grid.setContentsMargins(0, 0, 0, 0)
        self.metric_grid.setHorizontalSpacing(_w(8 if _COMPACT_RESULTS else 12))
        self.metric_grid.setVerticalSpacing(_h(8 if _COMPACT_RESULTS else 12))

        self.metric_cards: Dict[str, _ResultMetricCard] = {}
        self.metric_card_order: List[str] = []

        metric_specs: List[Tuple[str, str, str, bool]] = [
            (METRIC_TEMPERATURE, "Temperature", "°C", True),
            (METRIC_SPO2, "SpO₂", "%", True),
            (METRIC_PULSE, "Pulse", "bpm", True),
            (METRIC_RR, "Respiratory Rate", "breaths/min", True),
            (METRIC_WEIGHT, "Weight", "kg", False),
            (METRIC_HEIGHT, "Height", "cm", False),
            (METRIC_BMI, "BMI", "kg/m²", True),
        ]

        for metric_key, title, unit, clickable in metric_specs:
            card = _ResultMetricCard(
                metric_key,
                title=title,
                unit=unit,
                clickable=clickable,
                parent=self.metric_grid_widget,
            )
            card.clicked.connect(self._handle_metric_card_clicked)
            self.metric_cards[metric_key] = card
            self.metric_card_order.append(metric_key)

        self._layout_metric_cards()

        self.metric_hint = QLabel(
            "Tap Temperature, SpO₂, Pulse, Respiratory Rate, or BMI for detailed review.",
            self.metric_panel,
        )
        self.metric_hint.setWordWrap(True)

        metric_layout.addWidget(self.metric_panel_title)
        metric_layout.addWidget(self.metric_panel_subtitle)
        metric_layout.addWidget(self.metric_grid_widget, 1)
        metric_layout.addWidget(self.metric_hint)

        content_layout.addWidget(self.metric_panel, 1)

        # ---------------------------------------------------------------------
        # Bottom action row - uniform buttons
        # ---------------------------------------------------------------------
        self.action_row = QWidget(self)
        self.action_grid = QGridLayout(self.action_row)
        self.action_grid.setContentsMargins(0, 0, 0, 0)
        self.action_grid.setHorizontalSpacing(_w(8 if _COMPACT_RESULTS else 12))
        self.action_grid.setVerticalSpacing(_h(8 if _COMPACT_RESULTS else 10))

        self.refresh_button = self._create_button("Refresh Results", variant="ghost", min_width=_w(116 if _COMPACT_RESULTS else 148), parent=self.action_row)
        self.refresh_button.clicked.connect(self._handle_refresh_clicked)

        self.report_button = self._create_button("Generate Report", variant="ghost", min_width=_w(116 if _COMPACT_RESULTS else 148), parent=self.action_row)
        self.report_button.clicked.connect(self._handle_report_clicked)

        self.retake_button = self._create_button("New Checkup", variant="secondary", min_width=_w(116 if _COMPACT_RESULTS else 148), parent=self.action_row)
        self.retake_button.clicked.connect(self._handle_retake_clicked)

        self.qr_button = self._create_button("Open QR Screen", variant="secondary", min_width=_w(116 if _COMPACT_RESULTS else 148), parent=self.action_row)
        self.qr_button.clicked.connect(self._handle_qr_clicked)

        self.diagnosis_button = self._create_button("Open Diagnosis", variant="secondary", min_width=_w(116 if _COMPACT_RESULTS else 148), parent=self.action_row)
        self.diagnosis_button.clicked.connect(self._handle_diagnosis_clicked)

        self.consult_button = self._create_button("Open Consult", variant="primary", min_width=_w(116 if _COMPACT_RESULTS else 148), parent=self.action_row)
        self.consult_button.clicked.connect(self._handle_consult_clicked)

        self._action_buttons = [
            self.refresh_button,
            self.report_button,
            self.retake_button,
            self.qr_button,
            self.diagnosis_button,
            self.consult_button,
        ]

        for button in self._action_buttons:
            try:
                button.setMinimumHeight(_h(44 if _COMPACT_RESULTS else 52))
                button.setMaximumHeight(_h(44 if _COMPACT_RESULTS else 52))
                button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            except Exception:
                pass

        self._layout_action_buttons()

        root.addWidget(self.top_bar, 0)
        root.addWidget(self.header_card, 0)
        root.addWidget(self.content_row, 1)
        root.addWidget(self.action_row, 0)

    def _layout_metric_cards(self) -> None:
        """
        Layout metric cards responsively for both 1024x600 and 800x480 kiosks.

        Compact target preference:
        - 800x480: keep a 4 + 3 arrangement when possible to save height
        - mid widths: 3 + 3 + 1 arrangement
        - very narrow widths: 2 columns
        """
        while self.metric_grid.count():
            item = self.metric_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(self.metric_grid_widget)

        width = max(1, self.width())

        if width >= 720:
            placements = [
                (METRIC_TEMPERATURE, 0, 0, 1, 1),
                (METRIC_SPO2, 0, 1, 1, 1),
                (METRIC_PULSE, 0, 2, 1, 1),
                (METRIC_RR, 0, 3, 1, 1),
                (METRIC_WEIGHT, 1, 0, 1, 1),
                (METRIC_HEIGHT, 1, 1, 1, 1),
                (METRIC_BMI, 1, 2, 1, 2),
            ]
            for col in range(4):
                self.metric_grid.setColumnStretch(col, 1)
        elif width >= 620:
            placements = [
                (METRIC_TEMPERATURE, 0, 0, 1, 1),
                (METRIC_SPO2, 0, 1, 1, 1),
                (METRIC_PULSE, 0, 2, 1, 1),
                (METRIC_RR, 1, 0, 1, 1),
                (METRIC_WEIGHT, 1, 1, 1, 1),
                (METRIC_HEIGHT, 1, 2, 1, 1),
                (METRIC_BMI, 2, 0, 1, 3),
            ]
            for col in range(3):
                self.metric_grid.setColumnStretch(col, 1)
        else:
            placements = [
                (METRIC_TEMPERATURE, 0, 0, 1, 1),
                (METRIC_SPO2, 0, 1, 1, 1),
                (METRIC_PULSE, 1, 0, 1, 1),
                (METRIC_RR, 1, 1, 1, 1),
                (METRIC_WEIGHT, 2, 0, 1, 1),
                (METRIC_HEIGHT, 2, 1, 1, 1),
                (METRIC_BMI, 3, 0, 1, 2),
            ]
            for col in range(2):
                self.metric_grid.setColumnStretch(col, 1)

        for metric_key, row, col, row_span, col_span in placements:
            card = self.metric_cards.get(metric_key)
            if card is not None:
                self.metric_grid.addWidget(card, row, col, row_span, col_span)

    def _layout_action_buttons(self) -> None:
        while self.action_grid.count():
            item = self.action_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(self.action_row)

        width = max(1, self.width())

        if width >= 700:
            placements = [
                (0, 0, 1, 1),
                (0, 1, 1, 1),
                (0, 2, 1, 1),
                (1, 0, 1, 1),
                (1, 1, 1, 1),
                (1, 2, 1, 1),
            ]
            cols = 3
        else:
            placements = [
                (0, 0, 1, 1),
                (0, 1, 1, 1),
                (1, 0, 1, 1),
                (1, 1, 1, 1),
                (2, 0, 1, 1),
                (2, 1, 1, 1),
            ]
            cols = 2

        for col in range(cols):
            self.action_grid.setColumnStretch(col, 1)

        for button, (row, col, row_span, col_span) in zip(self._action_buttons, placements):
            self.action_grid.addWidget(button, row, col, row_span, col_span)

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
                    parent=parent,
                    variant=variant_map.get(variant),
                    size=getattr(AnimatedButton, "SIZE_MD", None),
                    minimum_width=min_width,
                )
                return btn
            except Exception:
                pass

        button = QPushButton(text, parent)
        button.setMinimumWidth(min_width)
        button.setMinimumHeight(52)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            """
            QPushButton {
                color: #F6FCFF;
                border: 1px solid rgba(157, 220, 255, 0.26);
                border-radius: 16px;
                padding: 10px 16px;
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

        self.content_opacity = QGraphicsOpacityEffect(self.content_row)
        self.content_row.setGraphicsEffect(self.content_opacity)
        self.content_opacity.setOpacity(0.0)

        self.entry_group = QParallelAnimationGroup(self)

        self.header_fade = QPropertyAnimation(self.header_opacity, b"opacity", self)
        self.header_fade.setDuration(320)
        self.header_fade.setStartValue(0.0)
        self.header_fade.setEndValue(1.0)
        self.header_fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.content_fade = QPropertyAnimation(self.content_opacity, b"opacity", self)
        self.content_fade.setDuration(460)
        self.content_fade.setStartValue(0.0)
        self.content_fade.setEndValue(1.0)
        self.content_fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.entry_group.addAnimation(self.header_fade)
        self.entry_group.addAnimation(self.content_fade)

        if _HAS_GLOW_LABEL and isinstance(self.hero_title, GlowLabel):
            try:
                self.hero_title.set_glow_color("#43D9FF")
                self.hero_title.set_text_color("#F5FCFF")
            except Exception:
                pass

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QFrame#ResultsScreen {
                background: transparent;
            }

            QLabel#LogoLabel {
                min-width: 42px;
                max-width: 42px;
                min-height: 42px;
                max-height: 42px;
                background: transparent;
                border: none;
            }
            QLabel#TopTitle {
                color: #F6FCFF;
                font-size: 13px;
                font-weight: 900;
                background: transparent;
            }

            QLabel#RuntimePill {
                color: #EEF9FF;
                font-size: 9px;
                font-weight: 700;
                border: 1px solid rgba(157, 220, 255, 0.22);
                border-radius: 14px;
                background: rgba(18, 39, 70, 0.56);
                padding: 5px 8px;
            }

            QFrame#ResultsHeaderCard {
                border: 1px solid rgba(170, 230, 255, 0.20);
                border-radius: 22px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(16, 34, 60, 0.86),
                    stop:1 rgba(8, 22, 44, 0.92)
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

            QFrame#MetricPanel {
                border: 1px solid rgba(170, 230, 255, 0.20);
                border-radius: 22px;
                background: rgba(12, 28, 50, 0.76);
            }

            QLabel#SectionTitle {
                color: #F4FCFF;
                font-size: 12px;
                font-weight: 800;
                background: transparent;
            }

            QLabel#MetricPanelSubtitle {
                color: rgba(214, 235, 248, 0.88);
                font-size: 9px;
                font-weight: 500;
                background: transparent;
            }
            """
        )

        if _HAS_GLOW_LABEL and isinstance(self.hero_title, GlowLabel):
            try:
                self.hero_title.set_text("Latest measurement results")
            except Exception:
                self.hero_title.setText("Latest measurement results")
        else:
            self.hero_title.setText("Latest measurement results")

        self.hero_subtitle.setText(
            "Review captured health metrics, overall interpretation, and next-step options for the active kiosk session."
        )
        self.summary_banner.setText(
            "Tap a supported metric to open its dedicated interpretation screen."
        )

        self.hero_title.setStyleSheet(
            """
            QLabel {
                color: #F6FCFF;
                font-size: 18px;
                font-weight: 900;
                background: transparent;
            }
            """
        )
        self.hero_subtitle.setStyleSheet(
            """
            QLabel {
                color: rgba(219, 237, 249, 0.92);
                font-size: 10px;
                font-weight: 600;
                background: transparent;
            }
            """
        )
        self.summary_banner.setStyleSheet(
            """
            QLabel {
                color: rgba(207, 229, 244, 0.90);
                font-size: 11px;
                font-weight: 600;
                background: transparent;
            }
            """
        )
        self.metric_hint.setStyleSheet(
            """
            QLabel {
                color: rgba(190, 214, 232, 0.84);
                font-size: 10px;
                font-weight: 500;
                background: transparent;
            }
            """
        )

    # =========================================================================
    # Lifecycle
    # =========================================================================

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._play_entry_animation()
        self._apply_responsive_layout()
        self.reload_results()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_metric_cards()
        self._layout_action_buttons()
        self._apply_responsive_layout()

    def _apply_responsive_layout(self) -> None:
        width = max(1, self.width())
        height = max(1, self.height())
        compact = bool(self._compact_results or width <= 860 or height <= 520)
        ultra = bool(width <= 760 or height <= 460)

        self.top_title.setText("Results" if ultra else "Measurement Results")

        self.report_pill.setVisible(not compact)
        self.detail_hint_chip.setVisible(not compact)
        self.hero_subtitle.setVisible(not ultra)
        self.metric_panel_subtitle.setVisible(not ultra)
        self.metric_hint.setVisible(not ultra)
        self.summary_banner.setVisible(not ultra)

        self.header_card.setMinimumHeight(_h(104 if compact else 116 if self._compact_results else 148))
        self.header_card.setMaximumHeight(_h(136 if compact else 148 if self._compact_results else 188))

        short_text = {
            self.refresh_button: "Refresh" if compact else "Refresh Results",
            self.report_button: "Report" if compact else "Generate Report",
            self.retake_button: "Retake" if compact else "New Checkup",
            self.qr_button: "QR" if ultra else ("Open QR" if compact else "Open QR Screen"),
            self.diagnosis_button: "Diagnosis" if compact else "Open Diagnosis",
            self.consult_button: "Consult" if compact else "Open Consult",
        }
        for button, label in short_text.items():
            try:
                button.setText(label)
            except Exception:
                pass

    def _play_entry_animation(self) -> None:
        try:
            self.entry_group.start()
        except Exception:
            pass

    # =========================================================================
    # Loading / integration
    # =========================================================================

    def reload_results(self) -> None:
        self._mode = self._read_current_mode()

        measurements = self._load_measurements()
        classifications = self._load_classifications(measurements)
        diagnosis_payload = self._load_diagnosis_payload(measurements, classifications)
        summary = self._build_overall_summary(measurements, classifications)

        self._results_payload = {
            "mode": self._mode,
            "measurements": dict(measurements),
            "classifications": dict(classifications),
            "diagnosis": dict(diagnosis_payload),
            "summary": dict(summary),
            "origin_screen": "results",
            "report_path": self._report_path,
            "qr_path": self._qr_path,
        }

        self._apply_results_payload(self._results_payload)
        self._persist_results_payload()
        self.results_loaded.emit(dict(self._results_payload))
        self.refresh_requested.emit()

    def _read_current_mode(self) -> str:
        mode = MODE_DEMO

        try:
            if self.app_state is not None:
                for attr_name in ("current_mode", "mode", "selected_mode"):
                    attr = getattr(self.app_state, attr_name, None)
                    if isinstance(attr, str) and attr.strip():
                        mode = attr.strip().lower()
                        break
                    if callable(attr):
                        result = attr()
                        if isinstance(result, str) and result.strip():
                            mode = result.strip().lower()
                            break
        except Exception:
            pass

        try:
            mode_service = self.services.get("mode_service") or self.services.get("mode")
            if mode_service is not None:
                for method_name in ("current_mode", "get_mode", "mode"):
                    method = getattr(mode_service, method_name, None)
                    if callable(method):
                        result = method()
                        result_text = safe_str(result, "").strip().lower()
                        if result_text:
                            mode = result_text
                            break
        except Exception:
            pass

        if mode not in {MODE_DEMO, MODE_HARDWARE}:
            mode = MODE_DEMO
        return mode

    def _load_measurements(self) -> Dict[str, Any]:
        """
        Best-effort loading of the latest active session measurements.
        """
        measurements: Dict[str, Any] = {}

        try:
            session_service = self.services.get("session_service") or self.services.get("session")
            if session_service is not None:
                for method_name in (
                    "get_current_measurements",
                    "current_measurements",
                    "get_latest_measurements",
                    "latest_measurements",
                    "current_session_measurements",
                    "get_session_payload",
                    "get_current_session",
                ):
                    method = getattr(session_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method()
                            if isinstance(raw, Mapping):
                                if "measurements" in raw and isinstance(raw.get("measurements"), Mapping):
                                    measurements = dict(raw.get("measurements", {}))
                                else:
                                    measurements = dict(raw)
                                if measurements:
                                    break
                        except Exception:
                            continue
        except Exception:
            pass

        if not measurements:
            try:
                if self.app_state is not None:
                    for attr_name in ("current_measurements", "measurements", "live_measurements"):
                        attr = getattr(self.app_state, attr_name, None)
                        if isinstance(attr, Mapping):
                            measurements = dict(attr)
                            if measurements:
                                break
            except Exception:
                pass

        normalized = {
            METRIC_TEMPERATURE: measurements.get(METRIC_TEMPERATURE, measurements.get("temp", measurements.get("body_temperature"))),
            METRIC_SPO2: measurements.get(METRIC_SPO2, measurements.get("oxygen_saturation")),
            METRIC_PULSE: measurements.get(METRIC_PULSE, measurements.get("pulse", measurements.get("heart_rate", measurements.get("bpm")))),
            METRIC_RR: measurements.get(METRIC_RR, measurements.get("rr", measurements.get("respiration_rate"))),
            METRIC_WEIGHT: measurements.get(METRIC_WEIGHT, measurements.get("weight_kg")),
            METRIC_HEIGHT: measurements.get(METRIC_HEIGHT, measurements.get("height_cm", measurements.get("height_mm", measurements.get("height_m")))),
            METRIC_BMI: measurements.get(METRIC_BMI),
        }

        raw_height = normalized.get(METRIC_HEIGHT)
        if raw_height not in (None, ""):
            height_numeric = safe_float(raw_height, 0.0)
            if height_numeric > 300:
                normalized[METRIC_HEIGHT] = round(height_numeric / 10.0, 1)
            elif 0 < height_numeric < 3.5:
                normalized[METRIC_HEIGHT] = round(height_numeric * 100.0, 1)

        if normalized.get(METRIC_BMI) in (None, ""):
            normalized[METRIC_BMI] = _compute_bmi(
                None if normalized.get(METRIC_WEIGHT) in (None, "") else safe_float(normalized.get(METRIC_WEIGHT), 0.0),
                None if normalized.get(METRIC_HEIGHT) in (None, "") else safe_float(normalized.get(METRIC_HEIGHT), 0.0),
            )

        return normalized

    def _load_classifications(self, measurements: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
        """
        Best-effort classification loading through diagnosis or health rules
        services, with robust fallback logic.
        """
        classifications: Dict[str, Dict[str, Any]] = {}

        try:
            diagnosis_service = self.services.get("diagnosis_service") or self.services.get("diagnosis")
            if diagnosis_service is not None:
                for method_name in (
                    "classify_measurements",
                    "analyze_measurements",
                    "diagnose_measurements",
                    "evaluate_measurements",
                    "get_classifications",
                ):
                    method = getattr(diagnosis_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method(dict(measurements))
                            if isinstance(raw, Mapping):
                                if "classifications" in raw and isinstance(raw.get("classifications"), Mapping):
                                    classifications = {
                                        safe_str(k, ""): dict(v)
                                        for k, v in dict(raw.get("classifications", {})).items()
                                        if isinstance(v, Mapping)
                                    }
                                else:
                                    classifications = {
                                        safe_str(k, ""): dict(v)
                                        for k, v in dict(raw).items()
                                        if isinstance(v, Mapping)
                                    }
                                if classifications:
                                    break
                        except Exception:
                            continue
        except Exception:
            pass

        if not classifications:
            try:
                health_rules_service = self.services.get("health_rules_service") or self.services.get("health_rules")
                if health_rules_service is not None:
                    per_metric: Dict[str, Dict[str, Any]] = {}
                    for metric_key, value in measurements.items():
                        for method_name in (
                            "classify_metric",
                            "evaluate_metric",
                            "classify_value",
                            "classify",
                        ):
                            method = getattr(health_rules_service, method_name, None)
                            if callable(method):
                                try:
                                    raw = method(metric_key, value)
                                    if isinstance(raw, Mapping):
                                        per_metric[metric_key] = dict(raw)
                                        break
                                except Exception:
                                    continue
                    if per_metric:
                        classifications = per_metric
            except Exception:
                pass

        for metric_key in (
            METRIC_TEMPERATURE,
            METRIC_SPO2,
            METRIC_PULSE,
            METRIC_RR,
            METRIC_WEIGHT,
            METRIC_HEIGHT,
            METRIC_BMI,
        ):
            if metric_key not in classifications:
                classifications[metric_key] = _default_metric_classification(metric_key, measurements.get(metric_key))
            else:
                item = dict(classifications.get(metric_key, {}))
                severity = safe_str(item.get("severity"), "unknown").strip().lower() or "unknown"
                item.setdefault("accent_hex", _severity_accent(severity))
                item.setdefault("label", "Review")
                item.setdefault("summary", "Result interpreted.")
                classifications[metric_key] = item

        return classifications

    def _load_diagnosis_payload(
        self,
        measurements: Mapping[str, Any],
        classifications: Mapping[str, Mapping[str, Any]],
    ) -> Dict[str, Any]:
        diagnosis_payload: Dict[str, Any] = {}

        try:
            diagnosis_service = self.services.get("diagnosis_service") or self.services.get("diagnosis")
            if diagnosis_service is not None:
                for method_name in ("build_diagnosis", "generate_diagnosis", "diagnose", "run_diagnosis"):
                    method = getattr(diagnosis_service, method_name, None)
                    if not callable(method):
                        continue
                    try:
                        if method_name == "build_diagnosis":
                            raw = method(dict(measurements), classifications=dict(classifications), store_in_app_state=True)
                        else:
                            raw = method(dict(measurements))
                    except TypeError:
                        try:
                            raw = method(dict(measurements), classifications=dict(classifications))
                        except Exception:
                            continue
                    except Exception:
                        continue

                    if isinstance(raw, Mapping):
                        diagnosis_payload = dict(raw)
                        if diagnosis_payload:
                            break
        except Exception:
            pass

        if not diagnosis_payload:
            try:
                if self.app_state is not None:
                    current_diagnosis = getattr(self.app_state, "current_diagnosis", None)
                    if callable(current_diagnosis):
                        raw = current_diagnosis()
                        if isinstance(raw, Mapping):
                            diagnosis_payload = dict(raw)
            except Exception:
                pass

        return diagnosis_payload

    def _build_overall_summary(
        self,
        measurements: Mapping[str, Any],
        classifications: Mapping[str, Mapping[str, Any]],
    ) -> Dict[str, Any]:
        available_count = 0
        highest_metric = ""
        highest_rank = -1
        highest_classification: Dict[str, Any] = {}

        for metric_key in (
            METRIC_TEMPERATURE,
            METRIC_SPO2,
            METRIC_PULSE,
            METRIC_RR,
            METRIC_WEIGHT,
            METRIC_HEIGHT,
            METRIC_BMI,
        ):
            if measurements.get(metric_key) not in (None, ""):
                available_count += 1

            item = classifications.get(metric_key, {})
            severity = safe_str(item.get("severity"), "unknown").strip().lower()
            rank = _severity_rank(severity)
            if rank > highest_rank:
                highest_rank = rank
                highest_metric = metric_key
                highest_classification = dict(item)

        if highest_rank >= 4:
            overall_label = "Critical Attention"
            overall_severity = "critical"
        elif highest_rank >= 3:
            overall_label = "Review Needed"
            overall_severity = "warning"
        elif highest_rank >= 2:
            overall_label = "Monitor"
            overall_severity = "attention"
        elif available_count > 0:
            overall_label = "Within Expected Range"
            overall_severity = "normal"
        else:
            overall_label = "No Results"
            overall_severity = "unknown"

        accent_hex = _severity_accent(overall_severity)

        summary_lines: List[str] = []
        if available_count == 0:
            main_summary = "No completed session measurements are currently available."
        else:
            if highest_metric and highest_classification:
                metric_title = {
                    METRIC_TEMPERATURE: "temperature",
                    METRIC_SPO2: "SpO₂",
                    METRIC_PULSE: "pulse",
                    METRIC_RR: "respiratory rate",
                    METRIC_WEIGHT: "weight",
                    METRIC_HEIGHT: "height",
                    METRIC_BMI: "BMI",
                }.get(highest_metric, highest_metric)
                main_summary = (
                    f"The session captured {available_count} metrics. "
                    f"The most significant interpretation is for {metric_title}: "
                    f"{safe_str(highest_classification.get('summary'), '').strip()}"
                )
            else:
                main_summary = f"The session captured {available_count} metrics and is ready for review."

        if self._mode == MODE_DEMO:
            source_text = "Demo session"
        else:
            source_text = "Hardware session"

        if overall_severity == "critical":
            summary_lines.append("At least one metric falls in a critical interpretation band.")
        elif overall_severity == "warning":
            summary_lines.append("At least one metric is outside a comfortable reference range and should be reviewed.")
        elif overall_severity == "attention":
            summary_lines.append("Some values should be monitored closely.")
        elif overall_severity == "normal":
            summary_lines.append("The captured values mostly align with normal reference expectations.")

        if measurements.get(METRIC_BMI) not in (None, ""):
            summary_lines.append("BMI was computed successfully from captured weight and height.")
        else:
            summary_lines.append("BMI could not be computed because one or more supporting inputs were unavailable.")

        summary_lines.append("Open metric detail screens for more specific interpretation guidance.")

        return {
            "overall_label": overall_label,
            "overall_severity": overall_severity,
            "accent_hex": accent_hex,
            "main_summary": main_summary,
            "source_text": source_text,
            "available_count": available_count,
            "bullets": summary_lines[:3],
        }

    # =========================================================================
    # Applying UI payload
    # =========================================================================

    def _apply_results_payload(self, payload: Mapping[str, Any]) -> None:
        data = dict(payload or {})
        measurements = dict(data.get("measurements", {}))
        classifications = dict(data.get("classifications", {}))
        summary = dict(data.get("summary", {}))

        self._mode = safe_str(data.get("mode"), self._mode).strip().lower() or self._mode
        self._apply_mode_pill()

        available_count = safe_int(summary.get("available_count"), 0)
        overall_label = safe_str(summary.get("overall_label"), "Review").strip() or "Review"
        overall_severity = safe_str(summary.get("overall_severity"), "unknown").strip().lower() or "unknown"
        accent_hex = safe_str(summary.get("accent_hex"), _severity_accent(overall_severity)).strip() or _severity_accent(overall_severity)

        self.metrics_pill.setText(f"{available_count} Metrics Ready")
        self._apply_pill_style(self.metrics_pill, accent_hex)

        self.overall_chip.setText(overall_label)
        self.source_chip.setText(safe_str(summary.get("source_text"), "Session").strip() or "Session")
        self.detail_hint_chip.setText("Tap a supported metric for detail review")
        self._apply_header_chip_style(self.overall_chip, accent_hex)
        self._apply_header_chip_style(self.source_chip, "#67D8FF" if self._mode == MODE_DEMO else "#39D8FF")
        self._apply_header_chip_style(self.detail_hint_chip, "#39D8FF")

        main_summary = safe_str(summary.get("main_summary"), "").strip()
        self.summary_banner.setText(main_summary or "The active session is ready for review.")

        self.report_pill.setText("Report Ready" if self._report_path else "Report Pending")
        self._apply_pill_style(self.report_pill, "#42E393" if self._report_path else "#FFD25E")

        for metric_key, card in self.metric_cards.items():
            classification = dict(classifications.get(metric_key, {}))
            severity = safe_str(classification.get("severity"), "unknown").strip().lower()
            accent = safe_str(classification.get("accent_hex"), _severity_accent(severity)).strip() or _severity_accent(severity)
            label = safe_str(classification.get("label"), "Review").strip() or "Review"
            subtitle = safe_str(classification.get("summary"), "Captured value available.").strip() or "Captured value available."

            card.set_payload(
                value=measurements.get(metric_key),
                status_text=label,
                subtitle=subtitle,
                accent_hex=accent,
            )

        bullets = summary.get("bullets", [])
        if not isinstance(bullets, list):
            bullets = []


        self._set_button_accent(self.back_button, "#2F8FFF")
        self._set_button_accent(self.refresh_button, "#39D8FF")
        self._set_button_accent(self.report_button, "#FFD25E")
        self._set_button_accent(self.retake_button, "#FFD25E")
        self._set_button_accent(self.qr_button, "#67D8FF")
        self._set_button_accent(self.diagnosis_button, "#2F8FFF")
        self._set_button_accent(self.consult_button, "#42E393" if overall_severity in {"critical", "warning"} else "#39D8FF")

    def _apply_mode_pill(self) -> None:
        if self._mode == MODE_DEMO:
            self.mode_pill.setText("Demo Mode")
            self._apply_pill_style(self.mode_pill, "#67D8FF")
        else:
            self.mode_pill.setText("Hardware Mode")
            self._apply_pill_style(self.mode_pill, "#39D8FF")

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
                    border-radius: 16px;
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

    def _persist_results_payload(self) -> None:
        payload = dict(self._results_payload or {})
        if not payload:
            return

        try:
            session_service = self.services.get("session_service") or self.services.get("session")
            if session_service is not None:
                for method_name in (
                    "set_results_payload",
                    "set_current_session",
                    "set_session_payload",
                    "update_session",
                    "update_current_session",
                    "store_session",
                ):
                    method = getattr(session_service, method_name, None)
                    if callable(method):
                        try:
                            method(dict(payload))
                            break
                        except Exception:
                            continue
        except Exception:
            pass

        try:
            sensor_service = self.services.get("sensor_service") or self.services.get("sensor")
            if sensor_service is not None:
                for method_name in ("set_latest_results_payload", "set_latest_results", "update_latest_results"):
                    method = getattr(sensor_service, method_name, None)
                    if callable(method):
                        try:
                            method(dict(payload))
                            break
                        except Exception:
                            continue
        except Exception:
            pass

        try:
            if self.app_state is not None:
                for attr_name in ("results_payload", "current_session_payload", "session_payload"):
                    try:
                        setattr(self.app_state, attr_name, dict(payload))
                    except Exception:
                        continue
        except Exception:
            pass

    def _extract_artifact_path(self, result: Any, *, preferred_keys: Iterable[str]) -> str:
        if isinstance(result, Mapping):
            for key in list(preferred_keys) + ["path", "file_path", "report_path", "qr_path"]:
                value = safe_str(result.get(key), "").strip()
                if value:
                    return value
        return safe_str(result, "").strip()

    def _current_session_payload_for_services(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}

        try:
            session_service = self.services.get("session_service") or self.services.get("session")
            if session_service is not None:
                snapshot_method = getattr(session_service, "snapshot", None)
                if callable(snapshot_method):
                    raw_snapshot = snapshot_method()
                    if isinstance(raw_snapshot, Mapping):
                        payload = dict(raw_snapshot)
        except Exception:
            payload = {}

        if not payload:
            try:
                if self.app_state is not None:
                    snapshot_method = getattr(self.app_state, "session_snapshot", None)
                    if callable(snapshot_method):
                        raw_snapshot = snapshot_method()
                        if isinstance(raw_snapshot, Mapping):
                            payload = dict(raw_snapshot)
            except Exception:
                payload = {}

        results_payload = dict(self._results_payload or {})
        result_measurements = dict(results_payload.get("measurements", {}) or {})
        result_summary = dict(results_payload.get("summary", {}) or {})
        result_diagnosis = dict(results_payload.get("diagnosis", {}) or {})

        payload["mode"] = safe_str(payload.get("mode"), self._mode).strip() or self._mode
        payload["measurements"] = result_measurements or dict(payload.get("measurements", {}) or {})
        payload["results_summary"] = result_summary
        payload["classifications"] = dict(results_payload.get("classifications", {}) or {})
        payload["diagnosis"] = result_diagnosis or dict(payload.get("diagnosis", {}) or {})
        payload["origin_screen"] = "results"

        if self._report_path:
            payload["report_path"] = self._report_path
        elif safe_str(payload.get("report_path"), "").strip():
            self._report_path = safe_str(payload.get("report_path"), "").strip()

        if self._qr_path:
            payload["qr_path"] = self._qr_path
        elif safe_str(payload.get("qr_path"), "").strip():
            self._qr_path = safe_str(payload.get("qr_path"), "").strip()

        return payload

    def _set_button_text_temporarily(self, button: QWidget, text: str, duration_ms: int = 1400) -> None:
        setter = getattr(button, "setText", None)
        getter = getattr(button, "text", None)
        if not callable(setter) or not callable(getter):
            return

        original_text = safe_str(getter(), "").strip()
        if not original_text:
            return

        try:
            setter(text)
        except Exception:
            return

        def _restore() -> None:
            try:
                setter(original_text)
                self._apply_responsive_layout()
            except Exception:
                pass

        QTimer.singleShot(max(300, int(duration_ms)), _restore)

    def _show_transient_banner_message(
        self,
        message: str,
        *,
        accent_hex: str = "#39D8FF",
        duration_ms: int = 1800,
    ) -> None:
        previous_text = safe_str(self.summary_banner.text(), "").strip()
        previous_chip_text = safe_str(self.overall_chip.text(), "").strip()

        self.summary_banner.setText(safe_str(message, "").strip() or previous_text)
        self.overall_chip.setText("Updated")
        self._apply_header_chip_style(self.overall_chip, accent_hex)

        def _restore() -> None:
            try:
                self.summary_banner.setText(previous_text)
                self.overall_chip.setText(previous_chip_text)
                summary = dict((self._results_payload or {}).get("summary", {}) or {})
                overall_label = safe_str(summary.get("overall_label"), previous_chip_text).strip() or previous_chip_text
                overall_severity = safe_str(summary.get("overall_severity"), "normal").strip().lower() or "normal"
                self.overall_chip.setText(overall_label)
                self._apply_header_chip_style(self.overall_chip, _severity_accent(overall_severity))
            except Exception:
                pass

        QTimer.singleShot(max(500, int(duration_ms)), _restore)

    def _animate_cards_refresh(self) -> None:
        """
        Keep refresh feedback instant and lightweight for the 800x480 kiosk.

        Earlier opacity animations looked attractive in isolation, but on the
        compact Raspberry Pi style layout they introduced visible flicker,
        partial repaints, and the impression that the screen was lagging.
        For the results page the user expectation is immediate response, so the
        refresh effect now simply clears any stale graphics effects and forces a
        clean repaint instead of fading cards in and out.
        """
        for card in self.metric_cards.values():
            try:
                effect = card.graphicsEffect()
                if isinstance(effect, QGraphicsOpacityEffect):
                    try:
                        effect.setOpacity(1.0)
                    except Exception:
                        pass
                    card.setGraphicsEffect(None)
                card.update()
                card.repaint()
            except Exception:
                continue

    # =========================================================================
    # Report / QR preparation
    # =========================================================================

    def _prepare_report(self) -> str:
        payload = self._current_session_payload_for_services()
        if not payload:
            return ""

        measurements = dict(payload.get("measurements", {}) or {})
        diagnosis_payload = dict(payload.get("diagnosis", {}) or {})
        path = ""

        try:
            report_service = self.services.get("report_service") or self.services.get("report")
            if report_service is not None:
                for method_name in (
                    "generate_report",
                    "create_report",
                    "build_report",
                    "generate_pdf_report",
                    "create_pdf_report",
                    "export_report",
                    "generate_current_session_report",
                ):
                    method = getattr(report_service, method_name, None)
                    if not callable(method):
                        continue

                    call_patterns = []
                    if method_name == "generate_current_session_report":
                        call_patterns.extend([
                            lambda m=method: m(),
                            lambda m=method: m(persist_to_database=True),
                        ])
                    else:
                        call_patterns.extend([
                            lambda m=method: m(session_payload=payload, measurements=measurements, diagnosis_payload=diagnosis_payload),
                            lambda m=method: m(session_payload=payload, measurements=measurements),
                            lambda m=method: m(session_payload=payload),
                            lambda m=method: m(measurements=measurements),
                            lambda m=method: m(dict(payload)),
                        ])

                    for caller in call_patterns:
                        try:
                            result = caller()
                            path = self._extract_artifact_path(result, preferred_keys=("report_path",))
                            if path:
                                break
                        except Exception:
                            continue
                    if path:
                        break
        except Exception:
            pass

        self._report_path = path
        self._results_payload["report_path"] = self._report_path
        self.report_pill.setText("Report Ready" if self._report_path else "Report Pending")
        self._apply_pill_style(self.report_pill, "#42E393" if self._report_path else "#FFD25E")

        self._persist_artifact_paths()
        return self._report_path

    def _prepare_qr(self) -> str:
        payload = self._current_session_payload_for_services()
        if not payload:
            return ""

        measurements = dict(payload.get("measurements", {}) or {})
        diagnosis_payload = dict(payload.get("diagnosis", {}) or {})
        path = ""

        try:
            qr_service = self.services.get("qr_service") or self.services.get("qr")
            if qr_service is not None:
                for method_name in (
                    "generate_qr",
                    "create_qr",
                    "build_qr",
                    "generate_session_qr",
                    "create_session_qr",
                    "generate_qr_for_session_id",
                ):
                    method = getattr(qr_service, method_name, None)
                    if not callable(method):
                        continue

                    call_patterns = []
                    if method_name == "generate_qr_for_session_id":
                        session_id = safe_str(payload.get("session_id"), "").strip()
                        if session_id:
                            call_patterns.append(lambda m=method, s=session_id: m(s))
                    else:
                        call_patterns.extend([
                            lambda m=method: m(session_payload=payload, measurements=measurements, diagnosis_payload=diagnosis_payload),
                            lambda m=method: m(session_payload=payload, measurements=measurements),
                            lambda m=method: m(session_payload=payload),
                            lambda m=method: m(measurements=measurements),
                            lambda m=method: m(dict(payload)),
                        ])

                    for caller in call_patterns:
                        try:
                            result = caller()
                            path = self._extract_artifact_path(result, preferred_keys=("qr_path",))
                            if path:
                                break
                        except Exception:
                            continue
                    if path:
                        break
        except Exception:
            pass

        self._qr_path = path
        self._results_payload["qr_path"] = self._qr_path
        self._persist_artifact_paths()
        return self._qr_path

    def _persist_artifact_paths(self) -> None:
        try:
            session_service = self.services.get("session_service") or self.services.get("session")
            if session_service is not None:
                for method_name in ("set_report_path", "update_report_path", "set_qr_path", "update_qr_path"):
                    method = getattr(session_service, method_name, None)
                    if callable(method):
                        try:
                            if "report" in method_name and self._report_path:
                                method(self._report_path)
                            elif "qr" in method_name and self._qr_path:
                                method(self._qr_path)
                        except Exception:
                            continue
        except Exception:
            pass

        try:
            if self.app_state is not None:
                if self._report_path and hasattr(self.app_state, "report_path"):
                    setattr(self.app_state, "report_path", self._report_path)
                if self._qr_path and hasattr(self.app_state, "qr_path"):
                    setattr(self.app_state, "qr_path", self._qr_path)
        except Exception:
            pass

    # =========================================================================
    # Actions / navigation
    # =========================================================================

    def _handle_refresh_clicked(self) -> None:
        """
        Refresh should feel immediate.

        The previous version changed the button text and ran a fade animation on
        every tile. On the compact kiosk that made the cards look like they were
        disappearing and reloading slowly. This handler now performs a direct
        refresh with updates briefly paused so the new values appear in one clean
        pass.
        """
        try:
            self.setUpdatesEnabled(False)
            self.reload_results()
        finally:
            self.setUpdatesEnabled(True)

        self._animate_cards_refresh()
        self.update()
        self.repaint()

        self._show_transient_banner_message(
            "Results refreshed.",
            accent_hex="#39D8FF",
            duration_ms=700,
        )

    def _handle_back_clicked(self) -> None:
        if self._navigate_to(SCREEN_MEASURING):
            return
        self.back_requested.emit()

    def _handle_retake_clicked(self) -> None:
        if self._navigate_to(SCREEN_MEASURING):
            self.retake_requested.emit()
            return
        self.retake_requested.emit()

    def _handle_qr_clicked(self) -> None:
        self._prepare_qr()
        payload = dict(self._results_payload)
        payload["qr_path"] = self._qr_path

        if self._navigate_to(SCREEN_QR):
            self.qr_requested.emit(payload)
            return

        self.qr_requested.emit(payload)

    def _handle_diagnosis_clicked(self) -> None:
        payload = self._current_session_payload_for_services()
        payload["origin_screen"] = "results"
        self._results_payload["origin_screen"] = "results"
        self._persist_results_payload()

        if self._navigate_to(SCREEN_RESULTS_DIAGNOSIS):
            self.diagnosis_requested.emit(payload)
            return

        self.diagnosis_requested.emit(payload)

    def _handle_consult_clicked(self) -> None:
        payload = dict(self._results_payload)

        if self._navigate_to(SCREEN_CONSULT):
            self.consult_requested.emit(payload)
            return

        self.consult_requested.emit(payload)

    def _handle_report_clicked(self) -> None:
        self._set_button_text_temporarily(self.report_button, "Generating...", 1800)
        report_path = self._prepare_report()

        if report_path:
            report_name = Path(report_path).name
            self._show_transient_banner_message(
                f"Report generated successfully: {report_name}",
                accent_hex="#42E393",
                duration_ms=2200,
            )
        else:
            self._show_transient_banner_message(
                "Report generation failed. Please try again.",
                accent_hex="#FFB84D",
                duration_ms=2200,
            )

        payload = dict(self._results_payload)
        payload["report_path"] = self._report_path
        self.report_requested.emit(payload)

    def _handle_metric_card_clicked(self, metric_key: str) -> None:
        metric = safe_str(metric_key, "").strip()
        if not metric:
            return

        self._persist_selected_metric(metric)
        target = self._detail_screen_for_metric(metric)
        if target and self._navigate_to(target):
            self.metric_detail_requested.emit(metric)
            return

        self.metric_detail_requested.emit(metric)

    def _persist_selected_metric(self, metric_key: str) -> None:
        try:
            session_service = self.services.get("session_service") or self.services.get("session")
            if session_service is not None:
                for method_name in ("set_selected_metric", "set_focus_metric", "update_focus_metric"):
                    method = getattr(session_service, method_name, None)
                    if callable(method):
                        try:
                            method(metric_key)
                            break
                        except Exception:
                            continue
        except Exception:
            pass

        try:
            if self.app_state is not None:
                for attr_name in ("selected_metric", "focus_metric", "current_metric"):
                    if hasattr(self.app_state, attr_name):
                        try:
                            setattr(self.app_state, attr_name, metric_key)
                        except Exception:
                            pass
        except Exception:
            pass

    def _detail_screen_for_metric(self, metric_key: str) -> str:
        mapping = {
            METRIC_TEMPERATURE: SCREEN_TEMPERATURE_DETAIL,
            METRIC_SPO2: SCREEN_SPO2_DETAIL,
            METRIC_PULSE: SCREEN_PULSE_DETAIL,
            METRIC_RR: SCREEN_RR_DETAIL,
            METRIC_BMI: SCREEN_BMI_DETAIL,
        }
        return mapping.get(metric_key, "")

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
    # Paint
    # =========================================================================

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        painter = QPainter(self)
        try:
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
            painter.fillRect(QRectF(0.0, 0.0, float(rect.width()), rect.height() * 0.38), QColor(53, 214, 255, 16))
            painter.fillRect(QRectF(0.0, rect.height() * 0.60, float(rect.width()), rect.height() * 0.40), QColor(20, 82, 128, 18))
        finally:
            painter.end()

    # =========================================================================
    # Diagnostics
    # =========================================================================

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "mode": self._mode,
            "results_payload_keys": list(self._results_payload.keys()),
            "report_path": self._report_path,
            "qr_path": self._qr_path,
            "background_path": self._background_path,
            "metric_card_count": len(self.metric_cards),
        }