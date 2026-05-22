/* GuitarLooper service worker — shell cache only (M0).
 * We cache the static shell so the app loads when installed. Future
 * milestones add nothing here; recordings stay in IndexedDB / OPFS
 * and don't go through the SW.
 */
const VERSION = "v0.0.3-m1b";
const SHELL_CACHE = `looper-shell-${VERSION}`;
const SHELL_URLS = [
  "./",
  "./index.html",
  "./styles.css",
  "./main.js",
  "./manifest.webmanifest",
  "./icons/icon.svg",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((c) => c.addAll(SHELL_URLS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== SHELL_CACHE).map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  // Cache-first for the shell, network-first for everything else.
  const url = new URL(request.url);
  if (url.origin === self.location.origin && SHELL_URLS.some(
        (u) => url.pathname.endsWith(u.replace("./", "")))) {
    event.respondWith(
      caches.match(request).then((hit) => hit || fetch(request))
    );
  }
});
