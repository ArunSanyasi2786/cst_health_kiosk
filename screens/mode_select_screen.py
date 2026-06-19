"""
screens/mode_select_screen.py

Compact but visually rich mode-select / instruction screen tuned for the
800x480 CST Health Monitoring Station kiosk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping, Optional

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
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.logger import get_logger

try:
    from core.utils import safe_bool, safe_str
except Exception:  # pragma: no cover
    def safe_str(value: Any, default: str = "") -> str:
        try:
            if value is None:
                return default
            return str(value)
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
        MODE_DEMO,
        MODE_HARDWARE,
        SCREEN_WELCOME,
        SCREEN_ADMIN_LOGIN,
    )
except Exception:  # pragma: no cover
    MODE_DEMO = "demo"
    MODE_HARDWARE = "hardware"
    SCREEN_WELCOME = "welcome"
    SCREEN_ADMIN_LOGIN = "admin_login"

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


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_asset(relative_path: str) -> str:
    relative_clean = safe_str(relative_path, "").strip().replace("\\", "/").lstrip("/")
    if not relative_clean:
        return ""
    try:
        import core.asset_paths as asset_paths

        for name in ("get_asset_path", "asset_path", "resolve_asset_path", "resolve_asset", "asset"):
            resolver = getattr(asset_paths, name, None)
            if callable(resolver):
                try:
                    resolved = safe_str(resolver(relative_clean), "").strip()
                    if resolved:
                        return resolved
                except Exception:
                    continue
    except Exception:
        pass
    return str(_project_root().joinpath("assets", *relative_clean.split("/")))


def _pixmap_or_empty(path: str) -> QPixmap:
    text = safe_str(path, "").strip()
    return QPixmap(text) if text else QPixmap()


class _ModePillButton(QPushButton):
    def __init__(self, text: str, mode_key: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.mode_key = safe_str(mode_key, "").strip().lower()
        self._selected = False
        self._hovered = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(38)
        self.setMinimumWidth(152)
        self.setMaximumHeight(38)
        self.setMouseTracking(True)
        self._apply_style()

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        self._apply_style()

    def enterEvent(self, event: QEvent) -> None:
        super().enterEvent(event)
        self._hovered = True
        self._apply_style()

    def leaveEvent(self, event: QEvent) -> None:
        super().leaveEvent(event)
        self._hovered = False
        self._apply_style()

    def _apply_style(self) -> None:
        if self._selected:
            border = "rgba(115, 224, 255, 0.82)"
            bg_top = "rgba(59, 157, 255, 0.98)"
            bg_bottom = "rgba(17, 104, 230, 0.98)"
            text = "#F9FDFF"
        elif self._hovered:
            border = "rgba(169, 232, 255, 0.42)"
            bg_top = "rgba(38, 81, 130, 0.88)"
            bg_bottom = "rgba(15, 39, 74, 0.92)"
            text = "#F3FAFF"
        else:
            border = "rgba(144, 210, 255, 0.26)"
            bg_top = "rgba(24, 54, 95, 0.76)"
            bg_bottom = "rgba(10, 28, 57, 0.86)"
            text = "#ECF8FF"
        self.setStyleSheet(
            f"""
            QPushButton {{
                color: {text};
                font-size: 11px;
                font-weight: 800;
                border: 1px solid {border};
                border-radius: 18px;
                padding: 8px 16px;
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {bg_top},
                    stop:1 {bg_bottom}
                );
            }}
            """
        )


class ModeSelectScreen(QFrame):
    back_requested = pyqtSignal()
    mode_selected = pyqtSignal(str)
    demo_requested = pyqtSignal()
    hardware_requested = pyqtSignal()
    demo_mode_selected = pyqtSignal()
    hardware_mode_selected = pyqtSignal()
    continue_requested = pyqtSignal(str)
    refresh_requested = pyqtSignal()
    admin_requested = pyqtSignal()

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
        self._logger = logger
        self.navigator = navigator
        self.app_state = app_state
        self.services = dict(services or {})
        self.animation_manager = animation_manager
        self.theme_manager = theme_manager

        self._selected_mode = self._read_initial_mode()
        self._runtime_snapshot: Dict[str, Any] = {}

        self._background_pixmap = _pixmap_or_empty(_resolve_asset("backgrounds/mode_select_bg.png"))
        self._logo_main_pixmap = _pixmap_or_empty(_resolve_asset("logos/cst_logo_main.png"))
        self._logo_small_pixmap = _pixmap_or_empty(_resolve_asset("logos/17911472.png"))
        self._doctor_left_pixmap = _pixmap_or_empty(_resolve_asset("illustrations/doctor_left.png"))
        self._doctor_right_pixmap = _pixmap_or_empty(_resolve_asset("illustrations/doctor_right.png"))

        self._status_poll_timer = QTimer(self)
        self._status_poll_timer.setInterval(1500)
        self._status_poll_timer.timeout.connect(self._refresh_runtime_status)

        self.setObjectName("ModeSelectScreen")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._build_ui()
        self._setup_effects()
        self._apply_styles()
        self._refresh_runtime_status()
        self._apply_selected_mode_ui(self._selected_mode)
        self._play_entry_animation()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 10, 18, 10)
        root.setSpacing(8)

        self.top_bar = QWidget(self)
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(10)

        self.back_button = self._create_button("Back", variant="secondary", min_width=96, parent=self.top_bar)
        if hasattr(self.back_button, "setMinimumHeight"):
            self.back_button.setMinimumHeight(40)
        if hasattr(self.back_button, "setMaximumHeight"):
            self.back_button.setMaximumHeight(40)
        if hasattr(self.back_button, "setFixedHeight"):
            try:
                self.back_button.setFixedHeight(40)
            except Exception:
                pass
        self.back_button.clicked.connect(self._handle_back_clicked)

        self.logo_badge = QLabel(self.top_bar)
        self.logo_badge.setObjectName("LogoBadge")
        self.logo_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.header_title = QLabel("HEALTH MONITORING STATION", self.top_bar)
        self.header_title.setObjectName("HeaderTitle")
        self.connection_pill = QLabel("Checking runtime…", self.top_bar)
        self.connection_pill.setObjectName("RuntimePill")
        self.port_pill = QLabel("Port Unknown", self.top_bar)
        self.port_pill.setObjectName("RuntimePill")

        top_layout.addWidget(self.back_button, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        top_layout.addWidget(self.logo_badge, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        top_layout.addWidget(self.header_title, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        top_layout.addStretch(1)
        top_layout.addWidget(self.connection_pill, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top_layout.addWidget(self.port_pill, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.main_card = QFrame(self)
        self.main_card.setObjectName("InstructionCard")
        self.main_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        card_layout = QVBoxLayout(self.main_card)
        card_layout.setContentsMargins(18, 14, 18, 12)
        card_layout.setSpacing(6)

        self.brand_row = QWidget(self.main_card)
        brand_layout = QHBoxLayout(self.brand_row)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(6)

        self.brand_logo = QLabel(self.brand_row)
        self.brand_logo.setObjectName("BrandLogo")
        self.brand_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.brand_logo.setFixedSize(56, 56)
        self.brand_logo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        if _HAS_GLOW_LABEL:
            try:
                self.instruction_title = GlowLabel(
                    text="Instructions",
                    parent=self.brand_row,
                    role=getattr(GlowLabel, "ROLE_TITLE", "title"),
                    align_center=False,
                    word_wrap=False,
                    use_outline=False,
                    enable_paint_glow=True,
                    initial_glow_strength=0.28,
                    initial_glow_blur=12,
                )
            except Exception:
                self.instruction_title = QLabel("Instructions", self.brand_row)
        else:
            self.instruction_title = QLabel("Instructions", self.brand_row)
        self.instruction_title.setObjectName("InstructionTitle")
        try:
            self.instruction_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        except Exception:
            pass

        self.mode_selector_wrap = QWidget(self.brand_row)
        mode_selector_layout = QHBoxLayout(self.mode_selector_wrap)
        mode_selector_layout.setContentsMargins(0, 0, 0, 0)
        mode_selector_layout.setSpacing(10)
        self.demo_mode_button = _ModePillButton("Demo Mode", MODE_DEMO, self.mode_selector_wrap)
        self.hardware_mode_button = _ModePillButton("Hardware Mode", MODE_HARDWARE, self.mode_selector_wrap)
        self.demo_mode_button.clicked.connect(lambda: self._on_mode_selected(MODE_DEMO))
        self.hardware_mode_button.clicked.connect(lambda: self._on_mode_selected(MODE_HARDWARE))
        mode_selector_layout.addWidget(self.demo_mode_button)
        mode_selector_layout.addWidget(self.hardware_mode_button)

        brand_layout.addWidget(self.brand_logo, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        brand_layout.addWidget(self.instruction_title, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        brand_layout.addStretch(1)
        brand_layout.addWidget(self.mode_selector_wrap, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.instruction_subtitle = QLabel(
            "Please review the instructions below before starting your health check.", self.main_card
        )
        self.instruction_subtitle.setObjectName("InstructionSubtitle")
        self.instruction_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.instruction_subtitle.setWordWrap(True)

        self.status_hint_row = QWidget(self.main_card)
        status_hint_layout = QHBoxLayout(self.status_hint_row)
        status_hint_layout.setContentsMargins(0, 0, 0, 0)
        status_hint_layout.setSpacing(10)
        self.selected_mode_chip = QLabel("Selected: Demo Mode", self.status_hint_row)
        self.selected_mode_chip.setObjectName("SelectionChip")
        self.hardware_state_chip = QLabel("Hardware status pending", self.status_hint_row)
        self.hardware_state_chip.setObjectName("SelectionChip")
        status_hint_layout.addStretch(1)
        status_hint_layout.addWidget(self.selected_mode_chip)
        status_hint_layout.addWidget(self.hardware_state_chip)
        status_hint_layout.addStretch(1)

        self.content_middle_row = QWidget(self.main_card)
        self.content_middle_row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        middle_layout = QHBoxLayout(self.content_middle_row)
        middle_layout.setContentsMargins(0, 2, 0, 0)
        middle_layout.setSpacing(16)

        self.left_column = QWidget(self.content_middle_row)
        self.left_column.setMinimumWidth(160)
        self.left_column.setMaximumWidth(185)
        left_layout = QVBoxLayout(self.left_column)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)
        left_layout.addStretch(1)
        self.left_doctor_label = QLabel(self.left_column)
        self.left_doctor_label.setObjectName("DoctorArt")
        self.left_doctor_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
        left_layout.addWidget(self.left_doctor_label, 0, alignment=Qt.AlignmentFlag.AlignHCenter)
        left_layout.addStretch(1)
        self.start_button = self._create_button("Start Check Up", variant="primary", min_width=176, parent=self.left_column)
        self.start_button.clicked.connect(self._handle_start_clicked)
        left_layout.addWidget(self.start_button, 0, alignment=Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)

        self.instructions_center_wrap = QFrame(self.content_middle_row)
        self.instructions_center_wrap.setObjectName("InstructionPanel")
        self.instructions_center_wrap.setMinimumWidth(300)
        self.instructions_center_wrap.setMaximumWidth(340)
        self.instructions_center_wrap.setFixedHeight(186)
        center_layout = QVBoxLayout(self.instructions_center_wrap)
        center_layout.setContentsMargins(18, 10, 18, 10)
        center_layout.setSpacing(3)
        self.step_heading = QLabel("How to use the kiosk", self.instructions_center_wrap)
        self.step_heading.setObjectName("StepHeading")
        self.step_heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_layout.addWidget(self.step_heading)
        self.lines = []
        instructions = [
            "1. Stand still on the platform.",
            "2. Place your finger properly until measurement ends.",
            "3. Wait until the result appears on the screen.",
            "4. Do not misuse the kiosk or leave during reading.",
        ]
        for text in instructions:
            lbl = QLabel(text, self.instructions_center_wrap)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setWordWrap(True)
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            self.lines.append(lbl)
            center_layout.addWidget(lbl)
        center_layout.addStretch(1)

        self.right_column = QWidget(self.content_middle_row)
        self.right_column.setMinimumWidth(160)
        self.right_column.setMaximumWidth(185)
        right_layout = QVBoxLayout(self.right_column)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)
        right_layout.addStretch(1)
        self.right_doctor_label = QLabel(self.right_column)
        self.right_doctor_label.setObjectName("DoctorArt")
        self.right_doctor_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
        right_layout.addWidget(self.right_doctor_label, 0, alignment=Qt.AlignmentFlag.AlignHCenter)
        right_layout.addStretch(1)
        self.admin_button = self._create_button("Admin", variant="primary", min_width=176, parent=self.right_column)
        self.admin_button.clicked.connect(self._handle_admin_clicked)
        right_layout.addWidget(self.admin_button, 0, alignment=Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)

        middle_layout.addWidget(self.left_column, 0, alignment=Qt.AlignmentFlag.AlignBottom)
        middle_layout.addStretch(1)
        middle_layout.addWidget(self.instructions_center_wrap, 0, alignment=Qt.AlignmentFlag.AlignVCenter)
        middle_layout.addStretch(1)
        middle_layout.addWidget(self.right_column, 0, alignment=Qt.AlignmentFlag.AlignBottom)

        self.connection_note = QLabel(
            "No confirmed hardware connection is active. Demo mode remains fully available.", self.main_card
        )
        self.connection_note.setObjectName("ConnectionNote")
        self.connection_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.connection_note.setWordWrap(True)

        self.bottom_hint = QLabel(
            "Select the operating mode, then press Start Check Up to continue.", self
        )
        self.bottom_hint.setObjectName("BottomHint")
        self.bottom_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card_layout.addWidget(self.brand_row)
        card_layout.addWidget(self.instruction_subtitle)
        card_layout.addWidget(self.status_hint_row)
        card_layout.addWidget(self.content_middle_row, 1)
        card_layout.addWidget(self.connection_note)

        root.addWidget(self.top_bar)
        root.addWidget(self.main_card, 1)
        root.addWidget(self.bottom_hint)

        self._refresh_static_pixmaps()

    def _create_button(self, text: str, *, variant: str, min_width: int, parent: QWidget) -> QWidget:
        is_back_button = safe_str(text, "").strip().lower() == "back"
        button_height = 56 if variant == "primary" else 40
        button_radius = 18 if variant == "primary" else 16

        if AnimatedButton is not None:
            try:
                variant_map = {
                    "primary": getattr(AnimatedButton, "VARIANT_PRIMARY", None),
                    "secondary": getattr(AnimatedButton, "VARIANT_SECONDARY", None),
                }
                size_key = getattr(AnimatedButton, "SIZE_LG", getattr(AnimatedButton, "SIZE_MD", None))
                if variant == "secondary":
                    size_key = getattr(AnimatedButton, "SIZE_MD", size_key)

                btn = AnimatedButton(
                    text=text,
                    parent=parent,
                    variant=variant_map.get(variant),
                    size=size_key,
                    minimum_width=min_width,
                )

                if hasattr(btn, "setFixedWidth"):
                    btn.setFixedWidth(min_width)
                else:
                    if hasattr(btn, "setMinimumWidth"):
                        btn.setMinimumWidth(min_width)
                    if hasattr(btn, "setMaximumWidth"):
                        btn.setMaximumWidth(min_width)

                if hasattr(btn, "setFixedHeight"):
                    btn.setFixedHeight(button_height)
                else:
                    if hasattr(btn, "setMinimumHeight"):
                        btn.setMinimumHeight(button_height)
                    if hasattr(btn, "setMaximumHeight"):
                        btn.setMaximumHeight(button_height)

                if hasattr(btn, "setSizePolicy"):
                    btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

                if is_back_button:
                    try:
                        if hasattr(btn, "set_accent_color"):
                            btn.set_accent_color("#2F8FFF")
                    except Exception:
                        pass
                    try:
                        if hasattr(btn, "set_text"):
                            btn.set_text("Back")
                    except Exception:
                        pass

                return btn
            except Exception:
                pass

        button = QPushButton(text, parent)
        button.setFixedWidth(min_width)
        button.setFixedHeight(button_height)
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        button.setCursor(Qt.CursorShape.PointingHandCursor)

        if variant == "secondary":
            if is_back_button:
                button.setStyleSheet(
                    f"""
                    QPushButton {{
                        color: #F6FCFF;
                        border: 1px solid rgba(157, 220, 255, 0.34);
                        border-radius: {button_radius}px;
                        padding: 8px 14px;
                        font-size: 13px;
                        font-weight: 800;
                        background: qlineargradient(
                            x1:0, y1:0, x2:0, y2:1,
                            stop:0 rgba(74, 160, 255, 0.98),
                            stop:1 rgba(34, 118, 236, 0.98)
                        );
                    }}
                    QPushButton:hover {{
                        border-color: rgba(186, 233, 255, 0.46);
                        background: qlineargradient(
                            x1:0, y1:0, x2:0, y2:1,
                            stop:0 rgba(92, 174, 255, 0.98),
                            stop:1 rgba(42, 126, 242, 0.98)
                        );
                    }}
                    QPushButton:disabled {{
                        color: rgba(220, 236, 246, 0.48);
                        background: rgba(20, 38, 62, 0.55);
                    }}
                    """
                )
            else:
                button.setStyleSheet(
                    f"""
                    QPushButton {{
                        color: #F6FCFF;
                        border: 1px solid rgba(157, 220, 255, 0.30);
                        border-radius: {button_radius}px;
                        padding: 8px 14px;
                        font-size: 13px;
                        font-weight: 800;
                        background: qlineargradient(
                            x1:0, y1:0, x2:0, y2:1,
                            stop:0 rgba(35, 76, 128, 0.92),
                            stop:1 rgba(13, 34, 67, 0.96)
                        );
                    }}
                    QPushButton:hover {{
                        border-color: rgba(186, 233, 255, 0.44);
                        background: qlineargradient(
                            x1:0, y1:0, x2:0, y2:1,
                            stop:0 rgba(49, 98, 157, 0.96),
                            stop:1 rgba(18, 45, 86, 0.98)
                        );
                    }}
                    QPushButton:disabled {{
                        color: rgba(220, 236, 246, 0.48);
                        background: rgba(20, 38, 62, 0.55);
                    }}
                    """
                )
            return button

        button.setStyleSheet(
            f"""
            QPushButton {{
                color: #F6FCFF;
                border: 1px solid rgba(157, 220, 255, 0.34);
                border-radius: {button_radius}px;
                padding: 12px 18px;
                font-size: 14px;
                font-weight: 800;
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(63, 149, 255, 0.98),
                    stop:1 rgba(24, 107, 232, 0.98)
                );
            }}
            QPushButton:hover {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(82, 166, 255, 0.98),
                    stop:1 rgba(30, 116, 238, 0.98)
                );
                border-color: rgba(186, 233, 255, 0.44);
            }}
            QPushButton:disabled {{
                color: rgba(220, 236, 246, 0.48);
                background: rgba(20, 38, 62, 0.55);
            }}
            """
        )
        return button

    def _set_label_pixmap(self, label: QLabel, pixmap: QPixmap, target_height: int) -> None:
        if pixmap.isNull():
            label.clear()
            return
        scaled = pixmap.scaledToHeight(target_height, Qt.TransformationMode.SmoothTransformation)
        label.setPixmap(scaled)

    def _refresh_static_pixmaps(self) -> None:
        self._set_label_pixmap(self.logo_badge, self._logo_small_pixmap, 42)
        self._set_label_pixmap(self.brand_logo, self._logo_main_pixmap, 56)
        self._set_label_pixmap(self.left_doctor_label, self._doctor_left_pixmap, 148)
        self._set_label_pixmap(self.right_doctor_label, self._doctor_right_pixmap, 148)
        self.left_column.setVisible(self.left_doctor_label.pixmap() is not None and not self.left_doctor_label.pixmap().isNull())
        self.right_column.setVisible(self.right_doctor_label.pixmap() is not None and not self.right_doctor_label.pixmap().isNull())

    def _setup_effects(self) -> None:
        self.card_opacity = QGraphicsOpacityEffect(self.main_card)
        self.bottom_opacity = QGraphicsOpacityEffect(self.bottom_hint)
        self.main_card.setGraphicsEffect(self.card_opacity)
        self.bottom_hint.setGraphicsEffect(self.bottom_opacity)
        self.card_opacity.setOpacity(0.0)
        self.bottom_opacity.setOpacity(0.0)
        self.entry_anim_group = QParallelAnimationGroup(self)
        self.card_fade = QPropertyAnimation(self.card_opacity, b"opacity", self)
        self.card_fade.setDuration(340)
        self.card_fade.setStartValue(0.0)
        self.card_fade.setEndValue(1.0)
        self.card_fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.bottom_fade = QPropertyAnimation(self.bottom_opacity, b"opacity", self)
        self.bottom_fade.setDuration(520)
        self.bottom_fade.setStartValue(0.0)
        self.bottom_fade.setEndValue(1.0)
        self.bottom_fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.entry_anim_group.addAnimation(self.card_fade)
        self.entry_anim_group.addAnimation(self.bottom_fade)

        self._card_shadow = QGraphicsDropShadowEffect(self)
        self._card_shadow.setBlurRadius(28)
        self._card_shadow.setOffset(0, 6)
        c = QColor("#39D8FF")
        c.setAlpha(44)
        self._card_shadow.setColor(c)

    def _play_entry_animation(self) -> None:
        try:
            self.entry_anim_group.start()
        except Exception:
            pass
        QTimer.singleShot(600, self._attach_card_shadow)

    def _attach_card_shadow(self) -> None:
        try:
            self.main_card.setGraphicsEffect(self._card_shadow)
        except Exception:
            pass

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QFrame#ModeSelectScreen { background: transparent; }
            QLabel#LogoBadge {
                min-width: 42px; max-width: 42px; min-height: 42px; max-height: 42px;
                border-radius: 0px;
                border: none;
                background: transparent;
            }
            QLabel#HeaderTitle {
                color: #F6FCFF; font-size: 14px; font-weight: 900; letter-spacing: 0.2px;
                background: transparent;
            }
            QLabel#RuntimePill {
                color: #EEF9FF; font-size: 10px; font-weight: 700;
                border: 1px solid rgba(157, 220, 255, 0.24);
                border-radius: 14px; background: rgba(18, 39, 70, 0.56);
                padding: 6px 10px;
            }
            QFrame#InstructionCard {
                border: 1px solid rgba(170, 230, 255, 0.24);
                border-radius: 24px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(18, 42, 76, 0.80),
                    stop:1 rgba(7, 22, 46, 0.90)
                );
            }
            QFrame#InstructionPanel {
                border: 1px solid rgba(175, 229, 255, 0.14);
                border-radius: 22px;
                background: rgba(255, 255, 255, 0.06);
            }
            QLabel#BrandLogo {
                min-width: 56px; max-width: 56px; min-height: 56px; max-height: 56px;
                border-radius: 0px;
                background: transparent;
                border: none;
            }
            QLabel#InstructionTitle {
                color: #F7FCFF; font-size: 22px; font-weight: 900; background: transparent;
            }
            QLabel#InstructionSubtitle {
                color: rgba(217, 236, 248, 0.88); font-size: 11px; font-weight: 500; background: transparent;
            }
            QLabel#SelectionChip {
                color: #EEF9FF; font-size: 10px; font-weight: 800;
                border: 1px solid rgba(157, 220, 255, 0.24);
                border-radius: 14px; background: rgba(18, 39, 70, 0.56);
                padding: 6px 10px;
            }
            QLabel#DoctorArt { background: transparent; }
            QLabel#StepHeading {
                color: #F8FDFF; font-size: 15px; font-weight: 900; background: transparent;
            }
            QLabel#ConnectionNote, QLabel#BottomHint {
                color: rgba(221, 240, 250, 0.88); font-size: 10px; font-weight: 600; background: transparent;
            }
            """
        )
        if _HAS_GLOW_LABEL and isinstance(self.instruction_title, GlowLabel):
            try:
                self.instruction_title.set_glow_color("#43D9FF")
                self.instruction_title.set_text_color("#F7FCFF")
                self.instruction_title.set_text("Instructions")
            except Exception:
                self.instruction_title.setText("Instructions")
        else:
            self.instruction_title.setText("Instructions")
        for lbl in self.lines:
            lbl.setStyleSheet(
                "QLabel { color: #F7FCFF; font-size: 11px; font-weight: 700; background: transparent; }"
            )

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._status_poll_timer.start()
        self._refresh_runtime_status()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._status_poll_timer.stop()

    def _read_initial_mode(self) -> str:
        mode = MODE_DEMO
        try:
            if self.app_state is not None:
                for attr_name in ("current_mode", "mode", "selected_mode"):
                    attr = getattr(self.app_state, attr_name, None)
                    if isinstance(attr, str) and attr.strip():
                        mode = attr.strip().lower()
                        break
                    if callable(attr):
                        result = attr()
                        if isinstance(result, str) and result.strip():
                            mode = result.strip().lower()
                            break
        except Exception:
            pass
        try:
            mode_service = self.services.get("mode_service") or self.services.get("mode")
            if mode_service is not None:
                for method_name in ("current_mode", "get_mode", "mode"):
                    method = getattr(mode_service, method_name, None)
                    if callable(method):
                        result = safe_str(method(), "").strip().lower()
                        if result:
                            mode = result
                            break
        except Exception:
            pass
        return mode if mode in {MODE_DEMO, MODE_HARDWARE} else MODE_DEMO

    def _runtime_snapshot_from_services(self) -> Dict[str, Any]:
        snapshot: Dict[str, Any] = {
            "mode": self._selected_mode,
            "connected": False,
            "waiting": False,
            "port": "",
            "detail": "",
            "available_ports": [],
        }
        try:
            if self.app_state is not None:
                method = getattr(self.app_state, "connection_snapshot", None)
                if callable(method):
                    raw = method()
                    if isinstance(raw, Mapping):
                        snapshot.update(dict(raw))
        except Exception:
            pass
        try:
            connection_service = self.services.get("connection_service") or self.services.get("connection")
            if connection_service is not None:
                for method_name in ("snapshot", "get_snapshot", "connection_snapshot"):
                    method = getattr(connection_service, method_name, None)
                    if callable(method):
                        raw = method()
                        if isinstance(raw, Mapping):
                            snapshot.update(dict(raw))
                            break
        except Exception:
            pass
        connected = bool(snapshot.get("connected", False)) or bool(snapshot.get("serial_connected", False)) or bool(snapshot.get("esp32_connected", False))
        waiting = bool(snapshot.get("waiting", False))
        available_ports = snapshot.get("available_ports", [])
        if not waiting and not connected and isinstance(available_ports, list) and available_ports:
            waiting = True
        port = safe_str(snapshot.get("port"), "").strip()
        if not port and isinstance(available_ports, list) and available_ports:
            port = safe_str(available_ports[0], "").strip()
        detail = safe_str(snapshot.get("detail"), "").strip()
        if not detail:
            if connected:
                detail = "Live hardware detected. Hardware mode can use real-time sensor measurement."
            elif waiting:
                detail = "Possible serial device detected. Hardware mode may connect on the next screen."
            else:
                detail = "No confirmed hardware connection is active. Demo mode remains fully available."
        snapshot.update({"connected": connected, "waiting": waiting, "port": port, "detail": detail})
        return snapshot

    def _refresh_runtime_status(self) -> None:
        self._runtime_snapshot = self._runtime_snapshot_from_services()
        connected = bool(self._runtime_snapshot.get("connected", False))
        waiting = bool(self._runtime_snapshot.get("waiting", False))
        port = safe_str(self._runtime_snapshot.get("port"), "").strip()
        detail = safe_str(self._runtime_snapshot.get("detail"), "").strip()
        if connected:
            self.connection_pill.setText("Hardware Connected")
            self._apply_runtime_pill_style(self.connection_pill, "#42E393")
            self.hardware_state_chip.setText("Hardware ready")
            self._apply_selection_chip_style(self.hardware_state_chip, "#42E393")
        elif waiting:
            self.connection_pill.setText("Waiting for Device")
            self._apply_runtime_pill_style(self.connection_pill, "#FFD25E")
            self.hardware_state_chip.setText("Possible serial device detected")
            self._apply_selection_chip_style(self.hardware_state_chip, "#FFD25E")
        else:
            self.connection_pill.setText("No Hardware Link")
            self._apply_runtime_pill_style(self.connection_pill, "#FF6E88")
            self.hardware_state_chip.setText("No confirmed hardware link")
            self._apply_selection_chip_style(self.hardware_state_chip, "#FF6E88")
        self.port_pill.setText(port if port else "Port Unknown")
        self._apply_runtime_pill_style(self.port_pill, "#67D8FF")
        self.connection_note.setText(detail)
        self._apply_selected_mode_ui(self._selected_mode)

    def _apply_runtime_pill_style(self, label: QLabel, accent_hex: str) -> None:
        accent = QColor(accent_hex)
        label.setStyleSheet(
            f"""
            QLabel {{
                color: #EEF9FF; font-size: 10px; font-weight: 700;
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.34);
                border-radius: 14px; background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.15);
                padding: 6px 10px;
            }}
            """
        )

    def _apply_selection_chip_style(self, label: QLabel, accent_hex: str) -> None:
        accent = QColor(accent_hex)
        label.setStyleSheet(
            f"""
            QLabel {{
                color: #EEF9FF; font-size: 10px; font-weight: 800;
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.34);
                border-radius: 14px; background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.15);
                padding: 6px 10px;
            }}
            """
        )

    def selected_mode(self) -> str:
        return self._selected_mode

    def set_selected_mode(self, mode: str, *, emit_signal: bool = False) -> None:
        mode_text = safe_str(mode, MODE_DEMO).strip().lower() or MODE_DEMO
        if mode_text not in {MODE_DEMO, MODE_HARDWARE}:
            mode_text = MODE_DEMO
        self._selected_mode = mode_text
        self._apply_selected_mode_ui(mode_text)
        if emit_signal:
            self.mode_selected.emit(mode_text)

    def _apply_selected_mode_ui(self, mode: str) -> None:
        connected = bool(self._runtime_snapshot.get("connected", False))
        waiting = bool(self._runtime_snapshot.get("waiting", False))
        self.demo_mode_button.set_selected(mode == MODE_DEMO)
        self.hardware_mode_button.set_selected(mode == MODE_HARDWARE)
        if mode == MODE_DEMO:
            self.selected_mode_chip.setText("Selected: Demo Mode")
            self._apply_selection_chip_style(self.selected_mode_chip, "#67D8FF")
        else:
            accent = "#42E393" if connected else ("#FFD25E" if waiting else "#FF6E88")
            self.selected_mode_chip.setText("Selected: Hardware Mode")
            self._apply_selection_chip_style(self.selected_mode_chip, accent)

    def _on_mode_selected(self, mode_key: str) -> None:
        self.set_selected_mode(mode_key, emit_signal=True)
        if mode_key == MODE_DEMO:
            self.demo_mode_selected.emit()
        else:
            self.hardware_mode_selected.emit()

    def _persist_mode(self, mode: str) -> None:
        mode_text = safe_str(mode, MODE_DEMO).strip().lower() or MODE_DEMO
        try:
            mode_service = self.services.get("mode_service") or self.services.get("mode")
            if mode_service is not None:
                for method_name in ("set_mode", "select_mode", "activate_mode", "update_mode"):
                    method = getattr(mode_service, method_name, None)
                    if callable(method):
                        try:
                            method(mode_text)
                            break
                        except Exception:
                            continue
        except Exception:
            pass
        try:
            if self.app_state is not None:
                for name in ("current_mode", "mode"):
                    if hasattr(self.app_state, name):
                        try:
                            setattr(self.app_state, name, mode_text)
                        except Exception:
                            pass
                for method_name in ("set_mode", "update_mode", "select_mode"):
                    method = getattr(self.app_state, method_name, None)
                    if callable(method):
                        try:
                            method(mode_text)
                            break
                        except Exception:
                            continue
        except Exception:
            pass

    def _handle_back_clicked(self) -> None:
        if self._navigate_to(SCREEN_WELCOME):
            return
        self.back_requested.emit()

    def _handle_start_clicked(self) -> None:
        mode = self._selected_mode or MODE_DEMO
        self._persist_mode(mode)
        self.continue_requested.emit(mode)
        if mode == MODE_DEMO:
            self.demo_requested.emit()
        else:
            self.hardware_requested.emit()

    def _handle_admin_clicked(self) -> None:
        if self._navigate_to(SCREEN_ADMIN_LOGIN):
            return
        self.admin_requested.emit()

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

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        width = self.width()
        self._refresh_static_pixmaps()
        compact = width <= 820
        if compact:
            self.instructions_center_wrap.setMinimumWidth(290)
            self.instructions_center_wrap.setMaximumWidth(330)
            self.instructions_center_wrap.setFixedHeight(186)
            self._set_label_pixmap(self.left_doctor_label, self._doctor_left_pixmap, 138)
            self._set_label_pixmap(self.right_doctor_label, self._doctor_right_pixmap, 138)
            self.connection_pill.setVisible(width > 690)
            self.port_pill.setVisible(width > 760)
        else:
            self.instructions_center_wrap.setMinimumWidth(320)
            self.instructions_center_wrap.setMaximumWidth(360)
            self.instructions_center_wrap.setFixedHeight(194)
            self._set_label_pixmap(self.left_doctor_label, self._doctor_left_pixmap, 150)
            self._set_label_pixmap(self.right_doctor_label, self._doctor_right_pixmap, 150)
            self.connection_pill.setVisible(True)
            self.port_pill.setVisible(True)

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
            painter.fillRect(rect, QColor(4, 14, 28, 150))
            painter.fillRect(QRectF(0.0, 0.0, float(rect.width()), rect.height() * 0.38), QColor(53, 214, 255, 12))
            painter.fillRect(QRectF(0.0, rect.height() * 0.58, float(rect.width()), rect.height() * 0.42), QColor(20, 82, 128, 12))
            if self.instructions_center_wrap.isVisible():
                panel_rect = self.instructions_center_wrap.geometry()
                rounded = QPainterPath()
                rounded.addRoundedRect(QRectF(panel_rect), 22.0, 22.0)
                painter.fillPath(rounded, QColor(31, 56, 90, 28))
                painter.setPen(QColor(175, 229, 255, 24))
                painter.drawPath(rounded)
        finally:
            painter.end()

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "selected_mode": self._selected_mode,
            "runtime_snapshot": dict(self._runtime_snapshot),
        }


SecondScreen = ModeSelectScreen
