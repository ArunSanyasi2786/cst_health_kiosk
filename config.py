"""
config.py
Central runtime configuration for the CST Health Monitoring Kiosk.

Design goals:
- Single source of truth for project paths and app defaults
- Safe first-run bootstrapping of folders and JSON config files
- Works on laptop demo mode and Raspberry Pi hardware mode
- Keeps later modules linked and consistent
"""

from __future__ import annotations

import copy
import json
import os
import platform
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


# ============================================================
# Project metadata
# ============================================================

APP_NAME = "CST Health Monitoring Station"
APP_SHORT_NAME = "CST Health Kiosk"
APP_VERSION = "1.0.0"
APP_ORGANIZATION = "College of Science and Technology"
APP_GROUP_CREDIT = "Group 3"

# ============================================================
# Display target
# ------------------------------------------------------------
# Original mockups and many screen proportions in this project
# were first tuned around 1024x600. The real deployment panel
# is now confirmed to be 800x480, so we keep the original
# design baseline and expose compact-resolution scale helpers.
# This lets later screens shrink intelligently instead of being
# rebuilt from scratch.
# ============================================================

DESIGN_BASE_WIDTH = 1024
DESIGN_BASE_HEIGHT = 600

KIOSK_WIDTH = 800
KIOSK_HEIGHT = 480
KIOSK_FIXED_SIZE = (KIOSK_WIDTH, KIOSK_HEIGHT)

WIDTH_SCALE = KIOSK_WIDTH / DESIGN_BASE_WIDTH
HEIGHT_SCALE = KIOSK_HEIGHT / DESIGN_BASE_HEIGHT
UI_SCALE = min(WIDTH_SCALE, HEIGHT_SCALE)

IS_COMPACT_WIDTH = KIOSK_WIDTH <= 900
IS_COMPACT_HEIGHT = KIOSK_HEIGHT <= 520
IS_COMPACT_KIOSK = IS_COMPACT_WIDTH or IS_COMPACT_HEIGHT

# Compatibility aliases used by some bootstrap files.
WINDOW_WIDTH = KIOSK_WIDTH
WINDOW_HEIGHT = KIOSK_HEIGHT
BASE_DIR = Path(__file__).resolve().parent
FULLSCREEN = False
FULLSCREEN_ON_RPI = True
DEMO_MODE_ON_BOOT = False

SUPPORTED_LANGUAGES = ["English"]
SUPPORTED_THEME_MODES = ["dark", "light"]
SUPPORTED_RUNTIME_MODES = ["demo", "hardware"]
SUPPORTED_SCREEN_TIMEOUTS = ["always_active", "15_min", "10_min"]


# ============================================================
# Environment / platform
# ============================================================

IS_WINDOWS = platform.system().lower() == "windows"
IS_LINUX = platform.system().lower() == "linux"
IS_MAC = platform.system().lower() == "darwin"

# Raspberry Pi detection is intentionally simple and safe.
# It does not break on normal Linux machines.
IS_RASPBERRY_PI = False
try:
    model_path = Path("/proc/device-tree/model")
    if model_path.exists():
        model_text = model_path.read_text(encoding="utf-8", errors="ignore").lower()
        if "raspberry pi" in model_text:
            IS_RASPBERRY_PI = True
except Exception:
    IS_RASPBERRY_PI = False


# ============================================================
# Path resolution
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent

ASSETS_DIR = PROJECT_ROOT / "assets"
DATA_DIR = PROJECT_ROOT / "data"
DOCS_DIR = PROJECT_ROOT / "docs"
TESTS_DIR = PROJECT_ROOT / "tests"

# Asset subfolders
BACKGROUNDS_DIR = ASSETS_DIR / "backgrounds"
LOGOS_DIR = ASSETS_DIR / "logos"
ILLUSTRATIONS_DIR = ASSETS_DIR / "illustrations"
ICONS_DIR = ASSETS_DIR / "icons"
DETAIL_GRAPHICS_DIR = ASSETS_DIR / "detail_graphics"
SOUNDS_DIR = ASSETS_DIR / "sounds"
FONTS_DIR = ASSETS_DIR / "fonts"

# Data subfolders
DB_DIR = DATA_DIR / "db"
REPORTS_DIR = DATA_DIR / "reports"
QR_DIR = DATA_DIR / "qr"
BACKUPS_DIR = DATA_DIR / "backups"
EXPORTS_DIR = DATA_DIR / "exports"
TEMP_DIR = DATA_DIR / "temp"
LOGS_DIR = DATA_DIR / "logs"
DATA_CONFIG_DIR = DATA_DIR / "config"

# Data/config files
DB_FILE = DB_DIR / "kiosk_data.db"
APP_LOG_FILE = LOGS_DIR / "app.log"
SERIAL_LOG_FILE = LOGS_DIR / "serial.log"

SETTINGS_FILE = DATA_CONFIG_DIR / "settings.json"
CALIBRATION_FILE = DATA_CONFIG_DIR / "calibration.json"
THRESHOLDS_FILE = DATA_CONFIG_DIR / "thresholds.json"
SESSION_DEFAULTS_FILE = DATA_CONFIG_DIR / "session_defaults.json"


# ============================================================
# Admin / kiosk security defaults
# ============================================================

ADMIN_USERNAME = os.environ.get("CST_KIOSK_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("CST_KIOSK_ADMIN_PASSWORD", "change-me")
EMERGENCY_NUMBER = "112"

# Admin lock is a software preference only.
# It is not intended as real high-security protection.
DEFAULT_ADMIN_LOCK = False


# ============================================================
# Runtime behavior defaults
# ============================================================

DEFAULT_RUNTIME_MODE = "demo"
DEFAULT_LANGUAGE = "English"
DEFAULT_THEME_MODE = "dark"
DEFAULT_SCREEN_TIMEOUT = "15_min"

WELCOME_SCREEN_DURATION_MS = 4000
DEMO_MEASUREMENT_DURATION_MS = 5500
TRANSITION_DURATION_MS = 320
BUTTON_CLICK_ANIMATION_MS = 140
LOGO_GLOW_PULSE_MS = 1500

# In hardware mode the measuring screen should remain active until
# the sensor service emits stable readings. This timeout is only a
# safety ceiling to avoid deadlock during demonstration.
HARDWARE_MEASUREMENT_FAILSAFE_TIMEOUT_MS = 45000

NETWORK_CHECK_INTERVAL_MS = 5000
CONNECTION_STATUS_REFRESH_MS = 3000
RESULTS_AUTO_REFRESH_MS = 1000
PUBLISH_REFRESH_INTERVAL_MS = 6000
IDLE_CHECK_INTERVAL_MS = 1000

DEFAULT_BRIGHTNESS_PERCENT = 75
DEFAULT_VOLUME_PERCENT = 55

# Timeout mapping in milliseconds.
SCREEN_TIMEOUT_MAP_MS = {
    "always_active": 0,
    "15_min": 15 * 60 * 1000,
    "10_min": 10 * 60 * 1000,
}

# Sound behavior
ENABLE_UI_SOUNDS = True


# ============================================================
# Serial / hardware defaults
# ============================================================

DEFAULT_SERIAL_BAUDRATE = 115200
DEFAULT_SERIAL_TIMEOUT_SECONDS = 1.0
DEFAULT_SERIAL_RECONNECT_SECONDS = 3.0

# Common defaults:
# - Windows laptop testing often uses COM ports
# - Raspberry Pi often uses ttyUSB0 or ttyAMA0 / ttyS0 depending on setup
SERIAL_PORT_CANDIDATES: List[str] = (
    ["COM3", "COM4", "COM5", "COM6"]
    if IS_WINDOWS
    else ["/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyAMA0", "/dev/ttyS0"]
)

# Minimal serial protocol expectation for later services.
# The sensor / serial services can parse lines into these fields.
SERIAL_EXPECTED_FIELDS = [
    "weight",
    "height",
    "bmi",
    "temperature",
    "spo2",
    "pulse_rate",
    "respiratory_rate",
]


# ============================================================
# Demo data ranges
# Used when running without real sensors
# ============================================================

DEMO_RANDOM_RANGES: Dict[str, Dict[str, float]] = {
    "weight": {"min": 42.0, "max": 95.0, "decimals": 1},
    "height": {"min": 145.0, "max": 188.0, "decimals": 1},
    "temperature": {"min": 36.1, "max": 39.4, "decimals": 1},
    "spo2": {"min": 88.0, "max": 100.0, "decimals": 0},
    "pulse_rate": {"min": 58.0, "max": 112.0, "decimals": 0},
    "respiratory_rate": {"min": 10.0, "max": 24.0, "decimals": 1},
}


# ============================================================
# Default persistent configuration payloads
# These are written on first run if missing.
# ============================================================

DEFAULT_SETTINGS: Dict[str, Any] = {
    "app": {
        "name": APP_NAME,
        "version": APP_VERSION,
        "organization": APP_ORGANIZATION,
        "group_credit": APP_GROUP_CREDIT,
    },
    "display": {
        "brightness_percent": DEFAULT_BRIGHTNESS_PERCENT,
        "screen_timeout": DEFAULT_SCREEN_TIMEOUT,
        "theme_mode": DEFAULT_THEME_MODE,
        "language": DEFAULT_LANGUAGE,
        "fullscreen": True,
        "fixed_resolution": [KIOSK_WIDTH, KIOSK_HEIGHT],
    },
    "audio": {
        "enabled": ENABLE_UI_SOUNDS,
        "volume_percent": DEFAULT_VOLUME_PERCENT,
    },
    "system": {
        "runtime_mode": DEFAULT_RUNTIME_MODE,
        "network_connected": False,
        "admin_lock": DEFAULT_ADMIN_LOCK,
        "data_export_enabled": True,
        "show_demo_mode_badge": True,
        "auto_backup_enabled": False,
    },
    "hardware": {
        "preferred_serial_port": SERIAL_PORT_CANDIDATES[0] if SERIAL_PORT_CANDIDATES else "",
        "serial_baudrate": DEFAULT_SERIAL_BAUDRATE,
        "serial_timeout_seconds": DEFAULT_SERIAL_TIMEOUT_SECONDS,
        "auto_reconnect_seconds": DEFAULT_SERIAL_RECONNECT_SECONDS,
        "hardware_measurement_failsafe_timeout_ms": HARDWARE_MEASUREMENT_FAILSAFE_TIMEOUT_MS,
    },
    "timing": {
        "welcome_screen_duration_ms": WELCOME_SCREEN_DURATION_MS,
        "demo_measurement_duration_ms": DEMO_MEASUREMENT_DURATION_MS,
        "transition_duration_ms": TRANSITION_DURATION_MS,
        "button_click_animation_ms": BUTTON_CLICK_ANIMATION_MS,
        "logo_glow_pulse_ms": LOGO_GLOW_PULSE_MS,
        "results_auto_refresh_ms": RESULTS_AUTO_REFRESH_MS,
        "publish_refresh_interval_ms": PUBLISH_REFRESH_INTERVAL_MS,
        "connection_status_refresh_ms": CONNECTION_STATUS_REFRESH_MS,
    },
}

DEFAULT_CALIBRATION: Dict[str, Any] = {
    "temperature": {
        "label": "Temperature Sensor",
        "unit": "Â°C",
        "offset": 0.0,
        "manual_offset_options": [0.00, 0.25, 0.50],
        "calibration_min": 0.0,
        "calibration_mid": 33.6,
        "calibration_max": 41.0,
        "update_frequency_seconds": 5,
    },
    "spo2": {
        "label": "SpO2 Sensor",
        "unit": "%",
        "offset": 0,
        "manual_offset_options": [0, 1, 2],
        "calibration_min": 90,
        "calibration_mid": 95,
        "calibration_max": 100,
        "update_frequency_seconds": 5,
    },
    "weight": {
        "label": "Weight Sensor",
        "unit": "kg",
        "offset": 0.0,
        "manual_offset_options": [0.00, 0.25, 0.50],
        "calibration_min": 5.0,
        "calibration_mid": 80.0,
        "calibration_max": 200.0,
        "update_frequency_seconds": 5,
    },
    "height": {
        "label": "Height Sensor",
        "unit": "cm",
        "offset": 0.0,
        "manual_offset_options": [0.00, 0.25, 0.50],
        "calibration_min": 100.0,
        "calibration_mid": 170.0,
        "calibration_max": 220.0,
        "update_frequency_seconds": 5,
    },
    "pulse_rate": {
        "label": "Pulse Rate Sensor",
        "unit": "bpm",
        "offset": 0,
        "manual_offset_options": [0, 1, 2],
        "calibration_min": 50,
        "calibration_mid": 85,
        "calibration_max": 150,
        "update_frequency_seconds": 5,
    },
    "respiratory_rate": {
        "label": "Respiratory Rate Sensor",
        "unit": "breaths/min",
        "offset": 0.0,
        "manual_offset_options": [0.0, 0.5, 1.0],
        "calibration_min": 8.0,
        "calibration_mid": 16.0,
        "calibration_max": 30.0,
        "update_frequency_seconds": 5,
    },
    "bmi": {
        "label": "BMI",
        "unit": "",
        "offset": 0.0,
        "manual_offset_options": [0.0],
        "calibration_min": 10.0,
        "calibration_mid": 22.0,
        "calibration_max": 40.0,
        "update_frequency_seconds": 5,
    },
}

DEFAULT_THRESHOLDS: Dict[str, Any] = {
    "weight": {
        "display_unit": "kg",
        "normal_note": "Weight is shown as measured and interpreted together with BMI.",
    },
    "height": {
        "display_unit": "cm",
        "normal_note": "Height is shown as measured and used for BMI calculation.",
    },
    "bmi": {
        "display_unit": "",
        "underweight_max": 18.4,
        "normal_min": 18.5,
        "normal_max": 24.9,
        "overweight_min": 25.0,
        "overweight_max": 29.9,
        "obese_min": 30.0,
    },
    "temperature": {
        "display_unit": "Â°C",
        "normal_min": 36.0,
        "normal_max": 37.0,
        "mild_fever_min": 37.1,
        "mild_fever_max": 38.0,
        "high_fever_min": 38.1,
        "high_fever_max": 40.0,
        "very_high_fever_min": 40.1,
    },
    "spo2": {
        "display_unit": "%",
        "normal_min": 95,
        "normal_max": 100,
        "concerning_min": 91,
        "concerning_max": 94,
        "low_min": 80,
        "low_max": 90,
        "critical_max": 79,
    },
    "pulse_rate": {
        "display_unit": "bpm",
        "low_max": 59,
        "normal_min": 60,
        "normal_max": 100,
        "high_min": 101,
        "high_max": 120,
        "critical_min": 121,
    },
    "respiratory_rate": {
        "display_unit": "breaths/min",
        "low_max": 11,
        "normal_min": 12,
        "normal_max": 20,
        "high_min": 21,
        "high_max": 24,
        "critical_min": 25,
    },
    "diagnosis": {
        "priority_order": [
            "spo2",
            "temperature",
            "pulse_rate",
            "respiratory_rate",
            "bmi",
        ],
        "normal_message": "All measured parameters are within acceptable range.",
        "needs_attention_message": "Some parameters need attention. Please review advice.",
        "critical_message": "Critical condition detected. Seek immediate help.",
    },
}

DEFAULT_SESSION_DEFAULTS: Dict[str, Any] = {
    "session": {
        "default_runtime_mode": DEFAULT_RUNTIME_MODE,
        "allow_manual_mode_switch": True,
        "anonymous_users_only": True,
    },
    "measurement": {
        "demo_duration_ms": DEMO_MEASUREMENT_DURATION_MS,
        "hardware_wait_until_complete": True,
        "generate_pdf_report": True,
        "generate_qr_report": True,
        "store_measurements_in_database": True,
    },
    "consult": {
        "ambulance_number": EMERGENCY_NUMBER,
        "enable_dynamic_tips": True,
    },
    "details": {
        "enable_bmi_detail_screen": True,
        "enable_temperature_detail_screen": True,
        "enable_spo2_detail_screen": True,
        "enable_pulse_detail_screen": True,
        "enable_rr_detail_screen": True,
    },
}


# ============================================================
# Dataclasses
# ============================================================

@dataclass(frozen=True)
class AppPaths:
    project_root: Path = PROJECT_ROOT
    assets_dir: Path = ASSETS_DIR
    data_dir: Path = DATA_DIR
    docs_dir: Path = DOCS_DIR
    tests_dir: Path = TESTS_DIR

    backgrounds_dir: Path = BACKGROUNDS_DIR
    logos_dir: Path = LOGOS_DIR
    illustrations_dir: Path = ILLUSTRATIONS_DIR
    icons_dir: Path = ICONS_DIR
    detail_graphics_dir: Path = DETAIL_GRAPHICS_DIR
    sounds_dir: Path = SOUNDS_DIR
    fonts_dir: Path = FONTS_DIR

    db_dir: Path = DB_DIR
    reports_dir: Path = REPORTS_DIR
    qr_dir: Path = QR_DIR
    backups_dir: Path = BACKUPS_DIR
    exports_dir: Path = EXPORTS_DIR
    temp_dir: Path = TEMP_DIR
    logs_dir: Path = LOGS_DIR
    config_dir: Path = DATA_CONFIG_DIR

    db_file: Path = DB_FILE
    app_log_file: Path = APP_LOG_FILE
    serial_log_file: Path = SERIAL_LOG_FILE
    settings_file: Path = SETTINGS_FILE
    calibration_file: Path = CALIBRATION_FILE
    thresholds_file: Path = THRESHOLDS_FILE
    session_defaults_file: Path = SESSION_DEFAULTS_FILE


@dataclass
class RuntimeFlags:
    is_windows: bool = IS_WINDOWS
    is_linux: bool = IS_LINUX
    is_mac: bool = IS_MAC
    is_raspberry_pi: bool = IS_RASPBERRY_PI


@dataclass
class RuntimeConfig:
    app_name: str = APP_NAME
    app_version: str = APP_VERSION
    app_group_credit: str = APP_GROUP_CREDIT
    width: int = KIOSK_WIDTH
    height: int = KIOSK_HEIGHT
    default_mode: str = DEFAULT_RUNTIME_MODE
    default_theme: str = DEFAULT_THEME_MODE
    default_language: str = DEFAULT_LANGUAGE
    emergency_number: str = EMERGENCY_NUMBER
    admin_username: str = ADMIN_USERNAME
    admin_password: str = ADMIN_PASSWORD
    serial_candidates: List[str] = field(default_factory=lambda: list(SERIAL_PORT_CANDIDATES))


PATHS = AppPaths()
FLAGS = RuntimeFlags()
RUNTIME = RuntimeConfig()


def scaled(value: int | float, minimum: int | None = None) -> int:
    """
    Scale a pixel-oriented design value from the original 1024x600 layout
    down to the current kiosk resolution. This is mainly intended for UI
    spacing, icon sizes, heights, and font fallbacks in compact screens.
    """
    scaled_value = int(round(float(value) * UI_SCALE))
    if minimum is not None:
        return max(int(minimum), scaled_value)
    return scaled_value


def h_scaled(value: int | float, minimum: int | None = None) -> int:
    """
    Scale a value using the kiosk height ratio. Helpful for vertical gaps,
    top/bottom padding, and screen sections where height is the limiting
    factor on the 800x480 display.
    """
    scaled_value = int(round(float(value) * HEIGHT_SCALE))
    if minimum is not None:
        return max(int(minimum), scaled_value)
    return scaled_value


def w_scaled(value: int | float, minimum: int | None = None) -> int:
    """
    Scale a value using the kiosk width ratio. Helpful for horizontal card
    widths, column gaps, and left/right padding.
    """
    scaled_value = int(round(float(value) * WIDTH_SCALE))
    if minimum is not None:
        return max(int(minimum), scaled_value)
    return scaled_value


# ============================================================
# Helpers
# ============================================================

def _make_directory(path: Path) -> None:
    """Create a directory if it does not already exist."""
    path.mkdir(parents=True, exist_ok=True)


def _write_json_if_missing(path: Path, payload: Dict[str, Any]) -> None:
    """Write JSON file only if it does not already exist."""
    if not path.exists():
        path.write_text(
            json.dumps(payload, indent=4, ensure_ascii=False),
            encoding="utf-8",
        )


def _touch_if_missing(path: Path) -> None:
    """Create an empty file if it does not already exist."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()


def _ensure_keep_file(folder: Path) -> None:
    """Ensure a .keep placeholder exists in data folders when needed."""
    folder.mkdir(parents=True, exist_ok=True)
    keep = folder / ".keep"
    if not keep.exists():
        keep.touch()


# ============================================================
# Public bootstrap API
# ============================================================

def ensure_project_directories() -> None:
    """
    Create all required project directories for first run and deployment.
    Safe to call repeatedly.
    """
    directories = [
        ASSETS_DIR,
        BACKGROUNDS_DIR,
        LOGOS_DIR,
        ILLUSTRATIONS_DIR,
        ICONS_DIR,
        DETAIL_GRAPHICS_DIR,
        SOUNDS_DIR,
        FONTS_DIR,
        DATA_DIR,
        DB_DIR,
        REPORTS_DIR,
        QR_DIR,
        BACKUPS_DIR,
        EXPORTS_DIR,
        TEMP_DIR,
        LOGS_DIR,
        DATA_CONFIG_DIR,
        DOCS_DIR,
        TESTS_DIR,
    ]
    for directory in directories:
        _make_directory(directory)

    _ensure_keep_file(REPORTS_DIR)
    _ensure_keep_file(QR_DIR)
    _ensure_keep_file(BACKUPS_DIR)
    _ensure_keep_file(EXPORTS_DIR)
    _ensure_keep_file(TEMP_DIR)


def ensure_runtime_files() -> None:
    """
    Create log files and default JSON configuration files if missing.
    Safe to call repeatedly.
    """
    _touch_if_missing(APP_LOG_FILE)
    _touch_if_missing(SERIAL_LOG_FILE)
    _write_json_if_missing(SETTINGS_FILE, DEFAULT_SETTINGS)
    _write_json_if_missing(CALIBRATION_FILE, DEFAULT_CALIBRATION)
    _write_json_if_missing(THRESHOLDS_FILE, DEFAULT_THRESHOLDS)
    _write_json_if_missing(SESSION_DEFAULTS_FILE, DEFAULT_SESSION_DEFAULTS)


def bootstrap_environment() -> None:
    """
    Main setup entry point for application startup.
    The main app can call this once before loading services and UI.
    """
    ensure_project_directories()
    ensure_runtime_files()


# ============================================================
# JSON readers
# These are intentionally lightweight so early modules can use
# them before the service layer is built.
# ============================================================

def _safe_read_json(path: Path, fallback: Dict[str, Any]) -> Dict[str, Any]:
    """
    Read JSON config safely. If malformed or missing, return a deep copy
    of the fallback to avoid accidental mutation of module-level defaults.
    """
    try:
        if not path.exists():
            return copy.deepcopy(fallback)
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return copy.deepcopy(fallback)


def read_settings() -> Dict[str, Any]:
    return _safe_read_json(SETTINGS_FILE, DEFAULT_SETTINGS)


def read_calibration() -> Dict[str, Any]:
    return _safe_read_json(CALIBRATION_FILE, DEFAULT_CALIBRATION)


def read_thresholds() -> Dict[str, Any]:
    return _safe_read_json(THRESHOLDS_FILE, DEFAULT_THRESHOLDS)


def read_session_defaults() -> Dict[str, Any]:
    return _safe_read_json(SESSION_DEFAULTS_FILE, DEFAULT_SESSION_DEFAULTS)


# ============================================================
# Convenience writers
# Later service classes may replace these, but these helpers make
# early startup and testing easier.
# ============================================================

def write_settings(payload: Dict[str, Any]) -> None:
    SETTINGS_FILE.write_text(json.dumps(payload, indent=4, ensure_ascii=False), encoding="utf-8")


def write_calibration(payload: Dict[str, Any]) -> None:
    CALIBRATION_FILE.write_text(json.dumps(payload, indent=4, ensure_ascii=False), encoding="utf-8")


def write_thresholds(payload: Dict[str, Any]) -> None:
    THRESHOLDS_FILE.write_text(json.dumps(payload, indent=4, ensure_ascii=False), encoding="utf-8")


def write_session_defaults(payload: Dict[str, Any]) -> None:
    SESSION_DEFAULTS_FILE.write_text(json.dumps(payload, indent=4, ensure_ascii=False), encoding="utf-8")


# ============================================================
# Useful runtime helpers for other modules
# ============================================================

def get_default_serial_port() -> str:
    """Return the first preferred serial port candidate, if any."""
    return SERIAL_PORT_CANDIDATES[0] if SERIAL_PORT_CANDIDATES else ""


def get_screen_timeout_ms(timeout_key: str | None = None) -> int:
    """
    Convert a timeout key to milliseconds.
    Returns 0 for always active or unknown keys falling back to default.
    """
    key = timeout_key or DEFAULT_SCREEN_TIMEOUT
    return SCREEN_TIMEOUT_MAP_MS.get(key, SCREEN_TIMEOUT_MAP_MS[DEFAULT_SCREEN_TIMEOUT])


def get_font_candidates() -> List[str]:
    """
    Preferred font stack for cross-platform use.
    Custom fonts can be loaded later from assets/fonts.
    """
    return [
        "Inter",
        "Segoe UI",
        "Arial",
        "DejaVu Sans",
        "Sans Serif",
    ]


def as_dict() -> Dict[str, Any]:
    """
    Flatten the main configuration into a serializable dictionary.
    Helpful for debugging, diagnostics, or README examples.
    """
    return {
        "app": {
            "name": APP_NAME,
            "short_name": APP_SHORT_NAME,
            "version": APP_VERSION,
            "organization": APP_ORGANIZATION,
            "group_credit": APP_GROUP_CREDIT,
        },
        "display": {
            "width": KIOSK_WIDTH,
            "height": KIOSK_HEIGHT,
            "fixed_size": list(KIOSK_FIXED_SIZE),
            "default_theme": DEFAULT_THEME_MODE,
            "default_language": DEFAULT_LANGUAGE,
        },
        "security": {
            "admin_username": ADMIN_USERNAME,
            "emergency_number": EMERGENCY_NUMBER,
            "default_admin_lock": DEFAULT_ADMIN_LOCK,
        },
        "runtime": {
            "default_mode": DEFAULT_RUNTIME_MODE,
            "supported_modes": SUPPORTED_RUNTIME_MODES,
            "supported_themes": SUPPORTED_THEME_MODES,
            "supported_timeouts": SUPPORTED_SCREEN_TIMEOUTS,
            "is_windows": IS_WINDOWS,
            "is_linux": IS_LINUX,
            "is_mac": IS_MAC,
            "is_raspberry_pi": IS_RASPBERRY_PI,
        },
        "serial": {
            "baudrate": DEFAULT_SERIAL_BAUDRATE,
            "timeout_seconds": DEFAULT_SERIAL_TIMEOUT_SECONDS,
            "reconnect_seconds": DEFAULT_SERIAL_RECONNECT_SECONDS,
            "candidates": list(SERIAL_PORT_CANDIDATES),
        },
        "paths": {
            "project_root": str(PROJECT_ROOT),
            "assets_dir": str(ASSETS_DIR),
            "data_dir": str(DATA_DIR),
            "db_file": str(DB_FILE),
            "settings_file": str(SETTINGS_FILE),
            "calibration_file": str(CALIBRATION_FILE),
            "thresholds_file": str(THRESHOLDS_FILE),
            "session_defaults_file": str(SESSION_DEFAULTS_FILE),
        },
    }


# ============================================================
# Bootstrap on import
# This makes development easier because the folder structure is
# prepared even before main.py is completed.
# ============================================================

bootstrap_environment()
