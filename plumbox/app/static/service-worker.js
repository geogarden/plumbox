const CACHE = "plumbox-gptsol-static-v68";
// Adresy z parametrem wersji: przegladarka nie moze podac starego pliku
// z cache HTTP po aktualizacji, bo URL sie zmienia razem z wydaniem.
const ASSET_VERSION = "gptsol-68";
const ASSETS = [
  `assets/styles.css?v=${ASSET_VERSION}`,
  `assets/scheme.css?v=${ASSET_VERSION}`,
  `assets/app.js?v=${ASSET_VERSION}`,
  `assets/boiler_views.js?v=${ASSET_VERSION}`,
  `assets/work_schedule.js?v=${ASSET_VERSION}`,
  "assets/icon.svg",
  "assets/sf11130.jpg",
  "manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET" || !ASSETS.some((asset) => event.request.url.endsWith(asset))) return;
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const copy = response.clone();
        caches.open(CACHE).then((cache) => cache.put(event.request, copy));
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});


