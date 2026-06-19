"""
core/asset_paths.py

Central asset registry and lookup helpers for the CST Health Monitoring Station kiosk.

Purpose:
- Keep all asset file mappings in one place
- Prevent hard-coded asset filenames across widgets/screens/services
- Provide safe lookup helpers for backgrounds, icons, logos, illustrations, sounds, and detail graphics
- Gracefully handle missing assets during development
- Support both laptop demo mode and Raspberry Pi deployment

Important design notes:
- This module only deals with asset paths and asset key resolution
- UI styling is handled in theme_manager.py
- Runtime state is handled in app_state.py
- Business logic is handled in services/*
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# -----------------------------------------------------------------------------
# Safe config/path imports
# -----------------------------------------------------------------------------

try:
    from config import PATHS
except Exception:  # pragma: no cover
    class _FallbackPaths:
        base_dir = Path(__file__).resolve().parent.parent
        assets_dir = base_dir / "assets"
        backgrounds_dir = assets_dir / "backgrounds"
        logos_dir = assets_dir / "logos"
        illustrations_dir = assets_dir / "illustrations"
        icons_dir = assets_dir / "icons"
        detail_graphics_dir = assets_dir / "detail_graphics"
        sounds_dir = assets_dir / "sounds"
        fonts_dir = assets_dir / "fonts"

    PATHS = _FallbackPaths()  # type: ignore


# -----------------------------------------------------------------------------
# Safe constants imports
# -----------------------------------------------------------------------------

try:
    from core.constants import (
        ADMIN_PANEL_TILE_ICON_KEYS,
        BACKGROUND_KEYS,
        MAIN_ICON_KEYS,
        METRIC_ICON_KEYS,
        SENSOR_ICON_KEYS,
        SOUND_CLICK,
        SOUND_SUCCESS,
        SOUND_WARNING,
        SOUND_ERROR,
        SOUND_STARTUP,
        SOUND_COMPLETE,
        SOUND_SCAN,
        SOUND_LOGOUT,
        SOUND_TRANSITION,
    )
except Exception:  # pragma: no cover
    ADMIN_PANEL_TILE_ICON_KEYS = {
        "settings": "settings",
        "calibration": "calibrate",
        "parameters": "parameters",
        "diagnosis": "diagnosis",
        "storage": "storage",
        "publish": "publish",
        "logout": "logout",
    }

    BACKGROUND_KEYS = {
        "welcome": "welcome_bg",
        "mode_select": "mode_select_bg",
        "measuring": "measuring_bg",
        "results": "results_bg",
        "qr": "qr_bg",
        "consult": "consult_bg",
        "admin_login": "admin_login_bg",
        "admin_panel": "admin_panel_bg",
        "settings": "settings_bg",
        "calibration": "calibration_bg",
        "parameters": "parameters_bg",
        "diagnosis": "diagnosis_bg",
        "storage": "storage_bg",
        "publish": "publish_bg",
        "bmi_detail": "bmi_detail_bg",
        "temperature_detail": "temperature_detail_bg",
        "spo2_detail": "spo2_detail_bg",
        "pulse_detail": "pulse_detail_bg",
        "rr_detail": "rr_detail_bg",
    }

    MAIN_ICON_KEYS = {
        "start_checkup": "start_checkup",
        "admin": "admin",
        "back": "back",
        "login": "login",
        "logout": "logout",
        "qr": "qr",
        "consult": "consult",
        "settings": "settings",
        "calibration": "calibrate",
        "parameters": "parameters",
        "diagnosis": "diagnosis",
        "storage": "storage",
        "publish": "publish",
        "save": "save",
        "reset": "reset",
        "backup": "backup",
        "clear_data": "clear_data",
        "update": "update",
        "network": "network",
        "brightness": "brightness",
        "timeout": "timeout",
        "light_mode": "light_mode",
        "dark_mode": "dark_mode",
        "volume": "volume",
        "admin_lock": "admin_lock",
        "export": "export",
        "warning": "warning",
        "success": "success",
        "info": "info",
        "ambulance": "ambulance",
        "pdf": "pdf",
        "report": "report",
        "chart": "chart",
    }

    METRIC_ICON_KEYS = {
        "weight": "weight",
        "height": "height",
        "bmi": "bmi",
        "temperature": "temperature",
        "spo2": "spo2",
        "pulse": "pulse",
        "pulse_rate": "pulse",
        "heart_rate": "pulse",
        "respiratory_rate": "respiratory_rate",
        "rr": "respiratory_rate",
    }

    SENSOR_ICON_KEYS = {
        "temperature": "sensor_temp",
        "spo2": "sensor_spo2",
        "weight": "sensor_weight",
        "height": "sensor_height",
        "pulse": "sensor_pulse",
        "pulse_rate": "sensor_pulse",
    }

    SOUND_CLICK = "sound_click"
    SOUND_SUCCESS = "sound_success"
    SOUND_WARNING = "sound_warning"
    SOUND_ERROR = "sound_error"
    SOUND_STARTUP = "sound_startup"
    SOUND_COMPLETE = "sound_complete"
    SOUND_SCAN = "sound_scan"
    SOUND_LOGOUT = "sound_logout"
    SOUND_TRANSITION = "sound_transition"


# -----------------------------------------------------------------------------
# Asset filename registries
# -----------------------------------------------------------------------------

BACKGROUND_FILES: Dict[str, str] = {
    "welcome_bg": "welcome_bg.png",
    "mode_select_bg": "mode_select_bg.png",
    "measuring_bg": "measuring_bg.png",
    "results_bg": "results_bg.png",
    "qr_bg": "qr_bg.png",
    "consult_bg": "consult_bg.png",
    "admin_login_bg": "admin_login_bg.png",
    "admin_panel_bg": "admin_panel_bg.png",
    "settings_bg": "settings_bg.png",
    "calibration_bg": "calibration_bg.png",
    "parameters_bg": "parameters_bg.png",
    "diagnosis_bg": "diagnosis_bg.png",
    "storage_bg": "storage_bg.png",
    "publish_bg": "publish_bg.png",
    "bmi_detail_bg": "bmi_detail_bg.png",
    "temperature_detail_bg": "temperature_detail_bg.png",
    "spo2_detail_bg": "spo2_detail_bg.png",
    "pulse_detail_bg": "pulse_detail_bg.png",
    "rr_detail_bg": "rr_detail_bg.png",
}

LOGO_FILES: Dict[str, str] = {
    "cst_logo_main": "cst_logo_main.png",
    "cst_logo_glow": "cst_logo_glow.png",
    "cst_logo_small": "cst_logo_small.png",
    "cst_logo_white": "cst_logo_white.png",
}

ILLUSTRATION_FILES: Dict[str, str] = {
    "doctor_left": "doctor_left.png",
    "doctor_right": "doctor_right.png",
    "measuring_assistant": "measuring_assistant.png",
    "admin_shield": "admin_shield.png",
    "kiosk_machine": "kiosk_machine.png",
    "consult_panel_art": "consult_panel_art.png",
}

ICON_FILES: Dict[str, str] = {
    "start_checkup": "start_checkup.png",
    "admin": "admin.png",
    "back": "back.png",
    "login": "login.png",
    "logout": "logout.png",
    "qr": "qr.png",
    "consult": "consult.png",
    "connected": "connected.png",
    "disconnected": "disconnected.png",
    "serial_waiting": "serial_waiting.png",
    "demo_mode": "demo_mode.png",
    "hardware_mode": "hardware_mode.png",
    "settings": "settings.png",
    "calibrate": "calibrate.png",
    "parameters": "parameters.png",
    "diagnosis": "diagnosis.png",
    "storage": "storage.png",
    "publish": "publish.png",
    "save": "save.png",
    "reset": "reset.png",
    "backup": "backup.png",
    "clear_data": "clear_data.png",
    "update": "update.png",
    "network": "network.png",
    "brightness": "brightness.png",
    "timeout": "timeout.png",
    "light_mode": "light_mode.png",
    "dark_mode": "dark_mode.png",
    "volume": "volume.png",
    "admin_lock": "admin_lock.png",
    "export": "export.png",
    "warning": "warning.png",
    "success": "success.png",
    "info": "info.png",
    "ambulance": "ambulance.png",
    "pdf": "pdf.png",
    "report": "report.png",
    "chart": "chart.png",
    "pulse": "pulse.png",
    "spo2": "spo2.png",
    "temperature": "temperature.png",
    "weight": "weight.png",
    "height": "height.png",
    "bmi": "bmi.png",
    "respiratory_rate": "respiratory_rate.png",
    "sensor_temp": "sensor_temp.png",
    "sensor_spo2": "sensor_spo2.png",
    "sensor_weight": "sensor_weight.png",
    "sensor_height": "sensor_height.png",
    "sensor_pulse": "sensor_pulse.png",
}

DETAIL_GRAPHIC_FILES: Dict[str, str] = {
    "bmi_gauge": "bmi_gauge.png",
    "thermometer_scale": "thermometer_scale.png",
    "spo2_bands": "spo2_bands.png",
    "pulse_reference_chart": "pulse_reference_chart.png",
    "rr_reference_chart": "rr_reference_chart.png",
}

SOUND_FILES: Dict[str, str] = {
    SOUND_CLICK: "click.wav",
    SOUND_SUCCESS: "success.wav",
    SOUND_WARNING: "warning.wav",
    SOUND_ERROR: "error.wav",
    SOUND_STARTUP: "startup.wav",
    SOUND_COMPLETE: "complete.wav",
    SOUND_SCAN: "scan.wav",
    SOUND_LOGOUT: "logout.wav",
    SOUND_TRANSITION: "transition.wav",
}

FONT_FILES: Dict[str, str] = {
    "inter_regular": "Inter-Regular.ttf",
    "inter_bold": "Inter-Bold.ttf",
    "orbitron_semibold": "Orbitron-SemiBold.ttf",
}


# -----------------------------------------------------------------------------
# Aggregate registries by category
# -----------------------------------------------------------------------------

CATEGORY_TO_REGISTRY: Dict[str, Dict[str, str]] = {
    "backgrounds": BACKGROUND_FILES,
    "logos": LOGO_FILES,
    "illustrations": ILLUSTRATION_FILES,
    "icons": ICON_FILES,
    "detail_graphics": DETAIL_GRAPHIC_FILES,
    "sounds": SOUND_FILES,
    "fonts": FONT_FILES,
}

CATEGORY_TO_DIRECTORY: Dict[str, Path] = {
    "backgrounds": Path(PATHS.backgrounds_dir),
    "logos": Path(PATHS.logos_dir),
    "illustrations": Path(PATHS.illustrations_dir),
    "icons": Path(PATHS.icons_dir),
    "detail_graphics": Path(PATHS.detail_graphics_dir),
    "sounds": Path(PATHS.sounds_dir),
    "fonts": Path(PATHS.fonts_dir),
}


# -----------------------------------------------------------------------------
# Primary symbolic asset keys used across the app
# -----------------------------------------------------------------------------

DEFAULT_BACKGROUND_KEY = "welcome_bg"
DEFAULT_LOGO_KEY = "cst_logo_main"
DEFAULT_SMALL_LOGO_KEY = "cst_logo_small"
DEFAULT_WHITE_LOGO_KEY = "cst_logo_white"

DEFAULT_MEASURING_ILLUSTRATION_KEY = "measuring_assistant"
DEFAULT_LEFT_DOCTOR_ILLUSTRATION_KEY = "doctor_left"
DEFAULT_RIGHT_DOCTOR_ILLUSTRATION_KEY = "doctor_right"
DEFAULT_ADMIN_ILLUSTRATION_KEY = "admin_shield"

DEFAULT_ICON_KEY = "info"
DEFAULT_BACK_ICON_KEY = "back"
DEFAULT_SUCCESS_ICON_KEY = "success"
DEFAULT_WARNING_ICON_KEY = "warning"
DEFAULT_NETWORK_ICON_KEY = "network"
DEFAULT_CONNECTED_ICON_KEY = "connected"
DEFAULT_DISCONNECTED_ICON_KEY = "disconnected"
DEFAULT_WAITING_ICON_KEY = "serial_waiting"

DEFAULT_BMI_GAUGE_KEY = "bmi_gauge"
DEFAULT_THERMOMETER_SCALE_KEY = "thermometer_scale"
DEFAULT_SPO2_BANDS_KEY = "spo2_bands"
DEFAULT_PULSE_CHART_KEY = "pulse_reference_chart"
DEFAULT_RR_CHART_KEY = "rr_reference_chart"


# -----------------------------------------------------------------------------
# Dataclasses
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class AssetRecord:
    category: str
    key: str
    filename: str
    path: Path

    @property
    def exists(self) -> bool:
        return self.path.exists()

    @property
    def as_posix(self) -> str:
        return self.path.as_posix()

    @property
    def absolute(self) -> str:
        return str(self.path.resolve())


@dataclass(frozen=True)
class AssetSummary:
    total: int
    existing: int
    missing: int
    missing_items: Tuple[AssetRecord, ...]


# -----------------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------------

def _get_registry(category: str) -> Dict[str, str]:
    if category not in CATEGORY_TO_REGISTRY:
        raise KeyError(f"Unknown asset category: {category}")
    return CATEGORY_TO_REGISTRY[category]


def _get_directory(category: str) -> Path:
    if category not in CATEGORY_TO_DIRECTORY:
        raise KeyError(f"Unknown asset category directory: {category}")
    return CATEGORY_TO_DIRECTORY[category]


def _build_record(category: str, key: str) -> AssetRecord:
    registry = _get_registry(category)
    directory = _get_directory(category)

    if key not in registry:
        raise KeyError(f"Unknown asset key '{key}' for category '{category}'")

    filename = registry[key]
    path = directory / filename
    return AssetRecord(category=category, key=key, filename=filename, path=path)


def _safe_build_record(category: str, key: str, fallback_key: Optional[str] = None) -> AssetRecord:
    try:
        return _build_record(category, key)
    except KeyError:
        if fallback_key is None:
            raise
        return _build_record(category, fallback_key)


# -----------------------------------------------------------------------------
# Generic asset lookup functions
# -----------------------------------------------------------------------------

def get_asset_record(category: str, key: str, fallback_key: Optional[str] = None) -> AssetRecord:
    return _safe_build_record(category=category, key=key, fallback_key=fallback_key)


def get_asset_path(category: str, key: str, fallback_key: Optional[str] = None) -> Path:
    return get_asset_record(category=category, key=key, fallback_key=fallback_key).path


def get_asset_path_str(category: str, key: str, fallback_key: Optional[str] = None) -> str:
    return str(get_asset_path(category=category, key=key, fallback_key=fallback_key))


# Compatibility aliases used by other files
def resolve_asset_path(relative_path: str) -> str:
    """
    Resolve an asset from a relative path like:
    - backgrounds/welcome_bg.png
    - icons/settings.png
    - logos/cst_logo_small.png
    """
    clean = str(relative_path or "").strip().replace("\\", "/").lstrip("/")
    if not clean:
        return ""

    parts = clean.split("/")
    if len(parts) < 2:
        candidate = Path(PATHS.assets_dir) / clean
        return str(candidate)

    category = parts[0]
    filename = "/".join(parts[1:])
    return str(Path(PATHS.assets_dir) / category / filename)


def resolve_asset(relative_path: str) -> str:
    return resolve_asset_path(relative_path)


def asset_path(relative_path: str) -> str:
    return resolve_asset_path(relative_path)


def asset(relative_path: str) -> str:
    return resolve_asset_path(relative_path)


def asset_exists(category: str, key: str, fallback_key: Optional[str] = None) -> bool:
    return get_asset_record(category=category, key=key, fallback_key=fallback_key).exists


def list_asset_records(category: str) -> List[AssetRecord]:
    registry = _get_registry(category)
    return [_build_record(category, key) for key in registry.keys()]


def list_existing_asset_records(category: str) -> List[AssetRecord]:
    return [record for record in list_asset_records(category) if record.exists]


def list_missing_asset_records(category: str) -> List[AssetRecord]:
    return [record for record in list_asset_records(category) if not record.exists]


def summarize_assets(category: str) -> AssetSummary:
    records = list_asset_records(category)
    missing_items = tuple(record for record in records if not record.exists)
    total = len(records)
    missing = len(missing_items)
    existing = total - missing
    return AssetSummary(
        total=total,
        existing=existing,
        missing=missing,
        missing_items=missing_items,
    )


# -----------------------------------------------------------------------------
# Background helpers
# -----------------------------------------------------------------------------

def get_background_path(background_key: str, fallback_key: str = DEFAULT_BACKGROUND_KEY) -> Path:
    return get_asset_path("backgrounds", background_key, fallback_key=fallback_key)


def get_background_path_for_route(route_name: str, fallback_key: str = DEFAULT_BACKGROUND_KEY) -> Path:
    key = BACKGROUND_KEYS.get(route_name, fallback_key)
    return get_background_path(key, fallback_key=fallback_key)


def background_exists_for_route(route_name: str) -> bool:
    key = BACKGROUND_KEYS.get(route_name, DEFAULT_BACKGROUND_KEY)
    return asset_exists("backgrounds", key, fallback_key=DEFAULT_BACKGROUND_KEY)


# -----------------------------------------------------------------------------
# Logo helpers
# -----------------------------------------------------------------------------

def get_logo_path(logo_key: str = DEFAULT_LOGO_KEY) -> Path:
    return get_asset_path("logos", logo_key, fallback_key=DEFAULT_LOGO_KEY)


def get_main_logo_path() -> Path:
    return get_logo_path("cst_logo_main")


def get_glow_logo_path() -> Path:
    return get_logo_path("cst_logo_glow")


def get_small_logo_path() -> Path:
    return get_logo_path("cst_logo_small")


def get_white_logo_path() -> Path:
    return get_logo_path("cst_logo_white")


# -----------------------------------------------------------------------------
# Illustration helpers
# -----------------------------------------------------------------------------

def get_illustration_path(illustration_key: str, fallback_key: str = DEFAULT_MEASURING_ILLUSTRATION_KEY) -> Path:
    return get_asset_path("illustrations", illustration_key, fallback_key=fallback_key)


def get_left_doctor_illustration_path() -> Path:
    return get_illustration_path(DEFAULT_LEFT_DOCTOR_ILLUSTRATION_KEY, fallback_key="doctor_left")


def get_right_doctor_illustration_path() -> Path:
    return get_illustration_path(DEFAULT_RIGHT_DOCTOR_ILLUSTRATION_KEY, fallback_key="doctor_right")


def get_measuring_assistant_illustration_path() -> Path:
    return get_illustration_path(DEFAULT_MEASURING_ILLUSTRATION_KEY, fallback_key="measuring_assistant")


def get_admin_shield_illustration_path() -> Path:
    return get_illustration_path(DEFAULT_ADMIN_ILLUSTRATION_KEY, fallback_key="admin_shield")


def get_kiosk_machine_illustration_path() -> Path:
    return get_illustration_path("kiosk_machine", fallback_key="measuring_assistant")


def get_consult_panel_art_path() -> Path:
    return get_illustration_path("consult_panel_art", fallback_key="doctor_left")


# -----------------------------------------------------------------------------
# Icon helpers
# -----------------------------------------------------------------------------

def get_icon_path(icon_key: str, fallback_key: str = DEFAULT_ICON_KEY) -> Path:
    return get_asset_path("icons", icon_key, fallback_key=fallback_key)


def get_main_action_icon_path(action_key: str) -> Path:
    icon_key = MAIN_ICON_KEYS.get(action_key, DEFAULT_ICON_KEY)
    return get_icon_path(icon_key, fallback_key=DEFAULT_ICON_KEY)


def get_metric_icon_path(metric_key: str) -> Path:
    icon_key = METRIC_ICON_KEYS.get(metric_key, DEFAULT_ICON_KEY)
    return get_icon_path(icon_key, fallback_key=DEFAULT_ICON_KEY)


def get_sensor_icon_path(metric_key: str) -> Path:
    icon_key = SENSOR_ICON_KEYS.get(metric_key)
    if icon_key is None:
        return get_metric_icon_path(metric_key)
    return get_icon_path(icon_key, fallback_key=DEFAULT_ICON_KEY)


def get_admin_tile_icon_path(tile_key: str) -> Path:
    icon_key = ADMIN_PANEL_TILE_ICON_KEYS.get(tile_key, DEFAULT_ICON_KEY)
    return get_icon_path(icon_key, fallback_key=DEFAULT_ICON_KEY)


def get_connected_icon_path() -> Path:
    return get_icon_path("connected", fallback_key=DEFAULT_SUCCESS_ICON_KEY)


def get_disconnected_icon_path() -> Path:
    return get_icon_path("disconnected", fallback_key=DEFAULT_WARNING_ICON_KEY)


def get_serial_waiting_icon_path() -> Path:
    return get_icon_path("serial_waiting", fallback_key=DEFAULT_WAITING_ICON_KEY)


def get_demo_mode_icon_path() -> Path:
    return get_icon_path("demo_mode", fallback_key=DEFAULT_ICON_KEY)


def get_hardware_mode_icon_path() -> Path:
    return get_icon_path("hardware_mode", fallback_key=DEFAULT_ICON_KEY)


def get_back_icon_path() -> Path:
    return get_icon_path(DEFAULT_BACK_ICON_KEY, fallback_key=DEFAULT_ICON_KEY)


def get_warning_icon_path() -> Path:
    return get_icon_path("warning", fallback_key=DEFAULT_ICON_KEY)


def get_success_icon_path() -> Path:
    return get_icon_path("success", fallback_key=DEFAULT_ICON_KEY)


def get_info_icon_path() -> Path:
    return get_icon_path("info", fallback_key=DEFAULT_ICON_KEY)


def get_network_icon_path() -> Path:
    return get_icon_path("network", fallback_key=DEFAULT_ICON_KEY)


def get_pdf_icon_path() -> Path:
    return get_icon_path("pdf", fallback_key=DEFAULT_ICON_KEY)


def get_report_icon_path() -> Path:
    return get_icon_path("report", fallback_key=DEFAULT_ICON_KEY)


def get_chart_icon_path() -> Path:
    return get_icon_path("chart", fallback_key=DEFAULT_ICON_KEY)


def get_ambulance_icon_path() -> Path:
    return get_icon_path("ambulance", fallback_key=DEFAULT_WARNING_ICON_KEY)


# -----------------------------------------------------------------------------
# Detail graphic helpers
# -----------------------------------------------------------------------------

def get_detail_graphic_path(graphic_key: str, fallback_key: str = DEFAULT_BMI_GAUGE_KEY) -> Path:
    return get_asset_path("detail_graphics", graphic_key, fallback_key=fallback_key)


def get_bmi_gauge_path() -> Path:
    return get_detail_graphic_path("bmi_gauge", fallback_key=DEFAULT_BMI_GAUGE_KEY)


def get_thermometer_scale_path() -> Path:
    return get_detail_graphic_path("thermometer_scale", fallback_key=DEFAULT_THERMOMETER_SCALE_KEY)


def get_spo2_bands_path() -> Path:
    return get_detail_graphic_path("spo2_bands", fallback_key=DEFAULT_SPO2_BANDS_KEY)


def get_pulse_reference_chart_path() -> Path:
    return get_detail_graphic_path("pulse_reference_chart", fallback_key=DEFAULT_PULSE_CHART_KEY)


def get_rr_reference_chart_path() -> Path:
    return get_detail_graphic_path("rr_reference_chart", fallback_key=DEFAULT_RR_CHART_KEY)


# -----------------------------------------------------------------------------
# Sound helpers
# -----------------------------------------------------------------------------

def get_sound_path(sound_key: str, fallback_key: str = SOUND_CLICK) -> Path:
    return get_asset_path("sounds", sound_key, fallback_key=fallback_key)


def get_click_sound_path() -> Path:
    return get_sound_path(SOUND_CLICK, fallback_key=SOUND_CLICK)


def get_success_sound_path() -> Path:
    return get_sound_path(SOUND_SUCCESS, fallback_key=SOUND_CLICK)


def get_warning_sound_path() -> Path:
    return get_sound_path(SOUND_WARNING, fallback_key=SOUND_CLICK)


def get_error_sound_path() -> Path:
    return get_sound_path(SOUND_ERROR, fallback_key=SOUND_CLICK)


def get_startup_sound_path() -> Path:
    return get_sound_path(SOUND_STARTUP, fallback_key=SOUND_CLICK)


def get_complete_sound_path() -> Path:
    return get_sound_path(SOUND_COMPLETE, fallback_key=SOUND_CLICK)


def get_scan_sound_path() -> Path:
    return get_sound_path(SOUND_SCAN, fallback_key=SOUND_CLICK)


def get_logout_sound_path() -> Path:
    return get_sound_path(SOUND_LOGOUT, fallback_key=SOUND_CLICK)


def get_transition_sound_path() -> Path:
    return get_sound_path(SOUND_TRANSITION, fallback_key=SOUND_CLICK)


# -----------------------------------------------------------------------------
# Font helpers
# -----------------------------------------------------------------------------

def get_font_path(font_key: str, fallback_key: str = "inter_regular") -> Path:
    return get_asset_path("fonts", font_key, fallback_key=fallback_key)


def get_inter_regular_font_path() -> Path:
    return get_font_path("inter_regular", fallback_key="inter_regular")


def get_inter_bold_font_path() -> Path:
    return get_font_path("inter_bold", fallback_key="inter_regular")


def get_orbitron_semibold_font_path() -> Path:
    return get_font_path("orbitron_semibold", fallback_key="inter_bold")


# -----------------------------------------------------------------------------
# PyQt-friendly safe helpers
# -----------------------------------------------------------------------------

def safe_background_path_for_route(route_name: str) -> str:
    path = get_background_path_for_route(route_name)
    return str(path) if path.exists() else ""


def safe_icon_path(icon_key: str) -> str:
    path = get_icon_path(icon_key, fallback_key=DEFAULT_ICON_KEY)
    return str(path) if path.exists() else ""


def safe_logo_path(logo_key: str = DEFAULT_LOGO_KEY) -> str:
    path = get_logo_path(logo_key)
    return str(path) if path.exists() else ""


def safe_illustration_path(illustration_key: str) -> str:
    path = get_illustration_path(illustration_key)
    return str(path) if path.exists() else ""


def safe_detail_graphic_path(graphic_key: str) -> str:
    path = get_detail_graphic_path(graphic_key)
    return str(path) if path.exists() else ""


def safe_sound_path(sound_key: str) -> str:
    path = get_sound_path(sound_key)
    return str(path) if path.exists() else ""


# -----------------------------------------------------------------------------
# Asset validation and diagnostics
# -----------------------------------------------------------------------------

def validate_category(category: str) -> AssetSummary:
    return summarize_assets(category)


def validate_all_assets() -> Dict[str, AssetSummary]:
    return {category: summarize_assets(category) for category in CATEGORY_TO_REGISTRY.keys()}


def get_missing_assets() -> List[AssetRecord]:
    missing: List[AssetRecord] = []
    for category in CATEGORY_TO_REGISTRY.keys():
        missing.extend(list_missing_asset_records(category))
    return missing


def get_existing_assets() -> List[AssetRecord]:
    existing: List[AssetRecord] = []
    for category in CATEGORY_TO_REGISTRY.keys():
        existing.extend(list_existing_asset_records(category))
    return existing


def has_minimum_required_assets() -> bool:
    required_checks = [
        get_main_logo_path().exists(),
        get_background_path("welcome_bg").exists(),
        get_background_path("mode_select_bg").exists(),
        get_background_path("measuring_bg").exists(),
        get_background_path("results_bg").exists(),
        get_background_path("admin_login_bg").exists(),
        get_background_path("admin_panel_bg").exists(),
        get_icon_path("back").exists(),
        get_icon_path("start_checkup").exists(),
        get_icon_path("admin").exists(),
    ]
    return all(required_checks)


def asset_debug_dump() -> Dict[str, Dict[str, object]]:
    dump: Dict[str, Dict[str, object]] = {}
    for category in CATEGORY_TO_REGISTRY.keys():
        summary = summarize_assets(category)
        dump[category] = {
            "directory": str(_get_directory(category)),
            "total": summary.total,
            "existing": summary.existing,
            "missing": summary.missing,
            "missing_keys": [item.key for item in summary.missing_items],
            "missing_files": [item.filename for item in summary.missing_items],
        }
    return dump


# -----------------------------------------------------------------------------
# Static collections for iteration in later modules
# -----------------------------------------------------------------------------

ALL_BACKGROUND_KEYS = tuple(BACKGROUND_FILES.keys())
ALL_LOGO_KEYS = tuple(LOGO_FILES.keys())
ALL_ILLUSTRATION_KEYS = tuple(ILLUSTRATION_FILES.keys())
ALL_ICON_KEYS = tuple(ICON_FILES.keys())
ALL_DETAIL_GRAPHIC_KEYS = tuple(DETAIL_GRAPHIC_FILES.keys())
ALL_SOUND_KEYS = tuple(SOUND_FILES.keys())
ALL_FONT_KEYS = tuple(FONT_FILES.keys())

ALL_ASSET_CATEGORIES = tuple(CATEGORY_TO_REGISTRY.keys())


# -----------------------------------------------------------------------------
# Convenience top-level registry for quick lookups
# -----------------------------------------------------------------------------

ALL_ASSET_FILES = {
    "backgrounds": BACKGROUND_FILES,
    "logos": LOGO_FILES,
    "illustrations": ILLUSTRATION_FILES,
    "icons": ICON_FILES,
    "detail_graphics": DETAIL_GRAPHIC_FILES,
    "sounds": SOUND_FILES,
    "fonts": FONT_FILES,
}


# -----------------------------------------------------------------------------
# Optional startup self-check
# -----------------------------------------------------------------------------

def ensure_asset_directories_exist() -> None:
    for directory in CATEGORY_TO_DIRECTORY.values():
        directory.mkdir(parents=True, exist_ok=True)


ensure_asset_directories_exist()