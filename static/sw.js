/* Static assets and a public offline shell only. Never cache private HTML. */
const VERSION = 'v5-security';
const STATIC = 'gf-static-' + VERSION;
const PAGES = 'gf-pages-' + VERSION;
const SLOW_MS = 3500;               // after this, prefer the saved copy of a page
const bc = ('BroadcastChannel' in self) ? new BroadcastChannel('gf-sw') : null;

const PRECACHE = [
  '/offline',
  '/static/css/style.css',
  '/static/js/app.js',
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(STATIC)
      .then(c => Promise.all(PRECACHE.map(u => c.add(u).catch(() => null))))
  );
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== STATIC).map(k => caches.delete(k))))
      .then(() => { if ('indexedDB' in self) indexedDB.deleteDatabase('gf-disease'); })
      .then(() => self.clients.claim())
  );
});

const cacheable = res => res && res.ok && res.type !== 'opaqueredirect' && !res.redirected;

async function handleNavigation(req) {
  return fetch(req).catch(async () => (await caches.match('/offline')) || new Response('Offline', {status: 503}));
}

async function staleWhileRevalidate(req) {
  const cache = await caches.open(STATIC);
  const cached = await cache.match(req);
  const refresh = fetch(req).then(res => {
    if (res && (res.ok || res.type === 'opaque')) cache.put(req, res.clone());
    return res;
  }).catch(() => null);
  return cached || (await refresh) || new Response('', { status: 504, statusText: 'Offline' });
}

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  const same = url.origin === self.location.origin;

  if (req.mode === 'navigate') {
    e.respondWith(handleNavigation(req));
    return;
  }
  if (same) {
    if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/avatar/') ||
        url.pathname === '/healthz' || url.pathname === '/sw.js') return;     // always live
    if (url.pathname.startsWith('/static/')) { e.respondWith(staleWhileRevalidate(req)); return; }
    return;
  }
  // Cross-origin libraries, fonts, map tiles-free: cache CSS/JS/fonts only
  if (['style', 'script', 'font'].includes(req.destination)) {
    e.respondWith(staleWhileRevalidate(req));
  }
});


// ── Push alerts (rain / storm / disease risk) ─────────────────────
self.addEventListener('push', e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = { title: 'GreenField', body: e.data ? e.data.text() : '' }; }
  e.waitUntil(self.registration.showNotification(d.title || 'GreenField', {
    body: d.body || '', tag: d.tag || 'gf-alert', icon: '/static/icons/icon-192.png',
    badge: '/static/icons/icon-192.png', data: { url: d.url || '/dashboard' }
  }));
});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const target = new URL((e.notification.data && e.notification.data.url) || '/dashboard', self.location.origin);
  const url = target.origin === self.location.origin ? target.href : '/dashboard';
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
    for (const c of list) { if ('focus' in c) { c.navigate(url); return c.focus(); } }
    return self.clients.openWindow(url);
  }));
});
