const CACHE_NAME = "yantos-warehouse-static-v1";
const STATIC_ASSET_PREFIX = "/static/";
const CACHEABLE_STATIC_EXTENSIONS = [".css", ".js", ".svg", ".webmanifest"];
const STOCK_OPERATION_PREFIXES = [
  "/uk/stock/",
  "/en/stock/",
  "/uk/stockbalances/",
  "/en/stockbalances/",
  "/uk/movements/",
  "/en/movements/"
];

self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => Promise.all(
      cacheNames
        .filter((cacheName) => cacheName !== CACHE_NAME)
        .map((cacheName) => caches.delete(cacheName))
    )).then(() => self.clients.claim())
  );
});

function isStockOperationPage(url) {
  return STOCK_OPERATION_PREFIXES.some((prefix) => url.pathname.startsWith(prefix));
}

function isCacheableStaticRequest(request) {
  if (request.method !== "GET") {
    return false;
  }

  const url = new URL(request.url);

  if (url.origin !== self.location.origin) {
    return false;
  }

  if (isStockOperationPage(url)) {
    return false;
  }

  if (!url.pathname.startsWith(STATIC_ASSET_PREFIX)) {
    return false;
  }

  return CACHEABLE_STATIC_EXTENSIONS.some((extension) => url.pathname.endsWith(extension));
}

self.addEventListener("fetch", (event) => {
  if (!isCacheableStaticRequest(event.request)) {
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cachedResponse) => {
      if (cachedResponse) {
        return cachedResponse;
      }

      return fetch(event.request).then((networkResponse) => {
        if (networkResponse && networkResponse.ok) {
          const responseToCache = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, responseToCache));
        }
        return networkResponse;
      });
    })
  );
});
