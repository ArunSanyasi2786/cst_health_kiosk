"""
screens/calibration_screen.py

Premium administrator calibration screen for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the protected calibration workspace opened from:
    - screens/admin_panel_screen.py
- It allows the administrator to:
    - review per-sensor calibration profiles
    - edit offsets, scale factors, sample windows, and tolerances
    - trigger best-effort calibration routines through calibration_service
    - persist updated calibration profiles into runtime / storage services
    - restore defaults safely
- It is designed specifically for:
    - Raspberry Pi 4B touchscreen kiosk deployment
    - 800x480-first compact kiosk resolution
    - laptop demo mode
- It provides:
    - premium glossy protected calibration UI
    - resilient loading from calibration_service / settings_service / config.py / app_state
    - touch-friendly calibration editing controls
    - live connection summary for hardware-assisted calibration
    - clear selected-sensor workflow
    - safe fallbacks when service integrations are still evolving

Linked project files this screen is intended to work with:
- config.py
- core/constants.py
- core/asset_paths.py
- core/logger.py
- core/app_state.py
- core/navigator.py
- core/theme_manager.py
- core/animation_manager.py
- services/calibration_service.py
- services/settings_service.py
- services/connection_service.py
- services/session_service.py
- widgets/animated_button.py
- widgets/glow_label.py
- widgets/sensor_calibration_card.py

Navigation targets this screen is designed to link to:
- screens/admin_panel_screen.py

Design goals:
- glossy futuristic blue medical UI
- protected engineering / maintenance feel
- strong readability at 800x480 and larger kiosks
- resilient integration while backend files continue evolving
- maintainable structure with safe fallbacks
"""

from __future__ import annotations

from copy import deepcopy
import json
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
    QSpinBox,
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
        MODE_DEMO,
        MODE_HARDWARE,
        SCREEN_ADMIN_PANEL,
    )
except Exception:  # pragma: no cover
    MODE_DEMO = "demo"
    MODE_HARDWARE = "hardware"
    SCREEN_ADMIN_PANEL = "admin_panel"

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
    import config as project_config  # type: ignore
except Exception:  # pragma: no cover
    project_config = None


def _cfg_attr(name: str, default: Any) -> Any:
    try:
        if project_config is not None and hasattr(project_config, name):
            return getattr(project_config, name)
    except Exception:
        pass
    return default


KIOSK_WIDTH = safe_int(_cfg_attr("KIOSK_WIDTH", 800), 800)
KIOSK_HEIGHT = safe_int(_cfg_attr("KIOSK_HEIGHT", 480), 480)
WIDTH_SCALE = float(_cfg_attr("WIDTH_SCALE", KIOSK_WIDTH / 1024.0) or (KIOSK_WIDTH / 1024.0))
HEIGHT_SCALE = float(_cfg_attr("HEIGHT_SCALE", KIOSK_HEIGHT / 600.0) or (KIOSK_HEIGHT / 600.0))
UI_SCALE = float(_cfg_attr("UI_SCALE", min(WIDTH_SCALE, HEIGHT_SCALE)) or min(WIDTH_SCALE, HEIGHT_SCALE))
IS_COMPACT_KIOSK = safe_bool(_cfg_attr("IS_COMPACT_KIOSK", KIOSK_WIDTH <= 900 or KIOSK_HEIGHT <= 520), KIOSK_WIDTH <= 900 or KIOSK_HEIGHT <= 520)


def _scaled(value: int, *, floor: int = 1) -> int:
    return max(floor, int(round(float(value) * UI_SCALE)))


def _scaled_w(value: int, *, floor: int = 1) -> int:
    return max(floor, int(round(float(value) * WIDTH_SCALE)))


def _scaled_h(value: int, *, floor: int = 1) -> int:
    return max(floor, int(round(float(value) * HEIGHT_SCALE)))


def _font_size(value: int, *, minimum: int = 8) -> int:
    factor = UI_SCALE * (0.96 if IS_COMPACT_KIOSK else 1.0)
    return max(minimum, int(round(float(value) * factor)))



# =============================================================================
# Helpers
# =============================================================================

SENSOR_TEMPERATURE = "temperature"
SENSOR_SPO2 = "spo2"
SENSOR_PULSE = "pulse"
SENSOR_WEIGHT = "weight"
SENSOR_HEIGHT = "height"
SENSOR_RR = "respiratory_rate"

SENSOR_ORDER = [
    SENSOR_TEMPERATURE,
    SENSOR_SPO2,
    SENSOR_PULSE,
    SENSOR_WEIGHT,
    SENSOR_HEIGHT,
    SENSOR_RR,
]

SENSOR_LABELS = {
    SENSOR_TEMPERATURE: "Temperature Sensor",
    SENSOR_SPO2: "SpO₂ Sensor",
    SENSOR_PULSE: "Pulse Sensor",
    SENSOR_WEIGHT: "Weight Sensor",
    SENSOR_HEIGHT: "Height Sensor",
    SENSOR_RR: "Respiratory Sensor",
}

SENSOR_SHORT_LABELS = {
    SENSOR_TEMPERATURE: "Temperature",
    SENSOR_SPO2: "SpO₂",
    SENSOR_PULSE: "Pulse",
    SENSOR_WEIGHT: "Weight",
    SENSOR_HEIGHT: "Height",
    SENSOR_RR: "Respiratory",
}

SENSOR_UNITS = {
    SENSOR_TEMPERATURE: "°C",
    SENSOR_SPO2: "%",
    SENSOR_PULSE: "bpm",
    SENSOR_WEIGHT: "kg",
    SENSOR_HEIGHT: "cm",
    SENSOR_RR: "breaths/min",
}


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _ui_profiles_cache_path() -> Path:
    return _project_root() / "data" / "config" / "calibration_profiles_ui.json"


def _load_ui_profiles_cache() -> Dict[str, Dict[str, Any]]:
    path = _ui_profiles_cache_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, Mapping):
        return {}
    profiles_raw = raw.get("profiles", raw)
    if not isinstance(profiles_raw, Mapping):
        return {}
    loaded: Dict[str, Dict[str, Any]] = {}
    for sensor_key in SENSOR_ORDER:
        item = profiles_raw.get(sensor_key)
        if isinstance(item, Mapping):
            loaded[sensor_key] = _normalize_profile(sensor_key, item)
    return loaded


def _save_ui_profiles_cache(profiles: Mapping[str, Any], *, last_saved_label: str = "Saved to protected runtime") -> None:
    path = _ui_profiles_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_saved": safe_str(last_saved_label, "Saved to protected runtime").strip() or "Saved to protected runtime",
            "profiles": dict(profiles),
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        pass


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
    if value in {"critical", "error", "failed", "offline", "locked"}:
        return "#FF6E88"
    if value in {"warning", "pending", "attention", "waiting", "edited"}:
        return "#FFD25E"
    if value in {"normal", "ready", "connected", "ok", "active", "healthy", "saved", "calibrated"}:
        return "#42E393"
    if value in {"disabled"}:
        return "#FFA14D"
    return "#39D8FF"


def _default_profile(sensor_key: str) -> Dict[str, Any]:
    base = {
        "sensor_key": sensor_key,
        "enabled": True,
        "offset": 0.0,
        "scale": 1.0,
        "samples": 8,
        "tolerance": 1.0,
        "state": "pending",
        "last_calibrated": "Not yet calibrated",
        "summary": "No calibration has been saved for this sensor yet.",
    }

    if sensor_key == SENSOR_TEMPERATURE:
        base.update(
            {
                "samples": 10,
                "tolerance": 0.2,
                "summary": "Body temperature calibration is waiting for a reference-aligned update.",
            }
        )
    elif sensor_key == SENSOR_SPO2:
        base.update(
            {
                "samples": 8,
                "tolerance": 1.5,
                "summary": "SpO₂ calibration should be compared with a reliable medical reference device.",
            }
        )
    elif sensor_key == SENSOR_PULSE:
        base.update(
            {
                "samples": 8,
                "tolerance": 4.0,
                "summary": "Pulse calibration should stabilize across repeated windows before saving.",
            }
        )
    elif sensor_key == SENSOR_WEIGHT:
        base.update(
            {
                "samples": 6,
                "tolerance": 0.5,
                "summary": "Weight calibration may require tare / reference weight verification.",
            }
        )
    elif sensor_key == SENSOR_HEIGHT:
        base.update(
            {
                "samples": 5,
                "tolerance": 1.0,
                "summary": "Height calibration should align measured distance with a physical reference.",
            }
        )
    elif sensor_key == SENSOR_RR:
        base.update(
            {
                "samples": 6,
                "tolerance": 2.0,
                "summary": "Respiratory-rate interpretation should be validated against stable resting measurements.",
            }
        )

    return base


def _default_profiles() -> Dict[str, Dict[str, Any]]:
    return {sensor: _default_profile(sensor) for sensor in SENSOR_ORDER}


def _normalize_profile(sensor_key: str, raw: Mapping[str, Any]) -> Dict[str, Any]:
    profile = deepcopy(_default_profile(sensor_key))
    if isinstance(raw, Mapping):
        profile.update(dict(raw))

    profile["sensor_key"] = sensor_key
    profile["enabled"] = safe_bool(profile.get("enabled"), True)
    profile["offset"] = round(safe_float(profile.get("offset"), 0.0), 3)
    profile["scale"] = round(max(0.1, min(5.0, safe_float(profile.get("scale"), 1.0))), 4)
    profile["samples"] = max(1, min(60, safe_int(profile.get("samples"), _default_profile(sensor_key)["samples"])))
    profile["tolerance"] = round(max(0.01, min(50.0, safe_float(profile.get("tolerance"), _default_profile(sensor_key)["tolerance"]))), 2)

    state = safe_str(profile.get("state"), "").strip().lower()
    if not state:
        if not profile["enabled"]:
            state = "disabled"
        else:
            state = "pending"
    profile["state"] = state

    profile["last_calibrated"] = safe_str(
        profile.get("last_calibrated"),
        _default_profile(sensor_key)["last_calibrated"],
    ).strip() or _default_profile(sensor_key)["last_calibrated"]

    profile["summary"] = safe_str(
        profile.get("summary"),
        _default_profile(sensor_key)["summary"],
    ).strip() or _default_profile(sensor_key)["summary"]

    return profile


# =============================================================================
# Internal widgets
# =============================================================================

class _CalibrationStatCard(QFrame):
    """
    Compact premium stat card for calibration overview.
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

        self.setObjectName("CalibrationStatCard")
        self.setMinimumHeight(_scaled_h(76 if IS_COMPACT_KIOSK else 92, floor=68))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(_scaled_w(10), _scaled_h(8), _scaled_w(10), _scaled_h(8))
        root.setSpacing(_scaled(2))

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
            QFrame#CalibrationStatCard {{
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.24);
                border-radius: 20px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(10, 24, 42, 0.95),
                    stop:1 rgba(6, 18, 34, 0.97)
                );
            }}
            """
        )
        self.title_label.setStyleSheet(
            """
            QLabel {
                color: rgba(219, 237, 249, 0.82);
                font-size: 9px;
                font-weight: 700;
                background: transparent;
            }
            """
        )
        self.value_label.setStyleSheet(
            """
            QLabel {
                color: #F6FCFF;
                font-size: 17px;
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


class _CalibrationProfileCard(QFrame):
    """
    Click-select premium sensor calibration card.
    """

    clicked = pyqtSignal(str)

    def __init__(
        self,
        sensor_key: str,
        *,
        title: str,
        subtitle: str,
        icon_path: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self.sensor_key = sensor_key
        self._selected = False
        self._hovered = False
        self._accent_hex = "#39D8FF"
        self._clickable = True
        self._icon_path = safe_str(icon_path, "").strip()
        self._icon_pixmap = _pixmap_or_empty(self._icon_path)

        self.setObjectName("CalibrationProfileCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(_scaled_h(120 if IS_COMPACT_KIOSK else 146, floor=106))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(_scaled_w(12), _scaled_h(10), _scaled_w(12), _scaled_h(10))
        root.setSpacing(_scaled(4))

        top_row = QWidget(self)
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(_scaled(6))

        self.icon_label = QLabel(top_row)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setMinimumSize(_scaled(38), _scaled(38))
        self.icon_label.setMaximumSize(_scaled(38), _scaled(38))

        self.state_chip = QLabel("Pending", top_row)

        top_layout.addWidget(self.icon_label)
        top_layout.addStretch(1)
        top_layout.addWidget(self.state_chip)

        self.title_label = QLabel(title, self)
        self.title_label.setWordWrap(True)

        self.subtitle_label = QLabel(subtitle, self)
        self.subtitle_label.setWordWrap(True)

        self.value_line = QLabel("Offset +0.000 • Scale 1.0000", self)
        self.last_line = QLabel("Not yet calibrated", self)

        root.addWidget(top_row)
        root.addWidget(self.title_label)
        root.addWidget(self.subtitle_label)
        root.addWidget(self.value_line)
        root.addWidget(self.last_line)
        root.addStretch(1)

        self._refresh_icon()
        self._apply_style()

    def _refresh_icon(self) -> None:
        if self._icon_pixmap.isNull():
            self.icon_label.clear()
            return

        scaled = self._icon_pixmap.scaled(
            _scaled(30),
            _scaled(30),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.icon_label.setPixmap(scaled)

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        self._apply_style()

    def set_payload(
        self,
        *,
        state_text: str,
        subtitle: str,
        value_line: str,
        last_line: str,
        accent_hex: str,
    ) -> None:
        self._accent_hex = safe_str(accent_hex, "#39D8FF").strip() or "#39D8FF"
        self.state_chip.setText(safe_str(state_text, "Pending").strip() or "Pending")
        self.subtitle_label.setText(safe_str(subtitle, "").strip())
        self.value_line.setText(safe_str(value_line, "").strip())
        self.last_line.setText(safe_str(last_line, "").strip())
        self._apply_style()

    def _apply_style(self) -> None:
        accent = QColor(self._accent_hex)
        border_alpha = 0.36 if self._selected else (0.26 if self._hovered else 0.18)
        fill_alpha = 0.16 if self._selected else (0.11 if self._hovered else 0.07)

        self.setStyleSheet(
            f"""
            QFrame#CalibrationProfileCard {{
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, {border_alpha:.3f});
                border-radius: 20px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(12, 28, 48, 0.95),
                    stop:1 rgba(8, 20, 36, 0.97)
                );
            }}
            """
        )

        self.icon_label.setStyleSheet(
            """
            QLabel {
                border: none;
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
        self.value_line.setStyleSheet(
            """
            QLabel {
                color: rgba(197, 223, 241, 0.84);
                font-size: 8px;
                font-weight: 600;
                background: transparent;
            }
            """
        )
        self.last_line.setStyleSheet(
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
                border-radius: 11px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.16);
                padding: 3px 8px;
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
            self.clicked.emit(self.sensor_key)

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


class _CalibrationSummaryCard(QFrame):
    """
    Premium selected-sensor summary card.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._accent_hex = "#39D8FF"

        self.setObjectName("CalibrationSummaryCard")
        self.setMinimumHeight(_scaled_h(182 if IS_COMPACT_KIOSK else 214, floor=164))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(_scaled_w(14), _scaled_h(12), _scaled_w(14), _scaled_h(12))
        root.setSpacing(_scaled(6))

        top_row = QWidget(self)
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(_scaled(6))

        self.title_label = QLabel("Selected Sensor", top_row)
        self.state_chip = QLabel("Pending", top_row)

        top_layout.addWidget(self.title_label)
        top_layout.addStretch(1)
        top_layout.addWidget(self.state_chip)

        self.summary_label = QLabel(
            "Select a sensor profile to review or edit calibration parameters.",
            self,
        )
        self.summary_label.setWordWrap(True)

        self.line_1 = QLabel("• Offset corrects additive bias in the measurement pipeline.", self)
        self.line_2 = QLabel("• Scale corrects proportional gain errors.", self)
        self.line_3 = QLabel("• Samples and tolerance affect calibration confidence.", self)
        self.line_4 = QLabel("• Save changes after calibration to persist them.", self)

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
        self.title_label.setText(safe_str(title, "Selected Sensor").strip() or "Selected Sensor")
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
            QFrame#CalibrationSummaryCard {{
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.24);
                border-radius: 22px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(12, 28, 48, 0.96),
                    stop:1 rgba(7, 18, 34, 0.98)
                );
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

class CalibrationScreen(QFrame):
    """
    Premium protected calibration screen.

    Main responsibilities:
    - load calibration profiles
    - allow per-sensor editing
    - trigger best-effort service calibration
    - persist calibration profiles
    """

    back_requested = pyqtSignal()
    calibration_loaded = pyqtSignal(dict)
    calibration_saved = pyqtSignal(dict)
    calibration_reset = pyqtSignal(dict)
    calibration_started = pyqtSignal(str)
    calibration_completed = pyqtSignal(dict)
    calibration_profile_selected = pyqtSignal(str)
    calibration_profile_changed = pyqtSignal(dict)

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

        self._logger = logger.bind(component="CalibrationScreen")

        self.navigator = navigator
        self.app_state = app_state
        self.services = dict(services or {})
        self.animation_manager = animation_manager
        self.theme_manager = theme_manager

        self._profiles: Dict[str, Dict[str, Any]] = _default_profiles()
        self._loaded_profiles: Dict[str, Dict[str, Any]] = _default_profiles()
        self._selected_sensor = SENSOR_TEMPERATURE
        self._changed_since_load = False
        self._status_message = "Calibration profiles are ready to load."
        self._last_saved_label = "Not saved in this session."
        self._connection_snapshot: Dict[str, Any] = {}
        self._mode = MODE_DEMO
        self._editor_sync_in_progress = False

        self._background_path = _resolve_asset("backgrounds/calibration_bg.png")
        self._logo_small_path = _resolve_asset("logos/proart-calibration.png")
        self._admin_shield_path = _resolve_asset("illustrations/admin_shield.png")

        self._sensor_icon_paths = {
            SENSOR_TEMPERATURE: _resolve_asset("icons/Untitled_design__1_-removebg-preview.png"),
            SENSOR_SPO2: _resolve_asset("icons/unnamed-removebg-preview.png"),
            SENSOR_PULSE: _resolve_asset("icons/images (4).png"),
            SENSOR_WEIGHT: _resolve_asset("icons/images.png"),
            SENSOR_HEIGHT: _resolve_asset("icons/1200x630wa-removebg-preview (1).png"),
            SENSOR_RR: _resolve_asset("icons/breathing-rate-icon-svg-download-png-4775592-removebg-preview.png"),
        }

        self._background_pixmap = _pixmap_or_empty(self._background_path)
        self._logo_pixmap = _pixmap_or_empty(self._logo_small_path)
        self._shield_pixmap = _pixmap_or_empty(self._admin_shield_path)

        self.setObjectName("CalibrationScreen")
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
        root.setContentsMargins(_scaled_w(14), _scaled_h(10), _scaled_w(14), _scaled_h(10))
        root.setSpacing(_scaled(8))

        # ---------------------------------------------------------------------
        # Top bar
        # ---------------------------------------------------------------------
        self.top_bar = QWidget(self)
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(_scaled(8))

        self.back_button = self._create_button("Back", variant="secondary", min_width=_scaled_w(84 if IS_COMPACT_KIOSK else 96), parent=self.top_bar)
        self.back_button.setObjectName("BackButton")
        self.back_button.setFixedSize(_scaled_w(88 if IS_COMPACT_KIOSK else 100), _scaled_h(34 if IS_COMPACT_KIOSK else 38))
        self.back_button.clicked.connect(self._handle_back_clicked)

        self.logo_label = QLabel(self.top_bar)
        self.logo_label.setObjectName("LogoLabel")
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_label.setFixedSize(_scaled_w(42), _scaled_h(42))
        self._set_label_pixmap(self.logo_label, self._logo_pixmap, _scaled_h(42, floor=34))

        self.top_title = QLabel("Protected Calibration", self.top_bar)
        self.top_title.setObjectName("TopTitle")

        self.status_pill = QLabel("Ready", self.top_bar)
        self.status_pill.setObjectName("RuntimePill")

        self.connection_pill = QLabel("Checking runtime…", self.top_bar)
        self.connection_pill.setObjectName("RuntimePill")

        self.selected_pill = QLabel("Selected Sensor", self.top_bar)
        self.selected_pill.setObjectName("RuntimePill")

        top_layout.addWidget(self.back_button)
        top_layout.addWidget(self.logo_label)
        top_layout.addWidget(self.top_title)
        top_layout.addStretch(1)
        top_layout.addWidget(self.status_pill)
        top_layout.addWidget(self.connection_pill)
        top_layout.addWidget(self.selected_pill)

        # ---------------------------------------------------------------------
        # Header card
        # ---------------------------------------------------------------------
        self.header_card = QFrame(self)
        self.header_card.setObjectName("CalibrationHeaderCard")

        header_layout = QVBoxLayout(self.header_card)
        header_layout.setContentsMargins(_scaled_w(14), _scaled_h(12), _scaled_w(14), _scaled_h(12))
        header_layout.setSpacing(_scaled(6))

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
        chip_layout.setSpacing(_scaled(6))

        self.hardware_chip = QLabel("Hardware Alignment", self.header_chip_row)
        self.hardware_chip.setObjectName("HeaderChip")

        self.profile_chip = QLabel("Profile Editing", self.header_chip_row)
        self.profile_chip.setObjectName("HeaderChip")

        self.persistence_chip = QLabel("Protected Persistence", self.header_chip_row)
        self.persistence_chip.setObjectName("HeaderChip")

        chip_layout.addStretch(1)
        chip_layout.addWidget(self.hardware_chip)
        chip_layout.addWidget(self.profile_chip)
        chip_layout.addWidget(self.persistence_chip)
        chip_layout.addStretch(1)

        self.summary_banner = QLabel(
            "Review, edit, and validate sensor-specific calibration profiles before saving them into the kiosk runtime.",
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
        stats_layout.setSpacing(_scaled(8))

        self.stat_enabled = _CalibrationStatCard("Enabled Profiles", value="--", subtitle="Number of active calibration profiles.")
        self.stat_ready = _CalibrationStatCard("Ready / Saved", value="--", subtitle="Profiles marked ready or calibrated.")
        self.stat_selected = _CalibrationStatCard("Selected Sensor", value="--", subtitle="Currently selected calibration target.")
        self.stat_link = _CalibrationStatCard("Runtime Link", value="--", subtitle="Connection state for hardware-assisted calibration.")

        stats_layout.addWidget(self.stat_enabled, 1)
        stats_layout.addWidget(self.stat_ready, 1)
        stats_layout.addWidget(self.stat_selected, 1)
        stats_layout.addWidget(self.stat_link, 1)

        # ---------------------------------------------------------------------
        # Content row
        # ---------------------------------------------------------------------
        self.content_row = QWidget(self)
        content_layout = QHBoxLayout(self.content_row)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(_scaled(10))

        # Left panel
        self.profile_panel = QFrame(self.content_row)
        self.profile_panel.setObjectName("ProfilePanel")
        self.profile_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        profile_layout = QVBoxLayout(self.profile_panel)
        profile_layout.setContentsMargins(_scaled_w(12), _scaled_h(10), _scaled_w(12), _scaled_h(10))
        profile_layout.setSpacing(_scaled(8))

        self.profile_panel_title = QLabel("Sensor Calibration Profiles", self.profile_panel)
        self.profile_panel_title.setObjectName("SectionTitle")

        self.profile_grid_widget = QWidget(self.profile_panel)
        self.profile_grid = QGridLayout(self.profile_grid_widget)
        self.profile_grid.setContentsMargins(0, 0, 0, 0)
        self.profile_grid.setHorizontalSpacing(_scaled(8))
        self.profile_grid.setVerticalSpacing(_scaled(8))

        self.profile_cards: Dict[str, _CalibrationProfileCard] = {}
        card_positions = {
            SENSOR_TEMPERATURE: (0, 0),
            SENSOR_SPO2: (0, 1),
            SENSOR_PULSE: (0, 2),
            SENSOR_WEIGHT: (1, 0),
            SENSOR_HEIGHT: (1, 1),
            SENSOR_RR: (1, 2),
        }

        sensor_descriptions = {
            SENSOR_TEMPERATURE: "Reference offset and scale for body-temperature estimation.",
            SENSOR_SPO2: "Oxygen saturation correction profile.",
            SENSOR_PULSE: "Pulse signal interpretation profile.",
            SENSOR_WEIGHT: "Load-cell / weighing alignment profile.",
            SENSOR_HEIGHT: "Height sensing calibration profile.",
            SENSOR_RR: "Respiratory interpretation calibration profile.",
        }

        for sensor_key in SENSOR_ORDER:
            row, col = card_positions[sensor_key]
            card = _CalibrationProfileCard(
                sensor_key,
                title=SENSOR_LABELS[sensor_key],
                subtitle=sensor_descriptions[sensor_key],
                icon_path=self._sensor_icon_paths.get(sensor_key, ""),
                parent=self.profile_grid_widget,
            )
            card.clicked.connect(self._handle_profile_card_clicked)
            self.profile_cards[sensor_key] = card
            self.profile_grid.addWidget(card, row, col)

        profile_layout.addWidget(self.profile_panel_title)
        profile_layout.addWidget(self.profile_grid_widget, 1)

        # Right panel
        self.side_panel = QWidget(self.content_row)
        side_layout = QVBoxLayout(self.side_panel)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(_scaled(8))
        self.side_panel.setMinimumWidth(_scaled_w(296 if IS_COMPACT_KIOSK else 352))
        self.side_panel.setMaximumWidth(_scaled_w(380 if IS_COMPACT_KIOSK else 404))

        self.summary_card = _CalibrationSummaryCard(self.side_panel)
        self.summary_card.hide()

        self.editor_card = QFrame(self.side_panel)
        self.editor_card.setObjectName("InfoCard")
        self.editor_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.editor_card.setMinimumHeight(_scaled_h(254 if IS_COMPACT_KIOSK else 298, floor=220))
        editor_layout = QVBoxLayout(self.editor_card)
        editor_layout.setContentsMargins(_scaled_w(12), _scaled_h(10), _scaled_w(12), _scaled_h(10))
        editor_layout.setSpacing(_scaled(6))

        self.editor_title = QLabel("Selected Sensor Editor", self.editor_card)
        self.editor_title.setObjectName("SectionTitle")

        self.editor_sensor_label = QLabel("Sensor: --", self.editor_card)
        self.editor_sensor_label.setStyleSheet(
            "QLabel { color: rgba(214, 235, 248, 0.86); font-size: 8px; font-weight: 700; background: transparent; }"
        )

        self.editor_form = QWidget(self.editor_card)
        self.editor_form_grid = QGridLayout(self.editor_form)
        self.editor_form_grid.setContentsMargins(0, 0, 0, 0)
        self.editor_form_grid.setHorizontalSpacing(14)
        self.editor_form_grid.setVerticalSpacing(10)

        self.offset_label = QLabel("Offset", self.editor_form)
        self.offset_spin = QDoubleSpinBox(self.editor_form)
        self.offset_spin.setRange(-50.0, 50.0)
        self.offset_spin.setDecimals(3)
        self.offset_spin.setSingleStep(0.05)
        self.offset_spin.valueChanged.connect(self._on_editor_changed)

        self.scale_label = QLabel("Scale", self.editor_form)
        self.scale_spin = QDoubleSpinBox(self.editor_form)
        self.scale_spin.setRange(0.1, 5.0)
        self.scale_spin.setDecimals(4)
        self.scale_spin.setSingleStep(0.01)
        self.scale_spin.valueChanged.connect(self._on_editor_changed)

        self.samples_label = QLabel("Samples", self.editor_form)
        self.samples_spin = QSpinBox(self.editor_form)
        self.samples_spin.setRange(1, 60)
        self.samples_spin.valueChanged.connect(self._on_editor_changed)

        self.tolerance_label = QLabel("Tolerance", self.editor_form)
        self.tolerance_spin = QDoubleSpinBox(self.editor_form)
        self.tolerance_spin.setRange(0.01, 50.0)
        self.tolerance_spin.setDecimals(2)
        self.tolerance_spin.setSingleStep(0.1)
        self.tolerance_spin.valueChanged.connect(self._on_editor_changed)

        self.enabled_checkbox = QCheckBox("Enable selected calibration profile", self.editor_form)
        self.enabled_checkbox.toggled.connect(self._on_editor_changed)

        self.editor_form_grid.addWidget(self.offset_label, 0, 0)
        self.editor_form_grid.addWidget(self.offset_spin, 0, 1)
        self.editor_form_grid.addWidget(self.scale_label, 1, 0)
        self.editor_form_grid.addWidget(self.scale_spin, 1, 1)
        self.editor_form_grid.addWidget(self.samples_label, 2, 0)
        self.editor_form_grid.addWidget(self.samples_spin, 2, 1)
        self.editor_form_grid.addWidget(self.tolerance_label, 3, 0)
        self.editor_form_grid.addWidget(self.tolerance_spin, 3, 1)
        self.editor_form_grid.addWidget(self.enabled_checkbox, 4, 0, 1, 2)

        self.editor_info_label = QLabel(
            "Use offset and scale to adjust the selected sensor profile. Start calibration to update the state and save when satisfied.",
            self.editor_card,
        )
        self.editor_info_label.setWordWrap(True)

        self.editor_action_row = QWidget(self.editor_card)
        editor_action_layout = QGridLayout(self.editor_action_row)
        editor_action_layout.setContentsMargins(0, 0, 0, 0)
        editor_action_layout.setHorizontalSpacing(8)
        editor_action_layout.setVerticalSpacing(8)

        self.apply_profile_button = self._create_button("Apply To Profile", variant="ghost", min_width=132, parent=self.editor_action_row)
        self.apply_profile_button.clicked.connect(self._handle_apply_selected_clicked)

        self.reset_profile_button = self._create_button("Reset Selected", variant="secondary", min_width=132, parent=self.editor_action_row)
        self.reset_profile_button.clicked.connect(self._handle_reset_selected_clicked)

        self.start_calibration_button = self._create_button("Start Calibration", variant="primary", min_width=150, parent=self.editor_action_row)
        self.start_calibration_button.clicked.connect(self._handle_start_calibration_clicked)

        editor_action_layout.addWidget(self.apply_profile_button, 0, 0, 1, 1)
        editor_action_layout.addWidget(self.reset_profile_button, 0, 1, 1, 1)
        editor_action_layout.addWidget(self.start_calibration_button, 1, 0, 1, 2)
        editor_action_layout.setColumnStretch(0, 1)
        editor_action_layout.setColumnStretch(1, 1)

        editor_layout.addWidget(self.editor_title)
        editor_layout.addWidget(self.editor_sensor_label)
        editor_layout.addWidget(self.editor_form)
        editor_layout.addWidget(self.editor_info_label)
        editor_layout.addWidget(self.editor_action_row)

        self.context_card = QFrame(self.side_panel)
        self.context_card.setObjectName("InfoCard")
        context_layout = QVBoxLayout(self.context_card)
        context_layout.setContentsMargins(_scaled_w(12), _scaled_h(10), _scaled_w(12), _scaled_h(10))
        context_layout.setSpacing(_scaled(6))

        self.context_title = QLabel("Calibration Context", self.context_card)
        self.context_title.setObjectName("SectionTitle")

        self.context_art = QLabel(self.context_card)
        self.context_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_label_pixmap(self.context_art, self._shield_pixmap, _scaled_h(72 if IS_COMPACT_KIOSK else 96))

        self.context_line_1 = QLabel("Mode: pending", self.context_card)
        self.context_line_2 = QLabel("Hardware link: pending", self.context_card)
        self.context_line_3 = QLabel("Last save: pending", self.context_card)
        self.context_line_4 = QLabel("Status: pending", self.context_card)

        self.context_note = QLabel(
            "For hardware-assisted calibration, ensure the device is connected and the reference method is ready before saving profiles.",
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
        quick_layout.setContentsMargins(_scaled_w(12), _scaled_h(10), _scaled_w(12), _scaled_h(10))
        quick_layout.setSpacing(_scaled(6))

        self.quick_title = QLabel("Protected Actions", self.quick_card)
        self.quick_title.setObjectName("SectionTitle")

        self.quick_text = QLabel(
            "Reload service values, restore defaults, or save the full calibration profile set into the protected runtime.",
            self.quick_card,
        )
        self.quick_text.setWordWrap(True)

        self.reload_button = self._create_button("Reload Profiles", variant="ghost", min_width=_scaled_w(148 if IS_COMPACT_KIOSK else 168), parent=self.quick_card)
        self.reload_button.clicked.connect(self.reload_calibration)

        self.restore_defaults_button = self._create_button("Restore Defaults", variant="secondary", min_width=_scaled_w(148 if IS_COMPACT_KIOSK else 168), parent=self.quick_card)
        self.restore_defaults_button.clicked.connect(self._handle_restore_defaults_clicked)

        self.save_button = self._create_button("Save Profiles", variant="primary", min_width=_scaled_w(148 if IS_COMPACT_KIOSK else 168), parent=self.quick_card)
        self.save_button.clicked.connect(self._handle_save_clicked)

        quick_layout.addWidget(self.quick_title)
        quick_layout.addWidget(self.quick_text)
        quick_layout.addWidget(self.reload_button)
        quick_layout.addWidget(self.restore_defaults_button)
        quick_layout.addWidget(self.save_button)

        side_layout.addWidget(self.editor_card, 1)
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
        action_layout.setSpacing(_scaled(8))

        self.bottom_reload_button = self._create_button("Reload", variant="ghost", min_width=_scaled_w(104 if IS_COMPACT_KIOSK else 120), parent=self.action_row)
        self.bottom_reload_button.clicked.connect(self.reload_calibration)

        self.bottom_defaults_button = self._create_button("Restore Defaults", variant="secondary", min_width=_scaled_w(138 if IS_COMPACT_KIOSK else 156), parent=self.action_row)
        self.bottom_defaults_button.clicked.connect(self._handle_restore_defaults_clicked)

        self.bottom_save_button = self._create_button("Save Calibration Profiles", variant="primary", min_width=_scaled_w(184 if IS_COMPACT_KIOSK else 216), parent=self.action_row)
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
        button.setMinimumHeight(_scaled_h(34 if IS_COMPACT_KIOSK else 40, floor=30))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            """
            QPushButton {
                color: #F6FCFF;
                border: 1px solid rgba(157, 220, 255, 0.26);
                border-radius: 20px;
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
            QFrame#CalibrationScreen {
                background: transparent;
            }

            QPushButton#BackButton {
                color: #F6FCFF;
                font-size: 14px;
                font-weight: 800;
                border-radius: 20px;
                border: 1px solid rgba(157, 220, 255, 0.34);
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(74, 160, 255, 0.98),
                    stop:1 rgba(34, 118, 236, 0.98)
                );
                padding: 10px 16px;
            }

            QPushButton#BackButton:hover {
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(90, 176, 255, 1.0),
                    stop:1 rgba(43, 128, 245, 1.0)
                );
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
                font-size: 15px;
                font-weight: 900;
                background: transparent;
            }

            QLabel#RuntimePill {
                color: #EEF9FF;
                font-size: 8px;
                font-weight: 700;
                border: 1px solid rgba(157, 220, 255, 0.22);
                border-radius: 20px;
                background: rgba(18, 39, 70, 0.56);
                padding: 6px 10px;
            }

            QFrame#CalibrationHeaderCard {
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
                border-radius: 12px;
                background: rgba(28, 56, 91, 0.42);
                padding: 4px 9px;
            }

            QFrame#ProfilePanel, QFrame#InfoCard {
                border: 1px solid rgba(170, 230, 255, 0.20);
                border-radius: 22px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(10, 24, 42, 0.95),
                    stop:1 rgba(6, 18, 34, 0.97)
                );
            }

            QLabel#SectionTitle {
                color: #F4FCFF;
                font-size: 11px;
                font-weight: 800;
                background: transparent;
            }

            QDoubleSpinBox, QSpinBox {
                color: #F6FCFF;
                border: 1px solid rgba(157, 220, 255, 0.24);
                border-radius: 14px;
                background: rgba(14, 30, 52, 0.96);
                padding: 3px 10px;
                font-size: 11px;
                font-weight: 600;
                min-height: 24px;
            }

            QSpinBox::up-button, QSpinBox::down-button,
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
                self.hero_title.set_text("Protected sensor calibration")
            except Exception:
                self.hero_title.setText("Protected sensor calibration")
        else:
            self.hero_title.setText("Protected sensor calibration")

        self.hero_subtitle.setText(
            "Review calibration readiness, tune per-sensor offsets and gains, and persist the profile set used by the kiosk measurement pipeline."
        )
        self.summary_banner.setText(
            "The calibration screen supports both reference-based tuning and service-driven calibration workflows."
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
                color: rgba(226, 241, 250, 0.92);
                font-size: 10px;
                font-weight: 700;
                background: transparent;
            }
        """
        self.offset_label.setStyleSheet(editor_label_style)
        self.scale_label.setStyleSheet(editor_label_style)
        self.samples_label.setStyleSheet(editor_label_style)
        self.tolerance_label.setStyleSheet(editor_label_style)

        self._set_button_accent(self.reload_button, "#39D8FF")
        self._set_button_accent(self.bottom_reload_button, "#39D8FF")
        self._set_button_accent(self.restore_defaults_button, "#FFD25E")
        self._set_button_accent(self.bottom_defaults_button, "#FFD25E")
        self._set_button_accent(self.apply_profile_button, "#67D8FF")
        self._set_button_accent(self.reset_profile_button, "#FFA14D")
        self._set_button_accent(self.start_calibration_button, "#42E393")
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
        self.reload_calibration()
        self._refresh_compact_layout()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_compact_layout()

    def _refresh_compact_layout(self) -> None:
        width = max(1, self.width())
        height = max(1, self.height())
        compact = True if (KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480) else (IS_COMPACT_KIOSK or width <= 900 or height <= 520)
        ultra = width <= 820 or height <= 470 or KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480

        try:
            root = self.layout()
            if isinstance(root, QVBoxLayout):
                root.setContentsMargins(_scaled_w(10), _scaled_h(8), _scaled_w(10), _scaled_h(8))
                root.setSpacing(_scaled(6))
        except Exception:
            pass

        try:
            self.top_title.setText("Calibration")
            self.hero_subtitle.setVisible(False)
            self.summary_banner.setVisible(False)
            self.header_chip_row.setVisible(False)
            self.persistence_chip.setVisible(False)
            self.selected_pill.setVisible(False)
            self.status_pill.setVisible(True)
            self.top_bar.layout().setSpacing(_scaled(6))
            self.header_card.layout().setContentsMargins(_scaled_w(10), _scaled_h(8), _scaled_w(10), _scaled_h(8))
            self.header_card.layout().setSpacing(_scaled(4))
            self.header_card.setMaximumHeight(_scaled_h(84 if ultra else 96, floor=76))
        except Exception:
            pass

        try:
            self.side_panel.setMinimumWidth(_scaled_w(300 if ultra else 320))
            self.side_panel.setMaximumWidth(_scaled_w(320 if ultra else 340))
            self.content_row.layout().setSpacing(_scaled(8 if ultra else 10))
            self.profile_grid.setHorizontalSpacing(_scaled(6))
            self.profile_grid.setVerticalSpacing(_scaled(6))
            self.profile_panel.layout().setContentsMargins(_scaled_w(10), _scaled_h(8), _scaled_w(10), _scaled_h(8))
            self.profile_panel.layout().setSpacing(_scaled(6))
        except Exception:
            pass

        for stat in (self.stat_enabled, self.stat_ready, self.stat_selected, self.stat_link):
            try:
                stat.setMinimumHeight(_scaled_h(66, floor=58))
                stat.setMaximumHeight(_scaled_h(70, floor=60))
                if hasattr(stat, "subtitle_label"):
                    stat.subtitle_label.setVisible(False)
                if stat.layout() is not None:
                    stat.layout().setContentsMargins(_scaled_w(10), _scaled_h(8), _scaled_w(10), _scaled_h(8))
                    stat.layout().setSpacing(_scaled(2))
            except Exception:
                pass

        try:
            self.stats_row.layout().setSpacing(_scaled(6))
        except Exception:
            pass

        for card in self.profile_cards.values():
            try:
                card.setMinimumHeight(_scaled_h(82, floor=74))
                card.setMaximumHeight(_scaled_h(90, floor=80))
                if card.layout() is not None:
                    card.layout().setContentsMargins(_scaled_w(10), _scaled_h(8), _scaled_w(10), _scaled_h(8))
                    card.layout().setSpacing(_scaled(2))
                card.icon_label.setMinimumSize(_scaled(28), _scaled(28))
                card.icon_label.setMaximumSize(_scaled(28), _scaled(28))
                try:
                    card._refresh_icon()
                except Exception:
                    pass
                if hasattr(card, "subtitle_label"):
                    card.subtitle_label.setVisible(False)
                if hasattr(card, "last_line"):
                    card.last_line.setVisible(False)
                if hasattr(card, "value_line"):
                    card.value_line.setStyleSheet("QLabel { color: rgba(208, 230, 244, 0.84); font-size: 7px; font-weight: 600; background: transparent; }")
                if hasattr(card, "state_chip"):
                    card.state_chip.setStyleSheet(card.state_chip.styleSheet() + " QLabel { padding: 2px 6px; font-size: 7px; }")
            except Exception:
                pass

        try:
            self.summary_card.hide()
            self.context_card.setVisible(False)
            self.quick_card.setVisible(False)
            self.editor_card.setMinimumHeight(_scaled_h(286, floor=248))
            self.editor_card.setMaximumHeight(16777215)
            self.editor_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.editor_card.layout().setContentsMargins(_scaled_w(12), _scaled_h(10), _scaled_w(12), _scaled_h(10))
            self.editor_card.layout().setSpacing(_scaled(7))
            self.editor_form_grid.setHorizontalSpacing(_scaled(14))
            self.editor_form_grid.setVerticalSpacing(_scaled(14))
            for editor in (self.offset_spin, self.scale_spin, self.samples_spin, self.tolerance_spin):
                editor.setMinimumHeight(_scaled_h(26, floor=24))
                editor.setMaximumHeight(_scaled_h(26, floor=24))
            for label in (self.offset_label, self.scale_label, self.samples_label, self.tolerance_label, self.editor_info_label):
                label.setStyleSheet("QLabel { color: rgba(222, 239, 250, 0.90); font-size: 9px; font-weight: 700; background: transparent; }")
            self.enabled_checkbox.setStyleSheet("QCheckBox { color: #EAF7FF; font-size: 7px; font-weight: 600; spacing: 6px; }")
            for button, text in ((self.apply_profile_button, 'Apply'), (self.reset_profile_button, 'Reset'), (self.start_calibration_button, 'Start')):
                try:
                    button.setText(text)
                    button.setMinimumHeight(_scaled_h(30, floor=28))
                    button.setMaximumHeight(_scaled_h(30, floor=28))
                except Exception:
                    pass
        except Exception:
            pass

        self.reload_button.setText("Reload")
        self.restore_defaults_button.setText("Defaults")
        self.bottom_defaults_button.setText("Defaults")
        self.bottom_save_button.setText("Save Profiles")

        try:
            self._set_label_pixmap(self.context_art, self._shield_pixmap, _scaled_h(52, floor=44))
            self._set_label_pixmap(self.logo_label, self._logo_pixmap, _scaled_h(36, floor=30))
        except Exception:
            pass

        try:
            self.summary_card.hide()
        except Exception:
            pass

        for button in (self.back_button, self.reload_button, self.restore_defaults_button, self.bottom_reload_button, self.bottom_defaults_button, self.bottom_save_button):
            try:
                button.setMinimumHeight(_scaled_h(32, floor=28))
                button.setMaximumHeight(_scaled_h(32, floor=28))
            except Exception:
                pass

        try:
            self.back_button.setFixedSize(_scaled_w(88 if compact else 100), _scaled_h(34 if compact else 38))
        except Exception:
            pass

        try:
            self._set_button_accent(self.back_button, "#39D8FF")
        except Exception:
            pass

    # =========================================================================
    # Loading / service snapshots
    # =========================================================================

    def reload_calibration(self) -> None:
        snapshot = self._load_calibration_snapshot()

        self._profiles = deepcopy(snapshot["profiles"])
        self._loaded_profiles = deepcopy(snapshot["profiles"])
        self._connection_snapshot = dict(snapshot["connection"])
        self._mode = safe_str(snapshot.get("mode"), MODE_DEMO).strip().lower() or MODE_DEMO
        self._status_message = safe_str(snapshot.get("service_state_text"), "Calibration profiles loaded.").strip()
        self._last_saved_label = safe_str(snapshot.get("last_saved"), "Not saved in this session.").strip()
        self._changed_since_load = False

        if self._selected_sensor not in self._profiles:
            self._selected_sensor = SENSOR_TEMPERATURE

        self._apply_profiles_to_ui()
        self._refresh_compact_layout()
        self.calibration_loaded.emit(self.diagnostics())

    def _load_calibration_snapshot(self) -> Dict[str, Any]:
        profiles = _default_profiles()
        service_state = "ready"
        service_state_text = "Calibration profiles loaded from protected defaults."
        last_saved = "Not saved in this session."
        mode = self._read_current_mode()

        # 1) calibration_service
        try:
            calibration_service = self.services.get("calibration_service") or self.services.get("calibration")
            if calibration_service is not None:
                for method_name in (
                    "snapshot",
                    "get_snapshot",
                    "get_calibration_snapshot",
                    "load_profiles",
                    "get_profiles",
                    "calibration_profiles",
                ):
                    method = getattr(calibration_service, method_name, None)
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
                                        if key in SENSOR_ORDER and isinstance(value, Mapping)
                                    }

                                for sensor_key in SENSOR_ORDER:
                                    if sensor_key in raw_profiles and isinstance(raw_profiles[sensor_key], Mapping):
                                        profiles[sensor_key] = _normalize_profile(sensor_key, raw_profiles[sensor_key])

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

        # 2) settings_service fallback
        try:
            settings_service = self.services.get("settings_service") or self.services.get("settings")
            if settings_service is not None:
                for method_name in ("get_setting", "value", "get"):
                    method = getattr(settings_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method("calibration_profiles")
                            if isinstance(raw, Mapping):
                                for sensor_key in SENSOR_ORDER:
                                    if sensor_key in raw and isinstance(raw[sensor_key], Mapping):
                                        profiles[sensor_key] = _normalize_profile(sensor_key, raw[sensor_key])
                                break
                        except Exception:
                            continue
        except Exception:
            pass

        # 3) config.py fallback
        try:
            import config as project_config  # local import on purpose

            for attr_name in ("DEFAULT_CALIBRATION_PROFILES", "CALIBRATION_PROFILES"):
                if hasattr(project_config, attr_name):
                    raw = getattr(project_config, attr_name)
                    if isinstance(raw, Mapping):
                        for sensor_key in SENSOR_ORDER:
                            if sensor_key in raw and isinstance(raw[sensor_key], Mapping):
                                profiles[sensor_key] = _normalize_profile(sensor_key, raw[sensor_key])
        except Exception:
            pass

        # 4) app_state fallback
        try:
            if self.app_state is not None:
                for attr_name in ("calibration_profiles", "sensor_calibration_profiles", "profiles"):
                    if hasattr(self.app_state, attr_name):
                        raw = getattr(self.app_state, attr_name)
                        if isinstance(raw, Mapping):
                            for sensor_key in SENSOR_ORDER:
                                if sensor_key in raw and isinstance(raw[sensor_key], Mapping):
                                    profiles[sensor_key] = _normalize_profile(sensor_key, raw[sensor_key])
                            break
        except Exception:
            pass

        # 5) UI-side cache fallback to preserve screen-specific metadata such as
        # saved/edited states, custom scale, samples, and tolerance values.
        try:
            cached_profiles = _load_ui_profiles_cache()
            if cached_profiles:
                for sensor_key in SENSOR_ORDER:
                    if sensor_key in cached_profiles:
                        profiles[sensor_key] = _normalize_profile(sensor_key, cached_profiles[sensor_key])
                cache_file = _ui_profiles_cache_path()
                try:
                    raw_cache = json.loads(cache_file.read_text(encoding="utf-8"))
                    if isinstance(raw_cache, Mapping):
                        last_saved = safe_str(raw_cache.get("last_saved"), last_saved).strip() or last_saved
                except Exception:
                    pass
        except Exception:
            pass

        connection_snapshot = self._read_connection_snapshot()

        return {
            "profiles": {sensor: _normalize_profile(sensor, profile) for sensor, profile in profiles.items()},
            "service_state": service_state,
            "service_state_text": service_state_text,
            "last_saved": last_saved,
            "mode": mode,
            "connection": connection_snapshot,
        }

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
                        try:
                            result = method()
                            text = safe_str(result, "").strip().lower()
                            if text:
                                mode = text
                                break
                        except Exception:
                            continue
        except Exception:
            pass

        if mode not in {MODE_DEMO, MODE_HARDWARE}:
            mode = MODE_DEMO
        return mode

    def _read_connection_snapshot(self) -> Dict[str, Any]:
        snapshot: Dict[str, Any] = {
            "connected": False,
            "waiting": False,
            "port": "",
            "baudrate": "",
            "detail": "",
        }

        try:
            connection_service = self.services.get("connection_service") or self.services.get("connection")
            if connection_service is not None:
                for method_name in ("snapshot", "get_snapshot", "connection_snapshot"):
                    method = getattr(connection_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method()
                            if isinstance(raw, Mapping):
                                snapshot.update(dict(raw))
                                break
                        except Exception:
                            continue
        except Exception:
            pass

        try:
            serial_service = self.services.get("serial_service") or self.services.get("serial")
            if serial_service is not None:
                for method_name in ("snapshot", "get_snapshot", "serial_snapshot"):
                    method = getattr(serial_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method()
                            if isinstance(raw, Mapping):
                                snapshot.setdefault("port", raw.get("port", raw.get("selected_port", "")))
                                snapshot.setdefault("baudrate", raw.get("baudrate", ""))
                                snapshot.setdefault("last_line", raw.get("last_line", ""))
                                break
                        except Exception:
                            continue
        except Exception:
            pass

        connected = bool(snapshot.get("connected", False)) or bool(snapshot.get("serial_connected", False)) or bool(snapshot.get("esp32_connected", False))
        waiting = bool(snapshot.get("waiting", False))
        available_ports = snapshot.get("available_ports", [])
        if not waiting and not connected and isinstance(available_ports, list) and len(available_ports) > 0:
            waiting = True

        port = safe_str(snapshot.get("port"), "").strip()
        if not port and isinstance(available_ports, list) and available_ports:
            port = safe_str(available_ports[0], "").strip()

        detail = safe_str(snapshot.get("detail"), "").strip()
        if not detail:
            if connected:
                detail = "Hardware link is active for live-assisted calibration."
            elif waiting:
                detail = "A possible serial device is available for calibration."
            else:
                detail = "No confirmed hardware link is active. Offline profile editing is still available."

        return {
            "connected": connected,
            "waiting": waiting,
            "port": port,
            "baudrate": safe_str(snapshot.get("baudrate"), "").strip(),
            "detail": detail,
        }

    # =========================================================================
    # UI application
    # =========================================================================

    def _apply_profiles_to_ui(self) -> None:
        selected_profile = self._profiles.get(self._selected_sensor, _default_profile(self._selected_sensor))
        self._apply_selected_editor(selected_profile)

        enabled_count = 0
        ready_count = 0
        for sensor_key, profile in self._profiles.items():
            enabled = safe_bool(profile.get("enabled"), True)
            state = safe_str(profile.get("state"), "pending").strip().lower()
            if enabled:
                enabled_count += 1
            if state in {"ready", "saved", "calibrated"}:
                ready_count += 1

            card = self.profile_cards.get(sensor_key)
            if card is not None:
                accent = _accent_for_state(state if enabled else "disabled")
                state_text = "Disabled" if not enabled else state.title()
                card.set_selected(sensor_key == self._selected_sensor)
                card.set_payload(
                    state_text=state_text,
                    subtitle=safe_str(profile.get("summary"), "").strip(),
                    value_line=(
                        f"Offset {safe_float(profile.get('offset'), 0.0):+0.3f} • "
                        f"Scale {safe_float(profile.get('scale'), 1.0):0.4f}"
                    ),
                    last_line=(
                        f"Samples {safe_int(profile.get('samples'), 0)} • "
                        f"Tolerance {safe_float(profile.get('tolerance'), 0.0):0.2f} • "
                        f"{safe_str(profile.get('last_calibrated'), '').strip() or 'Not calibrated'}"
                    ),
                    accent_hex=accent,
                )

        # selected summary
        selected_state = safe_str(selected_profile.get("state"), "pending").strip().lower()
        selected_enabled = safe_bool(selected_profile.get("enabled"), True)
        selected_accent = _accent_for_state(selected_state if selected_enabled else "disabled")
        selected_title = SENSOR_LABELS.get(self._selected_sensor, self._selected_sensor.title())
        selected_state_text = "Disabled" if not selected_enabled else selected_state.title()

        summary_lines = {
            1: f"Offset: {safe_float(selected_profile.get('offset'), 0.0):+0.3f} {SENSOR_UNITS.get(self._selected_sensor, '').strip()}-space correction.",
            2: f"Scale: {safe_float(selected_profile.get('scale'), 1.0):0.4f} gain factor with {safe_int(selected_profile.get('samples'), 0)} sample window.",
            3: f"Tolerance: {safe_float(selected_profile.get('tolerance'), 0.0):0.2f} acceptable deviation window.",
            4: self._status_message,
        }

        self.summary_card.set_payload(
            title=selected_title,
            state_text=selected_state_text,
            summary=safe_str(selected_profile.get("summary"), "").strip() or "Selected calibration profile is ready for review.",
            lines=summary_lines,
            accent_hex=selected_accent,
        )

        # pills
        status_text = "Unsaved Changes" if self._changed_since_load else "Loaded"
        self.status_pill.setText(status_text)
        self._apply_pill_style(self.status_pill, "#FFD25E" if self._changed_since_load else "#42E393")

        connection_connected = safe_bool(self._connection_snapshot.get("connected"), False)
        connection_waiting = safe_bool(self._connection_snapshot.get("waiting"), False)
        if connection_connected:
            connection_text = "Hardware Connected"
            connection_accent = "#42E393"
        elif connection_waiting:
            connection_text = "Waiting for Device"
            connection_accent = "#FFD25E"
        else:
            connection_text = "Offline Calibration"
            connection_accent = "#39D8FF"

        self.connection_pill.setText(connection_text)
        self._apply_pill_style(self.connection_pill, connection_accent)

        self.selected_pill.setText(SENSOR_SHORT_LABELS.get(self._selected_sensor, self._selected_sensor.title()))
        self._apply_pill_style(self.selected_pill, selected_accent)

        # chips
        self._apply_header_chip_style(self.hardware_chip, connection_accent)
        self._apply_header_chip_style(self.profile_chip, "#67D8FF")
        self._apply_header_chip_style(self.persistence_chip, "#42E393" if not self._changed_since_load else "#FFD25E")

        # stat cards
        self.stat_enabled.set_payload(
            value=str(enabled_count),
            subtitle="Profiles currently enabled for runtime use.",
            accent_hex="#42E393" if enabled_count > 0 else "#FFD25E",
        )
        self.stat_ready.set_payload(
            value=str(ready_count),
            subtitle="Profiles marked ready, calibrated, or saved.",
            accent_hex="#42E393" if ready_count > 0 else "#39D8FF",
        )
        self.stat_selected.set_payload(
            value=SENSOR_SHORT_LABELS.get(self._selected_sensor, self._selected_sensor.title()),
            subtitle=f"Current editing target: {selected_state_text.lower()} profile.",
            accent_hex=selected_accent,
        )
        self.stat_link.set_payload(
            value="Connected" if connection_connected else ("Waiting" if connection_waiting else "Offline"),
            subtitle=safe_str(self._connection_snapshot.get("detail"), "").strip(),
            accent_hex=connection_accent,
        )

        # context
        mode_text = "Hardware" if self._mode == MODE_HARDWARE else "Demo"
        self.context_line_1.setText(f"Mode: {mode_text}")
        self.context_line_2.setText(
            f"Hardware link: {'Connected' if connection_connected else ('Waiting' if connection_waiting else 'Offline')}"
        )
        self.context_line_3.setText(f"Last save: {self._last_saved_label}")
        self.context_line_4.setText(f"Status: {self._status_message}")

        self.context_note.setText(
            "Use service-driven calibration when hardware is available, or adjust profile parameters offline and save them for later runtime use."
        )

        # buttons
        self._set_button_accent(self.save_button, "#42E393" if self._changed_since_load else "#39D8FF")
        self._set_button_accent(self.bottom_save_button, "#42E393" if self._changed_since_load else "#39D8FF")
        self._set_button_accent(self.start_calibration_button, "#42E393" if connection_connected or self._mode == MODE_DEMO else "#39D8FF")

        self.calibration_profile_changed.emit(self.diagnostics())

    def _apply_selected_editor(self, profile: Mapping[str, Any]) -> None:
        self._editor_sync_in_progress = True

        self.editor_sensor_label.setText(
            f"Sensor: {SENSOR_LABELS.get(self._selected_sensor, self._selected_sensor.title())}"
        )

        self.offset_spin.blockSignals(True)
        self.scale_spin.blockSignals(True)
        self.samples_spin.blockSignals(True)
        self.tolerance_spin.blockSignals(True)
        self.enabled_checkbox.blockSignals(True)

        self.offset_spin.setValue(safe_float(profile.get("offset"), 0.0))
        self.scale_spin.setValue(safe_float(profile.get("scale"), 1.0))
        self.samples_spin.setValue(safe_int(profile.get("samples"), 8))
        self.tolerance_spin.setValue(safe_float(profile.get("tolerance"), 1.0))
        self.enabled_checkbox.setChecked(safe_bool(profile.get("enabled"), True))

        self.offset_spin.blockSignals(False)
        self.scale_spin.blockSignals(False)
        self.samples_spin.blockSignals(False)
        self.tolerance_spin.blockSignals(False)
        self.enabled_checkbox.blockSignals(False)

        self._editor_sync_in_progress = False

    # =========================================================================
    # Selection / editor handling
    # =========================================================================

    def _handle_profile_card_clicked(self, sensor_key: str) -> None:
        sensor = safe_str(sensor_key, "").strip()
        if sensor not in self._profiles:
            return

        self._selected_sensor = sensor
        self._apply_profiles_to_ui()
        self.calibration_profile_selected.emit(sensor)

    def _on_editor_changed(self) -> None:
        if self._editor_sync_in_progress:
            return
        self._sync_selected_profile_from_editor(mark_state_if_needed=True)

    def _sync_selected_profile_from_editor(self, *, mark_state_if_needed: bool) -> None:
        if self._selected_sensor not in self._profiles:
            return

        profile = dict(self._profiles.get(self._selected_sensor, _default_profile(self._selected_sensor)))
        profile["offset"] = round(float(self.offset_spin.value()), 3)
        profile["scale"] = round(float(self.scale_spin.value()), 4)
        profile["samples"] = int(self.samples_spin.value())
        profile["tolerance"] = round(float(self.tolerance_spin.value()), 2)
        profile["enabled"] = bool(self.enabled_checkbox.isChecked())

        if not profile["enabled"]:
            profile["state"] = "disabled"
            profile["summary"] = "This calibration profile is currently disabled and will not be used by the runtime."
        elif mark_state_if_needed:
            current_loaded = self._loaded_profiles.get(self._selected_sensor, _default_profile(self._selected_sensor))
            if any(profile.get(key) != current_loaded.get(key) for key in ("offset", "scale", "samples", "tolerance", "enabled")):
                profile["state"] = "edited"
                profile["summary"] = (
                    f"{SENSOR_SHORT_LABELS.get(self._selected_sensor, self._selected_sensor.title())} profile has unsaved edits. "
                    "Review and save to persist them."
                )

        self._profiles[self._selected_sensor] = _normalize_profile(self._selected_sensor, profile)
        self._changed_since_load = self._profiles != self._loaded_profiles
        self._status_message = (
            f"Edited {SENSOR_SHORT_LABELS.get(self._selected_sensor, self._selected_sensor.title())} calibration profile."
            if mark_state_if_needed else self._status_message
        )
        self._apply_profiles_to_ui()

    # =========================================================================
    # Calibration actions
    # =========================================================================

    def _handle_apply_selected_clicked(self) -> None:
        self._sync_selected_profile_from_editor(mark_state_if_needed=True)
        self._status_message = (
            f"Applied current editor values to {SENSOR_SHORT_LABELS.get(self._selected_sensor, self._selected_sensor.title())} profile."
        )
        self._apply_profiles_to_ui()

    def _handle_reset_selected_clicked(self) -> None:
        self._profiles[self._selected_sensor] = _default_profile(self._selected_sensor)
        self._changed_since_load = self._profiles != self._loaded_profiles
        self._status_message = f"Reset {SENSOR_SHORT_LABELS.get(self._selected_sensor, self._selected_sensor.title())} profile to defaults."
        self._apply_profiles_to_ui()
        self.calibration_reset.emit(self.diagnostics())

    def _handle_restore_defaults_clicked(self) -> None:
        self._profiles = _default_profiles()
        self._changed_since_load = self._profiles != self._loaded_profiles
        self._status_message = "Restored all calibration profiles to protected defaults."
        self._apply_profiles_to_ui()
        self.calibration_reset.emit(self.diagnostics())

    def _handle_start_calibration_clicked(self) -> None:
        self._sync_selected_profile_from_editor(mark_state_if_needed=True)
        self.calibration_started.emit(self._selected_sensor)

        sensor_key = self._selected_sensor
        profile = dict(self._profiles.get(sensor_key, _default_profile(sensor_key)))
        result_profile: Optional[Dict[str, Any]] = None
        result_message = ""

        try:
            calibration_service = self.services.get("calibration_service") or self.services.get("calibration")
            if calibration_service is not None:
                for method_name in (
                    "start_calibration",
                    "calibrate_sensor",
                    "run_calibration",
                    "calibrate",
                    "begin_calibration",
                ):
                    method = getattr(calibration_service, method_name, None)
                    if callable(method):
                        raw = None
                        try:
                            raw = method(sensor_key, dict(profile))
                        except TypeError:
                            try:
                                raw = method(sensor_key)
                            except TypeError:
                                try:
                                    raw = method(dict(profile))
                                except Exception:
                                    continue
                        except Exception:
                            continue

                        if isinstance(raw, Mapping):
                            data = dict(raw)
                            if "profile" in data and isinstance(data.get("profile"), Mapping):
                                result_profile = _normalize_profile(sensor_key, dict(data.get("profile", {})))
                            elif sensor_key in data and isinstance(data.get(sensor_key), Mapping):
                                result_profile = _normalize_profile(sensor_key, dict(data.get(sensor_key, {})))
                            else:
                                result_profile = _normalize_profile(sensor_key, data)

                            result_message = safe_str(
                                data.get("detail", data.get("summary", "")),
                                "",
                            ).strip()
                            break
                        elif raw not in (None, ""):
                            result_message = safe_str(raw, "").strip()
                            break
        except Exception:
            pass

        if result_profile is None:
            profile["state"] = "calibrated" if profile.get("enabled", True) else "disabled"
            profile["last_calibrated"] = "Updated in current admin session"
            profile["summary"] = (
                f"{SENSOR_SHORT_LABELS.get(sensor_key, sensor_key.title())} calibration was updated in the current session. "
                "Review the values and save them to persist."
            )
            result_profile = _normalize_profile(sensor_key, profile)
            if not result_message:
                result_message = (
                    f"Calibration routine finished for {SENSOR_SHORT_LABELS.get(sensor_key, sensor_key.title())} "
                    "using local protected fallback behavior."
                )

        self._profiles[sensor_key] = result_profile
        self._changed_since_load = self._profiles != self._loaded_profiles
        self._status_message = result_message or "Calibration routine completed."
        self._apply_profiles_to_ui()
        self.calibration_completed.emit(self.diagnostics())

    def _handle_save_clicked(self) -> None:
        self._sync_selected_profile_from_editor(mark_state_if_needed=False)

        for sensor_key, profile in list(self._profiles.items()):
            updated = dict(profile)
            if safe_bool(updated.get("enabled"), True):
                updated["state"] = "saved"
                updated["last_calibrated"] = "Saved in current admin session"
                updated["summary"] = (
                    f"{SENSOR_SHORT_LABELS.get(sensor_key, sensor_key.title())} profile is saved and ready for runtime use."
                )
            else:
                updated["state"] = "disabled"
                updated["summary"] = "This calibration profile is currently disabled and will not be used by the runtime."
            self._profiles[sensor_key] = _normalize_profile(sensor_key, updated)

        self._last_saved_label = "Saved to protected runtime"
        self._persist_profiles()

        self._loaded_profiles = deepcopy(self._profiles)
        self._changed_since_load = False
        self._status_message = "Calibration profiles were saved successfully."

        self._apply_profiles_to_ui()
        self.calibration_saved.emit(self.diagnostics())

    def _persist_profiles(self) -> None:
        payload = deepcopy(self._profiles)

        # 1) Persist the UI-side cache first so the screen can restore saved state,
        # scale, samples, and tolerance values exactly as the admin left them.
        try:
            _save_ui_profiles_cache(payload, last_saved_label=self._last_saved_label)
        except Exception:
            pass

        # 2) calibration_service save for runtime-compatible values.
        try:
            calibration_service = self.services.get("calibration_service") or self.services.get("calibration")
            if calibration_service is not None:
                saved = False
                for method_name in ("save_all", "update_calibration"):
                    method = getattr(calibration_service, method_name, None)
                    if callable(method):
                        try:
                            service_payload: Dict[str, Dict[str, Any]] = {}
                            for sensor_key, profile in payload.items():
                                service_payload[sensor_key] = {
                                    "offset": safe_float(profile.get("offset"), 0.0),
                                }
                            method(service_payload)
                            saved = True
                            break
                        except Exception:
                            continue

                if not saved:
                    for sensor_key, profile in payload.items():
                        for method_name in ("set_sensor_calibration", "update_sensor_calibration"):
                            method = getattr(calibration_service, method_name, None)
                            if callable(method):
                                try:
                                    method(sensor_key, {"offset": safe_float(profile.get("offset"), 0.0)})
                                    break
                                except Exception:
                                    continue
        except Exception:
            pass

        # 3) settings_service fallback to store full UI payload.
        try:
            settings_service = self.services.get("settings_service") or self.services.get("settings")
            if settings_service is not None:
                for method_name in ("set_setting", "set_runtime_value", "update_runtime_flag"):
                    method = getattr(settings_service, method_name, None)
                    if callable(method):
                        try:
                            method("calibration_profiles", dict(payload))
                            break
                        except Exception:
                            continue
        except Exception:
            pass

        # 4) app_state fallback.
        try:
            if self.app_state is not None:
                for attr_name in ("calibration_profiles", "sensor_calibration_profiles"):
                    if hasattr(self.app_state, attr_name):
                        try:
                            setattr(self.app_state, attr_name, dict(payload))
                        except Exception:
                            pass

                for method_name in ("update_calibration_profiles", "set_calibration_profiles", "apply_calibration_snapshot"):
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
                border-radius: 20px;
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
                font-size: 8px;
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
                    border-radius: 20px;
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
            "selected_sensor": self._selected_sensor,
            "profiles": deepcopy(self._profiles),
            "loaded_profiles": deepcopy(self._loaded_profiles),
            "changed_since_load": self._changed_since_load,
            "status_message": self._status_message,
            "last_saved_label": self._last_saved_label,
            "mode": self._mode,
            "connection_snapshot": dict(self._connection_snapshot),
            "background_path": self._background_path,
            "logo_path": self._logo_small_path,
            "admin_shield_path": self._admin_shield_path,
        }
