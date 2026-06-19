
"""
screens/settings_screen.py

Protected kiosk settings screen for the CST Health Monitoring Station.

Compact 800x480-tuned version with:
- darker, cleaner 4-tile layout
- slightly wider colored tiles so inner controls do not collide
- smaller dropdowns / controls so content fits inside each tile
- top icon shown without a badge box
- live brightness preview on the current window
- functional dropdowns, sliders, spinboxes, and checkboxes
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.logger import get_logger

try:
    from core.utils import safe_bool, safe_int, safe_str
except Exception:  # pragma: no cover
    def safe_str(value: Any, default: str = "") -> str:
        try:
            if value is None:
                return default
            return str(value)
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
    from core.constants import MODE_DEMO, MODE_HARDWARE, SCREEN_ADMIN_PANEL
except Exception:  # pragma: no cover
    MODE_DEMO = "demo"
    MODE_HARDWARE = "hardware"
    SCREEN_ADMIN_PANEL = "admin_panel"

try:
    from config import KIOSK_WIDTH, KIOSK_HEIGHT, IS_COMPACT_KIOSK
except Exception:  # pragma: no cover
    KIOSK_WIDTH = 800
    KIOSK_HEIGHT = 480
    IS_COMPACT_KIOSK = True

logger = get_logger(__name__)


DEFAULT_SETTINGS: Dict[str, Any] = {
    "appearance": "dark",
    "brightness": 100,
    "timeout": 90,
    "volume": 70,
    "network_mode": "local",
    "startup_mode": "remember_last",
    "serial_auto_connect": True,
    "touch_sounds_enabled": True,
}

APPEARANCE_LABELS = {
    "dark": "Dark",
    "light": "Light",
    "auto": "Auto",
}

NETWORK_MODE_LABELS = {
    "offline": "Offline",
    "local": "Local",
    "online": "Online",
    "auto": "Auto",
}

STARTUP_MODE_LABELS = {
    "demo": "Demo",
    "hardware": "Hardware",
    "remember_last": "Remember Last",
}


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_asset(relative_path: str) -> str:
    relative_clean = safe_str(relative_path, "").strip().replace("\\", "/").lstrip("/")
    if not relative_clean:
        return ""

    try:
        import core.asset_paths as asset_paths

        for name in (
            "get_asset_path",
            "asset_path",
            "resolve_asset_path",
            "resolve_asset",
            "asset",
        ):
            resolver = getattr(asset_paths, name, None)
            if callable(resolver):
                try:
                    resolved = resolver(relative_clean)
                    resolved_text = safe_str(resolved, "").strip()
                    if resolved_text:
                        return resolved_text
                except Exception:
                    continue
    except Exception:
        pass

    return str(_project_root().joinpath("assets", *relative_clean.split("/")))


def _pixmap_or_empty(path: str) -> QPixmap:
    text = safe_str(path, "").strip()
    if not text:
        return QPixmap()
    return QPixmap(text)


def _normalize_appearance(value: Any) -> str:
    text = safe_str(value, "dark").strip().lower()
    return text if text in {"dark", "light", "auto"} else "dark"


def _normalize_network_mode(value: Any) -> str:
    text = safe_str(value, "local").strip().lower()
    return text if text in {"offline", "local", "online", "auto"} else "local"


def _normalize_startup_mode(value: Any) -> str:
    text = safe_str(value, "remember_last").strip().lower()
    return text if text in {"demo", "hardware", "remember_last"} else "remember_last"


def _accent_for_state(value: str) -> str:
    text = safe_str(value, "").strip().lower()
    if text in {"unsaved", "warning", "pending", "attention"}:
        return "#E5C45D"
    if text in {"saved", "loaded", "ready", "active", "enabled", "ok"}:
        return "#2FD28C"
    if text in {"offline", "error", "failed", "disabled"}:
        return "#FF6E88"
    return "#39D8FF"


class _TileCard(QFrame):
    """Compact settings tile with slightly colored background and a small badge."""

    def __init__(self, title: str, *, accent_hex: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._accent_hex = safe_str(accent_hex, "#39D8FF").strip() or "#39D8FF"
        self._title_text = safe_str(title, "").strip() or "Tile"

        self.setObjectName("TileCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(114)
        self.setMaximumHeight(114)

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(10, 8, 10, 8)
        self.root_layout.setSpacing(6)

        self.header_row = QWidget(self)
        self.header_layout = QHBoxLayout(self.header_row)
        self.header_layout.setContentsMargins(0, 0, 0, 0)
        self.header_layout.setSpacing(6)

        self.title_label = QLabel(self._title_text, self.header_row)
        self.title_label.setObjectName("TileTitle")

        self.badge = QLabel("", self.header_row)
        self.badge.setObjectName("TileBadge")
        self.badge.setVisible(False)

        self.header_layout.addWidget(self.title_label)
        self.header_layout.addStretch(1)
        self.header_layout.addWidget(self.badge)

        self.body = QWidget(self)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(5)

        self.root_layout.addWidget(self.header_row)
        self.root_layout.addWidget(self.body, 1)

        self._apply_style()

    def add_row(self, row: QWidget) -> None:
        self.body_layout.addWidget(row)

    def set_badge(self, text: str) -> None:
        badge_text = safe_str(text, "").strip()
        self.badge.setText(badge_text)
        self.badge.setVisible(bool(badge_text))
        self._apply_style()

    def set_accent(self, accent_hex: str) -> None:
        self._accent_hex = safe_str(accent_hex, self._accent_hex).strip() or self._accent_hex
        self._apply_style()

    def set_compact(self, compact: bool, ultra_compact: bool = False) -> None:
        if ultra_compact:
            self.setMinimumHeight(104)
            self.setMaximumHeight(104)
            self.root_layout.setContentsMargins(9, 7, 9, 7)
            self.root_layout.setSpacing(5)
            self.body_layout.setSpacing(4)
        elif compact:
            self.setMinimumHeight(110)
            self.setMaximumHeight(110)
            self.root_layout.setContentsMargins(10, 8, 10, 8)
            self.root_layout.setSpacing(5)
            self.body_layout.setSpacing(4)
        else:
            self.setMinimumHeight(122)
            self.setMaximumHeight(122)
            self.root_layout.setContentsMargins(12, 10, 12, 10)
            self.root_layout.setSpacing(6)
            self.body_layout.setSpacing(5)
        self._apply_style()

    def _apply_style(self) -> None:
        accent = QColor(self._accent_hex)
        self.setStyleSheet(
            f"""
            QFrame#TileCard {{
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.72);
                border-radius: 18px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.12);
            }}
            QLabel#TileTitle {{
                color: #F8FCFF;
                font-size: 10px;
                font-weight: 900;
                background: transparent;
            }}
            QLabel#TileBadge {{
                color: #F8FCFF;
                font-size: 7px;
                font-weight: 800;
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.72);
                border-radius: 9px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.10);
                padding: 2px 9px;
                min-width: 62px;
            }}
            """
        )


class _LabeledControlRow(QFrame):
    """Compact labeled row used inside the main setting tiles."""

    def __init__(self, label_text: str, *, accent_hex: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._accent_hex = safe_str(accent_hex, "#39D8FF").strip() or "#39D8FF"

        self.setObjectName("LabeledControlRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(34)
        self.setMaximumHeight(34)

        self.root_layout = QHBoxLayout(self)
        self.root_layout.setContentsMargins(8, 4, 8, 4)
        self.root_layout.setSpacing(8)

        self.label = QLabel(label_text, self)
        self.label.setObjectName("RowLabel")
        self.label.setMinimumWidth(90)
        self.label.setMaximumWidth(90)

        self.control_holder = QWidget(self)
        self.control_layout = QHBoxLayout(self.control_holder)
        self.control_layout.setContentsMargins(0, 0, 0, 0)
        self.control_layout.setSpacing(6)

        self.root_layout.addWidget(self.label)
        self.root_layout.addWidget(self.control_holder, 1)

        self._apply_style()

    def set_control(self, widget: QWidget, stretch: int = 1) -> None:
        self.control_layout.addWidget(widget, stretch)

    def add_control(self, widget: QWidget, stretch: int = 0) -> None:
        self.control_layout.addWidget(widget, stretch)

    def add_stretch(self, stretch: int = 1) -> None:
        self.control_layout.addStretch(stretch)

    def set_compact(self, compact: bool, ultra_compact: bool = False) -> None:
        if ultra_compact:
            self.setMinimumHeight(32)
            self.setMaximumHeight(32)
            self.root_layout.setContentsMargins(7, 4, 7, 4)
            self.root_layout.setSpacing(6)
            self.label.setMinimumWidth(82)
            self.label.setMaximumWidth(82)
        elif compact:
            self.setMinimumHeight(33)
            self.setMaximumHeight(33)
            self.root_layout.setContentsMargins(8, 4, 8, 4)
            self.root_layout.setSpacing(7)
            self.label.setMinimumWidth(86)
            self.label.setMaximumWidth(86)
        else:
            self.setMinimumHeight(36)
            self.setMaximumHeight(36)
            self.root_layout.setContentsMargins(9, 5, 9, 5)
            self.root_layout.setSpacing(8)
            self.label.setMinimumWidth(94)
            self.label.setMaximumWidth(94)
        self._apply_style()

    def _apply_style(self) -> None:
        accent = QColor(self._accent_hex)
        self.setStyleSheet(
            f"""
            QFrame#LabeledControlRow {{
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.24);
                border-radius: 12px;
                background: rgba(10, 29, 49, 0.97);
            }}
            QLabel#RowLabel {{
                color: #F5FBFF;
                font-size: 8px;
                font-weight: 800;
                background: transparent;
            }}
            """
        )


class SettingsScreen(QFrame):
    """Protected settings screen rebuilt for clean compact kiosk use."""

    back_requested = pyqtSignal()
    settings_loaded = pyqtSignal(dict)
    settings_saved = pyqtSignal(dict)
    settings_reset = pyqtSignal(dict)
    settings_changed = pyqtSignal(dict)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        navigator: Optional[object] = None,
        app_state: Optional[object] = None,
        services: Optional[Mapping[str, Any]] = None,
        animation_manager: Optional[object] = None,
        theme_manager: Optional[object] = None,
    ) -> None:
        super().__init__(parent)

        self._logger = logger.bind(component="SettingsScreen")
        self.navigator = navigator
        self.app_state = app_state
        self.services = dict(services or {})
        self.animation_manager = animation_manager
        self.theme_manager = theme_manager

        self._snapshot: Dict[str, Any] = deepcopy(DEFAULT_SETTINGS)
        self._loaded_snapshot: Dict[str, Any] = deepcopy(DEFAULT_SETTINGS)
        self._changed_since_load = False
        self._saved_window_opacity: Optional[float] = None
        self._preview_brightness = safe_int(DEFAULT_SETTINGS.get("brightness"), 100)
        self._live_overlay_alpha = 160

        self._background_path = _resolve_asset("backgrounds/settings_bg.png")
        self._logo_small_path = _resolve_asset("logos/cst_logo_small.png")
        self._background_pixmap = _pixmap_or_empty(self._background_path)
        self._logo_pixmap = _pixmap_or_empty(self._logo_small_path)

        self.setObjectName("SettingsScreen")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._build_ui()
        self._apply_styles()
        self._apply_responsive_layout()

    def _build_ui(self) -> None:
        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(14, 10, 14, 10)
        self.root_layout.setSpacing(8)

        self.top_bar = QWidget(self)
        self.top_layout = QHBoxLayout(self.top_bar)
        self.top_layout.setContentsMargins(0, 0, 0, 0)
        self.top_layout.setSpacing(8)

        self.back_button = self._create_button("Back", role="nav")
        self.back_button.clicked.connect(self._handle_back_clicked)

        self.logo_label = QLabel(self.top_bar)
        self.logo_label.setObjectName("LogoLabel")
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_label.setFixedSize(38, 38)
        self._set_label_pixmap(self.logo_label, self._logo_pixmap, 38)

        self.top_title = QLabel("Settings", self.top_bar)
        self.top_title.setObjectName("TopTitle")

        self.status_pill = QLabel("Loaded", self.top_bar)
        self.status_pill.setObjectName("RuntimePill")
        self.appearance_pill = QLabel("Dark", self.top_bar)
        self.appearance_pill.setObjectName("RuntimePill")
        self.startup_pill = QLabel("Remember Last", self.top_bar)
        self.startup_pill.setObjectName("RuntimePill")

        self.top_layout.addWidget(self.back_button)
        self.top_layout.addWidget(self.logo_label)
        self.top_layout.addWidget(self.top_title)
        self.top_layout.addStretch(1)
        self.top_layout.addWidget(self.status_pill)
        self.top_layout.addWidget(self.appearance_pill)
        self.top_layout.addWidget(self.startup_pill)

        self.header_card = QFrame(self)
        self.header_card.setObjectName("SettingsHeaderCard")
        self.header_layout = QVBoxLayout(self.header_card)
        self.header_layout.setContentsMargins(12, 8, 12, 8)
        self.header_layout.setSpacing(3)

        self.hero_title = QLabel("Protected kiosk settings", self.header_card)
        self.hero_title.setObjectName("HeroTitle")
        self.hero_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.hero_subtitle = QLabel(
            "Compact display, session, connectivity, and startup controls.",
            self.header_card,
        )
        self.hero_subtitle.setObjectName("HeroSubtitle")
        self.hero_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hero_subtitle.setWordWrap(True)

        self.header_layout.addWidget(self.hero_title)
        self.header_layout.addWidget(self.hero_subtitle)

        self.settings_panel = QFrame(self)
        self.settings_panel.setObjectName("SettingsPanel")
        self.settings_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.settings_panel_layout = QVBoxLayout(self.settings_panel)
        self.settings_panel_layout.setContentsMargins(12, 10, 12, 10)
        self.settings_panel_layout.setSpacing(8)

        self.settings_panel_title = QLabel("Configuration Controls", self.settings_panel)
        self.settings_panel_title.setObjectName("SectionTitle")

        self.settings_grid_widget = QWidget(self.settings_panel)
        self.settings_grid = QGridLayout(self.settings_grid_widget)
        self.settings_grid.setContentsMargins(2, 4, 2, 2)
        self.settings_grid.setHorizontalSpacing(10)
        self.settings_grid.setVerticalSpacing(12)
        self.settings_grid.setColumnStretch(0, 1)
        self.settings_grid.setColumnStretch(1, 1)

        self.display_card = _TileCard("Display", accent_hex="#39D8FF", parent=self.settings_grid_widget)
        self.session_card = _TileCard("Session & Audio", accent_hex="#E6C257", parent=self.settings_grid_widget)
        self.connectivity_card = _TileCard("Connectivity", accent_hex="#885DFF", parent=self.settings_grid_widget)
        self.startup_card = _TileCard("Startup & Feedback", accent_hex="#2FD28C", parent=self.settings_grid_widget)

        self.appearance_row = _LabeledControlRow("Appearance", accent_hex="#39D8FF", parent=self.display_card)
        self.appearance_combo = QComboBox(self.appearance_row)
        self.appearance_combo.addItem("Dark", "dark")
        self.appearance_combo.addItem("Light", "light")
        self.appearance_combo.addItem("Auto", "auto")
        self.appearance_combo.currentIndexChanged.connect(self._on_form_changed)
        self.appearance_combo.setMinimumWidth(126)
        self.appearance_combo.setMaximumWidth(126)
        self.appearance_row.add_stretch(1)
        self.appearance_row.set_control(self.appearance_combo, 0)

        self.brightness_row = _LabeledControlRow("Brightness", accent_hex="#39D8FF", parent=self.display_card)
        self.brightness_slider = QSlider(Qt.Orientation.Horizontal, self.brightness_row)
        self.brightness_slider.setRange(10, 100)
        self.brightness_slider.valueChanged.connect(self._on_brightness_changed)
        self.brightness_value = QLabel("100%", self.brightness_row)
        self.brightness_value.setObjectName("InlineValueBox")
        self.brightness_row.add_control(self.brightness_slider, 1)
        self.brightness_row.add_control(self.brightness_value, 0)

        self.display_card.add_row(self.appearance_row)
        self.display_card.add_row(self.brightness_row)

        self.timeout_row = _LabeledControlRow("Session Timeout", accent_hex="#E6C257", parent=self.session_card)
        self.timeout_spin = QSpinBox(self.timeout_row)
        self.timeout_spin.setRange(15, 600)
        self.timeout_spin.setSuffix(" s")
        self.timeout_spin.valueChanged.connect(self._on_form_changed)
        self.timeout_spin.setMinimumWidth(82)
        self.timeout_spin.setMaximumWidth(82)
        self.timeout_row.add_stretch(1)
        self.timeout_row.set_control(self.timeout_spin, 0)

        self.volume_row = _LabeledControlRow("Volume", accent_hex="#E6C257", parent=self.session_card)
        self.volume_slider = QSlider(Qt.Orientation.Horizontal, self.volume_row)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        self.volume_value = QLabel("70%", self.volume_row)
        self.volume_value.setObjectName("InlineValueBox")
        self.volume_row.add_control(self.volume_slider, 1)
        self.volume_row.add_control(self.volume_value, 0)

        self.session_card.add_row(self.timeout_row)
        self.session_card.add_row(self.volume_row)

        self.network_row = _LabeledControlRow("Network Mode", accent_hex="#885DFF", parent=self.connectivity_card)
        self.network_combo = QComboBox(self.network_row)
        self.network_combo.addItem("Offline", "offline")
        self.network_combo.addItem("Local", "local")
        self.network_combo.addItem("Online", "online")
        self.network_combo.addItem("Auto", "auto")
        self.network_combo.currentIndexChanged.connect(self._on_form_changed)
        self.network_combo.setMinimumWidth(126)
        self.network_combo.setMaximumWidth(126)
        self.network_row.add_stretch(1)
        self.network_row.set_control(self.network_combo, 0)

        self.serial_row = _LabeledControlRow("Serial Auto Connect", accent_hex="#885DFF", parent=self.connectivity_card)
        self.serial_autoconnect_checkbox = QCheckBox("Enable automatic serial connection", self.serial_row)
        self.serial_autoconnect_checkbox.toggled.connect(self._on_form_changed)
        self.serial_row.set_control(self.serial_autoconnect_checkbox, 1)

        self.connectivity_card.add_row(self.network_row)
        self.connectivity_card.add_row(self.serial_row)

        self.startup_mode_row = _LabeledControlRow("Startup Mode", accent_hex="#2FD28C", parent=self.startup_card)
        self.startup_combo = QComboBox(self.startup_mode_row)
        self.startup_combo.addItem("Demo", "demo")
        self.startup_combo.addItem("Hardware", "hardware")
        self.startup_combo.addItem("Remember Last", "remember_last")
        self.startup_combo.currentIndexChanged.connect(self._on_form_changed)
        self.startup_combo.setMinimumWidth(126)
        self.startup_combo.setMaximumWidth(126)
        self.startup_mode_row.add_stretch(1)
        self.startup_mode_row.set_control(self.startup_combo, 0)

        self.touch_row = _LabeledControlRow("Touch Sounds", accent_hex="#2FD28C", parent=self.startup_card)
        self.touch_sounds_checkbox = QCheckBox("Enable touch and transition sounds", self.touch_row)
        self.touch_sounds_checkbox.toggled.connect(self._on_form_changed)
        self.touch_row.set_control(self.touch_sounds_checkbox, 1)

        self.startup_card.add_row(self.startup_mode_row)
        self.startup_card.add_row(self.touch_row)

        self.settings_grid.addWidget(self.display_card, 0, 0)
        self.settings_grid.addWidget(self.session_card, 0, 1)
        self.settings_grid.addWidget(self.connectivity_card, 1, 0)
        self.settings_grid.addWidget(self.startup_card, 1, 1)

        self.settings_panel_layout.addWidget(self.settings_panel_title)
        self.settings_panel_layout.addWidget(self.settings_grid_widget, 1)

        self.action_row = QWidget(self)
        self.action_layout = QHBoxLayout(self.action_row)
        self.action_layout.setContentsMargins(0, 0, 0, 0)
        self.action_layout.setSpacing(10)

        self.reload_button = self._create_button("Reload", role="ghost")
        self.reload_button.clicked.connect(self.reload_settings)
        self.reset_button = self._create_button("Reset", role="warn")
        self.reset_button.clicked.connect(self._handle_reset_clicked)
        self.save_button = self._create_button("Save Settings", role="primary")
        self.save_button.clicked.connect(self._handle_save_clicked)

        self.action_layout.addWidget(self.reload_button)
        self.action_layout.addWidget(self.reset_button)
        self.action_layout.addWidget(self.save_button)

        self.root_layout.addWidget(self.top_bar)
        self.root_layout.addWidget(self.header_card)
        self.root_layout.addWidget(self.settings_panel, 1)
        self.root_layout.addWidget(self.action_row)

    def _create_button(self, text: str, *, role: str) -> QPushButton:
        button = QPushButton(text, self)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setObjectName(f"Button_{role}")
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if role == "nav":
            button.setMinimumWidth(84)
            button.setMaximumWidth(84)
            button.setMinimumHeight(38)
            button.setMaximumHeight(38)
        else:
            button.setMinimumHeight(38)
            button.setMaximumHeight(38)
        return button

    def _set_label_pixmap(self, label: QLabel, pixmap: QPixmap, target_height: int) -> None:
        if pixmap.isNull():
            label.clear()
            return
        label.setPixmap(pixmap.scaledToHeight(target_height, Qt.TransformationMode.SmoothTransformation))

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QFrame#SettingsScreen {
                background: transparent;
            }
            QLabel#LogoLabel {
                min-width: 38px;
                max-width: 38px;
                min-height: 38px;
                max-height: 38px;
                background: transparent;
                border: none;
            }
            QLabel#TopTitle {
                color: #F8FCFF;
                font-size: 12px;
                font-weight: 900;
                background: transparent;
            }
            QLabel#RuntimePill {
                color: #F6FCFF;
                font-size: 8px;
                font-weight: 800;
                border-radius: 13px;
                padding: 4px 11px;
                background: rgba(11, 36, 64, 0.98);
                border: 1px solid rgba(93, 203, 255, 0.28);
                min-height: 26px;
            }
            QFrame#SettingsHeaderCard {
                border: 1px solid rgba(76, 194, 255, 0.24);
                border-radius: 18px;
                background: rgba(7, 24, 43, 0.965);
            }
            QLabel#HeroTitle {
                color: #F7FCFF;
                font-size: 17px;
                font-weight: 900;
                background: transparent;
            }
            QLabel#HeroSubtitle {
                color: rgba(219, 237, 249, 0.84);
                font-size: 8px;
                font-weight: 500;
                background: transparent;
            }
            QFrame#SettingsPanel {
                border: 1px solid rgba(76, 194, 255, 0.24);
                border-radius: 20px;
                background: rgba(7, 24, 43, 0.972);
            }
            QLabel#SectionTitle {
                color: #F6FCFF;
                font-size: 11px;
                font-weight: 800;
                background: transparent;
            }
            QLabel#InlineValueBox {
                color: #F8FCFF;
                font-size: 8px;
                font-weight: 800;
                border-radius: 9px;
                padding: 2px 7px;
                min-width: 50px;
                max-width: 50px;
                background: rgba(12, 33, 58, 0.98);
                border: 1px solid rgba(102, 187, 255, 0.28);
            }
            QComboBox, QSpinBox {
                color: #F7FCFF;
                border: 1px solid rgba(102, 187, 255, 0.26);
                border-radius: 8px;
                background: rgba(12, 33, 58, 0.98);
                padding: 1px 6px;
                font-size: 7px;
                font-weight: 700;
                min-height: 20px;
                max-height: 20px;
            }
            QComboBox::drop-down {
                width: 14px;
                border: none;
                background: transparent;
            }
            QComboBox QAbstractItemView {
                color: #F7FCFF;
                background: rgba(10, 28, 50, 0.995);
                border: 1px solid rgba(102, 187, 255, 0.26);
                selection-background-color: rgba(47, 173, 221, 0.35);
                selection-color: #FFFFFF;
                outline: none;
                font-size: 7px;
                padding: 3px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                width: 11px;
                border: none;
                background: transparent;
            }
            QSlider::groove:horizontal {
                height: 6px;
                border-radius: 3px;
                background: rgba(12, 33, 58, 0.96);
                border: 1px solid rgba(97, 171, 221, 0.18);
            }
            QSlider::handle:horizontal {
                width: 14px;
                margin: -4px 0;
                border-radius: 7px;
                background: rgba(72, 212, 255, 0.96);
                border: 1px solid rgba(190, 234, 255, 0.42);
            }
            QCheckBox {
                color: rgba(221, 238, 249, 0.92);
                font-size: 8px;
                font-weight: 700;
                spacing: 6px;
                background: transparent;
            }
            QCheckBox::indicator {
                width: 13px;
                height: 13px;
                border-radius: 4px;
                border: 1px solid rgba(102, 187, 255, 0.30);
                background: rgba(12, 33, 58, 0.95);
            }
            QCheckBox::indicator:checked {
                background: rgba(61, 214, 144, 0.92);
                border: 1px solid rgba(175, 247, 214, 0.44);
            }
            QPushButton#Button_nav,
            QPushButton#Button_ghost,
            QPushButton#Button_warn,
            QPushButton#Button_primary {
                color: #F8FCFF;
                font-size: 11px;
                font-weight: 800;
                border-radius: 16px;
                padding: 7px 16px;
            }
            QPushButton#Button_nav {
                min-width: 84px;
                max-width: 84px;
                border: 1px solid rgba(127, 228, 255, 0.52);
                background: rgba(67, 197, 236, 0.94);
                color: #FFFFFF;
            }
            QPushButton#Button_nav:hover {
                background: rgba(86, 212, 248, 0.98);
                border-color: rgba(188, 239, 255, 0.72);
            }
            QPushButton#Button_ghost {
                border: 1px solid rgba(79, 203, 255, 0.46);
                background: rgba(43, 184, 223, 0.92);
            }
            QPushButton#Button_ghost:hover {
                background: rgba(58, 197, 235, 0.98);
            }
            QPushButton#Button_warn {
                border: 1px solid rgba(255, 225, 117, 0.48);
                background: rgba(220, 187, 84, 0.94);
                color: #FFF8E8;
            }
            QPushButton#Button_warn:hover {
                background: rgba(234, 199, 92, 1.0);
            }
            QPushButton#Button_primary {
                border: 1px solid rgba(108, 220, 255, 0.48);
                background: rgba(56, 199, 231, 0.96);
            }
            QPushButton#Button_primary:hover {
                background: rgba(74, 214, 244, 1.0);
            }
            """
        )
        self._apply_pill_style(self.status_pill, "#2FD28C")
        self._apply_pill_style(self.appearance_pill, "#39D8FF")
        self._apply_pill_style(self.startup_pill, "#67D8FF")

    def _apply_pill_style(self, label: QLabel, accent_hex: str) -> None:
        accent = QColor(accent_hex)
        label.setStyleSheet(
            f"""
            QLabel {{
                color: #F7FCFF;
                font-size: 8px;
                font-weight: 800;
                border-radius: 13px;
                padding: 4px 11px;
                background: rgba(11, 36, 64, 0.98);
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.52);
                min-height: 26px;
            }}
            """
        )

    def _apply_responsive_layout(self) -> None:
        width = max(1, self.width() or KIOSK_WIDTH)
        height = max(1, self.height() or KIOSK_HEIGHT)
        ultra = width <= 820 or height <= 480
        compact = ultra or width <= 900 or IS_COMPACT_KIOSK

        self.root_layout.setContentsMargins(12 if compact else 16, 8 if compact else 12, 12 if compact else 16, 8 if compact else 12)
        self.root_layout.setSpacing(7 if compact else 10)
        self.top_layout.setSpacing(8 if compact else 10)
        self.header_layout.setContentsMargins(12 if compact else 16, 8 if compact else 10, 12 if compact else 16, 8 if compact else 10)
        self.header_layout.setSpacing(2 if compact else 4)
        self.settings_panel_layout.setContentsMargins(10 if compact else 16, 9 if compact else 12, 10 if compact else 16, 9 if compact else 12)
        self.settings_panel_layout.setSpacing(8 if compact else 10)
        self.settings_grid.setHorizontalSpacing(10 if compact else 12)
        self.settings_grid.setVerticalSpacing(12 if compact else 14)
        self.action_layout.setSpacing(10 if compact else 12)

        self.hero_subtitle.setVisible(not ultra)
        self.appearance_pill.setVisible(width > 640)
        self.startup_pill.setVisible(width > 740)

        self.header_card.setMinimumHeight(52 if compact else 62)
        self.header_card.setMaximumHeight(52 if compact else 62)

        for card in (self.display_card, self.session_card, self.connectivity_card, self.startup_card):
            card.set_compact(compact, ultra)

        for row in (
            self.appearance_row,
            self.brightness_row,
            self.timeout_row,
            self.volume_row,
            self.network_row,
            self.serial_row,
            self.startup_mode_row,
            self.touch_row,
        ):
            row.set_compact(compact, ultra)

        combo_width = 118 if ultra else 126 if compact else 136
        spin_width = 74 if ultra else 80 if compact else 88
        for combo in (self.appearance_combo, self.network_combo, self.startup_combo):
            combo.setMinimumWidth(combo_width)
            combo.setMaximumWidth(combo_width)
        self.timeout_spin.setMinimumWidth(spin_width)
        self.timeout_spin.setMaximumWidth(spin_width)

        nav_height = 38 if compact else 40
        other_height = 38 if compact else 40
        self.back_button.setMinimumHeight(nav_height)
        self.back_button.setMaximumHeight(nav_height)
        self.back_button.setMinimumWidth(84)
        self.back_button.setMaximumWidth(84)
        for button in (self.reload_button, self.reset_button, self.save_button):
            button.setMinimumHeight(other_height)
            button.setMaximumHeight(other_height)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_responsive_layout()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.reload_settings()
        self._apply_responsive_layout()

    def reload_settings(self) -> None:
        self._snapshot = self._load_settings_snapshot()
        self._loaded_snapshot = deepcopy(self._snapshot)
        self._changed_since_load = False
        self._apply_snapshot_to_form(self._snapshot)
        self._update_runtime_badges()
        self.settings_loaded.emit(dict(self._snapshot))

    def _load_settings_snapshot(self) -> Dict[str, Any]:
        snapshot = deepcopy(DEFAULT_SETTINGS)

        try:
            settings_service = self.services.get("settings_service") or self.services.get("settings")
            if settings_service is not None:
                for method_name in ("get_settings", "load_settings", "current_settings", "snapshot", "get_snapshot"):
                    method = getattr(settings_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method()
                            if isinstance(raw, Mapping):
                                snapshot.update(dict(raw))
                                break
                        except Exception:
                            continue

                for getter_name in ("get_setting", "value", "get"):
                    getter = getattr(settings_service, getter_name, None)
                    if callable(getter):
                        try:
                            for key in DEFAULT_SETTINGS.keys():
                                value = getter(key)
                                if value not in (None, ""):
                                    snapshot[key] = value
                        except Exception:
                            continue
        except Exception:
            pass

        try:
            import config as project_config
            if hasattr(project_config, "DEFAULT_SETTINGS"):
                raw = getattr(project_config, "DEFAULT_SETTINGS")
                if isinstance(raw, Mapping):
                    snapshot.update(dict(raw))

            for config_key, target_key in (
                ("APP_APPEARANCE", "appearance"),
                ("DEFAULT_APPEARANCE", "appearance"),
                ("DEFAULT_BRIGHTNESS", "brightness"),
                ("SESSION_TIMEOUT", "timeout"),
                ("DEFAULT_TIMEOUT", "timeout"),
                ("DEFAULT_VOLUME", "volume"),
                ("NETWORK_MODE", "network_mode"),
                ("DEFAULT_NETWORK_MODE", "network_mode"),
                ("STARTUP_MODE", "startup_mode"),
                ("DEFAULT_STARTUP_MODE", "startup_mode"),
                ("SERIAL_AUTO_CONNECT", "serial_auto_connect"),
                ("TOUCH_SOUNDS_ENABLED", "touch_sounds_enabled"),
            ):
                if hasattr(project_config, config_key):
                    value = getattr(project_config, config_key)
                    if value not in (None, ""):
                        snapshot[target_key] = value
        except Exception:
            pass

        try:
            if self.app_state is not None:
                for attr_name, target_key in (
                    ("appearance", "appearance"),
                    ("brightness", "brightness"),
                    ("timeout", "timeout"),
                    ("volume", "volume"),
                    ("network_mode", "network_mode"),
                    ("startup_mode", "startup_mode"),
                    ("serial_auto_connect", "serial_auto_connect"),
                    ("touch_sounds_enabled", "touch_sounds_enabled"),
                ):
                    if hasattr(self.app_state, attr_name):
                        value = getattr(self.app_state, attr_name)
                        if value not in (None, ""):
                            snapshot[target_key] = value
        except Exception:
            pass

        snapshot["appearance"] = _normalize_appearance(snapshot.get("appearance"))
        snapshot["network_mode"] = _normalize_network_mode(snapshot.get("network_mode"))
        snapshot["startup_mode"] = _normalize_startup_mode(snapshot.get("startup_mode"))
        snapshot["brightness"] = max(10, min(100, safe_int(snapshot.get("brightness"), 100)))
        snapshot["timeout"] = max(15, min(600, safe_int(snapshot.get("timeout"), 90)))
        snapshot["volume"] = max(0, min(100, safe_int(snapshot.get("volume"), 70)))
        snapshot["serial_auto_connect"] = safe_bool(snapshot.get("serial_auto_connect"), True)
        snapshot["touch_sounds_enabled"] = safe_bool(snapshot.get("touch_sounds_enabled"), True)
        return snapshot

    def _apply_snapshot_to_form(self, snapshot: Mapping[str, Any]) -> None:
        appearance = _normalize_appearance(snapshot.get("appearance"))
        brightness = max(10, min(100, safe_int(snapshot.get("brightness"), 100)))
        timeout = max(15, min(600, safe_int(snapshot.get("timeout"), 90)))
        volume = max(0, min(100, safe_int(snapshot.get("volume"), 70)))
        network_mode = _normalize_network_mode(snapshot.get("network_mode"))
        startup_mode = _normalize_startup_mode(snapshot.get("startup_mode"))
        serial_auto = safe_bool(snapshot.get("serial_auto_connect"), True)
        touch_sounds = safe_bool(snapshot.get("touch_sounds_enabled"), True)

        self._set_combobox_data(self.appearance_combo, appearance)
        self.brightness_slider.blockSignals(True)
        self.brightness_slider.setValue(brightness)
        self.brightness_slider.blockSignals(False)
        self.brightness_value.setText(f"{brightness}%")
        self._preview_brightness = brightness
        self._apply_brightness_preview(brightness)

        self.timeout_spin.blockSignals(True)
        self.timeout_spin.setValue(timeout)
        self.timeout_spin.blockSignals(False)

        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(volume)
        self.volume_slider.blockSignals(False)
        self.volume_value.setText(f"{volume}%")

        self._set_combobox_data(self.network_combo, network_mode)
        self._set_combobox_data(self.startup_combo, startup_mode)

        self.serial_autoconnect_checkbox.blockSignals(True)
        self.serial_autoconnect_checkbox.setChecked(serial_auto)
        self.serial_autoconnect_checkbox.blockSignals(False)

        self.touch_sounds_checkbox.blockSignals(True)
        self.touch_sounds_checkbox.setChecked(touch_sounds)
        self.touch_sounds_checkbox.blockSignals(False)

        self._update_runtime_badges()

    def _set_combobox_data(self, combo: QComboBox, value: str) -> None:
        wanted = safe_str(value, "").strip().lower()
        for index in range(combo.count()):
            item_data = safe_str(combo.itemData(index), "").strip().lower()
            if item_data == wanted:
                combo.blockSignals(True)
                combo.setCurrentIndex(index)
                combo.blockSignals(False)
                return

    def _collect_form_settings(self) -> Dict[str, Any]:
        return {
            "appearance": _normalize_appearance(self.appearance_combo.currentData()),
            "brightness": int(self.brightness_slider.value()),
            "timeout": int(self.timeout_spin.value()),
            "volume": int(self.volume_slider.value()),
            "network_mode": _normalize_network_mode(self.network_combo.currentData()),
            "startup_mode": _normalize_startup_mode(self.startup_combo.currentData()),
            "serial_auto_connect": bool(self.serial_autoconnect_checkbox.isChecked()),
            "touch_sounds_enabled": bool(self.touch_sounds_checkbox.isChecked()),
        }

    def _on_brightness_changed(self, value: int) -> None:
        value = int(value)
        self.brightness_value.setText(f"{value}%")
        self._preview_brightness = value
        self._apply_brightness_preview(value)
        self._on_form_changed()

    def _on_volume_changed(self, value: int) -> None:
        self.volume_value.setText(f"{int(value)}%")
        self._on_form_changed()

    def _apply_brightness_preview(self, value: int) -> None:
        percentage = max(10, min(100, int(value)))
        opacity = 0.60 + (percentage / 100.0) * 0.40
        window = self.window()
        if window is not None:
            try:
                if self._saved_window_opacity is None:
                    self._saved_window_opacity = float(window.windowOpacity())
            except Exception:
                self._saved_window_opacity = 1.0

            try:
                window.setWindowOpacity(max(0.65, min(1.0, opacity)))
            except Exception:
                pass

        base_alpha = 185 - int((percentage - 10) * 0.8)
        base_alpha = max(92, min(210, base_alpha))
        self._live_overlay_alpha = base_alpha
        self.update()

    def _on_form_changed(self) -> None:
        self._snapshot = self._collect_form_settings()
        self._changed_since_load = self._snapshot != self._loaded_snapshot
        self._update_runtime_badges()
        self.settings_changed.emit(dict(self._snapshot))

    def _update_runtime_badges(self) -> None:
        current = self._snapshot if self._snapshot else self._collect_form_settings()

        appearance_label = APPEARANCE_LABELS.get(_normalize_appearance(current.get("appearance")), "Dark")
        network_label = NETWORK_MODE_LABELS.get(_normalize_network_mode(current.get("network_mode")), "Local")
        startup_label = STARTUP_MODE_LABELS.get(_normalize_startup_mode(current.get("startup_mode")), "Remember Last")
        status_text = "Unsaved" if self._changed_since_load else "Loaded"

        self.status_pill.setText(status_text)
        self.appearance_pill.setText(appearance_label)
        self.startup_pill.setText(startup_label)

        self._apply_pill_style(self.status_pill, _accent_for_state(status_text))
        self._apply_pill_style(self.appearance_pill, "#39D8FF")
        self._apply_pill_style(self.startup_pill, "#67D8FF")

        self.display_card.set_badge(f"{int(current['brightness'])}%")
        self.session_card.set_badge(f"{int(current['timeout'])} s / {int(current['volume'])}%")
        self.connectivity_card.set_badge(network_label)
        self.startup_card.set_badge(startup_label)

        self.display_card.set_accent("#39D8FF")
        self.session_card.set_accent("#E6C257")
        self.connectivity_card.set_accent("#885DFF")
        self.startup_card.set_accent("#2FD28C" if safe_bool(current.get("touch_sounds_enabled"), True) else "#FF6E88")

    def _handle_save_clicked(self) -> None:
        payload = self._collect_form_settings()
        self._persist_snapshot(payload)
        self._loaded_snapshot = deepcopy(payload)
        self._snapshot = deepcopy(payload)
        self._changed_since_load = False
        self._update_runtime_badges()
        self.settings_saved.emit(dict(payload))

    def _handle_reset_clicked(self) -> None:
        payload = deepcopy(DEFAULT_SETTINGS)
        self._apply_snapshot_to_form(payload)
        self._snapshot = deepcopy(payload)
        self._changed_since_load = True
        self._update_runtime_badges()
        self.settings_reset.emit(dict(payload))

    def _handle_back_clicked(self) -> None:
        if self._navigate_to(SCREEN_ADMIN_PANEL):
            return
        self.back_requested.emit()

    def _navigate_to(self, screen_name: str) -> bool:
        navigator = self.navigator
        if navigator is None:
            return False
        for method_name in ("go_to", "navigate_to", "navigate", "show_screen", "set_current_screen"):
            method = getattr(navigator, method_name, None)
            if callable(method):
                try:
                    method(screen_name)
                    return True
                except Exception:
                    continue
        return False

    def _persist_snapshot(self, payload: Mapping[str, Any]) -> None:
        normalized = dict(payload)

        try:
            settings_service = self.services.get("settings_service") or self.services.get("settings")
            if settings_service is not None:
                saved = False
                for method_name in (
                    "save_settings",
                    "update_settings",
                    "set_settings",
                    "persist_settings",
                    "write_settings",
                ):
                    method = getattr(settings_service, method_name, None)
                    if callable(method):
                        try:
                            method(dict(normalized))
                            saved = True
                            break
                        except Exception:
                            continue

                if not saved:
                    for method_name in ("set_setting", "set", "update_runtime_value"):
                        method = getattr(settings_service, method_name, None)
                        if callable(method):
                            try:
                                for key, value in normalized.items():
                                    method(key, value)
                                saved = True
                                break
                            except Exception:
                                continue
        except Exception:
            pass

        try:
            appearance = _normalize_appearance(normalized.get("appearance"))
            if self.theme_manager is not None:
                for method_name in ("set_theme", "apply_theme", "set_mode", "set_appearance"):
                    method = getattr(self.theme_manager, method_name, None)
                    if callable(method):
                        try:
                            method(appearance)
                            break
                        except Exception:
                            continue
        except Exception:
            pass

        try:
            if self.app_state is not None:
                for attr_name, value in (
                    ("appearance", normalized.get("appearance")),
                    ("brightness", normalized.get("brightness")),
                    ("timeout", normalized.get("timeout")),
                    ("volume", normalized.get("volume")),
                    ("network_mode", normalized.get("network_mode")),
                    ("startup_mode", normalized.get("startup_mode")),
                    ("serial_auto_connect", normalized.get("serial_auto_connect")),
                    ("touch_sounds_enabled", normalized.get("touch_sounds_enabled")),
                ):
                    if hasattr(self.app_state, attr_name):
                        try:
                            setattr(self.app_state, attr_name, value)
                        except Exception:
                            pass
        except Exception:
            pass

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

            rect = self.rect()

            if not self._background_pixmap.isNull():
                scaled = self._background_pixmap.scaled(
                    rect.size(),
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                draw_x = int((rect.width() - scaled.width()) / 2)
                draw_y = int((rect.height() - scaled.height()) / 2)
                painter.drawPixmap(draw_x, draw_y, scaled)

            overlay_alpha = getattr(self, "_live_overlay_alpha", 160)
            painter.fillRect(rect, QColor(5, 15, 30, overlay_alpha))
            painter.fillRect(QRectF(0.0, 0.0, float(rect.width()), rect.height() * 0.28), QColor(53, 214, 255, 10))
            painter.fillRect(QRectF(0.0, rect.height() * 0.62, float(rect.width()), rect.height() * 0.38), QColor(20, 82, 128, 12))
        finally:
            painter.end()

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "snapshot": dict(self._snapshot),
            "loaded_snapshot": dict(self._loaded_snapshot),
            "changed_since_load": bool(self._changed_since_load),
            "preview_brightness": int(self._preview_brightness),
            "background_path": self._background_path,
            "logo_path": self._logo_small_path,
        }
