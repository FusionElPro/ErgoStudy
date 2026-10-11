import csv
import tempfile
import unittest
from pathlib import Path

import numpy as np

from modules.posture_knn import (
    FEATURE_NAMES,
    FEATURE_SPACE,
    predict_knn_posture,
    train_posture_knn,
)


class PostureKNNTests(unittest.TestCase):
    def test_trains_subject_separated_knn_from_mapped_csv(self):
        try:
            from sklearn.neighbors import KNeighborsClassifier
        except ImportError as exc:
            self.skipTest(f"scikit-learn is unavailable: {exc}")
        self.assertTrue(callable(KNeighborsClassifier))

        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "posture.csv"
            model_path = Path(directory) / "posture_knn.joblib"
            fields = ["subject", "upperbody_label", "lowerbody_label", *FEATURE_NAMES]
            with csv_path.open("w", newline="", encoding="utf-8") as destination:
                writer = csv.DictWriter(destination, fieldnames=fields)
                writer.writeheader()
                for subject in range(4):
                    for sample in range(3):
                        for label, value in (
                            ("TUP", 0.0),
                            ("TLF", 10.0),
                            ("TLB", 20.0),
                            ("TLL", 20.0),
                            ("TLR", 20.0),
                        ):
                            row = {
                                "subject": str(subject),
                                "upperbody_label": label,
                                "lowerbody_label": "unused",
                            }
                            row.update({
                                name: value + subject * 0.01 + sample * 0.001
                                for name in FEATURE_NAMES
                            })
                            writer.writerow(row)

            result = train_posture_knn(csv_path, model_path)

            self.assertTrue(model_path.exists())
            self.assertEqual(result.sample_count, 60)
            self.assertEqual(result.subject_count, 4)
            self.assertEqual(result.class_counts, {
                "Good": 12,
                "Slouching": 12,
                "Leaning": 36,
            })
            self.assertTrue(result.test_subjects)
            import joblib

            bundle = joblib.load(model_path)
            self.assertEqual(bundle["feature_space"], FEATURE_SPACE)
            self.assertGreater(bundle["knn_distance_limit"], 0)
            knn = bundle["classifier"].named_steps["kneighborsclassifier"]
            sample_indices = np.random.default_rng(42).choice(
                len(knn._fit_X),
                size=min(1024, len(knn._fit_X)),
                replace=False,
            )
            distances, _ = knn.kneighbors(
                knn._fit_X[sample_indices],
                n_neighbors=min(knn.n_neighbors + 1, len(knn._fit_X)),
            )
            expected_limit = float(np.quantile(distances[:, -1], 0.99) * 5.0)
            self.assertAlmostEqual(bundle["knn_distance_limit"], expected_limit)
            self.assertEqual(
                predict_knn_posture(bundle["classifier"], (0.0,) * 99, bundle["knn_distance_limit"])[0],
                "Good",
            )
            hidden_body_features = (0.0,) * 18 + (100.0,) * 81
            partial_status, partial_distance = predict_knn_posture(
                bundle["classifier"],
                hidden_body_features,
                bundle["knn_distance_limit"],
                (1.0,) * 6 + (0.0,) * 27,
            )
            self.assertEqual(partial_status, "Good")
            self.assertLessEqual(partial_distance, bundle["knn_distance_limit"])
            insufficient_status, _ = predict_knn_posture(
                bundle["classifier"],
                (0.0,) * 99,
                bundle["knn_distance_limit"],
                (1.0,) * 4 + (0.0,) * 29,
            )
            self.assertEqual(insufficient_status, "Uncertain")
            unknown_status, unknown_distance = predict_knn_posture(
                bundle["classifier"],
                (100.0,) * 99,
                bundle["knn_distance_limit"],
            )
            self.assertEqual(unknown_status, "Uncertain")
            self.assertGreater(unknown_distance, bundle["knn_distance_limit"])


if __name__ == "__main__":
    unittest.main()
