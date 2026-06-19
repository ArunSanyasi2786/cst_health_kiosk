"""
services/health_rules_service.py

Rule-based health interpretation service for the
CST Health Monitoring Station kiosk.

Why this file matters:
- It is the main clinical-style rule engine used by the kiosk
- It translates classified measurements into:
    - overall severity
    - issue list
    - readable health status
    - recommendations
    - consult tips
    - emergency guidance
- It keeps the logic centralized so later files stay consistent:
    - diagnosis_service.py
    - consult_screen.py
    - results_screen.py
    - publish_service.py
    - report_service.py
- It works for both demo mode and hardware mode because it only depends on measurements,
  threshold classifications, and rule mappings

Linked files:
- core/app_state.py
- core/constants.py
- core/utils.py
- services/threshold_service.py

Design goals:
- strong but understandable rule engine
- generic health guidance, not medical diagnosis
- consistent output structure across the app
- easy to reuse from later services and screens
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from config import EMERGENCY_NUMBER
from core.app_state import AppState, get_app_state
from core.constants import (
    DIAGNOSIS_ISSUE_LABELS,
    EMPTY_DIAGNOSIS_PAYLOAD,
    GENERIC_TIPS_BMI,
    GENERIC_TIPS_FEVER,
    GENERIC_TIPS_LOW_SPO2,
    GENERIC_TIPS_NORMAL,
    GENERIC_TIPS_PULSE,
    GENERIC_TIPS_RR,
    HEALTH_STATUS_CRITICAL,
    HEALTH_STATUS_NEEDS_ATTENTION,
    HEALTH_STATUS_NORMAL,
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
    METRIC_PULSE,
    METRIC_RR,
    METRIC_SPO2,
    METRIC_TEMPERATURE,
    SEVERITY_ATTENTION,
    SEVERITY_CRITICAL,
    SEVERITY_NORMAL,
    SEVERITY_ORDER,
    SEVERITY_PRIORITY,
    SEVERITY_UNKNOWN,
    SEVERITY_WARNING,
)
from core.logger import get_logger, log_exception
from core.utils import deep_copy, normalize_measurement_payload, safe_float, safe_str
from services.threshold_service import ThresholdService, get_threshold_service

logger = get_logger(__name__)


# ============================================================
# Dataclasses
# ============================================================

@dataclass
class RuleResult:
    """
    Rule evaluation result used by later services/screens.
    """
    overall_severity: str
    status_title: str
    summary: str
    issues: List[str]
    issue_labels: List[str]
    recommendations: List[str]
    metric_categories: Dict[str, Any]
    consult_tips: List[str]
    emergency_recommended: bool
    emergency_number: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_severity": self.overall_severity,
            "status_title": self.status_title,
            "summary": self.summary,
            "issues": list(self.issues),
            "issue_labels": list(self.issue_labels),
            "recommendations": list(self.recommendations),
            "metric_categories": deep_copy(self.metric_categories),
            "consult_tips": list(self.consult_tips),
            "emergency_recommended": self.emergency_recommended,
            "emergency_number": self.emergency_number,
        }


# ============================================================
# Health rules service
# ============================================================

class HealthRulesService(QObject):
    """
    Central rule-based health interpretation service.

    Main responsibilities:
    - classify measurements via ThresholdService
    - convert metric classifications into issue keys
    - prioritize the most important issues
    - produce generic recommendation text
    - produce consult/emergency tips
    - generate a diagnosis payload compatible with AppState and later DiagnosisService
    """

    rules_evaluated = pyqtSignal(dict)
    diagnosis_built = pyqtSignal(dict)
    consult_tips_ready = pyqtSignal(list)
    rules_error = pyqtSignal(str)

    def __init__(
        self,
        app_state: Optional[AppState] = None,
        threshold_service: Optional[ThresholdService] = None,
    ) -> None:
        super().__init__()

        self._logger = logger.bind(component="HealthRulesService")
        self._app_state: AppState = app_state or get_app_state()
        self._threshold_service: ThresholdService = threshold_service or get_threshold_service()

        self._issue_recommendation_map: Dict[str, List[str]] = self._build_issue_recommendation_map()
        self._issue_metric_map: Dict[str, str] = self._build_issue_metric_map()

    # ========================================================
    # Static rule maps
    # ========================================================

    def _build_issue_metric_map(self) -> Dict[str, str]:
        return {
            ISSUE_LOW_SPO2: METRIC_SPO2,
            ISSUE_CRITICAL_SPO2: METRIC_SPO2,
            ISSUE_FEVER: METRIC_TEMPERATURE,
            ISSUE_HIGH_FEVER: METRIC_TEMPERATURE,
            ISSUE_CRITICAL_FEVER: METRIC_TEMPERATURE,
            ISSUE_LOW_PULSE: METRIC_PULSE,
            ISSUE_HIGH_PULSE: METRIC_PULSE,
            ISSUE_LOW_RR: METRIC_RR,
            ISSUE_HIGH_RR: METRIC_RR,
            ISSUE_BMI_UNDERWEIGHT: METRIC_BMI,
            ISSUE_BMI_OVERWEIGHT: METRIC_BMI,
            ISSUE_BMI_OBESE: METRIC_BMI,
        }

    def _build_issue_recommendation_map(self) -> Dict[str, List[str]]:
        """
        Generic kiosk-safe guidance. These are not treatment instructions,
        but practical prompts for the user.
        """
        return {
            ISSUE_CRITICAL_SPO2: [
                "Seek immediate medical attention.",
                "Sit upright and remain calm while help is arranged.",
                "Use emergency support if breathing becomes difficult.",
            ],
            ISSUE_LOW_SPO2: [
                "Rest and repeat the check if needed.",
                "Avoid exertion until oxygen level improves.",
                "Consult a healthcare professional if symptoms persist.",
            ],
            ISSUE_CRITICAL_FEVER: [
                "Seek urgent medical attention immediately.",
                "Stay hydrated and avoid heavy activity.",
                "Use emergency support if symptoms worsen rapidly.",
            ],
            ISSUE_HIGH_FEVER: [
                "Rest and monitor temperature again.",
                "Increase fluid intake.",
                "Seek care if fever persists or rises further.",
            ],
            ISSUE_FEVER: [
                "Rest and drink fluids.",
                "Monitor your temperature again later.",
                "Seek advice if you feel unwell or symptoms continue.",
            ],
            ISSUE_LOW_PULSE: [
                "Sit and rest for a few minutes.",
                "Repeat the check after remaining still.",
                "Consult a professional if low pulse persists or feels unusual.",
            ],
            ISSUE_HIGH_PULSE: [
                "Remain seated and calm for a few minutes.",
                "Avoid physical exertion until stable.",
                "Consult a healthcare professional if elevated pulse persists.",
            ],
            ISSUE_LOW_RR: [
                "Relax and recheck while sitting comfortably.",
                "Avoid holding breath or changing posture abruptly.",
                "Seek advice if breathing pattern feels unusual.",
            ],
            ISSUE_HIGH_RR: [
                "Slow down and breathe calmly.",
                "Sit upright and avoid exertion.",
                "Seek care if rapid breathing continues or worsens.",
            ],
            ISSUE_BMI_UNDERWEIGHT: [
                "Maintain a balanced diet and healthy meal schedule.",
                "Track your nutrition and overall energy levels.",
                "Seek professional advice for long-term weight concerns.",
            ],
            ISSUE_BMI_OVERWEIGHT: [
                "Increase regular physical activity when possible.",
                "Follow a balanced diet and healthy routine.",
                "Monitor weight and BMI regularly.",
            ],
            ISSUE_BMI_OBESE: [
                "Adopt a structured healthy lifestyle plan.",
                "Increase physical activity gradually and safely.",
                "Seek professional support for long-term weight management.",
            ],
        }

    # ========================================================
    # Basic helpers
    # ========================================================

    def _issue_label(self, issue_key: str) -> str:
        return DIAGNOSIS_ISSUE_LABELS.get(issue_key, issue_key.replace("_", " ").title())

    def _severity_rank(self, severity: str) -> int:
        return SEVERITY_PRIORITY.get(safe_str(severity, SEVERITY_UNKNOWN).strip().lower(), -1)

    def _max_severity(self, severities: List[str]) -> str:
        if not severities:
            return SEVERITY_UNKNOWN

        highest = severities[0]
        for severity in severities[1:]:
            if self._severity_rank(severity) > self._severity_rank(highest):
                highest = severity
        return highest

    def _deduplicate_preserve_order(self, items: List[str]) -> List[str]:
        seen = set()
        ordered: List[str] = []
        for item in items:
            cleaned = safe_str(item, "").strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            ordered.append(cleaned)
        return ordered

    def _priority_sort_issues(
        self,
        issues: List[str],
        metric_categories: Mapping[str, Any],
    ) -> List[str]:
        """
        Sort issues according to diagnosis priority order from ThresholdService,
        then by severity.
        """
        priority_order = self._threshold_service.diagnosis_priority_order()

        def _issue_sort_key(issue_key: str) -> tuple[int, int, str]:
            metric_key = self._issue_metric_map.get(issue_key, "")
            try:
                priority_index = priority_order.index(metric_key)
            except ValueError:
                priority_index = len(priority_order) + 10

            metric_payload = metric_categories.get(metric_key, {})
            severity = safe_str(metric_payload.get("severity"), SEVERITY_UNKNOWN)
            severity_rank = -self._severity_rank(severity)  # negative for descending severity
            return (priority_index, severity_rank, issue_key)

        return sorted(self._deduplicate_preserve_order(issues), key=_issue_sort_key)

    # ========================================================
    # Classification and issue extraction
    # ========================================================

    def classify_measurements(self, measurements: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
        """
        Proxy to ThresholdService for consistent metric category structure.
        """
        normalized = normalize_measurement_payload(measurements)
        return self._threshold_service.classify_measurements(normalized)

    def extract_issues_from_classifications(
        self,
        classifications: Mapping[str, Any],
    ) -> List[str]:
        """
        Collect issue keys from metric classifications.
        """
        issues: List[str] = []

        for metric_key, payload in classifications.items():
            if not isinstance(payload, Mapping):
                continue
            issue_key = safe_str(payload.get("issue_key"), "").strip()
            is_normal = bool(payload.get("is_normal", False))

            if issue_key and not is_normal:
                issues.append(issue_key)

        return self._deduplicate_preserve_order(issues)

    def derive_overall_severity(
        self,
        classifications: Mapping[str, Any],
    ) -> str:
        severities: List[str] = []

        for payload in classifications.values():
            if not isinstance(payload, Mapping):
                continue
            severity = safe_str(payload.get("severity"), "").strip().lower()
            if severity:
                severities.append(severity)

        if not severities:
            return SEVERITY_UNKNOWN

        return self._max_severity(severities)

    def derive_status_title(self, overall_severity: str) -> str:
        severity = safe_str(overall_severity, SEVERITY_UNKNOWN).strip().lower()

        if severity == SEVERITY_CRITICAL:
            return HEALTH_STATUS_CRITICAL
        if severity in {SEVERITY_WARNING, SEVERITY_ATTENTION}:
            return HEALTH_STATUS_NEEDS_ATTENTION
        if severity == SEVERITY_NORMAL:
            return HEALTH_STATUS_NORMAL
        return "No Data"

    def derive_summary_text(
        self,
        overall_severity: str,
        issues: List[str],
    ) -> str:
        """
        Summary text shown on results or diagnosis screen.
        """
        messages = self._threshold_service.diagnosis_messages()
        severity = safe_str(overall_severity, SEVERITY_UNKNOWN).strip().lower()

        if severity == SEVERITY_CRITICAL:
            return messages.get("critical_message", "Critical condition detected. Seek immediate help.")

        if severity in {SEVERITY_WARNING, SEVERITY_ATTENTION} or issues:
            return messages.get("needs_attention_message", "Some parameters need attention. Please review advice.")

        if severity == SEVERITY_NORMAL:
            return messages.get("normal_message", "All measured parameters are within acceptable range.")

        return "No measurements available yet."

    # ========================================================
    # Recommendation builders
    # ========================================================

    def recommendations_for_issues(self, issues: List[str]) -> List[str]:
        recommendations: List[str] = []
        for issue_key in issues:
            recommendations.extend(self._issue_recommendation_map.get(issue_key, []))
        return self._deduplicate_preserve_order(recommendations)

    def consult_tips_for_issues(self, issues: List[str]) -> List[str]:
        """
        Generic consult/help tips used by consult screen.
        """
        tips: List[str] = []

        if not issues:
            tips.extend(GENERIC_TIPS_NORMAL)

        for issue_key in issues:
            if issue_key in {ISSUE_LOW_SPO2, ISSUE_CRITICAL_SPO2}:
                tips.extend(GENERIC_TIPS_LOW_SPO2)
            elif issue_key in {ISSUE_FEVER, ISSUE_HIGH_FEVER, ISSUE_CRITICAL_FEVER}:
                tips.extend(GENERIC_TIPS_FEVER)
            elif issue_key in {ISSUE_LOW_PULSE, ISSUE_HIGH_PULSE}:
                tips.extend(GENERIC_TIPS_PULSE)
            elif issue_key in {ISSUE_LOW_RR, ISSUE_HIGH_RR}:
                tips.extend(GENERIC_TIPS_RR)
            elif issue_key in {ISSUE_BMI_UNDERWEIGHT, ISSUE_BMI_OVERWEIGHT, ISSUE_BMI_OBESE}:
                tips.extend(GENERIC_TIPS_BMI)

        return self._deduplicate_preserve_order(tips)

    def emergency_recommended(self, overall_severity: str, issues: List[str]) -> bool:
        severity = safe_str(overall_severity, SEVERITY_UNKNOWN).strip().lower()
        if severity == SEVERITY_CRITICAL:
            return True

        critical_issue_set = {
            ISSUE_CRITICAL_SPO2,
            ISSUE_CRITICAL_FEVER,
        }
        return any(issue in critical_issue_set for issue in issues)

    # ========================================================
    # Composite diagnosis builders
    # ========================================================

    def build_rule_result(
        self,
        measurements: Mapping[str, Any],
        classifications: Optional[Mapping[str, Any]] = None,
    ) -> RuleResult:
        """
        Main rules entry point.

        Returns a standardized interpretation payload:
        - metric categories
        - issues
        - recommendations
        - summary
        - consult tips
        """
        normalized_measurements = normalize_measurement_payload(measurements)
        metric_categories = (
            deep_copy(dict(classifications))
            if classifications is not None
            else self.classify_measurements(normalized_measurements)
        )

        raw_issues = self.extract_issues_from_classifications(metric_categories)
        sorted_issues = self._priority_sort_issues(raw_issues, metric_categories)
        issue_labels = [self._issue_label(issue) for issue in sorted_issues]

        overall_severity = self.derive_overall_severity(metric_categories)
        status_title = self.derive_status_title(overall_severity)
        summary = self.derive_summary_text(overall_severity, sorted_issues)
        recommendations = self.recommendations_for_issues(sorted_issues)
        consult_tips = self.consult_tips_for_issues(sorted_issues)
        emergency_needed = self.emergency_recommended(overall_severity, sorted_issues)

        result = RuleResult(
            overall_severity=overall_severity,
            status_title=status_title,
            summary=summary,
            issues=sorted_issues,
            issue_labels=issue_labels,
            recommendations=recommendations,
            metric_categories=deep_copy(metric_categories),
            consult_tips=consult_tips,
            emergency_recommended=emergency_needed,
            emergency_number=EMERGENCY_NUMBER,
        )

        payload = result.to_dict()
        self.rules_evaluated.emit(payload)
        return result

    def build_diagnosis(
        self,
        measurements: Mapping[str, Any],
        classifications: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Build a diagnosis payload compatible with:
        - AppState
        - later DiagnosisService
        - report generation
        - results screen status card
        """
        result = self.build_rule_result(measurements, classifications=classifications)
        payload = result.to_dict()

        # Keep shape aligned with EMPTY_DIAGNOSIS_PAYLOAD and later UI usage
        diagnosis_payload = {
            "overall_severity": payload["overall_severity"],
            "status_title": payload["status_title"],
            "issues": payload["issues"],
            "issue_labels": payload["issue_labels"],
            "recommendations": payload["recommendations"],
            "summary": payload["summary"],
            "metric_categories": payload["metric_categories"],
            "consult_tips": payload["consult_tips"],
            "emergency_recommended": payload["emergency_recommended"],
            "emergency_number": payload["emergency_number"],
        }

        self.diagnosis_built.emit(deep_copy(diagnosis_payload))
        return diagnosis_payload

    def build_diagnosis_for_current_session(self) -> Dict[str, Any]:
        """
        Convenience helper for current AppState measurements.
        """
        measurements = self._app_state.current_measurements()
        payload = self.build_diagnosis(measurements)
        return payload

    def build_and_store_current_session_diagnosis(self) -> Dict[str, Any]:
        """
        Build diagnosis from current session measurements and write it into AppState.
        """
        diagnosis = self.build_diagnosis_for_current_session()
        self._app_state.set_diagnosis(diagnosis)
        return diagnosis

    # ========================================================
    # Consult screen helpers
    # ========================================================

    def consult_payload(
        self,
        measurements: Optional[Mapping[str, Any]] = None,
        diagnosis_payload: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Build a consult/help payload for the consult screen.

        Includes:
        - emergency number
        - whether emergency recommendation is active
        - consult tips
        - compact status title
        """
        if diagnosis_payload is None:
            source_measurements = measurements or self._app_state.current_measurements()
            diagnosis_payload = self.build_diagnosis(source_measurements)

        payload = {
            "status_title": safe_str(diagnosis_payload.get("status_title"), HEALTH_STATUS_NORMAL),
            "summary": safe_str(diagnosis_payload.get("summary"), ""),
            "consult_tips": deep_copy(diagnosis_payload.get("consult_tips", [])),
            "emergency_recommended": bool(diagnosis_payload.get("emergency_recommended", False)),
            "emergency_number": safe_str(diagnosis_payload.get("emergency_number"), EMERGENCY_NUMBER),
            "issue_labels": deep_copy(diagnosis_payload.get("issue_labels", [])),
        }

        self.consult_tips_ready.emit(list(payload["consult_tips"]))
        return payload

    # ========================================================
    # UI-oriented helper methods
    # ========================================================

    def dominant_issue_label(
        self,
        diagnosis_payload: Optional[Mapping[str, Any]] = None,
    ) -> str:
        if diagnosis_payload is None:
            diagnosis_payload = self._app_state.current_diagnosis()

        labels = diagnosis_payload.get("issue_labels", [])
        if isinstance(labels, list) and labels:
            return safe_str(labels[0], "")
        return ""

    def metric_highlight_payload(
        self,
        measurements: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """
        Useful for results/detail screens.
        Returns category and severity for the major detailed metrics.
        """
        classifications = self.classify_measurements(measurements)

        return {
            METRIC_BMI: deep_copy(classifications.get(METRIC_BMI, {})),
            METRIC_TEMPERATURE: deep_copy(classifications.get(METRIC_TEMPERATURE, {})),
            METRIC_SPO2: deep_copy(classifications.get(METRIC_SPO2, {})),
            METRIC_PULSE: deep_copy(classifications.get(METRIC_PULSE, {})),
            METRIC_RR: deep_copy(classifications.get(METRIC_RR, {})),
        }

    def results_status_payload(
        self,
        measurements: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Compact status payload for results screen card.
        """
        source_measurements = measurements or self._app_state.current_measurements()
        diagnosis = self.build_diagnosis(source_measurements)

        return {
            "title": safe_str(diagnosis.get("status_title"), HEALTH_STATUS_NORMAL),
            "summary": safe_str(diagnosis.get("summary"), ""),
            "severity": safe_str(diagnosis.get("overall_severity"), SEVERITY_UNKNOWN),
            "issue_labels": deep_copy(diagnosis.get("issue_labels", [])),
            "emergency_recommended": bool(diagnosis.get("emergency_recommended", False)),
        }

    # ========================================================
    # Publish / analytics helper
    # ========================================================

    def interpret_average_metrics(
        self,
        averages: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """
        Useful for publish_service later.
        It applies the same rule engine to average values to derive
        general trend hints.
        """
        normalized = normalize_measurement_payload(averages)
        diagnosis = self.build_diagnosis(normalized)

        return {
            "averages": deep_copy(normalized),
            "trend_status_title": diagnosis.get("status_title", ""),
            "trend_summary": diagnosis.get("summary", ""),
            "trend_severity": diagnosis.get("overall_severity", SEVERITY_UNKNOWN),
            "trend_issue_labels": deep_copy(diagnosis.get("issue_labels", [])),
        }

    # ========================================================
    # Empty/default helpers
    # ========================================================

    def empty_diagnosis_payload(self) -> Dict[str, Any]:
        payload = deep_copy(EMPTY_DIAGNOSIS_PAYLOAD)
        payload.update(
            {
                "consult_tips": [],
                "emergency_recommended": False,
                "emergency_number": EMERGENCY_NUMBER,
            }
        )
        return payload

    # ========================================================
    # Diagnostics
    # ========================================================

    def diagnostics(self) -> Dict[str, Any]:
        current_measurements = self._app_state.current_measurements()
        current_diagnosis = self._app_state.current_diagnosis()

        return {
            "current_measurements": deep_copy(current_measurements),
            "current_diagnosis": deep_copy(current_diagnosis),
            "issue_map_size": len(self._issue_metric_map),
            "recommendation_map_size": len(self._issue_recommendation_map),
            "priority_order": self._threshold_service.diagnosis_priority_order(),
        }


# ============================================================
# Singleton accessor
# ============================================================

_HEALTH_RULES_SERVICE_SINGLETON: Optional[HealthRulesService] = None


def get_health_rules_service(
    app_state: Optional[AppState] = None,
    threshold_service: Optional[ThresholdService] = None,
) -> HealthRulesService:
    global _HEALTH_RULES_SERVICE_SINGLETON
    if _HEALTH_RULES_SERVICE_SINGLETON is None:
        _HEALTH_RULES_SERVICE_SINGLETON = HealthRulesService(
            app_state=app_state,
            threshold_service=threshold_service,
        )
    return _HEALTH_RULES_SERVICE_SINGLETON