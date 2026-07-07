# Project Range — Roadmap to v1.0

**Current version:** `0.24.1` (beta) · shown in the top-right navbar area and in `app/config.py`.

This roadmap takes Project Range from its current beta to a **1.0 operational
release** — a stable, documented system deployed on the range network, meeting
the MVP success criteria in [Scope.txt](Scope.txt), with the day-to-day features
operators have asked for.

For a chronological release-by-release summary, see [VERSION_HISTORY.md](VERSION_HISTORY.md).

## Versioning

We use a simple semantic scheme while in beta:

- **0.x.y** — beta. Minor (`x`) = a milestone of features below; patch (`y`) = fixes/small tweaks.
- **1.0.0** — first release blessed for operational use on the range.
- Bump the single source of truth in `app/config.py` (`APP_VERSION`); the UI badge follows it.

---

## ✅ Already delivered (through 0.18.5)

Core of the MVP scope is in place:

- RF frequency calculator (TxIF/TxRF/RxRF/RxIF from one known value) + frequency templates
- Power converter (dBm/dBW/W), gain/loss chain, EIRP
- Signal logging with per-signal power-warning thresholds + band/frequency validation
- Live dashboard (status, transmitting indicator, drag-tab merge/split, steppers, column toggles, bulk-submit)
- Range state management (Standby/Closed Loop/Live) with reason + two-person administrator auth
- Package-level RF config (TxLO/RxLO/TTF) with one-frequency auto-calc across signals
- Documentation/wiki module, structured XLSX export, shift handover
- User auth (user/administrator), audit log, "remember this terminal"
- Device registry with TCP reachability, routing matrix (splitter/combiner), topology view
- Incident/fault reporting, hard-delete for logs, security hardening (CSRF, headers, throttle, forced PW change)
- Serial pending/pre-create: serials can be saved as pending before starting
- Log readability: signal log rows identify changed parameters and history lifecycle rows use calmer colours
- Settings dropdown and more distinct light/dark theme palettes
- Dashboard Zulu/local clock widget; admin-managed local timezone; optional local-time log view
- Device registry includes Antenna as a device type
- SQLite backup script with documented backup/restore procedure
- Dashboard utility widgets: quick notes, docs reference, extra clocks, quick links
- Instant text chat: online user list, private and group chats, unread alerts, minimisable chat windows, role tags, and dashboard chat widget
- Testing range state: administrator-only Testing mode with isolated packages, serials, logs, devices, CDA windows, incidents, and CEASE records
- Account roles renamed to Administrator/User/Observer, with account rename and archive flow
- Dashboard Engaged signal toggle with immediate save
- CBM-400 package import/export using modem-style text config files
- Live shared-state refresh: range-state banner updates across logged-in browsers, and dashboard signal tables poll every 5 seconds with immediate refresh on range-state change
- Source/CBM package cleanup: CBM modems appear as Sources, package imports split FEC/Inner Code/Symbol Rate, Carrier Label removed, and Eb/No is reserved for modem-derived reads
- Dashboard Force CBM Update button appears on active serial widgets with mapped CBM signals
- CBM symbol-rate import/export conversion and imported package edit dropdown preservation
- CBM Force Update issue details are written to audit logs and surfaced in dashboard toast messages
- Imported package signals can be edited reliably and their CBM Source mapping corrected after import
- CBM imports can capture package RF details before file selection, append configs into an existing package, and auto-calculate TxRF/RxRF from package LOs plus imported IF values
- Package deletion is blocked with a clear error when a package is still assigned to any serial, preventing internal server errors and preserving serial history links
- Dashboard Source edits on active serial signals now update the underlying package CBM source mapping as well as the displayed signal log row
- Package/dashboard Source controls include an explicit **No modem assigned** state so CBM sync only follows the signal currently mapped to a real modem
- Single-session enforcement: a user logging in somewhere else invalidates their previous session
- Dashboard quick-edit now stages all signal parameters/frequencies into one serial-widget bulk submit
- Dashboard and EBEM sync recalculate TxRF/RxRF when TxIF/RxIF or any related frequency changes
- Signal packages assigned only to closed serials can now be deleted while preserving log history
- Chat presence ages out faster and sends an offline beacon on browser/page close
- EBEM/CBM read-only sync runs automatically every 5 seconds by default (`CBM_AUTO_SYNC_SECONDS`, `0` disables)
- In-app Version History page available at `/docs/version-history`
- Observers can request documentation edits through the approval queue
- Chat launcher now shows unread rooms, room list, sender context, and group member management
- Chat delivery now de-dupes overlapping polls/sends, keeps open chat windows live, clears viewed notification bubbles reliably, and separates offline group-add candidates into a collapsed list
- Observer accounts can use calculators, docs, chat, CEASE, duty-role selection, dashboard Engaged toggles, and incident submission-for-approval while package/serial configuration remains read-only with clear hints
- CDA tables can be assigned to active serials directly from the CDA table detail page after windows are created
- Basic Calculator operator entry now moves cleanly to the second operand without requiring backspace
- Basic Calculator accepts keyboard/numpad input; Preferences shows account type and a per-role permissions table; chat unread bubble no longer sticks on rooms that no longer exist; document approval flags concurrent-edit conflicts before overwriting newer changes
- Chat panel tidy-up: clearer Unread/Conversations/People-online sections, online count + ephemeral-message note, labelled New group button and tidier group creator, friendlier empty states and composer
- **0.6.0:** TxLO/RxLO naming, version badge, fully offline (LAN) styling, Docker deploy on port 7474

---

## 0.7.0 — UI & presentation polish ✅ (shipped, except logo)

Theme: make it look and feel like an operations tool. *(User-requested batch.)*

- [x] **Range logo** — SEW Range eagle badge added to the navbar brand, login page, and favicon; app re-branded "SEW Range". A light gold accent (brand text, navbar underline, version badge) was applied from the logo.
- [x] **Selectable named themes** (0.9.1) — a **theme system** with two independent axes, both remembered per terminal and applied pre-paint (no flash):
  1. **Theme** (`data-theme`) — colour palette chosen on the Preferences page (swatch buttons).
  2. **Light / dark mode** (`data-bs-theme`) — the existing navbar toggle, working with every theme.

  Themes shipped, each in light **and** dark: **Classic** (Bootstrap blue, default), **SEW Gold** (logo palette), **Night Ops** (red/amber, dark variant tints the canvas for a darkened ops room), **Spectrum** (blue/teal). The accent maps onto Bootstrap "primary" surfaces (buttons, links, active nav, badges, focus rings, checkboxes); the SEW Range logo/brand stays gold across all themes.
- [x] **Navbar / UI tidy** — grouped right-side controls (preferences link, theme toggle, logout); user name now links to preferences.
- [x] **Light / dark mode** — toggle in the navbar (Bootstrap 5.3 `data-bs-theme`), remembered per terminal via localStorage, applied pre-paint to avoid flash; default dark; works on login too.
- [x] **User-selected default units** (MHz/GHz, dBm/dBW) — stored per user, set on the Preferences page, applied to the RF and Power calculators. Scope §12.5.
- [x] Centralise the version string into a shared template global (`app/templating.py`); removed the hard-coded fallback.

## 0.8.0 — RF distribution & device status ✅ (shipped)

Theme: visibility of the physical signal path. *(User-requested splitter page + Scope §11.9.)*

- [x] **Splitter / combiner routing page** — crossbar matrix (each output routed from an input) **plus** a free-text label on every input/output port. Port counts configurable per device (default 16/16). Persisted and audited (`DEVICE_ROUTING`).
- [x] **Basic device status checks** — live up/down/no-check badges via a non-blocking concurrent TCP reachability probe (`/devices/status`, polled every 15s); no hardware control. Scope §11.9.
- [x] **Device registry** (name, type, host/IP, check port, location, port counts) — administrator-managed CRUD, audited; underpins both of the above. New "Devices" nav entry.

## 0.9.3 — Device enhancements + serial pre-create ✅ (shipped 2026-06-26)

Theme: richer device modelling and operational pre-planning.

- [x] **Extended device types** — IP Switch, 10MHz Reference, Sync Server, DC Injector added to the registry dropdown. IP Switch is intentionally *not* a routing device (no crossbar matrix) — it gets topology links only.
- [x] **Device name vs model** — `RFDevice` now has `name` (instance, e.g. `CBM-400-1`) and `device_model` (product, e.g. `CBM-400`) as separate fields. Both shown in the devices table. Migration: `ALTER TABLE rf_devices ADD COLUMN device_model VARCHAR(128)`.
- [x] **Web GUI link** — `has_web_gui` boolean per device (checkbox in add/edit). When set, an "Open" link button appears in the devices table pointing to `http://<host>/`. Migration: `ALTER TABLE rf_devices ADD COLUMN has_web_gui BOOLEAN DEFAULT 0`.
- [x] **Topology view** (`/devices/topology`) — tabbed RF / IP / Clock / All views. SVG diagram auto-positioned by device layer type. Colour-coded links (RF=gold, IP=teal, Clock=purple, Power=red). Connection list with delete for administrators. Administrator add-connection form with port labels + port index for routing integration.
- [x] **`DeviceLink` model** — directed connection between two RFDevices (from/to device, port label, port index, link_type, label). Port index enables routing page auto-hints.
- [x] **Routing page auto-hints** — the combiner/splitter routing page reads `DeviceLink` records and pre-populates port label fields with the name of the connected device (and shows a "linked: DeviceName" hint below unlabelled ports).
- [x] **Serial pre-create / pending serials** — "Save as Pending" button on the serial create form saves a serial with `is_started=False`. Pending serials appear in their own section at the top of `/serials` with Start and Delete buttons. Serials can now be prepared in advance and started when needed.

## 0.9.4 — Log readability ✅ (shipped 2026-06-26)

Theme: make audit trails easier to scan under pressure.

- [x] **Changed-parameter highlighting** — `/logs` and `/history/{serial_id}` compare each signal log against the previous entry for the same signal in the same serial. A new "Changed" column summarizes changed fields, and visible changed cells are subtly highlighted.
- [x] **Calmer history lifecycle rows** — `SerialStart`, `SerialEnd`, and narrative note rows in serial history now use custom muted colours instead of the bright Bootstrap warning row.

## 0.9.5 — Settings and theme polish ✅ (shipped 2026-06-26)

Theme: quick user-facing polish before the dashboard clock work.

- [x] **Settings discoverability** — main navbar now has a visible Settings dropdown with Your Preferences, Password, and administrator-only Admin Config. This covers the immediate "where do I change themes/units/config?" issue.
- [x] **More distinct themes** — palette selection now changes body background, navbar, cards, borders, and muted panels as well as the accent colour. Light mode now uses softer backgrounds, darker body text, and stronger borders instead of stark Bootstrap white.
- [x] **Login theme toggle polish** — login page sun/moon icon now syncs with the saved light/dark mode on load; CSS cache key bumped to `app.css?v=11`.

## 0.9.0 — Operational hardening ✅ (security + features shipped; infra deferred)

Theme: ready to trust with real operations. *(Scope §13, Phase 4.)*
See the **Security hardening** section below for the security items shipped in 0.9.0.

- [x] **Soft / hard log delete** — soft delete (recoverable) for everyone; administrator-only restore and permanent hard-delete (two-step: only on already soft-deleted entries). Audited. Scope §4.10.
- [x] **Administrator approval for going Live** — going Live requires a safety acknowledgment, and an administrator must authorise (users supply an administrator's credentials = two-person). Approver recorded in the state log + audit. Scope §12.2.
- [x] **Incident / fault reporting** — log incidents (severity/status/affected/serial), update status with resolution, CSV export, audited; new "Incidents" nav with open count. Scope §12.2.
- [x] **Backups** — scripted SQLite backup and documented restore procedure shipped in 0.10.1. Schedule with cron or Windows Task Scheduler.
- [~] **PostgreSQL option** — **deferred** (your call — no infra to stand up yet). Support Postgres via `DATABASE_URL` with a real migration tool (Alembic).
- [~] **HTTPS/TLS** — **deferred** (your call). Reverse-proxy/self-signed setup for the range network. Session cookies are already `SameSite=Strict` + ready for `Secure` (`SESSION_HTTPS_ONLY=1`).

## 0.10.0 — Dashboard widgets & Settings UX ✅ (shipped 2026-06-26)

Theme: discoverability and at-a-glance ops info. *(User-requested.)*

- [x] **Settings area** — a clear, discoverable **Settings** entry (nav item / gear menu) that consolidates configuration in one place:
  - **Per-user (Preferences):** theme + light/dark, default units. *(These live on the existing `/preferences` page today, reached by Settings or the user's display name.)*
  - **Admin (Config):** the administrator-only `/config` page (modulation/FEC/sources/antennas/registry/freq templates, global local timezone).
  - Shipped as a Settings dropdown grouping Preferences, Password, and administrator Admin Config. A dedicated tabbed `/settings` page remains optional if more settings are added later.
- [x] **Dashboard clock widget** — a **Zulu (UTC) time** clock plus **local time**, where local time follows an administrator-set global IANA timezone under `/config` → System. Implemented as a dashboard widget that can be reordered, collapsed, hidden, and re-shown; updates live client-side and persists layout in localStorage.
- [x] **Zulu-first logs with optional local time** — `/logs` and `/history/{serial_id}` always show Zulu timestamps (`Z` suffix). A "Show local time" checkbox adds a local-time line using the configured timezone. CSV/XLSX exports label timestamps as `Timestamp (Zulu)`.
- [x] **Antenna device type** — "Antenna" added to the Devices registry type dropdown and topology renderer.

## 0.10.1 — Backup script ✅ (shipped 2026-06-26)

Theme: close an operational release gap with a simple, schedulable backup path.

- [x] **SQLite backup script** — `scripts/backup_db.py` copies `/app/data/range.db` out of the Docker Compose `web` service into `./backups/range-<UTC>.db`.
- [x] **Retention option** — `--keep N` prunes older backup files, making it suitable for cron or Windows Task Scheduler.
- [x] **Restore documentation** — `docs/DEPLOY.md` now documents stop/copy/start restore steps and backup access-control warning.

## 0.12.0 — CDA Windows ✅ (shipped 2026-06-29)

Theme: controlled data area time-window management and live dashboard countdown.

- [x] **CDA Tables** — administrator-managed named schedules of daily CDA time windows (Zulu). Each table holds any number of windows with a start time, end time, optional label, and optional max power (dBm). Audited CRUD at `/cda`.
- [x] **Window types** — blank max-power = **No Fire** (transmit prohibited); a max-power value = **Reduced Power** limit. Both types displayed with colour-coded badges.
- [x] **Serial assignment** — CDA tables are assigned to serials (many-to-many). Assignment/removal is visible on the Serials page and audited.
- [x] **Dashboard CDA widget** — appears automatically when any active serial has CDA tables assigned. Shows a window schedule table and a live per-table countdown timer updated every second.
- [x] **Colour-coded countdown** — green (>10 min), yellow (5–10 min), orange (2–5 min), red (<2 min). When **inside** a window the card switches to a red danger style and counts down the remaining window time. After the window the timer switches to the next upcoming window.
- [x] **Midnight-spanning windows** and day-wrap (last window of the day → first window tomorrow) handled correctly.
- [x] **CDA widget persistence** — hidden state persisted in `localStorage`; the widget can be shown/hidden from the Widgets dropdown or via the hide button on the widget header.

## 0.11.0 — Dashboard utility widgets ✅ (shipped 2026-06-26)

Theme: make the dashboard useful as a user workspace, not only a signal table.

- [x] **Quick Notes widget** — local scratchpad stored in the browser with a "Save to PC" `.txt` download action.
- [x] **Docs Reference widget** — add a dashboard widget, select a published Docs page, and view the rendered document content in a contained reference panel. Full doc link remains available.
- [x] **Multiple clock widgets** — add extra clocks and choose Zulu + local, Zulu only, or local only per widget. The original combined clock remains available.
- [x] **Quick Links widget** — compact shortcuts for common user actions: New Log, Note, Serials, Range State, Incidents, and Handover.
- [x] **Local widget persistence** — utility widgets are terminal-local via localStorage and reuse the dashboard widget container for drag reorder, collapse, remove, and saved layout.

## 1.0.0 — Operational release

Theme: blessed for use. Gate criteria:

- [ ] Deployed and validated on the target Windows Server / range network (Docker or direct).
- [ ] All MVP success criteria in Scope §19 met and signed off.
- [ ] Backups, user accounts, and audit verified in the live environment.
- [ ] User + administrator documentation complete in the wiki module.
- [ ] Password/secret hygiene enforced (no default `admin/changeme`, real `SECRET_KEY`).
- [ ] **Critical** security items below are closed (they gate 1.0.0).

## QoL / navigation backlog

These are usability and navigation improvements identified after the 0.19.x
device-routing, audit-retention, and archive work.

- [x] **Global command palette** — `Ctrl+K` search/jump for devices, serials,
  packages, docs, logs, topology, calculators, config, and common actions.
- [x] **Recently viewed shortcuts** — terminal-local quick links for the last
  pages a user opened.
- [ ] **Breadcrumb consistency** — add lightweight breadcrumbs to deeper pages
  where users commonly need to get back to a parent view.
- [x] **Dashboard layout management** — reset layout, collapse/expand all, search
  widget picker, and checkbox toggle state for visible widgets.
- [x] **Saved log filters and date chips** — quick filters for Today, Yesterday,
  Last 7 days, Current Serial, Faulted, and local saved filter presets.
- [x] **Admin health/archive tools** — surface DB size, audit/archive counts,
  archive folders, and browse/download server-side audit/serial archive files.
- [x] **Topology search and visibility controls** — search/highlight devices and
  toggle manual/inferred/live route visibility.
- [x] **Topology route explanations** — explain routed paths through
  splitter/combiner devices with source, destination, matrix ports, and whether
  the link is manual or inferred.
- [x] **Docs organisation** — tags/categories and related docs, plus a recycle
  bin if deleted docs need recoverability.
- [~] **Documentation Wiki Lite** — turn `/docs` into a MediaWiki-lite range
  wiki while preserving Markdown, approvals, version history, and audit logging.
  First slices: `[[Page Title]]` / `[[Page Title|label]]` wiki links,
  missing-page links, backlinks, wanted pages, aliases/redirects, page
  visibility levels, page templates, and a denser wiki home. Later slices:
  richer search snippets, orphan pages, and optional pinned/start-here pages.
- [~] **Form ergonomics** — duplicate-from-existing, inline validation, and
  preserved form values after validation errors.

---

## Signal Hound instrument integration (future)

Signal Hound devices in use on the range: **SM435C** (real-time spectrum analyser, 100 Hz–43.5 GHz), **BB60D** (USB spectrum analyser, 9 kHz–6 GHz), **VSG60A** (vector signal generator, up to 6 GHz). Their SDKs are C libraries with Python ctypes bindings (`smapi`, `bbapi`, `vsgapi`).

### Deployment model

**Option A — Direct (preferred if hardware is on the app server):**
The Signal Hound devices plug directly into the server running the range app. The FastAPI app loads the SDK libraries and drives the hardware from a background task (same pattern as CBM SSH sync and SNMP polling). No bridge or extra service needed. Tradeoff: spectrum analysis is CPU/memory intensive — sweep rate should be throttled to leave headroom for the rest of the app.

**Option B — Bridge service (if hardware is on a separate beefy PC):**
A lightweight FastAPI bridge service runs on the instrument PC, loads the SDK, and exposes REST/WebSocket endpoints over the LAN (`GET /sweep`, `GET /status`, `POST /configure`). The main range app polls or streams from the bridge. The BB60D and VSG60A are USB-only so they must stay on the machine they're plugged into; the SM435C has 10GbE which reduces (but doesn't eliminate) the need for a bridge.

### Planned feature scope

- [ ] **Spectrum dashboard widget** — live frequency-vs-power trace rendered on a Canvas element. Polled from the app backend (or bridge) at a configurable rate (e.g. every 500 ms–2 s). Widget header shows centre freq, span, RBW, reference level, and peak marker.
- [ ] **Device status in the Devices registry** — SM435C/BB60D/VSG60A appear as device entries with live connectivity state (SDK loaded, hardware found, sweep active).
- [ ] **Sweep configuration** — administrators can set centre frequency, span, RBW, and reference level from the dashboard. Changes POST to the backend/bridge and take effect on the next sweep.
- [ ] **VSG60A control** — set output frequency, power level, and enable/disable RF output from the dashboard. Audited.
- [ ] **Marker / threshold annotation** — overlay expected signal frequencies (from active serial signal packages) on the spectrum trace so operators can quickly see whether a signal is present.
- [ ] **Capture trigger** — administrator can trigger a timed IQ or sweep capture stored server-side; file listed for download in the device detail page.
- [ ] **IQ streaming** — lower priority; high data rate makes the browser an unsuitable direct sink. Would require a separate capture workflow rather than live display.

### Prerequisites

- Signal Hound SDK installed on the host (`.so` on Linux, `.dll` on Windows).
- USB access from the app process (udev rules / Docker `--device` flag for containerised deployments).
- For Option B: bridge service repo, LAN reachability, and configured bridge URL in app settings.

---

## Security hardening

This system will run on a **sensitive range server**, so security is treated as a
first-class part of the roadmap rather than an afterthought. The app already does
some things well — **bcrypt** password hashing, **bleach** sanitisation of
wiki/doc HTML (XSS), an audit log, sessions with idle timeout, runs as a
**non-root** container user, and (as of 0.6.0) needs **no internet** at runtime.
The items below close the remaining gaps. Defence-in-depth: assume the LAN is not
fully trusted.

### Critical — gate the 1.0.0 operational release

- [x] **Enforce a real `SECRET_KEY`.** (0.9.0) The hard-coded default is gone; an
  unset/placeholder key now generates a strong ephemeral key at boot with a loud
  warning, so there is no known static key to forge cookies with. Set `SECRET_KEY`
  in production for persistent sessions.
- [x] **Remove default credentials.** (0.9.0) The seeded `admin` account now has
  `must_change_password` set; the app forces a password change at first login
  before any other page is reachable. Admin-created/reset accounts do the same.
- [~] **HTTPS/TLS + `Secure` cookies.** (0.9.0, partial) Session cookies are now
  `HttpOnly` + `SameSite=Strict`, and `Secure` is available via `SESSION_HTTPS_ONLY=1`.
  **TLS termination itself is deferred** (your call — no infra to configure yet).
- [x] **CSRF protection.** (0.9.0) `SameSite=Strict` cookies plus a same-origin
  `Origin`/`Referer` check middleware on all unsafe methods — cross-origin POSTs
  are rejected (403). No per-form tokens needed.
- [x] **Login brute-force protection.** (0.9.0) Per username+IP throttle: lockout
  after `LOGIN_MAX_ATTEMPTS` (default 5) for `LOGIN_LOCKOUT_SECONDS` (default 300).
  `LOGIN_SUCCESS` / `LOGIN_FAILED` / `LOGIN_LOCKED` are written to the audit log.
- [x] **Password policy.** (0.9.0) Minimum length (`MIN_PASSWORD_LENGTH`, default 10),
  not-equal-to-username, and a common-password blocklist, enforced on change + admin create/reset.

### High

- [x] **Security headers** (0.9.0) via middleware: `Content-Security-Policy`
  (first-party; `'unsafe-inline'` allowed for our inline scripts/styles),
  `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`.
  Add `Strict-Transport-Security` once TLS is in place.
- [x] **Session hardening:** login now clears pre-auth session state before
  writing authenticated claims, stamps `session_issued_at`, enforces the absolute
  cookie-age ceiling server-side, and handles malformed timestamps as expired.
  Re-review the 30-day "remember this terminal" policy operationally — fine for
  a locked ops room, risky on any shared/general PC.
- [x] **Least-privilege data store:** SQLite DB, archive directories, and generated
  backup files are hardened to owner-only filesystem permissions where the host
  allows it; Admin Config reports the current DB/archive modes. If/when Postgres
  is adopted, use a dedicated app role with minimal grants.
- [ ] **Network exposure:** bind the service to the range subnet only, firewall to
  known client hosts, and front it with a reverse proxy. Do not expose it beyond
  the range LAN.

### Medium / ongoing

- [ ] **Dependency & image patching:** pin versions, run `pip-audit` (or similar)
  on a schedule, and rebuild the image regularly to pick up base-image security
  fixes. Track CVEs for FastAPI/Starlette/uvicorn/bcrypt.
- [x] **Container hardening:** Docker Compose now runs the app with a read-only
  root filesystem, `/tmp` tmpfs, `no-new-privileges`, all Linux capabilities
  dropped, and basic memory/process limits. `/app/data` remains the writable
  SQLite/archive volume.
- [ ] **Encrypted, access-controlled backups** with a tested restore procedure.
- [ ] **Finer-grained RBAC** beyond the two current roles; periodic access review.
- [x] **Upload validation:** package/CBM imports and CDA CSV imports now enforce
  type and size limits, zip member limits, and structured validation for legacy
  package JSON before processing.
- [x] **Audit log integrity:** audit records now carry a tamper-evident
  HMAC-SHA-256 hash chain per Live/Testing scope. Existing rows are backfilled
  as a baseline, the Audit page reports chain health, and archive spreadsheets
  include hash fields for exported records.
- [ ] **Pre-deployment review:** a focused security review / light pen test before
  operational sign-off, plus a documented incident-response and patching process.

> Tip: the `/security-review` command can review the pending diff for these
> categories as features land.

---

## Post-1.0 / under investigation

### ★ Range hardware monitoring expansion (PRIORITY) — user-requested

Goal: extend live monitoring beyond the modems so operators can see the health
and state of the wider signal path from the dashboard. All relevant equipment
manuals + vendor **SNMP MIBs** are held locally under `System Manuals/` (kept out
of git). Sequencing is led by **splitter/combiner state** (user priority), then
EBEM status lights, then infrastructure; Ranger BUC is deferred (see below).

**The key enabler — a shared SNMP polling foundation.** Most of this estate is
SNMP-managed (the `.mib` files confirm it): ETL Systems **Genus** matrices/switches,
the **VTR/VTRC-1xx** matrices, the **Dextra 10 MHz** reference, and the
**SyncServer S600/S650** (also web/HTTPS/REST). Building one generic SNMP client
(e.g. `pysnmp`, loading the supplied MIBs) covers items 1, 3-infra below in a
single reusable module, alongside the existing SSH/ICC (CBM-400) and future
serial (CDM-600L) clients.

- [ ] **SNMP access gate (do first).** Devices are reachable on the server LAN and
  can be logged into, but whether **SNMP is enabled** and what community/v3
  credentials apply is **unconfirmed**. Confirm SNMP is turned on per device, obtain
  v2c community strings or SNMPv3 creds, and verify reachability (UDP 161) from the
  Project Range server before committing build effort.
- [x] **New `app/snmp.py` client + `RFDevice` SNMP fields** — shipped in **0.19.0**.
  SNMP v2c/v3 client (pysnmp 7.x async, bridged to a sync worker thread), creds
  encrypted via `app/crypto.py`, `app/snmp_sync.py` mapper writing observed routing
  onto `DevicePort` + audit on change, and an opt-in background poller
  (`SNMP_AUTO_SYNC_SECONDS`, default 0).

**1. Splitter / combiner monitoring (LEAD ITEM).** Hardware = ETL Systems Genus
modular system + VTR/VTRC-1xx matrices (Hawk matrix, Swift switch modules).
SNMP-readable: matrix input→output routing (*how it is terminated*), switch
positions, module presence, input/output levels, and PSU/fan/temperature alarms.

- [x] Read and display current termination/routing per matrix from SNMP — shipped in
  **0.19.0**: the routing page shows live observed routing vs the plan with mismatch
  highlighting (`hawkOutputRoutingSettings` under ETL enterprise OID `20938`).
- [x] Show system alarm/module health status — shipped in 0.19.0 (`systemSummaryAlarm`
  + `moduleInfoTable` on the Devices page and routing panel). *(Per-port input/output
  level detail can be added later if operators want it.)*
- [x] **Guided state changes (follow-up):** named routing presets per device per range state — shipped in **0.22.0**. Admins snapshot current SNMP routing as a preset for each state. When changing state, the app compares live observed routing against the preset and shows a warning table listing port / required routing / current routing. Advisory only — operator confirms they've reviewed it and can proceed. Preset management on the device routing page.
- [ ] **Hardware validation:** confirm observed routing/alarm reads against the matrix
  front panel once SNMP is enabled + credentials obtained (v2c vs v3), and confirm the
  routing-table row/column → output-index interpretation in `app/snmp.py::parse_routing`.

**2. EBEM status lights (CBM-400) — extends existing SSH/ICC poller.** Surface the
extra EBEM status fields as red/green dashboard indicators: unit fault, Tx/Rx
traffic, modem/demod lock & sync, EDMAC **embedded channel**, and link status.

- [~] Extend `app/cbm.py` parsing to capture the additional status fields. *(Partial: `ESYNC_STAT`, `ACQ_STATE`, and `BSYNC_STAT` are read in `cbm_sync.py` and stored as `cbm_sync_state_json`. Remaining fields such as unit fault and Tx/Rx traffic are not yet surfaced.)*
- [ ] Confirm exact EBEM status field names/values against the EBEM manual.
- [x] Render red/green status lights on the dashboard signal/device view — shipped in **0.22.0** (the three-LED EBEM Sync column in the dashboard signal table).

**3-infra. Sync Server, 10 MHz reference, DC injector.**

- [ ] **SyncServer S600/S650** — SNMP + web/HTTPS + REST API. Monitor GPS lock,
  holdover state, NTP service status, oscillator/reference health, and alarms.
- [ ] **Dextra 10 MHz reference** — SNMP (MIB present). Monitor reference/PLL lock,
  output presence/level, and alarms.
- [ ] **DC injector** — no manual and typically **passive** (DC-onto-coax for
  BUC/LNB); confirm the actual device — likely little or nothing to monitor
  directly (useful signal, if any, is BUC current draw seen via the modem/ODU).

**Deferred within this item:**

- [~] **BUC power output — Ranger (via RICS).** RICS (`http://rics`) already shows
  real-time TX/output power, EIRP, temperature and Eb/No and logs them, but appears
  **web-only with no documented SNMP/REST API**. **Deferred pending confirmation of a
  vendor API** (per user); if none exists, revisit web-scrape or exported-log ingest.
- [~] **BUC power output — STLT-M.** Manual not yet supplied; parked until provided.

### Modem live status (Intelsat CBM-400) — research spike (start early, parallel)

Goal you described: pull signal/config state from the CBM-400 modems so operators
don't re-enter settings on both the modem and the range hub.

This needs a **spike before committing to a milestone**, because feasibility
depends entirely on what interface the CBM-400 exposes. Investigation steps:

1. Confirm the modem's management interfaces — typically one of: **SNMP** (get/poll),
   a **web/REST API**, or **Telnet/serial CLI**. Get the vendor management/ICD manual.
2. Determine what's readable: lock status, Tx/Rx frequency, power, MODCOD, Eb/No.
3. Decide direction: **read-only first** (poll + display, lowest risk — fits the
   "no hardware control in MVP" non-goal) before any write-back/validation.
4. Prototype a single-modem poller against the device registry from 0.8.0.

Likely lands as **1.1** (read-only live status / "modem matches plan" validation)
if the interface is friendly; later if it requires vendor support. Related Scope
items: §12.1 (automatic status detection, power/Eb/No capture, modem lock status,
config validation).

Current foundation now in place:

- CBM modem manuals and exported modem config samples have been reviewed locally.
- Package import/export can use CBM-style modem text config files, using the
  Project Range fields it understands and ignoring modem-only parameters.
- Package signals can carry modem mapping metadata (`cbm_device_id`, `cbm_path`)
  so a Project Range signal can be tied to a specific modem source. The selected
  Source is now the user-facing modem selector when it matches a CBM modem device.

Future target: **full CBM integration complete**.

- [x] Add live automatic modem-driven updates so active dashboard signal values can
  update from enabled CBM modems without operator double-entry.
- [x] Add a dashboard **Force CBM Update** action that runs the same sync on demand
  and reports per-modem success/errors.
- [x] Write automatic `SignalLog` rows only when modem-derived values change and
  keep Testing-state sync scoped to Testing data.
- [x] Add safeguards for ambiguous active mappings so one modem/path cannot update
  multiple package signals silently.
- [ ] Validate the automatic poller against real hardware: CBM SSH/ICC output,
  status mapping, credentials, timeouts, retry behaviour, and audit volume.

### Modem live status (Comtech CDM-600L) — serial integration (⏸ PARKED — hardware-gated)

Goal: monitor **and configure** the **six** CDM-600L L-Band modems from the dashboard,
similar to how we monitor the CBM-400s. Scope decision (2026-07): **monitor + configure**
(config-write gated behind explicit confirmation, since it is active control of live modems).

> **⏸ Status: PARKED (2026-07) — blocked on hardware, not software.** The blocker is
> purely the serial→IP transport: the modems' P4B ports are currently cabled into a
> **plain UniFi/Ethernet switch, which cannot carry RS-232** (Ethernet ≠ serial), so no
> data reaches the server. Nothing can be built/tested until a serial-to-Ethernet device
> server (or a direct serial port on the server) is in the path. User cannot obtain the
> equipment right now; revisit when available. Software effort is small once transport exists.

**Current physical setup (from the range):** **6× CDM-600L**; serial cables from each modem's
**P4B Remote Control port (DB9-M)** intended for the network, but landing on a plain UniFi
Ethernet switch. Only 2 serial cables on hand (2 modems), all 6 when more cables arrive.
**User is leaning toward the hub route (Option B).**

**Equipment needed — pick one topology (software handles all three identically; each modem
ends up as a raw-TCP `host:port`, plus an optional RS-485 address):**

| Option | Hardware | Notes |
|---|---|---|
| **A. One converter per modem** | 6× single-port RS-232→Ethernet, TCP-Server mode — e.g. **Altronics D4231** (RS-232/422/485, Modbus, 9–54 V; preferred) or **Jaycar XC4134** (cheaper, hobbyist) | Cheap, incremental (2 now/6 later), **failure-isolated** (one dies → one modem down). 6 boxes / 6 PSUs / 6 IPs. |
| **B. One multi-port "hub"** (⭐ user's preference, tidiest) | 1× **8-port** serial device server (next size up from 6) — **Moxa NPort 5610-8 / 5650-8** (5650 = RS-232/422/485), **USR-N580** (budget 8-port), **Perle IOLAN STS8**, or **Digi PortServer TS 8** | One box, one IP, ports 4001–4008 (6 used, 2 spare). Neatest for a permanent rack; dearer; single point of failure. 16-port units exist if more headroom wanted. |
| **C. One converter, RS-485 multidrop** (cheapest) | 1× RS-485-capable converter (e.g. Altronics D4231) wired to all 6 modems on one RS-485 bus | Modems addressed 1–6 in the packet (`<0001/…>`). Cheapest, but RS-485 daisy-chain wiring + per-modem address; single point of failure. |

Set the converter to **TCP Server (raw socket)** mode, **RS-232** (address `0000` per modem),
and match the modem's baud/format (front panel → CONFIG → Remote Control). **Cabling gotcha:**
converter DB9-M ↔ modem P4B DB9-M needs a **female-female, likely null-modem (crossover)**
cable — verify TX/RX against the manual's **P4B pinout (Table 5-5)** at install.

**Candidate hardware links (verify specs before buying — must be ≥6 ports / RS-232 / TCP-Server):**
- RS Components AU (Option B hub candidate): https://au.rs-online.com/web/p/serial-device-servers/0799631 — *spec not auto-verified; confirm it's an 8-port RS-232 device server with TCP Server mode.*

**Feasibility: confirmed possible, but a different transport from the CBM-400.**
The CDM-600L Installation & Operation Manual (Rev 2, reviewed locally — held
out of git, see `.gitignore`) documents the full remote-control protocol in
Chapter 16. Key findings:

- **Management is serial-only** — a rear 9-pin M&C port, user-selectable
  **RS-232 or RS-485 (2/4-wire)**, async, 1200–38400 baud, 7O2/7E2/8N1. There is
  **no Ethernet/IP port, no SSH, and no SNMP** (2005-era modem). This is the core
  difference from the CBM-400/EBEM, which we reach over IP via SSH/ICC.
- **The protocol is a clean ASCII request/response packet**, simpler than the
  CBM-400 interactive shell — no menu navigation, no `paramiko`:
  - Controller → modem: `<` + 4-digit address + `/` + 3-letter code + `?` + `[CR]`
    (e.g. `<0135/TFQ?[CR]` = "report Tx frequency").
  - Modem → controller: `>0135/TFQ=0950.0000[CR][LF]`.
  - RS-232 uses fixed address `0000`; RS-485 allows addresses 1–9999, so several
    modems can share one bus, each individually addressed.
  - Remote **monitoring works even in LOCAL mode** (LOCAL only disables remote
    *control*) — ideal for a read-only integration.
- **Every value we read off the CBM-400 has a direct query equivalent:**
  `TXO?` (Tx carrier on/off → Up/Down), **`BSQ?`** (bulk status: Eb/No, BER,
  buffer fill, Rx freq offset, Rx signal level in one reply — the `all_stat ?`
  analogue), `FLT?` (unit/Tx/Rx faults), `EBN?` (Eb/No), `RSL?` (Rx level),
  `BER?`, `TFQ?`/`RFQ?` (frequencies), `TSR?`/`RSR?` (symbol rates),
  `PLI?`/`TPL?` (Tx power), plus `RNE?`/`RNS?` (stored event + link-statistics
  logs) and `EID?`/`SNO?`/`SWR?` (equipment ID / serial / firmware).

**How it would be achieved (proposed, when scheduled):**

1. **Serial transport onto the LAN.** Recommended: a **serial-to-Ethernet device
   server** (e.g. Moxa NPort, Lantronix) presenting each modem's M&C port as a raw
   TCP socket. This keeps the existing `RFDevice` `host:port` model and works under
   Docker. Direct `pyserial` cabling is possible but pins the app server physically
   next to the modems and is awkward to pass through to a container.
2. **New client module `app/cdm600.py`** — analogous to `app/cbm.py`, but it builds
   `<addr/CODE?>` strings and parses `>addr/CODE=value` replies over a socket
   (or serial). No SSH/interactive shell state. Reuse the same read-only,
   change-only-write-back sync path as the CBM-400.
3. **Two small `RFDevice` additions:** a **connection/protocol type** field (route
   EBEM-SSH modems vs. CDM-600L-serial modems to the correct client + sync mapping)
   and, for RS-485 multidrop, a **modem address** field (1–9999). Additive
   migrations in `init_db.py`, following the existing CBM column pattern.
4. **Status mapping decision (needs sign-off):** `TXO` on/off → Up/Down;
   `FLT?` → fault surface/incident; `EBN?`/`RSL?`/`BER?` → existing Eb/No and
   signal-quality display fields. Reuse the CBM audit + Testing-scope behaviour.

**Remaining unknowns are physical, not protocol:** whether the modems' M&C ports
are (or can be) wired to a device server reachable on the range LAN, and each
modem's baud rate, character format, and RS-485 address. Confirm those before
committing to a milestone.

- [ ] **(BLOCKER) Obtain + install a serial→IP device server** (Option A/B/C above) so each
  modem's P4B port is reachable as a raw TCP socket on the LAN. Everything below waits on this.
- [ ] Confirm each modem's RS-232/485 mode, baud, format, and (if RS-485) address; sort the
  DB9 M-M null-modem cabling against the P4B pinout.
- [ ] Prototype `cdm600.py` against the documented packet format (can start offline, no HW).
- [ ] Add `RFDevice` protocol-type + `host:port` + optional RS-485 address fields; route sync
  to the right client (EBEM-SSH vs CDM-600L-serial).
- [ ] Agree the CDM-600L status → Project Range state mapping; add guarded config-write actions.
- [ ] Validate against real hardware (parsed values vs. front panel / SatMac).

### Other future enhancements (Scope §12)

- **Hardware integration:** spectrum analyser screenshot capture, RF switch matrix state, power meters, SNMP/serial/REST devices, auto power/Eb/No readings.
- **Advanced ops:** range booking, job/mission workflow, checklists, maintenance/calibration modes, restricted-access mode.
- **Advanced reporting:** formal PDF range reports, daily/per-mission summaries, signal uptime, fault history, exportable audit packages.
- **Auth:** Active Directory / Windows integrated auth / SSO / MFA; role-based permissions beyond the two roles.
- **UI:** large-screen operations display, customisable widgets, signal card view, range schematic view, power/Eb/No trend graphs.
- **Voice chat:** single-user and group voice chat as an extension of instant chat.
  Difficulty is **moderate to high**: one-to-one browser voice is feasible with
  WebRTC and app-managed signaling, but reliable multi-user group voice usually
  needs an SFU/media server such as Janus, mediasoup, LiveKit, or Jitsi components.
  Required work includes WebSocket signaling, call UI, microphone permissions,
  mute/deafen controls, group room membership, LAN/STUN/TURN testing, and a decision
  on whether call metadata is audited while audio remains ephemeral.

---

## Suggested near-term sequencing

`0.6.0 (done)` → **0.7.0 UI polish** (quick wins, high visibility) →
**0.8.0 splitter/device status** (your operational ask) →
**0.9.0 hardening** (Postgres/HTTPS/backups) → **1.0.0** —
with the **CBM-400 spike running in parallel** from ~0.8.0 so 1.1 can start on solid findings.
