import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from modules.posture import PostureAnalyzer, head_tilt_angle, mean_angle, signed_angle_delta


class PostureAngleTests(unittest.TestCase):
    def test_signed_angle_delta_wraps_at_half_turn(self):
        self.assertAlmostEqual(signed_angle_delta(-179.0, 179.0), 2.0)
        self.assertAlmostEqual(signed_angle_delta(179.0, -179.0), -2.0)

    def test_mean_angle_handles_wraparound(self):
        self.assertAlmostEqual(abs(mean_angle([179.0, -179.0])), 180.0)

    def test_head_tilt_is_measured_relative_to_shoulders(self):
        self.assertAlmostEqual(head_tilt_angle(0.0, 0.0, 1.0, 0.0, 0.0), 0.0)
        self.assertAlmostEqual(
            head_tilt_angle(0.0, 0.0, 1.0, 1.0, 0.0),
            45.0,
        )

    def test_clear_head_tilt_overrides_good_knn_prediction(self):
        pose_landmarks = [
            SimpleNamespace(x=0.5, y=0.5, z=0.0, visibility=1.0)
            for _ in range(33)
        ]
        pose_landmarks[0] = SimpleNamespace(x=0.5, y=0.3, z=0.0, visibility=1.0)
        pose_landmarks[2] = SimpleNamespace(x=0.45, y=0.4, z=0.0, visibility=1.0)
        pose_landmarks[5] = SimpleNamespace(x=0.55, y=0.45, z=0.0, visibility=1.0)
        pose_landmarks[11] = SimpleNamespace(x=0.4, y=0.5, z=0.0, visibility=1.0)
        pose_landmarks[12] = SimpleNamespace(x=0.6, y=0.5, z=0.0, visibility=1.0)
        result = SimpleNamespace(
            pose_landmarks=SimpleNamespace(landmark=pose_landmarks),
            pose_world_landmarks=SimpleNamespace(landmark=pose_landmarks),
        )
        analyzer = object.__new__(PostureAnalyzer)
        analyzer._cv2 = SimpleNamespace(
            COLOR_BGR2RGB=0,
            cvtColor=lambda frame, _code: frame,
        )
        analyzer._np = np
        analyzer._mp_pose = SimpleNamespace(
            PoseLandmark=SimpleNamespace(
                NOSE=SimpleNamespace(value=0),
                LEFT_EYE=SimpleNamespace(value=2),
                RIGHT_EYE=SimpleNamespace(value=5),
                LEFT_SHOULDER=SimpleNamespace(value=11),
                RIGHT_SHOULDER=SimpleNamespace(value=12),
            )
        )
        analyzer._pose = SimpleNamespace(process=lambda _frame: result)
        analyzer._baseline = (0.0, 0.2, 0.0, 0.0)
        analyzer._baseline_head_tilt = 0.0
        analyzer._calibration_started = 0.0
        analyzer._calibration_samples = []
        analyzer._calibration_head_tilt_samples = []
        analyzer._classifier = object()
        analyzer._classifier_name = "KNN"
        analyzer._knn_distance_limit = 12.2
        analyzer._knn_landmark_indices = tuple(range(33))
        analyzer._predict_knn_posture = Mock(return_value=("Good", 1.0))

        metrics = analyzer.process(object(), 6.0)

        self.assertEqual(metrics.status, "Leaning")
        self.assertEqual(metrics.rule_status, "Leaning")
        self.assertAlmostEqual(metrics.head_tilt_delta, 26.565, places=2)
        self.assertTrue(metrics.geometric_override)
        analyzer._predict_knn_posture.assert_called_once()


if __name__ == "__main__":
    unittest.main()
