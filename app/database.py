"""SQLite persistence for subjects, study blocks, and ergonomic samples."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from typing import Any

from main import DATABASE_PATH


class StudyDatabase:
    def __init__(self, path: Path = DATABASE_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with closing(self.connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS subjects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    color TEXT NOT NULL DEFAULT '#10B981',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS study_sessions (
                    id TEXT PRIMARY KEY,
                    subject_id INTEGER REFERENCES subjects(id) ON DELETE SET NULL,
                    kind TEXT NOT NULL CHECK (kind IN ('focus', 'break')),
                    status TEXT NOT NULL DEFAULT 'running'
                        CHECK (status IN ('running', 'completed', 'interrupted')),
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    duration_seconds REAL NOT NULL DEFAULT 0,
                    average_posture_score REAL,
                    total_blinks INTEGER NOT NULL DEFAULT 0,
                    total_yawns INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS ergonomic_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES study_sessions(id) ON DELETE CASCADE,
                    recorded_at TEXT NOT NULL,
                    posture_status TEXT NOT NULL,
                    posture_score REAL,
                    neck_angle REAL,
                    proximity_ratio REAL,
                    ear REAL,
                    mar REAL,
                    blink_count INTEGER NOT NULL DEFAULT 0,
                    yawn_count INTEGER NOT NULL DEFAULT 0,
                    drowsy INTEGER NOT NULL DEFAULT 0,
                    yawning INTEGER NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_study_sessions_started_at
                    ON study_sessions(started_at);
                CREATE INDEX IF NOT EXISTS idx_study_sessions_subject
                    ON study_sessions(subject_id, started_at);
                CREATE INDEX IF NOT EXISTS idx_ergonomic_metrics_session
                    ON ergonomic_metrics(session_id, recorded_at);
                """
            )
            connection.execute(
                """
                UPDATE study_sessions
                SET status = 'interrupted',
                    ended_at = COALESCE(ended_at, CURRENT_TIMESTAMP),
                    duration_seconds = MAX(
                        duration_seconds,
                        (julianday(COALESCE(ended_at, CURRENT_TIMESTAMP)) - julianday(started_at))
                            * 86400
                    )
                WHERE status = 'running'
                """
            )

    def list_subjects(self) -> list[dict[str, Any]]:
        with closing(self.connect()) as connection:
            rows = connection.execute(
                """
                SELECT s.id, s.name, s.color, s.created_at,
                    COALESCE(SUM(CASE WHEN l.kind = 'focus' THEN l.duration_seconds ELSE 0 END), 0)
                    AS total_focus_seconds
                FROM subjects s
                LEFT JOIN study_sessions l ON l.subject_id = s.id
                    AND l.status = 'completed'
                GROUP BY s.id
                ORDER BY s.created_at, s.id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def create_subject(self, name: str, color: str) -> dict[str, Any]:
        created_at = datetime.now(timezone.utc).isoformat()
        with closing(self.connect()) as connection, connection:
            cursor = connection.execute(
                "INSERT INTO subjects (name, color, created_at) VALUES (?, ?, ?)",
                (name, color, created_at),
            )
            row = connection.execute(
                """
                SELECT id, name, color, created_at, 0 AS total_focus_seconds
                FROM subjects WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()
        if row is None:
            raise RuntimeError("The subject was saved but could not be read back.")
        return dict(row)

    def delete_subject(self, subject_id: int) -> bool:
        with closing(self.connect()) as connection, connection:
            cursor = connection.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))
        return cursor.rowcount > 0

    def subject_exists(self, subject_id: int) -> bool:
        with closing(self.connect()) as connection:
            return connection.execute(
                "SELECT 1 FROM subjects WHERE id = ?", (subject_id,)
            ).fetchone() is not None

    def begin_session(
        self,
        session_id: str,
        subject_id: int | None,
        kind: str,
        started_at: str,
    ) -> None:
        with closing(self.connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO study_sessions (id, subject_id, kind, started_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, subject_id, kind, started_at),
            )

    def record_metrics(self, session_id: str, recorded_at: str, metrics: dict[str, Any]) -> None:
        with closing(self.connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO ergonomic_metrics (
                    session_id, recorded_at, posture_status, posture_score,
                    neck_angle, proximity_ratio, ear, mar, blink_count,
                    yawn_count, drowsy, yawning
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    recorded_at,
                    metrics["posture_status"],
                    metrics["posture_score"],
                    metrics["neck_angle"],
                    metrics["proximity_ratio"],
                    metrics["ear"],
                    metrics["mar"],
                    metrics["blink_count"],
                    metrics["yawn_count"],
                    int(metrics["drowsy"]),
                    int(metrics["yawning"]),
                ),
            )

    def finish_session(
        self,
        session_id: str,
        ended_at: str,
        duration_seconds: float,
        average_posture_score: float | None,
        total_blinks: int,
        total_yawns: int,
    ) -> None:
        with closing(self.connect()) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE study_sessions
                SET status = 'completed', ended_at = ?, duration_seconds = ?,
                    average_posture_score = ?, total_blinks = ?, total_yawns = ?
                WHERE id = ? AND status = 'running'
                """,
                (
                    ended_at,
                    duration_seconds,
                    average_posture_score,
                    total_blinks,
                    total_yawns,
                    session_id,
                ),
            )
        if cursor.rowcount != 1:
            raise RuntimeError(f"Could not complete active study session {session_id}.")

    def session_history(self, limit: int = 20) -> list[dict[str, Any]]:
        with closing(self.connect()) as connection:
            rows = connection.execute(
                """
                SELECT l.id, l.kind, l.status, l.started_at, l.ended_at,
                    l.duration_seconds, l.average_posture_score,
                    l.total_blinks, l.total_yawns, s.name AS subject_name,
                    s.color AS subject_color
                FROM study_sessions l
                LEFT JOIN subjects s ON s.id = l.subject_id
                WHERE l.status IN ('completed', 'interrupted')
                ORDER BY l.started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def statistics(self, days: int = 7, timezone_offset_minutes: int = 0) -> dict[str, Any]:
        local_now = datetime.now(timezone.utc) - timedelta(minutes=timezone_offset_minutes)
        today = local_now.date()
        first_day = today - timedelta(days=days - 1)
        start_utc = datetime.combine(first_day, datetime_time.min, timezone.utc) + timedelta(
            minutes=timezone_offset_minutes
        )
        end_utc = datetime.combine(today + timedelta(days=1), datetime_time.min, timezone.utc) + timedelta(
            minutes=timezone_offset_minutes
        )
        local_time_shift = f"{-timezone_offset_minutes:+d} minutes"
        first_day_text = first_day.isoformat()
        with closing(self.connect()) as connection:
            totals = connection.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN kind = 'focus' THEN duration_seconds ELSE 0 END), 0)
                        AS focus_seconds,
                    COALESCE(SUM(CASE WHEN kind = 'break' THEN duration_seconds ELSE 0 END), 0)
                        AS break_seconds,
                    COALESCE(SUM(total_blinks), 0) AS total_blinks,
                    COALESCE(SUM(total_yawns), 0) AS total_yawns,
                    AVG(CASE WHEN kind = 'focus' THEN average_posture_score END)
                        AS average_posture_score
                FROM study_sessions
                WHERE status = 'completed' AND started_at >= ? AND started_at < ?
                """,
                (start_utc.isoformat(), end_utc.isoformat()),
            ).fetchone()
            daily_rows = connection.execute(
                """
                SELECT date(started_at, ?) AS day,
                    SUM(CASE WHEN kind = 'focus' THEN duration_seconds ELSE 0 END)
                        AS focus_seconds,
                    SUM(CASE WHEN kind = 'break' THEN duration_seconds ELSE 0 END)
                        AS break_seconds
                FROM study_sessions
                WHERE status = 'completed' AND started_at >= ? AND started_at < ?
                GROUP BY date(started_at, ?)
                """,
                (
                    local_time_shift,
                    start_utc.isoformat(),
                    end_utc.isoformat(),
                    local_time_shift,
                ),
            ).fetchall()
            subject_rows = connection.execute(
                """
                SELECT s.id, s.name, s.color,
                    COALESCE(SUM(l.duration_seconds), 0) AS focus_seconds
                FROM subjects s
                LEFT JOIN study_sessions l ON l.subject_id = s.id
                    AND l.kind = 'focus' AND l.status = 'completed'
                    AND l.started_at >= ? AND l.started_at < ?
                GROUP BY s.id
                ORDER BY focus_seconds DESC, s.name
                """,
                (start_utc.isoformat(), end_utc.isoformat()),
            ).fetchall()

        by_day = {row["day"]: dict(row) for row in daily_rows}
        daily = []
        for offset in range(days):
            day = first_day + timedelta(days=offset)
            values = by_day.get(day.isoformat(), {})
            daily.append(
                {
                    "date": day.isoformat(),
                    "focus_seconds": values.get("focus_seconds", 0),
                    "break_seconds": values.get("break_seconds", 0),
                }
            )
        return {
            "from": first_day_text,
            "to": today.isoformat(),
            "focus_seconds": totals["focus_seconds"],
            "break_seconds": totals["break_seconds"],
            "today_focus_seconds": by_day.get(today.isoformat(), {}).get("focus_seconds", 0),
            "today_break_seconds": by_day.get(today.isoformat(), {}).get("break_seconds", 0),
            "average_posture_score": totals["average_posture_score"],
            "total_blinks": totals["total_blinks"],
            "total_yawns": totals["total_yawns"],
            "daily": daily,
            "subjects": [dict(row) for row in subject_rows],
        }
