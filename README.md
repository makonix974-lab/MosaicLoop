# GuitarLooper — Mobile PWA

Multi-cam looper that records overdub takes on a phone. Runs in the
browser, installs to the home screen, no app store.

## Status

**M0** — shell only (this folder is just a static PWA that reports
device capabilities). No recording, no UI yet.

## Test it locally (Android)

`getUserMedia` requires a secure context (HTTPS) **or** localhost. To
test from your phone on the same Wi-Fi:

```bash
# 1. Get the host's LAN IP (e.g. 192.168.1.42)
ipconfig          # Windows
ifconfig | grep inet   # macOS/Linux

# 2. Serve the mobile/ folder. From the repo root:
python -m http.server 8000 --directory mobile

# 3. On the phone (same Wi-Fi), open:
#    http://192.168.1.42:8000
```

Important: `http://<lan-ip>` is **not** a secure context, so
`getUserMedia` will refuse there. For the camera/mic milestones (M1+)
we'll either:

- use `adb reverse tcp:8000 tcp:8000` to expose `http://localhost:8000`
  on the phone (treated as secure), or
- ship the static files to GitHub Pages (HTTPS gratis).

For M0 (shell + manifest only) plain HTTP on the LAN is fine — the
status panel will simply mark `s-https` as insecure.

## File layout

```
mobile/
├── index.html              entry, links manifest + main.js
├── main.js                 capability checks + install prompt
├── manifest.webmanifest    PWA metadata (name, icons, standalone)
├── sw.js                   service worker (shell cache)
├── styles.css              minimal dark UI
└── icons/icon.svg          app icon (PNGs added later)
```

## Roadmap

| # | Milestone | Status |
|---|---|---|
| M0 | Shell PWA (manifest, SW, install prompt) | 🚧 |
| M1 | Camera + mic preview, MediaRecorder | — |
| M2 | Web Audio metronome | — |
| M3 | Backing track upload + BPM detection | — |
| M4 | Looper engine (BPM × bars = exact loop length) | — |
| M5 | Overdub: take N monitors all previous takes | — |
| M6 | Export takes + sync sidecar JSON for desktop pipeline | — |
