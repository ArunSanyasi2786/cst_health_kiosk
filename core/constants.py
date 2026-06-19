"""
core/constants.py

Central immutable constants for the CST Health Monitoring Station kiosk.

Purpose:
- Keep route names, metric keys, labels, UI IDs, ranges, and static mappings in one place
- Prevent hard-coded strings being repeated across screens/services/widgets
- Make later files consistent and easier to maintain
- Support both demo mode and hardware mode with the same app flow

Important design notes:
- Asset file paths are NOT stored here; those belong in core/asset_paths.py
- Mutable runtime state is NOT stored here; that belongs in core/app_state.py
- Persistent settings/calibration are NOT stored here; that belongs in services/*

Compact-resolution update:
- The real target screen is 800x480.
- Original visual tuning started around 1024x600.
- This file now derives its UI sizing tokens from config scale helpers so later
  screens/widgets can become more compact without rewriting business logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from config import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    APP_GROUP_CREDIT,
    APP_NAME,
    APP_ORGANIZATION,
    APP_SHORT_NAME,
    APP_VERSION,
    DEMO_MEASUREMENT_DURATION_MS,
    EMERGENCY_NUMBER,
    HARDWARE_MEASUREMENT_FAILSAFE_TIMEOUT_MS,
    HEIGHT_SCALE,
    IS_COMPACT_HEIGHT,
    IS_COMPACT_KIOSK,
    IS_COMPACT_WIDTH,
    KIOSK_HEIGHT,
    KIOSK_WIDTH,
    LOGO_GLOW_PULSE_MS,
    RESULTS_AUTO_REFRESH_MS,
    TRANSITION_DURATION_MS,
    UI_SCALE,
    WELCOME_SCREEN_DURATION_MS,
    WIDTH_SCALE,
)


# ============================================================
# Local scaling helpers
# ============================================================

def _scale(value: int | float, *, minimum: int | float | None = None) -> int:
    scaled = int(round(float(value) * UI_SCALE))
    if minimum is not None:
        scaled = max(int(round(minimum)), scaled)
    return scaled


def _wscale(value: int | float, *, minimum: int | float | None = None) -> int:
    scaled = int(round(float(value) * WIDTH_SCALE))
    if minimum is not None:
        scaled = max(int(round(minimum)), scaled)
    return scaled


def _hscale(value: int | float, *, minimum: int | float | None = None) -> int:
    scaled = int(round(float(value) * HEIGHT_SCALE))
    if minimum is not None:
        scaled = max(int(round(minimum)), scaled)
    return scaled


# ============================================================
# App identity
# ============================================================

APP_TITLE = APP_NAME
APP_SUBTITLE = "Health Monitoring Station"
APP_SHORT_TITLE = APP_SHORT_NAME
APP_COPYRIGHT = f"{APP_ORGANIZATION} • {APP_GROUP_CREDIT}"
APP_VERSION_TEXT = f"v{APP_VERSION}"

DEFAULT_WINDOW_TITLE = f"{APP_NAME} - {APP_VERSION_TEXT}"
DEVELOPED_BY_TEXT = f"Developed by: {APP_GROUP_CREDIT}"


# ============================================================
# Window / kiosk layout constants
# ============================================================

WINDOW_WIDTH = KIOSK_WIDTH
WINDOW_HEIGHT = KIOSK_HEIGHT
WINDOW_SIZE = (WINDOW_WIDTH, WINDOW_HEIGHT)
WINDOW_CENTER = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2)

# Compact-aware layout tokens.
MAIN_CONTENT_MARGIN = _scale(24, minimum=12)
SCREEN_SIDE_MARGIN = _wscale(26, minimum=12)
SCREEN_TOP_MARGIN = _hscale(20, minimum=10)
SCREEN_BOTTOM_MARGIN = _hscale(18, minimum=10)
SECTION_SPACING = _scale(16, minimum=8)
GRID_SPACING = _scale(14, minimum=8)
COMPACT_GAP = _scale(10, minimum=6)

CARD_RADIUS = _scale(20, minimum=12)
BUTTON_RADIUS = _scale(18, minimum=12)
METRIC_TILE_RADIUS = _scale(18, minimum=12)
PANEL_RADIUS = _scale(22, minimum=14)
INPUT_RADIUS = _scale(14, minimum=10)

HEADER_HEIGHT = _hscale(82, minimum=60)
HEADER_COMPACT_HEIGHT = _hscale(72, minimum=56)
FOOTER_HEIGHT = _hscale(56, minimum=40)

BUTTON_HEIGHT_LG = _hscale(56, minimum=42)
BUTTON_HEIGHT_MD = _hscale(48, minimum=38)
BUTTON_HEIGHT_SM = _hscale(40, minimum=34)

METRIC_TILE_HEIGHT = _hscale(118, minimum=88)
METRIC_TILE_HEIGHT_COMPACT = _hscale(100, minimum=82)
QUICK_ACTION_CARD_HEIGHT = _hscale(96, minimum=76)
STATUS_CARD_MIN_HEIGHT = _hscale(130, minimum=96)

ICON_SIZE_XL = _scale(44, minimum=28)
ICON_SIZE_LG = _scale(36, minimum=24)
ICON_SIZE_MD = _scale(28, minimum=20)
ICON_SIZE_SM = _scale(22, minimum=16)

TITLE_FONT_SIZE = _scale(28, minimum=18)
SUBTITLE_FONT_SIZE = _scale(13, minimum=10)
SECTION_TITLE_FONT_SIZE = _scale(20, minimum=14)
BODY_FONT_SIZE = _scale(13, minimum=10)
SMALL_FONT_SIZE = _scale(11, minimum=9)
VALUE_FONT_SIZE = _scale(26, minimum=18)
HERO_VALUE_FONT_SIZE = _scale(38, minimum=24)

ILLUSTRATION_MAX_HEIGHT_MODE_SELECT = _hscale(280, minimum=180)
ILLUSTRATION_MAX_HEIGHT_MEASURING = _hscale(250, minimum=160)
GAUGE_HEIGHT = _hscale(220, minimum=150)
DETAIL_BOTTOM_BOX_HEIGHT = _hscale(88, minimum=60)

DEFAULT_ANIMATION_DURATION_MS = TRANSITION_DURATION_MS
WELCOME_DURATION_MS = WELCOME_SCREEN_DURATION_MS
WELCOME_LOGO_GLOW_MS = LOGO_GLOW_PULSE_MS
DEFAULT_RESULTS_REFRESH_MS = RESULTS_AUTO_REFRESH_MS

DEMO_MEASURING_DURATION_MS = DEMO_MEASUREMENT_DURATION_MS
HARDWARE_MEASURING_TIMEOUT_MS = HARDWARE_MEASUREMENT_FAILSAFE_TIMEOUT_MS

RESPONSIVE_BREAKPOINT_XS = 800
RESPONSIVE_BREAKPOINT_SM = 920
RESPONSIVE_BREAKPOINT_MD = 1024
RESPONSIVE_BREAKPOINT_LG = 1120

IS_SMALL_LAYOUT = IS_COMPACT_KIOSK
IS_SMALL_WIDTH = IS_COMPACT_WIDTH
IS_SMALL_HEIGHT = IS_COMPACT_HEIGHT


# ============================================================
# Authentication constants
# ============================================================

ADMIN_LOGIN_USERNAME = ADMIN_USERNAME
ADMIN_LOGIN_PASSWORD = ADMIN_PASSWORD

AUTH_SUCCESS = "auth_success"
AUTH_FAILED = "auth_failed"


# ============================================================
# Runtime mode constants
# ============================================================

MODE_DEMO = "demo"
MODE_HARDWARE = "hardware"

RUNTIME_MODES = [MODE_DEMO, MODE_HARDWARE]

MODE_LABELS = {
    MODE_DEMO: "Demo Mode",
    MODE_HARDWARE: "Hardware Mode",
}

MODE_DESCRIPTIONS = {
    MODE_DEMO: "Simulated measurements for presentation and testing.",
    MODE_HARDWARE: "Live sensor measurements from connected hardware.",
}


# ============================================================
# Application route / screen names
# ============================================================

ROUTE_WELCOME = "welcome"
ROUTE_MODE_SELECT = "mode_select"
ROUTE_MEASURING = "measuring"
ROUTE_RESULTS = "results"
ROUTE_QR = "qr"
ROUTE_CONSULT = "consult"

ROUTE_ADMIN_LOGIN = "admin_login"
ROUTE_ADMIN_PANEL = "admin_panel"
ROUTE_SETTINGS = "settings"
ROUTE_CALIBRATION = "calibration"
ROUTE_PARAMETERS = "parameters"
ROUTE_DIAGNOSIS = "diagnosis"
ROUTE_STORAGE = "storage"
ROUTE_PUBLISH = "publish"

ROUTE_BMI_DETAIL = "bmi_detail"
ROUTE_TEMPERATURE_DETAIL = "temperature_detail"
ROUTE_SPO2_DETAIL = "spo2_detail"
ROUTE_PULSE_DETAIL = "pulse_detail"
ROUTE_RR_DETAIL = "rr_detail"

SCREEN_WELCOME = ROUTE_WELCOME
SCREEN_MODE_SELECT = ROUTE_MODE_SELECT
SCREEN_MEASURING = ROUTE_MEASURING
SCREEN_RESULTS = ROUTE_RESULTS
SCREEN_QR = ROUTE_QR
SCREEN_CONSULT = ROUTE_CONSULT

SCREEN_ADMIN_LOGIN = ROUTE_ADMIN_LOGIN
SCREEN_ADMIN_PANEL = ROUTE_ADMIN_PANEL
SCREEN_SETTINGS = ROUTE_SETTINGS
SCREEN_CALIBRATION = ROUTE_CALIBRATION
SCREEN_PARAMETERS = ROUTE_PARAMETERS
SCREEN_DIAGNOSIS = ROUTE_DIAGNOSIS
SCREEN_STORAGE = ROUTE_STORAGE
SCREEN_PUBLISH = ROUTE_PUBLISH

SCREEN_BMI_DETAIL = ROUTE_BMI_DETAIL
SCREEN_TEMPERATURE_DETAIL = ROUTE_TEMPERATURE_DETAIL
SCREEN_SPO2_DETAIL = ROUTE_SPO2_DETAIL
SCREEN_PULSE_DETAIL = ROUTE_PULSE_DETAIL
SCREEN_RR_DETAIL = ROUTE_RR_DETAIL

ALL_ROUTES = [
    ROUTE_WELCOME,
    ROUTE_MODE_SELECT,
    ROUTE_MEASURING,
    ROUTE_RESULTS,
    ROUTE_QR,
    ROUTE_CONSULT,
    ROUTE_ADMIN_LOGIN,
    ROUTE_ADMIN_PANEL,
    ROUTE_SETTINGS,
    ROUTE_CALIBRATION,
    ROUTE_PARAMETERS,
    ROUTE_DIAGNOSIS,
    ROUTE_STORAGE,
    ROUTE_PUBLISH,
    ROUTE_BMI_DETAIL,
    ROUTE_TEMPERATURE_DETAIL,
    ROUTE_SPO2_DETAIL,
    ROUTE_PULSE_DETAIL,
    ROUTE_RR_DETAIL,
]

PUBLIC_ROUTES = [
    ROUTE_WELCOME,
    ROUTE_MODE_SELECT,
    ROUTE_MEASURING,
    ROUTE_RESULTS,
    ROUTE_QR,
    ROUTE_CONSULT,
]

ADMIN_ROUTES = [
    ROUTE_ADMIN_LOGIN,
    ROUTE_ADMIN_PANEL,
    ROUTE_SETTINGS,
    ROUTE_CALIBRATION,
    ROUTE_PARAMETERS,
    ROUTE_DIAGNOSIS,
    ROUTE_STORAGE,
    ROUTE_PUBLISH,
]

DETAIL_ROUTES = [
    ROUTE_BMI_DETAIL,
    ROUTE_TEMPERATURE_DETAIL,
    ROUTE_SPO2_DETAIL,
    ROUTE_PULSE_DETAIL,
    ROUTE_RR_DETAIL,
]


# ============================================================
# Human-friendly screen titles
# ============================================================

SCREEN_TITLES = {
    ROUTE_WELCOME: "Welcome",
    ROUTE_MODE_SELECT: "Start Check Up",
    ROUTE_MEASURING: "Measuring",
    ROUTE_RESULTS: "Health Parameters",
    ROUTE_QR: "QR Report",
    ROUTE_CONSULT: "Consult",
    ROUTE_ADMIN_LOGIN: "Admin Access",
    ROUTE_ADMIN_PANEL: "Admin Control Panel",
    ROUTE_SETTINGS: "Settings",
    ROUTE_CALIBRATION: "Sensor Calibration",
    ROUTE_PARAMETERS: "Parameters Configuration",
    ROUTE_DIAGNOSIS: "Diagnosis",
    ROUTE_STORAGE: "Data Storage",
    ROUTE_PUBLISH: "Publish / Insights",
    ROUTE_BMI_DETAIL: "BMI",
    ROUTE_TEMPERATURE_DETAIL: "Temperature",
    ROUTE_SPO2_DETAIL: "SpO₂",
    ROUTE_PULSE_DETAIL: "Pulse Rate",
    ROUTE_RR_DETAIL: "Respiratory Rate",
}


# ============================================================
# Main public action IDs
# ============================================================

ACTION_START_CHECKUP = "start_checkup"
ACTION_ENTER_ADMIN = "enter_admin"
ACTION_CANCEL_MEASUREMENT = "cancel_measurement"
ACTION_SHOW_QR = "show_qr"
ACTION_SHOW_CONSULT = "show_consult"
ACTION_BACK = "back"
ACTION_LOGIN = "login"
ACTION_LOGOUT = "logout"
ACTION_UPDATE = "update"
ACTION_SAVE = "save"
ACTION_RESET = "reset"
ACTION_BACKUP = "backup"
ACTION_CLEAR_DATA = "clear_data"
ACTION_EXPORT = "export"
ACTION_AUTO_CALIBRATE = "auto_calibrate"
ACTION_MANUAL_CALIBRATE = "manual_calibrate"


# ============================================================
# Admin panel tile IDs
# ============================================================

ADMIN_TILE_SETTINGS = "admin_settings"
ADMIN_TILE_CALIBRATION = "admin_calibration"
ADMIN_TILE_PARAMETERS = "admin_parameters"
ADMIN_TILE_DIAGNOSIS = "admin_diagnosis"
ADMIN_TILE_STORAGE = "admin_storage"
ADMIN_TILE_PUBLISH = "admin_publish"

ADMIN_PANEL_TILES = [
    ADMIN_TILE_SETTINGS,
    ADMIN_TILE_CALIBRATION,
    ADMIN_TILE_PARAMETERS,
    ADMIN_TILE_DIAGNOSIS,
    ADMIN_TILE_STORAGE,
    ADMIN_TILE_PUBLISH,
]

ADMIN_PANEL_TILE_ROUTE_MAP = {
    ADMIN_TILE_SETTINGS: ROUTE_SETTINGS,
    ADMIN_TILE_CALIBRATION: ROUTE_CALIBRATION,
    ADMIN_TILE_PARAMETERS: ROUTE_PARAMETERS,
    ADMIN_TILE_DIAGNOSIS: ROUTE_DIAGNOSIS,
    ADMIN_TILE_STORAGE: ROUTE_STORAGE,
    ADMIN_TILE_PUBLISH: ROUTE_PUBLISH,
}

ADMIN_PANEL_TILE_LABELS = {
    ADMIN_TILE_SETTINGS: "Settings",
    ADMIN_TILE_CALIBRATION: "Calibrate",
    ADMIN_TILE_PARAMETERS: "Parameters",
    ADMIN_TILE_DIAGNOSIS: "Diagnosis",
    ADMIN_TILE_STORAGE: "Storage",
    ADMIN_TILE_PUBLISH: "Publish",
}

ADMIN_PANEL_TILE_ICON_KEYS = {
    "settings": "settings",
    "calibration": "calibrate",
    "parameters": "parameters",
    "diagnosis": "diagnosis",
    "storage": "storage",
    "publish": "publish",
    "logout": "logout",
}


# ============================================================
# Measurement metric keys
# ============================================================

METRIC_WEIGHT = "weight"
METRIC_HEIGHT = "height"
METRIC_BMI = "bmi"
METRIC_TEMPERATURE = "temperature"
METRIC_SPO2 = "spo2"
METRIC_PULSE = "pulse_rate"
METRIC_RR = "respiratory_rate"

PRIMARY_METRIC_KEYS = [
    METRIC_WEIGHT,
    METRIC_HEIGHT,
    METRIC_BMI,
    METRIC_TEMPERATURE,
    METRIC_SPO2,
    METRIC_PULSE,
    METRIC_RR,
]

METRIC_DISPLAY_ORDER = [
    METRIC_WEIGHT,
    METRIC_HEIGHT,
    METRIC_BMI,
    METRIC_TEMPERATURE,
    METRIC_SPO2,
    METRIC_PULSE,
    METRIC_RR,
]


# ============================================================
# Metric labels, units, formatting helpers
# ============================================================

METRIC_LABELS = {
    METRIC_WEIGHT: "Weight",
    METRIC_HEIGHT: "Height",
    METRIC_BMI: "BMI",
    METRIC_TEMPERATURE: "Temperature",
    METRIC_SPO2: "SpO₂",
    METRIC_PULSE: "Pulse Rate",
    METRIC_RR: "Respiratory Rate",
}

METRIC_SHORT_LABELS = {
    METRIC_WEIGHT: "WEIGHT",
    METRIC_HEIGHT: "HEIGHT",
    METRIC_BMI: "BMI",
    METRIC_TEMPERATURE: "TEMPERATURE",
    METRIC_SPO2: "SPO₂",
    METRIC_PULSE: "PULSE RATE",
    METRIC_RR: "RR",
}

METRIC_UNITS = {
    METRIC_WEIGHT: "kg",
    METRIC_HEIGHT: "cm",
    METRIC_BMI: "",
    METRIC_TEMPERATURE: "°C",
    METRIC_SPO2: "%",
    METRIC_PULSE: "bpm",
    METRIC_RR: "breaths/min",
}

METRIC_DECIMALS = {
    METRIC_WEIGHT: 1,
    METRIC_HEIGHT: 1,
    METRIC_BMI: 1,
    METRIC_TEMPERATURE: 1,
    METRIC_SPO2: 0,
    METRIC_PULSE: 0,
    METRIC_RR: 1,
}

METRIC_DEFAULT_VALUES = {
    METRIC_WEIGHT: 0.0,
    METRIC_HEIGHT: 0.0,
    METRIC_BMI: 0.0,
    METRIC_TEMPERATURE: 0.0,
    METRIC_SPO2: 0.0,
    METRIC_PULSE: 0.0,
    METRIC_RR: 0.0,
}


# ============================================================
# Results screen interactive tile -> detail route map
# ============================================================

METRIC_DETAIL_ROUTE_MAP = {
    METRIC_BMI: ROUTE_BMI_DETAIL,
    METRIC_TEMPERATURE: ROUTE_TEMPERATURE_DETAIL,
    METRIC_SPO2: ROUTE_SPO2_DETAIL,
    METRIC_PULSE: ROUTE_PULSE_DETAIL,
    METRIC_RR: ROUTE_RR_DETAIL,
}

RESULTS_QUICK_ACTION_QR = "quick_qr"
RESULTS_QUICK_ACTION_CONSULT = "quick_consult"

RESULTS_QUICK_ACTIONS = [
    RESULTS_QUICK_ACTION_QR,
    RESULTS_QUICK_ACTION_CONSULT,
]


# ============================================================
# Session and storage constants
# ============================================================

SESSION_STATUS_IDLE = "idle"
SESSION_STATUS_MEASURING = "measuring"
SESSION_STATUS_COMPLETE = "complete"
SESSION_STATUS_CANCELLED = "cancelled"
SESSION_STATUS_ERROR = "error"

SESSION_STATUSES = [
    SESSION_STATUS_IDLE,
    SESSION_STATUS_MEASURING,
    SESSION_STATUS_COMPLETE,
    SESSION_STATUS_CANCELLED,
    SESSION_STATUS_ERROR,
]

REPORT_FILE_PREFIX = "health_report"
QR_FILE_PREFIX = "health_qr"
BACKUP_FILE_PREFIX = "kiosk_backup"
EXPORT_FILE_PREFIX = "kiosk_export"

DATABASE_TABLE_SESSIONS = "health_sessions"
DATABASE_TABLE_SETTINGS_AUDIT = "settings_audit"
DATABASE_TABLE_CALIBRATION_AUDIT = "calibration_audit"


# ============================================================
# Status / severity constants
# ============================================================

SEVERITY_NORMAL = "normal"
SEVERITY_INFO = "info"
SEVERITY_ATTENTION = "attention"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"
SEVERITY_UNKNOWN = "unknown"

SEVERITY_ORDER = [
    SEVERITY_NORMAL,
    SEVERITY_INFO,
    SEVERITY_ATTENTION,
    SEVERITY_WARNING,
    SEVERITY_CRITICAL,
]

SEVERITY_PRIORITY = {
    SEVERITY_NORMAL: 0,
    SEVERITY_INFO: 1,
    SEVERITY_ATTENTION: 2,
    SEVERITY_WARNING: 3,
    SEVERITY_CRITICAL: 4,
    SEVERITY_UNKNOWN: -1,
}

HEALTH_STATUS_NORMAL = "All parameters are normal"
HEALTH_STATUS_NEEDS_ATTENTION = "Needs Attention"
HEALTH_STATUS_CRITICAL = "Critical Attention Required"

NETWORK_CONNECTED = "connected"
NETWORK_DISCONNECTED = "disconnected"
SERIAL_WAITING = "serial_waiting"
SERIAL_CONNECTED = "serial_connected"
SERIAL_DISCONNECTED = "serial_disconnected"


# ============================================================
# Diagnosis issue keys
# ============================================================

ISSUE_LOW_SPO2 = "low_spo2"
ISSUE_CRITICAL_SPO2 = "critical_spo2"
ISSUE_FEVER = "fever"
ISSUE_HIGH_FEVER = "high_fever"
ISSUE_CRITICAL_FEVER = "critical_fever"
ISSUE_LOW_PULSE = "low_pulse"
ISSUE_HIGH_PULSE = "high_pulse"
ISSUE_LOW_RR = "low_respiratory_rate"
ISSUE_HIGH_RR = "high_respiratory_rate"
ISSUE_BMI_UNDERWEIGHT = "bmi_underweight"
ISSUE_BMI_OVERWEIGHT = "bmi_overweight"
ISSUE_BMI_OBESE = "bmi_obese"

DIAGNOSIS_ISSUE_LABELS = {
    ISSUE_LOW_SPO2: "Low O₂",
    ISSUE_CRITICAL_SPO2: "Critical O₂",
    ISSUE_FEVER: "Mild Fever",
    ISSUE_HIGH_FEVER: "High Fever",
    ISSUE_CRITICAL_FEVER: "Very High Fever",
    ISSUE_LOW_PULSE: "Low Pulse",
    ISSUE_HIGH_PULSE: "High Pulse",
    ISSUE_LOW_RR: "Low Respiratory Rate",
    ISSUE_HIGH_RR: "High Respiratory Rate",
    ISSUE_BMI_UNDERWEIGHT: "Underweight BMI",
    ISSUE_BMI_OVERWEIGHT: "Overweight BMI",
    ISSUE_BMI_OBESE: "Obese BMI",
}


# ============================================================
# Static category constants per metric
# ============================================================

BMI_CATEGORY_UNDERWEIGHT = "underweight"
BMI_CATEGORY_NORMAL = "normal"
BMI_CATEGORY_OVERWEIGHT = "overweight"
BMI_CATEGORY_OBESE = "obese"

BMI_CATEGORIES = [
    BMI_CATEGORY_UNDERWEIGHT,
    BMI_CATEGORY_NORMAL,
    BMI_CATEGORY_OVERWEIGHT,
    BMI_CATEGORY_OBESE,
]

BMI_CATEGORY_LABELS = {
    BMI_CATEGORY_UNDERWEIGHT: "Underweight",
    BMI_CATEGORY_NORMAL: "Normal",
    BMI_CATEGORY_OVERWEIGHT: "Overweight",
    BMI_CATEGORY_OBESE: "Obese",
}

TEMPERATURE_CATEGORY_NORMAL = "normal"
TEMPERATURE_CATEGORY_MILD_FEVER = "mild_fever"
TEMPERATURE_CATEGORY_HIGH_FEVER = "high_fever"
TEMPERATURE_CATEGORY_VERY_HIGH_FEVER = "very_high_fever"

TEMPERATURE_CATEGORIES = [
    TEMPERATURE_CATEGORY_NORMAL,
    TEMPERATURE_CATEGORY_MILD_FEVER,
    TEMPERATURE_CATEGORY_HIGH_FEVER,
    TEMPERATURE_CATEGORY_VERY_HIGH_FEVER,
]

TEMPERATURE_CATEGORY_LABELS = {
    TEMPERATURE_CATEGORY_NORMAL: "Normal",
    TEMPERATURE_CATEGORY_MILD_FEVER: "Mild Fever",
    TEMPERATURE_CATEGORY_HIGH_FEVER: "High Fever",
    TEMPERATURE_CATEGORY_VERY_HIGH_FEVER: "Very High Fever",
}

SPO2_CATEGORY_NORMAL = "normal"
SPO2_CATEGORY_CONCERNING = "concerning"
SPO2_CATEGORY_LOW = "low"
SPO2_CATEGORY_CRITICAL = "critical"

SPO2_CATEGORIES = [
    SPO2_CATEGORY_NORMAL,
    SPO2_CATEGORY_CONCERNING,
    SPO2_CATEGORY_LOW,
    SPO2_CATEGORY_CRITICAL,
]

SPO2_CATEGORY_LABELS = {
    SPO2_CATEGORY_NORMAL: "Normal",
    SPO2_CATEGORY_CONCERNING: "Concerning",
    SPO2_CATEGORY_LOW: "Low Level",
    SPO2_CATEGORY_CRITICAL: "Critical",
}

PULSE_CATEGORY_LOW = "low"
PULSE_CATEGORY_NORMAL = "normal"
PULSE_CATEGORY_ELEVATED = "elevated"
PULSE_CATEGORY_HIGH = "high"

PULSE_CATEGORIES = [
    PULSE_CATEGORY_LOW,
    PULSE_CATEGORY_NORMAL,
    PULSE_CATEGORY_ELEVATED,
    PULSE_CATEGORY_HIGH,
]

PULSE_CATEGORY_LABELS = {
    PULSE_CATEGORY_LOW: "Low",
    PULSE_CATEGORY_NORMAL: "Normal",
    PULSE_CATEGORY_ELEVATED: "Elevated",
    PULSE_CATEGORY_HIGH: "High",
}

RR_CATEGORY_LOW = "low"
RR_CATEGORY_NORMAL = "normal"
RR_CATEGORY_HIGH = "high"
RR_CATEGORY_CRITICAL = "critical"

RR_CATEGORIES = [
    RR_CATEGORY_LOW,
    RR_CATEGORY_NORMAL,
    RR_CATEGORY_HIGH,
    RR_CATEGORY_CRITICAL,
]

RR_CATEGORY_LABELS = {
    RR_CATEGORY_LOW: "Low",
    RR_CATEGORY_NORMAL: "Normal",
    RR_CATEGORY_HIGH: "High",
    RR_CATEGORY_CRITICAL: "Critical",
}


# ============================================================
# Quick health advice / consult tips
# ============================================================

CONSULT_DEFAULT_HEADING = "Emergency Contacts"
CONSULT_DEFAULT_TIPS_HEADING = "Health Tips"
CONSULT_AMBULANCE_LABEL = "Ambulance Service"
CONSULT_AMBULANCE_NUMBER = EMERGENCY_NUMBER

GENERIC_TIPS_NORMAL = [
    "Stay hydrated and maintain a balanced diet.",
    "Exercise regularly and monitor your health.",
    "Keep following healthy daily habits.",
]

GENERIC_TIPS_LOW_SPO2 = [
    "Sit down and rest calmly.",
    "Monitor oxygen level again if concerned.",
    "Seek urgent help if breathing difficulty develops.",
]

GENERIC_TIPS_FEVER = [
    "Drink fluids and rest.",
    "Avoid overexertion while symptoms persist.",
    "Seek help if temperature remains very high.",
]

GENERIC_TIPS_PULSE = [
    "Rest for a few minutes and recheck.",
    "Avoid heavy activity until stable.",
    "Consult a professional if irregular or persistent.",
]

GENERIC_TIPS_RR = [
    "Slow down and breathe calmly.",
    "Sit upright and relax.",
    "Seek help if shortness of breath continues.",
]

GENERIC_TIPS_BMI = [
    "Follow a balanced diet and healthy routine.",
    "Stay physically active.",
    "Seek advice for long-term weight management if needed.",
]


# ============================================================
# Publish / analytics constants
# ============================================================

PUBLISH_CATEGORY_TOTAL_RECORDS = "total_records"
PUBLISH_CATEGORY_AVERAGE_BMI = "average_bmi"
PUBLISH_CATEGORY_AVERAGE_TEMPERATURE = "average_temperature"
PUBLISH_CATEGORY_AVERAGE_SPO2 = "average_spo2"
PUBLISH_CATEGORY_AVERAGE_PULSE = "average_pulse"
PUBLISH_CATEGORY_AVERAGE_RR = "average_rr"

PUBLISH_INSIGHT_UNDERWEIGHT = "More users fall into the underweight range."
PUBLISH_INSIGHT_NORMAL = "Most users appear within normal range."
PUBLISH_INSIGHT_OVERWEIGHT = "A significant number of users are overweight."
PUBLISH_INSIGHT_OBESE = "A significant number of users are in the obese range."
PUBLISH_INSIGHT_LOW_SPO2 = "Low oxygen readings appear in a noticeable number of records."
PUBLISH_INSIGHT_FEVER = "Elevated body temperature appears in several records."
PUBLISH_INSIGHT_HIGH_PULSE = "Pulse rate is elevated in several records."
PUBLISH_INSIGHT_HIGH_RR = "Respiratory rate is elevated in several records."


# ============================================================
# Settings constants
# ============================================================

THEME_DARK = "dark"
THEME_LIGHT = "light"

SCREEN_TIMEOUT_ALWAYS = "always_active"
SCREEN_TIMEOUT_15 = "15_min"
SCREEN_TIMEOUT_10 = "10_min"

SCREEN_TIMEOUT_LABELS = {
    SCREEN_TIMEOUT_ALWAYS: "Always Active",
    SCREEN_TIMEOUT_15: "15 min",
    SCREEN_TIMEOUT_10: "10 min",
}

SETTING_GROUP_DISPLAY = "display"
SETTING_GROUP_AUDIO = "audio"
SETTING_GROUP_SYSTEM = "system"
SETTING_GROUP_HARDWARE = "hardware"

LANGUAGE_ENGLISH = "English"


# ============================================================
# UI theme style tokens
# ============================================================

THEME_TOKEN_BG_DARK = "#07162F"
THEME_TOKEN_BG_PANEL = "#0D2445"
THEME_TOKEN_BG_CARD = "#102B52"
THEME_TOKEN_BG_LIGHT = "#E9F6FF"

THEME_TOKEN_TEXT_PRIMARY = "#F2F7FF"
THEME_TOKEN_TEXT_SECONDARY = "#B8CAE7"
THEME_TOKEN_TEXT_DARK = "#10233D"

THEME_TOKEN_CYAN = "#34D6FF"
THEME_TOKEN_CYAN_SOFT = "#8BEAFF"
THEME_TOKEN_BLUE = "#1C74FF"
THEME_TOKEN_GLOW = "#55E5FF"

THEME_TOKEN_SUCCESS = "#4CD964"
THEME_TOKEN_WARNING = "#FFC247"
THEME_TOKEN_DANGER = "#FF5E73"
THEME_TOKEN_ORANGE = "#FF9A3C"
THEME_TOKEN_RED = "#FF3B5C"
THEME_TOKEN_GREEN = "#33D17A"

THEME_TOKEN_BORDER = "rgba(122, 196, 255, 0.40)"
THEME_TOKEN_GLASS = "rgba(255, 255, 255, 0.08)"
THEME_TOKEN_SHADOW = "rgba(0, 0, 0, 0.35)"

THEME_PALETTE_DARK: Dict[str, str] = {
    "window_bg": "#07162F",
    "panel_bg": "#0B1F3C",
    "card_bg": "#12305D",
    "card_bg_soft": "rgba(20, 52, 94, 0.78)",
    "text_primary": "#F5FAFF",
    "text_secondary": "#C4D4EF",
    "text_muted": "#8FA7C7",
    "accent": "#34D6FF",
    "accent_soft": "#86EBFF",
    "accent_deep": "#1B84FF",
    "success": "#42D97B",
    "warning": "#FFC14E",
    "danger": "#FF5A6F",
    "border": "rgba(112, 187, 255, 0.42)",
    "glow": "rgba(52, 214, 255, 0.35)",
    "input_bg": "rgba(10, 29, 56, 0.82)",
}

THEME_PALETTE_LIGHT: Dict[str, str] = {
    "window_bg": "#DFF4FF",
    "panel_bg": "#F4FBFF",
    "card_bg": "#FFFFFF",
    "card_bg_soft": "rgba(255, 255, 255, 0.88)",
    "text_primary": "#14304D",
    "text_secondary": "#335B80",
    "text_muted": "#62809C",
    "accent": "#18BFFF",
    "accent_soft": "#67DCFF",
    "accent_deep": "#1B84FF",
    "success": "#2DBE66",
    "warning": "#EAA82E",
    "danger": "#E6485D",
    "border": "rgba(67, 143, 208, 0.28)",
    "glow": "rgba(63, 203, 255, 0.18)",
    "input_bg": "rgba(230, 245, 255, 0.95)",
}


# ============================================================
# Sound IDs
# ============================================================

SOUND_CLICK = "click"
SOUND_SUCCESS = "success"
SOUND_WARNING = "warning"
SOUND_ERROR = "error"
SOUND_STARTUP = "startup"
SOUND_COMPLETE = "complete"
SOUND_SCAN = "scan"
SOUND_LOGOUT = "logout"
SOUND_TRANSITION = "transition"

SOUND_KEYS = [
    SOUND_CLICK,
    SOUND_SUCCESS,
    SOUND_WARNING,
    SOUND_ERROR,
    SOUND_STARTUP,
    SOUND_COMPLETE,
    SOUND_SCAN,
    SOUND_LOGOUT,
    SOUND_TRANSITION,
]


# ============================================================
# Asset keys
# ============================================================

BACKGROUND_KEYS = {
    ROUTE_WELCOME: "welcome_bg",
    ROUTE_MODE_SELECT: "mode_select_bg",
    ROUTE_MEASURING: "measuring_bg",
    ROUTE_RESULTS: "results_bg",
    ROUTE_QR: "qr_bg",
    ROUTE_CONSULT: "consult_bg",
    ROUTE_ADMIN_LOGIN: "admin_login_bg",
    ROUTE_ADMIN_PANEL: "admin_panel_bg",
    ROUTE_SETTINGS: "settings_bg",
    ROUTE_CALIBRATION: "calibration_bg",
    ROUTE_PARAMETERS: "parameters_bg",
    ROUTE_DIAGNOSIS: "diagnosis_bg",
    ROUTE_STORAGE: "storage_bg",
    ROUTE_PUBLISH: "publish_bg",
    ROUTE_BMI_DETAIL: "bmi_detail_bg",
    ROUTE_TEMPERATURE_DETAIL: "temperature_detail_bg",
    ROUTE_SPO2_DETAIL: "spo2_detail_bg",
    ROUTE_PULSE_DETAIL: "pulse_detail_bg",
    ROUTE_RR_DETAIL: "rr_detail_bg",
}

MAIN_ICON_KEYS = {
    ACTION_START_CHECKUP: "start_checkup",
    ACTION_ENTER_ADMIN: "admin",
    ACTION_BACK: "back",
    ACTION_LOGIN: "login",
    ACTION_LOGOUT: "logout",
    ACTION_SHOW_QR: "qr",
    ACTION_SHOW_CONSULT: "consult",
    ACTION_UPDATE: "update",
    ACTION_SAVE: "save",
    ACTION_RESET: "reset",
    ACTION_BACKUP: "backup",
    ACTION_CLEAR_DATA: "clear_data",
    ACTION_EXPORT: "export",
    ACTION_AUTO_CALIBRATE: "update",
    ACTION_MANUAL_CALIBRATE: "calibrate",
}

METRIC_ICON_KEYS = {
    METRIC_WEIGHT: "weight",
    METRIC_HEIGHT: "height",
    METRIC_BMI: "bmi",
    METRIC_TEMPERATURE: "temperature",
    METRIC_SPO2: "spo2",
    METRIC_PULSE: "pulse",
    METRIC_RR: "respiratory_rate",
}

SENSOR_ICON_KEYS = {
    METRIC_TEMPERATURE: "sensor_temp",
    METRIC_SPO2: "sensor_spo2",
    METRIC_WEIGHT: "sensor_weight",
    METRIC_HEIGHT: "sensor_height",
    METRIC_PULSE: "sensor_pulse",
}

ADMIN_TILE_ICON_KEYS = {
    ADMIN_TILE_SETTINGS: "settings",
    ADMIN_TILE_CALIBRATION: "calibrate",
    ADMIN_TILE_PARAMETERS: "parameters",
    ADMIN_TILE_DIAGNOSIS: "diagnosis",
    ADMIN_TILE_STORAGE: "storage",
    ADMIN_TILE_PUBLISH: "publish",
}


# ============================================================
# Metric detail visual highlight colors
# ============================================================

CATEGORY_COLORS = {
    "blue": "#2D8DFF",
    "green": "#34D96F",
    "yellow": "#F3C546",
    "orange": "#FF9A3C",
    "red": "#FF546F",
    "grey": "#6F809C",
    "muted": "#2D3C54",
    "muted_text": "#A9B7CA",
}

BMI_CATEGORY_COLOR_MAP = {
    BMI_CATEGORY_UNDERWEIGHT: CATEGORY_COLORS["blue"],
    BMI_CATEGORY_NORMAL: CATEGORY_COLORS["green"],
    BMI_CATEGORY_OVERWEIGHT: CATEGORY_COLORS["orange"],
    BMI_CATEGORY_OBESE: CATEGORY_COLORS["red"],
}

TEMPERATURE_CATEGORY_COLOR_MAP = {
    TEMPERATURE_CATEGORY_NORMAL: CATEGORY_COLORS["green"],
    TEMPERATURE_CATEGORY_MILD_FEVER: CATEGORY_COLORS["yellow"],
    TEMPERATURE_CATEGORY_HIGH_FEVER: CATEGORY_COLORS["orange"],
    TEMPERATURE_CATEGORY_VERY_HIGH_FEVER: CATEGORY_COLORS["red"],
}

SPO2_CATEGORY_COLOR_MAP = {
    SPO2_CATEGORY_NORMAL: CATEGORY_COLORS["green"],
    SPO2_CATEGORY_CONCERNING: CATEGORY_COLORS["yellow"],
    SPO2_CATEGORY_LOW: CATEGORY_COLORS["orange"],
    SPO2_CATEGORY_CRITICAL: CATEGORY_COLORS["red"],
}

PULSE_CATEGORY_COLOR_MAP = {
    PULSE_CATEGORY_LOW: CATEGORY_COLORS["blue"],
    PULSE_CATEGORY_NORMAL: CATEGORY_COLORS["green"],
    PULSE_CATEGORY_ELEVATED: CATEGORY_COLORS["yellow"],
    PULSE_CATEGORY_HIGH: CATEGORY_COLORS["red"],
}

RR_CATEGORY_COLOR_MAP = {
    RR_CATEGORY_LOW: CATEGORY_COLORS["blue"],
    RR_CATEGORY_NORMAL: CATEGORY_COLORS["green"],
    RR_CATEGORY_HIGH: CATEGORY_COLORS["orange"],
    RR_CATEGORY_CRITICAL: CATEGORY_COLORS["red"],
}


# ============================================================
# Measurement step messages
# ============================================================

MEASUREMENT_STEP_INITIAL = "Preparing sensors..."
MEASUREMENT_STEP_POSITION = "Position yourself correctly..."
MEASUREMENT_STEP_COLLECT = "Collecting samples..."
MEASUREMENT_STEP_PROCESS = "Processing health parameters..."
MEASUREMENT_STEP_COMPLETE = "Measurement complete."
MEASUREMENT_STEP_WAIT_HARDWARE = "Waiting for hardware readings..."
MEASUREMENT_STEP_CANCELLED = "Measurement cancelled."


# ============================================================
# Report constants
# ============================================================

REPORT_TITLE = "Health Measurement Report"
REPORT_SUBTITLE = "CST Health Monitoring Station"
REPORT_ANONYMOUS_USER_LABEL = "Anonymous User"
REPORT_MODE_LABEL = "Measurement Mode"
REPORT_SESSION_ID_LABEL = "Session ID"
REPORT_DATE_LABEL = "Date"
REPORT_TIME_LABEL = "Time"
REPORT_STATUS_LABEL = "Overall Status"
REPORT_EMERGENCY_LABEL = "Emergency Contact"
REPORT_QR_NOTE = "Scan QR code to access this report."

REPORT_METRIC_SECTION_TITLE = "Measured Health Parameters"
REPORT_DIAGNOSIS_SECTION_TITLE = "Diagnosis Summary"
REPORT_ADVICE_SECTION_TITLE = "Recommendations"


# ============================================================
# Database / analytics defaults
# ============================================================

STORAGE_UNIT_BYTES = "bytes"
STORAGE_UNIT_KB = "KB"
STORAGE_UNIT_MB = "MB"
STORAGE_UNIT_GB = "GB"

DEFAULT_STORAGE_LIMIT_BYTES = 16 * 1024 * 1024 * 1024
PUBLISH_METRIC_COUNT_MINIMUM = 1


# ============================================================
# Diagnostics and debug constants
# ============================================================

LOG_SCOPE_APP = "app"
LOG_SCOPE_UI = "ui"
LOG_SCOPE_DB = "database"
LOG_SCOPE_SERIAL = "serial"
LOG_SCOPE_SENSOR = "sensor"
LOG_SCOPE_SETTINGS = "settings"
LOG_SCOPE_REPORT = "report"
LOG_SCOPE_QR = "qr"
LOG_SCOPE_STORAGE = "storage"
LOG_SCOPE_PUBLISH = "publish"
LOG_SCOPE_NAVIGATOR = "navigator"

LOG_SCOPES = [
    LOG_SCOPE_APP,
    LOG_SCOPE_UI,
    LOG_SCOPE_DB,
    LOG_SCOPE_SERIAL,
    LOG_SCOPE_SENSOR,
    LOG_SCOPE_SETTINGS,
    LOG_SCOPE_REPORT,
    LOG_SCOPE_QR,
    LOG_SCOPE_STORAGE,
    LOG_SCOPE_PUBLISH,
    LOG_SCOPE_NAVIGATOR,
]


# ============================================================
# Helpful dataclasses for later modules
# ============================================================

@dataclass(frozen=True)
class MetricPresentation:
    key: str
    label: str
    short_label: str
    unit: str
    decimals: int
    icon_key: str


METRIC_PRESENTATIONS: Dict[str, MetricPresentation] = {
    key: MetricPresentation(
        key=key,
        label=METRIC_LABELS[key],
        short_label=METRIC_SHORT_LABELS[key],
        unit=METRIC_UNITS[key],
        decimals=METRIC_DECIMALS[key],
        icon_key=METRIC_ICON_KEYS[key],
    )
    for key in PRIMARY_METRIC_KEYS
}


# ============================================================
# Default empty session payload
# ============================================================

EMPTY_MEASUREMENT_PAYLOAD: Dict[str, Any] = {
    "weight": 0.0,
    "height": 0.0,
    "bmi": 0.0,
    "temperature": 0.0,
    "spo2": 0.0,
    "pulse_rate": 0.0,
    "respiratory_rate": 0.0,
}

EMPTY_DIAGNOSIS_PAYLOAD: Dict[str, Any] = {
    "overall_severity": SEVERITY_UNKNOWN,
    "status_title": "No Data",
    "issues": [],
    "issue_labels": [],
    "recommendations": [],
    "summary": "No measurements available yet.",
    "metric_categories": {},
}

EMPTY_SESSION_PAYLOAD: Dict[str, Any] = {
    "session_id": "",
    "mode": MODE_DEMO,
    "status": SESSION_STATUS_IDLE,
    "started_at": "",
    "completed_at": "",
    "measurements": dict(EMPTY_MEASUREMENT_PAYLOAD),
    "diagnosis": dict(EMPTY_DIAGNOSIS_PAYLOAD),
    "report_path": "",
    "qr_path": "",
}


# ============================================================
# Friendly helper collections
# ============================================================

DETAIL_METRIC_KEYS = [
    METRIC_BMI,
    METRIC_TEMPERATURE,
    METRIC_SPO2,
    METRIC_PULSE,
    METRIC_RR,
]

CALIBRATABLE_SENSOR_KEYS = [
    METRIC_TEMPERATURE,
    METRIC_SPO2,
    METRIC_WEIGHT,
    METRIC_HEIGHT,
    METRIC_PULSE,
    METRIC_RR,
    METRIC_BMI,
]

SUMMARY_CARD_METRICS = [
    METRIC_BMI,
    METRIC_TEMPERATURE,
    METRIC_SPO2,
    METRIC_PULSE,
    METRIC_RR,
]

EXPORTABLE_FILE_TYPES = ["pdf", "json", "csv"]


# ============================================================
# Minor UI strings
# ============================================================

LABEL_BACK = "Back"
LABEL_LOGIN = "Login"
LABEL_LOGOUT = "Logout"
LABEL_CANCEL = "Cancel"
LABEL_UPDATE = "Update"
LABEL_SAVE = "Save Settings"
LABEL_RESET = "Reset Defaults"
LABEL_BACKUP = "Backup Data"
LABEL_CLEAR = "Clear Old Data"
LABEL_QR = "QR"
LABEL_CONSULT = "Consult"
LABEL_START_CHECKUP = "Start Check Up"
LABEL_ADMIN = "Admin"
LABEL_NETWORK_CONNECTED = "Connected"
LABEL_NETWORK_DISCONNECTED = "Disconnected"
LABEL_DEMO = "Demo"
LABEL_HARDWARE = "Hardware"
LABEL_MEASURING = "Measuring"
LABEL_PARAMETERS_NORMAL = "All parameters are normal"

TEXT_ADMIN_LOGIN_HINT = "Enter your credentials to continue"
TEXT_MEASUREMENT_INSTRUCTION = "Please stand still while the system collects your readings."
TEXT_RESULTS_HEADER = "Health Parameters"
TEXT_DIAGNOSIS_HEADER = "Diagnosis"
TEXT_QUICK_ACTIONS_HEADER = "Quick Actions"
TEXT_STORAGE_HEADER = "Storage Status"
TEXT_PUBLISH_HEADER = "Health Insights"
