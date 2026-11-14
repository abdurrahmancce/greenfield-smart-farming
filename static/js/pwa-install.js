/* GreenField — "Install app" prompt, shared by every page (landing, login, register, app pages).
 * - Shows a small card until the app is installed; hides itself once installed / when running as the installed app.
 * - Chrome/Edge/Android: uses the browser's real install dialog. iPhone/iPad Safari: shows "Add to Home Screen" steps.
 */
(function () {
  if (window.__gfInstallInit) return; window.__gfInstallInit = true;

  var BN = document.documentElement.lang === 'bn' || /(?:^|;\s*)gf_lang=bn/.test(document.cookie);
  var T = function (en, bn) { return BN ? bn : en; };
  var store = {
    get: function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) {} },
    del: function (k) { try { localStorage.removeItem(k); } catch (e) {} }
  };
  var isStandalone = function () {
    return ['standalone', 'fullscreen', 'minimal-ui', 'window-controls-overlay'].some(function (m) {
      return window.matchMedia('(display-mode: ' + m + ')').matches;
    }) || navigator.standalone === true;
  };

  // Make sure the service worker is registered on every page (needed for the browser to offer installation).
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(function () {});
    });
  }

  if (isStandalone()) { store.set('gf_installed', '1'); return; }          // already running as the app

  var isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent) ||
              (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  var deferred = null, card = null, modal = null;

  var css = document.createElement('style');
  css.textContent =
    '#gfInstall{position:fixed;right:18px;bottom:18px;z-index:1500;display:flex;align-items:center;gap:12px;' +
    'max-width:370px;padding:10px 12px 10px 10px;border-radius:18px;color:#fff;font-family:Poppins,Inter,"Hind Siliguri",system-ui,sans-serif;' +
    'background:linear-gradient(135deg,#0f3d14 0%,#1b5e20 55%,#2e7d32 100%);border:1px solid rgba(255,255,255,.16);' +
    'box-shadow:0 14px 40px rgba(0,0,0,.35),0 2px 8px rgba(0,0,0,.2);animation:gfInUp .45s cubic-bezier(.2,.8,.2,1) both}' +
    '#gfInstall img{width:42px;height:42px;border-radius:11px;flex:none;background:#fff;padding:3px;box-shadow:0 2px 8px rgba(0,0,0,.25)}' +
    '#gfInstall .gi-t{min-width:0;line-height:1.25}' +
    '#gfInstall .gi-t b{display:block;font-size:13.5px;font-weight:700;letter-spacing:-.1px}' +
    '#gfInstall .gi-t span{display:block;font-size:11.5px;opacity:.78;font-weight:400;margin-top:1px}' +
    '#gfInstall button.gi-go{flex:none;display:inline-flex;align-items:center;gap:7px;border:0;cursor:pointer;font:inherit;font-size:13px;font-weight:700;' +
    'color:#1b5e20;background:#fff;padding:9px 15px;border-radius:12px;transition:transform .15s,box-shadow .15s;box-shadow:0 2px 6px rgba(0,0,0,.2)}' +
    '#gfInstall button.gi-go:hover{transform:translateY(-1px);box-shadow:0 5px 14px rgba(0,0,0,.28)}' +
    '#gfInstall button.gi-go:focus-visible{outline:3px solid #a5d6a7;outline-offset:2px}' +
    '#gfInstall svg{width:15px;height:15px}' +
    '@keyframes gfInUp{from{opacity:0;transform:translateY(18px)}to{opacity:1;transform:none}}' +
    '@media(max-width:600px){#gfInstall{left:12px;right:12px;bottom:calc(12px + env(safe-area-inset-bottom,0px));max-width:none}}' +
    '@media(max-width:600px){body.gf-install-pad{padding-bottom:104px!important}}' +
    '@media print{#gfInstall,#gfInstallHelp{display:none!important}}' +
    '@media(prefers-reduced-motion:reduce){#gfInstall{animation:none}}' +
    '#gfInstallHelp{position:fixed;inset:0;z-index:2000;display:flex;align-items:flex-end;justify-content:center;background:rgba(0,0,0,.55);padding:16px;' +
    'font-family:Poppins,Inter,"Hind Siliguri",system-ui,sans-serif}' +
    '#gfInstallHelp .gh{width:100%;max-width:420px;background:#fff;color:#1b3a1e;border-radius:20px;padding:22px 22px 18px;box-shadow:0 20px 60px rgba(0,0,0,.4)}' +
    '#gfInstallHelp h3{margin:0 0 4px;font-size:17px;font-weight:800;color:#1b5e20}' +
    '#gfInstallHelp p{margin:0 0 12px;font-size:12.5px;color:#5f7a62}' +
    '#gfInstallHelp ol{margin:0 0 16px;padding-left:20px;font-size:13.5px;line-height:1.8}' +
    '#gfInstallHelp button{width:100%;border:0;border-radius:12px;padding:11px;font:inherit;font-weight:700;font-size:14px;color:#fff;background:#2e7d32;cursor:pointer}';
  document.head.appendChild(css);

  var ICON_DL = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
                '<path d="M12 3v12m0 0l-4.5-4.5M12 15l4.5-4.5M4 20h16"/></svg>';

  function helpModal() {
    if (modal) return;
    var steps = isIOS
      ? [T('Tap the <b>Share</b> button (square with an arrow) in Safari', 'Safari-তে <b>Share</b> বাটনে (তীরসহ বর্গ) চাপ দিন'),
         T('Scroll and tap <b>Add to Home Screen</b>', 'নিচে স্ক্রল করে <b>Add to Home Screen</b> চাপ দিন'),
         T('Tap <b>Add</b> — GreenField appears on your home screen', '<b>Add</b> চাপ দিন — GreenField হোম স্ক্রিনে চলে আসবে')]
      : [T('Open your browser menu (<b>⋮</b> or <b>⋯</b>)', 'ব্রাউজারের মেনু (<b>⋮</b> বা <b>⋯</b>) খুলুন'),
         T('Tap <b>Install app</b> or <b>Add to Home screen</b>', '<b>Install app</b> বা <b>Add to Home screen</b> চাপ দিন'),
         T('Confirm — GreenField opens like a normal app', 'নিশ্চিত করুন — GreenField সাধারণ অ্যাপের মতো খুলবে')];
    modal = document.createElement('div'); modal.id = 'gfInstallHelp';
    modal.setAttribute('role', 'dialog'); modal.setAttribute('aria-modal', 'true');
    modal.innerHTML = '<div class="gh"><h3>' + T('Install GreenField', 'GreenField ইনস্টল করুন') + '</h3><p>' +
      T('Quick steps to add the app to your device:', 'আপনার ডিভাইসে অ্যাপটি যোগ করার ধাপ:') + '</p><ol>' +
      steps.map(function (s) { return '<li>' + s + '</li>'; }).join('') + '</ol><button type="button">' + T('Got it', 'বুঝেছি') + '</button></div>';
    var close = function () { if (modal) { modal.remove(); modal = null; document.removeEventListener('keydown', esc); } };
    var esc = function (e) { if (e.key === 'Escape') close(); };
    modal.addEventListener('click', function (e) { if (e.target === modal || e.target.tagName === 'BUTTON') close(); });
    document.addEventListener('keydown', esc);
    document.body.appendChild(modal);
  }

  function onInstallClick() {
    if (!deferred) { helpModal(); return; }
    var p = deferred; deferred = null;
    p.prompt();
    p.userChoice.then(function (c) {
      if (c && c.outcome === 'accepted') { store.set('gf_installed', '1'); hide(); }
    }).catch(function () {});
  }

  function show() {
    if (card || !document.body) return;
    card = document.createElement('div'); card.id = 'gfInstall'; card.setAttribute('role', 'region');
    card.setAttribute('aria-label', T('Install GreenField app', 'GreenField অ্যাপ ইনস্টল'));
    card.innerHTML = '<img src="/static/icons/icon-96.png" alt="" width="42" height="42">' +
      '<div class="gi-t"><b>' + T('Install GreenField', 'GreenField ইনস্টল করুন') + '</b><span>' +
      T('Faster access · works offline', 'দ্রুত চালু · অফলাইনেও কাজ করে') + '</span></div>' +
      '<button type="button" class="gi-go">' + ICON_DL + '<span>' + T('Install', 'ইনস্টল') + '</span></button>';
    card.querySelector('button').addEventListener('click', onInstallClick);
    document.body.appendChild(card); document.body.classList.add('gf-install-pad');
  }
  function hide() { if (card) { card.remove(); card = null; } if (document.body) document.body.classList.remove('gf-install-pad'); if (modal) { modal.remove(); modal = null; } }
  function whenReady(fn) { if (document.body) fn(); else document.addEventListener('DOMContentLoaded', fn); }

  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault(); deferred = e; store.del('gf_installed');
    whenReady(show);
  });
  window.addEventListener('appinstalled', function () { store.set('gf_installed', '1'); deferred = null; hide(); });
  window.matchMedia('(display-mode: standalone)').addEventListener &&
    window.matchMedia('(display-mode: standalone)').addEventListener('change', function (e) { if (e.matches) hide(); });

  // Chrome can tell us the app is already installed even when this page is open in a normal browser tab.
  if (navigator.getInstalledRelatedApps) {
    navigator.getInstalledRelatedApps().then(function (apps) {
      if (apps && apps.length) { store.set('gf_installed', '1'); hide(); }
    }).catch(function () {});
  }

  // iPhone / iPad Safari never fires the install event, so show the card with the manual steps.
  if (isIOS) whenReady(show);
})();
