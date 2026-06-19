"""
core/animation_manager.py

Central animation helper system for the CST Health Monitoring Station kiosk.

Why this file matters:
- Keeps animation behavior consistent across welcome screen, buttons, tiles, cards,
  measuring progress, detail widgets, and route transitions
- Prevents every screen/widget from re-implementing animation logic
- Keeps strong references to running animations so they do not get garbage collected
- Provides reusable helpers for fade, press, pulse, glow, value interpolation,
  stacked-screen transitions, and subtle shimmer effects
- Designed for both laptop demo mode and Raspberry Pi deployment, with performance-safe defaults

Design principles:
- Smooth, premium-looking animations, but not overly heavy
- Safe fallbacks if a widget/effect is missing
- Reusable APIs for later screens/widgets
- No business logic here; only visual animation coordination
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

from PyQt6.QtCore import (
    QEasingCurve,
    QObject,
    QPoint,
    QPropertyAnimation,
    QParallelAnimationGroup,
    QSequentialAnimationGroup,
    QRect,
    QAbstractAnimation,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QPushButton,
    QStackedWidget,
    QWidget,
)

from config import BUTTON_CLICK_ANIMATION_MS, LOGO_GLOW_PULSE_MS, TRANSITION_DURATION_MS
from core.logger import get_logger

logger = get_logger(__name__)


# ============================================================
# Animation defaults
# ============================================================

DEFAULT_DURATION_MS = TRANSITION_DURATION_MS
DEFAULT_CLICK_DURATION_MS = BUTTON_CLICK_ANIMATION_MS
DEFAULT_GLOW_DURATION_MS = LOGO_GLOW_PULSE_MS

DEFAULT_EASING = QEasingCurve.Type.InOutCubic
EASING_OUT = QEasingCurve.Type.OutCubic
EASING_IN = QEasingCurve.Type.InCubic
EASING_BOUNCE = QEasingCurve.Type.OutBack

DEFAULT_GLOW_COLOR = QColor("#55E5FF")
DEFAULT_SUCCESS_GLOW_COLOR = QColor("#42D97B")
DEFAULT_WARNING_GLOW_COLOR = QColor("#FFC14E")
DEFAULT_DANGER_GLOW_COLOR = QColor("#FF5A6F")


# ============================================================
# Dataclasses
# ============================================================

@dataclass(frozen=True)
class FadeConfig:
    duration_ms: int = DEFAULT_DURATION_MS
    start_opacity: float = 0.0
    end_opacity: float = 1.0
    easing: QEasingCurve.Type = DEFAULT_EASING


@dataclass(frozen=True)
class GlowConfig:
    duration_ms: int = DEFAULT_GLOW_DURATION_MS
    color: QColor = DEFAULT_GLOW_COLOR
    blur_start: float = 8.0
    blur_end: float = 28.0
    alpha_start: int = 60
    alpha_end: int = 200


@dataclass(frozen=True)
class MoveConfig:
    duration_ms: int = DEFAULT_DURATION_MS
    offset_x: int = 0
    offset_y: int = 12
    easing: QEasingCurve.Type = DEFAULT_EASING


# ============================================================
# Lightweight animated value driver
# Useful later for gauges, needles, shimmer, numeric changes
# ============================================================

class AnimatedValueDriver(QObject):
    """
    Emits interpolated values using QVariantAnimation.

    Expected use later:
        driver = animation_manager.create_value_driver(...)
        driver.value_changed.connect(self.on_value_changed)
        driver.start()
    """

    value_changed = pyqtSignal(object)
    finished = pyqtSignal()

    def __init__(
        self,
        start_value: Any,
        end_value: Any,
        duration_ms: int = DEFAULT_DURATION_MS,
        easing: QEasingCurve.Type = DEFAULT_EASING,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._animation = QVariantAnimation(self)
        self._animation.setStartValue(start_value)
        self._animation.setEndValue(end_value)
        self._animation.setDuration(duration_ms)
        self._animation.setEasingCurve(easing)
        self._animation.valueChanged.connect(self.value_changed.emit)
        self._animation.finished.connect(self.finished.emit)

    def start(self) -> None:
        self._animation.start()

    def stop(self) -> None:
        self._animation.stop()

    def animation(self) -> QVariantAnimation:
        return self._animation


# ============================================================
# Main animation manager
# ============================================================

class AnimationManager(QObject):
    """
    Shared animation coordinator.

    Main responsibilities:
    - Keep references to running animations/effects
    - Provide reusable animation helpers
    - Offer simple APIs for screens/widgets
    """

    animation_started = pyqtSignal(str)
    animation_finished = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self._logger = logger.bind(component="AnimationManager")
        self._running: List[QAbstractAnimation] = []
        self._groups: List[QAbstractAnimation] = []
        self._effects: Dict[int, object] = {}
        self._value_drivers: List[AnimatedValueDriver] = []

    # ========================================================
    # Internal helpers
    # ========================================================

    def _track_animation(self, animation: QAbstractAnimation, tag: str = "") -> QAbstractAnimation:
        """
        Hold a strong reference until animation finishes.
        """
        self._running.append(animation)
        if tag:
            self.animation_started.emit(tag)

        def _cleanup() -> None:
            try:
                if animation in self._running:
                    self._running.remove(animation)
            except Exception:
                pass
            if tag:
                self.animation_finished.emit(tag)

        animation.finished.connect(_cleanup)
        return animation

    def _track_group(self, group: QAbstractAnimation, tag: str = "") -> QAbstractAnimation:
        self._groups.append(group)
        if tag:
            self.animation_started.emit(tag)

        def _cleanup() -> None:
            try:
                if group in self._groups:
                    self._groups.remove(group)
            except Exception:
                pass
            if tag:
                self.animation_finished.emit(tag)

        group.finished.connect(_cleanup)
        return group

    def _widget_key(self, widget: QWidget) -> int:
        return id(widget)

    def stop_all(self) -> None:
        """
        Stop all tracked animations. Useful during route changes or app shutdown.
        """
        for animation in list(self._running):
            try:
                animation.stop()
            except Exception:
                pass
        for group in list(self._groups):
            try:
                group.stop()
            except Exception:
                pass
        self._running.clear()
        self._groups.clear()

    def stop_widget_animations(self, widget: QWidget) -> None:
        """
        Best-effort stop for animations attached to a widget by looking at children/effects.
        """
        if widget is None:
            return

        for animation in list(self._running):
            try:
                if getattr(animation, "targetObject", None) and animation.targetObject() is widget:
                    animation.stop()
            except Exception:
                continue

    # ========================================================
    # Effect helpers
    # ========================================================

    def ensure_opacity_effect(self, widget: QWidget) -> Optional[QGraphicsOpacityEffect]:
        if widget is None:
            return None

        current = widget.graphicsEffect()
        if isinstance(current, QGraphicsOpacityEffect):
            return current

        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(1.0)
        widget.setGraphicsEffect(effect)
        self._effects[self._widget_key(widget)] = effect
        return effect

    def ensure_shadow_effect(
        self,
        widget: QWidget,
        color: QColor = DEFAULT_GLOW_COLOR,
        blur_radius: float = 20.0,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
    ) -> Optional[QGraphicsDropShadowEffect]:
        if widget is None:
            return None

        current = widget.graphicsEffect()
        if isinstance(current, QGraphicsDropShadowEffect):
            current.setColor(color)
            current.setBlurRadius(blur_radius)
            current.setOffset(offset_x, offset_y)
            return current

        effect = QGraphicsDropShadowEffect(widget)
        effect.setBlurRadius(blur_radius)
        effect.setOffset(offset_x, offset_y)
        effect.setColor(color)
        widget.setGraphicsEffect(effect)
        self._effects[self._widget_key(widget)] = effect
        return effect

    def clear_graphics_effect(self, widget: QWidget) -> None:
        if widget is None:
            return
        try:
            widget.setGraphicsEffect(None)
        except Exception:
            pass
        self._effects.pop(self._widget_key(widget), None)

    # ========================================================
    # Fade animations
    # ========================================================

    def fade_in(
        self,
        widget: QWidget,
        duration_ms: int = DEFAULT_DURATION_MS,
        end_opacity: float = 1.0,
        start_opacity: float = 0.0,
        easing: QEasingCurve.Type = DEFAULT_EASING,
        on_finished: Optional[Callable[[], None]] = None,
        tag: str = "fade_in",
    ) -> Optional[QPropertyAnimation]:
        if widget is None:
            return None

        effect = self.ensure_opacity_effect(widget)
        if effect is None:
            return None

        widget.show()
        effect.setOpacity(start_opacity)

        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(duration_ms)
        animation.setStartValue(start_opacity)
        animation.setEndValue(end_opacity)
        animation.setEasingCurve(easing)

        if on_finished is not None:
            animation.finished.connect(on_finished)

        self._track_animation(animation, tag=tag)
        animation.start()
        return animation

    def fade_out(
        self,
        widget: QWidget,
        duration_ms: int = DEFAULT_DURATION_MS,
        start_opacity: float = 1.0,
        end_opacity: float = 0.0,
        easing: QEasingCurve.Type = DEFAULT_EASING,
        hide_after: bool = False,
        on_finished: Optional[Callable[[], None]] = None,
        tag: str = "fade_out",
    ) -> Optional[QPropertyAnimation]:
        if widget is None:
            return None

        effect = self.ensure_opacity_effect(widget)
        if effect is None:
            return None

        effect.setOpacity(start_opacity)

        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(duration_ms)
        animation.setStartValue(start_opacity)
        animation.setEndValue(end_opacity)
        animation.setEasingCurve(easing)

        def _finalize() -> None:
            if hide_after:
                widget.hide()
            if on_finished is not None:
                on_finished()

        animation.finished.connect(_finalize)

        self._track_animation(animation, tag=tag)
        animation.start()
        return animation

    def cross_fade_widgets(
        self,
        outgoing: Optional[QWidget],
        incoming: Optional[QWidget],
        duration_ms: int = DEFAULT_DURATION_MS,
        on_finished: Optional[Callable[[], None]] = None,
        tag: str = "cross_fade_widgets",
    ) -> Optional[QParallelAnimationGroup]:
        """
        Fade out one widget while fading in another.
        """
        if incoming is None and outgoing is None:
            return None

        group = QParallelAnimationGroup(self)

        if outgoing is not None:
            out_effect = self.ensure_opacity_effect(outgoing)
            if out_effect is not None:
                out_effect.setOpacity(1.0)
                fade_out = QPropertyAnimation(out_effect, b"opacity", self)
                fade_out.setDuration(duration_ms)
                fade_out.setStartValue(1.0)
                fade_out.setEndValue(0.0)
                fade_out.setEasingCurve(DEFAULT_EASING)
                group.addAnimation(fade_out)

        if incoming is not None:
            in_effect = self.ensure_opacity_effect(incoming)
            if in_effect is not None:
                incoming.show()
                in_effect.setOpacity(0.0)
                fade_in = QPropertyAnimation(in_effect, b"opacity", self)
                fade_in.setDuration(duration_ms)
                fade_in.setStartValue(0.0)
                fade_in.setEndValue(1.0)
                fade_in.setEasingCurve(DEFAULT_EASING)
                group.addAnimation(fade_in)

        def _finish() -> None:
            if outgoing is not None:
                outgoing.hide()
            if on_finished is not None:
                on_finished()

        group.finished.connect(_finish)
        self._track_group(group, tag=tag)
        group.start()
        return group

    # ========================================================
    # Stacked widget route transition
    # ========================================================

    def fade_switch_stacked_widget(
        self,
        stacked_widget: QStackedWidget,
        target_index: int,
        duration_ms: int = DEFAULT_DURATION_MS,
        on_finished: Optional[Callable[[], None]] = None,
        tag: str = "fade_switch_stacked_widget",
    ) -> Optional[QSequentialAnimationGroup]:
        """
        Fade out current stacked page, switch page, then fade in new page.
        Useful later for navigator transitions.
        """
        if stacked_widget is None:
            return None
        if target_index < 0 or target_index >= stacked_widget.count():
            return None

        current_widget = stacked_widget.currentWidget()
        target_widget = stacked_widget.widget(target_index)

        if current_widget is target_widget:
            if on_finished is not None:
                on_finished()
            return None

        sequence = QSequentialAnimationGroup(self)

        if current_widget is not None:
            current_effect = self.ensure_opacity_effect(current_widget)
            if current_effect is not None:
                current_effect.setOpacity(1.0)
                fade_out = QPropertyAnimation(current_effect, b"opacity", self)
                fade_out.setDuration(max(120, duration_ms // 2))
                fade_out.setStartValue(1.0)
                fade_out.setEndValue(0.0)
                fade_out.setEasingCurve(DEFAULT_EASING)
                sequence.addAnimation(fade_out)

        def _switch_page() -> None:
            stacked_widget.setCurrentIndex(target_index)
            if target_widget is not None:
                target_effect = self.ensure_opacity_effect(target_widget)
                if target_effect is not None:
                    target_effect.setOpacity(0.0)

        sequence.currentAnimationChanged.connect(lambda _anim: None)
        sequence.finished.connect(lambda: None)

        # Insert the page switch in between using a tiny value animation callback
        switch_driver = QVariantAnimation(self)
        switch_driver.setDuration(1)
        switch_driver.setStartValue(0)
        switch_driver.setEndValue(1)
        switch_driver.valueChanged.connect(lambda _value: None)
        switch_driver.finished.connect(_switch_page)
        sequence.addAnimation(switch_driver)

        if target_widget is not None:
            target_effect = self.ensure_opacity_effect(target_widget)
            if target_effect is not None:
                fade_in = QPropertyAnimation(target_effect, b"opacity", self)
                fade_in.setDuration(max(120, duration_ms // 2))
                fade_in.setStartValue(0.0)
                fade_in.setEndValue(1.0)
                fade_in.setEasingCurve(DEFAULT_EASING)
                sequence.addAnimation(fade_in)

        if on_finished is not None:
            sequence.finished.connect(on_finished)

        self._track_group(sequence, tag=tag)
        sequence.start()
        return sequence

    # ========================================================
    # Button / press feedback
    # ========================================================

    def animate_button_press(
        self,
        button: QPushButton,
        duration_ms: int = DEFAULT_CLICK_DURATION_MS,
        offset_y: int = 2,
        on_finished: Optional[Callable[[], None]] = None,
        tag: str = "button_press",
    ) -> Optional[QSequentialAnimationGroup]:
        """
        Subtle tactile press animation:
        - moves button slightly down
        - returns it to original position
        """
        if button is None:
            return None

        start_pos = button.pos()
        pressed_pos = QPoint(start_pos.x(), start_pos.y() + offset_y)

        down = QPropertyAnimation(button, b"pos", self)
        down.setDuration(max(60, duration_ms // 2))
        down.setStartValue(start_pos)
        down.setEndValue(pressed_pos)
        down.setEasingCurve(EASING_OUT)

        up = QPropertyAnimation(button, b"pos", self)
        up.setDuration(max(60, duration_ms // 2))
        up.setStartValue(pressed_pos)
        up.setEndValue(start_pos)
        up.setEasingCurve(EASING_OUT)

        sequence = QSequentialAnimationGroup(self)
        sequence.addAnimation(down)
        sequence.addAnimation(up)

        if on_finished is not None:
            sequence.finished.connect(on_finished)

        self._track_group(sequence, tag=tag)
        sequence.start()
        return sequence

    def animate_button_pulse(
        self,
        button: QPushButton,
        duration_ms: int = 260,
        glow_color: QColor = DEFAULT_GLOW_COLOR,
        tag: str = "button_pulse",
    ) -> Optional[QParallelAnimationGroup]:
        """
        Quick glow pulse for button emphasis.
        """
        if button is None:
            return None

        shadow = self.ensure_shadow_effect(button, color=glow_color, blur_radius=8.0, offset_x=0.0, offset_y=0.0)
        if shadow is None:
            return None

        color_start = QColor(glow_color)
        color_start.setAlpha(70)
        color_end = QColor(glow_color)
        color_end.setAlpha(200)

        blur_anim = QPropertyAnimation(shadow, b"blurRadius", self)
        blur_anim.setDuration(duration_ms)
        blur_anim.setStartValue(8.0)
        blur_anim.setEndValue(26.0)
        blur_anim.setEasingCurve(DEFAULT_EASING)

        color_anim = QVariantAnimation(self)
        color_anim.setDuration(duration_ms)
        color_anim.setStartValue(color_start)
        color_anim.setEndValue(color_end)
        color_anim.setEasingCurve(DEFAULT_EASING)
        color_anim.valueChanged.connect(lambda value: shadow.setColor(value))

        group = QParallelAnimationGroup(self)
        group.addAnimation(blur_anim)
        group.addAnimation(color_anim)

        def _restore() -> None:
            shadow.setBlurRadius(10.0)
            restore = QColor(glow_color)
            restore.setAlpha(90)
            shadow.setColor(restore)

        group.finished.connect(_restore)
        self._track_group(group, tag=tag)
        group.start()
        return group

    def animate_click_feedback(
        self,
        button: QPushButton,
        on_finished: Optional[Callable[[], None]] = None,
        tag: str = "click_feedback",
    ) -> Optional[QSequentialAnimationGroup]:
        """
        Composite button feedback used by screens:
        - press motion
        - optional callback
        """
        return self.animate_button_press(
            button=button,
            duration_ms=DEFAULT_CLICK_DURATION_MS,
            offset_y=2,
            on_finished=on_finished,
            tag=tag,
        )

    # ========================================================
    # Glow / pulse animations
    # ========================================================

    def start_glow_pulse(
        self,
        widget: QWidget,
        duration_ms: int = DEFAULT_GLOW_DURATION_MS,
        color: QColor = DEFAULT_GLOW_COLOR,
        blur_start: float = 8.0,
        blur_end: float = 28.0,
        alpha_start: int = 60,
        alpha_end: int = 200,
        tag: str = "glow_pulse",
    ) -> Optional[QPropertyAnimation]:
        """
        Looping glow pulse, ideal for welcome logo or highlighted status badge.
        """
        if widget is None:
            return None

        shadow = self.ensure_shadow_effect(widget, color=color, blur_radius=blur_start, offset_x=0.0, offset_y=0.0)
        if shadow is None:
            return None

        blur_anim = QPropertyAnimation(shadow, b"blurRadius", self)
        blur_anim.setDuration(duration_ms)
        blur_anim.setStartValue(blur_start)
        blur_anim.setEndValue(blur_end)
        blur_anim.setEasingCurve(DEFAULT_EASING)
        blur_anim.setLoopCount(-1)
        blur_anim.setDirection(QAbstractAnimation.Direction.Forward)

        def _toggle_direction() -> None:
            if blur_anim.direction() == QAbstractAnimation.Direction.Forward:
                blur_anim.setDirection(QAbstractAnimation.Direction.Backward)
            else:
                blur_anim.setDirection(QAbstractAnimation.Direction.Forward)
            blur_anim.start()

        # Color breathing handled by separate value animation
        color_anim = QVariantAnimation(self)
        start_color = QColor(color)
        start_color.setAlpha(alpha_start)
        end_color = QColor(color)
        end_color.setAlpha(alpha_end)
        color_anim.setStartValue(start_color)
        color_anim.setEndValue(end_color)
        color_anim.setDuration(duration_ms)
        color_anim.setEasingCurve(DEFAULT_EASING)
        color_anim.valueChanged.connect(lambda value: shadow.setColor(value))

        def _toggle_color() -> None:
            if color_anim.direction() == QAbstractAnimation.Direction.Forward:
                color_anim.setDirection(QAbstractAnimation.Direction.Backward)
            else:
                color_anim.setDirection(QAbstractAnimation.Direction.Forward)
            color_anim.start()

        blur_anim.finished.connect(_toggle_direction)
        color_anim.finished.connect(_toggle_color)

        self._track_animation(blur_anim, tag=tag)
        self._track_animation(color_anim, tag=f"{tag}_color")
        blur_anim.start()
        color_anim.start()
        return blur_anim

    def stop_glow_pulse(self, widget: QWidget) -> None:
        """
        Best-effort stop for glow effect. Keeps effect attached but calm.
        """
        if widget is None:
            return
        effect = widget.graphicsEffect()
        if isinstance(effect, QGraphicsDropShadowEffect):
            effect.setBlurRadius(10.0)

    def animate_glow_once(
        self,
        widget: QWidget,
        duration_ms: int = 320,
        color: QColor = DEFAULT_GLOW_COLOR,
        tag: str = "glow_once",
    ) -> Optional[QParallelAnimationGroup]:
        if widget is None:
            return None

        shadow = self.ensure_shadow_effect(widget, color=color, blur_radius=6.0, offset_x=0.0, offset_y=0.0)
        if shadow is None:
            return None

        blur_anim = QPropertyAnimation(shadow, b"blurRadius", self)
        blur_anim.setDuration(duration_ms)
        blur_anim.setKeyValueAt(0.0, 6.0)
        blur_anim.setKeyValueAt(0.5, 26.0)
        blur_anim.setKeyValueAt(1.0, 10.0)
        blur_anim.setEasingCurve(DEFAULT_EASING)

        color_anim = QVariantAnimation(self)
        c1 = QColor(color)
        c1.setAlpha(60)
        c2 = QColor(color)
        c2.setAlpha(180)
        c3 = QColor(color)
        c3.setAlpha(90)
        color_anim.setDuration(duration_ms)
        color_anim.setKeyValueAt(0.0, c1)
        color_anim.setKeyValueAt(0.5, c2)
        color_anim.setKeyValueAt(1.0, c3)
        color_anim.valueChanged.connect(lambda value: shadow.setColor(value))

        group = QParallelAnimationGroup(self)
        group.addAnimation(blur_anim)
        group.addAnimation(color_anim)

        self._track_group(group, tag=tag)
        group.start()
        return group

    # ========================================================
    # Move / slide / rise animations
    # ========================================================

    def animate_slide_in(
        self,
        widget: QWidget,
        offset_x: int = 0,
        offset_y: int = 18,
        duration_ms: int = DEFAULT_DURATION_MS,
        easing: QEasingCurve.Type = DEFAULT_EASING,
        also_fade: bool = True,
        on_finished: Optional[Callable[[], None]] = None,
        tag: str = "slide_in",
    ) -> Optional[QParallelAnimationGroup]:
        if widget is None:
            return None

        end_pos = widget.pos()
        start_pos = QPoint(end_pos.x() + offset_x, end_pos.y() + offset_y)

        move_anim = QPropertyAnimation(widget, b"pos", self)
        move_anim.setDuration(duration_ms)
        move_anim.setStartValue(start_pos)
        move_anim.setEndValue(end_pos)
        move_anim.setEasingCurve(easing)

        group = QParallelAnimationGroup(self)
        group.addAnimation(move_anim)

        widget.move(start_pos)
        widget.show()

        if also_fade:
            effect = self.ensure_opacity_effect(widget)
            if effect is not None:
                effect.setOpacity(0.0)
                fade_anim = QPropertyAnimation(effect, b"opacity", self)
                fade_anim.setDuration(duration_ms)
                fade_anim.setStartValue(0.0)
                fade_anim.setEndValue(1.0)
                fade_anim.setEasingCurve(easing)
                group.addAnimation(fade_anim)

        if on_finished is not None:
            group.finished.connect(on_finished)

        self._track_group(group, tag=tag)
        group.start()
        return group

    def animate_slide_out(
        self,
        widget: QWidget,
        offset_x: int = 0,
        offset_y: int = -14,
        duration_ms: int = DEFAULT_DURATION_MS,
        easing: QEasingCurve.Type = DEFAULT_EASING,
        also_fade: bool = True,
        hide_after: bool = True,
        on_finished: Optional[Callable[[], None]] = None,
        tag: str = "slide_out",
    ) -> Optional[QParallelAnimationGroup]:
        if widget is None:
            return None

        start_pos = widget.pos()
        end_pos = QPoint(start_pos.x() + offset_x, start_pos.y() + offset_y)

        move_anim = QPropertyAnimation(widget, b"pos", self)
        move_anim.setDuration(duration_ms)
        move_anim.setStartValue(start_pos)
        move_anim.setEndValue(end_pos)
        move_anim.setEasingCurve(easing)

        group = QParallelAnimationGroup(self)
        group.addAnimation(move_anim)

        if also_fade:
            effect = self.ensure_opacity_effect(widget)
            if effect is not None:
                effect.setOpacity(1.0)
                fade_anim = QPropertyAnimation(effect, b"opacity", self)
                fade_anim.setDuration(duration_ms)
                fade_anim.setStartValue(1.0)
                fade_anim.setEndValue(0.0)
                fade_anim.setEasingCurve(easing)
                group.addAnimation(fade_anim)

        def _finish() -> None:
            if hide_after:
                widget.hide()
            if on_finished is not None:
                on_finished()

        group.finished.connect(_finish)
        self._track_group(group, tag=tag)
        group.start()
        return group

    # ========================================================
    # Rect / geometry animations
    # Useful later for card emphasis or pop transitions
    # ========================================================

    def animate_geometry(
        self,
        widget: QWidget,
        start_rect: QRect,
        end_rect: QRect,
        duration_ms: int = DEFAULT_DURATION_MS,
        easing: QEasingCurve.Type = DEFAULT_EASING,
        on_finished: Optional[Callable[[], None]] = None,
        tag: str = "geometry",
    ) -> Optional[QPropertyAnimation]:
        if widget is None:
            return None

        widget.setGeometry(start_rect)

        animation = QPropertyAnimation(widget, b"geometry", self)
        animation.setDuration(duration_ms)
        animation.setStartValue(start_rect)
        animation.setEndValue(end_rect)
        animation.setEasingCurve(easing)

        if on_finished is not None:
            animation.finished.connect(on_finished)

        self._track_animation(animation, tag=tag)
        animation.start()
        return animation

    def animate_pop_in(
        self,
        widget: QWidget,
        scale_margin: int = 10,
        duration_ms: int = 220,
        on_finished: Optional[Callable[[], None]] = None,
        tag: str = "pop_in",
    ) -> Optional[QParallelAnimationGroup]:
        """
        Simulated pop-in by animating geometry and opacity.
        """
        if widget is None:
            return None

        final_rect = widget.geometry()
        start_rect = QRect(
            final_rect.x() + scale_margin,
            final_rect.y() + scale_margin,
            max(1, final_rect.width() - scale_margin * 2),
            max(1, final_rect.height() - scale_margin * 2),
        )

        geo_anim = QPropertyAnimation(widget, b"geometry", self)
        geo_anim.setDuration(duration_ms)
        geo_anim.setStartValue(start_rect)
        geo_anim.setEndValue(final_rect)
        geo_anim.setEasingCurve(EASING_BOUNCE)

        effect = self.ensure_opacity_effect(widget)
        group = QParallelAnimationGroup(self)

        widget.setGeometry(start_rect)
        widget.show()
        group.addAnimation(geo_anim)

        if effect is not None:
            effect.setOpacity(0.0)
            fade_anim = QPropertyAnimation(effect, b"opacity", self)
            fade_anim.setDuration(duration_ms)
            fade_anim.setStartValue(0.0)
            fade_anim.setEndValue(1.0)
            fade_anim.setEasingCurve(DEFAULT_EASING)
            group.addAnimation(fade_anim)

        if on_finished is not None:
            group.finished.connect(on_finished)

        self._track_group(group, tag=tag)
        group.start()
        return group

    # ========================================================
    # Value interpolation helpers
    # ========================================================

    def animate_value(
        self,
        start_value: Any,
        end_value: Any,
        duration_ms: int = DEFAULT_DURATION_MS,
        easing: QEasingCurve.Type = DEFAULT_EASING,
        on_value_changed: Optional[Callable[[Any], None]] = None,
        on_finished: Optional[Callable[[], None]] = None,
        tag: str = "animate_value",
    ) -> AnimatedValueDriver:
        driver = AnimatedValueDriver(
            start_value=start_value,
            end_value=end_value,
            duration_ms=duration_ms,
            easing=easing,
            parent=self,
        )

        if on_value_changed is not None:
            driver.value_changed.connect(on_value_changed)
        if on_finished is not None:
            driver.finished.connect(on_finished)

        self._value_drivers.append(driver)

        def _cleanup() -> None:
            try:
                if driver in self._value_drivers:
                    self._value_drivers.remove(driver)
            except Exception:
                pass

        driver.finished.connect(_cleanup)
        self.animation_started.emit(tag)
        driver.finished.connect(lambda: self.animation_finished.emit(tag))
        driver.start()
        return driver

    def animate_number_change(
        self,
        start_value: float,
        end_value: float,
        duration_ms: int = DEFAULT_DURATION_MS,
        on_value_changed: Optional[Callable[[float], None]] = None,
        on_finished: Optional[Callable[[], None]] = None,
        tag: str = "number_change",
    ) -> AnimatedValueDriver:
        return self.animate_value(
            start_value=float(start_value),
            end_value=float(end_value),
            duration_ms=duration_ms,
            easing=DEFAULT_EASING,
            on_value_changed=on_value_changed,
            on_finished=on_finished,
            tag=tag,
        )

    # ========================================================
    # Sequential entrance animations for multiple widgets
    # ========================================================

    def animate_staggered_fade_in(
        self,
        widgets: Sequence[QWidget],
        item_duration_ms: int = 220,
        y_offset: int = 10,
        tag: str = "staggered_fade_in",
    ) -> Optional[QSequentialAnimationGroup]:
        valid_widgets = [w for w in widgets if w is not None]
        if not valid_widgets:
            return None

        sequence = QSequentialAnimationGroup(self)

        for widget in valid_widgets:
            end_pos = widget.pos()
            start_pos = QPoint(end_pos.x(), end_pos.y() + y_offset)
            widget.move(start_pos)
            widget.show()

            group = QParallelAnimationGroup(self)

            move_anim = QPropertyAnimation(widget, b"pos", self)
            move_anim.setDuration(item_duration_ms)
            move_anim.setStartValue(start_pos)
            move_anim.setEndValue(end_pos)
            move_anim.setEasingCurve(DEFAULT_EASING)
            group.addAnimation(move_anim)

            effect = self.ensure_opacity_effect(widget)
            if effect is not None:
                effect.setOpacity(0.0)
                fade_anim = QPropertyAnimation(effect, b"opacity", self)
                fade_anim.setDuration(item_duration_ms)
                fade_anim.setStartValue(0.0)
                fade_anim.setEndValue(1.0)
                fade_anim.setEasingCurve(DEFAULT_EASING)
                group.addAnimation(fade_anim)

            sequence.addAnimation(group)

        self._track_group(sequence, tag=tag)
        sequence.start()
        return sequence

    # ========================================================
    # Progress shimmer helper
    # Used later by custom progress widgets if desired
    # ========================================================

    def create_progress_shimmer_driver(
        self,
        duration_ms: int = 1200,
        on_value_changed: Optional[Callable[[float], None]] = None,
        tag: str = "progress_shimmer",
    ) -> AnimatedValueDriver:
        """
        Creates a looping 0..1 driver. Caller can use the emitted value
        to repaint a shimmer position in a custom widget.
        """
        driver = AnimatedValueDriver(
            start_value=0.0,
            end_value=1.0,
            duration_ms=duration_ms,
            easing=QEasingCurve.Type.Linear,
            parent=self,
        )

        if on_value_changed is not None:
            driver.value_changed.connect(on_value_changed)

        self._value_drivers.append(driver)

        def _restart() -> None:
            try:
                driver.animation().start()
            except Exception:
                pass

        def _cleanup_if_removed() -> None:
            if driver not in self._value_drivers:
                return
            _restart()

        driver.finished.connect(_cleanup_if_removed)
        self.animation_started.emit(tag)
        driver.start()
        return driver

    # ========================================================
    # Diagnostics
    # ========================================================

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "running_animations": len(self._running),
            "running_groups": len(self._groups),
            "tracked_effects": len(self._effects),
            "value_drivers": len(self._value_drivers),
        }


# ============================================================
# Singleton accessor
# ============================================================

_ANIMATION_MANAGER_SINGLETON: Optional[AnimationManager] = None


def get_animation_manager() -> AnimationManager:
    global _ANIMATION_MANAGER_SINGLETON
    if _ANIMATION_MANAGER_SINGLETON is None:
        _ANIMATION_MANAGER_SINGLETON = AnimationManager()
    return _ANIMATION_MANAGER_SINGLETON