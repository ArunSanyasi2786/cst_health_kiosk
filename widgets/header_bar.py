"""
widgets/header_bar.py

Compact-ready premium reusable header bar for the CST Health Monitoring Station kiosk.

Why this updated version matters for the 800x480 transition:
- preserves the same premium futuristic medical visual language
- keeps the same public API so existing screens do not need major rewrites
- reduces header height and horizontal crowding for compact kiosk displays
- auto-adjusts badge detail, subtitle visibility, and button density based on width
- remains safe for Raspberry Pi and laptop demo usage

This file is intentionally conservative:
- it does not change navigation logic
- it does not assume all services are already wired
- it provides safe fallbacks if app state / assets are unavailable
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import (
    QDateTime,
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from core.logger import get_logger
from core.utils import safe_str

try:
    from core.app_state import AppState, get_app_state
except Exception:  # pragma: no cover
    AppState = object  # type: ignore
    get_app_state = None  # type: ignore

try:
    from core.constants import HEADER_HEIGHT, MODE_DEMO, MODE_HARDWARE
except Exception:  # pragma: no cover
    HEADER_HEIGHT = 82
    MODE_DEMO = "demo"
    MODE_HARDWARE = "hardware"

try:
    from core.asset_paths import get_main_logo_path
except Exception:  # pragma: no cover
    get_main_logo_path = None  # type: ignore

try:
    from config import KIOSK_HEIGHT, KIOSK_WIDTH, UI_SCALE, WIDTH_SCALE, HEIGHT_SCALE, IS_COMPACT_KIOSK
except Exception:  # pragma: no cover
    KIOSK_WIDTH = 1024
    KIOSK_HEIGHT = 600
    UI_SCALE = 1.0
    WIDTH_SCALE = KIOSK_WIDTH / 1024.0
    HEIGHT_SCALE = KIOSK_HEIGHT / 600.0
    IS_COMPACT_KIOSK = KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480

from widgets.animated_button import AnimatedButton
from widgets.glow_label import GlowLabel

logger = get_logger(__name__)


# ============================================================
# Theme dataclass
# ============================================================

@dataclass(frozen=True)
class HeaderBarTheme:
    """Theme container for HeaderBar."""

    shell_top: str = "rgba(14, 33, 60, 0.90)"
    shell_bottom: str = "rgba(9, 22, 42, 0.94)"
    border_color: str = "rgba(155, 221, 255, 0.24)"
    inner_gloss: str = "rgba(255, 255, 255, 0.06)"
    title_color: str = "#F4FCFF"
    subtitle_color: str = "rgba(211, 233, 248, 0.78)"
    accent_color: str = "#38D7FF"
    shadow_hex: str = "#34D5FF"
    icon_ring_bg: str = "rgba(56, 124, 196, 0.16)"
    icon_ring_border: str = "rgba(141, 214, 255, 0.24)"
    badge_bg: str = "rgba(26, 48, 82, 0.82)"
    badge_border: str = "rgba(146, 216, 255, 0.22)"
    badge_text: str = "#EAF8FF"
    badge_subtle_text: str = "rgba(204, 226, 242, 0.76)"
    online_color: str = "#39D98D"
    warning_color: str = "#FFC857"
    offline_color: str = "#F36A7D"
    demo_color: str = "#67D5FF"
    hardware_color: str = "#84FFB8"


DEFAULT_HEADER_THEME = HeaderBarTheme()


# ============================================================
# Scaling helpers
# ============================================================

def _scale(value: int | float) -> int:
    return max(1, int(round(float(value) * float(UI_SCALE))))


def _w_scale(value: int | float) -> int:
    return max(1, int(round(float(value) * float(WIDTH_SCALE))))


def _h_scale(value: int | float) -> int:
    return max(1, int(round(float(value) * float(HEIGHT_SCALE))))


def _compact_default() -> bool:
    return bool(IS_COMPACT_KIOSK or KIOSK_WIDTH <= 860 or KIOSK_HEIGHT <= 520)


# ============================================================
# Internal helper widgets
# ============================================================

class _ClickableLogoLabel(QLabel):
    """Small clickable logo label used by HeaderBar."""

    clicked = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

    def mouseReleaseEvent(self, event: Optional[QMouseEvent]) -> None:
        super().mouseReleaseEvent(event)
        if event is not None and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


class _ClickableGlowLabel(GlowLabel):
    """GlowLabel with click support for the main title."""

    clicked = pyqtSignal()

    def mouseReleaseEvent(self, event: Optional[QMouseEvent]) -> None:
        super().mouseReleaseEvent(event)
        if event is not None and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


class _HeaderBadge(QFrame):
    """Compact pill badge used for connection/mode/time display."""

    clicked = pyqtSignal()

    ROLE_NEUTRAL = "neutral"
    ROLE_ONLINE = "online"
    ROLE_WARNING = "warning"
    ROLE_OFFLINE = "offline"
    ROLE_DEMO = "demo"
    ROLE_HARDWARE = "hardware"

    def __init__(
        self,
        text: str = "",
        detail: str = "",
        parent: Optional[QWidget] = None,
        *,
        theme: HeaderBarTheme = DEFAULT_HEADER_THEME,
        role: str = ROLE_NEUTRAL,
        clickable: bool = False,
        compact: bool = False,
    ) -> None:
        super().__init__(parent)

        self._theme = theme
        self._role = str(role or self.ROLE_NEUTRAL).strip().lower()
        self._clickable = bool(clickable)
        self._compact = bool(compact)
        self._show_detail = not compact
        self._hovered = False

        self.setObjectName("HeaderBadge")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor if self._clickable else Qt.CursorShape.ArrowCursor)
        self.setMouseTracking(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            _scale(10 if not compact else 8),
            _h_scale(6 if not compact else 4),
            _scale(10 if not compact else 8),
            _h_scale(6 if not compact else 4),
        )
        layout.setSpacing(_scale(8 if not compact else 6))

        dot_size = _scale(9 if not compact else 8)
        self._dot = QLabel(self)
        self._dot.setFixedSize(dot_size, dot_size)

        text_col = QWidget(self)
        text_layout = QVBoxLayout(text_col)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)

        self._text_label = QLabel(text_col)
        self._text_label.setWordWrap(False)

        self._detail_label = QLabel(text_col)
        self._detail_label.setWordWrap(False)

        text_layout.addWidget(self._text_label)
        text_layout.addWidget(self._detail_label)

        layout.addWidget(self._dot, 0, alignment=Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(text_col, 0, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.set_text(text)
        self.set_detail(detail)
        self._apply_style()

    def _role_color(self) -> str:
        if self._role == self.ROLE_ONLINE:
            return self._theme.online_color
        if self._role == self.ROLE_WARNING:
            return self._theme.warning_color
        if self._role == self.ROLE_OFFLINE:
            return self._theme.offline_color
        if self._role == self.ROLE_DEMO:
            return self._theme.demo_color
        if self._role == self.ROLE_HARDWARE:
            return self._theme.hardware_color
        return self._theme.accent_color

    def _apply_style(self) -> None:
        radius = _scale(16 if not self._compact else 13)
        border = self._theme.badge_border
        bg = self._theme.badge_bg
        if self._hovered and self._clickable:
            bg = "rgba(33, 58, 94, 0.94)"
            border = "rgba(173, 229, 255, 0.36)"

        accent = self._role_color()
        dot_radius = self._dot.width() // 2

        self.setStyleSheet(
            f"""
            QFrame#HeaderBadge {{
                border: 1px solid {border};
                border-radius: {radius}px;
                background: {bg};
            }}
            QLabel {{
                background: transparent;
                border: none;
            }}
            """
        )

        self._dot.setStyleSheet(
            f"""
            QLabel {{
                min-width: {self._dot.width()}px;
                min-height: {self._dot.height()}px;
                max-width: {self._dot.width()}px;
                max-height: {self._dot.height()}px;
                border-radius: {dot_radius}px;
                background: {accent};
                border: 1px solid rgba(255, 255, 255, 0.16);
            }}
            """
        )

        text_size = max(9, _scale(11 if not self._compact else 10))
        detail_size = max(8, _scale(9 if not self._compact else 8))

        self._text_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.badge_text};
                font-size: {text_size}px;
                font-weight: 700;
            }}
            """
        )
        self._detail_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.badge_subtle_text};
                font-size: {detail_size}px;
                font-weight: 500;
            }}
            """
        )
        self._detail_label.setVisible(self._show_detail and bool(self._detail_label.text().strip()))
        self.updateGeometry()

    def set_text(self, text: str) -> None:
        self._text_label.setText(str(text or "").strip())
        self._text_label.setToolTip(self._text_label.text())

    def text(self) -> str:
        return self._text_label.text()

    def set_detail(self, detail: str) -> None:
        self._detail_label.setText(str(detail or "").strip())
        self._detail_label.setToolTip(self._detail_label.text())
        self._detail_label.setVisible(self._show_detail and bool(self._detail_label.text().strip()))

    def detail(self) -> str:
        return self._detail_label.text()

    def set_role(self, role: str) -> None:
        self._role = str(role or self.ROLE_NEUTRAL).strip().lower()
        self._apply_style()

    def role(self) -> str:
        return self._role

    def set_clickable(self, clickable: bool) -> None:
        self._clickable = bool(clickable)
        self.setCursor(Qt.CursorShape.PointingHandCursor if self._clickable else Qt.CursorShape.ArrowCursor)

    def set_compact(self, compact: bool) -> None:
        self._compact = bool(compact)
        self._apply_style()

    def set_show_detail(self, visible: bool) -> None:
        self._show_detail = bool(visible)
        self._detail_label.setVisible(self._show_detail and bool(self._detail_label.text().strip()))
        self.updateGeometry()

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
            self.clicked.emit()


# ============================================================
# Main HeaderBar widget
# ============================================================

class HeaderBar(QFrame):
    """
    Reusable premium header/navigation bar.

    Main sections:
    - left: back/home buttons + logo
    - center: title + subtitle
    - right: mode badge, connection badge, clock, settings/admin buttons
    """

    back_clicked = pyqtSignal()
    home_clicked = pyqtSignal()
    admin_clicked = pyqtSignal()
    settings_clicked = pyqtSignal()
    logo_clicked = pyqtSignal()
    title_clicked = pyqtSignal()
    connection_badge_clicked = pyqtSignal()
    mode_badge_clicked = pyqtSignal()
    clock_clicked = pyqtSignal()

    def __init__(
        self,
        title: str = "",
        subtitle: str = "",
        parent: Optional[QWidget] = None,
        *,
        logo_path: str = "",
        theme: Optional[HeaderBarTheme] = None,
        show_back: bool = False,
        show_home: bool = False,
        show_admin: bool = False,
        show_settings: bool = False,
        show_mode_badge: bool = True,
        show_connection_badge: bool = True,
        show_clock: bool = True,
        compact: bool = False,
        fixed_height: Optional[int] = None,
        app_state: Optional[AppState] = None,
    ) -> None:
        super().__init__(parent)

        self._logger = logger.bind(component="HeaderBar")
        self._theme = theme or DEFAULT_HEADER_THEME
        self._compact = bool(compact or _compact_default())
        self._ultra_compact = False
        self._show_seconds = False
        self._logo_path = str(logo_path or "").strip()
        self._connection_label = "Disconnected"
        self._connection_detail = "No hardware connection detected."
        self._connection_role = _HeaderBadge.ROLE_OFFLINE
        self._mode_key = MODE_DEMO
        self._mode_label = "Demo Mode"
        self._mode_detail = "Simulated measurements"

        self._app_state = app_state
        if self._app_state is None and get_app_state is not None:
            try:
                self._app_state = get_app_state()
            except Exception:
                self._app_state = None

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._update_clock_text)

        self._lift_anim: Optional[QPropertyAnimation] = None
        self._base_pos: Optional[QPoint] = None
        self._hovered = False
        self._shadow_effect: Optional[QGraphicsDropShadowEffect] = None

        self.setObjectName("HeaderBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._build_ui(
            show_back=show_back,
            show_home=show_home,
            show_admin=show_admin,
            show_settings=show_settings,
            show_mode_badge=show_mode_badge,
            show_connection_badge=show_connection_badge,
            show_clock=show_clock,
        )

        self.set_title(title)
        self.set_subtitle(subtitle)
        self.set_logo(self._logo_path)
        self._apply_shadow()
        self._apply_style()

        if fixed_height is not None:
            self.setFixedHeight(int(fixed_height))
        else:
            default_h = min(max(_h_scale(HEADER_HEIGHT), _h_scale(56)), _h_scale(82))
            if self._compact:
                default_h = min(default_h, _h_scale(60))
            self.setFixedHeight(default_h)

        self._update_clock_text()
        if show_clock:
            self._clock_timer.start()

        self.refresh_from_app_state()
        self._refresh_compact_layout(force=True)

    # ========================================================
    # UI building
    # ========================================================

    def _build_ui(
        self,
        *,
        show_back: bool,
        show_home: bool,
        show_admin: bool,
        show_settings: bool,
        show_mode_badge: bool,
        show_connection_badge: bool,
        show_clock: bool,
    ) -> None:
        self.root_layout = QHBoxLayout(self)
        self.root_layout.setContentsMargins(
            _w_scale(14 if not self._compact else 10),
            _h_scale(8 if not self._compact else 6),
            _w_scale(14 if not self._compact else 10),
            _h_scale(8 if not self._compact else 6),
        )
        self.root_layout.setSpacing(_scale(12 if not self._compact else 8))

        # ----------------------------------------------------
        # Left section
        # ----------------------------------------------------
        left_wrap = QWidget(self)
        self.left_layout = QHBoxLayout(left_wrap)
        self.left_layout.setContentsMargins(0, 0, 0, 0)
        self.left_layout.setSpacing(_scale(8 if not self._compact else 6))

        self.back_button = AnimatedButton(
            text="Back",
            variant=AnimatedButton.VARIANT_GHOST,
            size=AnimatedButton.SIZE_SM if self._compact else AnimatedButton.SIZE_MD,
            minimum_width=_w_scale(74 if not self._compact else 56),
        )
        self.back_button.clicked.connect(self.back_clicked.emit)

        self.home_button = AnimatedButton(
            text="Home",
            variant=AnimatedButton.VARIANT_SECONDARY,
            size=AnimatedButton.SIZE_SM if self._compact else AnimatedButton.SIZE_MD,
            minimum_width=_w_scale(80 if not self._compact else 58),
        )
        self.home_button.clicked.connect(self.home_clicked.emit)

        ring_size = _scale(58 if not self._compact else 42)
        self._logo_ring = QFrame(self)
        self._logo_ring.setObjectName("HeaderLogoRing")
        self._logo_ring.setFixedSize(ring_size, ring_size)

        logo_ring_layout = QVBoxLayout(self._logo_ring)
        logo_ring_layout.setContentsMargins(_scale(6 if not self._compact else 5), _scale(6 if not self._compact else 5), _scale(6 if not self._compact else 5), _scale(6 if not self._compact else 5))
        logo_ring_layout.setSpacing(0)

        self.logo_label = _ClickableLogoLabel(self._logo_ring)
        logo_size = _scale(46 if not self._compact else 30)
        self.logo_label.setFixedSize(logo_size, logo_size)
        self.logo_label.clicked.connect(self.logo_clicked.emit)

        logo_ring_layout.addStretch(1)
        logo_ring_layout.addWidget(self.logo_label, alignment=Qt.AlignmentFlag.AlignCenter)
        logo_ring_layout.addStretch(1)

        self.left_layout.addWidget(self.back_button)
        self.left_layout.addWidget(self.home_button)
        self.left_layout.addWidget(self._logo_ring)

        # ----------------------------------------------------
        # Center section
        # ----------------------------------------------------
        center_wrap = QWidget(self)
        self.center_layout = QVBoxLayout(center_wrap)
        self.center_layout.setContentsMargins(_scale(2), 0, _scale(2), 0)
        self.center_layout.setSpacing(_h_scale(1))

        self.title_label = _ClickableGlowLabel(
            role=GlowLabel.ROLE_STATUS if self._compact else GlowLabel.ROLE_TITLE,
            align_center=False,
            use_outline=True,
            enable_paint_glow=True,
            initial_glow_strength=0.58 if self._compact else 0.62,
            initial_glow_blur=_scale(18 if self._compact else 24),
        )
        self.title_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.title_label.clicked.connect(self.title_clicked.emit)

        self.subtitle_label = GlowLabel(
            role=GlowLabel.ROLE_TINY if self._compact else GlowLabel.ROLE_SUBTITLE,
            align_center=False,
            use_outline=False,
            enable_paint_glow=False,
            initial_glow_strength=0.16,
            initial_glow_blur=_scale(10),
        )
        self.subtitle_label.set_text_color(self._theme.subtitle_color)
        self.subtitle_label.setWordWrap(False)

        self.center_layout.addWidget(self.title_label)
        self.center_layout.addWidget(self.subtitle_label)

        # ----------------------------------------------------
        # Right section
        # ----------------------------------------------------
        right_wrap = QWidget(self)
        self.right_layout = QHBoxLayout(right_wrap)
        self.right_layout.setContentsMargins(0, 0, 0, 0)
        self.right_layout.setSpacing(_scale(8 if not self._compact else 6))

        self.mode_badge = _HeaderBadge(
            theme=self._theme,
            text="Demo Mode",
            detail="Simulated measurements",
            role=_HeaderBadge.ROLE_DEMO,
            clickable=True,
            compact=self._compact,
        )
        self.mode_badge.clicked.connect(self.mode_badge_clicked.emit)

        self.connection_badge = _HeaderBadge(
            theme=self._theme,
            text="Disconnected",
            detail="No hardware connection detected.",
            role=_HeaderBadge.ROLE_OFFLINE,
            clickable=True,
            compact=self._compact,
        )
        self.connection_badge.clicked.connect(self.connection_badge_clicked.emit)

        self.clock_badge = _HeaderBadge(
            theme=self._theme,
            text="--:--",
            detail="Local time",
            role=_HeaderBadge.ROLE_NEUTRAL,
            clickable=True,
            compact=self._compact,
        )
        self.clock_badge.clicked.connect(self.clock_clicked.emit)

        self.admin_button = AnimatedButton(
            text="Admin",
            variant=AnimatedButton.VARIANT_SECONDARY,
            size=AnimatedButton.SIZE_SM if self._compact else AnimatedButton.SIZE_MD,
            minimum_width=_w_scale(82 if not self._compact else 60),
        )
        self.admin_button.clicked.connect(self.admin_clicked.emit)

        self.settings_button = AnimatedButton(
            text="Settings",
            variant=AnimatedButton.VARIANT_GHOST,
            size=AnimatedButton.SIZE_SM if self._compact else AnimatedButton.SIZE_MD,
            minimum_width=_w_scale(92 if not self._compact else 64),
        )
        self.settings_button.clicked.connect(self.settings_clicked.emit)

        self.right_layout.addWidget(self.mode_badge)
        self.right_layout.addWidget(self.connection_badge)
        self.right_layout.addWidget(self.clock_badge)
        self.right_layout.addWidget(self.admin_button)
        self.right_layout.addWidget(self.settings_button)

        # ----------------------------------------------------
        # Assemble
        # ----------------------------------------------------
        self.root_layout.addWidget(left_wrap, 0, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.root_layout.addWidget(center_wrap, 1, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.root_layout.addItem(QSpacerItem(_scale(2), 1, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum))
        self.root_layout.addWidget(right_wrap, 0, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.set_show_back(show_back)
        self.set_show_home(show_home)
        self.set_show_admin(show_admin)
        self.set_show_settings(show_settings)
        self.set_show_mode_badge(show_mode_badge)
        self.set_show_connection_badge(show_connection_badge)
        self.set_show_clock(show_clock)

    # ========================================================
    # Styling
    # ========================================================

    def _apply_shadow(self) -> None:
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(_scale(28 if not self._compact else 20))
        shadow.setOffset(0, _h_scale(7 if not self._compact else 5))

        color = QColor(self._theme.shadow_hex)
        color.setAlpha(70)
        shadow.setColor(color)
        self.setGraphicsEffect(shadow)
        self._shadow_effect = shadow

    def _apply_style(self) -> None:
        radius = _scale(24 if not self._compact else 18)
        ring_radius = self._logo_ring.width() // 2

        self.setStyleSheet(
            f"""
            QFrame#HeaderBar {{
                border: 1px solid {self._theme.border_color};
                border-radius: {radius}px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 {self._theme.shell_top},
                    stop:1 {self._theme.shell_bottom}
                );
            }}

            QFrame#HeaderLogoRing {{
                border: 1px solid {self._theme.icon_ring_border};
                border-radius: {ring_radius}px;
                background: {self._theme.icon_ring_bg};
            }}
            """
        )
        self.title_label.set_text_color(self._theme.title_color)
        self.subtitle_label.set_text_color(self._theme.subtitle_color)

    # ========================================================
    # Public title / subtitle / logo
    # ========================================================

    def set_title(self, title: str) -> None:
        cleaned = str(title or "").strip()
        self.title_label.set_text(cleaned)
        self.title_label.setVisible(bool(cleaned))
        self.title_label.setToolTip(cleaned)

    def title(self) -> str:
        return self.title_label.text()

    def set_subtitle(self, subtitle: str) -> None:
        cleaned = str(subtitle or "").strip()
        self.subtitle_label.set_text(cleaned)
        self.subtitle_label.setVisible(bool(cleaned))
        self.subtitle_label.setToolTip(cleaned)

    def subtitle(self) -> str:
        return self.subtitle_label.text()

    def set_logo(self, logo_path: str | Path) -> None:
        path_string = str(logo_path or "").strip()

        if not path_string and get_main_logo_path is not None:
            try:
                path_string = str(get_main_logo_path())
            except Exception:
                path_string = ""

        pixmap = QPixmap()
        if path_string:
            path = Path(path_string).expanduser()
            if path.exists() and path.is_file():
                pixmap = QPixmap(str(path))

        if pixmap.isNull():
            self.logo_label.clear()
            self.logo_label.setText("CST")
            font = QFont(self.logo_label.font())
            font.setBold(True)
            font.setPointSize(max(9, _scale(12 if not self._compact else 10)))
            self.logo_label.setFont(font)
            self.logo_label.setStyleSheet(
                f"""
                QLabel {{
                    color: {self._theme.title_color};
                    background: transparent;
                }}
                """
            )
            return

        self.logo_label.clear()
        target = _scale(36 if not self._compact else 24)
        scaled = pixmap.scaled(
            QSize(target, target),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.logo_label.setPixmap(scaled)
        self.logo_label.setStyleSheet("QLabel { background: transparent; }")

    # ========================================================
    # Public visibility controls
    # ========================================================

    def set_show_back(self, visible: bool) -> None:
        self.back_button.setVisible(bool(visible))

    def set_show_home(self, visible: bool) -> None:
        self.home_button.setVisible(bool(visible))

    def set_show_admin(self, visible: bool) -> None:
        self.admin_button.setVisible(bool(visible))

    def set_show_settings(self, visible: bool) -> None:
        self.settings_button.setVisible(bool(visible))

    def set_show_mode_badge(self, visible: bool) -> None:
        self.mode_badge.setVisible(bool(visible))

    def set_show_connection_badge(self, visible: bool) -> None:
        self.connection_badge.setVisible(bool(visible))

    def set_show_clock(self, visible: bool) -> None:
        visible = bool(visible)
        self.clock_badge.setVisible(visible)
        if visible:
            if not self._clock_timer.isActive():
                self._clock_timer.start()
            self._update_clock_text()
        else:
            self._clock_timer.stop()

    def set_show_seconds(self, visible: bool) -> None:
        self._show_seconds = bool(visible)
        self._update_clock_text()

    # ========================================================
    # Connection / mode / clock setters
    # ========================================================

    def set_connection_state(
        self,
        *,
        connected: bool = False,
        waiting: bool = False,
        label: str = "",
        detail: str = "",
    ) -> None:
        connected = bool(connected)
        waiting = bool(waiting)

        if connected:
            role = _HeaderBadge.ROLE_ONLINE
            fallback_text = "Hardware Connected" if not self._compact else "Connected"
            fallback_detail = "Hardware connection ready"
        elif waiting:
            role = _HeaderBadge.ROLE_WARNING
            fallback_text = "Serial Waiting" if not self._compact else "Waiting"
            fallback_detail = "Waiting for hardware connection"
        else:
            role = _HeaderBadge.ROLE_OFFLINE
            fallback_text = "ESP32 Not Detected" if not self._compact else "Offline"
            fallback_detail = "No hardware connection detected."

        self._connection_label = safe_str(label, fallback_text) or fallback_text
        self._connection_detail = safe_str(detail, fallback_detail) or fallback_detail
        self._connection_role = role

        self.connection_badge.set_role(role)
        self.connection_badge.set_text(self._connection_label)
        self.connection_badge.set_detail(self._connection_detail)
        self._refresh_compact_layout()

    def connection_label(self) -> str:
        return self._connection_label

    def set_mode(
        self,
        mode_key: str,
        *,
        label: str = "",
        detail: str = "",
    ) -> None:
        cleaned = safe_str(mode_key, MODE_DEMO).strip().lower()

        if cleaned == MODE_HARDWARE:
            role = _HeaderBadge.ROLE_HARDWARE
            fallback_label = "Hardware Mode" if not self._compact else "Hardware"
            fallback_detail = "Live sensor measurements"
        else:
            cleaned = MODE_DEMO
            role = _HeaderBadge.ROLE_DEMO
            fallback_label = "Demo Mode" if not self._compact else "Demo"
            fallback_detail = "Simulated measurements"

        self._mode_key = cleaned
        self._mode_label = safe_str(label, fallback_label) or fallback_label
        self._mode_detail = safe_str(detail, fallback_detail) or fallback_detail

        self.mode_badge.set_role(role)
        self.mode_badge.set_text(self._mode_label)
        self.mode_badge.set_detail(self._mode_detail)
        self._refresh_compact_layout()

    def mode(self) -> str:
        return self._mode_key

    def _update_clock_text(self) -> None:
        now = QDateTime.currentDateTime()
        if self._ultra_compact:
            fmt = "hh:mm" if not self._show_seconds else "hh:mm:ss"
        else:
            fmt = "hh:mm:ss AP" if self._show_seconds else "hh:mm AP"
        self.clock_badge.set_text(now.toString(fmt))
        self.clock_badge.set_detail(now.toString("ddd, dd MMM"))

    def set_clock_text(self, text: str, detail: str = "Local time") -> None:
        self.clock_badge.set_text(str(text or "").strip())
        self.clock_badge.set_detail(str(detail or "").strip())

    # ========================================================
    # AppState integration
    # ========================================================

    def refresh_from_app_state(self) -> None:
        """Best-effort UI refresh from AppState if available."""
        if self._app_state is None:
            return

        try:
            runtime_mode = MODE_DEMO
            if hasattr(self._app_state, "runtime_mode"):
                runtime_mode_attr = getattr(self._app_state, "runtime_mode")
                if callable(runtime_mode_attr):
                    try:
                        runtime_mode = safe_str(runtime_mode_attr(), MODE_DEMO)
                    except Exception:
                        runtime_mode = MODE_DEMO
                else:
                    runtime_mode = safe_str(runtime_mode_attr, MODE_DEMO)

            self.set_mode(runtime_mode)

            if hasattr(self._app_state, "connection_snapshot"):
                snapshot_attr = getattr(self._app_state, "connection_snapshot")
                snap = snapshot_attr() if callable(snapshot_attr) else snapshot_attr

                if isinstance(snap, dict):
                    serial_connected = bool(snap.get("serial_connected", False))
                    esp32_connected = bool(snap.get("esp32_connected", False))
                    connection_label = safe_str(snap.get("connection_label"), "")
                    connection_detail = safe_str(snap.get("connection_detail"), "")
                    waiting = bool(snap.get("waiting", False)) or not (serial_connected or esp32_connected)
                    self.set_connection_state(
                        connected=(serial_connected or esp32_connected),
                        waiting=waiting,
                        label=connection_label,
                        detail=connection_detail,
                    )
        except Exception as exc:
            self._logger.debug("HeaderBar refresh_from_app_state failed: %s", exc)

    # ========================================================
    # Compact adaptation
    # ========================================================

    def _refresh_compact_layout(self, force: bool = False) -> None:
        width = max(0, self.width()) or int(KIOSK_WIDTH)

        compact = self._compact or width <= 860
        ultra_compact = width <= 720 or KIOSK_WIDTH <= 800

        if not force and compact == self._compact and ultra_compact == self._ultra_compact:
            return

        self._compact = compact
        self._ultra_compact = ultra_compact

        # Title / subtitle density
        self.subtitle_label.setVisible(bool(self.subtitle_label.text().strip()) and not ultra_compact)

        # Badge density
        show_badge_detail = not compact and not ultra_compact
        self.mode_badge.set_show_detail(show_badge_detail)
        self.connection_badge.set_show_detail(show_badge_detail)
        self.clock_badge.set_show_detail(not ultra_compact)

        # Shorten labels for narrow width
        if ultra_compact:
            self.admin_button.setText("Admin")
            self.settings_button.setText("Prefs")
            self.home_button.setText("Home")
        else:
            self.admin_button.setText("Admin")
            self.settings_button.setText("Settings")
            self.home_button.setText("Home")

        # Button minimum widths
        self.back_button.setMinimumWidth(_w_scale(52 if compact else 72))
        self.home_button.setMinimumWidth(_w_scale(54 if compact else 78))
        self.admin_button.setMinimumWidth(_w_scale(58 if compact else 82))
        self.settings_button.setMinimumWidth(_w_scale(60 if compact else 92))

        # Reduce spacing a bit more on compact screens
        self.root_layout.setSpacing(_scale(8 if compact else 12))
        self.left_layout.setSpacing(_scale(6 if compact else 8))
        self.right_layout.setSpacing(_scale(5 if ultra_compact else (6 if compact else 8)))

        # Fixed height update
        target_h = min(max(_h_scale(HEADER_HEIGHT), _h_scale(56)), _h_scale(82))
        if ultra_compact:
            target_h = _h_scale(56)
        elif compact:
            target_h = min(target_h, _h_scale(60))
        self.setFixedHeight(target_h)

        self._update_clock_text()
        self._apply_shadow()
        self._apply_style()
        self.updateGeometry()
        self.update()

    # ========================================================
    # Mouse / hover
    # ========================================================

    def _is_layout_managed(self) -> bool:
        parent = self.parentWidget()
        if parent is None:
            return False
        return parent.layout() is not None

    def enterEvent(self, event: QEvent) -> None:
        super().enterEvent(event)
        self._hovered = True
        self._animate_lift(True)
        self._set_shadow_strength(True)

    def leaveEvent(self, event: QEvent) -> None:
        super().leaveEvent(event)
        self._hovered = False
        self._animate_lift(False)
        self._set_shadow_strength(False)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_compact_layout()

    def _set_shadow_strength(self, hovered: bool) -> None:
        if self._shadow_effect is None:
            return

        color = QColor(self._theme.shadow_hex)
        if hovered:
            color.setAlpha(100)
            self._shadow_effect.setBlurRadius(_scale(34 if not self._compact else 24))
            self._shadow_effect.setOffset(0, _h_scale(9 if not self._compact else 6))
        else:
            color.setAlpha(70)
            self._shadow_effect.setBlurRadius(_scale(28 if not self._compact else 20))
            self._shadow_effect.setOffset(0, _h_scale(7 if not self._compact else 5))
        self._shadow_effect.setColor(color)

    def _animate_lift(self, hovered: bool) -> None:
        if self._is_layout_managed():
            return

        if self._base_pos is None:
            self._base_pos = self.pos()

        target = self._base_pos if not hovered else QPoint(self._base_pos.x(), self._base_pos.y() - 1)

        if self._lift_anim is not None:
            try:
                self._lift_anim.stop()
            except Exception:
                pass

        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(130)
        anim.setStartValue(self.pos())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        self._lift_anim = anim

    # ========================================================
    # Paint extras
    # ========================================================

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            rect = QRectF(self.rect().adjusted(1, 1, -1, -1))
            if rect.width() <= 4 or rect.height() <= 4:
                return

            radius = float(_scale(24 if not self._compact else 18))
            path = QPainterPath()
            path.addRoundedRect(rect, radius, radius)

            painter.save()
            painter.setClipPath(path)

            gloss_rect = QRectF(
                rect.left() + 2.0,
                rect.top() + 2.0,
                max(0.0, rect.width() - 4.0),
                max(0.0, rect.height() * 0.42 - 2.0),
            )
            painter.fillRect(gloss_rect, QColor(255, 255, 255, 16 if not self._hovered else 24))

            pen = QPen(QColor(self._theme.accent_color))
            pen.setWidthF(1.0)
            painter.setPen(pen)
            painter.setOpacity(0.22)
            painter.drawLine(
                int(rect.left() + _scale(18)),
                int(rect.bottom() - 1),
                int(rect.right() - _scale(18)),
                int(rect.bottom() - 1),
            )

            painter.restore()
        finally:
            painter.end()

    # ========================================================
    # Diagnostics
    # ========================================================

    def diagnostics(self) -> dict:
        return {
            "title": self.title(),
            "subtitle": self.subtitle(),
            "mode": self._mode_key,
            "mode_label": self._mode_label,
            "connection_label": self._connection_label,
            "connection_detail": self._connection_detail,
            "show_seconds": self._show_seconds,
            "clock_visible": self.clock_badge.isVisible(),
            "back_visible": self.back_button.isVisible(),
            "home_visible": self.home_button.isVisible(),
            "admin_visible": self.admin_button.isVisible(),
            "settings_visible": self.settings_button.isVisible(),
            "compact": self._compact,
            "ultra_compact": self._ultra_compact,
            "kiosk_width": KIOSK_WIDTH,
            "kiosk_height": KIOSK_HEIGHT,
        }
