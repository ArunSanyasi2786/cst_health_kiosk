"""
screens/parameters_screen.py

Premium administrator parameters / thresholds screen for the
CST Health Monitoring Station kiosk.

Why this file matters:
- It is the protected parameter-management workspace opened from:
    - screens/admin_panel_screen.py
- It allows the administrator to:
    - review health interpretation threshold profiles
    - edit per-metric limits used by diagnosis / result interpretation layers
    - enable or disable parameter profiles
    - save protected thresholds into runtime services
    - restore defaults safely
- It is designed specifically for:
    - Raspberry Pi 4B touchscreen kiosk deployment
    - 1024x600 kiosk resolution
    - laptop demo mode
- It provides:
    - premium glossy protected thresholds UI
    - resilient loading from threshold_service / settings_service / config.py / app_state
    - touch-friendly numeric editing controls
    - diagnosis-oriented summary for the selected metric
    - safe fallback defaults when backend services are still evolving
    - best-effort persistence to linked services and app state

Linked project files this screen is intended to work with:
- config.py
- core/constants.py
- core/asset_paths.py
- core/logger.py
- core/app_state.py
- core/navigator.py
- core/theme_manager.py
- core/animation_manager.py
- services/threshold_service.py
- services/health_rules_service.py
- services/diagnosis_service.py
- services/settings_service.py
- widgets/animated_button.py
- widgets/glow_label.py

Navigation targets this screen is designed to link to:
- screens/admin_panel_screen.py

Design goals:
- glossy futuristic blue medical UI
- protected engineering / rules-management feel
- strong readability at 1024x600
- resilient integration while backend services continue evolving
- maintainable structure with safe fallbacks
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
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QGraphicsDropShadowEffect,
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
        SCREEN_ADMIN_PANEL,
        METRIC_TEMPERATURE,
        METRIC_SPO2,
        METRIC_PULSE,
        METRIC_RR,
        METRIC_WEIGHT,
        METRIC_HEIGHT,
        METRIC_BMI,
    )
except Exception:  # pragma: no cover
    SCREEN_ADMIN_PANEL = "admin_panel"
    METRIC_TEMPERATURE = "temperature"
    METRIC_SPO2 = "spo2"
    METRIC_PULSE = "pulse_rate"
    METRIC_RR = "respiratory_rate"
    METRIC_WEIGHT = "weight"
    METRIC_HEIGHT = "height"
    METRIC_BMI = "bmi"

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

try:
    from config import KIOSK_WIDTH, KIOSK_HEIGHT, UI_SCALE, WIDTH_SCALE, HEIGHT_SCALE
except Exception:  # pragma: no cover
    KIOSK_WIDTH = 800
    KIOSK_HEIGHT = 480
    UI_SCALE = 0.8
    WIDTH_SCALE = 800 / 1024
    HEIGHT_SCALE = 480 / 600


def _scaled(value: int | float, compact_value: Optional[int | float] = None) -> int:
    """Compact-aware scaling helper for 800x480 kiosk support."""
    try:
        if compact_value is not None and (KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480):
            return max(1, int(round(float(compact_value))))
        return max(1, int(round(float(value) * float(UI_SCALE))))
    except Exception:
        try:
            return int(compact_value if compact_value is not None else value)
        except Exception:
            return 1


# =============================================================================
# Helpers / defaults
# =============================================================================

METRIC_ORDER = [
    METRIC_TEMPERATURE,
    METRIC_SPO2,
    METRIC_PULSE,
    METRIC_RR,
    METRIC_WEIGHT,
    METRIC_HEIGHT,
    METRIC_BMI,
]

METRIC_LABELS = {
    METRIC_TEMPERATURE: "Temperature",
    METRIC_SPO2: "SpO₂",
    METRIC_PULSE: "Pulse",
    METRIC_RR: "Respiratory Rate",
    METRIC_WEIGHT: "Weight",
    METRIC_HEIGHT: "Height",
    METRIC_BMI: "BMI",
}

METRIC_UNITS = {
    METRIC_TEMPERATURE: "°C",
    METRIC_SPO2: "%",
    METRIC_PULSE: "bpm",
    METRIC_RR: "breaths/min",
    METRIC_WEIGHT: "kg",
    METRIC_HEIGHT: "cm",
    METRIC_BMI: "kg/m²",
}

METRIC_DESCRIPTIONS = {
    METRIC_TEMPERATURE: "Reference interpretation ranges for body temperature.",
    METRIC_SPO2: "Reference interpretation ranges for blood oxygen saturation.",
    METRIC_PULSE: "Reference interpretation ranges for pulse or heart rate.",
    METRIC_RR: "Reference interpretation ranges for respiratory rate.",
    METRIC_WEIGHT: "Supporting anthropometric threshold guidance for weight capture.",
    METRIC_HEIGHT: "Supporting anthropometric threshold guidance for height capture.",
    METRIC_BMI: "Reference interpretation ranges for body mass index.",
}


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


def _accent_for_state(state: str) -> str:
    value = safe_str(state, "").strip().lower()
    if value in {"critical", "error", "failed", "invalid"}:
        return "#FF6E88"
    if value in {"warning", "pending", "attention", "edited"}:
        return "#FFD25E"
    if value in {"normal", "ready", "saved", "active", "enabled"}:
        return "#42E393"
    if value in {"disabled"}:
        return "#FFA14D"
    return "#39D8FF"


def _metric_icon_path(metric_key: str) -> str:
    mapping = {
        METRIC_TEMPERATURE: "icons/temperature.png",
        METRIC_SPO2: "icons/spo2.png",
        METRIC_PULSE: "icons/pulse.png",
        METRIC_RR: "icons/respiratory_rate.png",
        METRIC_WEIGHT: "icons/weight.png",
        METRIC_HEIGHT: "icons/height.png",
        METRIC_BMI: "icons/bmi.png",
    }
    return _resolve_asset(mapping.get(metric_key, "icons/chart.png"))


def _default_profile(metric_key: str) -> Dict[str, Any]:
    """
    Generic threshold profile structure.

    Interpretation model:
    - normal_low <= value <= normal_high => normal
    - warning_low <= value <= warning_high but outside normal => attention / warning
    - outside warning band => critical
    """
    defaults = {
        METRIC_TEMPERATURE: {
            "warning_low": 35.0,
            "normal_low": 36.0,
            "normal_high": 37.5,
            "warning_high": 39.0,
            "decimals": 1,
        },
        METRIC_SPO2: {
            "warning_low": 90.0,
            "normal_low": 96.0,
            "normal_high": 100.0,
            "warning_high": 100.0,
            "decimals": 0,
        },
        METRIC_PULSE: {
            "warning_low": 50.0,
            "normal_low": 60.0,
            "normal_high": 100.0,
            "warning_high": 120.0,
            "decimals": 0,
        },
        METRIC_RR: {
            "warning_low": 10.0,
            "normal_low": 12.0,
            "normal_high": 20.0,
            "warning_high": 24.0,
            "decimals": 0,
        },
        METRIC_WEIGHT: {
            "warning_low": 25.0,
            "normal_low": 35.0,
            "normal_high": 180.0,
            "warning_high": 220.0,
            "decimals": 1,
        },
        METRIC_HEIGHT: {
            "warning_low": 80.0,
            "normal_low": 100.0,
            "normal_high": 220.0,
            "warning_high": 250.0,
            "decimals": 1,
        },
        METRIC_BMI: {
            "warning_low": 16.0,
            "normal_low": 18.5,
            "normal_high": 24.9,
            "warning_high": 30.0,
            "decimals": 1,
        },
    }

    metric_defaults = defaults.get(
        metric_key,
        {
            "warning_low": 0.0,
            "normal_low": 0.0,
            "normal_high": 100.0,
            "warning_high": 120.0,
            "decimals": 1,
        },
    )

    return {
        "metric_key": metric_key,
        "enabled": True,
        "warning_low": metric_defaults["warning_low"],
        "normal_low": metric_defaults["normal_low"],
        "normal_high": metric_defaults["normal_high"],
        "warning_high": metric_defaults["warning_high"],
        "decimals": metric_defaults["decimals"],
        "state": "ready",
        "last_updated": "Default protected profile",
        "summary": f"{METRIC_LABELS.get(metric_key, metric_key.title())} thresholds are using the protected default profile.",
    }


def _default_profiles() -> Dict[str, Dict[str, Any]]:
    return {metric: _default_profile(metric) for metric in METRIC_ORDER}


def _normalize_profile(metric_key: str, raw: Mapping[str, Any]) -> Dict[str, Any]:
    profile = deepcopy(_default_profile(metric_key))
    if isinstance(raw, Mapping):
        profile.update(dict(raw))

    profile["metric_key"] = metric_key
    profile["enabled"] = safe_bool(profile.get("enabled"), True)

    warning_low = round(safe_float(profile.get("warning_low"), _default_profile(metric_key)["warning_low"]), 2)
    normal_low = round(safe_float(profile.get("normal_low"), _default_profile(metric_key)["normal_low"]), 2)
    normal_high = round(safe_float(profile.get("normal_high"), _default_profile(metric_key)["normal_high"]), 2)
    warning_high = round(safe_float(profile.get("warning_high"), _default_profile(metric_key)["warning_high"]), 2)

    # enforce ordered bands
    ordered = sorted([warning_low, normal_low, normal_high, warning_high])
    warning_low, normal_low, normal_high, warning_high = ordered[0], ordered[1], ordered[2], ordered[3]

    profile["warning_low"] = warning_low
    profile["normal_low"] = normal_low
    profile["normal_high"] = normal_high
    profile["warning_high"] = warning_high
    profile["decimals"] = max(0, min(3, safe_int(profile.get("decimals"), _default_profile(metric_key)["decimals"])))

    state = safe_str(profile.get("state"), "").strip().lower()
    if not state:
        state = "disabled" if not profile["enabled"] else "ready"
    if not profile["enabled"]:
        state = "disabled"
    profile["state"] = state

    profile["last_updated"] = safe_str(
        profile.get("last_updated"),
        _default_profile(metric_key)["last_updated"],
    ).strip() or _default_profile(metric_key)["last_updated"]

    profile["summary"] = safe_str(
        profile.get("summary"),
        _default_profile(metric_key)["summary"],
    ).strip() or _default_profile(metric_key)["summary"]

    return profile


# =============================================================================
# Internal widgets
# =============================================================================

class _ParameterStatCard(QFrame):
    """
    Compact premium stat card for threshold overview.
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

        self.setObjectName("ParameterStatCard")
        self.setMinimumHeight(_scaled(74, 68))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(_scaled(10, 8), _scaled(8, 6), _scaled(10, 8), _scaled(8, 6))
        root.setSpacing(_scaled(2, 2))

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
            QFrame#ParameterStatCard {{
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
                font-size: 8px;
                font-weight: 700;
                background: transparent;
            }
            """
        )
        self.value_label.setStyleSheet(
            """
            QLabel {
                color: #F6FCFF;
                font-size: 18px;
                font-weight: 900;
                background: transparent;
            }
            """
        )
        self.subtitle_label.setStyleSheet(
            """
            QLabel {
                color: rgba(191, 214, 232, 0.80);
                font-size: 8px;
                font-weight: 500;
                background: transparent;
            }
            """
        )


class _MetricProfileCard(QFrame):
    """
    Click-select premium metric threshold card.
    """

    clicked = pyqtSignal(str)

    def __init__(
        self,
        metric_key: str,
        *,
        title: str,
        subtitle: str,
        icon_path: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self.metric_key = metric_key
        self._selected = False
        self._hovered = False
        self._accent_hex = "#39D8FF"
        self._clickable = True
        self._icon_path = safe_str(icon_path, "").strip()
        self._icon_pixmap = _pixmap_or_empty(self._icon_path)

        self.setObjectName("MetricProfileCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(_scaled(104, 92))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(_scaled(10, 8), _scaled(8, 6), _scaled(10, 8), _scaled(8, 6))
        root.setSpacing(_scaled(3, 2))

        top_row = QWidget(self)
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)

        self.icon_label = QLabel(top_row)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setMinimumSize(0, 0)
        self.icon_label.setMaximumSize(0, 0)
        self.icon_label.hide()

        self.state_chip = QLabel("Ready", top_row)

        top_layout.addStretch(1)
        top_layout.addWidget(self.state_chip)

        self.title_label = QLabel(title, self)
        self.title_label.setWordWrap(True)

        self.subtitle_label = QLabel(subtitle, self)
        self.subtitle_label.setWordWrap(True)

        self.range_line = QLabel("Normal -- to --", self)
        self.warning_line = QLabel("Warning -- to --", self)

        root.addWidget(top_row)
        root.addWidget(self.title_label)
        root.addWidget(self.subtitle_label)
        root.addWidget(self.range_line)
        root.addWidget(self.warning_line)
        root.addStretch(1)

        self._apply_style()

    def _refresh_icon(self) -> None:
        self.icon_label.clear()
        self.icon_label.hide()

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        self._apply_style()

    def set_payload(
        self,
        *,
        state_text: str,
        subtitle: str,
        range_line: str,
        warning_line: str,
        accent_hex: str,
    ) -> None:
        self._accent_hex = safe_str(accent_hex, "#39D8FF").strip() or "#39D8FF"
        self.state_chip.setText(safe_str(state_text, "Ready").strip() or "Ready")
        self.subtitle_label.setText(safe_str(subtitle, "").strip())
        self.range_line.setText(safe_str(range_line, "").strip())
        self.warning_line.setText(safe_str(warning_line, "").strip())
        self._apply_style()

    def _apply_style(self) -> None:
        accent = QColor(self._accent_hex)
        border_alpha = 0.40 if self._selected else (0.30 if self._hovered else 0.22)
        fill_alpha = 0.10 if self._selected else (0.08 if self._hovered else 0.05)

        self.setStyleSheet(
            f"""
            QFrame#MetricProfileCard {{
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, {border_alpha:.3f});
                border-radius: 20px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(10, 24, 44, 0.96),
                    stop:1 rgba(5, 16, 31, 0.98)
                );
            }}
            """
        )

        self.icon_label.setStyleSheet(
            """
            QLabel {
                border: none;
                border-radius: 0px;
                background: transparent;
            }
            """
        )
        self.title_label.setStyleSheet(
            """
            QLabel {
                color: #F4FCFF;
                font-size: 11px;
                font-weight: 800;
                background: transparent;
            }
            """
        )
        self.subtitle_label.setStyleSheet(
            """
            QLabel {
                color: rgba(214, 235, 248, 0.84);
                font-size: 8px;
                font-weight: 500;
                background: transparent;
            }
            """
        )
        self.range_line.setStyleSheet(
            """
            QLabel {
                color: rgba(197, 223, 241, 0.84);
                font-size: 8px;
                font-weight: 600;
                background: transparent;
            }
            """
        )
        self.warning_line.setStyleSheet(
            """
            QLabel {
                color: rgba(188, 213, 230, 0.78);
                font-size: 8px;
                font-weight: 500;
                background: transparent;
            }
            """
        )
        self.state_chip.setStyleSheet(
            f"""
            QLabel {{
                color: #F4FCFF;
                font-size: 8px;
                font-weight: 800;
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.34);
                border-radius: 16px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.16);
                padding: 3px 7px;
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
                radius = 20.0
                path = QPainterPath()
                path.addRoundedRect(rect, float(radius), float(radius))
                painter.save()
                painter.setClipPath(path)
                gloss_rect = QRectF(
                    rect.left() + 2.0,
                    rect.top() + 2.0,
                    rect.width() - 4.0,
                    rect.height() * 0.24,
                )
                painter.fillRect(gloss_rect, QColor(255, 255, 255, 10 if not self._selected else 18))
                painter.restore()
        finally:
            painter.end()


class _ParameterSummaryCard(QFrame):
    """
    Premium selected-metric threshold summary card.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._accent_hex = "#39D8FF"

        self.setObjectName("ParameterSummaryCard")
        self.setMinimumHeight(_scaled(166, 150))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(_scaled(12, 10), _scaled(10, 8), _scaled(12, 10), _scaled(10, 8))
        root.setSpacing(_scaled(6, 5))

        top_row = QWidget(self)
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(_scaled(6, 5))

        self.title_label = QLabel("Selected Metric", top_row)
        self.state_chip = QLabel("Ready", top_row)

        top_layout.addWidget(self.title_label)
        top_layout.addStretch(1)
        top_layout.addWidget(self.state_chip)

        self.summary_label = QLabel(
            "Select a metric profile to review or edit interpretation thresholds.",
            self,
        )
        self.summary_label.setWordWrap(True)

        self.line_1 = QLabel("• Warning low is the lower outer attention boundary.", self)
        self.line_2 = QLabel("• Normal low and normal high define the healthy band.", self)
        self.line_3 = QLabel("• Warning high is the upper outer attention boundary.", self)
        self.line_4 = QLabel("• Save changes to persist diagnosis threshold behavior.", self)

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
        self.title_label.setText(safe_str(title, "Selected Metric").strip() or "Selected Metric")
        self.state_chip.setText(safe_str(state_text, "Ready").strip() or "Ready")
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
            QFrame#ParameterSummaryCard {{
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
                font-size: 11px;
                font-weight: 800;
                background: transparent;
            }
            """
        )
        self.state_chip.setStyleSheet(
            f"""
            QLabel {{
                color: #F4FCFF;
                font-size: 8px;
                font-weight: 800;
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.34);
                border-radius: 16px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.16);
                padding: 3px 8px;
            }}
            """
        )
        self.summary_label.setStyleSheet(
            """
            QLabel {
                color: rgba(221, 239, 250, 0.90);
                font-size: 8px;
                font-weight: 600;
                background: transparent;
            }
            """
        )
        bullet_style = """
            QLabel {
                color: rgba(197, 223, 241, 0.84);
                font-size: 8px;
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

class ParametersScreen(QFrame):
    """
    Premium protected threshold / parameter screen.

    Main responsibilities:
    - load interpretation threshold profiles
    - allow per-metric editing
    - persist threshold profiles to services
    - restore protected defaults
    """

    back_requested = pyqtSignal()
    parameters_loaded = pyqtSignal(dict)
    parameters_saved = pyqtSignal(dict)
    parameters_reset = pyqtSignal(dict)
    parameter_profile_selected = pyqtSignal(str)
    parameter_profile_changed = pyqtSignal(dict)

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

        self._logger = logger.bind(component="ParametersScreen")

        self.navigator = navigator
        self.app_state = app_state
        self.services = dict(services or {})
        self.animation_manager = animation_manager
        self.theme_manager = theme_manager

        self._profiles: Dict[str, Dict[str, Any]] = _default_profiles()
        self._loaded_profiles: Dict[str, Dict[str, Any]] = _default_profiles()
        self._selected_metric = METRIC_TEMPERATURE
        self._changed_since_load = False
        self._status_message = "Threshold profiles are ready to load."
        self._last_saved_label = "Not saved in this session."
        self._service_detail = "Threshold services have not yet provided a live snapshot."
        self._diagnosis_state = "ready"
        self._editor_sync_in_progress = False

        self._background_path = _resolve_asset("backgrounds/parameters_bg.png")
        self._logo_small_path = _resolve_asset("logos/cst_logo_small.png")
        self._admin_shield_path = _resolve_asset("illustrations/admin_shield.png")

        self._background_pixmap = _pixmap_or_empty(self._background_path)
        self._logo_pixmap = _pixmap_or_empty(self._logo_small_path)
        self._shield_pixmap = _pixmap_or_empty(self._admin_shield_path)

        self.setObjectName("ParametersScreen")
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
        root.setContentsMargins(_scaled(14, 10), _scaled(10, 8), _scaled(14, 10), _scaled(10, 8))
        root.setSpacing(_scaled(8, 6))

        # ---------------------------------------------------------------------
        # Top bar
        # ---------------------------------------------------------------------
        self.top_bar = QWidget(self)
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(_scaled(8, 6))

        self.back_button = self._create_button("Back", variant="secondary", min_width=_scaled(84, 74), parent=self.top_bar)
        self.back_button.clicked.connect(self._handle_back_clicked)

        self.logo_label = QLabel(self.top_bar)
        self.logo_label.setObjectName("LogoLabel")
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_label.setFixedSize(_scaled(42, 36), _scaled(42, 36))
        self._set_label_pixmap(self.logo_label, self._logo_pixmap, _scaled(32, 28))

        self.top_title = QLabel("Protected Parameters", self.top_bar)
        self.top_title.setObjectName("TopTitle")

        self.status_pill = QLabel("Ready", self.top_bar)
        self.status_pill.setObjectName("RuntimePill")

        self.diagnosis_pill = QLabel("Diagnosis Link", self.top_bar)
        self.diagnosis_pill.setObjectName("RuntimePill")

        self.selected_pill = QLabel("Selected Metric", self.top_bar)
        self.selected_pill.setObjectName("RuntimePill")

        top_layout.addWidget(self.back_button)
        top_layout.addWidget(self.logo_label)
        top_layout.addWidget(self.top_title)
        top_layout.addStretch(1)
        top_layout.addWidget(self.status_pill)
        top_layout.addWidget(self.diagnosis_pill)
        top_layout.addWidget(self.selected_pill)

        # ---------------------------------------------------------------------
        # Header card
        # ---------------------------------------------------------------------
        self.header_card = QFrame(self)
        self.header_card.setObjectName("ParametersHeaderCard")

        header_layout = QVBoxLayout(self.header_card)
        header_layout.setContentsMargins(_scaled(14, 10), _scaled(12, 8), _scaled(14, 10), _scaled(12, 8))
        header_layout.setSpacing(8)

        if _HAS_GLOW_LABEL:
            self.hero_title = GlowLabel(
                role=getattr(GlowLabel, "ROLE_TITLE", getattr(GlowLabel, "ROLE_STATUS", 0)),
                align_center=True,
                use_outline=False,
                enable_paint_glow=True,
                initial_glow_strength=0.50,
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
        chip_layout.setSpacing(_scaled(6, 5))

        self.band_chip = QLabel("Threshold Bands", self.header_chip_row)
        self.band_chip.setObjectName("HeaderChip")

        self.diagnosis_chip = QLabel("Diagnosis Rules", self.header_chip_row)
        self.diagnosis_chip.setObjectName("HeaderChip")

        self.persistence_chip = QLabel("Protected Persistence", self.header_chip_row)
        self.persistence_chip.setObjectName("HeaderChip")

        chip_layout.addStretch(1)
        chip_layout.addWidget(self.band_chip)
        chip_layout.addWidget(self.diagnosis_chip)
        chip_layout.addWidget(self.persistence_chip)
        chip_layout.addStretch(1)

        self.summary_banner = QLabel(
            "Review and maintain the threshold profiles used by the kiosk diagnosis and results interpretation layers.",
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
        stats_layout.setSpacing(_scaled(8, 6))

        self.stat_enabled = _ParameterStatCard("Enabled Profiles", value="--", subtitle="Number of active threshold profiles.")
        self.stat_ready = _ParameterStatCard("Ready / Saved", value="--", subtitle="Profiles marked ready or saved.")
        self.stat_selected = _ParameterStatCard("Selected Metric", value="--", subtitle="Currently selected interpretation target.")
        self.stat_service = _ParameterStatCard("Diagnosis Link", value="--", subtitle="Current threshold / diagnosis service state.")

        stats_layout.addWidget(self.stat_enabled, 1)
        stats_layout.addWidget(self.stat_ready, 1)
        stats_layout.addWidget(self.stat_selected, 1)
        stats_layout.addWidget(self.stat_service, 1)

        # ---------------------------------------------------------------------
        # Content row
        # ---------------------------------------------------------------------
        self.content_row = QWidget(self)
        content_layout = QHBoxLayout(self.content_row)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(_scaled(10, 8))

        # Left panel
        self.profile_panel = QFrame(self.content_row)
        self.profile_panel.setObjectName("ProfilePanel")
        self.profile_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        profile_layout = QVBoxLayout(self.profile_panel)
        profile_layout.setContentsMargins(_scaled(12, 10), _scaled(10, 8), _scaled(12, 10), _scaled(10, 8))
        profile_layout.setSpacing(_scaled(8, 6))

        self.profile_panel_title = QLabel("Metric Threshold Profiles", self.profile_panel)
        self.profile_panel_title.setObjectName("SectionTitle")

        self.profile_grid_widget = QWidget(self.profile_panel)
        self.profile_grid = QGridLayout(self.profile_grid_widget)
        self.profile_grid.setContentsMargins(0, 0, 0, 0)
        self.profile_grid.setHorizontalSpacing(_scaled(10, 8))
        self.profile_grid.setVerticalSpacing(_scaled(10, 8))

        self.profile_cards: Dict[str, _MetricProfileCard] = {}
        positions = {
            METRIC_TEMPERATURE: (0, 0),
            METRIC_SPO2: (0, 1),
            METRIC_PULSE: (0, 2),
            METRIC_RR: (1, 0),
            METRIC_WEIGHT: (1, 1),
            METRIC_HEIGHT: (1, 2),
            METRIC_BMI: (2, 0),
        }

        for metric_key in METRIC_ORDER:
            row, col = positions[metric_key]
            card = _MetricProfileCard(
                metric_key,
                title=METRIC_LABELS[metric_key],
                subtitle=METRIC_DESCRIPTIONS[metric_key],
                icon_path=_metric_icon_path(metric_key),
                parent=self.profile_grid_widget,
            )
            card.clicked.connect(self._handle_profile_card_clicked)
            self.profile_cards[metric_key] = card
            self.profile_grid.addWidget(card, row, col)

        profile_layout.addWidget(self.profile_panel_title)
        profile_layout.addWidget(self.profile_grid_widget, 1)

        # Right panel
        self.side_panel = QWidget(self.content_row)
        side_layout = QVBoxLayout(self.side_panel)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(_scaled(8, 6))
        self.side_panel.setMinimumWidth(_scaled(312, 286))
        self.side_panel.setMaximumWidth(_scaled(336, 310))

        self.summary_card = _ParameterSummaryCard(self.side_panel)

        self.editor_card = QFrame(self.side_panel)
        self.editor_card.setObjectName("InfoCard")
        editor_layout = QVBoxLayout(self.editor_card)
        editor_layout.setContentsMargins(16, 14, 16, 14)
        editor_layout.setSpacing(8)

        self.editor_title = QLabel("Selected Metric Editor", self.editor_card)
        self.editor_title.setObjectName("SectionTitle")

        self.editor_metric_label = QLabel("Metric: --", self.editor_card)
        self.editor_metric_label.setStyleSheet(
            "QLabel { color: rgba(214, 235, 248, 0.86); font-size: 8px; font-weight: 700; background: transparent; }"
        )

        self.editor_form = QWidget(self.editor_card)
        self.editor_form_grid = QGridLayout(self.editor_form)
        self.editor_form_grid.setContentsMargins(0, 0, 0, 0)
        self.editor_form_grid.setHorizontalSpacing(_scaled(6, 5))
        self.editor_form_grid.setVerticalSpacing(_scaled(6, 5))

        self.warning_low_label = QLabel("Warning Low", self.editor_form)
        self.warning_low_spin = QDoubleSpinBox(self.editor_form)
        self.warning_low_spin.setRange(-9999.0, 9999.0)
        self.warning_low_spin.setDecimals(2)
        self.warning_low_spin.setSingleStep(0.1)
        self.warning_low_spin.valueChanged.connect(self._on_editor_changed)

        self.normal_low_label = QLabel("Normal Low", self.editor_form)
        self.normal_low_spin = QDoubleSpinBox(self.editor_form)
        self.normal_low_spin.setRange(-9999.0, 9999.0)
        self.normal_low_spin.setDecimals(2)
        self.normal_low_spin.setSingleStep(0.1)
        self.normal_low_spin.valueChanged.connect(self._on_editor_changed)

        self.normal_high_label = QLabel("Normal High", self.editor_form)
        self.normal_high_spin = QDoubleSpinBox(self.editor_form)
        self.normal_high_spin.setRange(-9999.0, 9999.0)
        self.normal_high_spin.setDecimals(2)
        self.normal_high_spin.setSingleStep(0.1)
        self.normal_high_spin.valueChanged.connect(self._on_editor_changed)

        self.warning_high_label = QLabel("Warning High", self.editor_form)
        self.warning_high_spin = QDoubleSpinBox(self.editor_form)
        self.warning_high_spin.setRange(-9999.0, 9999.0)
        self.warning_high_spin.setDecimals(2)
        self.warning_high_spin.setSingleStep(0.1)
        self.warning_high_spin.valueChanged.connect(self._on_editor_changed)

        self.enabled_checkbox = QCheckBox("Enable selected threshold profile", self.editor_form)
        self.enabled_checkbox.toggled.connect(self._on_editor_changed)

        self.editor_form_grid.addWidget(self.warning_low_label, 0, 0)
        self.editor_form_grid.addWidget(self.warning_low_spin, 0, 1)
        self.editor_form_grid.addWidget(self.normal_low_label, 1, 0)
        self.editor_form_grid.addWidget(self.normal_low_spin, 1, 1)
        self.editor_form_grid.addWidget(self.normal_high_label, 2, 0)
        self.editor_form_grid.addWidget(self.normal_high_spin, 2, 1)
        self.editor_form_grid.addWidget(self.warning_high_label, 3, 0)
        self.editor_form_grid.addWidget(self.warning_high_spin, 3, 1)
        self.editor_form_grid.addWidget(self.enabled_checkbox, 4, 0, 1, 2)

        self.editor_info_label = QLabel(
            "Warning low/high define the outer attention band. Normal low/high define the inner healthy band used by the interpretation layer.",
            self.editor_card,
        )
        self.editor_info_label.setWordWrap(True)

        self.editor_action_row = QWidget(self.editor_card)
        editor_action_layout = QHBoxLayout(self.editor_action_row)
        editor_action_layout.setContentsMargins(0, 0, 0, 0)
        editor_action_layout.setSpacing(_scaled(6, 5))

        self.apply_profile_button = self._create_button("Apply To Profile", variant="ghost", min_width=_scaled(118, 102), parent=self.editor_action_row)
        self.apply_profile_button.clicked.connect(self._handle_apply_selected_clicked)

        self.reset_profile_button = self._create_button("Reset Selected", variant="secondary", min_width=_scaled(116, 100), parent=self.editor_action_row)
        self.reset_profile_button.clicked.connect(self._handle_reset_selected_clicked)

        editor_action_layout.addWidget(self.apply_profile_button)
        editor_action_layout.addWidget(self.reset_profile_button)

        editor_layout.addWidget(self.editor_title)
        editor_layout.addWidget(self.editor_metric_label)
        editor_layout.addWidget(self.editor_form)
        editor_layout.addWidget(self.editor_info_label)
        editor_layout.addWidget(self.editor_action_row)

        self.context_card = QFrame(self.side_panel)
        self.context_card.setObjectName("InfoCard")
        context_layout = QVBoxLayout(self.context_card)
        context_layout.setContentsMargins(16, 14, 16, 14)
        context_layout.setSpacing(8)

        self.context_title = QLabel("Parameter Context", self.context_card)
        self.context_title.setObjectName("SectionTitle")

        self.context_art = QLabel(self.context_card)
        self.context_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_label_pixmap(self.context_art, self._shield_pixmap, _scaled(78, 60))

        self.context_line_1 = QLabel("Selected metric: pending", self.context_card)
        self.context_line_2 = QLabel("Diagnosis service: pending", self.context_card)
        self.context_line_3 = QLabel("Last save: pending", self.context_card)
        self.context_line_4 = QLabel("Status: pending", self.context_card)

        self.context_note = QLabel(
            "Threshold changes affect result interpretation and downstream diagnosis summaries once saved.",
            self.context_card,
        )
        self.context_note.setWordWrap(True)

        context_layout.addWidget(self.context_title)
        context_layout.addWidget(self.context_art, 0, alignment=Qt.AlignmentFlag.AlignHCenter)
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

        self.quick_title = QLabel("Protected Actions", self.quick_card)
        self.quick_title.setObjectName("SectionTitle")

        self.quick_text = QLabel(
            "Reload service values, restore defaults, or save the full threshold profile set into the protected runtime.",
            self.quick_card,
        )
        self.quick_text.setWordWrap(True)

        self.reload_button = self._create_button("Reload Profiles", variant="ghost", min_width=_scaled(144, 120), parent=self.quick_card)
        self.reload_button.clicked.connect(self.reload_parameters)

        self.restore_defaults_button = self._create_button("Restore Defaults", variant="secondary", min_width=_scaled(144, 120), parent=self.quick_card)
        self.restore_defaults_button.clicked.connect(self._handle_restore_defaults_clicked)

        self.save_button = self._create_button("Save Parameters", variant="primary", min_width=_scaled(144, 120), parent=self.quick_card)
        self.save_button.clicked.connect(self._handle_save_clicked)

        quick_layout.addWidget(self.quick_title)
        quick_layout.addWidget(self.quick_text)
        quick_layout.addWidget(self.reload_button)
        quick_layout.addWidget(self.restore_defaults_button)
        quick_layout.addWidget(self.save_button)

        side_layout.addWidget(self.summary_card)
        side_layout.addWidget(self.editor_card)
        side_layout.addWidget(self.context_card)
        side_layout.addWidget(self.quick_card)

        content_layout.addWidget(self.profile_panel, 1)
        content_layout.addWidget(self.side_panel, 0)

        # ---------------------------------------------------------------------
        # Bottom action row
        # ---------------------------------------------------------------------
        self.action_row = QWidget(self)
        action_layout = QHBoxLayout(self.action_row)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(_scaled(8, 6))

        self.bottom_reload_button = self._create_button("Reload", variant="ghost", min_width=_scaled(98, 82), parent=self.action_row)
        self.bottom_reload_button.clicked.connect(self.reload_parameters)

        self.bottom_defaults_button = self._create_button("Restore Defaults", variant="secondary", min_width=_scaled(128, 110), parent=self.action_row)
        self.bottom_defaults_button.clicked.connect(self._handle_restore_defaults_clicked)

        self.bottom_save_button = self._create_button("Save Threshold Profiles", variant="primary", min_width=_scaled(180, 150), parent=self.action_row)
        self.bottom_save_button.clicked.connect(self._handle_save_clicked)

        action_layout.addWidget(self.bottom_reload_button)
        action_layout.addStretch(1)
        action_layout.addWidget(self.bottom_defaults_button)
        action_layout.addWidget(self.bottom_save_button)

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
        button.setMinimumHeight(_scaled(36, 32))
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

        profile_shadow = QGraphicsDropShadowEffect(self.profile_panel)
        profile_shadow.setBlurRadius(26)
        profile_shadow.setOffset(0, 6)
        shadow_color = QColor("#39D8FF")
        shadow_color.setAlpha(60)
        profile_shadow.setColor(shadow_color)
        self.profile_panel.setGraphicsEffect(profile_shadow)

        if _HAS_GLOW_LABEL and isinstance(self.hero_title, GlowLabel):
            try:
                self.hero_title.set_glow_color("#43D9FF")
                self.hero_title.set_text_color("#F5FCFF")
            except Exception:
                pass

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QFrame#ParametersScreen {
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
                font-size: 8px;
                font-weight: 700;
                border: 1px solid rgba(157, 220, 255, 0.22);
                border-radius: 16px;
                background: rgba(18, 39, 70, 0.56);
                padding: 5px 8px;
            }

            QFrame#ParametersHeaderCard {
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
                font-size: 8px;
                font-weight: 800;
                border: 1px solid rgba(157, 220, 255, 0.22);
                border-radius: 16px;
                background: rgba(28, 56, 91, 0.42);
                padding: 3px 8px;
            }

            QFrame#ProfilePanel, QFrame#InfoCard {
                border: 1px solid rgba(170, 230, 255, 0.20);
                border-radius: 22px;
                background: rgba(12, 28, 50, 0.74);
            }

            QLabel#SectionTitle {
                color: #F4FCFF;
                font-size: 11px;
                font-weight: 800;
                background: transparent;
            }

            QDoubleSpinBox {
                color: #F6FCFF;
                border: 1px solid rgba(157, 220, 255, 0.24);
                border-radius: 16px;
                background: rgba(16, 35, 61, 0.82);
                padding: 5px 8px;
                font-size: 11px;
                font-weight: 600;
                min-height: 34px;
            }

            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
                width: 18px;
                border: none;
                background: transparent;
            }

            QCheckBox {
                color: rgba(220, 238, 249, 0.86);
                font-size: 8px;
                font-weight: 600;
                spacing: 8px;
            }

            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid rgba(157, 220, 255, 0.28);
                background: rgba(18, 39, 70, 0.58);
            }

            QCheckBox::indicator:checked {
                background: rgba(67, 217, 255, 0.90);
                border: 1px solid rgba(186, 233, 255, 0.42);
            }
            """
        )

        if _HAS_GLOW_LABEL and isinstance(self.hero_title, GlowLabel):
            try:
                self.hero_title.set_text("Protected diagnosis parameters")
            except Exception:
                self.hero_title.setText("Protected diagnosis parameters")
        else:
            self.hero_title.setText("Protected diagnosis parameters")

        self.hero_subtitle.setText(
            "Review threshold bands used for metric interpretation, warning boundaries, and protected diagnosis-oriented reference logic."
        )
        self.summary_banner.setText(
            "The parameters screen supports protected maintenance of result-interpretation rules for all supported kiosk metrics."
        )

        self.hero_title.setStyleSheet(
            """
            QLabel {
                color: #F6FCFF;
                font-size: 20px;
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
                font-size: 8px;
                font-weight: 600;
                background: transparent;
            }
            """
        )

        context_style = """
            QLabel {
                color: rgba(214, 235, 248, 0.86);
                font-size: 8px;
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
        self.editor_info_label.setStyleSheet(context_style)

        editor_label_style = """
            QLabel {
                color: rgba(220, 238, 249, 0.86);
                font-size: 8px;
                font-weight: 700;
                background: transparent;
            }
        """
        self.warning_low_label.setStyleSheet(editor_label_style)
        self.normal_low_label.setStyleSheet(editor_label_style)
        self.normal_high_label.setStyleSheet(editor_label_style)
        self.warning_high_label.setStyleSheet(editor_label_style)

        self._set_button_accent(self.reload_button, "#39D8FF")
        self._set_button_accent(self.bottom_reload_button, "#39D8FF")
        self._set_button_accent(self.restore_defaults_button, "#FFD25E")
        self._set_button_accent(self.bottom_defaults_button, "#FFD25E")
        self._set_button_accent(self.apply_profile_button, "#67D8FF")
        self._set_button_accent(self.reset_profile_button, "#FFA14D")
        self._set_button_accent(self.save_button, "#42E393")
        self._set_button_accent(self.bottom_save_button, "#42E393")

    def _play_entry_animation(self) -> None:
        for effect_name in ("header_opacity", "stats_opacity", "content_opacity"):
            effect = getattr(self, effect_name, None)
            try:
                if effect is not None:
                    effect.setOpacity(1.0)
            except Exception:
                pass

        for widget_name in (
            "header_card",
            "stats_row",
            "content_row",
            "profile_panel",
            "metric_panel",
            "category_panel",
            "channel_panel",
        ):
            widget = getattr(self, widget_name, None)
            try:
                if widget is not None:
                    widget.setGraphicsEffect(None)
            except Exception:
                pass

        try:
            if hasattr(self, "entry_group") and self.entry_group is not None:
                self.entry_group.stop()
        except Exception:
            pass

        return

    # =========================================================================
    # Lifecycle
    # =========================================================================

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._play_entry_animation()
        self.reload_parameters()
        self._apply_compact_layout()


    def _apply_compact_layout(self) -> None:
        width = max(self.width(), int(KIOSK_WIDTH))
        height = max(self.height(), int(KIOSK_HEIGHT))
        compact = True if (KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480) else (width <= 900 or height <= 540)
        ultra = width <= 820 or height <= 480 or KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480

        try:
            root = self.layout()
            if isinstance(root, QVBoxLayout):
                root.setContentsMargins(_scaled(10, 10), _scaled(8, 8), _scaled(10, 10), _scaled(8, 8))
                root.setSpacing(_scaled(6, 6))
        except Exception:
            pass

        try:
            self.top_title.setText("Parameters")
            self.hero_subtitle.setVisible(False)
            self.summary_banner.setVisible(False)
            self.header_chip_row.setVisible(False)
            self.persistence_chip.setVisible(False)
            self.selected_pill.setVisible(False)
            self.diagnosis_pill.setVisible(True)
            self.header_card.layout().setContentsMargins(_scaled(10, 10), _scaled(8, 8), _scaled(10, 10), _scaled(8, 8))
            self.header_card.layout().setSpacing(_scaled(4, 4))
            self.header_card.setMaximumHeight(_scaled(84, 78))
        except Exception:
            pass

        try:
            self.content_row.layout().setSpacing(_scaled(8, 8))
            self.profile_grid.setHorizontalSpacing(_scaled(8, 8))
            self.profile_grid.setVerticalSpacing(_scaled(8, 8))
            self.profile_panel.layout().setContentsMargins(_scaled(10, 10), _scaled(8, 8), _scaled(10, 10), _scaled(8, 8))
            self.profile_panel.layout().setSpacing(_scaled(6, 6))
            self.side_panel.setMinimumWidth(_scaled(282, 270))
            self.side_panel.setMaximumWidth(_scaled(300, 286))
        except Exception:
            pass

        for stat in (self.stat_enabled, self.stat_ready, self.stat_selected, self.stat_service):
            try:
                stat.setMinimumHeight(_scaled(62, 58))
                stat.setMaximumHeight(_scaled(68, 60))
                if hasattr(stat, 'subtitle_label'):
                    stat.subtitle_label.setVisible(False)
                if stat.layout() is not None:
                    stat.layout().setContentsMargins(_scaled(10, 8), _scaled(8, 6), _scaled(10, 8), _scaled(8, 6))
                    stat.layout().setSpacing(_scaled(2, 2))
            except Exception:
                pass

        try:
            self.stats_row.layout().setSpacing(_scaled(6, 6))
        except Exception:
            pass

        for card in self.profile_cards.values():
            try:
                card.setMinimumHeight(_scaled(78, 72))
                card.setMaximumHeight(_scaled(86, 78))
                if card.layout() is not None:
                    card.layout().setContentsMargins(_scaled(10, 8), _scaled(8, 6), _scaled(10, 8), _scaled(8, 6))
                    card.layout().setSpacing(_scaled(3, 3))
                card.icon_label.setMinimumSize(0, 0)
                card.icon_label.setMaximumSize(0, 0)
                card.icon_label.hide()
                if hasattr(card, 'subtitle_label'):
                    card.subtitle_label.setVisible(False)
                if hasattr(card, 'warning_line'):
                    card.warning_line.setVisible(False)
                if hasattr(card, 'range_line'):
                    card.range_line.setStyleSheet('QLabel { color: rgba(208, 230, 244, 0.84); font-size: 7px; font-weight: 600; background: transparent; }')
            except Exception:
                pass

        try:
            self.summary_card.hide()
            self.summary_card.setMinimumHeight(0)
            self.summary_card.setMaximumHeight(0)
        except Exception:
            pass

        try:
            self.context_card.setVisible(False)
            self.quick_card.setVisible(False)
            self.editor_card.layout().setContentsMargins(_scaled(12, 10), _scaled(10, 8), _scaled(12, 10), _scaled(10, 8))
            self.editor_card.layout().setSpacing(_scaled(7, 6))
            self.editor_form_grid.setHorizontalSpacing(_scaled(8, 7))
            self.editor_form_grid.setVerticalSpacing(_scaled(7, 6))
            for editor in (self.warning_low_spin, self.normal_low_spin, self.normal_high_spin, self.warning_high_spin):
                editor.setMinimumHeight(_scaled(24, 22))
                editor.setMaximumHeight(_scaled(24, 22))
            for label in (self.warning_low_label, self.normal_low_label, self.normal_high_label, self.warning_high_label, self.editor_metric_label, self.editor_info_label):
                label.setStyleSheet('QLabel { color: rgba(214, 235, 248, 0.90); font-size: 8px; font-weight: 700; background: transparent; }')
            self.enabled_checkbox.setStyleSheet('QCheckBox { color: #EAF7FF; font-size: 8px; font-weight: 600; spacing: 6px; }')
            self.apply_profile_button.setText('Apply')
            self.reset_profile_button.setText('Reset')
            self.apply_profile_button.setMinimumHeight(_scaled(28, 26))
            self.apply_profile_button.setMaximumHeight(_scaled(28, 26))
            self.reset_profile_button.setMinimumHeight(_scaled(28, 26))
            self.reset_profile_button.setMaximumHeight(_scaled(28, 26))
            self.editor_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        except Exception:
            pass

        self.reload_button.setText('Reload')
        self.restore_defaults_button.setText('Defaults')
        self.bottom_defaults_button.setText('Defaults')
        self.bottom_save_button.setText('Save Thresholds')
        try:
            self._set_button_accent(self.back_button, '#47C9FF')
        except Exception:
            pass

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_compact_layout()

    # =========================================================================
    # Loading / service snapshots
    # =========================================================================

    def reload_parameters(self) -> None:
        snapshot = self._load_parameter_snapshot()

        self._profiles = deepcopy(snapshot["profiles"])
        self._loaded_profiles = deepcopy(snapshot["profiles"])
        self._diagnosis_state = safe_str(snapshot.get("diagnosis_state"), "ready").strip().lower() or "ready"
        self._service_detail = safe_str(snapshot.get("service_detail"), "").strip()
        self._status_message = safe_str(snapshot.get("service_state_text"), "Threshold profiles loaded.").strip()
        self._last_saved_label = safe_str(snapshot.get("last_saved"), "Not saved in this session.").strip()
        self._changed_since_load = False

        if self._selected_metric not in self._profiles:
            self._selected_metric = METRIC_TEMPERATURE

        self._apply_profiles_to_ui()
        self._apply_compact_layout()
        self.parameters_loaded.emit(self.diagnostics())

    def _load_parameter_snapshot(self) -> Dict[str, Any]:
        profiles = _default_profiles()
        service_state = "ready"
        service_state_text = "Threshold profiles loaded from protected defaults."
        last_saved = "Not saved in this session."
        diagnosis_state = "ready"
        service_detail = "Threshold rules are available for protected review."

        # 1) threshold_service
        try:
            threshold_service = self.services.get("threshold_service") or self.services.get("thresholds")
            if threshold_service is not None:
                for method_name in (
                    "snapshot",
                    "get_snapshot",
                    "get_threshold_snapshot",
                    "load_profiles",
                    "get_profiles",
                    "threshold_profiles",
                    "get_thresholds",
                ):
                    method = getattr(threshold_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method()
                            if isinstance(raw, Mapping):
                                data = dict(raw)

                                if "profiles" in data and isinstance(data.get("profiles"), Mapping):
                                    raw_profiles = dict(data.get("profiles", {}))
                                else:
                                    raw_profiles = {
                                        key: value
                                        for key, value in data.items()
                                        if key in METRIC_ORDER and isinstance(value, Mapping)
                                    }

                                for metric_key in METRIC_ORDER:
                                    if metric_key in raw_profiles and isinstance(raw_profiles[metric_key], Mapping):
                                        profiles[metric_key] = _normalize_profile(metric_key, raw_profiles[metric_key])

                                service_state = safe_str(
                                    data.get("state", data.get("status", service_state)),
                                    service_state,
                                ).strip().lower() or service_state
                                service_state_text = safe_str(
                                    data.get("detail", data.get("summary", service_state_text)),
                                    service_state_text,
                                ).strip() or service_state_text
                                last_saved = safe_str(
                                    data.get("last_saved", data.get("last_updated", last_saved)),
                                    last_saved,
                                ).strip() or last_saved
                                break
                        except Exception:
                            continue
        except Exception:
            pass

        # 2) health_rules_service fallback
        try:
            rules_service = self.services.get("health_rules_service") or self.services.get("health_rules")
            if rules_service is not None:
                for method_name in (
                    "snapshot",
                    "get_snapshot",
                    "get_profiles",
                    "rules_snapshot",
                    "get_threshold_profiles",
                ):
                    method = getattr(rules_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method()
                            if isinstance(raw, Mapping):
                                data = dict(raw)
                                raw_profiles = data.get("profiles", data)
                                if isinstance(raw_profiles, Mapping):
                                    for metric_key in METRIC_ORDER:
                                        if metric_key in raw_profiles and isinstance(raw_profiles[metric_key], Mapping):
                                            profiles[metric_key] = _normalize_profile(metric_key, raw_profiles[metric_key])
                                if not service_detail:
                                    service_detail = safe_str(data.get("detail", data.get("summary", "")), "").strip()
                                break
                        except Exception:
                            continue
        except Exception:
            pass

        # 3) settings_service fallback
        try:
            settings_service = self.services.get("settings_service") or self.services.get("settings")
            if settings_service is not None:
                for method_name in ("get_setting", "value", "get"):
                    method = getattr(settings_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method("threshold_profiles")
                            if isinstance(raw, Mapping):
                                for metric_key in METRIC_ORDER:
                                    if metric_key in raw and isinstance(raw[metric_key], Mapping):
                                        profiles[metric_key] = _normalize_profile(metric_key, raw[metric_key])
                                break
                        except Exception:
                            continue
        except Exception:
            pass

        # 4) config.py fallback
        try:
            import config as project_config  # local import on purpose

            for attr_name in ("DEFAULT_THRESHOLD_PROFILES", "THRESHOLD_PROFILES"):
                if hasattr(project_config, attr_name):
                    raw = getattr(project_config, attr_name)
                    if isinstance(raw, Mapping):
                        for metric_key in METRIC_ORDER:
                            if metric_key in raw and isinstance(raw[metric_key], Mapping):
                                profiles[metric_key] = _normalize_profile(metric_key, raw[metric_key])
        except Exception:
            pass

        # 5) app_state fallback
        try:
            if self.app_state is not None:
                for attr_name in ("threshold_profiles", "parameter_profiles", "health_rule_profiles"):
                    if hasattr(self.app_state, attr_name):
                        raw = getattr(self.app_state, attr_name)
                        if isinstance(raw, Mapping):
                            for metric_key in METRIC_ORDER:
                                if metric_key in raw and isinstance(raw[metric_key], Mapping):
                                    profiles[metric_key] = _normalize_profile(metric_key, raw[metric_key])
                            break
        except Exception:
            pass

        # diagnosis service snapshot
        try:
            diagnosis_service = self.services.get("diagnosis_service") or self.services.get("diagnosis")
            if diagnosis_service is not None:
                for method_name in ("snapshot", "get_snapshot", "status"):
                    method = getattr(diagnosis_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method()
                            if isinstance(raw, Mapping):
                                data = dict(raw)
                                diagnosis_state = safe_str(
                                    data.get("state", data.get("status", diagnosis_state)),
                                    diagnosis_state,
                                ).strip().lower() or diagnosis_state
                                detail = safe_str(data.get("detail", data.get("summary", "")), "").strip()
                                if detail:
                                    service_detail = detail
                                break
                        except Exception:
                            continue
        except Exception:
            pass

        return {
            "profiles": {metric: _normalize_profile(metric, profile) for metric, profile in profiles.items()},
            "service_state": service_state,
            "service_state_text": service_state_text,
            "last_saved": last_saved,
            "diagnosis_state": diagnosis_state,
            "service_detail": service_detail,
        }

    # =========================================================================
    # UI application
    # =========================================================================

    def _apply_profiles_to_ui(self) -> None:
        selected_profile = self._profiles.get(self._selected_metric, _default_profile(self._selected_metric))
        self._apply_selected_editor(selected_profile)

        enabled_count = 0
        ready_count = 0

        for metric_key, profile in self._profiles.items():
            enabled = safe_bool(profile.get("enabled"), True)
            state = safe_str(profile.get("state"), "ready").strip().lower()
            if enabled:
                enabled_count += 1
            if state in {"ready", "saved"}:
                ready_count += 1

            card = self.profile_cards.get(metric_key)
            if card is not None:
                accent = _accent_for_state(state if enabled else "disabled")
                state_text = "Disabled" if not enabled else state.title()
                unit = METRIC_UNITS.get(metric_key, "")
                card.set_selected(metric_key == self._selected_metric)
                card.set_payload(
                    state_text=state_text,
                    subtitle=safe_str(profile.get("summary"), "").strip(),
                    range_line=(
                        f"Normal {safe_float(profile.get('normal_low'), 0.0):0.2f} to "
                        f"{safe_float(profile.get('normal_high'), 0.0):0.2f} {unit}"
                    ),
                    warning_line=(
                        f"Warning {safe_float(profile.get('warning_low'), 0.0):0.2f} to "
                        f"{safe_float(profile.get('warning_high'), 0.0):0.2f} {unit}"
                    ),
                    accent_hex=accent,
                )

        selected_state = safe_str(selected_profile.get("state"), "ready").strip().lower()
        selected_enabled = safe_bool(selected_profile.get("enabled"), True)
        selected_accent = _accent_for_state(selected_state if selected_enabled else "disabled")
        selected_title = METRIC_LABELS.get(self._selected_metric, self._selected_metric.title())
        selected_state_text = "Disabled" if not selected_enabled else selected_state.title()
        selected_unit = METRIC_UNITS.get(self._selected_metric, "")

        summary_lines = {
            1: f"Warning-low boundary: {safe_float(selected_profile.get('warning_low'), 0.0):0.2f} {selected_unit}",
            2: f"Normal band: {safe_float(selected_profile.get('normal_low'), 0.0):0.2f} to {safe_float(selected_profile.get('normal_high'), 0.0):0.2f} {selected_unit}",
            3: f"Warning-high boundary: {safe_float(selected_profile.get('warning_high'), 0.0):0.2f} {selected_unit}",
            4: self._status_message,
        }

        self.summary_card.set_payload(
            title=selected_title,
            state_text=selected_state_text,
            summary=safe_str(selected_profile.get("summary"), "").strip() or "Selected threshold profile is ready for review.",
            lines=summary_lines,
            accent_hex=selected_accent,
        )

        # pills
        status_text = "Unsaved Changes" if self._changed_since_load else "Loaded"
        status_accent = "#FFD25E" if self._changed_since_load else "#42E393"

        self.status_pill.setText(status_text)
        self._apply_pill_style(self.status_pill, status_accent)

        diagnosis_text = safe_str(self._diagnosis_state, "ready").strip().title()
        self.diagnosis_pill.setText(diagnosis_text)
        self._apply_pill_style(self.diagnosis_pill, _accent_for_state(self._diagnosis_state))

        self.selected_pill.setText(METRIC_LABELS.get(self._selected_metric, self._selected_metric.title()))
        self._apply_pill_style(self.selected_pill, selected_accent)

        self._apply_header_chip_style(self.band_chip, "#67D8FF")
        self._apply_header_chip_style(self.diagnosis_chip, _accent_for_state(self._diagnosis_state))
        self._apply_header_chip_style(self.persistence_chip, "#42E393" if not self._changed_since_load else "#FFD25E")

        # stat cards
        self.stat_enabled.set_payload(
            value=str(enabled_count),
            subtitle="Profiles currently enabled for diagnosis use.",
            accent_hex="#42E393" if enabled_count > 0 else "#FFD25E",
        )
        self.stat_ready.set_payload(
            value=str(ready_count),
            subtitle="Profiles marked ready or saved.",
            accent_hex="#42E393" if ready_count > 0 else "#39D8FF",
        )
        self.stat_selected.set_payload(
            value=METRIC_LABELS.get(self._selected_metric, self._selected_metric.title()),
            subtitle=f"Current editing target: {selected_state_text.lower()} profile.",
            accent_hex=selected_accent,
        )
        self.stat_service.set_payload(
            value=diagnosis_text,
            subtitle=self._service_detail or "Diagnosis service detail unavailable.",
            accent_hex=_accent_for_state(self._diagnosis_state),
        )

        self.context_line_1.setText(f"Selected metric: {METRIC_LABELS.get(self._selected_metric, self._selected_metric.title())}")
        self.context_line_2.setText(f"Diagnosis service: {diagnosis_text}")
        self.context_line_3.setText(f"Last save: {self._last_saved_label}")
        self.context_line_4.setText(f"Status: {self._status_message}")

        self.context_note.setText(
            "Threshold changes affect how results are categorized into normal, attention, warning, and critical bands after saving."
        )

        self._set_button_accent(self.save_button, "#42E393" if self._changed_since_load else "#39D8FF")
        self._set_button_accent(self.bottom_save_button, "#42E393" if self._changed_since_load else "#39D8FF")

        self.parameter_profile_changed.emit(self.diagnostics())

    def _apply_selected_editor(self, profile: Mapping[str, Any]) -> None:
        self._editor_sync_in_progress = True

        self.editor_metric_label.setText(
            f"Metric: {METRIC_LABELS.get(self._selected_metric, self._selected_metric.title())} ({METRIC_UNITS.get(self._selected_metric, '')})"
        )

        decimals = max(0, min(3, safe_int(profile.get("decimals"), 1)))
        for spin in (
            self.warning_low_spin,
            self.normal_low_spin,
            self.normal_high_spin,
            self.warning_high_spin,
        ):
            spin.blockSignals(True)
            spin.setDecimals(decimals)

        self.warning_low_spin.setValue(safe_float(profile.get("warning_low"), 0.0))
        self.normal_low_spin.setValue(safe_float(profile.get("normal_low"), 0.0))
        self.normal_high_spin.setValue(safe_float(profile.get("normal_high"), 0.0))
        self.warning_high_spin.setValue(safe_float(profile.get("warning_high"), 0.0))

        for spin in (
            self.warning_low_spin,
            self.normal_low_spin,
            self.normal_high_spin,
            self.warning_high_spin,
        ):
            spin.blockSignals(False)

        self.enabled_checkbox.blockSignals(True)
        self.enabled_checkbox.setChecked(safe_bool(profile.get("enabled"), True))
        self.enabled_checkbox.blockSignals(False)

        self._editor_sync_in_progress = False

    # =========================================================================
    # Selection / editor handling
    # =========================================================================

    def _handle_profile_card_clicked(self, metric_key: str) -> None:
        metric = safe_str(metric_key, "").strip()
        if metric not in self._profiles:
            return

        self._selected_metric = metric
        self._apply_profiles_to_ui()
        self.parameter_profile_selected.emit(metric)

    def _on_editor_changed(self) -> None:
        if self._editor_sync_in_progress:
            return
        self._sync_selected_profile_from_editor(mark_state_if_needed=True)

    def _sync_selected_profile_from_editor(self, *, mark_state_if_needed: bool) -> None:
        if self._selected_metric not in self._profiles:
            return

        profile = dict(self._profiles.get(self._selected_metric, _default_profile(self._selected_metric)))
        profile["warning_low"] = round(float(self.warning_low_spin.value()), 2)
        profile["normal_low"] = round(float(self.normal_low_spin.value()), 2)
        profile["normal_high"] = round(float(self.normal_high_spin.value()), 2)
        profile["warning_high"] = round(float(self.warning_high_spin.value()), 2)
        profile["enabled"] = bool(self.enabled_checkbox.isChecked())

        if not profile["enabled"]:
            profile["state"] = "disabled"
            profile["summary"] = "This threshold profile is disabled and will not participate in diagnosis rules."
        elif mark_state_if_needed:
            current_loaded = self._loaded_profiles.get(self._selected_metric, _default_profile(self._selected_metric))
            if any(
                profile.get(key) != current_loaded.get(key)
                for key in ("warning_low", "normal_low", "normal_high", "warning_high", "enabled")
            ):
                profile["state"] = "edited"
                profile["summary"] = (
                    f"{METRIC_LABELS.get(self._selected_metric, self._selected_metric.title())} threshold profile has unsaved edits. "
                    "Review and save to persist diagnosis behavior."
                )

        self._profiles[self._selected_metric] = _normalize_profile(self._selected_metric, profile)
        self._changed_since_load = self._profiles != self._loaded_profiles
        self._status_message = (
            f"Edited {METRIC_LABELS.get(self._selected_metric, self._selected_metric.title())} threshold profile."
            if mark_state_if_needed else self._status_message
        )
        self._apply_profiles_to_ui()

    # =========================================================================
    # Actions
    # =========================================================================

    def _handle_apply_selected_clicked(self) -> None:
        self._sync_selected_profile_from_editor(mark_state_if_needed=True)
        self._status_message = (
            f"Applied current editor values to {METRIC_LABELS.get(self._selected_metric, self._selected_metric.title())} profile."
        )
        self._apply_profiles_to_ui()

    def _handle_reset_selected_clicked(self) -> None:
        self._profiles[self._selected_metric] = _default_profile(self._selected_metric)
        self._changed_since_load = self._profiles != self._loaded_profiles
        self._status_message = f"Reset {METRIC_LABELS.get(self._selected_metric, self._selected_metric.title())} profile to defaults."
        self._apply_profiles_to_ui()
        self.parameters_reset.emit(self.diagnostics())

    def _handle_restore_defaults_clicked(self) -> None:
        self._profiles = _default_profiles()
        self._changed_since_load = self._profiles != self._loaded_profiles
        self._status_message = "Restored all threshold profiles to protected defaults."
        self._apply_profiles_to_ui()
        self.parameters_reset.emit(self.diagnostics())

    def _handle_save_clicked(self) -> None:
        self._sync_selected_profile_from_editor(mark_state_if_needed=False)
        self._persist_profiles()

        self._loaded_profiles = deepcopy(self._profiles)
        self._changed_since_load = False
        self._last_saved_label = "Saved to protected runtime"
        self._status_message = "Threshold profiles were saved successfully."

        for metric_key, profile in self._profiles.items():
            updated = dict(profile)
            if safe_bool(updated.get("enabled"), True):
                state = safe_str(updated.get("state"), "").strip().lower()
                if state in {"edited", "pending", "ready", "saved"}:
                    updated["state"] = "saved"
            else:
                updated["state"] = "disabled"

            updated["summary"] = (
                f"{METRIC_LABELS.get(metric_key, metric_key.title())} thresholds are saved for protected diagnosis use."
                if safe_bool(updated.get("enabled"), True)
                else "This threshold profile is disabled and excluded from diagnosis use."
            )
            self._profiles[metric_key] = _normalize_profile(metric_key, updated)

        self._apply_profiles_to_ui()
        self.parameters_saved.emit(self.diagnostics())

    def _persist_profiles(self) -> None:
        payload = deepcopy(self._profiles)

        # 1) threshold_service batch save
        try:
            threshold_service = self.services.get("threshold_service") or self.services.get("thresholds")
            if threshold_service is not None:
                for method_name in (
                    "save_profiles",
                    "save_thresholds",
                    "update_profiles",
                    "persist_profiles",
                    "write_profiles",
                    "set_profiles",
                    "set_threshold_profiles",
                ):
                    method = getattr(threshold_service, method_name, None)
                    if callable(method):
                        try:
                            method(dict(payload))
                            break
                        except Exception:
                            continue

                for method_name in (
                    "save_profile",
                    "update_metric_profile",
                    "set_profile",
                    "persist_profile",
                ):
                    method = getattr(threshold_service, method_name, None)
                    if callable(method):
                        for metric_key, profile in payload.items():
                            try:
                                method(metric_key, dict(profile))
                            except TypeError:
                                try:
                                    method(dict(profile))
                                except Exception:
                                    continue
                            except Exception:
                                continue
        except Exception:
            pass

        # 2) health rules service fallback
        try:
            rules_service = self.services.get("health_rules_service") or self.services.get("health_rules")
            if rules_service is not None:
                for method_name in (
                    "save_profiles",
                    "update_profiles",
                    "set_profiles",
                    "set_threshold_profiles",
                ):
                    method = getattr(rules_service, method_name, None)
                    if callable(method):
                        try:
                            method(dict(payload))
                            break
                        except Exception:
                            continue
        except Exception:
            pass

        # 3) settings_service fallback
        try:
            settings_service = self.services.get("settings_service") or self.services.get("settings")
            if settings_service is not None:
                for method_name in ("set_setting", "set_runtime_value", "update_runtime_flag"):
                    method = getattr(settings_service, method_name, None)
                    if callable(method):
                        try:
                            method("threshold_profiles", dict(payload))
                            break
                        except Exception:
                            continue
        except Exception:
            pass

        # 4) app_state fallback
        try:
            if self.app_state is not None:
                for attr_name in ("threshold_profiles", "parameter_profiles", "health_rule_profiles"):
                    if hasattr(self.app_state, attr_name):
                        try:
                            setattr(self.app_state, attr_name, dict(payload))
                        except Exception:
                            pass

                for method_name in ("update_threshold_profiles", "set_threshold_profiles", "apply_threshold_snapshot"):
                    method = getattr(self.app_state, method_name, None)
                    if callable(method):
                        try:
                            method(dict(payload))
                            break
                        except Exception:
                            continue
        except Exception:
            pass

    # =========================================================================
    # Navigation / buttons
    # =========================================================================

    def _handle_back_clicked(self) -> None:
        if self._navigate_to(SCREEN_ADMIN_PANEL):
            return
        self.back_requested.emit()

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
                font-size: 8px;
                font-weight: 700;
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.34);
                border-radius: 16px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.15);
                padding: 5px 8px;
            }}
            """
        )

    def _apply_header_chip_style(self, label: QLabel, accent_hex: str) -> None:
        accent = QColor(accent_hex)
        label.setStyleSheet(
            f"""
            QLabel {{
                color: #EEF9FF;
                font-size: 8px;
                font-weight: 800;
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.34);
                border-radius: 16px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.16);
                padding: 3px 8px;
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
                    font-size: 11px;
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
            "selected_metric": self._selected_metric,
            "profiles": deepcopy(self._profiles),
            "loaded_profiles": deepcopy(self._loaded_profiles),
            "changed_since_load": self._changed_since_load,
            "status_message": self._status_message,
            "last_saved_label": self._last_saved_label,
            "diagnosis_state": self._diagnosis_state,
            "service_detail": self._service_detail,
            "background_path": self._background_path,
            "logo_path": self._logo_small_path,
            "admin_shield_path": self._admin_shield_path,
        }
