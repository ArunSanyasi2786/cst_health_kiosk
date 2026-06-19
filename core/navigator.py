"""
core/navigator.py

Central route and screen navigation manager for the
CST Health Monitoring Station kiosk.

Why this file matters:
- It is the main glue between AppState and the actual PyQt screens
- It manages the QStackedWidget route registry
- It keeps navigation consistent across public screens, admin screens, and detail screens
- It supports animated transitions using core.animation_manager
- It keeps a route history stack for back navigation
- It allows screens to register themselves cleanly by route name
- It updates AppState whenever navigation changes

Design goals:
- Robust and explicit
- Safe even before all screens exist
- Reusable by main.py and later screens
- Works in both demo mode and hardware mode with the same flow
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QStackedWidget, QWidget

from core.animation_manager import AnimationManager, get_animation_manager
from core.app_state import AppState, get_app_state
from core.constants import (
    ADMIN_ROUTES,
    ALL_ROUTES,
    DETAIL_ROUTES,
    PUBLIC_ROUTES,
    ROUTE_ADMIN_LOGIN,
    ROUTE_ADMIN_PANEL,
    ROUTE_CONSULT,
    ROUTE_MEASURING,
    ROUTE_MODE_SELECT,
    ROUTE_QR,
    ROUTE_RESULTS,
    ROUTE_WELCOME,
    SCREEN_TITLES,
    SESSION_STATUS_MEASURING,
)
from core.logger import get_logger

logger = get_logger(__name__)


# ============================================================
# Dataclasses
# ============================================================

@dataclass
class RouteEntry:
    """
    Represents one registered route inside the navigator.
    """
    route_name: str
    widget: QWidget
    index: int
    title: str = ""
    allow_back: bool = True
    requires_admin: bool = False
    is_detail_route: bool = False
    is_public_route: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "route_name": self.route_name,
            "index": self.index,
            "title": self.title,
            "allow_back": self.allow_back,
            "requires_admin": self.requires_admin,
            "is_detail_route": self.is_detail_route,
            "is_public_route": self.is_public_route,
            "metadata": dict(self.metadata),
        }


# ============================================================
# Navigator
# ============================================================

class Navigator(QObject):
    """
    Central navigation manager for the kiosk.

    Responsibilities:
    - register screens by route name
    - manage QStackedWidget indices
    - switch screens with animation
    - maintain back-stack history
    - enforce basic admin access protection
    - update AppState route/title information
    - optionally notify screens about lifecycle events

    Expected later usage in main.py:
        navigator = Navigator(stacked_widget=stack, app_state=state)
        navigator.register_screen(ROUTE_WELCOME, welcome_screen)
        navigator.register_screen(ROUTE_MODE_SELECT, mode_screen)
        navigator.go_to(ROUTE_WELCOME)
    """

    route_registered = pyqtSignal(str)
    route_changed = pyqtSignal(str)
    route_change_blocked = pyqtSignal(str, str)
    back_navigation_changed = pyqtSignal(bool)
    navigation_error = pyqtSignal(str)
    current_widget_changed = pyqtSignal(object)

    def __init__(
        self,
        stacked_widget: Optional[QStackedWidget] = None,
        app_state: Optional[AppState] = None,
        animation_manager: Optional[AnimationManager] = None,
    ) -> None:
        super().__init__()

        self._logger = logger.bind(component="Navigator")

        self._stacked_widget: Optional[QStackedWidget] = stacked_widget
        self._app_state: AppState = app_state or get_app_state()
        self._animation_manager: AnimationManager = animation_manager or get_animation_manager()

        self._routes: Dict[str, RouteEntry] = {}
        self._history: List[str] = []
        self._blocked_routes_when_measuring: Set[str] = set()
        self._default_route: str = ROUTE_WELCOME
        self._animations_enabled: bool = True
        self._transition_in_progress: bool = False
        self._pending_route: Optional[str] = None

        self._configure_default_rules()

    # ========================================================
    # Internal setup
    # ========================================================

    def _configure_default_rules(self) -> None:
        """
        Define routes that should not be entered while a measurement is in progress,
        unless explicitly allowed.
        """
        self._blocked_routes_when_measuring = {
            ROUTE_ADMIN_LOGIN,
            ROUTE_ADMIN_PANEL,
            ROUTE_QR,
            ROUTE_CONSULT,
        }

    # ========================================================
    # Core object bindings
    # ========================================================

    def set_stacked_widget(self, stacked_widget: QStackedWidget) -> None:
        self._stacked_widget = stacked_widget
        self._logger.info("Stacked widget attached to navigator.")

    def stacked_widget(self) -> Optional[QStackedWidget]:
        return self._stacked_widget

    def set_app_state(self, app_state: AppState) -> None:
        self._app_state = app_state

    def app_state(self) -> AppState:
        return self._app_state

    def set_animation_manager(self, animation_manager: AnimationManager) -> None:
        self._animation_manager = animation_manager

    def animation_manager(self) -> AnimationManager:
        return self._animation_manager

    def set_default_route(self, route_name: str) -> None:
        if route_name in ALL_ROUTES:
            self._default_route = route_name

    def default_route(self) -> str:
        return self._default_route

    def enable_animations(self, enabled: bool = True) -> None:
        self._animations_enabled = bool(enabled)

    def animations_enabled(self) -> bool:
        return self._animations_enabled

    # ========================================================
    # Route registration
    # ========================================================

    def register_screen(
        self,
        route_name: str,
        widget: QWidget,
        *,
        title: Optional[str] = None,
        allow_back: bool = True,
        requires_admin: Optional[bool] = None,
        is_detail_route: Optional[bool] = None,
        is_public_route: Optional[bool] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RouteEntry:
        """
        Register a screen widget into the stacked widget and route registry.
        """
        if self._stacked_widget is None:
            raise RuntimeError("Navigator requires a QStackedWidget before registering screens.")

        cleaned_route = str(route_name).strip()
        if not cleaned_route:
            raise ValueError("Route name must not be empty.")
        if widget is None:
            raise ValueError(f"Widget for route '{cleaned_route}' must not be None.")
        if cleaned_route in self._routes:
            raise ValueError(f"Route '{cleaned_route}' is already registered.")

        widget_index = self._stacked_widget.addWidget(widget)

        resolved_title = title or SCREEN_TITLES.get(cleaned_route, cleaned_route.replace("_", " ").title())
        resolved_requires_admin = (
            bool(requires_admin) if requires_admin is not None else cleaned_route in ADMIN_ROUTES
        )
        resolved_is_detail_route = (
            bool(is_detail_route) if is_detail_route is not None else cleaned_route in DETAIL_ROUTES
        )
        resolved_is_public_route = (
            bool(is_public_route) if is_public_route is not None else cleaned_route in PUBLIC_ROUTES
        )

        entry = RouteEntry(
            route_name=cleaned_route,
            widget=widget,
            index=widget_index,
            title=resolved_title,
            allow_back=allow_back,
            requires_admin=resolved_requires_admin,
            is_detail_route=resolved_is_detail_route,
            is_public_route=resolved_is_public_route,
            metadata=dict(metadata or {}),
        )
        self._routes[cleaned_route] = entry

        self._wire_screen_if_supported(cleaned_route, widget)

        self._logger.info(
            "Route registered.",
            extra={
                "route": cleaned_route,
                "mode": self._app_state.runtime_mode(),
            },
        )
        self.route_registered.emit(cleaned_route)
        self.back_navigation_changed.emit(self.can_go_back())
        return entry

    def register_screens(self, mapping: Dict[str, QWidget]) -> Dict[str, RouteEntry]:
        """
        Convenience bulk registration helper.
        """
        result: Dict[str, RouteEntry] = {}
        for route_name, widget in mapping.items():
            result[route_name] = self.register_screen(route_name, widget)
        return result

    def _wire_screen_if_supported(self, route_name: str, widget: QWidget) -> None:
        """
        Best-effort screen injection so later screen classes can optionally expose:
        - set_navigator(navigator)
        - set_app_state(app_state)
        - on_route_registered(route_name)
        """
        try:
            setter = getattr(widget, "set_navigator", None)
            if callable(setter):
                setter(self)
        except Exception as exc:
            self._logger.warning("Could not inject navigator into route '%s': %s", route_name, exc)

        try:
            setter = getattr(widget, "set_app_state", None)
            if callable(setter):
                setter(self._app_state)
        except Exception as exc:
            self._logger.warning("Could not inject app_state into route '%s': %s", route_name, exc)

        try:
            callback = getattr(widget, "on_route_registered", None)
            if callable(callback):
                callback(route_name)
        except Exception as exc:
            self._logger.warning("Could not notify route '%s' of registration: %s", route_name, exc)

    # ========================================================
    # Route lookup helpers
    # ========================================================

    def is_registered(self, route_name: str) -> bool:
        return str(route_name).strip() in self._routes

    def route_entry(self, route_name: str) -> Optional[RouteEntry]:
        return self._routes.get(str(route_name).strip())

    def widget_for_route(self, route_name: str) -> Optional[QWidget]:
        entry = self.route_entry(route_name)
        return entry.widget if entry else None

    def route_index(self, route_name: str) -> int:
        entry = self.route_entry(route_name)
        return entry.index if entry else -1

    def current_route(self) -> str:
        return self._app_state.current_route()

    def current_entry(self) -> Optional[RouteEntry]:
        return self.route_entry(self.current_route())

    def current_widget(self) -> Optional[QWidget]:
        entry = self.current_entry()
        return entry.widget if entry else None

    def registered_routes(self) -> List[str]:
        return list(self._routes.keys())

    def registered_route_entries(self) -> Dict[str, Dict[str, Any]]:
        return {route_name: entry.to_dict() for route_name, entry in self._routes.items()}

    # ========================================================
    # History helpers
    # ========================================================

    def history(self) -> List[str]:
        return list(self._history)

    def clear_history(self) -> None:
        self._history.clear()
        self.back_navigation_changed.emit(self.can_go_back())

    def can_go_back(self) -> bool:
        return len(self._history) > 0

    def previous_route(self) -> str:
        return self._history[-1] if self._history else ""

    def _push_history(self, route_name: str) -> None:
        if not route_name:
            return
        self._history.append(route_name)
        self.back_navigation_changed.emit(self.can_go_back())

    def _pop_history(self) -> str:
        if not self._history:
            self.back_navigation_changed.emit(False)
            return ""
        route_name = self._history.pop()
        self.back_navigation_changed.emit(self.can_go_back())
        return route_name

    # ========================================================
    # Navigation guards
    # ========================================================

    def _is_admin_allowed(self, route_name: str) -> bool:
        entry = self.route_entry(route_name)
        if entry is None:
            return False
        if not entry.requires_admin:
            return True
        return bool(self._app_state.ui_snapshot().get("admin_authenticated", False))

    def _is_navigation_blocked_while_measuring(self, route_name: str) -> bool:
        session = self._app_state.session_snapshot()
        if session.get("status") != SESSION_STATUS_MEASURING:
            return False
        return route_name in self._blocked_routes_when_measuring

    def can_navigate_to(self, route_name: str) -> tuple[bool, str]:
        cleaned_route = str(route_name).strip()

        if self._transition_in_progress:
            return False, "transition_in_progress"

        if not self.is_registered(cleaned_route):
            return False, "route_not_registered"

        if self._is_navigation_blocked_while_measuring(cleaned_route):
            return False, "blocked_during_measurement"

        if not self._is_admin_allowed(cleaned_route):
            return False, "admin_required"

        return True, ""

    # ========================================================
    # Main navigation methods
    # ========================================================

    def go_to(
        self,
        route_name: str,
        *,
        add_current_to_history: bool = True,
        use_animation: Optional[bool] = None,
        clear_future_pending: bool = True,
    ) -> bool:
        """
        Navigate to a target route if registered and allowed.
        """
        cleaned_route = str(route_name).strip()
        current_route = self.current_route()

        if cleaned_route == current_route:
            return True

        allowed, reason = self.can_navigate_to(cleaned_route)
        if not allowed:
            self._logger.warning(
                "Navigation blocked.",
                extra={
                    "route": cleaned_route,
                    "mode": self._app_state.runtime_mode(),
                },
            )
            self.route_change_blocked.emit(cleaned_route, reason)
            return False

        if clear_future_pending:
            self._pending_route = None

        if add_current_to_history and current_route:
            current_entry = self.route_entry(current_route)
            if current_entry is not None and current_entry.allow_back:
                self._push_history(current_route)

        success = self._perform_route_change(
            cleaned_route,
            use_animation=self._animations_enabled if use_animation is None else bool(use_animation),
        )
        return success

    def go_to_default(self, *, use_animation: Optional[bool] = None) -> bool:
        return self.go_to(self._default_route, add_current_to_history=False, use_animation=use_animation)

    def go_back(self, *, use_animation: Optional[bool] = None) -> bool:
        """
        Navigate to previous route from history.
        """
        if not self.can_go_back():
            return False

        previous = self._pop_history()
        if not previous:
            return False

        if not self.is_registered(previous):
            self._logger.warning("Back route no longer registered: %s", previous)
            return False

        allowed, reason = self.can_navigate_to(previous)
        if not allowed:
            self._logger.warning("Back navigation blocked for route '%s': %s", previous, reason)
            self.route_change_blocked.emit(previous, reason)
            return False

        return self._perform_route_change(
            previous,
            use_animation=self._animations_enabled if use_animation is None else bool(use_animation),
        )

    def replace_current(
        self,
        route_name: str,
        *,
        use_animation: Optional[bool] = None,
    ) -> bool:
        """
        Navigate without pushing the current route to history.
        Useful for:
        - welcome -> mode select
        - measuring -> results
        - login -> admin panel
        """
        cleaned_route = str(route_name).strip()

        allowed, reason = self.can_navigate_to(cleaned_route)
        if not allowed:
            self.route_change_blocked.emit(cleaned_route, reason)
            return False

        return self._perform_route_change(
            cleaned_route,
            use_animation=self._animations_enabled if use_animation is None else bool(use_animation),
        )

    def force_go_to(
        self,
        route_name: str,
        *,
        use_animation: Optional[bool] = None,
        clear_history: bool = False,
    ) -> bool:
        """
        Bypass normal guards where needed for internal recovery flows.
        Should be used carefully.
        """
        cleaned_route = str(route_name).strip()
        if not self.is_registered(cleaned_route):
            self.navigation_error.emit(f"Route not registered: {cleaned_route}")
            return False

        if clear_history:
            self.clear_history()

        return self._perform_route_change(
            cleaned_route,
            use_animation=self._animations_enabled if use_animation is None else bool(use_animation),
        )

    def queue_navigation_after_transition(self, route_name: str) -> None:
        """
        Store one pending route if navigation is requested while transition is active.
        """
        self._pending_route = str(route_name).strip()

    def _perform_route_change(self, route_name: str, *, use_animation: bool = True) -> bool:
        if self._stacked_widget is None:
            self.navigation_error.emit("Navigator has no QStackedWidget attached.")
            return False

        entry = self.route_entry(route_name)
        if entry is None:
            self.navigation_error.emit(f"Route not registered: {route_name}")
            return False

        current_route = self.current_route()
        current_widget = self.current_widget()
        next_widget = entry.widget

        self._transition_in_progress = True

        self._notify_route_leave(current_route, current_widget)

        def _finalize() -> None:
            self._app_state.set_route(route_name)
            self._notify_route_enter(route_name, next_widget)

            self.route_changed.emit(route_name)
            self.current_widget_changed.emit(next_widget)

            self._transition_in_progress = False

            self._logger.info(
                "Route changed successfully.",
                extra={
                    "route": route_name,
                    "mode": self._app_state.runtime_mode(),
                    "session_id": self._app_state.session_snapshot().get("session_id", "-"),
                },
            )

            pending = self._pending_route
            self._pending_route = None
            if pending and pending != route_name and self.is_registered(pending):
                self.go_to(pending, add_current_to_history=True, use_animation=use_animation, clear_future_pending=False)

        try:
            if not use_animation:
                self._stacked_widget.setCurrentIndex(entry.index)
                _finalize()
                return True

            result = self._animation_manager.fade_switch_stacked_widget(
                stacked_widget=self._stacked_widget,
                target_index=entry.index,
                on_finished=_finalize,
                tag=f"route_transition:{route_name}",
            )

            if result is None:
                self._stacked_widget.setCurrentIndex(entry.index)
                _finalize()
            return True

        except Exception as exc:
            self._transition_in_progress = False
            self._logger.error("Route transition failed: %s", exc)
            self.navigation_error.emit(str(exc))
            return False

    # ========================================================
    # Screen lifecycle notifications
    # ========================================================

    def _notify_route_enter(self, route_name: str, widget: Optional[QWidget]) -> None:
        if widget is None:
            return

        self._safe_invoke(widget, "on_route_enter", route_name)
        self._safe_invoke(widget, "on_navigated_to", route_name)

    def _notify_route_leave(self, route_name: str, widget: Optional[QWidget]) -> None:
        if widget is None:
            return

        self._safe_invoke(widget, "on_route_leave", route_name)
        self._safe_invoke(widget, "on_navigated_from", route_name)

    def _safe_invoke(self, widget: QWidget, method_name: str, *args: Any) -> None:
        try:
            callback = getattr(widget, method_name, None)
            if callable(callback):
                callback(*args)
        except Exception as exc:
            self._logger.warning("Screen callback '%s' failed: %s", method_name, exc)

    # ========================================================
    # Route helpers for common flows
    # ========================================================

    def go_to_welcome(self, *, animated: Optional[bool] = None) -> bool:
        return self.replace_current(ROUTE_WELCOME, use_animation=animated)

    def go_to_mode_select(self, *, animated: Optional[bool] = None) -> bool:
        return self.replace_current(ROUTE_MODE_SELECT, use_animation=animated)

    def go_to_measuring(self, *, animated: Optional[bool] = None) -> bool:
        return self.replace_current(ROUTE_MEASURING, use_animation=animated)

    def go_to_results(self, *, animated: Optional[bool] = None) -> bool:
        return self.replace_current(ROUTE_RESULTS, use_animation=animated)

    def go_to_qr(self, *, animated: Optional[bool] = None) -> bool:
        return self.go_to(ROUTE_QR, add_current_to_history=True, use_animation=animated)

    def go_to_consult(self, *, animated: Optional[bool] = None) -> bool:
        return self.go_to(ROUTE_CONSULT, add_current_to_history=True, use_animation=animated)

    def go_to_admin_login(self, *, animated: Optional[bool] = None) -> bool:
        return self.go_to(ROUTE_ADMIN_LOGIN, add_current_to_history=True, use_animation=animated)

    def go_to_admin_panel(self, *, animated: Optional[bool] = None) -> bool:
        return self.replace_current(ROUTE_ADMIN_PANEL, use_animation=animated)

    # ========================================================
    # Measurement-aware navigation helpers
    # ========================================================

    def block_route_while_measuring(self, route_name: str) -> None:
        cleaned = str(route_name).strip()
        if cleaned:
            self._blocked_routes_when_measuring.add(cleaned)

    def unblock_route_while_measuring(self, route_name: str) -> None:
        cleaned = str(route_name).strip()
        self._blocked_routes_when_measuring.discard(cleaned)

    def blocked_routes_while_measuring(self) -> List[str]:
        return sorted(self._blocked_routes_when_measuring)

    # ========================================================
    # Reset / recovery helpers
    # ========================================================

    def reset_to_home(self, *, clear_history: bool = True, animated: Optional[bool] = None) -> bool:
        """
        Recovery helper that returns app to main selection screen.
        """
        if clear_history:
            self.clear_history()
        return self.force_go_to(ROUTE_MODE_SELECT, use_animation=animated, clear_history=False)

    def reset_to_welcome(self, *, clear_history: bool = True, animated: Optional[bool] = None) -> bool:
        if clear_history:
            self.clear_history()
        return self.force_go_to(ROUTE_WELCOME, use_animation=animated, clear_history=False)

    # ========================================================
    # Diagnostics
    # ========================================================

    def diagnostics(self) -> Dict[str, Any]:
        current = self.current_entry()
        return {
            "default_route": self._default_route,
            "current_route": self.current_route(),
            "current_index": current.index if current else -1,
            "registered_routes": self.registered_routes(),
            "history": self.history(),
            "can_go_back": self.can_go_back(),
            "animations_enabled": self._animations_enabled,
            "transition_in_progress": self._transition_in_progress,
            "pending_route": self._pending_route or "",
            "blocked_routes_when_measuring": self.blocked_routes_while_measuring(),
        }


# ============================================================
# Singleton accessor
# ============================================================

_NAVIGATOR_SINGLETON: Optional[Navigator] = None


def get_navigator(
    stacked_widget: Optional[QStackedWidget] = None,
    app_state: Optional[AppState] = None,
    animation_manager: Optional[AnimationManager] = None,
) -> Navigator:
    global _NAVIGATOR_SINGLETON
    if _NAVIGATOR_SINGLETON is None:
        _NAVIGATOR_SINGLETON = Navigator(
            stacked_widget=stacked_widget,
            app_state=app_state,
            animation_manager=animation_manager,
        )
    else:
        if stacked_widget is not None:
            _NAVIGATOR_SINGLETON.set_stacked_widget(stacked_widget)
        if app_state is not None:
            _NAVIGATOR_SINGLETON.set_app_state(app_state)
        if animation_manager is not None:
            _NAVIGATOR_SINGLETON.set_animation_manager(animation_manager)
    return _NAVIGATOR_SINGLETON