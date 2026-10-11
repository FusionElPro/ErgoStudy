"use strict";

const elements = Object.fromEntries(
  [
    "today-date", "day-name", "calendar-date", "study-time", "posture-score",
    "session-status", "session-pulse", "sound-toggle", "voice-toggle", "camera-video",
    "frame-canvas", "camera-placeholder", "camera-stage", "live-badge",
    "tracking-label", "camera-alert", "camera-clock", "start-button",
    "stop-button", "calibrate-button", "app-message", "posture-status-card",
    "posture-state", "posture-hint", "neck-angle", "distance-ratio",
    "standard-label", "standard-fill", "coach-message", "analysis-method", "count-good",
    "count-slouching", "count-leaning", "model-status", "train-button",
  ].map((id) => [id, document.getElementById(id)]),
);

const LABELS = ["Good", "Slouching", "Leaning"];
const COUNT_IDS = {
  Good: "count-good",
  Slouching: "count-slouching",
  Leaning: "count-leaning",
};
const COACHING = {
  Good: ["Looking comfortable", "Nice and easy. Keep settling into the position that feels natural."],
  Slouching: ["Try a small reset", "Let your shoulders soften and bring your head back over your shoulders."],
  Leaning: ["Find your center", "Gently recenter yourself and check that you feel comfortable at this distance."],
  Calibrating: ["Finding your baseline", "Hold a relaxed, comfortable position while your five-second baseline is measured."],
  "No person detected": ["Come into view", "Sit where your face and shoulders are visible to the camera."],
  Ready: ["A moment to check in", "Sit comfortably and look toward the camera while calibration finds your baseline."],
};

let stream = null;
let sessionActive = false;
let backendSessionActive = false;
let frameLoopRunning = false;
let sessionStartedAt = null;
let lastSoundAt = 0;
let soundEnabled = localStorage.getItem("ergostudy-sound") !== "off";
let voiceEnabled = localStorage.getItem("ergostudy-voice") !== "off";
let audioContext = null;
let currentSampleCounts = { Good: 0, Slouching: 0, Leaning: 0 };
let lastSpokenPosture = null;

function showMessage(message = "") {
  elements["app-message"].textContent = message;
}

function formatDuration(totalSeconds) {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return [hours, minutes, seconds % 60].map((part) => String(part).padStart(2, "0")).join(":");
}

function updateCalendar() {
  const now = new Date();
  elements["today-date"].textContent = new Intl.DateTimeFormat(undefined, {
    weekday: "short", month: "short", day: "numeric",
  }).format(now);
  elements["day-name"].textContent = new Intl.DateTimeFormat(undefined, {
    weekday: "long",
  }).format(now);
  elements["calendar-date"].textContent = new Intl.DateTimeFormat(undefined, {
    month: "long", day: "numeric", year: "numeric",
  }).format(now);
}

function setSoundEnabled(enabled) {
  soundEnabled = enabled;
  elements["sound-toggle"].classList.toggle("muted", !enabled);
  elements["sound-toggle"].setAttribute("aria-pressed", String(enabled));
  elements["sound-toggle"].title = enabled ? "Mute posture alert sound" : "Enable posture alert sound";
  localStorage.setItem("ergostudy-sound", enabled ? "on" : "off");
}

function setVoiceEnabled(enabled) {
  voiceEnabled = enabled;
  elements["voice-toggle"].classList.toggle("voice-muted", !enabled);
  elements["voice-toggle"].setAttribute("aria-pressed", String(enabled));
  elements["voice-toggle"].title = enabled
    ? "Mute spoken posture suggestions"
    : "Enable spoken posture suggestions";
  localStorage.setItem("ergostudy-voice", enabled ? "on" : "off");
  if (!enabled && "speechSynthesis" in window) {
    window.speechSynthesis.cancel();
  }
}

function speakPostureFeedback(status) {
  if (!voiceEnabled || !("speechSynthesis" in window)) return;
  const feedback = COACHING[status];
  if (!feedback || !["Slouching", "Leaning"].includes(status)) return;
  if (lastSpokenPosture === status) return;
  lastSpokenPosture = status;
  const message = new SpeechSynthesisUtterance(`${status}. Suggestion: ${feedback[1]}`);
  message.lang = document.documentElement.lang || "en";
  message.rate = 0.95;
  message.pitch = 1;
  message.onerror = (event) => {
    if (event.error !== "interrupted" && voiceEnabled) {
      showMessage(`Could not speak the posture suggestion: ${event.error}`);
    }
  };
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(message);
}

async function playPostureTone() {
  if (!soundEnabled) return;
  const now = Date.now();
  if (now - lastSoundAt < 2500) return;
  lastSoundAt = now;
  try {
    const AudioContextType = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextType) return;
    audioContext ||= new AudioContextType();
    if (audioContext.state === "suspended") await audioContext.resume();
    const oscillator = audioContext.createOscillator();
    const gain = audioContext.createGain();
    oscillator.type = "sine";
    oscillator.frequency.setValueAtTime(660, audioContext.currentTime);
    oscillator.frequency.exponentialRampToValueAtTime(520, audioContext.currentTime + 0.18);
    gain.gain.setValueAtTime(0.0001, audioContext.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.12, audioContext.currentTime + 0.025);
    gain.gain.exponentialRampToValueAtTime(0.0001, audioContext.currentTime + 0.24);
    oscillator.connect(gain);
    gain.connect(audioContext.destination);
    oscillator.start();
    oscillator.stop(audioContext.currentTime + 0.25);
  } catch (error) {
    showMessage(`Could not play the posture alert sound: ${error.message}`);
  }
}

async function unlockAudio() {
  if (!soundEnabled) return;
  const AudioContextType = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextType) return;
  audioContext ||= new AudioContextType();
  if (audioContext.state === "suspended") await audioContext.resume();
}

async function requestJson(path, options = {}) {
  const response = await fetch(path, options);
  let result;
  try {
    result = await response.json();
  } catch {
    throw new Error(`The local app returned an invalid response (${response.status}).`);
  }
  if (!response.ok) throw new Error(result.error || `Request failed (${response.status}).`);
  return result;
}

function updateSampleCounts(counts = {}) {
  for (const label of LABELS) {
    currentSampleCounts[label] = counts[label] || 0;
    document.getElementById(COUNT_IDS[label]).textContent = currentSampleCounts[label];
  }
}

function updateModelStatus(result = {}) {
  const modelStatus = elements["model-status"];
  modelStatus.classList.remove("error", "ready");
  if (result.active) {
    modelStatus.classList.toggle("ready", Boolean(result.metrics?.classifier_used));
    modelStatus.querySelector("span:last-child").textContent = result.metrics?.classifier_used
      ? `${result.metrics.classifier_name || "Classifier"} is primary; math-based posture rules are the secondary check.`
      : "Finish your session before training the posture model.";
    elements["train-button"].disabled = true;
    return;
  }
  const enoughSamples = LABELS.every((label) => currentSampleCounts[label] >= 10);
  elements["train-button"].disabled = !enoughSamples;
  modelStatus.classList.toggle("ready", Boolean(result.model_available));
  modelStatus.querySelector("span:last-child").textContent = result.model_available
    ? `${result.model_name || "Trained classifier"} leads new sessions; math-based posture rules are the secondary check.`
    : enoughSamples
      ? "Ready to train. Samples must include at least two separate sessions per label."
      : "Capture at least 10 of each label across two sessions.";
}

function updatePosture(metrics = {}, alerts = [], modelName = null) {
  const status = metrics.status || "Ready";
  const availableModel = modelName || metrics.classifier_name;
  if (!["Slouching", "Leaning"].includes(status)) {
    lastSpokenPosture = null;
  }
  const [title, hint] = COACHING[status] || COACHING.Ready;
  elements["posture-state"].textContent =
    metrics.classifier_used ? `${status} · MLP` : status;
  elements["posture-hint"].textContent = hint;
  elements["analysis-method"].textContent = !metrics.calibrated
    ? availableModel
      ? `Trained ${availableModel} ready · baseline calibration needed`
      : "Calibrating baseline · math fallback active"
    : metrics.classifier_used
      ? `${metrics.classifier_name || "Classifier"} primary · Math check: ${metrics.rule_status || "unavailable"}`
      : "Math-based fallback · no trained model available";
  elements["coach-message"].textContent = title === "Looking comfortable"
    ? COACHING.Good[1]
    : hint;
  elements["neck-angle"].textContent = Number.isFinite(metrics.neck_angle)
    ? metrics.neck_angle.toFixed(1)
    : "--";
  elements["distance-ratio"].textContent = Number.isFinite(metrics.proximity_ratio)
    ? metrics.proximity_ratio.toFixed(2)
    : "--";
  elements["posture-score"].textContent = Number.isFinite(metrics.score)
    ? Math.round(metrics.score)
    : "--";
  elements["standard-label"].textContent = !metrics.calibrated
    ? (status === "Calibrating" ? "Calibration in progress" : "Waiting for calibration")
    : status === "Good" ? "Within your baseline" : "Outside your baseline";
  const score = Number.isFinite(metrics.score) ? metrics.score : 0;
  elements["standard-fill"].style.width = `${Math.min(100, Math.max(0, score))}%`;
  elements["posture-status-card"].classList.toggle("good", status === "Good");
  elements["posture-status-card"].classList.toggle(
    "poor", status === "Slouching" || status === "Leaning",
  );
  elements["camera-alert"].hidden = !alerts.length;
  elements["tracking-label"].textContent = !metrics.valid
    ? "Looking for your posture"
    : metrics.calibrated ? "Posture tracking active" : "Calibrating your baseline";
  elements["tracking-label"].parentElement.classList.toggle("is-tracking", metrics.valid);
}

function updateStatus(result = {}) {
  backendSessionActive = Boolean(result.active);
  sessionActive = backendSessionActive && stream !== null;
  elements["start-button"].hidden = sessionActive;
  elements["start-button"].querySelector(".button-play").textContent =
    backendSessionActive ? "↻" : "▶";
  elements["start-button"].lastChild.textContent =
    backendSessionActive ? " Reconnect camera" : " Start session";
  elements["stop-button"].hidden = !sessionActive;
  elements["stop-button"].hidden = !backendSessionActive;
  elements["calibrate-button"].disabled = !sessionActive;
  for (const button of document.querySelectorAll(".sample-button")) {
    button.disabled = !backendSessionActive;
  }
  elements["session-status"].textContent = sessionActive
    ? "Session in progress"
    : backendSessionActive ? "Session running · reconnect camera" : "Ready when you are";
  elements["session-pulse"].style.background = backendSessionActive ? "#79a26f" : "#a1a69b";
  elements["session-pulse"].style.boxShadow = backendSessionActive ? "0 0 0 4px #e6efe2" : "none";
  elements["live-badge"].classList.toggle("is-live", sessionActive);
  elements["live-badge"].innerHTML = sessionActive
    ? "<span></span> CAMERA ON"
    : backendSessionActive ? "<span></span> RECONNECT CAMERA"
    : "<span></span> CAMERA OFF";
  if (backendSessionActive && result.elapsed_seconds !== undefined) {
    sessionStartedAt = Date.now() - result.elapsed_seconds * 1000;
  } else if (!backendSessionActive) {
    sessionStartedAt = null;
  }
  if (Number.isFinite(result.elapsed_seconds)) {
    elements["study-time"].textContent = formatDuration(result.elapsed_seconds);
    elements["camera-clock"].textContent = formatDuration(result.elapsed_seconds);
  }
  updatePosture(result.metrics || {}, result.alerts || [], result.model_name || null);
  updateSampleCounts(result.sample_counts || currentSampleCounts);
  updateModelStatus(result);
}

async function sendFrame() {
  const video = elements["camera-video"];
  const canvas = elements["frame-canvas"];
  if (!sessionActive || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return;
  canvas.width = Math.min(video.videoWidth, 960);
  canvas.height = Math.round(canvas.width * video.videoHeight / video.videoWidth);
  const context = canvas.getContext("2d", { alpha: false });
  context.drawImage(video, 0, 0, canvas.width, canvas.height);
  const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.72));
  if (!blob || !sessionActive) return;
  const result = await requestJson("/api/frame", {
    method: "POST",
    headers: { "Content-Type": "image/jpeg" },
    body: blob,
  });
  updateStatus(result);
  if (result.new_alerts?.length) {
    await playPostureTone();
    speakPostureFeedback(result.metrics?.status);
  }
}

async function frameLoop() {
  if (!sessionActive || frameLoopRunning) return;
  frameLoopRunning = true;
  while (sessionActive) {
    try {
      await sendFrame();
    } catch (error) {
      showMessage(error.message);
      await finishSession(false);
      break;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 140));
  }
  frameLoopRunning = false;
}

async function startSession() {
  showMessage();
  elements["start-button"].disabled = true;
  try {
    await unlockAudio();
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("Camera access is unavailable. Open this app from http://127.0.0.1.");
    }
    stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: "user", width: { ideal: 960 }, height: { ideal: 720 } },
    });
    elements["camera-video"].srcObject = stream;
    await elements["camera-video"].play();
    const result = backendSessionActive
      ? await requestJson("/api/status")
      : await requestJson("/api/session/start", { method: "POST" });
    stream = elements["camera-video"].srcObject;
    updateStatus(result);
    elements["camera-placeholder"].hidden = true;
    if (result.alerts?.length) await playPostureTone();
    if (result.alerts?.length) speakPostureFeedback(result.metrics?.status);
    frameLoop();
  } catch (error) {
    releaseCamera();
    showMessage(error.message);
    elements["start-button"].disabled = false;
  } finally {
    if (!sessionActive) elements["start-button"].disabled = false;
  }
}

function releaseCamera() {
  if (stream) {
    for (const track of stream.getTracks()) track.stop();
    stream = null;
  }
  elements["camera-video"].srcObject = null;
  elements["camera-placeholder"].hidden = false;
}

async function finishSession(showSummary = true) {
  sessionActive = false;
  backendSessionActive = false;
  releaseCamera();
  try {
    const result = await requestJson("/api/session/stop", { method: "POST" });
    updateStatus(result);
    elements["study-time"].textContent = formatDuration(result.duration_seconds || 0);
    if (showSummary && result.frame_count > 0) {
      showMessage(`Session saved · average posture score ${Math.round(result.average_posture_score || 0)}/100.`);
    }
  } catch (error) {
    updateStatus({ active: false });
    if (showSummary) showMessage(error.message);
  }
}

async function recalibrate() {
  try {
    updateStatus(await requestJson("/api/session/recalibrate", { method: "POST" }));
    showMessage("Calibration restarted. Sit in your comfortable baseline position.");
  } catch (error) {
    showMessage(error.message);
  }
}

async function captureLabel(label) {
  try {
    const result = await requestJson("/api/label", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label }),
    });
    updateSampleCounts(result.sample_counts);
    updateModelStatus({ active: true });
    showMessage(`Saved a ${label} posture sample.`);
  } catch (error) {
    showMessage(error.message);
  }
}

async function trainModel() {
  elements["train-button"].disabled = true;
  elements["model-status"].classList.remove("error");
  elements["model-status"].querySelector("span:last-child").textContent = "Training your small MLP…";
  try {
    const result = await requestJson("/api/model/train", { method: "POST" });
    elements["model-status"].classList.add("ready");
    elements["model-status"].querySelector("span:last-child").textContent =
      `Trained on ${result.sample_count} samples · held-out accuracy ${Math.round(result.accuracy * 100)}% · macro F1 ${result.macro_f1.toFixed(2)}. Restart the app to use it.`;
  } catch (error) {
    elements["model-status"].classList.add("error");
    elements["model-status"].querySelector("span:last-child").textContent = error.message;
    elements["train-button"].disabled = false;
  }
}

function updateClocks() {
  if (sessionStartedAt !== null) {
    const elapsed = (Date.now() - sessionStartedAt) / 1000;
    elements["study-time"].textContent = formatDuration(elapsed);
    elements["camera-clock"].textContent = formatDuration(elapsed);
  }
}

async function initialize() {
  updateCalendar();
  window.setInterval(updateClocks, 1000);
  setSoundEnabled(soundEnabled);
  setVoiceEnabled(voiceEnabled);
  elements["start-button"].addEventListener("click", startSession);
  elements["stop-button"].addEventListener("click", () => finishSession());
  elements["calibrate-button"].addEventListener("click", recalibrate);
  elements["sound-toggle"].addEventListener("click", async () => {
    setSoundEnabled(!soundEnabled);
    try {
      await unlockAudio();
    } catch (error) {
      showMessage(`Could not enable alert sound: ${error.message}`);
    }
  });
  elements["voice-toggle"].addEventListener("click", () => {
    setVoiceEnabled(!voiceEnabled);
    if (voiceEnabled && !("speechSynthesis" in window)) {
      showMessage("Spoken posture suggestions are not supported by this browser.");
    }
  });
  elements["train-button"].addEventListener("click", trainModel);
  for (const button of document.querySelectorAll(".sample-button")) {
    button.addEventListener("click", () => captureLabel(button.dataset.label));
  }

  try {
    const status = await requestJson("/api/status");
    updateStatus(status);
    if (status.alerts?.length) speakPostureFeedback(status.metrics?.status);
  } catch (error) {
    showMessage(`Could not connect to the ErgoStudy server: ${error.message}`);
  }
}

initialize();
