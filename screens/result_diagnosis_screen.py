"""
screens/result_diagnosis_screen.py

Clean public diagnosis screen for CST Health Monitoring Station.
"""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from PyQt6.QtCore import Qt, QRectF, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.logger import get_logger

try:
    from core.utils import safe_float, safe_str
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

try:
    from core.constants import SCREEN_RESULTS, MODE_DEMO
except Exception:  # pragma: no cover
    SCREEN_RESULTS = "results"
    MODE_DEMO = "demo"

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


class DiagnosisStatusRow(QFrame):
    def __init__(self, label: str, value: str, status: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("DiagnosisStatusRow")
        self.setFixedHeight(34)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 3, 0, 3)
        layout.setSpacing(8)

        self.label_widget = QLabel(label, self)
        self.label_widget.setObjectName("StatusRowLabel")

        self.value_widget = QLabel(value, self)
        self.value_widget.setObjectName("StatusRowValue")
        self.value_widget.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.value_widget.setMinimumWidth(78)
        self.value_widget.setMaximumWidth(92)

        self.status_chip = QLabel(status, self)
        self.status_chip.setObjectName("StatusText")
        self.status_chip.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.status_chip.setFixedWidth(70)

        layout.addWidget(self.label_widget, 3)
        layout.addWidget(self.value_widget, 1)
        layout.addWidget(self.status_chip, 0)

        self.set_row(label, value, status)

    def set_row(self, label: str, value: str, status: str) -> None:
        self.label_widget.setText(label)
        self.value_widget.setText(value)
        self.setStyleSheet(
            """
            QFrame#DiagnosisStatusRow {
                border: none;
                border-bottom: 1px solid rgba(157, 220, 255, 0.10);
                background: transparent;
            }
            QLabel#StatusRowLabel, QLabel#StatusRowValue {
                background: transparent;
            }
            """
        )
        self.set_status(status)

    def set_status(self, status: str) -> None:
        status_text = safe_str(status, "Normal").strip() or "Normal"
        self.status_chip.setText(status_text)

        lower = status_text.lower()
        if "high" in lower or "elevated" in lower or "overweight" in lower or "obese" in lower:
            color = "#FFD25E"
        elif "low" in lower or "under" in lower:
            color = "#FFA461"
        else:
            color = "#42E393"

        self.status_chip.setStyleSheet(
            f"""
            QLabel {{
                color: {color};
                font-size: 12px;
                font-weight: 800;
                background: transparent;
                border: none;
                padding: 0px;
            }}
            """
        )


class SimpleTipRow(QFrame):
    def __init__(self, text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("SimpleTipRow")
        self.setFixedHeight(52)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)

        bullet = QLabel("•", self)
        bullet.setObjectName("TipBullet")
        bullet.setFixedWidth(14)
        bullet.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        self.label = QLabel(text, self)
        self.label.setObjectName("TipText")
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        layout.addWidget(bullet, 0, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.label, 1)

    def set_text(self, text: str) -> None:
        self.label.setText(text)


class ResultDiagnosisScreen(QFrame):
    back_requested = pyqtSignal()

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
        self.navigator = navigator
        self.app_state = app_state
        self.services = dict(services or {})
        self.animation_manager = animation_manager
        self.theme_manager = theme_manager

        self._diagnosis_payload: Dict[str, Any] = {}
        self._background_pixmap = QPixmap(_resolve_asset("backgrounds/results_bg.png"))
        self._logo_small_pixmap = QPixmap(_resolve_asset("logos/diagnosis-icon-editable-stroke-linear-style-sign-for-use-web-design-logo-symbol-illustration-vector-removebg-preview.png"))

        self.setObjectName("ResultDiagnosisScreen")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._build_ui()
        self._apply_styles()
        QTimer.singleShot(0, self.refresh_from_session)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 12, 18, 12)
        root.setSpacing(12)

        self.top_bar = QWidget(self)
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        self.back_button = QPushButton("Back", self.top_bar)
        self.back_button.setObjectName("BackButton")
        self.back_button.setFixedSize(100, 38)
        self.back_button.clicked.connect(self._handle_back)

        self.logo_label = QLabel(self.top_bar)
        self.logo_label.setObjectName("LogoLabel")
        self.logo_label.setFixedSize(52, 52)
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.top_title = QLabel("HEALTH DIAGNOSIS", self.top_bar)
        self.top_title.setObjectName("TopTitle")

        self.mode_pill = QLabel("Demo", self.top_bar)
        self.mode_pill.setObjectName("TopPill")
        self.mode_pill.setFixedHeight(42)
        self.mode_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.kind_pill = QLabel("Simple remark", self.top_bar)
        self.kind_pill.setObjectName("TopPill")
        self.kind_pill.setFixedHeight(42)
        self.kind_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)

        top_layout.addWidget(self.back_button, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        top_layout.addWidget(self.logo_label, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        top_layout.addWidget(self.top_title, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        top_layout.addStretch(1)
        top_layout.addWidget(self.mode_pill, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top_layout.addWidget(self.kind_pill, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.hero_card = QFrame(self)
        self.hero_card.setObjectName("HeroCard")
        self.hero_card.setFixedHeight(156)

        hero_layout = QHBoxLayout(self.hero_card)
        hero_layout.setContentsMargins(22, 16, 22, 16)
        hero_layout.setSpacing(18)

        self.hero_text_block = QWidget(self.hero_card)
        self.hero_text_block.setObjectName("HeroTextBlock")
        hero_text_layout = QVBoxLayout(self.hero_text_block)
        hero_text_layout.setContentsMargins(0, 0, 0, 0)
        hero_text_layout.setSpacing(5)

        self.hero_condition = QLabel("General Health Remark", self.hero_card)
        self.hero_condition.setObjectName("HeroCondition")
        self.hero_condition.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.hero_condition.setWordWrap(True)

        self.hero_summary = QLabel("Your readings are mostly within the expected kiosk range.", self.hero_card)
        self.hero_summary.setObjectName("HeroSummary")
        self.hero_summary.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.hero_summary.setWordWrap(True)
        self.hero_summary.setTextFormat(Qt.TextFormat.RichText)

        self.hero_detail = QLabel(
            "This session does not show a strong warning pattern from the available kiosk measurements.",
            self.hero_card,
        )
        self.hero_detail.setObjectName("HeroDetail")
        self.hero_detail.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.hero_detail.setWordWrap(True)
        self.hero_detail.setTextFormat(Qt.TextFormat.RichText)

        hero_text_layout.addWidget(self.hero_condition)
        hero_text_layout.addSpacing(2)
        hero_text_layout.addWidget(self.hero_summary)
        hero_text_layout.addWidget(self.hero_detail)
        hero_text_layout.addStretch(1)

        self.hero_overview_card = QFrame(self.hero_card)
        self.hero_overview_card.setObjectName("HeroOverviewCard")
        self.hero_overview_card.setFixedWidth(228)
        self.hero_overview_card.setMinimumWidth(228)
        hero_overview_layout = QVBoxLayout(self.hero_overview_card)
        hero_overview_layout.setContentsMargins(12, 10, 12, 10)
        hero_overview_layout.setSpacing(4)

        self.hero_overview_title = QLabel("SESSION OVERVIEW", self.hero_overview_card)
        self.hero_overview_title.setObjectName("HeroOverviewTitle")

        self.hero_mode_info = QLabel("Mode: Demo", self.hero_overview_card)
        self.hero_mode_info.setObjectName("HeroOverviewInfo")

        self.hero_state_info = QLabel("State: Mostly stable", self.hero_overview_card)
        self.hero_state_info.setObjectName("HeroOverviewInfo")

        self.hero_followup_info = QLabel("Follow-up: Routine recheck only", self.hero_overview_card)
        self.hero_followup_info.setObjectName("HeroOverviewInfo")
        self.hero_followup_info.setWordWrap(True)

        self.hero_focus_info = QLabel("Focus: Stable overall pattern", self.hero_overview_card)
        self.hero_focus_info.setObjectName("HeroOverviewInfo")
        self.hero_focus_info.setWordWrap(True)

        hero_overview_layout.addWidget(self.hero_overview_title)
        hero_overview_layout.addWidget(self.hero_mode_info)
        hero_overview_layout.addWidget(self.hero_state_info)
        hero_overview_layout.addWidget(self.hero_followup_info)
        hero_overview_layout.addWidget(self.hero_focus_info)
        hero_overview_layout.addStretch(1)

        hero_layout.addWidget(self.hero_text_block, 1)
        hero_layout.addWidget(self.hero_overview_card, 0)

        self.middle_row = QWidget(self)
        middle_layout = QHBoxLayout(self.middle_row)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(16)

        self.status_card = QFrame(self.middle_row)
        self.status_card.setObjectName("SectionCard")
        self.status_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        status_layout = QVBoxLayout(self.status_card)
        status_layout.setContentsMargins(18, 14, 18, 14)
        status_layout.setSpacing(6)

        self.status_title = QLabel("Current reading status", self.status_card)
        self.status_title.setObjectName("SectionTitle")
        self.status_subtitle = QLabel(
            "Each parameter is shown clearly as High, Low, Normal, or Healthy.",
            self.status_card,
        )
        self.status_subtitle.setObjectName("SectionSubtitle")
        self.status_subtitle.setWordWrap(True)

        self.row_temperature = DiagnosisStatusRow("Temperature", "--", "Normal", self.status_card)
        self.row_spo2 = DiagnosisStatusRow("SpO₂", "--", "Normal", self.status_card)
        self.row_pulse = DiagnosisStatusRow("Pulse rate", "--", "Normal", self.status_card)
        self.row_bmi = DiagnosisStatusRow("BMI", "--", "Normal", self.status_card)
        self.row_rr = DiagnosisStatusRow("Respiratory rate", "--", "Normal", self.status_card)

        status_layout.addWidget(self.status_title)
        status_layout.addWidget(self.status_subtitle)
        status_layout.addSpacing(2)
        status_layout.addWidget(self.row_temperature)
        status_layout.addWidget(self.row_spo2)
        status_layout.addWidget(self.row_pulse)
        status_layout.addWidget(self.row_bmi)
        status_layout.addWidget(self.row_rr)
        status_layout.addStretch(1)

        self.tips_card = QFrame(self.middle_row)
        self.tips_card.setObjectName("SectionCard")
        self.tips_card.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.tips_card.setFixedWidth(390)

        tips_layout = QVBoxLayout(self.tips_card)
        tips_layout.setContentsMargins(18, 14, 18, 14)
        tips_layout.setSpacing(6)

        self.tips_title = QLabel("Simple care tips", self.tips_card)
        self.tips_title.setObjectName("SectionTitle")
        self.tips_subtitle = QLabel("These are light follow-up suggestions only.", self.tips_card)
        self.tips_subtitle.setObjectName("SectionSubtitle")
        self.tips_subtitle.setWordWrap(True)

        self.tip_1 = SimpleTipRow("Maintain a calm posture before the next measurement.", self.tips_card)
        self.tip_2 = SimpleTipRow("Repeat the scan once if you had just moved around.", self.tips_card)
        self.tip_3 = SimpleTipRow("Use routine follow-up if the same pattern appears again.", self.tips_card)

        tips_layout.addWidget(self.tips_title)
        tips_layout.addWidget(self.tips_subtitle)
        tips_layout.addSpacing(2)
        tips_layout.addWidget(self.tip_1)
        tips_layout.addWidget(self.tip_2)
        tips_layout.addWidget(self.tip_3)
        tips_layout.addStretch(1)

        middle_layout.addWidget(self.status_card, 1)
        middle_layout.addWidget(self.tips_card, 0)

        root.addWidget(self.top_bar)
        root.addWidget(self.hero_card, 0)
        root.addWidget(self.middle_row, 1)

        if not self._logo_small_pixmap.isNull():
            self.logo_label.setPixmap(
                self._logo_small_pixmap.scaled(
                    self.logo_label.width(),
                    self.logo_label.height(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QFrame#ResultDiagnosisScreen {
                background: transparent;
            }
            QPushButton#BackButton {
                color: #F6FCFF;
                font-size: 14px;
                font-weight: 800;
                border-radius: 18px;
                border: 1px solid rgba(157, 220, 255, 0.34);
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(74, 160, 255, 0.98),
                    stop:1 rgba(34, 118, 236, 0.98)
                );
                padding: 10px 16px;
            }
            QLabel#LogoLabel {
                background: transparent;
                border: none;
            }
            QLabel#TopTitle {
                color: #F6FCFF;
                font-size: 22px;
                font-weight: 900;
                letter-spacing: 0.8px;
                background: transparent;
            }
            QLabel#TopPill {
                color: #EEF9FF;
                font-size: 12px;
                font-weight: 800;
                min-width: 100px;
                padding: 0 18px;
                border-radius: 18px;
                border: 1px solid rgba(157, 220, 255, 0.28);
                background: rgba(18, 39, 70, 0.56);
            }
            QFrame#HeroCard, QFrame#SectionCard {
                border-radius: 24px;
                border: 1px solid rgba(170, 230, 255, 0.22);
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(12, 34, 66, 0.95),
                    stop:0.52 rgba(9, 27, 56, 0.96),
                    stop:1 rgba(6, 20, 42, 0.98)
                );
            }
            QFrame#HeroOverviewCard {
                border-radius: 18px;
                border: 1px solid rgba(111, 225, 255, 0.18);
                background: rgba(10, 27, 49, 0.78);
            }
            QLabel#HeroCondition {
                color: #6FE1FF;
                font-size: 18px;
                font-weight: 900;
                background: transparent;
            }
            QLabel#HeroSummary, QLabel#HeroDetail {
                color: rgba(226, 239, 248, 0.94);
                font-size: 12px;
                font-weight: 500;
                line-height: 1.25em;
                background: transparent;
                padding: 0;
            }
            QLabel#HeroOverviewTitle {
                color: #A8F0FF;
                font-size: 11px;
                font-weight: 900;
                letter-spacing: 1px;
                background: transparent;
            }
            QLabel#HeroOverviewInfo {
                color: #F4FBFF;
                font-size: 11px;
                font-weight: 700;
                background: transparent;
                padding-bottom: 3px;
                border-bottom: 1px solid rgba(157, 220, 255, 0.10);
            }
            QLabel#SectionTitle {
                color: #F7FCFF;
                font-size: 16px;
                font-weight: 900;
                background: transparent;
            }
            QLabel#SectionSubtitle {
                color: rgba(214, 232, 246, 0.90);
                font-size: 12px;
                font-weight: 500;
                background: transparent;
            }
            QFrame#DiagnosisStatusRow, QFrame#SimpleTipRow {
                border: none;
                border-radius: 0px;
                background: transparent;
            }
            QLabel#StatusRowLabel {
                color: #F4FBFF;
                font-size: 13px;
                font-weight: 800;
                background: transparent;
            }
            QLabel#StatusRowValue {
                color: rgba(221, 239, 249, 0.92);
                font-size: 12px;
                font-weight: 600;
                background: transparent;
            }
            QLabel#TipBullet {
                color: #6FE1FF;
                font-size: 16px;
                font-weight: 900;
                background: transparent;
            }
            QLabel#TipText {
                color: #F4FBFF;
                font-size: 12px;
                font-weight: 700;
                background: transparent;
            }
            """
        )

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

            painter.fillRect(rect, QColor(4, 14, 28, 148))
            painter.fillRect(
                QRectF(0.0, 0.0, float(rect.width()), rect.height() * 0.28),
                QColor(53, 214, 255, 8),
            )
            painter.fillRect(
                QRectF(0.0, rect.height() * 0.70, float(rect.width()), rect.height() * 0.30),
                QColor(20, 82, 128, 8),
            )
        finally:
            painter.end()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        w = self.width()
        if w <= 930:
            self.tips_card.setFixedWidth(340)
            self.hero_overview_card.setFixedWidth(218)
            self.hero_overview_card.setMinimumWidth(218)
            self.hero_card.setFixedHeight(152)
        else:
            self.tips_card.setFixedWidth(390)
            self.hero_overview_card.setFixedWidth(228)
            self.hero_overview_card.setMinimumWidth(228)
            self.hero_card.setFixedHeight(156)

    def refresh_from_session(self) -> None:
        payload = self._build_payload()
        self._diagnosis_payload = payload
        self._apply_payload(payload)

    def _build_payload(self) -> Dict[str, Any]:
        session_data: Dict[str, Any] = {}
        mode = MODE_DEMO

        try:
            if self.app_state is not None:
                getter = getattr(self.app_state, "current_session", None)
                if callable(getter):
                    raw = getter()
                    if isinstance(raw, Mapping):
                        session_data.update(dict(raw))
                elif isinstance(getattr(self.app_state, "session_data", None), Mapping):
                    session_data.update(dict(getattr(self.app_state, "session_data")))
        except Exception:
            pass

        try:
            if self.app_state is not None:
                mode_value = getattr(self.app_state, "current_mode", None)
                if isinstance(mode_value, str) and mode_value.strip():
                    mode = mode_value.strip()
        except Exception:
            pass

        diagnosis_service = self.services.get("diagnosis_service") or self.services.get("diagnosis")
        diagnosis_payload: Dict[str, Any] = {}

        if diagnosis_service is not None:
            for method_name in ("build_public_diagnosis", "generate_public_diagnosis", "evaluate_public_diagnosis", "evaluate"):
                method = getattr(diagnosis_service, method_name, None)
                if callable(method):
                    try:
                        result = method(session_data)
                        if isinstance(result, Mapping):
                            diagnosis_payload = dict(result)
                            break
                    except Exception:
                        continue

        if not diagnosis_payload:
            diagnosis_payload = self._fallback_diagnosis(session_data)

        diagnosis_payload["mode"] = safe_str(mode, "demo").title() or "Demo"
        return diagnosis_payload

    def _fallback_diagnosis(self, session_data: Mapping[str, Any]) -> Dict[str, Any]:
        temp = safe_float(session_data.get("temperature"), 0.0)
        spo2 = safe_float(session_data.get("spo2"), 0.0)
        pulse = safe_float(session_data.get("pulse_rate"), 0.0)
        bmi = safe_float(session_data.get("bmi"), 0.0)
        rr = safe_float(session_data.get("respiratory_rate"), 0.0)

        temp_status = "Low" if temp and temp < 36.0 else "High" if temp >= 37.5 else "Normal"
        spo2_status = "Low" if spo2 and spo2 < 96 else "Normal"
        pulse_status = "High" if pulse >= 100 else "Low" if pulse and pulse < 60 else "Normal"
        bmi_status = "High" if bmi >= 25 else "Low" if bmi and bmi < 18.5 else "Normal"
        rr_status = "High" if rr >= 20 else "Low" if rr and rr < 12 else "Normal"

        likely = "General Health Remark"
        summary = "Your readings are mostly within the expected kiosk range."
        tips = [
            "Maintain a calm posture before the next measurement.",
            "Repeat the scan once if you had just moved around.",
            "Use routine follow-up if the same pattern appears again.",
        ]

        if temp_status == "High" and rr_status == "High":
            likely = "Possible Mild Fever Pattern"
            summary = "Temperature is raised and breathing rate is above the usual resting range. Please take extra care and rest."
            tips = [
                "Rest and drink enough fluids before repeating the scan.",
                "Avoid overexertion until you recheck the reading.",
                "Use routine follow-up if the same pattern continues.",
            ]
        elif spo2_status == "Low" and rr_status == "High":
            likely = "Possible Breathing Discomfort Pattern"
            summary = "Oxygen is lower than ideal while breathing rate is raised. Please breathe slowly and repeat the scan once calm."
            tips = [
                "Sit upright and stay still before the next measurement.",
                "Repeat the scan once if you had just moved or talked.",
                "Use routine follow-up if the same pattern appears again.",
            ]
        elif pulse_status == "High" and rr_status == "High":
            likely = "Possible Body Strain Pattern"
            summary = "Pulse and breathing rate are both above the resting range. Please rest briefly and recheck."
            tips = [
                "Rest quietly for a few minutes before measuring again.",
                "Avoid talking or moving during the next scan.",
                "Use routine follow-up if the same pattern continues.",
            ]
        elif bmi_status == "High":
            likely = "Weight Management Remark"
            summary = "BMI is above the healthy reference range. Daily activity and routine wellness follow-up may help."
            tips = [
                "Maintain regular walking or light activity.",
                "Keep a balanced eating routine.",
                "Use routine follow-up for long-term wellness review.",
            ]

        return {
            "likely_condition": likely,
            "summary_text": summary,
            "tips": tips,
            "rows": [
                {"label": "Temperature", "value": f"{temp:.1f} °C" if temp else "--", "status": temp_status},
                {"label": "SpO₂", "value": f"{int(spo2)} %" if spo2 else "--", "status": spo2_status},
                {"label": "Pulse rate", "value": f"{int(pulse)} bpm" if pulse else "--", "status": pulse_status},
                {"label": "BMI", "value": f"{bmi:.1f} kg/m²" if bmi else "--", "status": bmi_status},
                {"label": "Respiratory rate", "value": f"{int(rr)} breaths/min" if rr else "--", "status": rr_status},
            ],
        }

    def _justify_html(self, text: str) -> str:
        clean = escape(safe_str(text, "").strip())
        if not clean:
            clean = "No additional interpretation is available for this session yet."
        return f"<div style='text-align:justify;'>{clean}</div>"

    def _build_secondary_detail(self, condition: str, abnormal_count: int) -> str:
        if abnormal_count <= 0:
            return (
                "Based on the latest kiosk reading, the overall pattern appears stable. "
                "A repeat scan can still improve confidence, especially if the user had just moved, talked, or changed posture."
            )
        if abnormal_count == 1:
            return (
                f"The reading suggests a mild variation related to {condition.lower()}. "
                "A calm repeat scan is recommended before treating this as a persistent pattern."
            )
        return (
            "More than one parameter is outside the usual resting reference range. "
            "This screen should be treated as a supportive kiosk summary, and a repeat check or follow-up review is advisable if the same pattern remains."
        )

    def _apply_payload(self, payload: Mapping[str, Any]) -> None:
        mode_text = safe_str(payload.get("mode"), "Demo")
        likely_condition = safe_str(payload.get("likely_condition"), "General Health Remark")
        summary_text = safe_str(payload.get("summary_text"), "Your readings are mostly within the expected kiosk range.")

        self.mode_pill.setText(mode_text)
        self.hero_condition.setText(likely_condition)

        rows = payload.get("rows", [])
        if not isinstance(rows, list):
            rows = []

        widgets = [self.row_temperature, self.row_spo2, self.row_pulse, self.row_bmi, self.row_rr]
        defaults = [
            {"label": "Temperature", "value": "--", "status": "Normal"},
            {"label": "SpO₂", "value": "--", "status": "Normal"},
            {"label": "Pulse rate", "value": "--", "status": "Normal"},
            {"label": "BMI", "value": "--", "status": "Normal"},
            {"label": "Respiratory rate", "value": "--", "status": "Normal"},
        ]

        while len(rows) < len(defaults):
            rows.append(defaults[len(rows)])

        abnormal_count = 0
        primary_focus = "Stable overall pattern"
        for widget, row_data in zip(widgets, rows):
            if isinstance(row_data, Mapping):
                label_text = safe_str(row_data.get("label"), "--")
                value_text = safe_str(row_data.get("value"), "--")
                status_text = safe_str(row_data.get("status"), "Normal")
                widget.set_row(label_text, value_text, status_text)
                if status_text.strip().lower() not in {"normal", "healthy"}:
                    abnormal_count += 1
                    if primary_focus == "Stable overall pattern":
                        primary_focus = f"{label_text}: {status_text}"

        self.hero_summary.setText(self._justify_html(summary_text))
        self.hero_detail.setText(self._justify_html(self._build_secondary_detail(likely_condition, abnormal_count)))
        self.hero_mode_info.setText(f"Mode: {mode_text}")
        self.hero_state_info.setText(
            "State: Mostly stable" if abnormal_count == 0 else
            "State: Mild variation noted" if abnormal_count == 1 else
            "State: Multiple variations noted"
        )
        self.hero_followup_info.setText(
            "Follow-up: Routine recheck only" if abnormal_count == 0 else
            "Follow-up: Repeat scan advised" if abnormal_count == 1 else
            "Follow-up: Closer review suggested"
        )
        self.hero_focus_info.setText(f"Focus: {primary_focus}")

        tips = payload.get("tips", [])
        if not isinstance(tips, list):
            tips = []
        tips = [safe_str(item, "").strip() for item in tips if safe_str(item, "").strip()]
        while len(tips) < 3:
            tips.append("Use routine follow-up if the same pattern appears again.")

        self.tip_1.set_text(tips[0])
        self.tip_2.set_text(tips[1])
        self.tip_3.set_text(tips[2])

    def _handle_back(self) -> None:
        if self._navigate_to(SCREEN_RESULTS):
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
