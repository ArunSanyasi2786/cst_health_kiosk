"""
services/sensor_service.py

Sensor orchestration service for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the main runtime bridge between the UI flow and actual measurement data
- It supports both:
    - Demo Mode: simulated measurements with realistic timing/progress
    - Hardware Mode: live measurement aggregation from SerialService packets
- It coordinates:
    - measurement start / cancel / complete / fail
    - demo data generation
    - hardware packet aggregation
    - stability filtering
    - progress updates
    - diagnosis building
    - session completion through SessionService
- It keeps AppState, SessionService, SerialService, ConnectionService, and DiagnosisService linked

Linked files:
- core/app_state.py
- core/constants.py
- core/utils.py
- services/mode_service.py
- services/calibration_service.py
- services/session_service.py
- services/serial_service.py
- services/connection_service.py
- services/diagnosis_service.py

Design goals:
- one unified measurement flow for demo and hardware modes
- clean separation between raw readings and stable accepted readings
- safe behavior even if serial hardware is absent
- easy for screens to consume through Qt signals
"""

from __future__ import annotations

import random
import statistics
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Mapping, Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from config import (
    DEMO_MEASUREMENT_DURATION_MS,
    HARDWARE_MEASUREMENT_FAILSAFE_TIMEOUT_MS,
)
from core.app_state import AppState, get_app_state
from core.constants import (
    METRIC_BMI,
    METRIC_HEIGHT,
    METRIC_PULSE,
    METRIC_RR,
    METRIC_SPO2,
    METRIC_TEMPERATURE,
    METRIC_WEIGHT,
    MODE_DEMO,
    MODE_HARDWARE,
    PRIMARY_METRIC_KEYS,
    SESSION_STATUS_COMPLETE,
    SESSION_STATUS_ERROR,
    SESSION_STATUS_MEASURING,
)
from core.logger import get_logger, log_exception
from core.utils import (
    calculate_bmi,
    deep_copy,
    metric_is_meaningful,
    normalize_measurement_payload,
    now_iso,
    safe_float,
    safe_int,
    safe_round,
    safe_str,
    validate_runtime_mode,
)
from services.calibration_service import CalibrationService, get_calibration_service
from services.connection_service import ConnectionService, get_connection_service
from services.diagnosis_service import DiagnosisService, get_diagnosis_service
from services.mode_service import ModeService, get_mode_service
from services.session_service import SessionService, get_session_service
from services.serial_service import SerialService, get_serial_service

logger = get_logger(__name__)


# ============================================================
# Dataclasses
# ============================================================

@dataclass
class SensorRunSnapshot:
    """
    Runtime sensor-service snapshot for the UI and debugging.
    """
    active: bool
    mode: str
    session_id: str
    started_at: str
    progress: int
    waiting_state: str
    finger_detected: bool
    raw_measurements: Dict[str, Any]
    stable_measurements: Dict[str, Any]
    stable_metric_count: int
    required_metric_count: int
    packet_count: int
    last_packet_at: str
    demo_elapsed_ms: int
    demo_duration_ms: int
    hardware_timeout_ms: int
    last_error: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================
# Sensor service
# ============================================================

class SensorService(QObject):
    """
    Central sensor orchestration service.

    Responsibilities:
    - start demo or hardware measurement sessions
    - generate simulated demo values
    - receive and aggregate live serial measurement packets
    - compute stable values before final acceptance
    - update session progress/messages continuously
    - finalize completed sessions with diagnosis
    """

    measurement_requested = pyqtSignal(str)
    measurement_started = pyqtSignal(dict)
    measurement_progress_changed = pyqtSignal(int, str)
    raw_measurements_changed = pyqtSignal(dict)
    stable_measurements_changed = pyqtSignal(dict)
    measurement_completed = pyqtSignal(dict)
    measurement_cancelled = pyqtSignal(dict)
    measurement_failed = pyqtSignal(str)

    demo_measurements_ready = pyqtSignal(dict)
    hardware_packet_received = pyqtSignal(dict)
    waiting_state_changed = pyqtSignal(str)
    finger_state_changed = pyqtSignal(bool)

    sensor_state_changed = pyqtSignal(dict)
    sensor_error = pyqtSignal(str)

    # --------------------------------------------------------
    # Stability tuning
    # --------------------------------------------------------
    _HARDWARE_REQUIRED_METRICS = [
        METRIC_WEIGHT,
        METRIC_HEIGHT,
        METRIC_TEMPERATURE,
        METRIC_SPO2,
        METRIC_PULSE,
        METRIC_RR,
    ]

    _STABLE_SAMPLE_COUNTS = {
        METRIC_WEIGHT: 1,
        METRIC_HEIGHT: 1,
        METRIC_TEMPERATURE: 1,
        METRIC_SPO2: 2,
        METRIC_PULSE: 2,
        METRIC_RR: 2,
    }

    _STABILITY_TOLERANCES = {
        METRIC_WEIGHT: 1.5,
        METRIC_HEIGHT: 1.0,
        METRIC_TEMPERATURE: 0.5,
        METRIC_SPO2: 2.0,
        METRIC_PULSE: 6.0,
        METRIC_RR: 4.0,
    }

    _BUFFER_LIMIT = 6

    def __init__(
        self,
        app_state: Optional[AppState] = None,
        mode_service: Optional[ModeService] = None,
        calibration_service: Optional[CalibrationService] = None,
        session_service: Optional[SessionService] = None,
        serial_service: Optional[SerialService] = None,
        connection_service: Optional[ConnectionService] = None,
        diagnosis_service: Optional[DiagnosisService] = None,
    ) -> None:
        super().__init__()

        self._logger = logger.bind(component="SensorService")

        self._app_state: AppState = app_state or get_app_state()
        self._mode_service: ModeService = mode_service or get_mode_service()
        self._calibration_service: CalibrationService = calibration_service or get_calibration_service()
        self._session_service: SessionService = session_service or get_session_service()
        self._serial_service: SerialService = serial_service or get_serial_service()
        self._connection_service: ConnectionService = connection_service or get_connection_service()
        self._diagnosis_service: DiagnosisService = diagnosis_service or get_diagnosis_service()

        # timers
        self._demo_tick_timer = QTimer(self)
        self._demo_tick_timer.setSingleShot(False)
        self._demo_tick_timer.setInterval(180)
        self._demo_tick_timer.timeout.connect(self._on_demo_tick)

        self._hardware_timeout_timer = QTimer(self)
        self._hardware_timeout_timer.setSingleShot(True)
        self._hardware_timeout_timer.timeout.connect(self._on_hardware_timeout)

        # runtime state
        self._active: bool = False
        self._mode: str = MODE_DEMO
        self._started_at: str = ""
        self._waiting_state: str = "idle"
        self._finger_detected: bool = False
        self._raw_measurements: Dict[str, Any] = normalize_measurement_payload({})
        self._stable_measurements: Dict[str, Any] = normalize_measurement_payload({})
        self._metric_buffers: Dict[str, List[float]] = {
            metric: [] for metric in self._HARDWARE_REQUIRED_METRICS
        }
        self._packet_count: int = 0
        self._last_packet_at: str = ""
        self._last_error: str = ""

        # demo runtime
        self._demo_started_monotonic: float = 0.0
        self._demo_elapsed_ms: int = 0
        self._demo_duration_ms: int = DEMO_MEASUREMENT_DURATION_MS
        self._persist_demo_sessions: bool = False

        # hardware runtime
        self._hardware_timeout_ms: int = HARDWARE_MEASUREMENT_FAILSAFE_TIMEOUT_MS
        self._minimum_metrics_to_finalize_on_timeout: int = 4

        self._serial_signals_bound: bool = False
        self._bind_serial_signals()
        self._emit_state_changed()

    # ========================================================
    # Dependency setters
    # ========================================================

    def set_serial_service(self, serial_service: SerialService) -> None:
        self._serial_service = serial_service
        self._serial_signals_bound = False
        self._bind_serial_signals()

    def set_connection_service(self, connection_service: ConnectionService) -> None:
        self._connection_service = connection_service

    def set_diagnosis_service(self, diagnosis_service: DiagnosisService) -> None:
        self._diagnosis_service = diagnosis_service

    # ========================================================
    # Internal helpers
    # ========================================================

    def _bind_serial_signals(self) -> None:
        """
        Connect to SerialService once.
        """
        if self._serial_service is None or self._serial_signals_bound:
            return

        try:
            self._serial_service.measurement_packet_received.connect(self._on_measurement_packet_received)
            self._serial_service.status_packet_received.connect(self._on_status_packet_received)
            self._serial_service.heartbeat_received.connect(self._on_heartbeat_received)
            self._serial_service.serial_error.connect(self._on_serial_error)
            self._serial_signals_bound = True
        except Exception as exc:
            self._logger.warning("Failed to bind serial signals: %s", exc)

    def _reset_runtime_state(self) -> None:
        self._active = False
        self._mode = validate_runtime_mode(self._mode_service.current_mode() or self._app_state.runtime_mode())
        self._started_at = ""
        self._waiting_state = "idle"
        self._finger_detected = False

        self._raw_measurements = normalize_measurement_payload({})
        self._stable_measurements = normalize_measurement_payload({})
        self._metric_buffers = {metric: [] for metric in self._HARDWARE_REQUIRED_METRICS}

        self._packet_count = 0
        self._last_packet_at = ""
        self._last_error = ""

        self._demo_started_monotonic = 0.0
        self._demo_elapsed_ms = 0

        self._stop_timers()

    def _stop_timers(self) -> None:
        if self._demo_tick_timer.isActive():
            self._demo_tick_timer.stop()
        if self._hardware_timeout_timer.isActive():
            self._hardware_timeout_timer.stop()

    def _session_id(self) -> str:
        snapshot = self._app_state.session_snapshot()
        return safe_str(snapshot.get("session_id"), "")

    def _required_metric_count(self) -> int:
        return len(self._HARDWARE_REQUIRED_METRICS)

    def _stable_metric_count(self) -> int:
        count = 0
        for metric in self._HARDWARE_REQUIRED_METRICS:
            if metric_is_meaningful(metric, self._stable_measurements.get(metric)):
                count += 1
        return count

    def _current_progress(self) -> int:
        snapshot = self._app_state.session_snapshot()
        return safe_int(snapshot.get("measurement_progress"), 0)

    def _emit_state_changed(self) -> Dict[str, Any]:
        payload = self.snapshot()
        self.sensor_state_changed.emit(deep_copy(payload))
        return payload

    def _set_waiting_state(self, state: str) -> None:
        state = safe_str(state, "").strip() or "idle"
        if state != self._waiting_state:
            self._waiting_state = state
            self.waiting_state_changed.emit(state)
            self._emit_state_changed()

    def _set_finger_detected(self, detected: bool) -> None:
        detected = bool(detected)
        if detected != self._finger_detected:
            self._finger_detected = detected
            self.finger_state_changed.emit(detected)
            self._emit_state_changed()

    def _set_error(self, message: str) -> None:
        self._last_error = safe_str(message, "").strip()
        self.sensor_error.emit(self._last_error)
        self._emit_state_changed()

    def _mean_or_latest(self, values: List[float]) -> float:
        if not values:
            return 0.0
        if len(values) == 1:
            return values[-1]
        return float(statistics.mean(values))

    def _metric_buffer(self, metric_key: str) -> List[float]:
        return self._metric_buffers.setdefault(metric_key, [])

    def _append_metric_sample(self, metric_key: str, value: float) -> None:
        buf = self._metric_buffer(metric_key)
        buf.append(safe_float(value, 0.0))
        if len(buf) > self._BUFFER_LIMIT:
            del buf[:-self._BUFFER_LIMIT]

    def _stable_sample_count(self, metric_key: str) -> int:
        return safe_int(self._STABLE_SAMPLE_COUNTS.get(metric_key), 1)

    def _stability_tolerance(self, metric_key: str) -> float:
        return safe_float(self._STABILITY_TOLERANCES.get(metric_key), 1.0)

    def _metric_is_stable(self, metric_key: str) -> bool:
        buf = self._metric_buffer(metric_key)
        minimum = self._stable_sample_count(metric_key)

        if len(buf) < minimum:
            return False

        if minimum <= 1:
            return True

        recent = buf[-minimum:]
        tolerance = self._stability_tolerance(metric_key)
        span = max(recent) - min(recent)
        return span <= tolerance

    def _stable_metric_value(self, metric_key: str) -> float:
        buf = self._metric_buffer(metric_key)
        minimum = self._stable_sample_count(metric_key)
        recent = buf[-minimum:] if len(buf) >= minimum else buf[:]
        value = self._mean_or_latest(recent)

        decimals = 0 if metric_key in {METRIC_SPO2, METRIC_PULSE, METRIC_RR} else 1
        return safe_round(value, decimals=decimals, default=0.0)

    def _hardware_completion_ratio(self) -> int:
        present = self._stable_metric_count()
        total = self._required_metric_count()
        if total <= 0:
            return 0
        return int(round((present / total) * 100.0))

    def _build_hardware_step_message(self) -> str:
        stable_count = self._stable_metric_count()
        total = self._required_metric_count()

        if stable_count >= total:
            return "All sensor readings collected."
        if not self._finger_detected and stable_count == 0:
            return "Waiting for live sensor data..."
        if self._finger_detected and stable_count == 0:
            return "Finger detected. Collecting stable readings..."
        return f"Collecting sensor data ({stable_count}/{total})..."

    def _refresh_session_from_stable_measurements(self, *, auto_diagnose: bool = False) -> None:
        """
        Push the current accepted stable measurements into SessionService/AppState.
        """
        step_message = self._build_hardware_step_message() if self._mode == MODE_HARDWARE else "Collecting data..."
        self._session_service.ingest_measurements(
            self._stable_measurements,
            apply_calibration=True,
            update_progress_from_completeness=False,
            step_message=step_message,
            auto_classify=True,
            auto_diagnose=auto_diagnose,
        )

        progress = self._hardware_completion_ratio() if self._mode == MODE_HARDWARE else self._current_progress()
        self._session_service.update_measurement_progress(progress, step_message)
        self.measurement_progress_changed.emit(progress, step_message)

    def _compute_bmi_if_possible(self) -> None:
        weight = safe_float(self._stable_measurements.get(METRIC_WEIGHT), 0.0)
        height = safe_float(self._stable_measurements.get(METRIC_HEIGHT), 0.0)
        if weight > 0 and height > 0:
            self._stable_measurements[METRIC_BMI] = calculate_bmi(weight, height, decimals=1)

    def _can_finalize_hardware_measurement(self, *, relaxed: bool = False) -> bool:
        stable_count = self._stable_metric_count()

        if stable_count >= self._required_metric_count():
            return True

        if not relaxed:
            return False

        if stable_count < self._minimum_metrics_to_finalize_on_timeout:
            return False

        # relaxed mode still expects weight and height so BMI can be computed,
        # plus at least a few other real metrics.
        if not metric_is_meaningful(METRIC_WEIGHT, self._stable_measurements.get(METRIC_WEIGHT)):
            return False
        if not metric_is_meaningful(METRIC_HEIGHT, self._stable_measurements.get(METRIC_HEIGHT)):
            return False

        return True

    def _finalize_measurement(
        self,
        *,
        mode: str,
        measurements: Mapping[str, Any],
        message: str,
        persist_to_db: bool,
    ) -> Dict[str, Any]:
        final_measurements = normalize_measurement_payload(measurements)
        final_measurements = self._calibration_service.apply_to_measurements(
            final_measurements,
            recompute_bmi=True,
        )

        diagnosis_payload = self._diagnosis_service.build_diagnosis(
            final_measurements,
            store_in_app_state=False,
        )

        if mode == MODE_DEMO:
            result = self._session_service.complete_demo_session_with_measurements(
                final_measurements,
                diagnosis_payload=diagnosis_payload,
                attach_default_report=False,
                attach_default_qr=False,
                persist_to_db=persist_to_db,
            )
        else:
            result = self._session_service.complete_hardware_session_with_measurements(
                final_measurements,
                diagnosis_payload=diagnosis_payload,
                report_path="",
                qr_path="",
                persist_to_db=persist_to_db,
            )

        self._stop_timers()
        self._active = False
        self._set_waiting_state("completed")

        payload = {
            "message": message,
            "session_result": result.to_dict() if hasattr(result, "to_dict") else deep_copy(result),
            "measurements": deep_copy(final_measurements),
            "diagnosis": deep_copy(diagnosis_payload),
            "snapshot": self.snapshot(),
        }

        self.measurement_completed.emit(deep_copy(payload))
        self._emit_state_changed()
        return payload

    def _fail_measurement(self, message: str) -> Dict[str, Any]:
        self._stop_timers()
        self._active = False
        self._set_waiting_state("failed")
        self._set_error(message)

        result = self._session_service.fail_session(message)

        payload = {
            "message": message,
            "session_result": result.to_dict() if hasattr(result, "to_dict") else deep_copy(result),
            "snapshot": self.snapshot(),
        }

        self.measurement_failed.emit(message)
        self._emit_state_changed()
        return payload

    # ========================================================
    # Public state accessors
    # ========================================================

    def is_active(self) -> bool:
        return self._active

    def mode(self) -> str:
        return self._mode

    def waiting_state(self) -> str:
        return self._waiting_state

    def finger_detected(self) -> bool:
        return self._finger_detected

    def raw_measurements(self) -> Dict[str, Any]:
        return deep_copy(self._raw_measurements)

    def stable_measurements(self) -> Dict[str, Any]:
        return deep_copy(self._stable_measurements)

    def snapshot(self) -> Dict[str, Any]:
        payload = SensorRunSnapshot(
            active=self._active,
            mode=self._mode,
            session_id=self._session_id(),
            started_at=self._started_at,
            progress=self._current_progress(),
            waiting_state=self._waiting_state,
            finger_detected=self._finger_detected,
            raw_measurements=deep_copy(self._raw_measurements),
            stable_measurements=deep_copy(self._stable_measurements),
            stable_metric_count=self._stable_metric_count(),
            required_metric_count=self._required_metric_count(),
            packet_count=self._packet_count,
            last_packet_at=self._last_packet_at,
            demo_elapsed_ms=self._demo_elapsed_ms,
            demo_duration_ms=self._demo_duration_ms,
            hardware_timeout_ms=self._hardware_timeout_ms,
            last_error=self._last_error,
        ).to_dict()
        return payload

    # ========================================================
    # Public measurement lifecycle
    # ========================================================

    def start_measurement(self, mode: Optional[str] = None) -> Dict[str, Any]:
        """
        Start a measurement run in demo mode or hardware mode.
        """
        if self._active:
            return self.snapshot()

        requested_mode = validate_runtime_mode(mode or self._mode_service.current_mode() or self._app_state.runtime_mode())

        self._reset_runtime_state()
        self._active = True
        self._mode = requested_mode
        self._started_at = now_iso()

        self.measurement_requested.emit(requested_mode)

        try:
            session_result = self._session_service.start_measurement(
                mode=requested_mode,
                step_message=self._mode_service.measuring_status_text(requested_mode),
            )

            session_result_payload = session_result.to_dict() if hasattr(session_result, "to_dict") else {}
            if hasattr(session_result, "success") and not session_result.success:
                self._active = False
                self._set_error(session_result.message)
                return {
                    "success": False,
                    "message": session_result.message,
                    "session_result": session_result_payload,
                    "snapshot": self.snapshot(),
                }

            if requested_mode == MODE_DEMO:
                self._start_demo_run()
            else:
                self._start_hardware_run()

            payload = {
                "success": True,
                "mode": requested_mode,
                "session_result": session_result_payload,
                "snapshot": self.snapshot(),
            }
            self.measurement_started.emit(deep_copy(payload))
            self._emit_state_changed()
            return payload

        except Exception as exc:
            log_exception(self._logger, "Failed to start sensor measurement", exc)
            self._active = False
            self._set_error(str(exc))
            self.sensor_error.emit(str(exc))
            return {
                "success": False,
                "message": str(exc),
                "snapshot": self.snapshot(),
            }

    def cancel_measurement(self, reason: str = "Measurement cancelled.") -> Dict[str, Any]:
        if not self._active:
            return self.snapshot()

        self._stop_timers()
        self._active = False
        self._set_waiting_state("cancelled")

        result = self._session_service.cancel_session()
        payload = {
            "message": reason,
            "session_result": result.to_dict() if hasattr(result, "to_dict") else deep_copy(result),
            "snapshot": self.snapshot(),
        }
        self.measurement_cancelled.emit(deep_copy(payload))
        self._emit_state_changed()
        return payload

    # ========================================================
    # Demo mode
    # ========================================================

    def _start_demo_run(self) -> None:
        self._demo_duration_ms = max(
            1000,
            safe_int(self._mode_service.measurement_duration_ms(MODE_DEMO), DEMO_MEASUREMENT_DURATION_MS),
        )
        self._demo_started_monotonic = time.monotonic()
        self._demo_elapsed_ms = 0
        self._set_waiting_state("simulating_demo_data")

        self._session_service.update_measurement_progress(0, "Collecting demo data...")
        self.measurement_progress_changed.emit(0, "Collecting demo data...")
        self._demo_tick_timer.start()

    def _on_demo_tick(self) -> None:
        if not self._active or self._mode != MODE_DEMO:
            self._demo_tick_timer.stop()
            return

        elapsed = int((time.monotonic() - self._demo_started_monotonic) * 1000)
        self._demo_elapsed_ms = max(0, elapsed)

        ratio = min(1.0, self._demo_elapsed_ms / float(max(self._demo_duration_ms, 1)))
        progress = min(99, int(round(ratio * 100)))

        if progress < 30:
            step = "Preparing demo sensors..."
        elif progress < 60:
            step = "Collecting demo data..."
        elif progress < 85:
            step = "Analyzing demo values..."
        else:
            step = "Finalizing demo results..."

        self._session_service.update_measurement_progress(progress, step)
        self.measurement_progress_changed.emit(progress, step)
        self._emit_state_changed()

        if self._demo_elapsed_ms >= self._demo_duration_ms:
            self._demo_tick_timer.stop()
            self._finalize_demo_run()

    def _weighted_demo_choice(self, normal_value: float, mild_value: float, abnormal_value: float) -> float:
        roll = random.random()
        if roll < 0.68:
            return normal_value
        if roll < 0.88:
            return mild_value
        return abnormal_value

    def _generate_demo_measurements(self) -> Dict[str, Any]:
        """
        Generate realistic-looking demo values with mostly normal outcomes.
        """
        height = safe_round(random.uniform(150.0, 180.0), decimals=1, default=165.0)

        bmi_target = self._weighted_demo_choice(
            random.uniform(20.0, 24.0),
            random.uniform(25.5, 29.0),
            random.uniform(17.0, 18.0) if random.random() < 0.5 else random.uniform(30.5, 35.0),
        )
        weight = safe_round((bmi_target * ((height / 100.0) ** 2)), decimals=1, default=65.0)

        temp = safe_round(
            self._weighted_demo_choice(
                random.uniform(36.3, 36.9),
                random.uniform(37.2, 38.0),
                random.uniform(38.4, 40.5),
            ),
            decimals=1,
            default=36.7,
        )

        spo2 = int(round(self._weighted_demo_choice(
            random.uniform(96, 99),
            random.uniform(92, 94),
            random.uniform(84, 90),
        )))

        pulse = int(round(self._weighted_demo_choice(
            random.uniform(66, 88),
            random.uniform(92, 108),
            random.uniform(48, 58) if random.random() < 0.35 else random.uniform(112, 128),
        )))

        rr = int(round(self._weighted_demo_choice(
            random.uniform(13, 18),
            random.uniform(21, 23),
            random.uniform(8, 11) if random.random() < 0.35 else random.uniform(25, 30),
        )))

        bmi = calculate_bmi(weight, height, decimals=1)

        return normalize_measurement_payload(
            {
                METRIC_WEIGHT: weight,
                METRIC_HEIGHT: height,
                METRIC_BMI: bmi,
                METRIC_TEMPERATURE: temp,
                METRIC_SPO2: spo2,
                METRIC_PULSE: pulse,
                METRIC_RR: rr,
            }
        )

    def _finalize_demo_run(self) -> Dict[str, Any]:
        measurements = self._generate_demo_measurements()
        self._raw_measurements = deep_copy(measurements)
        self._stable_measurements = deep_copy(measurements)

        self.demo_measurements_ready.emit(deep_copy(measurements))
        self.raw_measurements_changed.emit(deep_copy(self._raw_measurements))
        self.stable_measurements_changed.emit(deep_copy(self._stable_measurements))

        self._session_service.update_measurement_progress(100, "Demo measurement complete.")
        self.measurement_progress_changed.emit(100, "Demo measurement complete.")

        return self._finalize_measurement(
            mode=MODE_DEMO,
            measurements=measurements,
            message="Demo measurement completed successfully.",
            persist_to_db=self._persist_demo_sessions,
        )

    # ========================================================
    # Hardware mode
    # ========================================================

    def _start_hardware_run(self) -> None:
        if not self._connection_service.hardware_ready():
            self._active = False
            self._fail_measurement("Hardware mode selected, but no serial / ESP32 connection is ready.")
            return

        self._hardware_timeout_ms = max(
            1000,
            safe_int(
                self._settings_service_value("hardware", "hardware_measurement_failsafe_timeout_ms", HARDWARE_MEASUREMENT_FAILSAFE_TIMEOUT_MS),
                HARDWARE_MEASUREMENT_FAILSAFE_TIMEOUT_MS,
            ),
        )
        self._set_waiting_state("waiting_for_live_data")
        self._session_service.update_measurement_progress(0, "Waiting for live sensor data...")
        self.measurement_progress_changed.emit(0, "Waiting for live sensor data...")
        self._hardware_timeout_timer.start(self._hardware_timeout_ms)

        # Ask ESP32 for a measurement if supported.
        try:
            if self._serial_service is not None:
                if hasattr(self._serial_service, "request_measurement"):
                    self._serial_service.request_measurement()
                elif hasattr(self._serial_service, "send_command"):
                    self._serial_service.send_command("START_MEASUREMENT")
        except Exception as exc:
            self._logger.warning("Could not send measurement request to serial device: %s", exc)

    def _on_hardware_timeout(self) -> None:
        if not self._active or self._mode != MODE_HARDWARE:
            return

        if self._can_finalize_hardware_measurement(relaxed=True):
            self._logger.info("Hardware measurement timed out, finalizing with collected stable values.")
            self._finalize_measurement(
                mode=MODE_HARDWARE,
                measurements=self._stable_measurements,
                message="Hardware measurement finalized after timeout with collected readings.",
                persist_to_db=True,
            )
            return

        self._fail_measurement("Measurement timed out before enough sensor data was collected.")

    def _on_measurement_packet_received(self, packet: Mapping[str, Any]) -> None:
        self.hardware_packet_received.emit(deep_copy(dict(packet or {})))

        if not self._active or self._mode != MODE_HARDWARE:
            return

        measurements = packet.get("measurements", {}) if isinstance(packet, Mapping) else {}
        if not isinstance(measurements, Mapping):
            return

        self._packet_count += 1
        self._last_packet_at = now_iso()

        self._ingest_hardware_measurements(measurements)

    def _ingest_hardware_measurements(self, measurements: Mapping[str, Any]) -> None:
        updated_raw = deep_copy(self._raw_measurements)
        updated_stable = deep_copy(self._stable_measurements)

        for key, value in measurements.items():
            metric_key = safe_str(key, "").strip().lower()
            if metric_key not in {
                METRIC_WEIGHT,
                METRIC_HEIGHT,
                METRIC_TEMPERATURE,
                METRIC_SPO2,
                METRIC_PULSE,
                METRIC_RR,
                METRIC_BMI,
            }:
                continue

            numeric_value = safe_float(value, 0.0)
            if numeric_value <= 0:
                continue

            updated_raw[metric_key] = numeric_value
            if metric_key != METRIC_BMI:
                self._append_metric_sample(metric_key, numeric_value)

                if self._metric_is_stable(metric_key):
                    updated_stable[metric_key] = self._stable_metric_value(metric_key)
            else:
                updated_stable[metric_key] = safe_round(numeric_value, decimals=1, default=0.0)

        self._raw_measurements = normalize_measurement_payload(updated_raw)
        self._stable_measurements = normalize_measurement_payload(updated_stable)
        self._compute_bmi_if_possible()

        self.raw_measurements_changed.emit(deep_copy(self._raw_measurements))
        self.stable_measurements_changed.emit(deep_copy(self._stable_measurements))

        self._refresh_session_from_stable_measurements(auto_diagnose=False)

        progress = self._hardware_completion_ratio()
        step = self._build_hardware_step_message()
        self._session_service.update_measurement_progress(progress, step)
        self.measurement_progress_changed.emit(progress, step)

        self._emit_state_changed()

        if self._can_finalize_hardware_measurement(relaxed=False):
            self._finalize_measurement(
                mode=MODE_HARDWARE,
                measurements=self._stable_measurements,
                message="Hardware measurement completed successfully.",
                persist_to_db=True,
            )

    def _on_status_packet_received(self, packet: Mapping[str, Any]) -> None:
        if not isinstance(packet, Mapping):
            return

        state = safe_str(packet.get("state"), "").strip().lower()
        text = safe_str(packet.get("text"), "").strip().lower()

        if state in {"finger_detected"} or "finger detected" in text:
            self._set_finger_detected(True)
            self._set_waiting_state("collecting_live_data")

        elif state in {"finger_removed"} or "finger removed" in text:
            self._set_finger_detected(False)
            if self._active and self._mode == MODE_HARDWARE and self._stable_metric_count() == 0:
                self._set_waiting_state("waiting_for_finger")

        elif state in {"place_finger"} or "place finger" in text:
            self._set_finger_detected(False)
            self._set_waiting_state("waiting_for_finger")

        elif state in {"collecting"} or "collecting" in text:
            self._set_waiting_state("collecting_live_data")

        elif state in {"warning"}:
            self._set_waiting_state("signal_warning")

        self._emit_state_changed()

    def _on_heartbeat_received(self, heartbeat_at: str) -> None:
        if self._active and self._mode == MODE_HARDWARE:
            if self._waiting_state in {"waiting_for_live_data", "waiting_for_finger"}:
                self._set_waiting_state("device_online")

    def _on_serial_error(self, message: str) -> None:
        if self._active and self._mode == MODE_HARDWARE:
            self._set_error(message)
            self._set_waiting_state("serial_error")

    # ========================================================
    # Helpers / testing
    # ========================================================

    def simulate_hardware_packet(self, measurements: Mapping[str, Any]) -> Dict[str, Any]:
        """
        Testing helper for development without real hardware.
        """
        packet = {
            "kind": "measurement",
            "timestamp": now_iso(),
            "measurements": deep_copy(dict(measurements)),
            "raw_line": "SIMULATED_PACKET",
        }
        self._on_measurement_packet_received(packet)
        return packet

    def simulate_status_packet(self, state: str, text: str = "") -> Dict[str, Any]:
        packet = {
            "kind": "status",
            "timestamp": now_iso(),
            "state": safe_str(state, "").strip().lower(),
            "text": safe_str(text, ""),
            "raw_line": safe_str(text, state),
        }
        self._on_status_packet_received(packet)
        return packet

    def _settings_service_value(self, section: str, key: str, default: Any) -> Any:
        try:
            return self._connection_service._settings_service.get_setting(section, key, default) if False else self._mode_service._settings_service.get_setting(section, key, default)
        except Exception:
            pass
        try:
            return self._session_service._mode_service._settings_service.get_setting(section, key, default) if False else default
        except Exception:
            return default

    # ========================================================
    # Mode integration
    # ========================================================

    def on_mode_changed(self, mode: str) -> Dict[str, Any]:
        normalized = validate_runtime_mode(mode or self._mode)
        if self._active and normalized != self._mode:
            self.cancel_measurement("Measurement cancelled because the runtime mode changed.")
        self._mode = normalized
        return self.snapshot()

    # ========================================================
    # Diagnostics
    # ========================================================

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "snapshot": self.snapshot(),
            "raw_measurements": self.raw_measurements(),
            "stable_measurements": self.stable_measurements(),
            "metric_buffers": {key: len(values) for key, values in self._metric_buffers.items()},
        }


# ============================================================
# Singleton accessor
# ============================================================

_SENSOR_SERVICE_SINGLETON: Optional[SensorService] = None


def get_sensor_service(
    app_state: Optional[AppState] = None,
    mode_service: Optional[ModeService] = None,
    calibration_service: Optional[CalibrationService] = None,
    session_service: Optional[SessionService] = None,
    serial_service: Optional[SerialService] = None,
    connection_service: Optional[ConnectionService] = None,
    diagnosis_service: Optional[DiagnosisService] = None,
) -> SensorService:
    global _SENSOR_SERVICE_SINGLETON
    if _SENSOR_SERVICE_SINGLETON is None:
        _SENSOR_SERVICE_SINGLETON = SensorService(
            app_state=app_state,
            mode_service=mode_service,
            calibration_service=calibration_service,
            session_service=session_service,
            serial_service=serial_service,
            connection_service=connection_service,
            diagnosis_service=diagnosis_service,
        )
    else:
        if serial_service is not None:
            _SENSOR_SERVICE_SINGLETON.set_serial_service(serial_service)
        if connection_service is not None:
            _SENSOR_SERVICE_SINGLETON.set_connection_service(connection_service)
        if diagnosis_service is not None:
            _SENSOR_SERVICE_SINGLETON.set_diagnosis_service(diagnosis_service)
    return _SENSOR_SERVICE_SINGLETON
