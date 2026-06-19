"""
core/utils.py

Shared utility helpers for the CST Health Monitoring Station kiosk.

Purpose:
- Provide reusable low-level helpers across the project
- Keep formatting, IDs, time handling, JSON I/O, numeric safety, and file helpers centralized
- Reduce repeated code across services, widgets, screens, and tests
- Support both demo mode and hardware mode cleanly

Design rules:
- Keep this module framework-light where possible
- Avoid placing business rules here that belong in services/*
- Avoid putting asset path mappings here; those belong in core/asset_paths.py
- Avoid keeping mutable global runtime state here; that belongs in core/app_state.py
"""

from __future__ import annotations

import copy
import json
import math
import random
import re
import shutil
import socket
import sqlite3
import statistics
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple, Union

from config import (
    APP_NAME,
    APP_VERSION,
    BACKUPS_DIR,
    DEFAULT_RUNTIME_MODE,
    DEMO_RANDOM_RANGES,
    EXPORTS_DIR,
    QR_DIR,
    REPORTS_DIR,
    TEMP_DIR,
)
from core.constants import (
    EMPTY_MEASUREMENT_PAYLOAD,
    EXPORT_FILE_PREFIX,
    METRIC_BMI,
    METRIC_DECIMALS,
    METRIC_DEFAULT_VALUES,
    METRIC_HEIGHT,
    METRIC_LABELS,
    METRIC_PULSE,
    METRIC_RR,
    METRIC_SPO2,
    METRIC_TEMPERATURE,
    METRIC_UNITS,
    METRIC_WEIGHT,
    PRIMARY_METRIC_KEYS,
    QR_FILE_PREFIX,
    REPORT_FILE_PREFIX,
    STORAGE_UNIT_BYTES,
    STORAGE_UNIT_GB,
    STORAGE_UNIT_KB,
    STORAGE_UNIT_MB,
)
from core.logger import get_logger

logger = get_logger(__name__)


# ============================================================
# Basic type aliases
# ============================================================

Number = Union[int, float]
JsonDict = Dict[str, Any]
PathLike = Union[str, Path]


# ============================================================
# Generic simple helpers
# ============================================================

def is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def safe_str(value: Any, default: str = "") -> str:
    """
    Convert a value to string safely.
    """
    if value is None:
        return default
    try:
        return str(value)
    except Exception:
        return default


def normalize_spaces(text: Any) -> str:
    """
    Collapse repeated whitespace into single spaces.
    """
    raw = safe_str(text, "")
    return re.sub(r"\s+", " ", raw).strip()


def slugify(text: Any, fallback: str = "item") -> str:
    """
    Create a filesystem-friendly slug.
    """
    cleaned = normalize_spaces(text).lower()
    cleaned = re.sub(r"[^a-z0-9]+", "_", cleaned).strip("_")
    return cleaned or fallback


def coalesce(*values: Any, default: Any = None) -> Any:
    """
    Return the first non-None value, else default.
    """
    for value in values:
        if value is not None:
            return value
    return default


def first_non_empty(*values: Any, default: str = "") -> str:
    """
    Return the first non-empty string-like value.
    """
    for value in values:
        if is_non_empty_string(value):
            return str(value).strip()
    return default


def unique_preserve_order(items: Iterable[Any]) -> List[Any]:
    seen = set()
    ordered: List[Any] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def compact_list(items: Iterable[Any]) -> List[Any]:
    """
    Remove None and empty-string-like values.
    """
    result: List[Any] = []
    for item in items:
        if item is None:
            continue
        if isinstance(item, str) and not item.strip():
            continue
        result.append(item)
    return result


# ============================================================
# Dictionary helpers
# ============================================================

def deep_copy(value: Any) -> Any:
    return copy.deepcopy(value)


def deep_merge_dicts(base: Mapping[str, Any], override: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Recursively merge two dictionaries without mutating either.
    Values in override win.
    """
    result: Dict[str, Any] = dict(base)

    for key, override_value in override.items():
        base_value = result.get(key)

        if isinstance(base_value, dict) and isinstance(override_value, dict):
            result[key] = deep_merge_dicts(base_value, override_value)
        else:
            result[key] = copy.deepcopy(override_value)

    return result


def prune_none_values(data: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Return a shallow copy without None values.
    """
    return {key: value for key, value in data.items() if value is not None}


def flatten_dict(data: Mapping[str, Any], parent_key: str = "", sep: str = ".") -> Dict[str, Any]:
    """
    Flatten nested dictionaries into dot-notation.
    Example:
        {"a": {"b": 1}} -> {"a.b": 1}
    """
    items: Dict[str, Any] = {}
    for key, value in data.items():
        new_key = f"{parent_key}{sep}{key}" if parent_key else str(key)
        if isinstance(value, Mapping):
            items.update(flatten_dict(value, parent_key=new_key, sep=sep))
        else:
            items[new_key] = value
    return items


# ============================================================
# JSON and file helpers
# ============================================================

def ensure_directory(path: PathLike) -> Path:
    path_obj = Path(path)
    path_obj.mkdir(parents=True, exist_ok=True)
    return path_obj


def ensure_parent_directory(path: PathLike) -> Path:
    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    return path_obj.parent


def path_exists(path: PathLike) -> bool:
    return Path(path).exists()


def is_file(path: PathLike) -> bool:
    return Path(path).is_file()


def is_directory(path: PathLike) -> bool:
    return Path(path).is_dir()


def safe_unlink(path: PathLike, missing_ok: bool = True) -> bool:
    try:
        Path(path).unlink(missing_ok=missing_ok)
        return True
    except Exception:
        return False


def safe_rmtree(path: PathLike) -> bool:
    try:
        shutil.rmtree(Path(path), ignore_errors=False)
        return True
    except FileNotFoundError:
        return True
    except Exception:
        return False


def safe_copy_file(source: PathLike, destination: PathLike, overwrite: bool = True) -> Optional[Path]:
    """
    Copy a file safely. Returns destination path if successful, else None.
    """
    src = Path(source)
    dst = Path(destination)

    if not src.exists() or not src.is_file():
        return None

    ensure_parent_directory(dst)

    if dst.exists() and not overwrite:
        return None

    shutil.copy2(src, dst)
    return dst


def safe_move_file(source: PathLike, destination: PathLike, overwrite: bool = True) -> Optional[Path]:
    src = Path(source)
    dst = Path(destination)

    if not src.exists():
        return None

    ensure_parent_directory(dst)

    if dst.exists() and not overwrite:
        return None

    if dst.exists() and overwrite:
        safe_unlink(dst, missing_ok=True)

    moved = shutil.move(str(src), str(dst))
    return Path(moved)


def read_text_file(path: PathLike, default: str = "", encoding: str = "utf-8") -> str:
    try:
        return Path(path).read_text(encoding=encoding, errors="ignore")
    except Exception:
        return default


def write_text_file(path: PathLike, content: str, encoding: str = "utf-8") -> Path:
    path_obj = Path(path)
    ensure_parent_directory(path_obj)
    path_obj.write_text(content, encoding=encoding)
    return path_obj


def read_json_file(path: PathLike, default: Optional[JsonDict] = None) -> JsonDict:
    """
    Read a JSON file safely. Returns a deep copy of default if missing/invalid.
    """
    fallback = copy.deepcopy(default) if default is not None else {}
    path_obj = Path(path)

    if not path_obj.exists():
        return fallback

    try:
        return json.loads(path_obj.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def write_json_file(path: PathLike, payload: Mapping[str, Any], indent: int = 4) -> Path:
    path_obj = Path(path)
    ensure_parent_directory(path_obj)
    path_obj.write_text(
        json.dumps(dict(payload), indent=indent, ensure_ascii=False),
        encoding="utf-8",
    )
    return path_obj


def append_text_line(path: PathLike, line: str, encoding: str = "utf-8") -> Path:
    path_obj = Path(path)
    ensure_parent_directory(path_obj)
    with path_obj.open("a", encoding=encoding) as f:
        f.write(line.rstrip("\n") + "\n")
    return path_obj


# ============================================================
# Time and timestamp helpers
# ============================================================

def now_local() -> datetime:
    return datetime.now()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_local().isoformat(timespec="seconds")


def now_utc_iso() -> str:
    return now_utc().isoformat(timespec="seconds")


def timestamp_for_filename(dt: Optional[datetime] = None) -> str:
    value = dt or now_local()
    return value.strftime("%Y%m%d_%H%M%S")


def display_date(dt: Optional[datetime] = None) -> str:
    value = dt or now_local()
    return value.strftime("%Y-%m-%d")


def display_time(dt: Optional[datetime] = None) -> str:
    value = dt or now_local()
    return value.strftime("%H:%M:%S")


def display_datetime(dt: Optional[datetime] = None) -> str:
    value = dt or now_local()
    return value.strftime("%Y-%m-%d %H:%M:%S")


def parse_datetime(value: Any) -> Optional[datetime]:
    """
    Parse common datetime string values safely.
    """
    if isinstance(value, datetime):
        return value

    if not is_non_empty_string(value):
        return None

    text = str(value).strip()

    try:
        return datetime.fromisoformat(text)
    except Exception:
        pass

    common_formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y",
    ]
    for fmt in common_formats:
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue

    return None


def humanize_datetime(value: Any, fallback: str = "-") -> str:
    dt = parse_datetime(value)
    if dt is None:
        return fallback
    return dt.strftime("%d %b %Y, %I:%M %p")


# ============================================================
# Session ID / unique ID helpers
# ============================================================

def generate_short_uuid(length: int = 8) -> str:
    """
    Generate a short uppercase UUID fragment.
    """
    if length <= 0:
        length = 8
    return uuid.uuid4().hex.upper()[:length]


def generate_session_id(prefix: str = "CST", include_date: bool = True) -> str:
    """
    Generate a user/session-specific measurement ID.
    Example:
        CST-20260311-AB12CD34
    """
    unique = generate_short_uuid(8)
    if include_date:
        return f"{prefix}-{now_local().strftime('%Y%m%d')}-{unique}"
    return f"{prefix}-{unique}"


def generate_record_id(prefix: str = "REC") -> str:
    return f"{prefix}-{timestamp_for_filename()}-{generate_short_uuid(6)}"


# ============================================================
# Numeric safety helpers
# ============================================================

def safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        if isinstance(value, str):
            cleaned = value.strip().replace(",", "")
            if not cleaned:
                return default
            return float(cleaned)
        return float(value)
    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        if isinstance(value, str):
            cleaned = value.strip().replace(",", "")
            if not cleaned:
                return default
            return int(float(cleaned))
        return int(float(value))
    except Exception:
        return default


def clamp(value: Number, minimum: Number, maximum: Number) -> Number:
    return max(minimum, min(value, maximum))


def round_half_up(value: float, decimals: int = 0) -> float:
    """
    A stable user-facing rounding helper.
    """
    multiplier = 10 ** decimals
    return math.floor(value * multiplier + 0.5) / multiplier


def safe_round(value: Any, decimals: int = 2, default: float = 0.0) -> float:
    return round_half_up(safe_float(value, default=default), decimals=decimals)


def safe_percentage(numerator: Number, denominator: Number, default: float = 0.0, decimals: int = 1) -> float:
    denom = safe_float(denominator)
    if denom == 0:
        return default
    value = (safe_float(numerator) / denom) * 100.0
    return safe_round(value, decimals=decimals, default=default)


def average(values: Iterable[Any], default: float = 0.0, decimals: Optional[int] = None) -> float:
    numbers = [safe_float(v) for v in values if v is not None]
    if not numbers:
        return default
    mean_value = sum(numbers) / len(numbers)
    if decimals is None:
        return mean_value
    return safe_round(mean_value, decimals=decimals, default=default)


def median(values: Iterable[Any], default: float = 0.0, decimals: Optional[int] = None) -> float:
    numbers = [safe_float(v) for v in values if v is not None]
    if not numbers:
        return default
    med = statistics.median(numbers)
    if decimals is None:
        return float(med)
    return safe_round(float(med), decimals=decimals, default=default)


def maximum(values: Iterable[Any], default: float = 0.0) -> float:
    numbers = [safe_float(v) for v in values if v is not None]
    return max(numbers) if numbers else default


def minimum(values: Iterable[Any], default: float = 0.0) -> float:
    numbers = [safe_float(v) for v in values if v is not None]
    return min(numbers) if numbers else default


# ============================================================
# Health measurement math helpers
# ============================================================

def centimeters_to_meters(height_cm: Any) -> float:
    return safe_float(height_cm) / 100.0


def calculate_bmi(weight_kg: Any, height_cm: Any, decimals: int = 1) -> float:
    """
    Calculate BMI from kg and cm.
    Returns 0.0 if height is invalid.
    """
    weight = safe_float(weight_kg)
    height_m = centimeters_to_meters(height_cm)
    if height_m <= 0:
        return 0.0

    bmi_value = weight / (height_m ** 2)
    return safe_round(bmi_value, decimals=decimals, default=0.0)


def apply_offset(value: Any, offset: Any, decimals: Optional[int] = None) -> float:
    """
    Apply calibration offset.
    """
    adjusted = safe_float(value) + safe_float(offset)
    if decimals is None:
        return adjusted
    return safe_round(adjusted, decimals=decimals, default=0.0)


def normalize_measurement_payload(payload: Optional[Mapping[str, Any]]) -> Dict[str, float]:
    """
    Normalize any partial measurement dict into a full metric payload.
    """
    result = dict(EMPTY_MEASUREMENT_PAYLOAD)

    if payload:
        for metric_key in PRIMARY_METRIC_KEYS:
            decimals = METRIC_DECIMALS.get(metric_key, 1)
            if metric_key in payload:
                result[metric_key] = safe_round(payload.get(metric_key), decimals=decimals, default=0.0)

    # BMI can be derived if not provided or zero but weight/height exist
    if safe_float(result.get(METRIC_BMI, 0.0)) <= 0.0:
        if safe_float(result.get(METRIC_WEIGHT, 0.0)) > 0 and safe_float(result.get(METRIC_HEIGHT, 0.0)) > 0:
            result[METRIC_BMI] = calculate_bmi(result[METRIC_WEIGHT], result[METRIC_HEIGHT], decimals=1)

    return result


def has_all_primary_metrics(payload: Optional[Mapping[str, Any]]) -> bool:
    if not payload:
        return False

    for metric_key in PRIMARY_METRIC_KEYS:
        if metric_key not in payload:
            return False
        if safe_float(payload.get(metric_key, 0.0)) <= 0:
            return False
    return True


def metric_is_meaningful(metric_key: str, value: Any) -> bool:
    """
    Determine whether a measured value is usable for UI display and logic.
    """
    numeric = safe_float(value, default=0.0)
    if metric_key == METRIC_TEMPERATURE:
        return numeric > 20.0
    if metric_key == METRIC_SPO2:
        return numeric > 0
    if metric_key == METRIC_PULSE:
        return numeric > 0
    if metric_key == METRIC_RR:
        return numeric > 0
    if metric_key == METRIC_WEIGHT:
        return numeric > 0
    if metric_key == METRIC_HEIGHT:
        return numeric > 0
    if metric_key == METRIC_BMI:
        return numeric > 0
    return numeric > 0


def format_metric_value(metric_key: str, value: Any, show_unit: bool = True, fallback: str = "--") -> str:
    """
    Format a metric for on-screen display.
    """
    if not metric_is_meaningful(metric_key, value):
        return fallback

    decimals = METRIC_DECIMALS.get(metric_key, 1)
    unit = METRIC_UNITS.get(metric_key, "")
    numeric = safe_round(value, decimals=decimals, default=0.0)

    if decimals == 0:
        rendered = f"{int(round(numeric))}"
    else:
        rendered = f"{numeric:.{decimals}f}"

    if show_unit and unit:
        return f"{rendered} {unit}"
    return rendered


def metric_label(metric_key: str, fallback: Optional[str] = None) -> str:
    return METRIC_LABELS.get(metric_key, fallback or metric_key.replace("_", " ").title())


def metric_default_value(metric_key: str) -> float:
    return safe_float(METRIC_DEFAULT_VALUES.get(metric_key, 0.0), default=0.0)


# ============================================================
# Demo data helpers
# ============================================================

def random_in_range(min_value: float, max_value: float, decimals: int = 1) -> float:
    value = random.uniform(min_value, max_value)
    return safe_round(value, decimals=decimals, default=min_value)


def generate_demo_measurements() -> Dict[str, float]:
    """
    Generate realistic but varied demo measurements.

    Notes:
    - BMI is calculated from generated weight + height
    - Ranges come from config.DEMO_RANDOM_RANGES
    """
    weight_cfg = DEMO_RANDOM_RANGES[METRIC_WEIGHT]
    height_cfg = DEMO_RANDOM_RANGES[METRIC_HEIGHT]
    temp_cfg = DEMO_RANDOM_RANGES[METRIC_TEMPERATURE]
    spo2_cfg = DEMO_RANDOM_RANGES[METRIC_SPO2]
    pulse_cfg = DEMO_RANDOM_RANGES[METRIC_PULSE]
    rr_cfg = DEMO_RANDOM_RANGES[METRIC_RR]

    weight = random_in_range(weight_cfg["min"], weight_cfg["max"], int(weight_cfg["decimals"]))
    height = random_in_range(height_cfg["min"], height_cfg["max"], int(height_cfg["decimals"]))
    temperature = random_in_range(temp_cfg["min"], temp_cfg["max"], int(temp_cfg["decimals"]))
    spo2 = random_in_range(spo2_cfg["min"], spo2_cfg["max"], int(spo2_cfg["decimals"]))
    pulse = random_in_range(pulse_cfg["min"], pulse_cfg["max"], int(pulse_cfg["decimals"]))
    rr = random_in_range(rr_cfg["min"], rr_cfg["max"], int(rr_cfg["decimals"]))
    bmi = calculate_bmi(weight, height, decimals=1)

    payload = {
        METRIC_WEIGHT: weight,
        METRIC_HEIGHT: height,
        METRIC_BMI: bmi,
        METRIC_TEMPERATURE: temperature,
        METRIC_SPO2: spo2,
        METRIC_PULSE: pulse,
        METRIC_RR: rr,
    }
    return normalize_measurement_payload(payload)


# ============================================================
# File name generation for reports / QR / export / backup
# ============================================================

def build_report_filename(session_id: str, extension: str = "pdf") -> str:
    safe_session = slugify(session_id, fallback="session")
    return f"{REPORT_FILE_PREFIX}_{safe_session}.{extension.lstrip('.')}"


def build_qr_filename(session_id: str, extension: str = "png") -> str:
    safe_session = slugify(session_id, fallback="session")
    return f"{QR_FILE_PREFIX}_{safe_session}.{extension.lstrip('.')}"


def build_export_filename(label: str = "records", extension: str = "json") -> str:
    safe_label = slugify(label, fallback="export")
    return f"{EXPORT_FILE_PREFIX}_{safe_label}_{timestamp_for_filename()}.{extension.lstrip('.')}"


def build_backup_filename(label: str = "backup", extension: str = "zip") -> str:
    safe_label = slugify(label, fallback="backup")
    return f"{safe_label}_{timestamp_for_filename()}.{extension.lstrip('.')}"


def build_report_path(session_id: str, extension: str = "pdf") -> Path:
    return REPORTS_DIR / build_report_filename(session_id, extension=extension)


def build_qr_path(session_id: str, extension: str = "png") -> Path:
    return QR_DIR / build_qr_filename(session_id, extension=extension)


def build_export_path(label: str = "records", extension: str = "json") -> Path:
    return EXPORTS_DIR / build_export_filename(label=label, extension=extension)


def build_backup_path(label: str = "backup", extension: str = "zip") -> Path:
    return BACKUPS_DIR / build_backup_filename(label=label, extension=extension)


def build_temp_path(label: str = "temp", extension: str = "tmp") -> Path:
    safe_label = slugify(label, fallback="temp")
    return TEMP_DIR / f"{safe_label}_{timestamp_for_filename()}.{extension.lstrip('.')}"


# ============================================================
# Bytes / storage helpers
# ============================================================

def file_size_bytes(path: PathLike) -> int:
    try:
        return Path(path).stat().st_size
    except Exception:
        return 0


def directory_size_bytes(path: PathLike) -> int:
    """
    Recursively sum directory size.
    """
    path_obj = Path(path)
    if not path_obj.exists():
        return 0

    total = 0
    for item in path_obj.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except Exception:
            continue
    return total


def format_bytes(size_bytes: Any, decimals: int = 2) -> str:
    size = safe_float(size_bytes, default=0.0)

    if size < 1024:
        return f"{int(size)} {STORAGE_UNIT_BYTES}"

    kb = size / 1024
    if kb < 1024:
        return f"{safe_round(kb, decimals=decimals)} {STORAGE_UNIT_KB}"

    mb = kb / 1024
    if mb < 1024:
        return f"{safe_round(mb, decimals=decimals)} {STORAGE_UNIT_MB}"

    gb = mb / 1024
    return f"{safe_round(gb, decimals=decimals)} {STORAGE_UNIT_GB}"


# ============================================================
# SQLite helpers
# ============================================================

def sqlite_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """
    Convert sqlite3.Row into a normal dict safely.
    """
    return {key: row[key] for key in row.keys()}


def sqlite_rows_to_dicts(rows: Iterable[sqlite3.Row]) -> List[Dict[str, Any]]:
    return [sqlite_row_to_dict(row) for row in rows]


# ============================================================
# Network / system helpers
# ============================================================

def is_online(host: str = "8.8.8.8", port: int = 53, timeout_seconds: float = 1.5) -> bool:
    """
    Lightweight network reachability check.
    Used later by connection/settings screens.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except Exception:
        return False


def get_hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "unknown-host"


# ============================================================
# Validation helpers
# ============================================================

def validate_runtime_mode(value: Any, allowed: Optional[Sequence[str]] = None) -> str:
    from core.constants import MODE_DEMO, MODE_HARDWARE  # local import keeps flexibility

    options = list(allowed) if allowed is not None else [MODE_DEMO, MODE_HARDWARE]
    normalized = safe_str(value, "").strip().lower()
    return normalized if normalized in options else DEFAULT_RUNTIME_MODE


def validate_brightness(value: Any) -> int:
    return int(clamp(safe_int(value, default=75), 0, 100))


def validate_volume(value: Any) -> int:
    return int(clamp(safe_int(value, default=50), 0, 100))


# ============================================================
# UI-friendly data builders
# ============================================================

def make_metric_card_payload(metric_key: str, value: Any) -> Dict[str, Any]:
    """
    Helper for results screen tile preparation.
    """
    return {
        "key": metric_key,
        "label": metric_label(metric_key),
        "value": safe_float(value, default=metric_default_value(metric_key)),
        "formatted": format_metric_value(metric_key, value, show_unit=True),
        "unit": METRIC_UNITS.get(metric_key, ""),
        "decimals": METRIC_DECIMALS.get(metric_key, 1),
    }


def make_metrics_payload(measurements: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    normalized = normalize_measurement_payload(measurements or {})
    return [make_metric_card_payload(metric_key, normalized.get(metric_key, 0.0)) for metric_key in PRIMARY_METRIC_KEYS]


# ============================================================
# Measurement completeness helpers
# ============================================================

def measurement_completion_ratio(payload: Optional[Mapping[str, Any]]) -> float:
    if not payload:
        return 0.0

    total = len(PRIMARY_METRIC_KEYS)
    if total == 0:
        return 0.0

    valid = 0
    for metric_key in PRIMARY_METRIC_KEYS:
        if metric_is_meaningful(metric_key, payload.get(metric_key)):
            valid += 1

    return safe_percentage(valid, total, default=0.0, decimals=1)


def measurement_is_complete(payload: Optional[Mapping[str, Any]]) -> bool:
    return has_all_primary_metrics(payload)


# ============================================================
# Report / QR serialization helpers
# ============================================================

def make_session_summary_payload(
    session_id: str,
    mode: str,
    measurements: Mapping[str, Any],
    diagnosis_summary: str = "",
) -> Dict[str, Any]:
    normalized = normalize_measurement_payload(measurements)
    return {
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "session_id": session_id,
        "timestamp": now_iso(),
        "mode": validate_runtime_mode(mode),
        "measurements": normalized,
        "formatted_measurements": {
            metric_key: format_metric_value(metric_key, normalized.get(metric_key), show_unit=True)
            for metric_key in PRIMARY_METRIC_KEYS
        },
        "diagnosis_summary": diagnosis_summary,
    }


def json_dumps_pretty(payload: Any) -> str:
    return json.dumps(payload, indent=4, ensure_ascii=False)


def json_dumps_compact(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


# ============================================================
# Safe sorting helpers
# ============================================================

def sort_dicts_by_key(items: Iterable[Mapping[str, Any]], key: str, reverse: bool = False) -> List[Dict[str, Any]]:
    return sorted(
        [dict(item) for item in items],
        key=lambda item: item.get(key),
        reverse=reverse,
    )


def sort_dicts_by_numeric_key(
    items: Iterable[Mapping[str, Any]],
    key: str,
    reverse: bool = False,
) -> List[Dict[str, Any]]:
    return sorted(
        [dict(item) for item in items],
        key=lambda item: safe_float(item.get(key), default=0.0),
        reverse=reverse,
    )


# ============================================================
# Generic retry-safe helper wrappers
# ============================================================

def safe_call(default: Any, func, *args, **kwargs) -> Any:
    """
    Execute a callable and return default on failure.
    """
    try:
        return func(*args, **kwargs)
    except Exception as exc:
        logger.warning("safe_call fallback used: %s", exc)
        return default


# ============================================================
# Debug helpers
# ============================================================

def app_debug_snapshot() -> Dict[str, Any]:
    """
    Lightweight runtime diagnostics snapshot.
    Useful later in admin/publish/debug screens.
    """
    return {
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "timestamp": now_iso(),
        "reports_dir": str(REPORTS_DIR),
        "qr_dir": str(QR_DIR),
        "backups_dir": str(BACKUPS_DIR),
        "exports_dir": str(EXPORTS_DIR),
        "temp_dir": str(TEMP_DIR),
        "online": is_online(),
        "hostname": get_hostname(),
    }


# ============================================================
# Ensure important writable folders exist early
# ============================================================

ensure_directory(REPORTS_DIR)
ensure_directory(QR_DIR)
ensure_directory(BACKUPS_DIR)
ensure_directory(EXPORTS_DIR)
ensure_directory(TEMP_DIR)