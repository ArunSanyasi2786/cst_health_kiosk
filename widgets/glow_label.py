"""
widgets/glow_label.py

Premium glowing label widget for the CST Health Monitoring Station kiosk.

Stability-focused version for:
- Raspberry Pi
- laptop demo
- nested custom-painted screens
- safe usage inside parent widgets that may already use effects/animations

Important stability note:
This version defaults to PAINTED glow instead of QGraphicsEffect glow because
nested graphics effects inside complex custom-painted screens can cause labels
to disappear or render inconsistently.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QSequentialAnimationGroup,
    Qt,
    pyqtProperty,
    pyqtSignal,
    QRect,
    QSize,
)
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QFontMetrics
from PyQt6.QtWidgets import QLabel, QGraphicsDropShadowEffect, QSizePolicy, QWidget

from core.logger import get_logger

logger = get_logger(__name__)

try:
    from core.animation_manager import get_animation_manager
except Exception:  # pragma: no cover
    get_animation_manager = None  # type: ignore


@dataclass(frozen=True)
class GlowLabelTheme:
    text_color: str = "#F3FBFF"
    glow_hex: str = "#39D7FF"
    secondary_glow_hex: str = "#8AE8FF"
    outline_hex: str = "rgba(8, 32, 58, 0.45)"
    subtle_fill_hex: str = "rgba(255, 255, 255, 0.02)"
    disabled_text: str = "rgba(220, 232, 245, 0.45)"


DEFAULT_GLOW_LABEL_THEME = GlowLabelTheme()


class GlowLabel(QLabel):
    glow_started = pyqtSignal()
    glow_stopped = pyqtSignal()
    pulse_started = pyqtSignal()
    pulse_stopped = pyqtSignal()
    flashed = pyqtSignal()

    ROLE_TITLE = "title"
    ROLE_SUBTITLE = "subtitle"
    ROLE_STATUS = "status"
    ROLE_BODY = "body"
    ROLE_TINY = "tiny"

    def __init__(
        self,
        text: str = "",
        parent: Optional[QWidget] = None,
        *,
        theme: Optional[GlowLabelTheme] = None,
        glow_color: str = "",
        role: str = ROLE_TITLE,
        align_center: bool = False,
        word_wrap: bool = True,
        use_outline: bool = True,
        enable_paint_glow: bool = True,
        initial_glow_strength: float = 0.72,
        initial_glow_blur: float = 26.0,
        use_graphics_effect_glow: bool = False,
    ) -> None:
        super().__init__(parent)

        self._logger = logger
        self._theme = theme or DEFAULT_GLOW_LABEL_THEME

        if glow_color:
            self._theme = GlowLabelTheme(
                text_color=self._theme.text_color,
                glow_hex=str(glow_color),
                secondary_glow_hex=self._theme.secondary_glow_hex,
                outline_hex=self._theme.outline_hex,
                subtle_fill_hex=self._theme.subtle_fill_hex,
                disabled_text=self._theme.disabled_text,
            )

        self._role = str(role or self.ROLE_TITLE).strip().lower()
        self._use_outline = bool(use_outline)
        self._enable_paint_glow = bool(enable_paint_glow)
        self._use_graphics_effect_glow = bool(use_graphics_effect_glow)

        self._glow_strength: float = max(0.0, min(float(initial_glow_strength), 1.0))
        self._glow_blur_base: float = max(0.0, float(initial_glow_blur))
        self._pulse_active: bool = False

        self._glow_effect: Optional[QGraphicsDropShadowEffect] = None
        self._pulse_group: Optional[QSequentialAnimationGroup] = None
        self._flash_group: Optional[QSequentialAnimationGroup] = None
        self._animation_manager = None

        if get_animation_manager is not None:
            try:
                self._animation_manager = get_animation_manager()
            except Exception:
                self._animation_manager = None

        super().setText(str(text or ""))
        self.setWordWrap(word_wrap)
        self.setAlignment(
            Qt.AlignmentFlag.AlignCenter
            if align_center
            else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.setObjectName("GlowLabel")

        self._rebuild_graphics_effect()
        self._apply_role_style()
        self._apply_shadow_from_strength()
        self.updateGeometry()

    # ------------------------------------------------------------------
    # Graphics effect stability helpers
    # ------------------------------------------------------------------

    def _rebuild_graphics_effect(self) -> None:
        if self._glow_effect is not None:
            try:
                self._glow_effect.deleteLater()
            except Exception:
                pass
            self._glow_effect = None

        self.setGraphicsEffect(None)

        if not self._use_graphics_effect_glow:
            return

        effect = QGraphicsDropShadowEffect(self)
        effect.setOffset(0, 0)
        effect.setBlurRadius(self._glow_blur_base)
        glow = QColor(self._theme.glow_hex)
        glow.setAlpha(120)
        effect.setColor(glow)
        self.setGraphicsEffect(effect)
        self._glow_effect = effect

    def enable_graphics_effect_glow(self) -> None:
        self._use_graphics_effect_glow = True
        self._rebuild_graphics_effect()
        self._apply_shadow_from_strength()

    def disable_graphics_effect_glow(self) -> None:
        self._use_graphics_effect_glow = False
        self._rebuild_graphics_effect()
        self.update()

    # ------------------------------------------------------------------
    # Role / sizing
    # ------------------------------------------------------------------

    def _apply_role_style(self) -> None:
        font = self.font() if self.font() else QFont()
        font.setKerning(True)

        if self._role == self.ROLE_TINY:
            font.setPointSize(9)
            font.setWeight(QFont.Weight.Medium)
            min_h = 18
        elif self._role == self.ROLE_BODY:
            font.setPointSize(11)
            font.setWeight(QFont.Weight.Medium)
            min_h = 24
        elif self._role == self.ROLE_STATUS:
            font.setPointSize(13)
            font.setWeight(QFont.Weight.DemiBold)
            min_h = 28
        elif self._role == self.ROLE_SUBTITLE:
            font.setPointSize(12)
            font.setWeight(QFont.Weight.Medium)
            min_h = 28
        else:
            font.setPointSize(22)
            font.setWeight(QFont.Weight.Bold)
            min_h = 40

        self.setFont(font)
        self.setMinimumHeight(min_h)

        text_color = self._theme.text_color if self.isEnabled() else self._theme.disabled_text
        self.setStyleSheet(
            f"""
            QLabel#GlowLabel {{
                color: {text_color};
                background: transparent;
            }}
            """
        )
        self.updateGeometry()

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return self.wordWrap()

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        text = super().text()
        if not text:
            return super().heightForWidth(width)

        fm = QFontMetrics(self.font())
        flags = int(self.alignment() | Qt.TextFlag.TextWordWrap)
        rect = fm.boundingRect(QRect(0, 0, max(1, width - 12), 10000), flags, text)
        return rect.height() + 12

    def sizeHint(self) -> QSize:  # noqa: N802
        text = super().text()
        if not text:
            return super().sizeHint()

        fm = QFontMetrics(self.font())
        width = max(220, min(760, fm.horizontalAdvance(text) + 28))
        if self.wordWrap():
            height = self.heightForWidth(width)
        else:
            height = max(fm.height() + 10, self.minimumHeight())
        return QSize(width, height)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        fm = QFontMetrics(self.font())
        return QSize(140, max(fm.height() + 10, self.minimumHeight()))

    # ------------------------------------------------------------------
    # Glow state
    # ------------------------------------------------------------------

    def get_glow_strength(self) -> float:
        return self._glow_strength

    def set_glow_strength(self, value: float) -> None:
        self._glow_strength = max(0.0, min(float(value), 1.0))
        self._apply_shadow_from_strength()

    glowStrength = pyqtProperty(float, fget=get_glow_strength, fset=set_glow_strength)

    def _apply_shadow_from_strength(self) -> None:
        if self._glow_effect is None:
            self.update()
            return

        strength = max(0.0, min(self._glow_strength, 1.0))
        glow = QColor(self._theme.glow_hex)
        glow.setAlpha(int(18 + (160 * strength)))

        blur = self._glow_blur_base * (0.55 + strength * 0.95)

        self._glow_effect.setColor(glow)
        self._glow_effect.setBlurRadius(blur)
        self._glow_effect.setOffset(0, 0)
        self.update()

    # ------------------------------------------------------------------
    # Text / pixmap API
    # ------------------------------------------------------------------

    def set_text(self, text: str) -> None:
        super().setText(str(text or ""))
        self.updateGeometry()
        self.update()

    def setText(self, text: str) -> None:  # noqa: N802
        self.set_text(text)

    def text(self) -> str:  # noqa: A003
        return super().text()

    def set_pixmap_from_path(
        self,
        image_path: str | Path,
        *,
        max_width: int = 220,
        max_height: int = 220,
    ) -> None:
        path = Path(str(image_path or "")).expanduser()
        if not path.exists() or not path.is_file():
            self.clear()
            return

        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.clear()
            return

        scaled = pixmap.scaled(
            max_width,
            max_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(scaled)
        self.update()

    def clear_pixmap_and_text(self) -> None:
        self.clear()
        self.update()

    # ------------------------------------------------------------------
    # Theme API
    # ------------------------------------------------------------------

    def set_role(self, role: str) -> None:
        self._role = str(role or self.ROLE_TITLE).strip().lower()
        self._apply_role_style()
        self.update()

    def role(self) -> str:
        return self._role

    def set_glow_color(self, color_hex: str) -> None:
        cleaned = str(color_hex or "").strip()
        if not cleaned:
            return

        self._theme = GlowLabelTheme(
            text_color=self._theme.text_color,
            glow_hex=cleaned,
            secondary_glow_hex=self._theme.secondary_glow_hex,
            outline_hex=self._theme.outline_hex,
            subtle_fill_hex=self._theme.subtle_fill_hex,
            disabled_text=self._theme.disabled_text,
        )
        self._rebuild_graphics_effect()
        self._apply_shadow_from_strength()
        self.update()

    def glow_color(self) -> str:
        return self._theme.glow_hex

    def set_text_color(self, color_hex: str) -> None:
        cleaned = str(color_hex or "").strip()
        if not cleaned:
            return

        self._theme = GlowLabelTheme(
            text_color=cleaned,
            glow_hex=self._theme.glow_hex,
            secondary_glow_hex=self._theme.secondary_glow_hex,
            outline_hex=self._theme.outline_hex,
            subtle_fill_hex=self._theme.subtle_fill_hex,
            disabled_text=self._theme.disabled_text,
        )
        self._apply_role_style()
        self.update()

    def set_outline_enabled(self, enabled: bool) -> None:
        self._use_outline = bool(enabled)
        self.update()

    def outline_enabled(self) -> bool:
        return self._use_outline

    def set_paint_glow_enabled(self, enabled: bool) -> None:
        self._enable_paint_glow = bool(enabled)
        self.update()

    def paint_glow_enabled(self) -> bool:
        return self._enable_paint_glow

    def set_base_glow_blur(self, blur: float) -> None:
        self._glow_blur_base = max(0.0, float(blur))
        self._apply_shadow_from_strength()

    def base_glow_blur(self) -> float:
        return self._glow_blur_base

    # ------------------------------------------------------------------
    # Animations
    # ------------------------------------------------------------------

    def start_glow(self, strength: float = 0.78) -> None:
        self.stop_flash()
        self.set_glow_strength(strength)
        self.glow_started.emit()

    def stop_glow(self) -> None:
        self.stop_pulse()
        self.stop_flash()
        self.set_glow_strength(0.0)
        self.glow_stopped.emit()

    def start_pulse(
        self,
        *,
        duration_ms: int = 1500,
        min_strength: float = 0.28,
        max_strength: float = 0.98,
        loop_forever: bool = True,
    ) -> None:
        self.stop_pulse()
        self.stop_flash()

        min_strength = max(0.0, min(float(min_strength), 1.0))
        max_strength = max(0.0, min(float(max_strength), 1.0))
        if max_strength < min_strength:
            min_strength, max_strength = max_strength, min_strength

        half = max(120, int(duration_ms // 2))

        grow = QPropertyAnimation(self, b"glowStrength", self)
        grow.setDuration(half)
        grow.setStartValue(min_strength)
        grow.setEndValue(max_strength)
        grow.setEasingCurve(QEasingCurve.Type.InOutSine)

        shrink = QPropertyAnimation(self, b"glowStrength", self)
        shrink.setDuration(half)
        shrink.setStartValue(max_strength)
        shrink.setEndValue(min_strength)
        shrink.setEasingCurve(QEasingCurve.Type.InOutSine)

        group = QSequentialAnimationGroup(self)
        group.addAnimation(grow)
        group.addAnimation(shrink)

        if loop_forever:
            group.setLoopCount(-1)

        self._pulse_group = group
        self._pulse_active = True
        self._pulse_group.start()
        self.pulse_started.emit()

    def stop_pulse(self) -> None:
        if self._pulse_group is not None:
            try:
                self._pulse_group.stop()
            except Exception:
                pass
            self._pulse_group.deleteLater()
            self._pulse_group = None

        was_active = self._pulse_active
        self._pulse_active = False

        if was_active:
            self.pulse_stopped.emit()

    def is_pulsing(self) -> bool:
        return self._pulse_active

    def flash_once(
        self,
        *,
        duration_ms: int = 850,
        peak_strength: float = 1.0,
        end_strength: float = 0.58,
    ) -> None:
        self.stop_flash()

        peak_strength = max(0.0, min(float(peak_strength), 1.0))
        end_strength = max(0.0, min(float(end_strength), 1.0))

        up = QPropertyAnimation(self, b"glowStrength", self)
        up.setDuration(max(90, int(duration_ms * 0.35)))
        up.setStartValue(self._glow_strength)
        up.setEndValue(peak_strength)
        up.setEasingCurve(QEasingCurve.Type.OutCubic)

        down = QPropertyAnimation(self, b"glowStrength", self)
        down.setDuration(max(120, int(duration_ms * 0.65)))
        down.setStartValue(peak_strength)
        down.setEndValue(end_strength)
        down.setEasingCurve(QEasingCurve.Type.OutCubic)

        group = QSequentialAnimationGroup(self)
        group.addAnimation(up)
        group.addAnimation(down)
        group.finished.connect(self.flashed.emit)

        self._flash_group = group
        self._flash_group.start()

    def stop_flash(self) -> None:
        if self._flash_group is not None:
            try:
                self._flash_group.stop()
            except Exception:
                pass
            self._flash_group.deleteLater()
            self._flash_group = None

    def start_welcome_pulse(self) -> None:
        self.start_pulse(duration_ms=1500, min_strength=0.34, max_strength=0.98, loop_forever=True)

    def start_status_pulse(self) -> None:
        self.start_pulse(duration_ms=1200, min_strength=0.22, max_strength=0.78, loop_forever=True)

    def flash_success(self) -> None:
        self.flash_once(duration_ms=700, peak_strength=1.0, end_strength=0.55)

    # ------------------------------------------------------------------
    # QWidget overrides
    # ------------------------------------------------------------------

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802
        super().setEnabled(enabled)
        self._apply_role_style()
        self._apply_shadow_from_strength()
        self.update()

    def paintEvent(self, event) -> None:
        pix = self.pixmap()
        has_pixmap = pix is not None and not pix.isNull()

        if has_pixmap:
            super().paintEvent(event)

            if not self._enable_paint_glow:
                return

            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            rect = self.rect().adjusted(3, 3, -3, -3)
            color = QColor(self._theme.glow_hex)
            color.setAlpha(int(8 + 22 * self._glow_strength))
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, 20, 20)
            painter.end()
            return

        text = super().text()
        if not text:
            super().paintEvent(event)
            return

        if not self._enable_paint_glow:
            super().paintEvent(event)
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        rect = self.rect().adjusted(4, 0, -4, 0)
        alignment = self.alignment()
        font = self.font()

        if self._glow_strength > 0.02:
            fill_color = QColor(255, 255, 255, int(2 + 7 * self._glow_strength))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill_color)
            painter.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 12, 12)

        if self._glow_strength > 0.02:
            glow_color = QColor(self._theme.secondary_glow_hex)
            glow_color.setAlpha(int(12 + 42 * self._glow_strength))
            painter.setFont(font)
            pen = QPen(glow_color)
            pen.setWidth(1)
            painter.setPen(pen)

            offsets = [
                (-2, 0), (2, 0), (0, -2), (0, 2),
                (-1, -1), (1, -1), (-1, 1), (1, 1),
            ]
            for dx, dy in offsets:
                painter.drawText(
                    rect.translated(dx, dy),
                    int(alignment | Qt.TextFlag.TextWordWrap),
                    text,
                )

        if self._use_outline:
            outline = QColor(self._theme.outline_hex)
            if outline.isValid():
                outline.setAlpha(int(28 + 34 * self._glow_strength))
                painter.setPen(outline)
                painter.setFont(font)

                for dx, dy in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
                    painter.drawText(
                        rect.translated(dx, dy),
                        int(alignment | Qt.TextFlag.TextWordWrap),
                        text,
                    )

        text_color = QColor(self._theme.text_color if self.isEnabled() else self._theme.disabled_text)
        painter.setPen(text_color)
        painter.setFont(font)
        painter.drawText(rect, int(alignment | Qt.TextFlag.TextWordWrap), text)
        painter.end()

    def diagnostics(self) -> dict:
        pix = self.pixmap()
        return {
            "text": self.text(),
            "role": self._role,
            "glow_strength": self._glow_strength,
            "glow_blur_base": self._glow_blur_base,
            "pulse_active": self._pulse_active,
            "enabled": self.isEnabled(),
            "has_pixmap": bool(pix and not pix.isNull()),
            "glow_color": self._theme.glow_hex,
            "use_graphics_effect_glow": self._use_graphics_effect_glow,
        }