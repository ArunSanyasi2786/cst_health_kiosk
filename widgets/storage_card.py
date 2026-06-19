"""
widgets/storage_card.py

Premium storage summary card widget for the CST Health Monitoring Station kiosk.

Why this file matters:
- It is the reusable storage-focused widget used by the Storage screen
- It provides a polished, self-contained visual summary of:
    - database size
    - report files
    - QR files
    - exports
    - backups
    - cleanup / maintenance readiness
- It is designed to work directly with payloads coming from:
    - services/storage_service.py
    - services/database_service.py
    - services/export_service.py
- It keeps the visual language consistent with:
    - widgets/glass_card.py
    - widgets/animated_button.py
    - widgets/glow_label.py
    - widgets/animated_progress_bar.py

Typical payloads supported:
{
    "database": {
        "record_count": 128,
        "db_size_bytes": 3145728,
        "db_size_human": "3.0 MB"
    },
    "reports": {
        "count": 22,
        "size_bytes": 1048576,
        "size_human": "1.0 MB"
    },
    "qr": {
        "count": 57,
        "size_bytes": 524288,
        "size_human": "512 KB"
    },
    "exports": {
        "count": 8,
        "size_bytes": 262144,
        "size_human": "256 KB"
    },
    "backups": {
        "count": 3,
        "size_bytes": 6291456,
        "size_human": "6.0 MB"
    },
    "temp": {
        "count": 4,
        "size_bytes": 131072,
        "size_human": "128 KB"
    },
    "logs": {
        "size_bytes": 98304,
        "size_human": "96 KB"
    },
    "totals": {
        "size_bytes": 11010048,
        "size_human": "10.5 MB"
    },
    "capacity": {
        "used_percent": 34,
        "label": "Healthy"
    },
    "maintenance": {
        "cleanup_recommended": false
    },
    "last_backup": "2026-03-11 20:20"
}

Design goals:
- premium futuristic medical dashboard feel
- very readable storage summary for admin use
- safe defaults when payloads are incomplete
- reusable for storage/admin/publish screens
- lightweight enough for Raspberry Pi kiosk deployment
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.logger import get_logger

try:
    from config import KIOSK_WIDTH, KIOSK_HEIGHT, IS_COMPACT_KIOSK
except Exception:  # pragma: no cover
    KIOSK_WIDTH = 800
    KIOSK_HEIGHT = 480
    IS_COMPACT_KIOSK = True

try:
    from core.utils import safe_float, safe_int, safe_str
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

from widgets.animated_button import AnimatedButton
from widgets.glass_card import GlassCard

try:
    from widgets.animated_progress_bar import AnimatedProgressBar
    _HAS_PROGRESS_BAR = True
except Exception:  # pragma: no cover
    AnimatedProgressBar = QWidget  # type: ignore
    _HAS_PROGRESS_BAR = False

try:
    from widgets.glow_label import GlowLabel
    _HAS_GLOW_LABEL = True
except Exception:  # pragma: no cover
    GlowLabel = QLabel  # type: ignore
    _HAS_GLOW_LABEL = False


logger = get_logger(__name__)


# ============================================================
# Theme
# ============================================================

@dataclass(frozen=True)
class StorageCardTheme:
    """
    Theme container for StorageCard.
    """
    headline_color: str = "#F5FCFF"
    summary_color: str = "rgba(219, 237, 249, 0.92)"
    subtle_text: str = "rgba(190, 214, 232, 0.82)"
    stat_value_color: str = "#F8FDFF"
    stat_label_color: str = "rgba(198, 221, 240, 0.82)"

    strip_bg: str = "rgba(38, 65, 98, 0.16)"
    strip_border: str = "rgba(150, 214, 255, 0.18)"

    chip_text: str = "#F4FCFF"
    chip_bg_alpha: float = 0.16
    chip_border_alpha: float = 0.36

    neutral_accent: str = "#7FD2FF"
    primary_accent: str = "#39D8FF"
    success_accent: str = "#3FE28F"
    warning_accent: str = "#FFD15E"
    danger_accent: str = "#FF6E88"
    offline_accent: str = "#FF7C92"

    stat_block_bg: str = "rgba(26, 47, 76, 0.24)"
    stat_block_border: str = "rgba(149, 213, 255, 0.18)"


DEFAULT_STORAGE_CARD_THEME = StorageCardTheme()


# ============================================================
# Main widget
# ============================================================

class StorageCard(GlassCard):
    """
    Premium storage summary card.

    Main capabilities:
    - total storage display
    - usage state and maintenance chip
    - optional usage progress bar
    - quick stat blocks for database / reports / QR / backups
    - status/detail text
    - backup/export/cleanup/details actions
    - direct application of storage summary payloads
    """

    backup_requested = pyqtSignal()
    export_requested = pyqtSignal()
    cleanup_requested = pyqtSignal()
    details_requested = pyqtSignal()

    state_changed = pyqtSignal(str)
    storage_payload_applied = pyqtSignal(dict)

    STATE_NEUTRAL = "neutral"
    STATE_HEALTHY = "healthy"
    STATE_WARNING = "warning"
    STATE_CRITICAL = "critical"
    STATE_ACTIVE = "active"

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        title: str = "Storage Overview",
        subtitle: str = "Database, reports, exports, QR, and backup usage",
        icon_path: str = "",
        footer: str = "",
        state: str = STATE_NEUTRAL,
        compact: bool = False,
        clickable: bool = False,
        show_progress_bar: bool = True,
        show_stat_grid: bool = True,
        show_action_row: bool = True,
        theme: Optional[StorageCardTheme] = None,
        minimum_height: int = 218,
    ) -> None:
        self._logger = logger.bind(component="StorageCard")

        self._theme = theme or DEFAULT_STORAGE_CARD_THEME
        self._compact = bool(compact or IS_COMPACT_KIOSK or KIOSK_WIDTH <= 840 or KIOSK_HEIGHT <= 500)
        self._ultra_compact = bool(KIOSK_WIDTH <= 760 or KIOSK_HEIGHT <= 460)
        self._state = safe_str(state, self.STATE_NEUTRAL).strip().lower() or self.STATE_NEUTRAL

        self._total_size_human = "--"
        self._used_percent = 0
        self._capacity_label = "Unknown"
        self._cleanup_recommended = False
        self._status_text = ""
        self._detail_text = ""
        self._last_backup_text = ""

        self._database_record_count = 0
        self._database_size_human = "--"

        self._reports_count = 0
        self._reports_size_human = "--"

        self._qr_count = 0
        self._qr_size_human = "--"

        self._exports_count = 0
        self._exports_size_human = "--"

        self._backups_count = 0
        self._backups_size_human = "--"

        self._show_progress_bar = bool(show_progress_bar)
        self._show_stat_grid = bool(show_stat_grid)
        self._show_action_row = bool(show_action_row)

        super().__init__(
            title=title,
            subtitle=subtitle,
            body="",
            footer=footer,
            icon_path=icon_path,
            parent=parent,
            accent_color=self._accent_for_state(self._state),
            minimum_height=(max(170, minimum_height - (42 if self._ultra_compact else 28)) if self._compact else minimum_height),
            clickable=clickable,
            enable_hover_effect=True,
            show_accent_bar=True,
            compact=compact,
        )

        self._build_content()
        self.set_content_widget(self._content_root)
        self.clicked.connect(self.details_requested.emit)

        self._backup_button.clicked.connect(self.backup_requested.emit)
        self._export_button.clicked.connect(self.export_requested.emit)
        self._cleanup_button.clicked.connect(self.cleanup_requested.emit)
        self._details_button.clicked.connect(self.details_requested.emit)

        self._apply_style()
        self.set_state(self._state)
        self.set_total_usage("--", 0, "Unknown")
        self.set_database_summary(0, "--")
        self.set_reports_summary(0, "--")
        self.set_qr_summary(0, "--")
        self.set_exports_summary(0, "--")
        self.set_backups_summary(0, "--")
        self.set_status_text("")
        self.set_detail_text("")
        self.set_last_backup_text("")
        self.set_cleanup_recommended(False)
        self._sync_compact_mode(KIOSK_WIDTH, KIOSK_HEIGHT)
        self._refresh_visibility()

    # ========================================================
    # UI
    # ========================================================

    def _build_content(self) -> None:
        self._content_root = QWidget(self)
        self._content_root.setObjectName("StorageCardContentRoot")

        root = QVBoxLayout(self._content_root)
        root.setContentsMargins(0, 2 if not self._compact else (1 if not self._ultra_compact else 0), 0, 0)
        root.setSpacing(8 if not self._compact else (6 if not self._ultra_compact else 5))

        # ----------------------------------------------------
        # Top row
        # ----------------------------------------------------
        self._top_row = QWidget(self._content_root)
        top_layout = QHBoxLayout(self._top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(10 if not self._compact else (8 if not self._ultra_compact else 6))

        # total block
        self._total_block = QWidget(self._top_row)
        total_layout = QVBoxLayout(self._total_block)
        total_layout.setContentsMargins(0, 0, 0, 0)
        total_layout.setSpacing(2 if not self._compact else (1 if not self._ultra_compact else 0))

        self._total_caption_label = QLabel("Total Used", self._total_block)

        if _HAS_GLOW_LABEL:
            self._total_value_label = GlowLabel(
                role=GlowLabel.ROLE_STATUS if not self._compact else GlowLabel.ROLE_SUBTITLE,
                align_center=False,
                use_outline=False,
                enable_paint_glow=True,
                initial_glow_strength=0.42,
                initial_glow_blur=15 if not self._compact else 12,
            )
        else:
            self._total_value_label = QLabel(self._total_block)

        self._capacity_text_label = QLabel(self._total_block)

        total_layout.addWidget(self._total_caption_label)
        total_layout.addWidget(self._total_value_label)
        total_layout.addWidget(self._capacity_text_label)

        # chips
        self._chip_column = QWidget(self._top_row)
        chip_layout = QVBoxLayout(self._chip_column)
        chip_layout.setContentsMargins(0, 0, 0, 0)
        chip_layout.setSpacing(5 if not self._compact else (4 if not self._ultra_compact else 3))

        self._state_chip = QLabel(self._chip_column)
        self._state_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._cleanup_chip = QLabel(self._chip_column)
        self._cleanup_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)

        chip_layout.addWidget(self._state_chip, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        chip_layout.addWidget(self._cleanup_chip, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        chip_layout.addStretch(1)

        top_layout.addWidget(self._total_block, 1)
        top_layout.addWidget(self._chip_column, 0)

        # ----------------------------------------------------
        # Progress bar
        # ----------------------------------------------------
        if _HAS_PROGRESS_BAR:
            self._usage_progress = AnimatedProgressBar(
                caption="Storage usage",
                status_text="0% used",
                show_percentage=True,
                show_status_inside_bar=True,
                show_caption=True,
                size=AnimatedProgressBar.SIZE_MD if not self._compact else AnimatedProgressBar.SIZE_SM,
                compact=self._compact,
            )
        else:
            self._usage_progress = QLabel("Storage usage unavailable", self._content_root)  # type: ignore[assignment]

        # ----------------------------------------------------
        # Stat grid
        # ----------------------------------------------------
        self._stat_grid = QWidget(self._content_root)
        grid_layout = QHBoxLayout(self._stat_grid)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setSpacing(8 if not self._compact else (6 if not self._ultra_compact else 5))

        self._db_stat = self._make_stat_block("Database")
        self._reports_stat = self._make_stat_block("Reports")
        self._qr_stat = self._make_stat_block("QR")
        self._backups_stat = self._make_stat_block("Backups")

        grid_layout.addWidget(self._db_stat["frame"])
        grid_layout.addWidget(self._reports_stat["frame"])
        grid_layout.addWidget(self._qr_stat["frame"])
        grid_layout.addWidget(self._backups_stat["frame"])

        # ----------------------------------------------------
        # Detail strip
        # ----------------------------------------------------
        self._detail_strip = QFrame(self._content_root)
        self._detail_strip.setObjectName("StorageCardDetailStrip")

        detail_layout = QVBoxLayout(self._detail_strip)
        detail_layout.setContentsMargins(10 if not self._compact else (8 if not self._ultra_compact else 7), 7 if not self._compact else (6 if not self._ultra_compact else 5), 10 if not self._compact else (8 if not self._ultra_compact else 7), 7 if not self._compact else (6 if not self._ultra_compact else 5))
        detail_layout.setSpacing(3 if not self._compact else (2 if not self._ultra_compact else 1))

        self._status_label = QLabel(self._detail_strip)
        self._status_label.setWordWrap(True)

        self._detail_label = QLabel(self._detail_strip)
        self._detail_label.setWordWrap(True)

        self._last_backup_label = QLabel(self._detail_strip)
        self._last_backup_label.setWordWrap(False)

        detail_layout.addWidget(self._status_label)
        detail_layout.addWidget(self._detail_label)
        detail_layout.addWidget(self._last_backup_label)

        # ----------------------------------------------------
        # Action row
        # ----------------------------------------------------
        self._action_row = QWidget(self._content_root)
        action_layout = QHBoxLayout(self._action_row)
        action_layout.setContentsMargins(0, 2 if not self._compact else 0, 0, 0)
        action_layout.setSpacing(8 if not self._compact else (6 if not self._ultra_compact else 5))

        self._backup_button = AnimatedButton(
            text="Backup",
            variant=AnimatedButton.VARIANT_SUCCESS,
            size=AnimatedButton.SIZE_MD if not self._compact else AnimatedButton.SIZE_SM,
            minimum_width=88 if not self._compact else (74 if not self._ultra_compact else 66),
        )
        self._export_button = AnimatedButton(
            text="Export",
            variant=AnimatedButton.VARIANT_SECONDARY,
            size=AnimatedButton.SIZE_MD if not self._compact else AnimatedButton.SIZE_SM,
            minimum_width=84 if not self._compact else (72 if not self._ultra_compact else 64),
        )
        self._cleanup_button = AnimatedButton(
            text="Cleanup",
            variant=AnimatedButton.VARIANT_GHOST,
            size=AnimatedButton.SIZE_MD if not self._compact else AnimatedButton.SIZE_SM,
            minimum_width=92 if not self._compact else (78 if not self._ultra_compact else 70),
        )
        self._details_button = AnimatedButton(
            text="Details",
            variant=AnimatedButton.VARIANT_PRIMARY,
            size=AnimatedButton.SIZE_MD if not self._compact else AnimatedButton.SIZE_SM,
            minimum_width=86 if not self._compact else (72 if not self._ultra_compact else 64),
        )

        action_layout.addWidget(self._backup_button)
        action_layout.addWidget(self._export_button)
        action_layout.addWidget(self._cleanup_button)
        action_layout.addWidget(self._details_button)
        action_layout.addStretch(1)

        root.addWidget(self._top_row)
        root.addWidget(self._usage_progress)
        root.addWidget(self._stat_grid)
        root.addWidget(self._detail_strip)
        root.addWidget(self._action_row)

    def _make_stat_block(self, title: str) -> Dict[str, QWidget]:
        frame = QFrame(self._stat_grid)
        frame.setObjectName("StorageCardStatBlock")
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8 if not self._compact else (7 if not self._ultra_compact else 6), 7 if not self._compact else (6 if not self._ultra_compact else 5), 8 if not self._compact else (7 if not self._ultra_compact else 6), 7 if not self._compact else (6 if not self._ultra_compact else 5))
        layout.setSpacing(1 if not self._compact else 0)

        title_label = QLabel(title, frame)
        title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        value_label = QLabel("--", frame)
        value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        detail_label = QLabel("--", frame)
        detail_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        detail_label.setWordWrap(False)

        layout.addWidget(title_label)
        layout.addWidget(value_label)
        layout.addWidget(detail_label)

        return {
            "frame": frame,
            "title": title_label,
            "value": value_label,
            "detail": detail_label,
        }

    # ========================================================
    # Styling
    # ========================================================

    def _accent_for_state(self, state: str) -> str:
        state = safe_str(state, self.STATE_NEUTRAL).strip().lower()
        if state == self.STATE_HEALTHY:
            return self._theme.success_accent
        if state == self.STATE_WARNING:
            return self._theme.warning_accent
        if state == self.STATE_CRITICAL:
            return self._theme.danger_accent
        if state == self.STATE_ACTIVE:
            return self._theme.primary_accent
        return self._theme.neutral_accent

    def _chip_colors(self, accent_hex: str) -> tuple[str, str, str]:
        accent = QColor(accent_hex)
        bg = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, {self._theme.chip_bg_alpha:.3f})"
        border = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, {self._theme.chip_border_alpha:.3f})"
        return bg, border, self._theme.chip_text

    def _set_chip_style(self, label: QLabel, accent_hex: str) -> None:
        bg, border, text = self._chip_colors(accent_hex)
        label.setStyleSheet(
            f"""
            QLabel {{
                color: {text};
                font-size: {'10px' if not self._compact else ('9px' if not self._ultra_compact else '8px')};
                font-weight: 700;
                border: 1px solid {border};
                border-radius: {12 if not self._compact else (10 if not self._ultra_compact else 9)}px;
                background: {bg};
                padding: {4 if not self._compact else (3 if not self._ultra_compact else 2)}px {8 if not self._compact else (6 if not self._ultra_compact else 5)}px;
            }}
            """
        )

    def _apply_style(self) -> None:
        accent = self._accent_for_state(self._state)
        self.set_accent_color(accent)

        self._total_caption_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.subtle_text};
                font-size: {'10px' if not self._compact else ('9px' if not self._ultra_compact else '8px')};
                font-weight: 700;
                background: transparent;
            }}
            """
        )

        if _HAS_GLOW_LABEL and isinstance(self._total_value_label, GlowLabel):
            self._total_value_label.set_glow_color(accent)
            self._total_value_label.set_text_color(self._theme.stat_value_color)
            self._total_value_label.set_role(GlowLabel.ROLE_STATUS if not self._compact else GlowLabel.ROLE_SUBTITLE)
        else:
            self._total_value_label.setStyleSheet(
                f"""
                QLabel {{
                    color: {self._theme.stat_value_color};
                    font-size: {'22px' if not self._compact else ('18px' if not self._ultra_compact else '16px')};
                    font-weight: 800;
                    background: transparent;
                }}
                """
            )

        self._capacity_text_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.stat_label_color};
                font-size: {'10px' if not self._compact else ('9px' if not self._ultra_compact else '8px')};
                font-weight: 600;
                background: transparent;
            }}
            """
        )

        self._set_chip_style(self._state_chip, accent)
        self._set_chip_style(
            self._cleanup_chip,
            self._theme.warning_accent if self._cleanup_recommended else self._theme.success_accent,
        )

        self._detail_strip.setStyleSheet(
            f"""
            QFrame#StorageCardDetailStrip {{
                border: 1px solid {self._theme.strip_border};
                border-radius: {14 if not self._compact else (12 if not self._ultra_compact else 10)}px;
                background: {self._theme.strip_bg};
            }}
            """
        )

        self._status_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.headline_color};
                font-size: {'10px' if not self._compact else ('9px' if not self._ultra_compact else '8px')};
                font-weight: 700;
                background: transparent;
            }}
            """
        )
        self._detail_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.summary_color};
                font-size: {'10px' if not self._compact else ('9px' if not self._ultra_compact else '8px')};
                font-weight: 500;
                background: transparent;
            }}
            """
        )
        self._last_backup_label.setStyleSheet(
            f"""
            QLabel {{
                color: {self._theme.subtle_text};
                font-size: {'9px' if not self._compact else '8px'};
                font-weight: 500;
                background: transparent;
            }}
            """
        )

        for stat in [self._db_stat, self._reports_stat, self._qr_stat, self._backups_stat]:
            stat["frame"].setStyleSheet(
                f"""
                QFrame#StorageCardStatBlock {{
                    border: 1px solid {self._theme.stat_block_border};
                    border-radius: {14 if not self._compact else (12 if not self._ultra_compact else 10)}px;
                    background: {self._theme.stat_block_bg};
                }}
                """
            )
            stat["title"].setStyleSheet(
                f"""
                QLabel {{
                    color: {self._theme.subtle_text};
                    font-size: {'9px' if not self._compact else '8px'};
                    font-weight: 700;
                    background: transparent;
                }}
                """
            )
            stat["value"].setStyleSheet(
                f"""
                QLabel {{
                    color: {self._theme.stat_value_color};
                    font-size: {'14px' if not self._compact else ('12px' if not self._ultra_compact else '11px')};
                    font-weight: 800;
                    background: transparent;
                }}
                """
            )
            stat["detail"].setStyleSheet(
                f"""
                QLabel {{
                    color: {self._theme.stat_label_color};
                    font-size: {'8px' if not self._compact else '8px'};
                    font-weight: 500;
                    background: transparent;
                }}
                """
            )

        if _HAS_PROGRESS_BAR and isinstance(self._usage_progress, AnimatedProgressBar):
            if self._state == self.STATE_HEALTHY:
                self._usage_progress.set_state(AnimatedProgressBar.STATE_SUCCESS)
            elif self._state == self.STATE_WARNING:
                self._usage_progress.set_state(AnimatedProgressBar.STATE_WARNING)
            elif self._state == self.STATE_CRITICAL:
                self._usage_progress.set_state(AnimatedProgressBar.STATE_DANGER)
            else:
                self._usage_progress.set_state(AnimatedProgressBar.STATE_PRIMARY)

        self._details_button.set_accent_color(accent)
        self._cleanup_button.set_accent_color(self._theme.warning_accent if self._cleanup_recommended else self._theme.primary_accent)

    # ========================================================
    # Visibility
    # ========================================================

    def _refresh_visibility(self) -> None:
        narrow = self.width() > 0 and self.width() <= 560
        ultra_narrow = self.width() > 0 and self.width() <= 480

        self._top_row.setVisible(True)
        self._usage_progress.setVisible(self._show_progress_bar)
        self._stat_grid.setVisible(self._show_stat_grid)
        self._detail_strip.setVisible(
            bool(self._status_text.strip())
            or bool(self._detail_text.strip())
            or bool(self._last_backup_text.strip())
        )
        self._status_label.setVisible(bool(self._status_text.strip()))
        self._detail_label.setVisible(bool(self._detail_text.strip()) and not (self._ultra_compact and narrow))
        self._last_backup_label.setVisible(bool(self._last_backup_text.strip()) and not ultra_narrow)
        self._action_row.setVisible(self._show_action_row)

        self._cleanup_chip.setVisible(not ultra_narrow)
        self._qr_stat["frame"].setVisible(not (self._ultra_compact and narrow))
        self._backup_button.setText("Backup" if not self._ultra_compact else "Save")
        self._cleanup_button.setText("Cleanup" if not self._ultra_compact else "Clean")
        self._details_button.setText("Details" if not self._ultra_compact else "Info")

    # ========================================================
    # Public state / value setters
    # ========================================================

    def set_state(self, state: str) -> None:
        normalized = safe_str(state, self.STATE_NEUTRAL).strip().lower() or self.STATE_NEUTRAL
        if normalized not in {
            self.STATE_NEUTRAL,
            self.STATE_HEALTHY,
            self.STATE_WARNING,
            self.STATE_CRITICAL,
            self.STATE_ACTIVE,
        }:
            normalized = self.STATE_NEUTRAL

        self._state = normalized

        label_map = {
            self.STATE_NEUTRAL: "Storage",
            self.STATE_HEALTHY: "Healthy",
            self.STATE_WARNING: "Review",
            self.STATE_CRITICAL: "Critical",
            self.STATE_ACTIVE: "Active",
        }
        self._state_chip.setText(label_map.get(self._state, "Storage"))
        self._apply_style()
        self.state_changed.emit(self._state)

    def state(self) -> str:
        return self._state

    def set_total_usage(self, total_size_human: str, used_percent: int, capacity_label: str = "") -> None:
        self._total_size_human = safe_str(total_size_human, "--").strip() or "--"
        self._used_percent = max(0, min(100, safe_int(used_percent, 0)))
        self._capacity_label = safe_str(capacity_label, "").strip() or f"{self._used_percent}% used"

        if _HAS_GLOW_LABEL and isinstance(self._total_value_label, GlowLabel):
            self._total_value_label.set_text(self._total_size_human)
        else:
            self._total_value_label.setText(self._total_size_human)

        self._capacity_text_label.setText(self._capacity_label)

        if _HAS_PROGRESS_BAR and isinstance(self._usage_progress, AnimatedProgressBar):
            self._usage_progress.setValue(self._used_percent)
            self._usage_progress.set_status_text(f"{self._used_percent}% used")

    def total_size_human(self) -> str:
        return self._total_size_human

    def set_cleanup_recommended(self, recommended: bool) -> None:
        self._cleanup_recommended = bool(recommended)
        self._cleanup_chip.setText("Cleanup Recommended" if self._cleanup_recommended else "Storage OK")
        self._apply_style()

    def cleanup_recommended(self) -> bool:
        return self._cleanup_recommended

    def set_status_text(self, text: str) -> None:
        self._status_text = safe_str(text, "").strip()
        self._status_label.setText(self._status_text)
        self._refresh_visibility()

    def set_detail_text(self, text: str) -> None:
        self._detail_text = safe_str(text, "").strip()
        self._detail_label.setText(self._detail_text)
        self._refresh_visibility()

    def set_last_backup_text(self, text: str) -> None:
        self._last_backup_text = safe_str(text, "").strip()
        self._last_backup_label.setText(self._last_backup_text)
        self._refresh_visibility()

    def set_database_summary(self, record_count: int, size_human: str) -> None:
        self._database_record_count = max(0, safe_int(record_count, 0))
        self._database_size_human = safe_str(size_human, "--").strip() or "--"
        self._db_stat["value"].setText(str(self._database_record_count))
        self._db_stat["detail"].setText(self._database_size_human)

    def set_reports_summary(self, count: int, size_human: str) -> None:
        self._reports_count = max(0, safe_int(count, 0))
        self._reports_size_human = safe_str(size_human, "--").strip() or "--"
        self._reports_stat["value"].setText(str(self._reports_count))
        self._reports_stat["detail"].setText(self._reports_size_human)

    def set_qr_summary(self, count: int, size_human: str) -> None:
        self._qr_count = max(0, safe_int(count, 0))
        self._qr_size_human = safe_str(size_human, "--").strip() or "--"
        self._qr_stat["value"].setText(str(self._qr_count))
        self._qr_stat["detail"].setText(self._qr_size_human)

    def set_exports_summary(self, count: int, size_human: str) -> None:
        self._exports_count = max(0, safe_int(count, 0))
        self._exports_size_human = safe_str(size_human, "--").strip() or "--"

    def set_backups_summary(self, count: int, size_human: str) -> None:
        self._backups_count = max(0, safe_int(count, 0))
        self._backups_size_human = safe_str(size_human, "--").strip() or "--"
        self._backups_stat["value"].setText(str(self._backups_count))
        self._backups_stat["detail"].setText(self._backups_size_human)

    def set_action_buttons_enabled(
        self,
        *,
        backup_enabled: bool = True,
        export_enabled: bool = True,
        cleanup_enabled: bool = True,
        details_enabled: bool = True,
    ) -> None:
        self._backup_button.setEnabled(bool(backup_enabled))
        self._export_button.setEnabled(bool(export_enabled))
        self._cleanup_button.setEnabled(bool(cleanup_enabled))
        self._details_button.setEnabled(bool(details_enabled))

    def set_show_progress_bar(self, visible: bool) -> None:
        self._show_progress_bar = bool(visible)
        self._refresh_visibility()

    def set_show_stat_grid(self, visible: bool) -> None:
        self._show_stat_grid = bool(visible)
        self._refresh_visibility()

    def set_show_action_row(self, visible: bool) -> None:
        self._show_action_row = bool(visible)
        self._refresh_visibility()

    def set_compact(self, compact: bool) -> None:
        compact = bool(compact)
        if compact == self._compact:
            return
        self._compact = compact
        self._ultra_compact = bool(compact and ((self.width() and self.width() <= 520) or KIOSK_WIDTH <= 760 or KIOSK_HEIGHT <= 460))
        self._apply_style()
        self._refresh_visibility()
        self.updateGeometry()
        self.update()

    def compact(self) -> bool:
        return bool(self._compact)

    def _sync_compact_mode(self, width: int | None = None, height: int | None = None) -> None:
        w = int(width or self.width() or KIOSK_WIDTH)
        h = int(height or self.height() or KIOSK_HEIGHT)
        compact = bool(IS_COMPACT_KIOSK or w <= 840 or h <= 500)
        self._compact = compact
        self._ultra_compact = bool(w <= 520 or h <= 420 or KIOSK_WIDTH <= 760 or KIOSK_HEIGHT <= 460)
        if hasattr(self, "_usage_progress") and _HAS_PROGRESS_BAR and isinstance(self._usage_progress, AnimatedProgressBar):
            try:
                self._usage_progress.set_compact(self._compact)
            except Exception:
                pass

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._sync_compact_mode(self.width(), self.height())
        self._refresh_visibility()

    # ========================================================
    # Composite payload integration
    # ========================================================

    def apply_storage_payload(self, payload: Mapping[str, Any]) -> None:
        """
        Apply a storage summary payload from StorageService/DatabaseService.
        """
        data = dict(payload or {})

        database = data.get("database", {})
        reports = data.get("reports", {})
        qr = data.get("qr", {})
        exports = data.get("exports", {})
        backups = data.get("backups", {})
        totals = data.get("totals", {})
        capacity = data.get("capacity", {})
        maintenance = data.get("maintenance", {})

        if not isinstance(database, Mapping):
            database = {}
        if not isinstance(reports, Mapping):
            reports = {}
        if not isinstance(qr, Mapping):
            qr = {}
        if not isinstance(exports, Mapping):
            exports = {}
        if not isinstance(backups, Mapping):
            backups = {}
        if not isinstance(totals, Mapping):
            totals = {}
        if not isinstance(capacity, Mapping):
            capacity = {}
        if not isinstance(maintenance, Mapping):
            maintenance = {}

        total_size_human = safe_str(
            totals.get("size_human"),
            safe_str(data.get("total_size_human"), "--"),
        )
        used_percent = safe_int(
            capacity.get("used_percent"),
            safe_int(data.get("used_percent"), 0),
        )
        capacity_label = safe_str(
            capacity.get("label"),
            safe_str(data.get("capacity_label"), f"{used_percent}% used"),
        )

        self.set_total_usage(total_size_human, used_percent, capacity_label)

        self.set_database_summary(
            safe_int(database.get("record_count"), safe_int(data.get("record_count"), 0)),
            safe_str(database.get("db_size_human"), safe_str(database.get("size_human"), "--")),
        )
        self.set_reports_summary(
            safe_int(reports.get("count"), 0),
            safe_str(reports.get("size_human"), "--"),
        )
        self.set_qr_summary(
            safe_int(qr.get("count"), 0),
            safe_str(qr.get("size_human"), "--"),
        )
        self.set_exports_summary(
            safe_int(exports.get("count"), 0),
            safe_str(exports.get("size_human"), "--"),
        )
        self.set_backups_summary(
            safe_int(backups.get("count"), 0),
            safe_str(backups.get("size_human"), "--"),
        )

        cleanup_recommended = bool(
            maintenance.get("cleanup_recommended", data.get("cleanup_recommended", False))
        )
        self.set_cleanup_recommended(cleanup_recommended)

        # infer state if not explicitly provided
        inferred_state = safe_str(data.get("state"), "").strip().lower()
        if inferred_state:
            self.set_state(inferred_state)
        else:
            if used_percent >= 85:
                self.set_state(self.STATE_CRITICAL)
            elif used_percent >= 60 or cleanup_recommended:
                self.set_state(self.STATE_WARNING)
            elif used_percent > 0:
                self.set_state(self.STATE_HEALTHY)
            else:
                self.set_state(self.STATE_NEUTRAL)

        status_text = safe_str(data.get("status_text"), "").strip()
        if not status_text:
            if self._state == self.STATE_CRITICAL:
                status_text = "Storage usage is critically high."
            elif self._state == self.STATE_WARNING:
                status_text = "Storage should be reviewed and cleaned soon."
            elif self._state == self.STATE_HEALTHY:
                status_text = "Storage usage is within acceptable range."
            else:
                status_text = "Storage summary is available."

        detail_text = safe_str(data.get("detail_text"), "").strip()
        if not detail_text:
            detail_text = (
                f"DB records: {self._database_record_count} • "
                f"Reports: {self._reports_count} • "
                f"QR: {self._qr_count} • "
                f"Backups: {self._backups_count}"
            )

        self.set_status_text(status_text)
        self.set_detail_text(detail_text)

        last_backup = safe_str(data.get("last_backup"), "").strip()
        if last_backup:
            self.set_last_backup_text(f"Last backup: {last_backup}")
        else:
            self.set_last_backup_text("")

        # footer can optionally show exports size or temp/logs note
        temp_payload = data.get("temp", {})
        logs_payload = data.get("logs", {})
        footer_parts = []

        if isinstance(exports, Mapping) and safe_int(exports.get("count"), 0) > 0:
            footer_parts.append(f"Exports: {safe_str(exports.get('size_human'), '--')}")
        if isinstance(temp_payload, Mapping) and safe_int(temp_payload.get("count"), 0) > 0:
            footer_parts.append(f"Temp: {safe_str(temp_payload.get('size_human'), '--')}")
        if isinstance(logs_payload, Mapping) and safe_str(logs_payload.get("size_human"), "").strip():
            footer_parts.append(f"Logs: {safe_str(logs_payload.get('size_human'), '--')}")

        super().set_footer(" • ".join(footer_parts))
        self._refresh_visibility()
        self.storage_payload_applied.emit(dict(data))

    # ========================================================
    # Diagnostics
    # ========================================================

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "state": self._state,
            "total_size_human": self._total_size_human,
            "used_percent": self._used_percent,
            "capacity_label": self._capacity_label,
            "cleanup_recommended": self._cleanup_recommended,
            "database_record_count": self._database_record_count,
            "database_size_human": self._database_size_human,
            "reports_count": self._reports_count,
            "reports_size_human": self._reports_size_human,
            "qr_count": self._qr_count,
            "qr_size_human": self._qr_size_human,
            "exports_count": self._exports_count,
            "exports_size_human": self._exports_size_human,
            "backups_count": self._backups_count,
            "backups_size_human": self._backups_size_human,
            "status_text": self._status_text,
            "detail_text": self._detail_text,
            "last_backup_text": self._last_backup_text,
            "show_progress_bar": self._show_progress_bar,
            "show_stat_grid": self._show_stat_grid,
            "show_action_row": self._show_action_row,
            "compact": self._compact,
        }