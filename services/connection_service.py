"""
services/connection_service.py

Connection management service for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the main backend for connection awareness in both demo mode and hardware mode
- It manages and synchronizes:
    - network reachability
    - serial port discovery
    - selected/preferred serial port
    - serial connection state
    - ESP32 heartbeat / live-device presence
    - Raspberry Pi environment hint
- It keeps AppState connection flags updated for the UI
- It supports later integration with:
    - serial_service.py
    - sensor_service.py
    - settings screen
    - mode select screen
    - measuring screen
    - admin panel / publish / storage diagnostics

Linked files:
- config.py
- core/app_state.py
- core/utils.py
- services/settings_service.py
- services/mode_service.py
- services/serial_service.py (later optional integration)

Design goals:
- safe even if pyserial or hardware is unavailable
- useful in both laptop demo mode and Raspberry Pi deployment
- low-coupling: can work with or without later SerialService
- strong AppState synchronization
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from config import DEFAULT_RUNTIME_MODE
from core.app_state import AppState, get_app_state
from core.constants import MODE_DEMO, MODE_HARDWARE
from core.logger import get_logger, log_exception
from core.utils import (
    deep_copy,
    is_online,
    now_iso,
    parse_datetime,
    safe_float,
    safe_int,
    safe_str,
    validate_runtime_mode,
)
from services.mode_service import ModeService, get_mode_service
from services.settings_service import SettingsService, get_settings_service

logger = get_logger(__name__)

try:
    from serial.tools import list_ports as serial_list_ports  # type: ignore
    _PYSERIAL_AVAILABLE = True
except Exception:
    serial_list_ports = None
    _PYSERIAL_AVAILABLE = False


# ============================================================
# Dataclasses
# ============================================================

@dataclass
class SerialPortInfo:
    """
    Simplified serial port representation for the UI and connection logic.
    """
    device: str
    description: str
    manufacturer: str = ""
    hwid: str = ""
    vid: str = ""
    pid: str = ""
    serial_number: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ConnectionSnapshot:
    """
    Service-level connection summary.
    """
    mode: str
    network_connected: bool
    raspberry_pi_detected: bool
    serial_available: bool
    serial_connected: bool
    esp32_connected: bool
    selected_port: str
    preferred_port: str
    available_ports: List[Dict[str, Any]]
    baudrate: int
    last_heartbeat_at: str
    last_refresh_at: str
    connection_label: str
    connection_detail: str
    demo_mode_active: bool
    auto_refresh_enabled: bool
    refresh_interval_ms: int
    last_error: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "network_connected": self.network_connected,
            "raspberry_pi_detected": self.raspberry_pi_detected,
            "serial_available": self.serial_available,
            "serial_connected": self.serial_connected,
            "esp32_connected": self.esp32_connected,
            "selected_port": self.selected_port,
            "preferred_port": self.preferred_port,
            "available_ports": deep_copy(self.available_ports),
            "baudrate": self.baudrate,
            "last_heartbeat_at": self.last_heartbeat_at,
            "last_refresh_at": self.last_refresh_at,
            "connection_label": self.connection_label,
            "connection_detail": self.connection_detail,
            "demo_mode_active": self.demo_mode_active,
            "auto_refresh_enabled": self.auto_refresh_enabled,
            "refresh_interval_ms": self.refresh_interval_ms,
            "last_error": self.last_error,
        }


# ============================================================
# Connection service
# ============================================================

class ConnectionService(QObject):
    """
    Central connection manager.

    Main responsibilities:
    - monitor network reachability
    - scan serial ports
    - expose hardware readiness details
    - keep AppState connection state synchronized
    - provide optional adapters for later SerialService integration
    """

    connection_refreshed = pyqtSignal(dict)
    connection_changed = pyqtSignal(dict)

    network_status_changed = pyqtSignal(bool)
    serial_ports_updated = pyqtSignal(list)
    serial_status_changed = pyqtSignal(bool, str)
    esp32_status_changed = pyqtSignal(bool)
    raspberry_pi_detected_changed = pyqtSignal(bool)

    serial_connect_requested = pyqtSignal(str, int)
    serial_disconnect_requested = pyqtSignal()

    auto_refresh_started = pyqtSignal(int)
    auto_refresh_stopped = pyqtSignal()

    mode_policy_applied = pyqtSignal(dict)
    connection_error = pyqtSignal(str)

    def __init__(
        self,
        app_state: Optional[AppState] = None,
        settings_service: Optional[SettingsService] = None,
        mode_service: Optional[ModeService] = None,
        serial_service: Optional[object] = None,
    ) -> None:
        super().__init__()

        self._logger = logger.bind(component="ConnectionService")

        self._app_state: AppState = app_state or get_app_state()
        self._settings_service: SettingsService = settings_service or get_settings_service()
        self._mode_service: ModeService = mode_service or get_mode_service()
        self._serial_service: Optional[object] = serial_service

        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.setSingleShot(False)
        self._auto_refresh_timer.timeout.connect(self.refresh_connection_state)

        self._refresh_interval_ms: int = 3000
        self._available_ports: List[SerialPortInfo] = []
        self._selected_port: str = ""
        self._preferred_port: str = ""
        self._network_connected: bool = False
        self._serial_connected: bool = False
        self._esp32_connected: bool = False
        self._raspberry_pi_detected: bool = False
        self._last_heartbeat_at: str = ""
        self._last_refresh_at: str = ""
        self._last_error: str = ""
        self._heartbeat_timeout_seconds: float = 8.0
        self._connection_label: str = "Disconnected"
        self._connection_detail: str = "No hardware connection detected."

        self._load_initial_preferences()
        self._refresh_environment_flags()
        self.refresh_connection_state()

    # ========================================================
    # Internal helpers
    # ========================================================

    def _load_initial_preferences(self) -> None:
        """
        Resolve preferred serial config from settings.
        """
        try:
            hardware = self._settings_service.get_section("hardware")
            self._preferred_port = safe_str(hardware.get("preferred_serial_port"), "").strip()
            self._selected_port = self._preferred_port
            self._refresh_interval_ms = max(
                500,
                safe_int(
                    self._settings_service.get_setting("timing", "connection_status_refresh_ms", 3000),
                    3000,
                ),
            )
            self._heartbeat_timeout_seconds = max(
                2.0,
                safe_float(hardware.get("auto_reconnect_seconds"), 3.0) * 2.0,
            )
        except Exception as exc:
            self._logger.warning("Could not load connection preferences from settings: %s", exc)
            self._preferred_port = ""
            self._selected_port = ""
            self._refresh_interval_ms = 3000
            self._heartbeat_timeout_seconds = 8.0

    def _refresh_environment_flags(self) -> None:
        self._raspberry_pi_detected = self._detect_raspberry_pi()
        self._app_state.set_raspberry_pi_detected(self._raspberry_pi_detected)

    def _detect_raspberry_pi(self) -> bool:
        """
        Best-effort Raspberry Pi environment detection.
        """
        try:
            model_file = Path("/proc/device-tree/model")
            if model_file.exists():
                text = model_file.read_text(encoding="utf-8", errors="ignore").lower()
                if "raspberry pi" in text:
                    return True
        except Exception:
            pass

        try:
            uname = platform.uname()
            combined = " ".join(
                [
                    safe_str(uname.system, ""),
                    safe_str(uname.node, ""),
                    safe_str(uname.release, ""),
                    safe_str(uname.version, ""),
                    safe_str(uname.machine, ""),
                ]
            ).lower()
            if "raspberry" in combined or "armv7" in combined or "aarch64" in combined:
                # this is only a hint, but good enough for kiosk diagnostics
                return True
        except Exception:
            pass

        try:
            if os.name != "nt" and Path("/boot").exists() and Path("/sys/firmware").exists():
                # weak Linux SBC hint
                return False
        except Exception:
            pass

        return False

    def _mode(self) -> str:
        return validate_runtime_mode(self._mode_service.current_mode() or self._app_state.runtime_mode())

    def _call_attr(self, obj: object, attr_names: List[str], *args: Any, **kwargs: Any) -> Any:
        """
        Try a sequence of method/property names on an optional dependency.
        """
        if obj is None:
            return None

        for attr_name in attr_names:
            try:
                target = getattr(obj, attr_name, None)
                if callable(target):
                    return target(*args, **kwargs)
                if target is not None and not args and not kwargs:
                    return target
            except Exception as exc:
                self._logger.debug("Optional adapter call failed for %s: %s", attr_name, exc)
                continue
        return None

    def _coerce_serial_ports(self, raw_ports: Any) -> List[SerialPortInfo]:
        ports: List[SerialPortInfo] = []

        if raw_ports is None:
            return ports

        # Case 1: list of dict-like items
        if isinstance(raw_ports, list):
            for item in raw_ports:
                if isinstance(item, Mapping):
                    ports.append(
                        SerialPortInfo(
                            device=safe_str(item.get("device") or item.get("port") or item.get("name"), ""),
                            description=safe_str(item.get("description"), ""),
                            manufacturer=safe_str(item.get("manufacturer"), ""),
                            hwid=safe_str(item.get("hwid"), ""),
                            vid=safe_str(item.get("vid"), ""),
                            pid=safe_str(item.get("pid"), ""),
                            serial_number=safe_str(item.get("serial_number"), ""),
                        )
                    )
                else:
                    # pyserial ListPortInfo-like object
                    device = safe_str(getattr(item, "device", ""), "")
                    if device:
                        ports.append(
                            SerialPortInfo(
                                device=device,
                                description=safe_str(getattr(item, "description", ""), ""),
                                manufacturer=safe_str(getattr(item, "manufacturer", ""), ""),
                                hwid=safe_str(getattr(item, "hwid", ""), ""),
                                vid=safe_str(getattr(item, "vid", ""), ""),
                                pid=safe_str(getattr(item, "pid", ""), ""),
                                serial_number=safe_str(getattr(item, "serial_number", ""), ""),
                            )
                        )
        return ports

    def _scan_ports_direct(self) -> List[SerialPortInfo]:
        """
        Direct serial port scan fallback using pyserial if available.
        """
        if not _PYSERIAL_AVAILABLE or serial_list_ports is None:
            return []

        try:
            raw = list(serial_list_ports.comports())
            return self._coerce_serial_ports(raw)
        except Exception as exc:
            self._last_error = str(exc)
            self._logger.warning("Direct serial port scan failed: %s", exc)
            return []

    def _scan_ports_via_serial_service(self) -> List[SerialPortInfo]:
        """
        Ask later SerialService first if present.
        """
        raw = self._call_attr(
            self._serial_service,
            ["scan_ports", "list_ports", "available_ports", "get_available_ports"],
        )
        return self._coerce_serial_ports(raw)

    def _scan_ports(self) -> List[SerialPortInfo]:
        ports = self._scan_ports_via_serial_service()
        if ports:
            return ports
        return self._scan_ports_direct()

    def _resolve_selected_port(self, ports: List[SerialPortInfo]) -> str:
        """
        Choose a selected port using:
        1. active serial service port if connected
        2. user-selected port
        3. preferred port in settings
        4. first available port
        """
        active_port = safe_str(
            self._call_attr(
                self._serial_service,
                ["current_port_name", "port_name", "connected_port", "selected_port"],
            ),
            "",
        ).strip()
        if active_port:
            return active_port

        if self._selected_port and any(p.device == self._selected_port for p in ports):
            return self._selected_port

        if self._preferred_port and any(p.device == self._preferred_port for p in ports):
            return self._preferred_port

        if ports:
            return ports[0].device

        return ""

    def _query_network_state(self) -> bool:
        try:
            return bool(is_online())
        except Exception as exc:
            self._logger.debug("Network check failed: %s", exc)
            return False

    def _query_serial_connected(self) -> bool:
        value = self._call_attr(
            self._serial_service,
            ["is_connected", "serial_connected", "connected"],
        )
        if value is None:
            # if no serial service exists, infer from selected available port only for discovery, not real connection
            return False
        return bool(value)

    def _query_serial_baudrate(self) -> int:
        value = self._call_attr(
            self._serial_service,
            ["current_baudrate", "baudrate", "baud_rate"],
        )
        if value is None:
            value = self._settings_service.get_setting("hardware", "serial_baudrate", 115200)
        return max(1200, safe_int(value, 115200))

    def _query_last_heartbeat(self) -> str:
        value = self._call_attr(
            self._serial_service,
            ["last_heartbeat_at", "heartbeat_timestamp", "get_last_heartbeat_at"],
        )
        if value:
            return safe_str(value, "").strip()
        return self._last_heartbeat_at

    def _heartbeat_is_stale(self, heartbeat_at: str) -> bool:
        dt = parse_datetime(heartbeat_at)
        if dt is None:
            return True

        try:
            now_dt = parse_datetime(now_iso())
            if now_dt is None:
                return True
            delta_seconds = abs((now_dt - dt).total_seconds())
            return delta_seconds > self._heartbeat_timeout_seconds
        except Exception:
            return True

    def _query_esp32_connected(self, serial_connected: bool, heartbeat_at: str) -> bool:
        explicit = self._call_attr(
            self._serial_service,
            ["is_esp32_connected", "esp32_connected", "hardware_ready"],
        )
        if explicit is not None:
            return bool(explicit)

        if not serial_connected:
            return False

        if not heartbeat_at:
            return False

        return not self._heartbeat_is_stale(heartbeat_at)

    def _query_serial_last_error(self) -> str:
        value = self._call_attr(
            self._serial_service,
            ["last_error", "get_last_error", "error_message"],
        )
        return safe_str(value, self._last_error).strip()

    def _build_connection_label_and_detail(
        self,
        *,
        mode: str,
        network_connected: bool,
        serial_connected: bool,
        esp32_connected: bool,
        selected_port: str,
        available_ports_count: int,
    ) -> tuple[str, str]:
        """
        Human-friendly connection status text.
        """
        if mode == MODE_DEMO:
            return (
                "Demo Mode Active",
                "Using simulated measurements. Hardware connection is optional.",
            )

        if esp32_connected:
            detail = "ESP32 is connected and sending data."
            if selected_port:
                detail += f" Port: {selected_port}"
            return ("Hardware Connected", detail)

        if serial_connected:
            detail = "Serial link is connected, waiting for reliable device heartbeat."
            if selected_port:
                detail += f" Port: {selected_port}"
            return ("Serial Connected", detail)

        if available_ports_count > 0:
            detail = f"{available_ports_count} serial port(s) detected."
            if selected_port:
                detail += f" Selected: {selected_port}"
            if not network_connected:
                detail += " Network is currently offline."
            return ("Hardware Waiting", detail)

        return (
            "Disconnected",
            "No serial hardware connection detected.",
        )

    def _emit_change_signals(
        self,
        *,
        previous_snapshot: Optional[Dict[str, Any]],
        new_snapshot: Dict[str, Any],
    ) -> None:
        self.connection_refreshed.emit(deep_copy(new_snapshot))

        if previous_snapshot != new_snapshot:
            self.connection_changed.emit(deep_copy(new_snapshot))

        prev_network = bool((previous_snapshot or {}).get("network_connected", False))
        new_network = bool(new_snapshot.get("network_connected", False))
        if prev_network != new_network:
            self.network_status_changed.emit(new_network)

        prev_serial = bool((previous_snapshot or {}).get("serial_connected", False))
        new_serial = bool(new_snapshot.get("serial_connected", False))
        prev_port = safe_str((previous_snapshot or {}).get("selected_port"), "")
        new_port = safe_str(new_snapshot.get("selected_port"), "")
        if prev_serial != new_serial or prev_port != new_port:
            self.serial_status_changed.emit(new_serial, new_port)

        prev_esp32 = bool((previous_snapshot or {}).get("esp32_connected", False))
        new_esp32 = bool(new_snapshot.get("esp32_connected", False))
        if prev_esp32 != new_esp32:
            self.esp32_status_changed.emit(new_esp32)

        prev_pi = bool((previous_snapshot or {}).get("raspberry_pi_detected", False))
        new_pi = bool(new_snapshot.get("raspberry_pi_detected", False))
        if prev_pi != new_pi:
            self.raspberry_pi_detected_changed.emit(new_pi)

        prev_ports = previous_snapshot.get("available_ports", []) if previous_snapshot else []
        new_ports = new_snapshot.get("available_ports", [])
        if prev_ports != new_ports:
            self.serial_ports_updated.emit(deep_copy(new_ports))

    def _push_snapshot_to_app_state(self, snapshot: Dict[str, Any]) -> None:
        """
        Keep AppState connection flags synchronized for UI consumption.
        """
        try:
            self._app_state.update_connection_state(
                network_connected=bool(snapshot.get("network_connected", False)),
                serial_connected=bool(snapshot.get("serial_connected", False)),
                serial_port=safe_str(snapshot.get("selected_port"), ""),
                serial_baudrate=safe_int(snapshot.get("baudrate"), 115200),
                esp32_connected=bool(snapshot.get("esp32_connected", False)),
                raspberry_pi_detected=bool(snapshot.get("raspberry_pi_detected", False)),
                connection_label=safe_str(snapshot.get("connection_label"), ""),
                connection_detail=safe_str(snapshot.get("connection_detail"), ""),
                last_heartbeat_at=safe_str(snapshot.get("last_heartbeat_at"), ""),
                last_error=safe_str(snapshot.get("last_error"), ""),
                demo_mode_active=bool(snapshot.get("demo_mode_active", False)),
            )
        except Exception as exc:
            self._logger.warning("Failed to synchronize connection snapshot into AppState: %s", exc)

    # ========================================================
    # Public refresh / monitoring
    # ========================================================

    def refresh_connection_state(self) -> Dict[str, Any]:
        """
        Main connection refresh entry point.
        """
        previous_snapshot = getattr(self, "_last_snapshot", None)

        try:
            mode = self._mode()
            self._refresh_environment_flags()

            self._available_ports = self._scan_ports()
            self._selected_port = self._resolve_selected_port(self._available_ports)

            self._network_connected = self._query_network_state()
            self._serial_connected = self._query_serial_connected()
            self._last_heartbeat_at = self._query_last_heartbeat()
            self._esp32_connected = self._query_esp32_connected(
                self._serial_connected,
                self._last_heartbeat_at,
            )
            self._last_error = self._query_serial_last_error()
            self._last_refresh_at = now_iso()

            if mode == MODE_DEMO:
                # Demo mode should never falsely look like a hardware error.
                self._esp32_connected = False
                self._serial_connected = False
                self._last_error = ""

            self._connection_label, self._connection_detail = self._build_connection_label_and_detail(
                mode=mode,
                network_connected=self._network_connected,
                serial_connected=self._serial_connected,
                esp32_connected=self._esp32_connected,
                selected_port=self._selected_port,
                available_ports_count=len(self._available_ports),
            )

            snapshot = ConnectionSnapshot(
                mode=mode,
                network_connected=self._network_connected,
                raspberry_pi_detected=self._raspberry_pi_detected,
                serial_available=len(self._available_ports) > 0,
                serial_connected=self._serial_connected,
                esp32_connected=self._esp32_connected,
                selected_port=self._selected_port,
                preferred_port=self._preferred_port,
                available_ports=[p.to_dict() for p in self._available_ports],
                baudrate=self._query_serial_baudrate(),
                last_heartbeat_at=self._last_heartbeat_at,
                last_refresh_at=self._last_refresh_at,
                connection_label=self._connection_label,
                connection_detail=self._connection_detail,
                demo_mode_active=(mode == MODE_DEMO),
                auto_refresh_enabled=self._auto_refresh_timer.isActive(),
                refresh_interval_ms=self._refresh_interval_ms,
                last_error=self._last_error,
            ).to_dict()

            self._last_snapshot = deep_copy(snapshot)
            self._push_snapshot_to_app_state(snapshot)
            self._emit_change_signals(previous_snapshot=previous_snapshot, new_snapshot=snapshot)
            return snapshot

        except Exception as exc:
            log_exception(self._logger, "Failed to refresh connection state", exc)
            self.connection_error.emit(str(exc))
            fallback = {
                "mode": self._mode(),
                "network_connected": False,
                "raspberry_pi_detected": self._raspberry_pi_detected,
                "serial_available": False,
                "serial_connected": False,
                "esp32_connected": False,
                "selected_port": self._selected_port,
                "preferred_port": self._preferred_port,
                "available_ports": [],
                "baudrate": 115200,
                "last_heartbeat_at": self._last_heartbeat_at,
                "last_refresh_at": now_iso(),
                "connection_label": "Connection Error",
                "connection_detail": str(exc),
                "demo_mode_active": self._mode() == MODE_DEMO,
                "auto_refresh_enabled": self._auto_refresh_timer.isActive(),
                "refresh_interval_ms": self._refresh_interval_ms,
                "last_error": str(exc),
            }
            self._push_snapshot_to_app_state(fallback)
            return fallback

    def start_auto_refresh(self, interval_ms: Optional[int] = None) -> None:
        """
        Start periodic connection refresh.
        """
        if interval_ms is not None:
            self._refresh_interval_ms = max(500, safe_int(interval_ms, self._refresh_interval_ms))

        self._auto_refresh_timer.start(self._refresh_interval_ms)
        self.auto_refresh_started.emit(self._refresh_interval_ms)
        self.refresh_connection_state()

    def stop_auto_refresh(self) -> None:
        if self._auto_refresh_timer.isActive():
            self._auto_refresh_timer.stop()
            self.auto_refresh_stopped.emit()

    def is_auto_refresh_active(self) -> bool:
        return self._auto_refresh_timer.isActive()

    def set_refresh_interval_ms(self, interval_ms: int) -> int:
        self._refresh_interval_ms = max(500, safe_int(interval_ms, 3000))
        if self._auto_refresh_timer.isActive():
            self._auto_refresh_timer.start(self._refresh_interval_ms)
        return self._refresh_interval_ms

    # ========================================================
    # Serial port discovery / preference
    # ========================================================

    def scan_serial_ports(self) -> List[Dict[str, Any]]:
        self._available_ports = self._scan_ports()
        self._selected_port = self._resolve_selected_port(self._available_ports)
        ports = [p.to_dict() for p in self._available_ports]
        self.serial_ports_updated.emit(deep_copy(ports))
        self.refresh_connection_state()
        return ports

    def available_serial_ports(self) -> List[Dict[str, Any]]:
        return [p.to_dict() for p in self._available_ports]

    def selected_port(self) -> str:
        return self._selected_port

    def preferred_port(self) -> str:
        return self._preferred_port

    def set_selected_port(self, port_name: str, *, persist_as_preferred: bool = False) -> str:
        port_name = safe_str(port_name, "").strip()
        self._selected_port = port_name

        if persist_as_preferred:
            self.set_preferred_port(port_name)

        self.refresh_connection_state()
        return self._selected_port

    def set_preferred_port(self, port_name: str) -> str:
        port_name = safe_str(port_name, "").strip()
        self._preferred_port = port_name
        try:
            self._settings_service.set_preferred_serial_port(port_name)
        except Exception as exc:
            self._logger.warning("Failed to persist preferred serial port: %s", exc)
        self.refresh_connection_state()
        return self._preferred_port

    def clear_preferred_port(self) -> str:
        return self.set_preferred_port("")

    # ========================================================
    # Serial connect / disconnect delegation
    # ========================================================

    def connect_to_port(self, port_name: str, baudrate: Optional[int] = None) -> bool:
        """
        Request serial connection through later SerialService if available.
        """
        port_name = safe_str(port_name, "").strip()
        if not port_name:
            self._last_error = "No serial port specified."
            self.connection_error.emit(self._last_error)
            return False

        baud = max(
            1200,
            safe_int(
                baudrate if baudrate is not None else self._settings_service.get_setting("hardware", "serial_baudrate", 115200),
                115200,
            ),
        )

        self.serial_connect_requested.emit(port_name, baud)

        if self._serial_service is None:
            # Discovery-only fallback: no actual connect implementation yet
            self._selected_port = port_name
            self._last_error = "SerialService is not attached; connection request recorded only."
            self._logger.warning(self._last_error)
            self.refresh_connection_state()
            return False

        try:
            result = self._call_attr(
                self._serial_service,
                ["connect", "open", "open_port", "connect_to_port"],
                port_name,
                baud,
            )
            self._selected_port = port_name
            self.refresh_connection_state()
            return bool(result) if result is not None else self._serial_connected
        except Exception as exc:
            log_exception(self._logger, f"Failed to connect serial port {port_name}", exc)
            self._last_error = str(exc)
            self.connection_error.emit(str(exc))
            self.refresh_connection_state()
            return False

    def connect_to_selected_port(self) -> bool:
        if not self._selected_port:
            return False
        return self.connect_to_port(self._selected_port)

    def connect_to_preferred_port(self) -> bool:
        target = self._preferred_port or self._selected_port
        if not target and self._available_ports:
            target = self._available_ports[0].device
        if not target:
            self._last_error = "No preferred serial port available."
            self.connection_error.emit(self._last_error)
            return False
        return self.connect_to_port(target)

    def disconnect_serial(self) -> bool:
        self.serial_disconnect_requested.emit()

        if self._serial_service is None:
            self._serial_connected = False
            self._esp32_connected = False
            self._last_heartbeat_at = ""
            self.refresh_connection_state()
            return True

        try:
            result = self._call_attr(
                self._serial_service,
                ["disconnect", "close", "close_port"],
            )
            self.refresh_connection_state()
            return bool(result) if result is not None else not self._serial_connected
        except Exception as exc:
            log_exception(self._logger, "Failed to disconnect serial", exc)
            self._last_error = str(exc)
            self.connection_error.emit(str(exc))
            self.refresh_connection_state()
            return False

    # ========================================================
    # External state update hooks for later SerialService
    # ========================================================

    def update_network_connected(self, connected: bool) -> Dict[str, Any]:
        self._network_connected = bool(connected)
        return self.refresh_connection_state()

    def update_serial_connected(self, connected: bool, port_name: str = "", baudrate: Optional[int] = None) -> Dict[str, Any]:
        self._serial_connected = bool(connected)
        if port_name:
            self._selected_port = safe_str(port_name, "").strip()

        if self._app_state:
            self._app_state.set_serial_connected(self._serial_connected, serial_port=self._selected_port)

        if baudrate is not None:
            try:
                self._settings_service.set_serial_baudrate(baudrate)
            except Exception:
                pass

        return self.refresh_connection_state()

    def update_esp32_connected(
        self,
        connected: bool,
        *,
        heartbeat_at: str = "",
        error_message: str = "",
    ) -> Dict[str, Any]:
        self._esp32_connected = bool(connected)
        if heartbeat_at:
            self._last_heartbeat_at = heartbeat_at
        if error_message:
            self._last_error = error_message

        if self._app_state:
            self._app_state.set_esp32_connected(
                self._esp32_connected,
                heartbeat_at=self._last_heartbeat_at,
                error_message=self._last_error,
            )

        return self.refresh_connection_state()

    def record_heartbeat(self, heartbeat_at: Optional[str] = None) -> Dict[str, Any]:
        self._last_heartbeat_at = safe_str(heartbeat_at, now_iso()).strip() or now_iso()
        self._esp32_connected = True
        if self._app_state:
            self._app_state.set_esp32_connected(True, heartbeat_at=self._last_heartbeat_at)
        return self.refresh_connection_state()

    def set_last_error(self, message: str) -> Dict[str, Any]:
        self._last_error = safe_str(message, "").strip()
        return self.refresh_connection_state()

    # ========================================================
    # Mode integration
    # ========================================================

    def on_mode_changed(self, mode: str) -> Dict[str, Any]:
        """
        Called by ModeService when switching demo/hardware.
        """
        normalized = validate_runtime_mode(mode or self._mode())
        payload: Dict[str, Any] = {
            "mode": normalized,
            "policy": {},
        }

        if normalized == MODE_DEMO:
            # Demo mode should not present hardware as required.
            self._serial_connected = False
            self._esp32_connected = False
            self._last_error = ""
            self._connection_label = "Demo Mode Active"
            self._connection_detail = "Using simulated measurements."
            self._app_state.update_connection_state(
                serial_connected=False,
                esp32_connected=False,
                demo_mode_active=True,
                connection_label=self._connection_label,
                connection_detail=self._connection_detail,
                last_error="",
            )
            payload["policy"] = {
                "requires_hardware": False,
                "auto_connect_attempted": False,
                "selected_port": self._selected_port,
            }
        else:
            # Hardware mode: keep selected port, optionally try preferred port if available.
            auto_attempted = False
            if self._preferred_port:
                auto_attempted = True
            self._app_state.update_connection_state(
                demo_mode_active=False,
                connection_label="Hardware Waiting",
                connection_detail="Waiting for ESP32 / serial hardware connection.",
            )
            payload["policy"] = {
                "requires_hardware": True,
                "auto_connect_attempted": auto_attempted,
                "selected_port": self._selected_port,
                "preferred_port": self._preferred_port,
            }

        snapshot = self.refresh_connection_state()
        payload["snapshot"] = deep_copy(snapshot)
        self.mode_policy_applied.emit(deep_copy(payload))
        return payload

    # ========================================================
    # Readiness / UI helpers
    # ========================================================

    def hardware_ready(self) -> bool:
        snapshot = self.refresh_connection_state()
        return bool(snapshot.get("serial_connected", False) or snapshot.get("esp32_connected", False))

    def readiness_snapshot(self) -> Dict[str, Any]:
        snapshot = self.refresh_connection_state()
        mode = safe_str(snapshot.get("mode"), DEFAULT_RUNTIME_MODE)

        if mode == MODE_DEMO:
            return {
                "mode": mode,
                "ready": True,
                "requires_hardware": False,
                "serial_connected": False,
                "esp32_connected": False,
                "selected_port": snapshot.get("selected_port", ""),
                "available_ports": deep_copy(snapshot.get("available_ports", [])),
                "reason": "Demo mode is always ready.",
            }

        ready = bool(snapshot.get("serial_connected", False) or snapshot.get("esp32_connected", False))
        reason = "Hardware connected." if ready else "Waiting for serial / ESP32 connection."

        return {
            "mode": mode,
            "ready": ready,
            "requires_hardware": True,
            "serial_connected": bool(snapshot.get("serial_connected", False)),
            "esp32_connected": bool(snapshot.get("esp32_connected", False)),
            "selected_port": snapshot.get("selected_port", ""),
            "available_ports": deep_copy(snapshot.get("available_ports", [])),
            "reason": reason,
        }

    def connection_badge_payload(self) -> Dict[str, Any]:
        snapshot = self.refresh_connection_state()
        mode = safe_str(snapshot.get("mode"), DEFAULT_RUNTIME_MODE)

        if mode == MODE_DEMO:
            return {
                "connected": True,
                "waiting": False,
                "label": "Demo Mode Active",
                "detail": "Using simulated measurements.",
            }

        esp32_connected = bool(snapshot.get("esp32_connected", False))
        serial_connected = bool(snapshot.get("serial_connected", False))

        if esp32_connected:
            return {
                "connected": True,
                "waiting": False,
                "label": "Hardware Connected",
                "detail": safe_str(snapshot.get("connection_detail"), "ESP32 is connected and sending data."),
            }

        if serial_connected:
            return {
                "connected": True,
                "waiting": False,
                "label": "Serial Connected",
                "detail": safe_str(snapshot.get("connection_detail"), "Serial link is connected."),
            }

        return {
            "connected": False,
            "waiting": True,
            "label": "Hardware Waiting" if mode == MODE_HARDWARE else "Disconnected",
            "detail": safe_str(snapshot.get("connection_detail"), "Waiting for connection."),
        }

    # ========================================================
    # Snapshot / diagnostics
    # ========================================================

    def snapshot(self) -> Dict[str, Any]:
        return self.refresh_connection_state()

    def diagnostics(self) -> Dict[str, Any]:
        snapshot = self.refresh_connection_state()
        return {
            "pyserial_available": _PYSERIAL_AVAILABLE,
            "mode": snapshot.get("mode"),
            "network_connected": snapshot.get("network_connected"),
            "raspberry_pi_detected": snapshot.get("raspberry_pi_detected"),
            "serial_available": snapshot.get("serial_available"),
            "serial_connected": snapshot.get("serial_connected"),
            "esp32_connected": snapshot.get("esp32_connected"),
            "selected_port": snapshot.get("selected_port"),
            "preferred_port": snapshot.get("preferred_port"),
            "available_ports_count": len(snapshot.get("available_ports", [])),
            "baudrate": snapshot.get("baudrate"),
            "last_heartbeat_at": snapshot.get("last_heartbeat_at"),
            "last_refresh_at": snapshot.get("last_refresh_at"),
            "auto_refresh_enabled": snapshot.get("auto_refresh_enabled"),
            "refresh_interval_ms": snapshot.get("refresh_interval_ms"),
            "last_error": snapshot.get("last_error"),
        }


# ============================================================
# Singleton accessor
# ============================================================

_CONNECTION_SERVICE_SINGLETON: Optional[ConnectionService] = None


def get_connection_service(
    app_state: Optional[AppState] = None,
    settings_service: Optional[SettingsService] = None,
    mode_service: Optional[ModeService] = None,
    serial_service: Optional[object] = None,
) -> ConnectionService:
    global _CONNECTION_SERVICE_SINGLETON
    if _CONNECTION_SERVICE_SINGLETON is None:
        _CONNECTION_SERVICE_SINGLETON = ConnectionService(
            app_state=app_state,
            settings_service=settings_service,
            mode_service=mode_service,
            serial_service=serial_service,
        )
    else:
        if serial_service is not None:
            _CONNECTION_SERVICE_SINGLETON._serial_service = serial_service
    return _CONNECTION_SERVICE_SINGLETON