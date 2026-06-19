"""
services/database_service.py

SQLite database service for the CST Health Monitoring Station kiosk.

Why this file matters:
- It provides persistent storage for user measurement sessions
- It stores generated report / QR file references
- It supports admin audit trails for settings and calibration changes
- It exposes query helpers needed by storage, publish, report, and diagnosis flows
- It is designed to stay linked with AppState, later services, and future Raspberry Pi deployment

Design goals:
- Robust SQLite usage
- Safe table initialization on first run
- Clear schema for current and future project needs
- Compatible with demo mode and hardware mode
- Friendly helpers for analytics and admin screens
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

from PyQt6.QtCore import QObject, pyqtSignal

from config import PATHS
from core.app_state import AppState, get_app_state
from core.constants import (
    DATABASE_TABLE_CALIBRATION_AUDIT,
    DATABASE_TABLE_SESSIONS,
    DATABASE_TABLE_SETTINGS_AUDIT,
    METRIC_BMI,
    METRIC_HEIGHT,
    METRIC_PULSE,
    METRIC_RR,
    METRIC_SPO2,
    METRIC_TEMPERATURE,
    METRIC_WEIGHT,
    MODE_DEMO,
    MODE_HARDWARE,
    PUBLISH_METRIC_COUNT_MINIMUM,
    SEVERITY_ATTENTION,
    SEVERITY_CRITICAL,
    SEVERITY_NORMAL,
    SESSION_STATUS_CANCELLED,
    SESSION_STATUS_COMPLETE,
    SESSION_STATUS_ERROR,
    SESSION_STATUS_IDLE,
    SESSION_STATUS_MEASURING,
)
from core.logger import get_db_logger, log_exception
from core.utils import (
    deep_copy,
    directory_size_bytes,
    ensure_parent_directory,
    file_size_bytes,
    format_bytes,
    humanize_datetime,
    is_non_empty_string,
    json_dumps_compact,
    json_dumps_pretty,
    now_iso,
    safe_float,
    safe_int,
    safe_str,
    sqlite_row_to_dict,
    sqlite_rows_to_dicts,
)

logger = get_db_logger()


# ============================================================
# Schema constants
# ============================================================

SQLITE_PRAGMAS = [
    "PRAGMA foreign_keys = ON;",
    "PRAGMA journal_mode = WAL;",
    "PRAGMA synchronous = NORMAL;",
    "PRAGMA temp_store = MEMORY;",
    "PRAGMA cache_size = -2000;",
]

CREATE_TABLE_HEALTH_SESSIONS = f"""
CREATE TABLE IF NOT EXISTS {DATABASE_TABLE_SESSIONS} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT,
    measuring_started_at TEXT,
    completed_at TEXT,
    cancelled_at TEXT,
    report_path TEXT,
    qr_path TEXT,
    persisted INTEGER NOT NULL DEFAULT 0,
    measurement_progress INTEGER NOT NULL DEFAULT 0,
    measurement_step_message TEXT,
    measurement_complete_ratio REAL NOT NULL DEFAULT 0.0,
    source_label TEXT,
    weight REAL NOT NULL DEFAULT 0.0,
    height REAL NOT NULL DEFAULT 0.0,
    bmi REAL NOT NULL DEFAULT 0.0,
    temperature REAL NOT NULL DEFAULT 0.0,
    spo2 REAL NOT NULL DEFAULT 0.0,
    pulse_rate REAL NOT NULL DEFAULT 0.0,
    respiratory_rate REAL NOT NULL DEFAULT 0.0,
    diagnosis_summary TEXT,
    status_title TEXT,
    overall_severity TEXT,
    diagnosis_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

CREATE_INDEX_SESSIONS_SESSION_ID = f"""
CREATE INDEX IF NOT EXISTS idx_{DATABASE_TABLE_SESSIONS}_session_id
ON {DATABASE_TABLE_SESSIONS}(session_id);
"""

CREATE_INDEX_SESSIONS_CREATED_AT = f"""
CREATE INDEX IF NOT EXISTS idx_{DATABASE_TABLE_SESSIONS}_created_at
ON {DATABASE_TABLE_SESSIONS}(created_at DESC);
"""

CREATE_INDEX_SESSIONS_COMPLETED_AT = f"""
CREATE INDEX IF NOT EXISTS idx_{DATABASE_TABLE_SESSIONS}_completed_at
ON {DATABASE_TABLE_SESSIONS}(completed_at DESC);
"""

CREATE_INDEX_SESSIONS_STATUS = f"""
CREATE INDEX IF NOT EXISTS idx_{DATABASE_TABLE_SESSIONS}_status
ON {DATABASE_TABLE_SESSIONS}(status);
"""

CREATE_INDEX_SESSIONS_MODE = f"""
CREATE INDEX IF NOT EXISTS idx_{DATABASE_TABLE_SESSIONS}_mode
ON {DATABASE_TABLE_SESSIONS}(mode);
"""

CREATE_INDEX_SESSIONS_SEVERITY = f"""
CREATE INDEX IF NOT EXISTS idx_{DATABASE_TABLE_SESSIONS}_severity
ON {DATABASE_TABLE_SESSIONS}(overall_severity);
"""

CREATE_TABLE_SETTINGS_AUDIT = f"""
CREATE TABLE IF NOT EXISTS {DATABASE_TABLE_SETTINGS_AUDIT} (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    changed_at TEXT NOT NULL,
    actor TEXT,
    scope TEXT,
    key_path TEXT,
    before_json TEXT,
    after_json TEXT,
    note TEXT
);
"""

CREATE_TABLE_CALIBRATION_AUDIT = f"""
CREATE TABLE IF NOT EXISTS {DATABASE_TABLE_CALIBRATION_AUDIT} (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    changed_at TEXT NOT NULL,
    actor TEXT,
    sensor_key TEXT,
    before_json TEXT,
    after_json TEXT,
    note TEXT
);
"""

CREATE_INDEX_SETTINGS_AUDIT_CHANGED_AT = f"""
CREATE INDEX IF NOT EXISTS idx_{DATABASE_TABLE_SETTINGS_AUDIT}_changed_at
ON {DATABASE_TABLE_SETTINGS_AUDIT}(changed_at DESC);
"""

CREATE_INDEX_CALIBRATION_AUDIT_CHANGED_AT = f"""
CREATE INDEX IF NOT EXISTS idx_{DATABASE_TABLE_CALIBRATION_AUDIT}_changed_at
ON {DATABASE_TABLE_CALIBRATION_AUDIT}(changed_at DESC);
"""


# ============================================================
# Database service
# ============================================================

class DatabaseService(QObject):
    """
    Central SQLite persistence service.

    Main responsibilities:
    - initialize and validate SQLite database
    - save and update health session records
    - fetch recent sessions / completed sessions / specific session data
    - provide aggregate summaries for publish/storage screens
    - save settings and calibration audit logs
    """

    database_ready = pyqtSignal(str)
    database_error = pyqtSignal(str)
    session_saved = pyqtSignal(str)
    session_deleted = pyqtSignal(str)
    settings_audit_saved = pyqtSignal(str)
    calibration_audit_saved = pyqtSignal(str)

    def __init__(
        self,
        db_path: Optional[Path] = None,
        app_state: Optional[AppState] = None,
    ) -> None:
        super().__init__()
        self._logger = logger.bind(component="DatabaseService")
        self._db_path: Path = db_path or PATHS.db_file
        self._app_state: AppState = app_state or get_app_state()
        self._initialized: bool = False

        ensure_parent_directory(self._db_path)
        self.initialize()

    # ========================================================
    # Core connection helpers
    # ========================================================

    @property
    def db_path(self) -> Path:
        return self._db_path

    def initialize(self) -> bool:
        """
        Initialize database schema and pragmas.
        Safe to call multiple times.
        """
        try:
            ensure_parent_directory(self._db_path)

            with self._connect() as conn:
                self._apply_pragmas(conn)
                self._create_schema(conn)
                conn.commit()

            self._initialized = True
            self._logger.info("Database initialized at %s", self._db_path)
            self.database_ready.emit(str(self._db_path))
            return True

        except Exception as exc:
            self._initialized = False
            log_exception(self._logger, "Failed to initialize database", exc)
            self.database_error.emit(str(exc))
            return False

    def is_ready(self) -> bool:
        return self._initialized and self._db_path.exists()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """
        Open a SQLite connection with Row factory.
        """
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _apply_pragmas(self, conn: sqlite3.Connection) -> None:
        cursor = conn.cursor()
        for pragma in SQLITE_PRAGMAS:
            cursor.execute(pragma)

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        cursor = conn.cursor()
        cursor.execute(CREATE_TABLE_HEALTH_SESSIONS)
        cursor.execute(CREATE_INDEX_SESSIONS_SESSION_ID)
        cursor.execute(CREATE_INDEX_SESSIONS_CREATED_AT)
        cursor.execute(CREATE_INDEX_SESSIONS_COMPLETED_AT)
        cursor.execute(CREATE_INDEX_SESSIONS_STATUS)
        cursor.execute(CREATE_INDEX_SESSIONS_MODE)
        cursor.execute(CREATE_INDEX_SESSIONS_SEVERITY)

        cursor.execute(CREATE_TABLE_SETTINGS_AUDIT)
        cursor.execute(CREATE_TABLE_CALIBRATION_AUDIT)
        cursor.execute(CREATE_INDEX_SETTINGS_AUDIT_CHANGED_AT)
        cursor.execute(CREATE_INDEX_CALIBRATION_AUDIT_CHANGED_AT)

    # ========================================================
    # SQL execution helpers
    # ========================================================

    def _execute(
        self,
        sql: str,
        params: Sequence[Any] | Mapping[str, Any] | None = None,
        *,
        commit: bool = False,
    ) -> sqlite3.Cursor:
        """
        Execute SQL and return the cursor.
        """
        if params is None:
            params = []

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            if commit:
                conn.commit()
            return cursor

    def _execute_fetchone(
        self,
        sql: str,
        params: Sequence[Any] | Mapping[str, Any] | None = None,
    ) -> Optional[Dict[str, Any]]:
        if params is None:
            params = []

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            row = cursor.fetchone()
            return sqlite_row_to_dict(row) if row else None

    def _execute_fetchall(
        self,
        sql: str,
        params: Sequence[Any] | Mapping[str, Any] | None = None,
    ) -> List[Dict[str, Any]]:
        if params is None:
            params = []

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            return sqlite_rows_to_dicts(rows)

    def _execute_many(
        self,
        sql: str,
        seq_of_params: Iterable[Sequence[Any]],
        *,
        commit: bool = False,
    ) -> None:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.executemany(sql, seq_of_params)
            if commit:
                conn.commit()

    # ========================================================
    # Session record normalization
    # ========================================================

    def _normalize_session_record(
        self,
        session_record: Mapping[str, Any],
        diagnosis_payload: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Normalize and complete a session payload before database save.
        """
        diagnosis = deep_copy(dict(diagnosis_payload or {}))
        if not diagnosis and session_record.get("diagnosis_json"):
            try:
                diagnosis = json.loads(safe_str(session_record.get("diagnosis_json"), "{}"))
            except Exception:
                diagnosis = {}

        created_at = safe_str(session_record.get("created_at"), "").strip() or now_iso()
        updated_at = now_iso()

        normalized = {
            "session_id": safe_str(session_record.get("session_id"), "").strip(),
            "mode": safe_str(session_record.get("mode"), MODE_DEMO).strip().lower() or MODE_DEMO,
            "status": safe_str(session_record.get("status"), SESSION_STATUS_IDLE).strip().lower() or SESSION_STATUS_IDLE,
            "started_at": safe_str(session_record.get("started_at"), ""),
            "measuring_started_at": safe_str(session_record.get("measuring_started_at"), ""),
            "completed_at": safe_str(session_record.get("completed_at"), ""),
            "cancelled_at": safe_str(session_record.get("cancelled_at"), ""),
            "report_path": safe_str(session_record.get("report_path"), ""),
            "qr_path": safe_str(session_record.get("qr_path"), ""),
            "persisted": 1 if bool(session_record.get("persisted", False)) else 0,
            "measurement_progress": safe_int(session_record.get("measurement_progress"), 0),
            "measurement_step_message": safe_str(session_record.get("measurement_step_message"), ""),
            "measurement_complete_ratio": safe_float(session_record.get("measurement_complete_ratio"), 0.0),
            "source_label": safe_str(session_record.get("source_label"), ""),
            "weight": safe_float(session_record.get("weight"), 0.0),
            "height": safe_float(session_record.get("height"), 0.0),
            "bmi": safe_float(session_record.get("bmi"), 0.0),
            "temperature": safe_float(session_record.get("temperature"), 0.0),
            "spo2": safe_float(session_record.get("spo2"), 0.0),
            "pulse_rate": safe_float(session_record.get("pulse_rate"), 0.0),
            "respiratory_rate": safe_float(session_record.get("respiratory_rate"), 0.0),
            "diagnosis_summary": safe_str(session_record.get("diagnosis_summary"), safe_str(diagnosis.get("summary"), "")),
            "status_title": safe_str(session_record.get("status_title"), safe_str(diagnosis.get("status_title"), "")),
            "overall_severity": safe_str(session_record.get("overall_severity"), safe_str(diagnosis.get("overall_severity"), "")),
            "diagnosis_json": json_dumps_compact(diagnosis) if diagnosis else "",
            "created_at": created_at,
            "updated_at": updated_at,
        }

        return normalized

    def _decode_session_row(self, row: Mapping[str, Any]) -> Dict[str, Any]:
        """
        Convert raw DB row to a richer application-friendly record.
        """
        record = dict(row)

        diagnosis_json = safe_str(record.get("diagnosis_json"), "").strip()
        if diagnosis_json:
            try:
                record["diagnosis"] = json.loads(diagnosis_json)
            except Exception:
                record["diagnosis"] = {}
        else:
            record["diagnosis"] = {}

        record["persisted"] = bool(record.get("persisted", 0))
        record["created_at_human"] = humanize_datetime(record.get("created_at"))
        record["completed_at_human"] = humanize_datetime(record.get("completed_at"))
        record["started_at_human"] = humanize_datetime(record.get("started_at"))

        record["measurements"] = {
            METRIC_WEIGHT: safe_float(record.get("weight"), 0.0),
            METRIC_HEIGHT: safe_float(record.get("height"), 0.0),
            METRIC_BMI: safe_float(record.get("bmi"), 0.0),
            METRIC_TEMPERATURE: safe_float(record.get("temperature"), 0.0),
            METRIC_SPO2: safe_float(record.get("spo2"), 0.0),
            METRIC_PULSE: safe_float(record.get("pulse_rate"), 0.0),
            METRIC_RR: safe_float(record.get("respiratory_rate"), 0.0),
        }

        return record

    # ========================================================
    # Session save / update
    # ========================================================

    def session_exists(self, session_id: str) -> bool:
        if not is_non_empty_string(session_id):
            return False

        row = self._execute_fetchone(
            f"SELECT session_id FROM {DATABASE_TABLE_SESSIONS} WHERE session_id = ? LIMIT 1",
            [session_id],
        )
        return row is not None

    def save_session(
        self,
        session_record: Mapping[str, Any],
        diagnosis_payload: Optional[Mapping[str, Any]] = None,
    ) -> str:
        """
        Insert or update a session record using session_id as unique key.
        Returns the saved session_id.
        """
        normalized = self._normalize_session_record(session_record, diagnosis_payload=diagnosis_payload)
        session_id = normalized["session_id"]

        if not session_id:
            raise ValueError("Cannot save session without session_id.")

        existing = self.session_exists(session_id)

        if existing:
            sql = f"""
            UPDATE {DATABASE_TABLE_SESSIONS}
            SET
                mode = :mode,
                status = :status,
                started_at = :started_at,
                measuring_started_at = :measuring_started_at,
                completed_at = :completed_at,
                cancelled_at = :cancelled_at,
                report_path = :report_path,
                qr_path = :qr_path,
                persisted = :persisted,
                measurement_progress = :measurement_progress,
                measurement_step_message = :measurement_step_message,
                measurement_complete_ratio = :measurement_complete_ratio,
                source_label = :source_label,
                weight = :weight,
                height = :height,
                bmi = :bmi,
                temperature = :temperature,
                spo2 = :spo2,
                pulse_rate = :pulse_rate,
                respiratory_rate = :respiratory_rate,
                diagnosis_summary = :diagnosis_summary,
                status_title = :status_title,
                overall_severity = :overall_severity,
                diagnosis_json = :diagnosis_json,
                updated_at = :updated_at
            WHERE session_id = :session_id
            """
        else:
            sql = f"""
            INSERT INTO {DATABASE_TABLE_SESSIONS} (
                session_id, mode, status, started_at, measuring_started_at, completed_at, cancelled_at,
                report_path, qr_path, persisted, measurement_progress, measurement_step_message,
                measurement_complete_ratio, source_label, weight, height, bmi, temperature, spo2,
                pulse_rate, respiratory_rate, diagnosis_summary, status_title, overall_severity,
                diagnosis_json, created_at, updated_at
            ) VALUES (
                :session_id, :mode, :status, :started_at, :measuring_started_at, :completed_at, :cancelled_at,
                :report_path, :qr_path, :persisted, :measurement_progress, :measurement_step_message,
                :measurement_complete_ratio, :source_label, :weight, :height, :bmi, :temperature, :spo2,
                :pulse_rate, :respiratory_rate, :diagnosis_summary, :status_title, :overall_severity,
                :diagnosis_json, :created_at, :updated_at
            )
            """

        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, normalized)
                conn.commit()

            self._logger.info(
                "Session saved.",
                extra={
                    "session_id": session_id,
                    "mode": normalized["mode"],
                },
            )
            self.session_saved.emit(session_id)
            return session_id

        except Exception as exc:
            log_exception(
                self._logger.bind(session_id=session_id, mode=normalized["mode"]),
                "Failed to save session",
                exc,
            )
            self.database_error.emit(str(exc))
            raise

    def save_current_app_state_session(self) -> str:
        """
        Save whatever is currently in AppState.
        """
        session_record = self._app_state.export_current_session_record()
        session_id = self.save_session(
            session_record=session_record,
            diagnosis_payload=self._app_state.current_diagnosis(),
        )
        self._app_state.set_session_persisted(True)
        return session_id

    def mark_session_persisted(self, session_id: str, persisted: bool = True) -> bool:
        if not is_non_empty_string(session_id):
            return False

        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"""
                    UPDATE {DATABASE_TABLE_SESSIONS}
                    SET persisted = ?, updated_at = ?
                    WHERE session_id = ?
                    """,
                    [1 if persisted else 0, now_iso(), session_id],
                )
                conn.commit()

            self._logger.info("Session persisted flag updated.", extra={"session_id": session_id})
            return True
        except Exception as exc:
            log_exception(self._logger.bind(session_id=session_id), "Failed to update persisted flag", exc)
            self.database_error.emit(str(exc))
            return False

    def delete_session(self, session_id: str) -> bool:
        if not is_non_empty_string(session_id):
            return False

        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"DELETE FROM {DATABASE_TABLE_SESSIONS} WHERE session_id = ?",
                    [session_id],
                )
                conn.commit()

            self._logger.info("Session deleted.", extra={"session_id": session_id})
            self.session_deleted.emit(session_id)
            return True

        except Exception as exc:
            log_exception(self._logger.bind(session_id=session_id), "Failed to delete session", exc)
            self.database_error.emit(str(exc))
            return False

    # ========================================================
    # Session fetch helpers
    # ========================================================

    def get_session_by_session_id(self, session_id: str) -> Optional[Dict[str, Any]]:
        if not is_non_empty_string(session_id):
            return None

        row = self._execute_fetchone(
            f"SELECT * FROM {DATABASE_TABLE_SESSIONS} WHERE session_id = ? LIMIT 1",
            [session_id],
        )
        return self._decode_session_row(row) if row else None

    def get_last_session(self) -> Optional[Dict[str, Any]]:
        row = self._execute_fetchone(
            f"""
            SELECT * FROM {DATABASE_TABLE_SESSIONS}
            ORDER BY created_at DESC
            LIMIT 1
            """
        )
        return self._decode_session_row(row) if row else None

    def get_recent_sessions(
        self,
        limit: int = 50,
        *,
        mode: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        limit = max(1, safe_int(limit, 50))
        params: List[Any] = []
        where_clauses: List[str] = []

        if is_non_empty_string(mode):
            where_clauses.append("mode = ?")
            params.append(str(mode).strip().lower())

        if is_non_empty_string(status):
            where_clauses.append("status = ?")
            params.append(str(status).strip().lower())

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        rows = self._execute_fetchall(
            f"""
            SELECT * FROM {DATABASE_TABLE_SESSIONS}
            {where_sql}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            [*params, limit],
        )
        return [self._decode_session_row(row) for row in rows]

    def get_completed_sessions(self, limit: int = 200) -> List[Dict[str, Any]]:
        return self.get_recent_sessions(limit=limit, status=SESSION_STATUS_COMPLETE)

    def get_sessions_for_publish(self, limit: int = 500) -> List[Dict[str, Any]]:
        """
        Publish/analytics usually uses completed sessions.
        """
        return self.get_completed_sessions(limit=limit)

    def get_sessions_count(self) -> int:
        row = self._execute_fetchone(f"SELECT COUNT(*) AS count FROM {DATABASE_TABLE_SESSIONS}")
        return safe_int((row or {}).get("count"), 0)

    def get_completed_sessions_count(self) -> int:
        row = self._execute_fetchone(
            f"""
            SELECT COUNT(*) AS count
            FROM {DATABASE_TABLE_SESSIONS}
            WHERE status = ?
            """,
            [SESSION_STATUS_COMPLETE],
        )
        return safe_int((row or {}).get("count"), 0)

    def get_status_counts(self) -> Dict[str, int]:
        rows = self._execute_fetchall(
            f"""
            SELECT status, COUNT(*) AS count
            FROM {DATABASE_TABLE_SESSIONS}
            GROUP BY status
            """
        )

        counts = {
            SESSION_STATUS_IDLE: 0,
            SESSION_STATUS_MEASURING: 0,
            SESSION_STATUS_COMPLETE: 0,
            SESSION_STATUS_CANCELLED: 0,
            SESSION_STATUS_ERROR: 0,
        }
        for row in rows:
            status = safe_str(row.get("status"), "").strip().lower()
            counts[status] = safe_int(row.get("count"), 0)

        return counts

    def get_mode_counts(self) -> Dict[str, int]:
        rows = self._execute_fetchall(
            f"""
            SELECT mode, COUNT(*) AS count
            FROM {DATABASE_TABLE_SESSIONS}
            GROUP BY mode
            """
        )

        counts = {
            MODE_DEMO: 0,
            MODE_HARDWARE: 0,
        }
        for row in rows:
            mode = safe_str(row.get("mode"), "").strip().lower()
            counts[mode] = safe_int(row.get("count"), 0)

        return counts

    def get_severity_counts(self) -> Dict[str, int]:
        rows = self._execute_fetchall(
            f"""
            SELECT overall_severity, COUNT(*) AS count
            FROM {DATABASE_TABLE_SESSIONS}
            WHERE overall_severity IS NOT NULL AND overall_severity != ''
            GROUP BY overall_severity
            """
        )

        counts = {
            SEVERITY_NORMAL: 0,
            SEVERITY_ATTENTION: 0,
            SEVERITY_CRITICAL: 0,
        }
        for row in rows:
            severity = safe_str(row.get("overall_severity"), "").strip().lower()
            counts[severity] = safe_int(row.get("count"), 0)

        return counts

    # ========================================================
    # Aggregate helpers for storage / publish screens
    # ========================================================

    def get_metric_averages(self) -> Dict[str, float]:
        row = self._execute_fetchone(
            f"""
            SELECT
                AVG(weight) AS avg_weight,
                AVG(height) AS avg_height,
                AVG(bmi) AS avg_bmi,
                AVG(temperature) AS avg_temperature,
                AVG(spo2) AS avg_spo2,
                AVG(pulse_rate) AS avg_pulse_rate,
                AVG(respiratory_rate) AS avg_respiratory_rate
            FROM {DATABASE_TABLE_SESSIONS}
            WHERE status = ?
            """,
            [SESSION_STATUS_COMPLETE],
        ) or {}

        return {
            METRIC_WEIGHT: safe_float(row.get("avg_weight"), 0.0),
            METRIC_HEIGHT: safe_float(row.get("avg_height"), 0.0),
            METRIC_BMI: safe_float(row.get("avg_bmi"), 0.0),
            METRIC_TEMPERATURE: safe_float(row.get("avg_temperature"), 0.0),
            METRIC_SPO2: safe_float(row.get("avg_spo2"), 0.0),
            METRIC_PULSE: safe_float(row.get("avg_pulse_rate"), 0.0),
            METRIC_RR: safe_float(row.get("avg_respiratory_rate"), 0.0),
        }

    def get_basic_publish_summary(self) -> Dict[str, Any]:
        """
        Basic aggregate summary. More polished narrative logic can be added in publish_service.py,
        but this gives a strong backend foundation.
        """
        total_records = self.get_sessions_count()
        completed_records = self.get_completed_sessions_count()
        status_counts = self.get_status_counts()
        mode_counts = self.get_mode_counts()
        severity_counts = self.get_severity_counts()
        averages = self.get_metric_averages()

        summary: Dict[str, Any] = {
            "total_records": total_records,
            "completed_records": completed_records,
            "status_counts": status_counts,
            "mode_counts": mode_counts,
            "severity_counts": severity_counts,
            "averages": averages,
            "insights": [],
        }

        if completed_records < PUBLISH_METRIC_COUNT_MINIMUM:
            summary["insights"].append("Not enough completed records for trend analysis.")
            return summary

        avg_bmi = averages.get(METRIC_BMI, 0.0)
        avg_temp = averages.get(METRIC_TEMPERATURE, 0.0)
        avg_spo2 = averages.get(METRIC_SPO2, 0.0)
        avg_pulse = averages.get(METRIC_PULSE, 0.0)
        avg_rr = averages.get(METRIC_RR, 0.0)

        if avg_bmi >= 30.0:
            summary["insights"].append("Average BMI is in the obese range.")
        elif avg_bmi >= 25.0:
            summary["insights"].append("Average BMI is in the overweight range.")
        elif avg_bmi >= 18.5:
            summary["insights"].append("Average BMI is within the normal range.")
        elif avg_bmi > 0:
            summary["insights"].append("Average BMI is in the underweight range.")

        if avg_temp >= 38.1:
            summary["insights"].append("Average temperature suggests high fever trend in recent completed records.")
        elif avg_temp >= 37.1:
            summary["insights"].append("Average temperature suggests mild fever trend in recent completed records.")

        if 0 < avg_spo2 < 95:
            summary["insights"].append("Average SpO₂ is below the ideal normal level.")
        if avg_pulse > 100:
            summary["insights"].append("Average pulse rate is above the normal resting range.")
        if avg_rr > 20:
            summary["insights"].append("Average respiratory rate is above the normal resting range.")

        return summary

    # ========================================================
    # Settings / calibration audit tables
    # ========================================================

    def save_settings_audit(
        self,
        *,
        actor: str = "admin",
        scope: str = "",
        key_path: str = "",
        before_payload: Optional[Mapping[str, Any]] = None,
        after_payload: Optional[Mapping[str, Any]] = None,
        note: str = "",
    ) -> int:
        changed_at = now_iso()
        before_json = json_dumps_pretty(dict(before_payload or {}))
        after_json = json_dumps_pretty(dict(after_payload or {}))

        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"""
                    INSERT INTO {DATABASE_TABLE_SETTINGS_AUDIT} (
                        changed_at, actor, scope, key_path, before_json, after_json, note
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        changed_at,
                        safe_str(actor, "admin"),
                        safe_str(scope, ""),
                        safe_str(key_path, ""),
                        before_json,
                        after_json,
                        safe_str(note, ""),
                    ],
                )
                conn.commit()
                audit_id = safe_int(cursor.lastrowid, 0)

            self._logger.info("Settings audit saved.")
            self.settings_audit_saved.emit(str(audit_id))
            return audit_id

        except Exception as exc:
            log_exception(self._logger, "Failed to save settings audit", exc)
            self.database_error.emit(str(exc))
            raise

    def save_calibration_audit(
        self,
        *,
        actor: str = "admin",
        sensor_key: str = "",
        before_payload: Optional[Mapping[str, Any]] = None,
        after_payload: Optional[Mapping[str, Any]] = None,
        note: str = "",
    ) -> int:
        changed_at = now_iso()
        before_json = json_dumps_pretty(dict(before_payload or {}))
        after_json = json_dumps_pretty(dict(after_payload or {}))

        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"""
                    INSERT INTO {DATABASE_TABLE_CALIBRATION_AUDIT} (
                        changed_at, actor, sensor_key, before_json, after_json, note
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        changed_at,
                        safe_str(actor, "admin"),
                        safe_str(sensor_key, ""),
                        before_json,
                        after_json,
                        safe_str(note, ""),
                    ],
                )
                conn.commit()
                audit_id = safe_int(cursor.lastrowid, 0)

            self._logger.info("Calibration audit saved.")
            self.calibration_audit_saved.emit(str(audit_id))
            return audit_id

        except Exception as exc:
            log_exception(self._logger, "Failed to save calibration audit", exc)
            self.database_error.emit(str(exc))
            raise

    def get_recent_settings_audits(self, limit: int = 50) -> List[Dict[str, Any]]:
        limit = max(1, safe_int(limit, 50))
        rows = self._execute_fetchall(
            f"""
            SELECT * FROM {DATABASE_TABLE_SETTINGS_AUDIT}
            ORDER BY changed_at DESC
            LIMIT ?
            """,
            [limit],
        )
        return rows

    def get_recent_calibration_audits(self, limit: int = 50) -> List[Dict[str, Any]]:
        limit = max(1, safe_int(limit, 50))
        rows = self._execute_fetchall(
            f"""
            SELECT * FROM {DATABASE_TABLE_CALIBRATION_AUDIT}
            ORDER BY changed_at DESC
            LIMIT ?
            """,
            [limit],
        )
        return rows

    # ========================================================
    # Cleanup helpers
    # ========================================================

    def clear_all_sessions(self) -> int:
        """
        Delete all session rows.
        Returns the number of rows affected if available.
        """
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(f"DELETE FROM {DATABASE_TABLE_SESSIONS}")
                affected = safe_int(cursor.rowcount, 0)
                conn.commit()

            self._logger.warning("All session rows cleared from database.")
            return affected
        except Exception as exc:
            log_exception(self._logger, "Failed to clear all sessions", exc)
            self.database_error.emit(str(exc))
            return 0

    def clear_old_completed_sessions(self, keep_latest: int = 200) -> int:
        """
        Keep the latest N completed sessions and delete older completed ones.
        """
        keep_latest = max(0, safe_int(keep_latest, 200))

        try:
            with self._connect() as conn:
                cursor = conn.cursor()

                # Find ids to keep
                cursor.execute(
                    f"""
                    SELECT id
                    FROM {DATABASE_TABLE_SESSIONS}
                    WHERE status = ?
                    ORDER BY completed_at DESC, created_at DESC
                    LIMIT ?
                    """,
                    [SESSION_STATUS_COMPLETE, keep_latest],
                )
                keep_rows = cursor.fetchall()
                keep_ids = [row["id"] for row in keep_rows]

                if keep_ids:
                    placeholders = ",".join(["?"] * len(keep_ids))
                    sql = f"""
                    DELETE FROM {DATABASE_TABLE_SESSIONS}
                    WHERE status = ?
                      AND id NOT IN ({placeholders})
                    """
                    cursor.execute(sql, [SESSION_STATUS_COMPLETE, *keep_ids])
                else:
                    cursor.execute(
                        f"DELETE FROM {DATABASE_TABLE_SESSIONS} WHERE status = ?",
                        [SESSION_STATUS_COMPLETE],
                    )

                affected = safe_int(cursor.rowcount, 0)
                conn.commit()

            self._logger.info("Old completed sessions cleared.", extra={"mode": self._app_state.runtime_mode()})
            return affected

        except Exception as exc:
            log_exception(self._logger, "Failed to clear old completed sessions", exc)
            self.database_error.emit(str(exc))
            return 0

    # ========================================================
    # Storage / database file metadata
    # ========================================================

    def get_database_file_info(self) -> Dict[str, Any]:
        """
        Return useful DB file metadata for storage/admin screens.
        """
        size_bytes = file_size_bytes(self._db_path)

        return {
            "db_path": str(self._db_path),
            "db_exists": self._db_path.exists(),
            "db_size_bytes": size_bytes,
            "db_size_human": format_bytes(size_bytes),
            "db_parent_dir": str(self._db_path.parent),
        }

    def get_storage_summary(self) -> Dict[str, Any]:
        """
        Build a storage-oriented summary from the database plus data folders.
        """
        db_info = self.get_database_file_info()
        reports_bytes = directory_size_bytes(PATHS.reports_dir)
        qr_bytes = directory_size_bytes(PATHS.qr_dir)
        backup_bytes = directory_size_bytes(PATHS.backups_dir)
        export_bytes = directory_size_bytes(PATHS.exports_dir)
        temp_bytes = directory_size_bytes(PATHS.temp_dir)

        total_app_bytes = (
            db_info["db_size_bytes"] +
            reports_bytes +
            qr_bytes +
            backup_bytes +
            export_bytes +
            temp_bytes
        )

        summary = {
            "database": db_info,
            "folders": {
                "reports_bytes": reports_bytes,
                "reports_human": format_bytes(reports_bytes),
                "qr_bytes": qr_bytes,
                "qr_human": format_bytes(qr_bytes),
                "backups_bytes": backup_bytes,
                "backups_human": format_bytes(backup_bytes),
                "exports_bytes": export_bytes,
                "exports_human": format_bytes(export_bytes),
                "temp_bytes": temp_bytes,
                "temp_human": format_bytes(temp_bytes),
            },
            "record_counts": {
                "total_sessions": self.get_sessions_count(),
                "completed_sessions": self.get_completed_sessions_count(),
                "status_counts": self.get_status_counts(),
                "mode_counts": self.get_mode_counts(),
            },
            "total_app_storage_bytes": total_app_bytes,
            "total_app_storage_human": format_bytes(total_app_bytes),
        }
        return summary

    # ========================================================
    # Diagnostics
    # ========================================================

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "initialized": self._initialized,
            "db_path": str(self._db_path),
            "db_exists": self._db_path.exists(),
            "total_records": self.get_sessions_count() if self._initialized else 0,
            "completed_records": self.get_completed_sessions_count() if self._initialized else 0,
            "status_counts": self.get_status_counts() if self._initialized else {},
            "mode_counts": self.get_mode_counts() if self._initialized else {},
        }


# ============================================================
# Singleton accessor
# ============================================================

_DATABASE_SERVICE_SINGLETON: Optional[DatabaseService] = None


def get_database_service(
    db_path: Optional[Path] = None,
    app_state: Optional[AppState] = None,
) -> DatabaseService:
    global _DATABASE_SERVICE_SINGLETON
    if _DATABASE_SERVICE_SINGLETON is None:
        _DATABASE_SERVICE_SINGLETON = DatabaseService(db_path=db_path, app_state=app_state)
    return _DATABASE_SERVICE_SINGLETON