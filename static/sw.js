/* GreenField Service Worker v3
 *
 * Served from /sw.js (site root) so it really controls every page.
 *  - Pages: network first, but if the server is slow (Render free tier waking up)
 *    or offline, the last saved copy of that page is shown instead.
 *  - Static files + CDN fonts/icons/libraries: stale-while-revalidate.
 *  - /offline is pre-cached and used when nothing else is available.
 *  - Saved pages are wiped on logout so the next person never sees them.
 */
const VERSION = 'v3';
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
      .then(keys => Promise.all(keys.filter(k => k !== STATIC && k !== PAGES).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

const cacheable = res => res && res.ok && res.type !== 'opaqueredirect' && !res.redirected;

async function handleNavigation(req) {
  const url = new URL(req.url);

  // Logging out: forget every saved page.
  if (url.pathname === '/logout') {
    await caches.delete(PAGES);
    return fetch(req).catch(() => caches.match('/offline'));
  }

  const pages = await caches.open(PAGES);
  const saved = await pages.match(req);

  const network = fetch(req).then(res => {
    if (cacheable(res) && url.pathname !== '/offline') pages.put(req, res.clone());
    return res;
  });

  if (!saved) {
    // Nothing saved yet: wait for the server; only if it is unreachable show the offline page.
    return network.catch(() => caches.match('/offline'));
  }

  // We have a saved copy: use it if the network fails or is slow.
  return new Promise(resolve => {
    let done = false;
    const finish = r => { if (!done) { done = true; resolve(r); } };
    const timer = setTimeout(() => {
      if (!done) {
        bc && bc.postMessage({ type: 'stale', path: url.pathname });
        finish(saved);
        // keep waiting in the background; tell the page when fresh data is ready
        network.then(res => { if (cacheable(res)) bc && bc.postMessage({ type: 'fresh', path: url.pathname }); })
               .catch(() => {});
      }
    }, SLOW_MS);
    network.then(res => { clearTimeout(timer); finish(res); })
           .catch(() => { clearTimeout(timer); bc && bc.postMessage({ type: 'offline', path: url.pathname }); finish(saved); });
  });
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
