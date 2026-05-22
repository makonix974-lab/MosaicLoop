// MosaicLoop main entry — M2: recorder + metronome.

import { Metronome } from "./metronome.js";

const $ = (id) => document.getElementById(id);

// ---------- Capability checks (from M0) ----------

function setStatus(id, text, level = "") {
  const el = $(id);
  if (!el) return;
  el.textContent = text;
  el.className = level;
}

function pickRecorderMime() {
  const candidates = [
    "video/mp4;codecs=avc1,mp4a",
    "video/webm;codecs=vp9,opus",
    "video/webm;codecs=vp8,opus",
    "video/webm",
  ];
  for (const c of candidates) {
    if (MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(c)) {
      return c;
    }
  }
  return "";
}

function reportEnvironment() {
  setStatus("s-https",
    window.isSecureContext ? "secure context" : "INSECURE — getUserMedia will refuse",
    window.isSecureContext ? "ok" : "bad");

  setStatus("s-sw",
    "serviceWorker" in navigator ? "supported" : "missing",
    "serviceWorker" in navigator ? "ok" : "bad");

  const standalone = window.matchMedia("(display-mode: standalone)").matches
                  || window.navigator.standalone === true;
  setStatus("s-display",
    standalone ? "standalone (installed)" : "browser tab",
    standalone ? "ok" : "warn");

  const gum = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  setStatus("s-gum", gum ? "available" : "missing", gum ? "ok" : "bad");

  if ("MediaRecorder" in window) {
    const mime = pickRecorderMime();
    setStatus("s-mr", mime ? `supported (${mime})` : "no usable MIME",
              mime ? "ok" : "bad");
  } else {
    setStatus("s-mr", "missing", "bad");
  }

  const ac = "AudioContext" in window || "webkitAudioContext" in window;
  setStatus("s-ac", ac ? "available" : "missing", ac ? "ok" : "bad");
}

// ---------- PWA plumbing ----------

async function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  try { await navigator.serviceWorker.register("./sw.js"); }
  catch (err) { console.error("SW registration failed:", err); }
}

function wireInstallPrompt() {
  let deferred = null;
  const btn = $("install-btn");
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferred = e;
    btn.hidden = false;
  });
  btn.addEventListener("click", async () => {
    if (!deferred) return;
    deferred.prompt();
    await deferred.userChoice;
    deferred = null;
    btn.hidden = true;
  });
  window.addEventListener("appinstalled", () => { btn.hidden = true; });
}

// ---------- Recorder ----------
//
// State machine: idle -> ready -> recording -> stopped -> ready -> ...
//
// `ready` means we have a live MediaStream and the preview is running.
// Once stopped, we keep the stream so the user can record again without
// re-asking for permission.

const recState = {
  stream: null,
  recorder: null,
  chunks: [],
  mime: "",
  facing: "user",       // 'user' = selfie, 'environment' = rear
  startTime: 0,
  timerId: 0,
  blobUrl: null,
};

function fmtTime(seconds) {
  const m = Math.floor(seconds / 60).toString().padStart(2, "0");
  const s = Math.floor(seconds % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

function fmtBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function showMsg(text, level = "muted") {
  const el = $("rec-msg");
  el.textContent = text;
  el.className = level;
  el.hidden = !text;
}

function setRecMode(mode) {
  // mode: 'idle' | 'ready' | 'recording' | 'stopped'
  $("enable-btn").hidden  = mode !== "idle";
  $("record-btn").hidden  = !(mode === "ready" || mode === "stopped");
  $("stop-btn").hidden    = mode !== "recording";
  $("flip-btn").hidden    = !(mode === "ready" || mode === "stopped");
  $("download-link").hidden = mode !== "stopped";
  $("preview").hidden  = mode === "stopped";
  $("playback").hidden = mode !== "stopped";

  // Free memory: stop pinning the playback blob when we leave 'stopped'.
  if (mode !== "stopped") {
    $("playback").removeAttribute("src");
    $("playback").load();
  }
}

async function startStream(facing) {
  // Stop whatever was running before switching facing.
  if (recState.stream) {
    recState.stream.getTracks().forEach((t) => t.stop());
    recState.stream = null;
  }

  const constraints = {
    video: {
      facingMode: { ideal: facing },
      width:  { ideal: 1280 },
      height: { ideal: 720 },
      frameRate: { ideal: 30 },
    },
    audio: {
      // Critical for the future sync beep + raw musical signal.
      echoCancellation: false,
      noiseSuppression: false,
      autoGainControl:  false,
    },
  };

  const stream = await navigator.mediaDevices.getUserMedia(constraints);
  recState.stream = stream;
  recState.facing = facing;
  $("preview").srcObject = stream;
  await $("preview").play().catch(() => {});  // some Androids need explicit play
}

async function onEnable() {
  showMsg("Requesting camera…");
  try {
    await startStream(recState.facing);
    showMsg("");
    setRecMode("ready");
  } catch (err) {
    showMsg(`Camera error: ${err.name} — ${err.message}`, "bad");
    setRecMode("idle");
  }
}

async function onFlip() {
  const next = recState.facing === "user" ? "environment" : "user";
  try { await startStream(next); }
  catch (err) {
    // Fallback: many devices don't have a second camera or refuse the swap.
    showMsg(`Flip failed: ${err.message}. Sticking with ${recState.facing}.`,
            "warn");
    await startStream(recState.facing);
  }
}

function onRecord() {
  if (!recState.stream) return;

  // Throw away any previous blob URL so memory doesn't leak.
  if (recState.blobUrl) {
    URL.revokeObjectURL(recState.blobUrl);
    recState.blobUrl = null;
  }

  recState.mime = pickRecorderMime();
  recState.chunks = [];

  const recorder = new MediaRecorder(recState.stream,
    recState.mime ? { mimeType: recState.mime } : undefined);

  recorder.ondataavailable = (e) => {
    if (e.data && e.data.size > 0) recState.chunks.push(e.data);
  };

  recorder.onstop = () => {
    const blob = new Blob(recState.chunks, { type: recState.mime || "video/webm" });
    const url = URL.createObjectURL(blob);
    recState.blobUrl = url;

    const playback = $("playback");
    playback.src = url;
    // Chrome Android often writes webm without a duration header. The
    // <video> reads `duration === Infinity` and refuses to scrub. The
    // workaround: seek past the end, the browser then walks the stream,
    // computes the real duration, and resets currentTime to 0.
    playback.addEventListener("loadedmetadata", function fixDuration() {
      if (playback.duration === Infinity) {
        playback.currentTime = 1e10;
        playback.addEventListener("timeupdate", function once() {
          playback.removeEventListener("timeupdate", once);
          playback.currentTime = 0;
        });
      }
      playback.removeEventListener("loadedmetadata", fixDuration);
    });
    playback.load();

    const link = $("download-link");
    const ext = (recState.mime || "video/webm").startsWith("video/mp4") ? "mp4" : "webm";
    const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    link.href = url;
    link.download = `mosaic-${ts}.${ext}`;

    $("rec-info").textContent = `${fmtBytes(blob.size)} • ${recState.mime || "video/webm"}`;
    setRecMode("stopped");
  };

  recorder.onerror = (e) => {
    showMsg(`Recorder error: ${e.error?.message || "unknown"}`, "bad");
  };

  recState.recorder = recorder;
  recState.startTime = performance.now();
  recorder.start();  // collect a single chunk on stop; timeslice comes later
  setRecMode("recording");
  $("rec-info").textContent = "";
  startTimer();
}

function onStop() {
  if (recState.recorder && recState.recorder.state !== "inactive") {
    recState.recorder.stop();
  }
  stopTimer();
}

function startTimer() {
  stopTimer();
  const tick = () => {
    const elapsed = (performance.now() - recState.startTime) / 1000;
    $("rec-timer").textContent = fmtTime(elapsed);
  };
  tick();
  recState.timerId = setInterval(tick, 250);
}

function stopTimer() {
  if (recState.timerId) {
    clearInterval(recState.timerId);
    recState.timerId = 0;
  }
}

function wireRecorder() {
  $("enable-btn").addEventListener("click", onEnable);
  $("record-btn").addEventListener("click", onRecord);
  $("stop-btn").addEventListener("click", onStop);
  $("flip-btn").addEventListener("click", onFlip);

  // Free the camera if the page is hidden (saves battery + lets other
  // apps grab the cam). The user re-clicks Enable when they come back.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden" && recState.stream
        && (!recState.recorder || recState.recorder.state === "inactive")) {
      recState.stream.getTracks().forEach((t) => t.stop());
      recState.stream = null;
      setRecMode("idle");
      showMsg("Camera released. Tap Enable camera to resume.");
    }
  });
}

// ---------- Metronome ----------

const metro = new Metronome();

function renderMetroLeds() {
  const host = $("metro-leds");
  host.innerHTML = "";
  for (let i = 0; i < metro.beatsPerBar; i++) {
    const led = document.createElement("span");
    led.className = "metro-led";
    if (i === 0 && metro.accentFirst) led.classList.add("accent");
    host.appendChild(led);
  }
}

function flashLed(beat1Based, isAccent) {
  const leds = $("metro-leds").children;
  const idx = beat1Based - 1;
  if (idx < 0 || idx >= leds.length) return;
  const el = leds[idx];
  el.classList.add("on");
  if (isAccent) el.classList.add("flash-accent");
  setTimeout(() => {
    el.classList.remove("on", "flash-accent");
  }, 90);
}

function syncBpmInputs(v) {
  $("metro-bpm").value = v;
  $("metro-bpm-num").value = v;
  $("metro-bpm-val").textContent = v;
}

function wireMetronome() {
  metro.onTick = ({ beat, isAccent }) => flashLed(beat, isAccent);
  renderMetroLeds();

  const onBpm = (raw) => {
    const v = Math.max(40, Math.min(220, Math.round(Number(raw) || 100)));
    metro.setBpm(v);
    syncBpmInputs(v);
  };
  $("metro-bpm").addEventListener("input", (e) => onBpm(e.target.value));
  $("metro-bpm-num").addEventListener("change", (e) => onBpm(e.target.value));

  $("metro-beats").addEventListener("change", (e) => {
    metro.setBeatsPerBar(Number(e.target.value));
    renderMetroLeds();
  });

  $("metro-accent").addEventListener("change", (e) => {
    metro.setAccentFirst(e.target.checked);
    renderMetroLeds();
  });

  $("metro-vol").addEventListener("input", (e) => {
    metro.setVolume(Number(e.target.value));
  });

  $("metro-toggle").addEventListener("click", async () => {
    if (metro.isRunning) {
      metro.stop();
      $("metro-toggle").textContent = "Start metronome";
      $("metro-toggle").classList.remove("active");
    } else {
      try {
        await metro.start();
        $("metro-toggle").textContent = "Stop metronome";
        $("metro-toggle").classList.add("active");
      } catch (err) {
        console.error("Metronome failed to start:", err);
      }
    }
  });

  // Suspending the AudioContext when the tab is hidden saves battery
  // and avoids weird glitches when Android suspends background audio.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden" && metro.isRunning) {
      metro.stop();
      $("metro-toggle").textContent = "Start metronome";
      $("metro-toggle").classList.remove("active");
    }
  });
}

// ---------- Boot ----------

reportEnvironment();
registerServiceWorker();
wireInstallPrompt();
wireRecorder();
wireMetronome();
setRecMode("idle");
