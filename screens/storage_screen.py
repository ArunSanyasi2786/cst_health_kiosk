"""
screens/storage_screen.py

Protected storage-management screen for the CST Health Monitoring Station kiosk.

This file is a full defensive drop-in replacement focused on:
- clean 800x480 presentation
- no disappearing hover / opacity issues
- safe filesystem fallback behavior
- clickable maintenance actions
- service integration when available
- consistent admin-screen visual language

The implementation intentionally keeps the public signal surface and method names
stable so it can replace earlier versions that were throwing runtime errors.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import json
import shutil
from typing import Any, Dict, Iterable, Mapping, Optional

from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPixmap
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
    from core.constants import SCREEN_ADMIN_PANEL
except Exception:  # pragma: no cover
    SCREEN_ADMIN_PANEL = "admin_panel"

try:
    from config import KIOSK_WIDTH, KIOSK_HEIGHT, IS_COMPACT_KIOSK
except Exception:  # pragma: no cover
    KIOSK_WIDTH = 800
    KIOSK_HEIGHT = 480
    IS_COMPACT_KIOSK = True

try:
    from widgets.animated_button import AnimatedButton
except Exception:  # pragma: no cover
    AnimatedButton = None  # type: ignore

logger = get_logger(__name__)


CATEGORY_RECORDS = "records"
CATEGORY_REPORTS = "reports"
CATEGORY_QR = "qr"
CATEGORY_BACKUPS = "backups"
CATEGORY_EXPORTS = "exports"
CATEGORY_TEMP = "temp"
CATEGORY_LOGS = "logs"

CATEGORY_ORDER = [
    CATEGORY_RECORDS,
    CATEGORY_REPORTS,
    CATEGORY_QR,
    CATEGORY_BACKUPS,
    CATEGORY_EXPORTS,
    CATEGORY_TEMP,
    CATEGORY_LOGS,
]

CATEGORY_LABELS = {
    CATEGORY_RECORDS: "Records",
    CATEGORY_REPORTS: "Reports",
    CATEGORY_QR: "QR Files",
    CATEGORY_BACKUPS: "Backups",
    CATEGORY_EXPORTS: "Exports",
    CATEGORY_TEMP: "Temp Files",
    CATEGORY_LOGS: "Logs",
}

CATEGORY_DESCRIPTIONS = {
    CATEGORY_RECORDS: "Database-backed session records and persistent measurement data.",
    CATEGORY_REPORTS: "Generated PDF or report artifacts saved by the kiosk.",
    CATEGORY_QR: "QR handoff images or related result artifacts.",
    CATEGORY_BACKUPS: "Recovery snapshots and protected backup files.",
    CATEGORY_EXPORTS: "Exported CSV, JSON, or handoff packages.",
    CATEGORY_TEMP: "Temporary runtime files that can usually be cleared.",
    CATEGORY_LOGS: "Application and serial logs used for troubleshooting.",
}

CATEGORY_ACCENTS = {
    CATEGORY_RECORDS: "#33C8FF",
    CATEGORY_REPORTS: "#58D6A8",
    CATEGORY_QR: "#67D8FF",
    CATEGORY_BACKUPS: "#7A66FF",
    CATEGORY_EXPORTS: "#36D48E",
    CATEGORY_TEMP: "#FFD25E",
    CATEGORY_LOGS: "#F6906C",
}


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _data_root() -> Path:
    return _project_root() / "data"


def _resolve_asset(relative_path: str) -> str:
    relative_clean = safe_str(relative_path, "").strip().replace("\\", "/").lstrip("/")
    if not relative_clean:
        return ""

    try:
        import core.asset_paths as asset_paths  # local import on purpose

        for name in ("get_asset_path", "asset_path", "resolve_asset_path", "resolve_asset", "asset"):
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
    path_text = safe_str(path, "").strip()
    if not path_text:
        return QPixmap()
    return QPixmap(path_text)


def _iter_real_files(directory: Path) -> Iterable[Path]:
    if not directory.exists() or not directory.is_dir():
        return []
    return [p for p in directory.rglob("*") if p.is_file() and p.name != ".keep" and not p.name.startswith(".")]


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


def _format_bytes(size_bytes: int) -> str:
    size = float(max(0, safe_int(size_bytes, 0)))
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while size >= 1024.0 and idx < len(units) - 1:
        size /= 1024.0
        idx += 1
    if idx == 0:
        return f"{int(size)} {units[idx]}"
    return f"{size:.1f} {units[idx]}"


def _safe_dt_string(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "Unknown"


def _latest_file_label(directory: Path) -> str:
    latest: Optional[float] = None
    for file_path in _iter_real_files(directory):
        try:
            ts = float(file_path.stat().st_mtime)
            if latest is None or ts > latest:
                latest = ts
        except Exception:
            continue
    if latest is None:
        return "No recent files"
    return _safe_dt_string(latest)


def _accent_for_state(state: str, default: str = "#39D8FF") -> str:
    state_text = safe_str(state, "").strip().lower()
    if state_text in {"healthy", "ready", "available", "saved", "clean"}:
        return "#42E393"
    if state_text in {"warning", "attention", "pending", "dirty"}:
        return "#FFD25E"
    if state_text in {"critical", "error", "failed", "missing", "offline"}:
        return "#FF6E88"
    return default


class _StorageStatCard(QFrame):
    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._accent = "#39D8FF"
        self.setObjectName("StorageStatCard")
        self.setMinimumHeight(74)
        self.setMaximumHeight(86)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(12, 9, 12, 9)
        self.root_layout.setSpacing(2)

        self.title_label = QLabel(title, self)
        self.value_label = QLabel("--", self)
        self.subtitle_label = QLabel("", self)
        self.subtitle_label.setWordWrap(True)

        self.root_layout.addWidget(self.title_label)
        self.root_layout.addWidget(self.value_label)
        self.root_layout.addWidget(self.subtitle_label)
        self.root_layout.addStretch(1)

        self._apply_style()

    def set_payload(self, *, value: str, subtitle: str, accent_hex: str) -> None:
        self._accent = safe_str(accent_hex, "#39D8FF") or "#39D8FF"
        self.value_label.setText(safe_str(value, "--") or "--")
        self.subtitle_label.setText(safe_str(subtitle, ""))
        self._apply_style()

    def set_compact(self, compact: bool = True, ultra: bool = False) -> None:
        if ultra:
            self.setMinimumHeight(62)
            self.setMaximumHeight(68)
            self.root_layout.setContentsMargins(10, 7, 10, 7)
            self.root_layout.setSpacing(1)
            self.subtitle_label.setVisible(False)
        elif compact:
            self.setMinimumHeight(66)
            self.setMaximumHeight(72)
            self.root_layout.setContentsMargins(10, 8, 10, 8)
            self.root_layout.setSpacing(2)
            self.subtitle_label.setVisible(False)
        else:
            self.setMinimumHeight(74)
            self.setMaximumHeight(86)
            self.root_layout.setContentsMargins(12, 9, 12, 9)
            self.root_layout.setSpacing(2)
            self.subtitle_label.setVisible(True)
        self._apply_style()

    def _apply_style(self) -> None:
        accent = QColor(self._accent)
        self.setStyleSheet(
            f"""
            QFrame#StorageStatCard {{
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.34);
                border-radius: 18px;
                background: rgba(4, 24, 44, 0.96);
            }}
            QLabel {{ background: transparent; }}
            """
        )
        self.title_label.setStyleSheet("color:#D7F2FF; font-size:10px; font-weight:800;")
        self.value_label.setStyleSheet("color:#F8FDFF; font-size:21px; font-weight:900;")
        self.subtitle_label.setStyleSheet("color:rgba(210,231,245,0.72); font-size:8px; font-weight:500;")


class _StorageCategoryCard(QFrame):
    clicked = pyqtSignal(str)

    def __init__(self, category_key: str, title: str, subtitle: str, icon_path: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.category_key = category_key
        self._accent = CATEGORY_ACCENTS.get(category_key, "#39D8FF")
        self._selected = False
        self._icon_pixmap = _pixmap_or_empty(icon_path)

        self.setObjectName("StorageCategoryCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(86)
        self.setMaximumHeight(94)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(10, 8, 10, 8)
        self.root_layout.setSpacing(2)

        self.top_row = QWidget(self)
        self.top_layout = QHBoxLayout(self.top_row)
        self.top_layout.setContentsMargins(0, 0, 0, 0)
        self.top_layout.setSpacing(8)

        self.icon_box = QLabel(self.top_row)
        self.icon_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_box.setMinimumSize(30, 30)
        self.icon_box.setMaximumSize(30, 30)

        self.state_chip = QLabel("Ready", self.top_row)
        self.top_layout.addWidget(self.icon_box)
        self.top_layout.addStretch(1)
        self.top_layout.addWidget(self.state_chip)

        self.title_label = QLabel(title, self)
        self.subtitle_label = QLabel(subtitle, self)
        self.subtitle_label.setWordWrap(True)
        self.meta_label = QLabel("Items 0 • Size 0 B", self)

        self.root_layout.addWidget(self.top_row)
        self.root_layout.addWidget(self.title_label)
        self.root_layout.addWidget(self.subtitle_label)
        self.root_layout.addWidget(self.meta_label)

        self._refresh_icon()
        self._apply_style()

    def _refresh_icon(self) -> None:
        if self._icon_pixmap.isNull():
            self.icon_box.clear()
            return
        scaled = self._icon_pixmap.scaled(18, 18, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.icon_box.setPixmap(scaled)

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        self._apply_style()

    def set_payload(self, *, state_text: str, subtitle: str, meta_text: str, accent_hex: str) -> None:
        self._accent = safe_str(accent_hex, self._accent) or self._accent
        self.state_chip.setText(safe_str(state_text, "Ready") or "Ready")
        self.subtitle_label.setText(safe_str(subtitle, ""))
        self.meta_label.setText(safe_str(meta_text, ""))
        self._apply_style()

    def set_compact(self, compact: bool = True, ultra: bool = False) -> None:
        if ultra:
            self.setMinimumHeight(72)
            self.setMaximumHeight(78)
            self.root_layout.setContentsMargins(9, 7, 9, 7)
            self.root_layout.setSpacing(1)
            self.subtitle_label.setVisible(False)
            self.icon_box.setMinimumSize(26, 26)
            self.icon_box.setMaximumSize(26, 26)
            self.meta_label.setStyleSheet("color:rgba(205,226,240,0.74); font-size:7px; font-weight:600; background:transparent;")
        elif compact:
            self.setMinimumHeight(78)
            self.setMaximumHeight(84)
            self.root_layout.setContentsMargins(10, 7, 10, 7)
            self.root_layout.setSpacing(1)
            self.subtitle_label.setVisible(False)
            self.icon_box.setMinimumSize(28, 28)
            self.icon_box.setMaximumSize(28, 28)
            self.meta_label.setStyleSheet("color:rgba(205,226,240,0.76); font-size:7px; font-weight:600; background:transparent;")
        else:
            self.setMinimumHeight(86)
            self.setMaximumHeight(94)
            self.root_layout.setContentsMargins(10, 8, 10, 8)
            self.root_layout.setSpacing(2)
            self.subtitle_label.setVisible(True)
            self.icon_box.setMinimumSize(30, 30)
            self.icon_box.setMaximumSize(30, 30)
            self.meta_label.setStyleSheet("color:rgba(205,226,240,0.80); font-size:8px; font-weight:600; background:transparent;")
        self._refresh_icon()
        self._apply_style()

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if event is not None and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.category_key)

    def _apply_style(self) -> None:
        accent = QColor(self._accent)
        border_alpha = 0.90 if self._selected else 0.52
        fill_alpha = 0.22 if self._selected else 0.10
        self.setStyleSheet(
            f"""
            QFrame#StorageCategoryCard {{
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, {border_alpha:.3f});
                border-radius: 18px;
                background: rgba(5, 26, 46, 0.98);
            }}
            QLabel {{ background: transparent; }}
            """
        )
        self.icon_box.setStyleSheet(
            f"border:1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.52);"
            f"border-radius:12px; background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, {fill_alpha:.3f});"
        )
        self.state_chip.setStyleSheet(
            f"color:#F8FDFF; font-size:8px; font-weight:800; padding:3px 8px;"
            f"border:1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.65);"
            f"border-radius:10px; background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.14);"
        )
        self.title_label.setStyleSheet("color:#F8FDFF; font-size:11px; font-weight:900;")
        if self.subtitle_label.isVisible():
            self.subtitle_label.setStyleSheet("color:rgba(215,233,245,0.78); font-size:8px; font-weight:500;")
        if not self.meta_label.styleSheet():
            self.meta_label.setStyleSheet("color:rgba(205,226,240,0.80); font-size:8px; font-weight:600; background:transparent;")


class _StorageSummaryCard(QFrame):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._accent = "#39D8FF"
        self.setObjectName("StorageSummaryCard")
        self.setMinimumHeight(140)
        self.setMaximumHeight(170)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(12, 10, 12, 10)
        self.root_layout.setSpacing(4)

        self.top_row = QWidget(self)
        self.top_layout = QHBoxLayout(self.top_row)
        self.top_layout.setContentsMargins(0, 0, 0, 0)
        self.top_layout.setSpacing(6)
        self.title_label = QLabel("Selected Category", self.top_row)
        self.state_chip = QLabel("Ready", self.top_row)
        self.top_layout.addWidget(self.title_label)
        self.top_layout.addStretch(1)
        self.top_layout.addWidget(self.state_chip)

        self.summary_label = QLabel("Select a category to inspect its protected storage details.", self)
        self.summary_label.setWordWrap(True)
        self.line_1 = QLabel("", self)
        self.line_2 = QLabel("", self)
        self.line_3 = QLabel("", self)
        self.line_4 = QLabel("", self)

        self.root_layout.addWidget(self.top_row)
        self.root_layout.addWidget(self.summary_label)
        self.root_layout.addWidget(self.line_1)
        self.root_layout.addWidget(self.line_2)
        self.root_layout.addWidget(self.line_3)
        self.root_layout.addWidget(self.line_4)
        self.root_layout.addStretch(1)

        self._apply_style()

    def set_payload(self, *, title: str, state_text: str, summary: str, lines: Mapping[int, str], accent_hex: str) -> None:
        self._accent = safe_str(accent_hex, "#39D8FF") or "#39D8FF"
        self.title_label.setText(safe_str(title, "Selected Category") or "Selected Category")
        self.state_chip.setText(safe_str(state_text, "Ready") or "Ready")
        self.summary_label.setText(safe_str(summary, ""))
        for idx, label in ((1, self.line_1), (2, self.line_2), (3, self.line_3), (4, self.line_4)):
            text = safe_str(lines.get(idx), "").strip()
            label.setText(f"• {text}" if text else "")
            label.setVisible(bool(text))
        self._apply_style()

    def set_compact(self, compact: bool = True, ultra: bool = False) -> None:
        if ultra:
            self.setMinimumHeight(98)
            self.setMaximumHeight(112)
            self.root_layout.setContentsMargins(10, 8, 10, 8)
            self.root_layout.setSpacing(2)
            self.line_3.setVisible(False)
            self.line_4.setVisible(False)
        elif compact:
            self.setMinimumHeight(110)
            self.setMaximumHeight(124)
            self.root_layout.setContentsMargins(10, 8, 10, 8)
            self.root_layout.setSpacing(3)
            self.line_4.setVisible(False)
        else:
            self.setMinimumHeight(140)
            self.setMaximumHeight(170)
            self.root_layout.setContentsMargins(12, 10, 12, 10)
            self.root_layout.setSpacing(4)
        self._apply_style()

    def _apply_style(self) -> None:
        accent = QColor(self._accent)
        self.setStyleSheet(
            f"""
            QFrame#StorageSummaryCard {{
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.36);
                border-radius: 18px;
                background: rgba(5, 26, 46, 0.98);
            }}
            QLabel {{ background: transparent; }}
            """
        )
        self.title_label.setStyleSheet("color:#F8FDFF; font-size:11px; font-weight:900;")
        self.state_chip.setStyleSheet(
            f"color:#F8FDFF; font-size:8px; font-weight:800; padding:4px 8px;"
            f"border:1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.65);"
            f"border-radius:10px; background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.14);"
        )
        self.summary_label.setStyleSheet("color:rgba(221,239,250,0.90); font-size:9px; font-weight:600;")
        bullet_style = "color:rgba(203,225,240,0.84); font-size:8px; font-weight:500;"
        self.line_1.setStyleSheet(bullet_style)
        self.line_2.setStyleSheet(bullet_style)
        self.line_3.setStyleSheet(bullet_style)
        self.line_4.setStyleSheet(bullet_style)


class StorageScreen(QFrame):
    back_requested = pyqtSignal()
    storage_loaded = pyqtSignal(dict)
    storage_refreshed = pyqtSignal(dict)
    storage_category_selected = pyqtSignal(str)
    backup_created = pyqtSignal(dict)
    export_created = pyqtSignal(dict)
    temp_cleared = pyqtSignal(dict)
    storage_action_requested = pyqtSignal(str)

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

        self._logger = logger.bind(component="StorageScreen")
        self.navigator = navigator
        self.app_state = app_state
        self.services = dict(services or {})
        self.animation_manager = animation_manager
        self.theme_manager = theme_manager

        self._snapshot: Dict[str, Any] = {}
        self._categories: Dict[str, Dict[str, Any]] = {}
        self._selected_category = CATEGORY_RECORDS
        self._status_message = "Storage snapshot not loaded yet."
        self._health_state = "ready"
        self._last_backup_label = "No recent backup"
        self._last_export_label = "No recent export"
        self._action_detail = "Protected storage workspace ready."
        self._compact_mode = bool(IS_COMPACT_KIOSK)
        self._ultra_compact_mode = bool(KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480)

        self._background_path = _resolve_asset("backgrounds/storage_bg.png")
        self._logo_small_path = _resolve_asset("logos/cst_logo_small.png")
        self._background_pixmap = _pixmap_or_empty(self._background_path)
        self._logo_pixmap = _pixmap_or_empty(self._logo_small_path)

        self.setObjectName("StorageScreen")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._build_ui()
        self._apply_styles()
        self._apply_responsive_layout()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(12, 9, 12, 9)
        self.root_layout.setSpacing(7)

        self.top_bar = QWidget(self)
        self.top_layout = QHBoxLayout(self.top_bar)
        self.top_layout.setContentsMargins(0, 0, 0, 0)
        self.top_layout.setSpacing(8)

        self.back_button = self._create_button("Back", role="nav", min_width=88)
        self.back_button.clicked.connect(self._handle_back_clicked)

        self.logo_badge = QLabel(self.top_bar)
        self.logo_badge.setObjectName("LogoBadge")
        self.logo_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_label_pixmap(self.logo_badge, self._logo_pixmap, 20)

        self.top_title = QLabel("Storage", self.top_bar)
        self.top_title.setObjectName("TopTitle")

        self.status_pill = QLabel("Loaded", self.top_bar)
        self.status_pill.setObjectName("RuntimePill")
        self.health_pill = QLabel("Healthy", self.top_bar)
        self.health_pill.setObjectName("RuntimePill")
        self.selected_pill = QLabel("Records", self.top_bar)
        self.selected_pill.setObjectName("RuntimePill")

        self.top_layout.addWidget(self.back_button)
        self.top_layout.addWidget(self.logo_badge)
        self.top_layout.addWidget(self.top_title)
        self.top_layout.addStretch(1)
        self.top_layout.addWidget(self.status_pill)
        self.top_layout.addWidget(self.health_pill)
        self.top_layout.addWidget(self.selected_pill)

        self.header_card = QFrame(self)
        self.header_card.setObjectName("StorageHeaderCard")
        self.header_layout = QVBoxLayout(self.header_card)
        self.header_layout.setContentsMargins(14, 9, 14, 9)
        self.header_layout.setSpacing(4)
        self.hero_title = QLabel("Protected storage maintenance", self.header_card)
        self.hero_title.setObjectName("HeroTitle")
        self.hero_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hero_subtitle = QLabel(
            "Review records, reports, exports, backups, temp files, and storage health in a clean protected workspace.",
            self.header_card,
        )
        self.hero_subtitle.setObjectName("HeroSubtitle")
        self.hero_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hero_subtitle.setWordWrap(True)
        self.header_layout.addWidget(self.hero_title)
        self.header_layout.addWidget(self.hero_subtitle)

        self.stats_row = QWidget(self)
        self.stats_layout = QHBoxLayout(self.stats_row)
        self.stats_layout.setContentsMargins(0, 0, 0, 0)
        self.stats_layout.setSpacing(7)
        self.stat_total_items = _StorageStatCard("Stored Items", self.stats_row)
        self.stat_total_size = _StorageStatCard("Estimated Size", self.stats_row)
        self.stat_db = _StorageStatCard("Database", self.stats_row)
        self.stat_health = _StorageStatCard("Storage Health", self.stats_row)
        self.stats_layout.addWidget(self.stat_total_items, 1)
        self.stats_layout.addWidget(self.stat_total_size, 1)
        self.stats_layout.addWidget(self.stat_db, 1)
        self.stats_layout.addWidget(self.stat_health, 1)

        self.content_row = QWidget(self)
        self.content_layout = QHBoxLayout(self.content_row)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(8)

        self.category_panel = QFrame(self.content_row)
        self.category_panel.setObjectName("CategoryPanel")
        self.category_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.category_layout = QVBoxLayout(self.category_panel)
        self.category_layout.setContentsMargins(10, 8, 10, 8)
        self.category_layout.setSpacing(6)
        self.category_title = QLabel("Protected Storage Categories", self.category_panel)
        self.category_title.setObjectName("SectionTitle")
        self.category_layout.addWidget(self.category_title)

        self.category_grid_widget = QWidget(self.category_panel)
        self.category_grid = QGridLayout(self.category_grid_widget)
        self.category_grid.setContentsMargins(0, 0, 0, 0)
        self.category_grid.setHorizontalSpacing(6)
        self.category_grid.setVerticalSpacing(6)
        self.category_layout.addWidget(self.category_grid_widget, 1)

        self.category_cards: Dict[str, _StorageCategoryCard] = {}
        positions = {
            CATEGORY_RECORDS: (0, 0),
            CATEGORY_REPORTS: (0, 1),
            CATEGORY_QR: (0, 2),
            CATEGORY_BACKUPS: (1, 0),
            CATEGORY_EXPORTS: (1, 1),
            CATEGORY_TEMP: (1, 2),
            CATEGORY_LOGS: (2, 0),
        }
        for category_key in CATEGORY_ORDER:
            row, col = positions[category_key]
            card = _StorageCategoryCard(
                category_key,
                CATEGORY_LABELS[category_key],
                CATEGORY_DESCRIPTIONS[category_key],
                _resolve_asset({
                    CATEGORY_RECORDS: "icons/storage.png",
                    CATEGORY_REPORTS: "icons/report.png",
                    CATEGORY_QR: "icons/qr.png",
                    CATEGORY_BACKUPS: "icons/backup.png",
                    CATEGORY_EXPORTS: "icons/export.png",
                    CATEGORY_TEMP: "icons/clear_data.png",
                    CATEGORY_LOGS: "icons/info.png",
                }.get(category_key, "icons/storage.png")),
                self.category_grid_widget,
            )
            card.clicked.connect(self._handle_category_card_clicked)
            self.category_cards[category_key] = card
            self.category_grid.addWidget(card, row, col)

        self.side_panel = QWidget(self.content_row)
        self.side_layout = QVBoxLayout(self.side_panel)
        self.side_layout.setContentsMargins(0, 0, 0, 0)
        self.side_layout.setSpacing(7)
        self.side_panel.setMinimumWidth(250)
        self.side_panel.setMaximumWidth(260)

        self.summary_card = _StorageSummaryCard(self.side_panel)
        self.side_layout.addWidget(self.summary_card)

        self.context_card = QFrame(self.side_panel)
        self.context_card.setObjectName("InfoCard")
        self.context_layout = QVBoxLayout(self.context_card)
        self.context_layout.setContentsMargins(10, 8, 10, 8)
        self.context_layout.setSpacing(4)
        self.context_title = QLabel("Storage Context", self.context_card)
        self.context_title.setObjectName("SectionTitle")
        self.context_line_1 = QLabel("Selected category: pending", self.context_card)
        self.context_line_2 = QLabel("Health state: pending", self.context_card)
        self.context_line_3 = QLabel("Last backup: pending", self.context_card)
        self.context_line_4 = QLabel("Last export: pending", self.context_card)
        self.context_note = QLabel(
            "Use backups before aggressive cleanup operations and keep temp files under control.",
            self.context_card,
        )
        self.context_note.setWordWrap(True)
        self.context_layout.addWidget(self.context_title)
        self.context_layout.addWidget(self.context_line_1)
        self.context_layout.addWidget(self.context_line_2)
        self.context_layout.addWidget(self.context_line_3)
        self.context_layout.addWidget(self.context_line_4)
        self.context_layout.addWidget(self.context_note)
        self.side_layout.addWidget(self.context_card)

        self.quick_card = QFrame(self.side_panel)
        self.quick_card.setObjectName("InfoCard")
        self.quick_layout = QVBoxLayout(self.quick_card)
        self.quick_layout.setContentsMargins(10, 8, 10, 8)
        self.quick_layout.setSpacing(5)
        self.quick_title = QLabel("Protected Actions", self.quick_card)
        self.quick_title.setObjectName("SectionTitle")
        self.quick_text = QLabel(
            "Reload storage stats, create a backup snapshot, export data, or clear temp runtime files.",
            self.quick_card,
        )
        self.quick_text.setWordWrap(True)
        self.reload_button = self._create_button("Reload", role="primary", min_width=110)
        self.reload_button.clicked.connect(self.reload_storage)
        self.backup_button = self._create_button("Backup", role="secondary", min_width=110)
        self.backup_button.clicked.connect(self._handle_backup_clicked)
        self.export_button = self._create_button("Export", role="secondary", min_width=110)
        self.export_button.clicked.connect(self._handle_export_clicked)
        self.clear_temp_button = self._create_button("Clear", role="danger", min_width=110)
        self.clear_temp_button.clicked.connect(self._handle_clear_temp_clicked)
        self.quick_layout.addWidget(self.quick_title)
        self.quick_layout.addWidget(self.quick_text)
        self.quick_layout.addWidget(self.reload_button)
        self.quick_layout.addWidget(self.backup_button)
        self.quick_layout.addWidget(self.export_button)
        self.quick_layout.addWidget(self.clear_temp_button)
        self.side_layout.addWidget(self.quick_card)
        self.side_layout.addStretch(1)

        self.content_layout.addWidget(self.category_panel, 1)
        self.content_layout.addWidget(self.side_panel, 0)

        self.action_row = QWidget(self)
        self.action_layout = QHBoxLayout(self.action_row)
        self.action_layout.setContentsMargins(0, 0, 0, 0)
        self.action_layout.setSpacing(8)
        self.bottom_reload_button = self._create_button("Reload", role="primary", min_width=110)
        self.bottom_reload_button.clicked.connect(self.reload_storage)
        self.bottom_backup_button = self._create_button("Backup", role="secondary", min_width=110)
        self.bottom_backup_button.clicked.connect(self._handle_backup_clicked)
        self.bottom_export_button = self._create_button("Export", role="secondary", min_width=110)
        self.bottom_export_button.clicked.connect(self._handle_export_clicked)
        self.bottom_clear_button = self._create_button("Clear", role="danger", min_width=110)
        self.bottom_clear_button.clicked.connect(self._handle_clear_temp_clicked)
        self.action_layout.addWidget(self.bottom_reload_button)
        self.action_layout.addStretch(1)
        self.action_layout.addWidget(self.bottom_backup_button)
        self.action_layout.addWidget(self.bottom_export_button)
        self.action_layout.addWidget(self.bottom_clear_button)

        self.root_layout.addWidget(self.top_bar)
        self.root_layout.addWidget(self.header_card)
        self.root_layout.addWidget(self.stats_row)
        self.root_layout.addWidget(self.content_row, 1)
        self.root_layout.addWidget(self.action_row)

    def _create_button(self, text: str, role: str = "primary", min_width: int = 96) -> QWidget:
        accent_map = {
            "nav": "#47C9FF",
            "primary": "#39D8FF",
            "secondary": "#67D8FF",
            "danger": "#42E393",
        }
        accent = accent_map.get(role, "#39D8FF")
        if AnimatedButton is not None:
            try:
                variant_attr = {
                    "primary": getattr(AnimatedButton, "VARIANT_PRIMARY", None),
                    "secondary": getattr(AnimatedButton, "VARIANT_SECONDARY", None),
                    "danger": getattr(AnimatedButton, "VARIANT_SUCCESS", None),
                    "nav": getattr(AnimatedButton, "VARIANT_SECONDARY", None),
                }
                btn = AnimatedButton(
                    text=text,
                    variant=variant_attr.get(role),
                    size=getattr(AnimatedButton, "SIZE_SM", None),
                    minimum_width=min_width,
                )
                try:
                    btn.set_accent_color(accent)  # type: ignore[attr-defined]
                except Exception:
                    pass
                return btn
            except Exception:
                pass
        button = QPushButton(text, self)
        button.setMinimumWidth(min_width)
        button.setMinimumHeight(36)
        button.setMaximumHeight(36)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._style_plain_button(button, accent)
        return button

    def _style_plain_button(self, button: QPushButton, accent_hex: str) -> None:
        accent = QColor(accent_hex)
        button.setStyleSheet(
            f"""
            QPushButton {{
                color: #F7FDFF;
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.56);
                border-radius: 16px;
                padding: 8px 14px;
                font-size: 11px;
                font-weight: 900;
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.14);
            }}
            QPushButton:hover {{
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.22);
            }}
            QPushButton:pressed {{
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.28);
            }}
            """
        )

    def _set_label_pixmap(self, label: QLabel, pixmap: QPixmap, target_height: int) -> None:
        if pixmap.isNull():
            label.clear()
            return
        scaled = pixmap.scaledToHeight(target_height, Qt.TransformationMode.SmoothTransformation)
        label.setPixmap(scaled)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QFrame#StorageScreen { background: transparent; }
            QLabel#LogoBadge {
                min-width: 40px; max-width: 40px; min-height: 40px; max-height: 40px;
                border-radius: 12px;
                border: 1px solid rgba(71,201,255,0.34);
                background: rgba(10, 33, 56, 0.96);
            }
            QLabel#TopTitle {
                color: #F7FDFF;
                font-size: 15px;
                font-weight: 900;
                background: transparent;
            }
            QLabel#RuntimePill {
                color: #F7FDFF;
                font-size: 10px;
                font-weight: 800;
                border-radius: 13px;
                border: 1px solid rgba(71,201,255,0.38);
                background: rgba(10, 33, 56, 0.96);
                padding: 6px 10px;
            }
            QFrame#StorageHeaderCard, QFrame#CategoryPanel, QFrame#InfoCard {
                border: 1px solid rgba(71,201,255,0.28);
                border-radius: 22px;
                background: rgba(4, 24, 44, 0.965);
            }
            QLabel#HeroTitle {
                color: #F8FDFF;
                font-size: 22px;
                font-weight: 900;
                background: transparent;
            }
            QLabel#HeroSubtitle {
                color: rgba(217,236,247,0.88);
                font-size: 9px;
                font-weight: 500;
                background: transparent;
            }
            QLabel#SectionTitle {
                color: #F8FDFF;
                font-size: 11px;
                font-weight: 900;
                background: transparent;
            }
            """
        )
        context_style = "color:rgba(213,233,245,0.84); font-size:8px; font-weight:500; background:transparent;"
        self.context_line_1.setStyleSheet(context_style)
        self.context_line_2.setStyleSheet(context_style)
        self.context_line_3.setStyleSheet(context_style)
        self.context_line_4.setStyleSheet(context_style)
        self.context_note.setStyleSheet(context_style)
        self.quick_text.setStyleSheet(context_style)

    # ------------------------------------------------------------------
    # Lifecycle / responsiveness
    # ------------------------------------------------------------------
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_responsive_layout()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_responsive_layout()
        self.reload_storage()

    def _apply_responsive_layout(self) -> None:
        width = max(1, self.width())
        height = max(1, self.height())
        ultra = width <= 820 or height <= 500 or KIOSK_WIDTH <= 800 or KIOSK_HEIGHT <= 480
        compact = ultra or width <= 920 or height <= 560 or IS_COMPACT_KIOSK
        self._compact_mode = compact
        self._ultra_compact_mode = ultra

        self.root_layout.setContentsMargins(10 if ultra else 12, 8 if ultra else 9, 10 if ultra else 12, 8 if ultra else 9)
        self.root_layout.setSpacing(6 if ultra else 7)
        self.top_layout.setSpacing(6)
        self.header_layout.setContentsMargins(12 if ultra else 14, 8 if ultra else 9, 12 if ultra else 14, 8 if ultra else 9)
        self.header_layout.setSpacing(3)
        self.stats_layout.setSpacing(6)
        self.content_layout.setSpacing(8)
        self.category_layout.setContentsMargins(10, 8, 10, 8)
        self.category_layout.setSpacing(6)
        self.category_grid.setHorizontalSpacing(6)
        self.category_grid.setVerticalSpacing(6)
        self.side_layout.setSpacing(7 if not ultra else 6)
        self.context_layout.setContentsMargins(10, 8, 10, 8)
        self.quick_layout.setContentsMargins(10, 8, 10, 8)
        self.action_layout.setSpacing(8)

        self.side_panel.setMinimumWidth(236 if ultra else 248)
        self.side_panel.setMaximumWidth(248 if ultra else 260)
        self._set_label_pixmap(self.logo_badge, self._logo_pixmap, 20 if ultra else 22)

        self.top_title.setText("Storage")
        self.status_pill.setVisible(True)
        self.health_pill.setVisible(not ultra)
        self.selected_pill.setVisible(not ultra)
        self.hero_subtitle.setVisible(not ultra)

        for stat in (self.stat_total_items, self.stat_total_size, self.stat_db, self.stat_health):
            stat.set_compact(compact, ultra)

        for card in self.category_cards.values():
            card.set_compact(compact, ultra)

        self.summary_card.set_compact(compact, ultra)
        self.context_note.setVisible(not ultra)
        self.quick_text.setVisible(not ultra)

        if ultra:
            self.context_title.setText("Preview")
            self.quick_title.setText("Actions")
            self.bottom_clear_button.setText("Clear")
            self.bottom_backup_button.setText("Backup")
            self.bottom_export_button.setText("Export")
            self.bottom_reload_button.setText("Reload")
        else:
            self.context_title.setText("Storage Context")
            self.quick_title.setText("Protected Actions")

        # Make buttons uniform and smaller for compact admin screens.
        for btn, width_value in (
            (self.back_button, 88),
            (self.reload_button, 110),
            (self.backup_button, 110),
            (self.export_button, 110),
            (self.clear_temp_button, 110),
            (self.bottom_reload_button, 110),
            (self.bottom_backup_button, 110),
            (self.bottom_export_button, 110),
            (self.bottom_clear_button, 110),
        ):
            try:
                btn.setMinimumWidth(width_value)
                btn.setMaximumHeight(36)
                btn.setMinimumHeight(36)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Loading / data normalization
    # ------------------------------------------------------------------
    def reload_storage(self) -> None:
        self._snapshot = self._load_storage_snapshot()
        self._categories = deepcopy(self._snapshot.get("categories", {}))
        self._status_message = safe_str(self._snapshot.get("status_message"), "Storage snapshot loaded.")
        self._health_state = safe_str(self._snapshot.get("health_state"), "healthy").strip().lower() or "healthy"
        self._last_backup_label = safe_str(self._snapshot.get("last_backup"), "No recent backup")
        self._last_export_label = safe_str(self._snapshot.get("last_export"), "No recent export")
        self._action_detail = safe_str(self._snapshot.get("detail"), "Protected storage snapshot loaded.")
        if self._selected_category not in self._categories:
            self._selected_category = CATEGORY_RECORDS
        self._apply_snapshot_to_ui()
        self._persist_snapshot()
        payload = self.diagnostics()
        self.storage_loaded.emit(payload)
        self.storage_refreshed.emit(payload)

    def _load_storage_snapshot(self) -> Dict[str, Any]:
        snapshot = self._build_filesystem_snapshot()

        try:
            storage_service = self.services.get("storage_service") or self.services.get("storage")
            if storage_service is not None:
                for method_name in ("snapshot", "get_snapshot", "get_storage_stats", "stats", "status", "storage_snapshot"):
                    method = getattr(storage_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method()
                            if isinstance(raw, Mapping):
                                snapshot = self._merge_service_snapshot(snapshot, dict(raw))
                                break
                        except Exception:
                            continue
        except Exception:
            pass

        try:
            database_service = self.services.get("database_service") or self.services.get("database")
            if database_service is not None:
                for method_name in ("stats", "get_stats", "snapshot", "get_snapshot", "status"):
                    method = getattr(database_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method()
                            if isinstance(raw, Mapping):
                                data = dict(raw)
                                record_count = data.get("record_count", data.get("records", data.get("row_count")))
                                if record_count not in (None, ""):
                                    snapshot["categories"][CATEGORY_RECORDS]["count"] = safe_int(record_count, snapshot["categories"][CATEGORY_RECORDS]["count"])
                                if "db_exists" in data:
                                    snapshot["db_exists"] = safe_bool(data.get("db_exists"), snapshot.get("db_exists", False))
                                if data.get("state") or data.get("status"):
                                    snapshot["db_state"] = safe_str(data.get("state", data.get("status")), snapshot.get("db_state", "healthy")).strip().lower()
                                break
                        except Exception:
                            continue
        except Exception:
            pass

        try:
            export_service = self.services.get("export_service") or self.services.get("export")
            if export_service is not None:
                for method_name in ("stats", "get_stats", "snapshot", "get_snapshot", "status"):
                    method = getattr(export_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method()
                            if isinstance(raw, Mapping):
                                data = dict(raw)
                                export_count = data.get("export_count", data.get("count", data.get("exports")))
                                if export_count not in (None, ""):
                                    snapshot["categories"][CATEGORY_EXPORTS]["count"] = safe_int(export_count, snapshot["categories"][CATEGORY_EXPORTS]["count"])
                                last_export = safe_str(data.get("last_export", data.get("last_updated", "")), "").strip()
                                if last_export:
                                    snapshot["last_export"] = last_export
                                break
                        except Exception:
                            continue
        except Exception:
            pass

        try:
            report_service = self.services.get("report_service") or self.services.get("report")
            if report_service is not None:
                for method_name in ("stats", "get_stats", "snapshot", "get_snapshot", "status"):
                    method = getattr(report_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method()
                            if isinstance(raw, Mapping):
                                data = dict(raw)
                                report_count = data.get("report_count", data.get("count", data.get("reports")))
                                if report_count not in (None, ""):
                                    snapshot["categories"][CATEGORY_REPORTS]["count"] = safe_int(report_count, snapshot["categories"][CATEGORY_REPORTS]["count"])
                                break
                        except Exception:
                            continue
        except Exception:
            pass

        self._finalize_snapshot(snapshot)
        return snapshot

    def _build_filesystem_snapshot(self) -> Dict[str, Any]:
        data_root = _data_root()
        db_dir = data_root / "db"
        db_path = db_dir / "kiosk_data.db"

        categories = {
            CATEGORY_RECORDS: self._build_category_snapshot(CATEGORY_RECORDS, db_dir, "Database-backed records and persistent session storage."),
            CATEGORY_REPORTS: self._build_category_snapshot(CATEGORY_REPORTS, data_root / "reports", CATEGORY_DESCRIPTIONS[CATEGORY_REPORTS]),
            CATEGORY_QR: self._build_category_snapshot(CATEGORY_QR, data_root / "qr", CATEGORY_DESCRIPTIONS[CATEGORY_QR]),
            CATEGORY_BACKUPS: self._build_category_snapshot(CATEGORY_BACKUPS, data_root / "backups", CATEGORY_DESCRIPTIONS[CATEGORY_BACKUPS]),
            CATEGORY_EXPORTS: self._build_category_snapshot(CATEGORY_EXPORTS, data_root / "exports", CATEGORY_DESCRIPTIONS[CATEGORY_EXPORTS]),
            CATEGORY_TEMP: self._build_category_snapshot(CATEGORY_TEMP, data_root / "temp", CATEGORY_DESCRIPTIONS[CATEGORY_TEMP]),
            CATEGORY_LOGS: self._build_category_snapshot(CATEGORY_LOGS, data_root / "logs", CATEGORY_DESCRIPTIONS[CATEGORY_LOGS]),
        }

        snapshot: Dict[str, Any] = {
            "categories": categories,
            "db_exists": db_path.exists(),
            "db_path": str(db_path),
            "db_size_bytes": int(db_path.stat().st_size) if db_path.exists() else 0,
            "db_state": "healthy" if db_path.exists() else "missing",
            "health_state": "healthy",
            "status_message": "Storage snapshot loaded from filesystem fallback.",
            "detail": "Filesystem inspection was used because service-provided stats were incomplete or unavailable.",
            "last_backup": categories[CATEGORY_BACKUPS]["last_updated"],
            "last_export": categories[CATEGORY_EXPORTS]["last_updated"],
            "total_items": 0,
            "total_size_bytes": 0,
            "total_size_text": "0 B",
        }
        self._finalize_snapshot(snapshot)
        return snapshot

    def _build_category_snapshot(self, category_key: str, directory: Path, summary: str) -> Dict[str, Any]:
        exists = directory.exists()
        count = _count_files(directory)
        size_bytes = _directory_size_bytes(directory)
        state = "available"
        detail = summary
        if not exists:
            state = "missing"
            detail = f"The {CATEGORY_LABELS.get(category_key, category_key.title())} path is missing."
        elif category_key == CATEGORY_TEMP and count > 0:
            state = "dirty"
            detail = "Temporary runtime files are present and can be cleaned."
        elif count > 0:
            state = "ready"
        else:
            state = "available"
            detail = f"No stored items are currently present in {CATEGORY_LABELS.get(category_key, category_key.title()).lower()}."
        return {
            "category_key": category_key,
            "path": str(directory),
            "exists": exists,
            "count": count,
            "size_bytes": size_bytes,
            "size_text": _format_bytes(size_bytes),
            "state": state,
            "summary": detail,
            "last_updated": _latest_file_label(directory),
        }

    def _merge_service_snapshot(self, base_snapshot: Dict[str, Any], service_data: Dict[str, Any]) -> Dict[str, Any]:
        merged = deepcopy(base_snapshot)
        categories = dict(merged.get("categories", {}))

        detail = safe_str(service_data.get("detail", service_data.get("summary", "")), "").strip()
        if detail:
            merged["detail"] = detail
        status_message = safe_str(service_data.get("status_message", service_data.get("status", "")), "").strip()
        if status_message:
            merged["status_message"] = status_message
        if service_data.get("last_backup") not in (None, ""):
            merged["last_backup"] = safe_str(service_data.get("last_backup"), "")
        if service_data.get("last_export") not in (None, ""):
            merged["last_export"] = safe_str(service_data.get("last_export"), "")
        if "db_exists" in service_data:
            merged["db_exists"] = safe_bool(service_data.get("db_exists"), merged.get("db_exists", False))
        if "db_size_bytes" in service_data:
            merged["db_size_bytes"] = safe_int(service_data.get("db_size_bytes"), merged.get("db_size_bytes", 0))
        if service_data.get("db_state") not in (None, ""):
            merged["db_state"] = safe_str(service_data.get("db_state"), merged.get("db_state", "healthy")).strip().lower()

        raw_categories = service_data.get("categories", {})
        if isinstance(raw_categories, Mapping):
            for category_key in CATEGORY_ORDER:
                raw_item = raw_categories.get(category_key)
                if isinstance(raw_item, Mapping):
                    item = dict(categories.get(category_key, {}))
                    item.update(dict(raw_item))
                    item["count"] = safe_int(item.get("count"), 0)
                    item["size_bytes"] = safe_int(item.get("size_bytes"), 0)
                    item["size_text"] = _format_bytes(item["size_bytes"])
                    item["state"] = safe_str(item.get("state"), "ready").strip().lower() or "ready"
                    item["summary"] = safe_str(item.get("summary"), CATEGORY_DESCRIPTIONS.get(category_key, "")).strip()
                    item["last_updated"] = safe_str(item.get("last_updated"), "Unknown").strip() or "Unknown"
                    categories[category_key] = item

        flat_map = {
            "record_count": CATEGORY_RECORDS,
            "records": CATEGORY_RECORDS,
            "report_count": CATEGORY_REPORTS,
            "reports": CATEGORY_REPORTS,
            "qr_count": CATEGORY_QR,
            "backup_count": CATEGORY_BACKUPS,
            "backups": CATEGORY_BACKUPS,
            "export_count": CATEGORY_EXPORTS,
            "exports": CATEGORY_EXPORTS,
            "temp_count": CATEGORY_TEMP,
            "log_count": CATEGORY_LOGS,
        }
        for key, category_key in flat_map.items():
            if key in service_data and service_data.get(key) not in (None, ""):
                item = dict(categories.get(category_key, {}))
                item["count"] = safe_int(service_data.get(key), item.get("count", 0))
                categories[category_key] = item

        merged["categories"] = categories
        return merged

    def _finalize_snapshot(self, snapshot: Dict[str, Any]) -> None:
        categories = dict(snapshot.get("categories", {}))
        total_items = 0
        total_size = 0
        has_missing = False
        dirty_temp = False

        for category_key in CATEGORY_ORDER:
            item = dict(categories.get(category_key, {}))
            count = safe_int(item.get("count"), 0)
            size_bytes = safe_int(item.get("size_bytes"), 0)
            state = safe_str(item.get("state"), "ready").strip().lower() or "ready"
            total_items += count
            total_size += size_bytes
            if state == "missing":
                has_missing = True
            if category_key == CATEGORY_TEMP and count > 0:
                dirty_temp = True
            item["count"] = count
            item["size_bytes"] = size_bytes
            item["size_text"] = _format_bytes(size_bytes)
            item["summary"] = safe_str(item.get("summary"), CATEGORY_DESCRIPTIONS.get(category_key, "")).strip() or CATEGORY_DESCRIPTIONS.get(category_key, "")
            item["last_updated"] = safe_str(item.get("last_updated"), "Unknown").strip() or "Unknown"
            item["state"] = state
            categories[category_key] = item

        db_exists = safe_bool(snapshot.get("db_exists"), False)
        if not db_exists or has_missing:
            health_state = "warning"
            status_message = "Some protected storage paths or database resources need attention."
        elif dirty_temp:
            health_state = "attention"
            status_message = "Temporary runtime files are present and should be cleaned."
        else:
            health_state = "healthy"
            status_message = "Protected storage is healthy and available."

        snapshot["categories"] = categories
        snapshot["total_items"] = total_items
        snapshot["total_size_bytes"] = total_size
        snapshot["total_size_text"] = _format_bytes(total_size)
        snapshot["health_state"] = health_state
        snapshot["status_message"] = safe_str(snapshot.get("status_message"), status_message) or status_message

    def _persist_snapshot(self) -> None:
        try:
            storage_service = self.services.get("storage_service") or self.services.get("storage")
            if storage_service is not None:
                for method_name in ("set_runtime_snapshot", "update_runtime_snapshot", "set_storage_snapshot"):
                    method = getattr(storage_service, method_name, None)
                    if callable(method):
                        try:
                            method(dict(self._snapshot))
                            break
                        except Exception:
                            continue
        except Exception:
            pass

        try:
            if self.app_state is not None:
                if hasattr(self.app_state, "storage_snapshot"):
                    setattr(self.app_state, "storage_snapshot", dict(self._snapshot))
                if hasattr(self.app_state, "selected_storage_category"):
                    setattr(self.app_state, "selected_storage_category", self._selected_category)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # UI application
    # ------------------------------------------------------------------
    def _apply_snapshot_to_ui(self) -> None:
        categories = self._categories or {}
        selected = dict(categories.get(self._selected_category, {}))
        selected_label = CATEGORY_LABELS.get(self._selected_category, self._selected_category.title())
        selected_state = safe_str(selected.get("state"), "ready").strip().lower() or "ready"
        selected_accent = _accent_for_state(selected_state, CATEGORY_ACCENTS.get(self._selected_category, "#39D8FF"))

        for category_key in CATEGORY_ORDER:
            item = dict(categories.get(category_key, {}))
            state = safe_str(item.get("state"), "ready").strip().lower() or "ready"
            accent = _accent_for_state(state, CATEGORY_ACCENTS.get(category_key, "#39D8FF"))
            meta = f"Items {safe_int(item.get('count'), 0)} • Size {safe_str(item.get('size_text'), '--')}"
            card = self.category_cards.get(category_key)
            if card is not None:
                card.set_selected(category_key == self._selected_category)
                card.set_payload(
                    state_text=state.title(),
                    subtitle=safe_str(item.get("summary"), CATEGORY_DESCRIPTIONS.get(category_key, "")),
                    meta_text=meta,
                    accent_hex=accent,
                )

        self.summary_card.set_payload(
            title=selected_label,
            state_text=selected_state.title(),
            summary=safe_str(selected.get("summary"), CATEGORY_DESCRIPTIONS.get(self._selected_category, "")),
            lines={
                1: f"Path: {safe_str(selected.get('path'), 'Unavailable')}",
                2: f"Items: {safe_int(selected.get('count'), 0)} • Size: {safe_str(selected.get('size_text'), '--')}",
                3: f"Last activity: {safe_str(selected.get('last_updated'), 'Unknown')}",
                4: self._status_message,
            },
            accent_hex=selected_accent,
        )

        total_items = safe_int(self._snapshot.get("total_items"), 0)
        total_size_text = safe_str(self._snapshot.get("total_size_text"), "--") or "--"
        db_exists = safe_bool(self._snapshot.get("db_exists"), False)
        db_size_text = _format_bytes(safe_int(self._snapshot.get("db_size_bytes"), 0))
        db_state = safe_str(self._snapshot.get("db_state"), "missing").strip().lower() or "missing"

        health_label = safe_str(self._health_state, "healthy").title()
        health_accent = _accent_for_state(self._health_state)
        self.status_pill.setText("Loaded")
        self._apply_pill_style(self.status_pill, "#42E393")
        self.health_pill.setText(health_label)
        self._apply_pill_style(self.health_pill, health_accent)
        self.selected_pill.setText(selected_label)
        self._apply_pill_style(self.selected_pill, selected_accent)

        self.stat_total_items.set_payload(
            value=str(total_items),
            subtitle="All tracked protected files and storage items.",
            accent_hex="#42E393" if total_items > 0 else "#39D8FF",
        )
        self.stat_total_size.set_payload(
            value=total_size_text,
            subtitle="Approximate protected storage footprint.",
            accent_hex="#67D8FF",
        )
        self.stat_db.set_payload(
            value="Available" if db_exists else "Missing",
            subtitle=f"SQLite database footprint: {db_size_text}",
            accent_hex=_accent_for_state(db_state),
        )
        self.stat_health.set_payload(
            value=health_label,
            subtitle=self._action_detail,
            accent_hex=health_accent,
        )

        self.context_line_1.setText(f"Selected category: {selected_label}")
        self.context_line_2.setText(f"Health state: {health_label}")
        self.context_line_3.setText(f"Last backup: {self._last_backup_label}")
        self.context_line_4.setText(f"Last export: {self._last_export_label}")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _handle_category_card_clicked(self, category_key: str) -> None:
        category = safe_str(category_key, "").strip()
        if category not in self._categories:
            return
        self._selected_category = category
        self._apply_snapshot_to_ui()
        self.storage_category_selected.emit(category)

    def _handle_backup_clicked(self) -> None:
        self.storage_action_requested.emit("backup")
        result_path = ""
        try:
            storage_service = self.services.get("storage_service") or self.services.get("storage")
            if storage_service is not None:
                for method_name in ("create_backup", "backup_database", "backup_storage", "run_backup", "export_backup"):
                    method = getattr(storage_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method()
                            if isinstance(raw, Mapping):
                                result_path = safe_str(raw.get("path", raw.get("file_path", "")), "").strip()
                            else:
                                result_path = safe_str(raw, "").strip()
                            if result_path:
                                break
                        except Exception:
                            continue
        except Exception:
            pass
        if not result_path:
            result_path = self._filesystem_backup_fallback()
        if result_path:
            self._last_backup_label = result_path
            self._status_message = "Backup snapshot created successfully."
        else:
            self._status_message = "Backup action finished, but no explicit backup path was returned."
        self.reload_storage()
        self.backup_created.emit(self.diagnostics())

    def _handle_export_clicked(self) -> None:
        self.storage_action_requested.emit("export")
        result_path = ""
        try:
            export_service = self.services.get("export_service") or self.services.get("export")
            if export_service is not None:
                for method_name in ("export_all", "export_storage", "export_sessions", "run_export", "create_export"):
                    method = getattr(export_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method()
                            if isinstance(raw, Mapping):
                                result_path = safe_str(raw.get("path", raw.get("file_path", "")), "").strip()
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
            self._last_export_label = result_path
            self._status_message = "Export action completed successfully."
        else:
            self._status_message = "Export action finished, but no explicit export path was returned."
        self.reload_storage()
        self.export_created.emit(self.diagnostics())

    def _handle_clear_temp_clicked(self) -> None:
        self.storage_action_requested.emit("clear_temp")
        cleared_count = 0
        try:
            storage_service = self.services.get("storage_service") or self.services.get("storage")
            if storage_service is not None:
                for method_name in ("clear_temp", "cleanup_temp", "clear_temp_files", "cleanup_runtime_temp"):
                    method = getattr(storage_service, method_name, None)
                    if callable(method):
                        try:
                            raw = method()
                            if isinstance(raw, Mapping):
                                cleared_count = safe_int(raw.get("count", raw.get("cleared_count", 0)), 0)
                            else:
                                cleared_count = safe_int(raw, 0)
                            break
                        except Exception:
                            continue
        except Exception:
            pass
        if cleared_count <= 0:
            cleared_count = self._filesystem_clear_temp_fallback()
        self._status_message = f"Cleared {cleared_count} temporary file(s) from the runtime."
        self.reload_storage()
        self.temp_cleared.emit(self.diagnostics())

    def _filesystem_backup_fallback(self) -> str:
        try:
            data_root = _data_root()
            db_path = data_root / "db" / "kiosk_data.db"
            backup_dir = data_root / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            if not db_path.exists():
                return ""
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = backup_dir / f"kiosk_data_backup_{timestamp}.db"
            shutil.copy2(db_path, backup_path)
            return str(backup_path)
        except Exception:
            return ""

    def _filesystem_export_fallback(self) -> str:
        try:
            export_dir = _data_root() / "exports"
            export_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            export_path = export_dir / f"storage_export_{timestamp}.json"
            payload = {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "selected_category": self._selected_category,
                "snapshot": self._snapshot,
            }
            export_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            return str(export_path)
        except Exception:
            return ""

    def _filesystem_clear_temp_fallback(self) -> int:
        count = 0
        try:
            temp_dir = _data_root() / "temp"
            if not temp_dir.exists():
                return 0
            for file_path in _iter_real_files(temp_dir):
                try:
                    file_path.unlink(missing_ok=True)
                    count += 1
                except Exception:
                    continue
        except Exception:
            return count
        return count

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Styling helpers
    # ------------------------------------------------------------------
    def _apply_pill_style(self, label: QLabel, accent_hex: str) -> None:
        accent = QColor(accent_hex)
        label.setStyleSheet(
            f"color:#F7FDFF; font-size:10px; font-weight:800; padding:6px 10px;"
            f"border:1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.56);"
            f"border-radius:13px; background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.14);"
        )

    # ------------------------------------------------------------------
    # Paint / diagnostics
    # ------------------------------------------------------------------
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
            painter.fillRect(rect, QColor(3, 15, 28, 188))
            painter.fillRect(QRectF(0.0, 0.0, float(rect.width()), rect.height() * 0.30), QColor(53, 214, 255, 14))
            painter.fillRect(QRectF(0.0, rect.height() * 0.62, float(rect.width()), rect.height() * 0.38), QColor(20, 82, 128, 16))
        finally:
            painter.end()

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "selected_category": self._selected_category,
            "snapshot": deepcopy(self._snapshot),
            "categories": deepcopy(self._categories),
            "status_message": self._status_message,
            "health_state": self._health_state,
            "last_backup_label": self._last_backup_label,
            "last_export_label": self._last_export_label,
            "detail": self._action_detail,
            "background_path": self._background_path,
            "logo_path": self._logo_small_path,
        }
