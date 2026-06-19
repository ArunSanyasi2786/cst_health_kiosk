"""

screens/admin_panel_screen.py



Premium administrator dashboard screen for the CST Health Monitoring Station kiosk.



Why this file matters:

- It is the main protected administrator workspace after successful login

- It is the launch point for:

    - screens/settings_screen.py

    - screens/calibration_screen.py

    - screens/parameters_screen.py

    - screens/diagnosis_screen.py

    - screens/storage_screen.py

    - screens/publish_screen.py

- It is designed specifically for:

    - Raspberry Pi 4B touchscreen kiosk deployment

    - 1024x600 kiosk resolution

    - laptop demo mode

- It provides:

    - premium glossy protected dashboard feel

    - admin identity / session context

    - runtime overview and hardware status

    - quick access cards for all protected modules

    - resilient status aggregation from multiple services

    - logout and back navigation support



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

- services/calibration_service.py

- services/threshold_service.py

- services/diagnosis_service.py

- services/storage_service.py

- services/publish_service.py

- services/session_service.py

- services/connection_service.py

- services/database_service.py

- widgets/animated_button.py

- widgets/glow_label.py



Design goals:

- glossy futuristic blue medical UI

- clear protected-control dashboard

- strong readability at 1024x600

- resilient integration while backend files continue evolving

- maintainable structure with safe fallbacks

"""



from __future__ import annotations



from pathlib import Path

from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple



from PyQt6.QtCore import (

    QEasingCurve,

    QEvent,

    QParallelAnimationGroup,

    QPropertyAnimation,

    QRectF,

    Qt,

    pyqtSignal,

)

from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPixmap

from PyQt6.QtWidgets import (

    QFrame,

    QGraphicsDropShadowEffect,

    QGraphicsOpacityEffect,

    QGridLayout,

    QHBoxLayout,

    QLabel,

    QPushButton,

    QSizePolicy,

    QVBoxLayout,

    QWidget,

)



from core.logger import get_logger



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



    def safe_int(value: Any, default: int = 0) -> int:

        try:

            if value is None or value == "":

                return default

            return int(float(value))

        except Exception:

            return default



    def safe_float(value: Any, default: float = 0.0) -> float:

        try:

            if value is None or value == "":

                return default

            return float(value)

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

        SCREEN_ADMIN_LOGIN,

        SCREEN_CALIBRATION,

        SCREEN_DIAGNOSIS,

        SCREEN_PARAMETERS,

        SCREEN_PUBLISH,

        SCREEN_SETTINGS,

        SCREEN_STORAGE,

        SCREEN_WELCOME,

        SCREEN_MODE_SELECT,

    )

except Exception:  # pragma: no cover

    MODE_DEMO = "demo"

    MODE_HARDWARE = "hardware"



    SCREEN_WELCOME = "welcome"

    SCREEN_MODE_SELECT = "mode_select"

    SCREEN_ADMIN_LOGIN = "admin_login"

    SCREEN_SETTINGS = "settings"

    SCREEN_CALIBRATION = "calibration"

    SCREEN_PARAMETERS = "parameters"

    SCREEN_DIAGNOSIS = "diagnosis"

    SCREEN_STORAGE = "storage"

    SCREEN_PUBLISH = "publish"



try:

    from config import (

        KIOSK_WIDTH,

        KIOSK_HEIGHT,

        UI_SCALE,

        WIDTH_SCALE,

        HEIGHT_SCALE,

        IS_COMPACT_KIOSK,

    )

except Exception:  # pragma: no cover

    KIOSK_WIDTH = 800

    KIOSK_HEIGHT = 480

    UI_SCALE = 0.82

    WIDTH_SCALE = KIOSK_WIDTH / 1024.0

    HEIGHT_SCALE = KIOSK_HEIGHT / 600.0

    IS_COMPACT_KIOSK = KIOSK_WIDTH <= 900 or KIOSK_HEIGHT <= 560



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





def _clamp(value: float, minimum: int, maximum: int) -> int:

    return max(minimum, min(int(round(value)), maximum))





def _ui(value: float, minimum: int = 1, maximum: int = 9999) -> int:

    return _clamp(value * UI_SCALE, minimum, maximum)





def _w(value: float, minimum: int = 1, maximum: int = 9999) -> int:

    return _clamp(value * WIDTH_SCALE, minimum, maximum)





def _h(value: float, minimum: int = 1, maximum: int = 9999) -> int:

    return _clamp(value * HEIGHT_SCALE, minimum, maximum)





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





def _accent_for_state(state: str) -> str:

    value = safe_str(state, "").strip().lower()

    if value in {"critical", "error", "failed", "offline", "locked"}:

        return "#FF6E88"

    if value in {"warning", "pending", "attention", "waiting"}:

        return "#FFD25E"

    if value in {"normal", "ready", "connected", "ok", "active", "healthy", "success"}:

        return "#42E393"

    return "#39D8FF"





def _dark_fill_from_accent(accent_hex: str, *, lift: int = 0) -> QColor:

    accent = QColor(safe_str(accent_hex, "#39D8FF").strip() or "#39D8FF")

    red = max(8, min(255, int(accent.red() * 0.22) + 10 + lift))

    green = max(14, min(255, int(accent.green() * 0.24) + 12 + lift))

    blue = max(20, min(255, int(accent.blue() * 0.26) + 20 + lift))

    return QColor(red, green, blue)





# =============================================================================

# Internal widgets

# =============================================================================



class _AdminStatCard(QFrame):

    """

    Compact premium stat card for key system/admin dashboard metrics.

    """



    def __init__(

        self,

        title: str,

        *,

        value: str = "--",

        subtitle: str = "",

        accent_hex: str = "#39D8FF",

        parent: Optional[QWidget] = None,

    ) -> None:

        super().__init__(parent)



        self._accent_hex = accent_hex

        self._compact = IS_COMPACT_KIOSK

        self._ultra_compact = False



        self.setObjectName("AdminStatCard")

        self.setMinimumHeight(_h(84, 72, 98))

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)



        root = QVBoxLayout(self)

        root.setContentsMargins(_ui(12, 8, 14), _ui(10, 8, 12), _ui(12, 8, 14), _ui(10, 8, 12))

        root.setSpacing(_ui(3, 2, 5))



        self.title_label = QLabel(title, self)

        self.value_label = QLabel(value, self)

        self.subtitle_label = QLabel(subtitle, self)

        self.subtitle_label.setWordWrap(True)



        root.addWidget(self.title_label)

        root.addWidget(self.value_label)

        root.addWidget(self.subtitle_label)

        root.addStretch(1)



        self._apply_style()



    def set_payload(self, *, value: str, subtitle: str, accent_hex: str) -> None:

        self._accent_hex = safe_str(accent_hex, "#39D8FF").strip() or "#39D8FF"

        self.value_label.setText(safe_str(value, "--").strip() or "--")

        self.subtitle_label.setText(safe_str(subtitle, "").strip())

        self._apply_style()



    def set_compact(self, compact: bool, ultra_compact: bool = False) -> None:

        self._compact = bool(compact)

        self._ultra_compact = bool(ultra_compact)

        self.setMinimumHeight(72 if self._ultra_compact else 80 if self._compact else _h(84, 76, 98))

        layout = self.layout()

        if isinstance(layout, QVBoxLayout):

            pad_x = 10 if self._compact else _ui(12, 8, 14)

            pad_y = 8 if self._compact else _ui(10, 8, 12)

            layout.setContentsMargins(pad_x, pad_y, pad_x, pad_y)

            layout.setSpacing(2 if self._compact else _ui(3, 2, 5))

        self.subtitle_label.setVisible(not self._ultra_compact)

        self._apply_style()



    def _apply_style(self) -> None:

        accent = QColor(self._accent_hex)

        base = _dark_fill_from_accent(self._accent_hex)

        radius = 18 if self._ultra_compact else 20 if self._compact else 22



        self.setStyleSheet(

            f"""

            QFrame#AdminStatCard {{

                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.88);

                border-radius: {radius}px;

                background: rgba({base.red()}, {base.green()}, {base.blue()}, 1.0);

            }}

            """

        )

        title_size = 9 if self._ultra_compact else 10 if self._compact else 11

        value_size = 17 if self._ultra_compact else 19 if self._compact else 22

        subtitle_size = 7 if self._ultra_compact else 8 if self._compact else 9



        self.title_label.setStyleSheet(

            f"""

            QLabel {{

                color: rgba(218, 233, 244, 0.92);

                font-size: {title_size}px;

                font-weight: 700;

                background: transparent;

            }}

            """

        )

        self.value_label.setStyleSheet(

            f"""

            QLabel {{

                color: #F8FDFF;

                font-size: {value_size}px;

                font-weight: 900;

                background: transparent;

            }}

            """

        )

        self.subtitle_label.setStyleSheet(

            f"""

            QLabel {{

                color: rgba(186, 208, 224, 0.92);

                font-size: {subtitle_size}px;

                font-weight: 600;

                background: transparent;

            }}

            """

        )







class _AdminActionCard(QFrame):

    """

    Clickable premium action card for protected admin modules.



    Compact dashboard intent:

    - thick, fully filled, dark rounded tiles

    - icon and title on the same line

    - larger icon that fits the left cutout better

    - no description text shown inside compact tiles

    - stable hover feedback with no disappearing / glass fade behavior

    - visual language close to the thick rounded action buttons used in the

      kiosk, but scaled up for module-tile use

    """



    clicked = pyqtSignal(str)



    def __init__(

        self,

        action_key: str,

        *,

        title: str,

        subtitle: str,

        info_line_1: str,

        info_line_2: str,

        icon_path: str = "",

        parent: Optional[QWidget] = None,

    ) -> None:

        super().__init__(parent)



        self.action_key = safe_str(action_key, "").strip().lower()

        self._title_text = safe_str(title, "").strip() or "Module"

        self._subtitle_text = safe_str(subtitle, "").strip()

        self._info_line_1_text = safe_str(info_line_1, "").strip()

        self._info_line_2_text = safe_str(info_line_2, "").strip()

        self._hovered = False

        self._pressed = False

        self._clickable = True

        self._compact = IS_COMPACT_KIOSK

        self._ultra_compact = False

        self._accent_hex = "#39D8FF"

        self._tile_fill_hex = "#0C3154"

        self._icon_path = safe_str(icon_path, "").strip()

        self._icon_pixmap = _pixmap_or_empty(self._icon_path)



        self.setObjectName("AdminActionCard")

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.setMouseTracking(True)

        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.setMinimumHeight(82)

        self.setMaximumHeight(88)



        self._root_layout = QHBoxLayout(self)

        self._root_layout.setContentsMargins(16, 10, 16, 10)

        self._root_layout.setSpacing(14)



        self.icon_label = QLabel(self)

        self.icon_label.setObjectName("AdminActionIcon")

        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.icon_label.setMinimumSize(60, 60)

        self.icon_label.setMaximumSize(60, 60)



        self.center_wrap = QWidget(self)

        self.center_wrap.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

        self._center_layout = QVBoxLayout(self.center_wrap)

        self._center_layout.setContentsMargins(0, 0, 0, 0)

        self._center_layout.setSpacing(0)



        self.title_row = QWidget(self.center_wrap)

        self.title_row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

        self._title_layout = QHBoxLayout(self.title_row)

        self._title_layout.setContentsMargins(0, 0, 0, 0)

        self._title_layout.setSpacing(10)



        self.title_label = QLabel(self._title_text, self.title_row)

        self.title_label.setObjectName("AdminActionTitle")

        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.title_label.setWordWrap(False)

        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)



        self.state_chip = QLabel("Open", self.title_row)

        self.state_chip.setObjectName("AdminActionChip")

        self.state_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.state_chip.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)



        self._title_layout.addWidget(self.title_label, 1)

        self.state_chip.hide()



        # Keep the full data fields in the widget so the code remains complete

        # and future non-compact modes can still reuse the same object.

        self.detail_container = QWidget(self.center_wrap)

        self.detail_container.setVisible(False)

        self._detail_layout = QVBoxLayout(self.detail_container)

        self._detail_layout.setContentsMargins(0, 0, 0, 0)

        self._detail_layout.setSpacing(2)



        self.subtitle_label = QLabel(self._subtitle_text, self.detail_container)

        self.subtitle_label.setWordWrap(True)

        self.info_line_1 = QLabel(f"• {self._info_line_1_text}" if self._info_line_1_text else "", self.detail_container)

        self.info_line_2 = QLabel(f"• {self._info_line_2_text}" if self._info_line_2_text else "", self.detail_container)



        self._detail_layout.addWidget(self.subtitle_label)

        self._detail_layout.addWidget(self.info_line_1)

        self._detail_layout.addWidget(self.info_line_2)



        self._center_layout.addStretch(1)

        self._center_layout.addWidget(self.title_row)

        self._center_layout.addWidget(self.detail_container)

        self._center_layout.addStretch(1)



        self._root_layout.addWidget(self.icon_label, 0, alignment=Qt.AlignmentFlag.AlignVCenter)

        self._root_layout.addWidget(self.center_wrap, 1)



        self._refresh_icon()

        self._apply_style()



    def set_payload(

        self,

        *,

        state_text: str,

        accent_hex: str,

        subtitle: Optional[str] = None,

        info_line_1: Optional[str] = None,

        info_line_2: Optional[str] = None,

    ) -> None:

        self._accent_hex = safe_str(accent_hex, "#39D8FF").strip() or "#39D8FF"

        self._tile_fill_hex = self._resolve_tile_fill_hex(self._accent_hex)

        self.state_chip.setText(safe_str(state_text, "Open").strip() or "Open")



        if subtitle is not None:

            self._subtitle_text = safe_str(subtitle, "").strip()

            self.subtitle_label.setText(self._subtitle_text)

        if info_line_1 is not None:

            self._info_line_1_text = safe_str(info_line_1, "").strip()

            self.info_line_1.setText(f"• {self._info_line_1_text}" if self._info_line_1_text else "")

        if info_line_2 is not None:

            self._info_line_2_text = safe_str(info_line_2, "").strip()

            self.info_line_2.setText(f"• {self._info_line_2_text}" if self._info_line_2_text else "")



        self.detail_container.setVisible(False)

        self._apply_style()



    def set_clickable(self, clickable: bool) -> None:

        self._clickable = bool(clickable)

        self.setCursor(Qt.CursorShape.PointingHandCursor if self._clickable else Qt.CursorShape.ArrowCursor)



    def set_compact(self, compact: bool, ultra_compact: bool = False) -> None:

        self._compact = bool(compact)

        self._ultra_compact = bool(ultra_compact)



        min_h = 82 if self._ultra_compact else 86 if self._compact else 96

        max_h = 88 if self._ultra_compact else 90 if self._compact else 100

        self.setMinimumHeight(min_h)

        self.setMaximumHeight(max_h)



        pad_x = 16 if self._compact else 18

        pad_y = 10 if self._compact else 12

        spacing = 14 if self._compact else 16

        self._root_layout.setContentsMargins(pad_x, pad_y, pad_x, pad_y)

        self._root_layout.setSpacing(spacing)

        self._title_layout.setSpacing(10 if self._compact else 12)



        icon_box = 58 if self._ultra_compact else 62 if self._compact else 66

        self.icon_label.setMinimumSize(icon_box, icon_box)

        self.icon_label.setMaximumSize(icon_box, icon_box)



        self.detail_container.setVisible(False)

        self.subtitle_label.setVisible(False)

        self.info_line_1.setVisible(False)

        self.info_line_2.setVisible(False)



        self._refresh_icon()

        self._apply_style()



    def _resolve_tile_fill_hex(self, accent_hex: str) -> str:

        action = self.action_key

        palette = {

            "settings": "#13334F",

            "calibration": "#523B11",

            "parameters": "#103E2A",

            "diagnosis": "#15385B",

            "storage": "#0C4150",

            "publish": "#262C61",

        }

        if action in palette:

            return palette[action]



        return _dark_fill_from_accent(accent_hex).name()





    def _refresh_icon(self) -> None:

        box = 56 if self._ultra_compact else 62 if self._compact else 68

        icon_px = 36 if self._ultra_compact else 42 if self._compact else 46

        self.icon_label.setMinimumSize(box, box)

        self.icon_label.setMaximumSize(box, box)



        if self._icon_pixmap.isNull():

            self.icon_label.clear()

            return



        scaled = self._icon_pixmap.scaled(

            icon_px,

            icon_px,

            Qt.AspectRatioMode.KeepAspectRatio,

            Qt.TransformationMode.SmoothTransformation,

        )

        self.icon_label.setPixmap(scaled)



    def _apply_style(self) -> None:

        accent = QColor(self._accent_hex)

        fill = QColor(self._tile_fill_hex)



        if self._pressed:

            bg = QColor(max(0, fill.red() - 10), max(0, fill.green() - 10), max(0, fill.blue() - 10))

            border_alpha = 0.98

        elif self._hovered:

            bg = QColor(max(0, fill.red() - 2), max(0, fill.green() - 2), max(0, fill.blue() - 2))

            border_alpha = 0.94

        else:

            bg = fill

            border_alpha = 0.88



        radius = 20 if self._ultra_compact else 22 if self._compact else 24

        self.setStyleSheet(

            f"""

            QFrame#AdminActionCard {{

                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, {border_alpha:.3f});

                border-radius: {radius}px;

                background: rgba({bg.red()}, {bg.green()}, {bg.blue()}, 1.0);

            }}

            """

        )



        icon_bg = QColor(min(255, bg.red() + 8), min(255, bg.green() + 8), min(255, bg.blue() + 8))

        self.icon_label.setStyleSheet(

            f"""

            QLabel#AdminActionIcon {{

                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.82);

                border-radius: {18 if self._compact else 20}px;

                background: rgba({icon_bg.red()}, {icon_bg.green()}, {icon_bg.blue()}, 1.0);

            }}

            """

        )



        title_size = 14 if self._ultra_compact else 15 if self._compact else 17

        self.title_label.setStyleSheet(

            f"""

            QLabel#AdminActionTitle {{

                color: #F7FCFF;

                font-size: {title_size}px;

                font-weight: 900;

                background: transparent;

            }}

            """

        )



        self.subtitle_label.setVisible(False)

        self.info_line_1.setVisible(False)

        self.info_line_2.setVisible(False)

        self.detail_container.setVisible(False)

        self.state_chip.setVisible(False)

        self.state_chip.setFixedSize(0, 0)

        self.state_chip.setStyleSheet("QLabel#AdminActionChip { background: transparent; border: none; }")





    def enterEvent(self, event: QEvent) -> None:

        super().enterEvent(event)

        if not self._clickable:

            return

        self._hovered = True

        self._apply_style()



    def leaveEvent(self, event: QEvent) -> None:

        super().leaveEvent(event)

        self._hovered = False

        self._pressed = False

        self._apply_style()



    def mousePressEvent(self, event) -> None:

        super().mousePressEvent(event)

        if self._clickable and event is not None and event.button() == Qt.MouseButton.LeftButton:

            self._pressed = True

            self._apply_style()



    def mouseReleaseEvent(self, event) -> None:

        super().mouseReleaseEvent(event)

        self._pressed = False

        self._apply_style()

        if self._clickable and event is not None and event.button() == Qt.MouseButton.LeftButton:

            self.clicked.emit(self.action_key)



    def paintEvent(self, event) -> None:

        # Keep the tiles solid and stable. The stylesheet paints the full tile,

        # and we intentionally avoid any extra gloss overlays here because the

        # admin dashboard should feel darker and cleaner.

        super().paintEvent(event)

        return





# =============================================================================

# Main screen

# =============================================================================



class AdminPanelScreen(QFrame):

    """

    Premium protected admin dashboard.



    Main responsibilities:

    - aggregate status from services

    - present protected module shortcuts

    - show admin session/user context

    - support logout and module navigation

    """



    back_requested = pyqtSignal()

    logout_requested = pyqtSignal()

    dashboard_loaded = pyqtSignal(dict)

    action_requested = pyqtSignal(str)



    settings_requested = pyqtSignal()

    calibration_requested = pyqtSignal()

    parameters_requested = pyqtSignal()

    diagnosis_requested = pyqtSignal()

    storage_requested = pyqtSignal()

    publish_requested = pyqtSignal()



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



        self._logger = logger.bind(component="AdminPanelScreen")



        self.navigator = navigator

        self.app_state = app_state

        self.services = dict(services or {})

        self.animation_manager = animation_manager

        self.theme_manager = theme_manager



        self._snapshot: Dict[str, Any] = {}

        self._compact = IS_COMPACT_KIOSK

        self._ultra_compact = False

        self._action_specs: List[Tuple[str, str, str, str, str, str, int, int]] = []



        self._background_path = _resolve_asset("backgrounds/admin_panel_bg.png")

        self._logo_small_path = _resolve_asset("logos/images__3_-removebg-preview (1).png")

        self._admin_shield_path = _resolve_asset("illustrations/admin_shield.png")



        self._settings_icon_path = _resolve_asset("icons/images__4_-removebg-preview.png")

        self._calibrate_icon_path = _resolve_asset("icons/30c2378751c8a377d989890da16284d2_icon.png")

        self._parameters_icon_path = _resolve_asset("icons/a350f2d62329376b20cb10e77e3bc804_icon.png")

        self._diagnosis_icon_path = _resolve_asset("icons/dpngtree-multimedia-settings-icon-with-play-button-isolated-parameters-communication-vector-png-image_38089900-removebg-preview.png")

        self._storage_icon_path = _resolve_asset("icons/3812117.png")

        self._publish_icon_path = _resolve_asset("icons/10104041.png")

        self._logout_icon_path = _resolve_asset("icons/6188017.png")



        self._background_pixmap = _pixmap_or_empty(self._background_path)

        self._logo_pixmap = _pixmap_or_empty(self._logo_small_path)

        self._shield_pixmap = _pixmap_or_empty(self._admin_shield_path)



        self.setObjectName("AdminPanelScreen")

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.setMouseTracking(True)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)



        self._build_ui()

        self._setup_effects()

        self._apply_styles()



    # =========================================================================

    # UI

    # =========================================================================



    def _build_ui(self) -> None:

        self._root_layout = QVBoxLayout(self)

        root = self._root_layout

        root.setContentsMargins(16, 12, 16, 12)

        root.setSpacing(8)



        # ---------------------------------------------------------------------

        # Top bar

        # ---------------------------------------------------------------------

        self.top_bar = QWidget(self)

        self._top_layout = QHBoxLayout(self.top_bar)

        top_layout = self._top_layout

        top_layout.setContentsMargins(0, 0, 0, 0)

        top_layout.setSpacing(8)



        self.back_button = self._create_button("Back", variant="secondary", min_width=82, parent=self.top_bar)

        self.back_button.clicked.connect(self._handle_back_clicked)



        self.logo_label = QLabel(self.top_bar)

        self.logo_label.setObjectName("LogoLabel")

        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.logo_label.setFixedSize(38, 38)

        self._set_label_pixmap(self.logo_label, self._logo_pixmap, 34)



        self.top_title = QLabel("Administrator Dashboard", self.top_bar)

        self.top_title.setObjectName("TopTitle")



        self.access_pill = QLabel("Admin Active", self.top_bar)

        self.access_pill.setObjectName("RuntimePill")



        self.mode_pill = QLabel("Mode Unknown", self.top_bar)

        self.mode_pill.setObjectName("RuntimePill")



        self.connection_pill = QLabel("Checking runtime…", self.top_bar)

        self.connection_pill.setObjectName("RuntimePill")



        top_layout.addWidget(self.back_button)

        top_layout.addWidget(self.logo_label)

        top_layout.addWidget(self.top_title)

        top_layout.addStretch(1)

        top_layout.addWidget(self.access_pill)

        top_layout.addWidget(self.mode_pill)

        top_layout.addWidget(self.connection_pill)



        # ---------------------------------------------------------------------

        # Header card

        # ---------------------------------------------------------------------

        self.header_card = QFrame(self)

        self.header_card.setObjectName("AdminHeaderCard")



        self._header_layout = QVBoxLayout(self.header_card)

        header_layout = self._header_layout

        header_layout.setContentsMargins(14, 12, 14, 12)

        header_layout.setSpacing(6)



        if _HAS_GLOW_LABEL:

            self.hero_title = GlowLabel(

                role=getattr(GlowLabel, "ROLE_TITLE", getattr(GlowLabel, "ROLE_STATUS", 0)),

                align_center=True,

                use_outline=False,

                enable_paint_glow=True,

                initial_glow_strength=0.52,

                initial_glow_blur=18,

            )

        else:

            self.hero_title = QLabel(self.header_card)

            self.hero_title.setAlignment(Qt.AlignmentFlag.AlignCenter)



        self.hero_subtitle = QLabel(self.header_card)

        self.hero_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.hero_subtitle.setWordWrap(True)



        self.header_chip_row = QWidget(self.header_card)

        self._chip_layout = QHBoxLayout(self.header_chip_row)

        chip_layout = self._chip_layout

        chip_layout.setContentsMargins(0, 0, 0, 0)

        chip_layout.setSpacing(6)



        self.user_chip = QLabel("Admin User", self.header_chip_row)

        self.user_chip.setObjectName("HeaderChip")



        self.session_chip = QLabel("Protected Session", self.header_chip_row)

        self.session_chip.setObjectName("HeaderChip")



        self.guard_chip = QLabel("System Controls", self.header_chip_row)

        self.guard_chip.setObjectName("HeaderChip")



        chip_layout.addStretch(1)

        chip_layout.addWidget(self.user_chip)

        chip_layout.addWidget(self.session_chip)

        chip_layout.addWidget(self.guard_chip)

        chip_layout.addStretch(1)



        self.summary_banner = QLabel(

            "Use the protected dashboard to manage settings, calibration, parameters, storage, publication, and diagnostic support tools.",

            self.header_card,

        )

        self.summary_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.summary_banner.setWordWrap(True)



        header_layout.addWidget(self.hero_title)

        header_layout.addWidget(self.hero_subtitle)

        header_layout.addWidget(self.header_chip_row)

        header_layout.addWidget(self.summary_banner)



        # ---------------------------------------------------------------------

        # Overview row

        # ---------------------------------------------------------------------

        self.overview_row = QWidget(self)

        self._overview_layout = QHBoxLayout(self.overview_row)

        overview_layout = self._overview_layout

        overview_layout.setContentsMargins(0, 0, 0, 0)

        overview_layout.setSpacing(8)



        self.stat_user = _AdminStatCard("Admin User", value="--", subtitle="No active admin user loaded.")

        self.stat_connection = _AdminStatCard("Hardware Link", value="--", subtitle="Connection state pending.")

        self.stat_storage = _AdminStatCard("Stored Records", value="--", subtitle="Storage statistics pending.")

        self.stat_publish = _AdminStatCard("Publish Queue", value="--", subtitle="Publication statistics pending.")



        overview_layout.addWidget(self.stat_user, 1)

        overview_layout.addWidget(self.stat_connection, 1)

        overview_layout.addWidget(self.stat_storage, 1)

        overview_layout.addWidget(self.stat_publish, 1)



        # ---------------------------------------------------------------------

        # Content row

        # ---------------------------------------------------------------------

        self.content_row = QWidget(self)

        self._content_layout = QHBoxLayout(self.content_row)

        content_layout = self._content_layout

        content_layout.setContentsMargins(0, 0, 0, 0)

        content_layout.setSpacing(10)



        self.action_panel = QFrame(self.content_row)

        self.action_panel.setObjectName("ActionPanel")

        self.action_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)



        self._action_panel_layout = QVBoxLayout(self.action_panel)

        action_panel_layout = self._action_panel_layout

        action_panel_layout.setContentsMargins(12, 10, 12, 10)

        action_panel_layout.setSpacing(8)



        self.action_panel_title = QLabel("Protected Modules", self.action_panel)

        self.action_panel_title.setObjectName("SectionTitle")



        self.action_grid_widget = QWidget(self.action_panel)

        self.action_grid = QGridLayout(self.action_grid_widget)

        self.action_grid.setContentsMargins(0, 0, 0, 0)

        self.action_grid.setHorizontalSpacing(8)

        self.action_grid.setVerticalSpacing(8)



        self.action_cards: Dict[str, _AdminActionCard] = {}



        self._action_specs = [

            (

                "settings",

                "Settings",

                "Display, network, timeout, and runtime behavior controls.",

                "Review brightness, appearance, and device preferences",

                "Update environment-specific kiosk runtime behavior",

                self._settings_icon_path,

                0,

                0,

            ),

            (

                "calibration",

                "Calibration",

                "Sensor offsets, hardware tuning, and calibration review tools.",

                "Inspect calibration readiness and last update state",

                "Open calibration routines for supported sensor modules",

                self._calibrate_icon_path,

                0,

                1,

            ),

            (

                "parameters",

                "Parameters",

                "Threshold profiles and health interpretation parameters.",

                "Review measurement boundaries and reference limits",

                "Maintain rule-oriented parameter configuration",

                self._parameters_icon_path,

                0,

                2,

            ),

            (

                "diagnosis",

                "Diagnosis",

                "Interpretation support and health-rule review utilities.",

                "Review result logic and summary reasoning support",

                "Inspect the diagnostic layer behind kiosk conclusions",

                self._diagnosis_icon_path,

                1,

                0,

            ),

            (

                "storage",

                "Storage",

                "Session storage, backups, exports, and local retention tools.",

                "Inspect database/storage availability and file retention",

                "Review reports, exports, and backup resources",

                self._storage_icon_path,

                1,

                1,

            ),

            (

                "publish",

                "Publish",

                "Sharing, publication, report distribution, and output workflow.",

                "Inspect QR/report readiness and publish state",

                "Open publication and external handoff controls",

                self._publish_icon_path,

                1,

                2,

            ),

        ]



        for (

            action_key,

            title,

            subtitle,

            line_1,

            line_2,

            icon_path,

            row,

            col,

        ) in self._action_specs:

            card = _AdminActionCard(

                action_key,

                title=title,

                subtitle=subtitle,

                info_line_1=line_1,

                info_line_2=line_2,

                icon_path=icon_path,

                parent=self.action_grid_widget,

            )

            card.clicked.connect(self._handle_action_card_clicked)

            self.action_cards[action_key] = card



        self._rebuild_action_grid()



        action_panel_layout.addWidget(self.action_panel_title)

        action_panel_layout.addWidget(self.action_grid_widget, 1)



        self.side_panel = QWidget(self.content_row)

        self._side_layout = QVBoxLayout(self.side_panel)

        side_layout = self._side_layout

        side_layout.setContentsMargins(0, 0, 0, 0)

        side_layout.setSpacing(8)

        self.side_panel.setMinimumWidth(232)

        self.side_panel.setMaximumWidth(252)



        self.admin_context_card = QFrame(self.side_panel)

        self.admin_context_card.setObjectName("InfoCard")



        self._context_layout = QVBoxLayout(self.admin_context_card)

        context_layout = self._context_layout

        context_layout.setContentsMargins(12, 10, 12, 10)

        context_layout.setSpacing(6)



        self.context_art = QLabel(self.admin_context_card)

        self.context_art.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._set_label_pixmap(self.context_art, self._shield_pixmap, 84)



        self.context_title = QLabel("Admin Context", self.admin_context_card)

        self.context_title.setObjectName("SectionTitle")



        self.context_user_line = QLabel("User: pending", self.admin_context_card)

        self.context_auth_line = QLabel("Authenticated: pending", self.admin_context_card)

        self.context_mode_line = QLabel("Mode: pending", self.admin_context_card)

        self.context_connection_line = QLabel("Hardware: pending", self.admin_context_card)

        self.context_note = QLabel(

            "The administrator dashboard reflects the current kiosk runtime state and active service integration status.",

            self.admin_context_card,

        )

        self.context_note.setWordWrap(True)



        context_layout.addWidget(self.context_art, 0, alignment=Qt.AlignmentFlag.AlignHCenter)

        context_layout.addWidget(self.context_title)

        context_layout.addWidget(self.context_user_line)

        context_layout.addWidget(self.context_auth_line)

        context_layout.addWidget(self.context_mode_line)

        context_layout.addWidget(self.context_connection_line)

        context_layout.addWidget(self.context_note)



        self.system_note_card = QFrame(self.side_panel)

        self.system_note_card.setObjectName("InfoCard")



        self._note_layout = QVBoxLayout(self.system_note_card)

        note_layout = self._note_layout

        note_layout.setContentsMargins(12, 10, 12, 10)

        note_layout.setSpacing(6)



        self.note_title = QLabel("Operator Notes", self.system_note_card)

        self.note_title.setObjectName("SectionTitle")



        self.note_line_1 = QLabel("• Settings affect kiosk appearance and runtime behavior.", self.system_note_card)

        self.note_line_2 = QLabel("• Calibration impacts measurement accuracy and sensor interpretation.", self.system_note_card)

        self.note_line_3 = QLabel("• Storage and publish modules help preserve or distribute session data.", self.system_note_card)

        self.note_line_4 = QLabel("• Log out when protected administration is no longer required.", self.system_note_card)



        note_layout.addWidget(self.note_title)

        note_layout.addWidget(self.note_line_1)

        note_layout.addWidget(self.note_line_2)

        note_layout.addWidget(self.note_line_3)

        note_layout.addWidget(self.note_line_4)



        self.quick_actions_card = QFrame(self.side_panel)

        self.quick_actions_card.setObjectName("InfoCard")



        self._qa_layout = QVBoxLayout(self.quick_actions_card)

        qa_layout = self._qa_layout

        qa_layout.setContentsMargins(12, 10, 12, 10)

        qa_layout.setSpacing(6)



        self.quick_title = QLabel("Quick Actions", self.quick_actions_card)

        self.quick_title.setObjectName("SectionTitle")



        self.quick_text = QLabel(

            "Refresh the dashboard snapshot, return to the public kiosk flow, or securely close the admin session.",

            self.quick_actions_card,

        )

        self.quick_text.setWordWrap(True)



        self.refresh_button = self._create_button("Refresh Dashboard", variant="ghost", min_width=128, parent=self.quick_actions_card)

        self.refresh_button.clicked.connect(self.reload_dashboard)



        self.logout_button = self._create_button("Logout Admin", variant="secondary", min_width=128, parent=self.quick_actions_card)

        self.logout_button.clicked.connect(self._handle_logout_clicked)



        qa_layout.addWidget(self.quick_title)

        qa_layout.addWidget(self.quick_text)

        qa_layout.addWidget(self.refresh_button)

        qa_layout.addWidget(self.logout_button)



        side_layout.addWidget(self.admin_context_card)

        side_layout.addWidget(self.system_note_card)

        side_layout.addWidget(self.quick_actions_card)

        side_layout.addStretch(1)



        content_layout.addWidget(self.action_panel, 1)

        content_layout.addWidget(self.side_panel, 0)



        # ---------------------------------------------------------------------

        # Bottom action row

        # ---------------------------------------------------------------------

        self.action_row = QWidget(self)

        self._action_row_layout = QGridLayout(self.action_row)

        action_row_layout = self._action_row_layout

        action_row_layout.setContentsMargins(0, 0, 0, 0)

        action_row_layout.setHorizontalSpacing(8)

        action_row_layout.setVerticalSpacing(8)



        self.bottom_refresh_button = self._create_button("Refresh", variant="ghost", min_width=94, parent=self.action_row)

        self.bottom_refresh_button.clicked.connect(self.reload_dashboard)



        self.bottom_settings_button = self._create_button("Settings", variant="secondary", min_width=104, parent=self.action_row)

        self.bottom_settings_button.clicked.connect(lambda: self._open_action("settings"))



        self.bottom_storage_button = self._create_button("Storage", variant="secondary", min_width=104, parent=self.action_row)

        self.bottom_storage_button.clicked.connect(lambda: self._open_action("storage"))



        self.bottom_logout_button = self._create_button("Logout", variant="primary", min_width=104, parent=self.action_row)

        self.bottom_logout_button.clicked.connect(self._handle_logout_clicked)



        action_row_layout.addWidget(self.bottom_refresh_button, 0, 0)

        action_row_layout.addWidget(self.bottom_settings_button, 0, 1)

        action_row_layout.addWidget(self.bottom_storage_button, 0, 2)

        action_row_layout.addWidget(self.bottom_logout_button, 0, 3)

        for _col in range(4):

            action_row_layout.setColumnStretch(_col, 1)



        root.addWidget(self.top_bar)

        root.addWidget(self.header_card)

        root.addWidget(self.overview_row)

        root.addWidget(self.content_row, 1)

        root.addWidget(self.action_row)



        self._update_responsive_layout(self.width() or KIOSK_WIDTH, self.height() or KIOSK_HEIGHT)



    def _rebuild_action_grid(self) -> None:

        # For the 800x480 kiosk, a stable 3x2 module grid gives the cleanest

        # result and prevents the dashboard from becoming tall and empty.

        columns = 3

        if self._compact and self._ultra_compact and (self.width() and self.width() < 720):

            columns = 2



        while self.action_grid.count():

            item = self.action_grid.takeAt(0)

            widget = item.widget()

            if widget is not None:

                widget.setParent(self.action_grid_widget)



        for index, spec in enumerate(self._action_specs):

            action_key = spec[0]

            card = self.action_cards.get(action_key)

            if card is None:

                continue

            row = index // columns

            col = index % columns

            self.action_grid.addWidget(card, row, col)



        for col in range(columns):

            self.action_grid.setColumnStretch(col, 1)



    def _update_responsive_layout(self, width: int, height: int) -> None:

        width = max(1, int(width or KIOSK_WIDTH))

        height = max(1, int(height or KIOSK_HEIGHT))



        compact = width <= 900 or height <= 540 or IS_COMPACT_KIOSK

        ultra = width <= 820 or height <= 490

        self._compact = compact

        self._ultra_compact = ultra



        root_margin_x = 10 if ultra else 12 if compact else 22

        root_margin_y = 8 if ultra else 10 if compact else 16

        self._root_layout.setContentsMargins(root_margin_x, root_margin_y, root_margin_x, root_margin_y)

        self._root_layout.setSpacing(6 if compact else 12)



        self._top_layout.setSpacing(5 if ultra else 8 if compact else 10)

        self._header_layout.setContentsMargins(

            10 if ultra else 12 if compact else 18,

            8 if ultra else 10 if compact else 16,

            10 if ultra else 12 if compact else 18,

            8 if ultra else 10 if compact else 16,

        )

        self._header_layout.setSpacing(4 if compact else 8)

        self._chip_layout.setSpacing(4 if compact else 8)



        self._overview_layout.setSpacing(6 if compact else 10)

        self._content_layout.setSpacing(0 if compact else 14)

        self._action_panel_layout.setContentsMargins(

            10 if compact else 16,

            8 if compact else 14,

            10 if compact else 16,

            8 if compact else 14,

        )

        self._action_panel_layout.setSpacing(6 if compact else 10)

        self.action_grid.setHorizontalSpacing(10 if ultra else 12 if compact else 16)

        self.action_grid.setVerticalSpacing(10 if ultra else 12 if compact else 14)



        self._side_layout.setSpacing(6 if compact else 12)

        self._context_layout.setContentsMargins(10 if compact else 16, 8 if compact else 14, 10 if compact else 16, 8 if compact else 14)

        self._context_layout.setSpacing(5 if compact else 8)

        self._note_layout.setContentsMargins(10 if compact else 16, 8 if compact else 14, 10 if compact else 16, 8 if compact else 14)

        self._note_layout.setSpacing(5 if compact else 8)

        self._qa_layout.setContentsMargins(10 if compact else 16, 8 if compact else 14, 10 if compact else 16, 8 if compact else 14)

        self._qa_layout.setSpacing(5 if compact else 8)

        self._action_row_layout.setHorizontalSpacing(6 if compact else 10)

        self._action_row_layout.setVerticalSpacing(6 if compact else 10)



        self.side_panel.setMinimumWidth(224 if compact else 292)

        self.side_panel.setMaximumWidth(246 if compact else 320)

        self._set_label_pixmap(self.context_art, self._shield_pixmap, 72 if ultra else 88 if compact else 110)

        self.logo_label.setFixedSize(38, 38)

        self._set_label_pixmap(self.logo_label, self._logo_pixmap, 34)



        self.top_title.setText("Admin Panel" if compact else "Administrator Dashboard")

        self.connection_pill.setVisible(not ultra)

        self.mode_pill.setVisible(width > 680)

        self.access_pill.setVisible(width > 620)

        self.hero_subtitle.setVisible(False if compact else True)

        self.summary_banner.setVisible(False if compact else True)

        self.guard_chip.setVisible(not ultra)

        self.session_chip.setVisible(False if compact else width > 760)



        self.context_note.setVisible(not ultra)

        self.note_line_3.setVisible(not ultra)

        self.note_line_4.setVisible(not ultra)

        self.quick_text.setVisible(not ultra)



        self.refresh_button.setText("Refresh" if compact else "Refresh Dashboard")

        self.logout_button.setText("Logout" if compact else "Logout Admin")

        self.bottom_settings_button.setText("Prefs" if ultra else "Settings")

        self.bottom_storage_button.setText("Files" if ultra else "Storage")



        self.overview_row.setVisible(True)

        self.side_panel.setVisible(False if compact else True)

        self.action_panel_title.setText("Admin Modules" if compact else "Protected Modules")

        self._content_layout.setStretch(0, 1)

        self._content_layout.setStretch(1, 0)



        try:

            self.content_row.setMinimumHeight(220 if ultra else 250 if compact else 280)

            self.action_panel.setMinimumHeight(220 if ultra else 250 if compact else 260)

            self.action_grid_widget.setMinimumHeight(178 if ultra else 196 if compact else 210)

            self.action_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

            self.content_row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        except Exception:

            pass



        self.top_title.setStyleSheet(

            f"""

            QLabel#TopTitle {{

                color: #F6FCFF;

                font-size: {12 if ultra else 13 if compact else 14}px;

                font-weight: 900;

                background: transparent;

            }}

            """

        )

        self.hero_title.setStyleSheet(

            f"""

            QLabel {{

                color: #F6FCFF;

                font-size: {14 if ultra else 16 if compact else 20}px;

                font-weight: 900;

                background: transparent;

            }}

            """

        )



        for button in (

            self.bottom_refresh_button,

            self.bottom_settings_button,

            self.bottom_storage_button,

            self.bottom_logout_button,

        ):

            try:

                button.setMinimumHeight(36 if ultra else 40 if compact else 46)

                button.setMaximumHeight(36 if ultra else 40 if compact else 46)

                button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

            except Exception:

                pass



        for card in (self.stat_user, self.stat_connection, self.stat_storage, self.stat_publish):

            try:

                card.set_compact(True if compact else False, ultra)

                card.setMinimumHeight(56 if ultra else 62 if compact else _h(84, 76, 98))

                card.setMaximumHeight(64 if ultra else 70 if compact else 120)

            except Exception:

                pass



        for card in self.action_cards.values():

            try:

                card.set_compact(compact, ultra)

                card.setMinimumHeight(76 if ultra else 86 if compact else 96)

                card.setMaximumHeight(82 if ultra else 92 if compact else 100)

            except Exception:

                pass



        self._rebuild_action_grid()



    def resizeEvent(self, event) -> None:

        super().resizeEvent(event)

        self._update_responsive_layout(self.width(), self.height())



    def _create_button(self, text: str, *, variant: str, min_width: int, parent: QWidget) -> QWidget:

        if AnimatedButton is not None:

            try:

                variant_map = {

                    "primary": getattr(AnimatedButton, "VARIANT_PRIMARY", None),

                    "secondary": getattr(AnimatedButton, "VARIANT_SECONDARY", None),

                    "ghost": getattr(AnimatedButton, "VARIANT_GHOST", None),

                    "success": getattr(AnimatedButton, "VARIANT_SUCCESS", None),

                }

                btn = AnimatedButton(

                    text=text,

                    variant=variant_map.get(variant),

                    size=getattr(AnimatedButton, "SIZE_SM" if getattr(self, "_compact", IS_COMPACT_KIOSK) else "SIZE_MD", None),

                    minimum_width=min_width,

                )

                return btn

            except Exception:

                pass



        button = QPushButton(text, parent)

        button.setMinimumWidth(min_width)

        button.setMinimumHeight(36 if getattr(self, "_compact", IS_COMPACT_KIOSK) else 40)

        button.setCursor(Qt.CursorShape.PointingHandCursor)

        button.setStyleSheet(

            """

            QPushButton {

                color: #F6FCFF;

                border: 1px solid rgba(157, 220, 255, 0.26);

                border-radius: 14px;

                padding: 10px 16px;

                font-size: 10px;

                font-weight: 700;

                background: rgba(22, 47, 82, 0.78);

            }

            QPushButton:hover {

                background: rgba(34, 66, 110, 0.90);

                border-color: rgba(186, 233, 255, 0.40);

            }

            QPushButton:disabled {

                color: rgba(220, 236, 246, 0.48);

                background: rgba(20, 38, 62, 0.55);

            }

            """

        )

        return button



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

        # Keep this screen fully solid. Opacity/shadow effects caused the

        # center module area to disappear on some hover/repaint cycles.

        self.header_opacity = None

        self.overview_opacity = None

        self.content_opacity = None

        self.entry_group = None



        try:

            self.header_card.setGraphicsEffect(None)

        except Exception:

            pass

        try:

            self.overview_row.setGraphicsEffect(None)

        except Exception:

            pass

        try:

            self.content_row.setGraphicsEffect(None)

        except Exception:

            pass

        try:

            self.action_panel.setGraphicsEffect(None)

        except Exception:

            pass



        if _HAS_GLOW_LABEL and isinstance(self.hero_title, GlowLabel):

            try:

                self.hero_title.set_glow_color("#43D9FF")

                self.hero_title.set_text_color("#F5FCFF")

            except Exception:

                pass





    def _apply_styles(self) -> None:

        self.setStyleSheet(

            """

            QFrame#AdminPanelScreen {

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

                color: #F6FCFF;

                font-size: 14px;

                font-weight: 900;

                background: transparent;

            }



            QLabel#RuntimePill {

                color: #EEF9FF;

                font-size: 9px;

                font-weight: 700;

                border: 1px solid rgba(157, 220, 255, 0.22);

                border-radius: 12px;

                background: rgba(18, 39, 70, 0.56);

                padding: 5px 9px;

            }



            QFrame#AdminHeaderCard {

                border: 1px solid rgba(120, 195, 235, 0.22);

                border-radius: 18px;

                background: rgba(9, 21, 35, 0.94);

            }



            QLabel#HeaderChip {

                color: #EEF9FF;

                font-size: 8px;

                font-weight: 800;

                border: 1px solid rgba(157, 220, 255, 0.22);

                border-radius: 10px;

                background: rgba(28, 56, 91, 0.42);

                padding: 3px 8px;

            }



            QFrame#ActionPanel, QFrame#InfoCard {

                border: 1px solid rgba(120, 195, 235, 0.20);

                border-radius: 18px;

                background: rgba(8, 18, 30, 0.94);

            }



            QLabel#SectionTitle {

                color: #F4FCFF;

                font-size: 10px;

                font-weight: 800;

                background: transparent;

            }

            """

        )



        if _HAS_GLOW_LABEL and isinstance(self.hero_title, GlowLabel):

            try:

                self.hero_title.set_text("Protected administrator dashboard")

            except Exception:

                self.hero_title.setText("Protected administrator dashboard")

        else:

            self.hero_title.setText("Protected administrator dashboard")



        self.hero_subtitle.setText(

            "Review protected system status, runtime context, and module readiness before opening administration tools."

        )

        self.summary_banner.setText(

            "This dashboard centralizes secure access to kiosk configuration, maintenance, interpretation, storage, and publication controls."

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

                font-size: 9px;

                font-weight: 500;

                background: transparent;

            }

            """

        )

        self.summary_banner.setStyleSheet(

            """

            QLabel {

                color: rgba(207, 229, 244, 0.88);

                font-size: 9px;

                font-weight: 600;

                background: transparent;

            }

            """

        )



        info_text_style = """

            QLabel {

                color: rgba(214, 235, 248, 0.86);

                font-size: 9px;

                font-weight: 500;

                background: transparent;

            }

        """

        self.context_user_line.setStyleSheet(info_text_style)

        self.context_auth_line.setStyleSheet(info_text_style)

        self.context_mode_line.setStyleSheet(info_text_style)

        self.context_connection_line.setStyleSheet(info_text_style)

        self.context_note.setStyleSheet(info_text_style)



        self.note_line_1.setStyleSheet(info_text_style)

        self.note_line_2.setStyleSheet(info_text_style)

        self.note_line_3.setStyleSheet(info_text_style)

        self.note_line_4.setStyleSheet(info_text_style)

        self.quick_text.setStyleSheet(info_text_style)



        self._set_button_accent(self.back_button, "#39D8FF")

        self._set_button_accent(self.refresh_button, "#39D8FF")

        self._set_button_accent(self.bottom_refresh_button, "#39D8FF")

        self._set_button_accent(self.bottom_settings_button, "#67D8FF")

        self._set_button_accent(self.bottom_storage_button, "#67D8FF")

        self._set_button_accent(self.logout_button, "#FF6E88")

        self._set_button_accent(self.bottom_logout_button, "#FF6E88")



    def _play_entry_animation(self) -> None:

        # Keep the screen solid and stable.

        try:

            if getattr(self, "entry_group", None) is not None:

                self.entry_group.stop()

        except Exception:

            pass



        self.header_card.setVisible(True)

        self.overview_row.setVisible(True)

        self.content_row.setVisible(True)

        self.action_panel.setVisible(True)

        self.action_grid_widget.setVisible(True)

        for widget in self.action_cards.values():

            try:

                widget.setVisible(True)

            except Exception:

                pass





    # =========================================================================

    # Lifecycle



    # =========================================================================

    # Lifecycle

    # =========================================================================



    def showEvent(self, event) -> None:

        super().showEvent(event)

        self._play_entry_animation()

        self.reload_dashboard()



    # =========================================================================

    # Snapshot loading

    # =========================================================================



    def reload_dashboard(self) -> None:

        self._snapshot = self._build_dashboard_snapshot()

        self._apply_dashboard_snapshot(self._snapshot)

        self.dashboard_loaded.emit(dict(self._snapshot))



    def _build_dashboard_snapshot(self) -> Dict[str, Any]:

        admin_user = self._read_admin_user()

        authenticated = self._read_admin_authenticated()

        mode = self._read_current_mode()

        connection = self._read_connection_snapshot()

        settings = self._read_settings_snapshot()

        calibration = self._read_calibration_snapshot()

        thresholds = self._read_threshold_snapshot()

        storage = self._read_storage_snapshot()

        publish = self._read_publish_snapshot()

        session = self._read_session_snapshot()

        diagnosis = self._read_diagnosis_snapshot()



        return {

            "admin_user": admin_user,

            "authenticated": authenticated,

            "mode": mode,

            "connection": connection,

            "settings": settings,

            "calibration": calibration,

            "thresholds": thresholds,

            "storage": storage,

            "publish": publish,

            "session": session,

            "diagnosis": diagnosis,

        }



    def _read_admin_user(self) -> str:

        user = ""



        try:

            if self.app_state is not None:

                for attr_name in ("current_admin_user", "admin_user", "last_admin_user"):

                    attr = getattr(self.app_state, attr_name, None)

                    if isinstance(attr, str) and attr.strip():

                        user = attr.strip()

                        break

        except Exception:

            pass



        try:

            settings_service = self.services.get("settings_service") or self.services.get("settings")

            if not user and settings_service is not None:

                for method_name in ("get_runtime_value", "get_setting", "value", "get"):

                    method = getattr(settings_service, method_name, None)

                    if callable(method):

                        try:

                            result = method("admin_user")

                            text = safe_str(result, "").strip()

                            if text:

                                user = text

                                break

                        except Exception:

                            continue

        except Exception:

            pass



        return user or "Administrator"



    def _read_admin_authenticated(self) -> bool:

        authenticated = False



        try:

            if self.app_state is not None:

                for attr_name in ("admin_authenticated", "is_admin_authenticated"):

                    attr = getattr(self.app_state, attr_name, None)

                    if isinstance(attr, bool):

                        authenticated = attr

                        break

        except Exception:

            pass



        try:

            settings_service = self.services.get("settings_service") or self.services.get("settings")

            if not authenticated and settings_service is not None:

                for method_name in ("get_runtime_value", "get_setting", "value", "get"):

                    method = getattr(settings_service, method_name, None)

                    if callable(method):

                        try:

                            result = method("admin_authenticated")

                            authenticated = safe_bool(result, False)

                            if authenticated:

                                break

                        except Exception:

                            continue

        except Exception:

            pass



        return authenticated



    def _read_current_mode(self) -> str:

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

                        try:

                            result = method()

                            text = safe_str(result, "").strip().lower()

                            if text:

                                mode = text

                                break

                        except Exception:

                            continue

        except Exception:

            pass



        if mode not in {MODE_DEMO, MODE_HARDWARE}:

            mode = MODE_DEMO

        return mode



    def _read_connection_snapshot(self) -> Dict[str, Any]:

        snapshot: Dict[str, Any] = {

            "connected": False,

            "waiting": False,

            "port": "",

            "baudrate": "",

            "detail": "",

        }



        try:

            connection_service = self.services.get("connection_service") or self.services.get("connection")

            if connection_service is not None:

                for method_name in ("snapshot", "get_snapshot", "connection_snapshot"):

                    method = getattr(connection_service, method_name, None)

                    if callable(method):

                        try:

                            raw = method()

                            if isinstance(raw, Mapping):

                                snapshot.update(dict(raw))

                                break

                        except Exception:

                            continue

        except Exception:

            pass



        try:

            serial_service = self.services.get("serial_service") or self.services.get("serial")

            if serial_service is not None:

                for method_name in ("snapshot", "get_snapshot", "serial_snapshot"):

                    method = getattr(serial_service, method_name, None)

                    if callable(method):

                        try:

                            raw = method()

                            if isinstance(raw, Mapping):

                                snapshot.setdefault("port", raw.get("port", raw.get("selected_port", "")))

                                snapshot.setdefault("baudrate", raw.get("baudrate", ""))

                                snapshot.setdefault("last_line", raw.get("last_line", ""))

                                break

                        except Exception:

                            continue

        except Exception:

            pass



        connected = bool(snapshot.get("connected", False)) or bool(snapshot.get("serial_connected", False)) or bool(snapshot.get("esp32_connected", False))

        waiting = bool(snapshot.get("waiting", False))

        available_ports = snapshot.get("available_ports", [])

        if not waiting and not connected and isinstance(available_ports, list) and len(available_ports) > 0:

            waiting = True



        port = safe_str(snapshot.get("port"), "").strip()

        if not port and isinstance(available_ports, list) and available_ports:

            port = safe_str(available_ports[0], "").strip()



        detail = safe_str(snapshot.get("detail"), "").strip()

        if not detail:

            if connected:

                detail = "Hardware link is active."

            elif waiting:

                detail = "A possible serial device is available."

            else:

                detail = "No confirmed hardware link is active."



        return {

            "connected": connected,

            "waiting": waiting,

            "port": port,

            "baudrate": safe_str(snapshot.get("baudrate"), "").strip(),

            "detail": detail,

        }



    def _read_settings_snapshot(self) -> Dict[str, Any]:

        snapshot: Dict[str, Any] = {

            "theme": "",

            "brightness": "",

            "timeout": "",

            "network": "",

        }



        try:

            settings_service = self.services.get("settings_service") or self.services.get("settings")

            if settings_service is not None:

                for method_name in ("get_settings", "load_settings", "current_settings", "snapshot", "get_snapshot"):

                    method = getattr(settings_service, method_name, None)

                    if callable(method):

                        try:

                            raw = method()

                            if isinstance(raw, Mapping):

                                data = dict(raw)

                                snapshot["theme"] = data.get("appearance", data.get("theme", data.get("ui_theme", "")))

                                snapshot["brightness"] = data.get("brightness", "")

                                snapshot["timeout"] = data.get("timeout", data.get("session_timeout", ""))

                                snapshot["network"] = data.get("network", data.get("network_mode", ""))

                                break

                        except Exception:

                            continue

        except Exception:

            pass



        return snapshot



    def _read_calibration_snapshot(self) -> Dict[str, Any]:

        snapshot: Dict[str, Any] = {

            "state": "pending",

            "count": "",

            "detail": "Calibration state unavailable.",

        }



        try:

            calibration_service = self.services.get("calibration_service") or self.services.get("calibration")

            if calibration_service is not None:

                for method_name in ("snapshot", "get_snapshot", "get_calibration_status", "status"):

                    method = getattr(calibration_service, method_name, None)

                    if callable(method):

                        try:

                            raw = method()

                            if isinstance(raw, Mapping):

                                data = dict(raw)

                                snapshot["state"] = data.get("state", data.get("status", "pending"))

                                snapshot["count"] = data.get("calibrated_count", data.get("sensor_count", ""))

                                snapshot["detail"] = data.get("detail", data.get("summary", snapshot["detail"]))

                                break

                        except Exception:

                            continue

        except Exception:

            pass



        return snapshot



    def _read_threshold_snapshot(self) -> Dict[str, Any]:

        snapshot: Dict[str, Any] = {

            "state": "ready",

            "count": "",

            "detail": "Threshold profile is available.",

        }



        try:

            threshold_service = self.services.get("threshold_service") or self.services.get("thresholds")

            if threshold_service is not None:

                for method_name in ("snapshot", "get_snapshot", "get_threshold_status", "status"):

                    method = getattr(threshold_service, method_name, None)

                    if callable(method):

                        try:

                            raw = method()

                            if isinstance(raw, Mapping):

                                data = dict(raw)

                                snapshot["state"] = data.get("state", data.get("status", "ready"))

                                snapshot["count"] = data.get("count", data.get("rule_count", data.get("profile_count", "")))

                                snapshot["detail"] = data.get("detail", data.get("summary", snapshot["detail"]))

                                break

                        except Exception:

                            continue

        except Exception:

            pass



        return snapshot



    def _read_storage_snapshot(self) -> Dict[str, Any]:

        snapshot: Dict[str, Any] = {

            "state": "ready",

            "record_count": "",

            "backup_count": "",

            "export_count": "",

            "detail": "Storage snapshot unavailable.",

        }



        try:

            storage_service = self.services.get("storage_service") or self.services.get("storage")

            if storage_service is not None:

                for method_name in ("snapshot", "get_snapshot", "get_storage_stats", "stats", "status"):

                    method = getattr(storage_service, method_name, None)

                    if callable(method):

                        try:

                            raw = method()

                            if isinstance(raw, Mapping):

                                data = dict(raw)

                                snapshot["state"] = data.get("state", data.get("status", "ready"))

                                snapshot["record_count"] = data.get("record_count", data.get("records", data.get("row_count", "")))

                                snapshot["backup_count"] = data.get("backup_count", data.get("backups", ""))

                                snapshot["export_count"] = data.get("export_count", data.get("exports", ""))

                                snapshot["detail"] = data.get("detail", data.get("summary", snapshot["detail"]))

                                break

                        except Exception:

                            continue

        except Exception:

            pass



        try:

            if snapshot.get("record_count") in ("", None):

                database_service = self.services.get("database_service") or self.services.get("database")

                if database_service is not None:

                    for method_name in ("stats", "get_stats", "snapshot", "get_snapshot"):

                        method = getattr(database_service, method_name, None)

                        if callable(method):

                            try:

                                raw = method()

                                if isinstance(raw, Mapping):

                                    data = dict(raw)

                                    snapshot["record_count"] = data.get("record_count", data.get("records", snapshot.get("record_count", "")))

                                    if not snapshot.get("detail"):

                                        snapshot["detail"] = data.get("detail", "")

                                    break

                            except Exception:

                                continue

        except Exception:

            pass



        return snapshot



    def _read_publish_snapshot(self) -> Dict[str, Any]:

        snapshot: Dict[str, Any] = {

            "state": "ready",

            "queue_count": "",

            "detail": "Publish snapshot unavailable.",

        }



        try:

            publish_service = self.services.get("publish_service") or self.services.get("publish")

            if publish_service is not None:

                for method_name in ("snapshot", "get_snapshot", "get_publish_stats", "stats", "status"):

                    method = getattr(publish_service, method_name, None)

                    if callable(method):

                        try:

                            raw = method()

                            if isinstance(raw, Mapping):

                                data = dict(raw)

                                snapshot["state"] = data.get("state", data.get("status", "ready"))

                                snapshot["queue_count"] = data.get("queue_count", data.get("pending_count", data.get("count", "")))

                                snapshot["detail"] = data.get("detail", data.get("summary", snapshot["detail"]))

                                break

                        except Exception:

                            continue

        except Exception:

            pass



        return snapshot



    def _read_session_snapshot(self) -> Dict[str, Any]:

        snapshot: Dict[str, Any] = {

            "active_mode": self._read_current_mode(),

            "has_measurements": False,

            "report_path": "",

            "qr_path": "",

        }



        try:

            session_service = self.services.get("session_service") or self.services.get("session")

            if session_service is not None:

                for method_name in ("get_current_session", "get_session_payload", "current_session_payload", "snapshot", "get_snapshot"):

                    method = getattr(session_service, method_name, None)

                    if callable(method):

                        try:

                            raw = method()

                            if isinstance(raw, Mapping):

                                data = dict(raw)

                                measurements = data.get("measurements", {})

                                snapshot["has_measurements"] = isinstance(measurements, Mapping) and bool(measurements)

                                snapshot["report_path"] = data.get("report_path", "")

                                snapshot["qr_path"] = data.get("qr_path", "")

                                break

                        except Exception:

                            continue

        except Exception:

            pass



        return snapshot



    def _read_diagnosis_snapshot(self) -> Dict[str, Any]:

        snapshot: Dict[str, Any] = {

            "state": "ready",

            "detail": "Diagnosis service available.",

        }



        try:

            diagnosis_service = self.services.get("diagnosis_service") or self.services.get("diagnosis")

            if diagnosis_service is not None:

                for method_name in ("snapshot", "get_snapshot", "status"):

                    method = getattr(diagnosis_service, method_name, None)

                    if callable(method):

                        try:

                            raw = method()

                            if isinstance(raw, Mapping):

                                data = dict(raw)

                                snapshot["state"] = data.get("state", data.get("status", "ready"))

                                snapshot["detail"] = data.get("detail", data.get("summary", snapshot["detail"]))

                                break

                        except Exception:

                            continue

        except Exception:

            pass



        return snapshot



    # =========================================================================

    # UI application

    # =========================================================================



    def _apply_dashboard_snapshot(self, snapshot: Mapping[str, Any]) -> None:

        data = dict(snapshot or {})

        admin_user = safe_str(data.get("admin_user"), "Administrator").strip() or "Administrator"

        authenticated = safe_bool(data.get("authenticated"), False)

        mode = safe_str(data.get("mode"), MODE_DEMO).strip().lower() or MODE_DEMO



        connection = dict(data.get("connection", {}))

        settings = dict(data.get("settings", {}))

        calibration = dict(data.get("calibration", {}))

        thresholds = dict(data.get("thresholds", {}))

        storage = dict(data.get("storage", {}))

        publish = dict(data.get("publish", {}))

        session = dict(data.get("session", {}))

        diagnosis = dict(data.get("diagnosis", {}))



        # top pills

        self.user_chip.setText(f"User: {admin_user}")

        self.session_chip.setText("Protected Session Active" if authenticated else "Auth State Unverified")

        self.guard_chip.setText("Protected Modules Ready")



        self._apply_header_chip_style(self.user_chip, "#67D8FF")

        self._apply_header_chip_style(self.session_chip, "#42E393" if authenticated else "#FFD25E")

        self._apply_header_chip_style(self.guard_chip, "#39D8FF")



        self.access_pill.setText("Admin Active" if authenticated else "Admin Unverified")

        self._apply_pill_style(self.access_pill, "#42E393" if authenticated else "#FFD25E")



        if mode == MODE_HARDWARE:

            self.mode_pill.setText("Hardware Mode")

            self._apply_pill_style(self.mode_pill, "#39D8FF")

        else:

            self.mode_pill.setText("Demo Mode")

            self._apply_pill_style(self.mode_pill, "#67D8FF")



        connected = safe_bool(connection.get("connected"), False)

        waiting = safe_bool(connection.get("waiting"), False)

        if connected:

            connection_text = "Hardware Connected"

            connection_state = "connected"

        elif waiting:

            connection_text = "Waiting for Device"

            connection_state = "waiting"

        else:

            connection_text = "No Hardware Link"

            connection_state = "offline"



        self.connection_pill.setText(connection_text)

        self._apply_pill_style(self.connection_pill, _accent_for_state(connection_state))



        # header text

        self.hero_subtitle.setText(

            "Protected tools are available for kiosk configuration, calibration, interpretation, storage, and publication workflows."

        )

        self.summary_banner.setText(

            f"Administrator {admin_user} is viewing the secure dashboard. "

            f"{safe_str(connection.get('detail'), '').strip() or 'Hardware status is being monitored.'}"

        )



        # stat cards

        self.stat_user.set_payload(

            value=admin_user,

            subtitle="Authenticated administrator session." if authenticated else "Authentication state could not be fully verified.",

            accent_hex="#42E393" if authenticated else "#FFD25E",

        )



        port_text = safe_str(connection.get("port"), "").strip()

        baudrate_text = safe_str(connection.get("baudrate"), "").strip()

        connection_subtitle = safe_str(connection.get("detail"), "").strip()

        if port_text:

            connection_subtitle = f"{connection_subtitle} Port: {port_text}{f' @ {baudrate_text}' if baudrate_text else ''}"



        self.stat_connection.set_payload(

            value="Connected" if connected else ("Waiting" if waiting else "Offline"),

            subtitle=connection_subtitle or "Connection state unavailable.",

            accent_hex=_accent_for_state(connection_state),

        )



        record_count = safe_str(storage.get("record_count"), "").strip() or "--"

        storage_subtitle_parts = []

        if safe_str(storage.get("backup_count"), "").strip():

            storage_subtitle_parts.append(f"Backups: {safe_str(storage.get('backup_count'), '')}")

        if safe_str(storage.get("export_count"), "").strip():

            storage_subtitle_parts.append(f"Exports: {safe_str(storage.get('export_count'), '')}")

        storage_detail = safe_str(storage.get("detail"), "").strip()

        storage_subtitle = " • ".join(storage_subtitle_parts) if storage_subtitle_parts else storage_detail

        if not storage_subtitle:

            storage_subtitle = "Storage statistics unavailable."



        self.stat_storage.set_payload(

            value=record_count,

            subtitle=storage_subtitle,

            accent_hex="#27C1D3" if safe_str(storage.get("state"), "ready").strip().lower() == "ready" else _accent_for_state(safe_str(storage.get("state"), "ready")),

        )



        queue_count = safe_str(publish.get("queue_count"), "").strip() or "--"

        publish_detail = safe_str(publish.get("detail"), "").strip() or "Publication statistics unavailable."

        self.stat_publish.set_payload(

            value=queue_count,

            subtitle=publish_detail,

            accent_hex="#7E8CFF" if safe_str(publish.get("state"), "ready").strip().lower() == "ready" else _accent_for_state(safe_str(publish.get("state"), "ready")),

        )



        # context panel

        self.context_user_line.setText(f"User: {admin_user}")

        self.context_auth_line.setText(f"Authenticated: {'Yes' if authenticated else 'No / Unknown'}")

        self.context_mode_line.setText(f"Current Mode: {'Hardware' if mode == MODE_HARDWARE else 'Demo'}")

        self.context_connection_line.setText(

            f"Hardware: {'Connected' if connected else ('Waiting' if waiting else 'Offline')}"

        )

        self.context_note.setText(

            "This dashboard is linked to the live protected session context and reflects currently available service snapshots."

        )



        # action cards

        settings_subtitle = (

            f"Theme: {safe_str(settings.get('theme'), 'Unknown')} • "

            f"Brightness: {safe_str(settings.get('brightness'), 'Unknown')} • "

            f"Timeout: {safe_str(settings.get('timeout'), 'Unknown')}"

        )

        self.action_cards["settings"].set_payload(

            state_text="Review",

            accent_hex="#67D8FF",

            subtitle=settings_subtitle,

            info_line_1=f"Network: {safe_str(settings.get('network'), 'Unknown') or 'Unknown'}",

            info_line_2="Open protected settings and display/network preferences",

        )



        self.action_cards["calibration"].set_payload(

            state_text=safe_str(calibration.get("state"), "Pending").title(),

            accent_hex=_accent_for_state(safe_str(calibration.get("state"), "pending")),

            subtitle=safe_str(calibration.get("detail"), "Calibration state unavailable."),

            info_line_1=f"Calibrated sensors: {safe_str(calibration.get('count'), '--') or '--'}",

            info_line_2="Review offsets and supported sensor calibration routines",

        )



        self.action_cards["parameters"].set_payload(

            state_text=safe_str(thresholds.get("state"), "Ready").title(),

            accent_hex=_accent_for_state(safe_str(thresholds.get("state"), "ready")),

            subtitle=safe_str(thresholds.get("detail"), "Threshold configuration available."),

            info_line_1=f"Profiles / rules: {safe_str(thresholds.get('count'), '--') or '--'}",

            info_line_2="Adjust measurement limits and interpretation parameters",

        )



        self.action_cards["diagnosis"].set_payload(

            state_text=safe_str(diagnosis.get("state"), "Ready").title(),

            accent_hex=_accent_for_state(safe_str(diagnosis.get("state"), "ready")),

            subtitle=safe_str(diagnosis.get("detail"), "Diagnosis module ready."),

            info_line_1="Review result interpretation and logic support",

            info_line_2="Inspect triage/summary flow behind the kiosk output",

        )



        storage_state = safe_str(storage.get("state"), "ready")

        self.action_cards["storage"].set_payload(

            state_text=storage_state.title(),

            accent_hex="#27C1D3" if storage_state.strip().lower() == "ready" else _accent_for_state(storage_state),

            subtitle=safe_str(storage.get("detail"), "Storage status available."),

            info_line_1=f"Stored records: {record_count}",

            info_line_2=f"Backups: {safe_str(storage.get('backup_count'), '--') or '--'} • Exports: {safe_str(storage.get('export_count'), '--') or '--'}",

        )



        publish_state = safe_str(publish.get("state"), "ready")

        report_path = safe_str(session.get("report_path"), "").strip()

        qr_path = safe_str(session.get("qr_path"), "").strip()

        session_has_measurements = safe_bool(session.get("has_measurements"), False)

        publish_subtitle = safe_str(publish.get("detail"), "Publish workflow available.")

        self.action_cards["publish"].set_payload(

            state_text=publish_state.title(),

            accent_hex="#7E8CFF" if publish_state.strip().lower() == "ready" else _accent_for_state(publish_state),

            subtitle=publish_subtitle,

            info_line_1=f"Active session payload: {'Available' if session_has_measurements else 'No completed session'}",

            info_line_2=f"QR: {'Ready' if qr_path else 'Pending'} • PDF: {'Ready' if report_path else 'Pending'}",

        )



        # side quick text

        self.quick_text.setText(

            "Refresh protected status, open a module directly, or securely close the administrator session when finished."

        )



        # button accents

        self._set_button_accent(self.back_button, "#39D8FF")

        self._set_button_accent(self.refresh_button, "#39D8FF")

        self._set_button_accent(self.bottom_refresh_button, "#39D8FF")

        self._set_button_accent(self.bottom_settings_button, "#67D8FF")

        self._set_button_accent(self.bottom_storage_button, "#67D8FF")

        self._set_button_accent(self.logout_button, "#FF6E88")

        self._set_button_accent(self.bottom_logout_button, "#FF6E88")



    # =========================================================================

    # Action routing

    # =========================================================================



    def _handle_action_card_clicked(self, action_key: str) -> None:

        self._open_action(action_key)



    def _open_action(self, action_key: str) -> None:

        action = safe_str(action_key, "").strip().lower()

        if not action:

            return



        self.action_requested.emit(action)



        screen_map = {

            "settings": SCREEN_SETTINGS,

            "calibration": SCREEN_CALIBRATION,

            "parameters": SCREEN_PARAMETERS,

            "diagnosis": SCREEN_DIAGNOSIS,

            "storage": SCREEN_STORAGE,

            "publish": SCREEN_PUBLISH,

        }



        signal_map = {

            "settings": self.settings_requested,

            "calibration": self.calibration_requested,

            "parameters": self.parameters_requested,

            "diagnosis": self.diagnosis_requested,

            "storage": self.storage_requested,

            "publish": self.publish_requested,

        }



        target = screen_map.get(action, "")

        if target and self._navigate_to(target):

            signal = signal_map.get(action)

            if signal is not None:

                signal.emit()

            return



        signal = signal_map.get(action)

        if signal is not None:

            signal.emit()



    # =========================================================================

    # Logout / session clearing

    # =========================================================================



    def _clear_admin_session(self) -> None:

        try:

            if self.app_state is not None:

                for attr_name, value in (

                    ("admin_authenticated", False),

                    ("is_admin_authenticated", False),

                    ("admin_user", ""),

                    ("current_admin_user", ""),

                ):

                    if hasattr(self.app_state, attr_name):

                        try:

                            setattr(self.app_state, attr_name, value)

                        except Exception:

                            pass



                for method_name in ("set_admin_authenticated", "set_admin_user", "clear_admin_session", "admin_logout"):

                    method = getattr(self.app_state, method_name, None)

                    if callable(method):

                        try:

                            if method_name == "set_admin_authenticated":

                                method(False)

                            elif method_name == "set_admin_user":

                                method("")

                            else:

                                method()

                        except Exception:

                            continue

        except Exception:

            pass



        try:

            settings_service = self.services.get("settings_service") or self.services.get("settings")

            if settings_service is not None:

                for method_name in ("set_runtime_value", "set_setting", "update_runtime_flag"):

                    method = getattr(settings_service, method_name, None)

                    if callable(method):

                        try:

                            method("admin_authenticated", False)

                        except Exception:

                            continue

        except Exception:

            pass



    # =========================================================================

    # Navigation / actions

    # =========================================================================



    def _handle_back_clicked(self) -> None:

        if self._navigate_to("results"):

            return

        self.back_requested.emit()



    def _handle_logout_clicked(self) -> None:

        self._clear_admin_session()

        # Navigate directly and stop. Emitting logout_requested after a successful

        # navigation caused some app shells to route back to the wrong public

        # screen, so only emit the signal when no navigator route succeeds.

        if self._navigate_to(SCREEN_MODE_SELECT):

            return

        if self._navigate_to(SCREEN_ADMIN_LOGIN):

            return

        if self._navigate_to(SCREEN_WELCOME):

            return

        self.logout_requested.emit()



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

    # Styling helpers

    # =========================================================================



    def _apply_pill_style(self, label: QLabel, accent_hex: str) -> None:

        accent = QColor(accent_hex)

        label.setStyleSheet(

            f"""

            QLabel {{

                color: #EEF9FF;

                font-size: 9px;

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

                border-radius: 10px;

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

            button.setStyleSheet(

                f"""

                QPushButton {{

                    color: #F6FCFF;

                    border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.34);

                    border-radius: 14px;

                    padding: 10px 16px;

                    font-size: 11px;

                    font-weight: 700;

                    background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.16);

                }}

                QPushButton:hover {{

                    background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.24);

                    border-color: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.48);

                }}

                QPushButton:disabled {{

                    color: rgba(220, 236, 246, 0.48);

                    background: rgba(20, 38, 62, 0.55);

                }}

                """

            )



    # =========================================================================

    # Paint

    # =========================================================================



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



            painter.fillRect(rect, QColor(4, 14, 28, 176))

            painter.fillRect(QRectF(0.0, 0.0, float(rect.width()), rect.height() * 0.38), QColor(53, 214, 255, 16))

            painter.fillRect(QRectF(0.0, rect.height() * 0.60, float(rect.width()), rect.height() * 0.40), QColor(20, 82, 128, 18))

        finally:

            painter.end()



    # =========================================================================

    # Diagnostics

    # =========================================================================



    def diagnostics(self) -> Dict[str, Any]:

        return {

            "snapshot_keys": list(self._snapshot.keys()),

            "background_path": self._background_path,

            "logo_path": self._logo_small_path,

            "admin_shield_path": self._admin_shield_path,

            "available_action_cards": list(self.action_cards.keys()),

        }
