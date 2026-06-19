"""
core/theme_manager.py

Central theme, palette, font, and shared stylesheet manager for the
CST Health Monitoring Station kiosk.

Why this file is important:
- Keeps the app visually consistent across all screens, widgets, and dialogs
- Supports both dark mode and light mode from the same codebase
- Loads optional bundled fonts from assets/fonts when available
- Provides reusable style builders for buttons, cards, inputs, tiles, labels, headers, etc.
- Works with AppState so theme changes propagate across the kiosk
- Supports laptop demo mode and Raspberry Pi deployment with graceful fallbacks

Design goals:
- Stable and reusable
- Easy for later widgets/screens to consume
- Safe if fonts/assets are missing
- Avoid hardcoding styles repeatedly across the project
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QColor, QFontDatabase, QPalette
from PyQt6.QtWidgets import QApplication, QWidget

from config import get_font_candidates
from core.asset_paths import (
    get_inter_bold_font_path,
    get_inter_regular_font_path,
    get_orbitron_semibold_font_path,
)
from core.constants import (
    BUTTON_RADIUS,
    CARD_RADIUS,
    DEFAULT_WINDOW_TITLE,
    INPUT_RADIUS,
    METRIC_TILE_RADIUS,
    PANEL_RADIUS,
    THEME_DARK,
    THEME_LIGHT,
    THEME_PALETTE_DARK,
    THEME_PALETTE_LIGHT,
)
from core.logger import get_logger

logger = get_logger(__name__)


# ============================================================
# Dataclasses
# ============================================================

@dataclass(frozen=True)
class FontSet:
    """
    Resolved font family bundle used throughout the kiosk.
    """
    body: str
    body_bold: str
    heading: str
    numeric: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "body": self.body,
            "body_bold": self.body_bold,
            "heading": self.heading,
            "numeric": self.numeric,
        }


@dataclass(frozen=True)
class ThemeDefinition:
    """
    Theme definition for the kiosk.
    """
    name: str
    palette: Dict[str, str]

    def get(self, key: str, default: str = "") -> str:
        return self.palette.get(key, default)


# ============================================================
# Theme Manager
# ============================================================

class ThemeManager(QObject):
    """
    Central manager for:
    - theme selection
    - font loading
    - palette building
    - global stylesheets
    - reusable component styles

    Expected usage later:
        theme_manager = get_theme_manager(app_state=state, app=app)
        theme_manager.apply_theme()

        widget.setStyleSheet(theme_manager.get_primary_button_style())
        label.setStyleSheet(theme_manager.get_label_style("primary"))
    """

    theme_applied = pyqtSignal(str)
    fonts_loaded = pyqtSignal(dict)

    def __init__(self, app_state: Optional[QObject] = None, app: Optional[QApplication] = None) -> None:
        super().__init__()

        self._logger = logger.bind(component="ThemeManager")
        self._app: Optional[QApplication] = app
        self._app_state: Optional[QObject] = None

        self._theme_definitions: Dict[str, ThemeDefinition] = {
            THEME_DARK: ThemeDefinition(name=THEME_DARK, palette=dict(THEME_PALETTE_DARK)),
            THEME_LIGHT: ThemeDefinition(name=THEME_LIGHT, palette=dict(THEME_PALETTE_LIGHT)),
        }

        self._current_theme_name: str = THEME_DARK
        self._fonts: FontSet = FontSet(
            body="Segoe UI",
            body_bold="Segoe UI",
            heading="Segoe UI",
            numeric="Segoe UI",
        )
        self._loaded_font_families: Dict[str, str] = {}

        self.load_custom_fonts()
        self.register_with_app_state(app_state)

    # ========================================================
    # Registration / wiring
    # ========================================================

    def register_with_app_state(self, app_state: Optional[QObject]) -> None:
        """
        Connect theme manager to AppState, if provided.
        """
        if app_state is None:
            return

        self._app_state = app_state

        # Pull initial theme from app state if possible
        try:
            ui_snapshot = getattr(app_state, "ui_snapshot", None)
            if callable(ui_snapshot):
                ui = ui_snapshot()
                theme = str(ui.get("theme_mode", THEME_DARK)).lower().strip()
                if theme in self._theme_definitions:
                    self._current_theme_name = theme
        except Exception as exc:
            self._logger.warning("Could not read initial theme from app_state: %s", exc)

        # Connect if the signal exists
        try:
            signal = getattr(app_state, "theme_changed", None)
            if signal is not None:
                signal.connect(self._handle_external_theme_change)
        except Exception as exc:
            self._logger.warning("Could not connect to app_state.theme_changed: %s", exc)

    def set_application(self, app: QApplication) -> None:
        self._app = app

    # ========================================================
    # Font handling
    # ========================================================

    def load_custom_fonts(self) -> Dict[str, str]:
        """
        Load optional custom fonts from assets/fonts.
        If unavailable, gracefully fall back to safe system fonts.
        """
        loaded: Dict[str, str] = {}

        # Safe fallbacks
        fallback_candidates = get_font_candidates()
        fallback_body = fallback_candidates[0] if fallback_candidates else "Segoe UI"
        fallback_heading = fallback_candidates[0] if fallback_candidates else "Segoe UI"
        fallback_numeric = fallback_candidates[0] if fallback_candidates else "Segoe UI"

        inter_regular = self._load_single_font(get_inter_regular_font_path(), fallback_body)
        inter_bold = self._load_single_font(get_inter_bold_font_path(), inter_regular)
        orbitron = self._load_single_font(get_orbitron_semibold_font_path(), fallback_heading)

        loaded["inter_regular"] = inter_regular
        loaded["inter_bold"] = inter_bold
        loaded["orbitron_semibold"] = orbitron

        self._fonts = FontSet(
            body=inter_regular,
            body_bold=inter_bold,
            heading=orbitron or inter_bold or inter_regular or fallback_heading,
            numeric=orbitron or inter_bold or inter_regular or fallback_numeric,
        )
        self._loaded_font_families = loaded

        self._logger.info("Font families resolved: %s", loaded)
        self.fonts_loaded.emit(self._fonts.to_dict())
        return dict(loaded)

    def _load_single_font(self, path: Path, fallback_family: str) -> str:
        """
        Load one font file and return the resolved family name.
        """
        try:
            if path.exists():
                font_id = QFontDatabase.addApplicationFont(str(path))
                if font_id != -1:
                    families = QFontDatabase.applicationFontFamilies(font_id)
                    if families:
                        return families[0]
        except Exception as exc:
            self._logger.warning("Failed to load font %s: %s", path, exc)

        return fallback_family

    def font_family_body(self) -> str:
        return self._fonts.body

    def font_family_body_bold(self) -> str:
        return self._fonts.body_bold

    def font_family_heading(self) -> str:
        return self._fonts.heading

    def font_family_numeric(self) -> str:
        return self._fonts.numeric

    def font_set(self) -> FontSet:
        return self._fonts

    # ========================================================
    # Theme state
    # ========================================================

    def current_theme_name(self) -> str:
        return self._current_theme_name

    def is_dark_mode(self) -> bool:
        return self._current_theme_name == THEME_DARK

    def is_light_mode(self) -> bool:
        return self._current_theme_name == THEME_LIGHT

    def current_theme(self) -> ThemeDefinition:
        return self._theme_definitions.get(self._current_theme_name, self._theme_definitions[THEME_DARK])

    def palette_dict(self) -> Dict[str, str]:
        return dict(self.current_theme().palette)

    def get_color(self, key: str, default: str = "#FFFFFF") -> str:
        return self.current_theme().get(key, default)

    def set_theme(self, theme_name: str, apply_immediately: bool = True) -> None:
        """
        Set and optionally apply a new theme.
        """
        theme_name = str(theme_name).strip().lower()
        if theme_name not in self._theme_definitions:
            theme_name = THEME_DARK

        if theme_name == self._current_theme_name and not apply_immediately:
            return

        self._current_theme_name = theme_name
        self._logger.info("Theme set to %s", theme_name)

        if apply_immediately:
            self.apply_theme(theme_name=theme_name)

    def toggle_theme(self) -> str:
        new_theme = THEME_LIGHT if self.is_dark_mode() else THEME_DARK
        self.set_theme(new_theme, apply_immediately=True)
        return new_theme

    def _handle_external_theme_change(self, theme_name: str) -> None:
        """
        Called when AppState emits theme_changed.
        """
        normalized = str(theme_name).strip().lower()
        if normalized not in self._theme_definitions:
            normalized = THEME_DARK

        if normalized != self._current_theme_name:
            self._current_theme_name = normalized
            self.apply_theme(theme_name=normalized)

    # ========================================================
    # Application-level theme application
    # ========================================================

    def apply_theme(
        self,
        app: Optional[QApplication] = None,
        theme_name: Optional[str] = None,
    ) -> None:
        """
        Apply the current or specified theme to the entire QApplication.
        """
        if app is not None:
            self._app = app

        if theme_name:
            normalized = str(theme_name).strip().lower()
            if normalized in self._theme_definitions:
                self._current_theme_name = normalized

        target_app = self._app or QApplication.instance()
        if target_app is None:
            self._logger.warning("No QApplication available yet; theme stored but not applied.")
            return

        palette = self.build_qpalette(self.current_theme())
        stylesheet = self.build_global_stylesheet(self.current_theme())

        target_app.setPalette(palette)
        target_app.setStyleSheet(stylesheet)
        target_app.setApplicationName(DEFAULT_WINDOW_TITLE)

        self._logger.info("Theme applied to QApplication: %s", self._current_theme_name)
        self.theme_applied.emit(self._current_theme_name)

    def apply_widget_theme(self, widget: QWidget) -> None:
        """
        Apply global kiosk style to one widget.
        Useful for top-level screens if needed.
        """
        if widget is None:
            return
        widget.setStyleSheet(self.build_global_stylesheet(self.current_theme()))

    # ========================================================
    # Qt palette builder
    # ========================================================

    def build_qpalette(self, theme: ThemeDefinition) -> QPalette:
        palette = QPalette()

        window_bg = QColor(theme.get("window_bg", "#07162F"))
        panel_bg = QColor(theme.get("panel_bg", "#0B1F3C"))
        text_primary = QColor(theme.get("text_primary", "#F5FAFF"))
        text_secondary = QColor(theme.get("text_secondary", "#C4D4EF"))
        accent = QColor(theme.get("accent", "#34D6FF"))
        danger = QColor(theme.get("danger", "#FF5A6F"))
        button_bg = QColor(theme.get("card_bg", "#12305D"))
        input_bg = QColor(theme.get("input_bg", "#102B52"))

        palette.setColor(QPalette.ColorRole.Window, window_bg)
        palette.setColor(QPalette.ColorRole.WindowText, text_primary)
        palette.setColor(QPalette.ColorRole.Base, input_bg)
        palette.setColor(QPalette.ColorRole.AlternateBase, panel_bg)
        palette.setColor(QPalette.ColorRole.ToolTipBase, panel_bg)
        palette.setColor(QPalette.ColorRole.ToolTipText, text_primary)
        palette.setColor(QPalette.ColorRole.Text, text_primary)
        palette.setColor(QPalette.ColorRole.Button, button_bg)
        palette.setColor(QPalette.ColorRole.ButtonText, text_primary)
        palette.setColor(QPalette.ColorRole.BrightText, danger)
        palette.setColor(QPalette.ColorRole.Link, accent)
        palette.setColor(QPalette.ColorRole.Highlight, accent)
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#051421"))

        # Disabled colors
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, text_secondary)
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, text_secondary)
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, text_secondary)

        return palette

    # ========================================================
    # Global stylesheet
    # ========================================================

    def build_global_stylesheet(self, theme: Optional[ThemeDefinition] = None) -> str:
        """
        Build the app-wide stylesheet for QApplication.
        """
        theme = theme or self.current_theme()
        p = theme.palette
        f = self._fonts

        return f"""
        QWidget {{
            background-color: {p["window_bg"]};
            color: {p["text_primary"]};
            font-family: "{f.body}";
            font-size: 14px;
            selection-background-color: {p["accent"]};
            selection-color: #051421;
        }}

        QLabel {{
            background: transparent;
            color: {p["text_primary"]};
            font-family: "{f.body}";
        }}

        QFrame {{
            background: transparent;
            border: none;
        }}

        QPushButton {{
            background-color: {p["card_bg"]};
            color: {p["text_primary"]};
            border: 1px solid {p["border"]};
            border-radius: {BUTTON_RADIUS}px;
            padding: 10px 16px;
            font-family: "{f.body_bold}";
            font-size: 14px;
        }}

        QPushButton:hover {{
            border: 1px solid {p["accent"]};
            background-color: {self._mix_color(p["card_bg"], p["accent"], 0.10)};
        }}

        QPushButton:pressed {{
            background-color: {self._mix_color(p["card_bg"], p["accent"], 0.18)};
        }}

        QPushButton:disabled {{
            color: {p["text_muted"]};
            border: 1px solid {self._alpha_or_default(p["border"], 0.18)};
            background-color: {self._alpha_or_default(p["card_bg"], 0.60)};
        }}

        QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {{
            background-color: {p["input_bg"]};
            color: {p["text_primary"]};
            border: 1px solid {p["border"]};
            border-radius: {INPUT_RADIUS}px;
            padding: 10px 12px;
            font-family: "{f.body}";
            font-size: 14px;
        }}

        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
            border: 1px solid {p["accent"]};
        }}

        QComboBox {{
            background-color: {p["input_bg"]};
            color: {p["text_primary"]};
            border: 1px solid {p["border"]};
            border-radius: {INPUT_RADIUS}px;
            padding: 8px 12px;
            min-height: 20px;
        }}

        QComboBox:hover {{
            border: 1px solid {p["accent"]};
        }}

        QComboBox QAbstractItemView {{
            background-color: {p["panel_bg"]};
            color: {p["text_primary"]};
            border: 1px solid {p["border"]};
            selection-background-color: {p["accent"]};
            selection-color: #051421;
            outline: none;
        }}

        QCheckBox, QRadioButton {{
            color: {p["text_primary"]};
            spacing: 8px;
            font-family: "{f.body}";
            font-size: 14px;
        }}

        QGroupBox {{
            color: {p["text_primary"]};
            font-family: "{f.body_bold}";
            font-size: 15px;
            border: 1px solid {p["border"]};
            border-radius: {PANEL_RADIUS}px;
            margin-top: 14px;
            padding-top: 16px;
            background-color: {p["card_bg_soft"]};
        }}

        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 14px;
            padding: 0 6px;
            color: {p["accent_soft"]};
        }}

        QProgressBar {{
            background-color: {self._alpha_or_default(p["panel_bg"], 0.90)};
            border: 1px solid {p["border"]};
            border-radius: 10px;
            text-align: center;
            color: {p["text_primary"]};
            min-height: 16px;
            max-height: 16px;
        }}

        QProgressBar::chunk {{
            border-radius: 9px;
            background-color: {p["accent"]};
        }}

        QSlider::groove:horizontal {{
            height: 8px;
            background: {self._alpha_or_default(p["panel_bg"], 0.95)};
            border-radius: 4px;
        }}

        QSlider::handle:horizontal {{
            background: {p["accent"]};
            border: 1px solid {p["accent_soft"]};
            width: 18px;
            margin: -6px 0;
            border-radius: 9px;
        }}

        QScrollBar:vertical {{
            background: transparent;
            width: 12px;
            margin: 4px;
        }}

        QScrollBar::handle:vertical {{
            background: {self._alpha_or_default(p["accent"], 0.55)};
            min-height: 28px;
            border-radius: 6px;
        }}

        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: none;
            border: none;
            height: 0;
        }}

        QTabWidget::pane {{
            border: 1px solid {p["border"]};
            background: {p["card_bg_soft"]};
            border-radius: 18px;
            top: -1px;
        }}

        QTabBar::tab {{
            background: {self._alpha_or_default(p["panel_bg"], 0.85)};
            color: {p["text_secondary"]};
            padding: 10px 16px;
            margin-right: 6px;
            border-top-left-radius: 12px;
            border-top-right-radius: 12px;
        }}

        QTabBar::tab:selected {{
            background: {p["card_bg"]};
            color: {p["text_primary"]};
            border: 1px solid {p["border"]};
        }}

        QToolTip {{
            background-color: {p["panel_bg"]};
            color: {p["text_primary"]};
            border: 1px solid {p["border"]};
            padding: 8px 10px;
            border-radius: 8px;
        }}
        """

    # ========================================================
    # Reusable component styles
    # ========================================================

    def get_window_style(self) -> str:
        p = self.palette_dict()
        return f"""
        QWidget {{
            background-color: {p["window_bg"]};
            color: {p["text_primary"]};
        }}
        """

    def get_glass_card_style(self, radius: int = CARD_RADIUS, stronger: bool = False) -> str:
        p = self.palette_dict()
        bg = p["card_bg"] if stronger else p["card_bg_soft"]
        return f"""
        QFrame {{
            background-color: {bg};
            border: 1px solid {p["border"]};
            border-radius: {radius}px;
        }}
        """

    def get_primary_button_style(self) -> str:
        p = self.palette_dict()
        f = self.font_set()
        return f"""
        QPushButton {{
            background-color: {p["accent"]};
            color: #051421;
            border: 1px solid {p["accent_soft"]};
            border-radius: {BUTTON_RADIUS}px;
            padding: 12px 18px;
            font-family: "{f.body_bold}";
            font-size: 15px;
            font-weight: 700;
        }}
        QPushButton:hover {{
            background-color: {self._lighten_hex(p["accent"], 0.10)};
            border: 1px solid {p["accent_soft"]};
        }}
        QPushButton:pressed {{
            background-color: {self._darken_hex(p["accent"], 0.08)};
        }}
        QPushButton:disabled {{
            background-color: {self._alpha_or_default(p["accent"], 0.35)};
            color: {p["text_muted"]};
            border: 1px solid {self._alpha_or_default(p["accent"], 0.20)};
        }}
        """

    def get_secondary_button_style(self) -> str:
        p = self.palette_dict()
        f = self.font_set()
        return f"""
        QPushButton {{
            background-color: {p["card_bg"]};
            color: {p["text_primary"]};
            border: 1px solid {p["border"]};
            border-radius: {BUTTON_RADIUS}px;
            padding: 12px 18px;
            font-family: "{f.body_bold}";
            font-size: 14px;
        }}
        QPushButton:hover {{
            border: 1px solid {p["accent"]};
            background-color: {self._mix_color(p["card_bg"], p["accent"], 0.10)};
        }}
        QPushButton:pressed {{
            background-color: {self._mix_color(p["card_bg"], p["accent"], 0.18)};
        }}
        """

    def get_danger_button_style(self) -> str:
        p = self.palette_dict()
        f = self.font_set()
        return f"""
        QPushButton {{
            background-color: {p["danger"]};
            color: white;
            border: 1px solid {self._lighten_hex(p["danger"], 0.08)};
            border-radius: {BUTTON_RADIUS}px;
            padding: 12px 18px;
            font-family: "{f.body_bold}";
            font-size: 14px;
        }}
        QPushButton:hover {{
            background-color: {self._lighten_hex(p["danger"], 0.08)};
        }}
        QPushButton:pressed {{
            background-color: {self._darken_hex(p["danger"], 0.10)};
        }}
        """

    def get_icon_button_style(self, compact: bool = False) -> str:
        p = self.palette_dict()
        f = self.font_set()
        padding = "8px 12px" if compact else "10px 14px"
        return f"""
        QPushButton {{
            background-color: {p["card_bg_soft"]};
            color: {p["text_primary"]};
            border: 1px solid {p["border"]};
            border-radius: {BUTTON_RADIUS}px;
            padding: {padding};
            font-family: "{f.body_bold}";
            font-size: 14px;
            text-align: left;
        }}
        QPushButton:hover {{
            border: 1px solid {p["accent"]};
            background-color: {self._mix_color(p["card_bg"], p["accent"], 0.12)};
        }}
        """

    def get_input_style(self) -> str:
        p = self.palette_dict()
        f = self.font_set()
        return f"""
        QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {{
            background-color: {p["input_bg"]};
            color: {p["text_primary"]};
            border: 1px solid {p["border"]};
            border-radius: {INPUT_RADIUS}px;
            padding: 10px 12px;
            font-family: "{f.body}";
            font-size: 14px;
        }}
        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
            border: 1px solid {p["accent"]};
        }}
        """

    def get_combo_style(self) -> str:
        p = self.palette_dict()
        f = self.font_set()
        return f"""
        QComboBox {{
            background-color: {p["input_bg"]};
            color: {p["text_primary"]};
            border: 1px solid {p["border"]};
            border-radius: {INPUT_RADIUS}px;
            padding: 8px 12px;
            font-family: "{f.body}";
            font-size: 14px;
        }}
        QComboBox:hover {{
            border: 1px solid {p["accent"]};
        }}
        QComboBox::drop-down {{
            border: none;
            width: 24px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {p["panel_bg"]};
            color: {p["text_primary"]};
            border: 1px solid {p["border"]};
            selection-background-color: {p["accent"]};
            selection-color: #051421;
            outline: none;
        }}
        """

    def get_progress_bar_style(self) -> str:
        p = self.palette_dict()
        return f"""
        QProgressBar {{
            background-color: {self._alpha_or_default(p["panel_bg"], 0.95)};
            border: 1px solid {p["border"]};
            border-radius: 10px;
            text-align: center;
            color: {p["text_primary"]};
            min-height: 18px;
            max-height: 18px;
            font-weight: 600;
        }}
        QProgressBar::chunk {{
            background-color: {p["accent"]};
            border-radius: 9px;
        }}
        """

    def get_slider_style(self) -> str:
        p = self.palette_dict()
        return f"""
        QSlider::groove:horizontal {{
            height: 8px;
            background: {self._alpha_or_default(p["panel_bg"], 0.95)};
            border-radius: 4px;
        }}
        QSlider::handle:horizontal {{
            background: {p["accent"]};
            border: 1px solid {p["accent_soft"]};
            width: 18px;
            margin: -6px 0;
            border-radius: 9px;
        }}
        QSlider::sub-page:horizontal {{
            background: {p["accent"]};
            border-radius: 4px;
        }}
        """

    def get_header_style(self) -> str:
        p = self.palette_dict()
        f = self.font_set()
        return f"""
        QFrame {{
            background-color: {self._alpha_or_default(p["card_bg"], 0.90)};
            border: 1px solid {p["border"]};
            border-radius: {PANEL_RADIUS}px;
        }}
        QLabel {{
            color: {p["text_primary"]};
            font-family: "{f.heading}";
        }}
        """

    def get_metric_tile_style(self, highlighted: bool = False) -> str:
        p = self.palette_dict()
        f = self.font_set()
        border = p["accent"] if highlighted else p["border"]
        bg = self._mix_color(p["card_bg"], p["accent"], 0.14) if highlighted else p["card_bg_soft"]
        return f"""
        QFrame {{
            background-color: {bg};
            border: 1px solid {border};
            border-radius: {METRIC_TILE_RADIUS}px;
        }}
        QLabel {{
            background: transparent;
            color: {p["text_primary"]};
            font-family: "{f.body}";
        }}
        """

    def get_status_card_style(self, severity: str = "normal") -> str:
        p = self.palette_dict()

        accent = p["success"]
        if severity in {"attention", "warning"}:
            accent = p["warning"]
        elif severity in {"critical", "danger"}:
            accent = p["danger"]
        elif severity == "info":
            accent = p["accent"]

        return f"""
        QFrame {{
            background-color: {self._mix_color(p["card_bg"], accent, 0.12)};
            border: 1px solid {accent};
            border-radius: {CARD_RADIUS}px;
        }}
        """

    def get_label_style(self, kind: str = "primary") -> str:
        p = self.palette_dict()
        f = self.font_set()

        if kind == "heading":
            return f"""
            QLabel {{
                color: {p["text_primary"]};
                font-family: "{f.heading}";
                font-size: 24px;
                font-weight: 700;
                background: transparent;
            }}
            """
        if kind == "subheading":
            return f"""
            QLabel {{
                color: {p["accent_soft"]};
                font-family: "{f.body_bold}";
                font-size: 16px;
                font-weight: 600;
                background: transparent;
            }}
            """
        if kind == "secondary":
            return f"""
            QLabel {{
                color: {p["text_secondary"]};
                font-family: "{f.body}";
                font-size: 14px;
                background: transparent;
            }}
            """
        if kind == "muted":
            return f"""
            QLabel {{
                color: {p["text_muted"]};
                font-family: "{f.body}";
                font-size: 13px;
                background: transparent;
            }}
            """
        if kind == "numeric":
            return f"""
            QLabel {{
                color: {p["text_primary"]};
                font-family: "{f.numeric}";
                font-size: 24px;
                font-weight: 700;
                background: transparent;
            }}
            """

        return f"""
        QLabel {{
            color: {p["text_primary"]};
            font-family: "{f.body}";
            font-size: 14px;
            background: transparent;
        }}
        """

    def get_group_title_style(self) -> str:
        p = self.palette_dict()
        f = self.font_set()
        return f"""
        QLabel {{
            color: {p["accent_soft"]};
            font-family: "{f.body_bold}";
            font-size: 15px;
            font-weight: 700;
            background: transparent;
            padding: 2px 0;
        }}
        """

    def get_scrollbar_style(self) -> str:
        p = self.palette_dict()
        return f"""
        QScrollBar:vertical {{
            background: transparent;
            width: 12px;
            margin: 4px;
        }}
        QScrollBar::handle:vertical {{
            background: {self._alpha_or_default(p["accent"], 0.55)};
            min-height: 28px;
            border-radius: 6px;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: none;
            border: none;
            height: 0;
        }}
        """

    def get_tooltip_style(self) -> str:
        p = self.palette_dict()
        return f"""
        QToolTip {{
            background-color: {p["panel_bg"]};
            color: {p["text_primary"]};
            border: 1px solid {p["border"]};
            padding: 8px 10px;
            border-radius: 8px;
        }}
        """

    def get_tab_style(self) -> str:
        p = self.palette_dict()
        return f"""
        QTabWidget::pane {{
            border: 1px solid {p["border"]};
            background: {p["card_bg_soft"]};
            border-radius: 18px;
            top: -1px;
        }}
        QTabBar::tab {{
            background: {self._alpha_or_default(p["panel_bg"], 0.85)};
            color: {p["text_secondary"]};
            padding: 10px 16px;
            margin-right: 6px;
            border-top-left-radius: 12px;
            border-top-right-radius: 12px;
        }}
        QTabBar::tab:selected {{
            background: {p["card_bg"]};
            color: {p["text_primary"]};
            border: 1px solid {p["border"]};
        }}
        """

    # ========================================================
    # Specialized visual helpers for later widgets/screens
    # ========================================================

    def get_background_overlay_rgba(self, brightness_percent: int) -> str:
        """
        Approximate screen brightness by controlling a translucent overlay.
        Lower brightness => darker overlay.
        """
        brightness_percent = max(0, min(int(brightness_percent), 100))
        darkness_alpha = int((100 - brightness_percent) * 1.4)
        darkness_alpha = max(0, min(darkness_alpha, 140))
        return f"rgba(0, 0, 0, {darkness_alpha})"

    def get_connection_badge_style(self, connected: bool = False, waiting: bool = False) -> str:
        p = self.palette_dict()

        if connected:
            accent = p["success"]
        elif waiting:
            accent = p["warning"]
        else:
            accent = p["danger"]

        return f"""
        QFrame {{
            background-color: {self._alpha_or_default(accent, 0.18)};
            border: 1px solid {accent};
            border-radius: 14px;
        }}
        QLabel {{
            color: {accent};
            background: transparent;
            font-weight: 700;
        }}
        """

    def get_highlight_box_style(self, active_color: str, active: bool) -> str:
        p = self.palette_dict()
        if active:
            return f"""
            QFrame {{
                background-color: {self._alpha_or_default(active_color, 0.20)};
                border: 1px solid {active_color};
                border-radius: 16px;
            }}
            QLabel {{
                color: {active_color};
                background: transparent;
                font-weight: 700;
            }}
            """
        return f"""
        QFrame {{
            background-color: {self._alpha_or_default(p["panel_bg"], 0.75)};
            border: 1px solid {self._alpha_or_default(p["border"], 0.55)};
            border-radius: 16px;
        }}
        QLabel {{
            color: {p["text_muted"]};
            background: transparent;
        }}
        """

    # ========================================================
    # Color helpers
    # ========================================================

    def _lighten_hex(self, hex_color: str, factor: float = 0.10) -> str:
        color = QColor(hex_color)
        if not color.isValid():
            return hex_color
        factor = max(0.0, min(factor, 1.0))
        r = color.red()
        g = color.green()
        b = color.blue()
        r = int(r + (255 - r) * factor)
        g = int(g + (255 - g) * factor)
        b = int(b + (255 - b) * factor)
        return QColor(r, g, b, color.alpha()).name()

    def _darken_hex(self, hex_color: str, factor: float = 0.10) -> str:
        color = QColor(hex_color)
        if not color.isValid():
            return hex_color
        factor = max(0.0, min(factor, 1.0))
        r = int(color.red() * (1.0 - factor))
        g = int(color.green() * (1.0 - factor))
        b = int(color.blue() * (1.0 - factor))
        return QColor(r, g, b, color.alpha()).name()

    def _mix_color(self, color_a: str, color_b: str, ratio_b: float = 0.50) -> str:
        qa = QColor(color_a)
        qb = QColor(color_b)
        if not qa.isValid():
            return color_b if qb.isValid() else "#000000"
        if not qb.isValid():
            return color_a

        ratio_b = max(0.0, min(ratio_b, 1.0))
        ratio_a = 1.0 - ratio_b

        r = int(qa.red() * ratio_a + qb.red() * ratio_b)
        g = int(qa.green() * ratio_a + qb.green() * ratio_b)
        b = int(qa.blue() * ratio_a + qb.blue() * ratio_b)
        a = int(qa.alpha() * ratio_a + qb.alpha() * ratio_b)

        return QColor(r, g, b, a).name(QColor.NameFormat.HexArgb)

    def _alpha_or_default(self, color_value: str, alpha_ratio: float = 1.0) -> str:
        """
        Convert a hex/rgb-capable color into rgba-like hex with alpha.
        """
        color = QColor(color_value)
        if not color.isValid():
            return color_value

        alpha_ratio = max(0.0, min(alpha_ratio, 1.0))
        color.setAlpha(int(255 * alpha_ratio))
        return color.name(QColor.NameFormat.HexArgb)

    # ========================================================
    # Diagnostics / snapshots
    # ========================================================

    def theme_snapshot(self) -> Dict[str, Any]:
        return {
            "current_theme": self._current_theme_name,
            "fonts": self._fonts.to_dict(),
            "palette": self.palette_dict(),
        }

    def available_themes(self) -> List[str]:
        return list(self._theme_definitions.keys())

    def loaded_fonts(self) -> Dict[str, str]:
        return dict(self._loaded_font_families)


# ============================================================
# Shared singleton accessor
# ============================================================

_THEME_MANAGER_SINGLETON: Optional[ThemeManager] = None


def get_theme_manager(
    app_state: Optional[QObject] = None,
    app: Optional[QApplication] = None,
) -> ThemeManager:
    global _THEME_MANAGER_SINGLETON
    if _THEME_MANAGER_SINGLETON is None:
        _THEME_MANAGER_SINGLETON = ThemeManager(app_state=app_state, app=app)
    else:
        if app is not None:
            _THEME_MANAGER_SINGLETON.set_application(app)
        if app_state is not None:
            _THEME_MANAGER_SINGLETON.register_with_app_state(app_state)
    return _THEME_MANAGER_SINGLETON