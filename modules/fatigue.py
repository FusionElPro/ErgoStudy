<<<<<<< HEAD
"""MediaPipe Face Mesh-based blink, eyelid, and yawn analysis."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class FatigueMetrics:
    ear: float
    mar: float
    blink_count: int
    yawn_count: int
    blinks_per_minute: float
    drowsy: bool
    yawning: bool
    valid: bool


def _distance(np, first, second) -> float:
    first_xy = np.asarray((first.x, first.y))
    second_xy = np.asarray((second.x, second.y))
    return float(np.linalg.norm(first_xy - second_xy))


def calculate_ear(np, points, indices: tuple[int, ...]) -> float:
    """Calculate EAR from six ordered eye-corner/eyelid landmarks."""
    p1, p2, p3, p4, p5, p6 = (points[index] for index in indices)
    horizontal = _distance(np, p1, p4)
    if horizontal == 0:
        return 0.0
    return (_distance(np, p2, p6) + _distance(np, p3, p5)) / (2.0 * horizontal)


def calculate_mar(np, points) -> float:
    vertical = _distance(np, points[13], points[14])
    horizontal = _distance(np, points[78], points[308])
    if horizontal == 0:
        return 0.0
    return vertical / horizontal


class FatigueAnalyzer:
    EAR_CLOSED_THRESHOLD = 0.21
    EAR_OPEN_THRESHOLD = 0.23
    MAR_YAWN_THRESHOLD = 0.6

    def __init__(self) -> None:
        try:
            import cv2
            import mediapipe as mp
            import numpy as np
        except ImportError as exc:
            raise RuntimeError(
                "Fatigue analysis requires OpenCV, MediaPipe, and NumPy. "
                "Install them with `pip install -r requirements.txt`."
            ) from exc

        self._cv2 = cv2
        self._np = np
        self._face_mesh = mp.solutions.face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._started_at: float | None = None
        self._eye_closed_since: float | None = None
        self._yawn_started_at: float | None = None
        self._yawn_counted = False
        self._blink_count = 0
        self._yawn_count = 0

    def process(self, frame, now: float) -> FatigueMetrics:
        if self._started_at is None:
            self._started_at = now

        rgb = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB)
        result = self._face_mesh.process(rgb)
        if not result.multi_face_landmarks:
            self._eye_closed_since = None
            self._yawn_started_at = None
            self._yawn_counted = False
            return self._metrics(0.0, 0.0, False, False, now)

        points = result.multi_face_landmarks[0].landmark
        left_ear = calculate_ear(
            self._np, points, (33, 160, 158, 133, 153, 144)
        )
        right_ear = calculate_ear(
            self._np, points, (362, 385, 387, 263, 373, 380)
        )
        ear = (left_ear + right_ear) / 2.0
        mar = calculate_mar(self._np, points)

        if ear < self.EAR_CLOSED_THRESHOLD:
            if self._eye_closed_since is None:
                self._eye_closed_since = now
        elif ear >= self.EAR_OPEN_THRESHOLD and self._eye_closed_since is not None:
            if now - self._eye_closed_since <= 0.5:
                self._blink_count += 1
            self._eye_closed_since = None

        yawning = mar > self.MAR_YAWN_THRESHOLD
        if yawning:
            if self._yawn_started_at is None:
                self._yawn_started_at = now
            elif now - self._yawn_started_at >= 0.8 and not self._yawn_counted:
                self._yawn_count += 1
                self._yawn_counted = True
        else:
            self._yawn_started_at = None
            self._yawn_counted = False

        return self._metrics(ear, mar, True, yawning, now)

    def _metrics(
        self, ear: float, mar: float, valid: bool, yawning: bool, now: float
    ) -> FatigueMetrics:
        elapsed = max(0.0, now - (self._started_at if self._started_at is not None else now))
        blink_rate = self._blink_count * 60.0 / elapsed if elapsed > 0 else 0.0
        prolonged_eye_closure = (
            self._eye_closed_since is not None
            and now - self._eye_closed_since >= 1.0
        )
        low_blink_rate = elapsed >= 60.0 and blink_rate < 8.0
        prolonged_yawn = (
            self._yawn_started_at is not None
            and now - self._yawn_started_at >= 2.0
        )
        drowsy = valid and (prolonged_eye_closure or low_blink_rate or prolonged_yawn)
        return FatigueMetrics(
            ear=ear,
            mar=mar,
            blink_count=self._blink_count,
            yawn_count=self._yawn_count,
            blinks_per_minute=blink_rate,
            drowsy=drowsy,
            yawning=yawning,
            valid=valid,
        )

    def close(self) -> None:
        self._face_mesh.close()
=======
"""MediaPipe Face Mesh-based blink, eyelid, and yawn analysis."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class FatigueMetrics:
    ear: float
    mar: float
    blink_count: int
    yawn_count: int
    blinks_per_minute: float
    drowsy: bool
    yawning: bool
    valid: bool


def _distance(np, first, second) -> float:
    first_xy = np.asarray((first.x, first.y))
    second_xy = np.asarray((second.x, second.y))
    return float(np.linalg.norm(first_xy - second_xy))


def calculate_ear(np, points, indices: tuple[int, ...]) -> float:
    """Calculate EAR from six ordered eye-corner/eyelid landmarks."""
    p1, p2, p3, p4, p5, p6 = (points[index] for index in indices)
    horizontal = _distance(np, p1, p4)
    if horizontal == 0:
        return 0.0
    return (_distance(np, p2, p6) + _distance(np, p3, p5)) / (2.0 * horizontal)


def calculate_mar(np, points) -> float:
    vertical = _distance(np, points[13], points[14])
    horizontal = _distance(np, points[78], points[308])
    if horizontal == 0:
        return 0.0
    return vertical / horizontal


class FatigueAnalyzer:
    EAR_CLOSED_THRESHOLD = 0.21
    EAR_OPEN_THRESHOLD = 0.23
    MAR_YAWN_THRESHOLD = 0.6

    def __init__(self) -> None:
        try:
            import cv2
            import mediapipe as mp
            import numpy as np
        except ImportError as exc:
            raise RuntimeError(
                "Fatigue analysis requires OpenCV, MediaPipe, and NumPy. "
                "Install them with `pip install -r requirements.txt`."
            ) from exc

        self._cv2 = cv2
        self._np = np
        self._face_mesh = mp.solutions.face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._started_at: float | None = None
        self._eye_closed_since: float | None = None
        self._yawn_started_at: float | None = None
        self._yawn_counted = False
        self._blink_count = 0
        self._yawn_count = 0

    def process(self, frame, now: float) -> FatigueMetrics:
        if self._started_at is None:
            self._started_at = now

        rgb = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB)
        result = self._face_mesh.process(rgb)
        if not result.multi_face_landmarks:
            self._eye_closed_since = None
            self._yawn_started_at = None
            self._yawn_counted = False
            return self._metrics(0.0, 0.0, False, False, now)

        points = result.multi_face_landmarks[0].landmark
        left_ear = calculate_ear(
            self._np, points, (33, 160, 158, 133, 153, 144)
        )
        right_ear = calculate_ear(
            self._np, points, (362, 385, 387, 263, 373, 380)
        )
        ear = (left_ear + right_ear) / 2.0
        mar = calculate_mar(self._np, points)

        if ear < self.EAR_CLOSED_THRESHOLD:
            if self._eye_closed_since is None:
                self._eye_closed_since = now
        elif ear >= self.EAR_OPEN_THRESHOLD and self._eye_closed_since is not None:
            if now - self._eye_closed_since <= 0.5:
                self._blink_count += 1
            self._eye_closed_since = None

        yawning = mar > self.MAR_YAWN_THRESHOLD
        if yawning:
            if self._yawn_started_at is None:
                self._yawn_started_at = now
            elif now - self._yawn_started_at >= 0.8 and not self._yawn_counted:
                self._yawn_count += 1
                self._yawn_counted = True
        else:
            self._yawn_started_at = None
            self._yawn_counted = False

        return self._metrics(ear, mar, True, yawning, now)

    def _metrics(
        self, ear: float, mar: float, valid: bool, yawning: bool, now: float
    ) -> FatigueMetrics:
        elapsed = max(0.0, now - (self._started_at if self._started_at is not None else now))
        blink_rate = self._blink_count * 60.0 / elapsed if elapsed > 0 else 0.0
        prolonged_eye_closure = (
            self._eye_closed_since is not None
            and now - self._eye_closed_since >= 1.0
        )
        low_blink_rate = elapsed >= 60.0 and blink_rate < 8.0
        prolonged_yawn = (
            self._yawn_started_at is not None
            and now - self._yawn_started_at >= 2.0
        )
        drowsy = valid and (prolonged_eye_closure or low_blink_rate or prolonged_yawn)
        return FatigueMetrics(
            ear=ear,
            mar=mar,
            blink_count=self._blink_count,
            yawn_count=self._yawn_count,
            blinks_per_minute=blink_rate,
            drowsy=drowsy,
            yawning=yawning,
            valid=valid,
        )

    def close(self) -> None:
        self._face_mesh.close()
>>>>>>> origin/main
