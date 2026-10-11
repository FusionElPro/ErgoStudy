"""User-labeled posture samples and a small, calibrated MLP classifier."""

from __future__ import annotations

import math
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeAlias


LABELS = ("Good", "Slouching", "Leaning")
FEATURE_COUNT = 4
MINIMUM_SAMPLES_PER_LABEL = 10

FeatureVector: TypeAlias = tuple[float, float, float, float]
StoredSample: TypeAlias = tuple[FeatureVector, str, str]

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE_PATH = ROOT / "data" / "sessions.db"
DEFAULT_MODEL_PATH = ROOT / "data" / "posture_mlp.joblib"


@dataclass(frozen=True)
class TrainingResult:
    model_path: Path
    accuracy: float
    macro_f1: float
    sample_count: int
    training_session_count: int
    test_session_count: int


class PostureSampleStore:
    def __init__(self, database_path: Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS posture_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    captured_at TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    neck_angle_delta REAL NOT NULL,
                    proximity_ratio REAL NOT NULL,
                    shoulder_tilt_delta REAL NOT NULL,
                    nose_offset_delta REAL NOT NULL,
                    label TEXT NOT NULL CHECK (label IN ('Good', 'Slouching', 'Leaning'))
                )
                """
            )
            connection.commit()

    def record(
        self,
        features: FeatureVector,
        label: str,
        session_id: str,
        captured_at: datetime | None = None,
    ) -> None:
        if label not in LABELS:
            raise ValueError(f"label must be one of {', '.join(LABELS)}")
        if len(features) != FEATURE_COUNT:
            raise ValueError(f"features must contain exactly {FEATURE_COUNT} values")
        if not all(math.isfinite(value) for value in features):
            raise ValueError("features must all be finite numbers")

        with closing(sqlite3.connect(self.database_path)) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO posture_samples (
                        captured_at, session_id, neck_angle_delta,
                        proximity_ratio, shoulder_tilt_delta, nose_offset_delta, label
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        (captured_at or datetime.now(timezone.utc)).isoformat(),
                        session_id,
                        *features,
                        label,
                    ),
                )

    def counts(self) -> dict[str, int]:
        with closing(sqlite3.connect(self.database_path)) as connection:
            rows = connection.execute(
                "SELECT label, COUNT(*) FROM posture_samples GROUP BY label"
            ).fetchall()
        counts = {label: 0 for label in LABELS}
        counts.update({label: count for label, count in rows})
        return counts

    def samples(self) -> list[StoredSample]:
        with closing(sqlite3.connect(self.database_path)) as connection:
            rows = connection.execute(
                """
                SELECT neck_angle_delta, proximity_ratio,
                       shoulder_tilt_delta, nose_offset_delta, label, session_id
                FROM posture_samples
                ORDER BY id
                """
            ).fetchall()
        return [
            ((neck, proximity, tilt, offset), label, session_id)
            for neck, proximity, tilt, offset, label, session_id in rows
        ]


def train_posture_classifier(
    database_path: Path | str = DEFAULT_DATABASE_PATH,
    model_path: Path | str = DEFAULT_MODEL_PATH,
) -> TrainingResult:
    database_path = Path(database_path)
    model_path = Path(model_path)
    samples = PostureSampleStore(database_path).samples()
    counts = {label: 0 for label in LABELS}
    sessions_by_label = {label: set() for label in LABELS}
    for _, label, session_id in samples:
        counts[label] += 1
        sessions_by_label[label].add(session_id)

    missing = {
        label: count
        for label, count in counts.items()
        if count < MINIMUM_SAMPLES_PER_LABEL
    }
    if missing:
        details = ", ".join(
            f"{label}: {counts[label]}/{MINIMUM_SAMPLES_PER_LABEL}"
            for label in LABELS
        )
        raise ValueError(f"Not enough labeled posture samples ({details}).")
    labels_without_multiple_sessions = [
        label for label in LABELS if len(sessions_by_label[label]) < 2
    ]
    if labels_without_multiple_sessions:
        names = ", ".join(labels_without_multiple_sessions)
        raise ValueError(
            f"Capture each posture label in at least two separate sessions before "
            f"training; missing session diversity for: {names}."
        )

    try:
        from joblib import dump
        from sklearn.metrics import accuracy_score, f1_score
        from sklearn.model_selection import GroupShuffleSplit
        from sklearn.neural_network import MLPClassifier
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:
        raise RuntimeError(
            "Could not import scikit-learn and its native extensions: "
            f"{exc}"
        ) from exc

    features = [sample[0] for sample in samples]
    targets = [sample[1] for sample in samples]
    groups = [sample[2] for sample in samples]
    splitter = GroupShuffleSplit(n_splits=100, test_size=0.25, random_state=42)
    split = next(
        (
            (train_indices, test_indices)
            for train_indices, test_indices in splitter.split(features, targets, groups)
            if set(targets[index] for index in train_indices) == set(LABELS)
            and set(targets[index] for index in test_indices) == set(LABELS)
        ),
        None,
    )
    if split is None:
        raise ValueError(
            "Could not make a session-separated train/test split containing all three "
            "labels in both sets. Capture all labels in more sessions."
        )
    train_indices, test_indices = split

    classifier = make_pipeline(
        StandardScaler(),
        MLPClassifier(
            hidden_layer_sizes=(16, 8),
            alpha=0.001,
            max_iter=1000,
            random_state=42,
        ),
    )
    classifier.fit(
        [features[index] for index in train_indices],
        [targets[index] for index in train_indices],
    )
    predictions = classifier.predict([features[index] for index in test_indices])
    accuracy = float(accuracy_score([targets[index] for index in test_indices], predictions))
    macro_f1 = float(f1_score(
        [targets[index] for index in test_indices],
        predictions,
        labels=LABELS,
        average="macro",
        zero_division=0,
    ))

    model_path.parent.mkdir(parents=True, exist_ok=True)
    dump(classifier, model_path)
    return TrainingResult(
        model_path=model_path,
        accuracy=accuracy,
        macro_f1=macro_f1,
        sample_count=len(samples),
        training_session_count=len({groups[index] for index in train_indices}),
        test_session_count=len({groups[index] for index in test_indices}),
    )
