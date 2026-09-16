/* GreenField Service Worker — PWA offline support (v2) */
const CACHE = 'greenfield-v2';

// Only cache truly public, always-accessible assets on install.
// Protected pages (/dashboard, /farms, etc.) are NOT pre-cached here —
// caching them would risk storing a "please log in" redirect instead
// of the real page. They're cached opportunistically as the user visits
// them while logged in (see the fetch handler below).
const CORE_ASSETS = [
  '/',
  '/login',
  '/register',
  '/static/css/style.css',
  '/static/js/app.js',
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

/* Install: cache the core public shell */
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE)
      .then(c => c.addAll(CORE_ASSETS))
      .catch(err => console.warn('[SW] Precache failed:', err))
  );
  self.skipWaiting();
});

/* Activate: remove any old cache versions */
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

/* Fetch strategy:
   - Navigations (HTML pages) and API calls: network-first, so logged-in
     users always see fresh data when online; falls back to cache offline.
   - Never cache a redirected or non-OK response — this is what previously
     risked caching a login-redirect in place of a protected page. */
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;

  // Don't try to cache cross-origin API calls like the weather/map providers
  const url = new URL(e.request.url);
  const isSameOrigin = url.origin === self.location.origin;

  e.respondWith(
    fetch(e.request)
      .then(res => {
        if (isSameOrigin && res.ok && !res.redirected) {
          const clone = res.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
        }
        return res;
      })
      .catch(() => caches.match(e.request).then(cached => {
        if (cached) return cached;
        // Offline fallback for full-page navigations with nothing cached
        if (e.request.mode === 'navigate') {
          return caches.match('/login');
        }
        return new Response('', { status: 503, statusText: 'Offline' });
      }))
  );
});
