"""
services/storage_service.py

Storage and records management service for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the main backend for the Storage screen
- It provides real storage statistics for:
    - database size
    - reports folder
    - QR folder
    - exports
    - backups
    - temp
    - logs
- It provides measurement record counts for the admin storage view
- It supports:
    - backup creation
    - backup listing
    - cleanup of temp/export/report/QR files
    - selective clearing of database records
    - full storage summary refresh into AppState
- It is designed to work on both laptop demo mode and Raspberry Pi deployment

Linked files:
- config.py
- core/app_state.py
- core/constants.py
- core/utils.py
- services/database_service.py

Design goals:
- safe file handling
- explicit cleanup controls
- useful admin-facing summaries
- database-backed record counts plus filesystem-backed storage metrics
"""

from __future__ import annotations

import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from config import PATHS
from core.app_state import AppState, get_app_state
from core.constants import DEFAULT_STORAGE_LIMIT_BYTES
from core.logger import get_logger, log_exception
from core.utils import (
    build_backup_path,
    deep_copy,
    ensure_directory,
    file_size_bytes,
    format_bytes,
    now_iso,
    safe_float,
    safe_int,
    safe_str,
)
from services.database_service import DatabaseService, get_database_service

logger = get_logger(__name__)


# ============================================================
# Dataclasses
# ============================================================

@dataclass
class BackupResult:
    success: bool
    backup_path: str
    size_bytes: int
    size_human: str
    file_count: int
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "backup_path": self.backup_path,
            "size_bytes": self.size_bytes,
            "size_human": self.size_human,
            "file_count": self.file_count,
            "message": self.message,
        }


@dataclass
class CleanupResult:
    success: bool
    target: str
    deleted_files: int
    freed_bytes: int
    freed_human: str
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "target": self.target,
            "deleted_files": self.deleted_files,
            "freed_bytes": self.freed_bytes,
            "freed_human": self.freed_human,
            "message": self.message,
        }


# ============================================================
# Storage service
# ============================================================

class StorageService(QObject):
    """
    Central storage management service.

    Main responsibilities:
    - produce storage summary for admin storage screen
    - create and inspect backups
    - clear generated files safely
    - clear old measurement records while optionally preserving latest history
    - synchronize storage summary into AppState
    """

    storage_summary_updated = pyqtSignal(dict)
    backup_created = pyqtSignal(dict)
    backup_deleted = pyqtSignal(str)
    cleanup_completed = pyqtSignal(dict)
    records_cleared = pyqtSignal(dict)
    storage_error = pyqtSignal(str)

    def __init__(
        self,
        app_state: Optional[AppState] = None,
        database_service: Optional[DatabaseService] = None,
    ) -> None:
        super().__init__()

        self._logger = logger.bind(component="StorageService")
        self._app_state: AppState = app_state or get_app_state()
        self._database_service: DatabaseService = database_service or get_database_service()

        self._ensure_storage_dirs()

    # ========================================================
    # Internal helpers
    # ========================================================

    def _ensure_storage_dirs(self) -> None:
        ensure_directory(PATHS.backups_dir)
        ensure_directory(PATHS.reports_dir)
        ensure_directory(PATHS.qr_dir)
        ensure_directory(PATHS.exports_dir)
        ensure_directory(PATHS.temp_dir)
        ensure_directory(PATHS.logs_dir)

    def _is_hidden_or_keep(self, path: Path) -> bool:
        name = path.name.strip()
        return name.startswith(".") or name.lower() == ".keep"

    def _iter_real_files(self, folder: Path) -> Iterable[Path]:
        if not folder.exists():
            return []
        return [p for p in folder.rglob("*") if p.is_file() and not self._is_hidden_or_keep(p)]

    def _folder_file_count(self, folder: Path) -> int:
        return sum(1 for _ in self._iter_real_files(folder))

    def _folder_size_bytes(self, folder: Path) -> int:
        total = 0
        for file_path in self._iter_real_files(folder):
            try:
                total += file_path.stat().st_size
            except Exception:
                continue
        return total

    def _folder_stats(self, folder: Path, label: str) -> Dict[str, Any]:
        size_bytes = self._folder_size_bytes(folder)
        file_count = self._folder_file_count(folder)

        return {
            "label": label,
            "path": str(folder),
            "exists": folder.exists(),
            "file_count": file_count,
            "size_bytes": size_bytes,
            "size_human": format_bytes(size_bytes),
        }

    def _disk_usage_snapshot(self, target_path: Optional[Path] = None) -> Dict[str, Any]:
        base = target_path or PATHS.project_root
        try:
            usage = shutil.disk_usage(str(base))
            total = safe_int(usage.total, 0)
            used = safe_int(usage.used, 0)
            free = safe_int(usage.free, 0)
            usage_percent = round((used / total) * 100.0, 1) if total > 0 else 0.0

            return {
                "path": str(base),
                "total_bytes": total,
                "used_bytes": used,
                "free_bytes": free,
                "total_human": format_bytes(total),
                "used_human": format_bytes(used),
                "free_human": format_bytes(free),
                "usage_percent": usage_percent,
            }
        except Exception as exc:
            log_exception(self._logger, "Failed to read disk usage", exc)
            return {
                "path": str(base),
                "total_bytes": 0,
                "used_bytes": 0,
                "free_bytes": 0,
                "total_human": format_bytes(0),
                "used_human": format_bytes(0),
                "free_human": format_bytes(0),
                "usage_percent": 0.0,
            }

    def _baseline_capacity_snapshot(self, used_bytes: int) -> Dict[str, Any]:
        baseline_total = DEFAULT_STORAGE_LIMIT_BYTES
        usage_percent = round((used_bytes / baseline_total) * 100.0, 2) if baseline_total > 0 else 0.0
        return {
            "baseline_total_bytes": baseline_total,
            "baseline_total_human": format_bytes(baseline_total),
            "used_bytes": used_bytes,
            "used_human": format_bytes(used_bytes),
            "usage_percent_of_baseline": usage_percent,
        }

    def _backup_metadata(self, backup_path: Path) -> Dict[str, Any]:
        size_bytes = file_size_bytes(backup_path)
        return {
            "name": backup_path.name,
            "path": str(backup_path),
            "size_bytes": size_bytes,
            "size_human": format_bytes(size_bytes),
            "created_at": now_iso(),
            "exists": backup_path.exists(),
        }

    def _collect_backup_listing(self, limit: int = 50) -> List[Dict[str, Any]]:
        limit = max(1, safe_int(limit, 50))
        self._ensure_storage_dirs()

        files = [
            p for p in PATHS.backups_dir.glob("*.zip")
            if p.is_file() and not self._is_hidden_or_keep(p)
        ]
        files.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)

        result: List[Dict[str, Any]] = []
        for backup_path in files[:limit]:
            stat = backup_path.stat()
            result.append(
                {
                    "name": backup_path.name,
                    "path": str(backup_path),
                    "size_bytes": safe_int(stat.st_size, 0),
                    "size_human": format_bytes(stat.st_size),
                    "modified_at_epoch": safe_float(stat.st_mtime, 0.0),
                }
            )
        return result

    def _refresh_app_state_summary(self, summary: Dict[str, Any]) -> None:
        try:
            self._app_state.set_storage_summary(summary)
        except Exception as exc:
            self._logger.warning("Failed to push storage summary into AppState: %s", exc)

    def _delete_files_in_folder(
        self,
        folder: Path,
        *,
        allowed_suffixes: Optional[List[str]] = None,
        keep_hidden: bool = True,
    ) -> CleanupResult:
        """
        Delete files inside a folder recursively.
        """
        deleted_files = 0
        freed_bytes = 0

        try:
            if not folder.exists():
                return CleanupResult(
                    success=True,
                    target=str(folder),
                    deleted_files=0,
                    freed_bytes=0,
                    freed_human=format_bytes(0),
                    message="Folder does not exist; nothing to delete.",
                )

            for file_path in folder.rglob("*"):
                if not file_path.is_file():
                    continue
                if keep_hidden and self._is_hidden_or_keep(file_path):
                    continue
                if allowed_suffixes is not None and file_path.suffix.lower() not in allowed_suffixes:
                    continue

                try:
                    size = file_path.stat().st_size
                except Exception:
                    size = 0

                try:
                    file_path.unlink(missing_ok=True)
                    deleted_files += 1
                    freed_bytes += size
                except Exception as exc:
                    self._logger.warning("Could not delete file '%s': %s", file_path, exc)

            result = CleanupResult(
                success=True,
                target=str(folder),
                deleted_files=deleted_files,
                freed_bytes=freed_bytes,
                freed_human=format_bytes(freed_bytes),
                message=f"Deleted {deleted_files} files.",
            )
            self.cleanup_completed.emit(result.to_dict())
            return result

        except Exception as exc:
            log_exception(self._logger, f"Failed to clear folder {folder}", exc)
            self.storage_error.emit(str(exc))
            return CleanupResult(
                success=False,
                target=str(folder),
                deleted_files=0,
                freed_bytes=0,
                freed_human=format_bytes(0),
                message=str(exc),
            )

    # ========================================================
    # Public summary helpers
    # ========================================================

    def get_storage_summary(self) -> Dict[str, Any]:
        """
        Build a complete storage summary for the storage screen.
        """
        self._ensure_storage_dirs()

        db_summary = self._database_service.get_storage_summary()
        reports_stats = self._folder_stats(PATHS.reports_dir, "Reports")
        qr_stats = self._folder_stats(PATHS.qr_dir, "QR Files")
        backups_stats = self._folder_stats(PATHS.backups_dir, "Backups")
        exports_stats = self._folder_stats(PATHS.exports_dir, "Exports")
        temp_stats = self._folder_stats(PATHS.temp_dir, "Temp")
        logs_stats = self._folder_stats(PATHS.logs_dir, "Logs")

        project_used_bytes = (
            safe_int(db_summary.get("database", {}).get("db_size_bytes"), 0)
            + reports_stats["size_bytes"]
            + qr_stats["size_bytes"]
            + backups_stats["size_bytes"]
            + exports_stats["size_bytes"]
            + temp_stats["size_bytes"]
            + logs_stats["size_bytes"]
        )

        record_counts = db_summary.get("record_counts", {})
        total_sessions = safe_int(record_counts.get("total_sessions"), 0)
        completed_sessions = safe_int(record_counts.get("completed_sessions"), 0)

        disk_usage = self._disk_usage_snapshot(PATHS.project_root)
        baseline_usage = self._baseline_capacity_snapshot(project_used_bytes)

        backup_list = self._collect_backup_listing(limit=25)

        summary = {
            "generated_at": now_iso(),
            "database": deep_copy(db_summary.get("database", {})),
            "folders": {
                "reports": reports_stats,
                "qr": qr_stats,
                "backups": backups_stats,
                "exports": exports_stats,
                "temp": temp_stats,
                "logs": logs_stats,
            },
            "records": {
                "total_sessions": total_sessions,
                "completed_sessions": completed_sessions,
                "people_measured_count": completed_sessions,
                "status_counts": deep_copy(record_counts.get("status_counts", {})),
                "mode_counts": deep_copy(record_counts.get("mode_counts", {})),
            },
            "project_storage": {
                "used_bytes": project_used_bytes,
                "used_human": format_bytes(project_used_bytes),
            },
            "baseline_usage": baseline_usage,
            "system_disk_usage": disk_usage,
            "backups": {
                "count": len(backup_list),
                "items": backup_list,
            },
        }

        return summary

    def refresh_storage_summary(self) -> Dict[str, Any]:
        """
        Recompute storage summary and push it into AppState.
        """
        summary = self.get_storage_summary()
        self._refresh_app_state_summary(summary)
        self.storage_summary_updated.emit(deep_copy(summary))
        return summary

    def current_storage_summary(self) -> Dict[str, Any]:
        """
        Return AppState copy if available, otherwise refresh.
        """
        existing = self._app_state.storage_summary_snapshot()
        if existing:
            return existing
        return self.refresh_storage_summary()

    # ========================================================
    # Backup helpers
    # ========================================================

    def create_backup(
        self,
        *,
        label: str = "backup",
        include_database: bool = True,
        include_reports: bool = True,
        include_qr: bool = True,
        include_exports: bool = True,
        include_logs: bool = True,
        include_config: bool = True,
    ) -> Dict[str, Any]:
        """
        Create a zip backup under data/backups/.

        Included content can be controlled per category.
        """
        self._ensure_storage_dirs()

        backup_path = build_backup_path(label=label, extension="zip")
        ensure_directory(backup_path.parent)

        file_count = 0

        try:
            with zipfile.ZipFile(backup_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
                # Database
                if include_database and PATHS.db_file.exists():
                    archive.write(PATHS.db_file, arcname=f"data/db/{PATHS.db_file.name}")
                    file_count += 1

                # Config JSONs
                if include_config and PATHS.config_dir.exists():
                    for config_file in PATHS.config_dir.iterdir():
                        if config_file.is_file() and not self._is_hidden_or_keep(config_file):
                            archive.write(config_file, arcname=f"data/config/{config_file.name}")
                            file_count += 1

                # Reports
                if include_reports:
                    for file_path in self._iter_real_files(PATHS.reports_dir):
                        archive.write(file_path, arcname=str(file_path.relative_to(PATHS.project_root)))
                        file_count += 1

                # QR
                if include_qr:
                    for file_path in self._iter_real_files(PATHS.qr_dir):
                        archive.write(file_path, arcname=str(file_path.relative_to(PATHS.project_root)))
                        file_count += 1

                # Exports
                if include_exports:
                    for file_path in self._iter_real_files(PATHS.exports_dir):
                        archive.write(file_path, arcname=str(file_path.relative_to(PATHS.project_root)))
                        file_count += 1

                # Logs
                if include_logs:
                    for file_path in self._iter_real_files(PATHS.logs_dir):
                        archive.write(file_path, arcname=str(file_path.relative_to(PATHS.project_root)))
                        file_count += 1

            size_bytes = file_size_bytes(backup_path)
            result = BackupResult(
                success=True,
                backup_path=str(backup_path),
                size_bytes=size_bytes,
                size_human=format_bytes(size_bytes),
                file_count=file_count,
                message="Backup created successfully.",
            )

            self._logger.info("Backup created at %s", backup_path)
            self.backup_created.emit(result.to_dict())
            self.refresh_storage_summary()
            return result.to_dict()

        except Exception as exc:
            log_exception(self._logger, "Failed to create backup", exc)
            self.storage_error.emit(str(exc))
            result = BackupResult(
                success=False,
                backup_path=str(backup_path),
                size_bytes=0,
                size_human=format_bytes(0),
                file_count=0,
                message=str(exc),
            )
            return result.to_dict()

    def list_backups(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._collect_backup_listing(limit=limit)

    def delete_backup(self, backup_name_or_path: str) -> bool:
        """
        Delete one backup zip by filename or absolute/relative path.
        """
        target = Path(backup_name_or_path)
        if not target.is_absolute():
            target = PATHS.backups_dir / target.name

        try:
            if target.exists() and target.is_file():
                target.unlink(missing_ok=True)
                self._logger.info("Backup deleted: %s", target)
                self.backup_deleted.emit(str(target))
                self.refresh_storage_summary()
                return True
            return False
        except Exception as exc:
            log_exception(self._logger, "Failed to delete backup", exc)
            self.storage_error.emit(str(exc))
            return False

    # ========================================================
    # Cleanup helpers for generated files
    # ========================================================

    def clear_temp_files(self) -> Dict[str, Any]:
        result = self._delete_files_in_folder(PATHS.temp_dir)
        self.refresh_storage_summary()
        return result.to_dict()

    def clear_export_files(self) -> Dict[str, Any]:
        result = self._delete_files_in_folder(PATHS.exports_dir)
        self.refresh_storage_summary()
        return result.to_dict()

    def clear_qr_files(self) -> Dict[str, Any]:
        result = self._delete_files_in_folder(PATHS.qr_dir)
        self.refresh_storage_summary()
        return result.to_dict()

    def clear_report_files(self) -> Dict[str, Any]:
        result = self._delete_files_in_folder(PATHS.reports_dir)
        self.refresh_storage_summary()
        return result.to_dict()

    def clear_log_files(self) -> Dict[str, Any]:
        result = self._delete_files_in_folder(PATHS.logs_dir, allowed_suffixes=[".log"])
        self.refresh_storage_summary()
        return result.to_dict()

    # ========================================================
    # Database record cleanup helpers
    # ========================================================

    def clear_old_completed_records(
        self,
        *,
        keep_latest: int = 200,
        clear_reports: bool = False,
        clear_qr: bool = False,
    ) -> Dict[str, Any]:
        """
        Keep the latest N completed records and remove older completed DB rows.
        Optionally also clear generated report/QR files.
        """
        removed_rows = self._database_service.clear_old_completed_sessions(keep_latest=keep_latest)

        extra_cleanup: Dict[str, Any] = {}
        if clear_reports:
            extra_cleanup["reports"] = self.clear_report_files()
        if clear_qr:
            extra_cleanup["qr"] = self.clear_qr_files()

        payload = {
            "success": True,
            "removed_rows": safe_int(removed_rows, 0),
            "keep_latest": safe_int(keep_latest, 200),
            "extra_cleanup": extra_cleanup,
            "message": f"Cleared older completed records while keeping latest {keep_latest}.",
        }

        self._logger.info("Old completed records cleared. Removed rows=%s", removed_rows)
        self.records_cleared.emit(deep_copy(payload))
        self.refresh_storage_summary()
        return payload

    def clear_all_records(
        self,
        *,
        clear_reports: bool = False,
        clear_qr: bool = False,
        clear_exports: bool = False,
        clear_temp: bool = False,
    ) -> Dict[str, Any]:
        """
        Clear all health session records from the database.
        Optionally clear generated file folders too.
        """
        removed_rows = self._database_service.clear_all_sessions()

        cleanup_payload: Dict[str, Any] = {}
        if clear_reports:
            cleanup_payload["reports"] = self.clear_report_files()
        if clear_qr:
            cleanup_payload["qr"] = self.clear_qr_files()
        if clear_exports:
            cleanup_payload["exports"] = self.clear_export_files()
        if clear_temp:
            cleanup_payload["temp"] = self.clear_temp_files()

        payload = {
            "success": True,
            "removed_rows": safe_int(removed_rows, 0),
            "cleanup": cleanup_payload,
            "message": "All session records cleared.",
        }

        self._logger.warning("All session records cleared from storage service.")
        self.records_cleared.emit(deep_copy(payload))
        self.refresh_storage_summary()
        return payload

    # ========================================================
    # Convenience helpers for storage screen
    # ========================================================

    def people_measured_count(self) -> int:
        summary = self.get_storage_summary()
        return safe_int(summary.get("records", {}).get("people_measured_count"), 0)

    def total_records_count(self) -> int:
        summary = self.get_storage_summary()
        return safe_int(summary.get("records", {}).get("total_sessions"), 0)

    def completed_records_count(self) -> int:
        summary = self.get_storage_summary()
        return safe_int(summary.get("records", {}).get("completed_sessions"), 0)

    def storage_usage_percent_of_baseline(self) -> float:
        summary = self.get_storage_summary()
        return safe_float(summary.get("baseline_usage", {}).get("usage_percent_of_baseline"), 0.0)

    # ========================================================
    # Diagnostics
    # ========================================================

    def diagnostics(self) -> Dict[str, Any]:
        summary = self.get_storage_summary()
        return {
            "database_path": str(PATHS.db_file),
            "backups_dir": str(PATHS.backups_dir),
            "reports_dir": str(PATHS.reports_dir),
            "qr_dir": str(PATHS.qr_dir),
            "exports_dir": str(PATHS.exports_dir),
            "temp_dir": str(PATHS.temp_dir),
            "log_dir": str(PATHS.logs_dir),
            "people_measured_count": safe_int(summary.get("records", {}).get("people_measured_count"), 0),
            "project_storage_used_human": safe_str(summary.get("project_storage", {}).get("used_human"), "0 bytes"),
            "backup_count": safe_int(summary.get("backups", {}).get("count"), 0),
        }


# ============================================================
# Singleton accessor
# ============================================================

_STORAGE_SERVICE_SINGLETON: Optional[StorageService] = None


def get_storage_service(
    app_state: Optional[AppState] = None,
    database_service: Optional[DatabaseService] = None,
) -> StorageService:
    global _STORAGE_SERVICE_SINGLETON
    if _STORAGE_SERVICE_SINGLETON is None:
        _STORAGE_SERVICE_SINGLETON = StorageService(
            app_state=app_state,
            database_service=database_service,
        )
    return _STORAGE_SERVICE_SINGLETON