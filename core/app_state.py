"""
core/app_state.py

Central shared in-memory state container for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the main bridge between screens, widgets, and services
- It keeps the current runtime mode, active session, measurements, diagnosis, settings,
  calibration, thresholds, connection state, and UI route in one place
- It emits Qt signals so later screens and services stay linked without fragile coupling
- It supports both demo mode and hardware mode using the same UI flow

Design approach:
- QObject-based so PyQt screens can subscribe to changes
- Keeps state normalized and easy to serialize
- Loads persistent JSON defaults from config.py on startup
- Does not directly write to database; that belongs to services/*
- Does not directly own navigation widgets; it only stores and emits route state
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from config import (
    DEFAULT_THEME_MODE,
    read_calibration,
    read_session_defaults,
    read_settings,
    read_thresholds,
)
from core.constants import (
    AUTH_FAILED,
    AUTH_SUCCESS,
    EMPTY_DIAGNOSIS_PAYLOAD,
    EMPTY_MEASUREMENT_PAYLOAD,
    EMPTY_SESSION_PAYLOAD,
    HEALTH_STATUS_NEEDS_ATTENTION,
    HEALTH_STATUS_NORMAL,
    MODE_DEMO,
    MODE_HARDWARE,
    PRIMARY_METRIC_KEYS,
    ROUTE_WELCOME,
    SCREEN_TITLES,
    SESSION_STATUS_CANCELLED,
    SESSION_STATUS_COMPLETE,
    SESSION_STATUS_ERROR,
    SESSION_STATUS_IDLE,
    SESSION_STATUS_MEASURING,
    THEME_DARK,
    THEME_LIGHT,
)
from core.logger import get_logger
from core.utils import (
    deep_copy,
    deep_merge_dicts,
    generate_session_id,
    metric_is_meaningful,
    normalize_measurement_payload,
    now_iso,
    prune_none_values,
    safe_float,
    safe_int,
    safe_str,
    validate_brightness,
    validate_runtime_mode,
    validate_volume,
)

logger = get_logger(__name__)


# ============================================================
# Dataclasses for structured state
# ============================================================

@dataclass
class ConnectionState:
    """
    Lightweight runtime connection state shared by UI and services.
    """
    network_connected: bool = False
    serial_connected: bool = False
    serial_port: str = ""
    serial_baudrate: int = 115200
    esp32_connected: bool = False
    raspberry_pi_detected: bool = False
    connection_label: str = "Disconnected"
    connection_detail: str = "No hardware connection detected."
    last_heartbeat_at: str = ""
    last_error: str = ""
    demo_mode_active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class UIState:
    """
    General UI state not tied to a specific measurement session.
    """
    current_route: str = ROUTE_WELCOME
    current_title: str = SCREEN_TITLES.get(ROUTE_WELCOME, "Welcome")
    previous_route: str = ""
    theme_mode: str = DEFAULT_THEME_MODE
    fullscreen: bool = True
    brightness_percent: int = 75
    volume_percent: int = 55
    screen_timeout: str = "15_min"
    busy: bool = False
    status_message: str = ""
    last_error_message: str = ""
    admin_authenticated: bool = False
    admin_auth_status: str = ""
    mode_selector_visible: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MeasurementSessionState:
    """
    The active user measurement session.
    """
    session_id: str = ""
    mode: str = MODE_DEMO
    status: str = SESSION_STATUS_IDLE
    started_at: str = ""
    measuring_started_at: str = ""
    completed_at: str = ""
    cancelled_at: str = ""
    report_path: str = ""
    qr_path: str = ""
    measurements: Dict[str, float] = field(default_factory=lambda: dict(EMPTY_MEASUREMENT_PAYLOAD))
    diagnosis: Dict[str, Any] = field(default_factory=lambda: dict(EMPTY_DIAGNOSIS_PAYLOAD))
    measurement_progress: int = 0
    measurement_step_message: str = ""
    measurement_complete_ratio: float = 0.0
    source_label: str = "Demo"
    persisted: bool = False

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        return payload


# ============================================================
# Main AppState object
# ============================================================

class AppState(QObject):
    """
    Shared state object for the whole application.

    Major responsibilities:
    - keep active runtime mode (demo / hardware)
    - hold current session, measurements, diagnosis, report, QR
    - keep connection state for ESP32 / Raspberry Pi / network
    - keep UI state such as route, title, theme, brightness, volume
    - expose signals so screens and services update reactively
    """

    # -------------------------
    # High-level signals
    # -------------------------
    state_initialized = pyqtSignal()
    state_reset = pyqtSignal()

    # -------------------------
    # UI / route signals
    # -------------------------
    route_changed = pyqtSignal(str)
    title_changed = pyqtSignal(str)
    theme_changed = pyqtSignal(str)
    busy_changed = pyqtSignal(bool)
    status_message_changed = pyqtSignal(str)
    error_message_changed = pyqtSignal(str)
    ui_state_changed = pyqtSignal(dict)

    # -------------------------
    # Authentication signals
    # -------------------------
    admin_auth_changed = pyqtSignal(bool)
    admin_auth_status_changed = pyqtSignal(str)

    # -------------------------
    # Mode / settings signals
    # -------------------------
    runtime_mode_changed = pyqtSignal(str)
    settings_changed = pyqtSignal(dict)
    calibration_changed = pyqtSignal(dict)
    thresholds_changed = pyqtSignal(dict)

    # -------------------------
    # Connection signals
    # -------------------------
    connection_changed = pyqtSignal(dict)
    network_connection_changed = pyqtSignal(bool)
    serial_connection_changed = pyqtSignal(bool)
    esp32_connection_changed = pyqtSignal(bool)

    # -------------------------
    # Session signals
    # -------------------------
    session_started = pyqtSignal(str)
    session_reset_signal = pyqtSignal(str)
    session_status_changed = pyqtSignal(str)
    session_completed = pyqtSignal(dict)
    session_cancelled = pyqtSignal(str)
    session_persisted_changed = pyqtSignal(bool)
    session_changed = pyqtSignal(dict)

    # -------------------------
    # Measurement signals
    # -------------------------
    measurements_changed = pyqtSignal(dict)
    measurement_progress_changed = pyqtSignal(int)
    measurement_step_changed = pyqtSignal(str)
    measurement_completion_ratio_changed = pyqtSignal(float)
    metric_value_changed = pyqtSignal(str, float)

    # -------------------------
    # Diagnosis / report / QR signals
    # -------------------------
    diagnosis_changed = pyqtSignal(dict)
    report_path_changed = pyqtSignal(str)
    qr_path_changed = pyqtSignal(str)

    # -------------------------
    # Storage / publish / misc
    # -------------------------
    storage_summary_changed = pyqtSignal(dict)
    publish_summary_changed = pyqtSignal(dict)

    def __init__(self) -> None:
        super().__init__()

        self._logger = logger.bind(component="AppState")

        # Persistent configuration loaded from disk
        self._settings: Dict[str, Any] = {}
        self._calibration: Dict[str, Any] = {}
        self._thresholds: Dict[str, Any] = {}
        self._session_defaults: Dict[str, Any] = {}

        # Runtime memory state
        self.ui = UIState()
        self.connection = ConnectionState()
        self.session = MeasurementSessionState()

        self._storage_summary: Dict[str, Any] = {}
        self._publish_summary: Dict[str, Any] = {}

        self._load_persistent_state()
        self._initialize_runtime_state()

    # ========================================================
    # Initialization
    # ========================================================

    def _load_persistent_state(self) -> None:
        """
        Load JSON-backed settings, calibration, thresholds, and session defaults.
        """
        self._settings = read_settings()
        self._calibration = read_calibration()
        self._thresholds = read_thresholds()
        self._session_defaults = read_session_defaults()

        self._logger.info("Persistent state loaded from JSON configuration files.")

    def _initialize_runtime_state(self) -> None:
        """
        Initialize runtime UI/session state from loaded configuration.
        """
        display = self._settings.get("display", {})
        audio = self._settings.get("audio", {})
        system = self._settings.get("system", {})
        hardware = self._settings.get("hardware", {})

        theme_mode = safe_str(display.get("theme_mode"), DEFAULT_THEME_MODE).lower()
        if theme_mode not in {THEME_DARK, THEME_LIGHT}:
            theme_mode = DEFAULT_THEME_MODE

        runtime_mode = validate_runtime_mode(system.get("runtime_mode"))
        preferred_baudrate = safe_int(hardware.get("serial_baudrate"), default=115200)

        self.ui.theme_mode = theme_mode
        self.ui.brightness_percent = validate_brightness(display.get("brightness_percent"))
        self.ui.volume_percent = validate_volume(audio.get("volume_percent"))
        self.ui.screen_timeout = safe_str(display.get("screen_timeout"), "15_min")
        self.ui.fullscreen = bool(display.get("fullscreen", True))
        self.ui.current_route = ROUTE_WELCOME
        self.ui.current_title = SCREEN_TITLES.get(ROUTE_WELCOME, "Welcome")
        self.ui.mode_selector_visible = bool(
            self._session_defaults.get("session", {}).get("allow_manual_mode_switch", True)
        )

        self.connection.demo_mode_active = runtime_mode == MODE_DEMO
        self.connection.serial_baudrate = preferred_baudrate
        self.connection.connection_label = "Demo Mode Active" if runtime_mode == MODE_DEMO else "Hardware Waiting"
        self.connection.connection_detail = (
            "Using simulated measurements."
            if runtime_mode == MODE_DEMO
            else "Waiting for hardware connection."
        )

        self.session.mode = runtime_mode
        self.session.source_label = "Demo" if runtime_mode == MODE_DEMO else "Hardware"

        self._logger.info(
            "Runtime state initialized.",
            extra={
                "mode": runtime_mode,
                "route": self.ui.current_route,
            },
        )

        self.state_initialized.emit()
        self.settings_changed.emit(self.settings_snapshot())
        self.calibration_changed.emit(self.calibration_snapshot())
        self.thresholds_changed.emit(self.thresholds_snapshot())
        self.ui_state_changed.emit(self.ui_snapshot())
        self.connection_changed.emit(self.connection_snapshot())
        self.session_changed.emit(self.session_snapshot())

    # ========================================================
    # Snapshot helpers
    # ========================================================

    def settings_snapshot(self) -> Dict[str, Any]:
        return deep_copy(self._settings)

    def calibration_snapshot(self) -> Dict[str, Any]:
        return deep_copy(self._calibration)

    def thresholds_snapshot(self) -> Dict[str, Any]:
        return deep_copy(self._thresholds)

    def session_defaults_snapshot(self) -> Dict[str, Any]:
        return deep_copy(self._session_defaults)

    def ui_snapshot(self) -> Dict[str, Any]:
        return self.ui.to_dict()

    def connection_snapshot(self) -> Dict[str, Any]:
        return self.connection.to_dict()

    def session_snapshot(self) -> Dict[str, Any]:
        return self.session.to_dict()

    def storage_summary_snapshot(self) -> Dict[str, Any]:
        return deep_copy(self._storage_summary)

    def publish_summary_snapshot(self) -> Dict[str, Any]:
        return deep_copy(self._publish_summary)

    def full_snapshot(self) -> Dict[str, Any]:
        return {
            "ui": self.ui_snapshot(),
            "connection": self.connection_snapshot(),
            "session": self.session_snapshot(),
            "settings": self.settings_snapshot(),
            "calibration": self.calibration_snapshot(),
            "thresholds": self.thresholds_snapshot(),
            "session_defaults": self.session_defaults_snapshot(),
            "storage_summary": self.storage_summary_snapshot(),
            "publish_summary": self.publish_summary_snapshot(),
        }

    # ========================================================
    # Route / UI state
    # ========================================================

    def current_route(self) -> str:
        return self.ui.current_route

    def current_title(self) -> str:
        return self.ui.current_title

    def set_route(self, route_name: str) -> None:
        route_name = safe_str(route_name, ROUTE_WELCOME)
        if not route_name:
            route_name = ROUTE_WELCOME

        if route_name == self.ui.current_route:
            return

        previous = self.ui.current_route
        self.ui.previous_route = previous
        self.ui.current_route = route_name
        self.ui.current_title = SCREEN_TITLES.get(route_name, route_name.replace("_", " ").title())

        self._logger.info(
            "Route changed.",
            extra={
                "route": route_name,
                "mode": self.session.mode,
            },
        )

        self.route_changed.emit(route_name)
        self.title_changed.emit(self.ui.current_title)
        self.ui_state_changed.emit(self.ui_snapshot())

    def set_title(self, title: str) -> None:
        cleaned = safe_str(title, self.ui.current_title).strip()
        if not cleaned:
            return
        if cleaned == self.ui.current_title:
            return

        self.ui.current_title = cleaned
        self.title_changed.emit(cleaned)
        self.ui_state_changed.emit(self.ui_snapshot())

    def set_busy(self, value: bool) -> None:
        value = bool(value)
        if value == self.ui.busy:
            return
        self.ui.busy = value
        self.busy_changed.emit(value)
        self.ui_state_changed.emit(self.ui_snapshot())

    def set_status_message(self, message: str) -> None:
        message = safe_str(message, "").strip()
        if message == self.ui.status_message:
            return
        self.ui.status_message = message
        self.status_message_changed.emit(message)
        self.ui_state_changed.emit(self.ui_snapshot())

    def clear_status_message(self) -> None:
        self.set_status_message("")

    def set_error_message(self, message: str) -> None:
        message = safe_str(message, "").strip()
        self.ui.last_error_message = message
        self.error_message_changed.emit(message)
        self.ui_state_changed.emit(self.ui_snapshot())

        if message:
            self._logger.warning(
                "UI error message set.",
                extra={
                    "route": self.ui.current_route,
                    "mode": self.session.mode,
                },
            )

    def clear_error_message(self) -> None:
        self.set_error_message("")

    def set_theme_mode(self, theme_mode: str) -> None:
        theme_mode = safe_str(theme_mode, DEFAULT_THEME_MODE).lower()
        if theme_mode not in {THEME_DARK, THEME_LIGHT}:
            theme_mode = DEFAULT_THEME_MODE

        if theme_mode == self.ui.theme_mode:
            return

        self.ui.theme_mode = theme_mode

        display = self._settings.setdefault("display", {})
        display["theme_mode"] = theme_mode

        self._logger.info("Theme mode changed.", extra={"mode": self.session.mode})
        self.theme_changed.emit(theme_mode)
        self.settings_changed.emit(self.settings_snapshot())
        self.ui_state_changed.emit(self.ui_snapshot())

    def set_brightness_percent(self, value: Any) -> None:
        brightness = validate_brightness(value)
        if brightness == self.ui.brightness_percent:
            return

        self.ui.brightness_percent = brightness
        self._settings.setdefault("display", {})["brightness_percent"] = brightness

        self.settings_changed.emit(self.settings_snapshot())
        self.ui_state_changed.emit(self.ui_snapshot())

    def set_volume_percent(self, value: Any) -> None:
        volume = validate_volume(value)
        if volume == self.ui.volume_percent:
            return

        self.ui.volume_percent = volume
        self._settings.setdefault("audio", {})["volume_percent"] = volume

        self.settings_changed.emit(self.settings_snapshot())
        self.ui_state_changed.emit(self.ui_snapshot())

    def set_screen_timeout(self, timeout_key: str) -> None:
        timeout_key = safe_str(timeout_key, "15_min")
        if timeout_key == self.ui.screen_timeout:
            return

        self.ui.screen_timeout = timeout_key
        self._settings.setdefault("display", {})["screen_timeout"] = timeout_key

        self.settings_changed.emit(self.settings_snapshot())
        self.ui_state_changed.emit(self.ui_snapshot())

    def set_fullscreen(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self.ui.fullscreen:
            return

        self.ui.fullscreen = enabled
        self._settings.setdefault("display", {})["fullscreen"] = enabled

        self.settings_changed.emit(self.settings_snapshot())
        self.ui_state_changed.emit(self.ui_snapshot())

    # ========================================================
    # Admin authentication state
    # ========================================================

    def set_admin_authenticated(self, authenticated: bool, status: str = "") -> None:
        authenticated = bool(authenticated)
        status = safe_str(status, "").strip()

        changed = False

        if self.ui.admin_authenticated != authenticated:
            self.ui.admin_authenticated = authenticated
            self.admin_auth_changed.emit(authenticated)
            changed = True

        if status and status != self.ui.admin_auth_status:
            self.ui.admin_auth_status = status
            self.admin_auth_status_changed.emit(status)
            changed = True

        if changed:
            self.ui_state_changed.emit(self.ui_snapshot())

    def mark_admin_login_success(self) -> None:
        self.set_admin_authenticated(True, AUTH_SUCCESS)
        self._logger.info("Admin authenticated successfully.", extra={"route": self.ui.current_route})

    def mark_admin_login_failure(self) -> None:
        self.set_admin_authenticated(False, AUTH_FAILED)
        self._logger.warning("Admin authentication failed.", extra={"route": self.ui.current_route})

    def logout_admin(self) -> None:
        self.set_admin_authenticated(False, "")
        self._logger.info("Admin logged out.", extra={"route": self.ui.current_route})

    # ========================================================
    # Runtime mode
    # ========================================================

    def runtime_mode(self) -> str:
        return self.session.mode

    def is_demo_mode(self) -> bool:
        return self.session.mode == MODE_DEMO

    def is_hardware_mode(self) -> bool:
        return self.session.mode == MODE_HARDWARE

    def set_runtime_mode(self, mode: str, reset_session: bool = False) -> None:
        normalized = validate_runtime_mode(mode)

        if normalized == self.session.mode and not reset_session:
            return

        self.session.mode = normalized
        self.session.source_label = "Demo" if normalized == MODE_DEMO else "Hardware"

        self.connection.demo_mode_active = normalized == MODE_DEMO
        self.connection.connection_label = "Demo Mode Active" if normalized == MODE_DEMO else self.connection.connection_label
        if normalized == MODE_DEMO:
            self.connection.connection_detail = "Using simulated measurements."
            self.connection.serial_connected = False
            self.connection.esp32_connected = False

        self._settings.setdefault("system", {})["runtime_mode"] = normalized

        self._logger.info(
            "Runtime mode changed.",
            extra={
                "mode": normalized,
                "route": self.ui.current_route,
            },
        )

        if reset_session:
            self.reset_session(mode=normalized)

        self.runtime_mode_changed.emit(normalized)
        self.settings_changed.emit(self.settings_snapshot())
        self.connection_changed.emit(self.connection_snapshot())
        self.session_changed.emit(self.session_snapshot())

    # ========================================================
    # Connection state
    # ========================================================

    def update_connection_state(self, **fields: Any) -> None:
        """
        Patch connection state in a flexible way.
        """
        changed = False

        for field_name, value in fields.items():
            if not hasattr(self.connection, field_name):
                continue
            if getattr(self.connection, field_name) != value:
                setattr(self.connection, field_name, value)
                changed = True

        if changed:
            self.connection_changed.emit(self.connection_snapshot())
            self.network_connection_changed.emit(self.connection.network_connected)
            self.serial_connection_changed.emit(self.connection.serial_connected)
            self.esp32_connection_changed.emit(self.connection.esp32_connected)

    def set_network_connected(self, connected: bool) -> None:
        self.update_connection_state(network_connected=bool(connected))

    def set_serial_connected(self, connected: bool, serial_port: str = "") -> None:
        payload = {
            "serial_connected": bool(connected),
        }
        if serial_port:
            payload["serial_port"] = serial_port

        if connected:
            payload["connection_label"] = "Serial Connected"
            payload["connection_detail"] = f"Serial port connected: {serial_port or 'available'}"
        else:
            payload["connection_label"] = "Serial Waiting"
            payload["connection_detail"] = "Waiting for ESP32 serial connection."

        self.update_connection_state(**payload)

    def set_esp32_connected(self, connected: bool, heartbeat_at: str = "", error_message: str = "") -> None:
        payload = {
            "esp32_connected": bool(connected),
        }

        if heartbeat_at:
            payload["last_heartbeat_at"] = heartbeat_at

        if error_message:
            payload["last_error"] = error_message

        if connected:
            payload["connection_label"] = "Hardware Connected"
            payload["connection_detail"] = "ESP32 is connected and sending data."
            payload["demo_mode_active"] = False
        elif self.is_hardware_mode():
            payload["connection_label"] = "Hardware Waiting"
            payload["connection_detail"] = "ESP32 not detected yet."

        self.update_connection_state(**payload)

    def set_raspberry_pi_detected(self, detected: bool) -> None:
        self.update_connection_state(raspberry_pi_detected=bool(detected))

    # ========================================================
    # Persistent settings / calibration / thresholds in memory
    # ========================================================

    def reload_persistent_state(self) -> None:
        """
        Reload settings/calibration/thresholds/session defaults from disk.
        Useful after services save changes.
        """
        self._load_persistent_state()
        self._initialize_runtime_state()

    def get_setting(self, *keys: str, default: Any = None) -> Any:
        current: Any = self._settings
        for key in keys:
            if not isinstance(current, Mapping):
                return default
            if key not in current:
                return default
            current = current[key]
        return current

    def update_settings(self, patch: Mapping[str, Any]) -> None:
        self._settings = deep_merge_dicts(self._settings, patch)
        self._sync_ui_from_settings()
        self.settings_changed.emit(self.settings_snapshot())
        self.ui_state_changed.emit(self.ui_snapshot())

    def _sync_ui_from_settings(self) -> None:
        display = self._settings.get("display", {})
        audio = self._settings.get("audio", {})
        system = self._settings.get("system", {})

        self.ui.theme_mode = safe_str(display.get("theme_mode"), self.ui.theme_mode).lower() or self.ui.theme_mode
        self.ui.brightness_percent = validate_brightness(display.get("brightness_percent", self.ui.brightness_percent))
        self.ui.volume_percent = validate_volume(audio.get("volume_percent", self.ui.volume_percent))
        self.ui.screen_timeout = safe_str(display.get("screen_timeout"), self.ui.screen_timeout)
        self.ui.fullscreen = bool(display.get("fullscreen", self.ui.fullscreen))

        runtime_mode = validate_runtime_mode(system.get("runtime_mode", self.session.mode))
        self.session.mode = runtime_mode
        self.session.source_label = "Demo" if runtime_mode == MODE_DEMO else "Hardware"
        self.connection.demo_mode_active = runtime_mode == MODE_DEMO

    def set_setting_value(self, section: str, key: str, value: Any) -> None:
        if not section or not key:
            return
        section_data = self._settings.setdefault(section, {})
        if not isinstance(section_data, dict):
            section_data = {}
            self._settings[section] = section_data

        section_data[key] = value
        self._sync_ui_from_settings()
        self.settings_changed.emit(self.settings_snapshot())
        self.ui_state_changed.emit(self.ui_snapshot())

    def get_calibration_for_sensor(self, sensor_key: str) -> Dict[str, Any]:
        sensor = self._calibration.get(sensor_key, {})
        return deep_copy(sensor) if isinstance(sensor, dict) else {}

    def update_calibration_for_sensor(self, sensor_key: str, patch: Mapping[str, Any]) -> None:
        current = self._calibration.get(sensor_key, {})
        if not isinstance(current, dict):
            current = {}
        current = deep_merge_dicts(current, patch)
        self._calibration[sensor_key] = current
        self.calibration_changed.emit(self.calibration_snapshot())

    def get_thresholds_for_metric(self, metric_key: str) -> Dict[str, Any]:
        metric = self._thresholds.get(metric_key, {})
        return deep_copy(metric) if isinstance(metric, dict) else {}

    def update_thresholds_for_metric(self, metric_key: str, patch: Mapping[str, Any]) -> None:
        current = self._thresholds.get(metric_key, {})
        if not isinstance(current, dict):
            current = {}
        current = deep_merge_dicts(current, patch)
        self._thresholds[metric_key] = current
        self.thresholds_changed.emit(self.thresholds_snapshot())

    # ========================================================
    # Session lifecycle
    # ========================================================

    def create_new_session(self, mode: Optional[str] = None) -> str:
        """
        Create a fresh active session and return the new session_id.
        """
        runtime_mode = validate_runtime_mode(mode or self.session.mode)

        self.session = MeasurementSessionState(
            session_id=generate_session_id(prefix="CST", include_date=True),
            mode=runtime_mode,
            status=SESSION_STATUS_IDLE,
            started_at=now_iso(),
            measurements=dict(EMPTY_MEASUREMENT_PAYLOAD),
            diagnosis=dict(EMPTY_DIAGNOSIS_PAYLOAD),
            source_label="Demo" if runtime_mode == MODE_DEMO else "Hardware",
            persisted=False,
        )

        self.connection.demo_mode_active = runtime_mode == MODE_DEMO

        self._logger.info(
            "New session created.",
            extra={
                "session_id": self.session.session_id,
                "mode": runtime_mode,
                "route": self.ui.current_route,
            },
        )

        self.session_started.emit(self.session.session_id)
        self.session_changed.emit(self.session_snapshot())
        return self.session.session_id

    def reset_session(self, mode: Optional[str] = None) -> None:
        """
        Reset the active session to an empty state and keep the chosen mode.
        """
        runtime_mode = validate_runtime_mode(mode or self.session.mode)

        self.session = MeasurementSessionState(
            session_id="",
            mode=runtime_mode,
            status=SESSION_STATUS_IDLE,
            measurements=dict(EMPTY_MEASUREMENT_PAYLOAD),
            diagnosis=dict(EMPTY_DIAGNOSIS_PAYLOAD),
            source_label="Demo" if runtime_mode == MODE_DEMO else "Hardware",
            persisted=False,
        )

        self._logger.info(
            "Session reset.",
            extra={
                "mode": runtime_mode,
                "route": self.ui.current_route,
            },
        )

        self.session_reset_signal.emit(runtime_mode)
        self.session_status_changed.emit(self.session.status)
        self.measurements_changed.emit(deep_copy(self.session.measurements))
        self.diagnosis_changed.emit(deep_copy(self.session.diagnosis))
        self.measurement_progress_changed.emit(self.session.measurement_progress)
        self.measurement_step_changed.emit(self.session.measurement_step_message)
        self.measurement_completion_ratio_changed.emit(self.session.measurement_complete_ratio)
        self.report_path_changed.emit("")
        self.qr_path_changed.emit("")
        self.session_changed.emit(self.session_snapshot())
        self.state_reset.emit()

    def ensure_active_session(self) -> str:
        if not self.session.session_id:
            return self.create_new_session(mode=self.session.mode)
        return self.session.session_id

    def mark_measurement_started(self, step_message: str = "Preparing sensors...") -> str:
        session_id = self.ensure_active_session()

        self.session.status = SESSION_STATUS_MEASURING
        self.session.measuring_started_at = now_iso()
        self.session.measurement_step_message = safe_str(step_message, "Preparing sensors...")
        self.session.measurement_progress = 0
        self.session.measurement_complete_ratio = 0.0

        self._logger.info(
            "Measurement started.",
            extra={
                "session_id": session_id,
                "mode": self.session.mode,
                "route": self.ui.current_route,
            },
        )

        self.session_status_changed.emit(self.session.status)
        self.measurement_step_changed.emit(self.session.measurement_step_message)
        self.measurement_progress_changed.emit(self.session.measurement_progress)
        self.measurement_completion_ratio_changed.emit(self.session.measurement_complete_ratio)
        self.session_changed.emit(self.session_snapshot())

        return session_id

    def mark_measurement_cancelled(self) -> None:
        if not self.session.session_id:
            return

        self.session.status = SESSION_STATUS_CANCELLED
        self.session.cancelled_at = now_iso()
        self.session.measurement_step_message = "Measurement cancelled."
        self.session.measurement_progress = 0

        self._logger.info(
            "Measurement cancelled.",
            extra={
                "session_id": self.session.session_id,
                "mode": self.session.mode,
                "route": self.ui.current_route,
            },
        )

        self.session_status_changed.emit(self.session.status)
        self.measurement_step_changed.emit(self.session.measurement_step_message)
        self.measurement_progress_changed.emit(self.session.measurement_progress)
        self.session_cancelled.emit(self.session.session_id)
        self.session_changed.emit(self.session_snapshot())

    def mark_measurement_error(self, message: str = "Measurement error.") -> None:
        self.session.status = SESSION_STATUS_ERROR
        self.session.measurement_step_message = safe_str(message, "Measurement error.")
        self.session.measurement_progress = 0

        self._logger.warning(
            "Measurement error state set.",
            extra={
                "session_id": self.session.session_id or "-",
                "mode": self.session.mode,
                "route": self.ui.current_route,
            },
        )

        self.session_status_changed.emit(self.session.status)
        self.measurement_step_changed.emit(self.session.measurement_step_message)
        self.session_changed.emit(self.session_snapshot())

    def mark_session_complete(self, report_path: str = "", qr_path: str = "") -> None:
        """
        Mark session as completed. Report/QR paths are optional at completion time.
        """
        if not self.session.session_id:
            self.ensure_active_session()

        self.session.status = SESSION_STATUS_COMPLETE
        self.session.completed_at = now_iso()
        self.session.measurement_progress = 100
        self.session.measurement_complete_ratio = 100.0
        self.session.measurement_step_message = "Measurement complete."

        if report_path:
            self.session.report_path = safe_str(report_path, "")
        if qr_path:
            self.session.qr_path = safe_str(qr_path, "")

        self._logger.info(
            "Session completed.",
            extra={
                "session_id": self.session.session_id,
                "mode": self.session.mode,
                "route": self.ui.current_route,
            },
        )

        self.session_status_changed.emit(self.session.status)
        self.measurement_progress_changed.emit(self.session.measurement_progress)
        self.measurement_completion_ratio_changed.emit(self.session.measurement_complete_ratio)
        self.measurement_step_changed.emit(self.session.measurement_step_message)
        self.report_path_changed.emit(self.session.report_path)
        self.qr_path_changed.emit(self.session.qr_path)
        self.session_completed.emit(self.session_snapshot())
        self.session_changed.emit(self.session_snapshot())

    def set_session_persisted(self, persisted: bool) -> None:
        persisted = bool(persisted)
        if self.session.persisted == persisted:
            return
        self.session.persisted = persisted
        self.session_persisted_changed.emit(persisted)
        self.session_changed.emit(self.session_snapshot())

    # ========================================================
    # Measurement updates
    # ========================================================

    def current_measurements(self) -> Dict[str, float]:
        return deep_copy(self.session.measurements)

    def get_metric_value(self, metric_key: str, default: float = 0.0) -> float:
        return safe_float(self.session.measurements.get(metric_key, default), default=default)

    def update_measurements(
        self,
        measurements: Mapping[str, Any],
        *,
        apply_calibration: bool = False,
        auto_fill_bmi: bool = True,
        emit_signals: bool = True,
    ) -> Dict[str, float]:
        """
        Merge new measurement values into the current session.

        Notes:
        - can be used by demo mode generator or hardware serial ingestion
        - calibration application is optional because some services may apply it first
        """
        self.ensure_active_session()

        merged = dict(self.session.measurements)
        for metric_key in PRIMARY_METRIC_KEYS:
            if metric_key in measurements:
                merged[metric_key] = measurements.get(metric_key)

        normalized = normalize_measurement_payload(merged)

        if apply_calibration:
            normalized = self.apply_calibration_to_measurements(normalized, recompute_bmi=auto_fill_bmi)

        self.session.measurements = normalized
        self.session.measurement_complete_ratio = self.compute_measurement_completion_ratio(normalized)

        if emit_signals:
            self.measurements_changed.emit(deep_copy(normalized))
            self.measurement_completion_ratio_changed.emit(self.session.measurement_complete_ratio)
            for metric_key in PRIMARY_METRIC_KEYS:
                self.metric_value_changed.emit(metric_key, safe_float(normalized.get(metric_key), 0.0))
            self.session_changed.emit(self.session_snapshot())

        self._logger.info(
            "Measurements updated.",
            extra={
                "session_id": self.session.session_id,
                "mode": self.session.mode,
                "route": self.ui.current_route,
            },
        )

        return deep_copy(normalized)

    def clear_measurements(self) -> None:
        self.session.measurements = dict(EMPTY_MEASUREMENT_PAYLOAD)
        self.session.measurement_complete_ratio = 0.0
        self.measurements_changed.emit(deep_copy(self.session.measurements))
        self.measurement_completion_ratio_changed.emit(self.session.measurement_complete_ratio)
        self.session_changed.emit(self.session_snapshot())

    def set_measurement_progress(self, progress: Any) -> None:
        progress_value = safe_int(progress, default=0)
        progress_value = max(0, min(progress_value, 100))
        if progress_value == self.session.measurement_progress:
            return

        self.session.measurement_progress = progress_value
        self.measurement_progress_changed.emit(progress_value)
        self.session_changed.emit(self.session_snapshot())

    def set_measurement_step(self, message: str) -> None:
        message = safe_str(message, "").strip()
        if message == self.session.measurement_step_message:
            return
        self.session.measurement_step_message = message
        self.measurement_step_changed.emit(message)
        self.session_changed.emit(self.session_snapshot())

    def compute_measurement_completion_ratio(self, measurements: Optional[Mapping[str, Any]] = None) -> float:
        payload = measurements or self.session.measurements
        total = len(PRIMARY_METRIC_KEYS)
        if total <= 0:
            return 0.0

        complete = 0
        for metric_key in PRIMARY_METRIC_KEYS:
            if metric_is_meaningful(metric_key, payload.get(metric_key)):
                complete += 1

        return round((complete / total) * 100.0, 1)

    def is_measurement_complete(self) -> bool:
        for metric_key in PRIMARY_METRIC_KEYS:
            if not metric_is_meaningful(metric_key, self.session.measurements.get(metric_key)):
                return False
        return True

    # ========================================================
    # Diagnosis / report / QR state
    # ========================================================

    def current_diagnosis(self) -> Dict[str, Any]:
        return deep_copy(self.session.diagnosis)

    def set_diagnosis(self, diagnosis_payload: Mapping[str, Any]) -> None:
        merged = deep_merge_dicts(dict(EMPTY_DIAGNOSIS_PAYLOAD), dict(diagnosis_payload))
        self.session.diagnosis = merged

        self.diagnosis_changed.emit(deep_copy(merged))
        self.session_changed.emit(self.session_snapshot())

    def clear_diagnosis(self) -> None:
        self.session.diagnosis = dict(EMPTY_DIAGNOSIS_PAYLOAD)
        self.diagnosis_changed.emit(deep_copy(self.session.diagnosis))
        self.session_changed.emit(self.session_snapshot())

    def diagnosis_summary_text(self) -> str:
        diagnosis = self.session.diagnosis or {}
        summary = safe_str(diagnosis.get("summary"), "").strip()
        if summary:
            return summary

        status_title = safe_str(diagnosis.get("status_title"), "").strip()
        if status_title:
            return status_title

        return HEALTH_STATUS_NORMAL if not diagnosis.get("issues") else HEALTH_STATUS_NEEDS_ATTENTION

    def set_report_path(self, path: str) -> None:
        path = safe_str(path, "").strip()
        if path == self.session.report_path:
            return
        self.session.report_path = path
        self.report_path_changed.emit(path)
        self.session_changed.emit(self.session_snapshot())

    def set_qr_path(self, path: str) -> None:
        path = safe_str(path, "").strip()
        if path == self.session.qr_path:
            return
        self.session.qr_path = path
        self.qr_path_changed.emit(path)
        self.session_changed.emit(self.session_snapshot())

    # ========================================================
    # Storage / publish summaries
    # ========================================================

    def set_storage_summary(self, payload: Mapping[str, Any]) -> None:
        self._storage_summary = deep_copy(dict(payload))
        self.storage_summary_changed.emit(self.storage_summary_snapshot())

    def set_publish_summary(self, payload: Mapping[str, Any]) -> None:
        self._publish_summary = deep_copy(dict(payload))
        self.publish_summary_changed.emit(self.publish_summary_snapshot())

    # ========================================================
    # Calibration application
    # ========================================================

    def apply_calibration_to_measurements(
        self,
        measurements: Mapping[str, Any],
        *,
        recompute_bmi: bool = True,
    ) -> Dict[str, float]:
        """
        Apply configured sensor offsets to incoming measurements.

        Current strategy:
        - use simple offset-based adjustment
        - if BMI is derived, recompute after weight/height offset
        """
        from core.utils import calculate_bmi, safe_round  # local import avoids circular heaviness

        normalized = normalize_measurement_payload(measurements)

        # Apply simple offsets where configured
        for metric_key, metric_value in list(normalized.items()):
            metric_calibration = self._calibration.get(metric_key, {})
            if not isinstance(metric_calibration, Mapping):
                continue

            offset = safe_float(metric_calibration.get("offset"), 0.0)
            if offset == 0:
                continue

            normalized[metric_key] = safe_round(
                safe_float(metric_value) + offset,
                decimals=1 if metric_key not in {"spo2", "pulse_rate"} else 0,
                default=0.0,
            )

        if recompute_bmi:
            weight = safe_float(normalized.get("weight"), 0.0)
            height = safe_float(normalized.get("height"), 0.0)
            if weight > 0 and height > 0:
                normalized["bmi"] = calculate_bmi(weight, height, decimals=1)

        return normalize_measurement_payload(normalized)

    # ========================================================
    # Convenience composite flows
    # ========================================================

    def begin_measurement_flow(self, mode: Optional[str] = None, step_message: str = "Preparing sensors...") -> str:
        """
        Common entry for measuring screen start.
        """
        if mode:
            self.set_runtime_mode(mode, reset_session=False)

        session_id = self.create_new_session(mode=self.session.mode)
        self.mark_measurement_started(step_message=step_message)
        return session_id

    def complete_measurement_flow(
        self,
        measurements: Mapping[str, Any],
        diagnosis_payload: Optional[Mapping[str, Any]] = None,
        report_path: str = "",
        qr_path: str = "",
        *,
        apply_calibration: bool = False,
    ) -> Dict[str, Any]:
        """
        Common finalize entry after demo generation or hardware completion.
        """
        self.update_measurements(measurements, apply_calibration=apply_calibration, auto_fill_bmi=True, emit_signals=True)

        if diagnosis_payload:
            self.set_diagnosis(diagnosis_payload)

        if report_path:
            self.set_report_path(report_path)

        if qr_path:
            self.set_qr_path(qr_path)

        self.mark_session_complete(report_path=report_path, qr_path=qr_path)
        return self.session_snapshot()

    def cancel_measurement_flow(self) -> None:
        self.mark_measurement_cancelled()

    # ========================================================
    # Public reset helpers
    # ========================================================

    def reset_ui_only(self) -> None:
        self.ui.current_route = ROUTE_WELCOME
        self.ui.current_title = SCREEN_TITLES.get(ROUTE_WELCOME, "Welcome")
        self.ui.previous_route = ""
        self.ui.busy = False
        self.ui.status_message = ""
        self.ui.last_error_message = ""
        self.route_changed.emit(self.ui.current_route)
        self.title_changed.emit(self.ui.current_title)
        self.busy_changed.emit(self.ui.busy)
        self.ui_state_changed.emit(self.ui_snapshot())

    def reset_all_runtime_state(self) -> None:
        """
        Reset UI, connection, storage summary, publish summary, and active session.
        Persistent settings/calibration/thresholds remain loaded.
        """
        current_mode = self.session.mode

        self.ui = UIState(
            current_route=ROUTE_WELCOME,
            current_title=SCREEN_TITLES.get(ROUTE_WELCOME, "Welcome"),
            theme_mode=self.ui.theme_mode,
            fullscreen=self.ui.fullscreen,
            brightness_percent=self.ui.brightness_percent,
            volume_percent=self.ui.volume_percent,
            screen_timeout=self.ui.screen_timeout,
            admin_authenticated=False,
            admin_auth_status="",
            mode_selector_visible=self.ui.mode_selector_visible,
        )

        self.connection = ConnectionState(
            network_connected=False,
            serial_connected=False,
            esp32_connected=False,
            serial_port="",
            serial_baudrate=self.connection.serial_baudrate,
            raspberry_pi_detected=self.connection.raspberry_pi_detected,
            connection_label="Demo Mode Active" if current_mode == MODE_DEMO else "Disconnected",
            connection_detail="Using simulated measurements." if current_mode == MODE_DEMO else "No hardware connection detected.",
            demo_mode_active=(current_mode == MODE_DEMO),
        )

        self.session = MeasurementSessionState(
            mode=current_mode,
            status=SESSION_STATUS_IDLE,
            source_label="Demo" if current_mode == MODE_DEMO else "Hardware",
            measurements=dict(EMPTY_MEASUREMENT_PAYLOAD),
            diagnosis=dict(EMPTY_DIAGNOSIS_PAYLOAD),
        )

        self._storage_summary = {}
        self._publish_summary = {}

        self._logger.info("Full runtime state reset.", extra={"mode": current_mode})

        self.ui_state_changed.emit(self.ui_snapshot())
        self.connection_changed.emit(self.connection_snapshot())
        self.session_changed.emit(self.session_snapshot())
        self.storage_summary_changed.emit(self.storage_summary_snapshot())
        self.publish_summary_changed.emit(self.publish_summary_snapshot())
        self.state_reset.emit()

    # ========================================================
    # Validation / health helpers
    # ========================================================

    def has_active_session(self) -> bool:
        return bool(self.session.session_id)

    def is_session_complete(self) -> bool:
        return self.session.status == SESSION_STATUS_COMPLETE

    def is_session_measuring(self) -> bool:
        return self.session.status == SESSION_STATUS_MEASURING

    def is_session_idle(self) -> bool:
        return self.session.status == SESSION_STATUS_IDLE

    def has_report(self) -> bool:
        return bool(self.session.report_path)

    def has_qr(self) -> bool:
        return bool(self.session.qr_path)

    def has_diagnosis_issues(self) -> bool:
        issues = self.session.diagnosis.get("issues", [])
        return bool(issues)

    # ========================================================
    # Serializable exports for database/report/services
    # ========================================================

    def export_current_session_record(self) -> Dict[str, Any]:
        """
        Compact session record for saving in the database.
        """
        diagnosis = self.session.diagnosis or {}
        return {
            "session_id": self.session.session_id,
            "mode": self.session.mode,
            "status": self.session.status,
            "started_at": self.session.started_at,
            "measuring_started_at": self.session.measuring_started_at,
            "completed_at": self.session.completed_at,
            "cancelled_at": self.session.cancelled_at,
            "report_path": self.session.report_path,
            "qr_path": self.session.qr_path,
            "persisted": self.session.persisted,
            "measurement_progress": self.session.measurement_progress,
            "measurement_step_message": self.session.measurement_step_message,
            "measurement_complete_ratio": self.session.measurement_complete_ratio,
            "source_label": self.session.source_label,
            "weight": safe_float(self.session.measurements.get("weight"), 0.0),
            "height": safe_float(self.session.measurements.get("height"), 0.0),
            "bmi": safe_float(self.session.measurements.get("bmi"), 0.0),
            "temperature": safe_float(self.session.measurements.get("temperature"), 0.0),
            "spo2": safe_float(self.session.measurements.get("spo2"), 0.0),
            "pulse_rate": safe_float(self.session.measurements.get("pulse_rate"), 0.0),
            "respiratory_rate": safe_float(self.session.measurements.get("respiratory_rate"), 0.0),
            "diagnosis_summary": safe_str(diagnosis.get("summary"), ""),
            "status_title": safe_str(diagnosis.get("status_title"), ""),
            "overall_severity": safe_str(diagnosis.get("overall_severity"), ""),
        }

    # ========================================================
    # Debug helpers
    # ========================================================

    def debug_summary(self) -> Dict[str, Any]:
        return {
            "route": self.ui.current_route,
            "theme_mode": self.ui.theme_mode,
            "runtime_mode": self.session.mode,
            "session_id": self.session.session_id,
            "session_status": self.session.status,
            "measurement_complete_ratio": self.session.measurement_complete_ratio,
            "network_connected": self.connection.network_connected,
            "serial_connected": self.connection.serial_connected,
            "esp32_connected": self.connection.esp32_connected,
            "admin_authenticated": self.ui.admin_authenticated,
        }


# ============================================================
# Shared singleton accessor
# Useful for simpler composition in later files
# ============================================================

_APP_STATE_SINGLETON: Optional[AppState] = None


def get_app_state() -> AppState:
    global _APP_STATE_SINGLETON
    if _APP_STATE_SINGLETON is None:
        _APP_STATE_SINGLETON = AppState()
    return _APP_STATE_SINGLETON