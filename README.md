# ErgoStudy

ErgoStudy uses a webcam to estimate posture, eye closure, blinking, and yawning
locally with OpenCV and MediaPipe. Camera frames are processed in memory and
are not saved. On normal exit, an aggregate session summary is stored in
`data/sessions.db`.

## Install

Use Python 3.10 or newer, then install the dependencies:

```bash
pip install -r requirements.txt
```

## Run

```bash
python main.py
```

Use `--camera N` to select a webcam device other than the default device `0`.
Add `--beep` to enable a system beep when a sustained alert begins. Press `q`
in the video window to finish the session and print its summary.

At startup, hold your intended posture until the five-second baseline
calibration completes. Posture deviations use a 15% threshold from the
calibrated measurements (with small minimum angle tolerances). Alerts require
more than 15 consecutive frames in a poor-posture or drowsy state. Drowsiness
is estimated from prolonged eye closure, a blink rate below 8 per minute after
one minute of observation, or a prolonged yawn; these are heuristic signals,
not medical assessments.
