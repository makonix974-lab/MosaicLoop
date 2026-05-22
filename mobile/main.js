// GuitarLooper main entry — M0 shell.
// Reports environment capabilities and handles the install flow.

const $ = (id) => document.getElementById(id);

function setStatus(id, text, level = "") {
  const el = $(id);
  el.textContent = text;
  el.className = level;
}

function reportEnvironment() {
  // HTTPS (or localhost, which is treated as secure by browsers).
  const secure = window.isSecureContext;
  setStatus("s-https", secure ? "secure context" : "INSECURE — getUserMedia will refuse",
            secure ? "ok" : "bad");

  // Service worker support.
  setStatus("s-sw", "serviceWorker" in navigator ? "supported" : "missing",
            "serviceWorker" in navigator ? "ok" : "bad");

  // Display mode (standalone = launched from home screen).
  const standalone = window.matchMedia("(display-mode: standalone)").matches
                  || window.navigator.standalone === true;
  setStatus("s-display", standalone ? "standalone (installed)" : "browser tab",
            standalone ? "ok" : "warn");

  // getUserMedia (camera + mic).
  const gum = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  setStatus("s-gum", gum ? "available" : "missing", gum ? "ok" : "bad");

  // MediaRecorder + a video MIME the device understands.
  const mr = "MediaRecorder" in window;
  if (mr) {
    const candidates = [
      "video/mp4;codecs=avc1,mp4a",
      "video/webm;codecs=vp9,opus",
      "video/webm;codecs=vp8,opus",
      "video/webm",
    ];
    const supported = candidates.find(
      (c) => MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(c));
    setStatus("s-mr", supported ? `supported (${supported})` : "no usable MIME",
              supported ? "ok" : "bad");
  } else {
    setStatus("s-mr", "missing", "bad");
  }

  // AudioContext (Web Audio API, for the click + sync beep).
  const ac = "AudioContext" in window || "webkitAudioContext" in window;
  setStatus("s-ac", ac ? "available" : "missing", ac ? "ok" : "bad");
}

async function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  try {
    await navigator.serviceWorker.register("./sw.js");
  } catch (err) {
    console.error("SW registration failed:", err);
  }
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

  window.addEventListener("appinstalled", () => {
    btn.hidden = true;
  });
}

reportEnvironment();
registerServiceWorker();
wireInstallPrompt();
