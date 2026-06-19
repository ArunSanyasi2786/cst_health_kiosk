"""
services/session_service.py

Session lifecycle management service for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the main backend for user measurement sessions
- It coordinates the active session across:
    - AppState
    - ModeService
    - CalibrationService
    - ThresholdService
    - DatabaseService
- It provides one consistent flow for both demo mode and hardware mode
- It manages:
    - session creation
    - measurement start
    - measurement updates
    - progress / step messages
    - session completion
    - session cancellation
    - session failure
    - report / QR path attachment
    - persistence to database
- It prepares clean data for later DiagnosisService, QRService, ReportService, and PublishService

Linked files:
- core/app_state.py
- core/constants.py
- core/utils.py
- services/mode_service.py
- services/calibration_service.py
- services/threshold_service.py
- services/database_service.py

Design goals:
- keep the same UI flow in demo mode and hardware mode
- only the measurement source differs
- strongly typed and easy to call from screens/services
- safe to use before all later services are fully implemented
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from config import DEFAULT_RUNTIME_MODE
from core.app_state import AppState, get_app_state
from core.constants import (
    EMPTY_DIAGNOSIS_PAYLOAD,
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
    SESSION_STATUS_CANCELLED,
    SESSION_STATUS_COMPLETE,
    SESSION_STATUS_ERROR,
    SESSION_STATUS_IDLE,
    SESSION_STATUS_MEASURING,
)
from core.logger import get_logger, log_exception
from core.utils import (
    build_qr_path,
    build_report_path,
    deep_copy,
    format_metric_value,
    normalize_measurement_payload,
    safe_float,
    safe_int,
    safe_str,
    validate_runtime_mode,
)
from services.calibration_service import CalibrationService, get_calibration_service
from services.database_service import DatabaseService, get_database_service
from services.mode_service import ModeService, get_mode_service
from services.threshold_service import ThresholdService, get_threshold_service

logger = get_logger(__name__)


# ============================================================
# Dataclasses
# ============================================================

@dataclass
class SessionResult:
    """
    Standard return object for session operations.
    """
    success: bool
    session_id: str
    status: str
    message: str
    payload: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "session_id": self.session_id,
            "status": self.status,
            "message": self.message,
            "payload": deep_copy(self.payload),
        }


# ============================================================
# Session service
# ============================================================

class SessionService(QObject):
    """
    Central session lifecycle manager.

    Main responsibilities:
    - create and reset sessions
    - start measuring flows
    - ingest and normalize measurements
    - apply calibration where appropriate
    - classify measurements with ThresholdService
    - save session state to database
    - provide helpers for results / QR / report generation pipeline
    """

    session_created = pyqtSignal(str)
    session_started = pyqtSignal(str)
    session_updated = pyqtSignal(dict)
    session_completed = pyqtSignal(dict)
    session_cancelled = pyqtSignal(str)
    session_failed = pyqtSignal(str, str)
    session_saved = pyqtSignal(str)
    session_loaded = pyqtSignal(dict)
    measurement_ingested = pyqtSignal(dict)
    session_error = pyqtSignal(str)

    def __init__(
        self,
        app_state: Optional[AppState] = None,
        mode_service: Optional[ModeService] = None,
        calibration_service: Optional[CalibrationService] = None,
        threshold_service: Optional[ThresholdService] = None,
        database_service: Optional[DatabaseService] = None,
        diagnosis_service: Optional[object] = None,
    ) -> None:
        super().__init__()

        self._logger = logger.bind(component="SessionService")
        self._app_state: AppState = app_state or get_app_state()
        self._mode_service: ModeService = mode_service or get_mode_service()
        self._calibration_service: CalibrationService = calibration_service or get_calibration_service()
        self._threshold_service: ThresholdService = threshold_service or get_threshold_service()
        self._database_service: DatabaseService = database_service or get_database_service()
        self._diagnosis_service: Optional[object] = diagnosis_service

    # ========================================================
    # Dependency setters for later services
    # ========================================================

    def set_diagnosis_service(self, diagnosis_service: object) -> None:
        self._diagnosis_service = diagnosis_service

    # ========================================================
    # Public state accessors
    # ========================================================

    def current_session_id(self) -> str:
        snapshot = self._app_state.session_snapshot()
        return safe_str(snapshot.get("session_id"), "")

    def current_session_status(self) -> str:
        snapshot = self._app_state.session_snapshot()
        return safe_str(snapshot.get("status"), SESSION_STATUS_IDLE)

    def has_active_session(self) -> bool:
        return bool(self.current_session_id())

    def is_measuring(self) -> bool:
        return self.current_session_status() == SESSION_STATUS_MEASURING

    def is_complete(self) -> bool:
        return self.current_session_status() == SESSION_STATUS_COMPLETE

    def is_cancelled(self) -> bool:
        return self.current_session_status() == SESSION_STATUS_CANCELLED

    def is_failed(self) -> bool:
        return self.current_session_status() == SESSION_STATUS_ERROR

    def snapshot(self) -> Dict[str, Any]:
        return self._app_state.session_snapshot()

    # ========================================================
    # Session creation / reset
    # ========================================================

    def create_session(self, mode: Optional[str] = None) -> str:
        """
        Create a fresh session in AppState and return its session_id.
        """
        runtime_mode = validate_runtime_mode(mode or self._mode_service.current_mode())
        session_id = self._app_state.create_new_session(runtime_mode)

        self._logger.info(
            "Session created.",
            extra={
                "session_id": session_id,
                "mode": runtime_mode,
                "route": self._app_state.current_route(),
            },
        )

        self.session_created.emit(session_id)
        self.session_updated.emit(self._app_state.session_snapshot())
        return session_id

    def reset_session(self, mode: Optional[str] = None) -> Dict[str, Any]:
        """
        Reset the in-memory session but keep the selected mode.
        """
        runtime_mode = validate_runtime_mode(mode or self._mode_service.current_mode())
        self._app_state.reset_session(runtime_mode)

        self._logger.info(
            "Session reset.",
            extra={
                "mode": runtime_mode,
                "route": self._app_state.current_route(),
            },
        )
        snapshot = self._app_state.session_snapshot()
        self.session_updated.emit(snapshot)
        return snapshot

    # ========================================================
    # Measurement lifecycle
    # ========================================================

    def start_measurement(
        self,
        mode: Optional[str] = None,
        step_message: Optional[str] = None,
    ) -> SessionResult:
        """
        Start a new measurement session.

        Demo mode:
        - creates session
        - marks measuring
        - ready for simulated measurement duration

        Hardware mode:
        - creates session
        - marks measuring
        - waits for real data through SensorService / SerialService later
        """
        runtime_mode = validate_runtime_mode(mode or self._mode_service.current_mode())

        if runtime_mode == MODE_HARDWARE and not self._mode_service.can_measure_now(MODE_HARDWARE):
            message = "Hardware mode selected but ESP32 / serial connection is not ready."
            self._logger.warning(message, extra={"mode": runtime_mode})
            return SessionResult(
                success=False,
                session_id="",
                status=SESSION_STATUS_IDLE,
                message=message,
                payload=self._mode_service.readiness_snapshot(MODE_HARDWARE),
            )

        start_message = step_message or self._mode_service.measuring_status_text(runtime_mode)
        session_id = self._app_state.begin_measurement_flow(mode=runtime_mode, step_message=start_message)

        self._logger.info(
            "Measurement started.",
            extra={
                "session_id": session_id,
                "mode": runtime_mode,
                "route": self._app_state.current_route(),
            },
        )

        snapshot = self._app_state.session_snapshot()
        self.session_started.emit(session_id)
        self.session_updated.emit(snapshot)

        return SessionResult(
            success=True,
            session_id=session_id,
            status=SESSION_STATUS_MEASURING,
            message="Measurement session started successfully.",
            payload=snapshot,
        )

    def update_measurement_progress(self, progress: Any, step_message: Optional[str] = None) -> Dict[str, Any]:
        progress_value = safe_int(progress, 0)
        self._app_state.set_measurement_progress(progress_value)

        if step_message is not None:
            self._app_state.set_measurement_step(step_message)

        snapshot = self._app_state.session_snapshot()
        self.session_updated.emit(snapshot)
        return snapshot

    def set_measurement_step(self, message: str) -> Dict[str, Any]:
        self._app_state.set_measurement_step(message)
        snapshot = self._app_state.session_snapshot()
        self.session_updated.emit(snapshot)
        return snapshot

    # ========================================================
    # Measurement ingestion / normalization
    # ========================================================

    def ingest_measurements(
        self,
        measurements: Mapping[str, Any],
        *,
        apply_calibration: bool = True,
        update_progress_from_completeness: bool = True,
        step_message: Optional[str] = None,
        auto_classify: bool = True,
        auto_diagnose: bool = False,
    ) -> Dict[str, Any]:
        """
        Ingest new measurement values into the active session.

        Notes:
        - can be used incrementally in hardware mode
        - can be used once with a full payload in demo mode
        - applies calibration if requested
        - classifies detailed metrics if requested
        - optionally delegates to a later DiagnosisService if attached
        """
        self._app_state.ensure_active_session()

        normalized = normalize_measurement_payload(measurements)

        if apply_calibration:
            normalized = self._calibration_service.apply_to_measurements(
                normalized,
                recompute_bmi=True,
            )

        updated = self._app_state.update_measurements(
            normalized,
            apply_calibration=False,
            auto_fill_bmi=True,
            emit_signals=True,
        )

        if step_message is not None:
            self._app_state.set_measurement_step(step_message)

        completion_ratio = self._app_state.compute_measurement_completion_ratio(updated)

        if update_progress_from_completeness:
            self._app_state.set_measurement_progress(int(round(completion_ratio)))

        classifications: Dict[str, Any] = {}
        if auto_classify:
            classifications = self._threshold_service.classify_measurements(updated)

        if auto_diagnose:
            self._try_run_diagnosis_service(updated, classifications)

        snapshot = self._app_state.session_snapshot()
        payload = {
            "session": snapshot,
            "measurements": deep_copy(updated),
            "classifications": deep_copy(classifications),
            "completion_ratio": completion_ratio,
        }

        self._logger.info(
            "Measurements ingested.",
            extra={
                "session_id": snapshot.get("session_id", "-"),
                "mode": snapshot.get("mode", "-"),
                "route": self._app_state.current_route(),
            },
        )

        self.measurement_ingested.emit(payload)
        self.session_updated.emit(snapshot)
        return payload

    def _try_run_diagnosis_service(
        self,
        measurements: Mapping[str, Any],
        classifications: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """
        Best-effort diagnosis integration without hard dependency.
        """
        if self._diagnosis_service is None:
            return

        try:
            builder = getattr(self._diagnosis_service, "build_diagnosis", None)
            if callable(builder):
                diagnosis_payload = builder(measurements, classifications=classifications or {})
                if isinstance(diagnosis_payload, Mapping):
                    self._app_state.set_diagnosis(diagnosis_payload)
                    return
        except Exception as exc:
            self._logger.warning("Diagnosis service build_diagnosis failed: %s", exc)

        try:
            builder = getattr(self._diagnosis_service, "generate_diagnosis", None)
            if callable(builder):
                diagnosis_payload = builder(measurements)
                if isinstance(diagnosis_payload, Mapping):
                    self._app_state.set_diagnosis(diagnosis_payload)
        except Exception as exc:
            self._logger.warning("Diagnosis service generate_diagnosis failed: %s", exc)

    # ========================================================
    # Completion / cancellation / failure
    # ========================================================

    def complete_session(
        self,
        *,
        measurements: Optional[Mapping[str, Any]] = None,
        diagnosis_payload: Optional[Mapping[str, Any]] = None,
        report_path: str = "",
        qr_path: str = "",
        apply_calibration: bool = True,
        persist_to_db: bool = True,
        mark_persisted: bool = True,
        step_message: str = "Measurement complete.",
    ) -> SessionResult:
        """
        Complete the current session.

        Typical usage:
        - demo mode: call after random values are generated
        - hardware mode: call after stable sensor readings are finished
        """
        if measurements is not None:
            self.ingest_measurements(
                measurements,
                apply_calibration=apply_calibration,
                update_progress_from_completeness=True,
                step_message=step_message,
                auto_classify=True,
                auto_diagnose=False,
            )

        if diagnosis_payload:
            self._app_state.set_diagnosis(diagnosis_payload)

        if report_path:
            self._app_state.set_report_path(report_path)

        if qr_path:
            self._app_state.set_qr_path(qr_path)

        self._app_state.mark_session_complete(
            report_path=safe_str(report_path, ""),
            qr_path=safe_str(qr_path, ""),
        )

        if persist_to_db:
            try:
                saved_session_id = self.save_current_session(mark_persisted=mark_persisted)
                self._logger.info("Completed session persisted as %s", saved_session_id)
            except Exception as exc:
                log_exception(self._logger, "Failed to save completed session", exc)

        snapshot = self._app_state.session_snapshot()
        self.session_completed.emit(snapshot)
        self.session_updated.emit(snapshot)

        return SessionResult(
            success=True,
            session_id=snapshot.get("session_id", ""),
            status=SESSION_STATUS_COMPLETE,
            message="Session completed successfully.",
            payload=snapshot,
        )

    def cancel_session(self) -> SessionResult:
        """
        Cancel the active measuring flow.
        """
        session_id = self.current_session_id()
        self._app_state.cancel_measurement_flow()

        snapshot = self._app_state.session_snapshot()
        self._logger.info(
            "Session cancelled.",
            extra={
                "session_id": session_id or "-",
                "mode": snapshot.get("mode", "-"),
            },
        )

        self.session_cancelled.emit(session_id)
        self.session_updated.emit(snapshot)

        return SessionResult(
            success=True,
            session_id=session_id,
            status=SESSION_STATUS_CANCELLED,
            message="Session cancelled.",
            payload=snapshot,
        )

    def fail_session(self, message: str = "Session failed.") -> SessionResult:
        """
        Mark the active session as failed.
        """
        session_id = self.current_session_id()
        self._app_state.mark_measurement_error(message)

        snapshot = self._app_state.session_snapshot()
        self._logger.warning(
            "Session failed.",
            extra={
                "session_id": session_id or "-",
                "mode": snapshot.get("mode", "-"),
            },
        )

        self.session_failed.emit(session_id, message)
        self.session_updated.emit(snapshot)

        return SessionResult(
            success=False,
            session_id=session_id,
            status=SESSION_STATUS_ERROR,
            message=message,
            payload=snapshot,
        )

    # ========================================================
    # Report / QR attachment helpers
    # ========================================================

    def assign_default_report_path(self, extension: str = "pdf") -> str:
        session_id = self._app_state.ensure_active_session()
        path = build_report_path(session_id, extension=extension)
        self._app_state.set_report_path(str(path))
        self.session_updated.emit(self._app_state.session_snapshot())
        return str(path)

    def assign_default_qr_path(self, extension: str = "png") -> str:
        session_id = self._app_state.ensure_active_session()
        path = build_qr_path(session_id, extension=extension)
        self._app_state.set_qr_path(str(path))
        self.session_updated.emit(self._app_state.session_snapshot())
        return str(path)

    def attach_report_path(self, report_path: str) -> Dict[str, Any]:
        self._app_state.set_report_path(report_path)
        snapshot = self._app_state.session_snapshot()
        self.session_updated.emit(snapshot)
        return snapshot

    def attach_qr_path(self, qr_path: str) -> Dict[str, Any]:
        self._app_state.set_qr_path(qr_path)
        snapshot = self._app_state.session_snapshot()
        self.session_updated.emit(snapshot)
        return snapshot

    # ========================================================
    # Persistence helpers
    # ========================================================

    def build_persistence_record(self) -> Dict[str, Any]:
        """
        Export the current AppState session as a DB-ready record.
        """
        return self._app_state.export_current_session_record()

    def save_current_session(self, *, mark_persisted: bool = True) -> str:
        """
        Save the current active session to the database.
        """
        record = self.build_persistence_record()
        diagnosis = self._app_state.current_diagnosis()

        session_id = self._database_service.save_session(
            session_record=record,
            diagnosis_payload=diagnosis,
        )

        if mark_persisted:
            self._app_state.set_session_persisted(True)
            self._database_service.mark_session_persisted(session_id, True)

        self._logger.info(
            "Current session saved.",
            extra={
                "session_id": session_id,
                "mode": record.get("mode", "-"),
            },
        )

        self.session_saved.emit(session_id)
        self.session_updated.emit(self._app_state.session_snapshot())
        return session_id

    def load_session_into_app_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Load a saved session from DB back into AppState.
        Useful for admin review or future replay flows.
        """
        record = self._database_service.get_session_by_session_id(session_id)
        if not record:
            return None

        # Reset app state session and rehydrate
        mode = safe_str(record.get("mode"), DEFAULT_RUNTIME_MODE)
        self._app_state.reset_session(mode=mode)

        self._app_state.ensure_active_session()
        # Replace session core fields by direct structured flow
        self._app_state.session.session_id = safe_str(record.get("session_id"), "")
        self._app_state.session.mode = mode
        self._app_state.session.status = safe_str(record.get("status"), SESSION_STATUS_IDLE)
        self._app_state.session.started_at = safe_str(record.get("started_at"), "")
        self._app_state.session.measuring_started_at = safe_str(record.get("measuring_started_at"), "")
        self._app_state.session.completed_at = safe_str(record.get("completed_at"), "")
        self._app_state.session.cancelled_at = safe_str(record.get("cancelled_at"), "")
        self._app_state.session.report_path = safe_str(record.get("report_path"), "")
        self._app_state.session.qr_path = safe_str(record.get("qr_path"), "")
        self._app_state.session.persisted = bool(record.get("persisted", False))
        self._app_state.session.measurement_progress = safe_int(record.get("measurement_progress"), 0)
        self._app_state.session.measurement_step_message = safe_str(record.get("measurement_step_message"), "")
        self._app_state.session.measurement_complete_ratio = safe_float(record.get("measurement_complete_ratio"), 0.0)
        self._app_state.session.source_label = safe_str(record.get("source_label"), "")
        self._app_state.session.measurements = normalize_measurement_payload(record.get("measurements", {}))
        self._app_state.session.diagnosis = deep_copy(record.get("diagnosis", {})) or dict(EMPTY_DIAGNOSIS_PAYLOAD)

        snapshot = self._app_state.session_snapshot()
        self.session_loaded.emit(snapshot)
        self.session_updated.emit(snapshot)

        self._logger.info(
            "Session loaded into AppState.",
            extra={
                "session_id": session_id,
                "mode": mode,
            },
        )
        return snapshot

    # ========================================================
    # Convenience composite flows
    # ========================================================

    def start_demo_session(self) -> SessionResult:
        return self.start_measurement(mode=MODE_DEMO, step_message="Collecting demo data...")

    def start_hardware_session(self) -> SessionResult:
        return self.start_measurement(mode=MODE_HARDWARE, step_message="Collecting live sensor data...")

    def complete_demo_session_with_measurements(
        self,
        measurements: Mapping[str, Any],
        *,
        diagnosis_payload: Optional[Mapping[str, Any]] = None,
        attach_default_report: bool = False,
        attach_default_qr: bool = False,
        persist_to_db: bool = True,
    ) -> SessionResult:
        report_path = self.assign_default_report_path() if attach_default_report else ""
        qr_path = self.assign_default_qr_path() if attach_default_qr else ""

        return self.complete_session(
            measurements=measurements,
            diagnosis_payload=diagnosis_payload,
            report_path=report_path,
            qr_path=qr_path,
            apply_calibration=True,
            persist_to_db=persist_to_db,
            mark_persisted=persist_to_db,
            step_message="Demo measurement complete.",
        )

    def complete_hardware_session_with_measurements(
        self,
        measurements: Mapping[str, Any],
        *,
        diagnosis_payload: Optional[Mapping[str, Any]] = None,
        report_path: str = "",
        qr_path: str = "",
        persist_to_db: bool = True,
    ) -> SessionResult:
        return self.complete_session(
            measurements=measurements,
            diagnosis_payload=diagnosis_payload,
            report_path=report_path,
            qr_path=qr_path,
            apply_calibration=True,
            persist_to_db=persist_to_db,
            mark_persisted=persist_to_db,
            step_message="Hardware measurement complete.",
        )

    # ========================================================
    # Session summary helpers
    # ========================================================

    def measurement_summary(self) -> Dict[str, Any]:
        measurements = self._app_state.current_measurements()
        return {
            "weight": format_metric_value(METRIC_WEIGHT, measurements.get(METRIC_WEIGHT)),
            "height": format_metric_value(METRIC_HEIGHT, measurements.get(METRIC_HEIGHT)),
            "bmi": format_metric_value(METRIC_BMI, measurements.get(METRIC_BMI)),
            "temperature": format_metric_value(METRIC_TEMPERATURE, measurements.get(METRIC_TEMPERATURE)),
            "spo2": format_metric_value(METRIC_SPO2, measurements.get(METRIC_SPO2)),
            "pulse_rate": format_metric_value(METRIC_PULSE, measurements.get(METRIC_PULSE)),
            "respiratory_rate": format_metric_value(METRIC_RR, measurements.get(METRIC_RR)),
        }

    def classifications_summary(self) -> Dict[str, Any]:
        measurements = self._app_state.current_measurements()
        return self._threshold_service.classify_measurements(measurements)

    # ========================================================
    # Diagnostics
    # ========================================================

    def diagnostics(self) -> Dict[str, Any]:
        session = self._app_state.session_snapshot()
        return {
            "session_id": session.get("session_id", ""),
            "status": session.get("status", SESSION_STATUS_IDLE),
            "mode": session.get("mode", DEFAULT_RUNTIME_MODE),
            "persisted": bool(session.get("persisted", False)),
            "measurement_progress": session.get("measurement_progress", 0),
            "measurement_complete_ratio": session.get("measurement_complete_ratio", 0.0),
            "has_report": bool(session.get("report_path", "")),
            "has_qr": bool(session.get("qr_path", "")),
            "can_measure_now": self._mode_service.can_measure_now(session.get("mode", DEFAULT_RUNTIME_MODE)),
        }


# ============================================================
# Singleton accessor
# ============================================================

_SESSION_SERVICE_SINGLETON: Optional[SessionService] = None


def get_session_service(
    app_state: Optional[AppState] = None,
    mode_service: Optional[ModeService] = None,
    calibration_service: Optional[CalibrationService] = None,
    threshold_service: Optional[ThresholdService] = None,
    database_service: Optional[DatabaseService] = None,
    diagnosis_service: Optional[object] = None,
) -> SessionService:
    global _SESSION_SERVICE_SINGLETON
    if _SESSION_SERVICE_SINGLETON is None:
        _SESSION_SERVICE_SINGLETON = SessionService(
            app_state=app_state,
            mode_service=mode_service,
            calibration_service=calibration_service,
            threshold_service=threshold_service,
            database_service=database_service,
            diagnosis_service=diagnosis_service,
        )
    else:
        if diagnosis_service is not None:
            _SESSION_SERVICE_SINGLETON.set_diagnosis_service(diagnosis_service)
    return _SESSION_SERVICE_SINGLETON