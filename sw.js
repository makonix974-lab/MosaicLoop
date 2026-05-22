/* MosaicLoop service worker.
 *
 * Strategy:
 *   network-first for the shell (HTML/JS/CSS/manifest), with a cache
 *   fallback for offline. This is the right call while we're iterating —
 *   cache-first means every code change spends a day fighting the SW.
 *   We can switch back to cache-first once the app stabilises.
 */
const VERSION = "v0.0.5-m2";
const SHELL_CACHE = `looper-shell-${VERSION}`;
const SHELL_URLS = [
  "./",
  "./index.html",
  "./styles.css",
  "./main.js",
  "./metronome.js",
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
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Network-first: try fresh, fall back to cache when offline.
  event.respondWith((async () => {
    try {
      const fresh = await fetch(request);
      // Update the cache for offline use, best-effort.
      try {
        const cache = await caches.open(SHELL_CACHE);
        cache.put(request, fresh.clone());
      } catch (_) { /* ignore quota etc. */ }
      return fresh;
    } catch (_) {
      const hit = await caches.match(request);
      if (hit) return hit;
      throw _;
    }
  })());
});
