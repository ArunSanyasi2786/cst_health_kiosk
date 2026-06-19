"""
services/threshold_service.py

Persistent threshold and classification management service for the
CST Health Monitoring Station kiosk.

Why this file matters:
- It is the main backend for threshold configuration and diagnosis boundaries
- It reads/writes the JSON thresholds file under data/config/thresholds.json
- It keeps AppState and on-disk thresholds synchronized
- It records threshold changes through DatabaseService using the settings audit table
- It provides reusable classification helpers for:
    - BMI
    - Temperature
    - SpO2
    - Pulse Rate
    - Respiratory Rate
- It supports detail screens, diagnosis logic, results highlights, and publish summaries

Linked files:
- config.py
- core/app_state.py
- core/constants.py
- core/utils.py
- services/database_service.py

Design goals:
- central and explicit
- safe on first run
- easy for screens and diagnosis service to call
- strongly validated
- consistent categories for current UI and future hardware integration
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from config import (
    DEFAULT_THRESHOLDS,
    THRESHOLDS_FILE,
    read_thresholds,
    write_thresholds,
)
from core.app_state import AppState, get_app_state
from core.constants import (
    BMI_CATEGORY_LABELS,
    BMI_CATEGORY_NORMAL,
    BMI_CATEGORY_OBESE,
    BMI_CATEGORY_OVERWEIGHT,
    BMI_CATEGORY_UNDERWEIGHT,
    BMI_CATEGORIES,
    CALIBRATABLE_SENSOR_KEYS,
    ISSUE_BMI_OBESE,
    ISSUE_BMI_OVERWEIGHT,
    ISSUE_BMI_UNDERWEIGHT,
    ISSUE_CRITICAL_FEVER,
    ISSUE_CRITICAL_SPO2,
    ISSUE_FEVER,
    ISSUE_HIGH_FEVER,
    ISSUE_HIGH_PULSE,
    ISSUE_HIGH_RR,
    ISSUE_LOW_PULSE,
    ISSUE_LOW_RR,
    ISSUE_LOW_SPO2,
    METRIC_BMI,
    METRIC_HEIGHT,
    METRIC_PULSE,
    METRIC_RR,
    METRIC_SPO2,
    METRIC_TEMPERATURE,
    METRIC_WEIGHT,
    PULSE_CATEGORY_ELEVATED,
    PULSE_CATEGORY_HIGH,
    PULSE_CATEGORY_LABELS,
    PULSE_CATEGORY_LOW,
    PULSE_CATEGORY_NORMAL,
    PULSE_CATEGORIES,
    RR_CATEGORY_CRITICAL,
    RR_CATEGORY_HIGH,
    RR_CATEGORY_LABELS,
    RR_CATEGORY_LOW,
    RR_CATEGORY_NORMAL,
    RR_CATEGORIES,
    SEVERITY_ATTENTION,
    SEVERITY_CRITICAL,
    SEVERITY_NORMAL,
    SEVERITY_WARNING,
    SPO2_CATEGORY_CONCERNING,
    SPO2_CATEGORY_CRITICAL,
    SPO2_CATEGORY_LABELS,
    SPO2_CATEGORY_LOW,
    SPO2_CATEGORY_NORMAL,
    SPO2_CATEGORIES,
    TEMPERATURE_CATEGORY_HIGH_FEVER,
    TEMPERATURE_CATEGORY_LABELS,
    TEMPERATURE_CATEGORY_MILD_FEVER,
    TEMPERATURE_CATEGORY_NORMAL,
    TEMPERATURE_CATEGORY_VERY_HIGH_FEVER,
    TEMPERATURE_CATEGORIES,
)
from core.logger import get_logger, log_exception
from core.utils import (
    deep_copy,
    deep_merge_dicts,
    safe_float,
    safe_str,
    write_json_file,
)
from services.database_service import DatabaseService, get_database_service

logger = get_logger(__name__)


# ============================================================
# Dataclasses
# ============================================================

@dataclass
class ThresholdValidationResult:
    """
    Validation result returned by normalize helpers.
    """
    is_valid: bool
    normalized: Dict[str, Any]
    warnings: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "normalized": deep_copy(self.normalized),
            "warnings": list(self.warnings),
        }


@dataclass
class MetricClassification:
    """
    Generic classification payload used by diagnosis, detail screens,
    result highlighting, and publish summaries.
    """
    metric_key: str
    value: float
    category: str
    label: str
    severity: str
    is_normal: bool
    issue_key: str
    summary: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric_key": self.metric_key,
            "value": self.value,
            "category": self.category,
            "label": self.label,
            "severity": self.severity,
            "is_normal": self.is_normal,
            "issue_key": self.issue_key,
            "summary": self.summary,
        }


# ============================================================
# Threshold service
# ============================================================

class ThresholdService(QObject):
    """
    Central threshold manager for the kiosk.

    Main responsibilities:
    - load thresholds JSON
    - normalize and validate threshold payloads
    - save threshold JSON
    - update AppState immediately
    - save threshold audit entries
    - classify current measurements into categories
    - provide helpers for diagnosis and detail screens
    """

    thresholds_loaded = pyqtSignal(dict)
    thresholds_saved = pyqtSignal(dict)
    thresholds_changed = pyqtSignal(dict)
    metric_thresholds_changed = pyqtSignal(str, dict)
    thresholds_error = pyqtSignal(str)
    thresholds_reset = pyqtSignal(dict)
    classification_performed = pyqtSignal(dict)

    def __init__(
        self,
        app_state: Optional[AppState] = None,
        database_service: Optional[DatabaseService] = None,
    ) -> None:
        super().__init__()

        self._logger = logger.bind(component="ThresholdService")
        self._app_state: AppState = app_state or get_app_state()
        self._database_service: DatabaseService = database_service or get_database_service()

        self._thresholds: Dict[str, Any] = {}
        self._load_into_memory()

    # ========================================================
    # Internal normalization helpers
    # ========================================================

    def _default_metric_payload(self, metric_key: str) -> Dict[str, Any]:
        payload = DEFAULT_THRESHOLDS.get(metric_key, {})
        return deep_copy(payload if isinstance(payload, dict) else {})

    def _normalize_string(self, value: Any, fallback: str = "") -> str:
        return safe_str(value, fallback).strip()

    def _normalize_float(self, value: Any, fallback: float = 0.0) -> float:
        return safe_float(value, fallback)

    def _normalize_priority_order(self, value: Any) -> List[str]:
        if not isinstance(value, list):
            value = DEFAULT_THRESHOLDS.get("diagnosis", {}).get("priority_order", [])

        normalized: List[str] = []
        allowed = [METRIC_SPO2, METRIC_TEMPERATURE, METRIC_PULSE, METRIC_RR, METRIC_BMI]

        for item in value:
            cleaned = safe_str(item, "").strip().lower()
            if cleaned in allowed and cleaned not in normalized:
                normalized.append(cleaned)

        if not normalized:
            normalized = list(DEFAULT_THRESHOLDS.get("diagnosis", {}).get("priority_order", allowed))

        return normalized

    def _normalize_simple_metric_payload(
        self,
        metric_key: str,
        payload: Mapping[str, Any],
    ) -> ThresholdValidationResult:
        """
        Used for weight and height which are mostly informational.
        """
        base = self._default_metric_payload(metric_key)
        merged = deep_merge_dicts(base, dict(payload or {}))

        normalized = {
            "display_unit": self._normalize_string(merged.get("display_unit"), base.get("display_unit", "")),
            "normal_note": self._normalize_string(merged.get("normal_note"), base.get("normal_note", "")),
        }

        return ThresholdValidationResult(
            is_valid=True,
            normalized=normalized,
            warnings=[],
        )

    def _normalize_bmi_payload(self, payload: Mapping[str, Any]) -> ThresholdValidationResult:
        base = self._default_metric_payload(METRIC_BMI)
        merged = deep_merge_dicts(base, dict(payload or {}))
        warnings: List[str] = []

        normalized = {
            "display_unit": self._normalize_string(merged.get("display_unit"), base.get("display_unit", "")),
            "underweight_max": self._normalize_float(merged.get("underweight_max"), base.get("underweight_max", 18.4)),
            "normal_min": self._normalize_float(merged.get("normal_min"), base.get("normal_min", 18.5)),
            "normal_max": self._normalize_float(merged.get("normal_max"), base.get("normal_max", 24.9)),
            "overweight_min": self._normalize_float(merged.get("overweight_min"), base.get("overweight_min", 25.0)),
            "overweight_max": self._normalize_float(merged.get("overweight_max"), base.get("overweight_max", 29.9)),
            "obese_min": self._normalize_float(merged.get("obese_min"), base.get("obese_min", 30.0)),
        }

        if normalized["underweight_max"] > normalized["normal_min"]:
            normalized["underweight_max"] = normalized["normal_min"] - 0.1
            warnings.append("bmi.underweight_max was adjusted to remain below bmi.normal_min.")

        if normalized["normal_min"] > normalized["normal_max"]:
            normalized["normal_min"], normalized["normal_max"] = normalized["normal_max"], normalized["normal_min"]
            warnings.append("bmi.normal_min and bmi.normal_max were swapped.")

        if normalized["normal_max"] > normalized["overweight_min"]:
            normalized["overweight_min"] = normalized["normal_max"] + 0.1
            warnings.append("bmi.overweight_min was adjusted to remain above bmi.normal_max.")

        if normalized["overweight_min"] > normalized["overweight_max"]:
            normalized["overweight_min"], normalized["overweight_max"] = normalized["overweight_max"], normalized["overweight_min"]
            warnings.append("bmi.overweight_min and bmi.overweight_max were swapped.")

        if normalized["overweight_max"] > normalized["obese_min"]:
            normalized["obese_min"] = normalized["overweight_max"] + 0.1
            warnings.append("bmi.obese_min was adjusted to remain above bmi.overweight_max.")

        return ThresholdValidationResult(True, normalized, warnings)

    def _normalize_temperature_payload(self, payload: Mapping[str, Any]) -> ThresholdValidationResult:
        base = self._default_metric_payload(METRIC_TEMPERATURE)
        merged = deep_merge_dicts(base, dict(payload or {}))
        warnings: List[str] = []

        normalized = {
            "display_unit": self._normalize_string(merged.get("display_unit"), base.get("display_unit", "°C")),
            "normal_min": self._normalize_float(merged.get("normal_min"), base.get("normal_min", 36.0)),
            "normal_max": self._normalize_float(merged.get("normal_max"), base.get("normal_max", 37.0)),
            "mild_fever_min": self._normalize_float(merged.get("mild_fever_min"), base.get("mild_fever_min", 37.1)),
            "mild_fever_max": self._normalize_float(merged.get("mild_fever_max"), base.get("mild_fever_max", 38.0)),
            "high_fever_min": self._normalize_float(merged.get("high_fever_min"), base.get("high_fever_min", 38.1)),
            "high_fever_max": self._normalize_float(merged.get("high_fever_max"), base.get("high_fever_max", 40.0)),
            "very_high_fever_min": self._normalize_float(merged.get("very_high_fever_min"), base.get("very_high_fever_min", 40.1)),
        }

        if normalized["normal_min"] > normalized["normal_max"]:
            normalized["normal_min"], normalized["normal_max"] = normalized["normal_max"], normalized["normal_min"]
            warnings.append("temperature.normal_min and temperature.normal_max were swapped.")

        if normalized["normal_max"] > normalized["mild_fever_min"]:
            normalized["mild_fever_min"] = normalized["normal_max"] + 0.1
            warnings.append("temperature.mild_fever_min was adjusted.")

        if normalized["mild_fever_min"] > normalized["mild_fever_max"]:
            normalized["mild_fever_min"], normalized["mild_fever_max"] = normalized["mild_fever_max"], normalized["mild_fever_min"]
            warnings.append("temperature.mild_fever_min and temperature.mild_fever_max were swapped.")

        if normalized["mild_fever_max"] > normalized["high_fever_min"]:
            normalized["high_fever_min"] = normalized["mild_fever_max"] + 0.1
            warnings.append("temperature.high_fever_min was adjusted.")

        if normalized["high_fever_min"] > normalized["high_fever_max"]:
            normalized["high_fever_min"], normalized["high_fever_max"] = normalized["high_fever_max"], normalized["high_fever_min"]
            warnings.append("temperature.high_fever_min and temperature.high_fever_max were swapped.")

        if normalized["high_fever_max"] > normalized["very_high_fever_min"]:
            normalized["very_high_fever_min"] = normalized["high_fever_max"] + 0.1
            warnings.append("temperature.very_high_fever_min was adjusted.")

        return ThresholdValidationResult(True, normalized, warnings)

    def _normalize_spo2_payload(self, payload: Mapping[str, Any]) -> ThresholdValidationResult:
        base = self._default_metric_payload(METRIC_SPO2)
        merged = deep_merge_dicts(base, dict(payload or {}))
        warnings: List[str] = []

        normalized = {
            "display_unit": self._normalize_string(merged.get("display_unit"), base.get("display_unit", "%")),
            "normal_min": self._normalize_float(merged.get("normal_min"), base.get("normal_min", 95)),
            "normal_max": self._normalize_float(merged.get("normal_max"), base.get("normal_max", 100)),
            "concerning_min": self._normalize_float(merged.get("concerning_min"), base.get("concerning_min", 91)),
            "concerning_max": self._normalize_float(merged.get("concerning_max"), base.get("concerning_max", 94)),
            "low_min": self._normalize_float(merged.get("low_min"), base.get("low_min", 80)),
            "low_max": self._normalize_float(merged.get("low_max"), base.get("low_max", 90)),
            "critical_max": self._normalize_float(merged.get("critical_max"), base.get("critical_max", 79)),
        }

        if normalized["normal_min"] > normalized["normal_max"]:
            normalized["normal_min"], normalized["normal_max"] = normalized["normal_max"], normalized["normal_min"]
            warnings.append("spo2.normal_min and spo2.normal_max were swapped.")

        if normalized["concerning_min"] > normalized["concerning_max"]:
            normalized["concerning_min"], normalized["concerning_max"] = normalized["concerning_max"], normalized["concerning_min"]
            warnings.append("spo2.concerning_min and spo2.concerning_max were swapped.")

        if normalized["low_min"] > normalized["low_max"]:
            normalized["low_min"], normalized["low_max"] = normalized["low_max"], normalized["low_min"]
            warnings.append("spo2.low_min and spo2.low_max were swapped.")

        if normalized["critical_max"] >= normalized["low_min"]:
            normalized["critical_max"] = normalized["low_min"] - 1
            warnings.append("spo2.critical_max was adjusted to remain below spo2.low_min.")

        return ThresholdValidationResult(True, normalized, warnings)

    def _normalize_pulse_payload(self, payload: Mapping[str, Any]) -> ThresholdValidationResult:
        base = self._default_metric_payload(METRIC_PULSE)
        merged = deep_merge_dicts(base, dict(payload or {}))
        warnings: List[str] = []

        normalized = {
            "display_unit": self._normalize_string(merged.get("display_unit"), base.get("display_unit", "bpm")),
            "low_max": self._normalize_float(merged.get("low_max"), base.get("low_max", 59)),
            "normal_min": self._normalize_float(merged.get("normal_min"), base.get("normal_min", 60)),
            "normal_max": self._normalize_float(merged.get("normal_max"), base.get("normal_max", 100)),
            "high_min": self._normalize_float(merged.get("high_min"), base.get("high_min", 101)),
            "high_max": self._normalize_float(merged.get("high_max"), base.get("high_max", 120)),
            "critical_min": self._normalize_float(merged.get("critical_min"), base.get("critical_min", 121)),
        }

        if normalized["low_max"] >= normalized["normal_min"]:
            normalized["low_max"] = normalized["normal_min"] - 1
            warnings.append("pulse_rate.low_max was adjusted to remain below pulse_rate.normal_min.")

        if normalized["normal_min"] > normalized["normal_max"]:
            normalized["normal_min"], normalized["normal_max"] = normalized["normal_max"], normalized["normal_min"]
            warnings.append("pulse_rate.normal_min and pulse_rate.normal_max were swapped.")

        if normalized["normal_max"] >= normalized["high_min"]:
            normalized["high_min"] = normalized["normal_max"] + 1
            warnings.append("pulse_rate.high_min was adjusted to remain above pulse_rate.normal_max.")

        if normalized["high_min"] > normalized["high_max"]:
            normalized["high_min"], normalized["high_max"] = normalized["high_max"], normalized["high_min"]
            warnings.append("pulse_rate.high_min and pulse_rate.high_max were swapped.")

        if normalized["high_max"] >= normalized["critical_min"]:
            normalized["critical_min"] = normalized["high_max"] + 1
            warnings.append("pulse_rate.critical_min was adjusted to remain above pulse_rate.high_max.")

        return ThresholdValidationResult(True, normalized, warnings)

    def _normalize_rr_payload(self, payload: Mapping[str, Any]) -> ThresholdValidationResult:
        base = self._default_metric_payload(METRIC_RR)
        merged = deep_merge_dicts(base, dict(payload or {}))
        warnings: List[str] = []

        normalized = {
            "display_unit": self._normalize_string(merged.get("display_unit"), base.get("display_unit", "breaths/min")),
            "low_max": self._normalize_float(merged.get("low_max"), base.get("low_max", 11)),
            "normal_min": self._normalize_float(merged.get("normal_min"), base.get("normal_min", 12)),
            "normal_max": self._normalize_float(merged.get("normal_max"), base.get("normal_max", 20)),
            "high_min": self._normalize_float(merged.get("high_min"), base.get("high_min", 21)),
            "high_max": self._normalize_float(merged.get("high_max"), base.get("high_max", 24)),
            "critical_min": self._normalize_float(merged.get("critical_min"), base.get("critical_min", 25)),
        }

        if normalized["low_max"] >= normalized["normal_min"]:
            normalized["low_max"] = normalized["normal_min"] - 1
            warnings.append("respiratory_rate.low_max was adjusted.")

        if normalized["normal_min"] > normalized["normal_max"]:
            normalized["normal_min"], normalized["normal_max"] = normalized["normal_max"], normalized["normal_min"]
            warnings.append("respiratory_rate.normal_min and respiratory_rate.normal_max were swapped.")

        if normalized["normal_max"] >= normalized["high_min"]:
            normalized["high_min"] = normalized["normal_max"] + 1
            warnings.append("respiratory_rate.high_min was adjusted.")

        if normalized["high_min"] > normalized["high_max"]:
            normalized["high_min"], normalized["high_max"] = normalized["high_max"], normalized["high_min"]
            warnings.append("respiratory_rate.high_min and respiratory_rate.high_max were swapped.")

        if normalized["high_max"] >= normalized["critical_min"]:
            normalized["critical_min"] = normalized["high_max"] + 1
            warnings.append("respiratory_rate.critical_min was adjusted.")

        return ThresholdValidationResult(True, normalized, warnings)

    def _normalize_diagnosis_payload(self, payload: Mapping[str, Any]) -> ThresholdValidationResult:
        base = self._default_metric_payload("diagnosis")
        merged = deep_merge_dicts(base, dict(payload or {}))

        normalized = {
            "priority_order": self._normalize_priority_order(merged.get("priority_order")),
            "normal_message": self._normalize_string(
                merged.get("normal_message"),
                base.get("normal_message", "All measured parameters are within acceptable range."),
            ),
            "needs_attention_message": self._normalize_string(
                merged.get("needs_attention_message"),
                base.get("needs_attention_message", "Some parameters need attention. Please review advice."),
            ),
            "critical_message": self._normalize_string(
                merged.get("critical_message"),
                base.get("critical_message", "Critical condition detected. Seek immediate help."),
            ),
        }

        return ThresholdValidationResult(True, normalized, [])

    def _normalize_metric_payload(self, metric_key: str, payload: Mapping[str, Any]) -> ThresholdValidationResult:
        if metric_key in {METRIC_WEIGHT, METRIC_HEIGHT}:
            return self._normalize_simple_metric_payload(metric_key, payload)
        if metric_key == METRIC_BMI:
            return self._normalize_bmi_payload(payload)
        if metric_key == METRIC_TEMPERATURE:
            return self._normalize_temperature_payload(payload)
        if metric_key == METRIC_SPO2:
            return self._normalize_spo2_payload(payload)
        if metric_key == METRIC_PULSE:
            return self._normalize_pulse_payload(payload)
        if metric_key == METRIC_RR:
            return self._normalize_rr_payload(payload)
        if metric_key == "diagnosis":
            return self._normalize_diagnosis_payload(payload)

        # Fallback: preserve a normalized dictionary
        return ThresholdValidationResult(True, deep_copy(dict(payload or {})), [])

    def _normalize_thresholds_payload(self, payload: Mapping[str, Any]) -> ThresholdValidationResult:
        merged = deep_merge_dicts(DEFAULT_THRESHOLDS, dict(payload or {}))
        warnings: List[str] = []
        normalized: Dict[str, Any] = {}

        required_metric_keys = [
            METRIC_WEIGHT,
            METRIC_HEIGHT,
            METRIC_BMI,
            METRIC_TEMPERATURE,
            METRIC_SPO2,
            METRIC_PULSE,
            METRIC_RR,
            "diagnosis",
        ]

        for metric_key in required_metric_keys:
            metric_payload = merged.get(metric_key, {})
            if not isinstance(metric_payload, Mapping):
                metric_payload = {}
                warnings.append(f"{metric_key}: invalid threshold block replaced with defaults.")

            result = self._normalize_metric_payload(metric_key, metric_payload)
            normalized[metric_key] = result.normalized
            warnings.extend(result.warnings)

        return ThresholdValidationResult(
            is_valid=True,
            normalized=normalized,
            warnings=warnings,
        )

    def _load_into_memory(self) -> None:
        raw = read_thresholds()
        validation = self._normalize_thresholds_payload(raw)
        self._thresholds = validation.normalized

        try:
            write_thresholds(self._thresholds)
        except Exception as exc:
            log_exception(self._logger, "Failed to write normalized thresholds during load", exc)

        self._apply_to_app_state()
        self._logger.info("Thresholds loaded into memory.")
        self.thresholds_loaded.emit(self.snapshot())

    def _apply_to_app_state(self) -> None:
        try:
            for metric_key, metric_payload in self._thresholds.items():
                self._app_state.update_thresholds_for_metric(metric_key, metric_payload)
        except Exception as exc:
            log_exception(self._logger, "Failed to apply thresholds to AppState", exc)
            self.thresholds_error.emit(str(exc))

    def _audit_change(
        self,
        *,
        key_path: str,
        before_payload: Mapping[str, Any],
        after_payload: Mapping[str, Any],
        note: str = "",
    ) -> None:
        try:
            self._database_service.save_settings_audit(
                actor="admin",
                scope="thresholds",
                key_path=key_path,
                before_payload=before_payload,
                after_payload=after_payload,
                note=note,
            )
        except Exception as exc:
            log_exception(self._logger, "Failed to save threshold audit", exc)

    # ========================================================
    # Public read helpers
    # ========================================================

    def snapshot(self) -> Dict[str, Any]:
        return deep_copy(self._thresholds)

    def get_thresholds(self) -> Dict[str, Any]:
        return self.snapshot()

    def get_metric_thresholds(self, metric_key: str) -> Dict[str, Any]:
        value = self._thresholds.get(metric_key, {})
        return deep_copy(value if isinstance(value, dict) else {})

    def reload_from_disk(self) -> Dict[str, Any]:
        self._load_into_memory()
        return self.snapshot()

    def validate_payload(self, payload: Mapping[str, Any]) -> ThresholdValidationResult:
        return self._normalize_thresholds_payload(payload)

    def validate_metric_payload(self, metric_key: str, payload: Mapping[str, Any]) -> ThresholdValidationResult:
        return self._normalize_metric_payload(metric_key, payload)

    # ========================================================
    # Public write helpers
    # ========================================================

    def save_all(self, payload: Mapping[str, Any], note: str = "Bulk threshold update") -> Dict[str, Any]:
        before = self.snapshot()
        validation = self._normalize_thresholds_payload(payload)
        self._thresholds = validation.normalized

        try:
            write_thresholds(self._thresholds)
            self._apply_to_app_state()

            self._audit_change(
                key_path="*",
                before_payload=before,
                after_payload=self._thresholds,
                note=note,
            )

            snapshot = self.snapshot()
            self._logger.info("Thresholds saved via bulk update.")
            self.thresholds_saved.emit(snapshot)
            self.thresholds_changed.emit(snapshot)
            return snapshot

        except Exception as exc:
            log_exception(self._logger, "Failed to save all thresholds", exc)
            self.thresholds_error.emit(str(exc))
            raise

    def update_thresholds(self, patch: Mapping[str, Any], note: str = "Threshold patch update") -> Dict[str, Any]:
        before = self.snapshot()
        merged = deep_merge_dicts(self._thresholds, dict(patch or {}))
        validation = self._normalize_thresholds_payload(merged)
        self._thresholds = validation.normalized

        try:
            write_thresholds(self._thresholds)
            self._apply_to_app_state()

            self._audit_change(
                key_path="patch",
                before_payload=before,
                after_payload=self._thresholds,
                note=note,
            )

            snapshot = self.snapshot()
            self._logger.info("Thresholds updated via patch.")
            self.thresholds_saved.emit(snapshot)
            self.thresholds_changed.emit(snapshot)
            return snapshot

        except Exception as exc:
            log_exception(self._logger, "Failed to update thresholds", exc)
            self.thresholds_error.emit(str(exc))
            raise

    def set_metric_thresholds(
        self,
        metric_key: str,
        payload: Mapping[str, Any],
        *,
        note: str = "",
    ) -> Dict[str, Any]:
        before = self.get_metric_thresholds(metric_key)
        result = self._normalize_metric_payload(metric_key, payload)
        self._thresholds[metric_key] = result.normalized

        try:
            write_thresholds(self._thresholds)
            self._app_state.update_thresholds_for_metric(metric_key, result.normalized)

            self._audit_change(
                key_path=metric_key,
                before_payload=before,
                after_payload=result.normalized,
                note=note or f"Updated thresholds for {metric_key}",
            )

            snapshot = self.snapshot()
            self._logger.info("Thresholds updated for metric '%s'.", metric_key)
            self.metric_thresholds_changed.emit(metric_key, deep_copy(result.normalized))
            self.thresholds_saved.emit(snapshot)
            self.thresholds_changed.emit(snapshot)
            return snapshot

        except Exception as exc:
            log_exception(self._logger, f"Failed to update thresholds for {metric_key}", exc)
            self.thresholds_error.emit(str(exc))
            raise

    def update_metric_thresholds(
        self,
        metric_key: str,
        patch: Mapping[str, Any],
        *,
        note: str = "",
    ) -> Dict[str, Any]:
        current = self.get_metric_thresholds(metric_key)
        merged = deep_merge_dicts(current, dict(patch or {}))
        return self.set_metric_thresholds(metric_key, merged, note=note or f"Patched thresholds for {metric_key}")

    def reset_metric_to_default(self, metric_key: str) -> Dict[str, Any]:
        default_payload = self._default_metric_payload(metric_key)
        return self.set_metric_thresholds(metric_key, default_payload, note=f"{metric_key} thresholds reset to default")

    def reset_all_to_defaults(self, note: str = "All thresholds reset to defaults") -> Dict[str, Any]:
        before = self.snapshot()
        self._thresholds = deep_copy(DEFAULT_THRESHOLDS)

        try:
            write_thresholds(self._thresholds)
            self._apply_to_app_state()

            self._audit_change(
                key_path="*",
                before_payload=before,
                after_payload=self._thresholds,
                note=note,
            )

            snapshot = self.snapshot()
            self._logger.warning("All thresholds reset to defaults.")
            self.thresholds_reset.emit(snapshot)
            self.thresholds_saved.emit(snapshot)
            self.thresholds_changed.emit(snapshot)
            return snapshot

        except Exception as exc:
            log_exception(self._logger, "Failed to reset thresholds to defaults", exc)
            self.thresholds_error.emit(str(exc))
            raise

    # ========================================================
    # Generic classification helpers
    # ========================================================

    def classify_bmi(self, value: Any) -> MetricClassification:
        t = self.get_metric_thresholds(METRIC_BMI)
        bmi = safe_float(value, 0.0)

        if bmi < t.get("normal_min", 18.5):
            if bmi <= t.get("underweight_max", 18.4):
                return MetricClassification(
                    metric_key=METRIC_BMI,
                    value=bmi,
                    category=BMI_CATEGORY_UNDERWEIGHT,
                    label=BMI_CATEGORY_LABELS[BMI_CATEGORY_UNDERWEIGHT],
                    severity=SEVERITY_ATTENTION,
                    is_normal=False,
                    issue_key=ISSUE_BMI_UNDERWEIGHT,
                    summary="BMI is in the underweight range.",
                )

        if t.get("normal_min", 18.5) <= bmi <= t.get("normal_max", 24.9):
            return MetricClassification(
                metric_key=METRIC_BMI,
                value=bmi,
                category=BMI_CATEGORY_NORMAL,
                label=BMI_CATEGORY_LABELS[BMI_CATEGORY_NORMAL],
                severity=SEVERITY_NORMAL,
                is_normal=True,
                issue_key="",
                summary="BMI is within the normal range.",
            )

        if t.get("overweight_min", 25.0) <= bmi <= t.get("overweight_max", 29.9):
            return MetricClassification(
                metric_key=METRIC_BMI,
                value=bmi,
                category=BMI_CATEGORY_OVERWEIGHT,
                label=BMI_CATEGORY_LABELS[BMI_CATEGORY_OVERWEIGHT],
                severity=SEVERITY_ATTENTION,
                is_normal=False,
                issue_key=ISSUE_BMI_OVERWEIGHT,
                summary="BMI is in the overweight range.",
            )

        if bmi >= t.get("obese_min", 30.0):
            return MetricClassification(
                metric_key=METRIC_BMI,
                value=bmi,
                category=BMI_CATEGORY_OBESE,
                label=BMI_CATEGORY_LABELS[BMI_CATEGORY_OBESE],
                severity=SEVERITY_WARNING,
                is_normal=False,
                issue_key=ISSUE_BMI_OBESE,
                summary="BMI is in the obese range.",
            )

        # Safety fallback
        return MetricClassification(
            metric_key=METRIC_BMI,
            value=bmi,
            category=BMI_CATEGORY_NORMAL,
            label=BMI_CATEGORY_LABELS[BMI_CATEGORY_NORMAL],
            severity=SEVERITY_NORMAL,
            is_normal=True,
            issue_key="",
            summary="BMI evaluated successfully.",
        )

    def classify_temperature(self, value: Any) -> MetricClassification:
        t = self.get_metric_thresholds(METRIC_TEMPERATURE)
        temp = safe_float(value, 0.0)

        if temp >= t.get("very_high_fever_min", 40.1):
            return MetricClassification(
                metric_key=METRIC_TEMPERATURE,
                value=temp,
                category=TEMPERATURE_CATEGORY_VERY_HIGH_FEVER,
                label=TEMPERATURE_CATEGORY_LABELS[TEMPERATURE_CATEGORY_VERY_HIGH_FEVER],
                severity=SEVERITY_CRITICAL,
                is_normal=False,
                issue_key=ISSUE_CRITICAL_FEVER,
                summary="Temperature indicates very high fever.",
            )

        if t.get("high_fever_min", 38.1) <= temp <= t.get("high_fever_max", 40.0):
            return MetricClassification(
                metric_key=METRIC_TEMPERATURE,
                value=temp,
                category=TEMPERATURE_CATEGORY_HIGH_FEVER,
                label=TEMPERATURE_CATEGORY_LABELS[TEMPERATURE_CATEGORY_HIGH_FEVER],
                severity=SEVERITY_WARNING,
                is_normal=False,
                issue_key=ISSUE_HIGH_FEVER,
                summary="Temperature indicates high fever.",
            )

        if t.get("mild_fever_min", 37.1) <= temp <= t.get("mild_fever_max", 38.0):
            return MetricClassification(
                metric_key=METRIC_TEMPERATURE,
                value=temp,
                category=TEMPERATURE_CATEGORY_MILD_FEVER,
                label=TEMPERATURE_CATEGORY_LABELS[TEMPERATURE_CATEGORY_MILD_FEVER],
                severity=SEVERITY_ATTENTION,
                is_normal=False,
                issue_key=ISSUE_FEVER,
                summary="Temperature indicates mild fever.",
            )

        return MetricClassification(
            metric_key=METRIC_TEMPERATURE,
            value=temp,
            category=TEMPERATURE_CATEGORY_NORMAL,
            label=TEMPERATURE_CATEGORY_LABELS[TEMPERATURE_CATEGORY_NORMAL],
            severity=SEVERITY_NORMAL,
            is_normal=True,
            issue_key="",
            summary="Temperature is within the normal range.",
        )

    def classify_spo2(self, value: Any) -> MetricClassification:
        t = self.get_metric_thresholds(METRIC_SPO2)
        spo2 = safe_float(value, 0.0)

        if spo2 <= t.get("critical_max", 79):
            return MetricClassification(
                metric_key=METRIC_SPO2,
                value=spo2,
                category=SPO2_CATEGORY_CRITICAL,
                label=SPO2_CATEGORY_LABELS[SPO2_CATEGORY_CRITICAL],
                severity=SEVERITY_CRITICAL,
                is_normal=False,
                issue_key=ISSUE_CRITICAL_SPO2,
                summary="SpO₂ is critically low.",
            )

        if t.get("low_min", 80) <= spo2 <= t.get("low_max", 90):
            return MetricClassification(
                metric_key=METRIC_SPO2,
                value=spo2,
                category=SPO2_CATEGORY_LOW,
                label=SPO2_CATEGORY_LABELS[SPO2_CATEGORY_LOW],
                severity=SEVERITY_WARNING,
                is_normal=False,
                issue_key=ISSUE_LOW_SPO2,
                summary="SpO₂ is below the healthy range.",
            )

        if t.get("concerning_min", 91) <= spo2 <= t.get("concerning_max", 94):
            return MetricClassification(
                metric_key=METRIC_SPO2,
                value=spo2,
                category=SPO2_CATEGORY_CONCERNING,
                label=SPO2_CATEGORY_LABELS[SPO2_CATEGORY_CONCERNING],
                severity=SEVERITY_ATTENTION,
                is_normal=False,
                issue_key=ISSUE_LOW_SPO2,
                summary="SpO₂ is slightly below the ideal range.",
            )

        return MetricClassification(
            metric_key=METRIC_SPO2,
            value=spo2,
            category=SPO2_CATEGORY_NORMAL,
            label=SPO2_CATEGORY_LABELS[SPO2_CATEGORY_NORMAL],
            severity=SEVERITY_NORMAL,
            is_normal=True,
            issue_key="",
            summary="SpO₂ is within the normal range.",
        )

    def classify_pulse_rate(self, value: Any) -> MetricClassification:
        t = self.get_metric_thresholds(METRIC_PULSE)
        pulse = safe_float(value, 0.0)

        if pulse >= t.get("critical_min", 121):
            return MetricClassification(
                metric_key=METRIC_PULSE,
                value=pulse,
                category=PULSE_CATEGORY_HIGH,
                label=PULSE_CATEGORY_LABELS[PULSE_CATEGORY_HIGH],
                severity=SEVERITY_WARNING,
                is_normal=False,
                issue_key=ISSUE_HIGH_PULSE,
                summary="Pulse rate is critically high.",
            )

        if t.get("high_min", 101) <= pulse <= t.get("high_max", 120):
            return MetricClassification(
                metric_key=METRIC_PULSE,
                value=pulse,
                category=PULSE_CATEGORY_ELEVATED,
                label=PULSE_CATEGORY_LABELS[PULSE_CATEGORY_ELEVATED],
                severity=SEVERITY_ATTENTION,
                is_normal=False,
                issue_key=ISSUE_HIGH_PULSE,
                summary="Pulse rate is above the normal resting range.",
            )

        if t.get("normal_min", 60) <= pulse <= t.get("normal_max", 100):
            return MetricClassification(
                metric_key=METRIC_PULSE,
                value=pulse,
                category=PULSE_CATEGORY_NORMAL,
                label=PULSE_CATEGORY_LABELS[PULSE_CATEGORY_NORMAL],
                severity=SEVERITY_NORMAL,
                is_normal=True,
                issue_key="",
                summary="Pulse rate is within the normal resting range.",
            )

        return MetricClassification(
            metric_key=METRIC_PULSE,
            value=pulse,
            category=PULSE_CATEGORY_LOW,
            label=PULSE_CATEGORY_LABELS[PULSE_CATEGORY_LOW],
            severity=SEVERITY_ATTENTION,
            is_normal=False,
            issue_key=ISSUE_LOW_PULSE,
            summary="Pulse rate is below the normal resting range.",
        )

    def classify_respiratory_rate(self, value: Any) -> MetricClassification:
        t = self.get_metric_thresholds(METRIC_RR)
        rr = safe_float(value, 0.0)

        if rr >= t.get("critical_min", 25):
            return MetricClassification(
                metric_key=METRIC_RR,
                value=rr,
                category=RR_CATEGORY_CRITICAL,
                label=RR_CATEGORY_LABELS[RR_CATEGORY_CRITICAL],
                severity=SEVERITY_CRITICAL,
                is_normal=False,
                issue_key=ISSUE_HIGH_RR,
                summary="Respiratory rate is critically high.",
            )

        if t.get("high_min", 21) <= rr <= t.get("high_max", 24):
            return MetricClassification(
                metric_key=METRIC_RR,
                value=rr,
                category=RR_CATEGORY_HIGH,
                label=RR_CATEGORY_LABELS[RR_CATEGORY_HIGH],
                severity=SEVERITY_WARNING,
                is_normal=False,
                issue_key=ISSUE_HIGH_RR,
                summary="Respiratory rate is above the normal resting range.",
            )

        if t.get("normal_min", 12) <= rr <= t.get("normal_max", 20):
            return MetricClassification(
                metric_key=METRIC_RR,
                value=rr,
                category=RR_CATEGORY_NORMAL,
                label=RR_CATEGORY_LABELS[RR_CATEGORY_NORMAL],
                severity=SEVERITY_NORMAL,
                is_normal=True,
                issue_key="",
                summary="Respiratory rate is within the normal resting range.",
            )

        return MetricClassification(
            metric_key=METRIC_RR,
            value=rr,
            category=RR_CATEGORY_LOW,
            label=RR_CATEGORY_LABELS[RR_CATEGORY_LOW],
            severity=SEVERITY_ATTENTION,
            is_normal=False,
            issue_key=ISSUE_LOW_RR,
            summary="Respiratory rate is below the normal resting range.",
        )

    def classify_metric(self, metric_key: str, value: Any) -> MetricClassification:
        if metric_key == METRIC_BMI:
            result = self.classify_bmi(value)
        elif metric_key == METRIC_TEMPERATURE:
            result = self.classify_temperature(value)
        elif metric_key == METRIC_SPO2:
            result = self.classify_spo2(value)
        elif metric_key == METRIC_PULSE:
            result = self.classify_pulse_rate(value)
        elif metric_key == METRIC_RR:
            result = self.classify_respiratory_rate(value)
        else:
            result = MetricClassification(
                metric_key=metric_key,
                value=safe_float(value, 0.0),
                category="normal",
                label="Normal",
                severity=SEVERITY_NORMAL,
                is_normal=True,
                issue_key="",
                summary=f"{metric_key} evaluated.",
            )

        self.classification_performed.emit(result.to_dict())
        return result

    def classify_measurements(self, measurements: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
        """
        Classify the key metrics that have detailed screens and diagnosis value.
        """
        results = {
            METRIC_BMI: self.classify_bmi(measurements.get(METRIC_BMI)).to_dict(),
            METRIC_TEMPERATURE: self.classify_temperature(measurements.get(METRIC_TEMPERATURE)).to_dict(),
            METRIC_SPO2: self.classify_spo2(measurements.get(METRIC_SPO2)).to_dict(),
            METRIC_PULSE: self.classify_pulse_rate(measurements.get(METRIC_PULSE)).to_dict(),
            METRIC_RR: self.classify_respiratory_rate(measurements.get(METRIC_RR)).to_dict(),
        }
        self.classification_performed.emit(deep_copy(results))
        return results

    # ========================================================
    # Diagnosis message helpers
    # ========================================================

    def diagnosis_priority_order(self) -> List[str]:
        diagnosis = self.get_metric_thresholds("diagnosis")
        order = diagnosis.get("priority_order", [])
        return list(order) if isinstance(order, list) else list(DEFAULT_THRESHOLDS["diagnosis"]["priority_order"])

    def diagnosis_messages(self) -> Dict[str, str]:
        diagnosis = self.get_metric_thresholds("diagnosis")
        return {
            "normal_message": self._normalize_string(
                diagnosis.get("normal_message"),
                DEFAULT_THRESHOLDS["diagnosis"]["normal_message"],
            ),
            "needs_attention_message": self._normalize_string(
                diagnosis.get("needs_attention_message"),
                DEFAULT_THRESHOLDS["diagnosis"]["needs_attention_message"],
            ),
            "critical_message": self._normalize_string(
                diagnosis.get("critical_message"),
                DEFAULT_THRESHOLDS["diagnosis"]["critical_message"],
            ),
        }

    # ========================================================
    # File/export helpers
    # ========================================================

    def thresholds_file_exists(self) -> bool:
        return THRESHOLDS_FILE.exists()

    def thresholds_file_path(self) -> str:
        return str(THRESHOLDS_FILE)

    def export_thresholds_payload(self) -> Dict[str, Any]:
        return self.snapshot()

    def save_snapshot_to_path(self, target_path: str) -> str:
        try:
            write_json_file(target_path, self._thresholds)
            self._logger.info("Threshold snapshot exported to %s", target_path)
            return str(target_path)
        except Exception as exc:
            log_exception(self._logger, "Failed to export threshold snapshot", exc)
            self.thresholds_error.emit(str(exc))
            raise

    # ========================================================
    # Diagnostics
    # ========================================================

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "thresholds_file": str(THRESHOLDS_FILE),
            "thresholds_file_exists": THRESHOLDS_FILE.exists(),
            "bmi": self.get_metric_thresholds(METRIC_BMI),
            "temperature": self.get_metric_thresholds(METRIC_TEMPERATURE),
            "spo2": self.get_metric_thresholds(METRIC_SPO2),
            "pulse_rate": self.get_metric_thresholds(METRIC_PULSE),
            "respiratory_rate": self.get_metric_thresholds(METRIC_RR),
            "diagnosis": self.get_metric_thresholds("diagnosis"),
        }


# ============================================================
# Singleton accessor
# ============================================================

_THRESHOLD_SERVICE_SINGLETON: Optional[ThresholdService] = None


def get_threshold_service(
    app_state: Optional[AppState] = None,
    database_service: Optional[DatabaseService] = None,
) -> ThresholdService:
    global _THRESHOLD_SERVICE_SINGLETON
    if _THRESHOLD_SERVICE_SINGLETON is None:
        _THRESHOLD_SERVICE_SINGLETON = ThresholdService(
            app_state=app_state,
            database_service=database_service,
        )
    return _THRESHOLD_SERVICE_SINGLETON