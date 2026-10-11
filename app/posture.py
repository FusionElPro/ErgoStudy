"""Standalone, KNN-only posture analysis for the website's Posture Coach."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from modules.posture import PostureAnalyzer, PostureMetrics
from modules.posture_knn import DEFAULT_KNN_MODEL_PATH
from web_app import _decode_frame


class PostureAnalysisManager:
    """Keep a calibrated KNN pose analyzer available outside study timers."""

    def __init__(self, knn_model_path: Path = DEFAULT_KNN_MODEL_PATH) -> None:
        self.knn_model_path = knn_model_path
        self._lock = threading.RLock()
        self._analyzer: PostureAnalyzer | None = None
        self._started_at = 0.0
        self._metrics: dict[str, Any] = self._empty_metrics()

    @staticmethod
    def _empty_metrics() -> dict[str, Any]:
        return {
            "status": "Ready",
            "neck_angle": None,
            "proximity_ratio": None,
            "score": None,
            "calibrated": False,
            "valid": False,
            "classifier_used": False,
            "classifier_name": None,
            "classifier_distance": None,
            "classifier_distance_limit": None,
            "rule_status": None,
            "head_tilt_delta": None,
            "geometric_override": False,
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "active": self._analyzer is not None,
                "model_ready": self.knn_model_path.is_file(),
                "model_name": "KNN" if self.knn_model_path.is_file() else None,
                "elapsed_seconds": (
                    max(0.0, time.monotonic() - self._started_at)
                    if self._analyzer is not None
                    else 0.0
                ),
                "metrics": dict(self._metrics),
            }

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._analyzer is not None:
                raise ValueError("The posture analyzer is already running.")
            if not self.knn_model_path.is_file():
                raise RuntimeError(
                    "The trained KNN posture model is unavailable. "
                    "Train it with train_posture_knn.py before analyzing posture."
                )

            analyzer = PostureAnalyzer(model_path=None, knn_model_path=self.knn_model_path)
            if analyzer.classifier_name != "KNN":
                analyzer.close()
                raise RuntimeError(
                    "The posture model is not a trained KNN. "
                    "Train the KNN model before analyzing posture."
                )
            self._analyzer = analyzer
            self._started_at = time.monotonic()
            self._metrics = self._empty_metrics()
            return self.status()

    def process_frame(self, frame_bytes: bytes) -> dict[str, Any]:
        with self._lock:
            if self._analyzer is None:
                raise ValueError("Start the posture analyzer before sending webcam frames.")
            metrics: PostureMetrics = self._analyzer.process(
                _decode_frame(frame_bytes), time.monotonic()
            )
            self._metrics = {
                "status": metrics.status,
                "neck_angle": metrics.neck_angle,
                "proximity_ratio": metrics.proximity_ratio,
                "score": metrics.score,
                "calibrated": metrics.calibrated,
                "valid": metrics.valid,
                "classifier_used": metrics.classifier_used,
                "classifier_name": metrics.classifier_name,
                "classifier_distance": metrics.classifier_distance,
                "classifier_distance_limit": metrics.classifier_distance_limit,
                "rule_status": metrics.rule_status,
                "head_tilt_delta": metrics.head_tilt_delta,
                "geometric_override": metrics.geometric_override,
            }
            result = self.status()
            result["metrics"] = dict(self._metrics)
            return result

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if self._analyzer is None:
                raise ValueError("The posture analyzer is not running.")
            analyzer = self._analyzer
            self._analyzer = None
            analyzer.close()
            self._metrics = self._empty_metrics()
            return self.status()

    def close(self) -> None:
        with self._lock:
            if self._analyzer is None:
                return
            analyzer = self._analyzer
            self._analyzer = None
            analyzer.close()
