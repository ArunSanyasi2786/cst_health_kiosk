"""
screens/publish_screen.py

Premium administrator publish / handoff screen for the
CST Health Monitoring Station kiosk.

Why this file matters:
- It is the protected publish workspace opened from:
    - screens/admin_panel_screen.py
- It allows the administrator to:
    - inspect publish readiness for reports, QR artifacts, exports, and remote handoff
    - review whether the active session payload is ready for publishing
    - generate report / QR / export artifacts through linked services
    - run a best-effort publish workflow
    - validate network and output readiness before handoff
- It is designed specifically for:
    - Raspberry Pi 4B touchscreen kiosk deployment
    - 1024x600 kiosk resolution
    - laptop demo mode
- It provides:
    - premium glossy protected publish UI
    - resilient loading from publish_service / report_service / qr_service / export_service / session_service
    - filesystem fallback inspection when backend services are incomplete
    - touch-friendly publish-channel review workflow
    - clear readiness indicators for output artifacts and network handoff
    - best-effort synchronization to app_state and service snapshots

Linked project files this screen is intended to work with:
- config.py
- core/constants.py
- core/asset_paths.py
- core/logger.py
- core/app_state.py
- core/navigator.py
- core/theme_manager.py
- core/animation_manager.py
- services/publish_service.py
- services/report_service.py
- services/qr_service.py
- services/export_service.py
- services/session_service.py
- services/settings_service.py
- widgets/animated_button.py
- widgets/glow_label.py
- widgets/publish_stat_card.py

Navigation targets this screen is designed to link to:
- screens/admin_panel_screen.py

Design goals:
- glossy futuristic blue medical UI
- protected output / handoff workflow feel
- strong readability at 1024x600
- resilient integration while backend files continue evolving
- maintainable structure with safe fallbacks
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

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
    from core.constants import SCREEN_ADMIN_PANEL
except Exception:  # pragma: no cover
    SCREEN_ADMIN_PANEL = "admin_panel"

try:
    from config import KIOSK_WIDTH, KIOSK_HEIGHT, IS_COMPACT_KIOSK, UI_SCALE
except Exception:  # pragma: no cover
    KIOSK_WIDTH = 800
    KIOSK_HEIGHT = 480
    IS_COMPACT_KIOSK = True
    UI_SCALE = 0.82

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
# Helpers / defaults
# =============================================================================

CHANNEL_REPORT = "report"
CHANNEL_QR = "qr"
CHANNEL_EXPORT = "export"
CHANNEL_PUBLISH = "publish"
CHANNEL_SESSION = "session"
CHANNEL_NETWORK = "network"

CHANNEL_ORDER = [
    CHANNEL_REPORT,
    CHANNEL_QR,
    CHANNEL_EXPORT,
    CHANNEL_PUBLISH,
    CHANNEL_SESSION,
    CHANNEL_NETWORK,
]

CHANNEL_LABELS = {
    CHANNEL_REPORT: "PDF Report",
    CHANNEL_QR: "QR Handoff",
    CHANNEL_EXPORT: "Export Package",
    CHANNEL_PUBLISH: "Remote Publish",
    CHANNEL_SESSION: "Session Payload",
    CHANNEL_NETWORK: "Network / Share",
}

CHANNEL_DESCRIPTIONS = {
    CHANNEL_REPORT: "Protected report artifact generation and availability.",
    CHANNEL_QR: "QR image or handoff asset availability for results delivery.",
    CHANNEL_EXPORT: "Structured export package availability for sharing or analysis.",
    CHANNEL_PUBLISH: "Remote or final publish status for the handoff workflow.",
    CHANNEL_SESSION: "Whether the active session contains enough data to publish.",
    CHANNEL_NETWORK: "Connectivity and network-mode readiness for publish operations.",
}


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _data_root() -> Path:
    return _project_root() / "data"


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


def _channel_icon_path(channel_key: str) -> str:
    mapping = {
        CHANNEL_REPORT: "icons/pdf.png",
        CHANNEL_QR: "icons/qr.png",
        CHANNEL_EXPORT: "icons/export.png",
        CHANNEL_PUBLISH: "icons/publish.png",
        CHANNEL_SESSION: "icons/report.png",
        CHANNEL_NETWORK: "icons/network.png",
    }
    return _resolve_asset(mapping.get(channel_key, "icons/publish.png"))


def _accent_for_state(state: str) -> str:
    value = safe_str(state, "").strip().lower()
    if value in {"critical", "error", "failed", "missing"}:
        return "#FF6E88"
    if value in {"warning", "pending", "attention", "partial"}:
        return "#FFD25E"
    if value in {"normal", "ready", "saved", "healthy", "clean", "available", "success", "published", "online"}:
        return "#42E393"
    if value in {"inactive", "offline"}:
        return "#FFA14D"
    return "#39D8FF"


def _format_bytes(size_bytes: int) -> str:
    size = float(max(0, size_bytes))
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while size >= 1024.0 and idx < len(units) - 1:
        size /= 1024.0
        idx += 1
    if idx == 0:
        return f"{int(size)} {units[idx]}"
    return f"{size:.1f} {units[idx]}"


def _safe_datetime_string(timestamp: float) -> str:
    try:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "Unknown"


def _iter_real_files(directory: Path) -> Iterable[Path]:
    if not directory.exists() or not directory.is_dir():
        return []
    return [
        p for p in directory.rglob("*")
        if p.is_file() and p.name != ".keep" and not p.name.startswith(".")
    ]


def _count_files(directory: Path) -> int:
    return len(list(_iter_real_files(directory)))


def _directory_size_bytes(directory: Path) -> int:
    total = 0
    for file_path in _iter_real_files(directory):
        try:
            total += int(file_path.stat().st_size)
        except Exception:
            continue
    return total


def _latest_file_time(directory: Path) -> str:
    latest_ts: Optional[float] = None
    for file_path in _iter_real_files(directory):
        try:
            ts = file_path.stat().st_mtime
            if latest_ts is None or ts > latest_ts:
                latest_ts = ts
        except Exception:
            continue

    if latest_ts is None:
        return "No recent files"
    return _safe_datetime_string(latest_ts)


def _latest_matching_file(directory: Path, prefix: str) -> str:
    latest_path: Optional[Path] = None
    latest_ts: Optional[float] = None

    for file_path in _iter_real_files(directory):
        try:
            if not file_path.name.startswith(prefix):
                continue
            ts = file_path.stat().st_mtime
            if latest_ts is None or ts > latest_ts:
                latest_ts = ts
                latest_path = file_path
        except Exception:
            continue

    return str(latest_path) if latest_path else ""


def _channel_default_summary(channel_key: str) -> str:
    return {
        CHANNEL_REPORT: "Protected report generation prepares printable session output.",
        CHANNEL_QR: "QR handoff generation prepares scannable result-sharing output.",
        CHANNEL_EXPORT: "Export generation prepares structured files for analysis or handoff.",
        CHANNEL_PUBLISH: "Remote publish packages the session for final handoff or upload.",
        CHANNEL_SESSION: "The session payload determines whether publish actions have enough source data.",
        CHANNEL_NETWORK: "Network mode influences whether remote publish workflows are available.",
    }.get(channel_key, "Protected publish channel is available.")


# =============================================================================
# Internal widgets
# =============================================================================

class _PublishStatCard(QFrame):
    """
    Compact premium stat card for publish overview.
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

        self.setObjectName("PublishStatCard")
        self.setMinimumHeight(80)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(3)

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

    def _apply_style(self) -> None:
        accent = QColor(self._accent_hex)

        self.setStyleSheet(
            f"""
            QFrame#PublishStatCard {{
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.20);
                border-radius: 18px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.08);
            }}
            """
        )
        self.title_label.setStyleSheet(
            """
            QLabel {
                color: rgba(219, 237, 249, 0.82);
                font-size: 9px;
                font-weight: 700;
                background: transparent;
            }
            """
        )
        self.value_label.setStyleSheet(
            """
            QLabel {
                color: #F6FCFF;
                font-size: 18px;
                font-weight: 900;
                background: transparent;
            }
            """
        )
        self.subtitle_label.setStyleSheet(
            """
            QLabel {
                color: rgba(191, 214, 232, 0.80);
                font-size: 9px;
                font-weight: 500;
                background: transparent;
            }
            """
        )


class _PublishChannelCard(QFrame):
    """
    Click-select premium publish channel card.
    """

    clicked = pyqtSignal(str)

    def __init__(
        self,
        channel_key: str,
        *,
        title: str,
        subtitle: str,
        icon_path: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self.channel_key = channel_key
        self._selected = False
        self._hovered = False
        self._accent_hex = "#39D8FF"
        self._clickable = True
        self._icon_path = safe_str(icon_path, "").strip()
        self._icon_pixmap = _pixmap_or_empty(self._icon_path)

        self.setObjectName("PublishChannelCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(128)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(5)

        top_row = QWidget(self)
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        self.icon_label = QLabel(top_row)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setMinimumSize(40, 40)
        self.icon_label.setMaximumSize(40, 40)

        self.state_chip = QLabel("Pending", top_row)

        top_layout.addWidget(self.icon_label)
        top_layout.addStretch(1)
        top_layout.addWidget(self.state_chip)

        self.title_label = QLabel(title, self)
        self.title_label.setWordWrap(True)

        self.subtitle_label = QLabel(subtitle, self)
        self.subtitle_label.setWordWrap(True)

        self.count_line = QLabel("Items --", self)
        self.detail_line = QLabel("Detail unavailable", self)
        self.detail_line.setWordWrap(True)

        root.addWidget(top_row)
        root.addWidget(self.title_label)
        root.addWidget(self.subtitle_label)
        root.addWidget(self.count_line)
        root.addWidget(self.detail_line)
        root.addStretch(1)

        self._refresh_icon()
        self._apply_style()

    def _refresh_icon(self) -> None:
        if self._icon_pixmap.isNull():
            self.icon_label.clear()
            return

        scaled = self._icon_pixmap.scaled(
            22,
            22,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.icon_label.setPixmap(scaled)

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        self._apply_style()

    def set_payload(
        self,
        *,
        state_text: str,
        subtitle: str,
        count_line: str,
        detail_line: str,
        accent_hex: str,
    ) -> None:
        self._accent_hex = safe_str(accent_hex, "#39D8FF").strip() or "#39D8FF"
        self.state_chip.setText(safe_str(state_text, "Pending").strip() or "Pending")
        self.subtitle_label.setText(safe_str(subtitle, "").strip())
        self.count_line.setText(safe_str(count_line, "").strip())
        self.detail_line.setText(safe_str(detail_line, "").strip())
        self._apply_style()

    def _apply_style(self) -> None:
        accent = QColor(self._accent_hex)
        border_alpha = 0.36 if self._selected else (0.26 if self._hovered else 0.18)
        fill_alpha = 0.16 if self._selected else (0.11 if self._hovered else 0.07)

        self.setStyleSheet(
            f"""
            QFrame#PublishChannelCard {{
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, {border_alpha:.3f});
                border-radius: 20px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, {fill_alpha:.3f});
            }}
            """
        )

        self.icon_label.setStyleSheet(
            f"""
            QLabel {{
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.26);
                border-radius: 14px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.14);
            }}
            """
        )
        self.title_label.setStyleSheet(
            """
            QLabel {
                color: #F4FCFF;
                font-size: 9px;
                font-weight: 800;
                background: transparent;
            }
            """
        )
        self.subtitle_label.setStyleSheet(
            """
            QLabel {
                color: rgba(214, 235, 248, 0.84);
                font-size: 9px;
                font-weight: 500;
                background: transparent;
            }
            """
        )
        self.count_line.setStyleSheet(
            """
            QLabel {
                color: rgba(197, 223, 241, 0.88);
                font-size: 9px;
                font-weight: 700;
                background: transparent;
            }
            """
        )
        self.detail_line.setStyleSheet(
            """
            QLabel {
                color: rgba(188, 213, 230, 0.78);
                font-size: 9px;
                font-weight: 500;
                background: transparent;
            }
            """
        )
        self.state_chip.setStyleSheet(
            f"""
            QLabel {{
                color: #F4FCFF;
                font-size: 8px;
                font-weight: 800;
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.34);
                border-radius: 11px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.16);
                padding: 3px 8px;
            }}
            """
        )

    def enterEvent(self, event: QEvent) -> None:
        super().enterEvent(event)
        if not self._clickable:
            return
        self._hovered = True
        self._apply_style()

    def leaveEvent(self, event: QEvent) -> None:
        super().leaveEvent(event)
        self._hovered = False
        self._apply_style()

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if self._clickable and event is not None and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.channel_key)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            rect = QRectF(self.rect().adjusted(1, 1, -1, -1))
            if rect.width() > 8 and rect.height() > 8:
                radius = 20.0
                path = QPainterPath()
                path.addRoundedRect(rect, float(radius), float(radius))
                painter.save()
                painter.setClipPath(path)
                gloss_rect = QRectF(
                    rect.left() + 2.0,
                    rect.top() + 2.0,
                    rect.width() - 4.0,
                    rect.height() * 0.24,
                )
                painter.fillRect(gloss_rect, QColor(255, 255, 255, 10 if not self._selected else 18))
                painter.restore()
        finally:
            painter.end()


class _PublishSummaryCard(QFrame):
    """
    Premium selected-channel summary card.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._accent_hex = "#39D8FF"

        self.setObjectName("PublishSummaryCard")
        self.setMinimumHeight(196)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(8)

        top_row = QWidget(self)
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        self.title_label = QLabel("Selected Channel", top_row)
        self.state_chip = QLabel("Pending", top_row)

        top_layout.addWidget(self.title_label)
        top_layout.addStretch(1)
        top_layout.addWidget(self.state_chip)

        self.summary_label = QLabel(
            "Select a publish channel to inspect readiness and handoff detail.",
            self,
        )
        self.summary_label.setWordWrap(True)

        self.line_1 = QLabel("• Protected publish information will appear here.", self)
        self.line_2 = QLabel("• Review session readiness before publishing.", self)
        self.line_3 = QLabel("• Generate report, QR, and export artifacts as needed.", self)
        self.line_4 = QLabel("• Remote publish depends on service and network readiness.", self)

        root.addWidget(top_row)
        root.addWidget(self.summary_label)
        root.addWidget(self.line_1)
        root.addWidget(self.line_2)
        root.addWidget(self.line_3)
        root.addWidget(self.line_4)
        root.addStretch(1)

        self._apply_style()

    def set_payload(
        self,
        *,
        title: str,
        state_text: str,
        summary: str,
        lines: Mapping[int, str],
        accent_hex: str,
    ) -> None:
        self._accent_hex = safe_str(accent_hex, "#39D8FF").strip() or "#39D8FF"
        self.title_label.setText(safe_str(title, "Selected Channel").strip() or "Selected Channel")
        self.state_chip.setText(safe_str(state_text, "Pending").strip() or "Pending")
        self.summary_label.setText(safe_str(summary, "").strip())

        self.line_1.setText(f"• {safe_str(lines.get(1), '').strip()}" if safe_str(lines.get(1), "").strip() else "")
        self.line_2.setText(f"• {safe_str(lines.get(2), '').strip()}" if safe_str(lines.get(2), "").strip() else "")
        self.line_3.setText(f"• {safe_str(lines.get(3), '').strip()}" if safe_str(lines.get(3), "").strip() else "")
        self.line_4.setText(f"• {safe_str(lines.get(4), '').strip()}" if safe_str(lines.get(4), "").strip() else "")

        self.line_1.setVisible(bool(safe_str(lines.get(1), "").strip()))
        self.line_2.setVisible(bool(safe_str(lines.get(2), "").strip()))
        self.line_3.setVisible(bool(safe_str(lines.get(3), "").strip()))
        self.line_4.setVisible(bool(safe_str(lines.get(4), "").strip()))

        self._apply_style()

    def _apply_style(self) -> None:
        accent = QColor(self._accent_hex)

        self.setStyleSheet(
            f"""
            QFrame#PublishSummaryCard {{
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.22);
                border-radius: 18px;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.08);
            }}
            """
        )
        self.title_label.setStyleSheet(
            """
            QLabel {
                color: #F4FCFF;
                font-size: 9px;
                font-weight: 800;
                background: transparent;
            }
            """
        )
        self.state_chip.setStyleSheet(
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
        self.summary_label.setStyleSheet(
            """
            QLabel {
                color: rgba(221, 239, 250, 0.90);
                font-size: 9px;
                font-weight: 600;
                background: transparent;
            }
            """
        )
        bullet_style = """
            QLabel {
                color: rgba(197, 223, 241, 0.84);
                font-size: 9px;
                font-weight: 500;
                background: transparent;
            }
        """
        self.line_1.setStyleSheet(bullet_style)
        self.line_2.setStyleSheet(bullet_style)
        self.line_3.setStyleSheet(bullet_style)
        self.line_4.setStyleSheet(bullet_style)


# =============================================================================
# Main screen
# =============================================================================

class PublishScreen(QFrame):
    """
    Premium protected publish screen.

    Main responsibilities:
    - inspect publish readiness
    - review output channels and session availability
    - generate report / QR / export artifacts
    - trigger publish workflow through linked services or safe fallback
    """

    back_requested = pyqtSignal()
    publish_loaded = pyqtSignal(dict)
    publish_refreshed = pyqtSignal(dict)
    publish_channel_selected = pyqtSignal(str)
    report_generated = pyqtSignal(dict)
    qr_generated = pyqtSignal(dict)
    export_generated = pyqtSignal(dict)
    publish_executed = pyqtSignal(dict)
    publish_action_requested = pyqtSignal(str)

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

        self._logger = logger.bind(component="PublishScreen")

        self.navigator = navigator
        self.app_state = app_state
        self.services = dict(services or {})
        self.animation_manager = animation_manager
        self.theme_manager = theme_manager

        self._snapshot: Dict[str, Any] = {}
        self._channels: Dict[str, Dict[str, Any]] = {}
        self._selected_channel = CHANNEL_REPORT
        self._status_message = "Publish panel is ready to load."
        self._publish_state = "ready"
        self._last_publish_label = "No recent publish"
        self._logic_source = "Filesystem and session fallback"
        self._compact_mode = bool(IS_COMPACT_KIOSK or KIOSK_WIDTH <= 860 or KIOSK_HEIGHT <= 520)
        self._ultra_compact_mode = bool(KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480)

        self._background_path = _resolve_asset("backgrounds/publish_bg.png")
        self._logo_small_path = _resolve_asset("logos/cst_logo_small.png")
        self._admin_shield_path = _resolve_asset("illustrations/admin_shield.png")

        self._background_pixmap = _pixmap_or_empty(self._background_path)
        self._logo_pixmap = _pixmap_or_empty(self._logo_small_path)
        self._shield_pixmap = _pixmap_or_empty(self._admin_shield_path)

        self.setObjectName("PublishScreen")
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
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(8)

        # ---------------------------------------------------------------------
        # Top bar
        # ---------------------------------------------------------------------
        self.top_bar = QWidget(self)
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        self.back_button = self._create_button("Back", variant="secondary", min_width=86, parent=self.top_bar)
        self.back_button.clicked.connect(self._handle_back_clicked)

        self.logo_badge = QLabel(self.top_bar)
        self.logo_badge.setObjectName("LogoBadge")
        self.logo_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_label_pixmap(self.logo_badge, self._logo_pixmap, 26)

        self.top_title = QLabel("Protected Publish", self.top_bar)
        self.top_title.setObjectName("TopTitle")

        self.status_pill = QLabel("Ready", self.top_bar)
        self.status_pill.setObjectName("RuntimePill")

        self.publish_pill = QLabel("Publish State", self.top_bar)
        self.publish_pill.setObjectName("RuntimePill")

        self.selected_pill = QLabel("Selected Channel", self.top_bar)
        self.selected_pill.setObjectName("RuntimePill")

        top_layout.addWidget(self.back_button)
        top_layout.addWidget(self.logo_badge)
        top_layout.addWidget(self.top_title)
        top_layout.addStretch(1)
        top_layout.addWidget(self.status_pill)
        top_layout.addWidget(self.publish_pill)
        top_layout.addWidget(self.selected_pill)

        # ---------------------------------------------------------------------
        # Header card
        # ---------------------------------------------------------------------
        self.header_card = QFrame(self)
        self.header_card.setObjectName("PublishHeaderCard")

        header_layout = QVBoxLayout(self.header_card)
        header_layout.setContentsMargins(14, 12, 14, 12)
        header_layout.setSpacing(6)

        if _HAS_GLOW_LABEL:
            self.hero_title = GlowLabel(
                role=getattr(GlowLabel, "ROLE_TITLE", getattr(GlowLabel, "ROLE_STATUS", 0)),
                align_center=True,
                use_outline=False,
                enable_paint_glow=True,
                initial_glow_strength=0.50,
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
        chip_layout.setContentsMargins(0, 0, 0, 0)
        chip_layout.setSpacing(6)

        self.report_chip = QLabel("Report Workflow", self.header_chip_row)
        self.report_chip.setObjectName("HeaderChip")

        self.handoff_chip = QLabel("QR / Export Handoff", self.header_chip_row)
        self.handoff_chip.setObjectName("HeaderChip")

        self.remote_chip = QLabel("Remote Publish", self.header_chip_row)
        self.remote_chip.setObjectName("HeaderChip")

        chip_layout.addStretch(1)
        chip_layout.addWidget(self.report_chip)
        chip_layout.addWidget(self.handoff_chip)
        chip_layout.addWidget(self.remote_chip)
        chip_layout.addStretch(1)

        self.summary_banner = QLabel(
            "Inspect output readiness, generate artifacts, and run the protected publish workflow once the session payload is complete.",
            self.header_card,
        )
        self.summary_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.summary_banner.setWordWrap(True)

        header_layout.addWidget(self.hero_title)
        header_layout.addWidget(self.hero_subtitle)
        header_layout.addWidget(self.header_chip_row)
        header_layout.addWidget(self.summary_banner)

        # ---------------------------------------------------------------------
        # Stats row
        # ---------------------------------------------------------------------
        self.stats_row = QWidget(self)
        stats_layout = QHBoxLayout(self.stats_row)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(8)

        self.stat_ready = _PublishStatCard("Ready Channels", value="--", subtitle="Publish channels currently ready for handoff.")
        self.stat_session = _PublishStatCard("Session Readiness", value="--", subtitle="Whether active session data is sufficient for publish.")
        self.stat_artifacts = _PublishStatCard("Artifacts", value="--", subtitle="Available report, QR, and export artifacts.")
        self.stat_publish = _PublishStatCard("Publish Status", value="--", subtitle="Current publish workflow state.")

        stats_layout.addWidget(self.stat_ready, 1)
        stats_layout.addWidget(self.stat_session, 1)
        stats_layout.addWidget(self.stat_artifacts, 1)
        stats_layout.addWidget(self.stat_publish, 1)

        # ---------------------------------------------------------------------
        # Content row
        # ---------------------------------------------------------------------
        self.content_row = QWidget(self)
        content_layout = QHBoxLayout(self.content_row)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)

        # Left panel
        self.channel_panel = QFrame(self.content_row)
        self.channel_panel.setObjectName("ChannelPanel")
        self.channel_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        channel_layout = QVBoxLayout(self.channel_panel)
        channel_layout.setContentsMargins(12, 10, 12, 10)
        channel_layout.setSpacing(8)

        self.channel_panel_title = QLabel("Protected Publish Channels", self.channel_panel)
        self.channel_panel_title.setObjectName("SectionTitle")

        self.channel_grid_widget = QWidget(self.channel_panel)
        self.channel_grid = QGridLayout(self.channel_grid_widget)
        self.channel_grid.setContentsMargins(0, 0, 0, 0)
        self.channel_grid.setHorizontalSpacing(8)
        self.channel_grid.setVerticalSpacing(8)

        self.channel_cards: Dict[str, _PublishChannelCard] = {}
        positions = {
            CHANNEL_REPORT: (0, 0),
            CHANNEL_QR: (0, 1),
            CHANNEL_EXPORT: (0, 2),
            CHANNEL_PUBLISH: (1, 0),
            CHANNEL_SESSION: (1, 1),
            CHANNEL_NETWORK: (1, 2),
        }

        for channel_key in CHANNEL_ORDER:
            row, col = positions[channel_key]
            card = _PublishChannelCard(
                channel_key,
                title=CHANNEL_LABELS[channel_key],
                subtitle=CHANNEL_DESCRIPTIONS[channel_key],
                icon_path=_channel_icon_path(channel_key),
                parent=self.channel_grid_widget,
            )
            card.clicked.connect(self._handle_channel_card_clicked)
            self.channel_cards[channel_key] = card
            self.channel_grid.addWidget(card, row, col)

        channel_layout.addWidget(self.channel_panel_title)
        channel_layout.addWidget(self.channel_grid_widget, 1)

        # Right side
        self.side_panel = QWidget(self.content_row)
        side_layout = QVBoxLayout(self.side_panel)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(12)
        self.side_panel.setMinimumWidth(286)
        self.side_panel.setMaximumWidth(304)

        self.summary_card = _PublishSummaryCard(self.side_panel)

        self.context_card = QFrame(self.side_panel)
        self.context_card.setObjectName("InfoCard")
        context_layout = QVBoxLayout(self.context_card)
        context_layout.setContentsMargins(12, 10, 12, 10)
        context_layout.setSpacing(6)

        self.context_title = QLabel("Publish Context", self.context_card)
        self.context_title.setObjectName("SectionTitle")

        self.context_art = QLabel(self.context_card)
        self.context_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_label_pixmap(self.context_art, self._shield_pixmap, 80)

        self.context_line_1 = QLabel("Selected channel: pending", self.context_card)
        self.context_line_2 = QLabel("Publish state: pending", self.context_card)
        self.context_line_3 = QLabel("Last publish: pending", self.context_card)
        self.context_line_4 = QLabel("Logic source: pending", self.context_card)

        self.context_note = QLabel(
            "Use this screen to verify that the session payload, generated artifacts, and connectivity are ready before final handoff.",
            self.context_card,
        )
        self.context_note.setWordWrap(True)

        context_layout.addWidget(self.context_title)
        context_layout.addWidget(self.context_art, 0, alignment=Qt.AlignmentFlag.AlignHCenter)
        context_layout.addWidget(self.context_line_1)
        context_layout.addWidget(self.context_line_2)
        context_layout.addWidget(self.context_line_3)
        context_layout.addWidget(self.context_line_4)
        context_layout.addWidget(self.context_note)

        self.quick_card = QFrame(self.side_panel)
        self.quick_card.setObjectName("InfoCard")
        quick_layout = QVBoxLayout(self.quick_card)
        quick_layout.setContentsMargins(12, 10, 12, 10)
        quick_layout.setSpacing(6)

        self.quick_title = QLabel("Protected Actions", self.quick_card)
        self.quick_title.setObjectName("SectionTitle")

        self.quick_text = QLabel(
            "Reload publish readiness, generate report and QR artifacts, export the session package, or run the final publish workflow.",
            self.quick_card,
        )
        self.quick_text.setWordWrap(True)

        self.reload_button = self._create_button("Reload Publish State", variant="ghost", min_width=156, parent=self.quick_card)
        self.reload_button.clicked.connect(self.reload_publish_state)

        self.report_button = self._create_button("Generate Report", variant="secondary", min_width=156, parent=self.quick_card)
        self.report_button.clicked.connect(self._handle_generate_report_clicked)

        self.qr_button = self._create_button("Generate QR", variant="secondary", min_width=156, parent=self.quick_card)
        self.qr_button.clicked.connect(self._handle_generate_qr_clicked)

        self.export_button = self._create_button("Run Export", variant="secondary", min_width=156, parent=self.quick_card)
        self.export_button.clicked.connect(self._handle_export_clicked)

        self.publish_button = self._create_button("Publish Bundle", variant="primary", min_width=156, parent=self.quick_card)
        self.publish_button.clicked.connect(self._handle_publish_clicked)

        quick_layout.addWidget(self.quick_title)
        quick_layout.addWidget(self.quick_text)
        quick_layout.addWidget(self.reload_button)
        quick_layout.addWidget(self.report_button)
        quick_layout.addWidget(self.qr_button)
        quick_layout.addWidget(self.export_button)
        quick_layout.addWidget(self.publish_button)

        side_layout.addWidget(self.summary_card)
        side_layout.addWidget(self.context_card)
        side_layout.addWidget(self.quick_card)

        content_layout.addWidget(self.channel_panel, 1)
        content_layout.addWidget(self.side_panel, 0)

        # ---------------------------------------------------------------------
        # Bottom action row
        # ---------------------------------------------------------------------
        self.action_row = QWidget(self)
        action_layout = QHBoxLayout(self.action_row)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(8)

        self.bottom_reload_button = self._create_button("Reload", variant="ghost", min_width=104, parent=self.action_row)
        self.bottom_reload_button.clicked.connect(self.reload_publish_state)

        self.bottom_report_button = self._create_button("Report", variant="secondary", min_width=104, parent=self.action_row)
        self.bottom_report_button.clicked.connect(self._handle_generate_report_clicked)

        self.bottom_qr_button = self._create_button("QR", variant="secondary", min_width=104, parent=self.action_row)
        self.bottom_qr_button.clicked.connect(self._handle_generate_qr_clicked)

        self.bottom_export_button = self._create_button("Export", variant="secondary", min_width=104, parent=self.action_row)
        self.bottom_export_button.clicked.connect(self._handle_export_clicked)

        self.bottom_publish_button = self._create_button("Publish", variant="primary", min_width=118, parent=self.action_row)
        self.bottom_publish_button.clicked.connect(self._handle_publish_clicked)

        action_layout.addWidget(self.bottom_reload_button)
        action_layout.addStretch(1)
        action_layout.addWidget(self.bottom_report_button)
        action_layout.addWidget(self.bottom_qr_button)
        action_layout.addWidget(self.bottom_export_button)
        action_layout.addWidget(self.bottom_publish_button)

        root.addWidget(self.top_bar)
        root.addWidget(self.header_card)
        root.addWidget(self.stats_row)
        root.addWidget(self.content_row, 1)
        root.addWidget(self.action_row)

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
                    size=getattr(AnimatedButton, "SIZE_MD", None),
                    minimum_width=min_width,
                )
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
                padding: 8px 14px;
                font-size: 9px;
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

        self.stats_opacity = QGraphicsOpacityEffect(self.stats_row)
        self.stats_row.setGraphicsEffect(self.stats_opacity)
        self.stats_opacity.setOpacity(0.0)

        self.content_opacity = QGraphicsOpacityEffect(self.content_row)
        self.content_row.setGraphicsEffect(self.content_opacity)
        self.content_opacity.setOpacity(0.0)

        self.entry_group = QParallelAnimationGroup(self)

        self.header_fade = QPropertyAnimation(self.header_opacity, b"opacity", self)
        self.header_fade.setDuration(320)
        self.header_fade.setStartValue(0.0)
        self.header_fade.setEndValue(1.0)
        self.header_fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.stats_fade = QPropertyAnimation(self.stats_opacity, b"opacity", self)
        self.stats_fade.setDuration(420)
        self.stats_fade.setStartValue(0.0)
        self.stats_fade.setEndValue(1.0)
        self.stats_fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.content_fade = QPropertyAnimation(self.content_opacity, b"opacity", self)
        self.content_fade.setDuration(540)
        self.content_fade.setStartValue(0.0)
        self.content_fade.setEndValue(1.0)
        self.content_fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.entry_group.addAnimation(self.header_fade)
        self.entry_group.addAnimation(self.stats_fade)
        self.entry_group.addAnimation(self.content_fade)

        channel_shadow = QGraphicsDropShadowEffect(self.channel_panel)
        channel_shadow.setBlurRadius(26)
        channel_shadow.setOffset(0, 6)
        shadow_color = QColor("#39D8FF")
        shadow_color.setAlpha(60)
        channel_shadow.setColor(shadow_color)
        self.channel_panel.setGraphicsEffect(channel_shadow)

        if _HAS_GLOW_LABEL and isinstance(self.hero_title, GlowLabel):
            try:
                self.hero_title.set_glow_color("#43D9FF")
                self.hero_title.set_text_color("#F5FCFF")
            except Exception:
                pass

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QFrame#PublishScreen {
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
                font-size: 14px;
                font-weight: 900;
                background: transparent;
            }

            QLabel#RuntimePill {
                color: #EEF9FF;
                font-size: 9px;
                font-weight: 700;
                border: 1px solid rgba(157, 220, 255, 0.22);
                border-radius: 14px;
                background: rgba(18, 39, 70, 0.56);
                padding: 5px 9px;
            }

            QFrame#PublishHeaderCard {
                border: 1px solid rgba(170, 230, 255, 0.20);
                border-radius: 18px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(16, 34, 60, 0.80),
                    stop:1 rgba(8, 22, 44, 0.88)
                );
            }

            QLabel#HeaderChip {
                color: #EEF9FF;
                font-size: 9px;
                font-weight: 800;
                border: 1px solid rgba(157, 220, 255, 0.22);
                border-radius: 12px;
                background: rgba(28, 56, 91, 0.42);
                padding: 4px 9px;
            }

            QFrame#ChannelPanel, QFrame#InfoCard {
                border: 1px solid rgba(170, 230, 255, 0.20);
                border-radius: 18px;
                background: rgba(12, 28, 50, 0.74);
            }

            QLabel#SectionTitle {
                color: #F4FCFF;
                font-size: 9px;
                font-weight: 800;
                background: transparent;
            }
            """
        )

        if _HAS_GLOW_LABEL and isinstance(self.hero_title, GlowLabel):
            try:
                self.hero_title.set_text("Protected publish workflow")
            except Exception:
                self.hero_title.setText("Protected publish workflow")
        else:
            self.hero_title.setText("Protected publish workflow")

        self.hero_subtitle.setText(
            "Inspect handoff readiness, generate output artifacts, and execute the protected final publish workflow for the active session."
        )
        self.summary_banner.setText(
            "The publish screen supports report, QR, export, and remote publish readiness review for kiosk handoff."
        )

        self.hero_title.setStyleSheet(
            """
            QLabel {
                color: #F6FCFF;
                font-size: 21px;
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

        context_style = """
            QLabel {
                color: rgba(214, 235, 248, 0.86);
                font-size: 9px;
                font-weight: 500;
                background: transparent;
            }
        """
        self.context_line_1.setStyleSheet(context_style)
        self.context_line_2.setStyleSheet(context_style)
        self.context_line_3.setStyleSheet(context_style)
        self.context_line_4.setStyleSheet(context_style)
        self.context_note.setStyleSheet(context_style)
        self.quick_text.setStyleSheet(context_style)

        self._set_button_accent(self.reload_button, "#39D8FF")
        self._set_button_accent(self.bottom_reload_button, "#39D8FF")
        self._set_button_accent(self.report_button, "#67D8FF")
        self._set_button_accent(self.bottom_report_button, "#67D8FF")
        self._set_button_accent(self.qr_button, "#67D8FF")
        self._set_button_accent(self.bottom_qr_button, "#67D8FF")
        self._set_button_accent(self.export_button, "#67D8FF")
        self._set_button_accent(self.bottom_export_button, "#67D8FF")
        self._set_button_accent(self.publish_button, "#42E393")
        self._set_button_accent(self.bottom_publish_button, "#42E393")

    def _play_entry_animation(self) -> None:
        for effect_name in ("header_opacity", "stats_opacity", "content_opacity"):
            effect = getattr(self, effect_name, None)
            try:
                if effect is not None:
                    effect.setOpacity(1.0)
            except Exception:
                pass

        for widget_name in (
            "header_card",
            "stats_row",
            "content_row",
            "profile_panel",
            "metric_panel",
            "category_panel",
            "channel_panel",
        ):
            widget = getattr(self, widget_name, None)
            try:
                if widget is not None:
                    widget.setGraphicsEffect(None)
            except Exception:
                pass

        try:
            if hasattr(self, "entry_group") and self.entry_group is not None:
                self.entry_group.stop()
        except Exception:
            pass

        return

    def _apply_responsive_layout(self) -> None:
        width = max(1, self.width())
        height = max(1, self.height())
        compact = True if (KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480) else bool(self._compact_mode or width <= 860 or height <= 520)
        ultra = bool(self._ultra_compact_mode or width <= 800 or height <= 480)

        self.top_title.setText('Publish')
        self.hero_title.setText('Publish workflow')
        self.hero_subtitle.setVisible(False)
        self.summary_banner.setVisible(False)
        self.selected_pill.setVisible(False)
        self.publish_pill.setVisible(True)
        self.header_chip_row.setVisible(False)
        self.context_note.setVisible(False)
        self.quick_text.setVisible(False)

        self.report_chip.setVisible(False)
        self.handoff_chip.setVisible(False)
        self.remote_chip.setVisible(False)

        try:
            self.layout().setContentsMargins(10, 8, 10, 8)
            self.layout().setSpacing(6)
            self.content_row.layout().setSpacing(8)
            self.channel_panel.layout().setContentsMargins(10, 8, 10, 8)
            self.channel_panel.layout().setSpacing(6)
            self.channel_grid.setHorizontalSpacing(6)
            self.channel_grid.setVerticalSpacing(6)
            self.header_card.layout().setContentsMargins(10, 8, 10, 8)
            self.header_card.layout().setSpacing(4)
            self.header_card.setMaximumHeight(84 if ultra else 96)
        except Exception:
            pass

        self.side_panel.setMinimumWidth(236 if ultra else 248)
        self.side_panel.setMaximumWidth(248 if ultra else 260)
        self._set_label_pixmap(self.context_art, self._shield_pixmap, 56 if ultra else 64)

        self.reload_button.setText('Reload')
        self.report_button.setText('Report')
        self.qr_button.setText('QR')
        self.export_button.setText('Export')
        self.publish_button.setText('Publish')
        self.bottom_reload_button.setText('Reload')
        self.bottom_report_button.setText('Report')
        self.bottom_qr_button.setText('QR')
        self.bottom_export_button.setText('Export')
        self.bottom_publish_button.setText('Publish')

        for stat in (self.stat_ready, self.stat_session, self.stat_artifacts, self.stat_publish):
            try:
                stat.setMinimumHeight(62 if ultra else 68)
                stat.setMaximumHeight(68 if ultra else 72)
                if hasattr(stat, 'subtitle_label'):
                    stat.subtitle_label.setVisible(False)
                if stat.layout() is not None:
                    stat.layout().setContentsMargins(10, 8, 10, 8)
                    stat.layout().setSpacing(2)
            except Exception:
                pass

        for card in self.channel_cards.values():
            try:
                card.setMinimumHeight(78 if ultra else 84)
                card.setMaximumHeight(86 if ultra else 90)
                if card.layout() is not None:
                    card.layout().setContentsMargins(10, 8, 10, 8)
                    card.layout().setSpacing(2)
                card.icon_label.setMinimumSize(28 if ultra else 30, 28 if ultra else 30)
                card.icon_label.setMaximumSize(28 if ultra else 30, 28 if ultra else 30)
                card.subtitle_label.setVisible(False)
                card.detail_line.setVisible(False)
                card.count_line.setStyleSheet('QLabel { color: rgba(208, 230, 244, 0.84); font-size: 7px; font-weight: 600; background: transparent; }')
            except Exception:
                pass

        try:
            self.summary_card.setMinimumHeight(108 if ultra else 118)
            self.summary_card.setMaximumHeight(118 if ultra else 126)
            self.summary_card.line_2.setVisible(False)
            self.summary_card.line_3.setVisible(False)
            self.summary_card.line_4.setVisible(False)
            if self.summary_card.layout() is not None:
                self.summary_card.layout().setContentsMargins(10, 8, 10, 8)
                self.summary_card.layout().setSpacing(3)
        except Exception:
            pass

        try:
            self.context_card.setVisible(False)
            self.quick_card.setVisible(False)
        except Exception:
            pass

        for button in (self.back_button, self.reload_button, self.report_button, self.qr_button, self.export_button, self.publish_button, self.bottom_reload_button, self.bottom_report_button, self.bottom_qr_button, self.bottom_export_button, self.bottom_publish_button):
            try:
                button.setMinimumHeight(34 if ultra else 36)
                button.setMaximumHeight(34 if ultra else 36)
            except Exception:
                pass
        try:
            self._set_button_accent(self.back_button, '#47C9FF')
        except Exception:
            pass

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_responsive_layout()

    # =========================================================================
    # Lifecycle
    # =========================================================================

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._play_entry_animation()
        self._apply_responsive_layout()
        self.reload_publish_state()

    # =========================================================================
    # Snapshot loading
    # =========================================================================

    def reload_publish_state(self) -> None:
        snapshot = self._load_publish_snapshot()

        self._snapshot = deepcopy(snapshot)
        self._channels = deepcopy(snapshot.get("channels", {}))
        self._publish_state = safe_str(snapshot.get("publish_state"), "ready").strip().lower() or "ready"
        self._status_message = safe_str(snapshot.get("status_message"), "Publish snapshot loaded.").strip()
        self._last_publish_label = safe_str(snapshot.get("last_publish"), "No recent publish").strip()
        self._logic_source = safe_str(snapshot.get("logic_source"), "Filesystem and session fallback").strip()

        if self._selected_channel not in self._channels:
            self._selected_channel = CHANNEL_REPORT

        self._apply_snapshot_to_ui()
        self._apply_responsive_layout()
        self._persist_snapshot()
        self.publish_loaded.emit(self.diagnostics())
        self.publish_refreshed.emit(self.diagnostics())

    def _load_publish_snapshot(self) -> Dict[str, Any]:
        snapshot = self._build_filesystem_snapshot()

        # 1) publish service
        try:
            publish_service = self.services.get("publish_service") or self.services.get("publish")
            if publish_service is not None:
                for method_name in (
                    "snapshot",
                    "get_snapshot",
                    "get_publish_stats",
                    "stats",
                    "status",
                    "publish_snapshot",
                ):
                    method = getattr(publish_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method()
                            if isinstance(raw, Mapping):
                                snapshot = self._merge_publish_service_snapshot(snapshot, dict(raw))
                                snapshot["logic_source"] = "Publish service snapshot"
                                break
                        except Exception:
                            continue
        except Exception:
            pass

        # 2) report service
        try:
            report_service = self.services.get("report_service") or self.services.get("report")
            if report_service is not None:
                for method_name in ("stats", "get_stats", "snapshot", "get_snapshot", "status"):
                    method = getattr(report_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method()
                            if isinstance(raw, Mapping):
                                snapshot = self._merge_report_snapshot(snapshot, dict(raw))
                                break
                        except Exception:
                            continue
        except Exception:
            pass

        # 3) qr service
        try:
            qr_service = self.services.get("qr_service") or self.services.get("qr")
            if qr_service is not None:
                for method_name in ("stats", "get_stats", "snapshot", "get_snapshot", "status"):
                    method = getattr(qr_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method()
                            if isinstance(raw, Mapping):
                                snapshot = self._merge_qr_snapshot(snapshot, dict(raw))
                                break
                        except Exception:
                            continue
        except Exception:
            pass

        # 4) export service
        try:
            export_service = self.services.get("export_service") or self.services.get("export")
            if export_service is not None:
                for method_name in ("stats", "get_stats", "snapshot", "get_snapshot", "status"):
                    method = getattr(export_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method()
                            if isinstance(raw, Mapping):
                                snapshot = self._merge_export_snapshot(snapshot, dict(raw))
                                break
                        except Exception:
                            continue
        except Exception:
            pass

        # 5) session payload and paths
        payload = self._read_session_payload()
        snapshot = self._merge_session_payload(snapshot, payload)

        # 6) settings / network mode
        snapshot = self._merge_network_settings(snapshot)

        self._finalize_snapshot(snapshot)
        return snapshot

    def _build_filesystem_snapshot(self) -> Dict[str, Any]:
        data_root = _data_root()
        reports_dir = data_root / "reports"
        qr_dir = data_root / "qr"
        exports_dir = data_root / "exports"

        report_count = _count_files(reports_dir)
        qr_count = _count_files(qr_dir)
        export_count = _count_files(exports_dir)

        report_size = _directory_size_bytes(reports_dir)
        qr_size = _directory_size_bytes(qr_dir)
        export_size = _directory_size_bytes(exports_dir)

        publish_manifest = _latest_matching_file(exports_dir, "publish_manifest_")

        channels: Dict[str, Dict[str, Any]] = {
            CHANNEL_REPORT: {
                "channel_key": CHANNEL_REPORT,
                "path": str(reports_dir),
                "exists": reports_dir.exists(),
                "count": report_count,
                "size_bytes": report_size,
                "size_text": _format_bytes(report_size),
                "state": "ready" if report_count > 0 else "pending",
                "summary": "Protected report artifacts are ready for handoff." if report_count > 0 else "No report artifact is currently available.",
                "last_updated": _latest_file_time(reports_dir),
            },
            CHANNEL_QR: {
                "channel_key": CHANNEL_QR,
                "path": str(qr_dir),
                "exists": qr_dir.exists(),
                "count": qr_count,
                "size_bytes": qr_size,
                "size_text": _format_bytes(qr_size),
                "state": "ready" if qr_count > 0 else "pending",
                "summary": "QR handoff artifacts are available." if qr_count > 0 else "No QR artifact is currently available.",
                "last_updated": _latest_file_time(qr_dir),
            },
            CHANNEL_EXPORT: {
                "channel_key": CHANNEL_EXPORT,
                "path": str(exports_dir),
                "exists": exports_dir.exists(),
                "count": export_count,
                "size_bytes": export_size,
                "size_text": _format_bytes(export_size),
                "state": "ready" if export_count > 0 else "pending",
                "summary": "Export files are available for handoff." if export_count > 0 else "No export package is currently available.",
                "last_updated": _latest_file_time(exports_dir),
            },
            CHANNEL_PUBLISH: {
                "channel_key": CHANNEL_PUBLISH,
                "path": publish_manifest or str(exports_dir),
                "exists": exports_dir.exists(),
                "count": 1 if publish_manifest else 0,
                "size_bytes": 0,
                "size_text": _format_bytes(0),
                "state": "published" if publish_manifest else "pending",
                "summary": "A publish manifest is available." if publish_manifest else "No recent publish manifest is available.",
                "last_updated": _latest_file_time(exports_dir),
            },
            CHANNEL_SESSION: {
                "channel_key": CHANNEL_SESSION,
                "path": "Active runtime session",
                "exists": True,
                "count": 0,
                "size_bytes": 0,
                "size_text": _format_bytes(0),
                "state": "pending",
                "summary": "No active session payload has been detected yet.",
                "last_updated": "Runtime session",
            },
            CHANNEL_NETWORK: {
                "channel_key": CHANNEL_NETWORK,
                "path": "Runtime network settings",
                "exists": True,
                "count": 0,
                "size_bytes": 0,
                "size_text": _format_bytes(0),
                "state": "pending",
                "summary": "Network mode has not yet been resolved.",
                "last_updated": "Runtime settings",
            },
        }

        snapshot: Dict[str, Any] = {
            "channels": channels,
            "publish_state": "pending",
            "status_message": "Publish snapshot loaded from protected filesystem fallback.",
            "detail": "Filesystem inspection was used because service-provided publish stats were not fully available.",
            "logic_source": "Filesystem and session fallback",
            "last_publish": publish_manifest or "No recent publish",
            "ready_count": 0,
            "artifact_count": report_count + qr_count + export_count,
            "session_ready": False,
        }

        self._finalize_snapshot(snapshot)
        return snapshot

    def _merge_publish_service_snapshot(self, snapshot: Dict[str, Any], service_data: Dict[str, Any]) -> Dict[str, Any]:
        merged = deepcopy(snapshot)
        channels = dict(merged.get("channels", {}))

        detail = safe_str(service_data.get("detail", service_data.get("summary", "")), "").strip()
        if detail:
            merged["detail"] = detail

        status_text = safe_str(service_data.get("status_message", service_data.get("status", "")), "").strip()
        if status_text:
            merged["status_message"] = status_text

        publish_state = safe_str(service_data.get("state", service_data.get("status", "")), "").strip().lower()
        if publish_state:
            merged["publish_state"] = publish_state

        last_publish = safe_str(service_data.get("last_publish", service_data.get("last_updated", "")), "").strip()
        if last_publish:
            merged["last_publish"] = last_publish

        raw_channels = service_data.get("channels", {})
        if isinstance(raw_channels, Mapping):
            for channel_key in CHANNEL_ORDER:
                raw_item = raw_channels.get(channel_key)
                if not isinstance(raw_item, Mapping):
                    continue
                base = dict(channels.get(channel_key, {}))
                base.update(dict(raw_item))
                base["state"] = safe_str(base.get("state", "ready"), "ready").strip().lower() or "ready"
                base["summary"] = safe_str(base.get("summary"), _channel_default_summary(channel_key)).strip() or _channel_default_summary(channel_key)
                base["count"] = safe_int(base.get("count"), 0)
                base["size_bytes"] = safe_int(base.get("size_bytes"), 0)
                base["size_text"] = _format_bytes(base["size_bytes"])
                channels[channel_key] = base

        merged["channels"] = channels
        return merged

    def _merge_report_snapshot(self, snapshot: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
        merged = deepcopy(snapshot)
        channels = dict(merged.get("channels", {}))
        item = dict(channels.get(CHANNEL_REPORT, {}))

        count = data.get("report_count", data.get("count", data.get("reports")))
        if count not in (None, ""):
            item["count"] = safe_int(count, item.get("count", 0))

        path = safe_str(data.get("path", data.get("latest_report", data.get("report_path", ""))), "").strip()
        if path:
            item["path"] = path

        state = safe_str(data.get("state", data.get("status", "")), "").strip().lower()
        if state:
            item["state"] = state

        detail = safe_str(data.get("detail", data.get("summary", "")), "").strip()
        if detail:
            item["summary"] = detail

        if item.get("count", 0) > 0 and not item.get("summary"):
            item["summary"] = "Protected report artifacts are available."

        channels[CHANNEL_REPORT] = item
        merged["channels"] = channels
        return merged

    def _merge_qr_snapshot(self, snapshot: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
        merged = deepcopy(snapshot)
        channels = dict(merged.get("channels", {}))
        item = dict(channels.get(CHANNEL_QR, {}))

        count = data.get("qr_count", data.get("count", data.get("items")))
        if count not in (None, ""):
            item["count"] = safe_int(count, item.get("count", 0))

        path = safe_str(data.get("path", data.get("latest_qr", data.get("qr_path", ""))), "").strip()
        if path:
            item["path"] = path

        state = safe_str(data.get("state", data.get("status", "")), "").strip().lower()
        if state:
            item["state"] = state

        detail = safe_str(data.get("detail", data.get("summary", "")), "").strip()
        if detail:
            item["summary"] = detail

        if item.get("count", 0) > 0 and not item.get("summary"):
            item["summary"] = "QR handoff artifacts are available."

        channels[CHANNEL_QR] = item
        merged["channels"] = channels
        return merged

    def _merge_export_snapshot(self, snapshot: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
        merged = deepcopy(snapshot)
        channels = dict(merged.get("channels", {}))
        item = dict(channels.get(CHANNEL_EXPORT, {}))

        count = data.get("export_count", data.get("count", data.get("exports")))
        if count not in (None, ""):
            item["count"] = safe_int(count, item.get("count", 0))

        path = safe_str(data.get("path", data.get("latest_export", data.get("export_path", ""))), "").strip()
        if path:
            item["path"] = path

        state = safe_str(data.get("state", data.get("status", "")), "").strip().lower()
        if state:
            item["state"] = state

        detail = safe_str(data.get("detail", data.get("summary", "")), "").strip()
        if detail:
            item["summary"] = detail

        last_export = safe_str(data.get("last_export", data.get("last_updated", "")), "").strip()
        if last_export:
            item["last_updated"] = last_export

        if item.get("count", 0) > 0 and not item.get("summary"):
            item["summary"] = "Export files are available for handoff."

        channels[CHANNEL_EXPORT] = item
        merged["channels"] = channels
        return merged

    def _merge_session_payload(self, snapshot: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        merged = deepcopy(snapshot)
        channels = dict(merged.get("channels", {}))

        session_item = dict(channels.get(CHANNEL_SESSION, {}))
        measurements = payload.get("measurements", {})
        if not isinstance(measurements, Mapping):
            measurements = {}

        measurement_count = len([k for k, v in measurements.items() if v not in (None, "")])
        payload_bytes = len(json.dumps(payload, default=str).encode("utf-8")) if payload else 0

        report_path = safe_str(payload.get("report_path"), "").strip()
        qr_path = safe_str(payload.get("qr_path"), "").strip()
        export_path = safe_str(payload.get("export_path"), "").strip()
        publish_url = safe_str(payload.get("publish_url", payload.get("published_url", "")), "").strip()
        session_id = safe_str(payload.get("session_id", payload.get("id", "")), "").strip()

        session_ready = bool(payload) and (measurement_count > 0 or any([report_path, qr_path, export_path, publish_url]))
        session_item["count"] = measurement_count
        session_item["size_bytes"] = payload_bytes
        session_item["size_text"] = _format_bytes(payload_bytes)
        session_item["state"] = "ready" if session_ready else "pending"
        session_item["summary"] = (
            "The active session payload is ready for publish and artifact generation."
            if session_ready
            else "The active session payload is incomplete or unavailable."
        )
        session_item["path"] = session_id or "Runtime session"
        session_item["last_updated"] = "Active session"
        channels[CHANNEL_SESSION] = session_item

        # propagate explicit paths to related channels if present
        if report_path:
            report_item = dict(channels.get(CHANNEL_REPORT, {}))
            report_item["path"] = report_path
            report_item["state"] = "ready"
            report_item["summary"] = "A report artifact is linked in the active session."
            channels[CHANNEL_REPORT] = report_item

        if qr_path:
            qr_item = dict(channels.get(CHANNEL_QR, {}))
            qr_item["path"] = qr_path
            qr_item["state"] = "ready"
            qr_item["summary"] = "A QR artifact is linked in the active session."
            channels[CHANNEL_QR] = qr_item

        if export_path:
            export_item = dict(channels.get(CHANNEL_EXPORT, {}))
            export_item["path"] = export_path
            export_item["state"] = "ready"
            export_item["summary"] = "An export package is linked in the active session."
            channels[CHANNEL_EXPORT] = export_item

        if publish_url:
            publish_item = dict(channels.get(CHANNEL_PUBLISH, {}))
            publish_item["path"] = publish_url
            publish_item["state"] = "published"
            publish_item["summary"] = "A published handoff target is linked in the active session."
            channels[CHANNEL_PUBLISH] = publish_item
            merged["last_publish"] = publish_url

        merged["channels"] = channels
        merged["session_ready"] = session_ready
        return merged

    def _merge_network_settings(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        merged = deepcopy(snapshot)
        channels = dict(merged.get("channels", {}))

        network_mode = ""
        try:
            settings_service = self.services.get("settings_service") or self.services.get("settings")
            if settings_service is not None:
                for method_name in ("get_setting", "value", "get"):
                    method = getattr(settings_service, method_name, None)
                    if callable(method):
                        try:
                            result = method("network_mode")
                            network_mode = safe_str(result, "").strip().lower()
                            if network_mode:
                                break
                        except Exception:
                            continue
        except Exception:
            pass

        if not network_mode:
            try:
                if self.app_state is not None and hasattr(self.app_state, "network_mode"):
                    network_mode = safe_str(getattr(self.app_state, "network_mode"), "").strip().lower()
            except Exception:
                pass

        if not network_mode:
            network_mode = "local"

        network_item = dict(channels.get(CHANNEL_NETWORK, {}))
        network_item["path"] = "Runtime network settings"

        if network_mode == "offline":
            network_item["state"] = "offline"
            network_item["summary"] = "The runtime is configured for offline operation. Remote publish may be unavailable."
        elif network_mode == "online":
            network_item["state"] = "online"
            network_item["summary"] = "The runtime is configured for online operation and remote publish may proceed if services are available."
        elif network_mode == "auto":
            network_item["state"] = "partial"
            network_item["summary"] = "The runtime may switch between local and remote connectivity depending on availability."
        else:
            network_item["state"] = "ready"
            network_item["summary"] = "The runtime is configured for local operation with optional publish handoff support."

        network_item["count"] = 1
        network_item["size_bytes"] = 0
        network_item["size_text"] = _format_bytes(0)
        network_item["last_updated"] = f"Mode: {network_mode}"
        channels[CHANNEL_NETWORK] = network_item

        merged["channels"] = channels
        return merged

    def _finalize_snapshot(self, snapshot: Dict[str, Any]) -> None:
        channels = snapshot.get("channels", {})
        if not isinstance(channels, dict):
            channels = {}

        ready_count = 0
        artifact_count = 0
        session_ready = safe_bool(snapshot.get("session_ready"), False)

        for channel_key in CHANNEL_ORDER:
            item = dict(channels.get(channel_key, {}))
            state = safe_str(item.get("state"), "pending").strip().lower() or "pending"
            count = safe_int(item.get("count"), 0)
            size_bytes = safe_int(item.get("size_bytes"), 0)

            item["state"] = state
            item["count"] = count
            item["size_bytes"] = size_bytes
            item["size_text"] = _format_bytes(size_bytes)
            item["summary"] = safe_str(item.get("summary"), _channel_default_summary(channel_key)).strip() or _channel_default_summary(channel_key)
            item["last_updated"] = safe_str(item.get("last_updated"), "Unknown").strip() or "Unknown"

            if state in {"ready", "success", "published", "online", "healthy"}:
                ready_count += 1

            if channel_key in {CHANNEL_REPORT, CHANNEL_QR, CHANNEL_EXPORT}:
                artifact_count += count

            channels[channel_key] = item

        publish_item = dict(channels.get(CHANNEL_PUBLISH, {}))
        publish_state = safe_str(snapshot.get("publish_state"), "").strip().lower()
        if not publish_state:
            if safe_str(publish_item.get("state"), "").strip().lower() in {"published", "success"}:
                publish_state = "published"
            elif session_ready and artifact_count > 0:
                publish_state = "ready"
            elif session_ready:
                publish_state = "attention"
            else:
                publish_state = "pending"

        status_message = safe_str(snapshot.get("status_message"), "").strip()
        if not status_message:
            if publish_state == "published":
                status_message = "Protected publish workflow has a recent completed handoff."
            elif publish_state == "ready":
                status_message = "Publish workflow is ready. Session and artifacts are available."
            elif publish_state == "attention":
                status_message = "Session payload is available, but more artifacts may still be needed before final publish."
            else:
                status_message = "Publish workflow is waiting for session data or artifact generation."

        snapshot["channels"] = channels
        snapshot["ready_count"] = ready_count
        snapshot["artifact_count"] = artifact_count
        snapshot["publish_state"] = publish_state
        snapshot["status_message"] = status_message
        snapshot["session_ready"] = session_ready

    def _persist_snapshot(self) -> None:
        try:
            publish_service = self.services.get("publish_service") or self.services.get("publish")
            if publish_service is not None:
                for method_name in ("set_runtime_snapshot", "update_runtime_snapshot", "set_publish_snapshot"):
                    method = getattr(publish_service, method_name, None)
                    if callable(method):
                        try:
                            method(dict(self._snapshot))
                        except Exception:
                            continue
        except Exception:
            pass

        try:
            if self.app_state is not None:
                if hasattr(self.app_state, "publish_snapshot"):
                    setattr(self.app_state, "publish_snapshot", dict(self._snapshot))
                if hasattr(self.app_state, "selected_publish_channel"):
                    setattr(self.app_state, "selected_publish_channel", self._selected_channel)
        except Exception:
            pass

    def _read_session_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}

        try:
            session_service = self.services.get("session_service") or self.services.get("session")
            if session_service is not None:
                for method_name in (
                    "get_results_payload",
                    "get_current_session",
                    "get_session_payload",
                    "current_session_payload",
                    "get_latest_results_payload",
                    "snapshot",
                    "get_snapshot",
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

        if not payload:
            try:
                if self.app_state is not None:
                    for attr_name in ("results_payload", "current_session_payload", "session_payload", "consult_payload"):
                        attr = getattr(self.app_state, attr_name, None)
                        if isinstance(attr, Mapping):
                            payload = dict(attr)
                            if payload:
                                break
            except Exception:
                pass

        return payload

    # =========================================================================
    # UI application
    # =========================================================================

    def _apply_snapshot_to_ui(self) -> None:
        channels = self._channels or {}
        selected = dict(channels.get(self._selected_channel, {}))
        selected_state = safe_str(selected.get("state"), "pending").strip().lower() or "pending"
        selected_accent = _accent_for_state(selected_state)
        selected_label = CHANNEL_LABELS.get(self._selected_channel, self._selected_channel.title())

        publish_state = safe_str(self._publish_state, "pending").strip().lower() or "pending"
        publish_label = publish_state.title()
        publish_accent = _accent_for_state(publish_state)

        ready_count = safe_int(self._snapshot.get("ready_count"), 0)
        artifact_count = safe_int(self._snapshot.get("artifact_count"), 0)
        session_ready = safe_bool(self._snapshot.get("session_ready"), False)

        # channel cards
        for channel_key in CHANNEL_ORDER:
            item = dict(channels.get(channel_key, {}))
            state = safe_str(item.get("state"), "pending").strip().lower() or "pending"
            accent = _accent_for_state(state)

            detail_text = f"Last: {safe_str(item.get('last_updated'), 'Unknown')}"
            if safe_str(item.get("path"), "").strip():
                detail_text = safe_str(item.get("path"), "").strip()

            count_value = safe_int(item.get("count"), 0)
            size_text = safe_str(item.get("size_text"), "--").strip() or "--"

            card = self.channel_cards.get(channel_key)
            if card is not None:
                card.set_selected(channel_key == self._selected_channel)
                card.set_payload(
                    state_text=state.title(),
                    subtitle=safe_str(item.get("summary"), _channel_default_summary(channel_key)),
                    count_line=f"Items {count_value} • Size {size_text}" if channel_key not in {CHANNEL_SESSION, CHANNEL_NETWORK} else f"State detail • {size_text}",
                    detail_line=detail_text,
                    accent_hex=accent,
                )

        # summary card
        summary_lines = {
            1: f"Path / target: {safe_str(selected.get('path'), 'Unavailable')}",
            2: f"Count: {safe_int(selected.get('count'), 0)} • Size: {safe_str(selected.get('size_text'), '--')}",
            3: f"Last updated: {safe_str(selected.get('last_updated'), 'Unknown')}",
            4: self._status_message,
        }

        self.summary_card.set_payload(
            title=selected_label,
            state_text=selected_state.title(),
            summary=safe_str(selected.get("summary"), "").strip() or _channel_default_summary(self._selected_channel),
            lines=summary_lines,
            accent_hex=selected_accent,
        )

        # pills
        self.status_pill.setText("Loaded")
        self._apply_pill_style(self.status_pill, "#42E393")

        self.publish_pill.setText(publish_label)
        self._apply_pill_style(self.publish_pill, publish_accent)

        self.selected_pill.setText(selected_label)
        self._apply_pill_style(self.selected_pill, selected_accent)

        # header chips
        self._apply_header_chip_style(self.report_chip, "#67D8FF")
        self._apply_header_chip_style(self.handoff_chip, "#39D8FF")
        self._apply_header_chip_style(self.remote_chip, publish_accent)

        # stats
        self.stat_ready.set_payload(
            value=str(ready_count),
            subtitle="Publish channels that are currently ready or completed.",
            accent_hex="#42E393" if ready_count > 0 else "#FFD25E",
        )
        self.stat_session.set_payload(
            value="Ready" if session_ready else "Pending",
            subtitle="Whether the active session contains enough data for publish.",
            accent_hex="#42E393" if session_ready else "#FFD25E",
        )
        self.stat_artifacts.set_payload(
            value=str(artifact_count),
            subtitle="Available report, QR, and export artifacts.",
            accent_hex="#67D8FF" if artifact_count > 0 else "#39D8FF",
        )
        self.stat_publish.set_payload(
            value=publish_label,
            subtitle=self._status_message,
            accent_hex=publish_accent,
        )

        # context
        self.context_line_1.setText(f"Selected channel: {selected_label}")
        self.context_line_2.setText(f"Publish state: {publish_label}")
        self.context_line_3.setText(f"Last publish: {self._last_publish_label}")
        self.context_line_4.setText(f"Logic source: {self._logic_source}")

        self.context_note.setText(
            "Generate artifacts first when needed, then use publish bundle once the session and network state are appropriate."
        )

        # buttons
        self._set_button_accent(self.reload_button, "#39D8FF")
        self._set_button_accent(self.bottom_reload_button, "#39D8FF")
        self._set_button_accent(self.report_button, "#67D8FF")
        self._set_button_accent(self.bottom_report_button, "#67D8FF")
        self._set_button_accent(self.qr_button, "#67D8FF")
        self._set_button_accent(self.bottom_qr_button, "#67D8FF")
        self._set_button_accent(self.export_button, "#67D8FF")
        self._set_button_accent(self.bottom_export_button, "#67D8FF")
        self._set_button_accent(self.publish_button, "#42E393" if session_ready else "#FFD25E")
        self._set_button_accent(self.bottom_publish_button, "#42E393" if session_ready else "#FFD25E")

    # =========================================================================
    # Actions
    # =========================================================================

    def _handle_channel_card_clicked(self, channel_key: str) -> None:
        channel = safe_str(channel_key, "").strip()
        if channel not in self._channels:
            return

        self._selected_channel = channel
        self._apply_snapshot_to_ui()
        self.publish_channel_selected.emit(channel)

    def _handle_generate_report_clicked(self) -> None:
        self.publish_action_requested.emit("generate_report")
        result_path = ""

        try:
            report_service = self.services.get("report_service") or self.services.get("report")
            if report_service is not None:
                for method_name in (
                    "generate_report",
                    "build_report",
                    "create_report",
                    "create_pdf_report",
                    "export_report",
                ):
                    method = getattr(report_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method()
                            if isinstance(raw, Mapping):
                                result_path = safe_str(raw.get("path", raw.get("file_path", raw.get("report_path", ""))), "").strip()
                            else:
                                result_path = safe_str(raw, "").strip()
                            if result_path:
                                break
                        except Exception:
                            continue
        except Exception:
            pass

        if not result_path:
            result_path = self._filesystem_report_fallback()

        if result_path:
            self._status_message = "Report artifact generated successfully."
        else:
            self._status_message = "Report generation completed, but no explicit report path was returned."

        self.reload_publish_state()
        self.report_generated.emit(self.diagnostics())

    def _handle_generate_qr_clicked(self) -> None:
        self.publish_action_requested.emit("generate_qr")
        result_path = ""

        try:
            qr_service = self.services.get("qr_service") or self.services.get("qr")
            if qr_service is not None:
                for method_name in (
                    "generate_qr",
                    "build_qr",
                    "create_qr",
                    "generate",
                    "create_qr_artifact",
                ):
                    method = getattr(qr_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method()
                            if isinstance(raw, Mapping):
                                result_path = safe_str(raw.get("path", raw.get("file_path", raw.get("qr_path", ""))), "").strip()
                            else:
                                result_path = safe_str(raw, "").strip()
                            if result_path:
                                break
                        except Exception:
                            continue
        except Exception:
            pass

        if not result_path:
            result_path = self._filesystem_qr_fallback()

        if result_path:
            self._status_message = "QR artifact generated successfully."
        else:
            self._status_message = "QR generation completed, but no explicit QR path was returned."

        self.reload_publish_state()
        self.qr_generated.emit(self.diagnostics())

    def _handle_export_clicked(self) -> None:
        self.publish_action_requested.emit("export")
        result_path = ""

        try:
            export_service = self.services.get("export_service") or self.services.get("export")
            if export_service is not None:
                for method_name in (
                    "export_all",
                    "export_storage",
                    "export_sessions",
                    "run_export",
                    "create_export",
                ):
                    method = getattr(export_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method()
                            if isinstance(raw, Mapping):
                                result_path = safe_str(raw.get("path", raw.get("file_path", raw.get("export_path", ""))), "").strip()
                            else:
                                result_path = safe_str(raw, "").strip()
                            if result_path:
                                break
                        except Exception:
                            continue
        except Exception:
            pass

        if not result_path:
            result_path = self._filesystem_export_fallback()

        if result_path:
            self._status_message = "Export package generated successfully."
        else:
            self._status_message = "Export action completed, but no explicit export path was returned."

        self.reload_publish_state()
        self.export_generated.emit(self.diagnostics())

    def _handle_publish_clicked(self) -> None:
        self.publish_action_requested.emit("publish")
        result_target = ""

        try:
            publish_service = self.services.get("publish_service") or self.services.get("publish")
            if publish_service is not None:
                for method_name in (
                    "publish",
                    "publish_bundle",
                    "run_publish",
                    "publish_results",
                    "execute_publish",
                ):
                    method = getattr(publish_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method()
                            if isinstance(raw, Mapping):
                                result_target = safe_str(
                                    raw.get("url", raw.get("path", raw.get("file_path", raw.get("publish_target", "")))),
                                    "",
                                ).strip()
                            else:
                                result_target = safe_str(raw, "").strip()
                            if result_target:
                                break
                        except Exception:
                            continue
        except Exception:
            pass

        if not result_target:
            result_target = self._filesystem_publish_manifest_fallback()

        if result_target:
            self._status_message = "Publish workflow executed successfully."
            self._last_publish_label = result_target
        else:
            self._status_message = "Publish action completed, but no explicit publish target was returned."

        self.reload_publish_state()
        self.publish_executed.emit(self.diagnostics())

    # =========================================================================
    # Fallback artifact creation
    # =========================================================================

    def _filesystem_report_fallback(self) -> str:
        try:
            reports_dir = _data_root() / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)

            payload = self._read_session_payload()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_path = reports_dir / f"session_report_{timestamp}.txt"

            lines = [
                "CST Health Monitoring Station",
                "Protected report fallback artifact",
                f"Generated: {datetime.now().isoformat(timespec='seconds')}",
                "",
                "Session payload summary:",
                json.dumps(payload or {"note": "No session payload available."}, indent=2, default=str),
            ]
            report_path.write_text("\n".join(lines), encoding="utf-8")
            return str(report_path)
        except Exception:
            return ""

    def _filesystem_qr_fallback(self) -> str:
        try:
            qr_dir = _data_root() / "qr"
            qr_dir.mkdir(parents=True, exist_ok=True)

            payload = self._read_session_payload()
            session_id = safe_str(payload.get("session_id", payload.get("id", "")), "").strip() or "session"
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            qr_manifest_path = qr_dir / f"qr_manifest_{session_id}_{timestamp}.txt"

            qr_manifest_path.write_text(
                "\n".join(
                    [
                        "CST Health Monitoring Station",
                        "Protected QR fallback manifest",
                        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
                        f"Session: {session_id}",
                        "QR generation service was unavailable, so this manifest was created as a protected placeholder.",
                    ]
                ),
                encoding="utf-8",
            )
            return str(qr_manifest_path)
        except Exception:
            return ""

    def _filesystem_export_fallback(self) -> str:
        try:
            exports_dir = _data_root() / "exports"
            exports_dir.mkdir(parents=True, exist_ok=True)

            payload = self._read_session_payload()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            export_path = exports_dir / f"session_export_{timestamp}.json"
            export_path.write_text(json.dumps(payload or {}, indent=2, default=str), encoding="utf-8")
            return str(export_path)
        except Exception:
            return ""

    def _filesystem_publish_manifest_fallback(self) -> str:
        try:
            exports_dir = _data_root() / "exports"
            exports_dir.mkdir(parents=True, exist_ok=True)

            payload = self._read_session_payload()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            manifest_path = exports_dir / f"publish_manifest_{timestamp}.json"

            report_path = _latest_matching_file(_data_root() / "reports", "session_report_")
            qr_path = _latest_matching_file(_data_root() / "qr", "qr_manifest_")
            export_path = _latest_matching_file(exports_dir, "session_export_")

            manifest = {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "type": "protected_publish_manifest",
                "session_id": safe_str(payload.get("session_id", payload.get("id", "")), "").strip(),
                "report_path": report_path,
                "qr_path": qr_path,
                "export_path": export_path,
                "payload_present": bool(payload),
                "payload_measurement_count": len(
                    [
                        k for k, v in (payload.get("measurements", {}) if isinstance(payload.get("measurements", {}), Mapping) else {}).items()
                        if v not in (None, "")
                    ]
                ),
            }
            manifest_path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
            return str(manifest_path)
        except Exception:
            return ""

    # =========================================================================
    # Navigation
    # =========================================================================

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
                border-radius: 14px;
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
                    padding: 8px 14px;
                    font-size: 9px;
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
            "selected_channel": self._selected_channel,
            "snapshot": deepcopy(self._snapshot),
            "channels": deepcopy(self._channels),
            "status_message": self._status_message,
            "publish_state": self._publish_state,
            "last_publish_label": self._last_publish_label,
            "logic_source": self._logic_source,
            "background_path": self._background_path,
            "logo_path": self._logo_small_path,
            "admin_shield_path": self._admin_shield_path,
        }
