import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.posture import PostureAnalysisManager


class FakePostureAnalyzer:
    classifier_name = "KNN"

    def __init__(self, **_kwargs):
        self.closed = False

    def process(self, _frame, _now):
        return SimpleNamespace(
            status="Leaning",
            neck_angle=12.0,
            proximity_ratio=0.91,
            score=80.0,
            calibrated=True,
            valid=True,
            classifier_used=True,
            classifier_name="KNN",
            classifier_distance=2.0,
            classifier_distance_limit=6.0,
            rule_status="Good",
            head_tilt_delta=None,
            geometric_override=False,
        )

    def close(self):
        self.closed = True


class PostureAnalysisManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.model_path = Path(self.temporary_directory.name) / "posture_knn.joblib"
        self.model_path.touch()
        self.manager = PostureAnalysisManager(self.model_path)

    def tearDown(self):
        if self.manager.status()["active"]:
            self.manager.stop()
        self.temporary_directory.cleanup()

    def test_standalone_analysis_uses_knn_prediction_and_keeps_rule_as_secondary(self):
        with (
            patch("app.posture.PostureAnalyzer", FakePostureAnalyzer),
            patch("app.posture._decode_frame", return_value=object()),
        ):
            started = self.manager.start()
            self.assertEqual(started["model_name"], "KNN")
            result = self.manager.process_frame(b"jpeg")
            self.assertEqual(result["metrics"]["classifier_name"], "KNN")
            self.assertEqual(result["metrics"]["status"], "Leaning")
            self.assertEqual(result["metrics"]["classifier_distance"], 2.0)
            self.assertEqual(result["metrics"]["classifier_distance_limit"], 6.0)
            self.assertEqual(result["metrics"]["rule_status"], "Good")
            self.assertIsNone(result["metrics"]["head_tilt_delta"])
            self.assertFalse(result["metrics"]["geometric_override"])
            stopped = self.manager.stop()

        self.assertFalse(stopped["active"])

    def test_missing_knn_artifact_rejects_start(self):
        self.model_path.unlink()
        self.assertFalse(self.manager.status()["model_ready"])
        with self.assertRaisesRegex(RuntimeError, "trained KNN"):
            self.manager.start()

    def test_non_knn_classifier_is_closed_and_rejected(self):
        class FakeMlpAnalyzer(FakePostureAnalyzer):
            classifier_name = "MLP"

        with patch("app.posture.PostureAnalyzer", FakeMlpAnalyzer):
            with self.assertRaisesRegex(RuntimeError, "trained KNN"):
                self.manager.start()
        self.assertFalse(self.manager.status()["active"])


if __name__ == "__main__":
    unittest.main()
