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
scikit-learn pipeline as `data/posture_mlp.joblib`. When present, the MLP
prediction is the primary posture classification; the geometric rule check is
reported separately as a secondary comparison and does not override it. Until
a model is trained, the geometric rules provide a clearly labeled fallback.
The reported metrics are a personal-data check, not a guarantee of
generalization.

### Train KNN from pose-landmark CSV

The browser and desktop apps prefer `data/posture_knn.joblib` when it exists.
Train it from a CSV containing the 33 MediaPipe pose landmarks as `{landmark}_{x,y,z}` columns, plus `subject` and `upperbody_label`:

```powershell
.\.venv-ergo\Scripts\python.exe train_posture_knn.py C:\path\to\data.csv
```

The CSV upper-body classes map as follows: `TUP` → Good, `TLF` → Slouching,
and `TLB`, `TLL`, or `TLR` → Leaning. Lower-body labels are ignored. The
trainer evaluates with entire subjects held out, then fits the saved KNN using
all CSV rows. Its landmark ordering matches MediaPipe Pose; the app reports
the mathematical posture rule alongside the KNN prediction as a secondary
check. The personal MLP remains available as a fallback if no KNN model exists.

At startup, hold your intended posture until the five-second baseline
calibration completes. Shoulder angles are compared using wrapped angular
deltas so crossing the -180°/180° boundary does not create a false large
deviation. Posture deviations use a 15% threshold from the calibrated
measurements (with small minimum angle tolerances). Alerts require
more than 15 consecutive frames in a poor-posture or drowsy state. Drowsiness
is estimated from prolonged eye closure, a blink rate below 8 per minute after
one minute of observation, or a prolonged yawn; these are heuristic signals,
not medical assessments.

## YPT-inspired study dashboard

The Next.js dashboard uses the FastAPI backend for subject management, focus
and break timers, daily/weekly summaries, session history, and live webcam
metrics. The database migration is additive: the existing `sessions` and
posture-label tables and their data remain intact. New records use
`subjects`, `study_sessions`, and `ergonomic_metrics`.

Install the frontend dependencies once with Node.js 18.18 or newer:

```powershell
Set-Location frontend
npm install
```

Run the backend and frontend in separate terminals from the project root:

```powershell
.\.venv-ergo\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```powershell
Set-Location frontend
npm run dev
```

Open `http://localhost:3000`. Select or create a subject, then start a focus
or break block. Allow camera access to enable the compact posture/fatigue HUD;
the dashboard continues to work as a timer without camera permission. Camera
frames are processed in memory and never written to disk. Only metrics and
session summaries are stored in `data/sessions.db`. There is no shared study
room; camera data is never shared.

The API is local-only by default (`127.0.0.1:8000`) and exposes:

- `/api/subjects` — list, create, and delete subjects.
- `/api/sessions/start`, `/api/sessions/stop`, and `/api/sessions/active` —
  manage the current focus or break block.
- `/api/webcam/frame` — process a bounded JPEG frame and return live posture,
  EAR/MAR, blink/yawn, and alert metrics.
- `/api/statistics` and `/api/sessions` — retrieve daily summaries and recent
  study blocks.

## Legacy browser study app

Start the local dashboard with Python 3.12:

```powershell
.\.venv-ergo\Scripts\python.exe web_app.py
```

Open `http://127.0.0.1:8765/` if the browser does not open automatically. Allow
camera access, select **Start session**, and sit comfortably for the five-second
baseline calibration. The browser sends webcam frames only to the local server;
frames are not saved. The gentle sound toggle is on by default and plays when a
poor-posture alert persists for more than 15 consecutive frames. Press
**Finish session** to save the summary. The original OpenCV desktop app remains
available with `.\.venv-ergo\Scripts\python.exe main.py`.

The Next.js dashboard has a **Posture analyzer** tab for standalone webcam
posture analysis without starting a study timer. It replaces the former Study
Room preview and shows the live camera, KNN result, posture score, neck angle,
screen-distance ratio, calibration, geometric comparison, pose detection,
classifier usage, and analysis time. It requires the trained
`data/posture_knn.joblib` artifact: webcam frames are converted to MediaPipe
world-space Pose landmarks and classified by the trained 7-neighbor KNN.
World-space features keep camera framing offsets out of the classifier input.
It will not silently fall back to the MLP or geometric rules. Calibration,
the KNN class, and the geometric-rule comparison are displayed separately.
Low-visibility landmarks are excluded from KNN matching so cropped or
partially-obscured body joints do not make an otherwise usable frame appear
out of range. Frames beyond twice the 99th-percentile training-neighbor
distance, with a five-times safety factor, are reported as uncertain instead of
being assigned an unreliable class. A calibrated head-tilt guardrail reports
a clear lateral head tilt as Leaning even when the KNN predicts Good. The
browser can speak posture-specific correction guidance after an incorrect KNN
prediction persists for 2.5 seconds; voice guidance can be disabled on the
analyzer page. Stop the standalone analyzer before starting a timer session.
