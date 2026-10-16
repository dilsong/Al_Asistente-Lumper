importScripts("/static/version.js");

const APP_VERSION = self.AL_APP_VERSION || "dev";
const CACHE_BUST = `AL-${APP_VERSION}`;
const CACHE_NAME = `al-asistente-v${APP_VERSION}`;
const PRECACHE = [
  "/",
  "/static/index.html",
  "/static/version.js",
  `/static/styles.css?v=${CACHE_BUST}`,
  `/static/config.js?v=${CACHE_BUST}`,
  `/static/app.js?v=${CACHE_BUST}`,
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
    url.pathname.endsWith("/sw.js") ||
    url.pathname.endsWith("/version.js");
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
