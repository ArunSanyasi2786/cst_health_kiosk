"""
widgets/animated_button.py

Premium animated button widget for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is one of the most reused interactive widgets across the entire kiosk
- It provides the polished futuristic medical-button feel required by the project
- It is designed for:
    - welcome screen primary actions
    - mode selection buttons
    - admin navigation buttons
    - save / reset / export / publish buttons
    - QR / consult / report quick actions
    - settings and calibration actions
- It centralizes hover, press, glow, icon, and loading behavior so screens remain consistent

Design goals:
- premium glossy UI
- smooth hover and press feedback
- optional icon support
- optional loading/spinner text state
- safe performance on Raspberry Pi and laptop demo
- easy reuse from every screen
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
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QMouseEvent, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from core.logger import get_logger

logger = get_logger(__name__)

try:
    from config import BUTTON_CLICK_ANIMATION_MS
except Exception:  # pragma: no cover
    BUTTON_CLICK_ANIMATION_MS = 140

try:
    from core.animation_manager import get_animation_manager
except Exception:  # pragma: no cover
    get_animation_manager = None  # type: ignore


# ============================================================
# Theme dataclasses
# ============================================================

@dataclass(frozen=True)
class AnimatedButtonTheme:
    """
    Visual theme for one button style.
    """
    bg_top: str
    bg_bottom: str
    bg_hover_top: str
    bg_hover_bottom: str
    bg_pressed_top: str
    bg_pressed_bottom: str
    border_color: str
    border_hover_color: str
    text_color: str
    icon_tint_hint: str
    glow_hex: str
    disabled_bg_top: str
    disabled_bg_bottom: str
    disabled_border: str
    disabled_text: str


def _default_primary_theme() -> AnimatedButtonTheme:
    return AnimatedButtonTheme(
        bg_top="rgba(41, 134, 255, 0.95)",
        bg_bottom="rgba(12, 92, 224, 0.95)",
        bg_hover_top="rgba(62, 154, 255, 0.98)",
        bg_hover_bottom="rgba(24, 108, 236, 0.98)",
        bg_pressed_top="rgba(18, 96, 230, 0.98)",
        bg_pressed_bottom="rgba(8, 72, 190, 0.98)",
        border_color="rgba(162, 223, 255, 0.55)",
        border_hover_color="rgba(196, 236, 255, 0.85)",
        text_color="#F8FDFF",
        icon_tint_hint="#F8FDFF",
        glow_hex="#35D6FF",
        disabled_bg_top="rgba(56, 77, 101, 0.72)",
        disabled_bg_bottom="rgba(39, 57, 79, 0.72)",
        disabled_border="rgba(128, 152, 177, 0.25)",
        disabled_text="rgba(211, 224, 238, 0.52)",
    )


def _default_secondary_theme() -> AnimatedButtonTheme:
    return AnimatedButtonTheme(
        bg_top="rgba(23, 45, 79, 0.85)",
        bg_bottom="rgba(13, 28, 52, 0.88)",
        bg_hover_top="rgba(35, 62, 102, 0.90)",
        bg_hover_bottom="rgba(18, 37, 67, 0.92)",
        bg_pressed_top="rgba(15, 33, 58, 0.95)",
        bg_pressed_bottom="rgba(10, 24, 44, 0.96)",
        border_color="rgba(123, 197, 255, 0.32)",
        border_hover_color="rgba(151, 214, 255, 0.55)",
        text_color="#EAF6FF",
        icon_tint_hint="#EAF6FF",
        glow_hex="#2ABEF0",
        disabled_bg_top="rgba(44, 57, 74, 0.70)",
        disabled_bg_bottom="rgba(29, 39, 53, 0.72)",
        disabled_border="rgba(116, 135, 155, 0.20)",
        disabled_text="rgba(207, 219, 232, 0.48)",
    )


def _default_ghost_theme() -> AnimatedButtonTheme:
    return AnimatedButtonTheme(
        bg_top="rgba(255, 255, 255, 0.06)",
        bg_bottom="rgba(255, 255, 255, 0.04)",
        bg_hover_top="rgba(71, 172, 255, 0.14)",
        bg_hover_bottom="rgba(40, 125, 220, 0.12)",
        bg_pressed_top="rgba(24, 96, 181, 0.18)",
        bg_pressed_bottom="rgba(18, 70, 140, 0.16)",
        border_color="rgba(150, 212, 255, 0.22)",
        border_hover_color="rgba(176, 226, 255, 0.48)",
        text_color="#E7F5FF",
        icon_tint_hint="#E7F5FF",
        glow_hex="#34CCFF",
        disabled_bg_top="rgba(255, 255, 255, 0.03)",
        disabled_bg_bottom="rgba(255, 255, 255, 0.02)",
        disabled_border="rgba(150, 170, 190, 0.14)",
        disabled_text="rgba(205, 215, 225, 0.42)",
    )


def _default_success_theme() -> AnimatedButtonTheme:
    return AnimatedButtonTheme(
        bg_top="rgba(44, 192, 120, 0.95)",
        bg_bottom="rgba(20, 154, 92, 0.95)",
        bg_hover_top="rgba(57, 208, 132, 0.98)",
        bg_hover_bottom="rgba(28, 170, 102, 0.98)",
        bg_pressed_top="rgba(20, 155, 96, 0.98)",
        bg_pressed_bottom="rgba(13, 126, 77, 0.98)",
        border_color="rgba(187, 255, 222, 0.45)",
        border_hover_color="rgba(215, 255, 236, 0.78)",
        text_color="#F8FFFC",
        icon_tint_hint="#F8FFFC",
        glow_hex="#3BEB9C",
        disabled_bg_top="rgba(56, 77, 101, 0.72)",
        disabled_bg_bottom="rgba(39, 57, 79, 0.72)",
        disabled_border="rgba(128, 152, 177, 0.25)",
        disabled_text="rgba(211, 224, 238, 0.52)",
    )


def _default_danger_theme() -> AnimatedButtonTheme:
    return AnimatedButtonTheme(
        bg_top="rgba(241, 83, 110, 0.95)",
        bg_bottom="rgba(206, 46, 75, 0.95)",
        bg_hover_top="rgba(248, 101, 126, 0.98)",
        bg_hover_bottom="rgba(221, 57, 88, 0.98)",
        bg_pressed_top="rgba(207, 46, 76, 0.98)",
        bg_pressed_bottom="rgba(174, 35, 62, 0.98)",
        border_color="rgba(255, 200, 210, 0.48)",
        border_hover_color="rgba(255, 228, 234, 0.82)",
        text_color="#FFF9FA",
        icon_tint_hint="#FFF9FA",
        glow_hex="#FF758E",
        disabled_bg_top="rgba(56, 77, 101, 0.72)",
        disabled_bg_bottom="rgba(39, 57, 79, 0.72)",
        disabled_border="rgba(128, 152, 177, 0.25)",
        disabled_text="rgba(211, 224, 238, 0.52)",
    )


# ============================================================
# Main widget
# ============================================================

class AnimatedButton(QPushButton):
    """
    Premium animated button for kiosk screens.

    Main features:
    - icon + text layout inside button
    - hover glow and subtle lift
    - press feedback
    - loading state with animated ellipsis
    - size variants and theme variants
    - safe fallback even if icon/theme manager is unavailable
    """

    hover_entered = pyqtSignal()
    hover_left = pyqtSignal()
    loading_started = pyqtSignal()
    loading_stopped = pyqtSignal()

    VARIANT_PRIMARY = "primary"
    VARIANT_SECONDARY = "secondary"
    VARIANT_GHOST = "ghost"
    VARIANT_SUCCESS = "success"
    VARIANT_DANGER = "danger"

    SIZE_SM = "sm"
    SIZE_MD = "md"
    SIZE_LG = "lg"
    SIZE_XL = "xl"

    def __init__(
        self,
        text: str = "",
        parent: Optional[QWidget] = None,
        *,
        icon_path: str = "",
        variant: str = VARIANT_PRIMARY,
        size: str = SIZE_MD,
        fixed_height: Optional[int] = None,
        minimum_width: int = 0,
        expand: bool = False,
        accent_color: str = "",
        enable_hover_lift: bool = True,
        enable_glow: bool = True,
        enable_press_animation: bool = True,
        loading_text: str = "Loading",
        uppercase: bool = False,
    ) -> None:
        super().__init__(parent)

        try:
            self._logger = logger.bind(component="AnimatedButton")
        except Exception:
            self._logger = logger

        self._variant = str(variant or self.VARIANT_PRIMARY).strip().lower()
        self._size = str(size or self.SIZE_MD).strip().lower()
        self._enable_hover_lift = bool(enable_hover_lift)
        self._enable_glow = bool(enable_glow)
        self._enable_press_animation = bool(enable_press_animation)
        self._loading_text_base = str(loading_text or "Loading").strip() or "Loading"
        self._uppercase = bool(uppercase)

        self._hovered = False
        self._pressed_state = False
        self._loading = False
        self._loading_dots = 0
        self._base_text = str(text or "")
        self._base_icon_path = str(icon_path or "")
        self._base_pos: Optional[QPoint] = None

        self._theme = self._resolve_theme(self._variant, accent_color=accent_color)

        self._shadow_effect: Optional[QGraphicsDropShadowEffect] = None
        self._press_anim: Optional[QPropertyAnimation] = None
        self._loading_timer = QTimer(self)
        self._loading_timer.setInterval(350)
        self._loading_timer.timeout.connect(self._on_loading_tick)

        self._animation_manager = None
        if get_animation_manager is not None:
            try:
                self._animation_manager = get_animation_manager()
            except Exception:
                self._animation_manager = None

        self._build_ui()

        # Keep the native QPushButton text empty so Qt does not paint a second text layer.
        super().setText("")

        self.setText(text)
        self.set_icon(icon_path)
        self.set_variant(self._variant)
        self.set_size(self._size)

        if fixed_height is not None:
            self.setFixedHeight(int(fixed_height))
        if minimum_width > 0:
            self.setMinimumWidth(int(minimum_width))

        if expand:
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        else:
            self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        self._apply_shadow()
        self._apply_style()
        self._sync_label_content()

    # ========================================================
    # UI
    # ========================================================

    def _build_ui(self) -> None:
        self.setObjectName("AnimatedButton")
        self.setCheckable(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.setFlat(True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._container = QWidget(self)
        self._container.setObjectName("AnimatedButtonContainer")
        self._container.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._layout = QHBoxLayout(self._container)
        self._layout.setContentsMargins(14, 8, 14, 8)
        self._layout.setSpacing(8)

        self._layout.addStretch(1)

        self._icon_label = QLabel(self._container)
        self._icon_label.setObjectName("AnimatedButtonIcon")
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._icon_label.setVisible(False)
        self._icon_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self._text_label = QLabel(self._container)
        self._text_label.setObjectName("AnimatedButtonText")
        self._text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._text_label.setWordWrap(False)
        self._text_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self._layout.addWidget(self._icon_label, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self._text_label, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        self._layout.addStretch(1)

        outer.addWidget(self._container, 1)

    # ========================================================
    # Theme / style
    # ========================================================

    def _resolve_theme(self, variant: str, *, accent_color: str = "") -> AnimatedButtonTheme:
        variant = str(variant or self.VARIANT_PRIMARY).strip().lower()

        if variant == self.VARIANT_SECONDARY:
            theme = _default_secondary_theme()
        elif variant == self.VARIANT_GHOST:
            theme = _default_ghost_theme()
        elif variant == self.VARIANT_SUCCESS:
            theme = _default_success_theme()
        elif variant == self.VARIANT_DANGER:
            theme = _default_danger_theme()
        else:
            theme = _default_primary_theme()

        if accent_color:
            color = QColor(accent_color)
            if color.isValid():
                darker = color.darker(120)
                hover = color.lighter(112)
                pressed = color.darker(126)
                return AnimatedButtonTheme(
                    bg_top=self._rgba(color, 0.95),
                    bg_bottom=self._rgba(darker, 0.96),
                    bg_hover_top=self._rgba(hover, 0.98),
                    bg_hover_bottom=self._rgba(color, 0.98),
                    bg_pressed_top=self._rgba(pressed, 0.98),
                    bg_pressed_bottom=self._rgba(darker.darker(108), 0.98),
                    border_color=self._rgba(color.lighter(170), 0.45),
                    border_hover_color=self._rgba(color.lighter(210), 0.82),
                    text_color="#F8FDFF",
                    icon_tint_hint="#F8FDFF",
                    glow_hex=color.name(),
                    disabled_bg_top="rgba(56, 77, 101, 0.72)",
                    disabled_bg_bottom="rgba(39, 57, 79, 0.72)",
                    disabled_border="rgba(128, 152, 177, 0.25)",
                    disabled_text="rgba(211, 224, 238, 0.52)",
                )
        return theme

    def _apply_style(self) -> None:
        radius = self._radius_for_size(self._size)

        if not self.isEnabled():
            bg_top = self._theme.disabled_bg_top
            bg_bottom = self._theme.disabled_bg_bottom
            border = self._theme.disabled_border
            text_color = self._theme.disabled_text
        elif self._pressed_state:
            bg_top = self._theme.bg_pressed_top
            bg_bottom = self._theme.bg_pressed_bottom
            border = self._theme.border_hover_color
            text_color = self._theme.text_color
        elif self._hovered:
            bg_top = self._theme.bg_hover_top
            bg_bottom = self._theme.bg_hover_bottom
            border = self._theme.border_hover_color
            text_color = self._theme.text_color
        else:
            bg_top = self._theme.bg_top
            bg_bottom = self._theme.bg_bottom
            border = self._theme.border_color
            text_color = self._theme.text_color

        style = f"""
        QPushButton#AnimatedButton {{
            border: 1px solid {border};
            border-radius: {radius}px;
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {bg_top},
                stop:1 {bg_bottom}
            );
            padding: 0px;
        }}

        QPushButton#AnimatedButton:focus {{
            outline: none;
        }}

        QLabel#AnimatedButtonText {{
            color: {text_color};
            font-weight: 700;
            background: transparent;
        }}

        QLabel#AnimatedButtonIcon {{
            background: transparent;
        }}

        QWidget#AnimatedButtonContainer {{
            background: transparent;
        }}
        """
        self.setStyleSheet(style)
        self._apply_text_font()

    def _apply_shadow(self) -> None:
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 7)

        glow = QColor(self._theme.glow_hex)
        glow.setAlpha(70)
        shadow.setColor(glow)

        self.setGraphicsEffect(shadow)
        self._shadow_effect = shadow

    def _set_shadow_state(self, hovered: bool, pressed: bool = False) -> None:
        if self._shadow_effect is None:
            return

        glow = QColor(self._theme.glow_hex)

        if not self.isEnabled():
            glow.setAlpha(35)
            self._shadow_effect.setColor(glow)
            self._shadow_effect.setBlurRadius(14)
            self._shadow_effect.setOffset(0, 4)
            return

        if pressed:
            glow.setAlpha(110)
            self._shadow_effect.setColor(glow)
            self._shadow_effect.setBlurRadius(20)
            self._shadow_effect.setOffset(0, 5)
            return

        if hovered:
            glow.setAlpha(125)
            self._shadow_effect.setColor(glow)
            self._shadow_effect.setBlurRadius(34)
            self._shadow_effect.setOffset(0, 10)
            return

        glow.setAlpha(70)
        self._shadow_effect.setColor(glow)
        self._shadow_effect.setBlurRadius(24)
        self._shadow_effect.setOffset(0, 7)

    # ========================================================
    # Size helpers
    # ========================================================

    def _height_for_size(self, size: str) -> int:
        if size == self.SIZE_SM:
            return 38
        if size == self.SIZE_LG:
            return 52
        if size == self.SIZE_XL:
            return 60
        return 44

    def _icon_size_for_size(self, size: str) -> int:
        if size == self.SIZE_SM:
            return 16
        if size == self.SIZE_LG:
            return 22
        if size == self.SIZE_XL:
            return 24
        return 18

    def _font_size_for_size(self, size: str) -> int:
        if size == self.SIZE_SM:
            return 11
        if size == self.SIZE_LG:
            return 14
        if size == self.SIZE_XL:
            return 15
        return 12

    def _minimum_font_size_for_size(self, size: str) -> int:
        if size == self.SIZE_SM:
            return 9
        if size == self.SIZE_LG:
            return 11
        if size == self.SIZE_XL:
            return 12
        return 10

    def _radius_for_size(self, size: str) -> int:
        if size == self.SIZE_SM:
            return 14
        if size == self.SIZE_LG:
            return 18
        if size == self.SIZE_XL:
            return 20
        return 16

    def _padding_for_size(self, size: str) -> tuple[int, int]:
        if size == self.SIZE_SM:
            return (12, 6)
        if size == self.SIZE_LG:
            return (18, 9)
        if size == self.SIZE_XL:
            return (20, 11)
        return (15, 8)

    def set_size(self, size: str) -> None:
        self._size = str(size or self.SIZE_MD).strip().lower()
        if self._size not in {self.SIZE_SM, self.SIZE_MD, self.SIZE_LG, self.SIZE_XL}:
            self._size = self.SIZE_MD

        h = self._height_for_size(self._size)
        self.setFixedHeight(h)

        px, py = self._padding_for_size(self._size)
        self._layout.setContentsMargins(px, py, px, py)
        self._layout.setSpacing(8 if self._size in {self.SIZE_MD, self.SIZE_LG, self.SIZE_XL} else 6)

        self._sync_label_content()
        self._apply_style()
        self.update()

    def size_variant(self) -> str:
        return self._size

    # ========================================================
    # Text / icon content
    # ========================================================

    def setText(self, text: str) -> None:  # noqa: N802
        self._base_text = str(text or "")
        super().setText("")
        self.setToolTip(self._base_text)
        self._sync_label_content()

    def text(self) -> str:  # noqa: A003, N802
        return self._base_text

    def set_icon(self, icon_path: str | Path) -> None:
        self._base_icon_path = str(icon_path or "")
        self._sync_icon()

    def clear_icon(self) -> None:
        self._base_icon_path = ""
        self._icon_label.clear()
        self._icon_label.setVisible(False)
        self._apply_text_font()

    def _sync_icon(self) -> None:
        icon_path = Path(self._base_icon_path).expanduser() if self._base_icon_path else None
        pixmap = QPixmap()

        if icon_path and icon_path.exists() and icon_path.is_file():
            pixmap = QPixmap(str(icon_path))

        if pixmap.isNull():
            self._icon_label.clear()
            self._icon_label.setVisible(False)
            self._apply_text_font()
            return

        target = self._icon_size_for_size(self._size)
        scaled = pixmap.scaled(
            QSize(target, target),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._icon_label.setPixmap(scaled)
        self._icon_label.setFixedSize(target + 4, target + 4)
        self._icon_label.setVisible(True)
        self._apply_text_font()

    def _sync_label_content(self) -> None:
        label_text = self._display_text()
        if self._uppercase:
            label_text = label_text.upper()
        self._text_label.setText(label_text)
        self._sync_icon()
        self._apply_style()

    def _display_text(self) -> str:
        if self._loading:
            dots = "." * self._loading_dots
            return f"{self._loading_text_base}{dots}"
        return self._base_text

    def _available_text_width(self) -> int:
        left, _, right, _ = self._layout.getContentsMargins()
        spacing = self._layout.spacing()

        available = self.width() - left - right

        if self._icon_label.isVisible():
            available -= self._icon_label.width()
            available -= spacing

        available -= 32  # center stretch and safe visual buffer
        return max(36, available)

    def _apply_text_font(self) -> None:
        text = self._text_label.text()
        base_size = self._font_size_for_size(self._size)
        min_size = self._minimum_font_size_for_size(self._size)

        font = QFont(self._text_label.font())
        font.setBold(True)

        available = self._available_text_width()

        chosen_size = base_size
        fitted_text = text

        for pixel_size in range(base_size, min_size - 1, -1):
            test_font = QFont(font)
            test_font.setPixelSize(pixel_size)
            metrics = QFontMetrics(test_font)
            if metrics.horizontalAdvance(text) <= available:
                chosen_size = pixel_size
                fitted_text = text
                break
        else:
            fallback_font = QFont(font)
            fallback_font.setPixelSize(min_size)
            metrics = QFontMetrics(fallback_font)
            fitted_text = metrics.elidedText(text, Qt.TextElideMode.ElideRight, available)
            chosen_size = min_size

        font.setPixelSize(chosen_size)
        self._text_label.setFont(font)
        self._text_label.setText(fitted_text)

    # ========================================================
    # Variant / behavior setters
    # ========================================================

    def set_variant(self, variant: str, *, accent_color: str = "") -> None:
        self._variant = str(variant or self.VARIANT_PRIMARY).strip().lower()
        self._theme = self._resolve_theme(self._variant, accent_color=accent_color)
        self._apply_style()
        self._set_shadow_state(self._hovered, self._pressed_state)
        self.update()

    def variant(self) -> str:
        return self._variant

    def set_accent_color(self, accent_color: str) -> None:
        self._theme = self._resolve_theme(self._variant, accent_color=accent_color)
        self._apply_style()
        self._set_shadow_state(self._hovered, self._pressed_state)
        self.update()

    def set_loading_text(self, loading_text: str) -> None:
        self._loading_text_base = str(loading_text or "Loading").strip() or "Loading"
        if self._loading:
            self._sync_label_content()

    # ========================================================
    # Loading state
    # ========================================================

    def start_loading(self, loading_text: Optional[str] = None, disable_button: bool = True) -> None:
        if loading_text is not None:
            self._loading_text_base = str(loading_text or "Loading").strip() or "Loading"

        self._loading = True
        self._loading_dots = 0
        if disable_button:
            self.setEnabled(False)

        self._loading_timer.start()
        self._sync_label_content()
        self.loading_started.emit()

    def stop_loading(self, enable_button: bool = True) -> None:
        self._loading = False
        self._loading_dots = 0
        self._loading_timer.stop()

        if enable_button:
            self.setEnabled(True)

        self._sync_label_content()
        self.loading_stopped.emit()

    def is_loading(self) -> bool:
        return self._loading

    def _on_loading_tick(self) -> None:
        self._loading_dots = (self._loading_dots + 1) % 4
        self._sync_label_content()

    # ========================================================
    # Hover / press animation
    # ========================================================

    def enterEvent(self, event: QEvent) -> None:
        super().enterEvent(event)
        self._hovered = True
        self.hover_entered.emit()

        if self._enable_hover_lift:
            self._animate_lift(True)
        self._set_shadow_state(True, self._pressed_state)
        self._apply_style()

        if self._enable_glow and self._animation_manager is not None and self.isEnabled():
            try:
                self._animation_manager.animate_glow_once(
                    self,
                    duration_ms=220,
                    color=QColor(self._theme.glow_hex),
                    tag="animated_button_hover",
                )
            except Exception:
                pass

    def leaveEvent(self, event: QEvent) -> None:
        super().leaveEvent(event)
        self._hovered = False
        self.hover_left.emit()

        if self._enable_hover_lift:
            self._animate_lift(False)
        self._set_shadow_state(False, self._pressed_state)
        self._apply_style()

    def mousePressEvent(self, event: Optional[QMouseEvent]) -> None:
        if event is not None and event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        self._pressed_state = True
        self._set_shadow_state(self._hovered, True)
        self._apply_style()

        if self._enable_press_animation:
            self._animate_press(True)

        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: Optional[QMouseEvent]) -> None:
        self._pressed_state = False
        self._set_shadow_state(self._hovered, False)
        self._apply_style()

        if self._enable_press_animation:
            self._animate_press(False)

        super().mouseReleaseEvent(event)

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802
        super().setEnabled(enabled)
        if not enabled:
            self._pressed_state = False
            self._hovered = False
        self._set_shadow_state(self._hovered, self._pressed_state)
        self._apply_style()

    def _is_layout_managed(self) -> bool:
        parent = self.parentWidget()
        if parent is None:
            return False
        return parent.layout() is not None

    def _animate_lift(self, hovered: bool) -> None:
        if self._is_layout_managed():
            return

        if self._base_pos is None:
            self._base_pos = self.pos()

        target = self._base_pos if not hovered else QPoint(self._base_pos.x(), self._base_pos.y() - 2)
        self._start_pos_animation(target, duration=140)

    def _animate_press(self, pressed: bool) -> None:
        if self._is_layout_managed():
            return

        if self._base_pos is None:
            self._base_pos = self.pos()

        hovered_base = QPoint(self._base_pos.x(), self._base_pos.y() - 2) if self._hovered else self._base_pos
        target = QPoint(hovered_base.x(), hovered_base.y() + 2) if pressed else hovered_base
        self._start_pos_animation(target, duration=BUTTON_CLICK_ANIMATION_MS)

    def _start_pos_animation(self, target: QPoint, duration: int) -> None:
        if self._press_anim is not None:
            try:
                self._press_anim.stop()
            except Exception:
                pass

        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(max(70, int(duration)))
        anim.setStartValue(self.pos())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        self._press_anim = anim

    # ========================================================
    # Resize / paint extras
    # ========================================================

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_text_font()

    def paintEvent(self, event) -> None:
        """
        Add subtle glossy highlight on top of the stylesheet background.
        Uses QRectF and guarantees painter cleanup.
        """
        super().paintEvent(event)

        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

            rect = QRectF(self.rect().adjusted(1, 1, -1, -1))
            if rect.width() <= 4.0 or rect.height() <= 4.0:
                return

            radius = float(self._radius_for_size(self._size))

            path = QPainterPath()
            path.addRoundedRect(rect, radius, radius)

            gloss_height = rect.height() * 0.46
            gloss_rect = QRectF(
                rect.left() + 2.0,
                rect.top() + 2.0,
                max(0.0, rect.width() - 4.0),
                max(0.0, gloss_height - 2.0),
            )

            gloss_alpha = 28
            if self._hovered:
                gloss_alpha = 40
            if self._pressed_state:
                gloss_alpha = 18
            if not self.isEnabled():
                gloss_alpha = 10

            painter.save()
            painter.setClipPath(path)
            painter.fillRect(gloss_rect, QColor(255, 255, 255, gloss_alpha))

            if self._hovered and self.isEnabled():
                glow = QColor(self._theme.glow_hex)
                glow.setAlpha(14)
                painter.fillPath(path, glow)

            painter.restore()

        finally:
            painter.end()

    # ========================================================
    # Utilities
    # ========================================================

    @staticmethod
    def _rgba(color: QColor, alpha: float) -> str:
        alpha = max(0.0, min(float(alpha), 1.0))
        return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha:.3f})"