"use client";

import {
  Activity,
  AlarmClock,
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  BookOpen,
  Check,
  ChevronDown,
  CircleHelp,
  Clock3,
  Coffee,
  Focus,
  Headphones,
  Plus,
  Settings2,
  ShieldCheck,
  Sparkles,
  Volume2,
  VolumeX,
  Webcam,
  X
} from "lucide-react";
import {
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";

const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

type Tab = "timer" | "posture" | "stats";
type Kind = "focus" | "break";

type Subject = {
  id: number;
  name: string;
  color: string;
  total_focus_seconds: number;
};

type Metrics = {
  posture_status: string;
  posture_score: number | null;
  neck_angle: number | null;
  proximity_ratio: number | null;
  ear: number | null;
  mar: number | null;
  blink_count: number;
  yawn_count: number;
  blinks_per_minute: number;
  drowsy: boolean;
  yawning: boolean;
  face_valid: boolean;
  calibrated: boolean;
  classifier_name: string | null;
};

type ActiveSession = {
  active: boolean;
  session_id: string | null;
  subject_id: number | null;
  kind: Kind | null;
  elapsed_seconds: number;
  metrics: Metrics;
  alerts: string[];
};

type PostureStatus = {
  active: boolean;
  model_ready: boolean;
  model_name: string | null;
  elapsed_seconds: number;
  metrics: {
    status: string;
    neck_angle: number | null;
    proximity_ratio: number | null;
    score: number | null;
    calibrated: boolean;
    valid: boolean;
    classifier_used: boolean;
    classifier_name: string | null;
    classifier_distance: number | null;
    classifier_distance_limit: number | null;
    rule_status: string | null;
    head_tilt_delta: number | null;
    geometric_override: boolean;
  };
};

type DayStat = {
  date: string;
  focus_seconds: number;
  break_seconds: number;
};

type Stats = {
  focus_seconds: number;
  break_seconds: number;
  today_focus_seconds: number;
  today_break_seconds: number;
  average_posture_score: number | null;
  total_blinks: number;
  total_yawns: number;
  daily: DayStat[];
  subjects: Array<{ id: number; name: string; color: string; focus_seconds: number }>;
};

type SessionLog = {
  id: string;
  kind: Kind;
  status: "completed" | "interrupted";
  started_at: string;
  duration_seconds: number;
  average_posture_score: number | null;
  total_blinks: number;
  total_yawns: number;
  subject_name: string | null;
  subject_color: string | null;
};

const idleMetrics: Metrics = {
  posture_status: "Ready",
  posture_score: null,
  neck_angle: null,
  proximity_ratio: null,
  ear: null,
  mar: null,
  blink_count: 0,
  yawn_count: 0,
  blinks_per_minute: 0,
  drowsy: false,
  yawning: false,
  face_valid: false,
  calibrated: false,
  classifier_name: null
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof Blob ? {} : { "Content-Type": "application/json" }),
      ...init?.headers
    },
    cache: "no-store"
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail ?? `Request failed (${response.status}).`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
};

const outOfRangeMessages = [
  "You seem a little close to the screen. Please move back so I can see you clearly.",
  "Let's adjust your distance a bit. Try moving back from the screen.",
  "I'm having trouble seeing your posture. Please move back a little from the camera.",
  "For a clearer posture check, sit a little farther away from the screen."
];

function preferredEnglishVoice(voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | null {
  const englishVoices = voices.filter((voice) => voice.lang.toLowerCase().startsWith("en"));
  const preferredNameVoice = englishVoices.find((voice) =>
    /natural|neural|google/i.test(voice.name)
  );
  return preferredNameVoice
    ?? englishVoices.find((voice) => /en[-_]in/i.test(voice.lang))
    ?? englishVoices.find((voice) => /en[-_]us/i.test(voice.lang))
    ?? voices.find((voice) => voice.default)
    ?? null;
}

function waitForSpeechVoice(): Promise<SpeechSynthesisVoice | null> {
  const synthesis = window.speechSynthesis;
  const availableVoices = synthesis.getVoices();
  if (availableVoices.length) {
    return Promise.resolve(preferredEnglishVoice(availableVoices));
  }

  return new Promise((resolve) => {
    let timeout: number | null = null;
    const finish = () => {
      synthesis.removeEventListener("voiceschanged", onVoicesChanged);
      if (timeout !== null) window.clearTimeout(timeout);
      resolve(preferredEnglishVoice(synthesis.getVoices()));
    };
    const onVoicesChanged = () => {
      if (synthesis.getVoices().length) finish();
    };

    synthesis.addEventListener("voiceschanged", onVoicesChanged);
    timeout = window.setTimeout(finish, 1500);
  });
}

function formatTime(seconds: number): string {
  const safeSeconds = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const remaining = safeSeconds % 60;
  return [hours, minutes, remaining].map((part) => String(part).padStart(2, "0")).join(":");
}

function formatHours(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours}h ${String(minutes).padStart(2, "0")}m`;
}

function formatClock(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function localDateKey(date = new Date()): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function postureGuidance(status: string): { title: string; advice: string; spoken: string } | null {
  if (status === "Slouching") {
    return {
      title: "Sit back and support your spine",
      advice: "Sit back with your spine supported, relax your shoulders, and bring your screen closer to eye level.",
      spoken: "You're slouching. Sit back with your spine supported, relax your shoulders, and bring your screen closer to eye level."
    };
  }
  if (status === "Leaning") {
    return {
      title: "Bring your head back over your shoulders",
      advice: "Sit upright, gently bring your head back over your shoulders, and keep both shoulders relaxed and level.",
      spoken: "You're leaning. Sit upright, gently bring your head back over your shoulders, and keep both shoulders relaxed and level."
    };
  }
  if (status === "Good") {
    return {
      title: "Your posture looks good",
      advice: "Keep your shoulders relaxed and take a comfortable movement break when you need one.",
      spoken: ""
    };
  }
  if (status === "Uncertain") {
    return {
      title: "Camera view is outside the model's training range",
      advice: "The KNN is withholding a guess because this frame does not resemble its training examples. Adjust the camera view or retrain it with labeled samples captured from this same position.",
      spoken: ""
    };
  }
  return null;
}

export default function Home() {
  const [tab, setTab] = useState<Tab>("timer");
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [selectedSubject, setSelectedSubject] = useState<number | null>(null);
  const [session, setSession] = useState<ActiveSession>({
    active: false,
    session_id: null,
    subject_id: null,
    kind: null,
    elapsed_seconds: 0,
    metrics: idleMetrics,
    alerts: []
  });
  const [stats, setStats] = useState<Stats | null>(null);
  const [history, setHistory] = useState<SessionLog[]>([]);
  const [now, setNow] = useState(0);
  const [mounted, setMounted] = useState(false);
  const [anchor, setAnchor] = useState<{ elapsed: number; at: number } | null>(null);
  const [name, setName] = useState("");
  const [color, setColor] = useState("#10B981");
  const [addingSubject, setAddingSubject] = useState(false);
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [postureStatus, setPostureStatus] = useState<PostureStatus>({
    active: false,
    model_ready: false,
    model_name: null,
    elapsed_seconds: 0,
    metrics: {
      status: "Ready",
      neck_angle: null,
      proximity_ratio: null,
      score: null,
      calibrated: false,
      valid: false,
      classifier_used: false,
      classifier_name: null,
      classifier_distance: null,
      classifier_distance_limit: null,
      rule_status: null,
      head_tilt_delta: null,
      geometric_override: false
    }
  });
  const [postureStream, setPostureStream] = useState<MediaStream | null>(null);
  const [postureBusy, setPostureBusy] = useState(false);
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [outOfRangeVoiceEnabled, setOutOfRangeVoiceEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const postureCaptureVideoRef = useRef<HTMLVideoElement>(null);
  const posturePreviewVideoRef = useRef<HTMLVideoElement>(null);
  const postureCanvasRef = useRef<HTMLCanvasElement>(null);
  const lastAlertsRef = useRef<string[]>([]);
  const postureIncorrectRef = useRef(false);
  const standalonePostureIncorrectRef = useRef(false);
  const postureWarningSinceRef = useRef<number | null>(null);
  const lastPostureObservationAtRef = useRef(0);
  const lastPostureSpeechAtRef = useRef(0);
  const outOfRangeVoiceEnabledRef = useRef(true);
  const outOfRangeConsecutiveFramesRef = useRef(0);
  const outOfRangeEpisodeHandledRef = useRef(false);
  const outOfRangeEpisodeRef = useRef(0);
  const lastOutOfRangeSpeechAtRef = useRef(0);
  const outOfRangeMessageIndexRef = useRef(0);
  const postureVoiceSessionEnabledRef = useRef(false);
  const speechVoicePromiseRef = useRef<Promise<SpeechSynthesisVoice | null> | null>(null);

  const currentSeconds = session.active && anchor
    ? anchor.elapsed + (now - anchor.at) / 1000
    : 0;
  const selected = subjects.find((subject) => subject.id === selectedSubject) ?? null;
  const currentFocusSeconds = session.active && session.kind === "focus" ? currentSeconds : 0;
  const currentBreakSeconds = session.active && session.kind === "break" ? currentSeconds : 0;
  const focusToday = (stats?.today_focus_seconds ?? 0) + currentFocusSeconds;
  const breakToday = (stats?.today_break_seconds ?? 0) + currentBreakSeconds;
  const todayKey = localDateKey();

  const refreshData = useCallback(async () => {
    const [subjectList, newStats, logs, current, postureCurrent] = await Promise.all([
      api<Subject[]>("/api/subjects"),
      api<Stats>(`/api/statistics?days=7&timezone_offset_minutes=${new Date().getTimezoneOffset()}`),
      api<SessionLog[]>("/api/sessions?limit=12"),
      api<ActiveSession>("/api/sessions/active"),
      api<PostureStatus>("/api/posture/status")
    ]);
    setSubjects(subjectList);
    setStats(newStats);
    setHistory(logs);
    setSelectedSubject((previous) =>
      previous !== null && subjectList.some((subject) => subject.id === previous)
        ? previous
        : subjectList[0]?.id ?? null
    );
    setSession(current);
    setAnchor(current.active ? { elapsed: current.elapsed_seconds, at: Date.now() } : null);
    setPostureStatus(postureCurrent);
  }, []);

  useEffect(() => {
    setMounted(true);
    setNow(Date.now());
    refreshData().catch((reason: unknown) => {
      setError(reason instanceof Error ? reason.message : "Could not connect to ErgoStudy API.");
    });
    const timer = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, [refreshData]);

  useEffect(() => {
    if (!session.active) return;
    const poll = window.setInterval(() => {
      api<ActiveSession>("/api/sessions/active")
        .then((current) => {
          setSession(current);
          setAnchor({ elapsed: current.elapsed_seconds, at: Date.now() });
        })
        .catch((reason: unknown) => {
          setError(reason instanceof Error ? reason.message : "Could not refresh session.");
        });
    }, 1000);
    return () => window.clearInterval(poll);
  }, [session.active]);

  useEffect(() => {
    if (!stream || !videoRef.current) return;
    videoRef.current.srcObject = stream;
    void videoRef.current.play();
  }, [stream]);

  useEffect(() => {
    if (!postureStream || !postureCaptureVideoRef.current) return;
    postureCaptureVideoRef.current.srcObject = postureStream;
    void postureCaptureVideoRef.current.play();
    if (posturePreviewVideoRef.current) {
      posturePreviewVideoRef.current.srcObject = postureStream;
      void posturePreviewVideoRef.current.play();
    }
  }, [postureStream]);

  const playAlert = useCallback(() => {
    if (!soundEnabled) return;
    const AudioContextType = window.AudioContext;
    if (!AudioContextType) return;
    const context = new AudioContextType();
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = "sine";
    oscillator.frequency.value = 660;
    gain.gain.setValueAtTime(0.0001, context.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.07, context.currentTime + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.25);
    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.start();
    oscillator.stop(context.currentTime + 0.26);
    oscillator.onended = () => void context.close();
  }, [soundEnabled]);

  const speakPostureGuidance = useCallback((result: PostureStatus) => {
    const metrics = result.metrics;
    const isKnnWarning = result.active
      && metrics.valid
      && metrics.classifier_used
      && metrics.classifier_name === "KNN"
      && (metrics.status === "Slouching" || metrics.status === "Leaning");
    if (!isKnnWarning) {
      postureWarningSinceRef.current = null;
      lastPostureObservationAtRef.current = 0;
      return;
    }

    const now = Date.now();
    if (now - lastPostureObservationAtRef.current > 1500) {
      postureWarningSinceRef.current = now;
    }
    lastPostureObservationAtRef.current = now;
    postureWarningSinceRef.current ??= now;
    if (
      !soundEnabled
      || now - postureWarningSinceRef.current < 2500
      || now - lastPostureSpeechAtRef.current < 30000
      || !("speechSynthesis" in window)
    ) return;

    const guidance = postureGuidance(metrics.status);
    if (!guidance?.spoken) return;
    const utterance = new SpeechSynthesisUtterance(`Posture reminder. ${guidance.spoken}`);
    utterance.lang = "en-US";
    utterance.rate = 0.95;
    utterance.volume = 0.85;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
    lastPostureSpeechAtRef.current = now;
  }, [soundEnabled]);

  const speakOutOfRangeWarning = useCallback((result: PostureStatus) => {
    const metrics = result.metrics;
    const isOutOfRange = result.active
      && metrics.valid
      && metrics.classifier_used
      && metrics.classifier_name === "KNN"
      && metrics.classifier_distance !== null
      && metrics.classifier_distance_limit !== null
      && metrics.classifier_distance > metrics.classifier_distance_limit;

    if (!isOutOfRange) {
      if (outOfRangeConsecutiveFramesRef.current > 0) {
        outOfRangeEpisodeRef.current += 1;
      }
      outOfRangeConsecutiveFramesRef.current = 0;
      outOfRangeEpisodeHandledRef.current = false;
      return;
    }

    if (outOfRangeConsecutiveFramesRef.current === 0) {
      outOfRangeEpisodeRef.current += 1;
    }
    outOfRangeConsecutiveFramesRef.current += 1;
    if (
      outOfRangeConsecutiveFramesRef.current < 10
      || outOfRangeEpisodeHandledRef.current
    ) return;

    outOfRangeEpisodeHandledRef.current = true;
    const episode = outOfRangeEpisodeRef.current;
    if (
      !postureVoiceSessionEnabledRef.current
      || !outOfRangeVoiceEnabledRef.current
      || !("speechSynthesis" in window)
      || Date.now() - lastOutOfRangeSpeechAtRef.current < 15000
    ) return;
    const synthesis = window.speechSynthesis;
    if (synthesis.speaking || synthesis.pending) return;

    const voicePromise = speechVoicePromiseRef.current ?? waitForSpeechVoice();
    speechVoicePromiseRef.current = voicePromise;
    void voicePromise.then((voice) => {
      if (
        episode !== outOfRangeEpisodeRef.current
        || outOfRangeConsecutiveFramesRef.current < 10
        || !postureVoiceSessionEnabledRef.current
        || !outOfRangeVoiceEnabledRef.current
        || Date.now() - lastOutOfRangeSpeechAtRef.current < 15000
        || synthesis.speaking
        || synthesis.pending
      ) return;

      const message = outOfRangeMessages[
        outOfRangeMessageIndexRef.current % outOfRangeMessages.length
      ];
      const utterance = new SpeechSynthesisUtterance(message);
      utterance.lang = "en-US";
      utterance.rate = 0.95;
      utterance.pitch = 1.0;
      if (voice) utterance.voice = voice;
      synthesis.speak(utterance);
      lastOutOfRangeSpeechAtRef.current = Date.now();
      outOfRangeMessageIndexRef.current += 1;
    }).catch((reason: unknown) => {
      setError(reason instanceof Error ? reason.message : "Could not play the out-of-range voice warning.");
    });
  }, []);

  const testPostureVoice = () => {
    if (!("speechSynthesis" in window) || window.speechSynthesis.speaking || window.speechSynthesis.pending) return;
    const utterance = new SpeechSynthesisUtterance(
      "Voice guidance is on. Sit upright, gently bring your head back over your shoulders, and keep both shoulders relaxed and level."
    );
    utterance.lang = "en-US";
    utterance.rate = 0.95;
    window.speechSynthesis.speak(utterance);
  };

  useEffect(() => {
    if (soundEnabled || !("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
  }, [soundEnabled]);

  useEffect(() => () => {
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  }, []);

  useEffect(() => {
    if (!stream || !session.active || busy) return;
    const timer = window.setInterval(async () => {
      const video = videoRef.current;
      const canvas = canvasRef.current;
      if (!video || !canvas || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return;
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      const context = canvas.getContext("2d");
      if (!context) return;
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise<Blob | null>((resolve) =>
        canvas.toBlob(resolve, "image/jpeg", 0.75)
      );
      if (!blob) return;
      try {
        const result = await api<ActiveSession>("/api/webcam/frame", {
          method: "POST",
          headers: { "Content-Type": "image/jpeg" },
          body: blob
        });
        setSession(result);
        const postureIncorrect = result.metrics.posture_status === "Slouching"
          || result.metrics.posture_status === "Leaning";
        if (postureIncorrect && !postureIncorrectRef.current) playAlert();
        postureIncorrectRef.current = postureIncorrect;
        const newAlerts = result.alerts.filter((alert) => !lastAlertsRef.current.includes(alert));
        if (newAlerts.length) playAlert();
        lastAlertsRef.current = result.alerts;
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "Could not process webcam frame.");
      }
    }, 500);
    return () => window.clearInterval(timer);
  }, [busy, playAlert, session.active, stream]);

  useEffect(() => {
    if (!postureStream || !postureStatus.active || postureBusy) return;
    let sending = false;
    const timer = window.setInterval(async () => {
      if (sending) return;
      const video = postureCaptureVideoRef.current;
      const canvas = postureCanvasRef.current;
      if (!video || !canvas || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return;
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      const context = canvas.getContext("2d");
      if (!context) return;
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise<Blob | null>((resolve) =>
        canvas.toBlob(resolve, "image/jpeg", 0.8)
      );
      if (!blob) return;
      sending = true;
      try {
        const result = await api<PostureStatus>("/api/posture/frame", {
          method: "POST",
          headers: { "Content-Type": "image/jpeg" },
          body: blob
        });
        setPostureStatus(result);
        const postureIncorrect = result.metrics.valid
          && (result.metrics.status === "Slouching" || result.metrics.status === "Leaning");
        if (postureIncorrect && !standalonePostureIncorrectRef.current) playAlert();
        standalonePostureIncorrectRef.current = postureIncorrect;
        speakPostureGuidance(result);
        speakOutOfRangeWarning(result);
      } catch (reason) {
        standalonePostureIncorrectRef.current = false;
        postureWarningSinceRef.current = null;
        lastPostureObservationAtRef.current = 0;
        outOfRangeConsecutiveFramesRef.current = 0;
        outOfRangeEpisodeHandledRef.current = false;
        setError(reason instanceof Error ? reason.message : "The KNN posture analyzer could not process this frame.");
      } finally {
        sending = false;
      }
    }, 400);
    return () => window.clearInterval(timer);
  }, [playAlert, postureBusy, postureStatus.active, postureStream, speakOutOfRangeWarning, speakPostureGuidance]);

  const openCamera = async () => {
    try {
      const cameraStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } },
        audio: false
      });
      setStream(cameraStream);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? `Camera unavailable: ${reason.message}` : "Camera permission was denied.");
    }
  };

  const closeCamera = () => {
    stream?.getTracks().forEach((track) => track.stop());
    setStream(null);
  };

  const startPostureAnalysis = async () => {
    setPostureBusy(true);
    setError("");
    postureVoiceSessionEnabledRef.current = true;
    outOfRangeConsecutiveFramesRef.current = 0;
    outOfRangeEpisodeHandledRef.current = false;
    let analysisStarted = false;
    try {
      speechVoicePromiseRef.current = "speechSynthesis" in window ? waitForSpeechVoice() : null;
      const status = await api<PostureStatus>("/api/posture/start", { method: "POST" });
      analysisStarted = true;
      setPostureStatus(status);
      const cameraStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 960 }, height: { ideal: 720 } },
        audio: false
      });
      setPostureStream(cameraStream);
    } catch (reason) {
      postureVoiceSessionEnabledRef.current = false;
      speechVoicePromiseRef.current = null;
      outOfRangeConsecutiveFramesRef.current = 0;
      outOfRangeEpisodeHandledRef.current = false;
      if ("speechSynthesis" in window) window.speechSynthesis.cancel();
      if (analysisStarted) {
        try {
          await api<PostureStatus>("/api/posture/stop", { method: "POST" });
        } catch {
          setError("Camera access failed, and the server could not stop the posture analyzer.");
          setPostureBusy(false);
          return;
        }
      }
      setPostureStatus((current) => ({ ...current, active: false }));
      setError(reason instanceof Error ? reason.message : "Could not start the KNN posture analyzer.");
    } finally {
      setPostureBusy(false);
    }
  };

  const stopPostureAnalysis = async () => {
    setPostureBusy(true);
    setError("");
    postureVoiceSessionEnabledRef.current = false;
    outOfRangeConsecutiveFramesRef.current = 0;
    outOfRangeEpisodeHandledRef.current = false;
    speechVoicePromiseRef.current = null;
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    try {
      const status = await api<PostureStatus>("/api/posture/stop", { method: "POST" });
      postureStream?.getTracks().forEach((track) => track.stop());
      setPostureStream(null);
      setPostureStatus(status);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not stop posture analysis.");
    } finally {
      setPostureBusy(false);
    }
  };

  const startBlock = async (kind: Kind) => {
    setBusy(true);
    setError("");
    try {
      const current = await api<ActiveSession>("/api/sessions/start", {
        method: "POST",
        body: JSON.stringify({ subject_id: selectedSubject, kind })
      });
      setSession(current);
      setAnchor({ elapsed: 0, at: Date.now() });
      lastAlertsRef.current = [];
      await openCamera();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not start the session.");
    } finally {
      setBusy(false);
    }
  };

  const stopBlock = async () => {
    setBusy(true);
    setError("");
    try {
      await api<ActiveSession>("/api/sessions/stop", { method: "POST" });
      setSession({
        active: false,
        session_id: null,
        subject_id: null,
        kind: null,
        elapsed_seconds: 0,
        metrics: idleMetrics,
        alerts: []
      });
      setAnchor(null);
      lastAlertsRef.current = [];
      closeCamera();
      try {
        await refreshData();
      } catch (reason) {
        setError(reason instanceof Error
          ? `Session finished, but the dashboard could not refresh: ${reason.message}`
          : "Session finished, but the dashboard could not refresh.");
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not finish the session.");
    } finally {
      setBusy(false);
    }
  };

  const switchBlock = async (kind: Kind) => {
    setBusy(true);
    setError("");
    try {
      await api<ActiveSession>("/api/sessions/stop", { method: "POST" });
      const next = await api<ActiveSession>("/api/sessions/start", {
        method: "POST",
        body: JSON.stringify({ subject_id: selectedSubject, kind })
      });
      setSession(next);
      setAnchor({ elapsed: 0, at: Date.now() });
      lastAlertsRef.current = [];
      try {
        await refreshData();
      } catch (reason) {
        setError(reason instanceof Error
          ? `Block switched, but the dashboard could not refresh: ${reason.message}`
          : "Block switched, but the dashboard could not refresh.");
      }
    } catch (reason) {
      try {
        const current = await api<ActiveSession>("/api/sessions/active");
        setSession(current);
        setAnchor(current.active ? { elapsed: current.elapsed_seconds, at: Date.now() } : null);
        if (!current.active) closeCamera();
      } catch {
        setSession({
          active: false,
          session_id: null,
          subject_id: null,
          kind: null,
          elapsed_seconds: 0,
          metrics: idleMetrics,
          alerts: []
        });
        setAnchor(null);
        closeCamera();
      }
      setError(reason instanceof Error ? reason.message : "Could not switch study blocks.");
    } finally {
      setBusy(false);
    }
  };

  const addSubject = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const subject = await api<Subject>("/api/subjects", {
        method: "POST",
        body: JSON.stringify({ name, color })
      });
      setSubjects((current) => [...current, subject]);
      setSelectedSubject(subject.id);
      setName("");
      setAddingSubject(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not add subject.");
    } finally {
      setBusy(false);
    }
  };

  const deleteSubject = async (subjectId: number) => {
    setError("");
    try {
      await api<void>(`/api/subjects/${subjectId}`, { method: "DELETE" });
      setSubjects((current) => current.filter((subject) => subject.id !== subjectId));
      if (selectedSubject === subjectId) setSelectedSubject(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not delete subject.");
    }
  };

  const maxDailyFocusSeconds = useMemo(
    () => Math.max(1, ...(stats?.daily.map((day) =>
      day.focus_seconds + (day.date === todayKey ? currentFocusSeconds : 0)
    ) ?? [])),
    [currentFocusSeconds, stats, todayKey]
  );
  const maxDailyTotalSeconds = useMemo(
    () => Math.max(1, ...(stats?.daily.map((day) =>
      day.focus_seconds + day.break_seconds +
      (day.date === todayKey ? currentFocusSeconds + currentBreakSeconds : 0)
    ) ?? [])),
    [currentBreakSeconds, currentFocusSeconds, stats, todayKey]
  );
  const posture = session.metrics;
  const postureTone = posture.posture_status === "Good"
    ? "good"
    : posture.posture_status === "Slouching" || posture.posture_status === "Leaning"
      ? "warning"
      : "neutral";
  const postureAnalyzerTone = postureStatus.metrics.status === "Good"
    ? "good"
    : postureStatus.metrics.status === "Slouching" || postureStatus.metrics.status === "Leaning"
      ? "warning"
      : "neutral";

  return (
    <main className="app-shell min-h-screen bg-ink text-zinc-100">
      <aside className="sidebar">
        <a className="brand" href="#" onClick={(event) => event.preventDefault()}>
          <span className="brand-mark"><Activity size={20} strokeWidth={2.7} /></span>
          <span>ergo<span className="brand-light">study</span><small>YOUR FOCUS, IN BALANCE</small></span>
        </a>

        <div className="side-label">WORKSPACE</div>
        <nav className="main-nav" aria-label="Main navigation">
          <button className={tab === "timer" ? "nav-item selected" : "nav-item"} onClick={() => setTab("timer")}>
            <Clock3 size={18} /><span>Focus timer</span><span className="nav-hotkey">⌘ 1</span>
          </button>
          <button className={tab === "stats" ? "nav-item selected" : "nav-item"} onClick={() => setTab("stats")}>
            <BarChart3 size={18} /><span>Study stats</span>
          </button>
          <button className={tab === "posture" ? "nav-item selected" : "nav-item"} onClick={() => setTab("posture")}>
            <Focus size={18} /><span>Posture analyzer</span>
          </button>
        </nav>

        <div className="side-section-heading">
          <div className="side-label">MY SUBJECTS</div>
          <button className="icon-button small" onClick={() => setAddingSubject((value) => !value)} aria-label="Add subject">
            {addingSubject ? <X size={16} /> : <Plus size={16} />}
          </button>
        </div>
        <div className="subject-list">
          {subjects.map((subject) => (
            <div className={selectedSubject === subject.id ? "subject-row active-subject" : "subject-row"} key={subject.id}>
              <button className="subject-select" onClick={() => setSelectedSubject(subject.id)} disabled={session.active}>
                <span className="subject-swatch" style={{ backgroundColor: subject.color }} />
                <span className="subject-name">{subject.name}</span>
                <span className="subject-time">{formatHours(subject.total_focus_seconds)}</span>
              </button>
              <button className="subject-remove" onClick={() => deleteSubject(subject.id)} disabled={session.active && session.subject_id === subject.id} aria-label={`Delete ${subject.name}`}>
                <X size={13} />
              </button>
            </div>
          ))}
          {subjects.length === 0 && <p className="empty-subjects">Add a subject to organize your focus time.</p>}
        </div>
        {addingSubject && (
          <form className="subject-form" onSubmit={addSubject}>
            <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Subject name" maxLength={100} required autoFocus />
            <div className="subject-form-bottom">
              <input aria-label="Subject color" type="color" value={color} onChange={(event) => setColor(event.target.value)} />
              <button className="mini-save" disabled={busy || !name.trim()}>Add subject</button>
            </div>
          </form>
        )}

        <div className="sidebar-spacer" />
        <div className="weekly-mini">
          <div className="weekly-mini-top"><span>LAST 7 DAYS</span><ArrowUpRight size={15} /></div>
          <strong>{formatHours((stats?.focus_seconds ?? 0) + currentFocusSeconds)}</strong>
          <span className="weekly-caption">focused this week</span>
          <div className="mini-progress"><i style={{ width: `${Math.min(100, focusToday / 14400 * 100)}%` }} /></div>
          <span className="goal-line">of 4h daily goal today</span>
        </div>
        <div className="profile-row">
          <div className="profile-avatar">E</div>
          <div><strong>Ergo learner</strong><small>Local workspace</small></div>
          <button className="icon-button profile-settings" aria-label="Settings"><Settings2 size={17} /></button>
        </div>
      </aside>

      <section className="main-panel">
        <header className="topbar">
          <div className="breadcrumb"><span>Workspace</span><span className="crumb-slash">/</span><strong>{tab === "timer" ? "Focus timer" : tab === "posture" ? "Posture analyzer" : "Study stats"}</strong></div>
          <div className="topbar-right">
            <span className="local-pill"><ShieldCheck size={14} /> LOCAL & PRIVATE</span>
            <button className="icon-button help-button" aria-label="Help"><CircleHelp size={18} /></button>
          </div>
        </header>

        {error && <div className="error-banner" role="alert"><span>{error}</span><button onClick={() => setError("")} aria-label="Dismiss"><X size={15} /></button></div>}
        <video ref={postureCaptureVideoRef} muted playsInline className="hidden-canvas" />
        <canvas ref={postureCanvasRef} className="hidden-canvas" />

        {tab === "timer" && (
          <div className="content timer-content">
            <div className="page-heading">
              <div><p className="eyebrow">{mounted ? new Date(now).toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" }) : " "}</p><h1>Make this time count.</h1><p className="subheading">A little progress, with a little more balance.</p></div>
              <div className="today-chip"><span className="today-dot" /><span>Today&apos;s focus</span><strong>{formatTime(focusToday)}</strong></div>
            </div>

            <div className="timer-grid">
              <section className={`timer-card ${session.kind === "break" ? "break-mode" : ""}`}>
                <div className="timer-card-header">
                  <div className="timer-state"><span className={session.active ? "state-dot live" : "state-dot"} />{session.active ? session.kind === "break" ? "ON A BREAK" : "FOCUS SESSION" : "READY WHEN YOU ARE"}</div>
                  <button className="icon-button" aria-label="Timer options"><Settings2 size={17} /></button>
                </div>
                <div className={`timer-ring ${session.active ? "ring-active" : ""} ${session.kind === "break" ? "ring-rest" : ""}`}>
                  <div className="ring-inner">
                    <span className="timer-label">{session.active ? session.kind === "break" ? "REST EASY" : "STAY IN THE FLOW" : "YOUR NEXT SESSION"}</span>
                    <div className="timer-digits">{formatTime(currentSeconds)}</div>
                    <span className="timer-subject">{selected?.name ?? "Choose a subject"}</span>
                  </div>
                </div>
                <div className="timer-controls">
                  {!session.active ? (
                    <button className="primary-button" onClick={() => startBlock("focus")} disabled={busy || postureStatus.active}>
                      <span className="play-triangle">▶</span>{busy ? "Starting…" : "Start focusing"}
                    </button>
                  ) : (
                    <button className="primary-button stop-button" onClick={stopBlock} disabled={busy}>
                      <span className="stop-square" />{busy ? "Finishing…" : "Finish session"}
                    </button>
                  )}
                  <button
                    className="secondary-button"
                    onClick={() => session.active ? switchBlock(session.kind === "break" ? "focus" : "break") : startBlock("break")}
                    disabled={busy || postureStatus.active}
                    title={session.active ? "Switch between focus and break" : "Start a break timer"}
                  >
                    {session.active && session.kind === "focus" ? <Coffee size={16} /> : <BookOpen size={16} />}
                    {session.active ? session.kind === "break" ? "Back to focus" : "Start a break" : "Take a break"}
                  </button>
                </div>
                <div className="timer-footer">
                  <label className="subject-picker"><BookOpen size={15} /><span>Studying</span>
                    <select value={selectedSubject ?? ""} onChange={(event) => setSelectedSubject(event.target.value ? Number(event.target.value) : null)} disabled={session.active}>
                      <option value="">No subject</option>
                      {subjects.map((subject) => <option value={subject.id} key={subject.id}>{subject.name}</option>)}
                    </select><ChevronDown size={14} />
                  </label>
                  <span className="session-kind"><AlarmClock size={14} /> Stopwatch</span>
                </div>
              </section>

              <section className="right-column">
                <div className="summary-card">
                  <div className="card-heading"><div><p className="eyebrow">YOUR DAY, AT A GLANCE</p><h2>Study rhythm</h2></div><button className="text-button" onClick={() => setTab("stats")}>Details <ArrowUpRight size={14} /></button></div>
                  <div className="summary-numbers">
                    <div><span>FOCUS TIME</span><strong>{formatHours(focusToday)}</strong><small className="positive"><ArrowUpRight size={13} /> Let&apos;s keep it steady</small></div>
                    <div><span>BREAK TIME</span><strong>{formatHours(breakToday)}</strong><small className="muted">Rest is part of the work</small></div>
                  </div>
                  <div className="week-bars" aria-label="Focus time over the last seven days">
                    {(stats?.daily ?? []).map((day) => {
                      const focus = day.focus_seconds + (day.date === todayKey ? currentFocusSeconds : 0);
                      const height = focus ? Math.max(8, focus / maxDailyFocusSeconds * 100) : 4;
                      const isToday = day.date === todayKey;
                      return <div className="bar-column" key={day.date}><div className="bar-track"><i className={isToday ? "bar-fill today" : "bar-fill"} style={{ height: `${height}%` }} /></div><span>{new Date(`${day.date}T12:00:00`).toLocaleDateString([], { weekday: "narrow" })}</span></div>;
                    })}
                  </div>
                </div>

                <div className="ergonomics-card">
                  <div className="card-heading ergonomic-heading"><div className="coach-icon"><Activity size={17} /></div><div><p className="eyebrow">QUIETLY LOOKING OUT FOR YOU</p><h2>Ergo coach</h2></div><span className="live-badge"><i />{stream && session.active ? "LIVE" : "STANDBY"}</span></div>
                  <div className="ergo-status-row">
                    <div className={`posture-indicator ${postureTone}`}><span className="posture-pulse" /><div><small>POSTURE</small><strong>{posture.posture_status}</strong></div></div>
                    <div className="ergo-metric"><small>EAR</small><strong>{posture.ear === null ? "—" : posture.ear.toFixed(2)}</strong></div>
                    <div className="ergo-metric"><small>MAR</small><strong>{posture.mar === null ? "—" : posture.mar.toFixed(2)}</strong></div>
                  </div>
                  <div className="ergo-bottom">
                    <span><span className="metric-count">{posture.blink_count}</span> blinks</span><span className="metric-divider" /><span><span className="metric-count">{posture.yawn_count}</span> yawns</span>
                    <button className="camera-toggle" onClick={stream ? closeCamera : openCamera} disabled={!session.active}>
                      <Webcam size={14} />{stream ? "Camera on" : "Enable camera"}
                    </button>
                    <label className="sound-toggle" title="Posture and fatigue alert sounds"><input type="checkbox" checked={soundEnabled} onChange={(event) => setSoundEnabled(event.target.checked)} /><span /><Headphones size={14} /></label>
                  </div>
                  {posture.drowsy && <div className="coach-alert"><Sparkles size={14} /> You seem tired. A short reset may help.</div>}
                  {!posture.calibrated && session.active && <div className="calibration-note">Hold a comfortable posture while your coach calibrates.</div>}
                  {posture.calibrated && !posture.drowsy && !session.alerts.length && <p className="coach-note">{posture.posture_status === "Good" ? "Nice alignment. Keep your shoulders relaxed." : "Your coach will nudge you if posture needs attention."}</p>}
                  {session.alerts.map((alert) => <div className="coach-alert" key={alert}><Sparkles size={14} />{alert}</div>)}
                </div>
                {stream && <div className="camera-preview"><video ref={videoRef} muted playsInline /><div className="camera-preview-label"><span className="live-dot" /> ERGONOMICS FEED</div><button onClick={closeCamera} aria-label="Turn camera off"><X size={15} /></button></div>}
                <canvas ref={canvasRef} className="hidden-canvas" />
              </section>
            </div>

            <section className="subject-focus-card">
              <div className="card-heading"><div><p className="eyebrow">YOUR SUBJECTS</p><h2>Pick up where you left off</h2></div><button className="text-button" onClick={() => setAddingSubject(true)}>Manage subjects <ArrowUpRight size={14} /></button></div>
              <div className="focus-subject-list">
                {subjects.slice(0, 4).map((subject, index) => (
                  <button className={`focus-subject ${selectedSubject === subject.id ? "focus-subject-selected" : ""}`} key={subject.id} onClick={() => setSelectedSubject(subject.id)} disabled={session.active}>
                    <span className="subject-icon" style={{ color: subject.color, backgroundColor: `${subject.color}18` }}>{index % 2 === 0 ? <BookOpen size={17} /> : <Activity size={17} />}</span>
                    <span className="focus-subject-info"><strong>{subject.name}</strong><small>{formatHours(subject.total_focus_seconds)} focused</small></span>
                    <span className="subject-select-arrow">{selectedSubject === subject.id ? <Check size={16} /> : <ArrowDownRight size={16} />}</span>
                  </button>
                ))}
                <button className="add-subject-tile" onClick={() => setAddingSubject(true)}><span><Plus size={17} /></span><strong>Add a subject</strong></button>
              </div>
            </section>
          </div>
        )}

        {tab === "posture" && (
          <div className="content posture-content">
            <div className="page-heading">
              <div>
                <p className="eyebrow">LIVE, LOCAL POSTURE CHECK</p>
                <h1>Posture analyzer.</h1>
                <p className="subheading">See the live camera analysis, KNN prediction, and every posture measurement it reads.</p>
              </div>
              <span className={`knn-ready-pill ${postureStatus.model_ready ? "ready" : "unavailable"}`}>
                <span />{postureStatus.model_ready ? "TRAINED KNN READY" : "KNN MODEL MISSING"}
              </span>
            </div>

            <div className="posture-layout">
              <section className="posture-feed-card">
                <div className="posture-feed-header">
                  <div><p className="eyebrow">CAMERA ANALYSIS</p><h2>{postureStatus.active ? "Your live posture" : "Start a posture check"}</h2></div>
                  <span className={`analyzer-live-state ${postureStatus.active ? "running" : ""}`}><i />{postureStatus.active ? "ANALYZING" : "STANDBY"}</span>
                </div>
                <div className={`posture-feed ${postureStream ? "feed-live" : ""}`}>
                  {postureStream ? (
                    <>
                      <video ref={posturePreviewVideoRef} muted playsInline />
                      <div className="feed-corner-mark"><span className="live-dot" /> LIVE KNN ANALYSIS</div>
                      <div className="feed-model-tag">33 POSE LANDMARKS · KNN</div>
                      <div className={`feed-result ${postureStatus.metrics.status === "Good" ? "good" : postureStatus.metrics.status === "Slouching" || postureStatus.metrics.status === "Leaning" ? "warning" : ""}`}>
                        <span className="feed-result-dot" />
                        <div><small>POSTURE CLASS</small><strong>{postureStatus.metrics.status}</strong></div>
                        {postureStatus.metrics.score !== null && <b>{Math.round(postureStatus.metrics.score)}<small>%</small></b>}
                      </div>
                    </>
                  ) : (
                    <div className="camera-empty">
                      <span className="camera-empty-icon"><Webcam size={27} /></span>
                      <strong>{postureStatus.active ? "Reconnect your camera" : "Your camera stays on this device"}</strong>
                      <p>{postureStatus.active ? "The analyzer is running. Allow camera access to send a live frame." : "Start the check to stream frames locally to the KNN posture model."}</p>
                    </div>
                  )}
                </div>
                <div className="posture-feed-controls">
                  <p><ShieldCheck size={14} /> Frames are analyzed in memory and never stored.</p>
                  <div className="posture-control-actions">
                    <button
                      className={`range-voice-toggle ${soundEnabled ? "enabled" : ""}`}
                      type="button"
                      onClick={() => setSoundEnabled((enabled) => !enabled)}
                      aria-label={soundEnabled ? "Mute posture alert sound" : "Enable posture alert sound"}
                      aria-pressed={soundEnabled}
                      title="Toggle immediate posture alert sound"
                    >
                      {soundEnabled ? <Volume2 size={14} /> : <VolumeX size={14} />}
                      {soundEnabled ? "Sound on" : "Sound muted"}
                    </button>
                    <button
                      className={`range-voice-toggle ${outOfRangeVoiceEnabled ? "enabled" : ""}`}
                      type="button"
                      onClick={() => {
                        const enabled = !outOfRangeVoiceEnabledRef.current;
                        outOfRangeVoiceEnabledRef.current = enabled;
                        setOutOfRangeVoiceEnabled(enabled);
                        if (!enabled && "speechSynthesis" in window) window.speechSynthesis.cancel();
                      }}
                      disabled={!mounted || !("speechSynthesis" in window)}
                      aria-label={outOfRangeVoiceEnabled ? "Mute out-of-range voice warning" : "Unmute out-of-range voice warning"}
                      aria-pressed={outOfRangeVoiceEnabled}
                      title="Toggle spoken out-of-range warning"
                    >
                      {outOfRangeVoiceEnabled ? <Volume2 size={14} /> : <VolumeX size={14} />}
                      {outOfRangeVoiceEnabled ? "Voice on" : "Voice muted"}
                    </button>
                    {postureStatus.active ? (
                      <button className="primary-button stop-button" onClick={stopPostureAnalysis} disabled={postureBusy}><span className="stop-square" />{postureBusy ? "Stopping…" : "Stop analysis"}</button>
                    ) : (
                      <button className="primary-button" onClick={startPostureAnalysis} disabled={postureBusy || !postureStatus.model_ready || session.active}>
                        <Activity size={15} />{postureBusy ? "Starting…" : "Start posture analysis"}
                      </button>
                    )}
                  </div>
                </div>
                {!postureStatus.model_ready && <p className="model-missing-note">The trained KNN file was not found. Train it with <code>train_posture_knn.py</code> before starting analysis.</p>}
                {session.active && <p className="model-missing-note">Finish the running focus/break timer before using this standalone analyzer.</p>}
              </section>

              <div className="posture-detail-column">
                <section className="posture-classification-card">
                  <div className="card-heading">
                    <div><p className="eyebrow">PRIMARY CLASSIFIER</p><h2>Trained KNN model</h2></div>
                    <span className="knn-chip">K = 7</span>
                  </div>
                  <p className="classifier-description">Each camera frame is converted into 33 MediaPipe world-space pose landmarks (99 coordinates), centered on the body rather than the camera frame. The trained, scaled 7-neighbor KNN predicts the posture class.</p>
                  <div className="classifier-flow"><span>WEBCAM FRAME</span><i /><span>WORLD POSE</span><i /><strong>KNN</strong></div>
                  <div className={`posture-verdict ${postureAnalyzerTone}`}>
                    <span className="verdict-symbol">{postureAnalyzerTone === "good" ? <Check size={17} /> : postureAnalyzerTone === "warning" ? <Activity size={17} /> : <Webcam size={17} />}</span>
                    <div><small>{postureStatus.metrics.geometric_override ? "HEAD-TILT RULE" : "MODEL PREDICTION"}</small><strong>{postureStatus.metrics.status}</strong></div>
                    <span className="verdict-model">{postureStatus.metrics.geometric_override ? "GEOMETRY" : postureStatus.metrics.classifier_name ?? "KNN"}</span>
                  </div>
                  {postureStatus.metrics.classifier_name !== "KNN" && postureStatus.active && <div className="model-missing-note">Analysis is paused until the KNN classifier returns a prediction.</div>}
                </section>

                <section className="posture-readings-card">
                  <div className="card-heading"><div><p className="eyebrow">LIVE MEASUREMENTS</p><h2>Posture readings</h2></div></div>
                  <div className="reading-row"><span>Neck angle</span><strong>{postureStatus.metrics.neck_angle === null ? "—" : `${postureStatus.metrics.neck_angle.toFixed(1)}°`}</strong></div>
                  <div className="reading-row"><span>Head tilt from baseline</span><strong>{postureStatus.metrics.head_tilt_delta === null ? "—" : `${Math.abs(postureStatus.metrics.head_tilt_delta).toFixed(1)}°`}</strong></div>
                  <div className="reading-row"><span>Screen distance ratio</span><strong>{postureStatus.metrics.proximity_ratio === null ? "—" : postureStatus.metrics.proximity_ratio.toFixed(2)}</strong></div>
                  <div className="reading-row"><span>Posture score</span><strong>{postureStatus.metrics.score === null ? "—" : `${Math.round(postureStatus.metrics.score)}%`}</strong></div>
                  <div className="reading-row"><span>Calibration</span><strong className={postureStatus.metrics.calibrated ? "reading-good" : "reading-pending"}>{postureStatus.metrics.calibrated ? "Complete" : postureStatus.active ? "In progress · 5 sec" : "Not started"}</strong></div>
                  <div className="reading-row"><span>Geometric rule check</span><strong>{postureStatus.metrics.rule_status ?? "—"}</strong></div>
                  <div className="reading-row"><span>Pose detected</span><strong className={postureStatus.metrics.valid ? "reading-good" : "reading-pending"}>{postureStatus.metrics.valid ? "Yes" : postureStatus.active ? "Waiting" : "No"}</strong></div>
                  <div className="reading-row"><span>KNN classifier used</span><strong className={postureStatus.metrics.classifier_used && postureStatus.metrics.classifier_name === "KNN" ? "reading-good" : "reading-pending"}>{postureStatus.metrics.classifier_used && postureStatus.metrics.classifier_name === "KNN" ? "Yes" : "Waiting"}</strong></div>
                  <div className="reading-row"><span>KNN match distance / limit</span><strong>{postureStatus.metrics.classifier_distance === null || postureStatus.metrics.classifier_distance_limit === null ? "—" : `${postureStatus.metrics.classifier_distance.toFixed(1)} / ${postureStatus.metrics.classifier_distance_limit.toFixed(1)}`}</strong></div>
                  <div className="reading-row"><span>Analysis time</span><strong>{postureStatus.active ? formatTime(postureStatus.elapsed_seconds) : "—"}</strong></div>
                  <p className="secondary-check-note">A clear head tilt overrides the model result; other geometric checks remain a secondary comparison.</p>
                  {postureStatus.metrics.status === "Uncertain" && <p className="model-missing-note">This frame is outside the KNN&apos;s learned range. No posture class or score is being guessed.</p>}
                </section>

                <section className={`posture-guidance-card ${postureAnalyzerTone}`}>
                  <div className="card-heading"><div><p className="eyebrow">LIVE CORRECTION</p><h2>{postureGuidance(postureStatus.metrics.status)?.title ?? "Waiting for a posture reading"}</h2></div></div>
                  <p>{postureGuidance(postureStatus.metrics.status)?.advice ?? "Start analysis and sit where your upper body is visible to the camera."}</p>
                  <label className="speech-setting">
                    <input
                      type="checkbox"
                      checked={soundEnabled}
                      onChange={(event) => setSoundEnabled(event.target.checked)}
                      aria-label="Speak posture warnings and correction guidance"
                    />
                    <Headphones size={15} />
                    <span>Speak posture warnings and corrections</span>
                  </label>
                  <button
                    className="speech-test-button"
                    onClick={testPostureVoice}
                    disabled={!mounted || !("speechSynthesis" in window)}
                  >
                    Test voice guidance
                  </button>
                  {mounted && !("speechSynthesis" in window) && <p className="speech-unavailable">Voice guidance is not supported by this browser.</p>}
                  <p className="speech-timing">Voice guidance waits for a sustained incorrect KNN prediction and repeats no more than every 30 seconds.</p>
                </section>
              </div>
            </div>
            <div className="posture-footnote"><Activity size={14} /><span>Model posture score is a display mapping of its predicted class (Good 100, Leaning 80, Slouching 70), not a calibrated medical or ergonomic measurement.</span></div>
          </div>
        )}

        {tab === "stats" && (
          <div className="content">
            <div className="page-heading stats-heading"><div><p className="eyebrow">THE BIG PICTURE</p><h1>Your study rhythm.</h1><p className="subheading">Small steps add up. Here&apos;s your last seven days.</p></div><span className="range-pill">LAST 7 DAYS <ChevronDown size={14} /></span></div>
            <div className="stats-cards">
              <div className="stat-card"><span className="stat-icon green"><Clock3 size={17} /></span><small>FOCUS TIME</small><strong>{formatHours(stats?.focus_seconds ?? 0)}</strong><span className="stat-foot">Across your study blocks</span></div>
              <div className="stat-card"><span className="stat-icon orange"><Coffee size={17} /></span><small>BREAK TIME</small><strong>{formatHours(stats?.break_seconds ?? 0)}</strong><span className="stat-foot">Every reset counts</span></div>
              <div className="stat-card"><span className="stat-icon blue"><Activity size={17} /></span><small>POSTURE SCORE</small><strong>{stats?.average_posture_score === null || stats?.average_posture_score === undefined ? "—" : `${Math.round(stats.average_posture_score)}%`}</strong><span className="stat-foot">Average during focus blocks</span></div>
              <div className="stat-card"><span className="stat-icon purple"><Sparkles size={17} /></span><small>BLINKS / YAWNS</small><strong>{stats?.total_blinks ?? 0}<em> / {stats?.total_yawns ?? 0}</em></strong><span className="stat-foot">Captured while camera was on</span></div>
            </div>
            <div className="stats-main-grid">
              <section className="chart-card">
                <div className="card-heading"><div><p className="eyebrow">CONSISTENCY OVER INTENSITY</p><h2>Daily focus time</h2></div><span className="chart-legend"><i />Focus <i className="legend-break" />Break</span></div>
                <div className="large-chart">
                  {(stats?.daily ?? []).map((day) => {
                    const today = day.date === todayKey;
                    const focusSeconds = day.focus_seconds + (today ? currentFocusSeconds : 0);
                    const breakSeconds = day.break_seconds + (today ? currentBreakSeconds : 0);
                    const totalSeconds = focusSeconds + breakSeconds;
                    const height = totalSeconds ? Math.max(4, totalSeconds / maxDailyTotalSeconds * 100) : 2;
                    const focusPercent = totalSeconds ? focusSeconds / totalSeconds * 100 : 0;
                    const breakPercent = totalSeconds ? breakSeconds / totalSeconds * 100 : 0;
                    return <div className="large-bar-column" key={day.date}><strong>{focusSeconds ? formatHours(focusSeconds) : ""}</strong><div className="large-bar-track"><i className="large-bar-stack" style={{ height: `${height}%` }}><span className={today ? "large-bar-focus today" : "large-bar-focus"} style={{ height: `${focusPercent}%` }} /><span className="large-bar-break" style={{ height: `${breakPercent}%` }} /></i></div><span>{new Date(`${day.date}T12:00:00`).toLocaleDateString([], { weekday: "short" })}</span></div>;
                  })}
                </div>
              </section>
              <section className="subject-stats-card">
                <div className="card-heading"><div><p className="eyebrow">WHERE YOUR TIME GOES</p><h2>By subject</h2></div></div>
                {stats?.subjects.filter((subject) => subject.focus_seconds > 0).length ? stats.subjects.filter((subject) => subject.focus_seconds > 0).map((subject) => (
                  <div className="subject-stat-row" key={subject.id}><span className="subject-swatch" style={{ backgroundColor: subject.color }} /><div className="subject-stat-info"><div><strong>{subject.name}</strong><span>{formatHours(subject.focus_seconds)}</span></div><div className="subject-stat-track"><i style={{ width: `${Math.max(4, subject.focus_seconds / Math.max(1, ...stats.subjects.map((item) => item.focus_seconds)) * 100)}%`, backgroundColor: subject.color }} /></div></div></div>
                )) : <p className="empty-state">Your subject breakdown will show up after your first focus session.</p>}
              </section>
            </div>
            <section className="history-card">
              <div className="card-heading"><div><p className="eyebrow">RECENT BLOCKS</p><h2>Study log</h2></div></div>
              <div className="log-list">
                {history.length ? history.map((log) => <div className="log-row" key={log.id}><span className={`log-kind ${log.kind}`}>{log.kind === "focus" ? <BookOpen size={15} /> : <Coffee size={15} />}</span><span className="log-subject">{log.subject_name ?? (log.kind === "focus" ? "Focus session" : "Break")}</span><span className="log-date">{formatClock(log.started_at)}</span><strong>{formatTime(log.duration_seconds)}</strong><span className={`log-posture ${log.status === "interrupted" ? "log-interrupted" : ""}`}>{log.status === "interrupted" ? "Interrupted" : log.average_posture_score === null ? "—" : `${Math.round(log.average_posture_score)}% posture`}</span></div>) : <p className="empty-state">Your finished sessions will appear here.</p>}
              </div>
            </section>
          </div>
        )}

        <footer className="page-footer"><span>Made for longer focus & healthier habits.</span><span><ShieldCheck size={13} /> Your camera feed is processed locally and never saved.</span></footer>
      </section>
    </main>
  );
}
