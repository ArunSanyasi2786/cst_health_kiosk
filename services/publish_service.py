"""
services/publish_service.py

Analytics and publish-insight service for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the main backend for the Publish screen
- It transforms stored session data into polished dashboard-ready analytics
- It supports:
    - publish overview cards
    - metric trend cards
    - severity / mode distributions
    - recent activity datasets
    - trend interpretation summaries
    - exportable publish snapshots
- It works for both demo mode and hardware mode because it uses stored completed sessions
- It keeps AppState synchronized with the latest publish summary when possible

Linked files:
- config.py
- core/app_state.py
- core/constants.py
- core/utils.py
- services/database_service.py
- services/diagnosis_service.py
- services/settings_service.py

Design goals:
- safe with small datasets
- useful for admin/publish dashboard
- consistent payloads for cards and charts
- stable on laptop demo and Raspberry Pi kiosk deployment
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Mapping, Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from config import APP_NAME, APP_VERSION, PATHS
from core.app_state import AppState, get_app_state
from core.constants import (
    METRIC_BMI,
    METRIC_HEIGHT,
    METRIC_LABELS,
    METRIC_PULSE,
    METRIC_RR,
    METRIC_SPO2,
    METRIC_TEMPERATURE,
    METRIC_UNITS,
    METRIC_WEIGHT,
    MODE_DEMO,
    MODE_HARDWARE,
    PRIMARY_METRIC_KEYS,
    PUBLISH_METRIC_COUNT_MINIMUM,
    SEVERITY_ATTENTION,
    SEVERITY_CRITICAL,
    SEVERITY_NORMAL,
    SEVERITY_UNKNOWN,
    SEVERITY_WARNING,
)
from core.logger import get_logger, log_exception
from core.utils import (
    build_export_path,
    deep_copy,
    ensure_directory,
    file_size_bytes,
    format_bytes,
    now_iso,
    parse_datetime,
    safe_float,
    safe_int,
    safe_str,
    write_json_file,
)
from services.database_service import DatabaseService, get_database_service
from services.diagnosis_service import DiagnosisService, get_diagnosis_service
from services.settings_service import SettingsService, get_settings_service

logger = get_logger(__name__)


# ============================================================
# Dataclasses
# ============================================================

@dataclass
class PublishExportResult:
    success: bool
    path: str
    size_bytes: int
    size_human: str
    message: str
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "path": self.path,
            "size_bytes": self.size_bytes,
            "size_human": self.size_human,
            "message": self.message,
            "metadata": deep_copy(self.metadata),
        }


# ============================================================
# Publish service
# ============================================================

class PublishService(QObject):
    """
    Central analytics/publish insight manager.

    Main responsibilities:
    - build publish dashboard summary from stored sessions
    - calculate metric trend/stat cards
    - expose chart-friendly datasets
    - provide a refresh timer for the publish screen
    - export publish summary snapshots as JSON
    """

    publish_summary_updated = pyqtSignal(dict)
    publish_insights_ready = pyqtSignal(list)
    publish_cards_ready = pyqtSignal(dict)
    publish_refresh_started = pyqtSignal(int)
    publish_refresh_stopped = pyqtSignal()
    publish_exported = pyqtSignal(dict)
    publish_error = pyqtSignal(str)

    _METRIC_KEYS = [
        METRIC_WEIGHT,
        METRIC_HEIGHT,
        METRIC_BMI,
        METRIC_TEMPERATURE,
        METRIC_SPO2,
        METRIC_PULSE,
        METRIC_RR,
    ]

    def __init__(
        self,
        app_state: Optional[AppState] = None,
        database_service: Optional[DatabaseService] = None,
        diagnosis_service: Optional[DiagnosisService] = None,
        settings_service: Optional[SettingsService] = None,
    ) -> None:
        super().__init__()

        self._logger = logger.bind(component="PublishService")
        self._app_state: AppState = app_state or get_app_state()
        self._database_service: DatabaseService = database_service or get_database_service()
        self._diagnosis_service: DiagnosisService = diagnosis_service or get_diagnosis_service()
        self._settings_service: SettingsService = settings_service or get_settings_service()

        self._summary_cache: Dict[str, Any] = {}
        self._refresh_interval_ms: int = self._resolve_refresh_interval()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(False)
        self._refresh_timer.timeout.connect(self.refresh_publish_summary)

        ensure_directory(PATHS.exports_dir)

    # ========================================================
    # Internal helpers
    # ========================================================

    def _resolve_refresh_interval(self) -> int:
        try:
            value = self._settings_service.get_setting("timing", "publish_refresh_interval_ms", 6000)
            return max(1000, safe_int(value, 6000))
        except Exception:
            return 6000

    def _push_summary_to_app_state(self, summary: Dict[str, Any]) -> None:
        """
        Best-effort synchronization into AppState.
        """
        try:
            setter = getattr(self._app_state, "set_publish_summary", None)
            if callable(setter):
                setter(summary)
                return

            updater = getattr(self._app_state, "update_publish_summary", None)
            if callable(updater):
                updater(summary)
        except Exception as exc:
            self._logger.debug("Could not push publish summary into AppState: %s", exc)

    def _record_measurements(self, record: Mapping[str, Any]) -> Dict[str, float]:
        measurements = record.get("measurements", {})
        if isinstance(measurements, Mapping) and measurements:
            return {
                metric: safe_float(measurements.get(metric), 0.0)
                for metric in self._METRIC_KEYS
            }

        # Fallback to flattened DB row values
        return {
            METRIC_WEIGHT: safe_float(record.get("weight"), 0.0),
            METRIC_HEIGHT: safe_float(record.get("height"), 0.0),
            METRIC_BMI: safe_float(record.get("bmi"), 0.0),
            METRIC_TEMPERATURE: safe_float(record.get("temperature"), 0.0),
            METRIC_SPO2: safe_float(record.get("spo2"), 0.0),
            METRIC_PULSE: safe_float(record.get("pulse_rate"), 0.0),
            METRIC_RR: safe_float(record.get("respiratory_rate"), 0.0),
        }

    def _meaningful_metric(self, metric_key: str, value: Any) -> bool:
        numeric = safe_float(value, 0.0)
        return numeric > 0.0

    def _record_timestamp(self, record: Mapping[str, Any]) -> Optional[datetime]:
        candidates = [
            record.get("completed_at"),
            record.get("created_at"),
            record.get("started_at"),
        ]
        for value in candidates:
            dt = parse_datetime(safe_str(value, ""))
            if dt is not None:
                return dt
        return None

    def _safe_record_label(self, record: Mapping[str, Any], index: int) -> str:
        dt = self._record_timestamp(record)
        if dt is not None:
            return dt.strftime("%m-%d")
        session_id = safe_str(record.get("session_id"), "")
        if session_id:
            return session_id[-6:]
        return f"R{index + 1}"

    def _sort_records_oldest_first(self, records: List[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
        return sorted(
            list(records),
            key=lambda item: self._record_timestamp(item) or datetime.min,
        )

    def _trend_direction(self, values: List[float], metric_key: str) -> str:
        """
        Compare first half vs second half and classify the general direction.
        """
        clean = [safe_float(v, 0.0) for v in values if safe_float(v, 0.0) > 0]
        if len(clean) < 4:
            return "stable"

        half = len(clean) // 2
        first_half = clean[:half]
        second_half = clean[half:]

        if not first_half or not second_half:
            return "stable"

        first_avg = mean(first_half)
        second_avg = mean(second_half)
        delta = second_avg - first_avg

        # Slightly metric-aware tolerance
        tolerance_map = {
            METRIC_WEIGHT: 0.8,
            METRIC_HEIGHT: 0.3,
            METRIC_BMI: 0.3,
            METRIC_TEMPERATURE: 0.15,
            METRIC_SPO2: 0.8,
            METRIC_PULSE: 2.0,
            METRIC_RR: 1.0,
        }
        tolerance = safe_float(tolerance_map.get(metric_key), 0.5)

        if delta > tolerance:
            return "up"
        if delta < -tolerance:
            return "down"
        return "stable"

    def _metric_statistics(self, records: List[Mapping[str, Any]], metric_key: str) -> Dict[str, Any]:
        ordered = self._sort_records_oldest_first(records)
        values: List[float] = []
        points: List[Dict[str, Any]] = []

        for idx, record in enumerate(ordered):
            value = safe_float(self._record_measurements(record).get(metric_key), 0.0)
            if not self._meaningful_metric(metric_key, value):
                continue
            values.append(value)
            points.append(
                {
                    "label": self._safe_record_label(record, idx),
                    "value": value,
                    "session_id": safe_str(record.get("session_id"), ""),
                    "timestamp": safe_str(record.get("completed_at") or record.get("created_at"), ""),
                }
            )

        if not values:
            return {
                "metric_key": metric_key,
                "metric_label": METRIC_LABELS.get(metric_key, metric_key.replace("_", " ").title()),
                "unit": METRIC_UNITS.get(metric_key, ""),
                "count": 0,
                "avg": 0.0,
                "min": 0.0,
                "max": 0.0,
                "latest": 0.0,
                "trend": "stable",
                "points": [],
                "has_data": False,
            }

        return {
            "metric_key": metric_key,
            "metric_label": METRIC_LABELS.get(metric_key, metric_key.replace("_", " ").title()),
            "unit": METRIC_UNITS.get(metric_key, ""),
            "count": len(values),
            "avg": round(mean(values), 2),
            "min": round(min(values), 2),
            "max": round(max(values), 2),
            "latest": round(values[-1], 2),
            "trend": self._trend_direction(values, metric_key),
            "points": points[-30:],
            "has_data": True,
        }

    def _daily_counts(self, records: List[Mapping[str, Any]], days: int = 7) -> List[Dict[str, Any]]:
        today = datetime.now().date()
        day_map: Dict[date, int] = {today - timedelta(days=i): 0 for i in range(days - 1, -1, -1)}

        for record in records:
            dt = self._record_timestamp(record)
            if dt is None:
                continue
            day_key = dt.date()
            if day_key in day_map:
                day_map[day_key] += 1

        result: List[Dict[str, Any]] = []
        for day_key, count in day_map.items():
            result.append(
                {
                    "date": day_key.isoformat(),
                    "label": day_key.strftime("%m-%d"),
                    "count": count,
                }
            )
        return result

    def _dominant_severity(self, severity_counts: Mapping[str, Any]) -> str:
        cleaned = {
            SEVERITY_NORMAL: safe_int(severity_counts.get(SEVERITY_NORMAL), 0),
            SEVERITY_ATTENTION: safe_int(severity_counts.get(SEVERITY_ATTENTION), 0),
            SEVERITY_WARNING: safe_int(severity_counts.get(SEVERITY_WARNING), 0),
            SEVERITY_CRITICAL: safe_int(severity_counts.get(SEVERITY_CRITICAL), 0),
        }

        if all(value == 0 for value in cleaned.values()):
            return SEVERITY_UNKNOWN

        return max(cleaned, key=lambda key: cleaned[key])

    def _build_overview_cards(
        self,
        db_summary: Mapping[str, Any],
        trend_interpretation: Mapping[str, Any],
        storage_summary: Mapping[str, Any],
    ) -> List[Dict[str, Any]]:
        total_records = safe_int(db_summary.get("total_records"), 0)
        completed_records = safe_int(db_summary.get("completed_records"), 0)
        severity_counts = dict(db_summary.get("severity_counts", {}) or {})
        mode_counts = dict(db_summary.get("mode_counts", {}) or {})
        dominant_severity = self._dominant_severity(severity_counts)

        db_size_human = safe_str(storage_summary.get("database", {}).get("db_size_human"), "0 bytes")

        cards = [
            {
                "key": "completed_records",
                "title": "Completed Records",
                "value": completed_records,
                "subtitle": f"Total records: {total_records}",
                "state": "primary",
            },
            {
                "key": "overall_trend",
                "title": "Overall Trend",
                "value": safe_str(trend_interpretation.get("trend_status_title"), "No Data"),
                "subtitle": safe_str(trend_interpretation.get("trend_summary"), "Not enough data for interpretation."),
                "state": safe_str(trend_interpretation.get("trend_severity"), SEVERITY_UNKNOWN),
            },
            {
                "key": "dominant_severity",
                "title": "Dominant Severity",
                "value": dominant_severity.replace("_", " ").title() if dominant_severity else "Unknown",
                "subtitle": "Based on completed session distribution",
                "state": dominant_severity,
            },
            {
                "key": "hardware_sessions",
                "title": "Hardware Sessions",
                "value": safe_int(mode_counts.get(MODE_HARDWARE), 0),
                "subtitle": f"Demo sessions: {safe_int(mode_counts.get(MODE_DEMO), 0)}",
                "state": "info",
            },
            {
                "key": "database_size",
                "title": "Database Size",
                "value": db_size_human,
                "subtitle": "Current SQLite storage footprint",
                "state": "neutral",
            },
        ]
        return cards

    def _build_metric_cards(self, metric_stats: Mapping[str, Any]) -> List[Dict[str, Any]]:
        cards: List[Dict[str, Any]] = []

        for metric_key in self._METRIC_KEYS:
            stat = dict(metric_stats.get(metric_key, {}) or {})
            cards.append(
                {
                    "key": metric_key,
                    "title": safe_str(stat.get("metric_label"), metric_key.replace("_", " ").title()),
                    "value": stat.get("avg", 0.0),
                    "unit": safe_str(stat.get("unit"), ""),
                    "latest": stat.get("latest", 0.0),
                    "min": stat.get("min", 0.0),
                    "max": stat.get("max", 0.0),
                    "count": safe_int(stat.get("count"), 0),
                    "trend": safe_str(stat.get("trend"), "stable"),
                    "state": "has_data" if bool(stat.get("has_data")) else "empty",
                }
            )
        return cards

    def _build_chart_payload(self, metric_stats: Mapping[str, Any], records: List[Mapping[str, Any]]) -> Dict[str, Any]:
        return {
            "daily_sessions": self._daily_counts(records, days=7),
            "metrics": {
                metric_key: deep_copy(dict(metric_stats.get(metric_key, {})).get("points", []))
                for metric_key in self._METRIC_KEYS
            },
        }

    def _generate_insights(
        self,
        db_summary: Mapping[str, Any],
        trend_interpretation: Mapping[str, Any],
        metric_stats: Mapping[str, Any],
        records: List[Mapping[str, Any]],
    ) -> List[str]:
        insights: List[str] = list(db_summary.get("insights", []) or [])

        completed_records = safe_int(db_summary.get("completed_records"), 0)
        if completed_records < PUBLISH_METRIC_COUNT_MINIMUM:
            insights.append(
                f"At least {PUBLISH_METRIC_COUNT_MINIMUM} completed records are recommended for stronger trend analysis."
            )

        trend_summary = safe_str(trend_interpretation.get("trend_summary"), "")
        if trend_summary:
            insights.append(trend_summary)

        trend_issue_labels = list(trend_interpretation.get("trend_issue_labels", []) or [])
        if trend_issue_labels:
            joined = ", ".join(safe_str(item, "") for item in trend_issue_labels if safe_str(item, ""))
            if joined:
                insights.append(f"Average-measurement interpretation highlights: {joined}.")

        severity_counts = dict(db_summary.get("severity_counts", {}) or {})
        critical_count = safe_int(severity_counts.get(SEVERITY_CRITICAL), 0)
        warning_count = safe_int(severity_counts.get(SEVERITY_WARNING), 0)
        attention_count = safe_int(severity_counts.get(SEVERITY_ATTENTION), 0)
        completed = max(1, completed_records)

        if critical_count > 0:
            insights.append(f"{critical_count} completed records are marked as critical.")
        if warning_count > 0:
            insights.append(f"{warning_count} completed records are marked as warning level.")
        if attention_count > 0 and critical_count == 0:
            insights.append(f"{attention_count} completed records currently fall into needs-attention ranges.")

        for metric_key in [METRIC_SPO2, METRIC_TEMPERATURE, METRIC_PULSE, METRIC_RR, METRIC_BMI]:
            stat = dict(metric_stats.get(metric_key, {}) or {})
            if not stat.get("has_data"):
                continue

            trend = safe_str(stat.get("trend"), "stable")
            label = safe_str(stat.get("metric_label"), metric_key)
            avg_value = stat.get("avg", 0.0)

            if trend == "up":
                insights.append(f"{label} shows an upward trend in recent completed records.")
            elif trend == "down":
                insights.append(f"{label} shows a downward trend in recent completed records.")

            if metric_key == METRIC_SPO2 and safe_float(avg_value, 0.0) < 95:
                insights.append("Average SpO₂ remains below the ideal normal threshold.")
            elif metric_key == METRIC_TEMPERATURE and safe_float(avg_value, 0.0) >= 37.1:
                insights.append("Average temperature indicates a mild-to-elevated fever trend.")
            elif metric_key == METRIC_PULSE and safe_float(avg_value, 0.0) > 100:
                insights.append("Average pulse rate is above the typical normal resting range.")
            elif metric_key == METRIC_RR and safe_float(avg_value, 0.0) > 20:
                insights.append("Average respiratory rate is above the normal resting range.")
            elif metric_key == METRIC_BMI and safe_float(avg_value, 0.0) >= 25:
                insights.append("Average BMI falls outside the ideal normal range.")

        recent_activity = self._daily_counts(records, days=7)
        active_days = sum(1 for item in recent_activity if safe_int(item.get("count"), 0) > 0)
        if active_days > 0:
            insights.append(f"Measurements were recorded on {active_days} of the last 7 days.")

        # Deduplicate while preserving order
        deduped: List[str] = []
        seen = set()
        for item in insights:
            cleaned = safe_str(item, "").strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                deduped.append(cleaned)
        return deduped

    def _build_publish_summary(self) -> Dict[str, Any]:
        db_summary = self._database_service.get_basic_publish_summary()
        storage_summary = self._database_service.get_storage_summary()
        records = self._database_service.get_sessions_for_publish(limit=250)

        averages = dict(db_summary.get("averages", {}) or {})
        trend_interpretation = self._diagnosis_service.interpret_average_metrics(averages)

        metric_stats = {
            metric_key: self._metric_statistics(records, metric_key)
            for metric_key in self._METRIC_KEYS
        }

        readiness = {
            "minimum_required_records": PUBLISH_METRIC_COUNT_MINIMUM,
            "completed_records": safe_int(db_summary.get("completed_records"), 0),
            "enough_for_trend_analysis": safe_int(db_summary.get("completed_records"), 0) >= PUBLISH_METRIC_COUNT_MINIMUM,
            "has_any_completed_records": safe_int(db_summary.get("completed_records"), 0) > 0,
        }

        overview_cards = self._build_overview_cards(
            db_summary=db_summary,
            trend_interpretation=trend_interpretation,
            storage_summary=storage_summary,
        )
        metric_cards = self._build_metric_cards(metric_stats)
        charts = self._build_chart_payload(metric_stats, records)
        insights = self._generate_insights(db_summary, trend_interpretation, metric_stats, records)

        summary = {
            "generated_at": now_iso(),
            "app": {
                "name": APP_NAME,
                "version": APP_VERSION,
            },
            "readiness": readiness,
            "overview_cards": overview_cards,
            "metric_cards": metric_cards,
            "charts": charts,
            "insights": insights,
            "database_summary": deep_copy(db_summary),
            "storage_summary": deep_copy(storage_summary),
            "trend_interpretation": deep_copy(trend_interpretation),
            "metric_statistics": deep_copy(metric_stats),
            "recent_records_count": len(records),
            "recent_records": [
                {
                    "session_id": safe_str(record.get("session_id"), ""),
                    "mode": safe_str(record.get("mode"), ""),
                    "status": safe_str(record.get("status"), ""),
                    "completed_at": safe_str(record.get("completed_at"), ""),
                    "overall_severity": safe_str(record.get("overall_severity"), ""),
                }
                for record in records[:20]
            ],
        }
        return summary

    # ========================================================
    # Public summary accessors
    # ========================================================

    def refresh_publish_summary(self) -> Dict[str, Any]:
        """
        Rebuild the complete publish dashboard payload.
        """
        try:
            summary = self._build_publish_summary()
            self._summary_cache = deep_copy(summary)
            self._push_summary_to_app_state(summary)

            self.publish_summary_updated.emit(deep_copy(summary))
            self.publish_insights_ready.emit(deep_copy(summary.get("insights", [])))
            self.publish_cards_ready.emit(
                {
                    "overview_cards": deep_copy(summary.get("overview_cards", [])),
                    "metric_cards": deep_copy(summary.get("metric_cards", [])),
                }
            )
            return summary

        except Exception as exc:
            log_exception(self._logger, "Failed to refresh publish summary", exc)
            self.publish_error.emit(str(exc))
            return deep_copy(self._summary_cache)

    def current_publish_summary(self) -> Dict[str, Any]:
        if self._summary_cache:
            return deep_copy(self._summary_cache)
        return self.refresh_publish_summary()

    def get_publish_summary(self) -> Dict[str, Any]:
        return self.current_publish_summary()

    def overview_cards(self) -> List[Dict[str, Any]]:
        summary = self.current_publish_summary()
        return deep_copy(summary.get("overview_cards", []))

    def metric_cards(self) -> List[Dict[str, Any]]:
        summary = self.current_publish_summary()
        return deep_copy(summary.get("metric_cards", []))

    def insights(self) -> List[str]:
        summary = self.current_publish_summary()
        return list(summary.get("insights", []) or [])

    def chart_payload(self) -> Dict[str, Any]:
        summary = self.current_publish_summary()
        return deep_copy(summary.get("charts", {}))

    def trend_interpretation(self) -> Dict[str, Any]:
        summary = self.current_publish_summary()
        return deep_copy(summary.get("trend_interpretation", {}))

    def publish_status_banner_payload(self) -> Dict[str, Any]:
        summary = self.current_publish_summary()
        readiness = dict(summary.get("readiness", {}) or {})
        trend = dict(summary.get("trend_interpretation", {}) or {})

        enough = bool(readiness.get("enough_for_trend_analysis", False))
        completed = safe_int(readiness.get("completed_records"), 0)
        minimum = safe_int(readiness.get("minimum_required_records"), PUBLISH_METRIC_COUNT_MINIMUM)

        return {
            "ready": enough,
            "title": safe_str(trend.get("trend_status_title"), "No Data"),
            "summary": safe_str(trend.get("trend_summary"), "Not enough completed records for publish analysis."),
            "severity": safe_str(trend.get("trend_severity"), SEVERITY_UNKNOWN),
            "completed_records": completed,
            "minimum_required_records": minimum,
        }

    def metric_detail_payload(self, metric_key: str) -> Dict[str, Any]:
        summary = self.current_publish_summary()
        stats = dict(summary.get("metric_statistics", {}) or {})
        return deep_copy(dict(stats.get(metric_key, {})))

    # ========================================================
    # Auto refresh
    # ========================================================

    def start_auto_refresh(self, interval_ms: Optional[int] = None) -> int:
        if interval_ms is not None:
            self._refresh_interval_ms = max(1000, safe_int(interval_ms, self._refresh_interval_ms))
        else:
            self._refresh_interval_ms = self._resolve_refresh_interval()

        self._refresh_timer.start(self._refresh_interval_ms)
        self.publish_refresh_started.emit(self._refresh_interval_ms)
        self.refresh_publish_summary()
        return self._refresh_interval_ms

    def stop_auto_refresh(self) -> None:
        if self._refresh_timer.isActive():
            self._refresh_timer.stop()
            self.publish_refresh_stopped.emit()

    def is_auto_refresh_active(self) -> bool:
        return self._refresh_timer.isActive()

    def set_refresh_interval_ms(self, interval_ms: int) -> int:
        self._refresh_interval_ms = max(1000, safe_int(interval_ms, 6000))
        if self._refresh_timer.isActive():
            self._refresh_timer.start(self._refresh_interval_ms)
        return self._refresh_interval_ms

    # ========================================================
    # Export helper
    # ========================================================

    def export_publish_snapshot_json(self, *, label: str = "publish_snapshot") -> Dict[str, Any]:
        """
        Export the current publish summary as JSON into data/exports/.
        """
        try:
            summary = self.current_publish_summary()
            output_path = build_export_path(label=label, extension="json")
            ensure_directory(Path(output_path).parent)

            payload = {
                "exported_at": now_iso(),
                "publish_summary": deep_copy(summary),
            }
            write_json_file(output_path, payload)

            size_bytes = file_size_bytes(Path(output_path))
            result = PublishExportResult(
                success=True,
                path=str(output_path),
                size_bytes=size_bytes,
                size_human=format_bytes(size_bytes),
                message="Publish snapshot exported successfully.",
                metadata={
                    "record_count": safe_int(summary.get("database_summary", {}).get("completed_records"), 0),
                },
            ).to_dict()

            self.publish_exported.emit(deep_copy(result))
            return result

        except Exception as exc:
            log_exception(self._logger, "Failed to export publish snapshot", exc)
            self.publish_error.emit(str(exc))
            return PublishExportResult(
                success=False,
                path=str(build_export_path(label=label, extension="json")),
                size_bytes=0,
                size_human=format_bytes(0),
                message=str(exc),
                metadata={},
            ).to_dict()

    # ========================================================
    # Diagnostics
    # ========================================================

    def diagnostics(self) -> Dict[str, Any]:
        summary = self.current_publish_summary()
        readiness = dict(summary.get("readiness", {}) or {})

        return {
            "refresh_interval_ms": self._refresh_interval_ms,
            "auto_refresh_active": self.is_auto_refresh_active(),
            "cached": bool(self._summary_cache),
            "completed_records": safe_int(readiness.get("completed_records"), 0),
            "minimum_required_records": safe_int(readiness.get("minimum_required_records"), PUBLISH_METRIC_COUNT_MINIMUM),
            "enough_for_trend_analysis": bool(readiness.get("enough_for_trend_analysis", False)),
            "insight_count": len(summary.get("insights", []) or []),
        }


# ============================================================
# Singleton accessor
# ============================================================

_PUBLISH_SERVICE_SINGLETON: Optional[PublishService] = None


def get_publish_service(
    app_state: Optional[AppState] = None,
    database_service: Optional[DatabaseService] = None,
    diagnosis_service: Optional[DiagnosisService] = None,
    settings_service: Optional[SettingsService] = None,
) -> PublishService:
    global _PUBLISH_SERVICE_SINGLETON
    if _PUBLISH_SERVICE_SINGLETON is None:
        _PUBLISH_SERVICE_SINGLETON = PublishService(
            app_state=app_state,
            database_service=database_service,
            diagnosis_service=diagnosis_service,
            settings_service=settings_service,
        )
    return _PUBLISH_SERVICE_SINGLETON
