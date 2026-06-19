"""
core/logger.py

Central logging system for the CST Health Monitoring Station kiosk.

Goals:
- Provide a clean, reusable logging API for all modules
- Keep log formatting consistent across the project
- Support separate app log and serial log files
- Work safely on laptop demo mode and Raspberry Pi hardware mode
- Avoid duplicate handlers during repeated imports or hot reloads
- Allow later modules to bind useful context like session_id, route, mode

Expected usage later:
    from core.logger import get_logger

    logger = get_logger(__name__)
    logger.info("Database initialized")

    serial_logger = get_logger(__name__, scope="serial")
    serial_logger.warning("Serial timeout waiting for sensor packet")

    bound = logger.bind(session_id="ABC123", route="results", mode="demo")
    bound.info("Showing results screen")
"""

from __future__ import annotations

import logging
import os
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from config import PATHS
from core.constants import (
    LOG_SCOPE_APP,
    LOG_SCOPE_DB,
    LOG_SCOPE_NAVIGATOR,
    LOG_SCOPE_PUBLISH,
    LOG_SCOPE_QR,
    LOG_SCOPE_REPORT,
    LOG_SCOPE_SENSOR,
    LOG_SCOPE_SERIAL,
    LOG_SCOPE_SETTINGS,
    LOG_SCOPE_STORAGE,
    LOG_SCOPE_UI,
    LOG_SCOPES,
)


# ============================================================
# Logging defaults
# ============================================================

LOGGER_NAMESPACE = "cst_health_kiosk"

DEFAULT_LOG_LEVEL_NAME = os.getenv("CST_KIOSK_LOG_LEVEL", "INFO").upper()
DEFAULT_LOG_LEVEL = getattr(logging, DEFAULT_LOG_LEVEL_NAME, logging.INFO)

CONSOLE_LOG_LEVEL_NAME = os.getenv("CST_KIOSK_CONSOLE_LOG_LEVEL", DEFAULT_LOG_LEVEL_NAME).upper()
CONSOLE_LOG_LEVEL = getattr(logging, CONSOLE_LOG_LEVEL_NAME, DEFAULT_LOG_LEVEL)

FILE_LOG_LEVEL_NAME = os.getenv("CST_KIOSK_FILE_LOG_LEVEL", DEFAULT_LOG_LEVEL_NAME).upper()
FILE_LOG_LEVEL = getattr(logging, FILE_LOG_LEVEL_NAME, DEFAULT_LOG_LEVEL)

# Log rotation kept modest for Raspberry Pi friendliness.
MAX_LOG_BYTES = int(os.getenv("CST_KIOSK_MAX_LOG_BYTES", str(2 * 1024 * 1024)))  # 2 MB
BACKUP_COUNT = int(os.getenv("CST_KIOSK_LOG_BACKUP_COUNT", "5"))

DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(scope)s | %(component)s | "
    "session=%(session_id)s | route=%(route)s | mode=%(mode)s | %(message)s"
)

# Optional environment flag to reduce console noise in deployment
ENABLE_CONSOLE_LOGGING = os.getenv("CST_KIOSK_ENABLE_CONSOLE_LOGGING", "1").strip() not in {"0", "false", "False"}

# Internal registry so handlers are not attached repeatedly
_LOGGER_CACHE: Dict[str, "KioskLoggerAdapter"] = {}
_BASE_LOGGER_CACHE: Dict[str, logging.Logger] = {}
_LOGGING_READY = False


# ============================================================
# Formatter
# ============================================================

class KioskFormatter(logging.Formatter):
    """
    Safe formatter that ensures custom fields always exist.
    This prevents KeyError when format strings reference custom values.
    """

    DEFAULT_RECORD_VALUES = {
        "scope": LOG_SCOPE_APP,
        "component": "app",
        "session_id": "-",
        "route": "-",
        "mode": "-",
    }

    def format(self, record: logging.LogRecord) -> str:
        for field_name, default_value in self.DEFAULT_RECORD_VALUES.items():
            if not hasattr(record, field_name):
                setattr(record, field_name, default_value)
        return super().format(record)


# ============================================================
# Logger adapter with bind() support
# ============================================================

class KioskLoggerAdapter(logging.LoggerAdapter):
    """
    Logger adapter that:
    - injects structured extra fields
    - supports .bind(...) to create contextual loggers
    - supports .event(...) convenience helper
    """

    def process(self, msg: str, kwargs: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
        extra = kwargs.get("extra", {})
        if extra is None:
            extra = {}

        merged = dict(self.extra)
        merged.update(extra)
        kwargs["extra"] = merged
        return msg, kwargs

    def bind(self, **context: Any) -> "KioskLoggerAdapter":
        merged = dict(self.extra)
        merged.update(context)
        return KioskLoggerAdapter(self.logger, merged)

    def event(self, level: int, message: str, **fields: Any) -> None:
        self.log(level, message, extra=fields)

    def debug_event(self, message: str, **fields: Any) -> None:
        self.event(logging.DEBUG, message, **fields)

    def info_event(self, message: str, **fields: Any) -> None:
        self.event(logging.INFO, message, **fields)

    def warning_event(self, message: str, **fields: Any) -> None:
        self.event(logging.WARNING, message, **fields)

    def error_event(self, message: str, **fields: Any) -> None:
        self.event(logging.ERROR, message, **fields)

    def critical_event(self, message: str, **fields: Any) -> None:
        self.event(logging.CRITICAL, message, **fields)


# ============================================================
# Internal helper functions
# ============================================================

def _ensure_log_directory() -> None:
    PATHS.logs_dir.mkdir(parents=True, exist_ok=True)


def _get_log_file_for_scope(scope: str) -> Path:
    """
    Serial logs go to serial.log, everything else goes to app.log.
    """
    return PATHS.serial_log_file if scope == LOG_SCOPE_SERIAL else PATHS.app_log_file


def _normalize_scope(scope: Optional[str]) -> str:
    if not scope:
        return LOG_SCOPE_APP
    normalized = str(scope).strip().lower()
    return normalized if normalized else LOG_SCOPE_APP


def _infer_scope_from_name(name: Optional[str]) -> str:
    """
    Infer a stable scope from a module path or plain logger name.
    This helps later files call get_logger(__name__) naturally.
    """
    if not name:
        return LOG_SCOPE_APP

    candidate = name.strip().lower()

    if candidate in LOG_SCOPES:
        return candidate

    # Inference from module/component names
    if "serial" in candidate:
        return LOG_SCOPE_SERIAL
    if "sensor" in candidate:
        return LOG_SCOPE_SENSOR
    if "database" in candidate or candidate.endswith(".db") or ".db" in candidate:
        return LOG_SCOPE_DB
    if "settings" in candidate:
        return LOG_SCOPE_SETTINGS
    if "storage" in candidate:
        return LOG_SCOPE_STORAGE
    if "report" in candidate:
        return LOG_SCOPE_REPORT
    if candidate.endswith("qr") or ".qr" in candidate or "qr_service" in candidate:
        return LOG_SCOPE_QR
    if "publish" in candidate:
        return LOG_SCOPE_PUBLISH
    if "navigator" in candidate:
        return LOG_SCOPE_NAVIGATOR
    if "screen" in candidate or "widget" in candidate or "ui" in candidate:
        return LOG_SCOPE_UI

    return LOG_SCOPE_APP


def _create_formatter() -> KioskFormatter:
    return KioskFormatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT)


def _create_console_handler() -> logging.Handler:
    console_handler = logging.StreamHandler()
    console_handler.setLevel(CONSOLE_LOG_LEVEL)
    console_handler.setFormatter(_create_formatter())
    return console_handler


def _create_rotating_file_handler(file_path: Path) -> RotatingFileHandler:
    file_handler = RotatingFileHandler(
        filename=str(file_path),
        maxBytes=MAX_LOG_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(FILE_LOG_LEVEL)
    file_handler.setFormatter(_create_formatter())
    return file_handler


def _clear_existing_handlers(logger: logging.Logger) -> None:
    """
    Remove existing handlers if we are reconfiguring during development.
    """
    if logger.handlers:
        for handler in list(logger.handlers):
            try:
                handler.flush()
                handler.close()
            except Exception:
                pass
            logger.removeHandler(handler)


def _build_base_logger(scope: str) -> logging.Logger:
    """
    Create a base logger for a given logical scope.
    Each scope gets:
    - one rotating file handler
    - optional console handler
    - no propagation to avoid duplicate lines
    """
    normalized_scope = _normalize_scope(scope)
    logger_name = f"{LOGGER_NAMESPACE}.{normalized_scope}"
    logger = logging.getLogger(logger_name)

    # Avoid reusing partially configured handlers from repeated imports
    _clear_existing_handlers(logger)

    logger.setLevel(min(FILE_LOG_LEVEL, CONSOLE_LOG_LEVEL, DEFAULT_LOG_LEVEL))
    logger.propagate = False

    log_file = _get_log_file_for_scope(normalized_scope)
    logger.addHandler(_create_rotating_file_handler(log_file))

    if ENABLE_CONSOLE_LOGGING:
        logger.addHandler(_create_console_handler())

    return logger


def _get_or_create_base_logger(scope: str) -> logging.Logger:
    normalized_scope = _normalize_scope(scope)
    cached = _BASE_LOGGER_CACHE.get(normalized_scope)
    if cached is not None:
        return cached

    logger = _build_base_logger(normalized_scope)
    _BASE_LOGGER_CACHE[normalized_scope] = logger
    return logger


def _adapter_cache_key(name: str, scope: str, extra: Optional[Dict[str, Any]] = None) -> str:
    extra_items = ""
    if extra:
        pairs = [f"{k}={extra[k]}" for k in sorted(extra.keys())]
        extra_items = "|".join(pairs)
    return f"{scope}::{name}::{extra_items}"


# ============================================================
# Public configuration API
# ============================================================

def configure_logging(force: bool = False) -> None:
    """
    Prepare logging system and log directory.
    Safe to call multiple times.
    """
    global _LOGGING_READY

    if _LOGGING_READY and not force:
        return

    _ensure_log_directory()

    if force:
        # Fully reset caches and rebuild later on demand
        shutdown_logging(clear_cache=True)

    _LOGGING_READY = True


def shutdown_logging(clear_cache: bool = True) -> None:
    """
    Flush and close all handlers.
    Useful for tests or app shutdown.
    """
    global _LOGGING_READY

    for logger in list(_BASE_LOGGER_CACHE.values()):
        for handler in list(logger.handlers):
            try:
                handler.flush()
                handler.close()
            except Exception:
                pass
            logger.removeHandler(handler)

    if clear_cache:
        _BASE_LOGGER_CACHE.clear()
        _LOGGER_CACHE.clear()

    _LOGGING_READY = False


def set_global_log_level(level: int | str) -> None:
    """
    Update log level for all configured base loggers.
    """
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    for logger in _BASE_LOGGER_CACHE.values():
        logger.setLevel(level)
        for handler in logger.handlers:
            handler.setLevel(level)


# ============================================================
# Public logger getters
# ============================================================

def get_logger(
    name: Optional[str] = None,
    scope: Optional[str] = None,
    **context: Any,
) -> KioskLoggerAdapter:
    """
    Return a contextual logger adapter.

    Parameters:
    - name: usually __name__ or a short component label
    - scope: optional logical scope (app, serial, db, ui, etc.)
    - context: any extra fields like session_id, route, mode

    Example:
        logger = get_logger(__name__)
        logger.info("Starting")

        db_logger = get_logger(__name__, scope="database")
        db_logger.info("Connected")

        results_logger = get_logger(__name__, route="results", mode="demo")
        results_logger.info("Rendering results screen")
    """
    configure_logging()

    component_name = (name or LOG_SCOPE_APP).strip()
    resolved_scope = _normalize_scope(scope or _infer_scope_from_name(component_name))

    # Use cache only when context is empty for maximum reuse
    if not context:
        key = _adapter_cache_key(component_name, resolved_scope, None)
        cached = _LOGGER_CACHE.get(key)
        if cached is not None:
            return cached

    base_logger = _get_or_create_base_logger(resolved_scope)
    adapter_extra = {
        "scope": resolved_scope,
        "component": component_name,
        "session_id": context.pop("session_id", "-"),
        "route": context.pop("route", "-"),
        "mode": context.pop("mode", "-"),
    }
    adapter_extra.update(context)

    adapter = KioskLoggerAdapter(base_logger, adapter_extra)

    if not context:
        _LOGGER_CACHE[key] = adapter

    return adapter


def get_app_logger(**context: Any) -> KioskLoggerAdapter:
    return get_logger(LOG_SCOPE_APP, scope=LOG_SCOPE_APP, **context)


def get_serial_logger(**context: Any) -> KioskLoggerAdapter:
    return get_logger(LOG_SCOPE_SERIAL, scope=LOG_SCOPE_SERIAL, **context)


def get_ui_logger(**context: Any) -> KioskLoggerAdapter:
    return get_logger(LOG_SCOPE_UI, scope=LOG_SCOPE_UI, **context)


def get_db_logger(**context: Any) -> KioskLoggerAdapter:
    return get_logger(LOG_SCOPE_DB, scope=LOG_SCOPE_DB, **context)


def get_sensor_logger(**context: Any) -> KioskLoggerAdapter:
    return get_logger(LOG_SCOPE_SENSOR, scope=LOG_SCOPE_SENSOR, **context)


def get_settings_logger(**context: Any) -> KioskLoggerAdapter:
    return get_logger(LOG_SCOPE_SETTINGS, scope=LOG_SCOPE_SETTINGS, **context)


def get_storage_logger(**context: Any) -> KioskLoggerAdapter:
    return get_logger(LOG_SCOPE_STORAGE, scope=LOG_SCOPE_STORAGE, **context)


def get_report_logger(**context: Any) -> KioskLoggerAdapter:
    return get_logger(LOG_SCOPE_REPORT, scope=LOG_SCOPE_REPORT, **context)


def get_qr_logger(**context: Any) -> KioskLoggerAdapter:
    return get_logger(LOG_SCOPE_QR, scope=LOG_SCOPE_QR, **context)


def get_publish_logger(**context: Any) -> KioskLoggerAdapter:
    return get_logger(LOG_SCOPE_PUBLISH, scope=LOG_SCOPE_PUBLISH, **context)


def get_navigator_logger(**context: Any) -> KioskLoggerAdapter:
    return get_logger(LOG_SCOPE_NAVIGATOR, scope=LOG_SCOPE_NAVIGATOR, **context)


# ============================================================
# Exception and structured logging helpers
# ============================================================

def log_exception(
    logger: KioskLoggerAdapter,
    message: str,
    exc: BaseException,
    *,
    include_traceback: bool = True,
    level: int = logging.ERROR,
    **context: Any,
) -> None:
    """
    Log an exception consistently with optional traceback text.
    """
    if include_traceback:
        tb_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        logger.log(level, f"{message}: {exc}\n{tb_text}", extra=context)
    else:
        logger.log(level, f"{message}: {exc}", extra=context)


def log_kv(
    logger: KioskLoggerAdapter,
    level: int,
    message: str,
    **fields: Any,
) -> None:
    """
    Convenience function for structured key-value event logging.
    """
    logger.log(level, message, extra=fields)


def log_startup_banner(logger: Optional[KioskLoggerAdapter] = None) -> None:
    """
    Helpful startup log entry for main.py later.
    """
    logger = logger or get_app_logger()
    logger.info(
        "Logging initialized",
        extra={
            "session_id": "-",
            "route": "-",
            "mode": "-",
        },
    )


# ============================================================
# Log file helpers
# ============================================================

def get_app_log_path() -> Path:
    return PATHS.app_log_file


def get_serial_log_path() -> Path:
    return PATHS.serial_log_file


def read_last_log_lines(log_file: Path, line_count: int = 100) -> List[str]:
    """
    Read the last N lines from a log file safely.
    Useful later for admin diagnostics or debug panels.
    """
    if line_count <= 0:
        return []

    if not log_file.exists():
        return []

    try:
        lines = log_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        return lines[-line_count:]
    except Exception:
        return []


def read_last_app_log_lines(line_count: int = 100) -> List[str]:
    return read_last_log_lines(PATHS.app_log_file, line_count=line_count)


def read_last_serial_log_lines(line_count: int = 100) -> List[str]:
    return read_last_log_lines(PATHS.serial_log_file, line_count=line_count)


def get_log_file_sizes() -> Dict[str, int]:
    """
    Return current app/serial log sizes in bytes.
    """
    return {
        "app_log_bytes": PATHS.app_log_file.stat().st_size if PATHS.app_log_file.exists() else 0,
        "serial_log_bytes": PATHS.serial_log_file.stat().st_size if PATHS.serial_log_file.exists() else 0,
    }


def clear_log_file(log_file: Path) -> bool:
    """
    Truncate a given log file safely.
    """
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text("", encoding="utf-8")
        return True
    except Exception:
        return False


def clear_app_log() -> bool:
    return clear_log_file(PATHS.app_log_file)


def clear_serial_log() -> bool:
    return clear_log_file(PATHS.serial_log_file)


# ============================================================
# Diagnostics
# ============================================================

def get_logging_status() -> Dict[str, Any]:
    """
    Return current logging configuration in a structured form.
    Useful for debugging and future admin diagnostics.
    """
    return {
        "namespace": LOGGER_NAMESPACE,
        "ready": _LOGGING_READY,
        "default_log_level": logging.getLevelName(DEFAULT_LOG_LEVEL),
        "console_log_level": logging.getLevelName(CONSOLE_LOG_LEVEL),
        "file_log_level": logging.getLevelName(FILE_LOG_LEVEL),
        "console_enabled": ENABLE_CONSOLE_LOGGING,
        "app_log_file": str(PATHS.app_log_file),
        "serial_log_file": str(PATHS.serial_log_file),
        "max_log_bytes": MAX_LOG_BYTES,
        "backup_count": BACKUP_COUNT,
        "configured_scopes": list(_BASE_LOGGER_CACHE.keys()),
        "cached_logger_adapters": len(_LOGGER_CACHE),
    }


# ============================================================
# Initialize logging on import for convenience
# ============================================================

configure_logging()