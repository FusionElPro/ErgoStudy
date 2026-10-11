"""Train a subject-separated KNN from world-space MediaPipe pose-landmark CSV data."""

from __future__ import annotations

import csv
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

import numpy as np
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .posture import POSE_LANDMARK_NAMES


LABEL_MAPPING = {
    "TUP": "Good",
    "TLF": "Slouching",
    "TLB": "Leaning",
    "TLL": "Leaning",
    "TLR": "Leaning",
}
POSTURE_LABELS = ("Good", "Slouching", "Leaning")
FEATURE_SPACE = "pose_world_landmarks"
FEATURE_NAMES = tuple(
    f"{landmark}_{axis}"
    for landmark in POSE_LANDMARK_NAMES
    for axis in ("x", "y", "z")
)
KNN_NEIGHBORS = 7
KNN_DISTANCE_QUANTILE = 0.99
KNN_DISTANCE_REFERENCE_SAMPLE_SIZE = 1024
KNN_DISTANCE_SAFETY_FACTOR = 5.0
KNN_LANDMARK_VISIBILITY_THRESHOLD = 0.5
KNN_MIN_VISIBLE_LANDMARKS = 5
DEFAULT_KNN_MODEL_PATH = Path(__file__).resolve().parent.parent / "data" / "posture_knn.joblib"

PoseVector: TypeAlias = tuple[float, ...]


@dataclass(frozen=True)
class KNNTrainingResult:
    model_path: Path
    sample_count: int
    subject_count: int
    accuracy: float
    macro_f1: float
    test_subjects: tuple[str, ...]
    class_counts: dict[str, int]


def _read_dataset(csv_path: Path) -> tuple[list[PoseVector], list[str], list[str]]:
    features: list[PoseVector] = []
    labels: list[str] = []
    subjects: list[str] = []
    expected_columns = set(FEATURE_NAMES) | {"subject", "upperbody_label"}

    try:
        with csv_path.open(newline="", encoding="utf-8-sig") as source:
            reader = csv.DictReader(source)
            columns = set(reader.fieldnames or ())
            missing_columns = expected_columns - columns
            if missing_columns:
                missing = ", ".join(sorted(missing_columns))
                raise ValueError(f"CSV is missing required columns: {missing}.")
            for row_number, row in enumerate(reader, start=2):
                raw_label = row.get("upperbody_label", "")
                label = LABEL_MAPPING.get(raw_label or "")
                subject = row.get("subject", "")
                if label is None:
                    raise ValueError(
                        f"CSV row {row_number} has unsupported upper-body label "
                        f"{raw_label!r}."
                    )
                if not subject:
                    raise ValueError(f"CSV row {row_number} has no subject identifier.")
                try:
                    vector = tuple(float(row[name]) for name in FEATURE_NAMES)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"CSV row {row_number} contains a missing or invalid landmark."
                    ) from exc
                if not all(math.isfinite(value) for value in vector):
                    raise ValueError(
                        f"CSV row {row_number} contains a non-finite landmark."
                    )
                features.append(vector)
                labels.append(label)
                subjects.append(subject)
    except OSError as exc:
        raise ValueError(f"Could not read posture dataset at {csv_path}: {exc}") from exc

    if not features:
        raise ValueError(f"No posture samples were found in {csv_path}.")
    return features, labels, subjects


def _make_classifier():
    return make_pipeline(
        StandardScaler(),
        KNeighborsClassifier(n_neighbors=KNN_NEIGHBORS, weights="distance"),
    )


def estimate_knn_distance_limit(classifier) -> float:
    """Estimate a tolerant upper bound from training-set neighbor distances."""
    knn = classifier.named_steps["kneighborsclassifier"]
    training_vectors = knn._fit_X
    sample_count = min(KNN_DISTANCE_REFERENCE_SAMPLE_SIZE, len(training_vectors))
    if sample_count < 2:
        raise ValueError("At least two KNN training samples are required.")

    sample_indices = np.random.default_rng(42).choice(
        len(training_vectors), size=sample_count, replace=False
    )
    neighbor_count = min(KNN_NEIGHBORS + 1, len(training_vectors))
    distances, _ = knn.kneighbors(
        training_vectors[sample_indices], n_neighbors=neighbor_count
    )
    return float(
        np.quantile(distances[:, -1], KNN_DISTANCE_QUANTILE)
        * KNN_DISTANCE_SAFETY_FACTOR
    )


def predict_knn_posture(
    classifier,
    features: PoseVector,
    distance_limit: float,
    landmark_visibility: tuple[float, ...] | None = None,
) -> tuple[str, float]:
    """Reject a KNN class when the frame is unlike the model's training samples."""
    scaler = classifier.named_steps["standardscaler"]
    knn = classifier.named_steps["kneighborsclassifier"]
    scaled_features = scaler.transform([features])
    if landmark_visibility is None:
        distances, _ = knn.kneighbors(scaled_features, n_neighbors=KNN_NEIGHBORS)
        neighbor_distance = float(distances[0, -1])
        if neighbor_distance > distance_limit:
            return "Uncertain", neighbor_distance
        return str(classifier.predict([features])[0]), neighbor_distance

    if len(features) != len(landmark_visibility) * 3:
        raise ValueError(
            "KNN landmark visibility must contain one value per three coordinates."
        )
    visible_landmarks = np.isfinite(landmark_visibility) & (
        np.asarray(landmark_visibility) >= KNN_LANDMARK_VISIBILITY_THRESHOLD
    )
    visible_coordinates = np.repeat(visible_landmarks, 3)
    visible_count = int(np.count_nonzero(visible_landmarks))
    if visible_count == 0:
        distances, _ = knn.kneighbors(scaled_features, n_neighbors=KNN_NEIGHBORS)
        return "Uncertain", float(distances[0, -1])

    distances_to_training = np.linalg.norm(
        knn._fit_X[:, visible_coordinates] - scaled_features[0, visible_coordinates],
        axis=1,
    )
    distances_to_training *= math.sqrt(len(features) / np.count_nonzero(visible_coordinates))
    neighbor_indices = np.argpartition(
        distances_to_training, KNN_NEIGHBORS - 1
    )[:KNN_NEIGHBORS]
    neighbor_indices = neighbor_indices[
        np.argsort(distances_to_training[neighbor_indices])
    ]
    neighbor_distances = distances_to_training[neighbor_indices]
    neighbor_distance = float(neighbor_distances[-1])
    if (
        visible_count < KNN_MIN_VISIBLE_LANDMARKS
        or neighbor_distance > distance_limit
    ):
        return "Uncertain", neighbor_distance

    neighbor_labels = knn._y[neighbor_indices]
    if np.any(neighbor_distances == 0):
        weights = (neighbor_distances == 0).astype(float)
    else:
        weights = 1 / neighbor_distances
    votes = np.bincount(
        neighbor_labels,
        weights=weights,
        minlength=len(classifier.classes_),
    )
    return str(classifier.classes_[int(np.argmax(votes))]), neighbor_distance


def train_posture_knn(
    csv_path: Path | str,
    model_path: Path | str = DEFAULT_KNN_MODEL_PATH,
) -> KNNTrainingResult:
    csv_path = Path(csv_path)
    model_path = Path(model_path)
    features, labels, subjects = _read_dataset(csv_path)
    class_counts = dict(Counter(labels))
    if set(class_counts) != set(POSTURE_LABELS):
        raise ValueError(
            "The CSV must contain samples for Good, Slouching, and Leaning "
            "after applying the upper-body label mapping."
        )

    splitter = GroupShuffleSplit(n_splits=100, test_size=0.25, random_state=42)
    split = next(
        (
            (train_indices, test_indices)
            for train_indices, test_indices in splitter.split(features, labels, subjects)
            if set(labels[index] for index in train_indices) == set(POSTURE_LABELS)
            and set(labels[index] for index in test_indices) == set(POSTURE_LABELS)
        ),
        None,
    )
    if split is None:
        raise ValueError(
            "Could not hold out complete subjects while keeping all three posture "
            "classes in both sets. Add more labeled subjects."
        )
    train_indices, test_indices = split

    evaluation_model = _make_classifier()
    evaluation_model.fit(
        [features[index] for index in train_indices],
        [labels[index] for index in train_indices],
    )
    predictions = evaluation_model.predict(
        [features[index] for index in test_indices]
    )
    accuracy = float(
        accuracy_score([labels[index] for index in test_indices], predictions)
    )
    macro_f1 = float(
        f1_score(
            [labels[index] for index in test_indices],
            predictions,
            labels=POSTURE_LABELS,
            average="macro",
            zero_division=0,
        )
    )

    classifier = _make_classifier()
    classifier.fit(features, labels)
    knn_distance_limit = estimate_knn_distance_limit(classifier)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from joblib import dump
    except ImportError as exc:
        raise RuntimeError(f"Could not import joblib to save the KNN model: {exc}") from exc

    dump(
        {
            "classifier": classifier,
            "classifier_name": "KNN",
            "feature_names": FEATURE_NAMES,
            "feature_space": FEATURE_SPACE,
            "label_mapping": LABEL_MAPPING,
            "knn_distance_limit": knn_distance_limit,
        },
        model_path,
    )
    return KNNTrainingResult(
        model_path=model_path,
        sample_count=len(features),
        subject_count=len(set(subjects)),
        accuracy=accuracy,
        macro_f1=macro_f1,
        test_subjects=tuple(sorted({subjects[index] for index in test_indices})),
        class_counts=class_counts,
    )
