"""
screens/qr_screen.py

Premium QR screen for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the dedicated sharing / handoff screen after results are available
- It presents:
    - the active session QR image
    - QR generation status
    - result/session context
    - quick guidance for scanning and follow-up
- It is designed specifically for:
    - Raspberry Pi 4B touchscreen kiosk deployment
    - 1024x600 kiosk resolution
    - laptop demo mode
- It supports both:
    - Demo Mode simulated results handoff
    - Hardware Mode live-session handoff

Linked project files this screen is intended to work with:
- core/constants.py
- core/asset_paths.py
- core/logger.py
- core/app_state.py
- core/navigator.py
- core/theme_manager.py
- core/animation_manager.py
- services/session_service.py
- services/qr_service.py
- services/report_service.py
- services/mode_service.py
- widgets/animated_button.py
- widgets/glow_label.py

Navigation targets this screen is designed to link to:
- screens/results_screen.py
- screens/consult_screen.py
- screens/measuring_screen.py

Design goals:
- glossy futuristic blue medical UI
- highly readable scan-focused layout
- clear kiosk handoff experience
- resilient QR generation with safe fallbacks
- maintainable structure while backend services continue to be integrated
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
        MODE_DEMO,
        MODE_HARDWARE,
        SCREEN_CONSULT,
        SCREEN_MEASURING,
        SCREEN_RESULTS,
    )
except Exception:  # pragma: no cover
    MODE_DEMO = "demo"
    MODE_HARDWARE = "hardware"
    SCREEN_RESULTS = "results"
    SCREEN_CONSULT = "consult"
    SCREEN_MEASURING = "measuring"

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


# =============================================================================
# Internal QR preview card
# =============================================================================

class _QRPreviewCard(QFrame):
    """
    Premium QR preview card with:
    - image preview
    - large scan focus
    - fallback placeholder when QR is missing
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._accent_hex = "#39D8FF"
        self._status_text = "QR Pending"
        self._subtitle_text = "The kiosk will display the active session QR code here."
        self._qr_path = ""
        self._qr_pixmap = QPixmap()

        self.setObjectName("QRPreviewCard")
        self.setMinimumWidth(420)
        self.setMinimumHeight(320)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        self._root_layout = root
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        top_row = QWidget(self)
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        self.title_label = QLabel("Scan QR Code", top_row)
        self.status_chip = QLabel(self._status_text, top_row)

        top_layout.addWidget(self.title_label)
        top_layout.addStretch(1)
        top_layout.addWidget(self.status_chip)

        self.preview_shell = QFrame(self)
        self.preview_shell.setObjectName("QRPreviewShell")
        self.preview_shell.setMinimumHeight(232)

        preview_layout = QVBoxLayout(self.preview_shell)
        preview_layout.setContentsMargins(14, 14, 14, 14)
        preview_layout.setSpacing(8)

        self.preview_label = QLabel(self.preview_shell)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(188)
        self.preview_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._preview_target_size = 262
        self._compact_mode = False
        self._ultra_compact_mode = False

        preview_layout.addStretch(1)
        preview_layout.addWidget(self.preview_label, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        preview_layout.addStretch(1)

        self.subtitle_label = QLabel(self._subtitle_text, self)
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        root.addWidget(top_row)
        root.addWidget(self.preview_shell, 1)
        root.addWidget(self.subtitle_label)

        self._apply_style()
        self._refresh_preview()

    def set_payload(
        self,
        *,
        qr_path: str,
        status_text: str,
        subtitle: str,
        accent_hex: str,
    ) -> None:
        self._qr_path = safe_str(qr_path, "").strip()
        self._status_text = safe_str(status_text, "QR Pending").strip() or "QR Pending"
        self._subtitle_text = safe_str(subtitle, "").strip() or "The active session QR code will appear here."
        self._accent_hex = safe_str(accent_hex, "#39D8FF").strip() or "#39D8FF"

        self.status_chip.setText(self._status_text)
        self.subtitle_label.setText(self._subtitle_text)
        self._qr_pixmap = _pixmap_or_empty(self._qr_path)

        self._apply_style()
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        available_w = max(120, self.preview_shell.width() - 34)
        available_h = max(120, self.preview_shell.height() - 34)
        target_size = max(112, min(available_w, available_h, self._preview_target_size))

        if not self._qr_pixmap.isNull():
            scaled = self._qr_pixmap.scaled(
                target_size,
                target_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.preview_label.setPixmap(scaled)
            self.preview_label.setText("")
            self.preview_label.setStyleSheet("QLabel { background: transparent; }")
            return

        placeholder_radius = 20 if not self._ultra_compact_mode else 16
        placeholder_font = 20 if not self._compact_mode else 18
        if self._ultra_compact_mode:
            placeholder_font = 16

        self.preview_label.clear()
        self.preview_label.setText("QR\nUnavailable")
        self.preview_label.setStyleSheet(
            f"""
            QLabel {{
                color: rgba(224, 241, 251, 0.86);
                font-size: {placeholder_font}px;
                font-weight: 900;
                border: 1px dashed rgba(157, 220, 255, 0.26);
                border-radius: {placeholder_radius}px;
                background: rgba(17, 37, 64, 0.68);
                padding: 18px;
            }}
            """
        )

    def set_compact_mode(self, compact: bool, ultra_compact: bool = False) -> None:
        self._compact_mode = bool(compact)
        self._ultra_compact_mode = bool(ultra_compact)

        if self._ultra_compact_mode:
            self._preview_target_size = 176
            self.setMinimumHeight(250)
            self.preview_shell.setMinimumHeight(172)
            self.preview_label.setMinimumHeight(136)
            self._root_layout.setContentsMargins(12, 12, 12, 12)
            self._root_layout.setSpacing(8)
        elif self._compact_mode:
            self._preview_target_size = 208
            self.setMinimumHeight(276)
            self.preview_shell.setMinimumHeight(194)
            self.preview_label.setMinimumHeight(152)
            self._root_layout.setContentsMargins(14, 14, 14, 14)
            self._root_layout.setSpacing(8)
        else:
            self._preview_target_size = 262
            self.setMinimumHeight(320)
            self.preview_shell.setMinimumHeight(232)
            self.preview_label.setMinimumHeight(188)
            self._root_layout.setContentsMargins(18, 16, 18, 16)
            self._root_layout.setSpacing(10)

        self._refresh_preview()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_preview()

    def _apply_style(self) -> None:
        accent = QColor(self._accent_hex)

        self.setStyleSheet(
            f"""
            QFrame#QRPreviewCard {{
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.22);
                border-radius: 24px;
                background: rgba(10, 28, 47, 0.96);
            }}

            QFrame#QRPreviewShell {{
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.18);
                border-radius: 22px;
                background: rgba(14, 34, 56, 0.98);
            }}
            """
        )

        self.title_label.setStyleSheet(
            """
            QLabel {
                color: #F4FCFF;
                font-size: 13px;
                font-weight: 800;
                background: transparent;
            }
            """
        )
        self.status_chip.setStyleSheet(
            f"""
            QLabel {{
                color: #F4FCFF;
                font-size: 9px;
                font-weight: 800;
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.34);
                border-radius: 12px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.16);
                padding: 4px 9px;
            }}
            """
        )
        self.subtitle_label.setStyleSheet(
            """
            QLabel {
                color: rgba(206, 229, 244, 0.88);
                font-size: 10px;
                font-weight: 500;
                background: transparent;
            }
            """
        )

        if not self._qr_pixmap.isNull():
            self.preview_label.setStyleSheet("QLabel { background: transparent; }")


# =============================================================================
# Main screen
# =============================================================================

class QRScreen(QFrame):
    """
    Premium QR presentation screen.

    Main responsibilities:
    - load the latest active session / results payload
    - display or regenerate the QR code
    - present scan instructions and session source context
    - hand off to consult or retake flow
    """

    back_requested = pyqtSignal()
    refresh_requested = pyqtSignal()
    qr_loaded = pyqtSignal(dict)
    qr_regenerated = pyqtSignal(dict)
    consult_requested = pyqtSignal(dict)
    retake_requested = pyqtSignal()
    report_requested = pyqtSignal(dict)

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

        self._logger = logger.bind(component="QRScreen")

        self.navigator = navigator
        self.app_state = app_state
        self.services = dict(services or {})
        self.animation_manager = animation_manager
        self.theme_manager = theme_manager

        self._mode = self._read_current_mode()
        self._payload: Dict[str, Any] = {}
        self._qr_path = ""
        self._report_path = ""

        self._background_path = _resolve_asset("backgrounds/qr_bg.png")
        self._logo_small_path = _resolve_asset("logos/17869566.png")
        self._qr_icon_path = _resolve_asset("icons/qr.png")
        self._report_icon_path = _resolve_asset("icons/pdf.png")
        self._consult_icon_path = _resolve_asset("icons/consult.png")

        self._background_pixmap = _pixmap_or_empty(self._background_path)
        self._logo_pixmap = _pixmap_or_empty(self._logo_small_path)

        self.setObjectName("QRScreen")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._build_ui()
        self._setup_effects()
        self._apply_styles()
        self._apply_responsive_layout()

    # =========================================================================
    # UI
    # =========================================================================

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        self._root_layout = root
        root.setContentsMargins(22, 16, 22, 16)
        root.setSpacing(12)

        # ---------------------------------------------------------------------
        # Top bar
        # ---------------------------------------------------------------------
        self.top_bar = QWidget(self)
        top_layout = QHBoxLayout(self.top_bar)
        self._top_layout = top_layout
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(10)

        self.back_button = self._create_button("Back", variant="secondary", min_width=96, parent=self.top_bar)
        self.back_button.clicked.connect(self._handle_back_clicked)

        self.logo_badge = QLabel(self.top_bar)
        self.logo_badge.setObjectName("LogoBadge")
        self.logo_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_label_pixmap(self.logo_badge, self._logo_pixmap, 26)

        self.top_title = QLabel("Session QR Code", self.top_bar)
        self.top_title.setObjectName("TopTitle")

        self.mode_pill = QLabel("Mode Unknown", self.top_bar)
        self.mode_pill.setObjectName("RuntimePill")

        self.qr_pill = QLabel("QR Pending", self.top_bar)
        self.qr_pill.setObjectName("RuntimePill")

        self.report_pill = QLabel("Report Pending", self.top_bar)
        self.report_pill.setObjectName("RuntimePill")

        top_layout.addWidget(self.back_button)
        top_layout.addWidget(self.logo_badge)
        top_layout.addWidget(self.top_title)
        top_layout.addStretch(1)
        top_layout.addWidget(self.mode_pill)
        top_layout.addWidget(self.qr_pill)
        top_layout.addWidget(self.report_pill)

        # ---------------------------------------------------------------------
        # Header card
        # ---------------------------------------------------------------------
        self.header_card = QFrame(self)
        self.header_card.setObjectName("QRHeaderCard")

        header_layout = QVBoxLayout(self.header_card)
        self._header_layout = header_layout
        header_layout.setContentsMargins(18, 16, 18, 16)
        header_layout.setSpacing(8)

        if _HAS_GLOW_LABEL:
            self.hero_title = GlowLabel(
                role=getattr(GlowLabel, "ROLE_TITLE", getattr(GlowLabel, "ROLE_STATUS", 0)),
                align_center=True,
                use_outline=False,
                enable_paint_glow=True,
                initial_glow_strength=0.48,
                initial_glow_blur=18,
            )
        else:
            self.hero_title = QLabel(self.header_card)
            self.hero_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.hero_subtitle = QLabel(self.header_card)
        self.hero_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hero_subtitle.setWordWrap(True)

        self.header_chip_row = QWidget(self.header_card)
        chip_layout = QHBoxLayout(self.header_chip_row)
        self._chip_layout = chip_layout
        chip_layout.setContentsMargins(0, 0, 0, 0)
        chip_layout.setSpacing(8)

        self.scan_chip = QLabel("Ready to Scan", self.header_chip_row)
        self.scan_chip.setObjectName("HeaderChip")

        self.source_chip = QLabel("Session Source", self.header_chip_row)
        self.source_chip.setObjectName("HeaderChip")

        self.hint_chip = QLabel("Show this to the user for scanning", self.header_chip_row)
        self.hint_chip.setObjectName("HeaderChip")

        chip_layout.addStretch(1)
        chip_layout.addWidget(self.scan_chip)
        chip_layout.addWidget(self.source_chip)
        chip_layout.addWidget(self.hint_chip)
        chip_layout.addStretch(1)

        self.summary_banner = QLabel(
            "The QR code can be used to access or share the active measurement session handoff.",
            self.header_card,
        )
        self.summary_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.summary_banner.setWordWrap(True)

        header_layout.addWidget(self.hero_title)
        header_layout.addWidget(self.hero_subtitle)
        header_layout.addWidget(self.header_chip_row)
        header_layout.addWidget(self.summary_banner)

        # ---------------------------------------------------------------------
        # Content row
        # ---------------------------------------------------------------------
        self.content_row = QWidget(self)
        content_layout = QHBoxLayout(self.content_row)
        self._content_layout = content_layout
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(14)

        self.preview_card = _QRPreviewCard(self.content_row)

        self.side_panel = QWidget(self.content_row)
        side_layout = QVBoxLayout(self.side_panel)
        self._side_layout = side_layout
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(12)
        self.side_panel.setMinimumWidth(252)
        self.side_panel.setMaximumWidth(290)

        self.info_card = QFrame(self.side_panel)
        self.info_card.setObjectName("InfoCard")

        info_layout = QVBoxLayout(self.info_card)
        self._info_layout = info_layout
        info_layout.setContentsMargins(16, 14, 16, 14)
        info_layout.setSpacing(8)

        self.info_title = QLabel("Scan Guidance", self.info_card)
        self.info_title.setObjectName("SectionTitle")

        self.info_line_1 = QLabel("• Hold the phone camera steadily over the QR code.", self.info_card)
        self.info_line_2 = QLabel("• Keep the full code visible without glare.", self.info_card)
        self.info_line_3 = QLabel("• Use the consult option if the result needs review.", self.info_card)

        self.info_note = QLabel(
            "This QR is linked to the active kiosk session handoff. Regenerate it if the payload changes or a new report is created.",
            self.info_card,
        )
        self.info_note.setWordWrap(True)

        info_layout.addWidget(self.info_title)
        info_layout.addWidget(self.info_line_1)
        info_layout.addWidget(self.info_line_2)
        info_layout.addWidget(self.info_line_3)
        info_layout.addWidget(self.info_note)

        self.session_card = QFrame(self.side_panel)
        self.session_card.setObjectName("InfoCard")

        session_layout = QVBoxLayout(self.session_card)
        self._session_layout = session_layout
        session_layout.setContentsMargins(16, 14, 16, 14)
        session_layout.setSpacing(6)

        self.session_title = QLabel("Session Context", self.session_card)
        self.session_title.setObjectName("SectionTitle")

        self.mode_line = QLabel("Mode: pending", self.session_card)
        self.metrics_line = QLabel("Metrics: pending", self.session_card)
        self.report_line = QLabel("Report path: pending", self.session_card)
        self.qr_line = QLabel("QR path: pending", self.session_card)
        self.session_detail = QLabel(
            "The QR handoff can be refreshed at any time after results or reports are updated.",
            self.session_card,
        )
        self.session_detail.setWordWrap(True)

        session_layout.addWidget(self.session_title)
        session_layout.addWidget(self.mode_line)
        session_layout.addWidget(self.metrics_line)
        session_layout.addWidget(self.report_line)
        session_layout.addWidget(self.qr_line)
        session_layout.addWidget(self.session_detail)

        self.quick_action_card = QFrame(self.side_panel)
        self.quick_action_card.setObjectName("InfoCard")

        qa_layout = QVBoxLayout(self.quick_action_card)
        self._qa_layout = qa_layout
        qa_layout.setContentsMargins(16, 14, 16, 14)
        qa_layout.setSpacing(8)

        self.quick_title = QLabel("Quick Actions", self.quick_action_card)
        self.quick_title.setObjectName("SectionTitle")

        self.quick_text = QLabel(
            "Regenerate the QR, open the consult flow, or return for a fresh measurement run.",
            self.quick_action_card,
        )
        self.quick_text.setWordWrap(True)

        self.regenerate_button = self._create_button("Regenerate QR", variant="ghost", min_width=150, parent=self.quick_action_card)
        self.regenerate_button.clicked.connect(self._handle_regenerate_clicked)

        self.report_button = self._create_button("Prepare PDF", variant="secondary", min_width=150, parent=self.quick_action_card)
        self.report_button.clicked.connect(self._handle_report_clicked)

        self.consult_button = self._create_button("Open Consult", variant="primary", min_width=150, parent=self.quick_action_card)
        self.consult_button.clicked.connect(self._handle_consult_clicked)

        qa_layout.addWidget(self.quick_title)
        qa_layout.addWidget(self.quick_text)
        qa_layout.addWidget(self.regenerate_button)
        qa_layout.addWidget(self.report_button)
        qa_layout.addWidget(self.consult_button)

        side_layout.addWidget(self.info_card)
        side_layout.addWidget(self.session_card)
        side_layout.addWidget(self.quick_action_card)
        side_layout.addStretch(1)

        self.info_card.hide()
        self.session_card.hide()
        self.quick_action_card.hide()
        self.side_panel.hide()
        self.side_panel.setMinimumWidth(0)
        self.side_panel.setMaximumWidth(0)

        content_layout.addWidget(self.preview_card, 1)

        # ---------------------------------------------------------------------
        # Bottom actions
        # ---------------------------------------------------------------------
        self.action_row = QWidget(self)
        action_layout = QHBoxLayout(self.action_row)
        self._action_layout = action_layout
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(10)

        self.refresh_button = self._create_button("Refresh QR", variant="ghost", min_width=130, parent=self.action_row)
        self.refresh_button.clicked.connect(self.reload_qr)

        self.results_button = self._create_button("Back to Results", variant="secondary", min_width=146, parent=self.action_row)
        self.results_button.clicked.connect(self._handle_back_clicked)

        self.new_checkup_button = self._create_button("New Checkup", variant="secondary", min_width=140, parent=self.action_row)
        self.new_checkup_button.clicked.connect(self._handle_new_checkup_clicked)

        self.bottom_consult_button = self._create_button("Consult", variant="primary", min_width=132, parent=self.action_row)
        self.bottom_consult_button.clicked.connect(self._handle_consult_clicked)

        action_layout.addWidget(self.refresh_button)
        action_layout.addStretch(1)
        action_layout.addWidget(self.results_button)
        action_layout.addWidget(self.new_checkup_button)
        action_layout.addWidget(self.bottom_consult_button)

        root.addWidget(self.top_bar)
        root.addWidget(self.header_card)
        root.addWidget(self.content_row, 1)
        root.addWidget(self.action_row)

    def _create_button(self, text: str, *, variant: str, min_width: int, parent: QWidget) -> QWidget:
        button_height = 42 if variant == "primary" else 40

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
                    size=getattr(AnimatedButton, "SIZE_MD", None),
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
                return btn
            except Exception:
                pass

        button = QPushButton(text, parent)
        button.setFixedWidth(min_width)
        button.setFixedHeight(button_height)
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            """
            QPushButton {
                color: #F6FCFF;
                border: 1px solid rgba(157, 220, 255, 0.26);
                border-radius: 14px;
                padding: 10px 16px;
                font-size: 12px;
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
        self.header_opacity = QGraphicsOpacityEffect(self.header_card)
        self.header_card.setGraphicsEffect(self.header_opacity)
        self.header_opacity.setOpacity(0.0)

        self.content_opacity = QGraphicsOpacityEffect(self.content_row)
        self.content_row.setGraphicsEffect(self.content_opacity)
        self.content_opacity.setOpacity(0.0)

        self.entry_group = QParallelAnimationGroup(self)

        self.header_fade = QPropertyAnimation(self.header_opacity, b"opacity", self)
        self.header_fade.setDuration(360)
        self.header_fade.setStartValue(0.0)
        self.header_fade.setEndValue(1.0)
        self.header_fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.content_fade = QPropertyAnimation(self.content_opacity, b"opacity", self)
        self.content_fade.setDuration(520)
        self.content_fade.setStartValue(0.0)
        self.content_fade.setEndValue(1.0)
        self.content_fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.entry_group.addAnimation(self.header_fade)
        self.entry_group.addAnimation(self.content_fade)

        preview_shadow = QGraphicsDropShadowEffect(self.preview_card)
        preview_shadow.setBlurRadius(26)
        preview_shadow.setOffset(0, 6)
        shadow_color = QColor("#39D8FF")
        shadow_color.setAlpha(62)
        preview_shadow.setColor(shadow_color)
        self.preview_card.setGraphicsEffect(preview_shadow)

        if _HAS_GLOW_LABEL and isinstance(self.hero_title, GlowLabel):
            try:
                self.hero_title.set_glow_color("#43D9FF")
                self.hero_title.set_text_color("#F5FCFF")
            except Exception:
                pass

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QFrame#QRScreen {
                background: transparent;
            }

            QLabel#LogoBadge {
                min-width: 42px;
                max-width: 42px;
                min-height: 42px;
                max-height: 42px;
                border-radius: 14px;
                border: 1px solid rgba(157, 220, 255, 0.18);
                background: rgba(17, 37, 62, 0.96);
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
                font-weight: 700;
                border: 1px solid rgba(157, 220, 255, 0.22);
                border-radius: 14px;
                background: rgba(17, 37, 62, 0.96);
                padding: 6px 10px;
            }

            QFrame#QRHeaderCard {
                border: 1px solid rgba(170, 230, 255, 0.20);
                border-radius: 22px;
                background: rgba(11, 28, 48, 0.97);
            }

            QLabel#HeaderChip {
                color: #EEF9FF;
                font-size: 9px;
                font-weight: 800;
                border: 1px solid rgba(157, 220, 255, 0.22);
                border-radius: 12px;
                background: rgba(21, 48, 78, 0.94);
                padding: 4px 9px;
            }

            QFrame#InfoCard {
                border: 1px solid rgba(170, 230, 255, 0.20);
                border-radius: 22px;
                background: rgba(11, 28, 48, 0.97);
            }

            QLabel#SectionTitle {
                color: #F4FCFF;
                font-size: 12px;
                font-weight: 800;
                background: transparent;
            }
            """
        )

        if _HAS_GLOW_LABEL and isinstance(self.hero_title, GlowLabel):
            try:
                self.hero_title.set_text("Share the active session by QR")
            except Exception:
                self.hero_title.setText("Share the active session by QR")
        else:
            self.hero_title.setText("Share the active session by QR")

        self.hero_subtitle.setText(
            "Display the active handoff code for scanning, regenerate it if needed, and continue to consultation when follow-up is required."
        )
        self.summary_banner.setText(
            "This screen is optimized for quick kiosk-side scanning and result handoff."
        )

        self.hero_title.setStyleSheet(
            """
            QLabel {
                color: #F6FCFF;
                font-size: 24px;
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
                font-weight: 500;
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

        info_text_style = """
            QLabel {
                color: rgba(214, 235, 248, 0.86);
                font-size: 10px;
                font-weight: 500;
                background: transparent;
            }
        """
        self.info_line_1.setStyleSheet(info_text_style)
        self.info_line_2.setStyleSheet(info_text_style)
        self.info_line_3.setStyleSheet(info_text_style)
        self.info_note.setStyleSheet(info_text_style)
        self.mode_line.setStyleSheet(info_text_style)
        self.metrics_line.setStyleSheet(info_text_style)
        self.report_line.setStyleSheet(info_text_style)
        self.qr_line.setStyleSheet(info_text_style)
        self.session_detail.setStyleSheet(info_text_style)
        self.quick_text.setStyleSheet(info_text_style)

    # =========================================================================
    # Lifecycle
    # =========================================================================

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_responsive_layout()
        self._play_entry_animation()
        self.reload_qr()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_responsive_layout()

    def _apply_responsive_layout(self) -> None:
        width = max(1, self.width())
        height = max(1, self.height())
        compact = (width <= 920 or height <= 560)
        ultra_compact = (width <= 820 or height <= 500)

        self.info_card.hide()
        self.session_card.hide()
        self.quick_action_card.hide()
        self.side_panel.hide()
        self.side_panel.setMinimumWidth(0)
        self.side_panel.setMaximumWidth(0)

        if ultra_compact:
            self._root_layout.setContentsMargins(14, 10, 14, 10)
            self._root_layout.setSpacing(8)
            self._top_layout.setSpacing(8)
            self._header_layout.setContentsMargins(14, 12, 14, 12)
            self._header_layout.setSpacing(6)
            self._chip_layout.setSpacing(6)
            self._content_layout.setSpacing(0)
            self._side_layout.setSpacing(8)
            self._info_layout.setContentsMargins(12, 10, 12, 10)
            self._session_layout.setContentsMargins(12, 10, 12, 10)
            self._qa_layout.setContentsMargins(12, 10, 12, 10)
            self._info_layout.setSpacing(6)
            self._session_layout.setSpacing(5)
            self._qa_layout.setSpacing(6)
            self.side_panel.setMinimumWidth(0)
            self.side_panel.setMaximumWidth(0)
            self.preview_card.set_compact_mode(True, True)
            self.hero_title.setStyleSheet(
                """
                QLabel {
                    color: #F6FCFF;
                    font-size: 18px;
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
            info_text_style = "QLabel { color: rgba(214, 235, 248, 0.86); font-size: 9px; font-weight: 500; background: transparent; }"
            self.info_line_1.setStyleSheet(info_text_style)
            self.info_line_2.setStyleSheet(info_text_style)
            self.info_line_3.setStyleSheet(info_text_style)
            self.info_note.setStyleSheet(info_text_style)
            self.mode_line.setStyleSheet(info_text_style)
            self.metrics_line.setStyleSheet(info_text_style)
            self.report_line.setStyleSheet(info_text_style)
            self.qr_line.setStyleSheet(info_text_style)
            self.session_detail.setStyleSheet(info_text_style)
            self.quick_text.setStyleSheet(info_text_style)
            self.refresh_button.setFixedWidth(116)
            self.results_button.setFixedWidth(132)
            self.new_checkup_button.setFixedWidth(126)
            self.bottom_consult_button.setFixedWidth(116)
            self.regenerate_button.setFixedWidth(136)
            self.report_button.setFixedWidth(136)
            self.consult_button.setFixedWidth(136)
        elif compact:
            self._root_layout.setContentsMargins(16, 12, 16, 12)
            self._root_layout.setSpacing(10)
            self._top_layout.setSpacing(8)
            self._header_layout.setContentsMargins(16, 14, 16, 14)
            self._header_layout.setSpacing(7)
            self._chip_layout.setSpacing(7)
            self._content_layout.setSpacing(0)
            self._side_layout.setSpacing(10)
            self._info_layout.setContentsMargins(14, 12, 14, 12)
            self._session_layout.setContentsMargins(14, 12, 14, 12)
            self._qa_layout.setContentsMargins(14, 12, 14, 12)
            self._info_layout.setSpacing(7)
            self._session_layout.setSpacing(6)
            self._qa_layout.setSpacing(7)
            self.side_panel.setMinimumWidth(0)
            self.side_panel.setMaximumWidth(0)
            self.preview_card.set_compact_mode(True, False)
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
                    font-size: 10px;
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
            info_text_style = "QLabel { color: rgba(214, 235, 248, 0.86); font-size: 9px; font-weight: 500; background: transparent; }"
            self.info_line_1.setStyleSheet(info_text_style)
            self.info_line_2.setStyleSheet(info_text_style)
            self.info_line_3.setStyleSheet(info_text_style)
            self.info_note.setStyleSheet(info_text_style)
            self.mode_line.setStyleSheet(info_text_style)
            self.metrics_line.setStyleSheet(info_text_style)
            self.report_line.setStyleSheet(info_text_style)
            self.qr_line.setStyleSheet(info_text_style)
            self.session_detail.setStyleSheet(info_text_style)
            self.quick_text.setStyleSheet(info_text_style)
            self.refresh_button.setFixedWidth(122)
            self.results_button.setFixedWidth(138)
            self.new_checkup_button.setFixedWidth(130)
            self.bottom_consult_button.setFixedWidth(120)
            self.regenerate_button.setFixedWidth(142)
            self.report_button.setFixedWidth(142)
            self.consult_button.setFixedWidth(142)
        else:
            self._root_layout.setContentsMargins(22, 16, 22, 16)
            self._root_layout.setSpacing(12)
            self._top_layout.setSpacing(10)
            self._header_layout.setContentsMargins(18, 16, 18, 16)
            self._header_layout.setSpacing(8)
            self._chip_layout.setSpacing(8)
            self._content_layout.setSpacing(0)
            self._side_layout.setSpacing(12)
            self._info_layout.setContentsMargins(16, 14, 16, 14)
            self._session_layout.setContentsMargins(16, 14, 16, 14)
            self._qa_layout.setContentsMargins(16, 14, 16, 14)
            self._info_layout.setSpacing(8)
            self._session_layout.setSpacing(6)
            self._qa_layout.setSpacing(8)
            self.side_panel.setMinimumWidth(0)
            self.side_panel.setMaximumWidth(0)
            self.preview_card.set_compact_mode(False, False)
            self.hero_title.setStyleSheet(
                """
                QLabel {
                    color: #F6FCFF;
                    font-size: 24px;
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
                    font-weight: 500;
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
            info_text_style = "QLabel { color: rgba(214, 235, 248, 0.86); font-size: 10px; font-weight: 500; background: transparent; }"
            self.info_line_1.setStyleSheet(info_text_style)
            self.info_line_2.setStyleSheet(info_text_style)
            self.info_line_3.setStyleSheet(info_text_style)
            self.info_note.setStyleSheet(info_text_style)
            self.mode_line.setStyleSheet(info_text_style)
            self.metrics_line.setStyleSheet(info_text_style)
            self.report_line.setStyleSheet(info_text_style)
            self.qr_line.setStyleSheet(info_text_style)
            self.session_detail.setStyleSheet(info_text_style)
            self.quick_text.setStyleSheet(info_text_style)
            self.refresh_button.setFixedWidth(130)
            self.results_button.setFixedWidth(146)
            self.new_checkup_button.setFixedWidth(140)
            self.bottom_consult_button.setFixedWidth(132)
            self.regenerate_button.setFixedWidth(150)
            self.report_button.setFixedWidth(150)
            self.consult_button.setFixedWidth(150)

        self.content_row.updateGeometry()
        self.preview_card.updateGeometry()
        self.preview_card._refresh_preview()

    def _play_entry_animation(self) -> None:
        try:
            self.entry_group.start()
        except Exception:
            pass

    # =========================================================================
    # Data loading / persistence
    # =========================================================================

    def set_payload(self, payload: Mapping[str, Any]) -> None:
        self._payload = dict(payload or {})
        self._mode = safe_str(self._payload.get("mode"), self._read_current_mode()).strip().lower() or self._read_current_mode()
        self._qr_path = safe_str(self._payload.get("qr_path"), "").strip()
        self._report_path = safe_str(self._payload.get("report_path"), "").strip()
        self._persist_payload()
        self._apply_payload_to_ui()

    def reload_qr(self) -> None:
        payload = self._load_payload()

        self._payload = dict(payload)
        self._mode = safe_str(payload.get("mode"), self._read_current_mode()).strip().lower() or self._read_current_mode()
        self._qr_path = safe_str(payload.get("qr_path"), "").strip()
        self._report_path = safe_str(payload.get("report_path"), "").strip()

        if not self._qr_path:
            self._qr_path = self._generate_qr_from_payload(payload)

        if not self._report_path:
            self._report_path = self._load_report_path_from_services()

        self._payload["qr_path"] = self._qr_path
        self._payload["report_path"] = self._report_path

        self._persist_payload()
        self._apply_payload_to_ui()
        self.qr_loaded.emit(dict(self._payload))
        self.refresh_requested.emit()

    def _load_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}

        # 1) session service
        try:
            session_service = self.services.get("session_service") or self.services.get("session")
            if session_service is not None:
                for method_name in (
                    "get_qr_payload",
                    "get_current_session",
                    "get_session_payload",
                    "current_session_payload",
                    "get_latest_results_payload",
                    "get_results_payload",
                ):
                    method = getattr(session_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method()
                            if isinstance(raw, Mapping):
                                payload = dict(raw)
                                if payload:
                                    break
                        except Exception:
                            continue
        except Exception:
            pass

        # 2) app state fallback
        if not payload:
            try:
                if self.app_state is not None:
                    for attr_name in ("results_payload", "current_session_payload", "session_payload"):
                        attr = getattr(self.app_state, attr_name, None)
                        if isinstance(attr, Mapping):
                            payload = dict(attr)
                            if payload:
                                break
            except Exception:
                pass

        # normalize minimum structure
        measurements = payload.get("measurements", {})
        if not isinstance(measurements, Mapping):
            measurements = {}

        payload.setdefault("mode", self._read_current_mode())
        payload.setdefault("measurements", dict(measurements))
        payload.setdefault("classifications", {})
        payload.setdefault("summary", {})
        payload.setdefault("qr_path", self._load_qr_path_from_services())
        payload.setdefault("report_path", self._load_report_path_from_services())

        return payload

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
                        result_text = safe_str(result, "").strip().lower()
                        if result_text:
                            mode = result_text
                            break
        except Exception:
            pass

        if mode not in {MODE_DEMO, MODE_HARDWARE}:
            mode = MODE_DEMO
        return mode

    def _load_qr_path_from_services(self) -> str:
        qr_path = ""

        try:
            session_service = self.services.get("session_service") or self.services.get("session")
            if session_service is not None:
                for method_name in ("get_qr_path", "qr_path", "current_qr_path"):
                    method = getattr(session_service, method_name, None)
                    if callable(method):
                        try:
                            result = method()
                            qr_path = safe_str(result, "").strip()
                            if qr_path:
                                return qr_path
                        except Exception:
                            continue
        except Exception:
            pass

        try:
            if self.app_state is not None:
                attr = getattr(self.app_state, "qr_path", None)
                if isinstance(attr, str) and attr.strip():
                    qr_path = attr.strip()
        except Exception:
            pass

        return qr_path

    def _load_report_path_from_services(self) -> str:
        report_path = ""

        try:
            session_service = self.services.get("session_service") or self.services.get("session")
            if session_service is not None:
                for method_name in ("get_report_path", "report_path", "current_report_path"):
                    method = getattr(session_service, method_name, None)
                    if callable(method):
                        try:
                            result = method()
                            report_path = safe_str(result, "").strip()
                            if report_path:
                                return report_path
                        except Exception:
                            continue
        except Exception:
            pass

        try:
            if self.app_state is not None:
                attr = getattr(self.app_state, "report_path", None)
                if isinstance(attr, str) and attr.strip():
                    report_path = attr.strip()
        except Exception:
            pass

        return report_path

    def _extract_generated_artifact_path(
        self,
        result: Any,
        *,
        preferred_keys: tuple[str, ...],
    ) -> str:
        if isinstance(result, Mapping):
            for key in preferred_keys:
                value = safe_str(result.get(key), "").strip()
                if value:
                    return value

            for nested_key in ("payload", "data", "result", "artifact"):
                nested = result.get(nested_key)
                if isinstance(nested, Mapping):
                    for key in preferred_keys:
                        value = safe_str(nested.get(key), "").strip()
                        if value:
                            return value

        return safe_str(result, "").strip()

    def _generate_qr_from_payload(self, payload: Mapping[str, Any]) -> str:
        qr_path = ""
        session_payload = dict(payload or {})
        measurements = session_payload.get("measurements", {})
        diagnosis_payload = session_payload.get("diagnosis", {})
        session_id = safe_str(session_payload.get("session_id"), "").strip()

        if not isinstance(measurements, Mapping):
            measurements = {}
        if not isinstance(diagnosis_payload, Mapping):
            diagnosis_payload = {}

        try:
            qr_service = self.services.get("qr_service") or self.services.get("qr")
            if qr_service is not None:
                for method_name in (
                    "generate_qr",
                    "generate_current_session_qr",
                    "create_qr",
                    "build_qr",
                    "generate_session_qr",
                    "create_session_qr",
                    "generate_qr_for_session_id",
                ):
                    method = getattr(qr_service, method_name, None)
                    if not callable(method):
                        continue

                    call_patterns = []
                    if method_name == "generate_qr_for_session_id":
                        if session_id:
                            call_patterns.append(lambda m=method, s=session_id: m(s, attach_to_app_state=True))
                            call_patterns.append(lambda m=method, s=session_id: m(s))
                    elif method_name == "generate_current_session_qr":
                        call_patterns.append(lambda m=method: m(persist_to_database=True))
                        call_patterns.append(lambda m=method: m())
                    else:
                        call_patterns.extend([
                            lambda m=method, p=session_payload, meas=measurements, diag=diagnosis_payload: m(
                                session_payload=p,
                                measurements=meas,
                                diagnosis_payload=diag,
                                attach_to_app_state=True,
                                persist_to_database=True,
                            ),
                            lambda m=method, p=session_payload, meas=measurements, diag=diagnosis_payload: m(
                                session_payload=p,
                                measurements=meas,
                                diagnosis_payload=diag,
                            ),
                            lambda m=method, p=session_payload, meas=measurements: m(
                                session_payload=p,
                                measurements=meas,
                            ),
                            lambda m=method, p=session_payload: m(session_payload=p),
                            lambda m=method, p=session_payload: m(dict(p)),
                        ])

                    for caller in call_patterns:
                        try:
                            result = caller()
                            qr_path = self._extract_generated_artifact_path(
                                result,
                                preferred_keys=("qr_path", "path", "file_path"),
                            )
                            if qr_path:
                                break
                        except Exception:
                            continue

                    if qr_path:
                        break
        except Exception:
            pass

        return qr_path

    def _prepare_report(self) -> str:
        report_path = ""
        session_payload = dict(self._payload or {})
        measurements = session_payload.get("measurements", {})
        diagnosis_payload = session_payload.get("diagnosis", {})

        if not isinstance(measurements, Mapping):
            measurements = {}
        if not isinstance(diagnosis_payload, Mapping):
            diagnosis_payload = {}

        try:
            report_service = self.services.get("report_service") or self.services.get("report")
            if report_service is not None:
                for method_name in (
                    "generate_report",
                    "generate_current_session_report",
                    "create_report",
                    "build_report",
                    "generate_pdf_report",
                    "create_pdf_report",
                    "export_report",
                ):
                    method = getattr(report_service, method_name, None)
                    if not callable(method):
                        continue

                    call_patterns = []
                    if method_name == "generate_current_session_report":
                        call_patterns.append(lambda m=method: m(persist_to_database=True))
                        call_patterns.append(lambda m=method: m())
                    else:
                        call_patterns.extend([
                            lambda m=method, p=session_payload, meas=measurements, diag=diagnosis_payload: m(
                                session_payload=p,
                                measurements=meas,
                                diagnosis_payload=diag,
                                attach_to_app_state=True,
                                persist_to_database=True,
                            ),
                            lambda m=method, p=session_payload, meas=measurements, diag=diagnosis_payload: m(
                                session_payload=p,
                                measurements=meas,
                                diagnosis_payload=diag,
                            ),
                            lambda m=method, p=session_payload: m(session_payload=p),
                            lambda m=method, p=session_payload: m(dict(p)),
                        ])

                    for caller in call_patterns:
                        try:
                            result = caller()
                            report_path = self._extract_generated_artifact_path(
                                result,
                                preferred_keys=("report_path", "path", "file_path"),
                            )
                            if report_path:
                                break
                        except Exception:
                            continue

                    if report_path:
                        break
        except Exception:
            pass

        self._report_path = report_path
        self._payload["report_path"] = self._report_path
        self._persist_payload()
        return self._report_path

    def _persist_payload(self) -> None:
        try:
            session_service = self.services.get("session_service") or self.services.get("session")
            if session_service is not None:
                for method_name in (
                    "set_qr_path",
                    "update_qr_path",
                    "set_report_path",
                    "update_report_path",
                    "set_results_payload",
                    "update_results_payload",
                ):
                    method = getattr(session_service, method_name, None)
                    if callable(method):
                        try:
                            if "qr_path" in method_name and self._qr_path:
                                method(self._qr_path)
                            elif "report_path" in method_name and self._report_path:
                                method(self._report_path)
                            elif "payload" in method_name:
                                method(dict(self._payload))
                        except Exception:
                            continue
        except Exception:
            pass

        try:
            if self.app_state is not None:
                if self._qr_path and hasattr(self.app_state, "qr_path"):
                    setattr(self.app_state, "qr_path", self._qr_path)
                if self._report_path and hasattr(self.app_state, "report_path"):
                    setattr(self.app_state, "report_path", self._report_path)
                if hasattr(self.app_state, "results_payload"):
                    setattr(self.app_state, "results_payload", dict(self._payload))
        except Exception:
            pass

    # =========================================================================
    # UI application
    # =========================================================================

    def _apply_payload_to_ui(self) -> None:
        measurements = self._payload.get("measurements", {})
        if not isinstance(measurements, Mapping):
            measurements = {}

        available_count = 0
        for key in ("temperature", "spo2", "pulse_rate", "respiratory_rate", "weight", "height", "bmi"):
            if measurements.get(key) not in (None, ""):
                available_count += 1

        self._apply_mode_pill()

        qr_ready = bool(self._qr_path and Path(self._qr_path).exists())
        report_ready = bool(self._report_path and Path(self._report_path).exists())
        qr_accent = "#42E393" if qr_ready else "#FFD25E"

        self.qr_pill.setText("QR Ready" if qr_ready else "QR Pending")
        self.report_pill.setText("Report Ready" if report_ready else "Report Pending")
        self._apply_pill_style(self.qr_pill, qr_accent)
        self._apply_pill_style(self.report_pill, "#42E393" if report_ready else "#FFD25E")

        self.scan_chip.setText("Ready to Scan" if qr_ready else "Generate to Scan")
        self.source_chip.setText("Demo Session" if self._mode == MODE_DEMO else "Hardware Session")
        self.hint_chip.setText("Show the full code to the camera")
        self._apply_header_chip_style(self.scan_chip, qr_accent)
        self._apply_header_chip_style(self.source_chip, "#67D8FF" if self._mode == MODE_DEMO else "#39D8FF")
        self._apply_header_chip_style(self.hint_chip, "#39D8FF")

        self.summary_banner.setText(
            "Display this QR for quick session handoff. When the phone is on the same Wi-Fi as the kiosk, the scan opens the session viewer page."
        )

        preview_subtitle = (
            "Hold the phone steadily over the full QR code. Refresh QR if the session or report changes."
            if qr_ready
            else "No active QR image is available yet. Use Refresh QR to build one from the current session payload."
        )
        self.preview_card.set_payload(
            qr_path=self._qr_path,
            status_text="QR Ready" if qr_ready else "QR Pending",
            subtitle=preview_subtitle,
            accent_hex=qr_accent,
        )

        self.mode_line.setText(f"Mode: {'Demo' if self._mode == MODE_DEMO else 'Hardware'}")
        self.metrics_line.setText(f"Captured metrics: {available_count}")
        self.report_line.setText(f"Report path: {self._report_path if self._report_path else 'Not prepared'}")
        self.qr_line.setText(f"QR path: {self._qr_path if self._qr_path else 'Not prepared'}")

        self.session_detail.setText(
            "The QR references the currently active session context. Refresh or regenerate after reports or session values are updated."
        )

        self._set_button_accent(self.refresh_button, "#39D8FF")
        self._set_button_accent(self.results_button, "#67D8FF")
        self._set_button_accent(self.new_checkup_button, "#FFD25E")
        self._set_button_accent(self.bottom_consult_button, "#42E393" if qr_ready else "#39D8FF")
        self.action_row.setMinimumHeight(52)
        self.action_row.setMaximumHeight(56)
        self._set_button_accent(self.regenerate_button, "#FFD25E" if not qr_ready else "#39D8FF")
        self._set_button_accent(self.report_button, "#67D8FF" if not report_ready else "#42E393")
        self._set_button_accent(self.consult_button, "#42E393" if qr_ready else "#39D8FF")

    def _apply_mode_pill(self) -> None:
        if self._mode == MODE_DEMO:
            self.mode_pill.setText("Demo Mode")
            self._apply_pill_style(self.mode_pill, "#67D8FF")
        else:
            self.mode_pill.setText("Hardware Mode")
            self._apply_pill_style(self.mode_pill, "#39D8FF")

    def _apply_pill_style(self, label: QLabel, accent_hex: str) -> None:
        accent = QColor(accent_hex)
        label.setStyleSheet(
            f"""
            QLabel {{
                color: #EEF9FF;
                font-size: 10px;
                font-weight: 700;
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.34);
                border-radius: 14px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.15);
                padding: 6px 10px;
            }}
            """
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

    # =========================================================================
    # Actions / navigation
    # =========================================================================

    def _handle_back_clicked(self) -> None:
        if self._navigate_to(SCREEN_RESULTS):
            return
        self.back_requested.emit()

    def _handle_new_checkup_clicked(self) -> None:
        if self._navigate_to(SCREEN_MEASURING):
            self.retake_requested.emit()
            return
        self.retake_requested.emit()

    def _handle_consult_clicked(self) -> None:
        payload = dict(self._payload)
        if self._navigate_to(SCREEN_CONSULT):
            self.consult_requested.emit(payload)
            return
        self.consult_requested.emit(payload)

    def _handle_report_clicked(self) -> None:
        self._prepare_report()
        self._apply_payload_to_ui()

        payload = dict(self._payload)
        payload["report_path"] = self._report_path
        self.report_requested.emit(payload)

    def _handle_regenerate_clicked(self) -> None:
        self._qr_path = self._generate_qr_from_payload(self._payload)
        self._payload["qr_path"] = self._qr_path
        self._persist_payload()
        self._apply_payload_to_ui()
        self.qr_regenerated.emit(dict(self._payload))

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
    # Paint
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
            "mode": self._mode,
            "qr_path": self._qr_path,
            "report_path": self._report_path,
            "payload_keys": list(self._payload.keys()),
            "background_path": self._background_path,
        }


# Backward-compatible alias expected by some loaders
QrScreen = QRScreen
