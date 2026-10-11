"""ErgoStudy webcam monitor."""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from modules.alerts import AlertManager
from modules.fatigue import FatigueAnalyzer
from modules.posture import PostureAnalyzer
from modules.posture_model import DEFAULT_MODEL_PATH, PostureSampleStore


ROOT = Path(__file__).resolve().parent
DATABASE_PATH = ROOT / "data" / "sessions.db"
POSTURE_LABEL_KEYS = {
    ord("1"): "Good",
    ord("2"): "Slouching",
    ord("3"): "Leaning",
}


@dataclass(frozen=True)
class SessionSummary:
    duration_seconds: float
    average_posture_score: float
    total_blinks: int
    total_yawns: int


def save_session(
    summary: SessionSummary,
    started_at: datetime,
    database_path: Path | None = None,
) -> None:
    database_path = database_path or DATABASE_PATH
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database_path)) as connection:
        with connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    duration_seconds REAL NOT NULL,
                    average_posture_score REAL NOT NULL,
                    total_blinks INTEGER NOT NULL,
                    total_yawns INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO sessions (
                    started_at, duration_seconds, average_posture_score,
                    total_blinks, total_yawns
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    started_at.isoformat(),
                    summary.duration_seconds,
                    summary.average_posture_score,
                    summary.total_blinks,
                    summary.total_yawns,
                ),
            )


def _load_vision_dependencies():
    try:
        import cv2
    except ImportError as exc:
        raise SystemExit(
            "OpenCV is missing. Install the project dependencies with "
            "`pip install -r requirements.txt`."
        ) from exc
    return cv2


def _draw_hud(
    cv2,
    frame,
    posture,
    fatigue,
    alerts: list[str],
    elapsed: float,
    sample_counts: dict[str, int],
    capture_message: str,
) -> None:
    height, width = frame.shape[:2]
    color_by_status = {
        "Good": (60, 190, 60),
        "Slouching": (0, 80, 255),
        "Leaning": (0, 150, 255),
    }
    color = color_by_status.get(posture.status, (220, 220, 220))
    lines = [
        (
            f"Posture: {posture.status}"
            + (" (MLP)" if posture.classifier_used else ""),
            color,
        ),
        (
            f"Neck angle: {posture.neck_angle:.1f} deg"
            if posture.neck_angle is not None
            else "Neck angle: --",
            (245, 245, 245),
        ),
        (f"EAR: {fatigue.ear:.3f}   MAR: {fatigue.mar:.3f}", (245, 245, 245)),
        (
            f"Blinks: {fatigue.blink_count}   Yawns: {fatigue.yawn_count}   "
            f"Blink rate: {fatigue.blinks_per_minute:.1f}/min",
            (245, 245, 245),
        ),
    ]
    if not posture.calibrated:
        lines.append(("Hold your ideal posture for 5 seconds to calibrate", (0, 200, 255)))
    elif posture.proximity_ratio is not None:
        lines.append((f"Screen distance ratio: {posture.proximity_ratio:.2f}", (245, 245, 245)))
    if fatigue.yawning:
        lines.append(("Yawning detected", (0, 150, 255)))
    fatigue_status = (
        "No face detected" if not fatigue.valid else "Drowsy" if fatigue.drowsy else "Normal"
    )
    lines.append((f"Fatigue: {fatigue_status}", (0, 80, 255) if fatigue.drowsy else (245, 245, 245)))
    lines.append(("Label this frame: 1=Good  2=Slouching  3=Leaning", (0, 200, 255)))
    lines.append(
        (
            f"Labeled samples: G {sample_counts['Good']}  S {sample_counts['Slouching']}  "
            f"L {sample_counts['Leaning']}",
            (245, 245, 245),
        )
    )
    if capture_message:
        lines.append((capture_message, (0, 220, 0)))

    cv2.rectangle(frame, (0, 0), (width, 20 + 25 * len(lines)), (20, 20, 20), -1)
    for index, (text, text_color) in enumerate(lines):
        cv2.putText(
            frame,
            text,
            (15, 27 + index * 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.62,
            text_color,
            2,
            cv2.LINE_AA,
        )

    if alerts:
        alert_text = "  |  ".join(alerts)
        cv2.rectangle(frame, (0, height - 55), (width, height), (20, 20, 20), -1)
        cv2.putText(
            frame,
            alert_text,
            (15, height - 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 70, 255),
            2,
            cv2.LINE_AA,
        )
    cv2.putText(
        frame,
        f"Session: {time.strftime('%H:%M:%S', time.gmtime(elapsed))}  |  q: quit",
        (max(15, width - 330), height - 15),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (220, 220, 220),
        1,
        cv2.LINE_AA,
    )


def run(camera_index: int, enable_beep: bool) -> SessionSummary:
    cv2 = _load_vision_dependencies()
    started_at = time.monotonic()
    started_at_utc = datetime.now(timezone.utc)
    session_id = started_at_utc.isoformat()
    sample_store = PostureSampleStore(DATABASE_PATH)
    sample_counts = sample_store.counts()
    capture_message = ""
    last_capture_at = float("-inf")
    camera = cv2.VideoCapture(camera_index)
    if not camera.isOpened():
        camera.release()
        raise RuntimeError(
            f"Could not open webcam {camera_index}. Check that it is connected "
            "and available to this application."
        )

    posture_analyzer = None
    fatigue_analyzer = None
    posture_score_total = 0.0
    posture_score_count = 0
    latest_fatigue = None

    try:
        posture_analyzer = PostureAnalyzer(DEFAULT_MODEL_PATH)
        fatigue_analyzer = FatigueAnalyzer()
        alert_manager = AlertManager()
        while True:
            success, frame = camera.read()
            if not success:
                raise RuntimeError("The webcam stopped providing frames.")

            now = time.monotonic()
            posture = posture_analyzer.process(frame, now)
            fatigue = fatigue_analyzer.process(frame, now)
            posture_analyzer.draw_landmarks(frame)
            latest_fatigue = fatigue
            if posture.score is not None:
                posture_score_total += posture.score
                posture_score_count += 1

            new_alerts = alert_manager.update(posture.status, fatigue.drowsy)
            if enable_beep and new_alerts:
                if sys.platform == "win32":
                    import winsound

                    winsound.MessageBeep()
                else:
                    print("\a", end="", flush=True)

            elapsed = now - started_at
            _draw_hud(
                cv2,
                frame,
                posture,
                fatigue,
                list(alert_manager.active_alerts),
                elapsed,
                sample_counts,
                capture_message,
            )
            cv2.imshow("ErgoStudy - press q to quit", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            label = POSTURE_LABEL_KEYS.get(key)
            if label is not None:
                if now - last_capture_at < 0.5:
                    capture_message = "Wait before recording the next sample"
                elif posture.features is None:
                    capture_message = "Wait for posture calibration to finish"
                else:
                    sample_store.record(posture.features, label, session_id)
                    sample_counts = sample_store.counts()
                    capture_message = f"Recorded {label} sample"
                    last_capture_at = now
    finally:
        camera.release()
        if posture_analyzer is not None:
            posture_analyzer.close()
        if fatigue_analyzer is not None:
            fatigue_analyzer.close()
        cv2.destroyAllWindows()

    if latest_fatigue is None:
        raise RuntimeError("The webcam session ended before any frame was processed.")

    duration = time.monotonic() - started_at
    summary = SessionSummary(
        duration_seconds=duration,
        average_posture_score=(
            posture_score_total / posture_score_count if posture_score_count else 0.0
        ),
        total_blinks=latest_fatigue.blink_count,
        total_yawns=latest_fatigue.yawn_count,
    )
    save_session(summary, started_at_utc)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Local webcam-based ergonomic study companion.")
    parser.add_argument("--camera", type=int, default=0, help="webcam device index (default: 0)")
    parser.add_argument(
        "--beep",
        action="store_true",
        help="play a subtle system beep when a sustained alert starts",
    )
    args = parser.parse_args()

    try:
        summary = run(args.camera, args.beep)
    except RuntimeError as exc:
        parser.exit(1, f"ErgoStudy: {exc}\n")

    print("\nErgoStudy session summary")
    print(f"  Study time: {time.strftime('%H:%M:%S', time.gmtime(summary.duration_seconds))}")
    print(f"  Average posture score: {summary.average_posture_score:.1f}/100")
    print(f"  Total blinks: {summary.total_blinks}")
    print(f"  Total yawns: {summary.total_yawns}")
    print(f"  Saved to: {DATABASE_PATH}")


if __name__ == "__main__":
    main()
