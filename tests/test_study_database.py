import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from app.database import StudyDatabase


class StudyDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "sessions.db"
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                """
                CREATE TABLE sessions (
                    id INTEGER PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    duration_seconds REAL NOT NULL,
                    average_posture_score REAL NOT NULL,
                    total_blinks INTEGER NOT NULL,
                    total_yawns INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT INTO sessions VALUES (1, 'existing', 10, 90, 2, 0)"
            )
            connection.commit()
        finally:
            connection.close()
        self.database = StudyDatabase(self.path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_additive_schema_preserves_legacy_rows_and_tracks_subject_sessions(self):
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(
                connection.execute("SELECT started_at FROM sessions WHERE id = 1").fetchone()[0],
                "existing",
            )

        subject = self.database.create_subject("Vector Calculus", "#10B981")
        self.assertEqual(subject["total_focus_seconds"], 0)
        now = datetime.now(timezone.utc).isoformat()
        self.database.begin_session("focus-1", subject["id"], "focus", now)
        self.database.record_metrics(
            "focus-1",
            now,
            {
                "posture_status": "Good",
                "posture_score": 92.0,
                "neck_angle": 4.0,
                "proximity_ratio": 1.0,
                "ear": 0.3,
                "mar": 0.2,
                "blink_count": 7,
                "yawn_count": 1,
                "drowsy": False,
                "yawning": False,
            },
        )
        self.database.finish_session("focus-1", now, 3600, 92.0, 7, 1)

        stats = self.database.statistics()
        self.assertEqual(stats["focus_seconds"], 3600)
        self.assertEqual(stats["today_focus_seconds"], 3600)
        self.assertEqual(stats["total_blinks"], 7)
        self.assertEqual(stats["total_yawns"], 1)
        self.assertEqual(stats["average_posture_score"], 92.0)
        self.assertEqual(stats["subjects"][0]["name"], "Vector Calculus")
        self.assertEqual(len(stats["daily"]), 7)
        self.assertEqual(self.database.session_history()[0]["subject_name"], "Vector Calculus")

    def test_deleting_subject_keeps_its_study_history(self):
        subject = self.database.create_subject("Physics", "#F59E0B")
        now = datetime.now(timezone.utc).isoformat()
        self.database.begin_session("focus-2", subject["id"], "focus", now)
        self.database.finish_session("focus-2", now, 60, None, 0, 0)

        self.assertTrue(self.database.delete_subject(subject["id"]))
        self.assertIsNone(self.database.session_history()[0]["subject_name"])
        self.assertFalse(self.database.delete_subject(subject["id"]))

    def test_startup_marks_abandoned_blocks_as_interrupted(self):
        now = datetime.now(timezone.utc).isoformat()
        self.database.begin_session("abandoned", None, "focus", now)

        migrated_database = StudyDatabase(self.path)
        history = migrated_database.session_history()

        self.assertEqual(history[0]["id"], "abandoned")
        self.assertEqual(history[0]["status"], "interrupted")


if __name__ == "__main__":
    unittest.main()
