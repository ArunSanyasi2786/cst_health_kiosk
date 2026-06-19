"""
widgets/highlight_range_box.py

Premium highlighted range/legend widget for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the reusable range-interpretation widget used inside metric detail screens
- It is designed for:
    - BMI category ranges
    - temperature range bands
    - SpO₂ interpretation ranges
    - pulse-rate interpretation ranges
    - respiratory-rate interpretation ranges
    - any future parameter that needs a highlighted classification legend
- It supports:
    - multiple range rows with labels and descriptions
    - automatic active-range highlighting from a current live value
    - current-value display chip
    - severity-aware colors
    - compact and full layouts
    - direct payload application from services or screen-level code

Linked files:
- core/constants.py
- core/utils.py
- widgets/glow_label.py
- screens/bmi_detail_screen.py
- screens/temperature_detail_screen.py
- screens/spo2_detail_screen.py
- screens/pulse_detail_screen.py
- screens/rr_detail_screen.py

Design goals:
- premium futuristic blue/cyan medical look
- clear at-a-glance explanation of where the current value falls
- lightweight enough for Raspberry Pi kiosk deployment
- reusable inside multiple detail screens without duplicating range UI logic
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional

from PyQt6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.logger import get_logger

try:
    from config import IS_COMPACT_KIOSK, KIOSK_HEIGHT, KIOSK_WIDTH
except Exception:  # pragma: no cover
    KIOSK_WIDTH = 800
    KIOSK_HEIGHT = 480
    IS_COMPACT_KIOSK = KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480

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
        SEVERITY_ATTENTION,
        SEVERITY_CRITICAL,
        SEVERITY_NORMAL,
        SEVERITY_UNKNOWN,
        SEVERITY_WARNING,
    )
except Exception:  # pragma: no cover
    SEVERITY_NORMAL = "normal"
    SEVERITY_ATTENTION = "attention"
    SEVERITY_WARNING = "warning"
    SEVERITY_CRITICAL = "critical"
    SEVERITY_UNKNOWN = "unknown"

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
class HighlightRangeTheme:
    """
    Theme container for HighlightRangeBox.
    """
    shell_top: str = "rgba(14, 33, 60, 0.86)"
    shell_bottom: str = "rgba(9, 22, 42, 0.90)"
    shell_hover_top: str = "rgba(20, 42, 74, 0.90)"
    shell_hover_bottom: str = "rgba(10, 27, 51, 0.94)"
    border_color: str = "rgba(151, 217, 255, 0.22)"
    border_hover: str = "rgba(181, 231, 255, 0.38)"
    inner_gloss: str = "rgba(255, 255, 255, 0.05)"

    title_color: str = "#F5FCFF"
    subtitle_color: str = "rgba(208, 231, 247, 0.82)"
    summary_color: str = "rgba(220, 239, 250, 0.90)"
    subtle_text: str = "rgba(187, 212, 231, 0.82)"
    value_color: str = "#F8FDFF"
    value_unit_color: str = "rgba(204, 226, 242, 0.84)"

    normal_accent: str = "#3FE28F"
    attention_accent: str = "#FFD25E"
    warning_accent: str = "#FFA14D"
    critical_accent: str = "#FF6F89"
    neutral_accent: str = "#7FD2FF"

    chip_text: str = "#F4FCFF"
    chip_bg_alpha: float = 0.16
    chip_border_alpha: float = 0.36

    row_bg: str = "rgba(28, 48, 78, 0.18)"
    row_border: str = "rgba(151, 216, 255, 0.14)"
    row_hover_bg: str = "rgba(35, 59, 92, 0.22)"
    row_active_overlay_alpha: float = 0.16

    shadow_hex: str = "#35D6FF"


DEFAULT_HIGHLIGHT_RANGE_THEME = HighlightRangeTheme()


# ============================================================
# Range model
# ============================================================

@dataclass
class RangeDefinition:
    """
    Internal normalized range definition.
    """
    label: str
    minimum: Optional[float]
    maximum: Optional[float]
    severity: str
    description: str = ""
    short_label: str = ""
    inclusive_min: bool = True
    inclusive_max: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================
# Internal row widget
# ============================================================

class _RangeItem(QFrame):
    """
    One visual row inside HighlightRangeBox.
    """

    clicked = pyqtSignal(dict)

    def __init__(
        self,
        range_definition: RangeDefinition,
        parent: Optional[QWidget] = None,
        *,
        compact: bool = False,
        ultra_compact: bool = False,
        clickable: bool = False,
        theme: HighlightRangeTheme = DEFAULT_HIGHLIGHT_RANGE_THEME,
    ) -> None:
        super().__init__(parent)

        self._range = range_definition
        self._compact = bool(compact or IS_COMPACT_KIOSK)
        self._ultra_compact = bool(KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480)
        self._ultra_compact = bool(ultra_compact)
        self._clickable = bool(clickable)
        self._theme = theme

        self._hovered = False
        self._active = False
        self._overlay_brush_color = QColor(0, 0, 0, 0)

        self.setObjectName("HighlightRangeRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor if self._clickable else Qt.CursorShape.ArrowCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._build_ui()
        self._apply_style()

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        if self._ultra_compact:
            root.setContentsMargins(7, 5, 7, 5)
            root.setSpacing(6)
        else:
            root.setContentsMargins(10 if not self._compact else 8, 8 if not self._compact else 6, 10 if not self._compact else 8, 8 if not self._compact else 6)
            root.setSpacing(10 if not self._compact else 7)

        self._accent_dot = QLabel(self)
        self._accent_dot.setFixedSize(7 if self._ultra_compact else (10 if not self._compact else 8), 7 if self._ultra_compact else (10 if not self._compact else 8))

        text_column = QWidget(self)
        text_layout = QVBoxLayout(text_column)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0 if self._ultra_compact else (2 if not self._compact else 1))

        self._label = QLabel(self._range.label, text_column)
        self._label.setWordWrap(True)

        self._description = QLabel(self._range.description, text_column)
        self._description.setWordWrap(True)

        text_layout.addWidget(self._label)
        text_layout.addWidget(self._description)

        right_column = QWidget(self)
        right_layout = QVBoxLayout(right_column)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0 if self._ultra_compact else (2 if not self._compact else 1))

        self._interval = QLabel("", right_column)
        self._interval.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._badge = QLabel("", right_column)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        right_layout.addWidget(self._interval)
        right_layout.addWidget(self._badge)

        root.addWidget(self._accent_dot, 0, alignment=Qt.AlignmentFlag.AlignTop)
        root.addWidget(text_column, 1)
        root.addWidget(right_column, 0)

    def range_definition(self) -> RangeDefinition:
        return self._range

    def set_range_definition(self, definition: RangeDefinition) -> None:
        self._range = definition
        self._label.setText(definition.label)
        self._description.setText(definition.description)
        self._apply_style()

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self._apply_style()
        self.update()

    def is_active(self) -> bool:
        return self._active

    def set_compact(self, compact: bool, ultra_compact: bool = False) -> None:
        self._compact = bool(compact)
        self._ultra_compact = bool(ultra_compact)
        self._accent_dot.setFixedSize(7 if self._ultra_compact else (8 if self._compact else 10), 7 if self._ultra_compact else (8 if self._compact else 10))
        layout = self.layout()
        if isinstance(layout, QHBoxLayout):
            if self._ultra_compact:
                layout.setContentsMargins(7, 5, 7, 5)
                layout.setSpacing(6)
            elif self._compact:
                layout.setContentsMargins(8, 6, 8, 6)
                layout.setSpacing(7)
            else:
                layout.setContentsMargins(10, 8, 10, 8)
                layout.setSpacing(10)
        self._apply_style()

    def set_clickable(self, clickable: bool) -> None:
        self._clickable = bool(clickable)
        self.setCursor(Qt.CursorShape.PointingHandCursor if self._clickable else Qt.CursorShape.ArrowCursor)

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
        return self._theme.neutral_accent

    def _chip_colors(self, accent_hex: str) -> tuple[str, str, str]:
        accent = QColor(accent_hex)
        bg = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, {self._theme.chip_bg_alpha:.3f})"
        border = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, {self._theme.chip_border_alpha:.3f})"
        return bg, border, self._theme.chip_text

    def _interval_text(self) -> str:
        lo = self._range.minimum
        hi = self._range.maximum

        if lo is None and hi is None:
            return "Any"
        if lo is None:
            op = "≤" if self._range.inclusive_max else "<"
            return f"{op} {self._format_num(hi)}"
        if hi is None:
            op = "≥" if self._range.inclusive_min else ">"
            return f"{op} {self._format_num(lo)}"

        left = "[" if self._range.inclusive_min else "("
        right = "]" if self._range.inclusive_max else ")"
        return f"{left}{self._format_num(lo)} – {self._format_num(hi)}{right}"

    def _format_num(self, value: Optional[float]) -> str:
        if value is None:
            return "--"
        if abs(value - round(value)) < 1e-9:
            return str(int(round(value)))
        return f"{value:.1f}"

    def _badge_text(self) -> str:
        if self._range.short_label.strip():
            return self._range.short_label.strip()
        severity = safe_str(self._range.severity, SEVERITY_UNKNOWN).strip().lower()
        mapping = {
            SEVERITY_NORMAL: "Normal",
            SEVERITY_ATTENTION: "Attention",
            SEVERITY_WARNING: "Warning",
            SEVERITY_CRITICAL: "Critical",
            SEVERITY_UNKNOWN: "Range",
        }
        return mapping.get(severity, "Range")

    def _rgba(self, color_hex: str, alpha: float) -> str:
        c = QColor(color_hex)
        alpha = max(0.0, min(float(alpha), 1.0))
        return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha:.3f})"

    def _apply_style(self) -> None:
        accent = self._accent_for_severity(self._range.severity)
        bg, border, chip_text = self._chip_colors(accent)

        overlay_alpha = self._theme.row_active_overlay_alpha if self._active else 0.0
        overlay = self._rgba(accent, overlay_alpha)

        if self._hovered and not self._active:
            row_bg = self._theme.row_hover_bg
            row_border = self._theme.border_hover
        else:
            row_bg = self._theme.row_bg
            row_border = self._theme.row_border

        self.setStyleSheet(
            f"""
            QFrame#HighlightRangeRow {{
                border: 1px solid {row_border};
                border-radius: {11 if self._ultra_compact else (16 if not self._compact else 13)}px;
                background: {row_bg};
            }}
            """
        )

        dot_color = QColor(accent)
        dot_radius = self._accent_dot.width() // 2
        self._accent_dot.setStyleSheet(
            f"""
            QLabel {{
                min-width: {self._accent_dot.width()}px;
                min-height: {self._accent_dot.height()}px;
                max-width: {self._accent_dot.width()}px;
                max-height: {self._accent_dot.height()}px;
                border-radius: {dot_radius}px;
                background: rgba({dot_color.red()}, {dot_color.green()}, {dot_color.blue()}, {0.95 if self._active else 0.80});
                border: 1px solid rgba(255,255,255,0.18);
            }}
            """
        )

        self._label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.title_color};
                font-size: {'9px' if self._ultra_compact else ('11px' if not self._compact else '10px')};
                font-weight: {800 if self._active else 700};
                background: transparent;
            }}
            """
        )
        self._description.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.subtitle_color};
                font-size: {'7px' if self._ultra_compact else ('9px' if not self._compact else '8px')};
                font-weight: 500;
                background: transparent;
            }}
            """
        )
        self._description.setVisible((not self._ultra_compact) and bool(self._range.description.strip()))

        self._interval.setText(self._interval_text())
        self._interval.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.summary_color};
                font-size: {'7px' if self._ultra_compact else ('9px' if not self._compact else '8px')};
                font-weight: 700;
                background: transparent;
            }}
            """
        )

        self._badge.setText(self._badge_text())
        self._badge.setStyleSheet(
            f"""
            QLabel {{
                color: {chip_text};
                font-size: {'7px' if self._ultra_compact else ('8px' if not self._compact else '8px')};
                font-weight: 700;
                border: 1px solid {border};
                border-radius: {8 if self._ultra_compact else (10 if not self._compact else 9)}px;
                background: {bg};
                padding: {2 if self._ultra_compact else (3 if not self._compact else 2)}px {4 if self._ultra_compact else (6 if not self._compact else 5)}px;
            }}
            """
        )

        self._badge.setVisible(not self._ultra_compact)
        self._overlay_brush_color = QColor(overlay)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_compact_mode()

    def enterEvent(self, event: QEvent) -> None:
        super().enterEvent(event)
        self._hovered = True
        self._apply_style()

    def leaveEvent(self, event: QEvent) -> None:
        super().leaveEvent(event)
        self._hovered = False
        self._apply_style()

    def mouseReleaseEvent(self, event: Optional[QMouseEvent]) -> None:
        super().mouseReleaseEvent(event)
        if self._clickable and event is not None and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._range.to_dict())

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        if not self._active:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = self.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 16 if not self._compact else 13, 16 if not self._compact else 13)

        painter.fillPath(path, self._overlay_brush_color)
        painter.end()


# ============================================================
# Main widget
# ============================================================

class HighlightRangeBox(QFrame):
    """
    Premium reusable highlighted range box.

    Main features:
    - header with title/subtitle/current value
    - list of multiple ranges
    - automatic current-value matching
    - active-range summary text
    - payload-based updates
    """

    current_value_changed = pyqtSignal(object)
    active_range_changed = pyqtSignal(dict)
    range_clicked = pyqtSignal(dict)
    payload_applied = pyqtSignal(dict)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        title: str = "",
        subtitle: str = "",
        unit: str = "",
        compact: bool = False,
        clickable_ranges: bool = False,
        show_header: bool = True,
        show_current_value: bool = True,
        show_summary: bool = True,
        theme: Optional[HighlightRangeTheme] = None,
        minimum_height: int = 150,
    ) -> None:
        super().__init__(parent)

        self._logger = logger.bind(component="HighlightRangeBox")
        self._theme = theme or DEFAULT_HIGHLIGHT_RANGE_THEME
        self._compact = bool(compact)
        self._clickable_ranges = bool(clickable_ranges)
        self._show_header = bool(show_header)
        self._show_current_value = bool(show_current_value)
        self._show_summary = bool(show_summary)

        self._title = safe_str(title, "").strip()
        self._subtitle = safe_str(subtitle, "").strip()
        self._unit = safe_str(unit, "").strip()
        self._current_value: Any = None
        self._active_index: int = -1
        self._ranges: List[RangeDefinition] = []

        self._hovered = False
        self._base_pos: Optional[QPoint] = None
        self._hover_anim: Optional[QPropertyAnimation] = None
        self._shadow_effect: Optional[QGraphicsDropShadowEffect] = None

        self.setObjectName("HighlightRangeBox")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        min_h = max(96 if self._ultra_compact else (108 if self._compact else 120), int(minimum_height * (0.82 if self._ultra_compact else (0.9 if self._compact else 1.0))))
        self.setMinimumHeight(min_h)

        self._build_ui()
        self._apply_shadow()
        self._apply_style()
        self.set_title(self._title)
        self.set_subtitle(self._subtitle)
        self.set_unit(self._unit)
        self.set_current_value(None, emit_signal=False)

    # ========================================================
    # UI
    # ========================================================

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        if self._ultra_compact:
            root.setContentsMargins(8, 7, 8, 7)
            root.setSpacing(5)
        else:
            root.setContentsMargins(12 if not self._compact else 10, 10 if not self._compact else 8, 12 if not self._compact else 10, 10 if not self._compact else 8)
            root.setSpacing(8 if not self._compact else 6)

        self._header = QWidget(self)
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(5 if self._ultra_compact else (8 if not self._compact else 6))

        text_column = QWidget(self._header)
        text_layout = QVBoxLayout(text_column)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)

        self._title_label = QLabel(text_column)
        self._title_label.setWordWrap(True)

        self._subtitle_label = QLabel(text_column)
        self._subtitle_label.setWordWrap(True)

        text_layout.addWidget(self._title_label)
        text_layout.addWidget(self._subtitle_label)

        value_column = QWidget(self._header)
        value_layout = QVBoxLayout(value_column)
        value_layout.setContentsMargins(0, 0, 0, 0)
        value_layout.setSpacing(1)

        self._current_caption = QLabel("Current", value_column)
        self._current_caption.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        current_row = QWidget(value_column)
        current_row_layout = QHBoxLayout(current_row)
        current_row_layout.setContentsMargins(0, 0, 0, 0)
        current_row_layout.setSpacing(2 if self._ultra_compact else (4 if not self._compact else 3))

        if _HAS_GLOW_LABEL:
            self._current_value_label = GlowLabel(
                role=GlowLabel.ROLE_STATUS if not self._compact else GlowLabel.ROLE_SUBTITLE,
                align_center=False,
                use_outline=False,
                enable_paint_glow=True,
                initial_glow_strength=0.40,
                initial_glow_blur=14 if not self._compact else 12,
            )
        else:
            self._current_value_label = QLabel(current_row)

        self._current_unit_label = QLabel(current_row)

        current_row_layout.addWidget(self._current_value_label, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        current_row_layout.addWidget(self._current_unit_label, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)

        value_layout.addWidget(self._current_caption)
        value_layout.addWidget(current_row)

        header_layout.addWidget(text_column, 1)
        header_layout.addWidget(value_column, 0)

        self._range_list = QWidget(self)
        self._range_layout = QVBoxLayout(self._range_list)
        self._range_layout.setContentsMargins(0, 0, 0, 0)
        self._range_layout.setSpacing(3 if self._ultra_compact else (6 if not self._compact else 4))

        self._summary_strip = QFrame(self)
        self._summary_strip.setObjectName("HighlightRangeSummaryStrip")

        summary_layout = QHBoxLayout(self._summary_strip)
        if self._ultra_compact:
            summary_layout.setContentsMargins(6, 4, 6, 4)
            summary_layout.setSpacing(4)
        else:
            summary_layout.setContentsMargins(9 if not self._compact else 7, 6 if not self._compact else 5, 9 if not self._compact else 7, 6 if not self._compact else 5)
            summary_layout.setSpacing(7 if not self._compact else 5)

        self._summary_dot = QLabel(self._summary_strip)
        self._summary_dot.setFixedSize(7 if self._ultra_compact else (10 if not self._compact else 8), 7 if self._ultra_compact else (10 if not self._compact else 8))

        self._summary_label = QLabel(self._summary_strip)
        self._summary_label.setWordWrap(True)

        summary_layout.addWidget(self._summary_dot, 0, alignment=Qt.AlignmentFlag.AlignTop)
        summary_layout.addWidget(self._summary_label, 1)

        root.addWidget(self._header)
        root.addWidget(self._range_list)
        root.addWidget(self._summary_strip)

    # ========================================================
    # Styling
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
        return self._theme.neutral_accent

    def _apply_shadow(self) -> None:
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(14 if self._ultra_compact else (24 if not self._compact else 18))
        shadow.setOffset(0, 3 if self._ultra_compact else (6 if not self._compact else 4))

        color = QColor(self._theme.shadow_hex)
        color.setAlpha(60)
        shadow.setColor(color)

        self.setGraphicsEffect(shadow)
        self._shadow_effect = shadow

    def _active_accent_hex(self) -> str:
        active = self.active_range_definition()
        if active is None:
            return self._theme.neutral_accent
        return self._accent_for_severity(active.severity)

    def _apply_style(self) -> None:
        bg_top = self._theme.shell_hover_top if self._hovered else self._theme.shell_top
        bg_bottom = self._theme.shell_hover_bottom if self._hovered else self._theme.shell_bottom
        border = self._theme.border_hover if self._hovered else self._theme.border_color
        radius = 15 if self._ultra_compact else (22 if not self._compact else 18)

        self.setStyleSheet(
            f"""
            QFrame#HighlightRangeBox {{
                border: 1px solid {border};
                border-radius: {radius}px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 {bg_top},
                    stop:1 {bg_bottom}
                );
            }}

            QFrame#HighlightRangeSummaryStrip {{
                border: 1px solid rgba(153, 216, 255, 0.18);
                border-radius: {10 if self._ultra_compact else (14 if not self._compact else 12)}px;
                background: rgba(38, 65, 98, 0.16);
            }}
            """
        )

        self._title_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.title_color};
                font-size: {'10px' if self._ultra_compact else ('13px' if not self._compact else '11px')};
                font-weight: 800;
                background: transparent;
            }}
            """
        )
        self._subtitle_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.subtitle_color};
                font-size: {'8px' if self._ultra_compact else ('10px' if not self._compact else '9px')};
                font-weight: 500;
                background: transparent;
            }}
            """
        )

        self._current_caption.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.subtle_text};
                font-size: {'7px' if self._ultra_compact else ('9px' if not self._compact else '8px')};
                font-weight: 700;
                background: transparent;
            }}
            """
        )

        current_accent = self._active_accent_hex()
        if _HAS_GLOW_LABEL and isinstance(self._current_value_label, GlowLabel):
            try:
                self._current_value_label.set_glow_color(current_accent)
                self._current_value_label.set_text_color(self._theme.value_color)
                self._current_value_label.set_role(GlowLabel.ROLE_SUBTITLE if self._ultra_compact else (GlowLabel.ROLE_STATUS if not self._compact else GlowLabel.ROLE_SUBTITLE))
            except Exception:
                pass
        else:
            self._current_value_label.setStyleSheet(
                f"""
                QLabel {{
                    color: {self._theme.value_color};
                    font-size: {'13px' if self._ultra_compact else ('19px' if not self._compact else '15px')};
                    font-weight: 800;
                    background: transparent;
                }}
                """
            )

        self._current_unit_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.value_unit_color};
                font-size: {'8px' if self._ultra_compact else ('10px' if not self._compact else '9px')};
                font-weight: 600;
                background: transparent;
                padding-bottom: 2px;
            }}
            """
        )

        self._summary_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.summary_color};
                font-size: {'8px' if self._ultra_compact else ('10px' if not self._compact else '9px')};
                font-weight: 600;
                background: transparent;
            }}
            """
        )

        dot_color = QColor(current_accent)
        dot_radius = self._summary_dot.width() // 2
        self._summary_dot.setStyleSheet(
            f"""
            QLabel {{
                min-width: {self._summary_dot.width()}px;
                min-height: {self._summary_dot.height()}px;
                max-width: {self._summary_dot.width()}px;
                max-height: {self._summary_dot.height()}px;
                border-radius: {dot_radius}px;
                background: rgba({dot_color.red()}, {dot_color.green()}, {dot_color.blue()}, 0.92);
                border: 1px solid rgba(255,255,255,0.18);
            }}
            """
        )

        if self._shadow_effect is not None:
            shadow_color = QColor(current_accent)
            shadow_color.setAlpha(72 if self._hovered else 56)
            self._shadow_effect.setColor(shadow_color)
            self._shadow_effect.setBlurRadius((18 if self._hovered else 14) if self._ultra_compact else (28 if self._hovered else 24))

    # ========================================================
    # Value / formatting helpers
    # ========================================================

    def _format_value(self, value: Any) -> str:
        if value is None or value == "":
            return "--"
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or "--"

        numeric = safe_float(value, 0.0)
        if abs(numeric - round(numeric)) < 1e-9:
            return str(int(round(numeric)))
        return f"{numeric:.1f}"

    def _coerce_range(self, item: Any) -> Optional[RangeDefinition]:
        if isinstance(item, RangeDefinition):
            return item

        if not isinstance(item, Mapping):
            return None

        label = safe_str(item.get("label"), "").strip()
        if not label:
            return None

        raw_min = item.get("minimum", item.get("min"))
        raw_max = item.get("maximum", item.get("max"))

        minimum = None if raw_min in (None, "") else safe_float(raw_min, 0.0)
        maximum = None if raw_max in (None, "") else safe_float(raw_max, 0.0)

        return RangeDefinition(
            label=label,
            minimum=minimum,
            maximum=maximum,
            severity=safe_str(item.get("severity"), SEVERITY_UNKNOWN).strip().lower() or SEVERITY_UNKNOWN,
            description=safe_str(item.get("description"), item.get("summary", "")).strip(),
            short_label=safe_str(item.get("short_label"), item.get("badge", "")).strip(),
            inclusive_min=bool(item.get("inclusive_min", True)),
            inclusive_max=bool(item.get("inclusive_max", False)),
        )

    def _value_matches_range(self, value: float, definition: RangeDefinition) -> bool:
        if definition.minimum is not None:
            if definition.inclusive_min:
                if value < definition.minimum:
                    return False
            else:
                if value <= definition.minimum:
                    return False

        if definition.maximum is not None:
            if definition.inclusive_max:
                if value > definition.maximum:
                    return False
            else:
                if value >= definition.maximum:
                    return False

        return True

    def _find_active_index(self, value: Any) -> int:
        if value in (None, ""):
            return -1

        numeric = safe_float(value, float("nan"))
        if numeric != numeric:
            return -1

        for idx, definition in enumerate(self._ranges):
            if self._value_matches_range(numeric, definition):
                return idx
        return -1

    # ========================================================
    # Public setters / getters
    # ========================================================

    def set_title(self, title: str) -> None:
        self._title = safe_str(title, "").strip()
        self._title_label.setText(self._title)
        self._refresh_visibility()

    def title(self) -> str:
        return self._title

    def set_subtitle(self, subtitle: str) -> None:
        self._subtitle = safe_str(subtitle, "").strip()
        self._subtitle_label.setText(self._subtitle)
        self._refresh_visibility()

    def subtitle(self) -> str:
        return self._subtitle

    def set_unit(self, unit: str) -> None:
        self._unit = safe_str(unit, "").strip()
        self._current_unit_label.setText(self._unit)
        self._refresh_visibility()

    def unit(self) -> str:
        return self._unit

    def set_current_value(self, value: Any, *, emit_signal: bool = True, auto_highlight: bool = True) -> None:
        self._current_value = value
        display = self._format_value(value)

        if _HAS_GLOW_LABEL and isinstance(self._current_value_label, GlowLabel):
            try:
                self._current_value_label.set_text(display)
            except Exception:
                self._current_value_label.setText(display)
        else:
            self._current_value_label.setText(display)

        if auto_highlight:
            self.set_active_index(self._find_active_index(value), emit_signal=emit_signal)
        else:
            self._update_summary_text()

        self._apply_style()
        self._refresh_visibility()

        if emit_signal:
            self.current_value_changed.emit(value)

    def current_value(self) -> Any:
        return self._current_value

    def ranges(self) -> List[Dict[str, Any]]:
        return [item.to_dict() for item in self._ranges]

    def active_index(self) -> int:
        return self._active_index

    def active_range_definition(self) -> Optional[RangeDefinition]:
        if 0 <= self._active_index < len(self._ranges):
            return self._ranges[self._active_index]
        return None

    def set_ranges(self, ranges: Iterable[Any]) -> None:
        self.clear_ranges()

        normalized: List[RangeDefinition] = []
        for item in ranges:
            definition = self._coerce_range(item)
            if definition is not None:
                normalized.append(definition)

        self._ranges = normalized

        for definition in self._ranges:
            row = _RangeItem(
                definition,
                self._range_list,
                compact=self._compact,
                ultra_compact=self._ultra_compact,
                clickable=self._clickable_ranges,
                theme=self._theme,
            )
            row.clicked.connect(self._on_range_row_clicked)
            self._range_layout.addWidget(row)

        self._range_layout.addStretch(1)
        self.set_active_index(self._find_active_index(self._current_value), emit_signal=False)
        self._refresh_visibility()

    def add_range(
        self,
        *,
        label: str,
        minimum: Optional[float] = None,
        maximum: Optional[float] = None,
        severity: str = SEVERITY_UNKNOWN,
        description: str = "",
        short_label: str = "",
        inclusive_min: bool = True,
        inclusive_max: bool = False,
    ) -> None:
        ranges = self._ranges[:]
        ranges.append(
            RangeDefinition(
                label=label,
                minimum=minimum,
                maximum=maximum,
                severity=severity,
                description=description,
                short_label=short_label,
                inclusive_min=inclusive_min,
                inclusive_max=inclusive_max,
            )
        )
        self.set_ranges(ranges)

    def clear_ranges(self) -> None:
        self._ranges.clear()
        while self._range_layout.count():
            item = self._range_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        self._active_index = -1
        self._update_summary_text()
        self._refresh_visibility()

    def set_active_index(self, index: int, *, emit_signal: bool = True) -> None:
        self._active_index = index if 0 <= index < len(self._ranges) else -1

        for i in range(self._range_layout.count()):
            item = self._range_layout.itemAt(i)
            widget = item.widget()
            if isinstance(widget, _RangeItem):
                widget.set_active(i == self._active_index)

        self._update_summary_text()
        self._apply_style()

        if emit_signal:
            active = self.active_range_definition()
            self.active_range_changed.emit(active.to_dict() if active else {})

    def set_compact(self, compact: bool, ultra_compact: Optional[bool] = None) -> None:
        self._compact = bool(compact)
        if ultra_compact is not None:
            self._ultra_compact = bool(ultra_compact)
        self._rebuild_for_compact_mode()

    def compact(self) -> bool:
        return self._compact

    def _rebuild_for_compact_mode(self) -> None:
        current_ranges = self.ranges()
        current_value = self._current_value
        current_active = self._active_index
        self._clear_layout_widgets()
        self._build_ui()
        self._apply_shadow()
        self._apply_style()
        self.set_title(self._title)
        self.set_subtitle(self._subtitle)
        self.set_unit(self._unit)
        self.set_ranges(current_ranges)
        self.set_current_value(current_value, emit_signal=False)
        if current_active >= 0:
            self.set_active_index(current_active, emit_signal=False)
        self._refresh_visibility()

    def _clear_layout_widgets(self) -> None:
        layout = self.layout()
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                while child_layout.count():
                    c = child_layout.takeAt(0)
                    if c.widget() is not None:
                        c.widget().deleteLater()
                child_layout.deleteLater()

    def _sync_compact_mode(self) -> None:
        width = self.width() or KIOSK_WIDTH
        height = self.height() or KIOSK_HEIGHT
        ultra = width <= 560 or height <= 180 or self._ultra_compact
        compact = width <= 720 or IS_COMPACT_KIOSK or ultra
        if compact != self._compact or ultra != self._ultra_compact:
            self.set_compact(compact, ultra)

    def set_clickable_ranges(self, clickable: bool) -> None:
        self._clickable_ranges = bool(clickable)
        for i in range(self._range_layout.count()):
            item = self._range_layout.itemAt(i)
            widget = item.widget()
            if isinstance(widget, _RangeItem):
                widget.set_clickable(self._clickable_ranges)

    def set_show_header(self, visible: bool) -> None:
        self._show_header = bool(visible)
        self._refresh_visibility()

    def set_show_current_value(self, visible: bool) -> None:
        self._show_current_value = bool(visible)
        self._refresh_visibility()

    def set_show_summary(self, visible: bool) -> None:
        self._show_summary = bool(visible)
        self._refresh_visibility()

    # ========================================================
    # Summary + payload
    # ========================================================

    def _update_summary_text(self) -> None:
        active = self.active_range_definition()
        if active is None:
            if self._current_value in (None, ""):
                self._summary_label.setText("No current value is available for range interpretation.")
            else:
                self._summary_label.setText("The current value does not match any configured interpretation range.")
            return

        current_text = self._format_value(self._current_value)
        parts = [f"Current value {current_text}"]
        if self._unit.strip():
            parts[-1] += f" {self._unit}"

        parts.append(f"falls in the “{active.label}” range.")
        if active.description.strip():
            parts.append(active.description.strip())

        summary = " ".join(parts)
        if self._ultra_compact and len(summary) > 120:
            summary = summary[:117].rstrip() + "..."
        self._summary_label.setText(summary)

    def apply_range_payload(self, payload: Mapping[str, Any]) -> None:
        """
        Apply a generic range payload.

        Supported structure:
        {
            "title": "BMI Categories",
            "subtitle": "Body mass index interpretation",
            "unit": "kg/m²",
            "current_value": 27.4,
            "ranges": [
                {
                    "label": "Normal",
                    "min": 18.5,
                    "max": 25.0,
                    "severity": "normal",
                    "description": "Healthy BMI range."
                }
            ]
        }
        """
        data = dict(payload or {})

        if "title" in data:
            self.set_title(safe_str(data.get("title"), ""))
        if "subtitle" in data:
            self.set_subtitle(safe_str(data.get("subtitle"), ""))
        if "unit" in data:
            self.set_unit(safe_str(data.get("unit"), ""))

        ranges = data.get("ranges", [])
        if isinstance(ranges, list):
            self.set_ranges(ranges)

        if "current_value" in data:
            self.set_current_value(data.get("current_value"), emit_signal=False)

        self.payload_applied.emit(dict(data))

    # ========================================================
    # Visibility / interaction
    # ========================================================

    def _refresh_visibility(self) -> None:
        header_has_text = bool(self._title.strip()) or bool(self._subtitle.strip())
        self._header.setVisible(self._show_header and header_has_text)

        self._current_caption.setVisible(self._show_current_value and (not self._ultra_compact))
        self._current_value_label.setVisible(self._show_current_value)
        self._current_unit_label.setVisible(self._show_current_value and bool(self._unit.strip()))
        self._subtitle_label.setVisible((not self._ultra_compact) and bool(self._subtitle.strip()))

        has_summary = bool(self._summary_label.text().strip())
        self._summary_strip.setVisible(self._show_summary and has_summary)
        self._summary_label.setVisible(self._show_summary and has_summary)

    def _on_range_row_clicked(self, payload: Dict[str, Any]) -> None:
        self.range_clicked.emit(dict(payload))

    def _is_layout_managed(self) -> bool:
        parent = self.parentWidget()
        if parent is None:
            return False
        return parent.layout() is not None

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_compact_mode()

    def enterEvent(self, event: QEvent) -> None:
        super().enterEvent(event)
        self._hovered = True
        self._apply_style()
        self._animate_lift(True)

    def leaveEvent(self, event: QEvent) -> None:
        super().leaveEvent(event)
        self._hovered = False
        self._apply_style()
        self._animate_lift(False)

    def _animate_lift(self, hovered: bool) -> None:
        if self._is_layout_managed():
            return

        if self._base_pos is None:
            self._base_pos = self.pos()

        target = self._base_pos if not hovered else QPoint(self._base_pos.x(), self._base_pos.y() - 1)

        if self._hover_anim is not None:
            try:
                self._hover_anim.stop()
            except Exception:
                pass

        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(120)
        anim.setStartValue(self.pos())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        self._hover_anim = anim

    # ========================================================
    # Paint
    # ========================================================

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = self.rect().adjusted(1, 1, -1, -1)
        if rect.width() > 4 and rect.height() > 4:
            radius = 15 if self._ultra_compact else (22 if not self._compact else 18)
            path = QPainterPath()
            path.addRoundedRect(rect, radius, radius)

            painter.save()
            painter.setClipPath(path)

            gloss_rect = rect.adjusted(2, 2, -2, -(rect.height() - int(rect.height() * 0.34)))
            painter.fillRect(gloss_rect, QColor(255, 255, 255, 12 if not self._hovered else 18))

            pen = QPen(QColor(self._active_accent_hex()))
            pen.setWidthF(1.0)
            painter.setOpacity(0.18)
            painter.setPen(pen)
            painter.drawLine(rect.left() + 16, rect.bottom() - 1, rect.right() - 16, rect.bottom() - 1)

            painter.restore()

        painter.end()

    # ========================================================
    # Diagnostics
    # ========================================================

    def diagnostics(self) -> Dict[str, Any]:
        active = self.active_range_definition()
        return {
            "title": self._title,
            "subtitle": self._subtitle,
            "unit": self._unit,
            "current_value": self._current_value,
            "active_index": self._active_index,
            "active_range": active.to_dict() if active else {},
            "range_count": len(self._ranges),
            "show_header": self._show_header,
            "show_current_value": self._show_current_value,
            "show_summary": self._show_summary,
            "compact": self._compact,
            "ultra_compact": self._ultra_compact,
            "clickable_ranges": self._clickable_ranges,
        }
