"""
services/mode_service.py

Runtime mode management service for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the central backend for Demo Mode vs Hardware Mode
- It keeps the selected mode synchronized across:
    - AppState
    - SettingsService
    - later ConnectionService / SensorService / SessionService
- It ensures both modes use the same UI flow but different data behavior
- It exposes mode profiles for measuring duration, hardware requirement, and UI labels
- It provides safe switching helpers for mode-select screen and admin settings

Linked files:
- config.py
- core/app_state.py
- core/constants.py
- core/utils.py
- services/settings_service.py

Design goals:
- same screens and same functionality in both modes
- only the data source and readiness rules differ
- safe mode switching
- easy for later screens and services to call
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from config import (
    DEFAULT_RUNTIME_MODE,
    DEMO_MEASUREMENT_DURATION_MS,
    HARDWARE_MEASUREMENT_FAILSAFE_TIMEOUT_MS,
    SUPPORTED_RUNTIME_MODES,
)
from core.app_state import AppState, get_app_state
from core.constants import (
    MODE_DEMO,
    MODE_DESCRIPTIONS,
    MODE_HARDWARE,
    MODE_LABELS,
    SERIAL_CONNECTED,
    SERIAL_DISCONNECTED,
    SERIAL_WAITING,
)
from core.logger import get_logger, log_exception
try:
    from core.utils import deep_copy, safe_bool, safe_str
except Exception:  # pragma: no cover
    from copy import deepcopy as deep_copy

    def safe_bool(value, default=False):
        try:
            if isinstance(value, bool):
                return value
            if value is None:
                return default
            text = str(value).strip().lower()
            if text in {"1", "true", "yes", "y", "on"}:
                return True
            if text in {"0", "false", "no", "n", "off"}:
                return False
            return default
        except Exception:
            return default

    def safe_str(value, default=""):
        try:
            if value is None:
                return default
            return str(value)
        except Exception:
            return default
from core.utils import safe_int, safe_str, validate_runtime_mode
from services.settings_service import SettingsService, get_settings_service

logger = get_logger(__name__)


# ============================================================
# Dataclasses
# ============================================================

@dataclass(frozen=True)
class ModeProfile:
    """
    Static runtime mode profile used by screens and services.
    """
    key: str
    label: str
    description: str
    measurement_duration_ms: int
    wait_until_readings_complete: bool
    requires_hardware: bool
    requires_serial: bool
    allows_demo_values: bool
    badge_text: str
    connection_hint: str
    measuring_hint: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================
# Mode service
# ============================================================

class ModeService(QObject):
    """
    Central runtime mode manager.

    Responsibilities:
    - expose current mode
    - switch between demo and hardware mode
    - persist selected mode in settings
    - update AppState immediately
    - provide mode-specific measurement behavior hints
    - expose readiness information for measuring screen and mode-select screen
    """

    mode_loaded = pyqtSignal(str)
    mode_changed = pyqtSignal(str)
    mode_switch_requested = pyqtSignal(str)
    mode_switch_completed = pyqtSignal(str)
    mode_profiles_changed = pyqtSignal(dict)
    mode_readiness_changed = pyqtSignal(dict)
    mode_error = pyqtSignal(str)

    def __init__(
        self,
        app_state: Optional[AppState] = None,
        settings_service: Optional[SettingsService] = None,
        connection_service: Optional[object] = None,
    ) -> None:
        super().__init__()

        self._logger = logger.bind(component="ModeService")
        self._app_state: AppState = app_state or get_app_state()
        self._settings_service: SettingsService = settings_service or get_settings_service()
        self._connection_service: Optional[object] = connection_service

        self._profiles: Dict[str, ModeProfile] = self._build_profiles()
        self._current_mode: str = DEFAULT_RUNTIME_MODE

        self._load_from_app_state_or_settings()

    # ========================================================
    # Internal helpers
    # ========================================================

    def _build_profiles(self) -> Dict[str, ModeProfile]:
        """
        Build the two canonical runtime profiles.
        """
        demo_profile = ModeProfile(
            key=MODE_DEMO,
            label=MODE_LABELS.get(MODE_DEMO, "Demo Mode"),
            description=MODE_DESCRIPTIONS.get(
                MODE_DEMO,
                "Simulated measurements for presentation and testing.",
            ),
            measurement_duration_ms=DEMO_MEASUREMENT_DURATION_MS,
            wait_until_readings_complete=False,
            requires_hardware=False,
            requires_serial=False,
            allows_demo_values=True,
            badge_text="Demo Mode Active",
            connection_hint="No ESP32 required. Simulated values will be used.",
            measuring_hint="Measurement completes after the demo timer finishes.",
        )

        hardware_profile = ModeProfile(
            key=MODE_HARDWARE,
            label=MODE_LABELS.get(MODE_HARDWARE, "Hardware Mode"),
            description=MODE_DESCRIPTIONS.get(
                MODE_HARDWARE,
                "Live sensor measurements from connected hardware.",
            ),
            measurement_duration_ms=HARDWARE_MEASUREMENT_FAILSAFE_TIMEOUT_MS,
            wait_until_readings_complete=True,
            requires_hardware=True,
            requires_serial=True,
            allows_demo_values=False,
            badge_text="Hardware Mode",
            connection_hint="ESP32 / serial connection required for live readings.",
            measuring_hint="Measurement stays active until real readings are completed.",
        )

        return {
            MODE_DEMO: demo_profile,
            MODE_HARDWARE: hardware_profile,
        }

    def _load_from_app_state_or_settings(self) -> None:
        """
        Resolve the current mode from AppState first, then settings.
        """
        try:
            app_mode = safe_str(self._app_state.runtime_mode(), "").strip().lower()
        except Exception:
            app_mode = ""

        if app_mode not in SUPPORTED_RUNTIME_MODES:
            try:
                settings_payload = self._settings_service.snapshot()
                app_mode = safe_str(
                    settings_payload.get("system", {}).get("runtime_mode"),
                    DEFAULT_RUNTIME_MODE,
                ).strip().lower()
            except Exception:
                app_mode = DEFAULT_RUNTIME_MODE

        self._current_mode = validate_runtime_mode(app_mode, allowed=SUPPORTED_RUNTIME_MODES)
        self._sync_mode_to_app_state(self._current_mode, reset_session=False, update_connection_labels=True)
        self._logger.info("Mode service initialized with mode '%s'.", self._current_mode)

        self.mode_loaded.emit(self._current_mode)
        self.mode_profiles_changed.emit(self.available_profiles())
        self.mode_readiness_changed.emit(self.readiness_snapshot())

    def _bool(self, value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            cleaned = value.strip().lower()
            if cleaned in {"1", "true", "yes", "y", "on"}:
                return True
            if cleaned in {"0", "false", "no", "n", "off"}:
                return False
        return default

    def _sync_mode_to_app_state(
        self,
        mode: str,
        *,
        reset_session: bool,
        update_connection_labels: bool,
    ) -> None:
        """
        Update AppState in one consistent place.
        """
        self._app_state.set_runtime_mode(mode, reset_session=reset_session)

        if update_connection_labels:
            if mode == MODE_DEMO:
                self._app_state.update_connection_state(
                    demo_mode_active=True,
                    serial_connected=False,
                    esp32_connected=False,
                    connection_label="Demo Mode Active",
                    connection_detail="Using simulated measurements.",
                )
            else:
                # Preserve existing serial state where possible, but make the label hardware-focused
                conn = self._app_state.connection_snapshot()
                serial_connected = bool(conn.get("serial_connected", False))
                esp32_connected = bool(conn.get("esp32_connected", False))
                serial_port = safe_str(conn.get("serial_port"), "")

                if esp32_connected:
                    label = "Hardware Connected"
                    detail = "ESP32 is connected and sending data."
                elif serial_connected:
                    label = "Serial Connected"
                    detail = f"Serial port connected: {serial_port or 'available'}"
                else:
                    label = "Hardware Waiting"
                    detail = "Waiting for ESP32 / serial hardware connection."

                self._app_state.update_connection_state(
                    demo_mode_active=False,
                    connection_label=label,
                    connection_detail=detail,
                )

    def _persist_mode_to_settings(self, mode: str) -> None:
        """
        Save current mode to settings service.
        """
        self._settings_service.set_runtime_mode(mode)

    def _notify_connection_service_mode_changed(self, mode: str) -> None:
        """
        Best-effort callback into a later connection service without hard dependency.
        """
        if self._connection_service is None:
            return

        try:
            callback = getattr(self._connection_service, "on_mode_changed", None)
            if callable(callback):
                callback(mode)
                return
        except Exception as exc:
            self._logger.warning("Connection service on_mode_changed failed: %s", exc)

        try:
            callback = getattr(self._connection_service, "refresh_connection_state", None)
            if callable(callback):
                callback()
        except Exception as exc:
            self._logger.warning("Connection service refresh_connection_state failed: %s", exc)

    # ========================================================
    # Public service bindings
    # ========================================================

    def set_connection_service(self, connection_service: object) -> None:
        self._connection_service = connection_service
        self.mode_readiness_changed.emit(self.readiness_snapshot())

    # ========================================================
    # Public mode accessors
    # ========================================================

    def current_mode(self) -> str:
        return self._current_mode

    def get_mode(self) -> str:
        return self.current_mode()

    def is_demo_mode(self) -> bool:
        return self._current_mode == MODE_DEMO

    def is_hardware_mode(self) -> bool:
        return self._current_mode == MODE_HARDWARE

    def supported_modes(self) -> List[str]:
        return list(SUPPORTED_RUNTIME_MODES)

    def available_profiles(self) -> Dict[str, Dict[str, Any]]:
        return {key: profile.to_dict() for key, profile in self._profiles.items()}

    def get_profile(self, mode: Optional[str] = None) -> ModeProfile:
        normalized = validate_runtime_mode(mode or self._current_mode, allowed=SUPPORTED_RUNTIME_MODES)
        return self._profiles.get(normalized, self._profiles[MODE_DEMO])

    def get_active_profile(self) -> ModeProfile:
        return self.get_profile(self._current_mode)

    def label_for_mode(self, mode: Optional[str] = None) -> str:
        return self.get_profile(mode).label

    def description_for_mode(self, mode: Optional[str] = None) -> str:
        return self.get_profile(mode).description

    # ========================================================
    # Public switching helpers
    # ========================================================

    def switch_mode(
        self,
        mode: str,
        *,
        persist: bool = True,
        reset_session: bool = True,
        update_connection_labels: bool = True,
    ) -> str:
        """
        Main mode switch entry point.

        Behavior:
        - validates requested mode
        - optionally persists to settings
        - updates AppState
        - optionally resets the active session
        - notifies later services if attached
        """
        requested = validate_runtime_mode(mode, allowed=SUPPORTED_RUNTIME_MODES)
        self.mode_switch_requested.emit(requested)

        if requested == self._current_mode and not reset_session:
            self.mode_readiness_changed.emit(self.readiness_snapshot())
            return self._current_mode

        previous_mode = self._current_mode

        try:
            self._current_mode = requested

            if persist:
                self._persist_mode_to_settings(requested)

            self._sync_mode_to_app_state(
                requested,
                reset_session=reset_session,
                update_connection_labels=update_connection_labels,
            )

            self._notify_connection_service_mode_changed(requested)

            self._logger.info(
                "Runtime mode switched from '%s' to '%s'.",
                previous_mode,
                requested,
            )

            self.mode_changed.emit(requested)
            self.mode_switch_completed.emit(requested)
            self.mode_readiness_changed.emit(self.readiness_snapshot())
            return requested

        except Exception as exc:
            # Restore previous in-memory value if something goes wrong
            self._current_mode = previous_mode
            log_exception(self._logger, "Failed to switch runtime mode", exc)
            self.mode_error.emit(str(exc))
            raise

    def set_mode(
        self,
        mode: str,
        *,
        persist: bool = True,
        reset_session: bool = True,
    ) -> str:
        return self.switch_mode(
            mode,
            persist=persist,
            reset_session=reset_session,
            update_connection_labels=True,
        )

    def enable_demo_mode(self, *, persist: bool = True, reset_session: bool = True) -> str:
        return self.switch_mode(MODE_DEMO, persist=persist, reset_session=reset_session)

    def enable_hardware_mode(self, *, persist: bool = True, reset_session: bool = True) -> str:
        return self.switch_mode(MODE_HARDWARE, persist=persist, reset_session=reset_session)

    def sync_from_settings(self, reset_session: bool = False) -> str:
        """
        Pull the current mode from settings and apply it.
        """
        settings_payload = self._settings_service.snapshot()
        mode = safe_str(
            settings_payload.get("system", {}).get("runtime_mode"),
            DEFAULT_RUNTIME_MODE,
        ).strip().lower()
        return self.switch_mode(mode, persist=False, reset_session=reset_session)

    # ========================================================
    # Mode-specific behavior helpers
    # ========================================================

    def measurement_duration_ms(self, mode: Optional[str] = None) -> int:
        """
        Returns:
        - demo mode: fixed animation duration
        - hardware mode: failsafe timeout ceiling
        """
        profile = self.get_profile(mode)
        return safe_int(profile.measurement_duration_ms, DEMO_MEASUREMENT_DURATION_MS)

    def should_wait_until_complete(self, mode: Optional[str] = None) -> bool:
        """
        Demo mode:
            False -> measure for fixed duration, then continue
        Hardware mode:
            True -> wait for real readings to complete
        """
        return bool(self.get_profile(mode).wait_until_readings_complete)

    def requires_hardware(self, mode: Optional[str] = None) -> bool:
        return bool(self.get_profile(mode).requires_hardware)

    def requires_serial(self, mode: Optional[str] = None) -> bool:
        return bool(self.get_profile(mode).requires_serial)

    def allows_demo_values(self, mode: Optional[str] = None) -> bool:
        return bool(self.get_profile(mode).allows_demo_values)

    def mode_badge_payload(self, mode: Optional[str] = None) -> Dict[str, Any]:
        profile = self.get_profile(mode)
        return {
            "mode": profile.key,
            "label": profile.label,
            "badge_text": profile.badge_text,
            "description": profile.description,
        }

    # ========================================================
    # Readiness helpers for measuring screen / mode select screen
    # ========================================================

    def hardware_ready(self) -> bool:
        """
        Hardware readiness for live measurements.

        We use AppState connection flags so this works before ConnectionService is fully built.
        """
        conn = self._app_state.connection_snapshot()
        serial_connected = bool(conn.get("serial_connected", False))
        esp32_connected = bool(conn.get("esp32_connected", False))
        return serial_connected or esp32_connected

    def can_measure_now(self, mode: Optional[str] = None) -> bool:
        normalized = validate_runtime_mode(mode or self._current_mode, allowed=SUPPORTED_RUNTIME_MODES)

        if normalized == MODE_DEMO:
            return True

        return self.hardware_ready()

    def readiness_snapshot(self, mode: Optional[str] = None) -> Dict[str, Any]:
        normalized = validate_runtime_mode(mode or self._current_mode, allowed=SUPPORTED_RUNTIME_MODES)
        profile = self.get_profile(normalized)
        conn = self._app_state.connection_snapshot()

        serial_connected = bool(conn.get("serial_connected", False))
        esp32_connected = bool(conn.get("esp32_connected", False))
        network_connected = bool(conn.get("network_connected", False))

        if normalized == MODE_DEMO:
            ready = True
            readiness_reason = "Demo mode is always ready."
            connection_state = "demo_ready"
        else:
            ready = self.hardware_ready()
            if esp32_connected:
                readiness_reason = "ESP32 is connected."
                connection_state = "esp32_connected"
            elif serial_connected:
                readiness_reason = "Serial connection detected."
                connection_state = SERIAL_CONNECTED
            else:
                readiness_reason = "Waiting for serial / ESP32 connection."
                connection_state = SERIAL_WAITING

        snapshot = {
            "mode": normalized,
            "label": profile.label,
            "description": profile.description,
            "ready": ready,
            "requires_hardware": profile.requires_hardware,
            "requires_serial": profile.requires_serial,
            "allows_demo_values": profile.allows_demo_values,
            "measurement_duration_ms": profile.measurement_duration_ms,
            "wait_until_readings_complete": profile.wait_until_readings_complete,
            "connection_state": connection_state,
            "serial_connected": serial_connected,
            "esp32_connected": esp32_connected,
            "network_connected": network_connected,
            "badge_text": profile.badge_text,
            "connection_hint": profile.connection_hint,
            "measuring_hint": profile.measuring_hint,
            "readiness_reason": readiness_reason,
        }
        return snapshot

    def demo_readiness_payload(self) -> Dict[str, Any]:
        return self.readiness_snapshot(MODE_DEMO)

    def hardware_readiness_payload(self) -> Dict[str, Any]:
        return self.readiness_snapshot(MODE_HARDWARE)

    # ========================================================
    # UI / flow convenience helpers
    # ========================================================

    def measuring_status_text(self, mode: Optional[str] = None) -> str:
        profile = self.get_profile(mode)
        if profile.key == MODE_DEMO:
            return "Collecting demo data..."
        return "Collecting live sensor data..."

    def connection_badge_state(self, mode: Optional[str] = None) -> Dict[str, Any]:
        normalized = validate_runtime_mode(mode or self._current_mode, allowed=SUPPORTED_RUNTIME_MODES)

        if normalized == MODE_DEMO:
            return {
                "connected": True,
                "waiting": False,
                "label": "Demo Mode Active",
                "detail": "Using simulated measurements.",
            }

        conn = self._app_state.connection_snapshot()
        serial_connected = bool(conn.get("serial_connected", False))
        esp32_connected = bool(conn.get("esp32_connected", False))

        if esp32_connected:
            return {
                "connected": True,
                "waiting": False,
                "label": "Hardware Connected",
                "detail": "ESP32 is connected and sending data.",
            }

        if serial_connected:
            return {
                "connected": True,
                "waiting": False,
                "label": "Serial Connected",
                "detail": f"Serial port connected: {safe_str(conn.get('serial_port'), 'available')}",
            }

        return {
            "connected": False,
            "waiting": True,
            "label": "Hardware Waiting",
            "detail": "Waiting for ESP32 / serial hardware connection.",
        }

    # ========================================================
    # Diagnostics
    # ========================================================

    def diagnostics(self) -> Dict[str, Any]:
        active_profile = self.get_active_profile()
        return {
            "current_mode": self._current_mode,
            "active_profile": active_profile.to_dict(),
            "supported_modes": list(SUPPORTED_RUNTIME_MODES),
            "hardware_ready": self.hardware_ready(),
            "can_measure_now": self.can_measure_now(),
            "readiness": self.readiness_snapshot(),
        }


# ============================================================
# Singleton accessor
# ============================================================

_MODE_SERVICE_SINGLETON: Optional[ModeService] = None


def get_mode_service(
    app_state: Optional[AppState] = None,
    settings_service: Optional[SettingsService] = None,
    connection_service: Optional[object] = None,
) -> ModeService:
    global _MODE_SERVICE_SINGLETON
    if _MODE_SERVICE_SINGLETON is None:
        _MODE_SERVICE_SINGLETON = ModeService(
            app_state=app_state,
            settings_service=settings_service,
            connection_service=connection_service,
        )
    else:
        if connection_service is not None:
            _MODE_SERVICE_SINGLETON.set_connection_service(connection_service)
    return _MODE_SERVICE_SINGLETON