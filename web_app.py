"""Serve the local ErgoStudy browser dashboard and posture analysis API."""

from __future__ import annotations

import argparse
import json
import mimetypes
import threading
import time
import uuid
import webbrowser
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from main import DATABASE_PATH, SessionSummary, save_session
from modules.alerts import AlertManager
from modules.posture import PostureAnalyzer
from modules.posture_model import (
    DEFAULT_MODEL_PATH,
    PostureSampleStore,
    train_posture_classifier,
)
from modules.posture_knn import DEFAULT_KNN_MODEL_PATH


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
MAX_FRAME_BYTES = 2_000_000
MAX_FRAMES_PER_SECOND = 8.0
MIN_CAPTURE_INTERVAL = 0.5


def _decode_frame(frame_bytes: bytes):
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            "Webcam processing needs OpenCV and NumPy. "
            "Install requirements with `python -m pip install -r requirements.txt`."
        ) from exc

    frame = cv2.imdecode(np.frombuffer(frame_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("Could not decode the webcam frame as a JPEG image.")
    return frame


class StudyState:
    """Own the single local webcam study session and its analyzer lifecycle."""

    def __init__(
        self,
        database_path: Path = DATABASE_PATH,
        model_path: Path = DEFAULT_MODEL_PATH,
        knn_model_path: Path = DEFAULT_KNN_MODEL_PATH,
    ) -> None:
        self.database_path = database_path
        self.model_path = model_path
        self.knn_model_path = knn_model_path
        self.sample_store = PostureSampleStore(database_path)
        self._lock = threading.RLock()
        self._analyzer: PostureAnalyzer | None = None
        self._alerts: AlertManager | None = None
        self._session_id: str | None = None
        self._started_at: datetime | None = None
        self._started_monotonic = 0.0
        self._last_frame_at = 0.0
        self._frame_count = 0
        self._score_total = 0.0
        self._score_count = 0
        self._metrics: dict[str, object] = self._idle_metrics()
        self._active_alerts: tuple[str, ...] = ()
        self._current_features: tuple[float, float, float, float] | None = None

    @staticmethod
    def _idle_metrics() -> dict[str, object]:
        return {
            "status": "Ready",
            "neck_angle": None,
            "proximity_ratio": None,
            "score": None,
            "calibrated": False,
            "valid": False,
            "classifier_used": False,
            "classifier_name": None,
            "rule_status": None,
        }

    def status(self) -> dict[str, object]:
        with self._lock:
            counts = self.sample_store.counts()
            elapsed = (
                max(0.0, time.monotonic() - self._started_monotonic)
                if self._analyzer is not None
                else 0.0
            )
            knn_available = self.knn_model_path.is_file()
            mlp_available = self.model_path.is_file()
            return {
                "active": self._analyzer is not None,
                "model_available": knn_available or mlp_available,
                "model_name": "KNN" if knn_available else "MLP" if mlp_available else None,
                "elapsed_seconds": elapsed,
                "frame_count": self._frame_count,
                "metrics": dict(self._metrics),
                "alerts": list(self._active_alerts),
                "sample_counts": counts,
            }

    def start(self) -> dict[str, object]:
        with self._lock:
            if self._analyzer is not None:
                raise ValueError("A study session is already running.")
            analyzer = PostureAnalyzer(self.model_path, self.knn_model_path)
            try:
                alerts = AlertManager()
            except Exception:
                analyzer.close()
                raise

            self._analyzer = analyzer
            self._alerts = alerts
            self._session_id = str(uuid.uuid4())
            self._started_at = datetime.now(timezone.utc)
            self._started_monotonic = time.monotonic()
            self._last_frame_at = 0.0
            self._frame_count = 0
            self._score_total = 0.0
            self._score_count = 0
            self._metrics = self._idle_metrics()
            self._active_alerts = ()
            self._current_features = None
            return self.status()

    def process_frame(self, frame_bytes: bytes) -> dict[str, object]:
        with self._lock:
            if self._analyzer is None or self._alerts is None:
                raise ValueError("Start a study session before sending webcam frames.")

            now = time.monotonic()
            if now - self._last_frame_at < 1.0 / MAX_FRAMES_PER_SECOND:
                return self.status()

            frame = _decode_frame(frame_bytes)
            posture = self._analyzer.process(frame, now)
            self._frame_count += 1
            self._last_frame_at = now
            if posture.score is not None:
                self._score_total += posture.score
                self._score_count += 1

            new_alerts = self._alerts.update(posture.status, False)
            self._active_alerts = self._alerts.active_alerts
            self._metrics = {
                "status": posture.status,
                "neck_angle": posture.neck_angle,
                "proximity_ratio": posture.proximity_ratio,
                "score": posture.score,
                "calibrated": posture.calibrated,
                "valid": posture.valid,
                "classifier_used": posture.classifier_used,
                "rule_status": posture.rule_status,
                "classifier_name": posture.classifier_name,
            }
            self._current_features = posture.features
            result = self.status()
            result["new_alerts"] = list(new_alerts)
            return result

    def capture_label(self, label: str) -> dict[str, int]:
        with self._lock:
            if self._analyzer is None or self._session_id is None:
                raise ValueError("Start a study session before recording labels.")
            if time.monotonic() - self._last_frame_at > MIN_CAPTURE_INTERVAL:
                raise ValueError("Wait for a fresh posture reading before recording a sample.")
            if self._metrics["status"] == "Calibrating":
                raise ValueError("Wait for posture calibration to finish.")
            posture = self._metrics
            if posture["status"] == "No person detected" or not posture["valid"]:
                raise ValueError("A person must be visible before recording a sample.")
            features = self._current_features
            if features is None:
                raise ValueError("Posture features are unavailable; wait for a valid frame.")
            self.sample_store.record(features, label, self._session_id)
            return self.sample_store.counts()

    def recalibrate(self) -> dict[str, object]:
        with self._lock:
            if self._analyzer is None:
                raise ValueError("Start a study session before recalibrating.")
            analyzer = PostureAnalyzer(self.model_path, self.knn_model_path)
            previous = self._analyzer
            self._analyzer = analyzer
            previous.close()
            self._metrics = self._idle_metrics()
            self._current_features = None
            self._active_alerts = ()
            self._alerts = AlertManager()
            return self.status()

    def train_model(self):
        with self._lock:
            if self._analyzer is not None:
                raise ValueError("Finish the current study session before training the model.")
            return train_posture_classifier(self.database_path, self.model_path)

    def stop(self) -> dict[str, object]:
        with self._lock:
            if self._analyzer is None:
                raise ValueError("No study session is running.")

            analyzer = self._analyzer
            self._analyzer = None
            self._alerts = None
            self._active_alerts = ()
            analyzer.close()

            duration = max(0.0, time.monotonic() - self._started_monotonic)
            if self._frame_count:
                summary = SessionSummary(
                    duration_seconds=duration,
                    average_posture_score=(
                        self._score_total / self._score_count if self._score_count else 0.0
                    ),
                    total_blinks=0,
                    total_yawns=0,
                )
                if self._started_at is None:
                    raise RuntimeError("Study session start time was lost.")
                save_session(summary, self._started_at, self.database_path)

            self._metrics = self._idle_metrics()
            result = self.status()
            result["duration_seconds"] = duration
            result["average_posture_score"] = (
                self._score_total / self._score_count if self._score_count else 0.0
            )
            return result

def create_handler(state: StudyState):
    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, payload: dict[str, object], status: HTTPStatus) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict[str, object]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 16_384:
                    raise ValueError("JSON request body is empty or too large.")
                payload = json.loads(self.rfile.read(length))
            except (ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"Invalid JSON request: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError("JSON request body must be an object.")
            return payload

        def do_GET(self) -> None:
            if self.path == "/api/status":
                self._send_json(state.status(), HTTPStatus.OK)
                return
            if self.path == "/":
                self.path = "/index.html"
            if self.path not in ("/index.html", "/styles.css", "/app.js"):
                self._send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
                return

            asset = WEB_ROOT / self.path.lstrip("/")
            try:
                body = asset.read_bytes()
            except OSError as exc:
                self._send_json(
                    {"error": f"Could not load web asset: {exc}"},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            content_type = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            try:
                if self.path == "/api/session/start":
                    result = state.start()
                elif self.path == "/api/session/stop":
                    result = state.stop()
                elif self.path == "/api/session/recalibrate":
                    result = state.recalibrate()
                elif self.path == "/api/frame":
                    content_type = self.headers.get("Content-Type", "")
                    if content_type != "image/jpeg":
                        raise ValueError("Webcam frame must use Content-Type image/jpeg.")
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > MAX_FRAME_BYTES:
                        raise ValueError("Webcam frame is empty or larger than 2 MB.")
                    result = state.process_frame(self.rfile.read(length))
                elif self.path == "/api/label":
                    payload = self._read_json()
                    label = payload.get("label")
                    if not isinstance(label, str):
                        raise ValueError("A posture label is required.")
                    result = {"sample_counts": state.capture_label(label)}
                elif self.path == "/api/model/train":
                    trained = state.train_model()
                    result = {
                        "accuracy": trained.accuracy,
                        "macro_f1": trained.macro_f1,
                        "sample_count": trained.sample_count,
                        "training_session_count": trained.training_session_count,
                        "test_session_count": trained.test_session_count,
                        "model_path": str(trained.model_path),
                    }
                else:
                    self._send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
                    return
            except ValueError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            except (RuntimeError, ValueError) as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            except OSError as exc:
                self._send_json({"error": f"Could not save session data: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return

            self._send_json(result, HTTPStatus.OK)

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local ErgoStudy browser app.")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: localhost only)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    args = parser.parse_args()

    state = StudyState()
    try:
        server = ThreadingHTTPServer((args.host, args.port), create_handler(state))
    except OSError as exc:
        parser.exit(1, f"Could not start ErgoStudy web server: {exc}\n")
    address = f"http://{args.host}:{args.port}/"
    print(f"ErgoStudy is available at {address}. Press Ctrl+C to stop the server.")
    if not args.no_browser:
        webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping ErgoStudy web server.")
    finally:
        server.server_close()
        if state.status()["active"]:
            try:
                state.stop()
            except (RuntimeError, OSError) as exc:
                print(f"Could not finalize the active session: {exc}")


if __name__ == "__main__":
    main()
