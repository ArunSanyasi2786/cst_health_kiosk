"""
widgets/publish_stat_card.py

Premium publish/statistics card widget for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the reusable analytics/statistics widget intended for the Publish screen
- It is designed to display:
    - publish overview cards
    - metric summary cards
    - trend cards
    - average / latest / min / max / count cards
    - compact analytics summaries for admin-style dashboards
- It is built to work especially well with payloads coming from:
    - services/publish_service.py
    - services/database_service.py
    - services/diagnosis_service.py
- It keeps the visual language consistent with:
    - widgets/glass_card.py
    - widgets/glow_label.py
    - widgets/animated_button.py

Typical payloads supported:
1) Overview card payload
   {
       "key": "completed_records",
       "title": "Completed Records",
       "value": 124,
       "subtitle": "Total records: 140",
       "state": "primary"
   }

2) Metric card payload
   {
       "key": "spo2",
       "title": "SpO₂",
       "value": 96.2,
       "unit": "%",
       "latest": 98,
       "min": 90,
       "max": 99,
       "count": 25,
       "trend": "stable",
       "state": "has_data"
   }

3) Detailed metric statistics payload
   {
       "metric_key": "pulse_rate",
       "metric_label": "Pulse Rate",
       "unit": "bpm",
       "count": 12,
       "avg": 84.3,
       "min": 68,
       "max": 110,
       "latest": 88,
       "trend": "up",
       "points": [{"label": "03-10", "value": 80}, ...],
       "has_data": true
   }

Design goals:
- premium futuristic medical analytics look
- clean at-a-glance reading for the publish/admin screens
- safe defaults for incomplete payloads
- lightweight enough for Raspberry Pi kiosk deployment
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional

from PyQt6.QtCore import Qt, QRectF, QSize, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
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
    from config import KIOSK_WIDTH, KIOSK_HEIGHT, IS_COMPACT_KIOSK
except Exception:  # pragma: no cover
    KIOSK_WIDTH = 800
    KIOSK_HEIGHT = 480
    IS_COMPACT_KIOSK = KIOSK_WIDTH <= 900 or KIOSK_HEIGHT <= 540

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

from widgets.animated_button import AnimatedButton
from widgets.glass_card import GlassCard

try:
    from widgets.glow_label import GlowLabel
    _HAS_GLOW_LABEL = True
except Exception:  # pragma: no cover
    GlowLabel = QLabel  # type: ignore
    _HAS_GLOW_LABEL = False


logger = get_logger(__name__)


# ============================================================
# Theme
# ============================================================

@dataclass(frozen=True)
class PublishStatCardTheme:
    """
    Theme container for PublishStatCard.
    """
    headline_color: str = "#F5FCFF"
    subtitle_color: str = "rgba(213, 235, 248, 0.86)"
    body_color: str = "rgba(223, 239, 250, 0.92)"
    subtle_text: str = "rgba(190, 214, 232, 0.82)"

    value_color: str = "#F8FDFF"
    unit_color: str = "rgba(202, 224, 241, 0.84)"

    chip_text: str = "#F4FCFF"
    chip_bg_alpha: float = 0.16
    chip_border_alpha: float = 0.36

    stat_value_color: str = "#F8FDFF"
    stat_label_color: str = "rgba(197, 221, 241, 0.82)"
    stat_block_bg: str = "rgba(28, 49, 79, 0.22)"
    stat_block_border: str = "rgba(149, 213, 255, 0.18)"

    sparkline_bg: str = "rgba(20, 39, 66, 0.22)"
    sparkline_border: str = "rgba(149, 213, 255, 0.18)"

    neutral_accent: str = "#7FD2FF"
    primary_accent: str = "#39D8FF"
    success_accent: str = "#3FE28F"
    warning_accent: str = "#FFD15E"
    danger_accent: str = "#FF6E88"
    empty_accent: str = "#8AA8C6"


DEFAULT_PUBLISH_STAT_CARD_THEME = PublishStatCardTheme()


# ============================================================
# Internal sparkline widget
# ============================================================

class _MiniSparkline(QWidget):
    """
    Lightweight inline sparkline/bars widget for publish metrics.

    It intentionally uses very simple painting:
    - supports up to ~30 points
    - no axes or labels
    - fits into the publish stat card without heavy rendering cost
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._points: List[float] = []
        self._accent_hex: str = DEFAULT_PUBLISH_STAT_CARD_THEME.primary_accent
        self._background = DEFAULT_PUBLISH_STAT_CARD_THEME.sparkline_bg
        self._border = DEFAULT_PUBLISH_STAT_CARD_THEME.sparkline_border
        self._compact = bool(IS_COMPACT_KIOSK)
        self._sync_compact_mode()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _sync_compact_mode(self) -> None:
        height = 42 if not self._compact else 34
        self.setMinimumHeight(height)
        self.setMaximumHeight(height)

    def set_compact(self, compact: bool) -> None:
        compact = bool(compact)
        if self._compact == compact:
            return
        self._compact = compact
        self._sync_compact_mode()
        self.update()

    def compact(self) -> bool:
        return self._compact

    def set_points(self, points: Iterable[float]) -> None:
        cleaned: List[float] = []
        for item in points:
            try:
                cleaned.append(float(item))
            except Exception:
                continue
        self._points = cleaned[-30:]
        self.update()

    def set_accent(self, accent_hex: str) -> None:
        self._accent_hex = safe_str(
            accent_hex,
            DEFAULT_PUBLISH_STAT_CARD_THEME.primary_accent,
        ) or DEFAULT_PUBLISH_STAT_CARD_THEME.primary_accent
        self.update()

    def set_palette_colors(self, background: str, border: str) -> None:
        self._background = background
        self._border = border
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(self.rect().adjusted(1, 1, -1, -1))
        if rect.width() <= 4 or rect.height() <= 4:
            painter.end()
            return

        radius = 12.0 if not self._compact else 10.0
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        painter.fillPath(path, QColor(self._background))
        pen = QPen(QColor(self._border))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawPath(path)

        points = [p for p in self._points if p is not None]
        if len(points) < 2:
            painter.end()
            return

        min_val = min(points)
        max_val = max(points)
        span = max(1e-9, max_val - min_val)

        inset = 6 if not self._compact else 5
        plot = QRectF(rect.adjusted(inset, inset, -inset, -inset))
        if plot.width() <= 2 or plot.height() <= 2:
            painter.end()
            return

        accent = QColor(self._accent_hex)
        fill = QColor(self._accent_hex)
        fill.setAlpha(55)

        count = len(points)
        bar_w = max(2.0, plot.width() / max(count, 1) - 1.5)
        for idx, value in enumerate(points):
            ratio = (value - min_val) / span
            height = max(2.0, plot.height() * ratio)
            x = plot.left() + (idx * (plot.width() / max(count, 1)))
            y = plot.bottom() - height

            bar_rect = QRectF(x, y, bar_w, height)
            painter.fillRect(bar_rect, fill)

        line_pen = QPen(accent)
        line_pen.setWidthF(1.8)
        painter.setPen(line_pen)

        coords: List[tuple[float, float]] = []
        for idx, value in enumerate(points):
            ratio = (value - min_val) / span
            x = plot.left() + (idx * (plot.width() / max(count - 1, 1)))
            y = plot.bottom() - (plot.height() * ratio)
            coords.append((x, y))

        for i in range(len(coords) - 1):
            painter.drawLine(
                int(coords[i][0]),
                int(coords[i][1]),
                int(coords[i + 1][0]),
                int(coords[i + 1][1]),
            )

        if coords:
            last_x, last_y = coords[-1]
            dot = QColor(self._accent_hex)
            dot.setAlpha(240)
            painter.setBrush(dot)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QRectF(last_x - 3.0, last_y - 3.0, 6.0, 6.0))

        painter.end()


# ============================================================
# Main widget
# ============================================================

class PublishStatCard(GlassCard):
    """
    Premium analytics/statistics card for publish/admin screens.

    Main capabilities:
    - large value display
    - unit label
    - state/trend chips
    - subtitle/detail line
    - latest/min/max/count stat mini-blocks
    - optional sparkline chart
    - direct application of publish service card payloads
    """

    card_clicked = pyqtSignal()
    details_requested = pyqtSignal()
    payload_applied = pyqtSignal(dict)
    state_changed = pyqtSignal(str)
    trend_changed = pyqtSignal(str)

    STATE_NEUTRAL = "neutral"
    STATE_PRIMARY = "primary"
    STATE_SUCCESS = "success"
    STATE_WARNING = "warning"
    STATE_DANGER = "danger"
    STATE_EMPTY = "empty"
    STATE_HAS_DATA = "has_data"

    TREND_UP = "up"
    TREND_DOWN = "down"
    TREND_STABLE = "stable"
    TREND_NONE = "none"

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        title: str = "",
        subtitle: str = "",
        value: Any = None,
        unit: str = "",
        icon_path: str = "",
        footer: str = "",
        state: str = STATE_NEUTRAL,
        trend: str = TREND_NONE,
        compact: bool = False,
        clickable: bool = True,
        show_sparkline: bool = True,
        show_stat_row: bool = True,
        show_action_row: bool = False,
        action_button_text: str = "Details",
        theme: Optional[PublishStatCardTheme] = None,
        minimum_height: int = 184,
    ) -> None:
        self._logger = logger.bind(component="PublishStatCard")

        self._theme = theme or DEFAULT_PUBLISH_STAT_CARD_THEME
        self._compact = bool(compact or IS_COMPACT_KIOSK)
        self._ultra_compact = bool(KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480)

        self._state = safe_str(state, self.STATE_NEUTRAL).strip().lower() or self.STATE_NEUTRAL
        self._trend = safe_str(trend, self.TREND_NONE).strip().lower() or self.TREND_NONE

        self._raw_value: Any = value
        self._value_text = ""
        self._unit = safe_str(unit, "").strip()
        self._badge_text = ""
        self._summary_text = safe_str(subtitle, "").strip()

        self._latest_value: Any = None
        self._min_value: Any = None
        self._max_value: Any = None
        self._count_value: Any = None

        self._show_sparkline = bool(show_sparkline)
        self._show_stat_row = bool(show_stat_row)
        self._show_action_row = bool(show_action_row)
        self._action_button_text = safe_str(action_button_text, "Details").strip() or "Details"

        super().__init__(
            title=title,
            subtitle="",
            body="",
            footer=footer,
            icon_path=icon_path,
            parent=parent,
            accent_color=self._accent_for_state(self._state),
            minimum_height=(
                minimum_height if not self._compact else (146 if self._ultra_compact else max(150, minimum_height - 24))
            ),
            clickable=clickable,
            enable_hover_effect=True,
            show_accent_bar=True,
            compact=self._compact,
        )

        self._build_content()
        self.set_content_widget(self._content_root)
        self.clicked.connect(self._on_card_clicked)
        self._details_button.clicked.connect(self.details_requested.emit)

        self._apply_style()
        self.set_summary_text(self._summary_text)
        self.set_unit(self._unit)
        self.set_state(self._state)
        self.set_trend(self._trend)
        self.set_value(value, flash=False)
        self.set_action_button_text(self._action_button_text)
        self._refresh_visibility()
        self._sync_compact_mode(force=True)

    # ========================================================
    # UI
    # ========================================================

    def _build_content(self) -> None:
        self._content_root = QWidget(self)
        self._content_root.setObjectName("PublishStatCardContentRoot")

        root = QVBoxLayout(self._content_root)
        top_margin = 2 if not self._compact else (1 if not self._ultra_compact else 0)
        root.setContentsMargins(0, top_margin, 0, 0)
        root.setSpacing(7 if not self._compact else (5 if not self._ultra_compact else 4))

        self._value_row = QWidget(self._content_root)
        value_layout = QHBoxLayout(self._value_row)
        value_layout.setContentsMargins(0, 0, 0, 0)
        value_layout.setSpacing(8 if not self._compact else (6 if not self._ultra_compact else 4))

        if _HAS_GLOW_LABEL:
            self._value_label = GlowLabel(
                role=GlowLabel.ROLE_STATUS if not self._compact else GlowLabel.ROLE_SUBTITLE,
                align_center=False,
                use_outline=False,
                enable_paint_glow=True,
                initial_glow_strength=0.42,
                initial_glow_blur=15 if not self._compact else (12 if not self._ultra_compact else 10),
            )
        else:
            self._value_label = QLabel(self._value_row)

        self._unit_label = QLabel(self._value_row)

        self._badge_label = QLabel(self._value_row)
        self._badge_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._trend_label = QLabel(self._value_row)
        self._trend_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        value_layout.addWidget(self._value_label, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        value_layout.addWidget(self._unit_label, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        value_layout.addStretch(1)
        value_layout.addWidget(self._badge_label, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        value_layout.addWidget(self._trend_label, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._summary_label = QLabel(self._content_root)
        self._summary_label.setWordWrap(True)
        self._summary_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        self._sparkline = _MiniSparkline(self._content_root)

        self._stat_row = QWidget(self._content_root)
        stat_layout = QHBoxLayout(self._stat_row)
        stat_layout.setContentsMargins(0, 0, 0, 0)
        stat_layout.setSpacing(7 if not self._compact else (5 if not self._ultra_compact else 4))

        self._latest_stat = self._make_stat_block("Latest")
        self._min_stat = self._make_stat_block("Min")
        self._max_stat = self._make_stat_block("Max")
        self._count_stat = self._make_stat_block("Count")

        stat_layout.addWidget(self._latest_stat["frame"])
        stat_layout.addWidget(self._min_stat["frame"])
        stat_layout.addWidget(self._max_stat["frame"])
        stat_layout.addWidget(self._count_stat["frame"])

        self._action_row = QWidget(self._content_root)
        action_layout = QHBoxLayout(self._action_row)
        action_layout.setContentsMargins(0, 2 if not self._compact else 0, 0, 0)
        action_layout.setSpacing(7 if not self._compact else (5 if not self._ultra_compact else 4))

        self._details_button = AnimatedButton(
            text=self._action_button_text,
            variant=AnimatedButton.VARIANT_PRIMARY,
            size=AnimatedButton.SIZE_MD if not self._compact else AnimatedButton.SIZE_SM,
            minimum_width=92 if not self._compact else (76 if not self._ultra_compact else 68),
        )

        action_layout.addWidget(self._details_button)
        action_layout.addStretch(1)

        root.addWidget(self._value_row)
        root.addWidget(self._summary_label)
        root.addWidget(self._sparkline)
        root.addWidget(self._stat_row)
        root.addWidget(self._action_row)

    def _make_stat_block(self, title: str) -> Dict[str, QWidget]:
        frame = QFrame(self._stat_row)
        frame.setObjectName("PublishStatCardStatBlock")
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(
            7 if not self._compact else (6 if not self._ultra_compact else 5),
            6 if not self._compact else (5 if not self._ultra_compact else 4),
            7 if not self._compact else (6 if not self._ultra_compact else 5),
            6 if not self._compact else (5 if not self._ultra_compact else 4),
        )
        layout.setSpacing(0)

        title_label = QLabel(title, frame)
        title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        value_label = QLabel("--", frame)
        value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(title_label)
        layout.addWidget(value_label)

        return {
            "frame": frame,
            "title": title_label,
            "value": value_label,
        }

    # ========================================================
    # Styling
    # ========================================================

    def _accent_for_state(self, state: str) -> str:
        state = safe_str(state, self.STATE_NEUTRAL).strip().lower()
        if state == self.STATE_SUCCESS:
            return self._theme.success_accent
        if state == self.STATE_HAS_DATA:
            return self._theme.primary_accent
        if state == self.STATE_WARNING:
            return self._theme.warning_accent
        if state == self.STATE_DANGER:
            return self._theme.danger_accent
        if state == self.STATE_EMPTY:
            return self._theme.empty_accent
        if state == self.STATE_PRIMARY:
            return self._theme.primary_accent
        return self._theme.neutral_accent

    def _trend_accent(self, trend: str) -> str:
        trend = safe_str(trend, self.TREND_NONE).strip().lower()
        if trend == self.TREND_UP:
            return self._theme.success_accent
        if trend == self.TREND_DOWN:
            return self._theme.danger_accent
        if trend == self.TREND_STABLE:
            return self._theme.primary_accent
        return self._theme.empty_accent

    def _chip_colors(self, accent_hex: str) -> tuple[str, str, str]:
        accent = QColor(accent_hex)
        bg = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, {self._theme.chip_bg_alpha:.3f})"
        border = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, {self._theme.chip_border_alpha:.3f})"
        return bg, border, self._theme.chip_text

    def _set_chip_style(self, label: QLabel, accent_hex: str) -> None:
        bg, border, text = self._chip_colors(accent_hex)
        label.setStyleSheet(
            f"""
            QLabel {{
                color: {text};
                font-size: {'10px' if not self._compact else ('9px' if not self._ultra_compact else '8px')};
                font-weight: 700;
                border: 1px solid {border};
                border-radius: {12 if not self._compact else (10 if not self._ultra_compact else 9)}px;
                background: {bg};
                padding: {4 if not self._compact else (3 if not self._ultra_compact else 2)}px {8 if not self._compact else (6 if not self._ultra_compact else 5)}px;
            }}
            """
        )

    def _apply_style(self) -> None:
        accent = self._accent_for_state(self._state)
        trend_accent = self._trend_accent(self._trend)

        self.set_accent_color(accent)

        if _HAS_GLOW_LABEL and isinstance(self._value_label, GlowLabel):
            try:
                self._value_label.set_glow_color(accent)
                self._value_label.set_text_color(self._theme.value_color)
                self._value_label.set_role(GlowLabel.ROLE_STATUS if not self._compact else GlowLabel.ROLE_SUBTITLE)
            except Exception:
                pass
        else:
            self._value_label.setStyleSheet(
                f"""
                QLabel {{
                    color: {self._theme.value_color};
                    font-size: {'24px' if not self._compact else ('19px' if not self._ultra_compact else '17px')};
                    font-weight: 800;
                    background: transparent;
                }}
                """
            )

        self._unit_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.unit_color};
                font-size: {'11px' if not self._compact else ('9px' if not self._ultra_compact else '8px')};
                font-weight: 600;
                background: transparent;
                padding-bottom: 3px;
            }}
            """
        )

        self._summary_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.body_color};
                font-size: {'10px' if not self._compact else ('9px' if not self._ultra_compact else '8px')};
                font-weight: 500;
                background: transparent;
            }}
            """
        )

        self._set_chip_style(self._badge_label, accent)
        self._set_chip_style(self._trend_label, trend_accent)

        self._sparkline.set_accent(accent)

        for stat in [self._latest_stat, self._min_stat, self._max_stat, self._count_stat]:
            stat["frame"].setStyleSheet(
                f"""
                QFrame#PublishStatCardStatBlock {{
                    border: 1px solid {self._theme.stat_block_border};
                    border-radius: {13 if not self._compact else (11 if not self._ultra_compact else 10)}px;
                    background: {self._theme.stat_block_bg};
                }}
                """
            )
            stat["title"].setStyleSheet(
                f"""
                QLabel {{
                    color: {self._theme.stat_label_color};
                    font-size: {'8px' if not self._compact else '8px'};
                    font-weight: 700;
                    background: transparent;
                }}
                """
            )
            stat["value"].setStyleSheet(
                f"""
                QLabel {{
                    color: {self._theme.stat_value_color};
                    font-size: {'12px' if not self._compact else ('10px' if not self._ultra_compact else '9px')};
                    font-weight: 800;
                    background: transparent;
                }}
                """
            )

        self._details_button.set_accent_color(accent)

    # ========================================================
    # Helpers
    # ========================================================

    def _format_value(self, value: Any, *, decimals: int = 1, fallback: str = "--") -> str:
        if value is None or value == "":
            return fallback

        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned if cleaned else fallback

        numeric = safe_float(value, 0.0)
        if abs(numeric - round(numeric)) < 1e-9:
            return str(int(round(numeric)))
        return f"{numeric:.{decimals}f}"

    def _trend_text(self, trend: str) -> str:
        trend = safe_str(trend, self.TREND_NONE).strip().lower()
        if trend == self.TREND_UP:
            return "▲ Up"
        if trend == self.TREND_DOWN:
            return "▼ Down"
        if trend == self.TREND_STABLE:
            return "● Stable"
        return ""

    def _derive_badge_from_state(self, state: str) -> str:
        state = safe_str(state, self.STATE_NEUTRAL).strip().lower()
        mapping = {
            self.STATE_PRIMARY: "Overview",
            self.STATE_SUCCESS: "Good",
            self.STATE_WARNING: "Watch",
            self.STATE_DANGER: "Alert",
            self.STATE_EMPTY: "No Data",
            self.STATE_HAS_DATA: "Metric",
            self.STATE_NEUTRAL: "Info",
        }
        return mapping.get(state, "Info")

    def _refresh_visibility(self) -> None:
        narrow = self.width() > 0 and self.width() <= 250
        self._unit_label.setVisible(bool(self._unit.strip()))
        self._badge_label.setVisible(bool(self._badge_label.text().strip()) and not (self._ultra_compact and narrow))
        self._trend_label.setVisible(bool(self._trend_label.text().strip()) and not (self._ultra_compact and narrow))
        self._summary_label.setVisible(bool(self._summary_text.strip()) and not (self._ultra_compact and self.height() <= 165))
        self._sparkline.setVisible(self._show_sparkline and len(self._sparkline._points) >= 2 and not (self._ultra_compact and self.height() <= 160))
        self._stat_row.setVisible(self._show_stat_row and not (self._ultra_compact and narrow and self.height() <= 170))
        self._action_row.setVisible(self._show_action_row)
        if self._ultra_compact and self._action_button_text.strip().lower() == 'details':
            self._details_button.setText('Info')
        else:
            self._details_button.setText(self._action_button_text)

    def _sync_compact_mode(self, force: bool = False) -> None:
        width = self.width() if self.width() > 0 else KIOSK_WIDTH
        compact_now = bool(self._compact or IS_COMPACT_KIOSK or width <= 900)
        ultra_now = bool(KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480 or width <= 240)
        changed = force or compact_now != self._compact or ultra_now != self._ultra_compact
        self._compact = compact_now
        self._ultra_compact = ultra_now
        self._sparkline.set_compact(self._compact)
        if changed:
            try:
                self._details_button.setMinimumWidth(92 if not self._compact else (76 if not self._ultra_compact else 68))
            except Exception:
                pass
            self._apply_style()
            self._refresh_visibility()
            self.updateGeometry()
            self.update()

    def set_compact(self, compact: bool) -> None:
        self._compact = bool(compact)
        self._sync_compact_mode(force=True)

    def compact(self) -> bool:
        return self._compact

    def resizeEvent(self, event) -> None:
        try:
            super().resizeEvent(event)
        finally:
            self._sync_compact_mode(force=False)

    # ========================================================
    # Public setters/getters
    # ========================================================

    def set_state(self, state: str) -> None:
        normalized = safe_str(state, self.STATE_NEUTRAL).strip().lower() or self.STATE_NEUTRAL
        if normalized not in {
            self.STATE_NEUTRAL,
            self.STATE_PRIMARY,
            self.STATE_SUCCESS,
            self.STATE_WARNING,
            self.STATE_DANGER,
            self.STATE_EMPTY,
            self.STATE_HAS_DATA,
        }:
            normalized = self.STATE_NEUTRAL

        self._state = normalized
        if not self._badge_text.strip():
            derived = self._derive_badge_from_state(self._state)
            self._badge_text = derived
            self._badge_label.setText(derived)

        self._apply_style()
        self._refresh_visibility()
        self.state_changed.emit(self._state)

    def state(self) -> str:
        return self._state

    def set_value(self, value: Any, *, flash: bool = False) -> None:
        self._raw_value = value
        self._value_text = self._format_value(value)

        if _HAS_GLOW_LABEL and isinstance(self._value_label, GlowLabel):
            try:
                self._value_label.set_text(self._value_text)
                if flash and hasattr(self._value_label, "flash_once"):
                    self._value_label.flash_once(duration_ms=620, peak_strength=1.0, end_strength=0.42)
            except Exception:
                self._value_label.setText(self._value_text)
        else:
            self._value_label.setText(self._value_text)

    def value(self) -> Any:
        return self._raw_value

    def set_unit(self, unit: str) -> None:
        self._unit = safe_str(unit, "").strip()
        self._unit_label.setText(self._unit)
        self._refresh_visibility()

    def unit(self) -> str:
        return self._unit

    def set_summary_text(self, text: str) -> None:
        self._summary_text = safe_str(text, "").strip()
        self._summary_label.setText(self._summary_text)
        self._refresh_visibility()

    def summary_text(self) -> str:
        return self._summary_text

    def set_badge_text(self, text: str) -> None:
        self._badge_text = safe_str(text, "").strip()
        self._badge_label.setText(self._badge_text)
        self._refresh_visibility()

    def badge_text(self) -> str:
        return self._badge_text

    def set_trend(self, trend: str) -> None:
        normalized = safe_str(trend, self.TREND_NONE).strip().lower() or self.TREND_NONE
        if normalized not in {self.TREND_UP, self.TREND_DOWN, self.TREND_STABLE, self.TREND_NONE}:
            normalized = self.TREND_NONE

        self._trend = normalized
        self._trend_label.setText(self._trend_text(normalized))
        self._apply_style()
        self._refresh_visibility()
        self.trend_changed.emit(self._trend)

    def trend(self) -> str:
        return self._trend

    def set_action_button_text(self, text: str) -> None:
        self._action_button_text = safe_str(text, "Details").strip() or "Details"
        self._details_button.setText(self._action_button_text)

    def set_show_sparkline(self, visible: bool) -> None:
        self._show_sparkline = bool(visible)
        self._refresh_visibility()

    def set_show_stat_row(self, visible: bool) -> None:
        self._show_stat_row = bool(visible)
        self._refresh_visibility()

    def set_show_action_row(self, visible: bool) -> None:
        self._show_action_row = bool(visible)
        self._refresh_visibility()

    def set_sparkline_points(self, points: Iterable[float]) -> None:
        self._sparkline.set_points(points)
        self._refresh_visibility()

    def set_latest_value(self, value: Any) -> None:
        self._latest_value = value
        self._latest_stat["value"].setText(self._format_value(value))

    def set_min_value(self, value: Any) -> None:
        self._min_value = value
        self._min_stat["value"].setText(self._format_value(value))

    def set_max_value(self, value: Any) -> None:
        self._max_value = value
        self._max_stat["value"].setText(self._format_value(value))

    def set_count_value(self, value: Any) -> None:
        self._count_value = value
        self._count_stat["value"].setText(self._format_value(value, decimals=0))

    def set_meta_stats(
        self,
        *,
        latest: Any = None,
        min_value: Any = None,
        max_value: Any = None,
        count: Any = None,
    ) -> None:
        self.set_latest_value(latest)
        self.set_min_value(min_value)
        self.set_max_value(max_value)
        self.set_count_value(count)

    # ========================================================
    # Payload integration
    # ========================================================

    def apply_publish_card_payload(self, payload: Mapping[str, Any]) -> None:
        """
        Apply a generic publish overview/metric card payload from PublishService.
        """
        data = dict(payload or {})

        title = safe_str(data.get("title"), "").strip()
        subtitle = safe_str(data.get("subtitle"), "").strip()
        value = data.get("value")
        unit = safe_str(data.get("unit"), "").strip()
        trend = safe_str(data.get("trend"), self.TREND_NONE).strip().lower()
        state = safe_str(data.get("state"), self.STATE_NEUTRAL).strip().lower()

        if title:
            self.set_title(title)
        self.set_summary_text(subtitle)
        self.set_value(value, flash=False)
        self.set_unit(unit)

        if state == "info":
            state = self.STATE_PRIMARY
        elif state == "empty":
            state = self.STATE_EMPTY
        elif state == "has_data":
            state = self.STATE_HAS_DATA
        elif state not in {
            self.STATE_NEUTRAL,
            self.STATE_PRIMARY,
            self.STATE_SUCCESS,
            self.STATE_WARNING,
            self.STATE_DANGER,
            self.STATE_EMPTY,
            self.STATE_HAS_DATA,
        }:
            state = self.STATE_NEUTRAL

        self.set_state(state)
        self.set_trend(trend)

        badge = safe_str(data.get("badge_text"), "").strip()
        if badge:
            self.set_badge_text(badge)
        else:
            if state == self.STATE_HAS_DATA:
                self.set_badge_text("Metric")
            elif self.badge_text() in {"", "Info"}:
                self.set_badge_text(self._derive_badge_from_state(state))

        self.set_meta_stats(
            latest=data.get("latest"),
            min_value=data.get("min"),
            max_value=data.get("max"),
            count=data.get("count"),
        )

        points = data.get("points")
        if isinstance(points, list):
            numeric_points: List[float] = []
            for item in points:
                if isinstance(item, Mapping):
                    try:
                        numeric_points.append(float(item.get("value")))
                    except Exception:
                        continue
                else:
                    try:
                        numeric_points.append(float(item))
                    except Exception:
                        continue
            self.set_sparkline_points(numeric_points)

        self.payload_applied.emit(dict(data))

    def apply_metric_statistics_payload(self, payload: Mapping[str, Any]) -> None:
        """
        Apply a detailed metric-statistics payload from PublishService.metric_statistics.
        """
        data = dict(payload or {})

        title = safe_str(
            data.get("metric_label"),
            safe_str(data.get("title"), self.title()),
        ).strip()

        subtitle = safe_str(data.get("subtitle"), "").strip()
        if not subtitle:
            count_value = safe_int(data.get("count"), 0)
            subtitle = f"{count_value} data points" if count_value > 0 else "No recorded points"

        avg_value = data.get("avg")
        latest = data.get("latest")
        min_value = data.get("min")
        max_value = data.get("max")
        count_value = data.get("count")
        unit = safe_str(data.get("unit"), "").strip()
        trend = safe_str(data.get("trend"), self.TREND_NONE).strip().lower()
        has_data = bool(data.get("has_data", False))
        points = data.get("points", [])

        self.set_title(title)
        self.set_summary_text(subtitle)
        self.set_value(avg_value, flash=False)
        self.set_unit(unit)
        self.set_trend(trend)
        self.set_state(self.STATE_HAS_DATA if has_data else self.STATE_EMPTY)
        self.set_badge_text("Average")

        self.set_meta_stats(
            latest=latest,
            min_value=min_value,
            max_value=max_value,
            count=count_value,
        )

        if isinstance(points, list):
            numeric_points = [
                safe_float(item.get("value"), 0.0)
                for item in points
                if isinstance(item, Mapping)
            ]
            self.set_sparkline_points(numeric_points)

        self.payload_applied.emit(dict(data))

    # ========================================================
    # Click forwarding
    # ========================================================

    def _on_card_clicked(self) -> None:
        self.card_clicked.emit()
        self.details_requested.emit()

    # ========================================================
    # Diagnostics
    # ========================================================

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "title": self.title(),
            "value": self._raw_value,
            "value_text": self._value_text,
            "unit": self._unit,
            "summary_text": self._summary_text,
            "badge_text": self.badge_text(),
            "trend": self._trend,
            "state": self._state,
            "latest_value": self._latest_value,
            "min_value": self._min_value,
            "max_value": self._max_value,
            "count_value": self._count_value,
            "sparkline_points": len(self._sparkline._points),
            "show_sparkline": self._show_sparkline,
            "show_stat_row": self._show_stat_row,
            "show_action_row": self._show_action_row,
            "compact": self._compact,
            "ultra_compact": self._ultra_compact,
        }
