"""
services/qr_service.py

QR generation and QR-payload management service for the
CST Health Monitoring Station kiosk.

Why this file matters:
- It is the main backend for the QR screen
- It generates session-specific QR PNG files under data/qr/
- It works for both demo mode and hardware mode
- It keeps the generated QR path synchronized with AppState
- It can persist the updated session record to the database after QR generation
- It provides reusable helpers for:
    - current session QR generation
    - QR generation for a saved session from the database
    - QR listing / deletion
    - compact payload generation for quick sharing or scanning

Intended QR use in this kiosk:
- The QR code contains a compact session summary payload
- It can optionally include:
    - session_id
    - mode
    - status
    - diagnosis summary
    - dominant issue labels
    - health index
    - report path
    - measurement summary
- This keeps the QR useful even without internet access

Linked files:
- config.py
- core/app_state.py
- core/utils.py
- services/diagnosis_service.py
- services/report_service.py
- services/database_service.py
- services/session_service.py (optional consumer)

Design goals:
- stable QR generation
- compact but meaningful payload
- safe filesystem handling
- AppState synchronization after QR generation
"""

from __future__ import annotations

import html
import json
import socket
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from PyQt6.QtCore import QObject, pyqtSignal

import qrcode
from qrcode.constants import ERROR_CORRECT_M

from config import APP_NAME, APP_VERSION, PATHS
from core.app_state import AppState, get_app_state
from core.constants import (
    METRIC_BMI,
    METRIC_HEIGHT,
    METRIC_PULSE,
    METRIC_RR,
    METRIC_SPO2,
    METRIC_TEMPERATURE,
    METRIC_WEIGHT,
    SEVERITY_UNKNOWN,
)
from core.logger import get_logger, log_exception
from core.utils import (
    build_qr_path,
    deep_copy,
    ensure_directory,
    file_size_bytes,
    format_bytes,
    format_metric_value,
    json_dumps_compact,
    normalize_measurement_payload,
    now_iso,
    safe_float,
    safe_str,
)
from services.database_service import DatabaseService, get_database_service
from services.diagnosis_service import DiagnosisService, get_diagnosis_service
from services.report_service import ReportService, get_report_service

logger = get_logger(__name__)


_QR_SHARE_SERVER: Optional[ThreadingHTTPServer] = None
_QR_SHARE_SERVER_THREAD: Optional[threading.Thread] = None
_QR_SHARE_SERVER_PORT: Optional[int] = None
_QR_SHARE_SERVER_ROOT: Optional[str] = None
_QR_SHARE_SERVER_LOCK = threading.Lock()


class _QuietShareHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # pragma: no cover
        return


# ============================================================
# Dataclasses
# ============================================================

@dataclass
class QRResult:
    success: bool
    session_id: str
    qr_path: str
    size_bytes: int
    size_human: str
    message: str
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "session_id": self.session_id,
            "qr_path": self.qr_path,
            "size_bytes": self.size_bytes,
            "size_human": self.size_human,
            "message": self.message,
            "metadata": deep_copy(self.metadata),
        }


# ============================================================
# QR service
# ============================================================

class QRService(QObject):
    """
    Central QR generation service.

    Main responsibilities:
    - build compact session QR payloads
    - generate PNG QR files in data/qr/
    - attach QR path to AppState
    - optionally persist updated session to DB
    - support regeneration for saved sessions
    """

    qr_payload_built = pyqtSignal(dict)
    qr_generated = pyqtSignal(dict)
    qr_saved = pyqtSignal(str)
    qr_deleted = pyqtSignal(str)
    qr_error = pyqtSignal(str)

    def __init__(
        self,
        app_state: Optional[AppState] = None,
        diagnosis_service: Optional[DiagnosisService] = None,
        report_service: Optional[ReportService] = None,
        database_service: Optional[DatabaseService] = None,
        session_service: Optional[object] = None,
    ) -> None:
        super().__init__()

        self._logger = logger.bind(component="QRService")
        self._app_state: AppState = app_state or get_app_state()
        self._diagnosis_service: DiagnosisService = diagnosis_service or get_diagnosis_service()
        self._report_service: ReportService = report_service or get_report_service()
        self._database_service: DatabaseService = database_service or get_database_service()
        self._session_service: Optional[object] = session_service

        self._ensure_qr_dir()

    # ========================================================
    # Dependency setters
    # ========================================================

    def set_session_service(self, session_service: object) -> None:
        self._session_service = session_service

    # ========================================================
    # Basic helpers
    # ========================================================

    def _ensure_qr_dir(self) -> None:
        ensure_directory(PATHS.qr_dir)

    def _default_qr_path(self, session_id: str) -> Path:
        return build_qr_path(session_id, extension="png")

    def _current_session_id(self) -> str:
        snapshot = self._app_state.session_snapshot()
        return safe_str(snapshot.get("session_id"), "").strip()

    def _current_report_path(self) -> str:
        session = self._app_state.session_snapshot()
        return safe_str(session.get("report_path"), "").strip()

    def _share_dir(self) -> Path:
        share_dir = PATHS.data_dir / "share"
        ensure_directory(share_dir)
        return share_dir

    def _share_html_path(self, session_id: str) -> Path:
        safe_session_id = safe_str(session_id, "session").strip() or "session"
        return self._share_dir() / f"session_{safe_session_id}.html"

    def _discover_local_ip(self) -> str:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.connect(("8.8.8.8", 80))
                local_ip = safe_str(sock.getsockname()[0], "").strip()
                if local_ip and not local_ip.startswith("127."):
                    return local_ip
            finally:
                sock.close()
        except Exception:
            pass

        try:
            host_ip = socket.gethostbyname(socket.gethostname())
            host_ip = safe_str(host_ip, "").strip()
            if host_ip and not host_ip.startswith("127."):
                return host_ip
        except Exception:
            pass

        return "127.0.0.1"

    def _ensure_share_server(self) -> str:
        global _QR_SHARE_SERVER, _QR_SHARE_SERVER_THREAD, _QR_SHARE_SERVER_PORT, _QR_SHARE_SERVER_ROOT

        share_root = str(PATHS.data_dir.resolve())
        local_ip = self._discover_local_ip()

        with _QR_SHARE_SERVER_LOCK:
            if _QR_SHARE_SERVER is not None and _QR_SHARE_SERVER_PORT is not None and _QR_SHARE_SERVER_ROOT == share_root:
                return f"http://{local_ip}:{_QR_SHARE_SERVER_PORT}"

            if _QR_SHARE_SERVER is not None:
                try:
                    _QR_SHARE_SERVER.shutdown()
                except Exception:
                    pass
                try:
                    _QR_SHARE_SERVER.server_close()
                except Exception:
                    pass
                _QR_SHARE_SERVER = None
                _QR_SHARE_SERVER_THREAD = None
                _QR_SHARE_SERVER_PORT = None
                _QR_SHARE_SERVER_ROOT = None

            server = None
            chosen_port = None
            for port in range(8765, 8791):
                try:
                    handler = partial(_QuietShareHandler, directory=share_root)
                    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
                    chosen_port = port
                    break
                except OSError:
                    continue

            if server is None or chosen_port is None:
                raise RuntimeError("Unable to start local QR share server.")

            thread = threading.Thread(target=server.serve_forever, daemon=True, name="qr-share-server")
            thread.start()

            _QR_SHARE_SERVER = server
            _QR_SHARE_SERVER_THREAD = thread
            _QR_SHARE_SERVER_PORT = chosen_port
            _QR_SHARE_SERVER_ROOT = share_root

            return f"http://{local_ip}:{chosen_port}"

    def _ensure_report_for_qr(
        self,
        *,
        session_payload: Mapping[str, Any],
        measurements: Mapping[str, Any],
        diagnosis_payload: Mapping[str, Any],
        requested_report_path: str,
    ) -> str:
        report_path = safe_str(requested_report_path, "").strip()
        if report_path and Path(report_path).exists():
            return report_path

        try:
            result = self._report_service.generate_report(
                session_payload=session_payload,
                measurements=measurements,
                diagnosis_payload=diagnosis_payload,
                attach_to_app_state=True,
                persist_to_database=False,
            )
            if isinstance(result, Mapping):
                report_path = safe_str(result.get("report_path", result.get("path", result.get("file_path", ""))), "").strip()
            else:
                report_path = safe_str(result, "").strip()
        except Exception as exc:
            self._logger.warning("Unable to auto-generate report for QR: %s", exc)

        return report_path

    def _session_view_html(
        self,
        *,
        payload: Mapping[str, Any],
        report_path: str,
        qr_path: str,
    ) -> str:
        session_id = html.escape(safe_str(payload.get("session_id"), "-") or "-")
        mode = html.escape(safe_str(payload.get("mode"), "-") or "-")
        severity = html.escape(safe_str(payload.get("severity"), "unknown") or "unknown")
        status_title = html.escape(safe_str(payload.get("status_title"), "No Data") or "No Data")
        summary = html.escape(safe_str(payload.get("summary"), "No summary available.") or "No summary available.")
        generated_at = html.escape(safe_str(payload.get("generated_at"), now_iso()) or now_iso())

        measurements = payload.get("measurements", {})
        if not isinstance(measurements, Mapping):
            measurements = {}

        def metric_row(label: str, key: str, suffix: str = "") -> str:
            raw_value = measurements.get(key, "-")
            value_text = html.escape(safe_str(raw_value, "-") or "-")
            suffix_text = f" {html.escape(suffix)}" if suffix else ""
            return f"<tr><td>{html.escape(label)}</td><td>{value_text}{suffix_text}</td></tr>"

        issue_labels = payload.get("issue_labels", [])
        if not isinstance(issue_labels, list):
            issue_labels = []
        issue_html = "".join(f"<span class='chip'>{html.escape(safe_str(item, ''))}</span>" for item in issue_labels if safe_str(item, '').strip())
        if not issue_html:
            issue_html = "<span class='chip ok'>No major flags</span>"

        report_link_html = ""
        if report_path and Path(report_path).exists():
            report_name = Path(report_path).name
            report_href = f"../reports/{quote(report_name)}"
            report_link_html = f"<a class='action' href='{report_href}' target='_blank' rel='noopener'>Open PDF report</a>"

        qr_name = Path(qr_path).name if qr_path else ""
        qr_preview_html = ""
        if qr_name:
            qr_preview_html = f"<img class='qr' src='../qr/{quote(qr_name)}' alt='Session QR code' />"

        return f"""<!doctype html>
<html lang='en'>
<head>
<meta charset='utf-8' />
<meta name='viewport' content='width=device-width, initial-scale=1' />
<title>{session_id} - CST Health Monitoring Station</title>
<style>
body {{ margin:0; font-family: Arial, Helvetica, sans-serif; background:#08192c; color:#eef8ff; }}
.wrap {{ max-width: 860px; margin: 0 auto; padding: 24px 18px 40px; }}
.hero {{ background:#0d2743; border:1px solid #1d547f; border-radius:20px; padding:24px; box-shadow:0 14px 30px rgba(0,0,0,0.28); }}
.kicker {{ color:#77d6ff; font-size:12px; font-weight:700; letter-spacing:0.08em; text-transform:uppercase; margin-bottom:8px; }}
.h1 {{ font-size:30px; font-weight:800; margin:0 0 8px; }}
.sub {{ color:#c6dded; font-size:15px; margin:0; line-height:1.55; }}
.grid {{ display:grid; gap:16px; grid-template-columns: 1.15fr 0.85fr; margin-top:16px; }}
.card {{ background:#0f2b48; border:1px solid #1b517a; border-radius:18px; padding:18px; }}
.table {{ width:100%; border-collapse:collapse; margin-top:10px; }}
.table td {{ padding:10px 8px; border-bottom:1px solid rgba(120,180,220,0.18); font-size:15px; }}
.table td:first-child {{ color:#99cfe9; width:52%; }}
.badge {{ display:inline-block; padding:7px 11px; border-radius:999px; font-weight:700; font-size:12px; background:#163e60; border:1px solid #2d7aad; margin-right:8px; margin-bottom:8px; }}
.chip {{ display:inline-block; padding:8px 10px; border-radius:999px; background:#143754; color:#ebf8ff; border:1px solid #2d7aad; margin:0 8px 8px 0; font-size:12px; font-weight:700; }}
.chip.ok {{ background:#143f34; border-color:#39b980; }}
.action {{ display:inline-block; margin-top:12px; padding:12px 16px; background:#2f8fff; color:#fff; text-decoration:none; border-radius:12px; font-weight:700; }}
.qrbox {{ text-align:center; }}
.qr {{ max-width:240px; width:100%; height:auto; background:#ffffff; padding:12px; border-radius:18px; }}
.meta {{ color:#c6dded; font-size:13px; line-height:1.6; }}
@media (max-width: 760px) {{ .grid {{ grid-template-columns: 1fr; }} .h1 {{ font-size:24px; }} }}
</style>
</head>
<body>
<div class='wrap'>
  <div class='hero'>
    <div class='kicker'>CST Health Monitoring Station</div>
    <h1 class='h1'>Session Result Viewer</h1>
    <p class='sub'>This page shows the exact handoff data for the scanned kiosk session.</p>
    <div style='margin-top:14px;'>
      <span class='badge'>Session: {session_id}</span>
      <span class='badge'>Mode: {mode}</span>
      <span class='badge'>Severity: {severity}</span>
    </div>
  </div>
  <div class='grid'>
    <div class='card'>
      <h2 style='margin:0 0 8px;'>Health Summary</h2>
      <p class='sub' style='margin-bottom:6px;'><strong>{status_title}</strong></p>
      <p class='sub'>{summary}</p>
      <div style='margin-top:10px;'>{issue_html}</div>
      <table class='table'>
        {metric_row('Weight', 'weight', 'kg')}
        {metric_row('Height', 'height', 'cm')}
        {metric_row('BMI', 'bmi')}
        {metric_row('Temperature', 'temperature', '°C')}
        {metric_row('SpO2', 'spo2', '%')}
        {metric_row('Pulse Rate', 'pulse_rate', 'bpm')}
        {metric_row('Respiratory Rate', 'respiratory_rate', 'rpm')}
      </table>
      {report_link_html}
    </div>
    <div class='card qrbox'>
      <h2 style='margin:0 0 12px;'>Session QR</h2>
      {qr_preview_html}
      <p class='meta' style='margin-top:12px;'>Generated at: {generated_at}</p>
      <p class='meta'>Scan from the kiosk to reopen this session page.</p>
    </div>
  </div>
</div>
</body>
</html>"""

    def _build_share_view(
        self,
        *,
        payload: Mapping[str, Any],
        qr_path: str,
        report_path: str,
    ) -> Dict[str, str]:
        session_id = safe_str(payload.get("session_id"), "").strip()
        if not session_id:
            return {"share_html_path": "", "viewer_url": ""}

        share_html_path = self._share_html_path(session_id)
        html_text = self._session_view_html(payload=payload, report_path=report_path, qr_path=qr_path)
        ensure_directory(share_html_path.parent)
        share_html_path.write_text(html_text, encoding="utf-8")

        try:
            base_url = self._ensure_share_server().rstrip("/")
            viewer_url = f"{base_url}/share/{quote(share_html_path.name)}"
        except Exception as exc:
            self._logger.warning("Unable to prepare viewer URL for QR: %s", exc)
            viewer_url = ""

        return {
            "share_html_path": str(share_html_path),
            "viewer_url": viewer_url,
        }

    def _safe_qr_payload_text(self, payload: Mapping[str, Any]) -> str:
        """
        Convert payload to compact JSON text for QR encoding.
        """
        try:
            return json_dumps_compact(payload)
        except Exception:
            return json.dumps(dict(payload or {}), ensure_ascii=False, separators=(",", ":"))

    def _compact_measurement_payload(self, measurements: Mapping[str, Any]) -> Dict[str, Any]:
        """
        Compact measurement representation for QR payload.
        Keeps values readable but not too verbose.
        """
        normalized = normalize_measurement_payload(measurements)
        return {
            "weight": safe_float(normalized.get(METRIC_WEIGHT), 0.0),
            "height": safe_float(normalized.get(METRIC_HEIGHT), 0.0),
            "bmi": safe_float(normalized.get(METRIC_BMI), 0.0),
            "temperature": safe_float(normalized.get(METRIC_TEMPERATURE), 0.0),
            "spo2": safe_float(normalized.get(METRIC_SPO2), 0.0),
            "pulse_rate": safe_float(normalized.get(METRIC_PULSE), 0.0),
            "respiratory_rate": safe_float(normalized.get(METRIC_RR), 0.0),
        }

    def _formatted_measurement_payload(self, measurements: Mapping[str, Any]) -> Dict[str, str]:
        normalized = normalize_measurement_payload(measurements)
        return {
            METRIC_WEIGHT: format_metric_value(METRIC_WEIGHT, normalized.get(METRIC_WEIGHT), show_unit=True),
            METRIC_HEIGHT: format_metric_value(METRIC_HEIGHT, normalized.get(METRIC_HEIGHT), show_unit=True),
            METRIC_BMI: format_metric_value(METRIC_BMI, normalized.get(METRIC_BMI), show_unit=True),
            METRIC_TEMPERATURE: format_metric_value(METRIC_TEMPERATURE, normalized.get(METRIC_TEMPERATURE), show_unit=True),
            METRIC_SPO2: format_metric_value(METRIC_SPO2, normalized.get(METRIC_SPO2), show_unit=True),
            METRIC_PULSE: format_metric_value(METRIC_PULSE, normalized.get(METRIC_PULSE), show_unit=True),
            METRIC_RR: format_metric_value(METRIC_RR, normalized.get(METRIC_RR), show_unit=True),
        }

    # ========================================================
    # Payload builders
    # ========================================================

    def build_qr_payload(
        self,
        *,
        session_payload: Optional[Mapping[str, Any]] = None,
        measurements: Optional[Mapping[str, Any]] = None,
        diagnosis_payload: Optional[Mapping[str, Any]] = None,
        report_path: Optional[str] = None,
        include_measurements: bool = True,
        include_formatted_measurements: bool = False,
        include_diagnosis: bool = True,
        include_report_path: bool = True,
    ) -> Dict[str, Any]:
        """
        Build compact session summary payload for QR encoding.
        """
        if session_payload is None:
            session_payload = self._app_state.session_snapshot()

        session = dict(session_payload or {})
        session_id = safe_str(session.get("session_id"), "").strip()
        if not session_id:
            session_id = self._app_state.ensure_active_session()

        measurement_payload = normalize_measurement_payload(
            measurements if measurements is not None else self._app_state.current_measurements()
        )

        if diagnosis_payload is None:
            diagnosis_payload = self._diagnosis_service.current_diagnosis()
            if not diagnosis_payload or not diagnosis_payload.get("summary"):
                diagnosis_payload = self._diagnosis_service.build_diagnosis(
                    measurement_payload,
                    store_in_app_state=False,
                )

        diagnosis = self._diagnosis_service.current_diagnosis()
        if diagnosis_payload:
            diagnosis = deep_copy(dict(diagnosis_payload))

        if report_path is None:
            report_path = safe_str(session.get("report_path"), self._current_report_path())

        health_index = self._diagnosis_service.health_index_payload(diagnosis)

        combination = dict(diagnosis.get("combination_diagnosis", {}) or {})

        payload: Dict[str, Any] = {
            "app": APP_NAME,
            "version": APP_VERSION,
            "type": "health_kiosk_session",
            "generated_at": now_iso(),
            "session_id": session_id,
            "mode": safe_str(session.get("mode"), self._app_state.runtime_mode()),
            "status": safe_str(session.get("status"), ""),
            "status_title": safe_str(diagnosis.get("status_title"), "No Data"),
            "severity": safe_str(diagnosis.get("overall_severity"), SEVERITY_UNKNOWN),
            "summary": safe_str(diagnosis.get("summary"), ""),
            "likely_condition": safe_str(combination.get("likely_condition") or combination.get("label"), ""),
            "parameter_status_text": safe_str(combination.get("parameter_status_text"), ""),
            "issue_labels": list(diagnosis.get("issue_labels", []) or []),
            "health_index": deep_copy(health_index),
        }

        if include_report_path and report_path:
            payload["report_path"] = safe_str(report_path, "")

        if include_measurements:
            payload["measurements"] = self._compact_measurement_payload(measurement_payload)

        if include_formatted_measurements:
            payload["formatted_measurements"] = self._formatted_measurement_payload(measurement_payload)

        if include_diagnosis:
            payload["recommendations"] = list(diagnosis.get("recommendations", []) or [])[:3]
            payload["emergency_recommended"] = bool(diagnosis.get("emergency_recommended", False))

        self.qr_payload_built.emit(deep_copy(payload))
        return payload

    def build_current_session_qr_payload(
        self,
        *,
        include_measurements: bool = True,
        include_diagnosis: bool = True,
        include_report_path: bool = True,
    ) -> Dict[str, Any]:
        return self.build_qr_payload(
            session_payload=self._app_state.session_snapshot(),
            measurements=self._app_state.current_measurements(),
            diagnosis_payload=self._diagnosis_service.current_diagnosis(),
            report_path=self._current_report_path(),
            include_measurements=include_measurements,
            include_formatted_measurements=False,
            include_diagnosis=include_diagnosis,
            include_report_path=include_report_path,
        )

    def build_qr_text(
        self,
        *,
        session_payload: Optional[Mapping[str, Any]] = None,
        measurements: Optional[Mapping[str, Any]] = None,
        diagnosis_payload: Optional[Mapping[str, Any]] = None,
        report_path: Optional[str] = None,
        include_measurements: bool = True,
        include_diagnosis: bool = True,
        include_report_path: bool = True,
    ) -> str:
        payload = self.build_qr_payload(
            session_payload=session_payload,
            measurements=measurements,
            diagnosis_payload=diagnosis_payload,
            report_path=report_path,
            include_measurements=include_measurements,
            include_diagnosis=include_diagnosis,
            include_report_path=include_report_path,
        )
        return self._safe_qr_payload_text(payload)

    # ========================================================
    # QR image generation
    # ========================================================

    def generate_qr_image(
        self,
        content: str,
        output_path: str | Path,
        *,
        box_size: int = 8,
        border: int = 3,
        fill_color: str = "#0E4F8A",
        back_color: str = "white",
    ) -> Path:
        """
        Generate a QR PNG file from text content.
        """
        path = Path(output_path)
        ensure_directory(path.parent)

        qr = qrcode.QRCode(
            version=None,
            error_correction=ERROR_CORRECT_M,
            box_size=max(2, int(box_size)),
            border=max(1, int(border)),
        )
        qr.add_data(content)
        qr.make(fit=True)

        image = qr.make_image(fill_color=fill_color, back_color=back_color)
        image.save(path)
        return path

    # ========================================================
    # Public QR generation
    # ========================================================

    def generate_qr(
        self,
        *,
        session_payload: Optional[Mapping[str, Any]] = None,
        measurements: Optional[Mapping[str, Any]] = None,
        diagnosis_payload: Optional[Mapping[str, Any]] = None,
        output_path: Optional[str | Path] = None,
        attach_to_app_state: bool = True,
        persist_to_database: bool = True,
        include_measurements: bool = True,
        include_diagnosis: bool = True,
        include_report_path: bool = True,
    ) -> Dict[str, Any]:
        """
        Generic QR generation entry point.

        Updated behavior:
        - ensures a session-specific PDF exists when possible
        - builds a lightweight HTML session-view page under data/share/
        - starts a tiny local HTTP server so phones can open the scanned QR
        - falls back to compact JSON text if the viewer URL cannot be prepared
        """
        try:
            if session_payload is None:
                session_payload = self._app_state.session_snapshot()

            session = dict(session_payload or {})
            session_id = safe_str(session.get("session_id"), "").strip()
            if not session_id:
                session_id = self._app_state.ensure_active_session()
                session["session_id"] = session_id

            measurement_payload = normalize_measurement_payload(
                measurements if measurements is not None else self._app_state.current_measurements()
            )

            if diagnosis_payload is None:
                diagnosis_payload = self._diagnosis_service.current_diagnosis()
                if not diagnosis_payload or not diagnosis_payload.get("summary"):
                    diagnosis_payload = self._diagnosis_service.build_diagnosis(
                        measurement_payload,
                        store_in_app_state=False,
                    )

            diagnosis_payload = dict(diagnosis_payload or {})
            report_path = safe_str(session.get("report_path"), self._current_report_path()).strip()
            if include_report_path:
                report_path = self._ensure_report_for_qr(
                    session_payload=session,
                    measurements=measurement_payload,
                    diagnosis_payload=diagnosis_payload,
                    requested_report_path=report_path,
                )

            payload = self.build_qr_payload(
                session_payload=session,
                measurements=measurement_payload,
                diagnosis_payload=diagnosis_payload,
                report_path=report_path,
                include_measurements=include_measurements,
                include_formatted_measurements=False,
                include_diagnosis=include_diagnosis,
                include_report_path=include_report_path,
            )

            qr_path = Path(output_path) if output_path is not None else self._default_qr_path(session_id)
            share_info = {"share_html_path": "", "viewer_url": ""}
            qr_text = ""
            content_kind = "json"

            temp_qr_text = self._safe_qr_payload_text(payload)
            temp_saved_path = self.generate_qr_image(temp_qr_text, qr_path)
            try:
                share_info = self._build_share_view(payload=payload, qr_path=str(temp_saved_path), report_path=report_path)
            except Exception as exc:
                self._logger.warning("Unable to build share view for QR: %s", exc)
                share_info = {"share_html_path": "", "viewer_url": ""}

            viewer_url = safe_str(share_info.get("viewer_url"), "").strip()
            share_html_path = safe_str(share_info.get("share_html_path"), "").strip()

            if viewer_url:
                qr_text = viewer_url
                content_kind = "url"
            else:
                qr_text = temp_qr_text
                content_kind = "json"

            saved_path = self.generate_qr_image(qr_text, qr_path)

            if share_html_path:
                try:
                    refreshed_share_info = self._build_share_view(payload=payload, qr_path=str(saved_path), report_path=report_path)
                    if refreshed_share_info.get("viewer_url"):
                        viewer_url = safe_str(refreshed_share_info.get("viewer_url"), "").strip()
                    if refreshed_share_info.get("share_html_path"):
                        share_html_path = safe_str(refreshed_share_info.get("share_html_path"), "").strip()
                except Exception:
                    pass

            if attach_to_app_state:
                self._app_state.set_qr_path(str(saved_path))
                if report_path:
                    self._app_state.set_report_path(report_path)

            if persist_to_database:
                try:
                    self._database_service.save_current_app_state_session()
                except Exception as exc:
                    self._logger.warning("QR generated but DB persistence failed: %s", exc)

            size_bytes = file_size_bytes(saved_path)
            result = QRResult(
                success=True,
                session_id=session_id,
                qr_path=str(saved_path),
                size_bytes=size_bytes,
                size_human=format_bytes(size_bytes),
                message="QR code generated successfully.",
                metadata={
                    "generated_at": now_iso(),
                    "include_measurements": include_measurements,
                    "include_diagnosis": include_diagnosis,
                    "include_report_path": include_report_path,
                    "payload_length": len(qr_text),
                    "content_kind": content_kind,
                    "viewer_url": viewer_url,
                    "share_html_path": share_html_path,
                    "report_path": report_path,
                },
            ).to_dict()
            result["viewer_url"] = viewer_url
            result["share_html_path"] = share_html_path
            result["report_path"] = report_path

            self._logger.info(
                "QR generated.",
                extra={
                    "session_id": session_id,
                    "mode": safe_str(session.get("mode"), self._app_state.runtime_mode()),
                    "route": self._app_state.current_route(),
                },
            )

            self.qr_generated.emit(deep_copy(result))
            self.qr_saved.emit(str(saved_path))
            return result

        except Exception as exc:
            log_exception(self._logger, "Failed to generate QR", exc)
            self.qr_error.emit(str(exc))
            return QRResult(
                success=False,
                session_id=safe_str((session_payload or {}).get("session_id"), ""),
                qr_path=str(output_path or ""),
                size_bytes=0,
                size_human=format_bytes(0),
                message=str(exc),
                metadata={},
            ).to_dict()

    def generate_current_session_qr(

        self,
        *,
        output_path: Optional[str | Path] = None,
        persist_to_database: bool = True,
        include_measurements: bool = True,
        include_diagnosis: bool = True,
        include_report_path: bool = True,
    ) -> Dict[str, Any]:
        """
        Generate QR for the current active session.
        """
        return self.generate_qr(
            session_payload=self._app_state.session_snapshot(),
            measurements=self._app_state.current_measurements(),
            diagnosis_payload=self._diagnosis_service.current_diagnosis(),
            output_path=output_path,
            attach_to_app_state=True,
            persist_to_database=persist_to_database,
            include_measurements=include_measurements,
            include_diagnosis=include_diagnosis,
            include_report_path=include_report_path,
        )

    def generate_qr_for_session_id(
        self,
        session_id: str,
        *,
        output_path: Optional[str | Path] = None,
        attach_to_app_state: bool = False,
    ) -> Dict[str, Any]:
        """
        Generate a QR file for a saved database session.
        """
        record = self._database_service.get_session_by_session_id(session_id)
        if not record:
            message = f"Session not found: {session_id}"
            self.qr_error.emit(message)
            return QRResult(
                success=False,
                session_id=session_id,
                qr_path=str(output_path or ""),
                size_bytes=0,
                size_human=format_bytes(0),
                message=message,
                metadata={},
            ).to_dict()

        session_payload = {
            "session_id": record.get("session_id", ""),
            "mode": record.get("mode", ""),
            "status": record.get("status", ""),
            "started_at": record.get("started_at", ""),
            "completed_at": record.get("completed_at", ""),
            "report_path": record.get("report_path", ""),
            "qr_path": record.get("qr_path", ""),
        }

        return self.generate_qr(
            session_payload=session_payload,
            measurements=record.get("measurements", {}),
            diagnosis_payload=record.get("diagnosis", {}),
            output_path=output_path,
            attach_to_app_state=attach_to_app_state,
            persist_to_database=False,
            include_measurements=True,
            include_diagnosis=True,
            include_report_path=True,
        )

    # ========================================================
    # Listing / deletion helpers
    # ========================================================

    def list_qr_files(self, limit: int = 100) -> List[Dict[str, Any]]:
        self._ensure_qr_dir()
        limit = max(1, int(limit))

        files = [
            p for p in PATHS.qr_dir.glob("*.png")
            if p.is_file() and not p.name.startswith(".")
        ]
        files.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)

        result: List[Dict[str, Any]] = []
        for path in files[:limit]:
            stat = path.stat()
            result.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "size_bytes": stat.st_size,
                    "size_human": format_bytes(stat.st_size),
                    "modified_at_epoch": stat.st_mtime,
                }
            )
        return result

    def delete_qr(self, qr_name_or_path: str) -> bool:
        target = Path(qr_name_or_path)
        if not target.is_absolute():
            target = PATHS.qr_dir / target.name

        try:
            if target.exists() and target.is_file():
                target.unlink(missing_ok=True)
                self._logger.info("QR deleted: %s", target)
                self.qr_deleted.emit(str(target))
                return True
            return False
        except Exception as exc:
            log_exception(self._logger, "Failed to delete QR", exc)
            self.qr_error.emit(str(exc))
            return False

    # ========================================================
    # Convenience payload helpers
    # ========================================================

    def current_qr_path(self) -> str:
        session = self._app_state.session_snapshot()
        return safe_str(session.get("qr_path"), "").strip()

    def qr_exists(self, qr_path: Optional[str] = None) -> bool:
        path = Path(qr_path or self.current_qr_path())
        return path.exists() and path.is_file()

    def current_qr_summary(self) -> Dict[str, Any]:
        qr_path = self.current_qr_path()
        path_obj = Path(qr_path) if qr_path else None
        exists = bool(path_obj and path_obj.exists() and path_obj.is_file())
        size_bytes = file_size_bytes(path_obj) if exists else 0

        return {
            "qr_path": qr_path,
            "exists": exists,
            "size_bytes": size_bytes,
            "size_human": format_bytes(size_bytes),
        }

    def current_qr_payload_preview(self) -> Dict[str, Any]:
        """
        Build payload without writing a file.
        Useful for QR screen previews or debugging.
        """
        return self.build_current_session_qr_payload(
            include_measurements=True,
            include_diagnosis=True,
            include_report_path=True,
        )

    # ========================================================
    # Diagnostics
    # ========================================================

    def diagnostics(self) -> Dict[str, Any]:
        qr_files = self.list_qr_files(limit=50)
        return {
            "qr_dir": str(PATHS.qr_dir),
            "qr_count": len(qr_files),
            "current_qr_path": self.current_qr_path(),
            "current_qr_exists": self.qr_exists(),
            "latest_qr_files": qr_files[:5],
        }


# ============================================================
# Singleton accessor
# ============================================================

_QR_SERVICE_SINGLETON: Optional[QRService] = None


def get_qr_service(
    app_state: Optional[AppState] = None,
    diagnosis_service: Optional[DiagnosisService] = None,
    report_service: Optional[ReportService] = None,
    database_service: Optional[DatabaseService] = None,
    session_service: Optional[object] = None,
) -> QRService:
    global _QR_SERVICE_SINGLETON
    if _QR_SERVICE_SINGLETON is None:
        _QR_SERVICE_SINGLETON = QRService(
            app_state=app_state,
            diagnosis_service=diagnosis_service,
            report_service=report_service,
            database_service=database_service,
            session_service=session_service,
        )
    else:
        if session_service is not None:
            _QR_SERVICE_SINGLETON.set_session_service(session_service)
    return _QR_SERVICE_SINGLETON