"""
screens/result_diagnosis_screen.py

Clean public diagnosis screen for the CST Health Monitoring Station kiosk.

Purpose:
- show a simple likely health remark from the active measurement session
- show parameter statuses in a clean readable layout
- show mild next-step care tips only
- remain visually separate from the results screen and admin diagnosis screen
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QBoxLayout,
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
    from core.utils import normalize_measurement_payload, safe_float, safe_str
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
            if value in (None, ""):
                return default
            return float(value)
        except Exception:
            return default

    def normalize_measurement_payload(payload: Mapping[str, Any]) -> Dict[str, float]:
        payload = dict(payload or {})
        return {
            "temperature": safe_float(payload.get("temperature"), 0.0),
            "spo2": safe_float(payload.get("spo2"), 0.0),
            "pulse_rate": safe_float(payload.get("pulse_rate", payload.get("pulse")), 0.0),
            "respiratory_rate": safe_float(payload.get("respiratory_rate", payload.get("rr")), 0.0),
            "weight": safe_float(payload.get("weight"), 0.0),
            "height": safe_float(payload.get("height"), 0.0),
            "bmi": safe_float(payload.get("bmi"), 0.0),
        }

try:
    from core.constants import SCREEN_RESULTS
except Exception:  # pragma: no cover
    SCREEN_RESULTS = "results"

try:
    from widgets.animated_button import AnimatedButton
except Exception:  # pragma: no cover
    AnimatedButton = None  # type: ignore

logger = get_logger(__name__)

METRIC_LABELS = {
    "temperature": "Temperature",
    "spo2": "SpO₂",
    "pulse_rate": "Pulse rate",
    "bmi": "BMI",
    "respiratory_rate": "Respiratory rate",
}

METRIC_UNITS = {
    "temperature": "°C",
    "spo2": "%",
    "pulse_rate": "bpm",
    "bmi": "kg/m²",
    "respiratory_rate": "breaths/min",
}


class _StatusRow(QFrame):
    def __init__(self, metric_key: str, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.metric_key = metric_key
        self.setObjectName("DiagnosisStatusRow")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(46)
        self.setMaximumHeight(46)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        self.title_label = QLabel(title, self)
        self.title_label.setObjectName("StatusRowTitle")

        self.value_label = QLabel("--", self)
        self.value_label.setObjectName("StatusRowValue")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.badge = QLabel("Normal", self)
        self.badge.setObjectName("StatusRowBadge")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setFixedWidth(84)

        layout.addWidget(self.title_label, 3)
        layout.addWidget(self.value_label, 2)
        layout.addWidget(self.badge, 0)

        self._apply_card_style("#42E393")

    def _apply_card_style(self, accent_hex: str) -> None:
        accent = QColor(accent_hex)
        self.setStyleSheet(
            f"""
            QFrame#DiagnosisStatusRow {{
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.18);
                border-radius: 14px;
                background: rgba(10, 30, 54, 0.96);
            }}
            QLabel#StatusRowTitle {{
                color: #F7FCFF;
                font-size: 12px;
                font-weight: 800;
                background: transparent;
            }}
            QLabel#StatusRowValue {{
                color: rgba(225, 239, 248, 0.95);
                font-size: 12px;
                font-weight: 700;
                background: transparent;
            }}
            QLabel#StatusRowBadge {{
                color: #F7FCFF;
                font-size: 10px;
                font-weight: 900;
                border-radius: 10px;
                padding: 4px 8px;
                border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.34);
                background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.16);
            }}
            """
        )

    def set_payload(self, value_text: str, status_text: str, accent_hex: str) -> None:
        self.value_label.setText(value_text)
        self.badge.setText(status_text)
        self._apply_card_style(accent_hex)


class _TipCard(QLabel):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("TipCard")
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setMinimumHeight(42)
        self.setMaximumHeight(52)

    def set_payload(self, text: str) -> None:
        self.setText(text)
        self.setStyleSheet(
            """
            QLabel {
                color: #F6FCFF;
                font-size: 11px;
                font-weight: 700;
                padding: 8px 12px;
                border-radius: 13px;
                border: 1px solid rgba(111, 206, 255, 0.18);
                background: rgba(18, 58, 92, 0.72);
            }
            """
        )


class ResultDiagnosisScreen(QFrame):
    back_requested = pyqtSignal()
    qr_requested = pyqtSignal(dict)
    consult_requested = pyqtSignal(dict)

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

        self._payload: Dict[str, Any] = {}
        self._diagnosis: Dict[str, Any] = {}
        self._measurements: Dict[str, float] = {}
        self._tip_cards: list[_TipCard] = []
        self._status_rows: Dict[str, _StatusRow] = {}

        self.setObjectName("ResultDiagnosisScreen")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._build_ui()
        self._apply_styles()

    def _build_ui(self) -> None:
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(14, 10, 14, 10)
        self._root_layout.setSpacing(8)

        self.top_bar = QWidget(self)
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(10)

        self.back_button = self._create_button("Back", accent="#2F8FFF", min_width=96, parent=self.top_bar)
        self.back_button.clicked.connect(self._handle_back_clicked)

        self.header_title = QLabel("Health Diagnosis", self.top_bar)
        self.header_title.setObjectName("HeaderTitle")

        self.mode_chip = QLabel("Session", self.top_bar)
        self.mode_chip.setObjectName("HeaderChip")

        self.status_chip = QLabel("Simple remark", self.top_bar)
        self.status_chip.setObjectName("HeaderChip")

        top_layout.addWidget(self.back_button)
        top_layout.addWidget(self.header_title)
        top_layout.addStretch(1)
        top_layout.addWidget(self.mode_chip)
        top_layout.addWidget(self.status_chip)

        self.hero_card = QFrame(self)
        self.hero_card.setObjectName("HeroCard")
        self.hero_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.hero_card.setMinimumHeight(168)
        self.hero_card.setMaximumHeight(190)
        hero_layout = QVBoxLayout(self.hero_card)
        hero_layout.setContentsMargins(24, 16, 24, 16)
        hero_layout.setSpacing(6)

        self.hero_title = QLabel("Likely health remark", self.hero_card)
        self.hero_title.setObjectName("HeroTitle")
        self.hero_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.hero_condition = QLabel("No clear issue seen", self.hero_card)
        self.hero_condition.setObjectName("HeroCondition")
        self.hero_condition.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hero_condition.setWordWrap(True)

        self.hero_status_line = QLabel("Temperature is Normal, SpO₂ is Normal, Pulse rate is Normal, BMI is Healthy, Respiratory rate is Normal.", self.hero_card)
        self.hero_status_line.setObjectName("HeroStatusLine")
        self.hero_status_line.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hero_status_line.setWordWrap(True)

        self.hero_note = QLabel("This is a simple kiosk remark based on the current readings.", self.hero_card)
        self.hero_note.setObjectName("HeroNote")
        self.hero_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hero_note.setWordWrap(True)

        hero_layout.addStretch(1)
        hero_layout.addWidget(self.hero_title)
        hero_layout.addWidget(self.hero_condition)
        hero_layout.addWidget(self.hero_status_line)
        hero_layout.addWidget(self.hero_note)
        hero_layout.addStretch(1)

        self.body_wrap = QWidget(self)
        self.body_layout = QHBoxLayout(self.body_wrap)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(10)

        self.status_card = QFrame(self)
        self.status_card.setObjectName("ContentCard")
        self.status_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        status_layout = QVBoxLayout(self.status_card)
        status_layout.setContentsMargins(16, 14, 16, 14)
        status_layout.setSpacing(8)

        self.status_title = QLabel("Current reading status", self.status_card)
        self.status_title.setObjectName("SectionTitle")
        self.status_hint = QLabel("Each parameter is shown as High, Low, Normal, or Healthy.", self.status_card)
        self.status_hint.setObjectName("SectionHint")
        self.status_hint.setWordWrap(True)

        status_layout.addWidget(self.status_title)
        status_layout.addWidget(self.status_hint)

        self.status_grid_host = QWidget(self.status_card)
        self.status_grid = QGridLayout(self.status_grid_host)
        self.status_grid.setContentsMargins(0, 0, 0, 0)
        self.status_grid.setHorizontalSpacing(10)
        self.status_grid.setVerticalSpacing(8)

        metric_order = ("temperature", "spo2", "pulse_rate", "bmi", "respiratory_rate")
        for index, metric_key in enumerate(metric_order):
            row = _StatusRow(metric_key, METRIC_LABELS[metric_key], self.status_card)
            self._status_rows[metric_key] = row
            self.status_grid.addWidget(row, index, 0)

        status_layout.addWidget(self.status_grid_host)
        status_layout.addStretch(1)

        self.tips_card = QFrame(self)
        self.tips_card.setObjectName("ContentCard")
        self.tips_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        tips_layout = QVBoxLayout(self.tips_card)
        tips_layout.setContentsMargins(16, 14, 16, 14)
        tips_layout.setSpacing(8)

        self.tips_title = QLabel("Simple care tips", self.tips_card)
        self.tips_title.setObjectName("SectionTitle")
        self.tips_hint = QLabel("These are gentle care suggestions only.", self.tips_card)
        self.tips_hint.setObjectName("SectionHint")
        self.tips_hint.setWordWrap(True)

        tips_layout.addWidget(self.tips_title)
        tips_layout.addWidget(self.tips_hint)

        for _ in range(3):
            tip = _TipCard(self.tips_card)
            self._tip_cards.append(tip)
            tips_layout.addWidget(tip)

        tips_layout.addStretch(1)

        self.body_layout.addWidget(self.status_card, 6)
        self.body_layout.addWidget(self.tips_card, 4)

        self.bottom_bar = QWidget(self)
        bottom_layout = QHBoxLayout(self.bottom_bar)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(10)

        self.back_results_button = self._create_button("Back to Results", accent="#E4BE57", min_width=180, parent=self.bottom_bar)
        self.back_results_button.clicked.connect(self._handle_back_clicked)

        bottom_layout.addStretch(1)
        bottom_layout.addWidget(self.back_results_button)

        self._root_layout.addWidget(self.top_bar)
        self._root_layout.addWidget(self.hero_card)
        self._root_layout.addWidget(self.body_wrap, 1)
        self._root_layout.addWidget(self.bottom_bar)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QFrame#ResultDiagnosisScreen {
                background: transparent;
            }
            QLabel#HeaderTitle {
                color: #F7FCFF;
                font-size: 17px;
                font-weight: 900;
                background: transparent;
            }
            QLabel#HeaderChip {
                color: #EEF9FF;
                font-size: 11px;
                font-weight: 800;
                padding: 8px 14px;
                border-radius: 15px;
                border: 1px solid rgba(136, 214, 255, 0.24);
                background: rgba(16, 50, 88, 0.78);
            }
            QFrame#HeroCard {
                border: 1px solid rgba(130, 212, 255, 0.18);
                border-radius: 24px;
                background: rgba(7, 30, 57, 0.98);
            }
            QFrame#ContentCard {
                border: 1px solid rgba(124, 203, 248, 0.16);
                border-radius: 22px;
                background: rgba(7, 27, 51, 0.96);
            }
            QLabel#HeroTitle {
                color: rgba(242, 249, 252, 0.98);
                font-size: 16px;
                font-weight: 800;
                background: transparent;
            }
            QLabel#HeroCondition {
                color: #7EE2FF;
                font-size: 19px;
                font-weight: 900;
                background: transparent;
            }
            QLabel#HeroStatusLine {
                color: rgba(228, 240, 247, 0.96);
                font-size: 12px;
                font-weight: 700;
                background: transparent;
            }
            QLabel#HeroNote {
                color: rgba(198, 224, 239, 0.88);
                font-size: 11px;
                font-weight: 600;
                background: transparent;
            }
            QLabel#SectionTitle {
                color: #F7FCFF;
                font-size: 15px;
                font-weight: 900;
                background: transparent;
            }
            QLabel#SectionHint {
                color: rgba(212, 233, 247, 0.86);
                font-size: 10px;
                font-weight: 600;
                background: transparent;
            }
            """
        )

    def _create_button(self, text: str, *, accent: str, min_width: int, parent: QWidget) -> QWidget:
        if AnimatedButton is not None:
            try:
                btn = AnimatedButton(
                    text=text,
                    parent=parent,
                    variant=getattr(AnimatedButton, "VARIANT_PRIMARY", None),
                    size=getattr(AnimatedButton, "SIZE_MD", getattr(AnimatedButton, "SIZE_LG", None)),
                    minimum_width=min_width,
                )
                if hasattr(btn, "setFixedWidth"):
                    btn.setFixedWidth(min_width)
                if hasattr(btn, "setFixedHeight"):
                    btn.setFixedHeight(44)
                if hasattr(btn, "set_accent_color"):
                    try:
                        btn.set_accent_color(accent)
                    except Exception:
                        pass
                return btn
            except Exception:
                pass

        button = QPushButton(text, parent)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedWidth(min_width)
        button.setFixedHeight(44)
        accent_color = QColor(accent)
        button.setStyleSheet(
            f"""
            QPushButton {{
                color: #F7FCFF;
                font-size: 13px;
                font-weight: 900;
                border-radius: 18px;
                border: 1px solid rgba({accent_color.red()}, {accent_color.green()}, {accent_color.blue()}, 0.50);
                background: rgba({accent_color.red()}, {accent_color.green()}, {accent_color.blue()}, 0.82);
                padding: 10px 18px;
            }}
            QPushButton:hover {{
                background: rgba({accent_color.red()}, {accent_color.green()}, {accent_color.blue()}, 0.95);
            }}
            """
        )
        return button

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

    def _status_for_metric(self, metric_key: str, value: float, diagnosis: Mapping[str, Any]) -> Dict[str, str]:
        combination = dict(diagnosis.get("combination_diagnosis", {}) or {})
        bands = dict(combination.get("bands", {}) or {})
        band = safe_str(bands.get(metric_key), "").strip().lower()

        if not band:
            if metric_key == "temperature":
                if value < 36.1:
                    band = "low"
                elif value > 37.0:
                    band = "high"
                else:
                    band = "normal"
            elif metric_key == "spo2":
                band = "low" if value and value < 95 else "normal"
            elif metric_key == "pulse_rate":
                if value and value < 60:
                    band = "low"
                elif value > 100:
                    band = "high"
                else:
                    band = "normal"
            elif metric_key == "respiratory_rate":
                if value and value < 12:
                    band = "low"
                elif value > 20:
                    band = "high"
                else:
                    band = "normal"
            elif metric_key == "bmi":
                if value and value < 18.5:
                    band = "low"
                elif value >= 25.0:
                    band = "high"
                else:
                    band = "normal"
            else:
                band = "normal"

        if metric_key == "bmi" and band == "normal":
            return {"status": "Healthy", "accent": "#42E393"}
        if band == "high":
            return {"status": "High", "accent": "#FFD25E"}
        if band == "low":
            return {"status": "Low", "accent": "#67D8FF"}
        return {"status": "Normal", "accent": "#42E393"}

    def _measurement_value_text(self, metric_key: str, value: float) -> str:
        unit = METRIC_UNITS.get(metric_key, "")
        if metric_key in {"temperature", "bmi"}:
            return f"{value:.1f} {unit}".strip()
        return f"{int(round(value))} {unit}".strip()

    def _default_tips(self) -> list[str]:
        return [
            "Please sit still and repeat the measurement once more.",
            "Drink water and rest for a while before checking again.",
            "Use routine follow-up if the same reading pattern keeps appearing.",
        ]

    def _load_payload_sources(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        try:
            session_service = self.services.get("session_service") or self.services.get("session")
            if session_service is not None:
                for method_name in (
                    "get_results_payload",
                    "get_current_session",
                    "get_session_payload",
                    "current_session_payload",
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
            payload = {}

        if not payload:
            try:
                if self.app_state is not None:
                    for attr_name in ("public_diagnosis_payload", "results_payload", "current_session_payload", "session_payload"):
                        raw = getattr(self.app_state, attr_name, None)
                        if isinstance(raw, Mapping):
                            payload = dict(raw)
                            if payload:
                                break
            except Exception:
                payload = {}

        return payload

    def reload_payload(self) -> None:
        payload = self._load_payload_sources()
        measurements = normalize_measurement_payload(payload.get("measurements", {}))
        diagnosis = dict(payload.get("diagnosis", {}) or {})

        try:
            diagnosis_service = self.services.get("diagnosis_service") or self.services.get("diagnosis")
            if diagnosis_service is not None and measurements:
                if not diagnosis:
                    for method_name in ("build_diagnosis", "generate_diagnosis", "diagnose", "evaluate"):
                        method = getattr(diagnosis_service, method_name, None)
                        if callable(method):
                            try:
                                raw = method(measurements, store_in_app_state=False)
                            except TypeError:
                                raw = method(measurements)
                            if isinstance(raw, Mapping):
                                diagnosis = dict(raw)
                                break
        except Exception:
            pass

        self._payload = dict(payload)
        self._payload["measurements"] = dict(measurements)
        self._payload["diagnosis"] = dict(diagnosis)
        self._measurements = dict(measurements)
        self._diagnosis = dict(diagnosis)
        self._apply_payload_to_ui()

    def reload(self) -> None:
        self.reload_payload()

    def refresh(self) -> None:
        self.reload_payload()

    def _apply_payload_to_ui(self) -> None:
        diagnosis = dict(self._diagnosis or {})
        measurements = dict(self._measurements or {})
        combination = dict(diagnosis.get("combination_diagnosis", {}) or {})

        mode_text = safe_str(self._payload.get("mode"), "session").strip().title() or "Session"
        self.mode_chip.setText(mode_text)
        self.status_chip.setText("Simple remark")

        likely_condition = safe_str(
            combination.get("likely_condition") or combination.get("label"),
            "",
        ).strip() or "No strong issue seen"

        parameter_status_text = safe_str(combination.get("parameter_status_text"), "").strip()
        if not parameter_status_text:
            ordered_keys = ("temperature", "spo2", "pulse_rate", "bmi", "respiratory_rate")
            parts = []
            for metric_key in ordered_keys:
                payload = self._status_for_metric(metric_key, safe_float(measurements.get(metric_key), 0.0), diagnosis)
                parts.append(f"{METRIC_LABELS[metric_key]} is {payload['status']}")
            parameter_status_text = ", ".join(parts) + "."

        care_note = safe_str(combination.get("care_note") or combination.get("remark"), "").strip()
        if not care_note:
            care_note = safe_str(diagnosis.get("summary"), "").strip()
        if not care_note:
            care_note = "This is a simple kiosk remark based on the current readings."

        self.hero_condition.setText(likely_condition)
        self.hero_status_line.setText(parameter_status_text)
        self.hero_note.setText(care_note)

        tips = [
            safe_str(item, "").strip()
            for item in list(combination.get("tips", []) or [])
            if safe_str(item, "").strip()
        ]
        if not tips:
            tips = [
                safe_str(item, "").strip()
                for item in list(diagnosis.get("consult_tips", []) or [])
                if safe_str(item, "").strip()
            ]
        if not tips:
            tips = self._default_tips()
        tips = tips[:3]
        while len(tips) < 3:
            fallback = self._default_tips()[len(tips)]
            if fallback not in tips:
                tips.append(fallback)
            else:
                break

        for index, tip_card in enumerate(self._tip_cards):
            text = tips[index] if index < len(tips) else ""
            tip_card.setVisible(bool(text))
            if text:
                tip_card.set_payload(text)

        for metric_key, row in self._status_rows.items():
            value = safe_float(measurements.get(metric_key), 0.0)
            status_payload = self._status_for_metric(metric_key, value, diagnosis)
            row.set_payload(
                self._measurement_value_text(metric_key, value),
                status_payload["status"],
                status_payload["accent"],
            )

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.reload_payload()
        self._apply_responsive_layout()

    def _handle_back_clicked(self) -> None:
        if self._navigate_to(SCREEN_RESULTS):
            self.back_requested.emit()
            return
        self.back_requested.emit()

    def _apply_responsive_layout(self) -> None:
        compact = self.width() <= 930 or self.height() <= 560
        if compact:
            self.hero_card.setMinimumHeight(152)
            self.hero_card.setMaximumHeight(172)
            self._root_layout.setContentsMargins(12, 8, 12, 8)
            self.body_layout.setSpacing(8)
            self.status_grid.setVerticalSpacing(6)
        else:
            self.hero_card.setMinimumHeight(168)
            self.hero_card.setMaximumHeight(190)
            self._root_layout.setContentsMargins(14, 10, 14, 10)
            self.body_layout.setSpacing(10)
        self.body_layout.setDirection(QBoxLayout.Direction.LeftToRight)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_responsive_layout()
        compact = self.width() <= 920
        for button in (self.back_button, self.back_results_button):
            if hasattr(button, "setFixedHeight"):
                try:
                    button.setFixedHeight(42 if compact else 44)
                except Exception:
                    pass

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            rect = self.rect()
            painter.fillRect(rect, QColor(3, 12, 26, 236))
            painter.fillRect(QRectF(0.0, 0.0, float(rect.width()), rect.height() * 0.28), QColor(28, 100, 160, 12))
            painter.fillRect(QRectF(0.0, rect.height() * 0.62, float(rect.width()), rect.height() * 0.38), QColor(12, 42, 76, 10))
            outer = rect.adjusted(2, 2, -2, -2)
            path = QPainterPath()
            path.addRoundedRect(QRectF(outer), 18.0, 18.0)
            painter.setPen(QColor(112, 207, 255, 24))
            painter.drawPath(path)
        finally:
            painter.end()
