// Bootstrap tooltip init on every page
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
    new bootstrap.Tooltip(el);
  });
});

// ── Page position / tab restore ──────────────────────────────────────────────
// Normal POST/GET forms intentionally reload the page in several places. Keep
// the operator on the tab/scroll position they were using after that reload.
const PAGE_UI_STATE_PREFIX = 'projectRangePageUiState:';
const PAGE_UI_STATE_MAX_AGE_MS = 10 * 60 * 1000;

function pageUiStateKey() {
  return PAGE_UI_STATE_PREFIX + window.location.pathname;
}

function activeTabTargets() {
  return [...document.querySelectorAll('[data-bs-toggle="tab"].active')]
    .map(el => el.getAttribute('data-bs-target') || el.getAttribute('href'))
    .filter(Boolean);
}

function savePageUiState({ restoreScroll = false } = {}) {
  try {
    sessionStorage.setItem(pageUiStateKey(), JSON.stringify({
      scrollY: window.scrollY || document.documentElement.scrollTop || 0,
      restoreScroll,
      activeTabs: activeTabTargets(),
      savedAt: Date.now(),
    }));
  } catch (e) {}
}

function restorePageUiState() {
  let state = null;
  try {
    state = JSON.parse(sessionStorage.getItem(pageUiStateKey()) || 'null');
  } catch (e) {}
  if (!state || Date.now() - (state.savedAt || 0) > PAGE_UI_STATE_MAX_AGE_MS) return;

  (state.activeTabs || []).forEach(target => {
    const trigger = [...document.querySelectorAll('[data-bs-toggle="tab"]')]
      .find(el => (el.getAttribute('data-bs-target') || el.getAttribute('href')) === target);
    if (trigger && window.bootstrap) bootstrap.Tab.getOrCreateInstance(trigger).show();
  });

  if (state.restoreScroll) {
    window.requestAnimationFrame(() => window.scrollTo(0, state.scrollY || 0));
    state.restoreScroll = false;
    try { sessionStorage.setItem(pageUiStateKey(), JSON.stringify(state)); } catch (e) {}
  }
}

document.addEventListener('DOMContentLoaded', () => {
  restorePageUiState();
  document.querySelectorAll('[data-bs-toggle="tab"]').forEach(el => {
    el.addEventListener('shown.bs.tab', () => savePageUiState());
  });
});

document.addEventListener('submit', event => {
  if (event.target instanceof HTMLFormElement && !event.target.hasAttribute('data-no-ui-restore')) {
    savePageUiState({ restoreScroll: true });
  }
}, true);

document.addEventListener('change', event => {
  const el = event.target;
  if (el instanceof HTMLSelectElement && el.form && !el.form.hasAttribute('data-no-ui-restore')) {
    savePageUiState({ restoreScroll: true });
  }
}, true);

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

// ── HTML escaping (used by dynamically-built widgets / overlays) ──────────────
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// ── CEASE: range-wide stop alert ──────────────────────────────────────────────
// Driven by a lightweight JSON poll so the full-screen overlay is only (re)built
// when the active event id changes — no per-poll flicker. Any user can raise or
// dismiss; the splash appears on every connected screen within the poll interval.
let ceaseCurrentId = null;

async function raiseCease() {
  const ta = document.getElementById('ceaseReason');
  const err = document.getElementById('ceaseError');
  const reason = (ta?.value || '').trim();
  if (!reason) { err?.classList.remove('d-none'); return; }
  err?.classList.add('d-none');
  try {
    const r = await fetch('/cease/raise', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ reason }),
    });
    if (!r.ok) throw new Error();
    const modalEl = document.getElementById('ceaseModal');
    if (modalEl && window.bootstrap) bootstrap.Modal.getOrCreateInstance(modalEl).hide();
    if (ta) ta.value = '';
    pollCease();  // show it immediately for the raiser
  } catch (e) {
    showToast?.('Could not raise CEASE — try again', 'danger');
  }
}

async function dismissCease() {
  try {
    await fetch('/cease/dismiss', { method: 'POST' });
  } catch (e) {}
  ceaseCurrentId = null;
  hideCeaseSplash();
  pollCease();
}

function showCeaseSplash(data) {
  const root = document.getElementById('ceaseRoot');
  if (!root) return;
  root.innerHTML = `
    <div class="cease-overlay" role="alertdialog" aria-label="CEASE alert">
      <div class="cease-box">
        <div class="cease-flash"><i class="bi bi-exclamation-octagon-fill"></i></div>
        <div class="cease-word">CEASE</div>
        <div class="cease-meta">Raised by <strong>${escapeHtml(data.raised_by)}</strong>${data.raised_at ? ' at ' + escapeHtml(data.raised_at) : ''}</div>
        <div class="cease-reason">${escapeHtml(data.reason)}</div>
        <button type="button" class="btn btn-light btn-lg mt-3 fw-bold" onclick="dismissCease()">
          <i class="bi bi-check-lg me-1"></i>Dismiss
        </button>
      </div>
    </div>`;
}

function hideCeaseSplash() {
  const root = document.getElementById('ceaseRoot');
  if (root) root.innerHTML = '';
}

async function pollCease() {
  if (!document.getElementById('ceaseRoot')) return;
  try {
    const r = await fetch('/cease/state', { headers: { 'Accept': 'application/json' } });
    if (!r.ok) return;
    const data = await r.json();
    if (data.active) {
      if (ceaseCurrentId !== data.id) { ceaseCurrentId = data.id; showCeaseSplash(data); }
    } else if (ceaseCurrentId !== null) {
      ceaseCurrentId = null;
      hideCeaseSplash();
    }
  } catch (e) {}
}

document.addEventListener('DOMContentLoaded', () => {
  if (document.getElementById('ceaseRoot')) {
    pollCease();
    setInterval(pollCease, 3000);
  }
});

// ── Instant chat: lightweight in-memory polling chat ─────────────────────────
function loadChatSessionState() {
  try {
    const raw = sessionStorage.getItem('projectRangeChatState');
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch (e) {
    return {};
  }
}

function saveChatSessionState() {
  try {
    sessionStorage.setItem('projectRangeChatState', JSON.stringify({
      lastMessageIds: chatState.lastMessageIds,
      unread: chatState.unread,
    }));
  } catch (e) {}
}

const savedChatState = loadChatSessionState();
const chatState = {
  me: null,
  users: [],
  rooms: {},
  openRooms: {},
  lastMessageIds: savedChatState.lastMessageIds || {},
  roomSeen: {},
  unread: savedChatState.unread || {},
  rosterOpen: false,
};
window.chatState = chatState;

function chatApi(path, opts = {}) {
  return fetch(path, {
    headers: { 'Accept': 'application/json', ...(opts.headers || {}) },
    ...opts,
  }).then(r => {
    if (!r.ok) throw new Error('chat request failed');
    return r.json();
  });
}

function toggleChatRoster(force) {
  const roster = document.getElementById('chatRoster');
  if (!roster) return;
  chatState.rosterOpen = typeof force === 'boolean' ? force : roster.classList.contains('d-none');
  roster.classList.toggle('d-none', !chatState.rosterOpen);
  if (chatState.rosterOpen) refreshChatState();
}

function toggleChatGroupCreator() {
  document.getElementById('chatGroupCreator')?.classList.toggle('d-none');
}

function renderChatRoster() {
  const online = document.getElementById('chatOnlineUsers');
  const groupUsers = document.getElementById('chatGroupUsers');
  if (!online || !groupUsers) return;
  const others = chatState.users.filter(u => !chatState.me || u.id !== chatState.me.id);
  online.innerHTML = others.length ? others.map(u => `
    <button type="button" class="chat-user-row" ondblclick="openPrivateChat(${u.id})" title="Double-click to chat">
      <span class="chat-presence-dot"></span>
      <span class="text-truncate">${escapeHtml(u.display_name)}</span>
      ${chatRoleBadge(u)}
    </button>
  `).join('') : '<div class="text-muted py-2">No other users online.</div>';
  groupUsers.innerHTML = others.length ? others.map(u => `
    <label class="d-flex align-items-center gap-2 py-1">
      <input class="form-check-input m-0" type="checkbox" value="${u.id}" data-chat-group-user>
      <span class="text-truncate">${escapeHtml(u.display_name)}</span>
      ${chatRoleBadge(u)}
    </label>
  `).join('') : '<div class="text-muted py-2">No online users to add.</div>';
}

function chatRoleBadge(user) {
  const label = user.duty_role || user.role || '';
  if (!label) return '';
  const colour = user.duty_role_color || '#6c757d';
  return `<span class="badge chat-role-badge" style="background:${escapeHtml(colour)}">${escapeHtml(label)}</span>`;
}

function mergeChatRooms(rooms) {
  (rooms || []).forEach(room => {
    const known = Boolean(chatState.rooms[room.id]);
    chatState.rooms[room.id] = room;
    if (!known) chatState.roomSeen[room.id] = false;
  });
  saveChatSessionState();
}

async function refreshChatState() {
  if (!document.getElementById('chatDock')) return;
  try {
    const data = await chatApi('/chat/state');
    chatState.me = data.me;
    chatState.users = data.online_users || [];
    mergeChatRooms(data.rooms);
    pollKnownChatRooms();
    renderChatRoster();
    window.renderDashboardChatWidget?.();
  } catch (e) {}
}

async function openPrivateChat(userId) {
  try {
    const data = await chatApi('/chat/rooms/private', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ user_id: userId }),
    });
    mergeChatRooms([data.room]);
    openChatWindow(data.room.id);
  } catch (e) {
    showToast?.('Could not open chat', 'danger');
  }
}

async function createChatGroup() {
  const ids = [...document.querySelectorAll('[data-chat-group-user]:checked')].map(x => x.value);
  if (!ids.length) { showToast?.('Select at least one user', 'warning'); return; }
  const title = document.getElementById('chatGroupTitle')?.value || 'Group Chat';
  try {
    const data = await chatApi('/chat/rooms/group', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ participant_ids: ids.join(','), title }),
    });
    mergeChatRooms([data.room]);
    document.getElementById('chatGroupTitle').value = '';
    document.querySelectorAll('[data-chat-group-user]').forEach(x => { x.checked = false; });
    openChatWindow(data.room.id);
  } catch (e) {
    showToast?.('Could not create group chat', 'danger');
  }
}

function openChatWindow(roomId) {
  const room = chatState.rooms[roomId];
  if (!room) return;
  chatState.openRooms[roomId] = true;
  chatState.unread[roomId] = 0;
  chatState.roomSeen[roomId] = true;
  const existing = document.querySelector(`[data-chat-window="${CSS.escape(roomId)}"]`);
  if (existing) {
    existing.classList.remove('minimised', 'has-alert');
    updateChatUnreadBadge();
    pollChatRoom(roomId, { full: true, alert: false });
    return;
  }
  const windows = document.getElementById('chatWindows');
  if (!windows) return;
  const node = document.createElement('div');
  node.className = 'chat-window';
  node.dataset.chatWindow = roomId;
  node.innerHTML = `
    <div class="chat-window-header" onclick="toggleChatWindowMinimised('${escapeHtml(roomId)}')" title="Click to minimise / expand">
      <i class="bi ${room.is_group ? 'bi-people-fill' : 'bi-person-fill'}"></i>
      <div class="chat-window-title">${escapeHtml(room.title)}</div>
      <button type="button" class="btn btn-sm btn-link link-secondary p-0 ms-auto" title="Minimise" onclick="event.stopPropagation(); toggleChatWindowMinimised('${escapeHtml(roomId)}')"><i class="bi bi-dash-lg"></i></button>
      <button type="button" class="btn btn-sm btn-link link-secondary p-0" title="Close" onclick="event.stopPropagation(); closeChatWindow('${escapeHtml(roomId)}')"><i class="bi bi-x-lg"></i></button>
    </div>
    <div class="chat-window-body" data-chat-messages></div>
    <form class="chat-window-form" onsubmit="sendChatMessage(event, '${escapeHtml(roomId)}')">
      <input type="text" class="form-control form-control-sm" name="body" autocomplete="off" maxlength="2000" placeholder="Message">
      <button type="submit" class="btn btn-sm btn-primary" title="Send"><i class="bi bi-send"></i></button>
    </form>`;
  windows.appendChild(node);
  pollChatRoom(roomId, { full: true, alert: false });
  updateChatUnreadBadge();
}

function toggleChatWindowMinimised(roomId) {
  const win = document.querySelector(`[data-chat-window="${CSS.escape(roomId)}"]`);
  if (!win) return;
  win.classList.toggle('minimised');
  if (!win.classList.contains('minimised')) {
    win.classList.remove('has-alert');
    chatState.unread[roomId] = 0;
    chatState.roomSeen[roomId] = true;
    updateChatUnreadBadge();
    saveChatSessionState();
  }
}

function closeChatWindow(roomId) {
  document.querySelector(`[data-chat-window="${CSS.escape(roomId)}"]`)?.remove();
  delete chatState.openRooms[roomId];
  chatState.unread[roomId] = 0;
  updateChatUnreadBadge();
  saveChatSessionState();
}

async function sendChatMessage(evt, roomId) {
  evt.preventDefault();
  const input = evt.target.querySelector('input[name="body"]');
  const body = (input?.value || '').trim();
  if (!body) return;
  input.value = '';
  try {
    await chatApi('/chat/rooms/' + encodeURIComponent(roomId) + '/messages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ body }),
    });
    pollChatRoom(roomId);
  } catch (e) {
    showToast?.('Message not sent', 'danger');
  }
}

function appendChatMessages(roomId, messages, opts = {}) {
  const alert = opts.alert !== false;
  const full = opts.full === true;
  const win = document.querySelector(`[data-chat-window="${CSS.escape(roomId)}"]`);
  const body = win?.querySelector('[data-chat-messages]');
  const roomOpen = Boolean(win && body);
  let receivedNewFromOther = false;
  if (full && body) body.innerHTML = '';
  messages.forEach(msg => {
    chatState.lastMessageIds[roomId] = Math.max(chatState.lastMessageIds[roomId] || 0, msg.id);
    const mine = chatState.me && msg.sender_id === chatState.me.id;
    if (!mine) receivedNewFromOther = true;
    if (body) {
      body.insertAdjacentHTML('beforeend', `
        <div class="chat-message ${mine ? 'mine' : ''}">
          <div class="chat-message-meta">${mine ? 'You' : escapeHtml(msg.sender_name)} · ${escapeHtml(msg.sent_at)}</div>
          <div class="chat-message-bubble">${escapeHtml(msg.body)}</div>
        </div>`);
    }
  });
  if (messages.length && body) body.scrollTop = body.scrollHeight;
  const unreadNew = messages.filter(m => !chatState.me || m.sender_id !== chatState.me.id).length;
  const shouldAlert = receivedNewFromOther && (!roomOpen || win.classList.contains('minimised'));
  if (alert && shouldAlert) {
    if (win) win.classList.add('has-alert');
    chatState.unread[roomId] = (chatState.unread[roomId] || 0) + unreadNew;
    updateChatUnreadBadge();
    const room = chatState.rooms[roomId];
    if (room && !roomOpen) showToast?.(`New chat message: ${escapeHtml(room.title)}`, 'info');
  }
  if (!alert && roomOpen && !win.classList.contains('minimised')) {
    chatState.unread[roomId] = 0;
    updateChatUnreadBadge();
  }
  saveChatSessionState();
}

async function pollChatRoom(roomId, opts = {}) {
  if (!chatState.openRooms[roomId] && !chatState.rooms[roomId]) return;
  try {
    const after = opts.full ? 0 : (chatState.lastMessageIds[roomId] || 0);
    const data = await chatApi('/chat/rooms/' + encodeURIComponent(roomId) + '/messages?after=' + after);
    if (data.room) mergeChatRooms([data.room]);
    appendChatMessages(roomId, data.messages || [], opts);
  } catch (e) {}
}

function pollKnownChatRooms() {
  Object.keys(chatState.rooms).forEach(roomId => pollChatRoom(roomId));
}

function updateChatUnreadBadge() {
  const badge = document.getElementById('chatUnreadBadge');
  if (!badge) return;
  const total = Object.values(chatState.unread).reduce((a, b) => a + b, 0);
  badge.textContent = total > 99 ? '99+' : String(total);
  badge.classList.toggle('d-none', total <= 0);
}

document.addEventListener('click', (evt) => {
  const win = evt.target.closest?.('.chat-window');
  if (win) {
    const roomId = win.dataset.chatWindow;
    win.classList.remove('has-alert');
    chatState.unread[roomId] = 0;
    updateChatUnreadBadge();
    saveChatSessionState();
  }
});

document.addEventListener('DOMContentLoaded', () => {
  if (!document.getElementById('chatDock')) return;
  refreshChatState();
  updateChatUnreadBadge();
  setInterval(refreshChatState, 10000);
  setInterval(pollKnownChatRooms, 2500);
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
