"""Runtime ownership for the active webcam-assisted study block."""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.database import StudyDatabase
from main import DATABASE_PATH
from modules.alerts import AlertManager
from modules.fatigue import FatigueAnalyzer
from modules.posture import PostureAnalyzer
from modules.posture_knn import DEFAULT_KNN_MODEL_PATH
from modules.posture_model import DEFAULT_MODEL_PATH
from web_app import _decode_frame


MAX_FRAMES_PER_SECOND = 4.0


class StudySessionManager:
    """Own a single session and its non-thread-safe vision analyzers."""

    def __init__(
        self,
        database: StudyDatabase,
        database_path: Path = DATABASE_PATH,
        model_path: Path = DEFAULT_MODEL_PATH,
        knn_model_path: Path = DEFAULT_KNN_MODEL_PATH,
    ) -> None:
        self.database = database
        self.database_path = database_path
        self.model_path = model_path
        self.knn_model_path = knn_model_path
        self._lock = threading.RLock()
        self._posture: PostureAnalyzer | None = None
        self._fatigue: FatigueAnalyzer | None = None
        self._alerts: AlertManager | None = None
        self._session_id: str | None = None
        self._subject_id: int | None = None
        self._kind: str | None = None
        self._started_at: datetime | None = None
        self._started_monotonic = 0.0
        self._last_frame_at = 0.0
        self._score_total = 0.0
        self._score_count = 0
        self._metrics: dict[str, Any] = self._empty_metrics()
        self._active_alerts: tuple[str, ...] = ()

    @staticmethod
    def _empty_metrics() -> dict[str, Any]:
        return {
            "posture_status": "Ready",
            "posture_score": None,
            "neck_angle": None,
            "proximity_ratio": None,
            "ear": None,
            "mar": None,
            "blink_count": 0,
            "yawn_count": 0,
            "blinks_per_minute": 0.0,
            "drowsy": False,
            "yawning": False,
            "face_valid": False,
            "calibrated": False,
            "classifier_name": None,
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            active = self._posture is not None
            elapsed = (
                max(0.0, time.monotonic() - self._started_monotonic)
                if active
                else 0.0
            )
            return {
                "active": active,
                "session_id": self._session_id,
                "subject_id": self._subject_id,
                "kind": self._kind,
                "elapsed_seconds": elapsed,
                "metrics": dict(self._metrics),
                "alerts": list(self._active_alerts),
            }

    def start(self, subject_id: int | None, kind: str) -> dict[str, Any]:
        with self._lock:
            if self._posture is not None:
                raise ValueError("A study block is already running.")
            if subject_id is not None and not self.database.subject_exists(subject_id):
                raise ValueError("The selected subject does not exist.")

            posture = PostureAnalyzer(self.model_path, self.knn_model_path)
            if posture.classifier_name != "KNN":
                posture.close()
                raise RuntimeError(
                    "A trained KNN posture model is required to start webcam analysis."
                )
            try:
                fatigue = FatigueAnalyzer()
                alerts = AlertManager()
            except Exception:
                posture.close()
                raise

            started_at = datetime.now(timezone.utc)
            session_id = str(uuid.uuid4())
            try:
                self.database.begin_session(
                    session_id, subject_id, kind, started_at.isoformat()
                )
            except Exception:
                posture.close()
                fatigue.close()
                raise

            self._posture = posture
            self._fatigue = fatigue
            self._alerts = alerts
            self._session_id = session_id
            self._subject_id = subject_id
            self._kind = kind
            self._started_at = started_at
            self._started_monotonic = time.monotonic()
            self._last_frame_at = 0.0
            self._score_total = 0.0
            self._score_count = 0
            self._metrics = self._empty_metrics()
            self._active_alerts = ()
            return self.status()

    def process_frame(self, frame_bytes: bytes) -> dict[str, Any]:
        with self._lock:
            if (
                self._posture is None
                or self._fatigue is None
                or self._alerts is None
                or self._session_id is None
            ):
                raise ValueError("Start a study block before sending webcam frames.")

            now = time.monotonic()
            if now - self._last_frame_at < 1.0 / MAX_FRAMES_PER_SECOND:
                return self.status()

            frame = _decode_frame(frame_bytes)
            posture = self._posture.process(frame, now)
            fatigue = self._fatigue.process(frame, now)
            self._last_frame_at = now
            if posture.score is not None:
                self._score_total += posture.score
                self._score_count += 1
            self._active_alerts = self._alerts.update(posture.status, fatigue.drowsy)

            self._metrics = {
                "posture_status": posture.status,
                "posture_score": posture.score,
                "neck_angle": posture.neck_angle,
                "proximity_ratio": posture.proximity_ratio,
                "ear": fatigue.ear,
                "mar": fatigue.mar,
                "blink_count": fatigue.blink_count,
                "yawn_count": fatigue.yawn_count,
                "blinks_per_minute": fatigue.blinks_per_minute,
                "drowsy": fatigue.drowsy,
                "yawning": fatigue.yawning,
                "face_valid": fatigue.valid,
                "calibrated": posture.calibrated,
                "classifier_name": posture.classifier_name,
            }
            self.database.record_metrics(
                self._session_id, datetime.now(timezone.utc).isoformat(), self._metrics
            )
            return self.status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if (
                self._posture is None
                or self._fatigue is None
                or self._session_id is None
                or self._kind is None
            ):
                raise ValueError("No study block is running.")

            posture = self._posture
            fatigue = self._fatigue
            session_id = self._session_id
            duration = max(0.0, time.monotonic() - self._started_monotonic)
            average_score = (
                self._score_total / self._score_count if self._score_count else None
            )
            final_metrics = dict(self._metrics)
            self._posture = None
            self._fatigue = None
            self._alerts = None
            self._active_alerts = ()
            posture.close()
            fatigue.close()

            self.database.finish_session(
                session_id,
                datetime.now(timezone.utc).isoformat(),
                duration,
                average_score,
                final_metrics["blink_count"],
                final_metrics["yawn_count"],
            )
            result = self.status()
            result.update(
                {
                    "duration_seconds": duration,
                    "average_posture_score": average_score,
                    "total_blinks": final_metrics["blink_count"],
                    "total_yawns": final_metrics["yawn_count"],
                }
            )
            self._session_id = None
            self._subject_id = None
            self._kind = None
            self._started_at = None
            self._metrics = self._empty_metrics()
            return result
