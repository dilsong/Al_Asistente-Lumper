const APP_VERSION = "1.0.1";
const CACHE_NAME = `al-cache-v${APP_VERSION}`;
const PRECACHE = [
  "/",
  "/static/index.html",
  `/static/styles.css?v=${APP_VERSION}`,
  `/static/config.js?v=${APP_VERSION}`,
  `/static/app.js?v=${APP_VERSION}`,
  "/static/manifest.json",
  "/static/icon.svg",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)));
      await self.clients.claim();
    })()
  );
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") self.skipWaiting();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.pathname.startsWith("/api/")) {
    return;
  }
  const revalidarSiempre =
    event.request.mode === "navigate" ||
    url.pathname === "/" ||
    url.pathname.endsWith(".html") ||
    url.pathname.endsWith("/sw.js");
  event.respondWith(
    fetch(event.request, revalidarSiempre ? { cache: "no-store" } : undefined)
      .then((response) => {
        if (!revalidarSiempre && response && response.ok) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
        }
        return response;
      })
      .catch(() => caches.match(event.request).then((hit) => hit || caches.match("/")))
  );
});
