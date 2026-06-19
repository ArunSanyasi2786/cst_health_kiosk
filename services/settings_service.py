"""
services/settings_service.py

Persistent settings management service for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the main backend for the Settings screen
- It reads/writes the JSON settings file under data/config/settings.json
- It keeps AppState and on-disk settings synchronized
- It records settings audit entries through DatabaseService
- It provides safe validation and update helpers for all important settings
- It supports both demo mode and hardware mode with the same UI

Linked files:
- config.py
- core/app_state.py
- core/constants.py
- core/utils.py
- services/database_service.py

Design goals:
- central and explicit
- safe on first run
- easy for screens to call
- strongly validated
- preserves user settings while filling missing defaults
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from config import (
    DEFAULT_SETTINGS,
    SETTINGS_FILE,
    SUPPORTED_RUNTIME_MODES,
    SUPPORTED_SCREEN_TIMEOUTS,
    SUPPORTED_THEME_MODES,
    read_settings,
    write_settings,
)
from core.app_state import AppState, get_app_state
from core.constants import (
    MODE_DEMO,
    MODE_HARDWARE,
    SCREEN_TIMEOUT_10,
    SCREEN_TIMEOUT_15,
    SCREEN_TIMEOUT_ALWAYS,
    THEME_DARK,
    THEME_LIGHT,
)
from core.logger import get_settings_logger, log_exception
from core.utils import (
    deep_copy,
    deep_merge_dicts,
    read_json_file,
    safe_float,
    safe_int,
    safe_str,
    validate_brightness,
    validate_runtime_mode,
    validate_volume,
    write_json_file,
)
from services.database_service import DatabaseService, get_database_service

logger = get_settings_logger()


# ============================================================
# Dataclasses
# ============================================================

@dataclass
class SettingsValidationResult:
    """
    Validation result returned by normalize/validate helpers.
    """
    is_valid: bool
    normalized: Dict[str, Any]
    warnings: list[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "normalized": deep_copy(self.normalized),
            "warnings": list(self.warnings),
        }


# ============================================================
# Settings service
# ============================================================

class SettingsService(QObject):
    """
    Central settings manager for the kiosk.

    Main responsibilities:
    - load settings JSON
    - merge with defaults safely
    - validate and normalize user/admin changes
    - save settings JSON
    - update AppState immediately
    - save audit logs to the database

    Settings structure managed here:
    - app
    - display
    - audio
    - system
    - hardware
    - timing
    """

    settings_loaded = pyqtSignal(dict)
    settings_saved = pyqtSignal(dict)
    settings_changed = pyqtSignal(dict)
    setting_changed = pyqtSignal(str, object)
    settings_reset = pyqtSignal(dict)
    settings_error = pyqtSignal(str)

    display_settings_changed = pyqtSignal(dict)
    audio_settings_changed = pyqtSignal(dict)
    system_settings_changed = pyqtSignal(dict)
    hardware_settings_changed = pyqtSignal(dict)
    timing_settings_changed = pyqtSignal(dict)

    def __init__(
        self,
        app_state: Optional[AppState] = None,
        database_service: Optional[DatabaseService] = None,
    ) -> None:
        super().__init__()

        self._logger = logger.bind(component="SettingsService")
        self._app_state: AppState = app_state or get_app_state()
        self._database_service: DatabaseService = database_service or get_database_service()

        self._settings: Dict[str, Any] = {}
        self._load_into_memory()

    # ========================================================
    # Internal normalization helpers
    # ========================================================

    def _safe_bool(self, value: Any, default: bool = False) -> bool:
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

    def _normalize_theme_mode(self, value: Any) -> str:
        cleaned = safe_str(value, THEME_DARK).strip().lower()
        if cleaned not in SUPPORTED_THEME_MODES:
            return THEME_DARK
        return cleaned

    def _normalize_screen_timeout(self, value: Any) -> str:
        cleaned = safe_str(value, SCREEN_TIMEOUT_15).strip().lower()
        if cleaned not in SUPPORTED_SCREEN_TIMEOUTS:
            return SCREEN_TIMEOUT_15
        return cleaned

    def _normalize_runtime_mode(self, value: Any) -> str:
        cleaned = validate_runtime_mode(value, allowed=SUPPORTED_RUNTIME_MODES)
        return cleaned if cleaned in SUPPORTED_RUNTIME_MODES else MODE_DEMO

    def _normalize_language(self, value: Any) -> str:
        cleaned = safe_str(value, "English").strip()
        return cleaned or "English"

    def _normalize_serial_port(self, value: Any) -> str:
        return safe_str(value, "").strip()

    def _normalize_positive_int(self, value: Any, default: int, minimum: int = 0, maximum: int = 999999) -> int:
        numeric = safe_int(value, default=default)
        if numeric < minimum:
            numeric = minimum
        if numeric > maximum:
            numeric = maximum
        return numeric

    def _normalize_positive_float(self, value: Any, default: float, minimum: float = 0.0, maximum: float = 999999.0) -> float:
        numeric = safe_float(value, default=default)
        if numeric < minimum:
            numeric = minimum
        if numeric > maximum:
            numeric = maximum
        return numeric

    def _normalize_settings_payload(self, payload: Mapping[str, Any]) -> SettingsValidationResult:
        """
        Normalize any partial or full settings payload into the canonical structure.
        Missing keys are filled from DEFAULT_SETTINGS.
        """
        merged = deep_merge_dicts(DEFAULT_SETTINGS, dict(payload or {}))
        warnings: list[str] = []

        display = dict(merged.get("display", {}))
        audio = dict(merged.get("audio", {}))
        system = dict(merged.get("system", {}))
        hardware = dict(merged.get("hardware", {}))
        timing = dict(merged.get("timing", {}))
        app_section = dict(merged.get("app", {}))

        # app
        app_section["name"] = safe_str(app_section.get("name"), DEFAULT_SETTINGS["app"]["name"])
        app_section["version"] = safe_str(app_section.get("version"), DEFAULT_SETTINGS["app"]["version"])
        app_section["organization"] = safe_str(
            app_section.get("organization"),
            DEFAULT_SETTINGS["app"]["organization"],
        )
        app_section["group_credit"] = safe_str(
            app_section.get("group_credit"),
            DEFAULT_SETTINGS["app"]["group_credit"],
        )

        # display
        display["brightness_percent"] = validate_brightness(display.get("brightness_percent"))
        display["screen_timeout"] = self._normalize_screen_timeout(display.get("screen_timeout"))
        display["theme_mode"] = self._normalize_theme_mode(display.get("theme_mode"))
        display["language"] = self._normalize_language(display.get("language"))
        display["fullscreen"] = self._safe_bool(display.get("fullscreen"), default=True)

        fixed_resolution = display.get("fixed_resolution", DEFAULT_SETTINGS["display"]["fixed_resolution"])
        if not isinstance(fixed_resolution, list) or len(fixed_resolution) != 2:
            fixed_resolution = list(DEFAULT_SETTINGS["display"]["fixed_resolution"])
            warnings.append("display.fixed_resolution was invalid and reset to default.")
        else:
            fixed_resolution = [
                self._normalize_positive_int(fixed_resolution[0], default=1024, minimum=320, maximum=4096),
                self._normalize_positive_int(fixed_resolution[1], default=600, minimum=240, maximum=4096),
            ]
        display["fixed_resolution"] = fixed_resolution

        # audio
        audio["enabled"] = self._safe_bool(audio.get("enabled"), default=True)
        audio["volume_percent"] = validate_volume(audio.get("volume_percent"))

        # system
        system["runtime_mode"] = self._normalize_runtime_mode(system.get("runtime_mode"))
        system["network_connected"] = self._safe_bool(system.get("network_connected"), default=False)
        system["admin_lock"] = self._safe_bool(system.get("admin_lock"), default=False)
        system["data_export_enabled"] = self._safe_bool(system.get("data_export_enabled"), default=True)
        system["show_demo_mode_badge"] = self._safe_bool(system.get("show_demo_mode_badge"), default=True)
        system["auto_backup_enabled"] = self._safe_bool(system.get("auto_backup_enabled"), default=False)

        # hardware
        hardware["preferred_serial_port"] = self._normalize_serial_port(hardware.get("preferred_serial_port"))
        hardware["serial_baudrate"] = self._normalize_positive_int(
            hardware.get("serial_baudrate"),
            default=115200,
            minimum=1200,
            maximum=2000000,
        )
        hardware["serial_timeout_seconds"] = self._normalize_positive_float(
            hardware.get("serial_timeout_seconds"),
            default=1.0,
            minimum=0.1,
            maximum=120.0,
        )
        hardware["auto_reconnect_seconds"] = self._normalize_positive_float(
            hardware.get("auto_reconnect_seconds"),
            default=3.0,
            minimum=0.5,
            maximum=600.0,
        )
        hardware["hardware_measurement_failsafe_timeout_ms"] = self._normalize_positive_int(
            hardware.get("hardware_measurement_failsafe_timeout_ms"),
            default=45000,
            minimum=1000,
            maximum=300000,
        )

        # timing
        timing["welcome_screen_duration_ms"] = self._normalize_positive_int(
            timing.get("welcome_screen_duration_ms"),
            default=4000,
            minimum=1000,
            maximum=20000,
        )
        timing["demo_measurement_duration_ms"] = self._normalize_positive_int(
            timing.get("demo_measurement_duration_ms"),
            default=5500,
            minimum=1000,
            maximum=30000,
        )
        timing["transition_duration_ms"] = self._normalize_positive_int(
            timing.get("transition_duration_ms"),
            default=320,
            minimum=50,
            maximum=5000,
        )
        timing["button_click_animation_ms"] = self._normalize_positive_int(
            timing.get("button_click_animation_ms"),
            default=140,
            minimum=50,
            maximum=3000,
        )
        timing["logo_glow_pulse_ms"] = self._normalize_positive_int(
            timing.get("logo_glow_pulse_ms"),
            default=1500,
            minimum=100,
            maximum=10000,
        )
        timing["results_auto_refresh_ms"] = self._normalize_positive_int(
            timing.get("results_auto_refresh_ms"),
            default=1000,
            minimum=100,
            maximum=10000,
        )
        timing["publish_refresh_interval_ms"] = self._normalize_positive_int(
            timing.get("publish_refresh_interval_ms"),
            default=6000,
            minimum=1000,
            maximum=60000,
        )
        timing["connection_status_refresh_ms"] = self._normalize_positive_int(
            timing.get("connection_status_refresh_ms"),
            default=3000,
            minimum=250,
            maximum=30000,
        )

        normalized = {
            "app": app_section,
            "display": display,
            "audio": audio,
            "system": system,
            "hardware": hardware,
            "timing": timing,
        }

        return SettingsValidationResult(
            is_valid=True,
            normalized=normalized,
            warnings=warnings,
        )

    def _load_into_memory(self) -> None:
        """
        Load settings from disk, normalize them, and sync AppState.
        """
        raw = read_settings()
        validation = self._normalize_settings_payload(raw)
        self._settings = validation.normalized

        # If file was missing keys or malformed values, write back the normalized shape.
        try:
            write_settings(self._settings)
        except Exception as exc:
            log_exception(self._logger, "Failed to write normalized settings during load", exc)

        self._apply_to_app_state()
        self._logger.info("Settings loaded into memory.")
        self.settings_loaded.emit(self.snapshot())

    def _apply_to_app_state(self) -> None:
        """
        Push current in-memory settings into AppState so UI updates immediately.
        """
        try:
            self._app_state.update_settings(self._settings)

            display = self._settings.get("display", {})
            audio = self._settings.get("audio", {})
            system = self._settings.get("system", {})

            self._app_state.set_theme_mode(display.get("theme_mode", THEME_DARK))
            self._app_state.set_brightness_percent(display.get("brightness_percent", 75))
            self._app_state.set_screen_timeout(display.get("screen_timeout", SCREEN_TIMEOUT_15))
            self._app_state.set_volume_percent(audio.get("volume_percent", 55))
            self._app_state.set_fullscreen(bool(display.get("fullscreen", True)))
            self._app_state.set_runtime_mode(system.get("runtime_mode", MODE_DEMO), reset_session=False)
            self._app_state.update_connection_state(
                network_connected=bool(system.get("network_connected", False)),
                demo_mode_active=system.get("runtime_mode", MODE_DEMO) == MODE_DEMO,
            )
        except Exception as exc:
            log_exception(self._logger, "Failed to apply settings to AppState", exc)
            self.settings_error.emit(str(exc))

    def _audit_change(
        self,
        *,
        scope: str,
        key_path: str,
        before_payload: Mapping[str, Any],
        after_payload: Mapping[str, Any],
        note: str = "",
    ) -> None:
        """
        Save one audit entry in the DB.
        """
        try:
            self._database_service.save_settings_audit(
                actor="admin",
                scope=scope,
                key_path=key_path,
                before_payload=before_payload,
                after_payload=after_payload,
                note=note,
            )
        except Exception as exc:
            # Audit failure should not block the actual settings save
            log_exception(self._logger, "Failed to save settings audit", exc)

    def _emit_section_signals(self) -> None:
        self.display_settings_changed.emit(deep_copy(self._settings.get("display", {})))
        self.audio_settings_changed.emit(deep_copy(self._settings.get("audio", {})))
        self.system_settings_changed.emit(deep_copy(self._settings.get("system", {})))
        self.hardware_settings_changed.emit(deep_copy(self._settings.get("hardware", {})))
        self.timing_settings_changed.emit(deep_copy(self._settings.get("timing", {})))

    # ========================================================
    # Public read helpers
    # ========================================================

    def snapshot(self) -> Dict[str, Any]:
        return deep_copy(self._settings)

    def get_settings(self) -> Dict[str, Any]:
        return self.snapshot()

    def get_section(self, section: str) -> Dict[str, Any]:
        value = self._settings.get(section, {})
        return deep_copy(value if isinstance(value, dict) else {})

    def get_setting(self, section: str, key: str, default: Any = None) -> Any:
        section_data = self._settings.get(section, {})
        if not isinstance(section_data, dict):
            return default
        return section_data.get(key, default)

    def reload_from_disk(self) -> Dict[str, Any]:
        self._load_into_memory()
        return self.snapshot()

    # ========================================================
    # Public validation helpers
    # ========================================================

    def validate_payload(self, payload: Mapping[str, Any]) -> SettingsValidationResult:
        return self._normalize_settings_payload(payload)

    # ========================================================
    # Public write helpers
    # ========================================================

    def save_all(self, payload: Mapping[str, Any], note: str = "Bulk settings update") -> Dict[str, Any]:
        """
        Replace settings using a normalized merged payload.
        """
        before = self.snapshot()
        validation = self._normalize_settings_payload(payload)
        self._settings = validation.normalized

        try:
            write_settings(self._settings)
            self._apply_to_app_state()

            self._audit_change(
                scope="settings",
                key_path="*",
                before_payload=before,
                after_payload=self._settings,
                note=note,
            )

            self._logger.info("Settings saved via bulk update.")
            self.settings_saved.emit(self.snapshot())
            self.settings_changed.emit(self.snapshot())
            self._emit_section_signals()
            return self.snapshot()

        except Exception as exc:
            log_exception(self._logger, "Failed to save all settings", exc)
            self.settings_error.emit(str(exc))
            raise

    def update_settings(self, patch: Mapping[str, Any], note: str = "Settings patch update") -> Dict[str, Any]:
        """
        Merge a partial patch into existing settings, normalize, save, and sync.
        """
        before = self.snapshot()
        merged = deep_merge_dicts(self._settings, dict(patch or {}))
        validation = self._normalize_settings_payload(merged)
        self._settings = validation.normalized

        try:
            write_settings(self._settings)
            self._apply_to_app_state()

            self._audit_change(
                scope="settings",
                key_path="patch",
                before_payload=before,
                after_payload=self._settings,
                note=note,
            )

            self._logger.info("Settings updated via patch.")
            self.settings_saved.emit(self.snapshot())
            self.settings_changed.emit(self.snapshot())
            self._emit_section_signals()
            return self.snapshot()

        except Exception as exc:
            log_exception(self._logger, "Failed to update settings", exc)
            self.settings_error.emit(str(exc))
            raise

    def set_setting(
        self,
        section: str,
        key: str,
        value: Any,
        *,
        note: str = "",
    ) -> Dict[str, Any]:
        """
        Update one individual setting field.
        """
        if not section or not key:
            raise ValueError("section and key are required.")

        before = self.snapshot()

        section_data = self._settings.setdefault(section, {})
        if not isinstance(section_data, dict):
            section_data = {}
            self._settings[section] = section_data

        section_data[key] = value

        validation = self._normalize_settings_payload(self._settings)
        self._settings = validation.normalized

        try:
            write_settings(self._settings)
            self._apply_to_app_state()

            key_path = f"{section}.{key}"
            self._audit_change(
                scope=section,
                key_path=key_path,
                before_payload=before,
                after_payload=self._settings,
                note=note or f"Updated {key_path}",
            )

            self._logger.info("Setting updated: %s", key_path)
            self.setting_changed.emit(key_path, self.get_setting(section, key))
            self.settings_saved.emit(self.snapshot())
            self.settings_changed.emit(self.snapshot())
            self._emit_section_signals()
            return self.snapshot()

        except Exception as exc:
            log_exception(self._logger, f"Failed to update setting {section}.{key}", exc)
            self.settings_error.emit(str(exc))
            raise

    # ========================================================
    # Strongly typed convenience setters
    # These are what later screens will likely call directly.
    # ========================================================

    def set_theme_mode(self, theme_mode: str) -> Dict[str, Any]:
        normalized = self._normalize_theme_mode(theme_mode)
        return self.set_setting("display", "theme_mode", normalized, note="Theme mode updated")

    def set_brightness_percent(self, brightness_percent: Any) -> Dict[str, Any]:
        normalized = validate_brightness(brightness_percent)
        return self.set_setting("display", "brightness_percent", normalized, note="Brightness updated")

    def set_screen_timeout(self, timeout_key: str) -> Dict[str, Any]:
        normalized = self._normalize_screen_timeout(timeout_key)
        return self.set_setting("display", "screen_timeout", normalized, note="Screen timeout updated")

    def set_fullscreen(self, enabled: Any) -> Dict[str, Any]:
        normalized = self._safe_bool(enabled, default=True)
        return self.set_setting("display", "fullscreen", normalized, note="Fullscreen preference updated")

    def set_volume_percent(self, volume_percent: Any) -> Dict[str, Any]:
        normalized = validate_volume(volume_percent)
        return self.set_setting("audio", "volume_percent", normalized, note="Volume updated")

    def set_audio_enabled(self, enabled: Any) -> Dict[str, Any]:
        normalized = self._safe_bool(enabled, default=True)
        return self.set_setting("audio", "enabled", normalized, note="Audio enabled updated")

    def set_runtime_mode(self, runtime_mode: str) -> Dict[str, Any]:
        normalized = self._normalize_runtime_mode(runtime_mode)
        return self.set_setting("system", "runtime_mode", normalized, note="Runtime mode updated")

    def set_network_connected(self, connected: Any) -> Dict[str, Any]:
        normalized = self._safe_bool(connected, default=False)
        return self.set_setting("system", "network_connected", normalized, note="Network status updated")

    def set_admin_lock(self, enabled: Any) -> Dict[str, Any]:
        normalized = self._safe_bool(enabled, default=False)
        return self.set_setting("system", "admin_lock", normalized, note="Admin lock updated")

    def set_data_export_enabled(self, enabled: Any) -> Dict[str, Any]:
        normalized = self._safe_bool(enabled, default=True)
        return self.set_setting("system", "data_export_enabled", normalized, note="Data export setting updated")

    def set_show_demo_mode_badge(self, enabled: Any) -> Dict[str, Any]:
        normalized = self._safe_bool(enabled, default=True)
        return self.set_setting("system", "show_demo_mode_badge", normalized, note="Demo badge visibility updated")

    def set_auto_backup_enabled(self, enabled: Any) -> Dict[str, Any]:
        normalized = self._safe_bool(enabled, default=False)
        return self.set_setting("system", "auto_backup_enabled", normalized, note="Auto backup setting updated")

    def set_preferred_serial_port(self, port_name: str) -> Dict[str, Any]:
        normalized = self._normalize_serial_port(port_name)
        return self.set_setting("hardware", "preferred_serial_port", normalized, note="Preferred serial port updated")

    def set_serial_baudrate(self, baudrate: Any) -> Dict[str, Any]:
        normalized = self._normalize_positive_int(baudrate, default=115200, minimum=1200, maximum=2000000)
        return self.set_setting("hardware", "serial_baudrate", normalized, note="Serial baudrate updated")

    def set_serial_timeout_seconds(self, timeout_seconds: Any) -> Dict[str, Any]:
        normalized = self._normalize_positive_float(timeout_seconds, default=1.0, minimum=0.1, maximum=120.0)
        return self.set_setting("hardware", "serial_timeout_seconds", normalized, note="Serial timeout updated")

    def set_auto_reconnect_seconds(self, seconds: Any) -> Dict[str, Any]:
        normalized = self._normalize_positive_float(seconds, default=3.0, minimum=0.5, maximum=600.0)
        return self.set_setting("hardware", "auto_reconnect_seconds", normalized, note="Auto reconnect interval updated")

    def set_hardware_measurement_timeout_ms(self, timeout_ms: Any) -> Dict[str, Any]:
        normalized = self._normalize_positive_int(timeout_ms, default=45000, minimum=1000, maximum=300000)
        return self.set_setting(
            "hardware",
            "hardware_measurement_failsafe_timeout_ms",
            normalized,
            note="Hardware measurement failsafe timeout updated",
        )

    # ========================================================
    # Section-level convenience updates
    # ========================================================

    def update_display_settings(self, patch: Mapping[str, Any]) -> Dict[str, Any]:
        return self.update_settings({"display": dict(patch)}, note="Display settings updated")

    def update_audio_settings(self, patch: Mapping[str, Any]) -> Dict[str, Any]:
        return self.update_settings({"audio": dict(patch)}, note="Audio settings updated")

    def update_system_settings(self, patch: Mapping[str, Any]) -> Dict[str, Any]:
        return self.update_settings({"system": dict(patch)}, note="System settings updated")

    def update_hardware_settings(self, patch: Mapping[str, Any]) -> Dict[str, Any]:
        return self.update_settings({"hardware": dict(patch)}, note="Hardware settings updated")

    def update_timing_settings(self, patch: Mapping[str, Any]) -> Dict[str, Any]:
        return self.update_settings({"timing": dict(patch)}, note="Timing settings updated")

    # ========================================================
    # Reset helpers
    # ========================================================

    def reset_to_defaults(self, note: str = "Settings reset to defaults") -> Dict[str, Any]:
        before = self.snapshot()
        self._settings = deep_copy(DEFAULT_SETTINGS)

        try:
            write_settings(self._settings)
            self._apply_to_app_state()

            self._audit_change(
                scope="settings",
                key_path="*",
                before_payload=before,
                after_payload=self._settings,
                note=note,
            )

            self._logger.warning("Settings reset to defaults.")
            snapshot = self.snapshot()
            self.settings_reset.emit(snapshot)
            self.settings_saved.emit(snapshot)
            self.settings_changed.emit(snapshot)
            self._emit_section_signals()
            return snapshot

        except Exception as exc:
            log_exception(self._logger, "Failed to reset settings to defaults", exc)
            self.settings_error.emit(str(exc))
            raise

    # ========================================================
    # File-level helpers
    # ========================================================

    def settings_file_exists(self) -> bool:
        return SETTINGS_FILE.exists()

    def settings_file_path(self) -> str:
        return str(SETTINGS_FILE)

    def export_settings_payload(self) -> Dict[str, Any]:
        """
        Returns a deep copy of the current normalized settings.
        Useful for export/backups.
        """
        return self.snapshot()

    def save_snapshot_to_path(self, target_path: str) -> str:
        """
        Save current settings JSON to a custom path, useful for exports/backups.
        """
        try:
            write_json_file(target_path, self._settings)
            self._logger.info("Settings snapshot exported to %s", target_path)
            return str(target_path)
        except Exception as exc:
            log_exception(self._logger, "Failed to export settings snapshot", exc)
            self.settings_error.emit(str(exc))
            raise

    # ========================================================
    # Diagnostics
    # ========================================================

    def diagnostics(self) -> Dict[str, Any]:
        display = self._settings.get("display", {})
        audio = self._settings.get("audio", {})
        system = self._settings.get("system", {})
        hardware = self._settings.get("hardware", {})

        return {
            "settings_file": str(SETTINGS_FILE),
            "settings_file_exists": SETTINGS_FILE.exists(),
            "theme_mode": display.get("theme_mode", THEME_DARK),
            "brightness_percent": display.get("brightness_percent", 75),
            "screen_timeout": display.get("screen_timeout", SCREEN_TIMEOUT_15),
            "volume_percent": audio.get("volume_percent", 55),
            "audio_enabled": audio.get("enabled", True),
            "runtime_mode": system.get("runtime_mode", MODE_DEMO),
            "network_connected": system.get("network_connected", False),
            "admin_lock": system.get("admin_lock", False),
            "preferred_serial_port": hardware.get("preferred_serial_port", ""),
            "serial_baudrate": hardware.get("serial_baudrate", 115200),
        }


# ============================================================
# Singleton accessor
# ============================================================

_SETTINGS_SERVICE_SINGLETON: Optional[SettingsService] = None


def get_settings_service(
    app_state: Optional[AppState] = None,
    database_service: Optional[DatabaseService] = None,
) -> SettingsService:
    global _SETTINGS_SERVICE_SINGLETON
    if _SETTINGS_SERVICE_SINGLETON is None:
        _SETTINGS_SERVICE_SINGLETON = SettingsService(
            app_state=app_state,
            database_service=database_service,
        )
    return _SETTINGS_SERVICE_SINGLETON