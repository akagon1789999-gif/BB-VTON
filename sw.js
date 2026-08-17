const CACHE = 'apparel-tryon-v3';
const APP_SHELL = [
  './index.html',
  './support.js',
  './image-slot.js',
  './manifest.webmanifest',
  './icons/icon-192.png',
  './icons/icon-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(APP_SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

// Network-first for the app document (so edits show up promptly), cache-first
// for everything else same-origin (images, scripts) with a background refresh.
self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== self.location.origin) return;

  // Never cache API calls or a customer's generated images. The cache-first
  // branch below would otherwise replay a stale "processing" status forever
  // while a try-on or a Fabric Studio design is being polled, and would serve
  // one person's saved result to the next visitor on a shared device.
  const path = new URL(req.url).pathname;
  if (path.startsWith('/api/') || path.startsWith('/media/generations/')) return;

  // Video is served with Range requests; the Cache API cannot store a 206, and
  // replaying a whole file to a range request breaks seeking. Let it stream.
  if (req.destination === 'video' || /\.(mp4|webm|mov)$/i.test(path)) return;

  if (req.mode === 'navigate' || req.destination === 'document') {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((cache) => cache.put(req, copy));
          return res;
        })
        .catch(() => caches.match(req).then((cached) => cached || caches.match('./index.html')))
    );
    return;
  }

  event.respondWith(
    caches.match(req).then((cached) => {
      const fetchPromise = fetch(req)
        .then((res) => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(CACHE).then((cache) => cache.put(req, copy));
          }
          return res;
        })
        .catch(() => cached);
      return cached || fetchPromise;
    })
  );
});
