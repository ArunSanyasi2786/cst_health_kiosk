"""
services/export_service.py

Export management service for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the main backend for exporting kiosk data from the admin side
- It supports exporting:
    - current session
    - recent session records
    - settings
    - calibration
    - thresholds
    - diagnosis snapshot
    - full admin bundle ZIP
- It writes exports into data/exports/
- It keeps exports linked with:
    - AppState
    - DatabaseService
    - SettingsService
    - CalibrationService
    - ThresholdService
    - DiagnosisService
    - StorageService
- It provides JSON, CSV, and ZIP outputs so later screens can call it directly

Linked files:
- config.py
- core/app_state.py
- core/utils.py
- services/database_service.py
- services/settings_service.py
- services/calibration_service.py
- services/threshold_service.py
- services/diagnosis_service.py
- services/storage_service.py

Design goals:
- safe file generation
- consistent export structure
- human-readable JSON
- CSV ready for spreadsheet use
- bundle export for backup/admin review
"""

from __future__ import annotations

import csv
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from config import PATHS
from core.app_state import AppState, get_app_state
from core.constants import EXPORTABLE_FILE_TYPES
from core.logger import get_logger, log_exception
from core.utils import (
    build_export_path,
    deep_copy,
    ensure_directory,
    file_size_bytes,
    format_bytes,
    json_dumps_pretty,
    normalize_measurement_payload,
    now_iso,
    safe_float,
    safe_int,
    safe_str,
    write_json_file,
    write_text_file,
)
from services.calibration_service import CalibrationService, get_calibration_service
from services.database_service import DatabaseService, get_database_service
from services.diagnosis_service import DiagnosisService, get_diagnosis_service
from services.settings_service import SettingsService, get_settings_service
from services.storage_service import StorageService, get_storage_service
from services.threshold_service import ThresholdService, get_threshold_service

logger = get_logger(__name__)


# ============================================================
# Dataclasses
# ============================================================

@dataclass
class ExportResult:
    success: bool
    export_type: str
    export_format: str
    path: str
    size_bytes: int
    size_human: str
    record_count: int
    message: str
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "export_type": self.export_type,
            "export_format": self.export_format,
            "path": self.path,
            "size_bytes": self.size_bytes,
            "size_human": self.size_human,
            "record_count": self.record_count,
            "message": self.message,
            "metadata": deep_copy(self.metadata),
        }


# ============================================================
# Export service
# ============================================================

class ExportService(QObject):
    """
    Central export manager.

    Main responsibilities:
    - export current session
    - export session history
    - export settings/calibration/thresholds
    - export diagnosis/status snapshots
    - export full ZIP bundle for admin use
    - list and delete exported files
    """

    export_created = pyqtSignal(dict)
    export_deleted = pyqtSignal(str)
    current_session_exported = pyqtSignal(dict)
    sessions_exported = pyqtSignal(dict)
    config_exported = pyqtSignal(dict)
    bundle_exported = pyqtSignal(dict)
    export_error = pyqtSignal(str)

    def __init__(
        self,
        app_state: Optional[AppState] = None,
        database_service: Optional[DatabaseService] = None,
        settings_service: Optional[SettingsService] = None,
        calibration_service: Optional[CalibrationService] = None,
        threshold_service: Optional[ThresholdService] = None,
        diagnosis_service: Optional[DiagnosisService] = None,
        storage_service: Optional[StorageService] = None,
    ) -> None:
        super().__init__()

        self._logger = logger.bind(component="ExportService")
        self._app_state: AppState = app_state or get_app_state()
        self._database_service: DatabaseService = database_service or get_database_service()
        self._settings_service: SettingsService = settings_service or get_settings_service()
        self._calibration_service: CalibrationService = calibration_service or get_calibration_service()
        self._threshold_service: ThresholdService = threshold_service or get_threshold_service()
        self._diagnosis_service: DiagnosisService = diagnosis_service or get_diagnosis_service()
        self._storage_service: StorageService = storage_service or get_storage_service()

        self._ensure_export_dir()

    # ========================================================
    # Internal helpers
    # ========================================================

    def _ensure_export_dir(self) -> None:
        ensure_directory(PATHS.exports_dir)

    def _build_result(
        self,
        *,
        success: bool,
        export_type: str,
        export_format: str,
        path: Path | str,
        record_count: int,
        message: str,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        path_obj = Path(path)
        size_bytes = file_size_bytes(path_obj) if path_obj.exists() else 0

        result = ExportResult(
            success=success,
            export_type=export_type,
            export_format=export_format,
            path=str(path_obj),
            size_bytes=size_bytes,
            size_human=format_bytes(size_bytes),
            record_count=safe_int(record_count, 0),
            message=message,
            metadata=deep_copy(dict(metadata or {})),
        )
        payload = result.to_dict()
        if success:
            self.export_created.emit(payload)
        return payload

    def _flatten_session_record(self, record: Mapping[str, Any]) -> Dict[str, Any]:
        """
        Flatten a database session record into CSV-friendly fields.
        """
        diagnosis = record.get("diagnosis", {})
        if not isinstance(diagnosis, Mapping):
            diagnosis = {}

        measurements = record.get("measurements", {})
        if not isinstance(measurements, Mapping):
            measurements = {
                "weight": record.get("weight", 0.0),
                "height": record.get("height", 0.0),
                "bmi": record.get("bmi", 0.0),
                "temperature": record.get("temperature", 0.0),
                "spo2": record.get("spo2", 0.0),
                "pulse_rate": record.get("pulse_rate", 0.0),
                "respiratory_rate": record.get("respiratory_rate", 0.0),
            }

        issues = diagnosis.get("issues", [])
        if not isinstance(issues, list):
            issues = []
        issue_labels = diagnosis.get("issue_labels", [])
        if not isinstance(issue_labels, list):
            issue_labels = []

        recommendations = diagnosis.get("recommendations", [])
        if not isinstance(recommendations, list):
            recommendations = []

        flattened = {
            "session_id": safe_str(record.get("session_id"), ""),
            "mode": safe_str(record.get("mode"), ""),
            "status": safe_str(record.get("status"), ""),
            "started_at": safe_str(record.get("started_at"), ""),
            "completed_at": safe_str(record.get("completed_at"), ""),
            "cancelled_at": safe_str(record.get("cancelled_at"), ""),
            "report_path": safe_str(record.get("report_path"), ""),
            "qr_path": safe_str(record.get("qr_path"), ""),
            "measurement_progress": safe_int(record.get("measurement_progress"), 0),
            "measurement_complete_ratio": safe_float(record.get("measurement_complete_ratio"), 0.0),
            "weight": safe_float(measurements.get("weight"), 0.0),
            "height": safe_float(measurements.get("height"), 0.0),
            "bmi": safe_float(measurements.get("bmi"), 0.0),
            "temperature": safe_float(measurements.get("temperature"), 0.0),
            "spo2": safe_float(measurements.get("spo2"), 0.0),
            "pulse_rate": safe_float(measurements.get("pulse_rate"), 0.0),
            "respiratory_rate": safe_float(measurements.get("respiratory_rate"), 0.0),
            "overall_severity": safe_str(record.get("overall_severity"), diagnosis.get("overall_severity", "")),
            "status_title": safe_str(record.get("status_title"), diagnosis.get("status_title", "")),
            "diagnosis_summary": safe_str(record.get("diagnosis_summary"), diagnosis.get("summary", "")),
            "issues": " | ".join(safe_str(item, "") for item in issues if safe_str(item, "")),
            "issue_labels": " | ".join(safe_str(item, "") for item in issue_labels if safe_str(item, "")),
            "recommendations": " | ".join(safe_str(item, "") for item in recommendations if safe_str(item, "")),
        }
        return flattened

    def _write_csv(self, path: Path, rows: List[Mapping[str, Any]]) -> Path:
        ensure_directory(path.parent)

        if not rows:
            with path.open("w", newline="", encoding="utf-8") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["message"])
                writer.writerow(["No records available"])
            return path

        # stable field order from union of row keys
        fieldnames: List[str] = []
        seen = set()
        for row in rows:
            for key in row.keys():
                if key not in seen:
                    seen.add(key)
                    fieldnames.append(str(key))

        with path.open("w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key, "") for key in fieldnames})

        return path

    def _current_session_export_payload(
        self,
        *,
        include_measurements: bool = True,
        include_diagnosis: bool = True,
        include_settings_snapshot: bool = False,
    ) -> Dict[str, Any]:
        session_snapshot = self._app_state.session_snapshot()
        payload: Dict[str, Any] = {
            "exported_at": now_iso(),
            "session": deep_copy(session_snapshot),
        }

        if include_measurements:
            payload["measurements"] = deep_copy(self._app_state.current_measurements())

        if include_diagnosis:
            current_diag = self._diagnosis_service.current_diagnosis()
            if not current_diag or not current_diag.get("summary"):
                current_diag = self._diagnosis_service.diagnose_current_session(store_in_app_state=False)
            payload["diagnosis"] = deep_copy(current_diag)

        if include_settings_snapshot:
            payload["settings_snapshot"] = self._settings_service.snapshot()

        return payload

    # ========================================================
    # Export current session
    # ========================================================

    def export_current_session_json(
        self,
        *,
        label: str = "current_session",
        include_measurements: bool = True,
        include_diagnosis: bool = True,
        include_settings_snapshot: bool = False,
    ) -> Dict[str, Any]:
        """
        Export the active session as pretty JSON.
        """
        try:
            payload = self._current_session_export_payload(
                include_measurements=include_measurements,
                include_diagnosis=include_diagnosis,
                include_settings_snapshot=include_settings_snapshot,
            )
            path = build_export_path(label=label, extension="json")
            write_json_file(path, payload)

            result = self._build_result(
                success=True,
                export_type="current_session",
                export_format="json",
                path=path,
                record_count=1,
                message="Current session exported as JSON.",
                metadata={
                    "include_measurements": include_measurements,
                    "include_diagnosis": include_diagnosis,
                    "include_settings_snapshot": include_settings_snapshot,
                },
            )
            self.current_session_exported.emit(deep_copy(result))
            return result

        except Exception as exc:
            log_exception(self._logger, "Failed to export current session JSON", exc)
            self.export_error.emit(str(exc))
            return self._build_result(
                success=False,
                export_type="current_session",
                export_format="json",
                path=build_export_path(label=label, extension="json"),
                record_count=0,
                message=str(exc),
                metadata={},
            )

    def export_current_session_csv(self, *, label: str = "current_session") -> Dict[str, Any]:
        """
        Export the active session as one-row CSV.
        """
        try:
            session_record = self._app_state.export_current_session_record()
            diagnosis = self._diagnosis_service.current_diagnosis()
            row = self._flatten_session_record(
                {
                    **session_record,
                    "diagnosis": diagnosis,
                    "measurements": self._app_state.current_measurements(),
                }
            )

            path = build_export_path(label=label, extension="csv")
            self._write_csv(path, [row])

            result = self._build_result(
                success=True,
                export_type="current_session",
                export_format="csv",
                path=path,
                record_count=1,
                message="Current session exported as CSV.",
                metadata={},
            )
            self.current_session_exported.emit(deep_copy(result))
            return result

        except Exception as exc:
            log_exception(self._logger, "Failed to export current session CSV", exc)
            self.export_error.emit(str(exc))
            return self._build_result(
                success=False,
                export_type="current_session",
                export_format="csv",
                path=build_export_path(label=label, extension="csv"),
                record_count=0,
                message=str(exc),
                metadata={},
            )

    # ========================================================
    # Export recent session records
    # ========================================================

    def export_sessions_json(
        self,
        *,
        label: str = "sessions",
        limit: int = 500,
        mode: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Export recent sessions from the database as JSON.
        """
        try:
            rows = self._database_service.get_recent_sessions(
                limit=safe_int(limit, 500),
                mode=mode,
                status=status,
            )

            payload = {
                "exported_at": now_iso(),
                "filters": {
                    "limit": safe_int(limit, 500),
                    "mode": safe_str(mode, ""),
                    "status": safe_str(status, ""),
                },
                "record_count": len(rows),
                "records": deep_copy(rows),
            }

            path = build_export_path(label=label, extension="json")
            write_json_file(path, payload)

            result = self._build_result(
                success=True,
                export_type="sessions",
                export_format="json",
                path=path,
                record_count=len(rows),
                message="Session records exported as JSON.",
                metadata=payload["filters"],
            )
            self.sessions_exported.emit(deep_copy(result))
            return result

        except Exception as exc:
            log_exception(self._logger, "Failed to export sessions JSON", exc)
            self.export_error.emit(str(exc))
            return self._build_result(
                success=False,
                export_type="sessions",
                export_format="json",
                path=build_export_path(label=label, extension="json"),
                record_count=0,
                message=str(exc),
                metadata={},
            )

    def export_sessions_csv(
        self,
        *,
        label: str = "sessions",
        limit: int = 500,
        mode: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Export recent sessions from the database as CSV.
        """
        try:
            rows = self._database_service.get_recent_sessions(
                limit=safe_int(limit, 500),
                mode=mode,
                status=status,
            )
            flattened = [self._flatten_session_record(row) for row in rows]

            path = build_export_path(label=label, extension="csv")
            self._write_csv(path, flattened)

            result = self._build_result(
                success=True,
                export_type="sessions",
                export_format="csv",
                path=path,
                record_count=len(flattened),
                message="Session records exported as CSV.",
                metadata={
                    "limit": safe_int(limit, 500),
                    "mode": safe_str(mode, ""),
                    "status": safe_str(status, ""),
                },
            )
            self.sessions_exported.emit(deep_copy(result))
            return result

        except Exception as exc:
            log_exception(self._logger, "Failed to export sessions CSV", exc)
            self.export_error.emit(str(exc))
            return self._build_result(
                success=False,
                export_type="sessions",
                export_format="csv",
                path=build_export_path(label=label, extension="csv"),
                record_count=0,
                message=str(exc),
                metadata={},
            )

    # ========================================================
    # Export configuration/state blocks
    # ========================================================

    def export_settings_json(self, *, label: str = "settings") -> Dict[str, Any]:
        try:
            payload = {
                "exported_at": now_iso(),
                "settings": self._settings_service.snapshot(),
            }
            path = build_export_path(label=label, extension="json")
            write_json_file(path, payload)

            result = self._build_result(
                success=True,
                export_type="settings",
                export_format="json",
                path=path,
                record_count=1,
                message="Settings exported as JSON.",
                metadata={},
            )
            self.config_exported.emit(deep_copy(result))
            return result
        except Exception as exc:
            log_exception(self._logger, "Failed to export settings JSON", exc)
            self.export_error.emit(str(exc))
            return self._build_result(
                success=False,
                export_type="settings",
                export_format="json",
                path=build_export_path(label=label, extension="json"),
                record_count=0,
                message=str(exc),
                metadata={},
            )

    def export_calibration_json(self, *, label: str = "calibration") -> Dict[str, Any]:
        try:
            payload = {
                "exported_at": now_iso(),
                "calibration": self._calibration_service.snapshot(),
            }
            path = build_export_path(label=label, extension="json")
            write_json_file(path, payload)

            result = self._build_result(
                success=True,
                export_type="calibration",
                export_format="json",
                path=path,
                record_count=1,
                message="Calibration exported as JSON.",
                metadata={},
            )
            self.config_exported.emit(deep_copy(result))
            return result
        except Exception as exc:
            log_exception(self._logger, "Failed to export calibration JSON", exc)
            self.export_error.emit(str(exc))
            return self._build_result(
                success=False,
                export_type="calibration",
                export_format="json",
                path=build_export_path(label=label, extension="json"),
                record_count=0,
                message=str(exc),
                metadata={},
            )

    def export_thresholds_json(self, *, label: str = "thresholds") -> Dict[str, Any]:
        try:
            payload = {
                "exported_at": now_iso(),
                "thresholds": self._threshold_service.snapshot(),
            }
            path = build_export_path(label=label, extension="json")
            write_json_file(path, payload)

            result = self._build_result(
                success=True,
                export_type="thresholds",
                export_format="json",
                path=path,
                record_count=1,
                message="Thresholds exported as JSON.",
                metadata={},
            )
            self.config_exported.emit(deep_copy(result))
            return result
        except Exception as exc:
            log_exception(self._logger, "Failed to export thresholds JSON", exc)
            self.export_error.emit(str(exc))
            return self._build_result(
                success=False,
                export_type="thresholds",
                export_format="json",
                path=build_export_path(label=label, extension="json"),
                record_count=0,
                message=str(exc),
                metadata={},
            )

    def export_current_diagnosis_json(self, *, label: str = "diagnosis") -> Dict[str, Any]:
        try:
            diagnosis = self._diagnosis_service.current_diagnosis()
            if not diagnosis or not diagnosis.get("summary"):
                diagnosis = self._diagnosis_service.diagnose_current_session(store_in_app_state=False)

            payload = {
                "exported_at": now_iso(),
                "diagnosis": diagnosis,
                "measurements": self._app_state.current_measurements(),
            }
            path = build_export_path(label=label, extension="json")
            write_json_file(path, payload)

            result = self._build_result(
                success=True,
                export_type="diagnosis",
                export_format="json",
                path=path,
                record_count=1,
                message="Current diagnosis exported as JSON.",
                metadata={},
            )
            self.config_exported.emit(deep_copy(result))
            return result
        except Exception as exc:
            log_exception(self._logger, "Failed to export diagnosis JSON", exc)
            self.export_error.emit(str(exc))
            return self._build_result(
                success=False,
                export_type="diagnosis",
                export_format="json",
                path=build_export_path(label=label, extension="json"),
                record_count=0,
                message=str(exc),
                metadata={},
            )

    def export_storage_summary_json(self, *, label: str = "storage_summary") -> Dict[str, Any]:
        try:
            payload = {
                "exported_at": now_iso(),
                "storage_summary": self._storage_service.get_storage_summary(),
            }
            path = build_export_path(label=label, extension="json")
            write_json_file(path, payload)

            result = self._build_result(
                success=True,
                export_type="storage_summary",
                export_format="json",
                path=path,
                record_count=1,
                message="Storage summary exported as JSON.",
                metadata={},
            )
            self.config_exported.emit(deep_copy(result))
            return result
        except Exception as exc:
            log_exception(self._logger, "Failed to export storage summary JSON", exc)
            self.export_error.emit(str(exc))
            return self._build_result(
                success=False,
                export_type="storage_summary",
                export_format="json",
                path=build_export_path(label=label, extension="json"),
                record_count=0,
                message=str(exc),
                metadata={},
            )

    # ========================================================
    # Export full bundle ZIP
    # ========================================================

    def export_admin_bundle_zip(
        self,
        *,
        label: str = "admin_bundle",
        include_current_session: bool = True,
        include_recent_sessions: bool = True,
        recent_limit: int = 500,
        include_settings: bool = True,
        include_calibration: bool = True,
        include_thresholds: bool = True,
        include_diagnosis: bool = True,
        include_storage_summary: bool = True,
    ) -> Dict[str, Any]:
        """
        Create a ZIP bundle containing multiple JSON/CSV exports.
        """
        try:
            bundle_path = build_export_path(label=label, extension="zip")
            ensure_directory(bundle_path.parent)

            temp_items: List[Path] = []

            # Build export components first as files in exports dir
            if include_current_session:
                res = self.export_current_session_json(
                    label=f"{label}_current_session",
                    include_measurements=True,
                    include_diagnosis=include_diagnosis,
                    include_settings_snapshot=False,
                )
                if res.get("success"):
                    temp_items.append(Path(res["path"]))

            if include_recent_sessions:
                res_json = self.export_sessions_json(
                    label=f"{label}_sessions",
                    limit=recent_limit,
                )
                if res_json.get("success"):
                    temp_items.append(Path(res_json["path"]))

                res_csv = self.export_sessions_csv(
                    label=f"{label}_sessions",
                    limit=recent_limit,
                )
                if res_csv.get("success"):
                    temp_items.append(Path(res_csv["path"]))

            if include_settings:
                res = self.export_settings_json(label=f"{label}_settings")
                if res.get("success"):
                    temp_items.append(Path(res["path"]))

            if include_calibration:
                res = self.export_calibration_json(label=f"{label}_calibration")
                if res.get("success"):
                    temp_items.append(Path(res["path"]))

            if include_thresholds:
                res = self.export_thresholds_json(label=f"{label}_thresholds")
                if res.get("success"):
                    temp_items.append(Path(res["path"]))

            if include_diagnosis:
                res = self.export_current_diagnosis_json(label=f"{label}_diagnosis")
                if res.get("success"):
                    temp_items.append(Path(res["path"]))

            if include_storage_summary:
                res = self.export_storage_summary_json(label=f"{label}_storage_summary")
                if res.get("success"):
                    temp_items.append(Path(res["path"]))

            # Add a README manifest
            manifest_path = build_export_path(label=f"{label}_manifest", extension="txt")
            manifest_text = "\n".join(
                [
                    "CST Health Monitoring Station - Admin Export Bundle",
                    f"Generated: {now_iso()}",
                    "",
                    "Included files:",
                    *[f"- {item.name}" for item in temp_items],
                ]
            )
            write_text_file(manifest_path, manifest_text)
            temp_items.append(manifest_path)

            # Bundle them
            with zipfile.ZipFile(bundle_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
                for file_path in temp_items:
                    if file_path.exists() and file_path.is_file():
                        archive.write(file_path, arcname=file_path.name)

            result = self._build_result(
                success=True,
                export_type="admin_bundle",
                export_format="zip",
                path=bundle_path,
                record_count=len(temp_items),
                message="Admin bundle ZIP exported successfully.",
                metadata={
                    "included_file_count": len(temp_items),
                    "recent_limit": safe_int(recent_limit, 500),
                },
            )
            self.bundle_exported.emit(deep_copy(result))
            return result

        except Exception as exc:
            log_exception(self._logger, "Failed to export admin bundle ZIP", exc)
            self.export_error.emit(str(exc))
            return self._build_result(
                success=False,
                export_type="admin_bundle",
                export_format="zip",
                path=build_export_path(label=label, extension="zip"),
                record_count=0,
                message=str(exc),
                metadata={},
            )

    # ========================================================
    # Export listing / deletion
    # ========================================================

    def list_exports(self, limit: int = 100) -> List[Dict[str, Any]]:
        self._ensure_export_dir()
        limit = max(1, safe_int(limit, 100))

        files = [
            p for p in PATHS.exports_dir.glob("*")
            if p.is_file() and not p.name.startswith(".") and p.name != ".keep"
        ]
        files.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)

        result: List[Dict[str, Any]] = []
        for file_path in files[:limit]:
            stat = file_path.stat()
            result.append(
                {
                    "name": file_path.name,
                    "path": str(file_path),
                    "suffix": file_path.suffix.lower(),
                    "size_bytes": safe_int(stat.st_size, 0),
                    "size_human": format_bytes(stat.st_size),
                    "modified_at_epoch": stat.st_mtime,
                }
            )
        return result

    def delete_export(self, export_name_or_path: str) -> bool:
        target = Path(export_name_or_path)
        if not target.is_absolute():
            target = PATHS.exports_dir / target.name

        try:
            if target.exists() and target.is_file():
                target.unlink(missing_ok=True)
                self._logger.info("Export deleted: %s", target)
                self.export_deleted.emit(str(target))
                return True
            return False
        except Exception as exc:
            log_exception(self._logger, "Failed to delete export", exc)
            self.export_error.emit(str(exc))
            return False

    # ========================================================
    # Diagnostics
    # ========================================================

    def diagnostics(self) -> Dict[str, Any]:
        exports = self.list_exports(limit=200)
        return {
            "exports_dir": str(PATHS.exports_dir),
            "export_count": len(exports),
            "supported_formats": list(EXPORTABLE_FILE_TYPES) + ["zip"],
            "latest_exports": exports[:5],
        }


# ============================================================
# Singleton accessor
# ============================================================

_EXPORT_SERVICE_SINGLETON: Optional[ExportService] = None


def get_export_service(
    app_state: Optional[AppState] = None,
    database_service: Optional[DatabaseService] = None,
    settings_service: Optional[SettingsService] = None,
    calibration_service: Optional[CalibrationService] = None,
    threshold_service: Optional[ThresholdService] = None,
    diagnosis_service: Optional[DiagnosisService] = None,
    storage_service: Optional[StorageService] = None,
) -> ExportService:
    global _EXPORT_SERVICE_SINGLETON
    if _EXPORT_SERVICE_SINGLETON is None:
        _EXPORT_SERVICE_SINGLETON = ExportService(
            app_state=app_state,
            database_service=database_service,
            settings_service=settings_service,
            calibration_service=calibration_service,
            threshold_service=threshold_service,
            diagnosis_service=diagnosis_service,
            storage_service=storage_service,
        )
    return _EXPORT_SERVICE_SINGLETON