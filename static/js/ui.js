/* GreenField - CSP-safe event wiring.
   Templates used inline onclick="..." handlers; a strict script-src forbids those, so they
   are written as data attributes and dispatched here:
     data-click="fn" data-args='["a",1,"$el"]'   -> window.fn("a", 1, element)   (also data-input / data-change)
     data-prevent / data-stop                     -> preventDefault / stopPropagation first
     data-confirm="Message"  (on a <form>)        -> ask before submitting
     data-hover-in / data-hover-out="prop:value;prop:value"
   Only named global functions are called - no eval, no string execution. */
(function () {
  'use strict';
  function parseArgs(el) {
    var raw = el.getAttribute('data-args');
    var out = [];
    if (raw) { try { out = JSON.parse(raw); } catch (e) { out = []; } }
    return out.map(function (a) { return a === '$el' ? el : (a === '$value' ? el.value : a); });
  }
  function run(kind, ev) {
    var el = ev.target && ev.target.closest ? ev.target.closest('[data-' + kind + ']') : null;
    if (!el) return;
    var name = el.getAttribute('data-' + kind);
    var fn = window[name];
    if (typeof fn !== 'function') return;
    if (el.hasAttribute('data-prevent')) ev.preventDefault();
    if (el.hasAttribute('data-stop')) ev.stopPropagation();
    fn.apply(el, parseArgs(el));
  }
  ['click', 'input', 'change'].forEach(function (kind) {
    document.addEventListener(kind, function (ev) { run(kind, ev); }, true);
  });
  document.addEventListener('submit', function (ev) {
    var f = ev.target;
    if (f && f.hasAttribute && f.hasAttribute('data-confirm') && !window.confirm(f.getAttribute('data-confirm'))) {
      ev.preventDefault();
    }
  }, true);
  function hover(attr) {
    return function (ev) {
      var el = ev.target && ev.target.closest ? ev.target.closest('[' + attr + ']') : null;
      if (!el || (ev.relatedTarget && el.contains(ev.relatedTarget))) return;
      el.getAttribute(attr).split(';').forEach(function (pair) {
        var i = pair.indexOf(':');
        if (i > 0) el.style.setProperty(pair.slice(0, i).trim(), pair.slice(i + 1).trim());
      });
    };
  }
  document.addEventListener('mouseover', hover('data-hover-in'));
  document.addEventListener('mouseout', hover('data-hover-out'));

  /* small helpers used by the data-click attributes */
  window.gfReload = function () { location.reload(); };
  window.gfPrint = function () { window.print(); };
  window.gfClickId = function (id) { var e = document.getElementById(id); if (e) e.click(); };
  window.gfSetBg = function (id, color) { var e = document.getElementById(id); if (e) e.style.background = color; };
  window.gfCopy = function (id) {
    var e = document.getElementById(id); if (!e) return;
    var t = e.textContent.trim();
    if (navigator.clipboard && navigator.clipboard.writeText) { navigator.clipboard.writeText(t).catch(function () {}); return; }
    var r = document.createRange(); r.selectNodeContents(e);
    var sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
    try { document.execCommand('copy'); } catch (x) {}
  };
  window.gfConfirmSubmit = function (msg, formId) {
    if (window.confirm(msg)) { var f = document.getElementById(formId); if (f) f.submit(); }
  };
})();
