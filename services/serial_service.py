"""
services/serial_service.py

Serial communication service for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the main backend for UART / serial communication with ESP32 hardware
- It supports both laptop development and Raspberry Pi deployment
- It provides:
    - serial port discovery
    - connection / disconnection
    - background serial reading
    - heartbeat tracking
    - packet parsing
    - auto reconnect
    - raw serial log writing
- It is designed to stay linked with:
    - services/connection_service.py
    - services/sensor_service.py
    - services/mode_service.py
    - services/settings_service.py
    - core/app_state.py

Important design notes:
- Demo mode does not require serial hardware, but this service can still exist safely
- Hardware mode can use this service to read live ESP32 data
- Incoming lines are parsed in a tolerant way:
    1. JSON lines
    2. key=value or key:value lines
    3. simple status / heartbeat messages
- The service emits both raw text and parsed packet signals so later services/screens can
  consume whichever level they need
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from config import PATHS
from core.app_state import AppState, get_app_state
from core.constants import MODE_DEMO, MODE_HARDWARE
from core.logger import get_logger, log_exception
from core.utils import (
    append_text_line,
    deep_copy,
    ensure_directory,
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
    import serial  # type: ignore
    from serial.tools import list_ports as serial_list_ports  # type: ignore
    _PYSERIAL_AVAILABLE = True
except Exception:
    serial = None
    serial_list_ports = None
    _PYSERIAL_AVAILABLE = False


# ============================================================
# Dataclasses
# ============================================================

@dataclass
class SerialPortEntry:
    """
    Simplified serial port listing payload.
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
class SerialSnapshot:
    """
    Runtime serial service state snapshot.
    """
    pyserial_available: bool
    mode: str
    connected: bool
    esp32_connected: bool
    port_name: str
    baudrate: int
    timeout_seconds: float
    available_ports: List[Dict[str, Any]]
    preferred_port: str
    last_line: str
    last_packet: Dict[str, Any]
    last_read_at: str
    last_write_at: str
    last_heartbeat_at: str
    heartbeat_age_seconds: float
    auto_reconnect_enabled: bool
    auto_reconnect_interval_ms: int
    last_error: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pyserial_available": self.pyserial_available,
            "mode": self.mode,
            "connected": self.connected,
            "esp32_connected": self.esp32_connected,
            "port_name": self.port_name,
            "baudrate": self.baudrate,
            "timeout_seconds": self.timeout_seconds,
            "available_ports": deep_copy(self.available_ports),
            "preferred_port": self.preferred_port,
            "last_line": self.last_line,
            "last_packet": deep_copy(self.last_packet),
            "last_read_at": self.last_read_at,
            "last_write_at": self.last_write_at,
            "last_heartbeat_at": self.last_heartbeat_at,
            "heartbeat_age_seconds": self.heartbeat_age_seconds,
            "auto_reconnect_enabled": self.auto_reconnect_enabled,
            "auto_reconnect_interval_ms": self.auto_reconnect_interval_ms,
            "last_error": self.last_error,
        }


# ============================================================
# Internal reader thread
# ============================================================

class _SerialReaderThread(threading.Thread):
    """
    Background thread that reads lines from an open pyserial connection.

    It is intentionally lightweight:
    - reads line by line using serial timeout
    - forwards decoded text to callbacks
    - exits cleanly when stop() is requested
    """

    def __init__(
        self,
        serial_obj: Any,
        on_line_callback,
        on_error_callback,
        stop_event: threading.Event,
    ) -> None:
        super().__init__(daemon=True)
        self._serial_obj = serial_obj
        self._on_line_callback = on_line_callback
        self._on_error_callback = on_error_callback
        self._stop_event = stop_event

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                if self._serial_obj is None:
                    break

                if not getattr(self._serial_obj, "is_open", False):
                    break

                raw = self._serial_obj.readline()
                if not raw:
                    continue

                try:
                    line = raw.decode("utf-8", errors="ignore").strip()
                except Exception:
                    line = safe_str(raw, "").strip()

                if line:
                    self._on_line_callback(line)

            except Exception as exc:
                self._on_error_callback(exc)
                break

    def stop(self) -> None:
        self._stop_event.set()


# ============================================================
# Serial service
# ============================================================

class SerialService(QObject):
    """
    Central serial/UART communication service.

    Main responsibilities:
    - discover available serial ports
    - open and close serial connections
    - continuously read serial lines in a background thread
    - parse lines into packet dictionaries
    - detect heartbeat / ready status from ESP32
    - expose simple APIs used by ConnectionService and SensorService later
    """

    ports_scanned = pyqtSignal(list)

    connected_signal = pyqtSignal(str, int)
    disconnected_signal = pyqtSignal()

    line_received = pyqtSignal(str)
    raw_data_received = pyqtSignal(str)
    packet_received = pyqtSignal(dict)
    measurement_packet_received = pyqtSignal(dict)
    status_packet_received = pyqtSignal(dict)
    heartbeat_received = pyqtSignal(str)

    write_completed = pyqtSignal(str)
    auto_reconnect_started = pyqtSignal(int)
    auto_reconnect_stopped = pyqtSignal()

    serial_state_changed = pyqtSignal(dict)
    serial_error = pyqtSignal(str)

    def __init__(
        self,
        app_state: Optional[AppState] = None,
        settings_service: Optional[SettingsService] = None,
        mode_service: Optional[ModeService] = None,
        connection_service: Optional[object] = None,
    ) -> None:
        super().__init__()

        self._logger = logger.bind(component="SerialService")

        self._app_state: AppState = app_state or get_app_state()
        self._settings_service: SettingsService = settings_service or get_settings_service()
        self._mode_service: ModeService = mode_service or get_mode_service()
        self._connection_service: Optional[object] = connection_service

        self._serial_obj: Optional[Any] = None
        self._reader_thread: Optional[_SerialReaderThread] = None
        self._reader_stop_event = threading.Event()
        self._state_lock = threading.RLock()

        self._available_ports: List[SerialPortEntry] = []
        self._port_name: str = ""
        self._preferred_port: str = ""
        self._baudrate: int = 115200
        self._timeout_seconds: float = 1.0

        self._connected: bool = False
        self._esp32_connected: bool = False

        self._last_line: str = ""
        self._last_packet: Dict[str, Any] = {}
        self._last_read_at: str = ""
        self._last_write_at: str = ""
        self._last_heartbeat_at: str = ""
        self._last_error: str = ""

        self._heartbeat_stale_after_seconds: float = 8.0

        self._serial_log_path: Path = PATHS.logs_dir / "serial.log"
        ensure_directory(PATHS.logs_dir)

        self._auto_reconnect_timer = QTimer(self)
        self._auto_reconnect_timer.setSingleShot(False)
        self._auto_reconnect_timer.timeout.connect(self._auto_reconnect_tick)
        self._auto_reconnect_interval_ms: int = 3000

        self._load_settings()
        self.scan_ports()

    # ========================================================
    # Basic settings / preferences
    # ========================================================

    def _load_settings(self) -> None:
        hardware = self._settings_service.get_section("hardware")
        self._preferred_port = safe_str(hardware.get("preferred_serial_port"), "").strip()
        self._port_name = self._preferred_port
        self._baudrate = max(1200, safe_int(hardware.get("serial_baudrate"), 115200))
        self._timeout_seconds = max(0.1, safe_float(hardware.get("serial_timeout_seconds"), 1.0))
        self._auto_reconnect_interval_ms = max(
            1000,
            int(max(0.5, safe_float(hardware.get("auto_reconnect_seconds"), 3.0)) * 1000),
        )
        self._heartbeat_stale_after_seconds = max(4.0, self._timeout_seconds * 6.0)

    def set_connection_service(self, connection_service: object) -> None:
        self._connection_service = connection_service

    def current_mode(self) -> str:
        return validate_runtime_mode(self._mode_service.current_mode() or self._app_state.runtime_mode())

    # ========================================================
    # Compatibility accessors for ConnectionService
    # ========================================================

    def is_connected(self) -> bool:
        with self._state_lock:
            return bool(self._connected)

    @property
    def serial_connected(self) -> bool:
        return self.is_connected()

    def is_esp32_connected(self) -> bool:
        with self._state_lock:
            if not self._connected:
                return False
            if not self._last_heartbeat_at:
                return False
            return not self._heartbeat_is_stale(self._last_heartbeat_at)

    @property
    def esp32_connected(self) -> bool:
        return self.is_esp32_connected()

    def hardware_ready(self) -> bool:
        return self.is_connected() and self.is_esp32_connected()

    def current_port_name(self) -> str:
        with self._state_lock:
            return self._port_name

    def current_baudrate(self) -> int:
        with self._state_lock:
            return int(self._baudrate)

    def get_last_heartbeat_at(self) -> str:
        with self._state_lock:
            return self._last_heartbeat_at

    @property
    def last_heartbeat_at(self) -> str:
        return self.get_last_heartbeat_at()

    def get_last_error(self) -> str:
        with self._state_lock:
            return self._last_error

    @property
    def last_error(self) -> str:
        return self.get_last_error()

    # ========================================================
    # Port discovery
    # ========================================================

    def _coerce_port_info(self, raw_port: Any) -> Optional[SerialPortEntry]:
        device = safe_str(getattr(raw_port, "device", ""), "").strip()
        if not device:
            return None

        return SerialPortEntry(
            device=device,
            description=safe_str(getattr(raw_port, "description", ""), ""),
            manufacturer=safe_str(getattr(raw_port, "manufacturer", ""), ""),
            hwid=safe_str(getattr(raw_port, "hwid", ""), ""),
            vid=safe_str(getattr(raw_port, "vid", ""), ""),
            pid=safe_str(getattr(raw_port, "pid", ""), ""),
            serial_number=safe_str(getattr(raw_port, "serial_number", ""), ""),
        )

    def scan_ports(self) -> List[Dict[str, Any]]:
        """
        Scan available serial ports using pyserial if available.
        """
        ports: List[SerialPortEntry] = []

        try:
            if _PYSERIAL_AVAILABLE and serial_list_ports is not None:
                for raw_port in serial_list_ports.comports():
                    port = self._coerce_port_info(raw_port)
                    if port is not None:
                        ports.append(port)
        except Exception as exc:
            self._last_error = str(exc)
            self._logger.warning("Serial port scan failed: %s", exc)

        with self._state_lock:
            self._available_ports = ports

            # Keep selected port valid if possible
            if self._port_name and any(p.device == self._port_name for p in ports):
                pass
            elif self._preferred_port and any(p.device == self._preferred_port for p in ports):
                self._port_name = self._preferred_port
            elif ports:
                self._port_name = ports[0].device
            else:
                self._port_name = ""

        payload = [p.to_dict() for p in ports]
        self.ports_scanned.emit(deep_copy(payload))
        self._emit_state_changed()
        return payload

    def list_ports(self) -> List[Dict[str, Any]]:
        return self.available_ports()

    def available_ports(self) -> List[Dict[str, Any]]:
        with self._state_lock:
            return [p.to_dict() for p in self._available_ports]

    def get_available_ports(self) -> List[Dict[str, Any]]:
        return self.available_ports()

    def set_preferred_port(self, port_name: str) -> str:
        port_name = safe_str(port_name, "").strip()
        with self._state_lock:
            self._preferred_port = port_name
            if not self._port_name:
                self._port_name = port_name
        try:
            self._settings_service.set_preferred_serial_port(port_name)
        except Exception as exc:
            self._logger.warning("Failed to save preferred serial port: %s", exc)
        self._emit_state_changed()
        return port_name

    def set_selected_port(self, port_name: str) -> str:
        port_name = safe_str(port_name, "").strip()
        with self._state_lock:
            self._port_name = port_name
        self._emit_state_changed()
        return port_name

    # ========================================================
    # Connection management
    # ========================================================

    def connect(
        self,
        port_name: str,
        baudrate: Optional[int] = None,
    ) -> bool:
        """
        Open a serial connection and start the reader thread.
        """
        port_name = safe_str(port_name, "").strip()
        if not port_name:
            self._set_error("No serial port specified.")
            return False

        if not _PYSERIAL_AVAILABLE or serial is None:
            self._set_error("pyserial is not available in this environment.")
            return False

        target_baud = max(1200, safe_int(baudrate, self._baudrate))

        try:
            # If already connected to same port, keep it.
            if self.is_connected() and self.current_port_name() == port_name and self.current_baudrate() == target_baud:
                return True

            # Disconnect old connection first
            if self.is_connected():
                self.disconnect()

            serial_obj = serial.Serial(
                port=port_name,
                baudrate=target_baud,
                timeout=self._timeout_seconds,
                write_timeout=self._timeout_seconds,
            )

            self._reader_stop_event = threading.Event()
            self._reader_thread = _SerialReaderThread(
                serial_obj=serial_obj,
                on_line_callback=self._handle_incoming_line,
                on_error_callback=self._handle_reader_error,
                stop_event=self._reader_stop_event,
            )

            with self._state_lock:
                self._serial_obj = serial_obj
                self._connected = True
                self._esp32_connected = False
                self._port_name = port_name
                self._baudrate = target_baud
                self._last_error = ""

            self._reader_thread.start()

            self._notify_connection_service_connected()
            self._emit_state_changed()
            self.connected_signal.emit(port_name, target_baud)

            self._logger.info("Serial connected on %s @ %s", port_name, target_baud)
            return True

        except Exception as exc:
            log_exception(self._logger, f"Failed to connect serial port {port_name}", exc)
            self._set_error(str(exc))
            self._cleanup_serial_objects()
            self._emit_state_changed()
            return False

    def open(self, port_name: str, baudrate: Optional[int] = None) -> bool:
        return self.connect(port_name, baudrate)

    def open_port(self, port_name: str, baudrate: Optional[int] = None) -> bool:
        return self.connect(port_name, baudrate)

    def connect_to_port(self, port_name: str, baudrate: Optional[int] = None) -> bool:
        return self.connect(port_name, baudrate)

    def disconnect(self) -> bool:
        """
        Close the serial connection and stop background reading.
        """
        try:
            self._reader_stop_event.set()

            if self._reader_thread is not None and self._reader_thread.is_alive():
                self._reader_thread.join(timeout=1.5)

            with self._state_lock:
                if self._serial_obj is not None:
                    try:
                        if getattr(self._serial_obj, "is_open", False):
                            self._serial_obj.close()
                    except Exception:
                        pass

                self._serial_obj = None
                self._reader_thread = None
                self._connected = False
                self._esp32_connected = False
                self._last_heartbeat_at = ""

            self._notify_connection_service_disconnected()
            self._emit_state_changed()
            self.disconnected_signal.emit()
            self._logger.info("Serial disconnected.")
            return True

        except Exception as exc:
            log_exception(self._logger, "Failed to disconnect serial", exc)
            self._set_error(str(exc))
            self._emit_state_changed()
            return False

    def close(self) -> bool:
        return self.disconnect()

    def close_port(self) -> bool:
        return self.disconnect()

    def _cleanup_serial_objects(self) -> None:
        with self._state_lock:
            try:
                if self._serial_obj is not None and getattr(self._serial_obj, "is_open", False):
                    self._serial_obj.close()
            except Exception:
                pass
            self._serial_obj = None
            self._reader_thread = None
            self._connected = False
            self._esp32_connected = False

    # ========================================================
    # Write helpers
    # ========================================================

    def send_text(self, text: str, newline: bool = True) -> bool:
        """
        Send plain text to the connected serial device.
        """
        if not self.is_connected():
            self._set_error("Cannot send text: serial is not connected.")
            return False

        payload = safe_str(text, "")
        if newline:
            payload += "\n"

        try:
            with self._state_lock:
                if self._serial_obj is None or not getattr(self._serial_obj, "is_open", False):
                    self._set_error("Cannot send text: serial port is closed.")
                    return False

                self._serial_obj.write(payload.encode("utf-8"))
                self._serial_obj.flush()
                self._last_write_at = now_iso()

            self._write_raw_log(f">>> {payload.rstrip()}")
            self.write_completed.emit(payload.rstrip("\n"))
            self._emit_state_changed()
            return True

        except Exception as exc:
            log_exception(self._logger, "Failed to send serial text", exc)
            self._set_error(str(exc))
            self._emit_state_changed()
            return False

    def send_command(self, command: str) -> bool:
        return self.send_text(command, newline=True)

    def ping(self) -> bool:
        return self.send_command("PING")

    def request_measurement(self) -> bool:
        """
        Generic measurement trigger command.
        Adjust later if your ESP32 protocol uses another command name.
        """
        return self.send_command("START_MEASUREMENT")

    def request_status(self) -> bool:
        return self.send_command("STATUS")

    # ========================================================
    # Background reading
    # ========================================================

    def _handle_reader_error(self, exc: Exception) -> None:
        self._set_error(str(exc))
        self._logger.warning("Serial reader thread error: %s", exc)

        with self._state_lock:
            self._connected = False
            self._esp32_connected = False

        self._notify_connection_service_disconnected()
        self._emit_state_changed()

    def _handle_incoming_line(self, line: str) -> None:
        """
        Called from the reader thread when a line arrives.
        """
        cleaned = safe_str(line, "").strip()
        if not cleaned:
            return

        with self._state_lock:
            self._last_line = cleaned
            self._last_read_at = now_iso()

        self._write_raw_log(cleaned)
        self.line_received.emit(cleaned)
        self.raw_data_received.emit(cleaned)

        packet = self._parse_line(cleaned)

        with self._state_lock:
            self._last_packet = deep_copy(packet)

        if packet.get("kind") == "heartbeat":
            self._record_heartbeat()
            self.heartbeat_received.emit(self._last_heartbeat_at)
            self.status_packet_received.emit(deep_copy(packet))
        elif packet.get("kind") == "measurement":
            # measurement packets also imply the device is alive
            self._record_heartbeat()
            self.measurement_packet_received.emit(deep_copy(packet))
        elif packet.get("kind") == "status":
            if packet.get("state") in {"ready", "connected", "alive"}:
                self._record_heartbeat()
            self.status_packet_received.emit(deep_copy(packet))
        else:
            # generic message still indicates serial link is alive
            pass

        self.packet_received.emit(deep_copy(packet))
        self._emit_state_changed()

    # ========================================================
    # Packet parsing
    # ========================================================

    _METRIC_ALIASES = {
        "temp": "temperature",
        "temperature": "temperature",
        "body_temp": "temperature",
        "t": "temperature",

        "spo2": "spo2",
        "o2": "spo2",
        "oxygen": "spo2",
        "sp02": "spo2",

        "pulse": "pulse_rate",
        "pulse_rate": "pulse_rate",
        "hr": "pulse_rate",
        "heart_rate": "pulse_rate",
        "bpm": "pulse_rate",

        "rr": "respiratory_rate",
        "respiratory_rate": "respiratory_rate",
        "resp": "respiratory_rate",
        "resp_rate": "respiratory_rate",
        "breathing_rate": "respiratory_rate",

        "weight": "weight",
        "wt": "weight",
        "mass": "weight",

        "height": "height",
        "ht": "height",

        "bmi": "bmi",
    }

    _HEARTBEAT_TERMS = {
        "heartbeat",
        "hb",
        "ping",
        "pong",
        "alive",
        "esp32_ready",
        "ready",
        "device_ready",
    }

    def _normalize_metric_key(self, key: str) -> str:
        cleaned = safe_str(key, "").strip().lower()
        return self._METRIC_ALIASES.get(cleaned, cleaned)

    def _packet_from_measurements(self, measurements: Mapping[str, Any], raw_line: str) -> Dict[str, Any]:
        compact: Dict[str, Any] = {}
        for key, value in measurements.items():
            metric_key = self._normalize_metric_key(key)
            if metric_key in {
                "temperature",
                "spo2",
                "pulse_rate",
                "respiratory_rate",
                "weight",
                "height",
                "bmi",
            }:
                compact[metric_key] = safe_float(value, 0.0)

        return {
            "kind": "measurement",
            "timestamp": now_iso(),
            "measurements": compact,
            "raw_line": raw_line,
        }

    def _parse_json_packet(self, raw_line: str) -> Optional[Dict[str, Any]]:
        try:
            obj = json.loads(raw_line)
        except Exception:
            return None

        if not isinstance(obj, Mapping):
            return {
                "kind": "message",
                "timestamp": now_iso(),
                "raw_line": raw_line,
                "text": safe_str(obj, raw_line),
            }

        lowered = {self._normalize_metric_key(k): v for k, v in obj.items()}

        # Heartbeat packet
        packet_type = safe_str(obj.get("type"), "").strip().lower()
        packet_status = safe_str(obj.get("status"), "").strip().lower()

        if packet_type in self._HEARTBEAT_TERMS or packet_status in self._HEARTBEAT_TERMS:
            return {
                "kind": "heartbeat",
                "timestamp": now_iso(),
                "state": packet_type or packet_status or "heartbeat",
                "payload": deep_copy(dict(obj)),
                "raw_line": raw_line,
            }

        measurement_keys = {
            "temperature",
            "spo2",
            "pulse_rate",
            "respiratory_rate",
            "weight",
            "height",
            "bmi",
        }
        measurements = {k: v for k, v in lowered.items() if k in measurement_keys}
        if measurements:
            return self._packet_from_measurements(measurements, raw_line)

        return {
            "kind": "status",
            "timestamp": now_iso(),
            "state": packet_status or packet_type or "json",
            "payload": deep_copy(dict(obj)),
            "raw_line": raw_line,
        }

    def _parse_kv_packet(self, raw_line: str) -> Optional[Dict[str, Any]]:
        """
        Supports lines like:
            temp=36.8, spo2=98, pulse=72
            temp:36.8 spo2:98 pulse:72
        """
        matches = re.findall(
            r"([A-Za-z_][A-Za-z0-9_]*)\s*[:=]\s*(-?\d+(?:\.\d+)?)",
            raw_line,
        )
        if not matches:
            return None

        measurements: Dict[str, Any] = {}
        for key, value in matches:
            metric_key = self._normalize_metric_key(key)
            measurements[metric_key] = safe_float(value, 0.0)

        if measurements:
            return self._packet_from_measurements(measurements, raw_line)
        return None

    def _parse_status_packet(self, raw_line: str) -> Dict[str, Any]:
        lowered = raw_line.strip().lower()

        if lowered in self._HEARTBEAT_TERMS:
            return {
                "kind": "heartbeat",
                "timestamp": now_iso(),
                "state": lowered,
                "raw_line": raw_line,
            }

        if "heartbeat" in lowered or "pong" in lowered or "esp32 ready" in lowered:
            return {
                "kind": "heartbeat",
                "timestamp": now_iso(),
                "state": "heartbeat",
                "raw_line": raw_line,
            }

        if "finger detected" in lowered:
            return {
                "kind": "status",
                "timestamp": now_iso(),
                "state": "finger_detected",
                "raw_line": raw_line,
                "text": raw_line,
            }

        if "finger removed" in lowered:
            return {
                "kind": "status",
                "timestamp": now_iso(),
                "state": "finger_removed",
                "raw_line": raw_line,
                "text": raw_line,
            }

        if "place finger" in lowered:
            return {
                "kind": "status",
                "timestamp": now_iso(),
                "state": "place_finger",
                "raw_line": raw_line,
                "text": raw_line,
            }

        if "stable data" in lowered or "collecting" in lowered:
            return {
                "kind": "status",
                "timestamp": now_iso(),
                "state": "collecting",
                "raw_line": raw_line,
                "text": raw_line,
            }

        if "rejected" in lowered or "noisy signal" in lowered or "weak" in lowered:
            return {
                "kind": "status",
                "timestamp": now_iso(),
                "state": "warning",
                "raw_line": raw_line,
                "text": raw_line,
            }

        return {
            "kind": "message",
            "timestamp": now_iso(),
            "raw_line": raw_line,
            "text": raw_line,
        }

    def _parse_line(self, raw_line: str) -> Dict[str, Any]:
        """
        Try JSON first, then key/value measurement line, then status/message.
        """
        parsed = self._parse_json_packet(raw_line)
        if parsed is not None:
            return parsed

        parsed = self._parse_kv_packet(raw_line)
        if parsed is not None:
            return parsed

        return self._parse_status_packet(raw_line)

    # ========================================================
    # Heartbeat / state helpers
    # ========================================================

    def _record_heartbeat(self) -> None:
        with self._state_lock:
            self._last_heartbeat_at = now_iso()
            self._esp32_connected = True

        try:
            if self._connection_service is not None:
                callback = getattr(self._connection_service, "record_heartbeat", None)
                if callable(callback):
                    callback(self._last_heartbeat_at)
                    return

                callback = getattr(self._connection_service, "update_esp32_connected", None)
                if callable(callback):
                    callback(True, heartbeat_at=self._last_heartbeat_at)
        except Exception as exc:
            self._logger.debug("ConnectionService heartbeat sync failed: %s", exc)

    def _heartbeat_is_stale(self, heartbeat_at: str) -> bool:
        dt = parse_datetime(heartbeat_at)
        if dt is None:
            return True

        now_dt = parse_datetime(now_iso())
        if now_dt is None:
            return True

        try:
            age = abs((now_dt - dt).total_seconds())
            return age > self._heartbeat_stale_after_seconds
        except Exception:
            return True

    def heartbeat_age_seconds(self) -> float:
        with self._state_lock:
            heartbeat_at = self._last_heartbeat_at

        dt = parse_datetime(heartbeat_at)
        if dt is None:
            return -1.0

        now_dt = parse_datetime(now_iso())
        if now_dt is None:
            return -1.0

        try:
            return float(abs((now_dt - dt).total_seconds()))
        except Exception:
            return -1.0

    def _set_error(self, message: str) -> None:
        with self._state_lock:
            self._last_error = safe_str(message, "").strip()
        self.serial_error.emit(self._last_error)

        try:
            if self._connection_service is not None:
                callback = getattr(self._connection_service, "set_last_error", None)
                if callable(callback):
                    callback(self._last_error)
        except Exception:
            pass

    def _write_raw_log(self, line: str) -> None:
        try:
            append_text_line(self._serial_log_path, f"[{now_iso()}] {line}")
        except Exception as exc:
            self._logger.debug("Failed to append serial log: %s", exc)

    def _notify_connection_service_connected(self) -> None:
        try:
            if self._connection_service is not None:
                callback = getattr(self._connection_service, "update_serial_connected", None)
                if callable(callback):
                    callback(True, port_name=self._port_name, baudrate=self._baudrate)
        except Exception as exc:
            self._logger.debug("ConnectionService connect sync failed: %s", exc)

    def _notify_connection_service_disconnected(self) -> None:
        try:
            if self._connection_service is not None:
                callback = getattr(self._connection_service, "update_serial_connected", None)
                if callable(callback):
                    callback(False, port_name=self._port_name, baudrate=self._baudrate)
                callback = getattr(self._connection_service, "update_esp32_connected", None)
                if callable(callback):
                    callback(False, heartbeat_at="", error_message=self._last_error)
        except Exception as exc:
            self._logger.debug("ConnectionService disconnect sync failed: %s", exc)

    def _emit_state_changed(self) -> None:
        snapshot = self.snapshot()
        self.serial_state_changed.emit(snapshot)

    # ========================================================
    # Auto reconnect
    # ========================================================

    def start_auto_reconnect(self, interval_ms: Optional[int] = None) -> None:
        if interval_ms is not None:
            self._auto_reconnect_interval_ms = max(1000, safe_int(interval_ms, self._auto_reconnect_interval_ms))

        self._auto_reconnect_timer.start(self._auto_reconnect_interval_ms)
        self.auto_reconnect_started.emit(self._auto_reconnect_interval_ms)
        self._emit_state_changed()

    def stop_auto_reconnect(self) -> None:
        if self._auto_reconnect_timer.isActive():
            self._auto_reconnect_timer.stop()
            self.auto_reconnect_stopped.emit()
            self._emit_state_changed()

    def auto_reconnect_enabled(self) -> bool:
        return self._auto_reconnect_timer.isActive()

    def _auto_reconnect_tick(self) -> None:
        """
        Try to reconnect only in hardware mode and only when not already connected.
        """
        if self.current_mode() != MODE_HARDWARE:
            return

        if self.is_connected():
            return

        ports = self.scan_ports()
        if not ports:
            return

        target = ""
        if self._preferred_port and any(p["device"] == self._preferred_port for p in ports):
            target = self._preferred_port
        elif self._port_name and any(p["device"] == self._port_name for p in ports):
            target = self._port_name
        elif ports:
            target = safe_str(ports[0].get("device"), "")

        if target:
            self.connect(target)

    # ========================================================
    # Mode integration
    # ========================================================

    def on_mode_changed(self, mode: str) -> Dict[str, Any]:
        """
        Called by ModeService or ConnectionService when demo/hardware mode changes.
        """
        normalized = validate_runtime_mode(mode or self.current_mode())

        if normalized == MODE_DEMO:
            # Demo mode should not keep serial connection open unless you explicitly want that.
            if self.is_connected():
                self.disconnect()

        elif normalized == MODE_HARDWARE:
            # In hardware mode, keep auto reconnect behavior available.
            pass

        snapshot = self.snapshot()
        return {
            "mode": normalized,
            "connected": snapshot.get("connected", False),
            "selected_port": snapshot.get("port_name", ""),
            "auto_reconnect_enabled": snapshot.get("auto_reconnect_enabled", False),
        }

    # ========================================================
    # Test / simulation helper
    # ========================================================

    def simulate_incoming_line(self, line: str) -> Dict[str, Any]:
        """
        Useful for testing without real hardware.
        """
        self._handle_incoming_line(line)
        return deep_copy(self._last_packet)

    # ========================================================
    # Snapshot / diagnostics
    # ========================================================

    def snapshot(self) -> Dict[str, Any]:
        with self._state_lock:
            heartbeat_age = self.heartbeat_age_seconds()
            snapshot = SerialSnapshot(
                pyserial_available=_PYSERIAL_AVAILABLE,
                mode=self.current_mode(),
                connected=self._connected,
                esp32_connected=self.is_esp32_connected(),
                port_name=self._port_name,
                baudrate=self._baudrate,
                timeout_seconds=self._timeout_seconds,
                available_ports=[p.to_dict() for p in self._available_ports],
                preferred_port=self._preferred_port,
                last_line=self._last_line,
                last_packet=deep_copy(self._last_packet),
                last_read_at=self._last_read_at,
                last_write_at=self._last_write_at,
                last_heartbeat_at=self._last_heartbeat_at,
                heartbeat_age_seconds=heartbeat_age,
                auto_reconnect_enabled=self._auto_reconnect_timer.isActive(),
                auto_reconnect_interval_ms=self._auto_reconnect_interval_ms,
                last_error=self._last_error,
            ).to_dict()

        return snapshot

    def refresh_connection_state(self) -> Dict[str, Any]:
        """
        Compatibility helper expected by ConnectionService.
        """
        self.scan_ports()

        # If heartbeat has gone stale, reflect that in state
        with self._state_lock:
            if self._connected and self._last_heartbeat_at and self._heartbeat_is_stale(self._last_heartbeat_at):
                self._esp32_connected = False

        snapshot = self.snapshot()
        self.serial_state_changed.emit(deep_copy(snapshot))
        return snapshot

    def diagnostics(self) -> Dict[str, Any]:
        return self.snapshot()

    # ========================================================
    # Cleanup
    # ========================================================

    def shutdown(self) -> None:
        self.stop_auto_reconnect()
        self.disconnect()

    def __del__(self) -> None:
        try:
            self.shutdown()
        except Exception:
            pass


# ============================================================
# Singleton accessor
# ============================================================

_SERIAL_SERVICE_SINGLETON: Optional[SerialService] = None


def get_serial_service(
    app_state: Optional[AppState] = None,
    settings_service: Optional[SettingsService] = None,
    mode_service: Optional[ModeService] = None,
    connection_service: Optional[object] = None,
) -> SerialService:
    global _SERIAL_SERVICE_SINGLETON
    if _SERIAL_SERVICE_SINGLETON is None:
        _SERIAL_SERVICE_SINGLETON = SerialService(
            app_state=app_state,
            settings_service=settings_service,
            mode_service=mode_service,
            connection_service=connection_service,
        )
    else:
        if connection_service is not None:
            _SERIAL_SERVICE_SINGLETON.set_connection_service(connection_service)
    return _SERIAL_SERVICE_SINGLETON
