"""
screens/measuring_screen.py

Premium live-measurement screen for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the core runtime screen after mode selection
- It handles both:
    - Demo Mode simulated measurement flow
    - Hardware Mode live sensor / serial-assisted measurement flow
- It is designed specifically for:
    - Raspberry Pi 4B touchscreen kiosk deployment
    - 1024x600 resolution
    - laptop demo mode
- It provides:
    - guided measurement workflow
    - staged progress animation
    - live metric tiles
    - connection/runtime summary
    - resilient service integration with low coupling
    - navigation handoff to results screen

Linked project files this screen is intended to work with:
- core/constants.py
- core/asset_paths.py
- core/logger.py
- core/app_state.py
- core/navigator.py
- core/theme_manager.py
- core/animation_manager.py
- services/mode_service.py
- services/session_service.py
- services/sensor_service.py
- services/connection_service.py
- services/serial_service.py
- services/diagnosis_service.py
- widgets/animated_button.py
- widgets/glow_label.py
- widgets/animated_progress_bar.py
- widgets/metric_tile.py
- widgets/connection_badge.py

Design goals:
- glossy futuristic blue medical UI
- highly readable live-measurement workflow
- resilient while backend/services are still being integrated
- clear demo vs hardware behavior
- maintainable and modular code
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from PyQt6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QRectF,
    QTimer,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
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
    from core.constants import (
        MODE_DEMO,
        MODE_HARDWARE,
        SCREEN_MODE_SELECT,
        SCREEN_RESULTS,
        METRIC_BMI,
        METRIC_HEIGHT,
        METRIC_PULSE,
        METRIC_RR,
        METRIC_SPO2,
        METRIC_TEMPERATURE,
        METRIC_WEIGHT,
    )
except Exception:  # pragma: no cover
    MODE_DEMO = "demo"
    MODE_HARDWARE = "hardware"
    SCREEN_MODE_SELECT = "mode_select"
    SCREEN_RESULTS = "results"
    METRIC_TEMPERATURE = "temperature"
    METRIC_SPO2 = "spo2"
    METRIC_PULSE = "pulse_rate"
    METRIC_RR = "respiratory_rate"
    METRIC_WEIGHT = "weight"
    METRIC_HEIGHT = "height"
    METRIC_BMI = "bmi"

try:
    from config import KIOSK_WIDTH, KIOSK_HEIGHT, UI_SCALE
except Exception:  # pragma: no cover
    KIOSK_WIDTH = 800
    KIOSK_HEIGHT = 480
    UI_SCALE = min(KIOSK_WIDTH / 1024.0, KIOSK_HEIGHT / 600.0)

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

try:
    from widgets.animated_progress_bar import AnimatedProgressBar
    _HAS_ANIMATED_PROGRESS = True
except Exception:  # pragma: no cover
    AnimatedProgressBar = QWidget  # type: ignore
    _HAS_ANIMATED_PROGRESS = False

try:
    from widgets.metric_tile import MetricTile
    _HAS_METRIC_TILE = True
except Exception:  # pragma: no cover
    MetricTile = QWidget  # type: ignore
    _HAS_METRIC_TILE = False

try:
    from widgets.connection_badge import ConnectionBadge
    _HAS_CONNECTION_BADGE = True
except Exception:  # pragma: no cover
    ConnectionBadge = QWidget  # type: ignore
    _HAS_CONNECTION_BADGE = False


logger = get_logger(__name__)


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_asset(relative_path: str) -> str:
    relative_clean = safe_str(relative_path, "").strip().replace("\\", "/").lstrip("/")
    if not relative_clean:
        return ""

    try:
        import core.asset_paths as asset_paths

        candidate_names = [
            "get_asset_path",
            "asset_path",
            "resolve_asset_path",
            "resolve_asset",
            "asset",
        ]
        for name in candidate_names:
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


def _format_number(value: Any, decimals: int = 1, fallback: str = "--") -> str:
    if value in (None, ""):
        return fallback
    if isinstance(value, str):
        text = value.strip()
        return text or fallback
    numeric = safe_float(value, 0.0)
    if abs(numeric - round(numeric)) < 1e-9:
        return str(int(round(numeric)))
    return f"{numeric:.{decimals}f}"


def _compute_bmi(weight_kg: Optional[float], height_value: Optional[float]) -> Optional[float]:
    if weight_kg in (None, "") or height_value in (None, ""):
        return None

    weight = safe_float(weight_kg, 0.0)
    raw_height = safe_float(height_value, 0.0)

    if weight <= 0 or raw_height <= 0:
        return None

    height_m = raw_height / 100.0 if raw_height > 3.5 else raw_height
    if height_m <= 0:
        return None

    bmi = weight / (height_m * height_m)
    if bmi <= 0:
        return None
    return round(bmi, 1)


@dataclass
class _PhaseDefinition:
    title: str
    subtitle: str
    min_progress: int


PHASES: List[_PhaseDefinition] = [
    _PhaseDefinition("Prepare", "Prepare the user and initialize the parameter measurement workflow.", 0),
    _PhaseDefinition("Acquire", "Collect live or simulated health readings.", 18),
    _PhaseDefinition("Stabilize", "Validate measurements and verify consistency.", 56),
    _PhaseDefinition("Finalize", "Package the completed session for the results screen.", 84),
]


class _FallbackProgressBar(QFrame):
    STATE_PRIMARY = "primary"
    STATE_SUCCESS = "success"
    STATE_WARNING = "warning"
    STATE_DANGER = "danger"

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._value = 0
        self._status_text = "Starting…"
        self._state = self.STATE_PRIMARY

        self.setObjectName("FallbackProgressShell")
        self.setMinimumHeight(34)
        self.setMaximumHeight(34)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def _accent(self) -> QColor:
        if self._state == self.STATE_SUCCESS:
            return QColor("#42E393")
        if self._state == self.STATE_WARNING:
            return QColor("#FFD25E")
        if self._state == self.STATE_DANGER:
            return QColor("#FF6E88")
        return QColor("#39D8FF")

    def setValue(self, value: int) -> None:
        self._value = max(0, min(100, safe_int(value, 0)))
        self.update()

    def set_value(self, value: int, animated: bool = False) -> None:
        _ = animated
        self.setValue(value)

    def set_status_text(self, text: str) -> None:
        self._status_text = safe_str(text, "").strip()
        self.update()

    def set_state(self, state: Any) -> None:
        self._state = safe_str(state, self.STATE_PRIMARY).strip().lower() or self.STATE_PRIMARY
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
            if r.width() <= 4 or r.height() <= 4:
                return

            radius = min(r.height() / 2.0, 16.0)
            accent = self._accent()

            # outer track
            track_grad = QLinearGradient(r.topLeft(), r.bottomLeft())
            track_grad.setColorAt(0.0, QColor(14, 34, 58, 245))
            track_grad.setColorAt(1.0, QColor(9, 23, 42, 250))
            painter.setPen(QPen(QColor(118, 223, 255, 130), 1.2))
            painter.setBrush(track_grad)
            painter.drawRoundedRect(r, radius, radius)

            inner = r.adjusted(2.5, 4, -2.5, -4)
            inner_radius = max(8.0, radius - 4.0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(3, 10, 20, 210))
            painter.drawRoundedRect(inner, inner_radius, inner_radius)

            fill_w = max(inner.height(), inner.width() * (self._value / 100.0)) if self._value > 0 else 0
            fill = QRectF(inner.left(), inner.top(), min(fill_w, inner.width()), inner.height())
            if fill.width() > 0:
                fill_grad = QLinearGradient(fill.topLeft(), fill.topRight())
                c1 = QColor(73, 224, 160) if self._state == self.STATE_SUCCESS else accent
                c2 = QColor(142, 239, 214) if self._state == self.STATE_SUCCESS else QColor(108, 219, 255)
                fill_grad.setColorAt(0.0, c1)
                fill_grad.setColorAt(1.0, c2)
                painter.setBrush(fill_grad)
                painter.drawRoundedRect(fill, inner_radius, inner_radius)


            # text
            painter.setPen(QColor('#F5FCFF'))
            font = painter.font()
            font.setPointSize(8)
            font.setWeight(QFont.Weight.Bold)
            painter.setFont(font)

            percent_rect = QRectF(inner.right()-72, inner.top(), 64, inner.height())
            painter.drawText(percent_rect, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), f"{self._value}%")

            status_rect = QRectF(inner.left()+12, inner.top(), max(40.0, inner.width()-92), inner.height())
            status_text = self._status_text or ''
            if len(status_text) > 46:
                status_text = status_text[:43].rstrip() + '…'
            painter.drawText(status_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), status_text)
        finally:
            painter.end()

class _FallbackMetricCard(QFrame):
    def __init__(self, title: str, unit: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._accent_hex = "#39D8FF"
        self._empty = True

        self.setObjectName("FallbackMetricCard")
        self.setMinimumHeight(92)
        self.setMaximumHeight(92)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(4)

        self.title_label = QLabel(title, self)
        self.value_row = QWidget(self)
        value_layout = QHBoxLayout(self.value_row)
        value_layout.setContentsMargins(0, 0, 0, 0)
        value_layout.setSpacing(4)

        self.value_label = QLabel("--", self.value_row)
        self.unit_label = QLabel(unit, self.value_row)

        value_layout.addWidget(self.value_label, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        value_layout.addWidget(self.unit_label, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        value_layout.addStretch(1)

        self.status_label = QLabel("Waiting", self)
        self.status_label.setWordWrap(True)

        root.addWidget(self.title_label)
        root.addWidget(self.value_row)
        root.addWidget(self.status_label)
        root.addStretch(1)

        self._apply_style()

    def _apply_style(self) -> None:
        accent = QColor(self._accent_hex)
        self.setStyleSheet(
            f"""
            QFrame#FallbackMetricCard {{
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, {0.32 if not self._empty else 0.18});
                border-radius: 18px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, {0.12 if not self._empty else 0.06});
            }}
            """
        )
        self.title_label.setStyleSheet("color: rgba(221, 239, 250, 0.82); font-size: 9px; font-weight: 700; background: transparent;")
        self.value_label.setStyleSheet("color: #F8FDFF; font-size: 19px; font-weight: 900; background: transparent;")
        self.unit_label.setStyleSheet("color: rgba(202, 224, 241, 0.84); font-size: 10px; font-weight: 700; background: transparent; padding-bottom: 3px;")
        self.status_label.setStyleSheet("color: rgba(190, 214, 232, 0.82); font-size: 9px; font-weight: 500; background: transparent;")

    def set_value(self, value: Any, unit: Optional[str] = None) -> None:
        if value in (None, ""):
            self.value_label.setText("--")
            self._empty = True
        else:
            self.value_label.setText(_format_number(value, 1))
            self._empty = False
        if unit is not None:
            self.unit_label.setText(safe_str(unit, "").strip())
        self._apply_style()

    def set_status(self, text: str) -> None:
        self.status_label.setText(safe_str(text, "").strip())

    def set_accent(self, accent_hex: str) -> None:
        self._accent_hex = safe_str(accent_hex, "#39D8FF").strip() or "#39D8FF"
        self._apply_style()


class _FallbackConnectionBadge(QFrame):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._accent = "#39D8FF"

        self.setObjectName("FallbackConnectionBadge")
        self.setMinimumHeight(128)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(4)

        self.headline = QLabel("Connection Status", self)
        self.detail = QLabel("Waiting for connection data.", self)
        self.detail.setWordWrap(True)

        self.meta_mode = QLabel("Mode: --", self)
        self.meta_port = QLabel("Port: --", self)
        self.meta_state = QLabel("State: --", self)

        root.addWidget(self.headline)
        root.addWidget(self.detail)
        root.addWidget(self.meta_mode)
        root.addWidget(self.meta_port)
        root.addWidget(self.meta_state)
        root.addStretch(1)

        self._apply_style()

    def _apply_style(self) -> None:
        accent = QColor(self._accent)
        self.setStyleSheet(
            f"""
            QFrame#FallbackConnectionBadge {{
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.24);
                border-radius: 18px;
                background: rgba(11, 27, 49, 0.78);
            }}
            """
        )
        self.headline.setStyleSheet("color: #F6FCFF; font-size: 11px; font-weight: 800; background: transparent;")
        for lbl in (self.detail, self.meta_mode, self.meta_port, self.meta_state):
            lbl.setStyleSheet("color: rgba(214, 235, 248, 0.86); font-size: 10px; font-weight: 500; background: transparent;")

    def set_accent(self, accent_hex: str) -> None:
        self._accent = safe_str(accent_hex, "#39D8FF").strip() or "#39D8FF"
        self._apply_style()

    def set_headline(self, text: str) -> None:
        self.headline.setText(safe_str(text, "").strip())

    def set_detail(self, text: str) -> None:
        self.detail.setText(safe_str(text, "").strip())

    def set_mode(self, text: str) -> None:
        self.meta_mode.setText(f"Mode: {safe_str(text, '--').strip()}")

    def set_port(self, text: str) -> None:
        self.meta_port.setText(f"Port: {safe_str(text, '--').strip()}")

    def set_state(self, text: str) -> None:
        self.meta_state.setText(f"State: {safe_str(text, '--').strip()}")


class MeasuringScreen(QFrame):
    back_requested = pyqtSignal()
    refresh_requested = pyqtSignal()
    measurement_started = pyqtSignal(str)
    measurement_progress = pyqtSignal(int, str)
    measurement_completed = pyqtSignal(dict)
    results_requested = pyqtSignal(dict)
    measurement_reset = pyqtSignal()

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

        try:
            self._logger = logger.bind(component="MeasuringScreen")
        except Exception:
            self._logger = logger

        self.navigator = navigator
        self.app_state = app_state
        self.services = dict(services or {})
        self.animation_manager = animation_manager
        self.theme_manager = theme_manager

        self._mode = self._read_current_mode()
        self._runtime_snapshot: Dict[str, Any] = {}
        self._latest_measurements: Dict[str, Any] = {}
        self._history_buffer: List[Dict[str, Any]] = []

        self._measurement_started = False
        self._measurement_complete = False
        self._progress_value = 0
        self._phase_title = "Prepare"
        self._phase_subtitle = "Prepare the user and initialize the parameter measurement workflow."
        self._status_text = "Preparing measurement screen…"
        self._last_persisted_payload: Dict[str, Any] = {}

        self._demo_step_index = 0
        self._hardware_stable_counter = 0
        self._hardware_ready_counter = 0

        self._background_path = _resolve_asset("backgrounds/measuring_bg.png")
        self._assistant_path = _resolve_asset("illustrations/measuring_assistant.png")
        self._logo_small_path = _resolve_asset("logos/bathroom-scale-measuring-weight-weight-control-and-healthy-lifestyle-vector-removebg-preview.png")

        self._background_pixmap = _pixmap_or_empty(self._background_path)
        self._assistant_pixmap = _pixmap_or_empty(self._assistant_path)
        self._logo_pixmap = _pixmap_or_empty(self._logo_small_path)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(520)
        self._poll_timer.timeout.connect(self._poll_runtime)

        self._demo_timer = QTimer(self)
        self._demo_timer.setInterval(420)
        self._demo_timer.timeout.connect(self._advance_demo_measurement)

        self._compact_runtime_layout = True
        self._ultra_compact_runtime_layout = (KIOSK_WIDTH <= 860 or KIOSK_HEIGHT <= 520)

        self.setObjectName("MeasuringScreen")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._build_ui()
        self._setup_effects()
        self._apply_styles()
        self._update_responsive_layout()

        self._set_progress(0, "Measurement station is ready to begin.", emit_signal=False)
        self._set_buttons_for_state()
        self._refresh_runtime_status()
        self._apply_mode_ui()

    # -------------------------------------------------------------------------
    # UI construction
    # -------------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        self._root_layout = root
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(0)

        # ---------------------------------------------------------------------
        # Top bar
        # ---------------------------------------------------------------------
        self.top_bar = QWidget(self)
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        top_layout.setSpacing(10)

        self.back_button = self._create_button("Back", variant="secondary", min_width=96, parent=self.top_bar)
        self.back_button.setMinimumHeight(40)
        self.back_button.setMaximumHeight(40)
        self.back_button.clicked.connect(self._handle_back_clicked)

        self.logo_label = QLabel(self.top_bar)
        self.logo_label.setObjectName("LogoLabel")
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_label.setFixedSize(42, 42)
        self._set_label_pixmap(self.logo_label, self._logo_pixmap, 42)

        self.top_title = QLabel("Measuring", self.top_bar)
        self.top_title.setObjectName("TopTitle")

        self.top_bar.setFixedHeight(52)

        self.mode_pill = QLabel("Mode Unknown", self.top_bar)
        self.mode_pill.setObjectName("RuntimePill")

        self.connection_pill = QLabel("Simulated Sensors", self.top_bar)
        self.connection_pill.setObjectName("RuntimePill")

        top_layout.addWidget(self.back_button)
        top_layout.addWidget(self.logo_label)
        top_layout.addWidget(self.top_title)
        top_layout.addStretch(1)
        top_layout.addWidget(self.mode_pill)
        top_layout.addWidget(self.connection_pill)

        # ---------------------------------------------------------------------
        # Hero header card
        # ---------------------------------------------------------------------
        self.header_card = QFrame(self)
        self.header_card.setObjectName("HeaderCard")
        self.header_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.header_card.setMinimumHeight(378)
        self.header_card.setMaximumHeight(410)

        header_layout = QVBoxLayout(self.header_card)
        header_layout.setContentsMargins(18, 8, 18, 2)
        header_layout.setSpacing(2)

        self.hero_title = QLabel(self.header_card)
        self.hero_title.setObjectName("HeroTitle")
        self.hero_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hero_title.setMinimumHeight(32)
        self.hero_title.setMaximumHeight(36)

        self.hero_subtitle = QLabel(self.header_card)
        self.hero_subtitle.setObjectName("HeroSubtitle")
        self.hero_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hero_subtitle.setWordWrap(True)
        self.hero_subtitle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.hero_subtitle.setMinimumHeight(18)
        self.hero_subtitle.setMaximumHeight(28)

        self.phase_chip_row = QWidget(self.header_card)
        phase_chip_layout = QHBoxLayout(self.phase_chip_row)
        phase_chip_layout.setContentsMargins(0, 0, 0, 0)
        phase_chip_layout.setSpacing(8)

        self.phase_chip = QLabel("Prepare", self.phase_chip_row)
        self.phase_chip.setObjectName("HeaderChip")

        self.metric_count_chip = QLabel("0 / 7 Metrics", self.phase_chip_row)
        self.metric_count_chip.setObjectName("HeaderChip")

        self.stability_chip = QLabel("Stability Pending", self.phase_chip_row)
        self.stability_chip.setObjectName("HeaderChip")

        phase_chip_layout.addStretch(1)
        phase_chip_layout.addWidget(self.phase_chip)
        phase_chip_layout.addWidget(self.metric_count_chip)
        phase_chip_layout.addWidget(self.stability_chip)
        phase_chip_layout.addStretch(1)

        self.header_art_wrap = QWidget(self.header_card)
        self.header_art_wrap.setObjectName("HeaderArtWrap")
        self.header_art_wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.header_art_wrap.setMinimumHeight(230)
        self.header_art_wrap.setMaximumHeight(258)

        header_art_layout = QVBoxLayout(self.header_art_wrap)
        header_art_layout.setContentsMargins(0, 0, 0, 0)
        header_art_layout.setSpacing(0)

        self.header_assistant_art = QLabel(self.header_art_wrap)
        self.header_assistant_art.setObjectName("HeaderAssistantArt")
        self.header_assistant_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.header_assistant_art.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._set_label_pixmap(self.header_assistant_art, self._assistant_pixmap, 270)

        header_art_layout.addWidget(self.header_assistant_art, 1, alignment=Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)

        header_layout.addWidget(self.hero_title)
        header_layout.addWidget(self.hero_subtitle)
        header_layout.addWidget(self.phase_chip_row)
        header_layout.addSpacing(2)
        header_layout.addWidget(self.header_art_wrap, 1)
        header_layout.addSpacing(0)

        # ---------------------------------------------------------------------
        # Main content row
        # ---------------------------------------------------------------------
        self.content_row = QWidget(self)
        self.content_row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.content_row.setMinimumHeight(0)

        content_layout = QHBoxLayout(self.content_row)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)

        self.measurement_panel = QFrame(self.content_row)
        self.measurement_panel.setObjectName("MeasurementPanel")
        self.measurement_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        measurement_layout = QVBoxLayout(self.measurement_panel)
        measurement_layout.setContentsMargins(12, 10, 12, 10)
        measurement_layout.setSpacing(8)

        self.grid_title = QLabel("Live Measurements", self.measurement_panel)
        self.grid_title.setObjectName("SectionTitle")

        self.grid_subtitle = QLabel(
            "Captured values will appear here as the kiosk acquires, validates, and finalizes the session.",
            self.measurement_panel,
        )
        self.grid_subtitle.setObjectName("GridSubtitle")
        self.grid_subtitle.setWordWrap(True)

        self.metric_grid_widget = QWidget(self.measurement_panel)
        self.metric_grid = QGridLayout(self.metric_grid_widget)
        self.metric_grid.setContentsMargins(0, 0, 0, 0)
        self.metric_grid.setHorizontalSpacing(8)
        self.metric_grid.setVerticalSpacing(8)

        self.metric_widgets: Dict[str, QWidget] = {}
        self.metric_units: Dict[str, str] = {
            METRIC_TEMPERATURE: "°C",
            METRIC_SPO2: "%",
            METRIC_PULSE: "bpm",
            METRIC_RR: "breaths/min",
            METRIC_WEIGHT: "kg",
            METRIC_HEIGHT: "cm",
            METRIC_BMI: "kg/m²",
        }

        metric_specs: List[Tuple[str, str]] = [
            (METRIC_TEMPERATURE, "Temperature"),
            (METRIC_SPO2, "SpO₂"),
            (METRIC_PULSE, "Pulse"),
            (METRIC_RR, "Respiratory Rate"),
            (METRIC_WEIGHT, "Weight"),
            (METRIC_HEIGHT, "Height"),
            (METRIC_BMI, "BMI"),
        ]

        positions = [
            (0, 0),
            (0, 1),
            (0, 2),
            (0, 3),
            (1, 0),
            (1, 1),
            (1, 2),
        ]

        for (metric_key, title), (row, col) in zip(metric_specs, positions):
            tile = self._create_metric_card(title, self.metric_units.get(metric_key, ""))
            self.metric_widgets[metric_key] = tile
            self.metric_grid.addWidget(tile, row, col)

        measurement_layout.addWidget(self.grid_title)
        measurement_layout.addWidget(self.grid_subtitle)
        measurement_layout.addWidget(self.metric_grid_widget, 1)

        self.guidance_panel = QFrame(self.content_row)
        self.guidance_panel.setObjectName("GuidancePanel")
        self.guidance_panel.setMinimumWidth(220)
        self.guidance_panel.setMaximumWidth(248)
        self.guidance_panel.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        guidance_layout = QVBoxLayout(self.guidance_panel)
        guidance_layout.setContentsMargins(12, 10, 12, 10)
        guidance_layout.setSpacing(8)

        self.side_title = QLabel("Measurement Guidance", self.guidance_panel)
        self.side_title.setObjectName("SectionTitle")

        self.side_detail = QLabel(
            "Guide the user to stay still, follow the prompts, and wait while the system stabilizes readings.",
            self.guidance_panel,
        )
        self.side_detail.setObjectName("SideDetail")
        self.side_detail.setWordWrap(True)

        self.connection_widget = self._create_connection_widget(self.guidance_panel)

        self.live_hint_card = QFrame(self.guidance_panel)
        self.live_hint_card.setObjectName("LiveHintCard")

        hint_layout = QVBoxLayout(self.live_hint_card)
        hint_layout.setContentsMargins(10, 8, 10, 8)
        hint_layout.setSpacing(4)

        self.live_hint_title = QLabel("Operator Note", self.live_hint_card)
        self.live_hint_title.setObjectName("HintTitle")

        self.live_hint_body = QLabel(
            "In hardware mode, keep the user steady and place the finger correctly on the sensor until readings become stable.",
            self.live_hint_card,
        )
        self.live_hint_body.setWordWrap(True)

        hint_layout.addWidget(self.live_hint_title)
        hint_layout.addWidget(self.live_hint_body)

        guidance_layout.addWidget(self.side_title)
        guidance_layout.addWidget(self.side_detail)
        guidance_layout.addWidget(self.connection_widget)
        guidance_layout.addWidget(self.live_hint_card)
        guidance_layout.addStretch(1)

        content_layout.addWidget(self.measurement_panel, 1)
        content_layout.addWidget(self.guidance_panel, 0)

        # ---------------------------------------------------------------------
        # Embedded progress module (inside header card)
        # ---------------------------------------------------------------------
        self.progress_card = QFrame(self.header_card)
        self.progress_card.setObjectName("ProgressCard")
        self.progress_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.progress_card.setMinimumHeight(98)
        self.progress_card.setMaximumHeight(110)

        progress_card_layout = QVBoxLayout(self.progress_card)
        progress_card_layout.setContentsMargins(10, 0, 10, 2)
        progress_card_layout.setSpacing(3)

        self.progress_caption = QLabel("Session Progress", self.progress_card)
        self.progress_caption.setObjectName("ProgressCaption")
        self.progress_caption.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.progress_visual_shell = QFrame(self.progress_card)
        self.progress_visual_shell.setObjectName("ProgressVisualShell")
        self.progress_visual_shell.setMinimumHeight(52)
        self.progress_visual_shell.setMaximumHeight(52)
        self.progress_visual_shell.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.progress_shell_layout = QVBoxLayout(self.progress_visual_shell)
        self.progress_shell_layout.setContentsMargins(7, 7, 7, 7)
        self.progress_shell_layout.setSpacing(0)

        self.progress_widget = self._create_progress_widget(self.progress_visual_shell)
        self.progress_widget.setMinimumHeight(34)
        self.progress_widget.setMaximumHeight(34)
        self.progress_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.progress_widget.show()

        self.progress_shell_layout.addWidget(self.progress_widget)

        self.instruction_label = QLabel(self.progress_card)
        self.instruction_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.instruction_label.setWordWrap(True)

        progress_card_layout.addWidget(self.progress_caption)
        progress_card_layout.addWidget(self.progress_visual_shell)
        progress_card_layout.addWidget(self.instruction_label)

        header_layout.addSpacing(0)
        header_layout.addWidget(self.progress_card)

        # ---------------------------------------------------------------------
        # Action row
        # ---------------------------------------------------------------------
        self.action_row = QWidget(self)
        action_layout = QHBoxLayout(self.action_row)
        action_layout.setContentsMargins(0, 4, 0, 0)
        action_layout.setSpacing(8)

        self.refresh_button = self._create_button("Refresh", variant="ghost", min_width=102, parent=self.action_row)
        self.refresh_button.clicked.connect(self._handle_refresh_clicked)

        self.restart_button = self._create_button("Restart", variant="secondary", min_width=118, parent=self.action_row)
        self.restart_button.clicked.connect(self.reset_measurement)

        self.results_button = self._create_button("Results", variant="primary", min_width=110, parent=self.action_row)
        self.results_button.clicked.connect(self._handle_results_clicked)

        action_layout.addWidget(self.refresh_button)
        action_layout.addStretch(1)
        action_layout.addWidget(self.restart_button)
        action_layout.addWidget(self.results_button)

        root.addWidget(self.top_bar, 0)
        root.addWidget(self.header_card, 0)
        root.addWidget(self.content_row, 1)
        root.addWidget(self.action_row, 0)

    # -------------------------------------------------------------------------
    # Widget creation helpers
    # -------------------------------------------------------------------------

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
                    parent=parent,
                    variant=variant_map.get(variant),
                    size=getattr(AnimatedButton, "SIZE_MD", None),
                    minimum_width=min_width,
                )
                try:
                    if text.strip().lower() == "back" and hasattr(btn, "set_accent_color"):
                        btn.set_accent_color("#2F8FFF")
                except Exception:
                    pass
                return btn
            except Exception:
                pass

        button = QPushButton(text, parent)
        button.setMinimumWidth(min_width)
        button.setMinimumHeight(36)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            """
            QPushButton {
                color: #F6FCFF;
                border: 1px solid rgba(157, 220, 255, 0.26);
                border-radius: 14px;
                padding: 10px 16px;
                font-size: 11px;
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

    def _create_progress_widget(self, parent: QWidget) -> QWidget:
        widget = _FallbackProgressBar(parent)
        widget.show()
        return widget

    def _create_metric_card(self, title: str, unit: str) -> QWidget:
        if _HAS_METRIC_TILE:
            try:
                tile = MetricTile(
                    title=title,
                    unit=unit,
                    value="--",
                    subtitle="Waiting for reading",
                    compact=True,
                    clickable=False,
                    show_source_tag=False,
                    show_reference_text=False,
                    show_trend=False,
                    show_status_chip=True,
                    minimum_height=92,
                )
                return tile
            except Exception:
                pass
        return _FallbackMetricCard(title, unit)

    def _create_connection_widget(self, parent: QWidget) -> QWidget:
        if _HAS_CONNECTION_BADGE:
            try:
                widget = ConnectionBadge(
                    parent=parent,
                    title="Connection Status",
                    subtitle="Serial / ESP32 / runtime readiness",
                    detail="Waiting for connection data.",
                    compact=True,
                    clickable=False,
                    show_action_button=False,
                    show_meta_row=True,
                    minimum_height=126,
                )
                return widget
            except Exception:
                pass
        return _FallbackConnectionBadge(parent)

    def _set_label_pixmap(self, label: QLabel, pixmap: QPixmap, target_height: int) -> None:
        if pixmap.isNull():
            label.clear()
            return
        scaled = pixmap.scaledToHeight(target_height, Qt.TransformationMode.SmoothTransformation)
        label.setPixmap(scaled)

    # -------------------------------------------------------------------------
    # Effects and styling
    # -------------------------------------------------------------------------

    def _setup_effects(self) -> None:
        # Intentionally kept stable and simple.
        self.entry_group: Optional[QParallelAnimationGroup] = None
        self.header_fade: Optional[QPropertyAnimation] = None
        self.content_fade: Optional[QPropertyAnimation] = None
        self.progress_fade: Optional[QPropertyAnimation] = None

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QFrame#MeasuringScreen {
                background: transparent;
            }

            QLabel#LogoBadge {
                min-width: 42px;
                max-width: 42px;
                min-height: 42px;
                max-height: 42px;
                border-radius: 14px;
                border: 1px solid rgba(157, 220, 255, 0.18);
                background: rgba(18, 39, 70, 0.58);
            }

            QLabel#TopTitle {
                color: #F6FCFF;
                font-size: 15px;
                font-weight: 900;
                background: transparent;
            }

            QLabel#RuntimePill {
                color: #EEF9FF;
                font-size: 10px;
                font-weight: 800;
                border: 1px solid rgba(155, 224, 255, 0.46);
                border-radius: 18px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(38, 120, 182, 0.88),
                    stop:1 rgba(22, 74, 122, 0.90)
                );
                padding: 9px 18px;
                min-height: 22px;
            }

            QFrame#HeaderCard {
                border: 1px solid rgba(170, 230, 255, 0.24);
                border-radius: 26px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(12, 30, 56, 0.94),
                    stop:1 rgba(8, 22, 44, 0.96)
                );
            }

            QFrame#ProgressCard {
                border: 0px;
                background: transparent;
            }

            QFrame#ProgressVisualShell {
                border: 1px solid rgba(120, 226, 255, 0.34);
                border-radius: 26px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(6, 18, 37, 0.98),
                    stop:1 rgba(3, 11, 25, 1.0)
                );
            }

            QLabel#HeroTitle {
                color: #F7FDFF;
                font-size: 17px;
                font-weight: 900;
                background: transparent;
            }

            QLabel#HeaderChip {
                color: #EEF9FF;
                font-size: 9px;
                font-weight: 800;
                border: 1px solid rgba(157, 220, 255, 0.26);
                border-radius: 12px;
                background: rgba(28, 56, 91, 0.48);
                padding: 4px 9px;
            }

            QLabel#HeroSubtitle {
                color: rgba(229, 244, 252, 0.98);
                font-size: 13px;
                font-weight: 600;
                background: transparent;
                padding-left: 16px;
                padding-right: 16px;
                padding-top: 2px;
                padding-bottom: 2px;
            }

            QLabel#ProgressCaption {
                color: #F8FDFF;
                font-size: 12px;
                font-weight: 800;
                background: transparent;
                padding-bottom: 2px;
            }

            QWidget#HeaderArtWrap, QLabel#HeaderAssistantArt {
                background: transparent;
            }

            QFrame#MeasurementPanel, QFrame#GuidancePanel, QFrame#LiveHintCard {
                border: 1px solid rgba(170, 230, 255, 0.24);
                border-radius: 24px;
                background: rgba(12, 28, 50, 0.74);
            }

            QLabel#SectionTitle {
                color: #F4FCFF;
                font-size: 12px;
                font-weight: 800;
                background: transparent;
            }

            QLabel#GridSubtitle {
                color: rgba(215, 236, 248, 0.82);
                font-size: 10px;
                font-weight: 500;
                background: transparent;
            }

            QLabel#SideDetail {
                color: rgba(214, 235, 248, 0.86);
                font-size: 10px;
                font-weight: 500;
                background: transparent;
            }

            QLabel#HintTitle {
                color: #F6FCFF;
                font-size: 10px;
                font-weight: 800;
                background: transparent;
            }
            """
        )

        self.hero_title.setText("Measuring the parameters")

        self.instruction_label.setStyleSheet(
            """
            QLabel {
                color: rgba(207, 229, 244, 0.94);
                font-size: 9px;
                font-weight: 600;
                background: transparent;
                padding-top: 2px;
            }
            """
        )

        self.live_hint_body.setStyleSheet(
            """
            QLabel {
                color: rgba(214, 235, 248, 0.86);
                font-size: 10px;
                font-weight: 500;
                background: transparent;
            }
            """
        )

        self.hero_subtitle.setText(
            "Please remain still while the kiosk measures your health parameters."
        )
        self.instruction_label.setText(
            "Tap Results to continue when the session finishes."
        )

        self._play_entry_animation()

    def _play_entry_animation(self) -> None:
        return

    # -------------------------------------------------------------------------
    # Responsive layout
    # -------------------------------------------------------------------------

    def _update_responsive_layout(self) -> None:
        width = max(1, self.width())
        height = max(1, self.height())

        ultra_compact = width <= 860 or height <= 520
        compact = ultra_compact or width <= 980 or height <= 620
        self._compact_runtime_layout = compact
        self._ultra_compact_runtime_layout = ultra_compact

        if ultra_compact:
            self._root_layout.setContentsMargins(12, 8, 12, 8)
            self.top_bar.layout().setSpacing(6)
            self.action_row.layout().setSpacing(6)
            self.content_row.setMinimumHeight(0)
            self.content_row.setMaximumHeight(0)
            self.content_row.hide()

            self.header_card.setMinimumHeight(386)
            self.header_card.setMaximumHeight(420)
            self.hero_title.setMinimumHeight(28)
            self.hero_title.setMaximumHeight(32)
            self.hero_subtitle.setMinimumHeight(16)
            self.hero_subtitle.setMaximumHeight(20)
            self.hero_subtitle.show()
            self.phase_chip_row.show()
            self.header_art_wrap.setMinimumHeight(226)
            self.header_art_wrap.setMaximumHeight(258)
            self._set_label_pixmap(self.header_assistant_art, self._assistant_pixmap, 264)

            self.progress_card.setMinimumHeight(94)
            self.progress_card.setMaximumHeight(104)
            self.progress_visual_shell.setMinimumHeight(48)
            self.progress_visual_shell.setMaximumHeight(48)
            self.progress_widget.setMinimumHeight(30)
            self.progress_widget.setMaximumHeight(30)
            self.progress_shell_layout.setContentsMargins(7, 7, 7, 7)

            self.metric_count_chip.setText(f"{self._count_available_metrics(self._latest_measurements)} / 7")
            self.stability_chip.setText("Pending" if not self._measurement_complete else "Stable")
            self.connection_pill.show()
            self.logo_label.show()
            self.refresh_button.setText("Refresh")
            self.back_button.setMinimumWidth(96)
            self.refresh_button.setMinimumWidth(102)
            self.restart_button.setMinimumWidth(114)
            self.results_button.setMinimumWidth(110)
        elif compact:
            self._root_layout.setContentsMargins(12, 8, 12, 8)
            self.top_bar.layout().setSpacing(8)
            self.action_row.layout().setSpacing(8)
            self.content_row.setMinimumHeight(0)
            self.content_row.setMaximumHeight(0)
            self.content_row.hide()

            self.header_card.setMinimumHeight(392)
            self.header_card.setMaximumHeight(426)
            self.hero_title.setMinimumHeight(28)
            self.hero_title.setMaximumHeight(32)
            self.hero_subtitle.setMinimumHeight(18)
            self.hero_subtitle.setMaximumHeight(24)
            self.hero_subtitle.show()
            self.header_art_wrap.setMinimumHeight(226)
            self.header_art_wrap.setMaximumHeight(258)
            self._set_label_pixmap(self.header_assistant_art, self._assistant_pixmap, 264)

            self.progress_card.setMinimumHeight(94)
            self.progress_card.setMaximumHeight(104)
            self.progress_visual_shell.setMinimumHeight(48)
            self.progress_visual_shell.setMaximumHeight(48)
            self.progress_widget.setMinimumHeight(30)
            self.progress_widget.setMaximumHeight(30)
            self.progress_shell_layout.setContentsMargins(7, 7, 7, 7)
            self.connection_pill.show()
            self.logo_label.show()
            self.refresh_button.setText("Refresh")
            self.back_button.setMinimumWidth(96)
            self.refresh_button.setMinimumWidth(102)
            self.restart_button.setMinimumWidth(114)
            self.results_button.setMinimumWidth(110)
        else:
            self._root_layout.setContentsMargins(16, 10, 16, 10)
            self.top_bar.layout().setSpacing(10)
            self.action_row.layout().setSpacing(10)
            self.content_row.setMinimumHeight(0)
            self.content_row.setMaximumHeight(16777215)
            self.content_row.show()

            self.header_card.setMinimumHeight(404)
            self.header_card.setMaximumHeight(438)
            self.hero_title.setMinimumHeight(32)
            self.hero_title.setMaximumHeight(36)
            self.hero_subtitle.setMinimumHeight(18)
            self.hero_subtitle.setMaximumHeight(28)
            self.hero_subtitle.show()
            self.header_art_wrap.setMinimumHeight(238)
            self.header_art_wrap.setMaximumHeight(268)
            self._set_label_pixmap(self.header_assistant_art, self._assistant_pixmap, 276)

            self.progress_card.setMinimumHeight(94)
            self.progress_card.setMaximumHeight(104)
            self.progress_visual_shell.setMinimumHeight(48)
            self.progress_visual_shell.setMaximumHeight(48)
            self.progress_widget.setMinimumHeight(30)
            self.progress_widget.setMaximumHeight(30)

            self.guidance_panel.setMinimumWidth(220)
            self.guidance_panel.setMaximumWidth(248)
            self.connection_pill.show()
            self.logo_label.show()
            self.refresh_button.setText("Refresh")
            self.back_button.setMinimumWidth(84)
            self.refresh_button.setMinimumWidth(116)
            self.restart_button.setMinimumWidth(126)
            self.results_button.setMinimumWidth(118)

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._update_responsive_layout()
        self._refresh_runtime_status()
        self._poll_timer.start()
        if not self._measurement_started:
            QTimer.singleShot(120, self.start_measurement)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._poll_timer.stop()
        self._demo_timer.stop()

    def on_route_enter(self, route_name: str) -> None:
        _ = route_name
        self._update_responsive_layout()
        self._refresh_runtime_status()
        if not self._measurement_started:
            QTimer.singleShot(100, self.start_measurement)

    def on_route_leave(self, route_name: str) -> None:
        _ = route_name
        self._demo_timer.stop()

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def current_mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        mode_text = safe_str(mode, MODE_DEMO).strip().lower() or MODE_DEMO
        if mode_text not in {MODE_DEMO, MODE_HARDWARE}:
            mode_text = MODE_DEMO
        self._mode = mode_text
        self._apply_mode_ui()

    def start_measurement(self) -> None:
        if self._measurement_started and not self._measurement_complete:
            return

        self._measurement_started = True
        self._measurement_complete = False
        self._progress_value = 0
        self._demo_step_index = 0
        self._hardware_ready_counter = 0
        self._hardware_stable_counter = 0
        self._history_buffer.clear()
        self._latest_measurements.clear()

        for metric_key in self.metric_widgets:
            self._set_metric(metric_key, None, "Waiting for reading", "#39D8FF")

        self._set_progress(4, "Initializing measurement workflow…", emit_signal=True)
        self._set_buttons_for_state()
        self._apply_phase_from_progress()
        self.measurement_started.emit(self._mode)

        if self._mode == MODE_DEMO:
            self._demo_timer.start()
        else:
            self._demo_timer.stop()
            self._poll_hardware_measurement(force=True)

    def stop_measurement(self) -> None:
        self._demo_timer.stop()
        self._measurement_started = False

    def reset_measurement(self) -> None:
        self._demo_timer.stop()
        self._measurement_started = False
        self._measurement_complete = False
        self._progress_value = 0
        self._latest_measurements.clear()
        self._history_buffer.clear()
        self._hardware_ready_counter = 0
        self._hardware_stable_counter = 0
        self._last_persisted_payload.clear()

        for metric_key in self.metric_widgets:
            self._set_metric(metric_key, None, "Waiting for reading", accent_hex="#39D8FF")

        self._set_progress(0, "Measurement station is ready to begin.", emit_signal=False)
        self._apply_phase_from_progress()
        self._set_buttons_for_state()
        self._refresh_runtime_status()
        self.measurement_reset.emit()

        QTimer.singleShot(120, self.start_measurement)

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "mode": self._mode,
            "measurement_started": self._measurement_started,
            "measurement_complete": self._measurement_complete,
            "progress_value": self._progress_value,
            "phase_title": self._phase_title,
            "status_text": self._status_text,
            "latest_measurements": dict(self._latest_measurements),
            "runtime_snapshot": dict(self._runtime_snapshot),
            "persisted_payload_keys": list(self._last_persisted_payload.keys()),
            "compact_runtime_layout": self._compact_runtime_layout,
            "content_row_visible": self.content_row.isVisible(),
            "progress_widget_visible": self.progress_widget.isVisible(),
        }

    # -------------------------------------------------------------------------
    # Runtime / mode integration
    # -------------------------------------------------------------------------

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
                        result = method()
                        text = safe_str(result, "").strip().lower()
                        if text:
                            mode = text
                            break
        except Exception:
            pass

        if mode not in {MODE_DEMO, MODE_HARDWARE}:
            mode = MODE_DEMO
        return mode

    def _runtime_snapshot_from_services(self) -> Dict[str, Any]:
        snapshot: Dict[str, Any] = {
            "mode": self._mode,
            "connected": False,
            "waiting": False,
            "port": "",
            "detail": "",
            "baudrate": "",
            "sensor_status": "unknown",
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

        try:
            serial_service = self.services.get("serial_service") or self.services.get("serial")
            if serial_service is not None:
                for method_name in ("snapshot", "get_snapshot", "serial_snapshot"):
                    method = getattr(serial_service, method_name, None)
                    if callable(method):
                        raw = method()
                        if isinstance(raw, Mapping):
                            if not snapshot.get("port"):
                                snapshot["port"] = raw.get("port", raw.get("selected_port", ""))
                            if not snapshot.get("baudrate"):
                                snapshot["baudrate"] = raw.get("baudrate", "")
                            if "last_line" not in snapshot:
                                snapshot["last_line"] = raw.get("last_line", "")
                            break
        except Exception:
            pass

        connected = bool(snapshot.get("connected", False))
        serial_connected = bool(snapshot.get("serial_connected", False))
        esp32_connected = bool(snapshot.get("esp32_connected", False))
        connected = connected or serial_connected or esp32_connected

        available_ports = snapshot.get("available_ports", [])
        waiting = bool(snapshot.get("waiting", False))
        if not waiting and not connected and isinstance(available_ports, list) and len(available_ports) > 0:
            waiting = True

        detail = safe_str(snapshot.get("detail"), "").strip()
        if not detail:
            if self._mode == MODE_DEMO:
                detail = "Demo mode is generating simulated health measurements."
            else:
                if connected:
                    detail = "Hardware connection is active. Live sensor values are being collected."
                elif waiting:
                    detail = "Possible serial device detected. Waiting for stable live readings."
                else:
                    detail = "No confirmed hardware connection is active. The screen will continue waiting for live data."

        snapshot["connected"] = connected
        snapshot["waiting"] = waiting
        snapshot["detail"] = detail
        return snapshot

    def _refresh_runtime_status(self) -> None:
        self._runtime_snapshot = self._runtime_snapshot_from_services()
        self._mode = safe_str(self._runtime_snapshot.get("mode"), self._mode).strip().lower() or self._mode
        self._apply_mode_ui()

    def _apply_mode_ui(self) -> None:
        connected = bool(self._runtime_snapshot.get("connected", False))
        waiting = bool(self._runtime_snapshot.get("waiting", False))
        port = safe_str(self._runtime_snapshot.get("port"), "").strip()
        baudrate = safe_str(self._runtime_snapshot.get("baudrate"), "").strip()
        detail = safe_str(self._runtime_snapshot.get("detail"), "").strip()

        if self._mode == MODE_DEMO:
            self.mode_pill.setText("Demo Mode")
            self._apply_pill_style(self.mode_pill, "#67D8FF")
            self.connection_pill.setText("Simulated Sensors")
            self._apply_pill_style(self.connection_pill, "#67D8FF")
            self.live_hint_body.setText(
                "Demo mode simulates a realistic kiosk measurement sequence so the UI, workflow, and transitions can be demonstrated without hardware."
            )
        else:
            self.mode_pill.setText("Hardware Mode")
            self._apply_pill_style(self.mode_pill, "#39D8FF")

            if connected:
                self.connection_pill.setText("Hardware Connected")
                self._apply_pill_style(self.connection_pill, "#42E393")
            elif waiting:
                self.connection_pill.setText("Waiting for Device")
                self._apply_pill_style(self.connection_pill, "#FFD25E")
            else:
                self.connection_pill.setText("No Device Link")
                self._apply_pill_style(self.connection_pill, "#FF6E88")

            self.live_hint_body.setText(
                "In hardware mode, guide the user to remain still. Keep the finger correctly placed and wait for stable readings before moving to results."
            )

        if self._ultra_compact_runtime_layout:
            self.top_title.setText("Measuring")
            if self._mode == MODE_DEMO:
                self.mode_pill.setText("Demo")
            else:
                self.mode_pill.setText("Hardware")
        else:
            self.top_title.setText("Live Measurement")

        self.side_detail.setText(detail)

        self._apply_connection_widget(
            mode_text=self._mode.title(),
            connected=connected,
            waiting=waiting,
            port_text=(port or "Unknown") + (f" @ {baudrate}" if baudrate else ""),
            detail_text=detail,
        )

    def _apply_pill_style(self, label: QLabel, accent_hex: str) -> None:
        accent = QColor(accent_hex)
        label.setStyleSheet(
            f"""
            QLabel {{
                color: #F5FCFF;
                font-size: 10px;
                font-weight: 800;
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.52);
                border-radius: 17px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.42),
                    stop:1 rgba(18, 48, 82, 0.74)
                );
                padding: 8px 16px;
                min-height: 18px;
            }}
            """
        )

    def _apply_connection_widget(
        self,
        *,
        mode_text: str,
        connected: bool,
        waiting: bool,
        port_text: str,
        detail_text: str,
    ) -> None:
        if _HAS_CONNECTION_BADGE and isinstance(self.connection_widget, ConnectionBadge):
            try:
                if self._mode == MODE_DEMO:
                    self.connection_widget.set_demo_mode(detail_text)
                elif connected:
                    self.connection_widget.set_online(
                        label="Hardware Connected",
                        detail=detail_text,
                        port=port_text,
                        network_connected=True,
                    )
                elif waiting:
                    self.connection_widget.set_waiting(
                        label="Waiting for Device",
                        detail=detail_text,
                        port_hint=port_text or "Port detected",
                    )
                else:
                    self.connection_widget.set_offline(
                        label="No Hardware Link",
                        detail=detail_text,
                    )
                return
            except Exception:
                pass

        if isinstance(self.connection_widget, _FallbackConnectionBadge):
            accent = "#67D8FF" if self._mode == MODE_DEMO else ("#42E393" if connected else "#FFD25E" if waiting else "#FF6E88")
            self.connection_widget.set_accent(accent)
            self.connection_widget.set_headline(
                "Demo Mode Active" if self._mode == MODE_DEMO else "Hardware Connected" if connected else "Waiting for Device" if waiting else "No Hardware Link"
            )
            self.connection_widget.set_detail(detail_text)
            self.connection_widget.set_mode(mode_text)
            self.connection_widget.set_port(port_text or "Unknown")
            self.connection_widget.set_state(
                "Simulated" if self._mode == MODE_DEMO else "Connected" if connected else "Waiting" if waiting else "Offline"
            )

    # -------------------------------------------------------------------------
    # Polling / measurement flow
    # -------------------------------------------------------------------------

    def _poll_runtime(self) -> None:
        self._refresh_runtime_status()
        if not self._measurement_started or self._measurement_complete:
            return
        if self._mode == MODE_HARDWARE:
            self._poll_hardware_measurement(force=False)

    def _advance_demo_measurement(self) -> None:
        demo_script: List[Dict[str, Any]] = [
            {"progress": 10, "status": "Preparing the simulated measurement session…", "measurements": {}},
            {"progress": 22, "status": "Acquiring temperature and oxygen saturation…", "measurements": {METRIC_TEMPERATURE: 36.8, METRIC_SPO2: 97}},
            {"progress": 38, "status": "Capturing pulse and respiratory rate…", "measurements": {METRIC_TEMPERATURE: 36.8, METRIC_SPO2: 98, METRIC_PULSE: 82, METRIC_RR: 16}},
            {"progress": 58, "status": "Capturing weight and height…", "measurements": {METRIC_TEMPERATURE: 36.9, METRIC_SPO2: 98, METRIC_PULSE: 81, METRIC_RR: 16, METRIC_WEIGHT: 68.4, METRIC_HEIGHT: 171.0}},
            {"progress": 78, "status": "Calculating BMI and validating the session…", "measurements": {METRIC_TEMPERATURE: 36.9, METRIC_SPO2: 98, METRIC_PULSE: 80, METRIC_RR: 15, METRIC_WEIGHT: 68.4, METRIC_HEIGHT: 171.0, METRIC_BMI: 23.4}},
            {"progress": 100, "status": "Demo measurement complete.", "measurements": {METRIC_TEMPERATURE: 36.9, METRIC_SPO2: 98, METRIC_PULSE: 80, METRIC_RR: 15, METRIC_WEIGHT: 68.4, METRIC_HEIGHT: 171.0, METRIC_BMI: 23.4}, "complete": True},
        ]

        if self._demo_step_index >= len(demo_script):
            self._demo_timer.stop()
            return

        step = demo_script[self._demo_step_index]
        self._demo_step_index += 1

        measurements = dict(step.get("measurements", {}))
        self._apply_measurements(measurements)

        progress = safe_int(step.get("progress"), self._progress_value)
        status = safe_str(step.get("status"), "Processing simulated measurements…")
        self._set_progress(progress, status, emit_signal=True)

        if safe_bool(step.get("complete"), False):
            self._demo_timer.stop()
            self._complete_measurement(reason="demo_complete")

    def _poll_hardware_measurement(self, *, force: bool) -> None:
        snapshot = self._read_sensor_snapshot()

        measurements = dict(snapshot.get("measurements", {}))
        detail = safe_str(snapshot.get("detail"), "").strip()
        stable = safe_bool(snapshot.get("stable"), False)
        connected = safe_bool(snapshot.get("connected"), self._runtime_snapshot.get("connected", False))

        if measurements:
            self._apply_measurements(measurements)
            self._history_buffer.append(dict(measurements))
            self._history_buffer = self._history_buffer[-6:]

            available_count = self._count_available_metrics(measurements)
            self.metric_count_chip.setText(f"{available_count} / 7 Metrics")

            if available_count >= 4:
                self._hardware_ready_counter += 1
            else:
                self._hardware_ready_counter = 0

            if stable or self._is_measurement_stable():
                self._hardware_stable_counter += 1
            else:
                self._hardware_stable_counter = 0

            self.stability_chip.setText("Stable" if self._hardware_stable_counter >= 2 else "Stabilizing")
            self._apply_header_chip_style(
                self.stability_chip,
                "#42E393" if self._hardware_stable_counter >= 2 else "#FFD25E",
            )

            progress = min(
                92,
                12 + int((available_count / 7.0) * 64) + min(self._hardware_stable_counter * 4, 16),
            )
            status_text = detail or "Collecting hardware measurements…"
            self._set_progress(progress, status_text, emit_signal=True)

            if available_count >= 5 and self._hardware_stable_counter >= 2:
                self._complete_measurement(reason="hardware_stable")
                return

        else:
            self.metric_count_chip.setText("0 / 7 Metrics")
            self.stability_chip.setText("Stability Pending")
            self._apply_header_chip_style(self.stability_chip, "#39D8FF")

            if self._mode == MODE_HARDWARE:
                if connected:
                    self._set_progress(
                        max(self._progress_value, 16),
                        detail or "Connected. Waiting for live sensor values…",
                        emit_signal=force,
                    )
                else:
                    self._set_progress(
                        max(self._progress_value, 8),
                        detail or "Waiting for hardware link and sensor data…",
                        emit_signal=force,
                    )

    def _read_sensor_snapshot(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "measurements": {},
            "connected": bool(self._runtime_snapshot.get("connected", False)),
            "stable": False,
            "detail": "",
        }

        service = self.services.get("sensor_service") or self.services.get("sensor")
        if service is not None:
            for method_name in (
                "snapshot",
                "get_snapshot",
                "current_readings",
                "get_current_readings",
                "get_latest_measurements",
                "latest_measurements",
                "measurements_snapshot",
            ):
                method = getattr(service, method_name, None)
                if callable(method):
                    try:
                        raw = method()
                        if isinstance(raw, Mapping):
                            payload.update(dict(raw))
                            break
                    except Exception:
                        continue

        if not payload.get("measurements"):
            try:
                if self.app_state is not None:
                    for attr_name in ("current_measurements", "measurements", "live_measurements"):
                        attr = getattr(self.app_state, attr_name, None)
                        if isinstance(attr, Mapping):
                            payload["measurements"] = dict(attr)
                            break
            except Exception:
                pass

        return self._normalize_measurement_payload(payload)

    def _normalize_measurement_payload(self, raw_payload: Mapping[str, Any]) -> Dict[str, Any]:
        payload = dict(raw_payload or {})
        raw_measurements = payload.get("measurements", payload)
        source = dict(raw_measurements) if isinstance(raw_measurements, Mapping) else {}

        normalized: Dict[str, Any] = {
            METRIC_TEMPERATURE: source.get(METRIC_TEMPERATURE, source.get("temp", source.get("body_temperature"))),
            METRIC_SPO2: source.get(METRIC_SPO2, source.get("oxygen_saturation")),
            METRIC_PULSE: source.get(METRIC_PULSE, source.get("pulse", source.get("heart_rate", source.get("bpm")))),
            METRIC_RR: source.get(METRIC_RR, source.get("rr", source.get("respiration_rate"))),
            METRIC_WEIGHT: source.get(METRIC_WEIGHT, source.get("weight_kg")),
            METRIC_HEIGHT: source.get(METRIC_HEIGHT, source.get("height_cm", source.get("height_mm", source.get("height_m")))),
            METRIC_BMI: source.get(METRIC_BMI),
        }

        raw_height = normalized.get(METRIC_HEIGHT)
        if raw_height not in (None, ""):
            height_numeric = safe_float(raw_height, 0.0)
            if height_numeric > 300:
                normalized[METRIC_HEIGHT] = round(height_numeric / 10.0, 1)
            elif 0 < height_numeric < 3.5:
                normalized[METRIC_HEIGHT] = round(height_numeric * 100.0, 1)

        if normalized.get(METRIC_BMI) in (None, ""):
            normalized[METRIC_BMI] = _compute_bmi(
                None if normalized.get(METRIC_WEIGHT) in (None, "") else safe_float(normalized.get(METRIC_WEIGHT), 0.0),
                None if normalized.get(METRIC_HEIGHT) in (None, "") else safe_float(normalized.get(METRIC_HEIGHT), 0.0),
            )

        detail = safe_str(payload.get("detail"), "").strip() or safe_str(payload.get("status"), "").strip()
        stable = safe_bool(payload.get("stable"), False)
        connected = safe_bool(payload.get("connected"), self._runtime_snapshot.get("connected", False))

        return {
            "measurements": normalized,
            "connected": connected,
            "stable": stable,
            "detail": detail,
        }

    # -------------------------------------------------------------------------
    # Measurement application
    # -------------------------------------------------------------------------

    def _apply_measurements(self, measurements: Mapping[str, Any]) -> None:
        merged = dict(self._latest_measurements)
        merged.update(dict(measurements or {}))

        if merged.get(METRIC_BMI) in (None, ""):
            merged[METRIC_BMI] = _compute_bmi(
                None if merged.get(METRIC_WEIGHT) in (None, "") else safe_float(merged.get(METRIC_WEIGHT), 0.0),
                None if merged.get(METRIC_HEIGHT) in (None, "") else safe_float(merged.get(METRIC_HEIGHT), 0.0),
            )

        self._latest_measurements = merged

        for metric_key in (
            METRIC_TEMPERATURE,
            METRIC_SPO2,
            METRIC_PULSE,
            METRIC_RR,
            METRIC_WEIGHT,
            METRIC_HEIGHT,
            METRIC_BMI,
        ):
            value = merged.get(metric_key)
            status_text, accent_hex = self._metric_status(metric_key, value)
            self._set_metric(metric_key, value, status_text, accent_hex)

        available_count = self._count_available_metrics(merged)
        self.metric_count_chip.setText(f"{available_count} / 7 Metrics")

    def _set_metric(self, metric_key: str, value: Any, status_text: str, accent_hex: str) -> None:
        widget = self.metric_widgets.get(metric_key)
        if widget is None:
            return

        unit = self.metric_units.get(metric_key, "")

        if _HAS_METRIC_TILE:
            for method_name in ("set_value", "update_value", "set_metric_value"):
                method = getattr(widget, method_name, None)
                if callable(method):
                    try:
                        method(value if value not in (None, "") else "--", unit)
                        break
                    except Exception:
                        try:
                            method(value if value not in (None, "") else "--")
                            break
                        except Exception:
                            continue

            for method_name in ("set_subtitle", "set_status_text", "set_status"):
                method = getattr(widget, method_name, None)
                if callable(method):
                    try:
                        method(status_text)
                        break
                    except Exception:
                        continue

            if hasattr(widget, "set_accent_color"):
                try:
                    widget.set_accent_color(accent_hex)  # type: ignore[attr-defined]
                except Exception:
                    pass
            elif hasattr(widget, "set_severity"):
                try:
                    severity = "normal" if accent_hex == "#42E393" else "attention" if accent_hex == "#FFD25E" else "warning" if accent_hex == "#FFA14D" else "critical" if accent_hex == "#FF6E88" else "unknown"
                    widget.set_severity(severity)  # type: ignore[attr-defined]
                except Exception:
                    pass
            return

        if isinstance(widget, _FallbackMetricCard):
            widget.set_value(value, unit)
            widget.set_status(status_text)
            widget.set_accent(accent_hex)

    def _metric_status(self, metric_key: str, value: Any) -> Tuple[str, str]:
        if value in (None, ""):
            return ("Waiting for reading", "#39D8FF")

        numeric = safe_float(value, 0.0)

        if metric_key == METRIC_TEMPERATURE:
            if numeric < 36.0:
                return ("Low", "#FFD25E")
            if numeric < 37.5:
                return ("Normal", "#42E393")
            if numeric < 39.0:
                return ("Elevated", "#FFA14D")
            return ("High", "#FF6E88")

        if metric_key == METRIC_SPO2:
            if numeric < 90:
                return ("Critical", "#FF6E88")
            if numeric < 94:
                return ("Low", "#FFA14D")
            if numeric < 96:
                return ("Borderline", "#FFD25E")
            return ("Healthy", "#42E393")

        if metric_key == METRIC_PULSE:
            if numeric < 60:
                return ("Low Pulse", "#FFD25E")
            if numeric < 100:
                return ("Normal", "#42E393")
            if numeric < 120:
                return ("Elevated", "#FFA14D")
            return ("Very High", "#FF6E88")

        if metric_key == METRIC_RR:
            if numeric < 12:
                return ("Low", "#FFD25E")
            if numeric < 20:
                return ("Normal", "#42E393")
            if numeric < 24:
                return ("Elevated", "#FFA14D")
            return ("High", "#FF6E88")

        if metric_key == METRIC_BMI:
            if numeric < 18.5:
                return ("Underweight", "#FFD25E")
            if numeric < 25.0:
                return ("Normal", "#42E393")
            if numeric < 30.0:
                return ("Overweight", "#FFA14D")
            return ("Obese", "#FF6E88")

        return ("Captured", "#39D8FF")

    def _count_available_metrics(self, measurements: Mapping[str, Any]) -> int:
        count = 0
        for key in (
            METRIC_TEMPERATURE,
            METRIC_SPO2,
            METRIC_PULSE,
            METRIC_RR,
            METRIC_WEIGHT,
            METRIC_HEIGHT,
            METRIC_BMI,
        ):
            if measurements.get(key) not in (None, ""):
                count += 1
        return count

    def _is_measurement_stable(self) -> bool:
        if len(self._history_buffer) < 3:
            return False

        latest = self._history_buffer[-1]
        prev = self._history_buffer[-2]
        prev2 = self._history_buffer[-3]

        tolerances = {
            METRIC_TEMPERATURE: 0.3,
            METRIC_SPO2: 2.0,
            METRIC_PULSE: 6.0,
            METRIC_RR: 3.0,
            METRIC_WEIGHT: 1.2,
            METRIC_HEIGHT: 2.0,
            METRIC_BMI: 0.6,
        }

        comparable = 0
        stable = 0

        for key, tol in tolerances.items():
            a = latest.get(key)
            b = prev.get(key)
            c = prev2.get(key)

            if a in (None, "") or b in (None, "") or c in (None, ""):
                continue

            comparable += 1
            av = safe_float(a, 0.0)
            bv = safe_float(b, 0.0)
            cv = safe_float(c, 0.0)

            if abs(av - bv) <= tol and abs(bv - cv) <= tol:
                stable += 1

        return comparable >= 4 and stable >= 4

    # -------------------------------------------------------------------------
    # Phase and progress
    # -------------------------------------------------------------------------

    def _phase_for_progress(self, progress: int) -> _PhaseDefinition:
        selected = PHASES[0]
        for phase in PHASES:
            if progress >= phase.min_progress:
                selected = phase
        return selected

    def _apply_phase_from_progress(self) -> None:
        phase = self._phase_for_progress(self._progress_value)
        self._phase_title = phase.title
        self._phase_subtitle = phase.subtitle

        self.phase_chip.setText(phase.title)
        self.hero_subtitle.setText(
            phase.subtitle
        )
        self._apply_header_chip_style(
            self.phase_chip,
            "#39D8FF" if self._progress_value < 56 else ("#FFD25E" if self._progress_value < 84 else "#42E393"),
        )

    def _apply_header_chip_style(self, label: QLabel, accent_hex: str) -> None:
        accent = QColor(accent_hex)
        label.setStyleSheet(
            f"""
            QLabel {{
                color: #EEF9FF;
                font-size: 9px;
                font-weight: 800;
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.34);
                border-radius: 12px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.16);
                padding: 4px 9px;
            }}
            """
        )

    def _set_progress(self, value: int, text: str, *, emit_signal: bool) -> None:
        self._progress_value = max(0, min(100, safe_int(value, 0)))
        self._status_text = safe_str(text, "").strip()

        try:
            if hasattr(self.progress_widget, "set_value"):
                self.progress_widget.set_value(self._progress_value, animated=False)  # type: ignore[attr-defined]
            else:
                self.progress_widget.setValue(self._progress_value)  # type: ignore[attr-defined]
        except Exception:
            pass

        try:
            if hasattr(self.progress_widget, "set_status_text"):
                self.progress_widget.set_status_text(self._status_text)  # type: ignore[attr-defined]
        except Exception:
            pass

        try:
            if hasattr(self.progress_widget, "set_state"):
                if self._progress_value >= 100:
                    state = getattr(self.progress_widget, "STATE_SUCCESS", None)
                else:
                    state = getattr(self.progress_widget, "STATE_PRIMARY", None)
                if state is not None:
                    self.progress_widget.set_state(state)  # type: ignore[attr-defined]
        except Exception:
            pass

        try:
            if hasattr(self.progress_widget, "set_accent_color"):
                if self._progress_value >= 100:
                    self.progress_widget.set_accent_color("#42E393")  # type: ignore[attr-defined]
                else:
                    self.progress_widget.set_accent_color("#39D8FF")  # type: ignore[attr-defined]
        except Exception:
            pass

        self.progress_widget.show()
        self.progress_widget.update()
        self.progress_visual_shell.update()
        self.progress_card.update()

        self.instruction_label.setText(self._status_text)
        self._apply_phase_from_progress()

        if emit_signal:
            self.measurement_progress.emit(self._progress_value, self._status_text)

    # -------------------------------------------------------------------------
    # Completion / persistence
    # -------------------------------------------------------------------------

    def _complete_measurement(self, *, reason: str) -> None:
        if self._measurement_complete:
            return

        self._measurement_complete = True
        self._demo_timer.stop()

        self._set_progress(100, "Measurement complete. Results are ready.", emit_signal=True)
        self.stability_chip.setText("Stable")
        self._apply_header_chip_style(self.stability_chip, "#42E393")

        payload = {
            "mode": self._mode,
            "reason": reason,
            "measurements": dict(self._latest_measurements),
            "runtime_snapshot": dict(self._runtime_snapshot),
        }

        self._persist_measurement_payload(payload)
        self._last_persisted_payload = dict(payload)
        self._set_buttons_for_state()
        self.measurement_completed.emit(dict(payload))

    def _persist_measurement_payload(self, payload: Mapping[str, Any]) -> None:
        data = dict(payload or {})
        measurements = dict(data.get("measurements", {}))

        try:
            session_service = self.services.get("session_service") or self.services.get("session")
            if session_service is not None:
                for method_name in (
                    "set_current_measurements",
                    "update_measurements",
                    "store_measurements",
                    "save_measurements",
                    "set_measurements",
                    "upsert_session_measurements",
                ):
                    method = getattr(session_service, method_name, None)
                    if callable(method):
                        try:
                            method(measurements)
                            break
                        except Exception:
                            try:
                                method(data)
                                break
                            except Exception:
                                continue

                for method_name in ("set_current_mode", "set_mode", "update_mode"):
                    method = getattr(session_service, method_name, None)
                    if callable(method):
                        try:
                            method(self._mode)
                            break
                        except Exception:
                            continue
        except Exception:
            pass

        try:
            if self.app_state is not None:
                for attr_name in ("current_measurements", "measurements", "live_measurements"):
                    if hasattr(self.app_state, attr_name):
                        try:
                            setattr(self.app_state, attr_name, dict(measurements))
                        except Exception:
                            pass

                for attr_name in ("current_mode", "mode"):
                    if hasattr(self.app_state, attr_name):
                        try:
                            setattr(self.app_state, attr_name, self._mode)
                        except Exception:
                            pass

                for method_name in ("set_measurements", "update_measurements", "set_mode"):
                    method = getattr(self.app_state, method_name, None)
                    if callable(method):
                        try:
                            if "mode" in method_name:
                                method(self._mode)
                            else:
                                method(dict(measurements))
                        except Exception:
                            continue
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Buttons / actions
    # -------------------------------------------------------------------------

    def _set_buttons_for_state(self) -> None:
        results_enabled = bool(self._measurement_complete)

        try:
            self.results_button.setEnabled(results_enabled)
            self.restart_button.setEnabled(True)
            self.refresh_button.setEnabled(True)
        except Exception:
            pass

        self._set_button_accent(self.back_button, "#2F8FFF")
        self._set_button_accent(self.results_button, "#42E393" if results_enabled else "#39D8FF")
        self._set_button_accent(self.restart_button, "#FFD25E")
        self._set_button_accent(self.refresh_button, "#67D8FF")

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
                    font-size: 12px;
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

    def _handle_back_clicked(self) -> None:
        self.stop_measurement()
        if self._navigate_to(SCREEN_MODE_SELECT):
            return
        self.back_requested.emit()

    def _handle_refresh_clicked(self) -> None:
        self._refresh_runtime_status()

        if self._measurement_complete:
            self.reset_measurement()
        elif self._measurement_started:
            if self._mode == MODE_HARDWARE:
                self._poll_hardware_measurement(force=True)
            else:
                self._set_progress(max(4, self._progress_value), self._status_text or "Refreshing measurement workflow…", emit_signal=False)
                self.update()
        else:
            self.start_measurement()

        self.refresh_requested.emit()

    def _handle_results_clicked(self) -> None:
        if not self._measurement_complete:
            return

        payload = dict(self._last_persisted_payload or {
            "mode": self._mode,
            "measurements": dict(self._latest_measurements),
            "runtime_snapshot": dict(self._runtime_snapshot),
        })

        if self._navigate_to(SCREEN_RESULTS):
            self.results_requested.emit(payload)
            return

        self.results_requested.emit(payload)

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

    # -------------------------------------------------------------------------
    # Resize / painting
    # -------------------------------------------------------------------------

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_responsive_layout()

    def _paint_header_card_overlay(self, painter: QPainter) -> None:
        header_rect = self.header_card.geometry()
        if not header_rect.isValid():
            return

        overlay_rect = header_rect.adjusted(2, 2, -2, -2)
        path = QPainterPath()
        path.addRoundedRect(QRectF(overlay_rect), 22.0, 22.0)

        painter.save()
        painter.setClipPath(path)

        top_glow_rect = QRectF(
            overlay_rect.left(),
            overlay_rect.top(),
            overlay_rect.width(),
            overlay_rect.height() * 0.48,
        )
        painter.fillRect(top_glow_rect, QColor(72, 220, 255, 16))

        center_glow_rect = QRectF(
            overlay_rect.left() + overlay_rect.width() * 0.18,
            overlay_rect.top() + overlay_rect.height() * 0.16,
            overlay_rect.width() * 0.64,
            overlay_rect.height() * 0.66,
        )
        center_path = QPainterPath()
        center_path.addRoundedRect(center_glow_rect, 34.0, 34.0)
        painter.fillPath(center_path, QColor(52, 170, 255, 16))

        lower_haze_rect = QRectF(
            overlay_rect.left(),
            overlay_rect.bottom() - overlay_rect.height() * 0.18,
            overlay_rect.width(),
            overlay_rect.height() * 0.18,
        )
        painter.fillRect(lower_haze_rect, QColor(78, 226, 255, 12))

        top_line_pen = QPen(QColor(148, 230, 255, 38))
        top_line_pen.setWidthF(1.1)
        painter.setPen(top_line_pen)
        painter.drawRoundedRect(QRectF(overlay_rect.adjusted(6, 6, -6, -6)), 18.0, 18.0)

        painter.restore()

    def _paint_header_progress_bridge(self, painter: QPainter) -> None:
        if self.content_row.isVisible():
            return

        header_rect = self.header_card.geometry()
        progress_rect = self.progress_card.geometry()

        if not header_rect.isValid() or not progress_rect.isValid():
            return

        top_y = float(header_rect.bottom() - 1)
        bottom_y = float(progress_rect.top() + 1)
        if bottom_y <= top_y:
            return

        # Fill the seam between the hero and progress modules so they read as a
        # single connected surface on the compact 800x480 layout.
        left = float(max(header_rect.left(), progress_rect.left()) + 10)
        right = float(min(header_rect.right(), progress_rect.right()) - 10)
        if right <= left:
            return

        bridge_rect = QRectF(left, top_y, right - left, bottom_y - top_y)

        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)

        base_grad = QLinearGradient(bridge_rect.left(), bridge_rect.top(), bridge_rect.left(), bridge_rect.bottom())
        base_grad.setColorAt(0.0, QColor(7, 25, 48, 248))
        base_grad.setColorAt(0.55, QColor(8, 28, 54, 252))
        base_grad.setColorAt(1.0, QColor(9, 30, 57, 248))
        painter.fillRect(bridge_rect, base_grad)

        glow_band = QRectF(bridge_rect.left(), bridge_rect.top() + 1.0, bridge_rect.width(), max(2.0, bridge_rect.height() - 2.0))
        painter.fillRect(glow_band, QColor(92, 210, 255, 18))

        edge_pen = QPen(QColor(136, 226, 255, 50))
        edge_pen.setWidthF(1.0)
        painter.setPen(edge_pen)
        painter.drawLine(int(left + 8), int(top_y + 1), int(right - 8), int(top_y + 1))
        painter.drawLine(int(left + 8), int(bottom_y - 1), int(right - 8), int(bottom_y - 1))
        painter.restore()

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
            painter.fillRect(QRectF(0, 0, rect.width(), rect.height() * 0.38), QColor(53, 214, 255, 16))
            painter.fillRect(QRectF(0, rect.height() * 0.60, rect.width(), rect.height() * 0.40), QColor(20, 82, 128, 18))

            self._paint_header_progress_bridge(painter)
            self._paint_header_card_overlay(painter)

        finally:
            painter.end()