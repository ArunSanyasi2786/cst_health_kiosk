"""
screens/pulse_detail_screen.py

Clean compact pulse-detail screen for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the pulse / heart-rate detail view opened from the main results screen.
- It is tuned for the user's current 800x480 kiosk target while still scaling up.
- It keeps the pulse screen visually consistent with the cleaned temperature and
  SpO2 detail screens: fewer panels, stronger hierarchy, less clutter, easier
  readability, and safer refresh behavior.
- It avoids slow refresh effects and heavy layered widgets that made the older
  pulse screen look busy or break alignment.

Primary goals of this revision:
- clean and professional compact presentation
- strong pulse value visibility
- full-width pulse reference band instead of crowded side panels
- reliable refresh with immediate repaint
- simple service integration with robust fallbacks
"""

from __future__ import annotations

import math
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
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
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
    from core.constants import SCREEN_RESULTS, SCREEN_QR, SCREEN_CONSULT, METRIC_PULSE
except Exception:  # pragma: no cover
    SCREEN_RESULTS = "results"
    SCREEN_QR = "qr"
    SCREEN_CONSULT = "consult"
    METRIC_PULSE = "pulse_rate"

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

PULSE_WARNING_LOW = 50.0
PULSE_NORMAL_LOW = 60.0
PULSE_NORMAL_HIGH = 100.0
PULSE_WARNING_HIGH = 120.0

PULSE_SCALE_MIN = 30.0
PULSE_SCALE_MAX = 160.0


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_asset(relative_path: str) -> str:
    relative_clean = safe_str(relative_path, "").strip().replace("\\", "/").lstrip("/")
    if not relative_clean:
        return ""

    try:
        import core.asset_paths as asset_paths

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


def _format_pulse(value: Optional[int]) -> str:
    if value is None:
        return "--"
    return f"{int(value)} bpm"


def _normalize_pulse(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None

    raw = safe_float(value, -1.0)
    if raw <= 0:
        return None
    if raw < 10.0:
        return None

    raw = max(0.0, min(220.0, raw))
    return int(round(raw))


def _accent_for_state(state: str) -> str:
    text = safe_str(state, "").strip().lower()
    if text in {"critical", "critical low", "very high pulse", "bradycardia", "tachycardia"}:
        return "#FF6E88"
    if text in {"warning", "elevated pulse", "high"}:
        return "#FFA14D"
    if text in {"attention", "low pulse", "borderline low"}:
        return "#FFD25E"
    if text in {"normal", "healthy"}:
        return "#42E393"
    return "#39D8FF"


def _normalize_pulse_thresholds(raw: Optional[Mapping[str, Any]]) -> Dict[str, float]:
    base = {
        "warning_low": PULSE_WARNING_LOW,
        "normal_low": PULSE_NORMAL_LOW,
        "normal_high": PULSE_NORMAL_HIGH,
        "warning_high": PULSE_WARNING_HIGH,
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
        "warning_low": round(max(20.0, ordered[0]), 1),
        "normal_low": round(max(25.0, ordered[1]), 1),
        "normal_high": round(min(220.0, ordered[2]), 1),
        "warning_high": round(min(220.0, ordered[3]), 1),
    }


def _build_pulse_interpretation(
    pulse_value: Optional[int], thresholds: Mapping[str, float]
) -> Dict[str, Any]:
    if pulse_value is None:
        return {
            "label": "Unavailable",
            "severity": "unknown",
            "summary": "Pulse could not be interpreted because no valid heart-rate reading is available.",
            "active_band": "unknown",
            "accent_hex": "#39D8FF",
        }

    warning_low = safe_float(thresholds.get("warning_low"), PULSE_WARNING_LOW)
    normal_low = safe_float(thresholds.get("normal_low"), PULSE_NORMAL_LOW)
    normal_high = safe_float(thresholds.get("normal_high"), PULSE_NORMAL_HIGH)
    warning_high = safe_float(thresholds.get("warning_high"), PULSE_WARNING_HIGH)

    if pulse_value < warning_low:
        return {
            "label": "Critical Low",
            "severity": "critical",
            "summary": "Pulse is markedly below the common adult resting range.",
            "active_band": "critical_low",
            "accent_hex": _accent_for_state("critical"),
        }

    if pulse_value < normal_low:
        return {
            "label": "Low Pulse",
            "severity": "attention",
            "summary": "Pulse is below the common adult resting reference band.",
            "active_band": "low",
            "accent_hex": _accent_for_state("attention"),
        }

    if pulse_value <= normal_high:
        return {
            "label": "Healthy",
            "severity": "normal",
            "summary": "Pulse falls within the common adult resting reference range.",
            "active_band": "normal",
            "accent_hex": _accent_for_state("normal"),
        }

    if pulse_value < warning_high:
        return {
            "label": "Elevated Pulse",
            "severity": "warning",
            "summary": "Pulse is above the common adult resting reference range.",
            "active_band": "high",
            "accent_hex": _accent_for_state("warning"),
        }

    return {
        "label": "Very High Pulse",
        "severity": "critical",
        "summary": "Pulse is markedly elevated above the common resting reference range.",
        "active_band": "critical_high",
        "accent_hex": _accent_for_state("critical"),
    }


# =============================================================================
# Internal widgets
# =============================================================================

class _InfoStatCard(QFrame):
    """Clean stat card used across the compact pulse detail layout."""

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

        self.setObjectName("PulseInfoStatCard")
        self.setMinimumHeight(72)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(2)

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
            QFrame#PulseInfoStatCard {{
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.22);
                border-radius: 18px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(13, 36, 66, 0.94),
                    stop:1 rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.10)
                );
            }}
            """
        )
        self.title_label.setStyleSheet(
            """
            QLabel {
                color: rgba(220, 236, 248, 0.84);
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
                font-size: 21px;
                font-weight: 900;
                background: transparent;
            }
            """
        )
        self.subtitle_label.setStyleSheet(
            """
            QLabel {
                color: rgba(191, 214, 232, 0.76);
                font-size: 8px;
                font-weight: 500;
                background: transparent;
            }
            """
        )


class _PulseBandWidget(QWidget):
    """Clean full-width pulse reference scale for the compact 800x480 layout."""

    def __init__(self, overlay_path: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._overlay_pixmap = _pixmap_or_empty(overlay_path)
        self._pulse_value: Optional[int] = None
        self._thresholds = _normalize_pulse_thresholds(None)
        self._label = "Pulse"
        self._accent_hex = "#42E393"
        self.setMinimumHeight(176)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_payload(
        self,
        *,
        pulse_value: Optional[int],
        label: str,
        thresholds: Mapping[str, float],
        accent_hex: str,
    ) -> None:
        self._pulse_value = pulse_value
        self._label = safe_str(label, "Pulse").strip() or "Pulse"
        self._thresholds = _normalize_pulse_thresholds(thresholds)
        self._accent_hex = safe_str(accent_hex, "#42E393").strip() or "#42E393"
        self.update()

    def _value_to_ratio(self, value: float) -> float:
        clamped = max(PULSE_SCALE_MIN, min(PULSE_SCALE_MAX, float(value)))
        return (clamped - PULSE_SCALE_MIN) / (PULSE_SCALE_MAX - PULSE_SCALE_MIN)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect = self.rect().adjusted(14, 12, -14, -12)
        if rect.width() <= 40 or rect.height() <= 40:
            painter.end()
            return

        shell = QRectF(rect)
        painter.setPen(QPen(QColor(120, 196, 255, 44), 1.5))
        painter.setBrush(QColor(8, 25, 48, 148))
        painter.drawRoundedRect(shell, 24, 24)

        if not self._overlay_pixmap.isNull():
            overlay = self._overlay_pixmap.scaled(
                rect.width() - 160,
                rect.height() - 54,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.setOpacity(0.035)
            painter.drawPixmap(
                int(rect.left() + (rect.width() - overlay.width()) / 2),
                int(rect.top() + (rect.height() - overlay.height()) / 2) - 4,
                overlay,
            )
            painter.setOpacity(1.0)

        accent = QColor(self._accent_hex)
        soft_cyan = QColor(67, 217, 255, 40)

        # --- Reserved geometry -------------------------------------------------
        badge_width = min(200.0, max(168.0, rect.width() * 0.23))
        badge_height = 74.0
        badge_gap = 20.0
        badge_rect = QRectF(
            rect.right() - badge_width - 24.0,
            rect.top() + 50.0,
            badge_width,
            badge_height,
        )

        scale_left = rect.left() + 34.0
        scale_right = badge_rect.left() - badge_gap
        scale_width = max(240.0, scale_right - scale_left)

        wave_rect = QRectF(scale_left, rect.top() + 18.0, scale_width, 22.0)
        zone_y = rect.top() + 70.0
        band_rect = QRectF(scale_left, rect.top() + 102.0, scale_width, 18.0)
        tick_top = band_rect.bottom() + 6.0

        # --- ECG line ----------------------------------------------------------
        path = QPainterPath()
        x0 = wave_rect.left()
        y_mid = wave_rect.center().y()
        path.moveTo(x0, y_mid)
        steps = 120
        for i in range(1, steps + 1):
            t = i / steps
            x = wave_rect.left() + wave_rect.width() * t
            if 0.18 < t < 0.22:
                y = y_mid - 1
            elif 0.22 <= t < 0.245:
                y = y_mid + 4
            elif 0.245 <= t < 0.27:
                y = y_mid - 13
            elif 0.27 <= t < 0.30:
                y = y_mid + 7
            else:
                y = y_mid + math.sin(t * 11.0) * 0.6
            path.lineTo(x, y)
        painter.setPen(QPen(soft_cyan, 3.5))
        painter.drawPath(path)
        painter.setPen(QPen(QColor(72, 235, 180, 205), 1.4))
        painter.drawPath(path)

        warning_low = self._thresholds["warning_low"]
        normal_low = self._thresholds["normal_low"]
        normal_high = self._thresholds["normal_high"]
        warning_high = self._thresholds["warning_high"]

        # --- Zone labels -------------------------------------------------------
        zone_style = QFont("Inter", 8, QFont.Weight.Bold)
        painter.setFont(zone_style)
        zone_labels = [
            (PULSE_SCALE_MIN, warning_low, "Critical Low", QColor("#FF6E88")),
            (warning_low, normal_low, "Low", QColor("#FFD25E")),
            (normal_low, normal_high, "Healthy", QColor("#42E393")),
            (normal_high, warning_high, "High", QColor("#FFA14D")),
            (warning_high, PULSE_SCALE_MAX, "Very High", QColor("#FF6E88")),
        ]

        inner = band_rect.adjusted(3, 3, -3, -3)

        for start_v, end_v, text_value, color in zone_labels:
            x1 = inner.left() + inner.width() * self._value_to_ratio(start_v)
            x2 = inner.left() + inner.width() * self._value_to_ratio(end_v)
            label_rect = QRectF(min(x1, x2), zone_y, max(44.0, abs(x2 - x1)), 18)
            painter.setPen(color)
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, text_value)

        # --- Band shell --------------------------------------------------------
        painter.setPen(QPen(QColor(181, 232, 255, 54), 1.3))
        painter.setBrush(QColor(9, 21, 40, 214))
        painter.drawRoundedRect(band_rect, 10, 10)

        segments = [
            (PULSE_SCALE_MIN, warning_low, QColor("#F66F89")),
            (warning_low, normal_low, QColor("#F3C955")),
            (normal_low, normal_high, QColor("#47D88D")),
            (normal_high, warning_high, QColor("#F4A04A")),
            (warning_high, PULSE_SCALE_MAX, QColor("#F66F89")),
        ]
        for start_v, end_v, color in segments:
            x1 = inner.left() + inner.width() * self._value_to_ratio(start_v)
            x2 = inner.left() + inner.width() * self._value_to_ratio(end_v)
            seg = QRectF(min(x1, x2), inner.top(), max(6.0, abs(x2 - x1)), inner.height())
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(seg, inner.height() / 2, inner.height() / 2)

        # --- Marker ------------------------------------------------------------
        if self._pulse_value is not None:
            ratio = self._value_to_ratio(float(self._pulse_value))
            marker_x = inner.left() + inner.width() * ratio
            marker_top = zone_y + 12.0
            painter.setPen(QPen(accent, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(int(marker_x), int(marker_top + 6.0), int(marker_x), int(inner.bottom() + 18))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawEllipse(QRectF(marker_x - 13, marker_top - 13, 26, 26))
            painter.setBrush(QColor("#F7FCFF"))
            painter.drawEllipse(QRectF(marker_x - 5, marker_top - 5, 10, 10))

        # --- Ticks -------------------------------------------------------------
        tick_values = [30, 50, 60, 80, 100, 120, 140, 160]
        painter.setFont(QFont("Inter", 8, QFont.Weight.Medium))
        painter.setPen(QColor(206, 230, 246, 188))
        for tick in tick_values:
            tick_x = inner.left() + inner.width() * self._value_to_ratio(float(tick))
            painter.drawLine(int(tick_x), int(tick_top), int(tick_x), int(tick_top + 7))
            painter.drawText(QRectF(tick_x - 16, tick_top + 8, 32, 14), Qt.AlignmentFlag.AlignCenter, str(tick))

        # --- Right value badge -------------------------------------------------
        painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 132), 1.6))
        painter.setBrush(QColor(8, 24, 45, 234))
        painter.drawRoundedRect(badge_rect, 20, 20)

        value_text = _format_pulse(self._pulse_value)
        painter.setPen(QColor("#F7FCFF"))
        painter.setFont(QFont("Inter", 18, QFont.Weight.Bold))
        painter.drawText(
            QRectF(badge_rect.left(), badge_rect.top() + 10, badge_rect.width(), 26),
            Qt.AlignmentFlag.AlignCenter,
            value_text,
        )
        painter.setPen(QColor(accent))
        painter.setFont(QFont("Inter", 10, QFont.Weight.DemiBold))
        painter.drawText(
            QRectF(badge_rect.left(), badge_rect.top() + 40, badge_rect.width(), 18),
            Qt.AlignmentFlag.AlignCenter,
            self._label,
        )

        painter.end()



# =============================================================================
# Main screen
# =============================================================================

class PulseDetailScreen(QFrame):
    """Clean pulse detail screen tuned for 800x480 and demo/hardware session data."""

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

        try:
            self._logger = logger.bind(component="PulseDetailScreen")
        except Exception:
            self._logger = logger

        self.navigator = navigator
        self.app_state = app_state
        self.services = dict(services or {})
        self.animation_manager = animation_manager
        self.theme_manager = theme_manager

        self._payload: Dict[str, Any] = {}
        self._measurements: Dict[str, Any] = {}
        self._thresholds: Dict[str, float] = _normalize_pulse_thresholds(None)
        self._insight: Dict[str, Any] = {}
        self._status_message = "Pulse detail screen ready."

        self._is_compact = bool(IS_COMPACT_KIOSK or KIOSK_WIDTH <= 840 or KIOSK_HEIGHT <= 500)
        self._is_ultra_compact = bool(KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480)

        self._background_path = _resolve_asset("backgrounds/pulse_detail_bg.png")
        self._logo_small_path = _resolve_asset("logos/cst_logo_small.png")
        self._chart_overlay_path = _resolve_asset("detail_graphics/pulse_reference_chart.png")

        self._background_pixmap = _pixmap_or_empty(self._background_path)
        self._logo_pixmap = _pixmap_or_empty(self._logo_small_path)

        self.setObjectName("PulseDetailScreen")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._build_ui()
        self._setup_effects()
        self._apply_styles()
        self._update_compact_layout()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(9)

        self.top_bar = QWidget(self)
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        self.back_button = self._create_button("Back", variant="secondary", min_width=92, parent=self.top_bar)
        self.back_button.clicked.connect(self._handle_back_clicked)

        self.logo_badge = QLabel(self.top_bar)
        self.logo_badge.setObjectName("LogoBadge")
        self.logo_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_label_pixmap(self.logo_badge, self._logo_pixmap, 26)

        self.top_title = QLabel("Pulse Detail", self.top_bar)
        self.top_title.setObjectName("TopTitle")

        self.category_pill = QLabel("Healthy", self.top_bar)
        self.category_pill.setObjectName("RuntimePill")
        self.value_pill = QLabel("Pulse --", self.top_bar)
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

        self.header_card = QFrame(self)
        self.header_card.setObjectName("PulseHeaderCard")
        header_layout = QVBoxLayout(self.header_card)
        header_layout.setContentsMargins(14, 12, 14, 12)
        header_layout.setSpacing(6)

        if _HAS_GLOW_LABEL:
            try:
                self.hero_title = GlowLabel(
                    role=getattr(GlowLabel, "ROLE_TITLE", getattr(GlowLabel, "ROLE_STATUS", 0)),
                    align_center=True,
                    use_outline=False,
                    enable_paint_glow=True,
                    initial_glow_strength=0.42,
                    initial_glow_blur=16,
                )
            except Exception:
                self.hero_title = QLabel(self.header_card)
                self.hero_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            self.hero_title = QLabel(self.header_card)
            self.hero_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.summary_banner = QLabel(self.header_card)
        self.summary_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.summary_banner.setWordWrap(True)

        header_layout.addWidget(self.hero_title)
        header_layout.addWidget(self.summary_banner)

        self.stats_row = QWidget(self)
        stats_layout = QHBoxLayout(self.stats_row)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(8)

        self.stat_pulse = _InfoStatCard("Pulse", value="--", subtitle="Current heart-rate reading.")
        self.stat_range = _InfoStatCard("Healthy Band", value="60–100 bpm", subtitle="Common resting reference band.")
        self.stat_alert = _InfoStatCard("High Threshold", value="≥ 120 bpm", subtitle="Higher pulse band needing review.")
        self.stat_status = _InfoStatCard("Status", value="Ready", subtitle="Current interpretation.")

        stats_layout.addWidget(self.stat_pulse, 1)
        stats_layout.addWidget(self.stat_range, 1)
        stats_layout.addWidget(self.stat_alert, 1)
        stats_layout.addWidget(self.stat_status, 1)

        self.visual_panel = QFrame(self)
        self.visual_panel.setObjectName("VisualPanel")
        visual_layout = QVBoxLayout(self.visual_panel)
        visual_layout.setContentsMargins(12, 10, 12, 10)
        visual_layout.setSpacing(8)

        self.visual_title = QLabel("Pulse Reference Scale", self.visual_panel)
        self.visual_title.setObjectName("SectionTitle")
        self.band_widget = _PulseBandWidget(self._chart_overlay_path, self.visual_panel)

        visual_layout.addWidget(self.visual_title)
        visual_layout.addWidget(self.band_widget, 1)

        self.bottom_row = QWidget(self)
        bottom_layout = QHBoxLayout(self.bottom_row)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(10)

        self.results_button = self._create_button("Results", variant="secondary", min_width=112, parent=self.bottom_row)
        self.results_button.clicked.connect(self._handle_back_clicked)

        self.refresh_button = self._create_button("Refresh", variant="primary", min_width=112, parent=self.bottom_row)
        self.refresh_button.clicked.connect(self.reload_detail)

        self.qr_button = self._create_button("QR", variant="ghost", min_width=92, parent=self.bottom_row)
        self.qr_button.clicked.connect(self._handle_qr_clicked)

        self.consult_button = self._create_button("Consult", variant="success", min_width=112, parent=self.bottom_row)
        self.consult_button.clicked.connect(self._handle_consult_clicked)

        bottom_layout.addWidget(self.results_button, 1)
        bottom_layout.addStretch(1)
        bottom_layout.addWidget(self.refresh_button, 0)
        bottom_layout.addWidget(self.qr_button, 0)
        bottom_layout.addWidget(self.consult_button, 0)

        root.addWidget(self.top_bar)
        root.addWidget(self.header_card)
        root.addWidget(self.stats_row)
        root.addWidget(self.visual_panel, 1)
        root.addWidget(self.bottom_row)

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
        button.setMinimumHeight(38)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            """
            QPushButton {
                color: #F6FCFF;
                border: 1px solid rgba(157, 220, 255, 0.28);
                border-radius: 16px;
                padding: 9px 16px;
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
        scaled = pixmap.scaledToHeight(target_height, Qt.TransformationMode.SmoothTransformation)
        label.setPixmap(scaled)

    # ------------------------------------------------------------------
    # Style / effects
    # ------------------------------------------------------------------

    def _setup_effects(self) -> None:
        self.header_opacity = QGraphicsOpacityEffect(self.header_card)
        self.header_card.setGraphicsEffect(self.header_opacity)
        self.header_opacity.setOpacity(0.0)

        self.content_opacity = QGraphicsOpacityEffect(self.visual_panel)
        self.visual_panel.setGraphicsEffect(self.content_opacity)
        self.content_opacity.setOpacity(0.0)

        self.entry_group = QParallelAnimationGroup(self)

        self.header_fade = QPropertyAnimation(self.header_opacity, b"opacity", self)
        self.header_fade.setDuration(240)
        self.header_fade.setStartValue(0.0)
        self.header_fade.setEndValue(1.0)
        self.header_fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.content_fade = QPropertyAnimation(self.content_opacity, b"opacity", self)
        self.content_fade.setDuration(320)
        self.content_fade.setStartValue(0.0)
        self.content_fade.setEndValue(1.0)
        self.content_fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.entry_group.addAnimation(self.header_fade)
        self.entry_group.addAnimation(self.content_fade)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QFrame#PulseDetailScreen {
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
            QFrame#PulseHeaderCard {
                border: 1px solid rgba(170, 230, 255, 0.20);
                border-radius: 22px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(16, 34, 60, 0.86),
                    stop:1 rgba(8, 22, 44, 0.92)
                );
            }
            QFrame#VisualPanel {
                border: 1px solid rgba(170, 230, 255, 0.20);
                border-radius: 22px;
                background: rgba(12, 28, 50, 0.80);
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
                self.hero_title.set_glow_color("#43D9FF")
                self.hero_title.set_text_color("#F5FCFF")
                self.hero_title.set_text("Pulse Detail")
            except Exception:
                self.hero_title.setText("Pulse Detail")
        else:
            self.hero_title.setText("Pulse Detail")

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
        self.summary_banner.setStyleSheet(
            """
            QLabel {
                color: rgba(207, 229, 244, 0.90);
                font-size: 9px;
                font-weight: 600;
                background: transparent;
            }
            """
        )
        self.visual_title.setStyleSheet(
            """QLabel { color: #F4FCFF; font-size: 12px; font-weight: 800; background: transparent; }"""
        )

        self._set_button_accent(self.back_button, "#39D8FF")
        self._set_button_accent(self.results_button, "#39D8FF")
        self._set_button_accent(self.refresh_button, "#39D8FF")
        self._set_button_accent(self.qr_button, "#67D8FF")
        self._set_button_accent(self.consult_button, "#42E393")

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

    # ------------------------------------------------------------------
    # Lifecycle / responsive
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._play_entry_animation()
        self._update_compact_layout()
        self.reload_detail()

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
        self.header_card.layout().setContentsMargins(12 if compact else 16, 10 if compact else 14, 12 if compact else 16, 10 if compact else 14)
        self.header_card.layout().setSpacing(4 if compact else 6)
        self.stats_row.layout().setSpacing(6 if compact else 9)
        self.visual_panel.layout().setContentsMargins(10 if compact else 14, 9 if compact else 12, 10 if compact else 14, 9 if compact else 12)
        self.visual_panel.layout().setSpacing(6 if compact else 8)
        self.band_widget.setMinimumHeight(156 if ultra else (172 if compact else 210))

        for card in (self.stat_pulse, self.stat_range, self.stat_alert, self.stat_status):
            card.setMinimumHeight(72 if compact else 86)
            card.subtitle_label.setVisible(not compact)

        self.logo_badge.setVisible(not ultra)
        self.top_title.setText("Pulse Detail")
        self.summary_banner.setMaximumHeight(20 if compact else 32)
        self.hero_title.setStyleSheet(
            f"""
            QLabel {{
                color: #F6FCFF;
                font-size: {18 if ultra else 20}px;
                font-weight: 900;
                background: transparent;
            }}
            """
        )
        self.summary_banner.setStyleSheet(
            f"""
            QLabel {{
                color: rgba(207, 229, 244, 0.90);
                font-size: {8 if ultra else 9}px;
                font-weight: 600;
                background: transparent;
            }}
            """
        )
        if ultra:
            self.results_button.setMinimumWidth(112)
            self.refresh_button.setMinimumWidth(112)
            self.qr_button.setMinimumWidth(92)
            self.consult_button.setMinimumWidth(112)

    def _play_entry_animation(self) -> None:
        try:
            self.entry_group.start()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def reload_detail(self) -> None:
        self._measurements = self._load_measurements()
        self._thresholds = self._load_thresholds()

        pulse_value = _normalize_pulse(
            self._measurements.get(METRIC_PULSE, self._measurements.get("pulse", self._measurements.get("heart_rate")))
        )
        self._insight = _build_pulse_interpretation(pulse_value, self._thresholds)

        self._payload = {
            "pulse_value": pulse_value,
            "thresholds": dict(self._thresholds),
            "insight": dict(self._insight),
            "measurements": dict(self._measurements),
        }
        self._apply_payload()
        self.detail_loaded.emit(dict(self._payload))
        self.detail_refreshed.emit(dict(self._payload))

        # Safe queued redraw only. No synchronous repaint calls.
        QTimer.singleShot(0, self.band_widget.update)
        QTimer.singleShot(0, self.visual_panel.update)
        QTimer.singleShot(0, self.update)

    def _load_measurements(self) -> Dict[str, Any]:
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

        return measurements

    def _load_thresholds(self) -> Dict[str, float]:
        raw: Optional[Mapping[str, Any]] = None
        try:
            threshold_service = self.services.get("threshold_service") or self.services.get("thresholds")
            if threshold_service is not None:
                for method_name in (
                    "get_pulse_thresholds",
                    "pulse_thresholds",
                    "get_thresholds",
                    "get_metric_thresholds",
                ):
                    method = getattr(threshold_service, method_name, None)
                    if callable(method):
                        try:
                            if method_name == "get_metric_thresholds":
                                result = method(METRIC_PULSE)
                            else:
                                result = method()
                            if isinstance(result, Mapping):
                                raw = result
                                break
                        except Exception:
                            continue
        except Exception:
            pass

        return _normalize_pulse_thresholds(raw)

    def _apply_payload(self) -> None:
        pulse_value = self._payload.get("pulse_value")
        insight = dict(self._payload.get("insight", {}))
        thresholds = dict(self._payload.get("thresholds", {}))

        label = safe_str(insight.get("label"), "Unavailable").strip() or "Unavailable"
        accent_hex = safe_str(insight.get("accent_hex"), "#39D8FF").strip() or "#39D8FF"
        summary = safe_str(insight.get("summary"), "Pulse detail is ready.").strip() or "Pulse detail is ready."

        self.category_pill.setText(label)
        self.value_pill.setText(_format_pulse(pulse_value))
        self.status_pill.setText("Normal" if safe_str(insight.get("severity"), "").lower() == "normal" else label)
        self.summary_banner.setText(summary)

        self._apply_pill_style(self.category_pill, accent_hex)
        self._apply_pill_style(self.value_pill, "#67D8FF")
        self._apply_pill_style(self.status_pill, accent_hex)

        self.stat_pulse.set_payload(
            value=_format_pulse(pulse_value),
            subtitle="Current normalized heart-rate reading.",
            accent_hex="#39D8FF",
        )
        self.stat_range.set_payload(
            value=f"{int(round(thresholds.get('normal_low', PULSE_NORMAL_LOW)))}–{int(round(thresholds.get('normal_high', PULSE_NORMAL_HIGH)))} bpm",
            subtitle="Common resting reference band.",
            accent_hex="#42E393",
        )
        self.stat_alert.set_payload(
            value=f"≥ {int(round(thresholds.get('warning_high', PULSE_WARNING_HIGH)))} bpm",
            subtitle="Higher pulse band needing review.",
            accent_hex="#FFA14D",
        )
        self.stat_status.set_payload(
            value=label,
            subtitle="Current interpretation category.",
            accent_hex=accent_hex,
        )

        self.band_widget.set_payload(
            pulse_value=pulse_value,
            label=label,
            thresholds=thresholds,
            accent_hex=accent_hex,
        )

        self._set_button_accent(self.consult_button, "#42E393" if safe_str(insight.get("severity"), "").lower() == "normal" else accent_hex)

    def _apply_pill_style(self, label_widget: QLabel, accent_hex: str) -> None:
        accent = QColor(accent_hex)
        label_widget.setStyleSheet(
            f"""
            QLabel {{
                color: #EEF9FF;
                font-size: 9px;
                font-weight: 700;
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.34);
                border-radius: 14px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.15);
                padding: 5px 10px;
            }}
            """
        )

    # ------------------------------------------------------------------
    # Navigation / actions
    # ------------------------------------------------------------------

    def _handle_back_clicked(self) -> None:
        if self._navigate_to(SCREEN_RESULTS):
            return
        self.back_requested.emit()

    def _handle_qr_clicked(self) -> None:
        if self._navigate_to(SCREEN_QR):
            self.qr_requested.emit()
            return
        self.qr_requested.emit()

    def _handle_consult_clicked(self) -> None:
        if self._navigate_to(SCREEN_CONSULT):
            self.consult_requested.emit()
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

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "pulse_value": self._payload.get("pulse_value"),
            "thresholds": dict(self._thresholds),
            "insight": dict(self._insight),
            "background_path": self._background_path,
        }
