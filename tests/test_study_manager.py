import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.database import StudyDatabase
from app.study import StudySessionManager


class FakePostureAnalyzer:
    def __init__(self, *_args):
        self.closed = False
        self.classifier_name = "KNN"

    def process(self, _frame, _now):
        return SimpleNamespace(
            status="Good",
            score=95.0,
            neck_angle=3.0,
            proximity_ratio=1.0,
            calibrated=True,
            classifier_name="KNN",
        )

    def close(self):
        self.closed = True


class FakeFatigueAnalyzer:
    def process(self, _frame, _now):
        return SimpleNamespace(
            ear=0.3,
            mar=0.2,
            blink_count=4,
            yawn_count=0,
            blinks_per_minute=12.0,
            drowsy=False,
            yawning=False,
            valid=True,
        )

    def close(self):
        pass


class StudyManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "sessions.db"
        self.database = StudyDatabase(self.path)
        self.subject = self.database.create_subject("Engineering Physics", "#10B981")
        self.manager = StudySessionManager(self.database, database_path=self.path)

    def tearDown(self):
        if self.manager.status()["active"]:
            self.manager.stop()
        self.temporary_directory.cleanup()

    def test_webcam_metrics_are_saved_with_the_active_focus_session(self):
        with (
            patch("app.study.PostureAnalyzer", FakePostureAnalyzer),
            patch("app.study.FatigueAnalyzer", FakeFatigueAnalyzer),
            patch("app.study._decode_frame", return_value=object()),
        ):
            started = self.manager.start(self.subject["id"], "focus")
            self.assertTrue(started["active"])
            metrics = self.manager.process_frame(b"jpeg")
            self.assertEqual(metrics["metrics"]["posture_status"], "Good")
            self.assertEqual(metrics["metrics"]["ear"], 0.3)
            stopped = self.manager.stop()

        self.assertFalse(stopped["active"])
        self.assertEqual(stopped["total_blinks"], 4)
        self.assertEqual(stopped["average_posture_score"], 95.0)
        with closing(self.database.connect()) as connection:
            row = connection.execute(
                """
                SELECT l.status, l.kind, l.total_blinks, m.posture_status, m.ear
                FROM study_sessions l
                JOIN ergonomic_metrics m ON m.session_id = l.id
                """
            ).fetchone()
        self.assertEqual(tuple(row), ("completed", "focus", 4, "Good", 0.3))

    def test_study_webcam_requires_knn_classifier(self):
        class NonKnnAnalyzer(FakePostureAnalyzer):
            def __init__(self, *_args):
                super().__init__()
                self.classifier_name = "MLP"

        with (
            patch("app.study.PostureAnalyzer", NonKnnAnalyzer),
            patch("app.study.FatigueAnalyzer", FakeFatigueAnalyzer),
        ):
            with self.assertRaisesRegex(RuntimeError, "trained KNN"):
                self.manager.start(self.subject["id"], "focus")
        self.assertFalse(self.manager.status()["active"])


if __name__ == "__main__":
    unittest.main()
