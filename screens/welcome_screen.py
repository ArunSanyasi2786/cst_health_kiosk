"""
screens/welcome_screen.py

Pixel-focused Bhutanese black/gold welcome screen for the CST Health Monitoring
Station kiosk. This file is designed to drop directly into the existing project
and keeps the same public signals/methods used by main.py.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from PyQt6.QtCore import QElapsedTimer, QPointF, QRectF, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PyQt6.QtWidgets import QFrame, QSizePolicy, QWidget

try:
    from core.logger import get_logger
except Exception:  # pragma: no cover
    import logging

    def get_logger(name: str):
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(name)

try:
    from core.utils import safe_int, safe_str
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

try:
    from core.constants import MODE_DEMO, MODE_HARDWARE, SCREEN_MODE_SELECT
except Exception:  # pragma: no cover
    MODE_DEMO = "demo"
    MODE_HARDWARE = "hardware"
    SCREEN_MODE_SELECT = "mode_select"


logger = get_logger(__name__)


# -----------------------------------------------------------------------------
# Asset helpers
# -----------------------------------------------------------------------------

def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_asset(relative_path: str) -> str:
    relative_clean = safe_str(relative_path, "").strip().replace("\\", "/").lstrip("/")
    if not relative_clean:
        return ""

    try:
        import core.asset_paths as asset_paths

        for name in (
            "resolve_asset_path",
            "resolve_asset",
            "asset_path",
            "asset",
            "get_asset_path",
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


def _rgba(hex_color: str, alpha: int) -> QColor:
    c = QColor(hex_color)
    c.setAlpha(max(0, min(255, alpha)))
    return c


# -----------------------------------------------------------------------------
# Welcome Screen
# -----------------------------------------------------------------------------

class WelcomeScreen(QFrame):
    """
    Drop-in replacement for the existing welcome screen.

    Public compatibility kept:
    - start_requested
    - admin_requested
    - intro_finished
    - intro_progress_changed
    - replay_intro(), skip_intro(), on_idle_return(), diagnostics()
    """

    start_requested = pyqtSignal()
    admin_requested = pyqtSignal()
    intro_finished = pyqtSignal()
    intro_progress_changed = pyqtSignal(int, str)

    INTRO_DURATION_MS = 4000
    INTRO_TICK_MS = 33
    AUTO_NAV_DELAY_MS = 160

    DESIGN_W = 800.0
    DESIGN_H = 480.0

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        navigator: Optional[object] = None,
        app_state: Optional[object] = None,
        services: Optional[Mapping[str, Any]] = None,
        animation_manager: Optional[object] = None,
        theme_manager: Optional[object] = None,
        **_: Any,
    ) -> None:
        super().__init__(parent)

        self.navigator = navigator
        self.app_state = app_state
        self.services: Dict[str, Any] = dict(services or {})
        self.animation_manager = animation_manager
        self.theme_manager = theme_manager

        self._background_path = _resolve_asset("backgrounds/welcome_bhutanese_screen.png")
        self._fallback_background_path = _resolve_asset("backgrounds/welcome_bg.png")
        self._background_pixmap = QPixmap(self._background_path)
        if self._background_pixmap.isNull():
            self._background_pixmap = QPixmap(self._fallback_background_path)

        self._intro_started = False
        self._intro_finished = False
        self._waiting_for_user_start = True
        self._current_progress = 0
        self._current_status_text = "Ready to launch CST Health Monitoring Station"
        self._bottom_hint_text = "Press Enter or tap anywhere to continue"
        self._subtitle_text = "Press Enter or tap anywhere to begin loading."
        self._last_start_trigger = "boot"
        self._clock_text = datetime.now().strftime("%H:%M:%S")
        self._shimmer_phase = 0.0
        self._runtime_snapshot: Dict[str, Any] = {}

        self._intro_elapsed = QElapsedTimer()

        self._intro_timer = QTimer(self)
        self._intro_timer.setInterval(self.INTRO_TICK_MS)
        self._intro_timer.timeout.connect(self._advance_intro)

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._update_clock)

        self._paint_timer = QTimer(self)
        self._paint_timer.setInterval(42)
        self._paint_timer.timeout.connect(self._tick_paint)

        self.setObjectName("WelcomeScreen")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(800, 480)

        self._update_clock()
        self._refresh_runtime_status()
        self._prepare_waiting_state(reset_animation=False)

    # ------------------------------------------------------------------
    # Runtime state
    # ------------------------------------------------------------------
    def _update_clock(self) -> None:
        self._clock_text = datetime.now().strftime("%H:%M:%S")
        self._refresh_runtime_status()
        self.update()

    def _tick_paint(self) -> None:
        self._shimmer_phase += 0.018
        if self._shimmer_phase > 1.0:
            self._shimmer_phase = 0.0
        self.update()

    def _prepare_waiting_state(self, *, reset_animation: bool = True) -> None:
        self._intro_timer.stop()
        self._intro_started = False
        self._intro_finished = False
        self._waiting_for_user_start = True
        self._current_progress = 0
        self._current_status_text = "Ready to launch CST Health Monitoring Station"
        self._subtitle_text = "Press Enter or tap anywhere to begin loading."
        self._bottom_hint_text = "Press Enter or tap anywhere to continue"
        self._refresh_runtime_status()
        self.update()

    def _start_intro_on_user_request(self, trigger: str = "manual") -> None:
        if self._intro_started and not self._intro_finished:
            return

        self._last_start_trigger = safe_str(trigger, "manual")
        self._waiting_for_user_start = False
        self._intro_started = True
        self._intro_finished = False
        self._current_progress = 0
        self._current_status_text = "Preparing health-monitoring workflow"
        self._subtitle_text = "Initializing touchscreen UI, service layer, and hardware interface."
        self._bottom_hint_text = "System booting... please wait"
        self._intro_elapsed.restart()
        self._intro_timer.start()
        self.intro_progress_changed.emit(0, self._current_status_text)
        self.update()

    def _advance_intro(self) -> None:
        elapsed = max(0, self._intro_elapsed.elapsed())
        progress = max(0, min(100, int((elapsed / float(self.INTRO_DURATION_MS)) * 100)))

        text = "Preparing health-monitoring workflow"
        if progress >= 10:
            text = "Warming up welcome interface"
        if progress >= 22:
            text = "Loading CST branding assets"
        if progress >= 40:
            text = "Preparing health-monitoring workflow"
        if progress >= 58:
            text = "Linking service layer and local storage"
        if progress >= 76:
            text = "Checking mode and hardware readiness"
        if progress >= 90:
            text = "Finalizing kiosk controls"
        if progress >= 100:
            text = "System ready"

        self._current_progress = progress
        self._current_status_text = text
        self._refresh_runtime_status()
        self.intro_progress_changed.emit(progress, text)
        self.update()

        if elapsed >= self.INTRO_DURATION_MS:
            self._intro_timer.stop()
            self._complete_intro()

    def _complete_intro(self) -> None:
        if self._intro_finished:
            return
        self._intro_finished = True
        self._current_progress = 100
        self._current_status_text = "System ready"
        self._subtitle_text = "Startup completed. Redirecting to operating mode selection..."
        self._bottom_hint_text = "Loading next screen..."
        self.intro_progress_changed.emit(100, self._current_status_text)
        self.intro_finished.emit()
        self.update()
        QTimer.singleShot(self.AUTO_NAV_DELAY_MS, self._go_to_mode_select)

    def replay_intro(self) -> None:
        self._prepare_waiting_state()
        self._start_intro_on_user_request("replay")

    def skip_intro(self) -> None:
        if self._waiting_for_user_start and not self._intro_started:
            self._start_intro_on_user_request("skip")

    def on_idle_return(self) -> None:
        self._prepare_waiting_state()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def intro_finished_flag(self) -> bool:
        return self._intro_finished

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "intro_started": self._intro_started,
            "intro_finished": self._intro_finished,
            "current_progress": self._current_progress,
            "current_status_text": self._current_status_text,
            "background_path": self._background_path,
            "fallback_background_path": self._fallback_background_path,
            "mode_text": self._mode_label(),
            "link_text": self._link_label(),
            "intro_duration_ms": self.INTRO_DURATION_MS,
            "timer_interval_ms": self._intro_timer.interval(),
        }

    # ------------------------------------------------------------------
    # Navigation / services
    # ------------------------------------------------------------------
    def _go_to_mode_select(self) -> None:
        if self._navigate_to(SCREEN_MODE_SELECT):
            return
        self.start_requested.emit()

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

    def _refresh_runtime_status(self) -> None:
        self._runtime_snapshot = self._read_runtime_snapshot()

    def _read_runtime_snapshot(self) -> Dict[str, Any]:
        snapshot: Dict[str, Any] = {
            "mode": MODE_HARDWARE,
            "connected": False,
            "waiting": False,
            "detail": "",
        }

        try:
            if self.app_state is not None:
                method = getattr(self.app_state, "connection_snapshot", None)
                if callable(method):
                    raw = method()
                    if isinstance(raw, Mapping):
                        snapshot.update(dict(raw))
        except Exception:
            pass

        try:
            service = self.services.get("connection_service") or self.services.get("connection")
            if service is not None:
                for method_name in ("snapshot", "get_snapshot", "connection_snapshot"):
                    method = getattr(service, method_name, None)
                    if callable(method):
                        raw = method()
                        if isinstance(raw, Mapping):
                            snapshot.update(dict(raw))
                            break
        except Exception:
            pass

        try:
            mode_service = self.services.get("mode_service") or self.services.get("mode")
            if mode_service is not None:
                for method_name in ("current_mode", "get_mode", "mode"):
                    method = getattr(mode_service, method_name, None)
                    if callable(method):
                        mode_value = method()
                        mode_text = safe_str(mode_value, "").strip().lower()
                        if mode_text:
                            snapshot["mode"] = mode_text
                            break
        except Exception:
            pass

        mode = safe_str(snapshot.get("mode"), MODE_HARDWARE).strip().lower() or MODE_HARDWARE
        if mode not in {MODE_DEMO, MODE_HARDWARE}:
            mode = MODE_HARDWARE
        snapshot["mode"] = mode

        serial_connected = bool(snapshot.get("serial_connected", False))
        esp32_connected = bool(snapshot.get("esp32_connected", False))
        connected = bool(snapshot.get("connected", esp32_connected or serial_connected))
        waiting = bool(snapshot.get("waiting", False))

        snapshot["connected"] = connected
        snapshot["waiting"] = waiting
        return snapshot

    def _mode_label(self) -> str:
        mode = safe_str(self._runtime_snapshot.get("mode"), MODE_HARDWARE).strip().lower()
        return "Demo Mode" if mode == MODE_DEMO else "Hardware Mode"

    def _link_label(self) -> str:
        mode = safe_str(self._runtime_snapshot.get("mode"), MODE_HARDWARE).strip().lower()
        connected = bool(self._runtime_snapshot.get("connected", False))
        waiting = bool(self._runtime_snapshot.get("waiting", False))

        if mode == MODE_DEMO:
            return "Simulated Sensors"
        if connected:
            return "Hardware Connected"
        if waiting:
            return "Waiting for Device"
        return "No Device Link"

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._clock_timer.start()
        self._paint_timer.start()
        self._refresh_runtime_status()
        self._prepare_waiting_state(reset_animation=False)
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._clock_timer.stop()
        self._paint_timer.stop()
        self._intro_timer.stop()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._waiting_for_user_start and not self._intro_started:
            self._start_intro_on_user_request("mouse")
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space} and self._waiting_for_user_start and not self._intro_started:
            self._start_intro_on_user_request("keyboard")
            event.accept()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        scale_x = max(0.01, self.width() / self.DESIGN_W)
        scale_y = max(0.01, self.height() / self.DESIGN_H)

        self._draw_background(p)

        p.save()
        p.scale(scale_x, scale_y)
        self._draw_dynamic_top_chips(p)
        self._draw_dynamic_main_content(p)
        self._draw_dynamic_center_status(p)
        self._draw_dynamic_progress(p)
        self._draw_dynamic_bottom_hint(p)
        p.restore()

        p.end()

    def _draw_background(self, p: QPainter) -> None:
        rect = self.rect()
        if not self._background_pixmap.isNull():
            scaled = self._background_pixmap.scaled(
                rect.size(),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            p.drawPixmap(0, 0, scaled)
            return

        grad = QLinearGradient(0, 0, rect.width(), rect.height())
        grad.setColorAt(0.0, QColor("#030505"))
        grad.setColorAt(0.48, QColor("#071211"))
        grad.setColorAt(1.0, QColor("#020303"))
        p.fillRect(rect, grad)

    def _font(self, size: int, weight: QFont.Weight = QFont.Weight.Normal, family: str = "Inter") -> QFont:
        f = QFont(family)
        f.setPixelSize(size)
        f.setWeight(weight)
        return f

    def _rounded_path(self, rect: QRectF, radius: float) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        return path

    def _draw_dynamic_top_chips(self, p: QPainter) -> None:
        # Cover the baked clock/mode chips in the background and repaint them live.
        self._soft_cover(p, QRectF(450, 12, 344, 34), radius=17, alpha=210)

        mode = safe_str(self._runtime_snapshot.get("mode"), MODE_HARDWARE).strip().lower()
        link = self._link_label()

        mode_accent = "#f2c257" if mode == MODE_HARDWARE else "#5bdcff"
        if mode == MODE_DEMO:
            link_accent = "#5bdcff"
        elif bool(self._runtime_snapshot.get("connected", False)):
            link_accent = "#57e39a"
        elif bool(self._runtime_snapshot.get("waiting", False)):
            link_accent = "#ffd25e"
        else:
            link_accent = "#ff735c"

        self._draw_pill(p, QRectF(462, 14, 112, 28), "▣  " + self._mode_label(), mode_accent)
        self._draw_pill(p, QRectF(582, 14, 113, 28), "⌁  " + link, link_accent)
        self._draw_pill(p, QRectF(704, 14, 84, 28), "◷  " + self._clock_text, "#f2c257", font_size=10)

    def _draw_pill(self, p: QPainter, rect: QRectF, text: str, accent_hex: str, *, font_size: int = 9) -> None:
        accent = QColor(accent_hex)
        glow = QColor(accent)
        glow.setAlpha(44)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawRoundedRect(rect.adjusted(-2, -2, 2, 2), rect.height() / 2 + 2, rect.height() / 2 + 2)

        bg = QColor(8, 7, 5, 222)
        border = QColor(accent)
        border.setAlpha(205)
        p.setBrush(bg)
        p.setPen(QPen(border, 1.2))
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)

        p.setFont(self._font(font_size, QFont.Weight.Bold))
        p.setPen(QColor("#f6e8bc"))
        clipped = self._elide_text(p, text, max(10, int(rect.width()) - 14))
        p.drawText(rect.adjusted(6, 0, -6, 0), int(Qt.AlignmentFlag.AlignCenter), clipped)

    def _draw_dynamic_main_content(self, p: QPainter) -> None:
        """
        Draw the real welcome content in the empty centre area of the new
        background. The background image must stay clean here, because these
        elements are rendered by code to avoid double text/overlap.
        """
        # Soft readable patch only behind the content zone. It keeps the gold
        # patterned background visible but gives the heading/buttons contrast.
        content_cover = QRectF(214, 198, 372, 124)
        cover_grad = QLinearGradient(content_cover.left(), content_cover.top(), content_cover.left(), content_cover.bottom())
        cover_grad.setColorAt(0.0, QColor(3, 6, 6, 62))
        cover_grad.setColorAt(0.55, QColor(3, 6, 6, 96))
        cover_grad.setColorAt(1.0, QColor(3, 6, 6, 50))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(cover_grad)
        p.drawRoundedRect(content_cover, 18, 18)

        # Main welcome heading - shifted lower so it does not touch the BHMS logo.
        title_rect = QRectF(238, 206, 324, 48)
        p.setFont(self._font(19, QFont.Weight.Black, "Segoe UI"))
        shadow_rect = title_rect.translated(1.6, 2.0)
        p.setPen(QColor(0, 0, 0, 190))
        p.drawText(shadow_rect, int(Qt.AlignmentFlag.AlignCenter), "Welcome to CST Health\nMonitoring Station")
        p.setPen(QColor("#f2d98d"))
        p.drawText(title_rect, int(Qt.AlignmentFlag.AlignCenter), "Welcome to CST Health\nMonitoring Station")

        # Small gold ornaments beside the title, matching the background style.
        p.setPen(QPen(_rgba("#d4a33e", 145), 1.1))
        y = 238
        p.drawLine(QPointF(221, y), QPointF(260, y))
        p.drawLine(QPointF(540, y), QPointF(579, y))
        p.setBrush(_rgba("#f6d26d", 170))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(264, y), 2.6, 2.6)
        p.drawEllipse(QPointF(536, y), 2.6, 2.6)
        p.setFont(self._font(13, QFont.Weight.Bold, "Segoe UI"))
        p.setPen(_rgba("#d6a740", 190))
        p.drawText(QRectF(215, 228, 20, 20), int(Qt.AlignmentFlag.AlignCenter), "❖")
        p.drawText(QRectF(565, 228, 20, 20), int(Qt.AlignmentFlag.AlignCenter), "❖")

        # Description text.
        desc_rect = QRectF(246, 258, 308, 32)
        p.setFont(self._font(9, QFont.Weight.Medium, "Segoe UI"))
        p.setPen(QColor("#e6ddc7"))
        p.drawText(
            desc_rect,
            int(Qt.AlignmentFlag.AlignCenter),
            "Touch-first digital health screening for kiosk demo,\n"
            "touchscreen use, and live hardware support.",
        )

        # Button/status row. These are painted controls so they perfectly align
        # with the background and do not create QWidget overlap problems.
        mode = safe_str(self._runtime_snapshot.get("mode"), MODE_HARDWARE).strip().lower()
        link_text = self._link_label()
        offline_text = "Online" if bool(self._runtime_snapshot.get("connected", False)) else "Offline"
        offline_accent = "#58e19a" if offline_text == "Online" else "#ff6b51"
        mode_text = "Demo Mode" if mode == MODE_DEMO else "Hardware Mode"

        self._draw_center_button(p, QRectF(224, 294, 100, 28), "⏻", "Standby", "#58dcff")
        self._draw_center_button(p, QRectF(350, 294, 100, 28), "⌁", offline_text, offline_accent)
        self._draw_center_button(p, QRectF(476, 294, 116, 28), "▣", mode_text, "#f2c257")

    def _draw_center_button(self, p: QPainter, rect: QRectF, icon: str, text: str, accent_hex: str) -> None:
        accent = QColor(accent_hex)

        glow = QColor(accent)
        glow.setAlpha(44)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawRoundedRect(rect.adjusted(-4, -4, 4, 4), 17, 17)

        bg_grad = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.bottom())
        bg_grad.setColorAt(0.0, QColor(8, 16, 17, 232))
        bg_grad.setColorAt(0.45, QColor(6, 8, 7, 244))
        bg_grad.setColorAt(1.0, QColor(2, 3, 3, 248))
        border = QColor(accent)
        border.setAlpha(205)
        p.setBrush(bg_grad)
        p.setPen(QPen(border, 1.3))
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)

        # Small icon circle.
        icon_box = QRectF(rect.left() + 12, rect.top() + 7, 16, 16)
        icon_bg = QColor(accent)
        icon_bg.setAlpha(30)
        p.setBrush(icon_bg)
        p.setPen(QPen(QColor(accent), 1.0))
        p.drawEllipse(icon_box)

        p.setFont(self._font(10, QFont.Weight.Bold, "Segoe UI"))
        p.setPen(QColor(accent))
        p.drawText(icon_box, int(Qt.AlignmentFlag.AlignCenter), icon)

        p.setFont(self._font(9, QFont.Weight.Bold, "Segoe UI"))
        p.setPen(QColor("#f7e8bd"))
        label_rect = rect.adjusted(32, 0, -8, 0)
        p.drawText(label_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self._elide_text(p, text, int(label_rect.width())))

    def _draw_dynamic_center_status(self, p: QPainter) -> None:
        # Status line above the loading bar. Shifted down to avoid button overlap.
        status_rect = QRectF(242, 326, 316, 22)
        self._soft_cover(p, status_rect.adjusted(-6, -2, 6, 2), radius=8, alpha=180)

        p.setFont(self._font(10, QFont.Weight.DemiBold))
        p.setPen(QColor("#ead59b"))
        p.drawText(status_rect, int(Qt.AlignmentFlag.AlignCenter), self._current_status_text)

        subtitle_rect = QRectF(221, 396, 358, 22)
        self._soft_cover(p, subtitle_rect.adjusted(-8, -2, 8, 2), radius=8, alpha=150)
        p.setFont(self._font(8, QFont.Weight.Medium))
        p.setPen(_rgba("#f2dfb0", 222))
        p.drawText(subtitle_rect, int(Qt.AlignmentFlag.AlignCenter), self._subtitle_text)

    def _draw_dynamic_progress(self, p: QPainter) -> None:
        outer = QRectF(209, 354, 392, 34)
        track = outer.adjusted(0.5, 0.5, -0.5, -0.5)
        radius = 17.0

        # Full cover removes the 0% baked into the background while preserving the same card feel.
        self._soft_cover(p, outer.adjusted(-4, -5, 4, 5), radius=20, alpha=210)

        # Outer halo.
        halo = QRadialGradient(QPointF(track.left() + 24, track.center().y()), 122)
        halo.setColorAt(0.0, QColor(255, 197, 71, 80))
        halo.setColorAt(1.0, QColor(255, 197, 71, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(QPointF(track.left() + 24, track.center().y()), 122, 34)

        track_grad = QLinearGradient(track.left(), track.top(), track.left(), track.bottom())
        track_grad.setColorAt(0.0, QColor(8, 11, 9, 245))
        track_grad.setColorAt(0.55, QColor(5, 8, 8, 252))
        track_grad.setColorAt(1.0, QColor(0, 0, 0, 250))
        p.setBrush(track_grad)
        p.setPen(QPen(_rgba("#ffd36a", 210), 1.4))
        p.drawRoundedRect(track, radius, radius)

        inner = track.adjusted(16, 12, -66, -12)
        p.setPen(QPen(_rgba("#b58e34", 78), 1.0))
        p.drawRoundedRect(inner, 4, 4)

        ratio = max(0.0, min(1.0, self._current_progress / 100.0))
        fill_w = inner.width() * ratio
        if fill_w > 2:
            fill = QRectF(inner.left(), inner.top(), fill_w, inner.height())
            fill_grad = QLinearGradient(fill.left(), fill.top(), fill.right(), fill.bottom())
            fill_grad.setColorAt(0.0, QColor("#f4ad2f"))
            fill_grad.setColorAt(0.52, QColor("#ffd565"))
            fill_grad.setColorAt(1.0, QColor("#fff2ab"))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill_grad)
            p.drawRoundedRect(fill, 4, 4)

            shimmer_center = fill.left() + fill.width() * self._shimmer_phase
            shimmer = QLinearGradient(shimmer_center - 42, fill.top(), shimmer_center + 42, fill.bottom())
            shimmer.setColorAt(0.0, QColor(255, 255, 255, 0))
            shimmer.setColorAt(0.50, QColor(255, 255, 255, 90))
            shimmer.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.setBrush(shimmer)
            p.drawRoundedRect(fill, 4, 4)

        # Left sparkle seen in the reference.
        sparkle_x = inner.left() + max(3.0, fill_w)
        p.setPen(QPen(_rgba("#fff2a6", 190), 1.2))
        p.drawLine(QPointF(sparkle_x - 7, track.center().y()), QPointF(sparkle_x + 7, track.center().y()))
        p.drawLine(QPointF(sparkle_x, track.center().y() - 7), QPointF(sparkle_x, track.center().y() + 7))
        p.setBrush(_rgba("#ffe276", 230))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(sparkle_x, track.center().y()), 3.2, 3.2)

        percent_rect = QRectF(track.right() - 62, track.top() + 4, 52, track.height() - 8)
        p.setBrush(QColor(7, 7, 5, 238))
        p.setPen(QPen(_rgba("#ffd36a", 170), 1.0))
        p.drawRoundedRect(percent_rect, 12, 12)

        p.setFont(self._font(15, QFont.Weight.Black))
        p.setPen(QColor("#f7d478"))
        p.drawText(percent_rect, int(Qt.AlignmentFlag.AlignCenter), f"{self._current_progress}%")

    def _draw_dynamic_bottom_hint(self, p: QPainter) -> None:
        rect = QRectF(200, 448, 400, 26)
        self._soft_cover(p, rect, radius=12, alpha=135)
        p.setFont(self._font(11, QFont.Weight.Medium))
        p.setPen(_rgba("#f4dfa8", 226))
        p.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), self._bottom_hint_text)

    def _soft_cover(self, p: QPainter, rect: QRectF, *, radius: float, alpha: int) -> None:
        # Dark glass patch matched to the central card/background so dynamic text does not double-render.
        path = self._rounded_path(rect, radius)
        grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        grad.setColorAt(0.0, QColor(6, 9, 8, max(0, min(255, alpha))))
        grad.setColorAt(1.0, QColor(1, 3, 3, max(0, min(255, alpha + 22))))
        p.setPen(Qt.PenStyle.NoPen)
        p.fillPath(path, grad)

    def _elide_text(self, p: QPainter, text: str, width: int) -> str:
        metrics = QFontMetrics(p.font())
        return metrics.elidedText(safe_str(text, ""), Qt.TextElideMode.ElideRight, width)
