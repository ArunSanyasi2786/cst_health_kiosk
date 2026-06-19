"""
services/calibration_service.py

Persistent calibration management service for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the main backend for the Calibration screen
- It reads/writes the JSON calibration file under data/config/calibration.json
- It keeps AppState and on-disk calibration synchronized
- It records calibration audit entries through DatabaseService
- It applies sensor offsets to both demo-mode and hardware-mode measurements
- It supports manual calibration, reference-based calibration, per-sensor update frequency,
  and reset-to-default flows

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
- keeps every sensor definition consistent
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from config import (
    CALIBRATION_FILE,
    DEFAULT_CALIBRATION,
    read_calibration,
    write_calibration,
)
from core.app_state import AppState, get_app_state
from core.constants import (
    CALIBRATABLE_SENSOR_KEYS,
    METRIC_BMI,
    METRIC_DECIMALS,
    METRIC_HEIGHT,
    METRIC_PULSE,
    METRIC_RR,
    METRIC_SPO2,
    METRIC_TEMPERATURE,
    METRIC_WEIGHT,
)
from core.logger import get_logger, log_exception
from core.utils import (
    apply_offset,
    calculate_bmi,
    deep_copy,
    deep_merge_dicts,
    normalize_measurement_payload,
    safe_float,
    safe_int,
    safe_round,
    safe_str,
    write_json_file,
)
from services.database_service import DatabaseService, get_database_service

logger = get_logger(__name__)


# ============================================================
# Dataclasses
# ============================================================

@dataclass
class CalibrationValidationResult:
    """
    Validation result returned by normalize helpers.
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
# Calibration service
# ============================================================

class CalibrationService(QObject):
    """
    Central calibration manager for the kiosk.

    Main responsibilities:
    - load calibration JSON
    - normalize and validate sensor calibration payloads
    - save calibration JSON
    - update AppState immediately
    - save calibration audit logs
    - apply offsets to individual values and measurement payloads
    - support manual and reference-based calibration
    """

    calibration_loaded = pyqtSignal(dict)
    calibration_saved = pyqtSignal(dict)
    calibration_changed = pyqtSignal(dict)
    sensor_calibration_changed = pyqtSignal(str, dict)
    calibration_error = pyqtSignal(str)
    calibration_reset = pyqtSignal(dict)
    calibration_applied = pyqtSignal(dict)

    def __init__(
        self,
        app_state: Optional[AppState] = None,
        database_service: Optional[DatabaseService] = None,
    ) -> None:
        super().__init__()

        self._logger = logger.bind(component="CalibrationService")
        self._app_state: AppState = app_state or get_app_state()
        self._database_service: DatabaseService = database_service or get_database_service()

        self._calibration: Dict[str, Any] = {}
        self._load_into_memory()

    # ========================================================
    # Internal normalization helpers
    # ========================================================

    def _default_sensor_payload(self, sensor_key: str) -> Dict[str, Any]:
        default_payload = DEFAULT_CALIBRATION.get(sensor_key, {})
        return deep_copy(default_payload if isinstance(default_payload, dict) else {})

    def _default_decimals_for_sensor(self, sensor_key: str) -> int:
        return int(METRIC_DECIMALS.get(sensor_key, 1))

    def _normalize_unit(self, value: Any, fallback: str = "") -> str:
        return safe_str(value, fallback).strip()

    def _normalize_label(self, value: Any, fallback: str) -> str:
        cleaned = safe_str(value, fallback).strip()
        return cleaned or fallback

    def _normalize_offset(self, sensor_key: str, value: Any) -> float:
        decimals = self._default_decimals_for_sensor(sensor_key)
        return safe_round(value, decimals=decimals, default=0.0)

    def _normalize_manual_offset_options(self, sensor_key: str, value: Any) -> list[float]:
        decimals = self._default_decimals_for_sensor(sensor_key)
        default_payload = self._default_sensor_payload(sensor_key)
        default_options = default_payload.get("manual_offset_options", [0.0])

        if not isinstance(value, list):
            value = default_options

        normalized = []
        for item in value:
            normalized.append(safe_round(item, decimals=decimals, default=0.0))

        # preserve order and remove exact duplicates
        unique: list[float] = []
        seen = set()
        for item in normalized:
            if item not in seen:
                seen.add(item)
                unique.append(item)

        return unique if unique else [0.0]

    def _normalize_range_value(self, sensor_key: str, value: Any, fallback: float) -> float:
        decimals = self._default_decimals_for_sensor(sensor_key)
        return safe_round(value, decimals=decimals, default=fallback)

    def _normalize_update_frequency_seconds(self, value: Any, fallback: int = 5) -> int:
        seconds = safe_int(value, default=fallback)
        if seconds < 1:
            seconds = 1
        if seconds > 120:
            seconds = 120
        return seconds

    def _normalize_sensor_calibration_payload(
        self,
        sensor_key: str,
        payload: Mapping[str, Any],
    ) -> CalibrationValidationResult:
        """
        Normalize one sensor calibration block.
        """
        base = self._default_sensor_payload(sensor_key)
        merged = deep_merge_dicts(base, dict(payload or {}))
        warnings: list[str] = []

        label = self._normalize_label(merged.get("label"), base.get("label", sensor_key.replace("_", " ").title()))
        unit = self._normalize_unit(merged.get("unit"), base.get("unit", ""))

        offset = self._normalize_offset(sensor_key, merged.get("offset", 0.0))
        calibration_min = self._normalize_range_value(sensor_key, merged.get("calibration_min"), base.get("calibration_min", 0.0))
        calibration_mid = self._normalize_range_value(sensor_key, merged.get("calibration_mid"), base.get("calibration_mid", 0.0))
        calibration_max = self._normalize_range_value(sensor_key, merged.get("calibration_max"), base.get("calibration_max", 0.0))
        manual_offset_options = self._normalize_manual_offset_options(sensor_key, merged.get("manual_offset_options", []))
        update_frequency_seconds = self._normalize_update_frequency_seconds(
            merged.get("update_frequency_seconds"),
            fallback=safe_int(base.get("update_frequency_seconds"), 5),
        )

        if calibration_min > calibration_mid:
            calibration_mid = calibration_min
            warnings.append(f"{sensor_key}: calibration_mid was below calibration_min and was adjusted.")

        if calibration_mid > calibration_max:
            calibration_mid = calibration_max
            warnings.append(f"{sensor_key}: calibration_mid was above calibration_max and was adjusted.")

        if calibration_min > calibration_max:
            calibration_min, calibration_max = calibration_max, calibration_min
            warnings.append(f"{sensor_key}: calibration_min and calibration_max were swapped.")

        normalized = {
            "label": label,
            "unit": unit,
            "offset": offset,
            "manual_offset_options": manual_offset_options,
            "calibration_min": calibration_min,
            "calibration_mid": calibration_mid,
            "calibration_max": calibration_max,
            "update_frequency_seconds": update_frequency_seconds,
        }

        return CalibrationValidationResult(
            is_valid=True,
            normalized=normalized,
            warnings=warnings,
        )

    def _normalize_calibration_payload(self, payload: Mapping[str, Any]) -> CalibrationValidationResult:
        """
        Normalize a full calibration payload.
        Ensures every supported sensor key exists.
        """
        warnings: list[str] = []
        normalized: Dict[str, Any] = {}

        merged = deep_merge_dicts(DEFAULT_CALIBRATION, dict(payload or {}))

        for sensor_key in CALIBRATABLE_SENSOR_KEYS:
            sensor_payload = merged.get(sensor_key, {})
            if not isinstance(sensor_payload, Mapping):
                sensor_payload = {}
                warnings.append(f"{sensor_key}: invalid calibration block replaced with defaults.")

            result = self._normalize_sensor_calibration_payload(sensor_key, sensor_payload)
            normalized[sensor_key] = result.normalized
            warnings.extend(result.warnings)

        return CalibrationValidationResult(
            is_valid=True,
            normalized=normalized,
            warnings=warnings,
        )

    def _load_into_memory(self) -> None:
        """
        Load calibration from disk, normalize it, write back if needed,
        and synchronize AppState.
        """
        raw = read_calibration()
        validation = self._normalize_calibration_payload(raw)
        self._calibration = validation.normalized

        try:
            write_calibration(self._calibration)
        except Exception as exc:
            log_exception(self._logger, "Failed to write normalized calibration during load", exc)

        self._apply_to_app_state()
        self._logger.info("Calibration loaded into memory.")
        self.calibration_loaded.emit(self.snapshot())

    def _apply_to_app_state(self) -> None:
        """
        Push all calibration values into AppState so later services/screens see the same state.
        """
        try:
            for sensor_key, sensor_payload in self._calibration.items():
                self._app_state.update_calibration_for_sensor(sensor_key, sensor_payload)
        except Exception as exc:
            log_exception(self._logger, "Failed to apply calibration to AppState", exc)
            self.calibration_error.emit(str(exc))

    def _audit_change(
        self,
        *,
        sensor_key: str,
        before_payload: Mapping[str, Any],
        after_payload: Mapping[str, Any],
        note: str = "",
    ) -> None:
        try:
            self._database_service.save_calibration_audit(
                actor="admin",
                sensor_key=sensor_key,
                before_payload=before_payload,
                after_payload=after_payload,
                note=note,
            )
        except Exception as exc:
            # audit failure should not stop the actual calibration save
            log_exception(self._logger, "Failed to save calibration audit", exc)

    # ========================================================
    # Public read helpers
    # ========================================================

    def snapshot(self) -> Dict[str, Any]:
        return deep_copy(self._calibration)

    def get_calibration(self) -> Dict[str, Any]:
        return self.snapshot()

    def get_sensor_calibration(self, sensor_key: str) -> Dict[str, Any]:
        sensor_payload = self._calibration.get(sensor_key, {})
        return deep_copy(sensor_payload if isinstance(sensor_payload, dict) else {})

    def get_sensor_offset(self, sensor_key: str) -> float:
        return safe_float(self.get_sensor_calibration(sensor_key).get("offset"), 0.0)

    def get_sensor_update_frequency_seconds(self, sensor_key: str) -> int:
        sensor = self.get_sensor_calibration(sensor_key)
        return self._normalize_update_frequency_seconds(sensor.get("update_frequency_seconds", 5), fallback=5)

    def reload_from_disk(self) -> Dict[str, Any]:
        self._load_into_memory()
        return self.snapshot()

    def validate_payload(self, payload: Mapping[str, Any]) -> CalibrationValidationResult:
        return self._normalize_calibration_payload(payload)

    def validate_sensor_payload(self, sensor_key: str, payload: Mapping[str, Any]) -> CalibrationValidationResult:
        return self._normalize_sensor_calibration_payload(sensor_key, payload)

    # ========================================================
    # Public write helpers
    # ========================================================

    def save_all(self, payload: Mapping[str, Any], note: str = "Bulk calibration update") -> Dict[str, Any]:
        """
        Replace full calibration payload with a normalized version.
        """
        before = self.snapshot()
        validation = self._normalize_calibration_payload(payload)
        self._calibration = validation.normalized

        try:
            write_calibration(self._calibration)
            self._apply_to_app_state()

            for sensor_key in self._calibration.keys():
                self._audit_change(
                    sensor_key=sensor_key,
                    before_payload=before.get(sensor_key, {}),
                    after_payload=self._calibration.get(sensor_key, {}),
                    note=note,
                )

            self._logger.info("Calibration saved via bulk update.")
            snapshot = self.snapshot()
            self.calibration_saved.emit(snapshot)
            self.calibration_changed.emit(snapshot)
            return snapshot

        except Exception as exc:
            log_exception(self._logger, "Failed to save full calibration payload", exc)
            self.calibration_error.emit(str(exc))
            raise

    def update_calibration(self, patch: Mapping[str, Any], note: str = "Calibration patch update") -> Dict[str, Any]:
        """
        Merge a partial patch into existing calibration, normalize, save, and sync.
        """
        before = self.snapshot()
        merged = deep_merge_dicts(self._calibration, dict(patch or {}))
        validation = self._normalize_calibration_payload(merged)
        self._calibration = validation.normalized

        try:
            write_calibration(self._calibration)
            self._apply_to_app_state()

            for sensor_key in patch.keys():
                self._audit_change(
                    sensor_key=sensor_key,
                    before_payload=before.get(sensor_key, {}),
                    after_payload=self._calibration.get(sensor_key, {}),
                    note=note,
                )

            self._logger.info("Calibration updated via patch.")
            snapshot = self.snapshot()
            self.calibration_saved.emit(snapshot)
            self.calibration_changed.emit(snapshot)
            return snapshot

        except Exception as exc:
            log_exception(self._logger, "Failed to update calibration", exc)
            self.calibration_error.emit(str(exc))
            raise

    def set_sensor_calibration(
        self,
        sensor_key: str,
        payload: Mapping[str, Any],
        *,
        note: str = "",
    ) -> Dict[str, Any]:
        """
        Replace or update one sensor's calibration block.
        """
        if sensor_key not in CALIBRATABLE_SENSOR_KEYS:
            raise ValueError(f"Unsupported sensor_key: {sensor_key}")

        before = self.get_sensor_calibration(sensor_key)
        result = self._normalize_sensor_calibration_payload(sensor_key, payload)
        self._calibration[sensor_key] = result.normalized

        try:
            write_calibration(self._calibration)
            self._app_state.update_calibration_for_sensor(sensor_key, result.normalized)

            self._audit_change(
                sensor_key=sensor_key,
                before_payload=before,
                after_payload=result.normalized,
                note=note or f"Updated calibration for {sensor_key}",
            )

            self._logger.info("Calibration updated for sensor '%s'.", sensor_key)
            snapshot = self.snapshot()
            self.sensor_calibration_changed.emit(sensor_key, deep_copy(result.normalized))
            self.calibration_saved.emit(snapshot)
            self.calibration_changed.emit(snapshot)
            return snapshot

        except Exception as exc:
            log_exception(self._logger, f"Failed to update calibration for {sensor_key}", exc)
            self.calibration_error.emit(str(exc))
            raise

    def update_sensor_calibration(
        self,
        sensor_key: str,
        patch: Mapping[str, Any],
        *,
        note: str = "",
    ) -> Dict[str, Any]:
        """
        Patch one sensor's calibration block.
        """
        current = self.get_sensor_calibration(sensor_key)
        merged = deep_merge_dicts(current, dict(patch or {}))
        return self.set_sensor_calibration(sensor_key, merged, note=note or f"Patched calibration for {sensor_key}")

    # ========================================================
    # Strongly typed convenience setters
    # ========================================================

    def set_sensor_offset(self, sensor_key: str, offset: Any) -> Dict[str, Any]:
        return self.update_sensor_calibration(
            sensor_key,
            {"offset": offset},
            note=f"{sensor_key} offset updated",
        )

    def set_sensor_manual_offset_options(self, sensor_key: str, options: list[Any]) -> Dict[str, Any]:
        return self.update_sensor_calibration(
            sensor_key,
            {"manual_offset_options": list(options)},
            note=f"{sensor_key} manual offset options updated",
        )

    def set_sensor_update_frequency_seconds(self, sensor_key: str, seconds: Any) -> Dict[str, Any]:
        return self.update_sensor_calibration(
            sensor_key,
            {"update_frequency_seconds": seconds},
            note=f"{sensor_key} update frequency updated",
        )

    def set_sensor_calibration_range(
        self,
        sensor_key: str,
        *,
        calibration_min: Any,
        calibration_mid: Any,
        calibration_max: Any,
    ) -> Dict[str, Any]:
        return self.update_sensor_calibration(
            sensor_key,
            {
                "calibration_min": calibration_min,
                "calibration_mid": calibration_mid,
                "calibration_max": calibration_max,
            },
            note=f"{sensor_key} calibration range updated",
        )

    def reset_sensor_to_default(self, sensor_key: str) -> Dict[str, Any]:
        if sensor_key not in CALIBRATABLE_SENSOR_KEYS:
            raise ValueError(f"Unsupported sensor_key: {sensor_key}")

        default_payload = self._default_sensor_payload(sensor_key)
        return self.set_sensor_calibration(
            sensor_key,
            default_payload,
            note=f"{sensor_key} calibration reset to default",
        )

    def reset_all_to_defaults(self, note: str = "All calibration reset to defaults") -> Dict[str, Any]:
        before = self.snapshot()
        self._calibration = deep_copy(DEFAULT_CALIBRATION)

        try:
            write_calibration(self._calibration)
            self._apply_to_app_state()

            for sensor_key in CALIBRATABLE_SENSOR_KEYS:
                self._audit_change(
                    sensor_key=sensor_key,
                    before_payload=before.get(sensor_key, {}),
                    after_payload=self._calibration.get(sensor_key, {}),
                    note=note,
                )

            self._logger.warning("All calibration reset to defaults.")
            snapshot = self.snapshot()
            self.calibration_reset.emit(snapshot)
            self.calibration_saved.emit(snapshot)
            self.calibration_changed.emit(snapshot)
            return snapshot

        except Exception as exc:
            log_exception(self._logger, "Failed to reset calibration to defaults", exc)
            self.calibration_error.emit(str(exc))
            raise

    # ========================================================
    # Reference-based calibration helpers
    # ========================================================

    def calculate_reference_offset(
        self,
        measured_value: Any,
        reference_value: Any,
        sensor_key: str,
    ) -> float:
        """
        Calculate offset = reference - measured.
        """
        decimals = self._default_decimals_for_sensor(sensor_key)
        measured = safe_float(measured_value, 0.0)
        reference = safe_float(reference_value, 0.0)
        return safe_round(reference - measured, decimals=decimals, default=0.0)

    def auto_calibrate_sensor(
        self,
        sensor_key: str,
        *,
        measured_value: Any,
        reference_value: Any,
        note: str = "",
    ) -> Dict[str, Any]:
        """
        Reference-based calibration:
        new_offset = reference_value - measured_value
        """
        if sensor_key not in CALIBRATABLE_SENSOR_KEYS:
            raise ValueError(f"Unsupported sensor_key: {sensor_key}")

        new_offset = self.calculate_reference_offset(
            measured_value=measured_value,
            reference_value=reference_value,
            sensor_key=sensor_key,
        )

        return self.update_sensor_calibration(
            sensor_key,
            {"offset": new_offset},
            note=note or f"Auto calibrated {sensor_key} using reference value",
        )

    # ========================================================
    # Application of calibration to data
    # ========================================================

    def apply_to_value(self, sensor_key: str, value: Any) -> float:
        """
        Apply the stored calibration offset to one raw sensor value.
        """
        decimals = self._default_decimals_for_sensor(sensor_key)
        offset = self.get_sensor_offset(sensor_key)
        return safe_round(apply_offset(value, offset, decimals=decimals), decimals=decimals, default=0.0)

    def apply_to_measurements(
        self,
        measurements: Mapping[str, Any],
        *,
        recompute_bmi: bool = True,
    ) -> Dict[str, float]:
        """
        Apply calibration offsets to a measurement payload.

        Behavior:
        - temperature, spo2, weight, height, pulse_rate, respiratory_rate, bmi can all hold offsets
        - if recompute_bmi is True, BMI is recalculated from calibrated weight and height
        """
        normalized = normalize_measurement_payload(measurements)
        adjusted = dict(normalized)

        for sensor_key in CALIBRATABLE_SENSOR_KEYS:
            if sensor_key in adjusted:
                adjusted[sensor_key] = self.apply_to_value(sensor_key, adjusted[sensor_key])

        if recompute_bmi:
            weight = safe_float(adjusted.get(METRIC_WEIGHT), 0.0)
            height = safe_float(adjusted.get(METRIC_HEIGHT), 0.0)
            if weight > 0 and height > 0:
                adjusted[METRIC_BMI] = calculate_bmi(weight, height, decimals=1)

        final_payload = normalize_measurement_payload(adjusted)
        self.calibration_applied.emit(deep_copy(final_payload))
        return final_payload

    def apply_demo_measurements(self, measurements: Mapping[str, Any]) -> Dict[str, float]:
        """
        Convenience alias for demo mode.
        """
        return self.apply_to_measurements(measurements, recompute_bmi=True)

    def apply_hardware_measurements(self, measurements: Mapping[str, Any]) -> Dict[str, float]:
        """
        Convenience alias for hardware mode.
        """
        return self.apply_to_measurements(measurements, recompute_bmi=True)

    # ========================================================
    # File-level helpers
    # ========================================================

    def calibration_file_exists(self) -> bool:
        return CALIBRATION_FILE.exists()

    def calibration_file_path(self) -> str:
        return str(CALIBRATION_FILE)

    def export_calibration_payload(self) -> Dict[str, Any]:
        return self.snapshot()

    def save_snapshot_to_path(self, target_path: str) -> str:
        """
        Save current calibration JSON to a custom path.
        Useful for export/backups.
        """
        try:
            write_json_file(target_path, self._calibration)
            self._logger.info("Calibration snapshot exported to %s", target_path)
            return str(target_path)
        except Exception as exc:
            log_exception(self._logger, "Failed to export calibration snapshot", exc)
            self.calibration_error.emit(str(exc))
            raise

    # ========================================================
    # Diagnostics
    # ========================================================

    def diagnostics(self) -> Dict[str, Any]:
        summary: Dict[str, Any] = {
            "calibration_file": str(CALIBRATION_FILE),
            "calibration_file_exists": CALIBRATION_FILE.exists(),
            "sensor_count": len(self._calibration),
            "sensors": {},
        }

        for sensor_key in CALIBRATABLE_SENSOR_KEYS:
            sensor = self.get_sensor_calibration(sensor_key)
            summary["sensors"][sensor_key] = {
                "label": sensor.get("label", ""),
                "unit": sensor.get("unit", ""),
                "offset": sensor.get("offset", 0.0),
                "update_frequency_seconds": sensor.get("update_frequency_seconds", 5),
                "calibration_min": sensor.get("calibration_min", 0.0),
                "calibration_mid": sensor.get("calibration_mid", 0.0),
                "calibration_max": sensor.get("calibration_max", 0.0),
            }

        return summary


# ============================================================
# Singleton accessor
# ============================================================

_CALIBRATION_SERVICE_SINGLETON: Optional[CalibrationService] = None


def get_calibration_service(
    app_state: Optional[AppState] = None,
    database_service: Optional[DatabaseService] = None,
) -> CalibrationService:
    global _CALIBRATION_SERVICE_SINGLETON
    if _CALIBRATION_SERVICE_SINGLETON is None:
        _CALIBRATION_SERVICE_SINGLETON = CalibrationService(
            app_state=app_state,
            database_service=database_service,
        )
    return _CALIBRATION_SERVICE_SINGLETON