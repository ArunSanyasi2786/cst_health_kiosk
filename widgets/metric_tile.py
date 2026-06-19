"""
widgets/metric_tile.py

Premium metric tile widget for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is one of the most important reusable data-display widgets in the kiosk UI
- It is designed for:
    - results screen metric cards
    - measuring screen live metric previews
    - admin dashboard metric summaries
    - detail-screen entry tiles
    - diagnosis overview blocks
- It builds on the premium frosted-glass design language already established in:
    - widgets/glass_card.py
    - widgets/glow_label.py
- It centralizes:
    - metric title / icon / unit
    - large highlighted value display
    - severity state coloring
    - category/status chip
    - trend indicator
    - reference/range hint
    - optional sensor/source tag
- It is intentionally flexible so the same tile can be used for:
    - temperature
    - SpO2
    - pulse rate
    - respiratory rate
    - BMI
    - weight
    - height

Design goals:
- premium futuristic medical dashboard look
- visually consistent with the kiosk theme
- lightweight enough for Raspberry Pi kiosk use
- safe fallback behavior when optional helpers are unavailable
- easy to wire into later screens with minimal custom code
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.logger import get_logger

try:
    from core.utils import safe_float, safe_str
except Exception:  # pragma: no cover
    def safe_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None or value == "":
                return default
            return float(value)
        except Exception:
            return default

    def safe_str(value: Any, default: str = "") -> str:
        try:
            if value is None:
                return default
            return str(value)
        except Exception:
            return default

try:
    from core.constants import (
        METRIC_BMI,
        METRIC_HEIGHT,
        METRIC_LABELS,
        METRIC_PULSE,
        METRIC_RR,
        METRIC_SPO2,
        METRIC_TEMPERATURE,
        METRIC_UNITS,
        METRIC_WEIGHT,
        SEVERITY_ATTENTION,
        SEVERITY_CRITICAL,
        SEVERITY_NORMAL,
        SEVERITY_UNKNOWN,
        SEVERITY_WARNING,
    )
except Exception:  # pragma: no cover
    METRIC_WEIGHT = "weight"
    METRIC_HEIGHT = "height"
    METRIC_BMI = "bmi"
    METRIC_TEMPERATURE = "temperature"
    METRIC_SPO2 = "spo2"
    METRIC_PULSE = "pulse_rate"
    METRIC_RR = "respiratory_rate"

    METRIC_LABELS = {
        METRIC_WEIGHT: "Weight",
        METRIC_HEIGHT: "Height",
        METRIC_BMI: "BMI",
        METRIC_TEMPERATURE: "Temperature",
        METRIC_SPO2: "SpO₂",
        METRIC_PULSE: "Pulse Rate",
        METRIC_RR: "Respiratory Rate",
    }
    METRIC_UNITS = {
        METRIC_WEIGHT: "kg",
        METRIC_HEIGHT: "cm",
        METRIC_BMI: "kg/m²",
        METRIC_TEMPERATURE: "°C",
        METRIC_SPO2: "%",
        METRIC_PULSE: "bpm",
        METRIC_RR: "breaths/min",
    }

    SEVERITY_NORMAL = "normal"
    SEVERITY_ATTENTION = "attention"
    SEVERITY_WARNING = "warning"
    SEVERITY_CRITICAL = "critical"
    SEVERITY_UNKNOWN = "unknown"

try:
    from core.utils import format_metric_value as _format_metric_value_helper
except Exception:  # pragma: no cover
    _format_metric_value_helper = None

from widgets.glass_card import GlassCard

try:
    from config import KIOSK_HEIGHT, KIOSK_WIDTH
except Exception:  # pragma: no cover
    KIOSK_WIDTH = 1024
    KIOSK_HEIGHT = 600


def _is_small_kiosk_default() -> bool:
    return bool(KIOSK_WIDTH <= 860 or KIOSK_HEIGHT <= 520)


try:
    from widgets.glow_label import GlowLabel
    _HAS_GLOW_LABEL = True
except Exception:  # pragma: no cover
    GlowLabel = QLabel  # type: ignore
    _HAS_GLOW_LABEL = False


logger = get_logger(__name__)


# ============================================================
# Theme dataclass
# ============================================================

@dataclass(frozen=True)
class MetricTileTheme:
    """
    Theme container for MetricTile.
    """
    title_color: str = "#F2FBFF"
    subtitle_color: str = "rgba(210, 233, 248, 0.80)"
    value_color: str = "#F8FDFF"
    unit_color: str = "rgba(216, 234, 247, 0.86)"
    reference_color: str = "rgba(190, 215, 234, 0.80)"
    source_color: str = "rgba(200, 224, 242, 0.82)"
    neutral_chip_bg: str = "rgba(52, 89, 128, 0.26)"
    neutral_chip_border: str = "rgba(151, 214, 255, 0.24)"
    neutral_chip_text: str = "#E9F8FF"
    trend_up: str = "#53E9A8"
    trend_down: str = "#FF8C9D"
    trend_stable: str = "#8FD8FF"
    primary_accent: str = "#39D8FF"
    normal_accent: str = "#3CE38E"
    attention_accent: str = "#FFD05A"
    warning_accent: str = "#FF9F43"
    critical_accent: str = "#FF6D84"


DEFAULT_METRIC_TILE_THEME = MetricTileTheme()


# ============================================================
# Main widget
# ============================================================

class MetricTile(GlassCard):
    """
    Premium metric card/tile based on GlassCard.

    Capabilities:
    - large metric value display
    - unit label
    - category chip
    - trend label
    - reference text
    - source tag
    - severity color system
    - update from measurement/classification payloads
    """

    metric_clicked = pyqtSignal(str)
    detail_requested = pyqtSignal(str)

    metric_key_changed = pyqtSignal(str)
    metric_value_changed = pyqtSignal(str, object)
    severity_changed = pyqtSignal(str)
    trend_changed = pyqtSignal(str, str)

    TREND_UP = "up"
    TREND_DOWN = "down"
    TREND_STABLE = "stable"
    TREND_NONE = "none"

    def __init__(
        self,
        metric_key: str = "",
        parent: Optional[QWidget] = None,
        *,
        title: str = "",
        subtitle: str = "",
        value: Any = None,
        unit: str = "",
        icon_path: str = "",
        footer: str = "",
        reference_text: str = "",
        source_text: str = "",
        status_label: str = "",
        status_detail: str = "",
        severity: str = SEVERITY_UNKNOWN,
        trend_direction: str = TREND_NONE,
        trend_text: str = "",
        theme: Optional[MetricTileTheme] = None,
        compact: bool = False,
        clickable: bool = True,
        show_status_chip: bool = True,
        show_reference_text: bool = True,
        show_source_tag: bool = False,
        show_trend: bool = True,
        minimum_height: int = 128,
    ) -> None:
        try:
            self._logger = logger.bind(component="MetricTile")
        except Exception:
            self._logger = logger

        self._theme = theme or DEFAULT_METRIC_TILE_THEME
        self._metric_key = safe_str(metric_key, "").strip().lower()
        self._severity = safe_str(severity, SEVERITY_UNKNOWN).strip().lower() or SEVERITY_UNKNOWN
        self._trend_direction = safe_str(trend_direction, self.TREND_NONE).strip().lower() or self.TREND_NONE
        self._trend_text = safe_str(trend_text, "").strip()
        self._status_label = safe_str(status_label, "").strip()
        self._status_detail = safe_str(status_detail, "").strip()
        self._reference_text = safe_str(reference_text, "").strip()
        self._reference_full_text = self._reference_text
        self._source_text = safe_str(source_text, "").strip()
        self._display_unit = safe_str(unit, "").strip()
        self._raw_value = value
        self._display_decimals: Optional[int] = None
        self._flash_enabled = True
        self._explicit_compact = bool(compact)
        self._auto_compact = _is_small_kiosk_default()
        self._compact = bool(compact) or self._auto_compact
        self._minimum_height_requested = max(88, int(minimum_height))
        self._row_height_value = 0
        self._row_height_meta = 0

        self._default_title = self._label_for_metric(self._metric_key) if self._metric_key else ""
        self._default_unit = self._unit_for_metric(self._metric_key) if self._metric_key else ""

        resolved_title = safe_str(title, "").strip() or self._default_title
        resolved_subtitle = safe_str(subtitle, "").strip() or ""
        resolved_unit = self._display_unit or self._default_unit

        super().__init__(
            title=resolved_title,
            subtitle=resolved_subtitle,
            body="",
            footer=footer,
            icon_path=icon_path,
            parent=parent,
            accent_color=self._accent_for_severity(self._severity),
            minimum_height=self._resolved_tile_height(),
            clickable=clickable,
            enable_hover_effect=not self._compact,
            show_accent_bar=True,
            compact=self._compact,
        )

        self._show_status_chip = bool(show_status_chip)
        self._show_reference_text = bool(show_reference_text)
        self._show_source_tag = bool(show_source_tag)
        self._show_trend = bool(show_trend)

        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.setInterval(250)
        self._flash_timer.timeout.connect(self._restore_value_visual_state)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._build_metric_content()
        self.set_content_widget(self._content_root)

        self.clicked.connect(self._on_self_clicked)

        self.set_unit(resolved_unit)
        self.set_reference_text(self._reference_text)
        self.set_source_text(self._source_text)
        self.set_status(self._status_label, detail=self._status_detail)
        self.set_trend(self._trend_direction, self._trend_text)
        self.set_severity(self._severity)

        if value is not None:
            self.set_value(value, flash=False)
        else:
            self.set_value_text("--", flash=False)

        self._refresh_meta_visibility()
        self._apply_metric_style()
        self._apply_geometry_constraints()

    # ========================================================
    # Geometry helpers
    # ========================================================

    def _resolved_tile_height(self) -> int:
        if self._compact:
            upper = 112 if self._auto_compact else 120
            lower = 92 if self._auto_compact else 100
            return max(lower, min(upper, self._minimum_height_requested))
        if self._auto_compact:
            return max(112, min(132, self._minimum_height_requested))
        return max(136, self._minimum_height_requested)

    def _meta_row_visible(self) -> bool:
        return (
            self._show_status_chip and bool(self._status_label)
        ) or (
            self._show_reference_text and bool(self._reference_full_text)
        ) or (
            self._show_source_tag and bool(self._source_text)
        )

    def _apply_geometry_constraints(self) -> None:
        tile_h = self._resolved_tile_height()
        self.setMinimumHeight(tile_h)
        self.setMaximumHeight(tile_h)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        if hasattr(self, "_content_root") and self._content_root is not None:
            self._content_root.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        if hasattr(self, "_value_row") and self._value_row is not None:
            self._value_row.setMinimumHeight(self._row_height_value)
            self._value_row.setMaximumHeight(self._row_height_value)
            self._value_row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        if hasattr(self, "_meta_row") and self._meta_row is not None:
            if self._meta_row.isVisible():
                self._meta_row.setMinimumHeight(self._row_height_meta)
                self._meta_row.setMaximumHeight(self._row_height_meta)
            else:
                self._meta_row.setMinimumHeight(0)
                self._meta_row.setMaximumHeight(0)
            self._meta_row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.updateGeometry()

    # ========================================================
    # UI building
    # ========================================================

    def _build_metric_content(self) -> None:
        self._content_root = QWidget(self)
        self._content_root.setObjectName("MetricTileContentRoot")
        self._content_root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self._content_root.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QVBoxLayout(self._content_root)
        top_margin = 1 if self._compact else (1 if self._auto_compact else 2)
        root.setContentsMargins(0, top_margin, 0, 0)
        root.setSpacing(3 if self._compact else (4 if self._auto_compact else 5))

        self._row_height_value = 28 if self._compact else (40 if self._auto_compact else 48)
        self._row_height_meta = 16 if self._compact else (22 if self._auto_compact else 26)

        # ----------------------------------------------------
        # Main value row
        # ----------------------------------------------------
        self._value_row = QWidget(self._content_root)
        self._value_row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._value_row.setMinimumHeight(self._row_height_value)
        self._value_row.setMaximumHeight(self._row_height_value)

        value_row_layout = QHBoxLayout(self._value_row)
        value_row_layout.setContentsMargins(0, 0, 0, 0)
        value_row_layout.setSpacing(4 if self._compact else (5 if self._auto_compact else 6))

        use_glow_value = _HAS_GLOW_LABEL and not self._compact
        if use_glow_value:
            try:
                self._value_label = GlowLabel(
                    role=GlowLabel.ROLE_TITLE,
                    align_center=False,
                    use_outline=False,
                    enable_paint_glow=True,
                    initial_glow_strength=0.30,
                    initial_glow_blur=16,
                )
                self._value_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            except Exception:
                self._value_label = QLabel(self._value_row)
                self._value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        else:
            self._value_label = QLabel(self._value_row)
            self._value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._value_label.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        self._unit_label = QLabel(self._value_row)
        self._unit_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        self._unit_label.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        self._trend_label = QLabel(self._value_row)
        self._trend_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._trend_label.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        value_row_layout.addWidget(self._value_label, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        value_row_layout.addWidget(self._unit_label, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        value_row_layout.addStretch(1)
        value_row_layout.addWidget(self._trend_label, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # ----------------------------------------------------
        # Bottom meta row
        # ----------------------------------------------------
        self._meta_row = QWidget(self._content_root)
        self._meta_row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._meta_row.setMinimumHeight(self._row_height_meta)
        self._meta_row.setMaximumHeight(self._row_height_meta)

        meta_layout = QHBoxLayout(self._meta_row)
        meta_layout.setContentsMargins(0, 0, 0, 0)
        meta_layout.setSpacing(4 if self._compact else (5 if self._auto_compact else 6))

        self._status_chip = QLabel(self._meta_row)
        self._status_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_chip.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        self._reference_label = QLabel(self._meta_row)
        self._reference_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._reference_label.setWordWrap(False)
        self._reference_label.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)

        self._source_chip = QLabel(self._meta_row)
        self._source_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._source_chip.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        meta_layout.addWidget(self._status_chip, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        meta_layout.addWidget(self._reference_label, 1, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        meta_layout.addStretch(1)
        meta_layout.addWidget(self._source_chip, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        root.addWidget(self._value_row)
        root.addWidget(self._meta_row)

    # ========================================================
    # Styling helpers
    # ========================================================

    def _accent_for_severity(self, severity: str) -> str:
        severity = safe_str(severity, SEVERITY_UNKNOWN).strip().lower()
        if severity == SEVERITY_NORMAL:
            return self._theme.normal_accent
        if severity == SEVERITY_ATTENTION:
            return self._theme.attention_accent
        if severity == SEVERITY_WARNING:
            return self._theme.warning_accent
        if severity == SEVERITY_CRITICAL:
            return self._theme.critical_accent
        return self._theme.primary_accent

    def _status_colors(self, severity: str) -> tuple[str, str, str]:
        severity = safe_str(severity, SEVERITY_UNKNOWN).strip().lower()

        if severity == SEVERITY_NORMAL:
            accent = self._theme.normal_accent
        elif severity == SEVERITY_ATTENTION:
            accent = self._theme.attention_accent
        elif severity == SEVERITY_WARNING:
            accent = self._theme.warning_accent
        elif severity == SEVERITY_CRITICAL:
            accent = self._theme.critical_accent
        else:
            accent = self._theme.primary_accent

        color = QColor(accent)
        chip_bg = f"rgba({color.red()}, {color.green()}, {color.blue()}, 0.16)"
        chip_border = f"rgba({color.red()}, {color.green()}, {color.blue()}, 0.38)"
        chip_text = "#F7FCFF" if severity in {SEVERITY_WARNING, SEVERITY_CRITICAL} else "#EAF9FF"
        return chip_bg, chip_border, chip_text

    def _trend_color(self, direction: str) -> str:
        direction = safe_str(direction, self.TREND_NONE).strip().lower()
        if direction == self.TREND_UP:
            return self._theme.trend_up
        if direction == self.TREND_DOWN:
            return self._theme.trend_down
        return self._theme.trend_stable

    def _apply_metric_style(self) -> None:
        accent = self._accent_for_severity(self._severity)
        chip_bg, chip_border, chip_text = self._status_colors(self._severity)

        if self._compact:
            value_size = 15 if self._auto_compact else 17
            unit_size = 8 if self._auto_compact else 9
            trend_size = 8
            reference_size = 7 if self._auto_compact else 8
            chip_size = 7 if self._auto_compact else 8
            source_size = 7 if self._auto_compact else 8
        elif self._auto_compact:
            value_size = 22
            unit_size = 10
            trend_size = 9
            reference_size = 8
            chip_size = 8
            source_size = 8
        else:
            value_size = 28
            unit_size = 12
            trend_size = 11
            reference_size = 10
            chip_size = 10
            source_size = 9

        self._value_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.value_color};
                font-size: {value_size}px;
                font-weight: 800;
                background: transparent;
            }}
            """
        )
        if _HAS_GLOW_LABEL and isinstance(self._value_label, GlowLabel):
            try:
                self._value_label.set_glow_color(accent)
                self._value_label.set_text_color(self._theme.value_color)
            except Exception:
                pass

        self._unit_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.unit_color};
                font-size: {unit_size}px;
                font-weight: 600;
                background: transparent;
                padding-bottom: {2 if not self._compact else 1}px;
            }}
            """
        )

        self._trend_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._trend_color(self._trend_direction)};
                font-size: {trend_size}px;
                font-weight: 700;
                background: transparent;
            }}
            """
        )

        self._status_chip.setStyleSheet(
            f"""
            QLabel {{
                color: {chip_text};
                font-size: {chip_size}px;
                font-weight: 700;
                border: 1px solid {chip_border};
                border-radius: {12 if not self._compact else 7}px;
                background: {chip_bg};
                padding: {4 if not self._compact else 1}px {8 if not self._compact else 4}px;
            }}
            """
        )

        self._reference_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.reference_color};
                font-size: {reference_size}px;
                font-weight: 500;
                background: transparent;
            }}
            """
        )

        self._source_chip.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.source_color};
                font-size: {source_size}px;
                font-weight: 700;
                border: 1px solid rgba(153, 214, 255, 0.20);
                border-radius: {10 if not self._compact else 6}px;
                background: rgba(40, 69, 102, 0.18);
                padding: {3 if not self._compact else 1}px {7 if not self._compact else 3}px;
            }}
            """
        )

        try:
            super().set_accent_color(accent)
        except Exception:
            pass

        self._apply_reference_text_display()
        self._apply_geometry_constraints()

    def _apply_reference_text_display(self) -> None:
        text = safe_str(self._reference_full_text, "").strip()
        if not text:
            self._reference_label.clear()
            return

        try:
            available = max(24, self._reference_label.width() - 4)
            metrics = QFontMetrics(self._reference_label.font())
            elided = metrics.elidedText(text, Qt.TextElideMode.ElideRight, available)
            self._reference_label.setText(elided)
            self._reference_label.setToolTip(text if elided != text else "")
        except Exception:
            self._reference_label.setText(text)
            self._reference_label.setToolTip("")

    def _refresh_meta_visibility(self) -> None:
        narrow = self.width() > 0 and self.width() < (188 if self._compact else 228)
        ultra_compact = self._auto_compact and narrow

        self._status_chip.setVisible(self._show_status_chip and bool(self._status_label))
        self._reference_label.setVisible(
            self._show_reference_text and bool(self._reference_full_text) and not ultra_compact
        )
        self._source_chip.setVisible(
            self._show_source_tag and bool(self._source_text) and not ultra_compact
        )

        trend_visible = (
            self._show_trend
            and self._trend_direction != self.TREND_NONE
            and bool(self._trend_label.text().strip())
            and not ultra_compact
        )
        self._trend_label.setVisible(trend_visible)

        self._unit_label.setVisible(bool(self._display_unit.strip()))
        self._meta_row.setVisible(self._meta_row_visible())

        self._apply_reference_text_display()
        self._apply_geometry_constraints()

    # ========================================================
    # Metric defaults
    # ========================================================

    def _label_for_metric(self, metric_key: str) -> str:
        metric_key = safe_str(metric_key, "").strip().lower()
        if not metric_key:
            return ""
        return safe_str(METRIC_LABELS.get(metric_key), metric_key.replace("_", " ").title())

    def _unit_for_metric(self, metric_key: str) -> str:
        metric_key = safe_str(metric_key, "").strip().lower()
        if not metric_key:
            return ""
        return safe_str(METRIC_UNITS.get(metric_key), "")

    def _default_decimals_for_metric(self, metric_key: str) -> int:
        metric_key = safe_str(metric_key, "").strip().lower()
        if metric_key in {METRIC_SPO2, METRIC_PULSE, METRIC_RR, METRIC_HEIGHT}:
            return 0
        return 1

    # ========================================================
    # Formatting helpers
    # ========================================================

    def _format_value_only(self, value: Any) -> str:
        if value is None or value == "":
            return "--"

        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or "--"

        numeric = safe_float(value, 0.0)

        if _format_metric_value_helper is not None and self._metric_key:
            try:
                formatted = _format_metric_value_helper(
                    self._metric_key,
                    value,
                    show_unit=False,
                    fallback="--",
                )
                if formatted is not None:
                    return safe_str(formatted, "--")
            except Exception:
                pass

        decimals = self._display_decimals
        if decimals is None:
            decimals = self._default_decimals_for_metric(self._metric_key)

        if decimals <= 0:
            try:
                return str(int(round(numeric)))
            except Exception:
                return "--"

        return f"{numeric:.{decimals}f}"

    def _trend_prefix(self, direction: str) -> str:
        direction = safe_str(direction, self.TREND_NONE).strip().lower()
        if direction == self.TREND_UP:
            return "▲"
        if direction == self.TREND_DOWN:
            return "▼"
        if direction == self.TREND_STABLE:
            return "●"
        return ""

    # ========================================================
    # Public getters
    # ========================================================

    def metric_key(self) -> str:
        return self._metric_key

    def raw_value(self) -> Any:
        return self._raw_value

    def severity(self) -> str:
        return self._severity

    def status_label(self) -> str:
        return self._status_label

    def trend_direction(self) -> str:
        return self._trend_direction

    # ========================================================
    # Public setters
    # ========================================================

    def set_metric_key(self, metric_key: str) -> None:
        new_key = safe_str(metric_key, "").strip().lower()
        old_key = self._metric_key
        old_default_title = self._default_title
        old_default_unit = self._default_unit

        self._metric_key = new_key
        self._default_title = self._label_for_metric(new_key)
        self._default_unit = self._unit_for_metric(new_key)

        if not self.title().strip() or self.title().strip() == old_default_title:
            self.set_title(self._default_title)

        if not self._display_unit.strip() or self._display_unit.strip() == old_default_unit:
            self.set_unit(self._default_unit)

        if new_key != old_key:
            self.metric_key_changed.emit(new_key)

    def set_title(self, title: str) -> None:  # type: ignore[override]
        super().set_title(title)

    def set_subtitle(self, subtitle: str) -> None:  # type: ignore[override]
        super().set_subtitle(subtitle)

    def set_display_decimals(self, decimals: Optional[int]) -> None:
        self._display_decimals = None if decimals is None else max(0, int(decimals))
        if self._raw_value not in (None, ""):
            self.set_value(self._raw_value, flash=False)

    def set_unit(self, unit: str) -> None:
        self._display_unit = safe_str(unit, "").strip()
        self._unit_label.setText(self._display_unit)
        self._refresh_meta_visibility()

    def set_value(self, value: Any, unit: Optional[str] = None, *, flash: bool = True) -> None:
        if unit is not None:
            self.set_unit(unit)

        self._raw_value = value
        text = self._format_value_only(value)
        self.set_value_text(text, flash=flash)
        self.metric_value_changed.emit(self._metric_key, value)

    def set_value_text(self, text: str, *, flash: bool = True) -> None:
        display = safe_str(text, "--").strip() or "--"

        if _HAS_GLOW_LABEL and isinstance(self._value_label, GlowLabel):
            try:
                self._value_label.set_text(display)
            except Exception:
                self._value_label.setText(display)
        else:
            self._value_label.setText(display)

        if flash and self._flash_enabled:
            self._flash_value_visual_state()

    def set_status(self, label: str, *, detail: str = "") -> None:
        self._status_label = safe_str(label, "").strip()
        self._status_detail = safe_str(detail, "").strip()
        self._status_chip.setText(self._status_label)
        self._refresh_meta_visibility()

        # In compact cards or small kiosks, detailed body text makes the tile visually crowded.
        # Keep the body area empty there so the card stays tight and readable.
        try:
            if self._compact or self._auto_compact:
                super().set_body("")
            else:
                super().set_body(self._status_detail if self._status_detail else "")
        except Exception:
            pass

    def set_status_text(self, text: str) -> None:
        self.set_status(text)

    def set_reference_text(self, text: str) -> None:
        self._reference_full_text = safe_str(text, "").strip()
        self._reference_text = self._reference_full_text
        self._apply_reference_text_display()
        self._refresh_meta_visibility()

    def set_source_text(self, text: str) -> None:
        self._source_text = safe_str(text, "").strip()
        self._source_chip.setText(self._source_text)
        self._refresh_meta_visibility()

    def set_show_source_tag(self, visible: bool) -> None:
        self._show_source_tag = bool(visible)
        self._refresh_meta_visibility()

    def set_show_status_chip(self, visible: bool) -> None:
        self._show_status_chip = bool(visible)
        self._refresh_meta_visibility()

    def set_show_reference_text(self, visible: bool) -> None:
        self._show_reference_text = bool(visible)
        self._refresh_meta_visibility()

    def set_show_trend(self, visible: bool) -> None:
        self._show_trend = bool(visible)
        self._refresh_meta_visibility()

    def set_severity(self, severity: str) -> None:
        normalized = safe_str(severity, SEVERITY_UNKNOWN).strip().lower() or SEVERITY_UNKNOWN
        self._severity = normalized
        self._apply_metric_style()
        self.severity_changed.emit(normalized)

    def set_accent_color(self, accent_color: str) -> None:  # type: ignore[override]
        color_text = safe_str(accent_color, "").strip()
        if not color_text:
            try:
                super().set_accent_color(color_text)
            except Exception:
                pass
            return

        color = QColor(color_text)
        if color.isValid():
            if color.name().lower() == QColor(self._theme.normal_accent).name().lower():
                self._severity = SEVERITY_NORMAL
            elif color.name().lower() == QColor(self._theme.attention_accent).name().lower():
                self._severity = SEVERITY_ATTENTION
            elif color.name().lower() == QColor(self._theme.warning_accent).name().lower():
                self._severity = SEVERITY_WARNING
            elif color.name().lower() == QColor(self._theme.critical_accent).name().lower():
                self._severity = SEVERITY_CRITICAL
            else:
                if self._severity == SEVERITY_UNKNOWN:
                    self._severity = SEVERITY_UNKNOWN

        try:
            super().set_accent_color(color_text)
        except Exception:
            pass
        self._apply_metric_style()

    def set_trend(self, direction: str, text: str = "") -> None:
        normalized = safe_str(direction, self.TREND_NONE).strip().lower() or self.TREND_NONE
        if normalized not in {self.TREND_UP, self.TREND_DOWN, self.TREND_STABLE, self.TREND_NONE}:
            normalized = self.TREND_NONE

        self._trend_direction = normalized
        self._trend_text = safe_str(text, "").strip()

        if normalized == self.TREND_NONE:
            self._trend_label.clear()
        else:
            prefix = self._trend_prefix(normalized)
            combined = prefix
            if self._trend_text:
                combined = f"{prefix} {self._trend_text}".strip()
            self._trend_label.setText(combined)

        self._apply_metric_style()
        self._refresh_meta_visibility()
        self.trend_changed.emit(self._trend_direction, self._trend_text)

    def clear_trend(self) -> None:
        self.set_trend(self.TREND_NONE, "")

    def set_click_enabled(self, enabled: bool) -> None:
        self.set_clickable(bool(enabled))

    # ========================================================
    # Measurement/classification integration
    # ========================================================

    def apply_measurement(
        self,
        value: Any,
        *,
        unit: Optional[str] = None,
        severity: Optional[str] = None,
        status_label: str = "",
        status_detail: str = "",
        reference_text: str = "",
        flash: bool = True,
    ) -> None:
        if unit is not None:
            self.set_unit(unit)
        if severity is not None:
            self.set_severity(severity)
        if status_label or status_detail:
            self.set_status(status_label, detail=status_detail)
        if reference_text:
            self.set_reference_text(reference_text)

        self.set_value(value, flash=flash)

    def apply_measurement_payload(
        self,
        measurements: Mapping[str, Any],
        classifications: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """
        Update the tile using a measurement payload and optional classification payload.

        Expected classification structure:
        {
            "temperature": {
                "label": "Mild Fever",
                "severity": "attention",
                "summary": "Temperature indicates mild fever."
            }
        }
        """
        if not self._metric_key:
            return

        value = None
        if isinstance(measurements, Mapping):
            value = measurements.get(self._metric_key)

        classification = {}
        if isinstance(classifications, Mapping):
            raw = classifications.get(self._metric_key, {})
            if isinstance(raw, Mapping):
                classification = dict(raw)

        if classification:
            self.set_severity(safe_str(classification.get("severity"), SEVERITY_UNKNOWN))
            self.set_status(
                safe_str(classification.get("label"), ""),
                detail=safe_str(classification.get("summary"), ""),
            )
        self.set_value(value, flash=False)

    def bind_metric_defaults_from_key(self) -> None:
        """
        Refresh title and unit using the current metric key.
        """
        if not self._metric_key:
            return
        self.set_title(self._label_for_metric(self._metric_key))
        self.set_unit(self._unit_for_metric(self._metric_key))

    # ========================================================
    # Visual flash helpers
    # ========================================================

    def set_flash_enabled(self, enabled: bool) -> None:
        self._flash_enabled = bool(enabled)

    def _flash_value_visual_state(self) -> None:
        accent = self._accent_for_severity(self._severity)

        if _HAS_GLOW_LABEL and isinstance(self._value_label, GlowLabel):
            try:
                self._value_label.flash_once(duration_ms=650, peak_strength=1.0, end_strength=0.42)
            except Exception:
                pass

        self._value_label.setStyleSheet(
            f"""
            QLabel {{
                color: {accent};
                font-size: {15 if (self._compact and self._auto_compact) else (17 if self._compact else (22 if self._auto_compact else 28))}px;
                font-weight: 900;
                background: transparent;
            }}
            """
        )
        self._flash_timer.start()

    def _restore_value_visual_state(self) -> None:
        self._apply_metric_style()

    # ========================================================
    # Interaction
    # ========================================================

    def _on_self_clicked(self) -> None:
        self.metric_clicked.emit(self._metric_key)
        self.detail_requested.emit(self._metric_key)

    # ========================================================
    # Resize handling
    # ========================================================

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_reference_text_display()
        self._apply_geometry_constraints()

    # ========================================================
    # Convenience presets
    # ========================================================

    def mark_normal(self, label: str = "Normal", detail: str = "") -> None:
        self.set_severity(SEVERITY_NORMAL)
        self.set_status(label, detail=detail)

    def mark_attention(self, label: str = "Attention", detail: str = "") -> None:
        self.set_severity(SEVERITY_ATTENTION)
        self.set_status(label, detail=detail)

    def mark_warning(self, label: str = "Warning", detail: str = "") -> None:
        self.set_severity(SEVERITY_WARNING)
        self.set_status(label, detail=detail)

    def mark_critical(self, label: str = "Critical", detail: str = "") -> None:
        self.set_severity(SEVERITY_CRITICAL)
        self.set_status(label, detail=detail)

    # ========================================================
    # Diagnostics
    # ========================================================

    def diagnostics(self) -> Dict[str, Any]:
        value_text = ""
        try:
            value_text = self._value_label.text() if hasattr(self._value_label, "text") else ""
        except Exception:
            value_text = ""

        return {
            "metric_key": self._metric_key,
            "title": self.title(),
            "subtitle": self.subtitle(),
            "value_text": value_text,
            "raw_value": self._raw_value,
            "unit": self._display_unit,
            "severity": self._severity,
            "status_label": self._status_label,
            "status_detail": self._status_detail,
            "trend_direction": self._trend_direction,
            "trend_text": self._trend_text,
            "reference_text": self._reference_full_text,
            "source_text": self._source_text,
            "compact": self._compact,
            "show_status_chip": self._show_status_chip,
            "show_reference_text": self._show_reference_text,
            "show_source_tag": self._show_source_tag,
            "show_trend": self._show_trend,
            "tile_height": self.height(),
            "meta_row_visible": self._meta_row.isVisible(),
        }