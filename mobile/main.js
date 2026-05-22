// MosaicLoop main entry — M6: export session.

import { Metronome } from "./metronome.js";
import { buildZip } from "./zipstore.js";

const $ = (id) => document.getElementById(id);

// ---------- On-screen debug log (so we can see errors on mobile) ----------

function debugLog(...parts) {
  const card = $("debug-card");
  const pre  = $("debug-log");
  if (!card || !pre) return;
  card.hidden = false;
  const ts = new Date().toLocaleTimeString();
  pre.textContent = `[${ts}] ${parts.join(" ")}\n` + pre.textContent;
}

window.addEventListener("error", (e) => {
  debugLog("ERROR:", e.message, "@", e.filename + ":" + e.lineno);
});
window.addEventListener("unhandledrejection", (e) => {
  debugLog("UNHANDLED:", String(e.reason && e.reason.message || e.reason));
});

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
  audioDeviceId: null,  // selected microphone, or null for default
  startTime: 0,
  timerId: 0,
  blobUrl: null,
};

// VU meter — separate AudioContext from the metronome's because we
// need to feed it the *recording* mic stream, and binding the mic into
// the metronome ctx would risk feedback if the routing is sloppy.
const vu = {
  ctx: null,
  src: null,
  analyser: null,
  rafId: 0,
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

async function startStream(facing, audioDeviceId = null) {
  // Stop whatever was running before switching facing or device.
  if (recState.stream) {
    recState.stream.getTracks().forEach((t) => t.stop());
    recState.stream = null;
  }
  stopVuMeter();

  const audio = {
    // Critical for the future sync beep + raw musical signal.
    echoCancellation: false,
    noiseSuppression: false,
    autoGainControl:  false,
  };
  if (audioDeviceId) {
    // 'exact' would throw if the device disappears (e.g. headphones
    // unplugged); 'ideal' lets the browser fall back gracefully.
    audio.deviceId = { ideal: audioDeviceId };
  }

  const constraints = {
    video: {
      facingMode: { ideal: facing },
      width:  { ideal: 1280 },
      height: { ideal: 720 },
      frameRate: { ideal: 30 },
    },
    audio,
  };

  const stream = await navigator.mediaDevices.getUserMedia(constraints);
  recState.stream = stream;
  recState.facing = facing;
  recState.audioDeviceId = audioDeviceId
    || stream.getAudioTracks()[0]?.getSettings()?.deviceId
    || null;
  $("preview").srcObject = stream;
  await $("preview").play().catch(() => {});

  await populateMicSelect();
  startVuMeter(stream);
}

async function populateMicSelect() {
  const sel = $("mic-select");
  if (!navigator.mediaDevices.enumerateDevices) {
    sel.innerHTML = "<option>(enumerateDevices unsupported)</option>";
    sel.disabled = true;
    return;
  }
  // enumerateDevices only returns labels after at least one
  // getUserMedia grant — by now we have one, so labels are populated.
  const devices = await navigator.mediaDevices.enumerateDevices();
  const mics = devices.filter(d => d.kind === "audioinput");
  sel.innerHTML = "";
  if (mics.length === 0) {
    sel.innerHTML = "<option>(no microphones found)</option>";
    sel.disabled = true;
    return;
  }
  for (const m of mics) {
    const opt = document.createElement("option");
    opt.value = m.deviceId;
    opt.textContent = m.label || `Mic ${m.deviceId.slice(0, 6)}`;
    if (recState.audioDeviceId && m.deviceId === recState.audioDeviceId) {
      opt.selected = true;
    }
    sel.appendChild(opt);
  }
  sel.disabled = false;
}

/** Called by navigator.mediaDevices 'devicechange' events: phone
 *  reports a new device list (e.g. headphones plugged or unplugged).
 *  We refresh the dropdown, and if the currently-active mic vanished,
 *  we re-acquire on whatever the OS now considers default. */
async function onDeviceChange() {
  if (!recState.stream) return;
  const recording = recState.recorder && recState.recorder.state === "recording";
  if (recording) {
    debugLog("devicechange ignored: recording in progress");
    return;
  }

  const devices = await navigator.mediaDevices.enumerateDevices();
  const mics = devices.filter(d => d.kind === "audioinput");
  const stillThere = recState.audioDeviceId
    && mics.some(m => m.deviceId === recState.audioDeviceId);

  if (!stillThere) {
    debugLog("devicechange: active mic gone, re-acquiring on default");
    showMsg("Audio device changed. Re-acquiring…");
    try {
      await startStream(recState.facing, null);
      showMsg("");
    } catch (err) {
      showMsg(`Re-acquire failed: ${err.message}`, "bad");
    }
  } else {
    // Same device still present, just refresh the list (labels may
    // have changed: 'wired headset' appears/disappears, etc.)
    await populateMicSelect();
  }
}

async function onMicChange(deviceId) {
  if (!recState.stream) return;
  if (recState.recorder && recState.recorder.state === "recording") {
    debugLog("mic change blocked: recording in progress");
    return;
  }
  try {
    showMsg("Switching mic…");
    await startStream(recState.facing, deviceId);
    showMsg("");
  } catch (err) {
    showMsg(`Mic switch failed: ${err.message}`, "bad");
    debugLog("mic switch failed:", err && err.message);
  }
}

// ---------- VU meter ----------

function startVuMeter(stream) {
  stopVuMeter();
  const tracks = stream.getAudioTracks();
  if (tracks.length === 0) return;

  const Ctor = window.AudioContext || window.webkitAudioContext;
  vu.ctx = new Ctor();
  vu.src = vu.ctx.createMediaStreamSource(stream);
  vu.analyser = vu.ctx.createAnalyser();
  vu.analyser.fftSize = 1024;
  vu.analyser.smoothingTimeConstant = 0.4;
  vu.src.connect(vu.analyser);
  // No connection to destination: we only want to *measure*, not play.

  const buf = new Uint8Array(vu.analyser.fftSize);
  let peakHold = 0;
  let peakHoldTimer = 0;

  const tick = () => {
    if (!vu.analyser) return;
    vu.analyser.getByteTimeDomainData(buf);
    // RMS in 0..1 of the [0..255] PCM-ish samples centred on 128.
    let sum = 0;
    for (let i = 0; i < buf.length; i++) {
      const v = (buf[i] - 128) / 128;
      sum += v * v;
    }
    const rms = Math.sqrt(sum / buf.length);
    // Compress to a friendlier scale: dB-ish, then clamp to 0..1.
    const level = Math.min(1, Math.max(0, (20 * Math.log10(rms + 1e-6) + 60) / 60));

    if (level > peakHold) {
      peakHold = level;
      clearTimeout(peakHoldTimer);
      peakHoldTimer = setTimeout(() => { peakHold = 0; }, 800);
    }

    const fill = $("vu-fill");
    if (fill) fill.style.width = `${(level * 100).toFixed(1)}%`;

    const label = $("vu-label");
    if (label) {
      if (level < 0.02) label.textContent = "mic silent (no signal)";
      else if (level < 0.15) label.textContent = `low (${(level * 100).toFixed(0)}%)`;
      else if (level < 0.85) label.textContent = `ok (${(level * 100).toFixed(0)}%)`;
      else label.textContent = `LOUD (${(level * 100).toFixed(0)}%)`;
    }
    vu.rafId = requestAnimationFrame(tick);
  };
  tick();
}

function stopVuMeter() {
  if (vu.rafId) cancelAnimationFrame(vu.rafId);
  vu.rafId = 0;
  if (vu.src) { try { vu.src.disconnect(); } catch (_) {} }
  if (vu.analyser) { try { vu.analyser.disconnect(); } catch (_) {} }
  if (vu.ctx) { try { vu.ctx.close(); } catch (_) {} }
  vu.src = vu.analyser = vu.ctx = null;
  const fill = $("vu-fill");
  if (fill) fill.style.width = "0%";
  const label = $("vu-label");
  if (label) label.textContent = "mic idle";
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
  startRecording();
}

/** Build, start and return a MediaRecorder against the current stream.
 *  Optional `durationSec` triggers an automatic stop. The existing UI
 *  bindings (timer, blob preview, download link) all work the same. */
function startRecording({ durationSec = 0, onAutoStop = null } = {}) {
  if (!recState.stream) return null;

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
    if (typeof onAutoStop === "function") onAutoStop({ blob, url });
  };

  recorder.onerror = (e) => {
    showMsg(`Recorder error: ${e.error?.message || "unknown"}`, "bad");
  };

  recState.recorder = recorder;
  recState.startTime = performance.now();
  recorder.start();
  setRecMode("recording");
  $("rec-info").textContent = "";
  startTimer();

  if (durationSec > 0) {
    setTimeout(() => {
      if (recState.recorder && recState.recorder.state !== "inactive") {
        recState.recorder.stop();
      }
      stopTimer();
    }, Math.round(durationSec * 1000));
  }
  return recorder;
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
  $("mic-select").addEventListener("change", (e) => onMicChange(e.target.value));

  // Auto-refresh the mic list when devices change (headphones in/out,
  // Bluetooth pair/unpair, USB audio plug, etc.).
  if (navigator.mediaDevices && navigator.mediaDevices.addEventListener) {
    navigator.mediaDevices.addEventListener("devicechange", onDeviceChange);
  }

  // Free the camera if the page is hidden (saves battery + lets other
  // apps grab the cam). The user re-clicks Enable when they come back.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden" && recState.stream
        && (!recState.recorder || recState.recorder.state === "inactive")) {
      recState.stream.getTracks().forEach((t) => t.stop());
      recState.stream = null;
      stopVuMeter();
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

// ---------- Looper ----------
//
// Marries the metronome and the recorder. Workflow:
//   1. user picks bars + count-in, clicks Arm
//   2. metronome starts (if not already), so the user can hear the click
//   3. we wait for the *next* downbeat, then play `count-in` bars
//   4. at the downbeat after count-in, MediaRecorder.start() fires
//   5. we auto-stop after exactly `bars * beats * 60/bpm` seconds
//
// Timing notes:
//   - The downbeat is computed in AudioContext seconds (sample-accurate
//     against the click). MediaRecorder.start() is fired via setTimeout
//     against that target; setTimeout jitter on Android is 1-4 ms, well
//     below one video frame at 30 fps.
//   - We don't try to align audio and video sample boundaries: the
//     desktop pipeline has its own sync stage and we'll trim there.

const looperState = {
  armed: false,
  cancel: () => {},
};

function loopDurationSec() {
  const bars = Math.max(1, Number($("loop-bars").value) || 1);
  return bars * metro.beatsPerBar * (60 / metro.bpm);
}

function refreshLoopDurationLabel() {
  const dur = loopDurationSec();
  $("loop-duration").textContent = `${dur.toFixed(2)} s`;
}

function syncLoopBars(v) {
  const n = Math.max(1, Math.min(32, Math.round(Number(v) || 1)));
  $("loop-bars").value = n;
  $("loop-bars-num").value = n;
  refreshLoopDurationLabel();
}

function setLoopStatus(text, level = "muted") {
  const el = $("loop-status");
  el.textContent = text;
  el.className = `small ${level}`;
}

function setLoopMode(mode) {
  // 'idle' | 'armed' (waiting for downbeat / counting in / recording loop)
  $("loop-arm-btn").hidden    = mode !== "idle";
  $("loop-cancel-btn").hidden = mode !== "armed";
}

async function onArmLoop() {
  debugLog("Arm clicked. armed=", looperState.armed, "stream=", !!recState.stream);
  try {
    await _onArmLoop();
  } catch (err) {
    debugLog("Arm threw:", err && err.message);
    setLoopStatus(`Arm error: ${err && err.message}`, "bad");
    looperState.armed = false;
    setLoopMode("idle");
  }
}

async function _onArmLoop() {
  if (looperState.armed) return;
  if (!recState.stream) {
    setLoopStatus("Enable the camera first.", "warn");
    return;
  }

  const bars = Math.max(1, Number($("loop-bars").value) || 1);
  const countInBars = Math.max(0, Number($("loop-countin").value) || 0);
  const dur = loopDurationSec();

  // Make sure the metronome is audible — start it if the user forgot.
  if (!metro.isRunning) {
    try { await metro.start(); }
    catch (err) {
      setLoopStatus(`Metronome failed: ${err.message}`, "bad");
      return;
    }
    $("metro-toggle").textContent = "Stop metronome";
    $("metro-toggle").classList.add("active");
  }

  looperState.armed = true;
  setLoopMode("armed");

  // The click that ended the previous bar is past; pick the *next* one.
  const audioCtx = metro._ctx;  // friend access; metronome owns the clock
  const downbeatA = metro.audioTimeOfNextDownbeat();
  const period    = 60 / metro.bpm;
  const downbeatB = downbeatA + countInBars * metro.beatsPerBar * period;

  const msUntilCountIn = Math.max(0, (downbeatA - audioCtx.currentTime) * 1000);
  const msUntilRecord  = Math.max(0, (downbeatB - audioCtx.currentTime) * 1000);

  let cancelled = false;
  let countTimer = 0;
  let recordTimer = 0;

  looperState.cancel = () => {
    cancelled = true;
    clearTimeout(countTimer);
    clearTimeout(recordTimer);
    stopAllScheduledTakes();
    looperState.armed = false;
    setLoopMode("idle");
    setLoopStatus("Cancelled.", "muted");
  };

  // Phase 1: announce the wait until the next downbeat.
  setLoopStatus(
    countInBars > 0
      ? `Count-in starts in ${(msUntilCountIn / 1000).toFixed(2)} s`
      : `Recording starts in ${(msUntilRecord / 1000).toFixed(2)} s`,
    "warn"
  );

  // Phase 2: count-in (purely UI; the metronome is already clicking).
  if (countInBars > 0) {
    countTimer = setTimeout(() => {
      if (cancelled) return;
      setLoopStatus(`Count-in… ${countInBars} bar(s)`, "warn");
    }, msUntilCountIn);
  }

  // Phase 3: actual record.
  recordTimer = setTimeout(() => {
    if (cancelled) return;
    const overdubMsg = takes.list.length > 0
      ? ` (overdub on ${takes.list.length} take${takes.list.length > 1 ? "s" : ""})`
      : "";
    setLoopStatus(`Recording ${bars} bar(s) (${dur.toFixed(2)} s)${overdubMsg}…`, "bad");

    // Schedule monitoring playback of previous takes — sample-accurate
    // against the same downbeat the recorder is about to start on.
    scheduleTakesAt(downbeatB);

    startRecording({
      durationSec: dur,
      onAutoStop: async ({ blob }) => {
        stopAllScheduledTakes();
        looperState.armed = false;
        setLoopMode("idle");
        try {
          const id = await addTake({ blob, mime: recState.mime });
          setLoopStatus(`Take ${id} captured (${dur.toFixed(2)} s).`, "ok");
        } catch (err) {
          debugLog("addTake failed:", err && err.message);
          setLoopStatus(`Take captured but indexing failed: ${err && err.message}`, "warn");
        }
      },
    });
  }, msUntilRecord);
}

function onCancelLoop() {
  looperState.cancel();
}

function wireLooper() {
  const onBars = (raw) => syncLoopBars(raw);
  $("loop-bars").addEventListener("input", (e) => onBars(e.target.value));
  $("loop-bars-num").addEventListener("change", (e) => onBars(e.target.value));
  $("loop-countin").addEventListener("change", refreshLoopDurationLabel);

  $("loop-arm-btn").addEventListener("click", onArmLoop);
  $("loop-cancel-btn").addEventListener("click", onCancelLoop);

  // BPM and beats-per-bar live in the metronome card; they affect the
  // computed loop duration so we reflect that here.
  $("metro-bpm").addEventListener("input", refreshLoopDurationLabel);
  $("metro-bpm-num").addEventListener("change", refreshLoopDurationLabel);
  $("metro-beats").addEventListener("change", refreshLoopDurationLabel);

  refreshLoopDurationLabel();
  setLoopMode("idle");
}

// ---------- Takes (overdub library) ----------
//
// Each take is one captured loop. We keep:
//   - the Blob (so the user can download it later)
//   - a fresh object URL for in-page playback
//   - an AudioBuffer decoded once at capture time, used to monitor the
//     take in the headphones during the *next* take's recording
//
// Tempo, beats and bar count are frozen while the list is non-empty:
//   takes share an exact length, so changing the grid would desync
//   anything you've already recorded.
//
// The monitoring graph is:
//   take.audioBuffer -> BufferSourceNode -> takes.monitorGain
//                                        -> AudioContext.destination
// It does NOT feed into the recorder MediaStream, so the previous
// takes don't bleed into the new recording's audio track. The user
// hears them in headphones; the mic captures only their playing.

const takes = {
  list: [],            // [{ id, blob, url, audioBuffer, mime }]
  monitorGain: null,
  scheduledNodes: [],
};

function ensureMonitorGain() {
  if (!metro._ctx) return null;
  if (!takes.monitorGain) {
    takes.monitorGain = metro._ctx.createGain();
    takes.monitorGain.gain.value = Number($("monitor-vol").value);
    takes.monitorGain.connect(metro._ctx.destination);
  }
  return takes.monitorGain;
}

function setMonitorVolume(v) {
  const value = Math.max(0, Math.min(1, Number(v)));
  if (takes.monitorGain) {
    takes.monitorGain.gain.setTargetAtTime(value, metro._ctx.currentTime, 0.01);
  }
}

async function decodeBlobAudio(blob) {
  await metro.ensureAudio();
  const buf = await blob.arrayBuffer();
  // decodeAudioData is callback-based on Safari; the Promise overload
  // works on modern Chrome which is our target. We could shim if iOS
  // becomes a target.
  return await metro._ctx.decodeAudioData(buf);
}

async function addTake({ blob, mime }) {
  let audioBuffer = null;
  try {
    audioBuffer = await decodeBlobAudio(blob);
  } catch (err) {
    debugLog("decodeAudioData failed:", err && err.message);
    setLoopStatus("Could not decode take audio (overdub disabled).", "warn");
  }
  const url = URL.createObjectURL(blob);
  const id  = takes.list.length + 1;
  takes.list.push({ id, blob, url, audioBuffer, mime });
  renderTakes();
  applyTempoLock();
  updateTakeCounter();
  return id;
}

function removeTake(id) {
  const idx = takes.list.findIndex(t => t.id === id);
  if (idx < 0) return;
  URL.revokeObjectURL(takes.list[idx].url);
  takes.list.splice(idx, 1);
  // Renumber so the user sees Take 1..N (gaps are confusing).
  takes.list.forEach((t, i) => { t.id = i + 1; });
  renderTakes();
  applyTempoLock();
  updateTakeCounter();
}

function clearAllTakes() {
  takes.list.forEach(t => URL.revokeObjectURL(t.url));
  takes.list = [];
  stopAllScheduledTakes();
  renderTakes();
  applyTempoLock();
  updateTakeCounter();
}

function scheduleTakesAt(audioStartTime) {
  stopAllScheduledTakes();
  ensureMonitorGain();
  if (!takes.monitorGain) return;
  for (const t of takes.list) {
    if (!t.audioBuffer) continue;
    const src = metro._ctx.createBufferSource();
    src.buffer = t.audioBuffer;
    src.connect(takes.monitorGain);
    src.start(audioStartTime);
    takes.scheduledNodes.push(src);
  }
}

function stopAllScheduledTakes() {
  for (const n of takes.scheduledNodes) {
    try { n.stop(); } catch (_) { /* already done */ }
  }
  takes.scheduledNodes = [];
}

function renderTakes() {
  const card = $("takes-card");
  const list = $("takes-list");
  card.hidden = takes.list.length === 0;
  list.innerHTML = "";
  for (const t of takes.list) {
    const li = document.createElement("li");
    li.className = "take-item";

    const label = document.createElement("span");
    label.className = "take-label";
    label.textContent = `Take ${t.id}`;
    if (!t.audioBuffer) {
      label.textContent += " (no monitor)";
      label.classList.add("warn");
    }
    li.appendChild(label);

    const audio = document.createElement("audio");
    audio.controls = true;
    audio.preload = "metadata";
    audio.src = t.url;
    li.appendChild(audio);

    const dl = document.createElement("a");
    dl.className = "take-btn";
    dl.textContent = "DL";
    dl.href = t.url;
    const ext = (t.mime || "").startsWith("video/mp4") ? "mp4" : "webm";
    dl.download = `mosaic-take-${t.id}.${ext}`;
    li.appendChild(dl);

    const del = document.createElement("button");
    del.className = "take-btn take-del";
    del.textContent = "X";
    del.addEventListener("click", () => removeTake(t.id));
    li.appendChild(del);

    list.appendChild(li);
  }
}

function applyTempoLock() {
  const locked = takes.list.length > 0;
  for (const id of ["metro-bpm", "metro-bpm-num", "metro-beats",
                    "loop-bars", "loop-bars-num"]) {
    $(id).disabled = locked;
  }
}

function updateTakeCounter() {
  $("loop-take-counter").textContent = `Take ${takes.list.length + 1}`;
}

function wireTakes() {
  $("monitor-vol").addEventListener("input", (e) => setMonitorVolume(e.target.value));
  $("takes-clear-btn").addEventListener("click", clearAllTakes);
  $("takes-export-btn").addEventListener("click", exportSession);
  applyTempoLock();
  updateTakeCounter();
}

// ---------- Export ----------
//
// Bundles every take + a session.json descriptor into a single ZIP
// the user can move to their desktop. The desktop pipeline reads
// session.json, knows the takes are already exact-length on the
// downbeat, and skips audio sync entirely.

function buildSessionManifest() {
  const bars       = Math.max(1, Number($("loop-bars").value) || 1);
  const countIn    = Math.max(0, Number($("loop-countin").value) || 0);
  const beatsPerBar = metro.beatsPerBar;
  const bpm        = metro.bpm;
  const loopSec    = bars * beatsPerBar * (60 / bpm);

  const ext = (mime) => (mime || "").startsWith("video/mp4") ? "mp4" : "webm";

  return {
    schema: "mosaicloop.session/1",
    created: new Date().toISOString(),
    app_version: $("app-version").textContent,
    tempo: { bpm, beats_per_bar: beatsPerBar },
    loop: { bars, count_in_bars: countIn, duration_seconds: loopSec },
    takes: takes.list.map((t) => ({
      id: t.id,
      file: `takes/take-${String(t.id).padStart(2, "0")}.${ext(t.mime)}`,
      mime: t.mime || "video/webm",
      bytes: t.blob.size,
    })),
  };
}

async function exportSession() {
  if (takes.list.length === 0) return;
  const btn = $("takes-export-btn");
  btn.disabled = true;
  const original = btn.textContent;
  btn.textContent = "Packing…";

  try {
    const manifest = buildSessionManifest();
    const entries = [
      { name: "session.json",
        blob: new Blob([JSON.stringify(manifest, null, 2)],
                       { type: "application/json" }) },
    ];
    for (const t of takes.list) {
      const ext = (t.mime || "").startsWith("video/mp4") ? "mp4" : "webm";
      entries.push({
        name: `takes/take-${String(t.id).padStart(2, "0")}.${ext}`,
        blob: t.blob,
      });
    }

    const zip = await buildZip(entries);
    const url = URL.createObjectURL(zip);
    const ts  = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    const a   = document.createElement("a");
    a.href = url;
    a.download = `mosaicloop-session-${ts}.zip`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    // Defer revoke so the browser actually starts the download.
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
    debugLog(`Exported ${entries.length} entries (${(zip.size / 1024 / 1024).toFixed(1)} MB)`);
  } catch (err) {
    debugLog("export failed:", err && err.message);
    setLoopStatus(`Export failed: ${err && err.message}`, "bad");
  } finally {
    btn.disabled = false;
    btn.textContent = original;
  }
}

// ---------- Boot ----------

reportEnvironment();
registerServiceWorker();
wireInstallPrompt();
wireRecorder();
wireMetronome();
wireLooper();
wireTakes();
setRecMode("idle");
