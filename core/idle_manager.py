"""
core/idle_manager.py

Lightweight kiosk idle manager for the CST Health Monitoring Station.

What this file does:
- observes global keyboard / mouse / touch activity
- resets an internal idle timer whenever the user interacts
- can return the kiosk to the welcome screen after inactivity
- intentionally avoids interrupting critical flows such as measurement and QR scanning

This implementation is conservative on purpose:
- no forced welcome jump while the QR screen is open
- no forced welcome jump while measurement is running
- no forced welcome jump on the welcome screen itself
- route changes reset the idle timer automatically
"""

from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import QEvent, QObject, QTimer
from PyQt6.QtWidgets import QApplication

try:
    from core.constants import (
        SCREEN_ADMIN_LOGIN,
        SCREEN_ADMIN_PANEL,
        SCREEN_CALIBRATION,
        SCREEN_CONSULT,
        SCREEN_DIAGNOSIS,
        SCREEN_MEASURING,
        SCREEN_MODE_SELECT,
        SCREEN_PARAMETERS,
        SCREEN_PUBLISH,
        SCREEN_QR,
        SCREEN_RESULTS,
        SCREEN_SETTINGS,
        SCREEN_STORAGE,
        SCREEN_WELCOME,
    )
except Exception:  # pragma: no cover
    SCREEN_WELCOME = "welcome"
    SCREEN_MODE_SELECT = "mode_select"
    SCREEN_MEASURING = "measuring"
    SCREEN_RESULTS = "results"
    SCREEN_QR = "qr"
    SCREEN_CONSULT = "consult"
    SCREEN_ADMIN_LOGIN = "admin_login"
    SCREEN_ADMIN_PANEL = "admin_panel"
    SCREEN_SETTINGS = "settings"
    SCREEN_CALIBRATION = "calibration"
    SCREEN_PARAMETERS = "parameters"
    SCREEN_DIAGNOSIS = "diagnosis"
    SCREEN_STORAGE = "storage"
    SCREEN_PUBLISH = "publish"

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


logger = get_logger(__name__)


class IdleManager(QObject):
    """
    Global activity watcher.

    Main behavior:
    - default public-screen timeout: 20 seconds
    - results screen timeout: 60 seconds
    - QR / consult / measuring / admin / maintenance screens: no forced timeout
    """

    DEFAULT_TIMEOUT_MS = 40_000
    RESULTS_TIMEOUT_MS = 40_000

    _NO_TIMEOUT_SCREENS = {
        SCREEN_WELCOME,
        SCREEN_MEASURING,
        SCREEN_QR,
        SCREEN_CONSULT,
        SCREEN_ADMIN_LOGIN,
        SCREEN_ADMIN_PANEL,
        SCREEN_SETTINGS,
        SCREEN_CALIBRATION,
        SCREEN_PARAMETERS,
        SCREEN_DIAGNOSIS,
        SCREEN_STORAGE,
        SCREEN_PUBLISH,
    }

    def __init__(
        self,
        parent: Optional[QObject] = None,
        *,
        app_state: Optional[object] = None,
        navigator: Optional[object] = None,
        config: Optional[object] = None,
        runtime_config: Optional[object] = None,
    ) -> None:
        super().__init__(parent)
        self._logger = logger
        self.app_state = app_state
        self.navigator = navigator
        self.config = config
        self.runtime_config = runtime_config
        self._current_screen = SCREEN_WELCOME
        self._enabled = True

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._handle_timeout)

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        self.reset_timer()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        event_type = event.type()
        if event_type in {
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseMove,
            QEvent.Type.Wheel,
            QEvent.Type.KeyPress,
            QEvent.Type.KeyRelease,
            QEvent.Type.TouchBegin,
            QEvent.Type.TouchUpdate,
            QEvent.Type.TouchEnd,
        }:
            self.touch(event_type)
        return super().eventFilter(obj, event)

    def notify_navigation(self, screen_name: Any = None) -> None:
        cleaned = safe_str(screen_name, "").strip()
        if cleaned:
            self._current_screen = cleaned
        self.reset_timer()

    def touch(self, *_args: Any) -> None:
        self.reset_timer()

    def activity(self, *_args: Any) -> None:
        self.reset_timer()

    def reset_timer(self, *_args: Any) -> None:
        if not self._enabled:
            self._timer.stop()
            return

        timeout_ms = self._timeout_for_current_screen()
        if timeout_ms <= 0:
            self._timer.stop()
            return

        self._timer.start(timeout_ms)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self.reset_timer()

    def _timeout_for_current_screen(self) -> int:
        current = self._resolve_current_screen_name()
        if current in self._NO_TIMEOUT_SCREENS:
            return 0
        if current == SCREEN_RESULTS:
            return self.RESULTS_TIMEOUT_MS
        return self.DEFAULT_TIMEOUT_MS

    def _resolve_current_screen_name(self) -> str:
        if self.navigator is not None:
            for method_name in ("current_name", "current_route", "route_name"):
                method = getattr(self.navigator, method_name, None)
                if callable(method):
                    try:
                        value = safe_str(method(), "").strip()
                        if value:
                            self._current_screen = value
                            return value
                    except Exception:
                        continue

        if self.app_state is not None:
            for attr_name in ("current_screen", "current_route"):
                attr = getattr(self.app_state, attr_name, None)
                if isinstance(attr, str) and attr.strip():
                    self._current_screen = attr.strip()
                    return self._current_screen
                if callable(attr):
                    try:
                        value = safe_str(attr(), "").strip()
                        if value:
                            self._current_screen = value
                            return value
                    except Exception:
                        continue

        return self._current_screen

    def _handle_timeout(self) -> None:
        current = self._resolve_current_screen_name()
        timeout_ms = self._timeout_for_current_screen()
        if timeout_ms <= 0:
            self.reset_timer()
            return

        if current == SCREEN_WELCOME:
            self.reset_timer()
            return

        navigated = False
        if self.navigator is not None:
            for method_name in ("go_to", "navigate_to", "navigate", "show_screen", "set_current_screen"):
                method = getattr(self.navigator, method_name, None)
                if callable(method):
                    try:
                        navigated = bool(method(SCREEN_WELCOME))
                        if navigated:
                            break
                    except Exception:
                        continue

        if navigated:
            try:
                welcome_widget = None
                if self.navigator is not None:
                    screen_getter = getattr(self.navigator, "screen", None)
                    if callable(screen_getter):
                        welcome_widget = screen_getter(SCREEN_WELCOME)
                if welcome_widget is not None:
                    callback = getattr(welcome_widget, "on_idle_return", None)
                    if callable(callback):
                        callback()
            except Exception:
                pass

        self._current_screen = SCREEN_WELCOME if navigated else current
        self.reset_timer()
