// Bootstrap tooltip init on every page
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
    new bootstrap.Tooltip(el);
  });
});

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
