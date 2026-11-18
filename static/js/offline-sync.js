/* GreenField offline entries.
 * Expense and irrigation forms are saved on the phone when there is no network (or the server
 * does not answer), and sent to /api/offline/sync as soon as the connection is back.
 * - Each entry has a random id (cid): a retry can never create a duplicate on the server.
 * - Entries are tagged with the signed-in user; they are only ever sent for that same user.
 * - Nothing leaves the device except to this site's own /api/offline/sync.
 */
(function () {
  'use strict';
  var KEY = 'gf_offline_q', MAX = 200;
  var uid = (document.querySelector('meta[name="gf-uid"]') || {}).content || '';
  var lang = (document.querySelector('meta[name="gf-lang"]') || {}).content === 'bn' ? 'bn' : 'en';
  if (!uid) return;                                   // not signed in: nothing to do
  var T = {
    en: { saved: 'No connection: saved on this phone. It will be sent automatically.',
          waiting: function (n) { return '📴 ' + n + ' entr' + (n === 1 ? 'y' : 'ies') + ' waiting to sync'; },
          synced: function (n) { return '✅ ' + n + ' offline entr' + (n === 1 ? 'y' : 'ies') + ' synced'; },
          bad: function (n) { return '⚠️ ' + n + ' offline entr' + (n === 1 ? 'y was' : 'ies were') + ' rejected (check farm/date/amount)'; },
          full: 'Too many unsent entries on this phone. Please connect to the internet first.' },
    bn: { saved: 'নেটওয়ার্ক নেই: ফোনে সংরক্ষিত হয়েছে। ইন্টারনেট এলে নিজে থেকে পাঠানো হবে।',
          waiting: function (n) { return '📴 ' + n + 'টি এন্ট্রি সিঙ্কের অপেক্ষায়'; },
          synced: function (n) { return '✅ ' + n + 'টি অফলাইন এন্ট্রি সিঙ্ক হয়েছে'; },
          bad: function (n) { return '⚠️ ' + n + 'টি অফলাইন এন্ট্রি গ্রহণ হয়নি (খামার/তারিখ/পরিমাণ দেখুন)'; },
          full: 'ফোনে অনেক অপ্রেরিত এন্ট্রি জমেছে। আগে ইন্টারনেটে যুক্ত হন।' }
  }[lang];

  function load() { try { var q = JSON.parse(localStorage.getItem(KEY) || '[]'); return Array.isArray(q) ? q : []; } catch (e) { return []; } }
  function save(q) { try { localStorage.setItem(KEY, JSON.stringify(q)); return true; } catch (e) { return false; } }
  function mine() { return load().filter(function (e) { return e.uid === uid; }); }
  function newId() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    var a = new Uint8Array(16); (window.crypto || {}).getRandomValues ? crypto.getRandomValues(a) : a.forEach(function (_, i) { a[i] = Math.random() * 256; });
    return Array.prototype.map.call(a, function (b) { return ('0' + b.toString(16)).slice(-2); }).join('');
  }

  var bar;
  function toast(msg, ms) {
    var t = document.createElement('div');
    t.textContent = msg; t.setAttribute('role', 'status');
    t.style.cssText = 'position:fixed;left:50%;bottom:76px;transform:translateX(-50%);background:#1B5E20;color:#fff;padding:10px 16px;border-radius:10px;z-index:9999;max-width:90vw;font-size:14px;box-shadow:0 4px 14px rgba(0,0,0,.3)';
    document.body.appendChild(t); setTimeout(function () { t.remove(); }, ms || 4000);
  }
  function paint() {
    var n = mine().length;
    if (!n) { if (bar) { bar.remove(); bar = null; } return; }
    if (!bar) {
      bar = document.createElement('div'); bar.setAttribute('role', 'status');
      bar.style.cssText = 'position:fixed;left:12px;bottom:12px;background:#E65100;color:#fff;padding:8px 14px;border-radius:999px;z-index:9998;font-size:13px;box-shadow:0 2px 10px rgba(0,0,0,.3)';
      document.body.appendChild(bar);
    }
    bar.textContent = T.waiting(n);
  }

  function formData(form) {
    var o = {}; new FormData(form).forEach(function (v, k) { if (typeof v === 'string') o[k] = v; }); return o;
  }
  function kindOf(form) {
    var a = form.getAttribute('action') || '';
    if (/\/expenses\/add$/.test(a)) return 'expense';
    if (/\/irrigation\/add$/.test(a)) return 'irrigation';
    return null;
  }
  function enqueue(kind, f, cid) {
    var q = load();
    if (q.length >= MAX) { toast(T.full, 6000); return false; }
    q.push({ cid: cid, uid: uid, kind: kind, f: f, ts: Date.now() });
    if (!save(q)) { toast(T.full, 6000); return false; }
    paint(); toast(T.saved, 5000); return true;
  }

  document.addEventListener('submit', function (ev) {
    var form = ev.target, kind = kindOf(form);
    if (!kind || ev.defaultPrevented || !form.checkValidity()) return;
    ev.preventDefault();
    var f = formData(form), cid = newId(); f.cid = cid;
    var btn = form.querySelector('[type=submit]'); if (btn) btn.disabled = true;
    var done = function () { window.location.href = window.location.pathname + window.location.search; };
    var queueIt = function () { enqueue(kind, f, cid); if (btn) btn.disabled = false; form.reset(); };
    if (navigator.onLine === false) return queueIt();
    var ctl = ('AbortController' in window) ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctl) ctl.abort(); }, 25000);
    fetch(form.getAttribute('action'), { method: 'POST', body: new URLSearchParams(f), credentials: 'same-origin',
                                         headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-GF-Fetch': '1' },
                                         signal: ctl ? ctl.signal : undefined })
      .then(function (r) {
        clearTimeout(timer);
        if (r.status === 401) { enqueue(kind, f, cid); window.location.href = '/login'; return; }   // session ended: keep the entry
        if (r.status >= 500 || r.status === 429) return queueIt();                                     // server trouble: keep it, retry later
        return r.json().then(function (j) {
          if (r.ok) { try { sessionStorage.setItem('gf_flash', j.msg || 'Saved'); } catch (e) {} done(); }
          else { toast('⚠️ ' + (j.msg || 'Not saved'), 6000); if (btn) btn.disabled = false; }      // real validation error
        }, queueIt);
      })
      .catch(function () { clearTimeout(timer); queueIt(); });   // same cid => safe even if the server did get it
  }, true);

  try { var fl = sessionStorage.getItem('gf_flash'); if (fl) { sessionStorage.removeItem('gf_flash'); toast(fl, 3500); } } catch (e) {}

  var busy = false;
  function sync() {
    var q = mine();
    if (busy || !q.length || navigator.onLine === false) return;
    busy = true;
    var batch = q.slice(0, 50);
    fetch('/api/offline/sync', { method: 'POST', credentials: 'same-origin',
                                 headers: { 'Content-Type': 'application/json' },
                                 body: JSON.stringify({ entries: batch.map(function (e) { return { cid: e.cid, kind: e.kind, f: e.f }; }) }) })
      .then(function (r) {
        var ct = r.headers.get('content-type') || '';
        if (!r.ok || ct.indexOf('json') < 0) throw new Error('not now');       // offline page / login page / error: keep entries
        return r.json();
      })
      .then(function (res) {
        var gone = {}; (res.done || []).forEach(function (c) { gone[c] = 1; });
        (res.rejected || []).forEach(function (x) { gone[x.cid] = 1; });
        save(load().filter(function (e) { return !(e.uid === uid && gone[e.cid]); }));
        paint();
        if ((res.done || []).length) toast(T.synced(res.done.length), 5000);
        if ((res.rejected || []).length) toast(T.bad(res.rejected.length), 8000);
        if ((res.done || []).length && /\/(expenses|irrigation)$/.test(location.pathname)) setTimeout(function () { location.reload(); }, 1200);
      })
      .catch(function () { /* try again later */ })
      .then(function () { busy = false; });
  }

  paint(); sync();
  window.addEventListener('online', function () { setTimeout(sync, 800); });
  document.addEventListener('visibilitychange', function () { if (!document.hidden) sync(); });
  setInterval(sync, 60000);
})();
