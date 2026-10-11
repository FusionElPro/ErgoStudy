"""MediaPipe Pose-based posture and workstation-distance analysis."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from statistics import mean


POSE_LANDMARK_NAMES = (
    "nose",
    "left_eye_inner",
    "left_eye",
    "left_eye_outer",
    "right_eye_inner",
    "right_eye",
    "right_eye_outer",
    "left_ear",
    "right_ear",
    "mouth_left",
    "mouth_right",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_pinky",
    "right_pinky",
    "left_index",
    "right_index",
    "left_thumb",
    "right_thumb",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
    "left_heel",
    "right_heel",
    "left_foot_index",
    "right_foot_index",
)


def signed_angle_delta(angle: float, baseline: float) -> float:
    return math.remainder(angle - baseline, 360.0)


def mean_angle(angles: list[float]) -> float:
    sine = mean(math.sin(math.radians(angle)) for angle in angles)
    cosine = mean(math.cos(math.radians(angle)) for angle in angles)
    return math.degrees(math.atan2(sine, cosine))


def head_tilt_angle(
    left_eye_x: float,
    left_eye_y: float,
    right_eye_x: float,
    right_eye_y: float,
    shoulder_tilt: float,
) -> float | None:
    eye_line_x = right_eye_x - left_eye_x
    eye_line_y = right_eye_y - left_eye_y
    if math.hypot(eye_line_x, eye_line_y) <= 1e-6:
        return None
    eye_line_tilt = math.degrees(math.atan2(eye_line_y, eye_line_x))
    return signed_angle_delta(eye_line_tilt, shoulder_tilt)


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
    rule_status: str | None = None
    classifier_name: str | None = None
    classifier_distance: float | None = None
    classifier_distance_limit: float | None = None
    head_tilt_delta: float | None = None
    geometric_override: bool = False


class PostureAnalyzer:
    CALIBRATION_SECONDS = 5.0
    HEAD_TILT_TOLERANCE = 15.0

    def __init__(
        self,
        model_path: Path | None = None,
        knn_model_path: Path | None = None,
    ) -> None:
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
        self._calibration_head_tilt_samples: list[float] = []
        self._baseline_head_tilt: float | None = None
        self._last_result = None
        self._classifier = None
        self._classifier_name: str | None = None
        self._knn_distance_limit: float | None = None
        try:
            from .posture_knn import (
                DEFAULT_KNN_MODEL_PATH,
                FEATURE_SPACE,
                estimate_knn_distance_limit,
                predict_knn_posture,
            )
        except ImportError:
            from posture_knn import (
                DEFAULT_KNN_MODEL_PATH,
                FEATURE_SPACE,
                estimate_knn_distance_limit,
                predict_knn_posture,
            )
        self._predict_knn_posture = predict_knn_posture
        knn_model_path = knn_model_path or DEFAULT_KNN_MODEL_PATH
        classifier_path = (
            knn_model_path
            if knn_model_path.is_file()
            else model_path if model_path is not None and model_path.is_file() else None
        )
        if classifier_path is not None:
            try:
                import joblib

                classifier_data = joblib.load(classifier_path)
            except (OSError, ValueError, ImportError) as exc:
                self._pose.close()
                raise RuntimeError(
                    f"Could not load posture classifier at {classifier_path}: {exc}"
                ) from exc
            if isinstance(classifier_data, dict):
                classifier = classifier_data.get("classifier")
                self._classifier_name = classifier_data.get("classifier_name")
                self._knn_distance_limit = classifier_data.get("knn_distance_limit")
                feature_space = classifier_data.get("feature_space")
                if not isinstance(self._classifier_name, str):
                    self._pose.close()
                    raise RuntimeError(
                        f"Posture classifier at {classifier_path} has invalid metadata."
                    )
                if (
                    self._classifier_name == "KNN"
                    and feature_space is not None
                    and feature_space != FEATURE_SPACE
                ):
                    self._pose.close()
                    raise RuntimeError(
                        f"Posture classifier at {classifier_path} uses unsupported "
                        f"feature space {feature_space!r}; expected {FEATURE_SPACE!r}."
                    )
            else:
                classifier = classifier_data
                self._classifier_name = "MLP"
            if classifier is None or set(classifier.classes_) != {
                "Good",
                "Slouching",
                "Leaning",
            }:
                self._pose.close()
                raise RuntimeError(
                    f"Posture classifier at {classifier_path} does not contain all expected classes."
                )
            if self._classifier_name == "KNN":
                if self._knn_distance_limit is None:
                    self._knn_distance_limit = estimate_knn_distance_limit(classifier)
                elif (
                    not isinstance(self._knn_distance_limit, (int, float))
                    or not math.isfinite(self._knn_distance_limit)
                    or self._knn_distance_limit <= 0
                ):
                    self._pose.close()
                    raise RuntimeError(
                        f"Posture classifier at {classifier_path} has an invalid "
                        "KNN distance limit."
                    )
            self._classifier = classifier
        if self._classifier_name == "KNN":
            self._knn_landmark_indices = tuple(
                getattr(self._mp_pose.PoseLandmark, name.upper()).value
                for name in POSE_LANDMARK_NAMES
            )
        else:
            self._knn_landmark_indices = ()

    @property
    def calibrated(self) -> bool:
        return self._baseline is not None

    @property
    def classifier_name(self) -> str | None:
        return self._classifier_name

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
        left_eye = points[pose.LEFT_EYE.value]
        right_eye = points[pose.RIGHT_EYE.value]
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
        head_tilt = head_tilt_angle(
            left_eye.x,
            left_eye.y,
            right_eye.x,
            right_eye.y,
            shoulder_tilt,
        )
        measurements = (neck_angle, shoulder_span, shoulder_tilt, nose_offset)

        if self._baseline is None:
            if self._calibration_started is None:
                self._calibration_started = now
            self._calibration_samples.append(measurements)
            if head_tilt is not None:
                self._calibration_head_tilt_samples.append(head_tilt)
            if now - self._calibration_started >= self.CALIBRATION_SECONDS:
                self._baseline = tuple(
                    mean_angle([sample[index] for sample in self._calibration_samples])
                    if index == 2
                    else mean(sample[index] for sample in self._calibration_samples)
                    for index in range(4)
                )
                if self._calibration_head_tilt_samples:
                    self._baseline_head_tilt = mean_angle(
                        self._calibration_head_tilt_samples
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
        shoulder_tilt_delta = signed_angle_delta(shoulder_tilt, baseline_tilt)
        head_tilt_delta = (
            signed_angle_delta(head_tilt, self._baseline_head_tilt)
            if head_tilt is not None and self._baseline_head_tilt is not None
            else None
        )
        head_tilted = (
            head_tilt_delta is not None
            and abs(head_tilt_delta) > self.HEAD_TILT_TOLERANCE
        )
        leaning = (
            abs(shoulder_tilt_delta) > tilt_tolerance
            or abs(nose_offset - baseline_nose_offset) > 0.15
            or abs(proximity_ratio - 1.0) > 0.15
            or head_tilted
        )
        rule_status = "Slouching" if slouching else "Leaning" if leaning else "Good"
        features = (
            neck_angle - baseline_neck,
            proximity_ratio,
            shoulder_tilt_delta,
            nose_offset - baseline_nose_offset,
        )
        classifier_distance = None
        if self._classifier_name == "KNN":
            world_landmarks = self._last_result.pose_world_landmarks
            if world_landmarks is None:
                return PostureMetrics(
                    "No world pose detected",
                    neck_angle,
                    proximity_ratio,
                    None,
                    True,
                    False,
                    classifier_name=self._classifier_name,
                    classifier_distance_limit=self._knn_distance_limit,
                )
            classifier_features = [
                coordinate
                for index in self._knn_landmark_indices
                for coordinate in (
                    world_landmarks.landmark[index].x,
                    world_landmarks.landmark[index].y,
                    world_landmarks.landmark[index].z,
                )
            ]
            landmark_visibility = tuple(
                world_landmarks.landmark[index].visibility
                for index in self._knn_landmark_indices
            )
            status, classifier_distance = self._predict_knn_posture(
                self._classifier,
                classifier_features,
                self._knn_distance_limit,
                landmark_visibility,
            )
        elif self._classifier is not None:
            status = str(self._classifier.predict([features])[0])
        else:
            status = rule_status
        geometric_override = head_tilted
        if geometric_override:
            status = "Leaning"
        score = {"Good": 100.0, "Slouching": 70.0, "Leaning": 80.0}.get(status)
        return PostureMetrics(
            status,
            neck_angle,
            proximity_ratio,
            score,
            True,
            True,
            features,
            self._classifier is not None,
            rule_status,
            self._classifier_name,
            classifier_distance,
            self._knn_distance_limit if self._classifier_name == "KNN" else None,
            head_tilt_delta,
            geometric_override,
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
