import tempfile
import unittest
from pathlib import Path

from modules.posture_model import LABELS, PostureSampleStore, train_posture_classifier


class PostureModelTests(unittest.TestCase):
    def test_store_counts_labels_and_samples_across_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PostureSampleStore(Path(directory) / "samples.db")
            store.record((0.0, 1.0, 0.0, 0.0), "Good", "session-1")
            store.record((16.0, 1.0, 0.0, 0.0), "Slouching", "session-1")

            self.assertEqual(store.counts(), {"Good": 1, "Slouching": 1, "Leaning": 0})
            self.assertEqual(len(store.samples()), 2)

    def test_rejects_invalid_labels_and_non_finite_features(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PostureSampleStore(Path(directory) / "samples.db")

            with self.assertRaises(ValueError):
                store.record((0.0, 1.0, 0.0, 0.0), "Unknown", "session-1")
            with self.assertRaises(ValueError):
                store.record((float("nan"), 1.0, 0.0, 0.0), "Good", "session-1")

    def test_trains_and_saves_mlp_from_session_separated_samples(self):
        try:
            from sklearn.metrics import accuracy_score
        except ImportError as exc:
            self.skipTest(f"scikit-learn metrics are unavailable: {exc}")
        self.assertTrue(callable(accuracy_score))

        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "samples.db"
            model_path = Path(directory) / "posture_mlp.joblib"
            store = PostureSampleStore(database_path)
            for session_index in range(2):
                session = f"session-{session_index}"
                for sample_index in range(12):
                    variation = (sample_index % 4) * 0.2 + session_index * 0.1
                    examples = {
                        "Good": (variation, 1.0 + variation / 100, variation, variation / 10),
                        "Slouching": (
                            18.0 + variation,
                            1.0 + variation / 100,
                            variation,
                            variation / 10,
                        ),
                        "Leaning": (
                            variation,
                            1.45 + variation / 100,
                            12.0 + variation,
                            0.3 + variation / 10,
                        ),
                    }
                    for label in LABELS:
                        store.record(examples[label], label, session)

            result = train_posture_classifier(database_path, model_path)

            self.assertTrue(model_path.exists())
            self.assertEqual(result.sample_count, 72)
            self.assertEqual(result.training_session_count + result.test_session_count, 2)
            self.assertGreaterEqual(result.accuracy, 0.8)

    def test_training_requires_more_than_one_capture_session_per_label(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "samples.db"
            store = PostureSampleStore(database_path)
            for sample_index in range(10):
                for label in LABELS:
                    store.record((float(sample_index), 1.0, 0.0, 0.0), label, "only-session")

            with self.assertRaisesRegex(ValueError, "at least two separate sessions"):
                train_posture_classifier(database_path, Path(directory) / "model.joblib")


if __name__ == "__main__":
    unittest.main()
