import unittest

from modules.alerts import AlertManager


class AlertManagerTests(unittest.TestCase):
    def test_alert_fires_only_after_more_than_required_consecutive_frames(self):
        manager = AlertManager(required_frames=15)

        for _ in range(15):
            self.assertEqual(manager.update("Slouching", False), ())
        self.assertEqual(
            manager.update("Slouching", False),
            ("Poor posture detected - sit upright",),
        )
        self.assertEqual(manager.active_alerts, ("Poor posture detected - sit upright",))

    def test_good_posture_resets_buffer_and_clears_active_alert(self):
        manager = AlertManager(required_frames=2)
        manager.update("Leaning", False)
        manager.update("Leaning", False)

        manager.update("Good", False)
        self.assertEqual(manager.active_alerts, ())
        self.assertEqual(manager.update("Leaning", False), ())
        self.assertEqual(manager.update("Leaning", False), ())
        self.assertEqual(
            manager.update("Leaning", False),
            ("Poor posture detected - sit upright",),
        )

    def test_drowsiness_alert_is_independent_of_posture(self):
        manager = AlertManager(required_frames=0)

        self.assertEqual(
            manager.update("Good", True),
            ("Fatigue detected - consider taking a break",),
        )
        self.assertEqual(len(manager.active_alerts), 1)

    def test_negative_frame_requirement_is_rejected(self):
        with self.assertRaises(ValueError):
            AlertManager(required_frames=-1)


if __name__ == "__main__":
    unittest.main()
