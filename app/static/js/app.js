// Bootstrap tooltip init on every page
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
    new bootstrap.Tooltip(el);
  });
});

// ── Light / dark theme (persisted per terminal via localStorage) ──────────────
const RANGE_THEME_KEY = 'rangeTheme';
function syncThemeIcon(theme) {
  const icon = document.querySelector('#themeToggle i');
  if (icon) icon.className = theme === 'dark' ? 'bi bi-moon-stars' : 'bi bi-sun-fill';
}
function applyTheme(theme) {
  document.documentElement.setAttribute('data-bs-theme', theme);
  try { localStorage.setItem(RANGE_THEME_KEY, theme); } catch (e) {}
  syncThemeIcon(theme);
}
function toggleTheme() {
  const current = document.documentElement.getAttribute('data-bs-theme') || 'dark';
  applyTheme(current === 'dark' ? 'light' : 'dark');
}

// ── Colour palette (independent of light/dark) ────────────────────────────────
const RANGE_PALETTE_KEY = 'rangePalette';
function applyPalette(name) {
  document.documentElement.setAttribute('data-theme', name);
  try { localStorage.setItem(RANGE_PALETTE_KEY, name); } catch (e) {}
  document.querySelectorAll('[data-palette-btn]').forEach(b =>
    b.classList.toggle('active', b.dataset.paletteBtn === name));
}
document.addEventListener('DOMContentLoaded', () => {
  syncThemeIcon(document.documentElement.getAttribute('data-bs-theme') || 'dark');
  const pal = document.documentElement.getAttribute('data-theme') || 'classic';
  document.querySelectorAll('[data-palette-btn]').forEach(b =>
    b.classList.toggle('active', b.dataset.paletteBtn === pal));
});

// ── Sidebar toggle ────────────────────────────────────────────────────────────
const SIDEBAR_KEY = 'sidebarCollapsed';
function toggleSidebar() {
  const collapsed = document.body.classList.toggle('sidebar-collapsed');
  try { localStorage.setItem(SIDEBAR_KEY, collapsed ? '1' : '0'); } catch (e) {}
}
(function initSidebar() {
  try {
    const isMobile = window.innerWidth < 768;
    // On mobile: default to collapsed (off-screen); restore desktop state on wide screens.
    const stored = localStorage.getItem(SIDEBAR_KEY);
    if (isMobile) {
      document.body.classList.add('sidebar-collapsed');
    } else if (stored === '1') {
      document.body.classList.add('sidebar-collapsed');
    }
    // else: sidebar open (default on desktop)
  } catch (e) {}
})();

// Show a Bootstrap toast notification
function showToast(message, type = 'success') {
  const container = document.getElementById('toastContainer');
  if (!container) return;
  const id = 'toast_' + Date.now();
  const html = `
    <div id="${id}" class="toast align-items-center text-bg-${type} border-0" role="alert" aria-live="assertive">
      <div class="d-flex">
        <div class="toast-body">${message}</div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
      </div>
    </div>`;
  container.insertAdjacentHTML('beforeend', html);
  const toastEl = document.getElementById(id);
  const toast = new bootstrap.Toast(toastEl, { delay: 4000 });
  toast.show();
  toastEl.addEventListener('hidden.bs.toast', () => toastEl.remove());
}

// Keyboard shortcut: N → new log entry (unless focus is in an input/textarea/select)
document.addEventListener('keydown', (evt) => {
  if (evt.key === 'n' || evt.key === 'N') {
    const tag = document.activeElement?.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
    if (evt.ctrlKey || evt.metaKey || evt.altKey) return;
    window.location.href = '/logs/new';
  }
});

// HTMX: pause the dashboard poll while a quick-edit row is open or a row has
// unsubmitted inline on/off / power changes staged.
document.addEventListener('htmx:beforeRequest', (evt) => {
  if (evt.detail.requestConfig?.path?.includes('/dashboard/fragment')) {
    if (document.querySelector('.signal-table .collapse.show') ||
        document.querySelector('.signal-row-dirty')) {
      evt.preventDefault();
    }
  }
});

// HTMX: update refresh timestamp after successful fragment refresh
document.addEventListener('htmx:afterRequest', (evt) => {
  if (evt.detail.successful && evt.detail.requestConfig?.path?.includes('/dashboard/fragment')) {
    updateRefreshTime?.();
  }
});

// ── Widget span toggle (half / full width in the 2-col grid) ─────────────────
function toggleWidgetSpan(btn) {
  const group = btn.closest('.serial-widget-group');
  if (!group) return;
  group.classList.toggle('span-1');
  saveLayout?.();
}

// ── Basic math calculator ─────────────────────────────────────────────────────
// State is per-instance, keyed by widget id stored on the DOM element.
const calcState = {};
function calcKey(id) { return calcState[id] || (calcState[id] = { expr: '', current: '0', hasResult: false }); }

function calcPress(id, val) {
  const s = calcKey(id);
  const disp = document.getElementById('mathCalcInput-' + id);
  const expr = document.getElementById('mathCalcExpr-' + id);
  if (!disp) return;

  if (val === 'C') {
    s.expr = ''; s.current = '0'; s.hasResult = false;
  } else if (val === '⌫') {
    if (s.current.length > 1) s.current = s.current.slice(0, -1);
    else s.current = '0';
    s.hasResult = false;
  } else if (val === '±') {
    if (s.current !== '0') s.current = s.current.startsWith('-') ? s.current.slice(1) : '-' + s.current;
  } else if (val === '%') {
    const v = parseFloat(s.current);
    if (!isNaN(v)) s.current = String(v / 100);
  } else if (['+', '−', '×', '÷'].includes(val)) {
    if (s.expr && !s.hasResult) {
      // chain: evaluate current expression first
      try { s.current = String(evalCalcExpr(s.expr + s.current)); } catch (e) {}
    }
    s.expr = s.current + ' ' + val + ' ';
    s.hasResult = false;
  } else if (val === '=') {
    if (s.expr) {
      const full = s.expr + s.current;
      try {
        const result = evalCalcExpr(full);
        if (expr) expr.textContent = full + ' =';
        s.current = formatCalcNum(result);
        s.expr = '';
        s.hasResult = true;
      } catch (e) { s.current = 'Error'; s.expr = ''; }
    }
  } else if (val === '.') {
    if (s.hasResult) { s.current = '0.'; s.hasResult = false; s.expr = ''; }
    else if (!s.current.includes('.')) s.current += '.';
  } else {
    // digit
    if (s.hasResult) { s.current = val; s.hasResult = false; s.expr = ''; }
    else s.current = s.current === '0' ? val : s.current + val;
  }

  disp.value = s.current;
  if (expr && val !== '=') expr.textContent = s.expr;
}

function evalCalcExpr(str) {
  // Parse "A op B" where op is one of our symbols
  const m = str.match(/^(-?[\d.]+)\s*([+−×÷])\s*(-?[\d.]+)$/);
  if (!m) throw new Error('bad expr');
  const a = parseFloat(m[1]), b = parseFloat(m[3]);
  if (m[2] === '+') return a + b;
  if (m[2] === '−') return a - b;
  if (m[2] === '×') return a * b;
  if (m[2] === '÷') { if (b === 0) throw new Error('div0'); return a / b; }
  throw new Error('unknown op');
}

function formatCalcNum(n) {
  if (!isFinite(n)) return 'Error';
  // Avoid floating-point noise like 0.1 + 0.2 = 0.30000000000000004
  const s = parseFloat(n.toPrecision(12));
  return String(s);
}

function mathCalcBody(id) {
  const btns = [
    ['C','clr'], ['±','op'], ['%','op'], ['÷','op'],
    ['7',''], ['8',''], ['9',''], ['×','op'],
    ['4',''], ['5',''], ['6',''], ['−','op'],
    ['1',''], ['2',''], ['3',''], ['+','op'],
    ['0',''], ['.',''], ['⌫','op'], ['=','eq'],
  ];
  const grid = btns.map(([v, cls]) =>
    `<button type="button" class="calc-btn ${cls}" onclick="calcPress('${id}','${v}')">${v}</button>`
  ).join('');
  return `<div class="p-2">
    <div class="math-calc-expr mb-1" id="mathCalcExpr-${id}"></div>
    <input id="mathCalcInput-${id}" class="form-control form-control-sm text-end font-monospace mb-2"
           value="0" readonly style="font-size:1.4rem;height:auto;padding:.3rem .6rem">
    <div class="calc-btn-grid">${grid}</div>
  </div>`;
}

// ── RF Frequency calculator (client-side, compact widget) ─────────────────────
function rfCalcBody(id) {
  return `<div class="p-2" id="rfCalcWidget-${id}">
  <div class="row g-2 mb-2">
    <div class="col-6">
      <label class="form-label small mb-1">Known value</label>
      <select class="form-select form-select-sm" id="rfKnown-${id}">
        <option value="TxIF">TxIF</option>
        <option value="TxRF">TxRF</option>
        <option value="RxRF">RxRF</option>
        <option value="RxIF">RxIF</option>
      </select>
    </div>
    <div class="col-6">
      <label class="form-label small mb-1">Unit</label>
      <select class="form-select form-select-sm" id="rfUnit-${id}">
        <option value="MHz">MHz</option>
        <option value="GHz">GHz</option>
      </select>
    </div>
  </div>
  <div class="row g-2 mb-2">
    <div class="col-6">
      <label class="form-label small mb-1">Value</label>
      <input type="number" step="any" class="form-control form-control-sm" id="rfVal-${id}" placeholder="0">
    </div>
    <div class="col-6">
      <label class="form-label small mb-1">TxLO</label>
      <input type="number" step="any" class="form-control form-control-sm" id="rfTxLO-${id}" placeholder="0">
    </div>
    <div class="col-6">
      <label class="form-label small mb-1">RxLO</label>
      <input type="number" step="any" class="form-control form-control-sm" id="rfRxLO-${id}" placeholder="0">
    </div>
    <div class="col-6">
      <label class="form-label small mb-1">TTF</label>
      <div class="input-group input-group-sm">
        <select class="form-select form-select-sm" id="rfTtfDir-${id}" style="max-width:3.5rem">
          <option value="+">+</option>
          <option value="-">−</option>
        </select>
        <input type="number" step="any" class="form-control form-control-sm" id="rfTtf-${id}" placeholder="0">
      </div>
    </div>
  </div>
  <button type="button" class="btn btn-sm btn-primary w-100 mb-2" onclick="runRfCalc('${id}')">
    <i class="bi bi-calculator me-1"></i>Calculate
  </button>
  <div id="rfResult-${id}" class="font-monospace small"></div>
  <div class="text-end mt-1"><a href="/calculator/rf" class="text-muted small">Full calculator →</a></div>
  </div>`;
}

function runRfCalc(id) {
  const known = document.getElementById('rfKnown-' + id)?.value;
  const unit  = document.getElementById('rfUnit-' + id)?.value;
  const val   = parseFloat(document.getElementById('rfVal-' + id)?.value) || 0;
  const txLo  = parseFloat(document.getElementById('rfTxLO-' + id)?.value) || 0;
  const rxLo  = parseFloat(document.getElementById('rfRxLO-' + id)?.value) || 0;
  const ttf   = parseFloat(document.getElementById('rfTtf-' + id)?.value) || 0;
  const dir   = document.getElementById('rfTtfDir-' + id)?.value || '+';
  const out   = document.getElementById('rfResult-' + id);
  if (!out) return;
  const mult = unit === 'GHz' ? 1000 : 1;
  const v = val * mult, tl = txLo * mult, rl = rxLo * mult, t = ttf * mult;
  const sign = dir === '+' ? 1 : -1;
  let ti, tr, rr, ri;
  if (known === 'TxIF') { ti = v; tr = ti + tl; rr = tr + sign*t; ri = rr - rl; }
  else if (known === 'TxRF') { tr = v; ti = tr - tl; rr = tr + sign*t; ri = rr - rl; }
  else if (known === 'RxRF') { rr = v; tr = rr - sign*t; ti = tr - tl; ri = rr - rl; }
  else { ri = v; rr = ri + rl; tr = rr - sign*t; ti = tr - tl; }
  const fmt = f => unit === 'GHz' ? (f/1000).toFixed(4) + ' GHz' : f.toFixed(2) + ' MHz';
  out.innerHTML = `
    <table class="table table-sm table-borderless mb-0" style="font-size:.8rem">
      <tr><td class="text-muted py-0">TxIF</td><td class="text-end py-0 fw-semibold">${fmt(ti)}</td></tr>
      <tr><td class="text-muted py-0">TxRF</td><td class="text-end py-0 fw-semibold">${fmt(tr)}</td></tr>
      <tr><td class="text-muted py-0">RxRF</td><td class="text-end py-0 fw-semibold">${fmt(rr)}</td></tr>
      <tr><td class="text-muted py-0">RxIF</td><td class="text-end py-0 fw-semibold">${fmt(ri)}</td></tr>
    </table>`;
}

// ── Power unit converter (client-side, compact widget) ────────────────────────
function powerConvBody(id) {
  return `<div class="p-2" id="pwrConvWidget-${id}">
  <div class="row g-2 mb-2">
    <div class="col-8">
      <label class="form-label small mb-1">Value</label>
      <input type="number" step="any" class="form-control form-control-sm" id="pwrVal-${id}" placeholder="0" oninput="runPwrConv('${id}')">
    </div>
    <div class="col-4">
      <label class="form-label small mb-1">Unit</label>
      <select class="form-select form-select-sm" id="pwrUnit-${id}" onchange="runPwrConv('${id}')">
        <option value="dBm">dBm</option>
        <option value="dBW">dBW</option>
        <option value="W">W</option>
        <option value="mW">mW</option>
      </select>
    </div>
  </div>
  <div id="pwrResult-${id}" class="font-monospace small"></div>
  <div class="text-end mt-1"><a href="/calculator/power" class="text-muted small">Full calculator →</a></div>
  </div>`;
}

function runPwrConv(id) {
  const val  = parseFloat(document.getElementById('pwrVal-' + id)?.value);
  const unit = document.getElementById('pwrUnit-' + id)?.value;
  const out  = document.getElementById('pwrResult-' + id);
  if (!out) return;
  if (isNaN(val)) { out.innerHTML = ''; return; }
  let watts;
  if (unit === 'W')   watts = val;
  else if (unit === 'mW')  watts = val / 1000;
  else if (unit === 'dBW') watts = Math.pow(10, val / 10);
  else /* dBm */           watts = Math.pow(10, (val - 30) / 10);
  if (watts <= 0) { out.innerHTML = '<span class="text-danger small">Value must be positive for log scale.</span>'; return; }
  const dBW = 10 * Math.log10(watts);
  const dBm = dBW + 30;
  const mW  = watts * 1000;
  function fmtW(w) {
    if (w >= 1000) return (w/1000).toPrecision(4) + ' kW';
    if (w >= 1) return w.toPrecision(4) + ' W';
    if (w >= 0.001) return (w*1000).toPrecision(4) + ' mW';
    return (w*1e6).toPrecision(4) + ' µW';
  }
  out.innerHTML = `
    <table class="table table-sm table-borderless mb-0" style="font-size:.8rem">
      <tr><td class="text-muted py-0">dBm</td><td class="text-end py-0 fw-semibold">${dBm.toFixed(2)}</td></tr>
      <tr><td class="text-muted py-0">dBW</td><td class="text-end py-0 fw-semibold">${dBW.toFixed(2)}</td></tr>
      <tr><td class="text-muted py-0">Watts</td><td class="text-end py-0 fw-semibold">${fmtW(watts)}</td></tr>
      <tr><td class="text-muted py-0">mW</td><td class="text-end py-0 fw-semibold">${mW.toPrecision(4)}</td></tr>
    </table>`;
}
