"""
widgets/glass_card.py

Premium glass-style card widget for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is one of the core reusable visual building blocks across the kiosk UI
- It provides the glossy / futuristic medical dashboard feel requested for the project
- It is designed for:
    - metric cards
    - status panels
    - quick actions
    - admin summary cards
    - diagnosis blocks
    - storage and publish widgets
- It supports icon, title, subtitle, body text, footer text, accent color, and hover/click feedback
- It is intentionally reusable so later widgets/screens stay visually consistent

Design goals:
- premium frosted-glass appearance
- soft glow and shadow
- safe on Raspberry Pi and laptop demo
- flexible enough for many other widgets to inherit or compose
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPixmap
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
    from config import IS_COMPACT_KIOSK, KIOSK_WIDTH, KIOSK_HEIGHT
except Exception:  # pragma: no cover - fallback when imported standalone
    IS_COMPACT_KIOSK = False
    KIOSK_WIDTH = 1024
    KIOSK_HEIGHT = 600

logger = get_logger(__name__)

try:
    from core.animation_manager import get_animation_manager
except Exception:  # pragma: no cover - graceful fallback
    get_animation_manager = None  # type: ignore


# ============================================================
# Theme / palette helpers
# ============================================================

@dataclass(frozen=True)
class GlassCardTheme:
    """
    Visual theme for one glass card instance.
    """
    accent_color: str = "#36D6FF"
    accent_soft_color: str = "rgba(54, 214, 255, 0.22)"
    border_color: str = "rgba(160, 220, 255, 0.32)"
    background_top: str = "rgba(18, 41, 72, 0.72)"
    background_bottom: str = "rgba(10, 22, 43, 0.78)"
    title_color: str = "#F4FBFF"
    subtitle_color: str = "rgba(219, 238, 255, 0.78)"
    body_color: str = "rgba(232, 244, 255, 0.90)"
    footer_color: str = "rgba(170, 201, 228, 0.86)"
    icon_bg: str = "rgba(58, 120, 188, 0.18)"
    shadow_color_hex: str = "#39D5FF"


DEFAULT_GLASS_CARD_THEME = GlassCardTheme()


# ============================================================
# Main widget
# ============================================================

class GlassCard(QFrame):
    """
    Reusable premium glass-style card widget.

    Features:
    - rounded glossy card with subtle gradient
    - left accent bar
    - optional icon
    - title / subtitle / body / footer labels
    - hover lift + glow feedback
    - optional click handling
    - optional content widget slot

    Expected usage later:
        card = GlassCard(
            title="SpO₂ Status",
            subtitle="Current oxygen saturation",
            body="Healthy range detected.",
            icon_path="assets/icons/spo2.png",
        )
    """

    clicked = pyqtSignal()
    pressed = pyqtSignal()
    released = pyqtSignal()
    hover_entered = pyqtSignal()
    hover_left = pyqtSignal()

    def __init__(
        self,
        title: str = "",
        subtitle: str = "",
        body: str = "",
        footer: str = "",
        icon_path: str = "",
        parent: Optional[QWidget] = None,
        *,
        theme: Optional[GlassCardTheme] = None,
        accent_color: str = "",
        minimum_height: int = 130,
        fixed_height: Optional[int] = None,
        clickable: bool = False,
        enable_hover_effect: bool = True,
        show_accent_bar: bool = True,
        compact: bool = False,
    ) -> None:
        super().__init__(parent)

        try:
            self._logger = logger.bind(component="GlassCard")
        except Exception:
            self._logger = logger

        self._theme: GlassCardTheme = theme or DEFAULT_GLASS_CARD_THEME
        if accent_color:
            self._theme = GlassCardTheme(
                accent_color=accent_color,
                accent_soft_color=self._rgba_from_hex(accent_color, 0.20),
                border_color=self._rgba_from_hex(accent_color, 0.28),
                background_top=self._theme.background_top,
                background_bottom=self._theme.background_bottom,
                title_color=self._theme.title_color,
                subtitle_color=self._theme.subtitle_color,
                body_color=self._theme.body_color,
                footer_color=self._theme.footer_color,
                icon_bg=self._rgba_from_hex(accent_color, 0.18),
                shadow_color_hex=accent_color,
            )

        self._clickable = bool(clickable)
        self._enable_hover_effect = bool(enable_hover_effect)
        self._show_accent_bar = bool(show_accent_bar)
        self._compact = bool(compact or IS_COMPACT_KIOSK)
        self._ultra_compact = bool(self._compact and KIOSK_WIDTH <= 800 and KIOSK_HEIGHT <= 480)

        self._minimum_height_requested = max(92, int(minimum_height))
        self._fixed_height_requested = int(fixed_height) if fixed_height is not None else None

        self._hovered = False
        self._pressed = False
        self._base_pos: Optional[QPoint] = None

        self._shadow_effect: Optional[QGraphicsDropShadowEffect] = None
        self._hover_anim: Optional[QPropertyAnimation] = None
        self._press_anim: Optional[QPropertyAnimation] = None
        self._animation_manager = None

        if get_animation_manager is not None:
            try:
                self._animation_manager = get_animation_manager()
            except Exception:
                self._animation_manager = None

        self._build_ui()

        self.set_title(title)
        self.set_subtitle(subtitle)
        self.set_body(body)
        self.set_footer(footer)
        self.set_icon(icon_path)

        self._apply_geometry_constraints()
        self._apply_shadow()
        self._apply_base_style()
        self._refresh_visibility()

    # ========================================================
    # Geometry helpers
    # ========================================================

    def _resolved_height(self) -> int:
        """Resolve the target card height for regular and compact kiosks."""
        if self._fixed_height_requested is not None:
            return max(76 if self._ultra_compact else 84, self._fixed_height_requested)

        if self._ultra_compact:
            return max(82, min(self._minimum_height_requested, 118))

        if self._compact:
            return max(92, min(self._minimum_height_requested, 132))

        return max(110, self._minimum_height_requested)

    def _content_row_spacing(self) -> int:
        if self._ultra_compact:
            return 6
        return 12 if not self._compact else 8

    def _content_inner_margins(self) -> tuple[int, int, int, int]:
        if self._ultra_compact:
            return (8, 6, 8, 6)
        if self._compact:
            return (10, 8, 10, 8)
        return (14, 12, 14, 12)

    def _accent_width(self) -> int:
        if self._ultra_compact:
            return 3
        return 6 if not self._compact else 4

    def _icon_box_size(self) -> int:
        if self._ultra_compact:
            return 34
        return 56 if not self._compact else 42

    def _icon_inner_size(self) -> int:
        if self._ultra_compact:
            return 20
        return 40 if not self._compact else 26

    def _resolved_size_policy(self) -> QSizePolicy:
        if self._compact or self._fixed_height_requested is not None:
            return QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def _visible_text_block_count(self) -> int:
        count = 0
        if hasattr(self, "_title_label") and self._title_label.isVisible():
            count += 1
        if hasattr(self, "_subtitle_label") and self._subtitle_label.isVisible():
            count += 1
        if hasattr(self, "_body_label") and self._body_label.isVisible():
            count += 1
        if hasattr(self, "_content_widget_container") and self._content_widget_container.isVisible():
            count += 1
        if hasattr(self, "_footer_label") and self._footer_label.isVisible():
            count += 1
        return count

    def _sync_content_density(self) -> None:
        """
        Tighten vertical density for compact cards.

        This is the key fix that reduces hidden-looking spacing in derived
        compact cards like MetricTile. When only a title + content widget are
        visible, spacing is collapsed so the card feels visually joined rather
        than stacked with empty slack.
        """
        if not hasattr(self, "_content_layout"):
            return

        visible_count = self._visible_text_block_count()

        if self._compact:
            if visible_count <= 1:
                spacing = 0
            elif visible_count == 2:
                spacing = 1
            elif visible_count == 3:
                spacing = 2
            else:
                spacing = 3

            self._content_layout.setSpacing(spacing)

            if hasattr(self, "_content_widget_layout"):
                self._content_widget_layout.setContentsMargins(0, 0, 0, 0)
                self._content_widget_layout.setSpacing(0)
        else:
            self._content_layout.setSpacing(5)
            if hasattr(self, "_content_widget_layout"):
                self._content_widget_layout.setContentsMargins(0, 2, 0, 0)
                self._content_widget_layout.setSpacing(0)

    def _apply_geometry_constraints(self) -> None:
        resolved_height = self._resolved_height()

        self.setSizePolicy(self._resolved_size_policy())

        if self._compact or self._fixed_height_requested is not None:
            self.setMinimumHeight(resolved_height)
            self.setMaximumHeight(resolved_height)
        else:
            self.setMinimumHeight(resolved_height)
            self.setMaximumHeight(16777215)

        self._accent_bar.setFixedWidth(self._accent_width())
        self._icon_wrap.setFixedSize(self._icon_box_size(), self._icon_box_size())
        self._icon_label.setFixedSize(self._icon_inner_size(), self._icon_inner_size())

        self._shell.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._content_col.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._content_widget_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._subtitle_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._body_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._footer_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self._sync_content_density()
        self.updateGeometry()

    def sizeHint(self) -> QSize:  # noqa: N802
        if self._ultra_compact:
            return QSize(180, self._resolved_height())
        return QSize(280 if not self._compact else 220, self._resolved_height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        if self._ultra_compact:
            return QSize(120, self._resolved_height())
        return QSize(180 if not self._compact else 150, self._resolved_height())

    # ========================================================
    # UI building
    # ========================================================

    def _build_ui(self) -> None:
        self.setObjectName("GlassCard")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setSizePolicy(self._resolved_size_policy())

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Accent rail
        self._accent_bar = QFrame(self)
        self._accent_bar.setObjectName("GlassCardAccentBar")
        self._accent_bar.setFixedWidth(self._accent_width())

        # Main content shell
        self._shell = QFrame(self)
        self._shell.setObjectName("GlassCardShell")
        self._shell.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._shell.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        shell_layout = QHBoxLayout(self._shell)
        left, top, right, bottom = self._content_inner_margins()
        shell_layout.setContentsMargins(left, top, right, bottom)
        shell_layout.setSpacing(self._content_row_spacing())
        shell_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Icon area
        self._icon_wrap = QFrame(self._shell)
        self._icon_wrap.setObjectName("GlassCardIconWrap")
        self._icon_wrap.setFixedSize(self._icon_box_size(), self._icon_box_size())
        self._icon_wrap.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        icon_layout = QVBoxLayout(self._icon_wrap)
        icon_layout.setContentsMargins(5 if self._ultra_compact else 8, 5 if self._ultra_compact else 8, 5 if self._ultra_compact else 8, 5 if self._ultra_compact else 8)
        icon_layout.setSpacing(0)

        self._icon_label = QLabel(self._icon_wrap)
        self._icon_label.setObjectName("GlassCardIconLabel")
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.setFixedSize(self._icon_inner_size(), self._icon_inner_size())
        self._icon_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        icon_layout.addStretch(1)
        icon_layout.addWidget(self._icon_label, alignment=Qt.AlignmentFlag.AlignCenter)
        icon_layout.addStretch(1)

        # Text/content area
        self._content_col = QWidget(self._shell)
        self._content_col.setObjectName("GlassCardContentColumn")
        self._content_col.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._content_layout = QVBoxLayout(self._content_col)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(2 if self._ultra_compact else (5 if not self._compact else 3))
        self._content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._title_label = QLabel(self._content_col)
        self._title_label.setObjectName("GlassCardTitle")
        self._title_label.setWordWrap(True)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._subtitle_label = QLabel(self._content_col)
        self._subtitle_label.setObjectName("GlassCardSubtitle")
        self._subtitle_label.setWordWrap(True)
        self._subtitle_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._body_label = QLabel(self._content_col)
        self._body_label.setObjectName("GlassCardBody")
        self._body_label.setWordWrap(True)
        self._body_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._content_widget_container = QWidget(self._content_col)
        self._content_widget_container.setObjectName("GlassCardContentWidgetContainer")
        self._content_widget_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._content_widget_layout = QVBoxLayout(self._content_widget_container)
        self._content_widget_layout.setContentsMargins(0, 2, 0, 0)
        self._content_widget_layout.setSpacing(0)
        self._content_widget_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._footer_label = QLabel(self._content_col)
        self._footer_label.setObjectName("GlassCardFooter")
        self._footer_label.setWordWrap(True)
        self._footer_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._content_layout.addWidget(self._title_label)
        self._content_layout.addWidget(self._subtitle_label)
        self._content_layout.addWidget(self._body_label)
        self._content_layout.addWidget(self._content_widget_container)
        self._content_layout.addWidget(self._footer_label)

        shell_layout.addWidget(self._icon_wrap, 0, alignment=Qt.AlignmentFlag.AlignTop)
        shell_layout.addWidget(self._content_col, 1, alignment=Qt.AlignmentFlag.AlignTop)

        outer.addWidget(self._accent_bar)
        outer.addWidget(self._shell, 1)

    # ========================================================
    # Styling
    # ========================================================

    def _apply_base_style(self) -> None:
        radius = 14 if self._ultra_compact else (26 if not self._compact else 18)
        shell_radius = radius
        accent_radius = max(4, shell_radius - 3)

        style = f"""
        QFrame#GlassCard {{
            background: transparent;
            border: none;
        }}

        QFrame#GlassCardAccentBar {{
            background-color: {self._theme.accent_color};
            border-top-left-radius: {accent_radius}px;
            border-bottom-left-radius: {accent_radius}px;
            border-top-right-radius: 2px;
            border-bottom-right-radius: 2px;
        }}

        QFrame#GlassCardShell {{
            border: 1px solid {self._theme.border_color};
            border-top-right-radius: {shell_radius}px;
            border-bottom-right-radius: {shell_radius}px;
            border-top-left-radius: {max(10, shell_radius - 4)}px;
            border-bottom-left-radius: {max(10, shell_radius - 4)}px;
            background: qlineargradient(
                x1:0, y1:0, x2:1, y2:1,
                stop:0 {self._theme.background_top},
                stop:1 {self._theme.background_bottom}
            );
        }}

        QFrame#GlassCardIconWrap {{
            border: 1px solid {self._theme.border_color};
            border-radius: {10 if self._ultra_compact else (18 if not self._compact else 13)}px;
            background-color: {self._theme.icon_bg};
        }}

        QLabel#GlassCardTitle {{
            color: {self._theme.title_color};
            font-size: {12 if self._ultra_compact else (18 if not self._compact else 14)}px;
            font-weight: 700;
            background: transparent;
        }}

        QLabel#GlassCardSubtitle {{
            color: {self._theme.subtitle_color};
            font-size: {8 if self._ultra_compact else (11 if not self._compact else 9)}px;
            font-weight: 500;
            background: transparent;
        }}

        QLabel#GlassCardBody {{
            color: {self._theme.body_color};
            font-size: {9 if self._ultra_compact else (12 if not self._compact else 10)}px;
            font-weight: 500;
            background: transparent;
        }}

        QLabel#GlassCardFooter {{
            color: {self._theme.footer_color};
            font-size: {7 if self._ultra_compact else (10 if not self._compact else 8)}px;
            font-weight: 500;
            background: transparent;
        }}
        """
        self.setStyleSheet(style)

        self.setCursor(
            Qt.CursorShape.PointingHandCursor
            if self._clickable
            else Qt.CursorShape.ArrowCursor
        )

        self._accent_bar.setVisible(self._show_accent_bar)

    def _apply_shadow(self) -> None:
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(14 if self._ultra_compact else (28 if not self._compact else 18))
        shadow.setOffset(0, 3 if self._ultra_compact else (8 if not self._compact else 5))

        color = QColor(self._theme.shadow_color_hex)
        color.setAlpha(40 if self._ultra_compact else (70 if not self._compact else 54))
        shadow.setColor(color)

        self.setGraphicsEffect(shadow)
        self._shadow_effect = shadow

    def _set_shadow_strength(self, hovered: bool) -> None:
        if self._shadow_effect is None:
            return

        if hovered:
            self._shadow_effect.setBlurRadius(20 if self._ultra_compact else (38 if not self._compact else 24))
            self._shadow_effect.setOffset(0, 5 if self._ultra_compact else (12 if not self._compact else 7))
            color = QColor(self._theme.shadow_color_hex)
            color.setAlpha(58 if self._ultra_compact else (115 if not self._compact else 74))
            self._shadow_effect.setColor(color)
        else:
            self._shadow_effect.setBlurRadius(14 if self._ultra_compact else (28 if not self._compact else 18))
            self._shadow_effect.setOffset(0, 3 if self._ultra_compact else (8 if not self._compact else 5))
            color = QColor(self._theme.shadow_color_hex)
            color.setAlpha(40 if self._ultra_compact else (70 if not self._compact else 54))
            self._shadow_effect.setColor(color)

    # ========================================================
    # Content visibility
    # ========================================================

    def _refresh_visibility(self) -> None:
        self._title_label.setVisible(bool(self._title_label.text().strip()))
        self._subtitle_label.setVisible(bool(self._subtitle_label.text().strip()))
        self._body_label.setVisible(bool(self._body_label.text().strip()))
        self._footer_label.setVisible(bool(self._footer_label.text().strip()))

        icon_pm = self._icon_label.pixmap()
        self._icon_wrap.setVisible(bool(icon_pm is not None and not icon_pm.isNull()))

        has_content_widget = self._content_widget_layout.count() > 0
        self._content_widget_container.setVisible(has_content_widget)

        self._sync_content_density()
        self._apply_geometry_constraints()

    # ========================================================
    # Public content setters
    # ========================================================

    def set_title(self, title: str) -> None:
        self._title_label.setText(str(title or "").strip())
        self._refresh_visibility()

    def title(self) -> str:
        return self._title_label.text()

    def set_subtitle(self, subtitle: str) -> None:
        self._subtitle_label.setText(str(subtitle or "").strip())
        self._refresh_visibility()

    def subtitle(self) -> str:
        return self._subtitle_label.text()

    def set_body(self, body: str) -> None:
        self._body_label.setText(str(body or "").strip())
        self._refresh_visibility()

    def body(self) -> str:
        return self._body_label.text()

    def set_footer(self, footer: str) -> None:
        self._footer_label.setText(str(footer or "").strip())
        self._refresh_visibility()

    def footer(self) -> str:
        return self._footer_label.text()

    def set_icon(self, icon_path: str | Path) -> None:
        path = Path(str(icon_path or "")).expanduser() if icon_path else None
        pixmap = QPixmap()

        if path and path.exists() and path.is_file():
            pixmap = QPixmap(str(path))

        if pixmap.isNull():
            self._icon_label.clear()
            self._refresh_visibility()
            return

        target_size = 20 if self._ultra_compact else (28 if self._compact else 36)
        scaled = pixmap.scaled(
            QSize(target_size, target_size),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._icon_label.setPixmap(scaled)
        self._refresh_visibility()

    def clear_icon(self) -> None:
        self._icon_label.clear()
        self._refresh_visibility()

    def set_accent_color(self, color: str) -> None:
        color = str(color or "").strip()
        if not color:
            return

        self._theme = GlassCardTheme(
            accent_color=color,
            accent_soft_color=self._rgba_from_hex(color, 0.20),
            border_color=self._rgba_from_hex(color, 0.28),
            background_top=self._theme.background_top,
            background_bottom=self._theme.background_bottom,
            title_color=self._theme.title_color,
            subtitle_color=self._theme.subtitle_color,
            body_color=self._theme.body_color,
            footer_color=self._theme.footer_color,
            icon_bg=self._rgba_from_hex(color, 0.18),
            shadow_color_hex=color,
        )
        self._apply_base_style()
        self._set_shadow_strength(self._hovered)
        self.update()

    def set_clickable(self, clickable: bool) -> None:
        self._clickable = bool(clickable)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor
            if self._clickable
            else Qt.CursorShape.ArrowCursor
        )

    def set_content_widget(self, widget: Optional[QWidget]) -> None:
        self.clear_content_widget()
        if widget is None:
            self._refresh_visibility()
            return

        if widget.parent() is not None and widget.parent() is not self._content_widget_container:
            widget.setParent(None)

        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._content_widget_layout.addWidget(widget, 0, alignment=Qt.AlignmentFlag.AlignTop)
        self._refresh_visibility()

    def clear_content_widget(self) -> None:
        while self._content_widget_layout.count():
            item = self._content_widget_layout.takeAt(0)
            child = item.widget()
            if child is not None:
                child.setParent(None)
        self._refresh_visibility()


    def set_compact(self, compact: bool) -> None:
        self._compact = bool(compact or IS_COMPACT_KIOSK)
        self._ultra_compact = bool(self._compact and KIOSK_WIDTH <= 800 and KIOSK_HEIGHT <= 480)
        self._apply_geometry_constraints()
        self._apply_base_style()
        self._apply_shadow()
        self._refresh_visibility()

    def compact(self) -> bool:
        return bool(self._compact)

    # ========================================================
    # Hover / click feedback
    # ========================================================

    def enterEvent(self, event: QEvent) -> None:
        super().enterEvent(event)
        self._hovered = True
        self.hover_entered.emit()

        if self._enable_hover_effect and not self._compact:
            self._animate_hover(True)
            self._set_shadow_strength(True)

    def leaveEvent(self, event: QEvent) -> None:
        super().leaveEvent(event)
        self._hovered = False
        self.hover_left.emit()

        if self._enable_hover_effect and not self._compact:
            self._animate_hover(False)
            self._set_shadow_strength(False)

    def mousePressEvent(self, event: Optional[QMouseEvent]) -> None:
        super().mousePressEvent(event)
        if not self._clickable:
            return

        if event is not None and event.button() != Qt.MouseButton.LeftButton:
            return

        self._pressed = True
        self.pressed.emit()
        if not self._compact:
            self._animate_press(True)

    def mouseReleaseEvent(self, event: Optional[QMouseEvent]) -> None:
        super().mouseReleaseEvent(event)
        was_pressed = self._pressed
        self._pressed = False

        if not self._clickable:
            return

        if not self._compact:
            self._animate_press(False)
        self.released.emit()

        if was_pressed and event is not None:
            point = event.position().toPoint() if hasattr(event, "position") else event.pos()
            if self.rect().contains(point):
                self.clicked.emit()

    def _is_layout_managed(self) -> bool:
        parent = self.parentWidget()
        if parent is None:
            return False
        return parent.layout() is not None

    def _animate_hover(self, hovered: bool) -> None:
        """
        Slight vertical lift on hover.
        Avoid position animation when controlled by a layout.
        """
        if self._is_layout_managed():
            if self._animation_manager is not None and hovered:
                try:
                    self._animation_manager.animate_glow_once(
                        self,
                        duration_ms=220,
                        color=QColor(self._theme.shadow_color_hex),
                        tag="glass_card_hover",
                    )
                except Exception:
                    pass
            return

        if self._base_pos is None:
            self._base_pos = self.pos()

        if self._press_anim is not None:
            try:
                self._press_anim.stop()
            except Exception:
                pass

        start_pos = self.pos()
        end_pos = self._base_pos if not hovered else QPoint(self._base_pos.x(), self._base_pos.y() - 3)

        if self._hover_anim is not None:
            try:
                self._hover_anim.stop()
            except Exception:
                pass

        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(150)
        anim.setStartValue(start_pos)
        anim.setEndValue(end_pos)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        self._hover_anim = anim

        if self._animation_manager is not None and hovered:
            try:
                self._animation_manager.animate_glow_once(
                    self,
                    duration_ms=220,
                    color=QColor(self._theme.shadow_color_hex),
                    tag="glass_card_hover",
                )
            except Exception:
                pass

    def _animate_press(self, pressed: bool) -> None:
        if self._is_layout_managed():
            return

        if self._base_pos is None:
            self._base_pos = self.pos()

        if self._hover_anim is not None:
            try:
                self._hover_anim.stop()
            except Exception:
                pass

        hovered_target = QPoint(self._base_pos.x(), self._base_pos.y() - 3) if self._hovered else self._base_pos
        end_pos = QPoint(hovered_target.x(), hovered_target.y() + 2) if pressed else hovered_target

        if self._press_anim is not None:
            try:
                self._press_anim.stop()
            except Exception:
                pass

        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(95 if pressed else 110)
        anim.setStartValue(self.pos())
        anim.setEndValue(end_pos)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        self._press_anim = anim


    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        width = self.width()
        desired_compact = bool(self._compact or IS_COMPACT_KIOSK)
        desired_ultra = bool((desired_compact and KIOSK_WIDTH <= 800 and KIOSK_HEIGHT <= 480) or width <= 210)
        if desired_ultra != self._ultra_compact:
            self._ultra_compact = desired_ultra
            self._apply_geometry_constraints()
            self._apply_base_style()
            self._set_shadow_strength(self._hovered)

    # ========================================================
    # Paint
    # ========================================================

    def paintEvent(self, event) -> None:
        """
        Add subtle top gloss highlight beyond stylesheet-only background.
        """
        super().paintEvent(event)

        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            rect = QRectF(self.rect().adjusted(1, 1, -1, -1))
            if rect.width() <= 4 or rect.height() <= 4:
                return

            shell_rect = QRectF(
                rect.left() + float(self._accent_bar.width()),
                rect.top(),
                max(0.0, rect.width() - float(self._accent_bar.width())),
                rect.height(),
            )

            if shell_rect.width() <= 4 or shell_rect.height() <= 4:
                return

            path = QPainterPath()
            radius = float(14 if self._ultra_compact else (26 if not self._compact else 18))
            path.addRoundedRect(shell_rect, radius, radius)

            gloss_height = shell_rect.height() * (0.26 if self._ultra_compact else (0.42 if not self._compact else 0.34))
            gloss_rect = QRectF(
                shell_rect.left() + 1.0,
                shell_rect.top() + 1.0,
                max(0.0, shell_rect.width() - 2.0),
                max(0.0, gloss_height - 1.0),
            )

            painter.save()
            painter.setClipPath(path)
            gloss = QColor(255, 255, 255, 24 if not self._hovered else 34)
            if self._compact:
                gloss = QColor(255, 255, 255, 12 if self._ultra_compact and not self._hovered else (18 if not self._hovered else 24))
            painter.fillRect(gloss_rect, gloss)

            if self._hovered and not self._compact:
                glow = QColor(self._theme.shadow_color_hex)
                glow.setAlpha(20)
                painter.fillPath(path, glow)
            painter.restore()
        finally:
            painter.end()

    # ========================================================
    # Utility helpers
    # ========================================================

    @staticmethod
    def _rgba_from_hex(color_hex: str, alpha: float) -> str:
        """
        Convert '#RRGGBB' to 'rgba(r,g,b,a)' for Qt stylesheets.
        """
        color = QColor(color_hex)
        alpha = max(0.0, min(float(alpha), 1.0))
        return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha:.3f})"