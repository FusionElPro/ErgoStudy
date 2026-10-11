"""Train a subject-separated posture KNN from pose landmarks in a CSV file."""

from __future__ import annotations

import argparse

from modules.posture_knn import DEFAULT_KNN_MODEL_PATH, train_posture_knn


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train a subject-separated KNN posture classifier from CSV landmarks."
    )
    parser.add_argument("csv", help="CSV containing MediaPipe pose landmarks and posture labels")
    parser.add_argument("--model", default=str(DEFAULT_KNN_MODEL_PATH))
    args = parser.parse_args()

    try:
        result = train_posture_knn(args.csv, args.model)
    except (RuntimeError, ValueError) as exc:
        parser.exit(1, f"Posture KNN training failed: {exc}\n")

    print(f"Trained KNN on {result.sample_count} samples from {result.subject_count} subjects.")
    print(f"Mapped class counts: {result.class_counts}")
    print(
        f"Subject-held-out evaluation: accuracy {result.accuracy:.1%}, "
        f"macro F1 {result.macro_f1:.3f} "
        f"(test subjects: {', '.join(result.test_subjects)})."
    )
    print(f"Saved model to: {result.model_path}")
    print("Restart ErgoStudy to use KNN as the primary posture classifier.")


if __name__ == "__main__":
    main()
