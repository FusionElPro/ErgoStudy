import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from main import SessionSummary, save_session


class SessionStorageTests(unittest.TestCase):
    def test_saves_summary_with_session_start_time(self):
        started_at = datetime(2026, 10, 11, 4, 0, tzinfo=timezone.utc)
        summary = SessionSummary(120.5, 90.0, 30, 2)

        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "sessions.db"
            with patch("main.DATABASE_PATH", database_path):
                save_session(summary, started_at)

            with closing(sqlite3.connect(database_path)) as connection:
                row = connection.execute(
                    """
                    SELECT started_at, duration_seconds, average_posture_score,
                           total_blinks, total_yawns
                    FROM sessions
                    """
                ).fetchone()

        self.assertEqual(
            row,
            (started_at.isoformat(), 120.5, 90.0, 30, 2),
        )


if __name__ == "__main__":
    unittest.main()
