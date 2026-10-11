"""Train and evaluate the user-labeled posture MLP."""

from __future__ import annotations

import argparse

from modules.posture_model import (
    DEFAULT_DATABASE_PATH,
    DEFAULT_MODEL_PATH,
    train_posture_classifier,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train a session-separated MLP posture classifier from labeled samples."
    )
    parser.add_argument("--database", default=str(DEFAULT_DATABASE_PATH))
    parser.add_argument("--model", default=str(DEFAULT_MODEL_PATH))
    args = parser.parse_args()

    try:
        result = train_posture_classifier(args.database, args.model)
    except (RuntimeError, ValueError) as exc:
        parser.exit(1, f"Posture training failed: {exc}\n")

    print(f"Trained on {result.sample_count} labeled samples.")
    print(
        "Session-separated evaluation: "
        f"accuracy {result.accuracy:.1%}, macro F1 {result.macro_f1:.3f} "
        f"({result.training_session_count} train sessions, "
        f"{result.test_session_count} test sessions)."
    )
    print(f"Saved model to: {result.model_path}")
    print("Restart ErgoStudy to use the trained model for live posture predictions.")


if __name__ == "__main__":
    main()
