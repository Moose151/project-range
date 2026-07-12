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

// ── Live range-state banner ─────────────────────────────────────────────────
function rangeStateBannerClass(state) {
  if (state === 'Live') return 'banner-live';
  if (state === 'Closed Loop') return 'banner-closed';
  if (state === 'Testing') return 'banner-testing';
  return 'banner-standby';
}

function rangeStateIcon(state) {
  if (state === 'Live') return 'bi-broadcast-pin blink-icon';
  if (state === 'Closed Loop') return 'bi-arrow-repeat';
  if (state === 'Testing') return 'bi-wrench-adjustable-circle';
  return 'bi-power';
}

function rangeStateTextClass(state) {
  if (state === 'Live') return 'text-danger';
  if (state === 'Closed Loop') return 'text-info';
  if (state === 'Testing') return 'text-warning';
  return 'text-secondary';
}

function rangeStateBannerHtml(state) {
  if (state === 'Live') {
    return '<i class="bi bi-broadcast-pin me-1 blink-icon"></i> <strong>RANGE IS LIVE — RF TRANSMITTING</strong>';
  }
  if (state === 'Closed Loop') {
    return '<i class="bi bi-arrow-repeat me-1"></i> Range State: <strong>Closed Loop</strong> — IF Only';
  }
  if (state === 'Testing') {
    return '<i class="bi bi-wrench-adjustable-circle me-1"></i> Range State: <strong>Testing</strong> — sandbox data only';
  }
  return `<i class="bi bi-power me-1"></i> Range State: <strong>${escapeHtml(state)}</strong>`;
}

function updateLiveRangeStateWidgets(state) {
  document.querySelectorAll('[data-live-range-state-value]').forEach(el => {
    el.className = `fw-bold fs-4 ${rangeStateTextClass(state)}`;
    el.innerHTML = `<i class="bi ${rangeStateIcon(state)} me-1"></i>${escapeHtml(state)}`;
  });
}

// Apply a range-state value to the banner + live widgets. Called by the
// consolidated heartbeat (and pollRangeStateStatus for any direct callers).
function applyRangeState(newState) {
  const banner = document.getElementById('rangeStateBanner');
  if (!banner) return;
  const oldState = banner.dataset.rangeState || '';
  if (!newState || newState === oldState) return;

  banner.dataset.rangeState = newState;
  banner.classList.remove('banner-live', 'banner-closed', 'banner-testing', 'banner-standby');
  banner.classList.add(rangeStateBannerClass(newState));
  const text = document.getElementById('rangeStateBannerText');
  if (text) text.innerHTML = rangeStateBannerHtml(newState);
  updateLiveRangeStateWidgets(newState);

  document.body.dispatchEvent(new Event('range-state-changed'));
  showToast?.(`Range state changed to ${escapeHtml(newState)}`, 'info');

  if (oldState === 'Testing' || newState === 'Testing') {
    window.setTimeout(() => window.location.reload(), 1200);
  }
}

async function pollRangeStateStatus() {
  if (!document.getElementById('rangeStateBanner')) return;
  try {
    const response = await fetch('/range-state/status', { headers: { 'Accept': 'application/json' } });
    if (!response.ok) return;
    const data = await response.json();
    applyRangeState(data.state || '');
  } catch (e) {}
}

// ── Consolidated status heartbeat ────────────────────────────────────────────
// A single poll drives the banner, buzzer/active-count/active-serials badges and
// the CEASE splash — replacing five separate timers (range-state 5s, CEASE 3s,
// buzzer 10s, active-count 10s, active-serials 15s). Paused while the tab is
// hidden; fires immediately when it becomes visible again.
async function heartbeat() {
  try {
    const r = await fetch('/status/heartbeat', { headers: { 'Accept': 'application/json' } });
    // Session idled out or was kicked (login on another terminal): the request
    // was redirected to /login. Bounce this page there too — the heartbeat runs
    // on every authed page, so this replaces the auto-redirect the old per-badge
    // HTMX pollers used to provide.
    if (r.redirected && /\/login/.test(r.url)) { window.location.href = r.url; return; }
    if (!r.ok) return;
    const d = await r.json();
    applyRangeState(d.rangeState || '');
    const bz = document.getElementById('buzzerBadge');
    if (bz && typeof d.buzzerHtml === 'string') bz.innerHTML = d.buzzerHtml;
    const ac = document.getElementById('bannerActiveSignals');
    if (ac) ac.innerHTML = `<i class="bi bi-broadcast me-1"></i>${d.upCount} Up`;
    const sb = document.getElementById('activeSerialsBadge');
    if (sb && typeof d.serialsHtml === 'string') sb.innerHTML = d.serialsHtml;
    document.querySelectorAll('[id^="utilActiveSigCount-"]').forEach(el => { el.textContent = d.upCount; });
    if (d.cease) applyCeaseState(d.cease);
  } catch (e) {}
}

document.addEventListener('DOMContentLoaded', () => {
  if (!document.getElementById('rangeStateBanner')) return;  // only on authed pages
  heartbeat();
  setInterval(() => { if (!document.hidden) heartbeat(); }, 5000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) heartbeat(); });
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
  const canDismiss = (window.userRole || '') !== 'observer';
  const dismissBtn = canDismiss
    ? `<button type="button" class="btn btn-light btn-lg mt-3 fw-bold" onclick="dismissCease()">
          <i class="bi bi-check-lg me-1"></i>Dismiss
        </button>`
    : `<p class="text-white-50 small mt-3 mb-0">Only users and administrators can dismiss CEASE.</p>`;
  root.innerHTML = `
    <div class="cease-overlay" role="alertdialog" aria-label="CEASE alert">
      <div class="cease-box">
        <div class="cease-flash"><i class="bi bi-exclamation-octagon-fill"></i></div>
        <div class="cease-word">CEASE</div>
        <div class="cease-meta">Raised by <strong>${escapeHtml(data.raised_by)}</strong>${data.raised_at ? ' at ' + escapeHtml(data.raised_at) : ''}</div>
        <div class="cease-reason">${escapeHtml(data.reason)}</div>
        ${dismissBtn}
      </div>
    </div>`;
}

function hideCeaseSplash() {
  const root = document.getElementById('ceaseRoot');
  if (root) root.innerHTML = '';
}

// Apply a CEASE state payload (from the heartbeat, or a direct pollCease call
// right after raising/dismissing). Shows/hides the full-screen splash.
function applyCeaseState(data) {
  if (!document.getElementById('ceaseRoot') || !data) return;
  if (data.active) {
    if (ceaseCurrentId !== data.id) { ceaseCurrentId = data.id; showCeaseSplash(data); }
  } else if (ceaseCurrentId !== null) {
    ceaseCurrentId = null;
    hideCeaseSplash();
  }
}

// Kept for the immediate refresh after a raise/dismiss; periodic CEASE polling
// now rides on the consolidated heartbeat.
async function pollCease() {
  if (!document.getElementById('ceaseRoot')) return;
  try {
    const r = await fetch('/cease/state', { headers: { 'Accept': 'application/json' } });
    if (!r.ok) return;
    applyCeaseState(await r.json());
  } catch (e) {}
}

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
      unreadSenders: chatState.unreadSenders,
    }));
  } catch (e) {}
}

const savedChatState = loadChatSessionState();
const chatState = {
  me: null,
  users: [],
  availableUsers: [],
  rooms: {},
  openRooms: {},
  lastMessageIds: savedChatState.lastMessageIds || {},
  roomSeen: {},
  unread: savedChatState.unread || {},
  unreadSenders: savedChatState.unreadSenders || {},
  pollingRooms: {},
  sendingRooms: {},
  typingTimers: {},
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
  const creator = document.getElementById('chatGroupCreator');
  if (!creator) return;
  creator.classList.toggle('d-none');
  if (!creator.classList.contains('d-none')) {
    document.getElementById('chatGroupTitle')?.focus();
  }
}

function chatRoomIcon(room) {
  return room.is_group ? 'bi-people-fill' : 'bi-person-fill';
}

function chatRoomParticipants(room) {
  const people = room.participant_details || [];
  if (!people.length || !chatState.me) return '';
  const names = people
    .filter(p => p.id !== chatState.me.id)
    .map(p => p.display_name)
    .slice(0, 4);
  const extra = Math.max(0, people.length - 1 - names.length);
  return names.join(', ') + (extra ? `, +${extra}` : '');
}

function chatRoomButton(room, { unreadOnly = false } = {}) {
  const unread = chatState.unread[room.id] || 0;
  const senders = [...(chatState.unreadSenders[room.id] || [])].filter(Boolean);
  const senderText = senders.length ? senders.slice(0, 3).join(', ') : '';
  const meta = unreadOnly && senderText
    ? `${unread} new from ${escapeHtml(senderText)}`
    : (chatRoomParticipants(room) || (room.is_group ? 'Group chat' : 'Private chat'));
  return `
    <button type="button" class="chat-room-row ${unread ? 'has-unread' : ''}" onclick="openChatWindow('${escapeHtml(room.id)}')">
      <i class="bi ${chatRoomIcon(room)}"></i>
      <span class="chat-room-main">
        <span class="chat-room-title">${escapeHtml(room.title)}</span>
        <span class="chat-room-meta">${meta}</span>
      </span>
      ${unread ? `<span class="chat-room-count">${unread > 99 ? '99+' : unread}</span>` : ''}
    </button>`;
}

function clearChatUnread(roomId, { redraw = true } = {}) {
  if (!roomId) return;
  chatState.unread[roomId] = 0;
  chatState.unreadSenders[roomId] = [];
  chatState.roomSeen[roomId] = true;
  document.querySelector(`[data-chat-window="${CSS.escape(roomId)}"]`)?.classList.remove('has-alert');
  updateChatUnreadBadge();
  if (redraw) {
    renderChatRoster();
    window.renderDashboardChatWidget?.();
  }
  saveChatSessionState();
}

function splitChatUsersByPresence(users) {
  const onlineIds = new Set((chatState.users || []).map(u => u.id));
  return {
    online: (users || []).filter(u => onlineIds.has(u.id)),
    offline: (users || []).filter(u => !onlineIds.has(u.id)),
  };
}

function chatUserCheckboxRows(users, attrName, { muted = false } = {}) {
  return (users || []).map(u => `
    <label class="d-flex align-items-center gap-2 py-1 ${muted ? 'chat-user-offline' : ''}">
      <input class="form-check-input m-0" type="checkbox" value="${u.id}" ${attrName}>
      <span class="text-truncate">${escapeHtml(u.display_name)}</span>
      ${chatRoleBadge(u)}
    </label>
  `).join('');
}

function chatUserPickerHtml(users, attrName, emptyText) {
  const split = splitChatUsersByPresence(users);
  const onlineHtml = split.online.length
    ? chatUserCheckboxRows(split.online, attrName)
    : `<div class="text-muted small py-1">${escapeHtml(emptyText)}</div>`;
  const offlineHtml = split.offline.length ? `
    <details class="chat-offline-users mt-1">
      <summary>Offline (${split.offline.length})</summary>
      <div class="pt-1">${chatUserCheckboxRows(split.offline, attrName, { muted: true })}</div>
    </details>
  ` : '';
  return onlineHtml + offlineHtml;
}

function renderChatRoster() {
  const online = document.getElementById('chatOnlineUsers');
  const groupUsers = document.getElementById('chatGroupUsers');
  const roomListEl = document.getElementById('chatRoomList');
  const unreadSection = document.getElementById('chatUnreadSection');
  const unreadRoomsEl = document.getElementById('chatUnreadRooms');
  const onlineCountEl = document.getElementById('chatOnlineCount');
  if (!online || !groupUsers || !roomListEl || !unreadSection || !unreadRoomsEl) return;
  const onlineOthers = chatState.users.filter(u => !chatState.me || u.id !== chatState.me.id);
  if (onlineCountEl) {
    onlineCountEl.textContent = onlineOthers.length ? `${onlineOthers.length} online` : 'You’re the only one here';
  }
  const availableOthers = (chatState.availableUsers || chatState.users || []).filter(u => !chatState.me || u.id !== chatState.me.id);
  const rooms = Object.values(chatState.rooms).sort((a, b) => (chatState.unread[b.id] || 0) - (chatState.unread[a.id] || 0) || a.title.localeCompare(b.title));
  const unreadRooms = rooms.filter(room => (chatState.unread[room.id] || 0) > 0);
  unreadSection.classList.toggle('d-none', unreadRooms.length === 0);
  unreadRoomsEl.innerHTML = unreadRooms.map(room => chatRoomButton(room, { unreadOnly: true })).join('');
  roomListEl.innerHTML = rooms.length
    ? rooms.map(room => chatRoomButton(room)).join('')
    : '<div class="chat-empty">No conversations yet.<br>Pick someone below to start chatting.</div>';
  online.innerHTML = onlineOthers.length ? onlineOthers.map(u => `
    <button type="button" class="chat-user-row" onclick="openPrivateChat(${u.id})" title="Start a private chat with ${escapeHtml(u.display_name)}">
      <span class="chat-presence-dot"></span>
      <span class="text-truncate flex-grow-1">${escapeHtml(u.display_name)}</span>
      ${chatRoleBadge(u)}
      <i class="bi bi-chat-dots chat-user-go"></i>
    </button>
  `).join('') : '<div class="chat-empty">No other users are online right now.</div>';
  groupUsers.innerHTML = availableOthers.length
    ? chatUserPickerHtml(availableOthers, 'data-chat-group-user', 'No online users available.')
    : '<div class="text-muted py-2">No users available to add.</div>';
}

function chatRoleBadge(user) {
  const label = user.duty_role || '';
  if (!label) return '';
  const colour = user.duty_role_color || '#6c757d';
  return `<span class="badge chat-role-badge" style="background:${escapeHtml(colour)}">${escapeHtml(label)}</span>`;
}

function chatRoomDutyBadge(room) {
  const label = room.title_duty_role || '';
  if (!label) return '';
  const colour = room.title_duty_role_color || '#6c757d';
  return `<span class="badge chat-role-badge" style="background:${escapeHtml(colour)}">${escapeHtml(label)}</span>`;
}

function chatReceiptHtml(receipt) {
  if (!receipt) return '';
  const state = receipt.state || 'sent';
  const icon = state === 'read' ? 'bi-check2-all' : (state === 'received' ? 'bi-check2-all' : 'bi-check2');
  return `<span class="chat-receipt chat-receipt-${escapeHtml(state)}" data-chat-receipt title="${escapeHtml(receipt.label || '')}"><i class="bi ${icon}"></i>${escapeHtml(receipt.label || '')}</span>`;
}

function updateChatReceipts(roomId, receipts) {
  if (!receipts || !receipts.length) return;
  receipts.forEach(item => {
    document.querySelectorAll(`[data-chat-message-id="${CSS.escape(String(item.id))}"] [data-chat-receipt]`).forEach(node => {
      node.outerHTML = chatReceiptHtml(item.receipt);
    });
  });
}

function chatTypingText(room) {
  const users = room?.typing_users || [];
  if (!users.length) return '';
  if (users.length === 1) return `${users[0].display_name} is typing`;
  if (users.length === 2) return `${users[0].display_name} and ${users[1].display_name} are typing`;
  return `${users[0].display_name} and ${users.length - 1} others are typing`;
}

function renderChatTypingIndicators(roomId) {
  const room = chatState.rooms[roomId];
  const text = chatTypingText(room);
  document.querySelectorAll(`[data-chat-typing-for="${CSS.escape(roomId)}"]`).forEach(node => {
    if (!text) {
      node.classList.add('d-none');
      node.innerHTML = '';
      return;
    }
    node.classList.remove('d-none');
    node.innerHTML = `<span>${escapeHtml(text)}</span><span class="chat-typing-dots"><i></i><i></i><i></i></span>`;
  });
}

const CHAT_EMOJIS = ['😀','😁','😂','🙂','😊','😍','😎','🤔','😬','👍','👌','👏','🙏','✅','⚠️','🚨','📡','🔧','📋','☕'];

function chatEmojiPicker() {
  let picker = document.getElementById('chatEmojiPicker');
  if (picker) return picker;
  picker = document.createElement('div');
  picker.id = 'chatEmojiPicker';
  picker.className = 'chat-emoji-picker shadow-lg d-none';
  picker.innerHTML = CHAT_EMOJIS.map(emoji =>
    `<button type="button" class="chat-emoji-choice" data-chat-emoji="${escapeHtml(emoji)}">${escapeHtml(emoji)}</button>`
  ).join('');
  document.body.appendChild(picker);
  picker.addEventListener('click', evt => {
    const btn = evt.target.closest('[data-chat-emoji]');
    const input = picker._targetInput;
    if (!btn || !input) return;
    insertChatEmoji(input, btn.dataset.chatEmoji || '');
    picker.classList.add('d-none');
  });
  return picker;
}

function insertChatEmoji(input, emoji) {
  if (!input || !emoji) return;
  const start = input.selectionStart ?? input.value.length;
  const end = input.selectionEnd ?? input.value.length;
  input.value = input.value.slice(0, start) + emoji + input.value.slice(end);
  const next = start + emoji.length;
  input.focus();
  input.setSelectionRange?.(next, next);
  input.dispatchEvent(new Event('input', { bubbles: true }));
}

function toggleChatEmojiPicker(button) {
  const form = button?.closest('form');
  const input = form?.querySelector('input[name="body"]');
  if (!button || !input || input.disabled) return;
  const picker = chatEmojiPicker();
  if (!picker.classList.contains('d-none') && picker._targetInput === input) {
    picker.classList.add('d-none');
    return;
  }
  picker._targetInput = input;
  const rect = button.getBoundingClientRect();
  picker.style.left = `${Math.min(rect.left, window.innerWidth - 230)}px`;
  picker.style.top = `${Math.max(8, rect.top - 132)}px`;
  picker.classList.remove('d-none');
}

document.addEventListener('click', evt => {
  const picker = document.getElementById('chatEmojiPicker');
  if (!picker || picker.classList.contains('d-none')) return;
  if (evt.target.closest('#chatEmojiPicker') || evt.target.closest('.chat-emoji-btn')) return;
  picker.classList.add('d-none');
});

function renderAllChatTypingIndicators() {
  Object.keys(chatState.rooms).forEach(renderChatTypingIndicators);
}

async function markChatRoomRead(roomId) {
  if (!roomId) return;
  const lastId = chatState.lastMessageIds[roomId] || chatState.rooms[roomId]?.last_message_id || 0;
  try {
    await chatApi('/chat/rooms/' + encodeURIComponent(roomId) + '/read', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ up_to: lastId }),
    });
  } catch (e) {}
}

function stopChatTyping(roomId) {
  if (!roomId) return;
  if (chatState.typingTimers[roomId]) {
    clearTimeout(chatState.typingTimers[roomId]);
    delete chatState.typingTimers[roomId];
  }
  chatApi('/chat/rooms/' + encodeURIComponent(roomId) + '/typing', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ is_typing: 0 }),
  }).catch(() => {});
}

function sendChatTyping(roomId, input) {
  if (!roomId || !input) return;
  const isTyping = input.value.trim().length > 0;
  chatApi('/chat/rooms/' + encodeURIComponent(roomId) + '/typing', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ is_typing: isTyping ? 1 : 0 }),
  }).catch(() => {});
  if (chatState.typingTimers[roomId]) clearTimeout(chatState.typingTimers[roomId]);
  if (isTyping) chatState.typingTimers[roomId] = setTimeout(() => stopChatTyping(roomId), 2500);
}

function mergeChatRooms(rooms) {
  (rooms || []).forEach(room => {
    const known = Boolean(chatState.rooms[room.id]);
    chatState.rooms[room.id] = room;
    if (!known) chatState.roomSeen[room.id] = false;
    renderChatTypingIndicators(room.id);
  });
  saveChatSessionState();
}

// Drop unread/room state for rooms the server no longer knows about. Chat is
// ephemeral (in-memory on the server), so a restart wipes rooms while stale
// unread counts survive in sessionStorage — that left the launcher badge stuck
// on a number for a room the user could never open to clear. This reconciles
// the local state against the authoritative room list on each refresh.
function reconcileChatState(serverRooms) {
  const validIds = new Set((serverRooms || []).map(r => r.id));
  let changed = false;
  Object.keys(chatState.rooms).forEach(id => { if (!validIds.has(id)) delete chatState.rooms[id]; });
  Object.keys(chatState.unread).forEach(id => {
    if (!validIds.has(id)) { delete chatState.unread[id]; changed = true; }
  });
  Object.keys(chatState.unreadSenders).forEach(id => { if (!validIds.has(id)) delete chatState.unreadSenders[id]; });
  Object.keys(chatState.lastMessageIds).forEach(id => { if (!validIds.has(id)) delete chatState.lastMessageIds[id]; });
  if (changed) { updateChatUnreadBadge(); saveChatSessionState(); }
}

async function refreshChatState() {
  if (!document.getElementById('chatDock')) return;
  try {
    const data = await chatApi('/chat/state');
    chatState.me = data.me;
    chatState.users = data.online_users || [];
    chatState.availableUsers = data.available_users || chatState.users || [];
    reconcileChatState(data.rooms);
    mergeChatRooms(data.rooms);
    pollKnownChatRooms();
    renderAllChatTypingIndicators();
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
  clearChatUnread(roomId, { redraw: false });
  markChatRoomRead(roomId);
  const existing = document.querySelector(`[data-chat-window="${CSS.escape(roomId)}"]`);
  if (existing) {
    existing.classList.remove('minimised', 'has-alert');
    renderChatRoster();
    window.renderDashboardChatWidget?.();
    pollChatRoom(roomId, { full: true, alert: false });
    markChatRoomRead(roomId);
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
      <div class="chat-window-title">
        <span class="text-truncate">${escapeHtml(room.title)}</span>
        ${chatRoomDutyBadge(room)}
      </div>
      ${room.is_group ? `<button type="button" class="btn btn-sm btn-link link-secondary p-0 ms-auto" title="Manage members" onclick="event.stopPropagation(); toggleGroupMembers('${escapeHtml(roomId)}')"><i class="bi bi-person-plus"></i></button>` : ''}
      <button type="button" class="btn btn-sm btn-link link-secondary p-0 ${room.is_group ? '' : 'ms-auto'}" title="Minimise" onclick="event.stopPropagation(); toggleChatWindowMinimised('${escapeHtml(roomId)}')"><i class="bi bi-dash-lg"></i></button>
      <button type="button" class="btn btn-sm btn-link link-secondary p-0" title="Close" onclick="event.stopPropagation(); closeChatWindow('${escapeHtml(roomId)}')"><i class="bi bi-x-lg"></i></button>
    </div>
    ${room.is_group ? `<div class="chat-group-members d-none" data-chat-group-members>${groupMembersPanel(room)}</div>` : ''}
    <div class="chat-window-body" data-chat-messages></div>
    <div class="chat-typing d-none" data-chat-typing-for="${escapeHtml(roomId)}"></div>
    <form class="chat-window-form" onsubmit="sendChatMessage(event, '${escapeHtml(roomId)}')">
      <button type="button" class="btn btn-sm btn-outline-secondary chat-emoji-btn" title="Add emoji" onclick="toggleChatEmojiPicker(this)"><i class="bi bi-emoji-smile"></i></button>
      <input type="text" class="form-control form-control-sm" name="body" autocomplete="off" maxlength="2000" placeholder="Type a message…" oninput="sendChatTyping('${escapeHtml(roomId)}', this)" onblur="stopChatTyping('${escapeHtml(roomId)}')">
      <button type="submit" class="btn btn-sm btn-primary" title="Send"><i class="bi bi-send-fill"></i></button>
    </form>`;
  windows.appendChild(node);
  renderChatTypingIndicators(roomId);
  pollChatRoom(roomId, { full: true, alert: false });
  renderChatRoster();
  window.renderDashboardChatWidget?.();
}

function toggleChatWindowMinimised(roomId) {
  const win = document.querySelector(`[data-chat-window="${CSS.escape(roomId)}"]`);
  if (!win) return;
  win.classList.toggle('minimised');
  if (!win.classList.contains('minimised')) {
    clearChatUnread(roomId);
    markChatRoomRead(roomId);
  }
}

function closeChatWindow(roomId) {
  document.querySelector(`[data-chat-window="${CSS.escape(roomId)}"]`)?.remove();
  delete chatState.openRooms[roomId];
  stopChatTyping(roomId);
  clearChatUnread(roomId);
}

function groupMembersPanel(room) {
  const people = room.participant_details || [];
  const participantIds = new Set(room.participants || []);
  const available = (chatState.availableUsers || chatState.users || []).filter(u => !participantIds.has(u.id));
  const members = people.map(p => `
    <span class="badge rounded-pill text-bg-secondary me-1 mb-1">${escapeHtml(p.display_name)}${chatRoleBadge(p)}</span>
  `).join('') || '<span class="text-muted">No members listed.</span>';
  const addList = available.length
    ? chatUserPickerHtml(available, 'data-chat-add-member', 'No online users available.')
    : '<div class="text-muted small">No users available to add.</div>';
  return `
    <div class="small text-muted mb-1">Members</div>
    <div class="mb-2">${members}</div>
    <div class="small text-muted mb-1">Add users</div>
    <div class="chat-add-members-list">${addList}</div>
    <button type="button" class="btn btn-sm btn-primary mt-2" onclick="addSelectedGroupMembers('${escapeHtml(room.id)}')">
      <i class="bi bi-person-plus me-1"></i>Add Selected
    </button>`;
}

function refreshGroupMembersPanel(roomId) {
  const room = chatState.rooms[roomId];
  const panel = document.querySelector(`[data-chat-window="${CSS.escape(roomId)}"] [data-chat-group-members]`);
  if (room && panel) panel.innerHTML = groupMembersPanel(room);
}

function toggleGroupMembers(roomId) {
  const panel = document.querySelector(`[data-chat-window="${CSS.escape(roomId)}"] [data-chat-group-members]`);
  if (!panel) return;
  panel.classList.toggle('d-none');
  refreshGroupMembersPanel(roomId);
}

async function addSelectedGroupMembers(roomId) {
  const panel = document.querySelector(`[data-chat-window="${CSS.escape(roomId)}"] [data-chat-group-members]`);
  const ids = [...(panel?.querySelectorAll('[data-chat-add-member]:checked') || [])].map(x => x.value);
  if (!ids.length) { showToast?.('Select at least one user to add', 'warning'); return; }
  try {
    const data = await chatApi('/chat/rooms/' + encodeURIComponent(roomId) + '/members', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ participant_ids: ids.join(',') }),
    });
    mergeChatRooms([data.room]);
    refreshGroupMembersPanel(roomId);
    renderChatRoster();
    window.renderDashboardChatWidget?.();
    showToast?.('Group members updated', 'success');
  } catch (e) {
    showToast?.('Could not add group members', 'danger');
  }
}

async function sendChatMessage(evt, roomId) {
  evt.preventDefault();
  if (chatState.sendingRooms[roomId]) return;
  const form = evt.target;
  const input = form.querySelector('input[name="body"]');
  const button = form.querySelector('button[type="submit"]');
  const body = (input?.value || '').trim();
  if (!body) return;
  chatState.sendingRooms[roomId] = true;
  stopChatTyping(roomId);
  input?.toggleAttribute('disabled', true);
  button?.toggleAttribute('disabled', true);
  input.value = '';
  try {
    const data = await chatApi('/chat/rooms/' + encodeURIComponent(roomId) + '/messages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ body }),
    });
    if (data.message) appendChatMessages(roomId, [data.message], { alert: false });
    pollChatRoom(roomId);
  } catch (e) {
    if (input) input.value = body;
    showToast?.('Message not sent', 'danger');
  } finally {
    delete chatState.sendingRooms[roomId];
    input?.toggleAttribute('disabled', false);
    button?.toggleAttribute('disabled', false);
    input?.focus();
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
  const appendedMessages = [];
  messages.forEach(msg => {
    chatState.lastMessageIds[roomId] = Math.max(chatState.lastMessageIds[roomId] || 0, msg.id);
    if (body?.querySelector(`[data-chat-message-id="${CSS.escape(String(msg.id))}"]`)) return;
    const mine = chatState.me && msg.sender_id === chatState.me.id;
    if (!mine) receivedNewFromOther = true;
    appendedMessages.push(msg);
    if (body) {
      const noMessages = body.querySelector('[data-chat-empty]');
      if (noMessages) noMessages.remove();
      body.insertAdjacentHTML('beforeend', `
        <div class="chat-message ${mine ? 'mine' : ''}" data-chat-message-id="${escapeHtml(String(msg.id))}">
          <div class="chat-message-meta">${mine ? 'You' : escapeHtml(msg.sender_name)} · ${escapeHtml(msg.sent_at)} ${mine ? chatReceiptHtml(msg.receipt) : ''}</div>
          <div class="chat-message-bubble">${escapeHtml(msg.body)}</div>
        </div>`);
    }
  });
  if (appendedMessages.length && body) body.scrollTop = body.scrollHeight;
  // Friendly placeholder while a conversation has no messages yet.
  if (body && !body.querySelector('.chat-message') && !body.querySelector('[data-chat-empty]')) {
    body.innerHTML = '<div class="chat-empty" data-chat-empty>No messages yet — say hello 👋</div>';
  }
  const unreadNew = appendedMessages.filter(m => !chatState.me || m.sender_id !== chatState.me.id).length;
  const shouldAlert = receivedNewFromOther && (!roomOpen || win.classList.contains('minimised'));
  if (alert && shouldAlert) {
    if (win) win.classList.add('has-alert');
    chatState.unread[roomId] = (chatState.unread[roomId] || 0) + unreadNew;
    const senders = new Set(chatState.unreadSenders[roomId] || []);
    appendedMessages.filter(m => !chatState.me || m.sender_id !== chatState.me.id).forEach(m => senders.add(m.sender_name));
    chatState.unreadSenders[roomId] = [...senders];
    updateChatUnreadBadge();
    renderChatRoster();
    const room = chatState.rooms[roomId];
    if (room && !roomOpen) showToast?.(`New chat message: ${escapeHtml(room.title)}`, 'info');
  }
  if (!alert && roomOpen && !win.classList.contains('minimised')) {
    clearChatUnread(roomId);
    markChatRoomRead(roomId);
  }
  saveChatSessionState();
}

async function pollChatRoom(roomId, opts = {}) {
  if (!chatState.openRooms[roomId] && !chatState.rooms[roomId]) return;
  if (!opts.full && chatState.pollingRooms[roomId]) return;
  chatState.pollingRooms[roomId] = true;
  try {
    const after = opts.full ? 0 : (chatState.lastMessageIds[roomId] || 0);
    const data = await chatApi('/chat/rooms/' + encodeURIComponent(roomId) + '/messages?after=' + after);
    if (data.room) mergeChatRooms([data.room]);
    appendChatMessages(roomId, data.messages || [], opts);
    updateChatReceipts(roomId, data.receipts || []);
    const win = document.querySelector(`[data-chat-window="${CSS.escape(roomId)}"]`);
    if (win && !win.classList.contains('minimised')) markChatRoomRead(roomId);
  } catch (e) {
  } finally {
    delete chatState.pollingRooms[roomId];
  }
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
    if (!win.classList.contains('minimised')) {
      clearChatUnread(roomId);
      markChatRoomRead(roomId);
    }
  }
});

document.addEventListener('DOMContentLoaded', () => {
  if (!document.getElementById('chatDock')) return;
  refreshChatState();
  updateChatUnreadBadge();
  // Skip chat polls while the tab is hidden (backgrounded/forgotten terminals
  // stop hammering the server); resume immediately when it becomes visible.
  setInterval(() => { if (!document.hidden) refreshChatState(); }, 10000);
  setInterval(() => { if (!document.hidden) pollKnownChatRooms(); }, 2500);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) { refreshChatState(); pollKnownChatRooms(); }
  });
});

function markChatOffline() {
  if (!document.getElementById('chatDock')) return;
  try {
    if (navigator.sendBeacon) {
      navigator.sendBeacon('/chat/offline', new Blob([], { type: 'application/x-www-form-urlencoded' }));
    } else {
      fetch('/chat/offline', { method: 'POST', keepalive: true });
    }
  } catch (e) {}
}

window.addEventListener('pagehide', markChatOffline);

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
function calcKey(id) {
  return calcState[id] || (calcState[id] = {
    expr: '',
    current: '0',
    hasResult: false,
    awaitingOperand: false,
  });
}

function calcPress(id, val) {
  const s = calcKey(id);
  window._lastCalcId = id;
  const disp = document.getElementById('mathCalcInput-' + id);
  const expr = document.getElementById('mathCalcExpr-' + id);
  if (!disp) return;

  if (val === 'C') {
    s.expr = ''; s.current = '0'; s.hasResult = false; s.awaitingOperand = false;
  } else if (val === '⌫') {
    if (s.awaitingOperand) s.current = '0';
    else if (s.current.length > 1) s.current = s.current.slice(0, -1);
    else s.current = '0';
    s.hasResult = false;
  } else if (val === '±') {
    if (s.current !== '0') s.current = s.current.startsWith('-') ? s.current.slice(1) : '-' + s.current;
  } else if (val === '%') {
    const v = parseFloat(s.current);
    if (!isNaN(v)) s.current = String(v / 100);
  } else if (['+', '−', '×', '÷'].includes(val)) {
    if (s.expr && !s.hasResult && !s.awaitingOperand) {
      // chain: evaluate current expression first
      try { s.current = String(evalCalcExpr(s.expr + s.current)); } catch (e) {}
    }
    s.expr = s.current + ' ' + val + ' ';
    s.hasResult = false;
    s.awaitingOperand = true;
  } else if (val === '=') {
    if (s.expr && !s.awaitingOperand) {
      const full = s.expr + s.current;
      try {
        const result = evalCalcExpr(full);
        if (expr) expr.textContent = full + ' =';
        s.current = formatCalcNum(result);
        s.expr = '';
        s.hasResult = true;
        s.awaitingOperand = false;
      } catch (e) { s.current = 'Error'; s.expr = ''; }
    }
  } else if (val === '.') {
    if (s.hasResult || s.awaitingOperand || s.current === 'Error') {
      if (s.hasResult) s.expr = '';
      s.current = '0.';
      s.hasResult = false;
      s.awaitingOperand = false;
    }
    else if (!s.current.includes('.')) s.current += '.';
  } else {
    // digit
    if (s.hasResult || s.awaitingOperand || s.current === 'Error') {
      if (s.hasResult) s.expr = '';
      s.current = val;
      s.hasResult = false;
      s.awaitingOperand = false;
    }
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
  return `<div class="p-2 math-calc" data-calc-id="${id}" tabindex="0">
    <div class="math-calc-expr mb-1" id="mathCalcExpr-${id}"></div>
    <input id="mathCalcInput-${id}" class="form-control form-control-sm text-end font-monospace mb-2"
           value="0" readonly style="font-size:1.4rem;height:auto;padding:.3rem .6rem">
    <div class="calc-btn-grid">${grid}</div>
    <div class="text-muted small mt-2 text-center">Tip: use your keyboard / numpad (0-9 · + − × ÷ · Enter = · Backspace · Esc clears)</div>
  </div>`;
}

// Keyboard / numpad support for the basic calculator. Routes key presses to the
// active calculator: the one the user last interacted with, the one focus is
// inside, or the only calculator on the page.
function activeCalcId() {
  const calcs = document.querySelectorAll('.math-calc[data-calc-id]');
  if (!calcs.length) return null;
  const focused = document.activeElement?.closest?.('.math-calc[data-calc-id]');
  if (focused) return focused.getAttribute('data-calc-id');
  const tag = document.activeElement?.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return null;
  if (calcs.length === 1) return calcs[0].getAttribute('data-calc-id');
  if (window._lastCalcId && document.querySelector(`.math-calc[data-calc-id="${CSS.escape(window._lastCalcId)}"]`)) {
    return window._lastCalcId;
  }
  return null;
}

const CALC_KEY_MAP = {
  '+': '+', '-': '−', '*': '×', '/': '÷',
  '=': '=', 'Enter': '=', 'Backspace': '⌫', 'Delete': 'C',
  'Escape': 'C', '.': '.', ',': '.', '%': '%',
};

document.addEventListener('keydown', (evt) => {
  if (evt.ctrlKey || evt.metaKey || evt.altKey) return;
  let val;
  if (/^[0-9]$/.test(evt.key)) val = evt.key;
  else if (evt.key in CALC_KEY_MAP) val = CALC_KEY_MAP[evt.key];
  else return;
  const id = activeCalcId();
  if (!id) return;
  evt.preventDefault();
  calcPress(id, val);
});

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

// ── Global command palette + recently viewed pages ──────────────────────────
const RECENT_PAGES_KEY = 'rangeRecentPages_v1';
let commandPaletteTimer = null;

function recentPages() {
  try { return JSON.parse(localStorage.getItem(RECENT_PAGES_KEY) || '[]'); } catch (e) { return []; }
}

function saveRecentPages(items) {
  try { localStorage.setItem(RECENT_PAGES_KEY, JSON.stringify(items.slice(0, 8))); } catch (e) {}
}

function rememberCurrentPage() {
  if (!document.body || location.pathname === '/login') return;
  const title = (document.title || 'SEW Range').replace(/\s+[-–]\s+SEW Range$/, '').trim();
  const url = location.pathname + location.search;
  const items = recentPages().filter(item => item.url !== url);
  items.unshift({ title, url, at: Date.now() });
  saveRecentPages(items);
}

function renderRecentPages() {
  const target = document.getElementById('recentPagesList');
  if (!target) return;
  const items = recentPages();
  target.innerHTML = items.length ? items.map(item => `
    <a href="${escapeHtml(item.url)}" class="list-group-item list-group-item-action py-2">
      <i class="bi bi-clock-history me-2 text-muted"></i>${escapeHtml(item.title || item.url)}
      <span class="text-muted small ms-2">${escapeHtml(item.url)}</span>
    </a>`).join('') : '<div class="text-muted small px-2 py-2">No recent pages yet.</div>';
}

function renderCommandResults(results) {
  const target = document.getElementById('commandPaletteResults');
  if (!target) return;
  if (!results.length) {
    target.innerHTML = '<div class="text-muted small px-3 py-3">No matches.</div>';
    return;
  }
  target.innerHTML = results.map(item => `
    <a href="${escapeHtml(item.url)}" class="list-group-item list-group-item-action d-flex align-items-center gap-2">
      <i class="bi ${escapeHtml(item.icon || 'bi-search')} text-primary"></i>
      <span class="flex-grow-1">
        <span class="fw-semibold">${escapeHtml(item.label)}</span>
        ${item.detail ? `<span class="text-muted small d-block">${escapeHtml(item.detail)}</span>` : ''}
      </span>
      <span class="badge bg-secondary">${escapeHtml(item.kind || 'Result')}</span>
    </a>`).join('');
}

async function searchCommandPalette() {
  const input = document.getElementById('commandPaletteInput');
  if (!input) return;
  const q = input.value || '';
  const target = document.getElementById('commandPaletteResults');
  if (target) target.innerHTML = '<div class="text-muted small px-3 py-3">Searching...</div>';
  try {
    const resp = await fetch('/quick-search?q=' + encodeURIComponent(q), { headers: { 'Accept': 'application/json' } });
    const data = await resp.json();
    renderCommandResults(data.results || []);
  } catch (e) {
    if (target) target.innerHTML = '<div class="text-danger small px-3 py-3">Search failed.</div>';
  }
}

function openCommandPalette() {
  const modalEl = document.getElementById('commandPaletteModal');
  const input = document.getElementById('commandPaletteInput');
  if (!modalEl || !window.bootstrap) return;
  renderRecentPages();
  window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
  setTimeout(() => { input?.focus(); input?.select(); searchCommandPalette(); }, 120);
}

document.addEventListener('DOMContentLoaded', () => {
  rememberCurrentPage();
  const input = document.getElementById('commandPaletteInput');
  input?.addEventListener('input', () => {
    clearTimeout(commandPaletteTimer);
    commandPaletteTimer = setTimeout(searchCommandPalette, 120);
  });
});

document.addEventListener('keydown', event => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault();
    openCommandPalette();
  }
});

// ── Shared Spectrum Chart ─────────────────────────────────────────────────────
function specToMHz(val, unit) {
  if (val === null || val === undefined) return null;
  const num = parseFloat(val);
  if (isNaN(num)) return null;
  return unit === 'GHz' ? num * 1000 : num;
}

function specModRate(modulation) {
  const mod = String(modulation || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
  if (!mod) return 1;
  if (mod.includes('BPSK')) return 1;
  if (mod.includes('QPSK') || mod.includes('OQPSK') || mod.includes('4PSK')) return 2;
  if (mod.includes('8PSK') || mod.includes('8QAM')) return 3;
  if (mod.includes('16APSK') || mod.includes('16QAM')) return 4;
  if (mod.includes('32APSK') || mod.includes('32QAM')) return 5;
  if (mod.includes('64QAM')) return 6;
  if (mod.includes('128QAM')) return 7;
  if (mod.includes('256QAM')) return 8;
  const explicit = mod.match(/(?:^|[^0-9])([1-9]\d*)\s*(?:ARY|QAM|APSK|PSK)/);
  if (explicit) return Math.max(1, Math.log2(parseInt(explicit[1], 10)));
  return 1;
}

function specOccupiedBandwidthMHz(signal) {
  const ROLLOFF = 0.25;
  const sr = parseFloat(signal?.symbolRate);
  if (!sr || sr <= 0) return 0;
  return (sr / specModRate(signal?.modulation)) * (1 + ROLLOFF) / 1000;
}

function specFreqStep(span) {
  if (span > 5000) return 1000;
  if (span > 2000) return 500;
  if (span > 1000) return 200;
  if (span > 500) return 100;
  if (span > 200) return 50;
  if (span > 100) return 20;
  if (span > 50) return 10;
  if (span > 20) return 5;
  return 1;
}

function specFreqPair(signal, freqMode = 'if') {
  return freqMode === 'rf'
    ? [signal.txRf, signal.rxRf]
    : [signal.txIf, signal.rxIf];
}

function specAutoSettings(signals, view = 'both', freqMode = 'if') {
  const freqs = [];
  (signals || []).forEach(s => {
    const [txRaw, rxRaw] = specFreqPair(s, freqMode);
    const tx = specToMHz(txRaw, s.freqUnit), rx = specToMHz(rxRaw, s.freqUnit);
    const halfBw = specOccupiedBandwidthMHz(s) / 2;
    if (tx !== null && view !== 'rx') freqs.push(tx - halfBw, tx + halfBw);
    if (rx !== null && view !== 'tx') freqs.push(rx - halfBw, rx + halfBw);
  });
  if (!freqs.length) return { centreFreq: 1000, span: 500 };
  freqs.sort((a, b) => a - b);
  const lo = freqs[0], hi = freqs[freqs.length - 1], mid = (lo + hi) / 2;
  return {
    centreFreq: Math.round(mid * 10) / 10,
    span: Math.round(Math.max(hi - lo, 50) * 1.6 * 10) / 10,
  };
}

function specSignalEdges(signal, view = 'both', freqMode = 'if') {
  const bwMHz = Math.max(0, specOccupiedBandwidthMHz(signal));
  const edges = [];
  const [txFreq, rxFreq] = specFreqPair(signal, freqMode);
  [[txFreq, true], [rxFreq, false]].forEach(([freq, isTx]) => {
    if (freq === null || freq === undefined) return;
    if (view === 'tx' && !isTx) return;
    if (view === 'rx' && isTx) return;
    const fMHz = specToMHz(freq, signal.freqUnit);
    if (fMHz === null) return;
    edges.push([fMHz - bwMHz / 2, fMHz + bwMHz / 2]);
  });
  return edges;
}

function specHasVisibleSignals(signals, centreFreq, span, view = 'both', freqMode = 'if') {
  if (!span || span <= 0) return false;
  const minFreq = centreFreq - span / 2, maxFreq = centreFreq + span / 2;
  return (signals || []).some(signal =>
    specSignalEdges(signal, view, freqMode).some(([lo, hi]) => hi >= minFreq && lo <= maxFreq)
  );
}

// signals: [{name, txIf, rxIf, txRf, rxRf, freqUnit, symbolRate, power, dimmed?}]
// view: 'both' | 'tx' | 'rx'
// freqMode: 'if' | 'rf'
function drawSpectrumChart(canvas, signals, centreFreq, span, guardLeft, guardRight, view, freqMode = 'if') {
  if (!canvas || !signals) return;
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const w = rect.width || canvas.offsetWidth || 600;
  const h = rect.height || canvas.offsetHeight || 280;
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  const padL = 68, padR = 20, padT = 32, padB = 50;
  const plotW = w - padL - padR, plotH = h - padT - padB;
  const minFreq = centreFreq - span / 2, maxFreq = centreFreq + span / 2;
  const minPow = -120, maxPow = 10;

  function fToX(f) { return padL + (f - minFreq) / (maxFreq - minFreq) * plotW; }
  function pToY(p) { return padT + (1 - (p - minPow) / (maxPow - minPow)) * plotH; }

  const bg = ctx.createLinearGradient(0, padT, 0, padT + plotH);
  bg.addColorStop(0, '#090d12'); bg.addColorStop(1, '#111820');
  ctx.fillStyle = bg; ctx.fillRect(0, 0, w, h); ctx.fillRect(padL, padT, plotW, plotH);

  const freqStep = specFreqStep(span);
  const startF = Math.ceil(minFreq / freqStep) * freqStep;
  ctx.font = '10px monospace';
  for (let f = startF; f <= maxFreq + 0.001; f = Math.round((f + freqStep) * 1000) / 1000) {
    const x = fToX(f);
    if (x < padL || x > padL + plotW) continue;
    ctx.strokeStyle = 'rgba(255,255,255,0.06)'; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
    ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, padT + plotH); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = '#777'; ctx.textAlign = 'center';
    const lbl = f >= 1000 ? (f / 1000).toFixed(3).replace(/\.?0+$/, '') + ' GHz' : f + ' MHz';
    ctx.fillText(lbl, x, padT + plotH + 16);
  }

  ctx.textAlign = 'right';
  for (let p = -120; p <= 10; p += 20) {
    const y = pToY(p);
    if (y < padT || y > padT + plotH) continue;
    ctx.strokeStyle = 'rgba(255,255,255,0.06)'; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(padL + plotW, y); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = '#777'; ctx.font = '10px monospace';
    ctx.fillText(p + ' dBm', padL - 5, y + 3);
  }

  ctx.save();
  ctx.translate(11, padT + plotH / 2); ctx.rotate(-Math.PI / 2);
  ctx.fillStyle = '#888'; ctx.font = '10px monospace'; ctx.textAlign = 'center';
  ctx.fillText('Power (dBm)', 0, 0);
  ctx.restore();
  ctx.fillStyle = '#888'; ctx.font = '10px monospace'; ctx.textAlign = 'center';
  ctx.fillText((freqMode === 'rf' ? 'RF' : 'IF') + ' Frequency', padL + plotW / 2, padT + plotH + 42);

  ctx.save();
  ctx.beginPath(); ctx.rect(padL, padT, plotW, plotH); ctx.clip();

  if (guardLeft !== null || guardRight !== null) {
    const gl = guardLeft !== null ? fToX(guardLeft) : padL;
    const gr = guardRight !== null ? fToX(guardRight) : padL + plotW;
    ctx.fillStyle = 'rgba(200,40,40,0.13)';
    if (guardLeft !== null) ctx.fillRect(padL, padT, Math.max(0, gl - padL), plotH);
    if (guardRight !== null) ctx.fillRect(Math.min(gr, padL + plotW), padT, Math.max(0, padL + plotW - gr), plotH);
    if (guardLeft !== null && guardRight !== null) {
      ctx.fillStyle = 'rgba(25,135,84,0.07)';
      ctx.fillRect(Math.max(gl, padL), padT, Math.min(gr, padL + plotW) - Math.max(gl, padL), plotH);
    }
  }

  [[guardLeft, 'left'], [guardRight, 'right']].forEach(([gf, side]) => {
    if (gf === null || gf === undefined) return;
    const x = fToX(gf);
    ctx.strokeStyle = '#ffc107'; ctx.lineWidth = 2; ctx.setLineDash([6, 4]);
    ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, padT + plotH); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = '#ffc107'; ctx.font = 'bold 10px monospace';
    ctx.textAlign = side === 'left' ? 'left' : 'right';
    const lbl = gf >= 1000 ? (gf / 1000).toFixed(3) + ' GHz' : gf + ' MHz';
    ctx.fillText((side === 'left' ? '◀ ' : '▶ ') + lbl, x + (side === 'left' ? 4 : -4), padT + 14);
  });

  signals.forEach(sig => {
    const bwMHz = Math.max(0, specOccupiedBandwidthMHz(sig));
    const pow = (sig.power !== null && sig.power !== undefined) ? sig.power : -60;
    const alpha = sig.dimmed ? '22' : '44';

    const [txFreq, rxFreq] = specFreqPair(sig, freqMode);
    [[txFreq, true], [rxFreq, false]].forEach(([freq, isTx]) => {
      if (freq === null || freq === undefined) return;
      if (view === 'tx' && !isTx) return;
      if (view === 'rx' && isTx) return;
      const fMHz = specToMHz(freq, sig.freqUnit);
      if (fMHz === null) return;
      const lo = fMHz - bwMHz / 2, hi = fMHz + bwMHz / 2;
      if (hi < minFreq || lo > maxFreq) return;
      const x1 = fToX(Math.max(lo, minFreq)), x2 = fToX(Math.min(hi, maxFreq));
      const blockW = Math.max(2, x2 - x1);
      const drawX = (x2 - x1) < 2 ? (x1 + x2) / 2 - blockW / 2 : x1;
      const yTop = pToY(pow), yBot = pToY(minPow);
      const colour = isTx ? '#0d6efd' : '#198754';
      ctx.fillStyle = colour + alpha;
      ctx.fillRect(drawX, yTop, blockW, yBot - yTop);
      ctx.strokeStyle = colour; ctx.lineWidth = 2; ctx.setLineDash([]);
      ctx.strokeRect(drawX, yTop, blockW, yBot - yTop);
      if (blockW > 12) {
        ctx.fillStyle = sig.dimmed ? '#888' : '#ddd';
        ctx.font = '10px sans-serif'; ctx.textAlign = 'center';
        ctx.fillText(sig.name + (isTx ? ' TX' : ' RX'), drawX + blockW / 2, Math.max(yTop - 5, padT + 12));
      }
    });
  });

  ctx.restore();
  ctx.strokeStyle = 'rgba(255,255,255,0.18)'; ctx.lineWidth = 1; ctx.setLineDash([]);
  ctx.strokeRect(padL, padT, plotW, plotH);
  const cx = fToX(centreFreq);
  if (cx >= padL && cx <= padL + plotW) {
    ctx.strokeStyle = 'rgba(255,255,255,0.12)'; ctx.lineWidth = 1; ctx.setLineDash([2, 4]);
    ctx.beginPath(); ctx.moveTo(cx, padT); ctx.lineTo(cx, padT + plotH); ctx.stroke();
    ctx.setLineDash([]);
  }
}
