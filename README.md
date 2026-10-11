# ErgoStudy

ErgoStudy uses a webcam to estimate posture, eye closure, blinking, and yawning
locally with OpenCV and MediaPipe. Camera frames are processed in memory and
are not saved. On normal exit, an aggregate session summary is stored in
`data/sessions.db`.

## Install

Use Python 3.10 through 3.12. MediaPipe 0.10.21 provides the Pose and Face Mesh
Solutions APIs used by the app; newer MediaPipe releases may not include them.
Then install the dependencies:

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

During the webcam session, press `1` to label the current posture Good, `2`
for Slouching, or `3` for Leaning. Label at least 10 examples of each posture
across at least two separate sessions. Samples contain only calibrated
landmark measurements, not images.

Train and evaluate the MLP from a terminal with:

```bash
python train_posture_model.py
```

The trainer holds out complete capture sessions for evaluation and saves the
scikit-learn pipeline as `data/posture_mlp.joblib`. Restart the app to use the
trained classifier; its prediction is marked `(MLP)` in the HUD. The reported
metrics are a personal-data check, not a guarantee of generalization.

At startup, hold your intended posture until the five-second baseline
calibration completes. Posture deviations use a 15% threshold from the
calibrated measurements (with small minimum angle tolerances). Alerts require
more than 15 consecutive frames in a poor-posture or drowsy state. Drowsiness
is estimated from prolonged eye closure, a blink rate below 8 per minute after
one minute of observation, or a prolonged yawn; these are heuristic signals,
not medical assessments.
