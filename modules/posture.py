"""MediaPipe Pose-based posture and workstation-distance analysis."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from statistics import mean


@dataclass(frozen=True)
class PostureMetrics:
    status: str
    neck_angle: float | None
    proximity_ratio: float | None
    score: float | None
    calibrated: bool
    valid: bool
    features: tuple[float, float, float, float] | None = None
    classifier_used: bool = False


class PostureAnalyzer:
    CALIBRATION_SECONDS = 5.0

    def __init__(self, model_path: Path | None = None) -> None:
        try:
            import cv2
            import mediapipe as mp
            import numpy as np
        except ImportError as exc:
            raise RuntimeError(
                "Posture analysis requires OpenCV, MediaPipe, and NumPy. "
                "Install them with `pip install -r requirements.txt`."
            ) from exc

        self._cv2 = cv2
        self._np = np
        self._mp_pose = mp.solutions.pose
        self._drawing = mp.solutions.drawing_utils
        self._pose = self._mp_pose.Pose(
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._calibration_started: float | None = None
        self._calibration_samples: list[tuple[float, float, float, float]] = []
        self._baseline: tuple[float, float, float, float] | None = None
        self._last_result = None
        self._classifier = None
        if model_path is not None and model_path.exists():
            try:
                import joblib

                classifier = joblib.load(model_path)
            except (OSError, ValueError, ImportError) as exc:
                self._pose.close()
                raise RuntimeError(f"Could not load posture classifier at {model_path}: {exc}") from exc
            if set(classifier.classes_) != {"Good", "Slouching", "Leaning"}:
                self._pose.close()
                raise RuntimeError(
                    f"Posture classifier at {model_path} does not contain all expected classes."
                )
            self._classifier = classifier

    @property
    def calibrated(self) -> bool:
        return self._baseline is not None

    def process(self, frame, now: float) -> PostureMetrics:
        rgb = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB)
        result = self._pose.process(rgb)
        self._last_result = result
        landmarks = result.pose_landmarks
        if landmarks is None:
            return PostureMetrics("No person detected", None, None, None, self.calibrated, False)

        points = landmarks.landmark
        pose = self._mp_pose.PoseLandmark
        left_shoulder = points[pose.LEFT_SHOULDER.value]
        right_shoulder = points[pose.RIGHT_SHOULDER.value]
        nose = points[pose.NOSE.value]
        shoulder_mid_x = (left_shoulder.x + right_shoulder.x) / 2
        shoulder_mid_y = (left_shoulder.y + right_shoulder.y) / 2
        shoulder_span = self._np.linalg.norm(
            self._np.array(
                [right_shoulder.x - left_shoulder.x, right_shoulder.y - left_shoulder.y]
            )
        )
        if shoulder_span <= 0:
            return PostureMetrics("No person detected", None, None, None, self.calibrated, False)

        neck_angle = math.degrees(
            math.atan2(abs(nose.x - shoulder_mid_x), abs(nose.y - shoulder_mid_y))
        )
        shoulder_tilt = math.degrees(
            math.atan2(
                right_shoulder.y - left_shoulder.y,
                right_shoulder.x - left_shoulder.x,
            )
        )
        nose_offset = (nose.x - shoulder_mid_x) / shoulder_span
        measurements = (neck_angle, shoulder_span, shoulder_tilt, nose_offset)

        if self._baseline is None:
            if self._calibration_started is None:
                self._calibration_started = now
            self._calibration_samples.append(measurements)
            if now - self._calibration_started >= self.CALIBRATION_SECONDS:
                self._baseline = tuple(
                    mean(sample[index] for sample in self._calibration_samples)
                    for index in range(4)
                )
            else:
                return PostureMetrics(
                    "Calibrating", neck_angle, None, None, False, True
                )

        baseline_neck, baseline_span, baseline_tilt, baseline_nose_offset = self._baseline
        proximity_ratio = shoulder_span / baseline_span
        neck_tolerance = max(abs(baseline_neck) * 0.15, 5.0)
        tilt_tolerance = max(abs(baseline_tilt) * 0.15, 3.0)
        slouching = neck_angle - baseline_neck > neck_tolerance
        leaning = (
            abs(shoulder_tilt - baseline_tilt) > tilt_tolerance
            or abs(nose_offset - baseline_nose_offset) > 0.15
            or abs(proximity_ratio - 1.0) > 0.15
        )
        status = "Slouching" if slouching else "Leaning" if leaning else "Good"
        features = (
            neck_angle - baseline_neck,
            proximity_ratio,
            shoulder_tilt - baseline_tilt,
            nose_offset - baseline_nose_offset,
        )
        if self._classifier is not None:
            status = str(self._classifier.predict([features])[0])
        score = {"Good": 100.0, "Slouching": 70.0, "Leaning": 80.0}[status]
        return PostureMetrics(
            status,
            neck_angle,
            proximity_ratio,
            score,
            True,
            True,
            features,
            self._classifier is not None,
        )

    def draw_landmarks(self, frame) -> None:
        if self._last_result is not None and self._last_result.pose_landmarks is not None:
            self._drawing.draw_landmarks(
                frame,
                self._last_result.pose_landmarks,
                self._mp_pose.POSE_CONNECTIONS,
            )

    def close(self) -> None:
        self._pose.close()
