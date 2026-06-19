"""
screens/admin_login_screen.py

Premium admin login screen for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the protected gateway into the administrator workflow
- It is the entry point to:
    - screens/admin_panel_screen.py
- It is designed specifically for:
    - Raspberry Pi 4B touchscreen kiosk deployment
    - 800x480 compact kiosk resolution
    - laptop demo mode
- It provides:
    - premium glossy login experience
    - resilient credential loading from settings/config
    - safe local lockout after repeated failed attempts
    - touch-friendly keypad support for kiosk use
    - keyboard support for laptop demo/testing
    - navigation handoff to the admin panel

Linked project files this screen is intended to work with:
- config.py
- core/constants.py
- core/asset_paths.py
- core/logger.py
- core/app_state.py
- core/navigator.py
- core/theme_manager.py
- core/animation_manager.py
- services/settings_service.py
- widgets/animated_button.py
- widgets/glow_label.py

Design goals:
- glossy futuristic blue medical UI
- strong security / protected-access feel
- clear feedback for success, failure, and lockout
- resilient integration while the rest of the app evolves
- maintainable structure and safe fallbacks
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QRectF,
    QTimer,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
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
    from core.constants import (
        SCREEN_ADMIN_PANEL,
        SCREEN_WELCOME,
    )
except Exception:  # pragma: no cover
    SCREEN_ADMIN_PANEL = "admin_panel"
    SCREEN_WELCOME = "welcome"

try:
    from widgets.animated_button import AnimatedButton
except Exception:  # pragma: no cover
    AnimatedButton = None  # type: ignore

try:
    from widgets.glow_label import GlowLabel
    _HAS_GLOW_LABEL = True
except Exception:  # pragma: no cover
    GlowLabel = QLabel  # type: ignore
    _HAS_GLOW_LABEL = False


logger = get_logger(__name__)


# =============================================================================
# Helpers
# =============================================================================

def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_asset(relative_path: str) -> str:
    """
    Resolve asset path using core.asset_paths if available, otherwise fallback
    to project-relative assets directory.
    """
    relative_clean = safe_str(relative_path, "").strip().replace("\\", "/").lstrip("/")
    if not relative_clean:
        return ""

    try:
        import core.asset_paths as asset_paths  # local import on purpose

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


def _looks_like_sha256_hex(value: str) -> bool:
    text = safe_str(value, "").strip().lower()
    return bool(re.fullmatch(r"[0-9a-f]{64}", text))


# =============================================================================
# Main screen
# =============================================================================

class AdminLoginScreen(QFrame):
    """
    Premium admin login screen with:
    - username/password fields
    - touch-friendly keypad
    - show/hide password
    - lockout after repeated failures
    - navigation to admin panel on success
    """

    back_requested = pyqtSignal()
    login_attempted = pyqtSignal(str)
    login_succeeded = pyqtSignal(dict)
    login_failed = pyqtSignal(str)

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

        self._logger = logger.bind(component="AdminLoginScreen")

        self.navigator = navigator
        self.app_state = app_state
        self.services = dict(services or {})
        self.animation_manager = animation_manager
        self.theme_manager = theme_manager

        self._background_path = _resolve_asset("backgrounds/admin_login_bg.png")
        self._logo_small_path = _resolve_asset("logos/10__2850_29-removebg-preview.png")
        self._shield_art_path = _resolve_asset("illustrations/admin_shield.png")
        self._lock_icon_path = _resolve_asset("icons/admin_lock.png")
        self._login_icon_path = _resolve_asset("icons/login.png")

        self._background_pixmap = _pixmap_or_empty(self._background_path)
        self._logo_pixmap = _pixmap_or_empty(self._logo_small_path)
        self._shield_pixmap = _pixmap_or_empty(self._shield_art_path)
        self._lock_pixmap = _pixmap_or_empty(self._lock_icon_path)

        self._failed_attempts = 0
        self._lockout_seconds_remaining = 0
        self._max_failed_attempts = 3
        self._lockout_seconds = 15
        self._last_login_message = "Administrator access is protected."

        self._compact_width_threshold = 1150
        self._ultra_compact_width_threshold = 980
        self._compact_height_threshold = 700
        self._ultra_compact_height_threshold = 620
        self._compact_login_layout = False

        self._lockout_timer = QTimer(self)
        self._lockout_timer.setInterval(1000)
        self._lockout_timer.timeout.connect(self._handle_lockout_tick)

        self.setObjectName("AdminLoginScreen")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._build_ui()
        self._setup_effects()
        self._apply_styles()
        self._apply_compact_layout()

        self._update_access_status()
        self._play_entry_animation()

    # =========================================================================
    # UI
    # =========================================================================

    def _build_ui(self) -> None:
        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(14, 10, 14, 10)
        self.root_layout.setSpacing(8)

        # ---------------------------------------------------------------------
        # Top bar
        # ---------------------------------------------------------------------
        self.top_bar = QWidget(self)
        self.top_layout = QHBoxLayout(self.top_bar)
        self.top_layout.setContentsMargins(0, 0, 0, 0)
        self.top_layout.setSpacing(8)

        self.back_button = self._create_button("Back", variant="secondary", min_width=86, parent=self.top_bar)
        self.back_button.clicked.connect(self._handle_back_clicked)

        self.logo_label = QLabel(self.top_bar)
        self.logo_label.setObjectName("LogoLabel")
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_label.setFixedSize(42, 42)
        self._set_label_pixmap(self.logo_label, self._logo_pixmap, 42)

        self.top_title = QLabel("Admin Login", self.top_bar)
        self.top_title.setObjectName("TopTitle")

        self.access_pill = QLabel("Protected", self.top_bar)
        self.access_pill.setObjectName("RuntimePill")

        self.attempt_pill = QLabel("0 Failed Attempts", self.top_bar)
        self.attempt_pill.setObjectName("RuntimePill")

        self.top_layout.addWidget(self.back_button)
        self.top_layout.addWidget(self.logo_label)
        self.top_layout.addWidget(self.top_title)
        self.top_layout.addStretch(1)
        self.top_layout.addWidget(self.access_pill)
        self.top_layout.addWidget(self.attempt_pill)

        # ---------------------------------------------------------------------
        # Header card
        # ---------------------------------------------------------------------
        self.header_card = QFrame(self)
        self.header_card.setObjectName("LoginHeaderCard")

        self.header_layout = QVBoxLayout(self.header_card)
        self.header_layout.setContentsMargins(16, 12, 16, 12)
        self.header_layout.setSpacing(5)

        self.hero_title = QLabel(self.header_card)
        self.hero_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hero_title.setText("Admin Login")

        self.hero_subtitle = QLabel(self.header_card)
        self.hero_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hero_subtitle.setWordWrap(True)
        self.hero_subtitle.setText("Enter your credentials to continue")

        self.header_chip_row = QWidget(self.header_card)
        self.chip_layout = QHBoxLayout(self.header_chip_row)
        self.chip_layout.setContentsMargins(0, 0, 0, 0)
        self.chip_layout.setSpacing(6)

        self.security_chip = QLabel("Protected Access", self.header_chip_row)
        self.security_chip.setObjectName("HeaderChip")
        self.method_chip = QLabel("Secure Login Portal", self.header_chip_row)
        self.method_chip.setObjectName("HeaderChip")
        self.lockout_chip = QLabel("Lockout Enabled", self.header_chip_row)
        self.lockout_chip.setObjectName("HeaderChip")

        self.chip_layout.addStretch(1)
        self.chip_layout.addWidget(self.security_chip)
        self.chip_layout.addWidget(self.method_chip)
        self.chip_layout.addWidget(self.lockout_chip)
        self.chip_layout.addStretch(1)

        self.summary_banner = QLabel(
            "Authorized administrators can access settings, calibration, storage, and protected kiosk tools from this portal.",
            self.header_card,
        )
        self.summary_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.summary_banner.setWordWrap(True)

        self.header_layout.addWidget(self.hero_title)
        self.header_layout.addWidget(self.hero_subtitle)
        self.header_layout.addWidget(self.header_chip_row)
        self.header_layout.addWidget(self.summary_banner)

        # ---------------------------------------------------------------------
        # Content row
        # ---------------------------------------------------------------------
        self.content_row = QWidget(self)
        self.content_layout = QHBoxLayout(self.content_row)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(10)

        self.login_panel = QFrame(self.content_row)
        self.login_panel.setObjectName("LoginPanel")
        self.login_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.login_layout = QHBoxLayout(self.login_panel)
        self.login_layout.setContentsMargins(14, 12, 14, 12)
        self.login_layout.setSpacing(12)

        self.visual_panel = QFrame(self.login_panel)
        self.visual_panel.setObjectName("InfoCard")
        self.visual_panel.setMinimumWidth(210)
        self.visual_layout = QVBoxLayout(self.visual_panel)
        self.visual_layout.setContentsMargins(14, 14, 14, 14)
        self.visual_layout.setSpacing(6)

        self.shield_art = QLabel(self.visual_panel)
        self.shield_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_label_pixmap(self.shield_art, self._shield_pixmap, 126)

        self.visual_title = QLabel("Protected Admin Area", self.visual_panel)
        self.visual_title.setObjectName("SectionTitle")
        self.visual_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.visual_title.setWordWrap(True)

        self.guidance_line_1 = QLabel("• Authorized staff only.", self.visual_panel)
        self.guidance_line_2 = QLabel("• Demo default: admin", self.visual_panel)
        self.guidance_line_3 = QLabel("• Failed attempts trigger lockout.", self.visual_panel)
        self.guidance_note = QLabel(
            "Use this screen to access administrator dashboard, device settings, calibration, and records tools.",
            self.visual_panel,
        )
        self.guidance_note.setWordWrap(True)

        self.visual_layout.addStretch(1)
        self.visual_layout.addWidget(self.shield_art, 0, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.visual_layout.addWidget(self.visual_title)
        self.visual_layout.addWidget(self.guidance_line_1)
        self.visual_layout.addWidget(self.guidance_line_2)
        self.visual_layout.addWidget(self.guidance_line_3)
        self.visual_layout.addWidget(self.guidance_note)
        self.visual_layout.addStretch(1)

        self.form_panel = QFrame(self.login_panel)
        self.form_panel.setObjectName("FormPanel")
        self.form_layout = QVBoxLayout(self.form_panel)
        self.form_layout.setContentsMargins(16, 16, 16, 16)
        self.form_layout.setSpacing(8)

        self.form_title = QLabel("Admin Login", self.form_panel)
        self.form_title.setObjectName("FormHeroTitle")

        self.form_subtitle = QLabel("Enter your credentials to continue", self.form_panel)
        self.form_subtitle.setWordWrap(True)
        self.form_subtitle.setObjectName("FormHeroSubtitle")

        self.username_label = QLabel("Username", self.form_panel)
        self.username_input = QLineEdit(self.form_panel)
        self.username_input.setPlaceholderText("Enter username")
        self.username_input.setObjectName("AuthLineEdit")
        self.username_input.setMinimumHeight(44)
        self.username_input.returnPressed.connect(self._handle_login_clicked)
        self.username_input.textChanged.connect(self._clear_error_state)

        self.password_label = QLabel("Password", self.form_panel)
        self.password_input = QLineEdit(self.form_panel)
        self.password_input.setPlaceholderText("Enter password")
        self.password_input.setObjectName("AuthLineEdit")
        self.password_input.setMinimumHeight(46)
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.returnPressed.connect(self._handle_login_clicked)
        self.password_input.textChanged.connect(self._clear_error_state)

        self.options_row = QWidget(self.form_panel)
        self.options_row.setObjectName("OptionsRow")
        self.options_row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.options_row.setMinimumHeight(34)
        self.options_row.setMaximumHeight(36)
        self.options_layout = QHBoxLayout(self.options_row)
        self.options_layout.setContentsMargins(0, 0, 0, 0)
        self.options_layout.setSpacing(10)

        self.remember_checkbox = QCheckBox("Remember Me", self.options_row)
        self.show_password_checkbox = QCheckBox("Show Password", self.options_row)
        self.show_password_checkbox.toggled.connect(self._toggle_password_visibility)

        self.options_layout.addWidget(self.remember_checkbox, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.options_layout.addStretch(1)
        self.options_layout.addWidget(self.show_password_checkbox, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.status_card = QFrame(self.form_panel)
        self.status_card.setObjectName("StatusCard")
        self.status_card.setMinimumHeight(74)
        self.status_card.setMaximumHeight(92)
        self.status_layout = QVBoxLayout(self.status_card)
        self.status_layout.setContentsMargins(10, 8, 10, 8)
        self.status_layout.setSpacing(3)

        self.status_title = QLabel("Access Status", self.status_card)
        self.status_title.setObjectName("MiniSectionTitle")
        self.status_message = QLabel(self._last_login_message, self.status_card)
        self.status_message.setWordWrap(True)
        self.lockout_message = QLabel("", self.status_card)
        self.lockout_message.setWordWrap(True)

        self.status_layout.addWidget(self.status_title)
        self.status_layout.addWidget(self.status_message)
        self.status_layout.addWidget(self.lockout_message)

        self.form_button_row = QWidget(self.form_panel)
        self.form_button_layout = QHBoxLayout(self.form_button_row)
        self.form_button_layout.setContentsMargins(0, 6, 0, 0)
        self.form_button_layout.setSpacing(10)

        self.clear_button = self._create_button("Clear", variant="ghost", min_width=140, parent=self.form_button_row)
        self.clear_button.clicked.connect(self._handle_clear_clicked)

        self.login_button = self._create_button("Login", variant="primary", min_width=170, parent=self.form_button_row)
        self.login_button.clicked.connect(self._handle_login_clicked)

        self.form_button_layout.addWidget(self.clear_button)
        self.form_button_layout.addWidget(self.login_button)

        self.form_layout.addWidget(self.form_title)
        self.form_layout.addWidget(self.form_subtitle)
        self.form_layout.addSpacing(4)
        self.form_layout.addWidget(self.username_label)
        self.form_layout.addWidget(self.username_input)
        self.form_layout.addWidget(self.password_label)
        self.form_layout.addWidget(self.password_input)
        self.form_layout.addWidget(self.options_row)
        self.form_layout.addWidget(self.status_card)
        self.form_layout.addSpacing(2)
        self.form_layout.addWidget(self.form_button_row)

        self.login_layout.addWidget(self.visual_panel, 0)
        self.login_layout.addWidget(self.form_panel, 1)

        # Optional kiosk keypad / helper panel
        self.side_panel = QWidget(self.content_row)
        self.side_layout = QVBoxLayout(self.side_panel)
        self.side_layout.setContentsMargins(0, 0, 0, 0)
        self.side_layout.setSpacing(8)
        self.side_panel.setMinimumWidth(220)
        self.side_panel.setMaximumWidth(248)

        self.keypad_card = QFrame(self.side_panel)
        self.keypad_card.setObjectName("InfoCard")
        self.keypad_layout = QVBoxLayout(self.keypad_card)
        self.keypad_layout.setContentsMargins(10, 10, 10, 10)
        self.keypad_layout.setSpacing(8)

        self.keypad_title = QLabel("Touch Keypad", self.keypad_card)
        self.keypad_title.setObjectName("SectionTitle")
        self.keypad_subtitle = QLabel("Use the on-screen keypad when a hardware keyboard is not available.", self.keypad_card)
        self.keypad_subtitle.setWordWrap(True)

        self.keypad_grid_widget = QWidget(self.keypad_card)
        self.keypad_grid = QGridLayout(self.keypad_grid_widget)
        self.keypad_grid.setContentsMargins(0, 0, 0, 0)
        self.keypad_grid.setHorizontalSpacing(6)
        self.keypad_grid.setVerticalSpacing(6)

        keypad_map = [
            ("1", 0, 0), ("2", 0, 1), ("3", 0, 2),
            ("4", 1, 0), ("5", 1, 1), ("6", 1, 2),
            ("7", 2, 0), ("8", 2, 1), ("9", 2, 2),
            ("CLR", 3, 0), ("0", 3, 1), ("⌫", 3, 2),
        ]
        self.keypad_buttons: Dict[str, QPushButton] = {}
        for text, row, col in keypad_map:
            btn = self._create_keypad_button(text, parent=self.keypad_grid_widget)
            btn.clicked.connect(lambda _=False, key=text: self._handle_keypad_press(key))
            self.keypad_buttons[text] = btn
            self.keypad_grid.addWidget(btn, row, col)

        self.keypad_layout.addWidget(self.keypad_title)
        self.keypad_layout.addWidget(self.keypad_subtitle)
        self.keypad_layout.addWidget(self.keypad_grid_widget)

        self.guidance_card = QFrame(self.side_panel)
        self.guidance_card.setObjectName("InfoCard")
        self.guidance_layout = QVBoxLayout(self.guidance_card)
        self.guidance_layout.setContentsMargins(10, 10, 10, 10)
        self.guidance_layout.setSpacing(6)

        self.guidance_title = QLabel("Security Guidance", self.guidance_card)
        self.guidance_title.setObjectName("SectionTitle")
        self.guidance_layout.addWidget(self.guidance_title)
        self.guidance_layout.addWidget(QLabel("• Keep credentials private.", self.guidance_card))
        self.guidance_layout.addWidget(QLabel("• Lockout activates after repeated failures.", self.guidance_card))
        self.guidance_layout.addWidget(QLabel("• Use admin access only for protected kiosk functions.", self.guidance_card))

        self.side_layout.addWidget(self.keypad_card)
        self.side_layout.addWidget(self.guidance_card)
        self.side_layout.addStretch(1)

        self.content_layout.addWidget(self.login_panel, 1)
        self.content_layout.addWidget(self.side_panel, 0)

        # ---------------------------------------------------------------------
        # Bottom helper row
        # ---------------------------------------------------------------------
        self.action_row = QWidget(self)
        self.action_layout = QHBoxLayout(self.action_row)
        self.action_layout.setContentsMargins(0, 0, 0, 0)
        self.action_layout.setSpacing(8)

        self.reset_lockout_button = self._create_button("Reset Lockout", variant="ghost", min_width=138, parent=self.action_row)
        self.reset_lockout_button.clicked.connect(self._handle_reset_lockout_clicked)

        self.try_default_button = self._create_button("Load Default User", variant="secondary", min_width=160, parent=self.action_row)
        self.try_default_button.clicked.connect(self._handle_load_default_username_clicked)

        self.bottom_login_button = self._create_button("Login", variant="primary", min_width=160, parent=self.action_row)
        self.bottom_login_button.clicked.connect(self._handle_login_clicked)

        self.action_layout.addWidget(self.reset_lockout_button)
        self.action_layout.addStretch(1)
        self.action_layout.addWidget(self.try_default_button)
        self.action_layout.addWidget(self.bottom_login_button)

        self.root_layout.addWidget(self.top_bar)
        self.root_layout.addWidget(self.header_card)
        self.root_layout.addWidget(self.content_row, 1)
        self.root_layout.addWidget(self.action_row)

    def _create_button(self, text: str, *, variant: str, min_width: int, parent: QWidget) -> QWidget:
        button = QPushButton(text, parent)
        button.setMinimumWidth(min_width)
        button.setMinimumHeight(42)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setProperty("variant", variant)
        base = {
            "primary": "#29C5FF",
            "secondary": "#43D2FF",
            "ghost": "#6E88A7",
            "success": "#42E393",
        }.get(variant, "#29C5FF")
        accent = QColor(base)
        button.setStyleSheet(
            f"""
            QPushButton {{
                color: #F7FCFF;
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.42);
                border-radius: 15px;
                padding: 8px 16px;
                font-size: 12px;
                font-weight: 800;
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.92),
                    stop:1 rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.74)
                );
            }}
            QPushButton:hover {{
                border-color: rgba(255, 255, 255, 0.58);
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba({accent.red()}, {accent.green()}, {accent.blue()}, 1.00),
                    stop:1 rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.84)
                );
            }}
            QPushButton:pressed {{
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.78);
            }}
            QPushButton:disabled {{
                color: rgba(220, 236, 246, 0.48);
                border-color: rgba(120, 150, 180, 0.20);
                background: rgba(20, 38, 62, 0.55);
            }}
            """
        )
        return button

    def _create_keypad_button(self, text: str, *, parent: QWidget) -> QPushButton:
        btn = QPushButton(text, parent)
        btn.setMinimumSize(60, 42)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            """
            QPushButton {
                color: #F6FCFF;
                border: 1px solid rgba(157, 220, 255, 0.28);
                border-radius: 12px;
                background: rgba(24, 50, 88, 0.84);
                font-size: 13px;
                font-weight: 800;
            }
            QPushButton:hover {
                background: rgba(36, 69, 114, 0.94);
                border-color: rgba(186, 233, 255, 0.42);
            }
            QPushButton:pressed {
                background: rgba(50, 96, 156, 0.98);
            }
            QPushButton:disabled {
                color: rgba(220, 236, 246, 0.45);
                background: rgba(20, 38, 62, 0.55);
            }
            """
        )
        return btn

    def _set_label_pixmap(self, label: QLabel, pixmap: QPixmap, target_height: int) -> None:
        if pixmap.isNull():
            label.clear()
            return

        scaled = pixmap.scaledToHeight(
            target_height,
            Qt.TransformationMode.SmoothTransformation,
        )
        label.setPixmap(scaled)

    # =========================================================================
    # Effects / styles
    # =========================================================================

    def _setup_effects(self) -> None:
        """
        Keep the admin login screen stable on compact kiosks.

        Earlier versions used opacity effects and entry animations here, but on
        some target environments that left the central login widgets visually
        blank during first paint. For this screen we prefer reliability over
        cinematic transitions, so the core login content is shown immediately.
        """
        self.header_opacity = None
        self.content_opacity = None
        self.entry_group = None

        # Ensure the key panels are fully visible from the first paint.
        try:
            self.header_card.setGraphicsEffect(None)
        except Exception:
            pass
        try:
            self.content_row.setGraphicsEffect(None)
        except Exception:
            pass
        try:
            self.login_panel.setGraphicsEffect(None)
        except Exception:
            pass

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QFrame#AdminLoginScreen {
                background: transparent;
            }

            QLabel#LogoLabel {
                min-width: 42px;
                max-width: 42px;
                min-height: 42px;
                max-height: 42px;
                background: transparent;
                border: none;
            }

            QLabel#TopTitle {
                color: #F6FCFF;
                font-size: 15px;
                font-weight: 900;
                background: transparent;
            }

            QLabel#RuntimePill {
                color: #EEF9FF;
                font-size: 9px;
                font-weight: 700;
                border: 1px solid rgba(157, 220, 255, 0.26);
                border-radius: 14px;
                background: rgba(18, 39, 70, 0.56);
                padding: 6px 10px;
            }

            QFrame#LoginHeaderCard {
                border: 1px solid rgba(170, 230, 255, 0.20);
                border-radius: 20px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(10, 28, 50, 0.90),
                    stop:1 rgba(6, 20, 40, 0.94)
                );
            }

            QLabel#HeaderChip {
                color: #EEF9FF;
                font-size: 9px;
                font-weight: 800;
                border: 1px solid rgba(157, 220, 255, 0.24);
                border-radius: 12px;
                background: rgba(28, 56, 91, 0.42);
                padding: 4px 9px;
            }

            QFrame#LoginPanel, QFrame#InfoCard, QFrame#StatusCard, QFrame#FormPanel {
                border: 1px solid rgba(170, 230, 255, 0.20);
                border-radius: 20px;
                background: rgba(9, 27, 48, 0.82);
            }

            QLabel#SectionTitle {
                color: #F4FCFF;
                font-size: 12px;
                font-weight: 800;
                background: transparent;
            }

            QWidget#OptionsRow {
                background: transparent;
            }

            QLabel#MiniSectionTitle {
                color: #F4FCFF;
                font-size: 9px;
                font-weight: 800;
                background: transparent;
            }

            QLabel#FormHeroTitle {
                color: #F4FCFF;
                font-size: 30px;
                font-weight: 900;
                background: transparent;
            }

            QLabel#FormHeroSubtitle {
                color: rgba(223, 239, 249, 0.86);
                font-size: 14px;
                font-weight: 500;
                background: transparent;
            }

            QLineEdit#AuthLineEdit {
                color: #F6FCFF;
                border: 1px solid rgba(157, 220, 255, 0.26);
                border-radius: 14px;
                background: rgba(16, 35, 61, 0.92);
                padding: 0 14px;
                font-size: 14px;
                font-weight: 600;
            }

            QLineEdit#AuthLineEdit:focus {
                border: 1px solid rgba(95, 219, 255, 0.52);
                background: rgba(18, 40, 70, 0.96);
            }

            QCheckBox {
                color: rgba(228, 242, 252, 0.92);
                font-size: 12px;
                font-weight: 600;
                spacing: 8px;
                background: transparent;
            }

            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid rgba(157, 220, 255, 0.30);
                background: rgba(18, 39, 70, 0.58);
            }

            QCheckBox::indicator:checked {
                background: rgba(67, 217, 255, 0.90);
                border: 1px solid rgba(186, 233, 255, 0.42);
            }
            """
        )

        self.hero_title.setStyleSheet(
            """
            QLabel {
                color: #F6FCFF;
                font-size: 20px;
                font-weight: 900;
                background: transparent;
            }
            """
        )
        self.hero_subtitle.setStyleSheet(
            """
            QLabel {
                color: rgba(219, 237, 249, 0.90);
                font-size: 11px;
                font-weight: 600;
                background: transparent;
            }
            """
        )
        self.summary_banner.setStyleSheet(
            """
            QLabel {
                color: rgba(207, 229, 244, 0.88);
                font-size: 10px;
                font-weight: 600;
                background: transparent;
            }
            """
        )

        label_style = """
            QLabel {
                color: rgba(228, 242, 252, 0.94);
                font-size: 12px;
                font-weight: 700;
                background: transparent;
            }
        """
        self.username_label.setStyleSheet(label_style)
        self.password_label.setStyleSheet(label_style)
        self.status_message.setStyleSheet(
            """
            QLabel {
                color: rgba(214, 235, 248, 0.92);
                font-size: 11px;
                font-weight: 500;
                background: transparent;
            }
            """
        )
        self.lockout_message.setStyleSheet(
            """
            QLabel {
                color: rgba(255, 201, 97, 0.98);
                font-size: 11px;
                font-weight: 700;
                background: transparent;
            }
            """
        )

        info_text_style = """
            QLabel {
                color: rgba(214, 235, 248, 0.88);
                font-size: 11px;
                font-weight: 500;
                background: transparent;
            }
        """
        self.keypad_subtitle.setStyleSheet(info_text_style)
        self.guidance_line_1.setStyleSheet(info_text_style)
        self.guidance_line_2.setStyleSheet(info_text_style)
        self.guidance_line_3.setStyleSheet(info_text_style)
        self.guidance_note.setStyleSheet(info_text_style)

        self.visual_title.setStyleSheet("QLabel { color: #F4FCFF; font-size: 12px; font-weight: 900; background: transparent; line-height: 1.15; background: transparent; }")
        self.form_title.setStyleSheet("QLabel { color:#F4FCFF; font-size: 28px; font-weight: 900; background: transparent; }")
        self.form_subtitle.setStyleSheet("QLabel { color: rgba(223,239,249,0.90); font-size: 13px; font-weight: 500; background: transparent; }")

        self._set_button_accent(self.back_button, "#39D8FF")
        self._set_button_accent(self.login_button, "#29C5FF")
        self._set_button_accent(self.bottom_login_button, "#29C5FF")
        self._set_button_accent(self.clear_button, "#6A88A8")
        self._set_button_accent(self.reset_lockout_button, "#6A88A8")
        self._set_button_accent(self.try_default_button, "#43D2FF")


    def _apply_compact_layout(self) -> None:
        width = max(1, self.width())
        height = max(1, self.height())

        compact = width <= self._compact_width_threshold or height <= self._compact_height_threshold
        ultra = width <= self._ultra_compact_width_threshold or height <= self._ultra_compact_height_threshold
        self._compact_login_layout = bool(compact or ultra)

        # Always keep the main portal visible, and keep the extra side/keypad
        # elements hidden on the kiosk-sized layout so the form stays clean.
        self.login_panel.setVisible(True)
        self.visual_panel.setVisible(True)
        self.form_panel.setVisible(True)
        self.form_button_row.setVisible(True)
        self.side_panel.setVisible(False)
        self.action_row.setVisible(False)
        self.keypad_card.setVisible(False)
        self.guidance_card.setVisible(False)

        self.top_title.setText("Admin Login")
        self.hero_title.setText("Protected administrator access")
        self.hero_subtitle.setText("Secure login portal")

        try:
            self.login_layout.setStretch(0, 3)
            self.login_layout.setStretch(1, 7)
        except Exception:
            pass

        if ultra:
            self.root_layout.setContentsMargins(10, 8, 10, 8)
            self.root_layout.setSpacing(6)
            self.top_layout.setSpacing(8)
            self.header_layout.setContentsMargins(14, 8, 14, 8)
            self.header_layout.setSpacing(4)
            self.content_layout.setSpacing(8)
            self.login_layout.setContentsMargins(10, 10, 10, 10)
            self.login_layout.setSpacing(10)
            self.visual_layout.setContentsMargins(10, 12, 10, 12)
            self.visual_layout.setSpacing(5)
            self.form_layout.setContentsMargins(12, 12, 12, 12)
            self.form_layout.setSpacing(5)
            self.visual_panel.setMinimumWidth(146)
            self.visual_panel.setMaximumWidth(158)
            self._set_label_pixmap(self.shield_art, self._shield_pixmap, 72)
            self.username_input.setMinimumHeight(36)
            self.password_input.setMinimumHeight(36)
            self.options_row.setMinimumHeight(26)
            self.options_row.setMaximumHeight(28)
            self.back_button.setMinimumHeight(42)
            self.clear_button.setMinimumHeight(38)
            self.login_button.setMinimumHeight(38)
            self.clear_button.setMinimumWidth(122)
            self.login_button.setMinimumWidth(138)
            self.header_card.setMinimumHeight(90)
            self.header_card.setMaximumHeight(100)
            self.hero_subtitle.setVisible(True)
            self.summary_banner.setVisible(False)
            self.attempt_pill.setVisible(False)
            self.method_chip.setVisible(False)
            self.lockout_chip.setVisible(False)
            self.guidance_line_3.setVisible(False)
            self.guidance_note.setVisible(False)
            self.form_title.setStyleSheet("QLabel { color:#F4FCFF; font-size: 19px; font-weight: 900; background: transparent; }")
            self.form_subtitle.setStyleSheet("QLabel { color: rgba(223,239,249,0.86); font-size: 11px; font-weight: 500; background: transparent; }")
            self.visual_title.setStyleSheet("QLabel { color: #F4FCFF; font-size: 12px; font-weight: 900; background: transparent; }")
            self.visual_title.setText("Protected Admin\nArea")
            self.status_card.setMaximumHeight(58)
        elif compact:
            self.root_layout.setContentsMargins(12, 8, 12, 8)
            self.root_layout.setSpacing(6)
            self.top_layout.setSpacing(8)
            self.header_layout.setContentsMargins(14, 8, 14, 8)
            self.header_layout.setSpacing(4)
            self.content_layout.setSpacing(8)
            self.login_layout.setContentsMargins(10, 10, 10, 10)
            self.login_layout.setSpacing(10)
            self.visual_layout.setContentsMargins(10, 12, 10, 12)
            self.visual_layout.setSpacing(5)
            self.form_layout.setContentsMargins(12, 12, 12, 12)
            self.form_layout.setSpacing(5)
            self.visual_panel.setMinimumWidth(154)
            self.visual_panel.setMaximumWidth(168)
            self._set_label_pixmap(self.shield_art, self._shield_pixmap, 76)
            self.username_input.setMinimumHeight(36)
            self.password_input.setMinimumHeight(36)
            self.options_row.setMinimumHeight(26)
            self.options_row.setMaximumHeight(28)
            self.back_button.setMinimumHeight(42)
            self.clear_button.setMinimumHeight(38)
            self.login_button.setMinimumHeight(38)
            self.clear_button.setMinimumWidth(126)
            self.login_button.setMinimumWidth(146)
            self.header_card.setMinimumHeight(92)
            self.header_card.setMaximumHeight(102)
            self.hero_subtitle.setVisible(True)
            self.summary_banner.setVisible(False)
            self.attempt_pill.setVisible(False)
            self.method_chip.setVisible(False)
            self.lockout_chip.setVisible(False)
            self.guidance_line_3.setVisible(False)
            self.guidance_note.setVisible(False)
            self.form_title.setStyleSheet("QLabel { color:#F4FCFF; font-size: 20px; font-weight: 900; background: transparent; }")
            self.form_subtitle.setStyleSheet("QLabel { color: rgba(223,239,249,0.88); font-size: 11px; font-weight: 500; background: transparent; }")
            self.visual_title.setStyleSheet("QLabel { color: #F4FCFF; font-size: 13px; font-weight: 900; background: transparent; }")
            self.visual_title.setText("Protected Admin\nArea")
            self.status_card.setMaximumHeight(60)
            self.guidance_line_3.setVisible(False)
            self.remember_checkbox.setText("Remember Me")
            self.show_password_checkbox.setText("Show Password")
        else:
            self.root_layout.setContentsMargins(16, 10, 16, 10)
            self.root_layout.setSpacing(8)
            self.top_layout.setSpacing(8)
            self.header_layout.setContentsMargins(16, 12, 16, 12)
            self.header_layout.setSpacing(5)
            self.content_layout.setSpacing(10)
            self.login_layout.setContentsMargins(14, 12, 14, 12)
            self.login_layout.setSpacing(12)
            self.visual_layout.setContentsMargins(14, 14, 14, 14)
            self.visual_layout.setSpacing(6)
            self.form_layout.setContentsMargins(16, 16, 16, 16)
            self.form_layout.setSpacing(8)
            self.visual_panel.setMinimumWidth(190)
            self.visual_panel.setMaximumWidth(206)
            self._set_label_pixmap(self.shield_art, self._shield_pixmap, 98)
            self.username_input.setMinimumHeight(44)
            self.password_input.setMinimumHeight(44)
            self.options_row.setMinimumHeight(34)
            self.options_row.setMaximumHeight(36)
            self.back_button.setMinimumHeight(46)
            self.clear_button.setMinimumHeight(44)
            self.login_button.setMinimumHeight(44)
            self.clear_button.setMinimumWidth(150)
            self.login_button.setMinimumWidth(170)
            self.header_card.setMinimumHeight(120)
            self.header_card.setMaximumHeight(138)
            self.hero_subtitle.setVisible(True)
            self.summary_banner.setVisible(False)
            self.attempt_pill.setVisible(True)
            self.method_chip.setVisible(True)
            self.lockout_chip.setVisible(True)
            self.guidance_line_3.setVisible(True)
            self.guidance_note.setVisible(True)
            self.form_title.setStyleSheet("QLabel { color:#F4FCFF; font-size: 28px; font-weight: 900; background: transparent; }")
            self.form_subtitle.setStyleSheet("QLabel { color: rgba(223,239,249,0.90); font-size: 13px; font-weight: 500; background: transparent; }")

        # Keep the compact portal visually close to the reference art: fewer
        # helper lines, more breathing room around the form, and no extra bottom
        # helper bar.
        self.hero_title.setText("Protected administrator access")
        self.hero_subtitle.setText("Secure login portal")
        self.login_panel.setMinimumHeight(0)
        self.login_panel.setMaximumHeight(16777215)

        self._update_access_status()


    def _play_entry_animation(self) -> None:
        # Admin login content should appear instantly and reliably.
        return

    # =========================================================================
    # Lifecycle
    # =========================================================================


    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_compact_layout()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_compact_layout()

        # Force the central login widgets to remain visible on first show.
        for widget in (
            self.content_row,
            self.login_panel,
            self.visual_panel,
            self.form_panel,
            self.username_label,
            self.username_input,
            self.password_label,
            self.password_input,
            self.show_password_checkbox,
            self.remember_checkbox,
            self.status_card,
            self.form_button_row,
            self.clear_button,
            self.login_button,
        ):
            try:
                widget.setVisible(True)
                widget.raise_()
            except Exception:
                pass

        self._update_access_status()
        self.username_input.setFocus()
        self.content_row.update()
        self.login_panel.update()
        self.form_panel.update()

    # =========================================================================
    # Credential loading / authentication
    # =========================================================================

    def _load_admin_credentials(self) -> Dict[str, Any]:
        """
        Best-effort credential loading.

        Supported sources:
        - services/settings_service.py
        - config.py
        - app_state fallback attributes

        Returns:
            {
                "username": "...",
                "password": "...",          # plain-text fallback
                "password_hash": "...",     # optional SHA256 hex
            }
        """
        credentials: Dict[str, Any] = {}

        # 1) settings_service
        try:
            settings_service = self.services.get("settings_service") or self.services.get("settings")
            if settings_service is not None:
                # A. direct admin credential methods
                for method_name in (
                    "get_admin_credentials",
                    "admin_credentials",
                    "load_admin_credentials",
                ):
                    method = getattr(settings_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method()
                            if isinstance(raw, Mapping):
                                credentials.update(dict(raw))
                                if credentials:
                                    break
                        except Exception:
                            continue

                # B. generic settings snapshot
                if not credentials:
                    for method_name in (
                        "get_settings",
                        "load_settings",
                        "current_settings",
                        "snapshot",
                        "get_snapshot",
                    ):
                        method = getattr(settings_service, method_name, None)
                        if callable(method):
                            try:
                                raw = method()
                                if isinstance(raw, Mapping):
                                    settings_map = dict(raw)
                                    admin_section = settings_map.get("admin", {})
                                    if isinstance(admin_section, Mapping):
                                        credentials.update(dict(admin_section))
                                    else:
                                        if "admin_username" in settings_map:
                                            credentials["username"] = settings_map.get("admin_username")
                                        if "admin_password" in settings_map:
                                            credentials["password"] = settings_map.get("admin_password")
                                        if "admin_password_hash" in settings_map:
                                            credentials["password_hash"] = settings_map.get("admin_password_hash")
                                    if credentials:
                                        break
                            except Exception:
                                continue

                # C. individual get_setting style API
                if not credentials:
                    for getter_name in ("get_setting", "value", "get"):
                        getter = getattr(settings_service, getter_name, None)
                        if callable(getter):
                            try:
                                username = getter("admin_username")
                                password = getter("admin_password")
                                password_hash = getter("admin_password_hash")
                                if username not in (None, ""):
                                    credentials["username"] = username
                                if password not in (None, ""):
                                    credentials["password"] = password
                                if password_hash not in (None, ""):
                                    credentials["password_hash"] = password_hash
                                if credentials:
                                    break
                            except Exception:
                                continue
        except Exception:
            pass

        # 2) config.py
        if not credentials:
            try:
                import config as project_config  # local import on purpose

                if hasattr(project_config, "ADMIN_CREDENTIALS"):
                    raw = getattr(project_config, "ADMIN_CREDENTIALS")
                    if isinstance(raw, Mapping):
                        credentials.update(dict(raw))

                if "username" not in credentials:
                    for key in ("ADMIN_USERNAME", "DEFAULT_ADMIN_USERNAME"):
                        if hasattr(project_config, key):
                            value = getattr(project_config, key)
                            if value not in (None, ""):
                                credentials["username"] = value
                                break

                if "password" not in credentials:
                    for key in ("ADMIN_PASSWORD", "DEFAULT_ADMIN_PASSWORD"):
                        if hasattr(project_config, key):
                            value = getattr(project_config, key)
                            if value not in (None, ""):
                                credentials["password"] = value
                                break

                if "password_hash" not in credentials:
                    for key in ("ADMIN_PASSWORD_HASH", "DEFAULT_ADMIN_PASSWORD_HASH"):
                        if hasattr(project_config, key):
                            value = getattr(project_config, key)
                            if value not in (None, ""):
                                credentials["password_hash"] = value
                                break
            except Exception:
                pass

        # 3) app_state fallback
        if not credentials:
            try:
                if self.app_state is not None:
                    for attr_name, target_key in (
                        ("admin_username", "username"),
                        ("admin_password", "password"),
                        ("admin_password_hash", "password_hash"),
                    ):
                        if hasattr(self.app_state, attr_name):
                            value = getattr(self.app_state, attr_name)
                            if value not in (None, ""):
                                credentials[target_key] = value
            except Exception:
                pass

        # 4) final fallback for offline demo, overridable for deployment.
        credentials.setdefault("username", os.environ.get("CST_KIOSK_ADMIN_USERNAME", "admin"))
        credentials.setdefault("password", os.environ.get("CST_KIOSK_ADMIN_PASSWORD", "change-me"))

        return {
            "username": safe_str(credentials.get("username"), "admin").strip() or "admin",
            "password": safe_str(credentials.get("password"), "").strip(),
            "password_hash": safe_str(credentials.get("password_hash"), "").strip().lower(),
        }

    def _verify_credentials(self, username: str, password: str) -> Tuple[bool, str]:
        credentials = self._load_admin_credentials()
        expected_username = safe_str(credentials.get("username"), "").strip()
        expected_password = safe_str(credentials.get("password"), "").strip()
        expected_hash = safe_str(credentials.get("password_hash"), "").strip().lower()

        entered_username = safe_str(username, "").strip()
        entered_password = safe_str(password, "").strip()

        if not entered_username:
            return False, "Please enter the administrator username."
        if not entered_password:
            return False, "Please enter the administrator password."

        username_ok = hmac.compare_digest(entered_username, expected_username)

        password_ok = False
        if expected_hash and _looks_like_sha256_hex(expected_hash):
            entered_hash = hashlib.sha256(entered_password.encode("utf-8")).hexdigest().lower()
            password_ok = hmac.compare_digest(entered_hash, expected_hash)

        if not password_ok and expected_password:
            password_ok = hmac.compare_digest(entered_password, expected_password)

        if username_ok and password_ok:
            return True, "Administrator login successful."

        return False, "Invalid administrator username or password."

    def _persist_admin_authenticated(self, username: str) -> None:
        """
        Best-effort persistence into app_state and settings_service.
        """
        user_text = safe_str(username, "").strip()

        # 1) app_state
        try:
            if self.app_state is not None:
                for attr_name, value in (
                    ("admin_authenticated", True),
                    ("is_admin_authenticated", True),
                    ("admin_user", user_text),
                    ("current_admin_user", user_text),
                ):
                    if hasattr(self.app_state, attr_name):
                        try:
                            setattr(self.app_state, attr_name, value)
                        except Exception:
                            pass

                for method_name in (
                    "set_admin_authenticated",
                    "set_admin_user",
                    "update_admin_session",
                    "admin_login_success",
                ):
                    method = getattr(self.app_state, method_name, None)
                    if callable(method):
                        try:
                            if method_name == "set_admin_authenticated":
                                method(True)
                            elif method_name == "set_admin_user":
                                method(user_text)
                            else:
                                method({"authenticated": True, "username": user_text})
                        except Exception:
                            continue
        except Exception:
            pass

        # 2) settings_service / runtime flags
        try:
            settings_service = self.services.get("settings_service") or self.services.get("settings")
            if settings_service is not None:
                for method_name in (
                    "set_runtime_value",
                    "set_setting",
                    "update_runtime_flag",
                    "set_admin_authenticated",
                ):
                    method = getattr(settings_service, method_name, None)
                    if callable(method):
                        try:
                            if method_name == "set_runtime_value":
                                method("admin_authenticated", True)
                            elif method_name == "set_setting":
                                method("admin_authenticated", True)
                            elif method_name == "update_runtime_flag":
                                method("admin_authenticated", True)
                            else:
                                method(True)
                        except Exception:
                            continue
        except Exception:
            pass

    # =========================================================================
    # Lockout handling
    # =========================================================================

    def _is_locked_out(self) -> bool:
        return self._lockout_seconds_remaining > 0

    def _start_lockout(self) -> None:
        self._lockout_seconds_remaining = max(1, self._lockout_seconds)
        self._lockout_timer.start()
        self._update_access_status()

    def _handle_lockout_tick(self) -> None:
        self._lockout_seconds_remaining = max(0, self._lockout_seconds_remaining - 1)
        if self._lockout_seconds_remaining <= 0:
            self._lockout_timer.stop()
            self._failed_attempts = 0
        self._update_access_status()

    def _reset_lockout_state(self) -> None:
        self._lockout_timer.stop()
        self._lockout_seconds_remaining = 0
        self._failed_attempts = 0
        self._update_access_status()

    # =========================================================================
    # Status / UI state
    # =========================================================================

    def _clear_error_state(self) -> None:
        if self._is_locked_out():
            return
        self._last_login_message = "Administrator access is protected."
        self._update_access_status()

    def _update_access_status(self) -> None:
        locked = self._is_locked_out()

        if locked:
            self.access_pill.setText("Temporarily Locked")
            self._apply_pill_style(self.access_pill, "#FF6E88")
            self.status_message.setText("Login is temporarily locked after repeated failed attempts.")
            self.lockout_message.setText(
                f"Please wait {self._lockout_seconds_remaining} second(s) before trying again."
            )
            self.lockout_message.setVisible(True)
            self.login_button.setEnabled(False)
            self.bottom_login_button.setEnabled(False)
            self._set_button_accent(self.login_button, "#FF6E88")
            self._set_button_accent(self.bottom_login_button, "#FF6E88")
        else:
            self.access_pill.setText("Protected")
            self._apply_pill_style(self.access_pill, "#39D8FF")
            self.status_message.setText(self._last_login_message)
            self.lockout_message.setVisible(False)
            self.login_button.setEnabled(True)
            self.bottom_login_button.setEnabled(True)
            self._set_button_accent(self.login_button, "#29C5FF")
            self._set_button_accent(self.bottom_login_button, "#29C5FF")

        show_status_card = bool(locked or self._failed_attempts > 0)
        self.status_card.setVisible(show_status_card)
        if show_status_card:
            self.status_card.setMinimumHeight(66)
            self.status_card.setMaximumHeight(74 if self._compact_login_layout else 88)

        if self._failed_attempts <= 0:
            self.attempt_pill.setText("0 Failed Attempts")
            self._apply_pill_style(self.attempt_pill, "#39D8FF")
        elif self._failed_attempts == 1:
            self.attempt_pill.setText("1 Failed Attempt")
            self._apply_pill_style(self.attempt_pill, "#FFD25E")
        else:
            self.attempt_pill.setText(f"{self._failed_attempts} Failed Attempts")
            self._apply_pill_style(self.attempt_pill, "#FFA14D" if not locked else "#FF6E88")

        self._apply_header_chip_style(self.security_chip, "#39D8FF")
        self._apply_header_chip_style(self.method_chip, "#67D8FF")
        self._apply_header_chip_style(self.lockout_chip, "#FF6E88" if locked else "#FFD25E")

    def _apply_pill_style(self, label: QLabel, accent_hex: str) -> None:
        accent = QColor(accent_hex)
        label.setStyleSheet(
            f"""
            QLabel {{
                color: #EEF9FF;
                font-size: 8px;
                font-weight: 700;
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.34);
                border-radius: 12px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.15);
                padding: 5px 9px;
            }}
            """
        )

    def _apply_header_chip_style(self, label: QLabel, accent_hex: str) -> None:
        accent = QColor(accent_hex)
        label.setStyleSheet(
            f"""
            QLabel {{
                color: #EEF9FF;
                font-size: 8px;
                font-weight: 800;
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.34);
                border-radius: 11px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.16);
                padding: 3px 8px;
            }}
            """
        )

    def _set_button_accent(self, button: QWidget, accent_hex: str) -> None:
        if AnimatedButton is not None and hasattr(button, "set_accent_color"):
            try:
                button.set_accent_color(accent_hex)  # type: ignore[attr-defined]
                return
            except Exception:
                pass

        if isinstance(button, QPushButton):
            accent = QColor(accent_hex)
            is_back_button = button is getattr(self, "back_button", None)

            if is_back_button:
                button.setStyleSheet(
                    f"""
                    QPushButton {{
                        color: #F6FCFF;
                        border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.44);
                        border-radius: 16px;
                        padding: 10px 18px;
                        font-size: 12px;
                        font-weight: 800;
                        background: qlineargradient(
                            x1:0, y1:0, x2:0, y2:1,
                            stop:0 rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.98),
                            stop:1 rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.76)
                        );
                    }}
                    QPushButton:hover {{
                        border-color: rgba(255, 255, 255, 0.24);
                        background: qlineargradient(
                            x1:0, y1:0, x2:0, y2:1,
                            stop:0 rgba({accent.red()}, {accent.green()}, {accent.blue()}, 1.00),
                            stop:1 rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.84)
                        );
                    }}
                    QPushButton:disabled {{
                        color: rgba(220, 236, 246, 0.48);
                        background: rgba(20, 38, 62, 0.55);
                    }}
                    """
                )
                return

            button.setStyleSheet(
                f"""
                QPushButton {{
                    color: #F6FCFF;
                    border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.36);
                    border-radius: 15px;
                    padding: 10px 16px;
                    font-size: 12px;
                    font-weight: 700;
                    background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.18);
                }}
                QPushButton:hover {{
                    background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.28);
                    border-color: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.54);
                }}
                QPushButton:disabled {{
                    color: rgba(220, 236, 246, 0.48);
                    background: rgba(20, 38, 62, 0.55);
                }}
                """
            )

    # =========================================================================
    # Input helpers
    # =========================================================================

    def _active_input(self) -> QLineEdit:
        if self.password_input.hasFocus():
            return self.password_input
        if self.username_input.hasFocus():
            return self.username_input
        return self.password_input

    def _toggle_password_visibility(self, checked: bool) -> None:
        self.password_input.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )

    def _handle_keypad_press(self, key: str) -> None:
        if self._is_locked_out():
            return

        target = self._active_input()
        current = target.text()

        if key == "CLR":
            target.clear()
            return

        if key == "⌫":
            target.setText(current[:-1] if current else "")
            return

        target.setText(current + key)

    # =========================================================================
    # Actions
    # =========================================================================

    def _handle_back_clicked(self) -> None:
        if self._navigate_to(SCREEN_WELCOME):
            return
        self.back_requested.emit()

    def _handle_clear_clicked(self) -> None:
        self.username_input.clear()
        self.password_input.clear()
        self.show_password_checkbox.setChecked(False)
        self._last_login_message = "Administrator access is protected."
        self._update_access_status()
        self.username_input.setFocus()

    def _handle_reset_lockout_clicked(self) -> None:
        self._reset_lockout_state()

    def _handle_load_default_username_clicked(self) -> None:
        creds = self._load_admin_credentials()
        username = safe_str(creds.get("username"), "").strip()
        if username:
            self.username_input.setText(username)
            self.password_input.setFocus()

    def _handle_login_clicked(self) -> None:
        if self._is_locked_out():
            self._last_login_message = "Login is temporarily locked. Please wait for the cooldown to end."
            self._update_access_status()
            return

        username = safe_str(self.username_input.text(), "").strip()
        password = safe_str(self.password_input.text(), "").strip()

        self.login_attempted.emit(username)

        ok, message = self._verify_credentials(username, password)

        if ok:
            self._failed_attempts = 0
            self._last_login_message = message
            self._persist_admin_authenticated(username)
            self._update_access_status()

            payload = {
                "authenticated": True,
                "username": username,
                "message": message,
            }

            if self._navigate_to(SCREEN_ADMIN_PANEL):
                self.login_succeeded.emit(payload)
                return

            self.login_succeeded.emit(payload)
            return

        self._failed_attempts += 1
        self._last_login_message = message
        self.password_input.clear()

        if self._failed_attempts >= self._max_failed_attempts:
            self._start_lockout()

        self._update_access_status()
        self.login_failed.emit(message)

    # =========================================================================
    # Navigation
    # =========================================================================

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

    # =========================================================================
    # Paint / effects
    # =========================================================================

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        painter = QPainter(self)
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

        painter.fillRect(rect, QColor(4, 14, 28, 176))
        painter.fillRect(QRectF(0, 0, rect.width(), rect.height() * 0.38), QColor(53, 214, 255, 16))
        painter.fillRect(QRectF(0, rect.height() * 0.60, rect.width(), rect.height() * 0.40), QColor(20, 82, 128, 18))

        painter.end()

    # =========================================================================
    # Diagnostics
    # =========================================================================

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "failed_attempts": self._failed_attempts,
            "lockout_seconds_remaining": self._lockout_seconds_remaining,
            "background_path": self._background_path,
            "logo_path": self._logo_small_path,
            "shield_art_path": self._shield_art_path,
            "is_locked_out": self._is_locked_out(),
            "username_text_length": len(safe_str(self.username_input.text(), "")),
            "password_text_length": len(safe_str(self.password_input.text(), "")),
        }
