"""
services/diagnosis_service.py

Diagnosis orchestration service for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the main diagnosis-layer backend used by results, consult, report, and admin views
- It converts measured health parameters into a clean, reusable diagnosis payload
- It sits above HealthRulesService and provides a stable public API for later screens/services
- It keeps AppState diagnosis data synchronized and easy to consume
- It supports both demo mode and hardware mode because it only depends on measurements and rules

Linked files:
- core/app_state.py
- core/constants.py
- core/utils.py
- services/threshold_service.py
- services/health_rules_service.py
- services/session_service.py (optional consumer)
- services/report_service.py (later)
- services/publish_service.py (later)

Design goals:
- keep diagnosis logic centralized and reusable
- expose stable helpers for UI and reports
- provide both full diagnosis and compact status summaries
- stay generic and safe for kiosk usage
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from core.app_state import AppState, get_app_state
from core.constants import (
    EMPTY_DIAGNOSIS_PAYLOAD,
    HEALTH_STATUS_NORMAL,
    HEALTH_STATUS_NEEDS_ATTENTION,
    METRIC_BMI,
    METRIC_PULSE,
    METRIC_RR,
    METRIC_SPO2,
    METRIC_TEMPERATURE,
    SEVERITY_ATTENTION,
    SEVERITY_CRITICAL,
    SEVERITY_NORMAL,
    SEVERITY_PRIORITY,
    SEVERITY_UNKNOWN,
    SEVERITY_WARNING,
)
from core.logger import get_logger, log_exception
from core.utils import (
    deep_copy,
    normalize_measurement_payload,
    safe_float,
    safe_str,
)
from services.health_rules_service import HealthRulesService, get_health_rules_service
from services.threshold_service import ThresholdService, get_threshold_service

logger = get_logger(__name__)


# ============================================================
# Dataclasses
# ============================================================

@dataclass
class DiagnosisBuildResult:
    """
    Standard diagnosis return object for internal and UI-facing use.
    """
    success: bool
    diagnosis: Dict[str, Any]
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "diagnosis": deep_copy(self.diagnosis),
            "message": self.message,
        }


# ============================================================
# Diagnosis service
# ============================================================

class DiagnosisService(QObject):
    """
    Central diagnosis orchestration service.

    Main responsibilities:
    - build diagnosis from measurement payloads
    - optionally store diagnosis in AppState
    - provide consult/status/detail-friendly summaries
    - expose stable methods for SessionService and later Report/Publish services
    """

    diagnosis_generated = pyqtSignal(dict)
    diagnosis_applied = pyqtSignal(dict)
    diagnosis_cleared = pyqtSignal()
    consult_payload_ready = pyqtSignal(dict)
    status_payload_ready = pyqtSignal(dict)
    diagnosis_error = pyqtSignal(str)

    def __init__(
        self,
        app_state: Optional[AppState] = None,
        threshold_service: Optional[ThresholdService] = None,
        health_rules_service: Optional[HealthRulesService] = None,
    ) -> None:
        super().__init__()

        self._logger = logger.bind(component="DiagnosisService")
        self._app_state: AppState = app_state or get_app_state()
        self._threshold_service: ThresholdService = threshold_service or get_threshold_service()
        self._health_rules_service: HealthRulesService = health_rules_service or get_health_rules_service()
        self._simple_rules_path = Path(__file__).resolve().parent.parent / "data" / "diagnosis_simple_rules.json"

    # ========================================================
    # Basic helpers
    # ========================================================

    def _severity_rank(self, severity: str) -> int:
        return SEVERITY_PRIORITY.get(safe_str(severity, SEVERITY_UNKNOWN).strip().lower(), -1)

    def _normalize_existing_diagnosis(self, payload: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
        """
        Normalize any diagnosis payload into a safe, complete shape.
        """
        base = deep_copy(EMPTY_DIAGNOSIS_PAYLOAD)
        incoming = dict(payload or {})
        base.update(incoming)

        if "consult_tips" not in base:
            base["consult_tips"] = []
        if "emergency_recommended" not in base:
            base["emergency_recommended"] = False
        if "emergency_number" not in base:
            base["emergency_number"] = ""
        if "combination_diagnosis" not in base or not isinstance(base.get("combination_diagnosis"), Mapping):
            base["combination_diagnosis"] = {}
        if "base_summary" not in base:
            base["base_summary"] = safe_str(base.get("summary"), "").strip()

        # guarantee expected types
        base["issues"] = list(base.get("issues", []) or [])
        base["issue_labels"] = list(base.get("issue_labels", []) or [])
        base["recommendations"] = list(base.get("recommendations", []) or [])
        base["consult_tips"] = list(base.get("consult_tips", []) or [])
        base["metric_categories"] = dict(base.get("metric_categories", {}) or {})
        combination = dict(base.get("combination_diagnosis", {}) or {})
        combination.setdefault("key", "")
        combination.setdefault("label", "")
        combination.setdefault("remark", "")
        combination.setdefault("tips", [])
        combination.setdefault("matched_from", "")
        combination.setdefault("bands", {})
        combination["tips"] = list(combination.get("tips", []) or [])
        combination["bands"] = dict(combination.get("bands", {}) or {})
        base["combination_diagnosis"] = combination

        base["overall_severity"] = safe_str(base.get("overall_severity"), SEVERITY_UNKNOWN).strip().lower() or SEVERITY_UNKNOWN
        base["status_title"] = safe_str(base.get("status_title"), "No Data").strip() or "No Data"
        base["summary"] = safe_str(base.get("summary"), "No measurements available yet.").strip() or "No measurements available yet."
        base["emergency_recommended"] = bool(base.get("emergency_recommended", False))
        base["emergency_number"] = safe_str(base.get("emergency_number"), "").strip()

        return base

    def _band_for_metric(
        self,
        metric_key: str,
        value: Any,
        metric_categories: Mapping[str, Any],
    ) -> str:
        item = dict(metric_categories.get(metric_key, {}) or {})
        is_normal = bool(item.get("is_normal", False))
        numeric = safe_float(value, 0.0)

        if metric_key == METRIC_TEMPERATURE:
            if value in (None, ""):
                return "unknown"
            if numeric < 36.1:
                return "low"
            if numeric <= 37.0:
                return "normal"
            return "high"

        if is_normal:
            return "normal"

        if metric_key == METRIC_SPO2:
            return "low"
        if metric_key == METRIC_BMI:
            return "low" if 0 < numeric < 18.5 else "high"
        if metric_key == METRIC_PULSE:
            return "low" if numeric < 60.0 else "high"
        if metric_key == METRIC_RR:
            return "low" if 0 < numeric < 12.0 else "high"

        return "normal"


    def _load_simple_rule_overrides(self) -> Dict[tuple[str, str, str, str, str], Dict[str, Any]]:
        rules: Dict[tuple[str, str, str, str, str], Dict[str, Any]] = {}
        try:
            if not self._simple_rules_path.exists():
                return rules
            raw = json.loads(self._simple_rules_path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                return rules
            for item in raw:
                if not isinstance(item, Mapping):
                    continue
                bands = dict(item.get("bands", {}) or {})
                key = (
                    safe_str(bands.get("spo2"), "").strip().lower(),
                    safe_str(bands.get("bmi"), "").strip().lower(),
                    safe_str(bands.get("pulse_rate"), bands.get("pulse")).strip().lower(),
                    safe_str(bands.get("respiratory_rate"), bands.get("rr")).strip().lower(),
                    safe_str(bands.get("temperature"), bands.get("temp")).strip().lower(),
                )
                if not all(key):
                    continue
                rules[key] = {
                    "label": safe_str(item.get("label"), "Custom diagnosis pattern").strip() or "Custom diagnosis pattern",
                    "remark": safe_str(item.get("remark"), "Custom diagnosis note saved from admin settings.").strip() or "Custom diagnosis note saved from admin settings.",
                    "tips": [safe_str(v, "").strip() for v in list(item.get("tips", []) or []) if safe_str(v, "").strip()],
                    "source": "custom",
                }
        except Exception:
            return {}
        return rules

    def list_simple_algorithm_rules(self) -> List[Dict[str, Any]]:
        output: List[Dict[str, Any]] = []
        for bands, payload in self._load_simple_rule_overrides().items():
            output.append({
                "bands": {
                    "spo2": bands[0],
                    "bmi": bands[1],
                    "pulse_rate": bands[2],
                    "respiratory_rate": bands[3],
                    "temperature": bands[4],
                },
                "label": safe_str(payload.get("label"), "").strip(),
                "remark": safe_str(payload.get("remark"), "").strip(),
                "tips": list(payload.get("tips", []) or []),
            })
        return output

    def save_simple_algorithm_rule(
        self,
        *,
        spo2: str,
        bmi: str,
        pulse_rate: str,
        respiratory_rate: str,
        temperature: str,
        label: str,
        remark: str,
        tips: Optional[List[str]] = None,
    ) -> bool:
        key_payload = {
            "bands": {
                "spo2": safe_str(spo2, "").strip().lower(),
                "bmi": safe_str(bmi, "").strip().lower(),
                "pulse_rate": safe_str(pulse_rate, "").strip().lower(),
                "respiratory_rate": safe_str(respiratory_rate, "").strip().lower(),
                "temperature": safe_str(temperature, "").strip().lower(),
            },
            "label": safe_str(label, "Custom diagnosis pattern").strip() or "Custom diagnosis pattern",
            "remark": safe_str(remark, "Custom diagnosis note saved from admin settings.").strip() or "Custom diagnosis note saved from admin settings.",
            "tips": [safe_str(v, "").strip() for v in list(tips or []) if safe_str(v, "").strip()],
        }
        if not all(key_payload["bands"].values()):
            return False

        rules = self.list_simple_algorithm_rules()
        replaced = False
        for idx, item in enumerate(rules):
            if dict(item.get("bands", {}) or {}) == key_payload["bands"]:
                rules[idx] = key_payload
                replaced = True
                break
        if not replaced:
            rules.append(key_payload)

        try:
            self._simple_rules_path.parent.mkdir(parents=True, exist_ok=True)
            self._simple_rules_path.write_text(json.dumps(rules, indent=2), encoding="utf-8")
            return True
        except Exception:
            return False

    def delete_simple_algorithm_rule(
        self,
        *,
        spo2: str,
        bmi: str,
        pulse_rate: str,
        respiratory_rate: str,
        temperature: str,
    ) -> bool:
        target = {
            "spo2": safe_str(spo2, "").strip().lower(),
            "bmi": safe_str(bmi, "").strip().lower(),
            "pulse_rate": safe_str(pulse_rate, "").strip().lower(),
            "respiratory_rate": safe_str(respiratory_rate, "").strip().lower(),
            "temperature": safe_str(temperature, "").strip().lower(),
        }
        rules = [item for item in self.list_simple_algorithm_rules() if dict(item.get("bands", {}) or {}) != target]
        try:
            self._simple_rules_path.parent.mkdir(parents=True, exist_ok=True)
            self._simple_rules_path.write_text(json.dumps(rules, indent=2), encoding="utf-8")
            return True
        except Exception:
            return False


    def _friendly_band_label(self, metric_key: str, band: str) -> str:
        band_text = safe_str(band, "normal").strip().lower() or "normal"
        if metric_key == METRIC_BMI and band_text == "normal":
            return "Healthy"
        if band_text == "high":
            return "High"
        if band_text == "low":
            return "Low"
        if band_text == "unknown":
            return "Unknown"
        return "Normal"

    def _parameter_status_text(self, bands: Mapping[str, str]) -> str:
        ordered_keys = [
            METRIC_TEMPERATURE,
            METRIC_SPO2,
            METRIC_PULSE,
            METRIC_BMI,
            METRIC_RR,
        ]
        labels = {
            METRIC_TEMPERATURE: "Temperature",
            METRIC_SPO2: "SpO₂",
            METRIC_PULSE: "Pulse rate",
            METRIC_BMI: "BMI",
            METRIC_RR: "Respiration rate",
        }
        parts: List[str] = []
        for key in ordered_keys:
            parts.append(f"{labels[key]} is {self._friendly_band_label(key, safe_str(bands.get(key), 'normal'))}")
        return ", ".join(parts) + "."

    def _worksheet_combination_rules(self) -> Dict[tuple[str, str, str, str, str], Dict[str, Any]]:
        base_rules = {
            ("low", "low", "low", "low", "low"): {
                "label": "Possible low vitality pattern",
                "remark": "Many readings are on the lower side today. Please rest, hydrate, and repeat the measurement once you are settled.",
                "tips": [
                    "Sit down and rest for a few minutes before rechecking.",
                    "Drink some water and avoid rushing into another scan.",
                    "Use routine follow-up if the same pattern appears again.",
                ],
            },
            ("low", "low", "low", "low", "normal"): {
                "label": "Possible low oxygen pattern",
                "remark": "Oxygen and a few supporting readings look low today. Please take extra care and repeat the scan calmly.",
                "tips": [
                    "Sit upright and stay still before repeating the measurement.",
                    "Avoid unnecessary exertion until you recheck the reading.",
                    "Arrange routine follow-up if the same result continues.",
                ],
            },
            ("low", "low", "low", "low", "high"): {
                "label": "Possible fever with low oxygen pattern",
                "remark": "Temperature looks raised while oxygen and some supporting readings are low. Please take extra care and repeat the check soon.",
                "tips": [
                    "Rest, cool down, and drink water before rechecking.",
                    "Stay calm and avoid heavy activity until the next scan.",
                    "Use routine follow-up if this same pattern remains.",
                ],
            },
            ("low", "low", "low", "normal", "low"): {
                "label": "Possible low body reserve pattern",
                "remark": "Body build and oxygen are on the lower side. A gentle wellness follow-up may be helpful.",
                "tips": [
                    "Repeat the scan after a short rest.",
                    "Maintain meals, fluids, and general self-care.",
                    "Use routine follow-up if this pattern keeps appearing.",
                ],
            },
            ("low", "low", "low", "normal", "normal"): {
                "label": "Possible mild low oxygen pattern",
                "remark": "Oxygen is slightly low today. Please repeat the scan once you are fully settled.",
                "tips": [
                    "Sit upright and keep still during the next measurement.",
                    "Repeat the reading after a short rest.",
                    "Use routine follow-up if the reading stays low.",
                ],
            },
            ("low", "low", "normal", "high", "normal"): {
                "label": "Possible breathing discomfort pattern",
                "remark": "Oxygen is low while breathing rate is higher than usual. Please sit upright, breathe slowly, and recheck.",
                "tips": [
                    "Relax your breathing and repeat the scan calmly.",
                    "Avoid talking or moving during the next reading.",
                    "Use routine follow-up if the same pattern appears again.",
                ],
            },
            ("normal", "normal", "normal", "normal", "normal"): {
                "label": "No clear issue seen",
                "remark": "All key readings are within the normal kiosk range for this session.",
                "tips": [
                    "Continue your normal routine and healthy habits.",
                    "Use the kiosk again anytime for another comparison.",
                    "No extra action is needed unless you feel unwell.",
                ],
            },
            ("high", "high", "high", "high", "high"): {
                "label": "Possible fever or body stress pattern",
                "remark": "Several readings are raised together today. Please rest, drink water, and repeat the scan after settling down.",
                "tips": [
                    "Rest quietly before repeating the measurement.",
                    "Drink water and avoid heavy activity for a while.",
                    "Use routine follow-up if elevated values keep returning.",
                ],
            },
        }
        base_rules.update(self._load_simple_rule_overrides())
        return base_rules

    def _build_combination_diagnosis(
        self,
        measurements: Mapping[str, Any],
        diagnosis_payload: Mapping[str, Any],
    ) -> Dict[str, Any]:
        metric_categories = dict(diagnosis_payload.get("metric_categories", {}) or {})
        bands = {
            METRIC_SPO2: self._band_for_metric(METRIC_SPO2, measurements.get(METRIC_SPO2), metric_categories),
            METRIC_BMI: self._band_for_metric(METRIC_BMI, measurements.get(METRIC_BMI), metric_categories),
            METRIC_PULSE: self._band_for_metric(METRIC_PULSE, measurements.get(METRIC_PULSE), metric_categories),
            METRIC_RR: self._band_for_metric(METRIC_RR, measurements.get(METRIC_RR), metric_categories),
            METRIC_TEMPERATURE: self._band_for_metric(METRIC_TEMPERATURE, measurements.get(METRIC_TEMPERATURE), metric_categories),
        }
        key_tuple = (
            bands[METRIC_SPO2],
            bands[METRIC_BMI],
            bands[METRIC_PULSE],
            bands[METRIC_RR],
            bands[METRIC_TEMPERATURE],
        )
        parameter_status_text = self._parameter_status_text(bands)

        worksheet_rule = self._worksheet_combination_rules().get(key_tuple)
        tips_from_payload = list(diagnosis_payload.get("consult_tips", []) or []) + list(diagnosis_payload.get("recommendations", []) or [])
        deduped_tips: List[str] = []
        for item in tips_from_payload:
            cleaned = safe_str(item, "").strip()
            if cleaned and cleaned not in deduped_tips:
                deduped_tips.append(cleaned)

        if worksheet_rule:
            label = safe_str(worksheet_rule.get("label"), "").strip()
            remark = safe_str(worksheet_rule.get("remark"), "").strip()
            tips = list(worksheet_rule.get("tips", []) or [])
            return {
                "key": "|".join(key_tuple),
                "label": label,
                "likely_condition": label,
                "remark": remark,
                "care_note": remark,
                "tips": tips,
                "matched_from": "worksheet_combo",
                "bands": bands,
                "parameter_status_text": parameter_status_text,
            }

        issues = list(diagnosis_payload.get("issue_labels", []) or [])
        severity = safe_str(diagnosis_payload.get("overall_severity"), SEVERITY_UNKNOWN).strip().lower() or SEVERITY_UNKNOWN

        label = "Mild variation seen"
        remark = "The readings show a small variation today. Please repeat the scan calmly and take extra care."
        tips: List[str] = [
            "Rest briefly and repeat the measurement.",
            "Stay relaxed and avoid moving during the next scan.",
        ]

        if all(band == "normal" for band in key_tuple):
            label = "No clear issue seen"
            remark = "All key readings are within the normal kiosk range for this session."
            tips = [
                "Continue your regular healthy routine.",
                "No extra action is needed unless you feel unwell.",
            ]
        elif bands[METRIC_TEMPERATURE] == "high" and bands[METRIC_SPO2] == "low" and bands[METRIC_RR] == "high":
            label = "Possible fever pattern"
            remark = "Temperature is raised, oxygen is low, and breathing rate is high. Please take extra care and repeat the scan after resting."
            tips = [
                "Sit upright, breathe slowly, and recheck once settled.",
                "Drink water and avoid exertion for a while.",
                "Use routine follow-up if the same pattern remains.",
            ]
        elif bands[METRIC_TEMPERATURE] == "high" and bands[METRIC_PULSE] == "high":
            label = "Possible fever or body stress pattern"
            remark = "Temperature and pulse are both raised. Please rest, cool down, and repeat the measurement calmly."
            tips = [
                "Sit quietly for a few minutes before rechecking.",
                "Hydrate well and avoid rushing.",
                "Use routine follow-up if the same result continues.",
            ]
        elif bands[METRIC_SPO2] == "low" and bands[METRIC_RR] == "high":
            label = "Possible breathing discomfort pattern"
            remark = "Oxygen is low while breathing rate is high. Please breathe slowly and repeat the scan once calm."
            tips = [
                "Sit upright and stay still before the next measurement.",
                "Avoid talking or walking around before rechecking.",
                "Use routine follow-up if this keeps appearing.",
            ]
        elif bands[METRIC_SPO2] == "low":
            label = "Possible low oxygen pattern"
            remark = "Oxygen appears lower than ideal today. Please take extra care and repeat the scan once settled."
            tips = [
                "Stay calm and repeat the scan after resting.",
                "Avoid unnecessary exertion for a while.",
                "Use routine follow-up if the same reading remains.",
            ]
        elif bands[METRIC_BMI] == "low" and bands[METRIC_SPO2] == "low":
            label = "Possible low body reserve pattern"
            remark = "BMI and oxygen are both on the lower side. Gentle wellness follow-up may be helpful."
            tips = [
                "Repeat the reading after a short rest.",
                "Maintain meals, fluids, and general self-care.",
                "Use routine follow-up if this pattern continues.",
            ]
        elif bands[METRIC_RR] == "high" and bands[METRIC_PULSE] == "high":
            label = "Possible stress or exertion pattern"
            remark = "Pulse and breathing are both raised, which can happen after movement or stress. Repeat the scan when calm."
            tips = [
                "Pause and relax before rechecking.",
                "Avoid walking or talking during the next scan.",
                "Use routine follow-up if the same pattern returns.",
            ]
        elif bands[METRIC_TEMPERATURE] == "low":
            label = "Possible cool-body reading"
            remark = "Temperature is below the usual range today. Please warm up, rest, and repeat the measurement calmly."
            tips = [
                "Warm your hands and rest before rechecking.",
                "Stay comfortable and repeat the scan once settled.",
            ]
        elif severity in {SEVERITY_ATTENTION, SEVERITY_WARNING, SEVERITY_CRITICAL} or issues:
            joined_issues = ", ".join(issues[:3]) if issues else "a few readings"
            label = "Possible follow-up pattern"
            remark = f"The kiosk noticed {joined_issues} outside the preferred range. Please take extra care and repeat the scan."
            tips = deduped_tips[:3] if deduped_tips else [
                "Rest briefly and repeat the measurement.",
                "Use routine follow-up if you keep seeing similar results.",
            ]
        else:
            tips = deduped_tips[:3] if deduped_tips else tips

        return {
            "key": "|".join(key_tuple),
            "label": label,
            "likely_condition": label,
            "remark": remark,
            "care_note": remark,
            "tips": tips,
            "matched_from": "heuristic",
            "bands": bands,
            "parameter_status_text": parameter_status_text,
        }

    # ========================================================
    # Diagnosis building
    # ========================================================

    def build_diagnosis(
        self,
        measurements: Mapping[str, Any],
        *,
        classifications: Optional[Mapping[str, Any]] = None,
        store_in_app_state: bool = False,
    ) -> Dict[str, Any]:
        """
        Main diagnosis builder.

        Parameters:
        - measurements: normalized or raw measurement payload
        - classifications: optional precomputed metric classifications
        - store_in_app_state: whether to immediately write diagnosis to AppState

        Returns:
        - normalized diagnosis payload
        """
        try:
            normalized_measurements = normalize_measurement_payload(measurements)
            diagnosis = self._health_rules_service.build_diagnosis(
                normalized_measurements,
                classifications=classifications,
            )
            diagnosis = self._normalize_existing_diagnosis(diagnosis)
            base_summary = safe_str(diagnosis.get("summary"), "").strip()
            diagnosis["base_summary"] = base_summary

            combination_diagnosis = self._build_combination_diagnosis(
                normalized_measurements,
                diagnosis,
            )
            diagnosis["combination_diagnosis"] = deep_copy(combination_diagnosis)

            combination_remark = safe_str(combination_diagnosis.get("remark"), "").strip()
            combination_tips = list(combination_diagnosis.get("tips", []) or [])
            if combination_remark:
                diagnosis["summary"] = combination_remark
            if combination_tips:
                diagnosis["consult_tips"] = self.consult_tips(diagnosis) + []
                merged_tips: List[str] = []
                for tip in combination_tips + list(diagnosis.get("consult_tips", []) or []) + list(diagnosis.get("recommendations", []) or []):
                    cleaned = safe_str(tip, "").strip()
                    if cleaned and cleaned not in merged_tips:
                        merged_tips.append(cleaned)
                diagnosis["consult_tips"] = merged_tips[:6]
                if not diagnosis.get("recommendations"):
                    diagnosis["recommendations"] = merged_tips[:3]

            self.diagnosis_generated.emit(deep_copy(diagnosis))

            if store_in_app_state:
                self._app_state.set_diagnosis(diagnosis)
                self.diagnosis_applied.emit(deep_copy(diagnosis))

            return diagnosis

        except Exception as exc:
            log_exception(self._logger, "Failed to build diagnosis", exc)
            self.diagnosis_error.emit(str(exc))
            return self.empty_diagnosis_payload()

    def generate_diagnosis(
        self,
        measurements: Mapping[str, Any],
        *,
        store_in_app_state: bool = False,
    ) -> Dict[str, Any]:
        """
        Alias for compatibility with other services that may call generate_diagnosis().
        """
        return self.build_diagnosis(
            measurements,
            classifications=None,
            store_in_app_state=store_in_app_state,
        )

    def diagnose_current_session(self, *, store_in_app_state: bool = True) -> Dict[str, Any]:
        """
        Build diagnosis from the current AppState measurements.
        """
        measurements = self._app_state.current_measurements()
        return self.build_diagnosis(
            measurements,
            classifications=None,
            store_in_app_state=store_in_app_state,
        )

    def rebuild_current_session_diagnosis(self) -> Dict[str, Any]:
        """
        Force rebuild and store diagnosis using current measurements.
        """
        return self.diagnose_current_session(store_in_app_state=True)

    # ========================================================
    # Current diagnosis accessors
    # ========================================================

    def current_diagnosis(self) -> Dict[str, Any]:
        payload = self._app_state.current_diagnosis()
        return self._normalize_existing_diagnosis(payload)

    def get_current_diagnosis(self) -> Dict[str, Any]:
        return self.current_diagnosis()

    def current_measurements(self) -> Dict[str, float]:
        return normalize_measurement_payload(self._app_state.current_measurements())

    def apply_diagnosis(self, diagnosis_payload: Mapping[str, Any]) -> Dict[str, Any]:
        """
        Store a provided diagnosis payload into AppState.
        """
        diagnosis = self._normalize_existing_diagnosis(diagnosis_payload)
        self._app_state.set_diagnosis(diagnosis)
        self.diagnosis_applied.emit(deep_copy(diagnosis))
        return diagnosis

    def clear_current_diagnosis(self) -> None:
        self._app_state.clear_diagnosis()
        self.diagnosis_cleared.emit()

    def empty_diagnosis_payload(self) -> Dict[str, Any]:
        return self._normalize_existing_diagnosis(self._health_rules_service.empty_diagnosis_payload())

    # ========================================================
    # Compact status helpers
    # ========================================================

    def overall_severity(self, diagnosis_payload: Optional[Mapping[str, Any]] = None) -> str:
        payload = self._normalize_existing_diagnosis(diagnosis_payload or self.current_diagnosis())
        return safe_str(payload.get("overall_severity"), SEVERITY_UNKNOWN).strip().lower() or SEVERITY_UNKNOWN

    def status_title(self, diagnosis_payload: Optional[Mapping[str, Any]] = None) -> str:
        payload = self._normalize_existing_diagnosis(diagnosis_payload or self.current_diagnosis())
        return safe_str(payload.get("status_title"), "No Data").strip() or "No Data"

    def summary_text(self, diagnosis_payload: Optional[Mapping[str, Any]] = None) -> str:
        payload = self._normalize_existing_diagnosis(diagnosis_payload or self.current_diagnosis())
        return safe_str(payload.get("summary"), "No measurements available yet.").strip() or "No measurements available yet."

    def issue_keys(self, diagnosis_payload: Optional[Mapping[str, Any]] = None) -> List[str]:
        payload = self._normalize_existing_diagnosis(diagnosis_payload or self.current_diagnosis())
        return list(payload.get("issues", []) or [])

    def issue_labels(self, diagnosis_payload: Optional[Mapping[str, Any]] = None) -> List[str]:
        payload = self._normalize_existing_diagnosis(diagnosis_payload or self.current_diagnosis())
        return list(payload.get("issue_labels", []) or [])

    def recommendations(self, diagnosis_payload: Optional[Mapping[str, Any]] = None) -> List[str]:
        payload = self._normalize_existing_diagnosis(diagnosis_payload or self.current_diagnosis())
        return list(payload.get("recommendations", []) or [])

    def consult_tips(self, diagnosis_payload: Optional[Mapping[str, Any]] = None) -> List[str]:
        payload = self._normalize_existing_diagnosis(diagnosis_payload or self.current_diagnosis())
        return list(payload.get("consult_tips", []) or [])

    def emergency_recommended(self, diagnosis_payload: Optional[Mapping[str, Any]] = None) -> bool:
        payload = self._normalize_existing_diagnosis(diagnosis_payload or self.current_diagnosis())
        return bool(payload.get("emergency_recommended", False))

    def emergency_number(self, diagnosis_payload: Optional[Mapping[str, Any]] = None) -> str:
        payload = self._normalize_existing_diagnosis(diagnosis_payload or self.current_diagnosis())
        return safe_str(payload.get("emergency_number"), "").strip()

    def has_issues(self, diagnosis_payload: Optional[Mapping[str, Any]] = None) -> bool:
        return bool(self.issue_keys(diagnosis_payload))

    def is_normal(self, diagnosis_payload: Optional[Mapping[str, Any]] = None) -> bool:
        return self.overall_severity(diagnosis_payload) == SEVERITY_NORMAL

    def needs_attention(self, diagnosis_payload: Optional[Mapping[str, Any]] = None) -> bool:
        severity = self.overall_severity(diagnosis_payload)
        return severity in {SEVERITY_ATTENTION, SEVERITY_WARNING}

    def is_critical(self, diagnosis_payload: Optional[Mapping[str, Any]] = None) -> bool:
        return self.overall_severity(diagnosis_payload) == SEVERITY_CRITICAL

    # ========================================================
    # UI payload builders
    # ========================================================

    def build_status_payload(
        self,
        measurements: Optional[Mapping[str, Any]] = None,
        diagnosis_payload: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Compact results-status payload for the results screen status card.
        """
        if diagnosis_payload is None:
            source_measurements = measurements or self.current_measurements()
            diagnosis_payload = self.build_diagnosis(source_measurements, store_in_app_state=False)

        diagnosis = self._normalize_existing_diagnosis(diagnosis_payload)

        combination = dict(diagnosis.get("combination_diagnosis", {}) or {})
        payload = {
            "title": self.status_title(diagnosis),
            "summary": self.summary_text(diagnosis),
            "severity": self.overall_severity(diagnosis),
            "issue_labels": self.issue_labels(diagnosis),
            "issue_count": len(self.issue_keys(diagnosis)),
            "emergency_recommended": self.emergency_recommended(diagnosis),
            "diagnosis_label": safe_str(combination.get("label"), "").strip(),
            "diagnosis_remark": safe_str(combination.get("remark"), "").strip(),
        }

        self.status_payload_ready.emit(deep_copy(payload))
        return payload

    def results_status_payload(
        self,
        measurements: Optional[Mapping[str, Any]] = None,
        diagnosis_payload: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Alias for results screen compatibility.
        """
        return self.build_status_payload(measurements=measurements, diagnosis_payload=diagnosis_payload)

    def build_consult_payload(
        self,
        measurements: Optional[Mapping[str, Any]] = None,
        diagnosis_payload: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Consult/help payload for the consult screen.
        """
        if diagnosis_payload is None:
            source_measurements = measurements or self.current_measurements()
            diagnosis_payload = self.build_diagnosis(source_measurements, store_in_app_state=False)

        diagnosis = self._normalize_existing_diagnosis(diagnosis_payload)
        payload = self._health_rules_service.consult_payload(
            measurements=measurements,
            diagnosis_payload=diagnosis,
        )
        payload["combination_diagnosis"] = deep_copy(diagnosis.get("combination_diagnosis", {}) or {})
        self.consult_payload_ready.emit(deep_copy(payload))
        return payload

    def consult_payload(
        self,
        measurements: Optional[Mapping[str, Any]] = None,
        diagnosis_payload: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Alias for consult screen compatibility.
        """
        return self.build_consult_payload(measurements=measurements, diagnosis_payload=diagnosis_payload)

    def dominant_issue_label(self, diagnosis_payload: Optional[Mapping[str, Any]] = None) -> str:
        labels = self.issue_labels(diagnosis_payload)
        return labels[0] if labels else ""

    def top_recommendations(
        self,
        diagnosis_payload: Optional[Mapping[str, Any]] = None,
        limit: int = 3,
    ) -> List[str]:
        recs = self.recommendations(diagnosis_payload)
        limit = max(0, int(limit))
        return recs[:limit]

    def metric_categories(
        self,
        diagnosis_payload: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        diagnosis = self._normalize_existing_diagnosis(diagnosis_payload or self.current_diagnosis())
        return deep_copy(diagnosis.get("metric_categories", {}) or {})

    def metric_category(self, metric_key: str, diagnosis_payload: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        categories = self.metric_categories(diagnosis_payload)
        value = categories.get(metric_key, {})
        return deep_copy(value if isinstance(value, dict) else {})

    # ========================================================
    # Health score / index helpers
    # ========================================================

    def calculate_health_index(
        self,
        diagnosis_payload: Optional[Mapping[str, Any]] = None,
    ) -> int:
        """
        Simple kiosk-friendly health index from 0 to 100.

        Intent:
        - normal => high score
        - attention/warning/critical => progressively lower score
        - useful later for publish_service and result summaries
        """
        diagnosis = self._normalize_existing_diagnosis(diagnosis_payload or self.current_diagnosis())
        severity = self.overall_severity(diagnosis)
        issue_count = len(self.issue_keys(diagnosis))

        if severity == SEVERITY_CRITICAL:
            base = 30
        elif severity == SEVERITY_WARNING:
            base = 55
        elif severity == SEVERITY_ATTENTION:
            base = 75
        elif severity == SEVERITY_NORMAL:
            base = 95
        else:
            base = 50

        penalty = min(issue_count * 7, 25)
        score = max(0, min(100, base - penalty))
        return int(score)

    def health_index_label(self, score: int) -> str:
        score = max(0, min(int(score), 100))
        if score >= 90:
            return "Excellent"
        if score >= 75:
            return "Good"
        if score >= 55:
            return "Needs Attention"
        return "Critical"

    def health_index_payload(
        self,
        diagnosis_payload: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        score = self.calculate_health_index(diagnosis_payload)
        return {
            "score": score,
            "label": self.health_index_label(score),
        }

    # ========================================================
    # Summary helpers for reports / publish
    # ========================================================

    def compact_summary_payload(
        self,
        measurements: Optional[Mapping[str, Any]] = None,
        diagnosis_payload: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Compact reusable summary block.
        """
        if diagnosis_payload is None:
            source_measurements = measurements or self.current_measurements()
            diagnosis_payload = self.build_diagnosis(source_measurements, store_in_app_state=False)

        diagnosis = self._normalize_existing_diagnosis(diagnosis_payload)
        return {
            "status_title": self.status_title(diagnosis),
            "summary": self.summary_text(diagnosis),
            "overall_severity": self.overall_severity(diagnosis),
            "issue_labels": self.issue_labels(diagnosis),
            "health_index": self.health_index_payload(diagnosis),
            "emergency_recommended": self.emergency_recommended(diagnosis),
            "emergency_number": self.emergency_number(diagnosis),
            "combination_diagnosis": deep_copy(diagnosis.get("combination_diagnosis", {}) or {}),
        }

    def interpret_average_metrics(self, averages: Mapping[str, Any]) -> Dict[str, Any]:
        """
        Helper for publish/analytics style interpretation of average measurements.
        """
        return self._health_rules_service.interpret_average_metrics(averages)

    # ========================================================
    # Current-session convenience flows
    # ========================================================

    def build_for_current_session(self, *, store_in_app_state: bool = True) -> Dict[str, Any]:
        """
        Build diagnosis from current AppState measurements.
        """
        return self.diagnose_current_session(store_in_app_state=store_in_app_state)

    def refresh_current_session_payloads(self) -> Dict[str, Any]:
        """
        Rebuild diagnosis and also return status + consult payloads together.
        Useful for results and consult screen refresh flows.
        """
        diagnosis = self.diagnose_current_session(store_in_app_state=True)
        status_payload = self.build_status_payload(diagnosis_payload=diagnosis)
        consult_payload = self.build_consult_payload(diagnosis_payload=diagnosis)

        return {
            "diagnosis": deep_copy(diagnosis),
            "status_payload": deep_copy(status_payload),
            "consult_payload": deep_copy(consult_payload),
        }

    # ========================================================
    # Diagnostics
    # ========================================================

    def diagnostics(self) -> Dict[str, Any]:
        diagnosis = self.current_diagnosis()
        return {
            "overall_severity": self.overall_severity(diagnosis),
            "status_title": self.status_title(diagnosis),
            "issue_count": len(self.issue_keys(diagnosis)),
            "issue_labels": self.issue_labels(diagnosis),
            "health_index": self.health_index_payload(diagnosis),
            "has_consult_tips": bool(self.consult_tips(diagnosis)),
            "emergency_recommended": self.emergency_recommended(diagnosis),
        }


# ============================================================
# Singleton accessor
# ============================================================

_DIAGNOSIS_SERVICE_SINGLETON: Optional[DiagnosisService] = None


def get_diagnosis_service(
    app_state: Optional[AppState] = None,
    threshold_service: Optional[ThresholdService] = None,
    health_rules_service: Optional[HealthRulesService] = None,
) -> DiagnosisService:
    global _DIAGNOSIS_SERVICE_SINGLETON
    if _DIAGNOSIS_SERVICE_SINGLETON is None:
        _DIAGNOSIS_SERVICE_SINGLETON = DiagnosisService(
            app_state=app_state,
            threshold_service=threshold_service,
            health_rules_service=health_rules_service,
        )
    return _DIAGNOSIS_SERVICE_SINGLETON