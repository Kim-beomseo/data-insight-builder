// Service Worker for AI Data Insight Builder PWA
const CACHE_NAME = 'data-insight-pwa-v1';
const PRECACHE_ASSETS = [
  '/',
  '/static/style.css',
  '/static/app.js',
  '/static/manifest.json',
  '/static/icons/icon.svg',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png'
];

// Install: Precache shell assets
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(PRECACHE_ASSETS).catch((err) => {
        console.warn('[SW] Precache asset fetch warning:', err);
      });
    }).then(() => self.skipWaiting())
  );
});

// Activate: Clean up old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((name) => {
          if (name !== CACHE_NAME) {
            return caches.delete(name);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch: Network-first with cache fallback for static, pass-through for APIs
self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Bypass cache for POST/PUT/DELETE, API calls, and health check
  if (
    req.method !== 'GET' ||
    url.pathname.startsWith('/inspect') ||
    url.pathname.startsWith('/query') ||
    url.pathname.startsWith('/suggest') ||
    url.pathname.startsWith('/run') ||
    url.pathname.startsWith('/explain') ||
    url.pathname.startsWith('/followup') ||
    url.pathname.startsWith('/api/') ||
    url.pathname.startsWith('/health')
  ) {
    return; // Standard network fetch
  }

  // Network-first strategy for navigation and static assets
  event.respondWith(
    fetch(req)
      .then((networkRes) => {
        if (networkRes && networkRes.status === 200) {
          const resClone = networkRes.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(req, resClone);
          });
        }
        return networkRes;
      })
      .catch(() => {
        return caches.match(req).then((cachedRes) => {
          if (cachedRes) return cachedRes;
          if (req.mode === 'navigate') {
            return caches.match('/');
          }
        });
      })
  );
});
