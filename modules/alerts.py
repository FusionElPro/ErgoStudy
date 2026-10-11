<<<<<<< HEAD
"""Frame-based temporal filtering for posture and fatigue alerts."""

from __future__ import annotations


class AlertManager:
    """Raise alerts only after an undesirable state persists across frames."""

    def __init__(self, required_frames: int = 15) -> None:
        if required_frames < 0:
            raise ValueError("required_frames must be zero or greater")
        self.required_frames = required_frames
        self._posture_frames = 0
        self._drowsy_frames = 0
        self._posture_alert_active = False
        self._drowsy_alert_active = False

    @property
    def active_alerts(self) -> tuple[str, ...]:
        alerts = []
        if self._posture_alert_active:
            alerts.append("Poor posture detected - sit upright")
        if self._drowsy_alert_active:
            alerts.append("Fatigue detected - consider taking a break")
        return tuple(alerts)

    def update(self, posture_status: str, drowsy: bool) -> tuple[str, ...]:
        """Return newly triggered messages; active alerts remain until the state clears."""
        new_alerts = []
        if posture_status in ("Slouching", "Leaning"):
            self._posture_frames += 1
            if (
                self._posture_frames > self.required_frames
                and not self._posture_alert_active
            ):
                self._posture_alert_active = True
                new_alerts.append("Poor posture detected - sit upright")
        else:
            self._posture_frames = 0
            self._posture_alert_active = False

        if drowsy:
            self._drowsy_frames += 1
            if self._drowsy_frames > self.required_frames and not self._drowsy_alert_active:
                self._drowsy_alert_active = True
                new_alerts.append("Fatigue detected - consider taking a break")
        else:
            self._drowsy_frames = 0
            self._drowsy_alert_active = False

        return tuple(new_alerts)
=======
"""Frame-based temporal filtering for posture and fatigue alerts."""

from __future__ import annotations


class AlertManager:
    """Raise alerts only after an undesirable state persists across frames."""

    def __init__(self, required_frames: int = 15) -> None:
        if required_frames < 0:
            raise ValueError("required_frames must be zero or greater")
        self.required_frames = required_frames
        self._posture_frames = 0
        self._drowsy_frames = 0
        self._posture_alert_active = False
        self._drowsy_alert_active = False

    @property
    def active_alerts(self) -> tuple[str, ...]:
        alerts = []
        if self._posture_alert_active:
            alerts.append("Poor posture detected - sit upright")
        if self._drowsy_alert_active:
            alerts.append("Fatigue detected - consider taking a break")
        return tuple(alerts)

    def update(self, posture_status: str, drowsy: bool) -> tuple[str, ...]:
        """Return newly triggered messages; active alerts remain until the state clears."""
        new_alerts = []
        if posture_status in ("Slouching", "Leaning"):
            self._posture_frames += 1
            if (
                self._posture_frames > self.required_frames
                and not self._posture_alert_active
            ):
                self._posture_alert_active = True
                new_alerts.append("Poor posture detected - sit upright")
        else:
            self._posture_frames = 0
            self._posture_alert_active = False

        if drowsy:
            self._drowsy_frames += 1
            if self._drowsy_frames > self.required_frames and not self._drowsy_alert_active:
                self._drowsy_alert_active = True
                new_alerts.append("Fatigue detected - consider taking a break")
        else:
            self._drowsy_frames = 0
            self._drowsy_alert_active = False

        return tuple(new_alerts)
>>>>>>> origin/main
