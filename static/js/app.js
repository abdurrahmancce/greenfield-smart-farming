/**
 * GreenField Smart Farming — app.js FINAL
 * ✅ Add/Edit/Delete Farm  — modal + fetch API + hidden form submit
 * ✅ Add/Edit/Delete Note  — modal + fetch API + hidden form submit
 * ✅ Fertilizer calculator — POST /api/fertilizer
 * ✅ Chart.js bar, line, doughnut
 * ✅ Progress bar animations
 * ✅ Live table/note search
 * ✅ Sidebar mobile toggle + ESC close
 * ✅ Flash auto-dismiss with close button
 */

document.addEventListener("DOMContentLoaded", () => {
  initFlash();
  initModals();
  initDate();
  initSearch();
  initProgressBars();
  initFertCalc();
  initCharts();
  highlightNav();
});

/* ══════════════════════════════════════
   SIDEBAR
   NOTE: sidebar/hamburger toggle is handled entirely by the inline
   script in templates/base.html (hamburgerBtn + sidebar + sidebarOverlay).
   Do not add another click handler here — having two listeners on the
   same button toggles the class twice per click, which cancels itself
   out and makes the menu look completely unresponsive.
══════════════════════════════════════ */

function highlightNav() {
  const path = window.location.pathname;
  document.querySelectorAll(".nav-link").forEach(a => {
    const href = a.getAttribute("href") || "";
    const match = href === "/" ? path === "/" : href !== "/" && path.startsWith(href);
    if (match) a.classList.add("active");
  });
}

/* ══════════════════════════════════════
   FLASH
══════════════════════════════════════ */
function initFlash() {
  document.querySelectorAll(".flash").forEach(el => {
    el.querySelector(".flash-close")?.addEventListener("click", () => dismiss(el));
    setTimeout(() => dismiss(el), 5000);
  });
}
function dismiss(el) {
  if (!el?.parentNode) return;
  el.style.cssText += "transition:opacity .35s ease,transform .35s ease;opacity:0;transform:translateX(22px)";
  setTimeout(() => el.remove(), 380);
}

/* ══════════════════════════════════════
   MODAL SYSTEM
   data-open="MODAL_ID"  → opens
   data-close="MODAL_ID" → closes
══════════════════════════════════════ */
function initModals() {
  document.querySelectorAll("[data-open]").forEach(el =>
    el.addEventListener("click", () => openModal(el.dataset.open)));
  document.querySelectorAll("[data-close]").forEach(el =>
    el.addEventListener("click", () => closeModal(el.dataset.close)));
  document.querySelectorAll(".modal-overlay").forEach(ov =>
    ov.addEventListener("click", e => { if (e.target === ov) closeModal(ov.id); }));
  document.addEventListener("keydown", e => {
    if (e.key === "Escape")
      document.querySelectorAll(".modal-overlay:not(.hidden)").forEach(m => closeModal(m.id));
  });
}
function openModal(id) {
  const el = document.getElementById(id);
  if (!el) return console.warn("openModal: not found →", id);
  el.classList.remove("hidden");
  setTimeout(() => el.querySelector("input,select,textarea")?.focus(), 60);
}
function closeModal(id) {
  document.getElementById(id)?.classList.add("hidden");
}
window.openModal  = openModal;
window.closeModal = closeModal;

/* ══════════════════════════════════════
   FARM — EDIT
   1. fetch /api/farm/<id>
   2. fill editFarmModal fields
   3. set form action
   4. open modal
══════════════════════════════════════ */
async function editFarm(id) {
  try {
    const res = await fetch(`/api/farm/${id}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const f = await res.json();

    const m = document.getElementById("editFarmModal");
    if (!m) throw new Error("editFarmModal element missing from DOM");

    m.querySelector("[name=farm_name]").value     = f.farm_name     ?? "";
    m.querySelector("[name=crop_type]").value      = f.crop_type     ?? "";
    m.querySelector("[name=location]").value       = f.location      ?? "";
    m.querySelector("[name=area]").value           = f.area          ?? "";
    m.querySelector("[name=planting_date]").value  = f.planting_date ?? "";
    m.querySelector("[name=status]").value         = f.status        ?? "Active";
    m.querySelector("form").setAttribute("action", `/farms/edit/${id}`);

    openModal("editFarmModal");
  } catch (err) {
    toast(`Could not load farm data: ${err.message}`, "error");
  }
}
window.editFarm = editFarm;

/* ══════════════════════════════════════
   FARM — DELETE
══════════════════════════════════════ */
function deleteFarm(id, name) {
  if (!confirm(`Delete farm "${name}"?\n\nAll notes will also be removed. This cannot be undone.`)) return;
  const f = document.getElementById(`del-farm-${id}`);
  if (f) f.submit();
  else toast(`Delete form for farm ${id} not found`, "error");
}
window.deleteFarm = deleteFarm;

/* ══════════════════════════════════════
   NOTE — EDIT
══════════════════════════════════════ */
async function editNote(id) {
  try {
    const res = await fetch(`/api/note/${id}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const n = await res.json();

    const m = document.getElementById("editNoteModal");
    if (!m) throw new Error("editNoteModal element missing from DOM");

    m.querySelector("[name=title]").value    = n.title    ?? "";
    m.querySelector("[name=category]").value = n.category ?? "General";
    m.querySelector("[name=note]").value     = n.note     ?? "";
    m.querySelector("form").setAttribute("action", `/notes/edit/${id}`);

    openModal("editNoteModal");
  } catch (err) {
    toast(`Could not load note: ${err.message}`, "error");
  }
}
window.editNote = editNote;

/* ══════════════════════════════════════
   NOTE — DELETE
══════════════════════════════════════ */
function deleteNote(id) {
  if (!confirm("Delete this note permanently? This cannot be undone.")) return;
  const f = document.getElementById(`del-note-${id}`);
  if (f) f.submit();
  else toast(`Delete form for note ${id} not found`, "error");
}
window.deleteNote = deleteNote;

/* ══════════════════════════════════════
   TOAST  (dynamic flash, no reload)
══════════════════════════════════════ */
function toast(msg, type = "success") {
  let wrap = document.querySelector(".flash-wrap");
  if (!wrap) { wrap = document.createElement("div"); wrap.className = "flash-wrap"; document.body.appendChild(wrap); }
  const el = document.createElement("div");
  el.className = `flash ${type}`;
  el.innerHTML = `<i class="fas fa-${type === "success" ? "check-circle" : "exclamation-circle"}"></i>
                  <span>${msg}</span><button class="flash-close">&times;</button>`;
  el.querySelector(".flash-close").onclick = () => dismiss(el);
  wrap.appendChild(el);
  setTimeout(() => dismiss(el), 5000);
}
window.toast = toast;

/* ══════════════════════════════════════
   DATE
══════════════════════════════════════ */
function initDate() {
  const el = document.getElementById("liveDate");
  if (!el) return;
  el.textContent = new Intl.DateTimeFormat("en-GB", {
    weekday:"short", day:"numeric", month:"short", year:"numeric"
  }).format(new Date());
}

/* ══════════════════════════════════════
   SEARCH  (live filter on data-searchable)
══════════════════════════════════════ */
function initSearch() {
  const inp = document.getElementById("tableSearch");
  if (inp) {
    inp.addEventListener("input", () => {
      const q = inp.value.trim().toLowerCase();
      document.querySelectorAll("[data-searchable]").forEach(row =>
        row.style.display = (!q || row.textContent.toLowerCase().includes(q)) ? "" : "none");
    });
  }
  // Weather city form
  document.getElementById("cityForm")?.addEventListener("submit", e => {
    e.preventDefault();
    const city = e.target.querySelector("[name=city]").value.trim();
    if (city) window.location.href = `/weather?city=${encodeURIComponent(city)}`;
  });
}

/* ══════════════════════════════════════
   PROGRESS BARS
══════════════════════════════════════ */
function initProgressBars() {
  const io = new IntersectionObserver(entries => entries.forEach(e => {
    if (e.isIntersecting) { e.target.style.width = e.target.dataset.w || "0%"; io.unobserve(e.target); }
  }), { threshold: 0.15 });
  document.querySelectorAll(".prog[data-w]").forEach(bar => { bar.style.width = "0%"; io.observe(bar); });
}

/* ══════════════════════════════════════
   FERTILIZER CALCULATOR
══════════════════════════════════════ */
function initFertCalc() {
  const form = document.getElementById("fertForm");
  if (!form) return;
  form.addEventListener("submit", async e => {
    e.preventDefault();
    const crop = form.querySelector("[name=calc_crop]").value;
    const area = parseFloat(form.querySelector("[name=calc_area]").value);
    const out  = document.getElementById("calcOut");
    if (!crop || isNaN(area) || area <= 0) {
      out.innerHTML = `<div class="flash error mt-16"><i class="fas fa-exclamation-circle"></i><span>Enter a valid crop and positive area.</span></div>`;
      return;
    }
    const btn = form.querySelector("[type=submit]");
    btn.disabled = true; btn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> Calculating…`;
    try {
      const d = await (await fetch("/api/fertilizer", {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({crop_type:crop, area})
      })).json();
      out.innerHTML = `
        <div class="card mt-20" style="border-top:3px solid var(--p-light)">
          <div class="card-header">
            <h2><i class="fas fa-flask"></i> Results — ${cap(crop)} · ${area} acre${area!==1?"s":""}</h2>
            <span class="badge badge-green"><i class="fas fa-check"></i> Calculated</span>
          </div>
          <div class="card-body">
            <div class="npk-grid">
              <div class="npk-card" style="--npk-color:#1B5E20"><div class="val">${d.N}</div><div class="lbl">Nitrogen (N)</div><div class="sub">kg total</div></div>
              <div class="npk-card" style="--npk-color:#1565C0"><div class="val">${d.P}</div><div class="lbl">Phosphorus (P)</div><div class="sub">kg total</div></div>
              <div class="npk-card" style="--npk-color:#E65100"><div class="val">${d.K}</div><div class="lbl">Potassium (K)</div><div class="sub">kg total</div></div>
              <div class="npk-card" style="--npk-color:#6A1B9A"><div class="val">${d.urea}</div><div class="lbl">Urea Equiv.</div><div class="sub">kg total</div></div>
              <div class="npk-card" style="--npk-color:#00695C;grid-column:span 2"><div class="val">${d.total} kg</div><div class="lbl">Total Fertilizer</div><div class="sub">N+P+K for ${area} acre${area!==1?"s":""}</div></div>
            </div>
            <p class="text-muted fs-12 mt-16"><i class="fas fa-info-circle"></i> General guidelines. Conduct a soil test for precision.</p>
          </div>
        </div>`;
    } catch {
      out.innerHTML = `<div class="flash error mt-16"><i class="fas fa-exclamation-circle"></i><span>Calculation failed — please try again.</span></div>`;
    } finally {
      btn.disabled = false; btn.innerHTML = `<i class="fas fa-calculator"></i> Calculate`;
    }
  });
}
function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase(); }

/* ══════════════════════════════════════
   CHART.JS
══════════════════════════════════════ */
function initCharts() {
  if (typeof Chart === "undefined") return;
  Chart.defaults.font.family = "'Poppins',sans-serif";
  Chart.defaults.color       = "#5C7A5C";

  const COLORS = ["#43A047","#0288D1","#F59E0B","#EF4444","#7C3AED","#00897B","#8D6E63","#78909C"];

  function data(id) {
    const el = document.getElementById(id);
    if (!el) return null;
    return { labels: JSON.parse(el.dataset.labels||"[]"), values: JSON.parse(el.dataset.values||"[]") };
  }

  function bar(id, col="#4CAF50", label="") {
    const d = data(id); if (!d) return;
    new Chart(document.getElementById(id), {
      type:"bar",
      data:{labels:d.labels,datasets:[{label,data:d.values,backgroundColor:col+"BB",borderColor:col,borderWidth:0,borderRadius:8,borderSkipped:false}]},
      options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},
        scales:{x:{grid:{display:false},ticks:{font:{size:11}}},y:{grid:{color:"rgba(0,0,0,.04)"},beginAtZero:true,ticks:{maxTicksLimit:5,font:{size:11}}}}}
    });
  }

  function line(id, col="#0288D1", label="", fill=true) {
    const d = data(id); if (!d) return;
    new Chart(document.getElementById(id), {
      type:"line",
      data:{labels:d.labels,datasets:[{label,data:d.values,tension:0.42,fill,
        borderColor:col,backgroundColor:col+"1A",borderWidth:2.5,
        pointBackgroundColor:"#fff",pointBorderColor:col,pointRadius:4,pointHoverRadius:7}]},
      options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},
        scales:{x:{grid:{display:false},ticks:{font:{size:11}}},y:{grid:{color:"rgba(0,0,0,.04)"},beginAtZero:true,ticks:{maxTicksLimit:5,font:{size:11}}}}}
    });
  }

  function donut(id) {
    const d = data(id); if (!d) return;
    const isMobile = window.innerWidth <= 640;
    new Chart(document.getElementById(id), {
      type:"doughnut",
      data:{labels:d.labels,datasets:[{data:d.values,backgroundColor:COLORS.slice(0,d.values.length),borderWidth:2,borderColor:"#fff",hoverOffset:8}]},
      options:{responsive:true,maintainAspectRatio:false,cutout:"68%",
        plugins:{legend:{display:true,position: isMobile ? "bottom" : "right",
          labels:{padding:isMobile?10:14,font:{size:isMobile?11:12},usePointStyle:true,boxWidth:10}}}}
    });
  }

  // Analytics
  bar("chartFarmArea",   "#2E7D32", "Area (ac)");
  line("chartWater",     "#0288D1", "Litres",  true);
  bar("chartHarvest",    "#8BC34A", "Tonnes");
  donut("chartCrops");

  // Dashboard mini
  bar("chartMiniArea",   "#43A047", "Area");
  donut("chartMiniCrops");
}
