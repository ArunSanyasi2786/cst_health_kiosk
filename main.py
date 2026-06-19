"""
main.py

Application bootstrap and runtime composition root for the
CST Health Monitoring Station kiosk.

Purpose of this file
--------------------
This is the main entry point that ties the whole kiosk together.

It is responsible for:
- creating the QApplication
- loading fonts and global styling
- initializing app state, theme, animation, and optional idle handling
- constructing and wiring all services
- constructing and registering all 19 screens
- coordinating navigation through a QStackedWidget
- handling demo mode and hardware mode routing
- moving the user through the primary flow:
    welcome -> mode select -> measuring -> results -> details / qr / consult
- moving the administrator through the protected flow:
    admin login -> admin panel -> settings / calibration / parameters / diagnosis / storage / publish
- preserving resilience while the project is still being built module by module

This file is deliberately defensive:
- if a screen class is missing, a placeholder screen is shown instead of crashing
- if a service class is missing, the rest of the app still boots
- constructor signatures are matched dynamically so files can evolve independently
- signal names are connected using best-effort multi-name matching
- session payloads can be sourced from services or app_state
- demo payloads can be seeded to keep the UI fully usable in demo mode

Target environment
------------------
- Raspberry Pi 4B touchscreen kiosk
- 1024x600 primary target resolution
- laptop demo mode supported

Project architecture assumptions
--------------------------------
Expected folders:
- core/
- services/
- screens/
- widgets/
- assets/
- data/

Expected public screens:
- welcome
- mode_select
- measuring
- results
- qr
- consult
- admin_login
- admin_panel
- settings
- calibration
- parameters
- diagnosis
- storage
- publish
- bmi_detail
- temperature_detail
- spo2_detail
- pulse_detail
- rr_detail

Expected services:
- database_service
- settings_service
- calibration_service
- threshold_service
- mode_service
- session_service
- health_rules_service
- diagnosis_service
- storage_service
- export_service
- report_service
- qr_service
- connection_service
- serial_service
- sensor_service
- publish_service
"""

from __future__ import annotations

import inspect
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple, Type, List

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QFontDatabase, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

# -----------------------------------------------------------------------------
# Optional imports from project files
# -----------------------------------------------------------------------------

try:
    import config as project_config
except Exception:  # pragma: no cover
    project_config = None  # type: ignore

try:
    from core.logger import get_logger
except Exception:  # pragma: no cover
    import logging

    def get_logger(name: str):
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        )
        return logging.getLogger(name)

try:
    from core.utils import safe_bool, safe_float, safe_int, safe_str
except Exception:  # pragma: no cover
    def safe_str(value: Any, default: str = "") -> str:
        try:
            if value is None:
                return default
            return str(value)
        except Exception:
            return default

    def safe_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None or value == "":
                return default
            return float(value)
        except Exception:
            return default

    def safe_int(value: Any, default: int = 0) -> int:
        try:
            if value is None or value == "":
                return default
            return int(float(value))
        except Exception:
            return default

    def safe_bool(value: Any, default: bool = False) -> bool:
        try:
            if isinstance(value, bool):
                return value
            if value is None:
                return default
            text = str(value).strip().lower()
            if text in {"1", "true", "yes", "y", "on"}:
                return True
            if text in {"0", "false", "no", "n", "off"}:
                return False
            return default
        except Exception:
            return default

try:
    from core.app_state import AppState
except Exception:  # pragma: no cover
    AppState = None  # type: ignore

try:
    from core.theme_manager import ThemeManager
except Exception:  # pragma: no cover
    ThemeManager = None  # type: ignore

try:
    from core.animation_manager import AnimationManager
except Exception:  # pragma: no cover
    AnimationManager = None  # type: ignore

try:
    from core.idle_manager import IdleManager
except Exception:  # pragma: no cover
    IdleManager = None  # type: ignore

# -----------------------------------------------------------------------------
# Constants and fallbacks
# -----------------------------------------------------------------------------

APP_NAME = getattr(project_config, "APP_NAME", "CST Health Monitoring Station") if project_config else "CST Health Monitoring Station"
APP_ORG = getattr(project_config, "APP_ORGANIZATION", "CST") if project_config else "CST"
APP_VERSION = getattr(project_config, "APP_VERSION", "1.0.0") if project_config else "1.0.0"

DEFAULT_WIDTH = int(getattr(project_config, "WINDOW_WIDTH", 1024)) if project_config else 1024
DEFAULT_HEIGHT = int(getattr(project_config, "WINDOW_HEIGHT", 600)) if project_config else 600
DEFAULT_FULLSCREEN = bool(getattr(project_config, "FULLSCREEN", False)) if project_config else False
DEFAULT_START_FULLSCREEN_ON_PI = bool(getattr(project_config, "FULLSCREEN_ON_RPI", True)) if project_config else True
DEFAULT_DEMO_ON_BOOT = bool(getattr(project_config, "DEMO_MODE_ON_BOOT", False)) if project_config else False

BASE_DIR = Path(getattr(project_config, "BASE_DIR", Path(__file__).resolve().parent)) if project_config else Path(__file__).resolve().parent
ASSETS_DIR = Path(getattr(project_config, "ASSETS_DIR", BASE_DIR / "assets")) if project_config else BASE_DIR / "assets"

# Screen names
SCREEN_WELCOME = getattr(project_config, "SCREEN_WELCOME", "welcome") if project_config else "welcome"
SCREEN_MODE_SELECT = getattr(project_config, "SCREEN_MODE_SELECT", "mode_select") if project_config else "mode_select"
SCREEN_MEASURING = getattr(project_config, "SCREEN_MEASURING", "measuring") if project_config else "measuring"
SCREEN_RESULTS = getattr(project_config, "SCREEN_RESULTS", "results") if project_config else "results"
SCREEN_RESULTS_DIAGNOSIS = getattr(project_config, "SCREEN_RESULTS_DIAGNOSIS", "results_diagnosis") if project_config else "results_diagnosis"
SCREEN_QR = getattr(project_config, "SCREEN_QR", "qr") if project_config else "qr"
SCREEN_CONSULT = getattr(project_config, "SCREEN_CONSULT", "consult") if project_config else "consult"
SCREEN_ADMIN_LOGIN = getattr(project_config, "SCREEN_ADMIN_LOGIN", "admin_login") if project_config else "admin_login"
SCREEN_ADMIN_PANEL = getattr(project_config, "SCREEN_ADMIN_PANEL", "admin_panel") if project_config else "admin_panel"
SCREEN_SETTINGS = getattr(project_config, "SCREEN_SETTINGS", "settings") if project_config else "settings"
SCREEN_CALIBRATION = getattr(project_config, "SCREEN_CALIBRATION", "calibration") if project_config else "calibration"
SCREEN_PARAMETERS = getattr(project_config, "SCREEN_PARAMETERS", "parameters") if project_config else "parameters"
SCREEN_DIAGNOSIS = getattr(project_config, "SCREEN_DIAGNOSIS", "diagnosis") if project_config else "diagnosis"
SCREEN_STORAGE = getattr(project_config, "SCREEN_STORAGE", "storage") if project_config else "storage"
SCREEN_PUBLISH = getattr(project_config, "SCREEN_PUBLISH", "publish") if project_config else "publish"
SCREEN_BMI_DETAIL = getattr(project_config, "SCREEN_BMI_DETAIL", "bmi_detail") if project_config else "bmi_detail"
SCREEN_TEMPERATURE_DETAIL = getattr(project_config, "SCREEN_TEMPERATURE_DETAIL", "temperature_detail") if project_config else "temperature_detail"
SCREEN_SPO2_DETAIL = getattr(project_config, "SCREEN_SPO2_DETAIL", "spo2_detail") if project_config else "spo2_detail"
SCREEN_PULSE_DETAIL = getattr(project_config, "SCREEN_PULSE_DETAIL", "pulse_detail") if project_config else "pulse_detail"
SCREEN_RR_DETAIL = getattr(project_config, "SCREEN_RR_DETAIL", "rr_detail") if project_config else "rr_detail"

# Metric keys
METRIC_BMI = getattr(project_config, "METRIC_BMI", "bmi") if project_config else "bmi"
METRIC_TEMPERATURE = getattr(project_config, "METRIC_TEMPERATURE", "temperature") if project_config else "temperature"
METRIC_SPO2 = getattr(project_config, "METRIC_SPO2", "spo2") if project_config else "spo2"
METRIC_PULSE = getattr(project_config, "METRIC_PULSE", "pulse_rate") if project_config else "pulse_rate"
METRIC_RESPIRATORY_RATE = getattr(project_config, "METRIC_RESPIRATORY_RATE", "respiratory_rate") if project_config else "respiratory_rate"
METRIC_WEIGHT = getattr(project_config, "METRIC_WEIGHT", "weight") if project_config else "weight"
METRIC_HEIGHT = getattr(project_config, "METRIC_HEIGHT", "height") if project_config else "height"

logger = get_logger(__name__)

# -----------------------------------------------------------------------------
# Helper data
# -----------------------------------------------------------------------------

@dataclass
class RuntimeConfig:
    app_name: str = APP_NAME
    app_org: str = APP_ORG
    app_version: str = APP_VERSION
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    fullscreen: bool = DEFAULT_FULLSCREEN
    fullscreen_on_pi: bool = DEFAULT_START_FULLSCREEN_ON_PI
    demo_on_boot: bool = DEFAULT_DEMO_ON_BOOT
    assets_dir: Path = ASSETS_DIR
    base_dir: Path = BASE_DIR
    app_icon_path: str = ""
    fonts_dir: Path = field(default_factory=lambda: ASSETS_DIR / "fonts")
    small_logo_path: str = ""
    theme_mode: str = "dark"
    kiosk_title: str = APP_NAME


@dataclass
class ScreenSpec:
    name: str
    module_path: str
    class_name: str
    title: str
    description: str


@dataclass
class ServiceSpec:
    key: str
    module_path: str
    class_names: Tuple[str, ...]
    aliases: Tuple[str, ...] = ()


# -----------------------------------------------------------------------------
# Import helpers
# -----------------------------------------------------------------------------

def _import_symbol(module_path: str, symbol_name: str) -> Optional[Any]:
    try:
        module = __import__(module_path, fromlist=[symbol_name])
    except Exception as exc:
        logger.exception("Failed importing module %s: %s", module_path, exc)
        return None

    obj = getattr(module, symbol_name, None)
    if obj is None:
        logger.warning("Symbol %s not found in module %s", symbol_name, module_path)
        return None

    return obj


def _import_service_class(module_path: str, preferred_names: Sequence[str]) -> Optional[type]:
    """
    Import a service class from a module using:
    1. exact preferred class names
    2. fallback detection of any public class ending with 'Service'
    """
    try:
        module = __import__(module_path, fromlist=["*"])
    except Exception:
        return None

    for name in preferred_names:
        obj = getattr(module, name, None)
        if isinstance(obj, type):
            return obj

    candidates: List[Tuple[str, type]] = []
    for name, obj in vars(module).items():
        if (
            isinstance(obj, type)
            and getattr(obj, "__module__", "") == module.__name__
            and not name.startswith("_")
            and name.lower().endswith("service")
        ):
            candidates.append((name, obj))

    if not candidates:
        return None

    if len(candidates) == 1:
        return candidates[0][1]

    preferred_keys = [name.lower().replace("_", "") for name in preferred_names]
    for name, obj in candidates:
        key = name.lower().replace("_", "")
        if any(pref in key or key in pref for pref in preferred_keys):
            return obj

    return candidates[0][1]


def _asset(relative_path: str) -> str:
    clean = safe_str(relative_path, "").replace("\\", "/").lstrip("/")
    if not clean:
        return ""

    try:
        import core.asset_paths as asset_paths  # local import on purpose

        # IMPORTANT FIX:
        # core.asset_paths.get_asset_path expects (category, key), not one relative path string.
        # So for one-string relative paths like "logos/cst_logo_small.png", use only the
        # helpers that actually accept a single relative path.
        for name in ("asset_path", "resolve_asset_path", "resolve_asset", "asset"):
            resolver = getattr(asset_paths, name, None)
            if callable(resolver):
                try:
                    value = resolver(clean)
                    text = safe_str(value, "").strip()
                    if text:
                        return text
                except Exception:
                    continue
    except Exception:
        pass

    return str(ASSETS_DIR.joinpath(*clean.split("/")))


def _is_raspberry_pi() -> bool:
    try:
        if sys.platform.startswith("linux"):
            cpuinfo = Path("/proc/cpuinfo")
            if cpuinfo.exists():
                text = cpuinfo.read_text(encoding="utf-8", errors="ignore").lower()
                return "raspberry pi" in text or "bcm270" in text or "bcm271" in text
    except Exception:
        pass
    return False


def _load_runtime_config() -> RuntimeConfig:
    cfg = RuntimeConfig()

    if project_config is not None:
        cfg.app_name = safe_str(getattr(project_config, "APP_NAME", cfg.app_name), cfg.app_name)
        cfg.app_org = safe_str(getattr(project_config, "APP_ORGANIZATION", cfg.app_org), cfg.app_org)
        cfg.app_version = safe_str(getattr(project_config, "APP_VERSION", cfg.app_version), cfg.app_version)
        cfg.width = safe_int(getattr(project_config, "WINDOW_WIDTH", cfg.width), cfg.width)
        cfg.height = safe_int(getattr(project_config, "WINDOW_HEIGHT", cfg.height), cfg.height)
        cfg.fullscreen = safe_bool(getattr(project_config, "FULLSCREEN", cfg.fullscreen), cfg.fullscreen)
        cfg.fullscreen_on_pi = safe_bool(getattr(project_config, "FULLSCREEN_ON_RPI", cfg.fullscreen_on_pi), cfg.fullscreen_on_pi)
        cfg.demo_on_boot = safe_bool(getattr(project_config, "DEMO_MODE_ON_BOOT", cfg.demo_on_boot), cfg.demo_on_boot)
        cfg.theme_mode = safe_str(getattr(project_config, "DEFAULT_THEME_MODE", cfg.theme_mode), cfg.theme_mode)
        cfg.kiosk_title = safe_str(getattr(project_config, "KIOSK_TITLE", cfg.kiosk_title), cfg.kiosk_title)
        cfg.base_dir = Path(getattr(project_config, "BASE_DIR", cfg.base_dir))
        cfg.assets_dir = Path(getattr(project_config, "ASSETS_DIR", cfg.assets_dir))
        cfg.fonts_dir = Path(getattr(project_config, "FONTS_DIR", cfg.assets_dir / "fonts"))

    cfg.small_logo_path = _asset("logos/cst_logo_small.png")
    cfg.app_icon_path = _asset("logos/cst_logo_main.png")
    return cfg


def _register_fonts(font_dir: Path) -> None:
    if not font_dir.exists():
        return

    for font_path in font_dir.glob("*.ttf"):
        try:
            QFontDatabase.addApplicationFont(str(font_path))
        except Exception:
            continue


def _filtered_kwargs_for_callable(callable_obj: Callable[..., Any], kwargs: Mapping[str, Any]) -> Dict[str, Any]:
    try:
        sig = inspect.signature(callable_obj)
        params = sig.parameters.values()
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params):
            return dict(kwargs)
        accepted = {
            p.name for p in params
            if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        }
        return {k: v for k, v in kwargs.items() if k in accepted}
    except Exception:
        return dict(kwargs)


def _construct_flexible(cls: Type[Any], **kwargs: Any) -> Any:
    try:
        filtered = _filtered_kwargs_for_callable(cls.__init__, kwargs)
        return cls(**filtered)
    except TypeError:
        pass
    except Exception:
        pass

    try:
        return cls(**kwargs)
    except Exception:
        pass

    common_patterns = [
        {},
        {"parent": kwargs.get("parent")},
        {"app_state": kwargs.get("app_state")},
        {"navigator": kwargs.get("navigator")},
        {"services": kwargs.get("services")},
        {
            "parent": kwargs.get("parent"),
            "navigator": kwargs.get("navigator"),
            "app_state": kwargs.get("app_state"),
            "services": kwargs.get("services"),
        },
        {
            "parent": kwargs.get("parent"),
            "navigator": kwargs.get("navigator"),
            "app_state": kwargs.get("app_state"),
        },
        {"parent": kwargs.get("parent"), "services": kwargs.get("services")},
    ]

    for pattern in common_patterns:
        try:
            pattern = {k: v for k, v in pattern.items() if v is not None}
            return cls(**pattern)
        except Exception:
            continue

    return cls()


def _call_first_available(obj: Any, method_names: Sequence[str], *args: Any, **kwargs: Any) -> Any:
    if obj is None:
        return None

    for method_name in method_names:
        method = getattr(obj, method_name, None)
        if callable(method):
            try:
                filtered_kwargs = _filtered_kwargs_for_callable(method, kwargs)
                return method(*args, **filtered_kwargs)
            except TypeError:
                try:
                    return method(*args)
                except Exception:
                    continue
            except Exception:
                continue
    return None


def _connect_first_signal(obj: Any, signal_names: Sequence[str], slot: Callable[..., Any]) -> bool:
    if obj is None:
        return False

    for signal_name in signal_names:
        signal_obj = getattr(obj, signal_name, None)
        if signal_obj is not None and hasattr(signal_obj, "connect"):
            try:
                signal_obj.connect(slot)
                return True
            except Exception:
                continue
    return False


def _get_first_mapping_arg(*args: Any) -> Dict[str, Any]:
    for arg in args:
        if isinstance(arg, Mapping):
            return dict(arg)
    return {}


def _normalize_metric_key(metric: str) -> str:
    text = safe_str(metric, "").strip().lower().replace(" ", "_")
    mapping = {
        "bmi": SCREEN_BMI_DETAIL,
        "body_mass_index": SCREEN_BMI_DETAIL,
        "temperature": SCREEN_TEMPERATURE_DETAIL,
        "temp": SCREEN_TEMPERATURE_DETAIL,
        "body_temperature": SCREEN_TEMPERATURE_DETAIL,
        "spo2": SCREEN_SPO2_DETAIL,
        "oxygen_saturation": SCREEN_SPO2_DETAIL,
        "pulse": SCREEN_PULSE_DETAIL,
        "pulse_rate": SCREEN_PULSE_DETAIL,
        "heart_rate": SCREEN_PULSE_DETAIL,
        "bpm": SCREEN_PULSE_DETAIL,
        "respiratory_rate": SCREEN_RR_DETAIL,
        "rr": SCREEN_RR_DETAIL,
        "resp_rate": SCREEN_RR_DETAIL,
        "breaths_per_minute": SCREEN_RR_DETAIL,
    }
    return mapping.get(text, "")


# -----------------------------------------------------------------------------
# Local navigator
# -----------------------------------------------------------------------------

class LocalNavigator:
    def __init__(self, stacked_widget: QStackedWidget, on_navigate: Optional[Callable[[str, QWidget], None]] = None) -> None:
        self._stack = stacked_widget
        self._on_navigate = on_navigate
        self._index_by_name: Dict[str, int] = {}
        self._widget_by_name: Dict[str, QWidget] = {}
        self._current_name: str = ""

    def register_screen(self, name: str, widget: QWidget) -> None:
        screen_name = safe_str(name, "").strip()
        if not screen_name:
            raise ValueError("Screen name cannot be empty.")

        if screen_name in self._widget_by_name:
            return

        index = self._stack.addWidget(widget)
        self._index_by_name[screen_name] = index
        self._widget_by_name[screen_name] = widget

    def go_to(self, name: str) -> bool:
        screen_name = safe_str(name, "").strip()
        if screen_name not in self._index_by_name:
            return False

        index = self._index_by_name[screen_name]
        self._stack.setCurrentIndex(index)
        self._current_name = screen_name
        widget = self._widget_by_name[screen_name]

        if callable(self._on_navigate):
            try:
                self._on_navigate(screen_name, widget)
            except Exception:
                pass

        return True

    navigate_to = go_to
    navigate = go_to
    show_screen = go_to
    set_current_screen = go_to

    def contains(self, name: str) -> bool:
        return safe_str(name, "").strip() in self._widget_by_name

    def current_name(self) -> str:
        return self._current_name

    def current_widget(self) -> Optional[QWidget]:
        return self._widget_by_name.get(self._current_name)

    def screen(self, name: str) -> Optional[QWidget]:
        return self._widget_by_name.get(safe_str(name, "").strip())

    def names(self) -> Tuple[str, ...]:
        return tuple(self._widget_by_name.keys())


# -----------------------------------------------------------------------------
# Placeholder screen
# -----------------------------------------------------------------------------

class PlaceholderScreen(QFrame):
    back_requested = pyqtSignal()

    def __init__(self, title: str, description: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("PlaceholderScreen")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 28)
        root.setSpacing(12)

        title_label = QLabel(title, self)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet(
            """
            QLabel {
                color: #F6FCFF;
                font-size: 28px;
                font-weight: 900;
                background: transparent;
            }
            """
        )

        desc_label = QLabel(description, self)
        desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet(
            """
            QLabel {
                color: rgba(220, 236, 246, 0.88);
                font-size: 13px;
                font-weight: 500;
                background: transparent;
            }
            """
        )

        back_button = QPushButton("Back", self)
        back_button.setMinimumWidth(160)
        back_button.setMinimumHeight(42)
        back_button.clicked.connect(self.back_requested.emit)
        back_button.setStyleSheet(
            """
            QPushButton {
                color: #F6FCFF;
                border: 1px solid rgba(157, 220, 255, 0.30);
                border-radius: 14px;
                padding: 10px 16px;
                font-size: 12px;
                font-weight: 700;
                background: rgba(22, 47, 82, 0.78);
            }
            QPushButton:hover {
                background: rgba(34, 66, 110, 0.92);
            }
            """
        )

        btn_wrap = QWidget(self)
        btn_layout = QHBoxLayout(btn_wrap)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.addStretch(1)
        btn_layout.addWidget(back_button)
        btn_layout.addStretch(1)

        root.addStretch(1)
        root.addWidget(title_label)
        root.addWidget(desc_label)
        root.addWidget(btn_wrap)
        root.addStretch(1)

        self.setStyleSheet(
            """
            QFrame#PlaceholderScreen {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(10, 24, 42, 0.98),
                    stop:1 rgba(6, 16, 30, 0.98)
                );
            }
            """
        )


# -----------------------------------------------------------------------------
# Main window
# -----------------------------------------------------------------------------

class KioskMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.log = logger
        self.runtime_config = _load_runtime_config()

        self.app_state: Any = None
        self.theme_manager: Any = None
        self.animation_manager: Any = None
        self.idle_manager: Any = None

        self.services: Dict[str, Any] = {}
        self.screens: Dict[str, QWidget] = {}

        self.central = QWidget(self)
        self.central.setObjectName("AppShell")
        self.root_layout = QVBoxLayout(self.central)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)

        self.stacked_widget = QStackedWidget(self.central)
        self.stacked_widget.setObjectName("AppStack")
        self.root_layout.addWidget(self.stacked_widget, 1)

        self.navigator = LocalNavigator(self.stacked_widget, on_navigate=self._on_navigated)

        self.setCentralWidget(self.central)
        self.setWindowTitle(self.runtime_config.app_name)

        if self.runtime_config.app_icon_path and Path(self.runtime_config.app_icon_path).exists():
            try:
                self.setWindowIcon(QIcon(self.runtime_config.app_icon_path))
            except Exception:
                pass

        self._init_runtime_objects()
        self._apply_global_styles()
        self._configure_window()
        self._build_services()
        self._build_screens()
        self._wire_navigation()

        QTimer.singleShot(0, self._post_bootstrap)

    # -------------------------------------------------------------------------
    # Runtime bootstrap
    # -------------------------------------------------------------------------

    def _init_runtime_objects(self) -> None:
        shared = {
            "config": self.runtime_config,
            "runtime_config": self.runtime_config,
            "parent": self,
        }

        if AppState is not None:
            try:
                self.app_state = _construct_flexible(AppState, **shared)
            except Exception:
                self.app_state = None

        if self.app_state is None:
            class _FallbackState:
                pass
            self.app_state = _FallbackState()

        setattr(self.app_state, "app_name", self.runtime_config.app_name)
        setattr(self.app_state, "runtime_config", self.runtime_config)

        if ThemeManager is not None:
            try:
                self.theme_manager = _construct_flexible(
                    ThemeManager,
                    parent=self,
                    app_state=self.app_state,
                    config=self.runtime_config,
                    runtime_config=self.runtime_config,
                )
            except Exception:
                self.theme_manager = None

        if AnimationManager is not None:
            try:
                self.animation_manager = _construct_flexible(
                    AnimationManager,
                    parent=self,
                    app_state=self.app_state,
                    config=self.runtime_config,
                    runtime_config=self.runtime_config,
                )
            except Exception:
                self.animation_manager = None

        if IdleManager is not None:
            try:
                self.idle_manager = _construct_flexible(
                    IdleManager,
                    parent=self,
                    app_state=self.app_state,
                    navigator=self.navigator,
                    config=self.runtime_config,
                    runtime_config=self.runtime_config,
                )
            except Exception:
                self.idle_manager = None

        setattr(self.app_state, "navigator", self.navigator)
        setattr(self.app_state, "theme_manager", self.theme_manager)
        setattr(self.app_state, "animation_manager", self.animation_manager)

    def _apply_global_styles(self) -> None:
        self.central.setStyleSheet(
            """
            QWidget#AppShell {
                background: #071420;
            }
            QStackedWidget#AppStack {
                background: transparent;
            }
            """
        )

    def _configure_window(self) -> None:
        self.resize(self.runtime_config.width, self.runtime_config.height)
        self.setMinimumSize(self.runtime_config.width, self.runtime_config.height)

        if _is_raspberry_pi() and self.runtime_config.fullscreen_on_pi:
            self.showFullScreen()
        elif self.runtime_config.fullscreen:
            self.showFullScreen()
        else:
            self.setFixedSize(self.runtime_config.width, self.runtime_config.height)

    def _post_bootstrap(self) -> None:
        self._run_service_startup_hooks()
        self._apply_saved_theme_preferences()
        self._restore_mode_and_seed_if_needed()

        if not self.navigator.go_to(SCREEN_WELCOME):
            names = self.navigator.names()
            if names:
                self.navigator.go_to(names[0])

    # -------------------------------------------------------------------------
    # Services
    # -------------------------------------------------------------------------

    def _service_specs(self) -> Tuple[ServiceSpec, ...]:
        return (
            ServiceSpec("database_service", "services.database_service", ("DatabaseService",), ("database", "db")),
            ServiceSpec("settings_service", "services.settings_service", ("SettingsService",), ("settings",)),
            ServiceSpec("calibration_service", "services.calibration_service", ("CalibrationService",), ("calibration",)),
            ServiceSpec("threshold_service", "services.threshold_service", ("ThresholdService",), ("thresholds",)),
            ServiceSpec("mode_service", "services.mode_service", ("ModeService", "AppModeService", "KioskModeService"), ("mode",)),
            ServiceSpec("session_service", "services.session_service", ("SessionService", "AppSessionService", "KioskSessionService"), ("session",)),
            ServiceSpec("health_rules_service", "services.health_rules_service", ("HealthRulesService",), ("health_rules",)),
            ServiceSpec("diagnosis_service", "services.diagnosis_service", ("DiagnosisService",), ("diagnosis",)),
            ServiceSpec("storage_service", "services.storage_service", ("StorageService",), ("storage",)),
            ServiceSpec("export_service", "services.export_service", ("ExportService",), ("export",)),
            ServiceSpec("report_service", "services.report_service", ("ReportService", "PDFReportService", "PdfReportService"), ("report",)),
            ServiceSpec("qr_service", "services.qr_service", ("QrService", "QRService", "QRCodeService"), ("qr",)),
            ServiceSpec("connection_service", "services.connection_service", ("ConnectionService", "DeviceConnectionService", "HardwareConnectionService"), ("connection",)),
            ServiceSpec("serial_service", "services.serial_service", ("SerialService", "SerialPortService", "UARTSerialService", "UartSerialService"), ("serial",)),
            ServiceSpec("sensor_service", "services.sensor_service", ("SensorService", "SensorRuntimeService", "HealthSensorService"), ("sensor",)),
            ServiceSpec("publish_service", "services.publish_service", ("PublishService",), ("publish",)),
        )

    def _build_services(self) -> None:
        for spec in self._service_specs():
            cls = _import_service_class(spec.module_path, spec.class_names)
            if cls is None:
                self.log.warning(
                    "Service class not found in %s. Tried: %s",
                    spec.module_path,
                    ", ".join(spec.class_names),
                )
                continue

            kwargs = self._service_kwargs()
            instance = None
            try:
                instance = _construct_flexible(cls, **kwargs)
            except Exception as exc:
                self.log.exception("Failed to construct service %s: %s", spec.key, exc)
                instance = None

            if instance is None:
                continue

            self.services[spec.key] = instance
            for alias in spec.aliases:
                self.services[alias] = instance

            try:
                setattr(self.app_state, spec.key, instance)
            except Exception:
                pass

    def _service_kwargs(self) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "parent": self,
            "app_state": self.app_state,
            "state": self.app_state,
            "config": self.runtime_config,
            "runtime_config": self.runtime_config,
            "base_dir": self.runtime_config.base_dir,
            "assets_dir": self.runtime_config.assets_dir,
            "theme_manager": self.theme_manager,
            "animation_manager": self.animation_manager,
            "navigator": self.navigator,
            "services": self.services,
        }

        for key, service in self.services.items():
            kwargs[key] = service

        if "database_service" in self.services:
            kwargs["database"] = self.services["database_service"]
            kwargs["db"] = self.services["database_service"]
        if "settings_service" in self.services:
            kwargs["settings"] = self.services["settings_service"]
        if "session_service" in self.services:
            kwargs["session"] = self.services["session_service"]
        if "threshold_service" in self.services:
            kwargs["thresholds"] = self.services["threshold_service"]
        if "health_rules_service" in self.services:
            kwargs["health_rules"] = self.services["health_rules_service"]
        if "diagnosis_service" in self.services:
            kwargs["diagnosis"] = self.services["diagnosis_service"]
        if "serial_service" in self.services:
            kwargs["serial"] = self.services["serial_service"]
        if "sensor_service" in self.services:
            kwargs["sensor"] = self.services["sensor_service"]
        if "connection_service" in self.services:
            kwargs["connection"] = self.services["connection_service"]
        if "report_service" in self.services:
            kwargs["report"] = self.services["report_service"]
        if "qr_service" in self.services:
            kwargs["qr"] = self.services["qr_service"]
        if "publish_service" in self.services:
            kwargs["publish"] = self.services["publish_service"]
        if "export_service" in self.services:
            kwargs["export"] = self.services["export_service"]
        if "storage_service" in self.services:
            kwargs["storage"] = self.services["storage_service"]
        if "mode_service" in self.services:
            kwargs["mode"] = self.services["mode_service"]

        return kwargs

    def _run_service_startup_hooks(self) -> None:
        startup_methods = (
            "initialize",
            "initialise",
            "startup",
            "boot",
            "load",
            "load_defaults",
            "ensure_defaults",
            "ensure_ready",
            "ensure_schema",
            "open",
            "connect_if_needed",
            "refresh",
        )

        for key in (
            "database_service",
            "settings_service",
            "calibration_service",
            "threshold_service",
            "mode_service",
            "session_service",
        ):
            _call_first_available(self.services.get(key), startup_methods)

        for key in (
            "health_rules_service",
            "diagnosis_service",
            "storage_service",
            "export_service",
            "report_service",
            "qr_service",
            "connection_service",
            "serial_service",
            "sensor_service",
            "publish_service",
        ):
            _call_first_available(self.services.get(key), startup_methods)

    # -------------------------------------------------------------------------
    # Screens
    # -------------------------------------------------------------------------

    def _screen_specs(self) -> Tuple[ScreenSpec, ...]:
        return (
            ScreenSpec(SCREEN_WELCOME, "screens.welcome_screen", "WelcomeScreen", "Welcome", "Welcome / boot splash / glow intro screen."),
            ScreenSpec(SCREEN_MODE_SELECT, "screens.mode_select_screen", "ModeSelectScreen", "Mode Select", "Choose demo mode or hardware mode."),
            ScreenSpec(SCREEN_MEASURING, "screens.measuring_screen", "MeasuringScreen", "Measuring", "Measurement progress and live acquisition screen."),
            ScreenSpec(SCREEN_RESULTS, "screens.results_screen", "ResultsScreen", "Results", "Primary session results dashboard."),
            ScreenSpec(SCREEN_RESULTS_DIAGNOSIS, "screens.result_diagnosis_screen", "ResultDiagnosisScreen", "Diagnosis Summary", "Public diagnosis summary screen opened from results."),
            ScreenSpec(SCREEN_QR, "screens.qr_screen", "QrScreen", "QR Handoff", "QR result-sharing screen."),
            ScreenSpec(SCREEN_CONSULT, "screens.consult_screen", "ConsultScreen", "Consult", "Consultation guidance screen."),
            ScreenSpec(SCREEN_ADMIN_LOGIN, "screens.admin_login_screen", "AdminLoginScreen", "Admin Login", "Protected admin login screen."),
            ScreenSpec(SCREEN_ADMIN_PANEL, "screens.admin_panel_screen", "AdminPanelScreen", "Admin Panel", "Protected admin control dashboard."),
            ScreenSpec(SCREEN_SETTINGS, "screens.settings_screen", "SettingsScreen", "Settings", "System and UI settings screen."),
            ScreenSpec(SCREEN_CALIBRATION, "screens.calibration_screen", "CalibrationScreen", "Calibration", "Sensor calibration management screen."),
            ScreenSpec(SCREEN_PARAMETERS, "screens.parameters_screen", "ParametersScreen", "Parameters", "Threshold and parameter configuration screen."),
            ScreenSpec(SCREEN_DIAGNOSIS, "screens.diagnosis_screen", "DiagnosisScreen", "Diagnosis", "Diagnosis review and rule interpretation screen."),
            ScreenSpec(SCREEN_STORAGE, "screens.storage_screen", "StorageScreen", "Storage", "Storage management and maintenance screen."),
            ScreenSpec(SCREEN_PUBLISH, "screens.publish_screen", "PublishScreen", "Publish", "Publish / handoff management screen."),
            ScreenSpec(SCREEN_BMI_DETAIL, "screens.bmi_detail_screen", "BmiDetailScreen", "BMI Detail", "BMI detail explanation screen."),
            ScreenSpec(SCREEN_TEMPERATURE_DETAIL, "screens.temperature_detail_screen", "TemperatureDetailScreen", "Temperature Detail", "Temperature detail explanation screen."),
            ScreenSpec(SCREEN_SPO2_DETAIL, "screens.spo2_detail_screen", "Spo2DetailScreen", "SpO₂ Detail", "Oxygen saturation detail explanation screen."),
            ScreenSpec(SCREEN_PULSE_DETAIL, "screens.pulse_detail_screen", "PulseDetailScreen", "Pulse Detail", "Pulse / heart-rate detail explanation screen."),
            ScreenSpec(SCREEN_RR_DETAIL, "screens.rr_detail_screen", "RrDetailScreen", "Respiratory Detail", "Respiratory-rate detail explanation screen."),
        )

    def _build_screens(self) -> None:
        for spec in self._screen_specs():
            cls = _import_symbol(spec.module_path, spec.class_name)

            if cls is None:
                widget = PlaceholderScreen(
                    title=spec.title,
                    description=(
                        f"{spec.description}\n\n"
                        f"The real screen class could not be imported yet.\n"
                        f"Module: {spec.module_path}\n"
                        f"Class: {spec.class_name}"
                    ),
                    parent=self.stacked_widget,
                )
            else:
                kwargs = {
                    "parent": self.stacked_widget,
                    "navigator": self.navigator,
                    "app_state": self.app_state,
                    "services": self.services,
                    "theme_manager": self.theme_manager,
                    "animation_manager": self.animation_manager,
                    "config": self.runtime_config,
                    "runtime_config": self.runtime_config,
                }
                try:
                    widget = _construct_flexible(cls, **kwargs)
                except Exception as exc:
                    self.log.exception("Failed to build screen %s: %s", spec.name, exc)
                    widget = PlaceholderScreen(
                        title=spec.title,
                        description=f"{spec.description}\n\nThe real screen failed during construction.\n{exc}",
                        parent=self.stacked_widget,
                    )

            self.screens[spec.name] = widget
            self.navigator.register_screen(spec.name, widget)

    # -------------------------------------------------------------------------
    # Wiring
    # -------------------------------------------------------------------------

    def _wire_navigation(self) -> None:
        welcome = self.screens.get(SCREEN_WELCOME)
        mode_select = self.screens.get(SCREEN_MODE_SELECT)
        measuring = self.screens.get(SCREEN_MEASURING)
        results = self.screens.get(SCREEN_RESULTS)
        results_diagnosis = self.screens.get(SCREEN_RESULTS_DIAGNOSIS)
        qr = self.screens.get(SCREEN_QR)
        consult = self.screens.get(SCREEN_CONSULT)
        admin_login = self.screens.get(SCREEN_ADMIN_LOGIN)
        admin_panel = self.screens.get(SCREEN_ADMIN_PANEL)

        settings = self.screens.get(SCREEN_SETTINGS)
        calibration = self.screens.get(SCREEN_CALIBRATION)
        parameters = self.screens.get(SCREEN_PARAMETERS)
        diagnosis = self.screens.get(SCREEN_DIAGNOSIS)
        storage = self.screens.get(SCREEN_STORAGE)
        publish = self.screens.get(SCREEN_PUBLISH)

        bmi_detail = self.screens.get(SCREEN_BMI_DETAIL)
        temperature_detail = self.screens.get(SCREEN_TEMPERATURE_DETAIL)
        spo2_detail = self.screens.get(SCREEN_SPO2_DETAIL)
        pulse_detail = self.screens.get(SCREEN_PULSE_DETAIL)
        rr_detail = self.screens.get(SCREEN_RR_DETAIL)

        _connect_first_signal(
            welcome,
            ("start_requested", "checkup_requested", "proceed_requested", "continue_requested"),
            lambda *a: self.navigator.go_to(SCREEN_MODE_SELECT),
        )
        _connect_first_signal(
            welcome,
            ("admin_requested", "admin_clicked", "open_admin_requested"),
            lambda *a: self.navigator.go_to(SCREEN_ADMIN_LOGIN),
        )

        _connect_first_signal(
            mode_select,
            ("demo_requested", "start_demo_requested", "demo_mode_selected"),
            lambda *a: self._on_mode_selected("demo"),
        )
        _connect_first_signal(
            mode_select,
            ("hardware_requested", "start_hardware_requested", "hardware_mode_selected"),
            lambda *a: self._on_mode_selected("hardware"),
        )
        _connect_first_signal(
            mode_select,
            ("back_requested", "cancel_requested"),
            lambda *a: self.navigator.go_to(SCREEN_WELCOME),
        )

        _connect_first_signal(
            measuring,
            ("back_requested", "cancel_requested"),
            lambda *a: self.navigator.go_to(SCREEN_MODE_SELECT),
        )
        _connect_first_signal(
            measuring,
            ("measurement_completed", "completed", "results_ready"),
            self._on_measurement_complete,
        )
        _connect_first_signal(measuring, ("qr_requested",), lambda *a: self.navigator.go_to(SCREEN_QR))
        _connect_first_signal(measuring, ("consult_requested",), lambda *a: self.navigator.go_to(SCREEN_CONSULT))

        _connect_first_signal(results, ("back_requested", "cancel_requested"), lambda *a: self.navigator.go_to(SCREEN_MODE_SELECT))
        _connect_first_signal(results, ("qr_requested", "open_qr_requested"), lambda *a: self.navigator.go_to(SCREEN_QR))
        _connect_first_signal(results, ("diagnosis_requested", "open_diagnosis_requested"), lambda *a: self.navigator.go_to(SCREEN_RESULTS_DIAGNOSIS))
        _connect_first_signal(results, ("consult_requested", "open_consult_requested"), lambda *a: self.navigator.go_to(SCREEN_CONSULT))
        _connect_first_signal(results, ("admin_requested", "open_admin_requested"), lambda *a: self.navigator.go_to(SCREEN_ADMIN_LOGIN))
        _connect_first_signal(results, ("refresh_requested", "reload_requested"), lambda *a: self._refresh_current_payload_views())
        _connect_first_signal(results, ("retake_requested", "restart_requested", "new_checkup_requested"), self._on_results_retake_requested)

        _connect_first_signal(results, ("metric_detail_requested", "detail_requested", "metric_clicked", "detail_card_clicked"), self._on_metric_detail_requested)
        _connect_first_signal(results, ("bmi_requested", "bmi_detail_requested", "open_bmi_detail"), lambda *a: self.navigator.go_to(SCREEN_BMI_DETAIL))
        _connect_first_signal(results, ("temperature_requested", "temperature_detail_requested", "open_temperature_detail"), lambda *a: self.navigator.go_to(SCREEN_TEMPERATURE_DETAIL))
        _connect_first_signal(results, ("spo2_requested", "spo2_detail_requested", "open_spo2_detail"), lambda *a: self.navigator.go_to(SCREEN_SPO2_DETAIL))
        _connect_first_signal(results, ("pulse_requested", "pulse_detail_requested", "open_pulse_detail"), lambda *a: self.navigator.go_to(SCREEN_PULSE_DETAIL))
        _connect_first_signal(results, ("rr_requested", "respiratory_requested", "rr_detail_requested", "open_rr_detail"), lambda *a: self.navigator.go_to(SCREEN_RR_DETAIL))

        _connect_first_signal(results_diagnosis, ("back_requested", "close_requested", "done_requested"), lambda *a: self.navigator.go_to(SCREEN_RESULTS))
        _connect_first_signal(results_diagnosis, ("qr_requested",), lambda *a: self.navigator.go_to(SCREEN_QR))
        _connect_first_signal(results_diagnosis, ("consult_requested",), lambda *a: self.navigator.go_to(SCREEN_CONSULT))

        _connect_first_signal(qr, ("back_requested", "close_requested", "done_requested"), lambda *a: self.navigator.go_to(SCREEN_RESULTS))
        _connect_first_signal(consult, ("back_requested", "close_requested", "done_requested"), lambda *a: self.navigator.go_to(SCREEN_RESULTS))

        _connect_first_signal(admin_login, ("back_requested", "cancel_requested"), lambda *a: self.navigator.go_to(SCREEN_RESULTS))
        _connect_first_signal(admin_login, ("login_successful", "login_succeeded", "authenticated", "auth_success"), self._on_admin_login_success)
        _connect_first_signal(admin_login, ("login_failed", "auth_failed"), lambda *a: None)

        _connect_first_signal(admin_panel, ("back_requested", "close_requested"), lambda *a: self.navigator.go_to(SCREEN_RESULTS))
        _connect_first_signal(admin_panel, ("logout_requested", "signout_requested"), self._on_admin_logout)
        _connect_first_signal(admin_panel, ("settings_requested", "open_settings_requested"), lambda *a: self.navigator.go_to(SCREEN_SETTINGS))
        _connect_first_signal(admin_panel, ("calibration_requested", "open_calibration_requested"), lambda *a: self.navigator.go_to(SCREEN_CALIBRATION))
        _connect_first_signal(admin_panel, ("parameters_requested", "open_parameters_requested"), lambda *a: self.navigator.go_to(SCREEN_PARAMETERS))
        _connect_first_signal(admin_panel, ("diagnosis_requested", "open_diagnosis_requested"), lambda *a: self.navigator.go_to(SCREEN_DIAGNOSIS))
        _connect_first_signal(admin_panel, ("storage_requested", "open_storage_requested"), lambda *a: self.navigator.go_to(SCREEN_STORAGE))
        _connect_first_signal(admin_panel, ("publish_requested", "open_publish_requested"), lambda *a: self.navigator.go_to(SCREEN_PUBLISH))

        for admin_child in (settings, calibration, parameters, diagnosis, storage, publish):
            _connect_first_signal(admin_child, ("back_requested", "close_requested", "done_requested"), lambda *a: self.navigator.go_to(SCREEN_ADMIN_PANEL))

        for detail_screen in (bmi_detail, temperature_detail, spo2_detail, pulse_detail, rr_detail):
            _connect_first_signal(detail_screen, ("back_requested",), lambda *a: self.navigator.go_to(SCREEN_RESULTS))
            _connect_first_signal(detail_screen, ("qr_requested",), lambda *a: self.navigator.go_to(SCREEN_QR))
            _connect_first_signal(detail_screen, ("consult_requested",), lambda *a: self.navigator.go_to(SCREEN_CONSULT))

    # -------------------------------------------------------------------------
    # Navigation events
    # -------------------------------------------------------------------------

    def _on_navigated(self, screen_name: str, widget: QWidget) -> None:
        try:
            setattr(self.app_state, "current_screen", screen_name)
        except Exception:
            pass

        _call_first_available(self.idle_manager, ("notify_navigation", "touch", "activity", "reset_timer"), screen_name)
        _call_first_available(widget, ("reload", "refresh", "reload_detail", "reload_storage", "reload_publish_state", "on_route_enter"), screen_name)

        if screen_name in {
            SCREEN_RESULTS,
            SCREEN_QR,
            SCREEN_CONSULT,
            SCREEN_BMI_DETAIL,
            SCREEN_TEMPERATURE_DETAIL,
            SCREEN_SPO2_DETAIL,
            SCREEN_PULSE_DETAIL,
            SCREEN_RR_DETAIL,
        }:
            if not self._has_active_payload():
                self._ensure_demo_session_payload()

    # -------------------------------------------------------------------------
    # Mode handling
    # -------------------------------------------------------------------------

    def _restore_mode_and_seed_if_needed(self) -> None:
        mode = self._read_current_mode()
        if not mode and self.runtime_config.demo_on_boot:
            self._set_mode("demo")
            self._ensure_demo_session_payload()

    def _read_current_mode(self) -> str:
        mode = _call_first_available(
            self.services.get("mode_service"),
            ("get_mode", "mode", "current_mode", "value"),
        )
        text = safe_str(mode, "").strip().lower()
        if text:
            return text
        return safe_str(getattr(self.app_state, "mode", ""), "").strip().lower()

    def _set_mode(self, mode: str) -> None:
        normalized = safe_str(mode, "demo").strip().lower() or "demo"

        _call_first_available(
            self.services.get("mode_service"),
            ("set_mode", "change_mode", "update_mode"),
            normalized,
        )

        try:
            setattr(self.app_state, "mode", normalized)
        except Exception:
            pass

        if normalized == "hardware":
            _call_first_available(self.services.get("connection_service"), ("connect", "connect_if_needed", "ensure_connected"))
            _call_first_available(self.services.get("serial_service"), ("connect", "open", "connect_if_needed"))
        else:
            self._ensure_demo_session_payload()

    def _on_mode_selected(self, mode: str) -> None:
        self._set_mode(mode)
        self.navigator.go_to(SCREEN_MEASURING)

    # -------------------------------------------------------------------------
    # Session payload handling
    # -------------------------------------------------------------------------

    def _build_demo_payload(self) -> Dict[str, Any]:
        weight_kg = 68.0
        height_cm = 171.0
        height_m = height_cm / 100.0
        bmi = round(weight_kg / (height_m * height_m), 1)

        return {
            "session_id": "demo-session",
            "mode": "demo",
            "measurements": {
                METRIC_WEIGHT: weight_kg,
                METRIC_HEIGHT: height_cm,
                METRIC_BMI: bmi,
                METRIC_TEMPERATURE: 36.8,
                METRIC_SPO2: 98,
                METRIC_PULSE: 76,
                METRIC_RESPIRATORY_RATE: 16,
            },
            "classifications": {
                METRIC_BMI: {
                    "label": "Healthy",
                    "severity": "normal",
                    "summary": "BMI falls within the healthy range.",
                },
                METRIC_TEMPERATURE: {
                    "label": "Healthy",
                    "severity": "normal",
                    "summary": "Temperature falls within the preferred reference band.",
                },
                METRIC_SPO2: {
                    "label": "Healthy",
                    "severity": "normal",
                    "summary": "Oxygen saturation falls within the healthy reference band.",
                },
                METRIC_PULSE: {
                    "label": "Healthy",
                    "severity": "normal",
                    "summary": "Pulse falls within the typical resting reference band.",
                },
                METRIC_RESPIRATORY_RATE: {
                    "label": "Healthy",
                    "severity": "normal",
                    "summary": "Respiratory rate falls within the common adult resting range.",
                },
            },
        }

    def _has_active_payload(self) -> bool:
        payload = self._read_active_payload()
        return bool(payload)

    def _read_active_payload(self) -> Dict[str, Any]:
        payload = _call_first_available(
            self.services.get("session_service"),
            ("get_results_payload", "get_current_session", "get_session_payload", "current_session_payload", "get_latest_results_payload", "snapshot", "get_snapshot"),
        )
        if isinstance(payload, Mapping) and payload:
            return dict(payload)

        payload = _call_first_available(
            self.services.get("sensor_service"),
            ("get_latest_results_payload", "get_latest_results", "latest_results", "snapshot", "get_snapshot"),
        )
        if isinstance(payload, Mapping) and payload:
            return dict(payload)

        for attr_name in ("results_payload", "current_session_payload", "session_payload", "consult_payload"):
            try:
                attr = getattr(self.app_state, attr_name, None)
                if isinstance(attr, Mapping) and attr:
                    return dict(attr)
            except Exception:
                continue

        return {}

    def _store_active_payload(self, payload: Mapping[str, Any]) -> None:
        if not isinstance(payload, Mapping):
            return

        clean_payload = dict(payload)

        _call_first_available(
            self.services.get("session_service"),
            ("set_results_payload", "set_current_session", "set_session_payload", "update_session", "update_current_session", "store_session"),
            clean_payload,
        )

        _call_first_available(
            self.services.get("sensor_service"),
            ("set_latest_results_payload", "set_latest_results", "update_latest_results"),
            clean_payload,
        )

        for attr_name in ("results_payload", "current_session_payload", "session_payload"):
            try:
                setattr(self.app_state, attr_name, clean_payload)
            except Exception:
                continue

    def _ensure_demo_session_payload(self) -> None:
        if self._has_active_payload():
            return
        self._store_active_payload(self._build_demo_payload())

    def _consume_latest_payload_from_services(self) -> Dict[str, Any]:
        payload = self._read_active_payload()
        if payload:
            return payload

        demo_payload = self._build_demo_payload()
        self._store_active_payload(demo_payload)
        return demo_payload

    # -------------------------------------------------------------------------
    # Event handlers
    # -------------------------------------------------------------------------

    def _on_measurement_complete(self, *args: Any) -> None:
        payload = _get_first_mapping_arg(*args)
        if not payload:
            payload = self._consume_latest_payload_from_services()

        self._store_active_payload(payload)
        self._refresh_current_payload_views()
        self.navigator.go_to(SCREEN_RESULTS)

    def _on_results_retake_requested(self, *args: Any) -> None:
        _ = args
        measuring = self.screens.get(SCREEN_MEASURING)

        self.navigator.go_to(SCREEN_MEASURING)

        if measuring is None:
            return

        def _restart_measurement() -> None:
            try:
                if hasattr(measuring, "reset_measurement") and callable(getattr(measuring, "reset_measurement")):
                    measuring.reset_measurement()
                    return
            except Exception:
                pass

            try:
                if hasattr(measuring, "stop_measurement") and callable(getattr(measuring, "stop_measurement")):
                    measuring.stop_measurement()
            except Exception:
                pass

            try:
                if hasattr(measuring, "start_measurement") and callable(getattr(measuring, "start_measurement")):
                    measuring.start_measurement()
            except Exception:
                pass

        QTimer.singleShot(40, _restart_measurement)

    def _on_metric_detail_requested(self, *args: Any) -> None:
        metric = ""
        for arg in args:
            if isinstance(arg, str):
                metric = arg
                break

        target = _normalize_metric_key(metric)
        if target and self.navigator.contains(target):
            self.navigator.go_to(target)

    def _on_admin_login_success(self, *args: Any) -> None:
        try:
            setattr(self.app_state, "admin_authenticated", True)
        except Exception:
            pass
        self.navigator.go_to(SCREEN_ADMIN_PANEL)

    def _on_admin_logout(self, *args: Any) -> None:
        try:
            setattr(self.app_state, "admin_authenticated", False)
        except Exception:
            pass
        self.navigator.go_to(SCREEN_RESULTS)

    def _refresh_current_payload_views(self) -> None:
        for screen_name in (
            SCREEN_RESULTS,
            SCREEN_QR,
            SCREEN_CONSULT,
            SCREEN_BMI_DETAIL,
            SCREEN_TEMPERATURE_DETAIL,
            SCREEN_SPO2_DETAIL,
            SCREEN_PULSE_DETAIL,
            SCREEN_RR_DETAIL,
            SCREEN_RESULTS_DIAGNOSIS,
            SCREEN_DIAGNOSIS,
            SCREEN_PUBLISH,
            SCREEN_STORAGE,
        ):
            widget = self.screens.get(screen_name)
            _call_first_available(widget, ("reload", "refresh", "reload_detail", "reload_publish_state", "reload_storage"))

    def _apply_saved_theme_preferences(self) -> None:
        theme_value = _call_first_available(
            self.services.get("settings_service"),
            ("get_setting", "value", "get"),
            "theme_mode",
        )

        if not theme_value:
            theme_value = _call_first_available(
                self.services.get("settings_service"),
                ("get_setting", "value", "get"),
                "appearance",
            )

        theme_text = safe_str(theme_value, self.runtime_config.theme_mode).strip().lower() or self.runtime_config.theme_mode

        _call_first_available(
            self.theme_manager,
            ("apply_theme", "set_theme", "load_theme", "activate_theme"),
            theme_text,
        )

    # -------------------------------------------------------------------------
    # Qt events
    # -------------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # type: ignore[override]
        for key in (
            "publish_service",
            "sensor_service",
            "serial_service",
            "connection_service",
            "session_service",
            "database_service",
        ):
            _call_first_available(
                self.services.get(key),
                ("shutdown", "close", "disconnect", "stop", "teardown"),
            )
        super().closeEvent(event)


# -----------------------------------------------------------------------------
# Application bootstrap
# -----------------------------------------------------------------------------

def _install_exception_hook() -> None:
    def _hook(exc_type, exc_value, exc_traceback):
        logger.exception(
            "Unhandled exception: %s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_traceback)),
        )
        try:
            QMessageBox.critical(
                None,
                APP_NAME,
                f"An unexpected error occurred:\n\n{exc_value}",
            )
        except Exception:
            pass

    sys.excepthook = _hook


def _configure_qt_application(app: QApplication, runtime_config: RuntimeConfig) -> None:
    app.setApplicationName(runtime_config.app_name)
    app.setOrganizationName(runtime_config.app_org)
    app.setApplicationVersion(runtime_config.app_version)
    app.setStyle("Fusion")

    _register_fonts(runtime_config.fonts_dir)

    app.setStyleSheet(
        """
        QWidget {
            selection-background-color: rgba(67, 217, 255, 0.38);
            selection-color: #F7FCFF;
        }
        QToolTip {
            color: #F7FCFF;
            background-color: rgba(10, 23, 40, 0.94);
            border: 1px solid rgba(157, 220, 255, 0.34);
            padding: 6px 8px;
        }
        """
    )


def main() -> int:
    _install_exception_hook()

    app = QApplication(sys.argv)
    runtime_config = _load_runtime_config()
    _configure_qt_application(app, runtime_config)

    window = KioskMainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())