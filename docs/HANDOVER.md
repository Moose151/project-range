# Project Range — Handover Document

<!-- IMPORTANT: Update this file whenever features are added, changed, bugs are found, or new requirements arise.
     This is the canonical reference for any assistant continuing work on this project. -->

---

## ⚑ Current Status & Handover — 2026-06-29 (READ THIS FIRST)

> The detailed sections **below this block predate a large body of work** and are
> partially stale (e.g. port, model/router lists, "dark only", **top navbar** —
> the navbar has since been replaced by a left sidebar). For *planned* work
> the source of truth is **[ROADMAP.md](ROADMAP.md)**; for *current behaviour* trust
> the code. This block summarises where things actually are.

**App name:** "SEW Range" (re-branded from "Project Range"). **Version:** `0.18.6` (single source: `app/config.py` `APP_VERSION`, shown in the top-right of the UI near the theme toggle).
**Repo:** github.com/Moose151/project-range · all work is on **`main`**.
**Deploy:** `git pull && docker compose up -d --build` → http://<host>:**7474** (Docker publishes 7474→container 8001). Dev: `python run.py` (port 8001).
**First login:** `admin` / `changeme` works **once**, then forces a password change before anything else loads. Set a real `SECRET_KEY` in `.env` (compose requires it).
**DB:** SQLite at `/app/data/range.db` (named volume). `init_db.py` runs automatically on container start and is idempotent (migrations + new tables auto-create).

### Shipped (all on `main`, in order)
- **TxLO/RxLO rename** (was BUC/LO) everywhere incl. DB columns (migration renames in place), calculator, package/log auto-calc, exports (legacy `buc`/`lo` keys still import).
- **Docker deployment** (`Dockerfile`, `docker-compose.yml`, `docker-entrypoint.sh`, `.dockerignore`, `.env.example`, `docs/DEPLOY.md`); `.gitattributes` keeps shell files LF for Windows.
- **Offline/LAN fix:** all frontend assets vendored under `app/static/vendor/` (Bootstrap, Icons, HTMX, SortableJS) — **no CDN/internet needed**. Do NOT reintroduce CDN links.
- **SEW Range logo** (`app/static/img/sew-range-logo.png`) in navbar/login/favicon; gold brand accent.
- **Theme system** (0.9.1): two axes — `data-bs-theme` (light/dark navbar toggle) × `data-theme` (palette: classic/sew-gold/night-ops/spectrum), chosen on `/preferences`, persisted in localStorage, applied pre-paint. CSS in `app/static/css/app.css`.
- **Preferences page** (`/preferences`, router `preferences.py`): theme, light/dark, default freq/power units (per-user on `User`).
- **Shared templates:** `app/templating.py` exports the single `templates` instance (with `app_version` global). All routers import it — do NOT create per-router `Jinja2Templates`.
- **Devices** (`routers/devices.py`, models `RFDevice`/`DevicePort`): registry CRUD, splitter/combiner **routing matrix** (crossbar + per-port labels), live **TCP reachability** status (`/devices/status`, polled). Nav: "Devices".
- **Incidents** (`routers/incidents.py`, model `Incident`): log/list/update/CSV export. Nav: "Incidents".
- **Security hardening:** `SECRET_KEY` no longer has a static default (ephemeral if unset); forced password change (`User.must_change_password`, enforced in `deps.get_current_user`, page `/account/password` via `routers/account.py`); password policy + login throttle + auth audit (`auth.py`); security headers + CSRF origin-check + `SameSite=Strict` cookies (middleware in `main.py`, knobs in `config.py`).
- **Logs:** hard-delete added (administrator, only on soft-deleted rows) alongside existing soft-delete/restore.
- **Range state:** going **Live** requires safety acknowledgment + administrator authorisation (users enter an administrator's credentials = two-person).
- **Dashboard bulk-submit** (0.9.2): per-row green tick replaced with a single "Submit All Changes" bar at the bottom of each serial widget. All staged signal changes in that widget are sent in one `POST /dashboard/bulk-update` (JSON body) and committed in a single DB transaction — staging multiple signals then submitting no longer wipes other staged rows.
- **0.9.2 bug fixes:**
  - Password minimum length set consistently to **6** across config, server validation (`auth.py → validate_password`), and all HTML `minlength` attributes. Previously the server enforced 10 but the form showed 8. `MIN_PASSWORD_LENGTH` is envvar-overridable.
  - **HTMX chaos on forced password-change page fixed:** When a new user logs in and must change their password, the range-state banner HTMX pollers in `base.html` were firing on page load and following the `must_change_password` redirect, injecting a full HTML page into tiny `<span>` elements — causing the card to visually jump and inputs to be unresponsive. Fixed by wrapping both poller spans in `{% if not user.must_change_password %}` guards.
- **0.9.3 — Device page enhancements + Serial pending:**
  - **New device types:** IP Switch, 10MHz Reference, Sync Server, DC Injector added to the device type dropdown (alongside existing Modem, Splitter, Combiner, RF Switch, Spectrum Analyser, Signal Generator, Power Meter, Other).
  - **Device name vs model:** `RFDevice` now has two separate text fields — `name` (unique instance name, e.g. `CBM-400-1`) and `device_model` (product model, e.g. `CBM-400`). Both shown in the devices table. Migration adds `device_model VARCHAR(128)`.
  - **Web GUI link:** `RFDevice.has_web_gui` boolean (checkbox in add/edit form). When set, a "Open" link button appears in the devices table pointing to `http://<host>/`. `web_gui_url` is a Python property on the model.  Migration adds `has_web_gui BOOLEAN DEFAULT 0`.
  - **Topology page** (`/devices/topology`, `app/templates/topology.html`): tabbed view (RF / IP / Clock / All), SVG diagram auto-arranged by device layer type (modems/generators at top, switches/combiners in middle, instruments at bottom), colour-coded connections (RF=gold, IP=teal, Clock=purple, Power=red). Connection list table with delete for administrators. Add-connection form for administrators (from device / port / port index → to device / port / port index / type / label). "Topology" button in devices page header.
  - **`DeviceLink` model** (`app/models.py`): stores directed connections between `RFDevice` instances. Fields: `from_device_id`, `from_port` (label), `from_port_idx` (integer, for routing matrix integration), `to_device_id`, `to_port`, `to_port_idx`, `link_type` (rf/ip/clock/power), `label`. Table auto-created by `Base.metadata.create_all`.
  - **Routing page auto-hints:** When a `DeviceLink` has `to_port_idx` matching a combiner/splitter port, the routing page (`/devices/{id}/routing`) pre-populates that port's label with the connected device's name and shows a "linked: DeviceName" hint. Input hints from the `to` side of links; output hints from the `from` side.
  - **Serial pending / pre-create:** The serial create form (`/serials`) now has two buttons — **Save as Pending** (creates the serial with packages attached, `is_started=False`, redirects to serials list) and **Create & Start** (existing behaviour, goes to start confirmation). Pending serials appear in a "Pending — not yet started" section at the top of the serials page with Start and Delete buttons. `Serial.is_started` and the pending/active separation already existed in the DB and router; the only change was adding the `action` form param and the second button.
- **0.9.4 — Log readability:** `/logs` and `/history/{serial_id}` now compare each signal log entry with the previous entry for that signal in the same serial. Changed fields are summarized in a new "Changed" column and visible changed cells get a subtle accent highlight. Serial history lifecycle rows now use calmer custom colours for `SerialStart`, `SerialEnd`, and narrative notes instead of the bright warning-yellow row.
- **0.9.5 — Settings/theme polish:**
  - **Settings discoverability:** main navbar now has a visible **Settings** dropdown with Your Preferences, Password, and administrator-only Admin Config. User display name still links to preferences.
  - **Theme rework:** palettes now change body canvas, navbar, cards, borders, and muted panel surfaces, not just button/link accents. Light mode is softened from Bootstrap's stark white with darker text and stronger borders. CSS cache key bumped to `app.css?v=11`.
  - **Login theme toggle polish:** login page now syncs the sun/moon icon with the saved light/dark mode on load.
- **0.10.0 — Dashboard clock + timezone/log time polish:**
  - **Dashboard Zulu/local clock widget:** dashboard now has a draggable, hideable clock widget showing Zulu (UTC) and the configured local timezone. It uses the existing dashboard widget container, grip reorder, collapse, and localStorage layout persistence. The widget can be re-shown from the dashboard "Clock" button.
  - **Global local timezone:** timezone is **not per-user**. Administrators set it under `/config` → System. Stored in new `AppSetting` table (`key="local_timezone"`, default `"UTC"` seeded by `init_db.py`).
  - **Logs are Zulu-first:** `/logs` and `/history/{serial_id}` always show timestamps with `Z`. Optional "Show local time" checkbox adds a second local-time line using the configured timezone. CSV/XLSX exports now label timestamp columns as "Timestamp (Zulu)" and include `Z`.
  - **Device type:** "Antenna" added as a selectable device type in the Devices registry and topology layering.
- **0.10.1 — Backup script:** Added `scripts/backup_db.py`, a Docker Compose friendly SQLite backup script that copies `/app/data/range.db` to `./backups/range-<UTC>.db` and prunes old backups with `--keep`. `docs/DEPLOY.md` now documents backup scheduling and restore steps. `backups/` is gitignored.
- **0.11.0 — Dashboard utility widgets:** Dashboard "Widgets" menu can add terminal-local widgets stored in localStorage:
  - **Quick Notes** widget: scratch text area with "Save to PC" download as `.txt`.
  - **Doc Reference** widget: select any published Docs page and render it in a contained dashboard reference panel via `/dashboard/doc-widget/{slug}`.
  - **Clock widgets:** multiple extra clock widgets can be added, each selectable as Zulu + local, Zulu only, or local only. The original combined clock remains hideable/showable.
  - **Quick Links** widget: compact shortcuts for New Log, Note, Serials, Range State, Incidents, and Handover.
  - Utility widgets reuse the dashboard widget container: drag reorder, collapse, remove, and layout persistence.
- **0.12.0 — CDA (Controlled Data Area) windows:** Named CDA tables hold daily-recurring Zulu time windows; each window has `start_zulu`/`end_zulu` (`HH:MM`), an optional label, and an optional `max_power_dbm` (null = **No Fire**, value = **Reduced Power**). Many-to-many assignment of CDA tables to serials. Dashboard CDA widget shows the schedule plus a per-table **live countdown** (updated every second, colour-coded by proximity; flips to red "in window" while inside one; handles midnight-spanning + next-day wrap). New models `CDATable`, `CDAWindow`, `SerialCDATable` (`models.py`); router `cda.py`; templates `cda_tables.html`, `cda_table_edit.html`; nav "CDA". Tables auto-create via `create_all`.
  - **24-hour time only** (no AM/PM): window time inputs are `type="text"` with JS auto-format — type `HHMM` (4 digits) and a colon is inserted; server normalises `HHMM`/`HH:MM` via `_parse_zulu_time`.
  - **CSV import/export:** per-table `GET /cda/{id}/export.csv` (opens in Excel/LibreOffice) and administrator `POST /cda/{id}/import` (additive/non-destructive, handles Excel BOM via `utf-8-sig`).
- **Login tiling bug fix:** the login `<body>` was a Bootstrap flex container, so browsers treated `<script>`/other children as flex items → duplicated/tiled login fields. Fixed by moving the centring flex onto an inner wrapper `<div>`; `<body>` keeps only `class="bg-body"`.
- **0.13.0 — Complete UI overhaul (navigation + dashboard):**
  - **Left sidebar replaces the top navbar.** Collapsible (hamburger in a slim top bar), icon-only when collapsed on desktop, fixed overlay + backdrop on mobile; state persisted in localStorage (`sidebarCollapsed`). Sections: Dashboard · Operations · Resources · Calculators · Records · Admin (administrator-only). Top bar also has a persistent **Back** button and the light/dark toggle. The old overlapping Settings/Admin dropdowns are gone — links live in coherent sidebar sections; user name + Password + Logout sit in the sidebar footer.
  - **Dashboard is a 2-column CSS grid** (`.widget-grid`), not a single column — widgets can sit **side by side**. Every widget header has a **span toggle** (half ↔ full width, `.span-1`), persisted in the layout. Drag-reorder / tab-merge / collapse all still work.
  - **Hardcoded summary cards removed** (Range State, Active Signals, Faulted, Last State Change). **Faulted is gone entirely.** Active-signals **Up count** now lives in the range-state banner (HTMX `GET /status/active-count`, refreshed each poll via OOB swap). Range State, Active Signals, and Last State Change are now **optional dashboard widgets**.
  - **New calculator widgets** (client-side, in `app.js`): **Basic Calculator** (full numpad), **RF Frequency**, **Power Converter**. Calculator sidebar links highlight per-calc via a new `page_name` (`rf`/`power`/`eirp`/`basic`) added to `calculator.py`.
  - Files: `base.html` (rewritten), `app/static/css/app.css` (sidebar + grid + calc styles), `app/static/js/app.js` (sidebar toggle, span toggle, calc widgets), `dashboard.html`, `partials/dashboard_fragment.html` (OOB now updates banner Up count). `partials/dashboard_summary.html` is now unused/dead.
- **app.js cache-busting fix + Basic Calculator page:** `base.html` loaded `app.js` with **no version query string**, so browsers served the stale pre-overhaul copy → the sidebar-collapse and span-toggle buttons silently did nothing. Now pinned (`app.js?v=14`, `app.css?v=14`); **bump these on any future JS/CSS change.** Also added a standalone `GET /calculator/basic` page (reuses the widget's calculator logic) and a Basic Calculator link in the sidebar Calculators section. *(A one-time hard refresh clears any stale tab.)*
- **0.14.0 — Observer (read-only) role + range-wide CEASE alert:**
  - **New Observer account role** (`Role.OBSERVER`, value `observer`; old internal alias `Role.SAFETY_SUPERVISOR` still exists for compatibility) — a **read-only** account. Enforced centrally in `main.py` `security_middleware`: all non-safe HTTP methods are blocked for these users, except an allow-list (`SAFETY_SUPERVISOR_ALLOWED_WRITES`). **Middleware ordering changed:** `SessionMiddleware` is now added **last** so it is outermost and `request.session` is populated before the read-only check runs. Users admin shows the role with a distinct red badge + explanatory note.
  - **CEASE:** a big red pulsing **CEASE** button pinned to the bottom of the sidebar, on every screen, pressable by **any** user (incl. Observer). Pressing it requires a **reason** (logged). A full-screen red **CEASE splash** then appears on every connected screen showing who/when/why, with a **Dismiss** any user can press. New model `CeaseEvent`; router `cease.py` with `GET /cease/state` (JSON), `POST /cease/raise`, `POST /cease/dismiss`. Driven by a 3-second JSON poll in `app.js` that rebuilds the overlay only when the active event id changes (no flicker). Both raise and dismiss are audit-logged. **Note:** CEASE is a visual/logged "all-stop" alert only — it does **not** change range state or stop hardware (possible future enhancement).
- **0.15.0 — Configurable duty-role tags (visual position indicator):**
  - A **duty-role tag** is a coloured badge showing what position a user is filling right now (e.g. Operator, Supervisor, EA Safety). **Separate from the permission role; grants no access.**
  - New admin-managed **`DutyRole`** list (Admin → Config → **Duty Roles** tab): add / rename / recolour (colour picker) / enable-disable / drag-reorder / delete, with full CRUD in `config.py`. Renaming or recolouring **propagates** to anyone currently wearing the tag; deleting clears it from them.
  - Users **self-select** their current role on `/preferences` (dedicated `POST /preferences/duty-role`). The chosen **name + colour are denormalised** onto `User.duty_role` / `User.duty_role_color` so the badge renders anywhere without a lookup. Shown in the **sidebar footer** (own) and a new **Duty Role column** in the Users admin list (the existing permission column is relabelled **"Account"**).
  - Read-only Observers **may** set their own tag (personal display setting — `/preferences/duty-role` is in the middleware allow-list); all other writes stay blocked.
  - Seeded defaults: Operator, Supervisor, EA Safety, Observer. Additive migration adds `users.duty_role` + `users.duty_role_color`; `duty_roles` table auto-creates.
- **CBM-400 read-only sync foundation (in progress, not versioned yet):**
  - Manuals confirmed EBEM supports read/monitor via ICC command messages over SSH/Telnet/serial and SNMPv3. Current implementation targets **SSH/ICC** first.
  - Four CBMs are idempotently seeded into the device registry: `CBM-400-1` → `10.74.10.61`, `CBM-400-2` → `.62`, `CBM-400-3` → `.63`, `CBM-400-4` → `.64`; check port `22`; web GUI enabled.
  - Package signals now carry an explicit modem mapping: `cbm_device_id` plus `cbm_path` (`tx`/`rx`/`tx_rx`/`dvb`). Operators select the modem through the normal **Source** field; if the Source matches an active modem device, Project Range links the signal to that modem internally. This is how Project Range knows which planned signal corresponds to which modem; it does **not** guess from modem state alone.
  - Devices page now has administrator-only EBEM credential fields (`cbm_username`, encrypted `cbm_password_encrypted`, `cbm_sync_enabled`) plus a per-device **Test CBM poll** action. Passwords are write-only in the GUI and encrypted at rest with a key derived from `SECRET_KEY`.
    - **Operational caveat:** because modem passwords are encrypted from `SECRET_KEY`, changing `SECRET_KEY` makes stored EBEM passwords unreadable. Production must use a stable `.env` `SECRET_KEY`; if it changes, re-enter modem passwords in Devices.
  - New modules: `app/crypto.py` (Fernet wrapper), `app/cbm.py` (read-only SSH/ICC client + parser), `app/cbm_sync.py` (manual active-serial sync). `requirements.txt` now includes `paramiko`.
  - Manual sync button on Devices (`POST /devices/cbm/sync-active`) polls enabled CBMs, refuses ambiguous active mappings, and writes automatic `SignalLog` rows only when mapped modem values differ.
    - First sync policy: `TX_OP=ON` maps to **Up**, `TX_OP` not ON maps to **Down** for Tx mappings; Rx/DVB uses available lock/link status heuristics. **This needs validation against real modem output before ops use.**
  - In-app Docs page seeded/ensured at `/docs/cbm-400-read-only-signal-sync` ("CBM-400 Read-Only Signal Sync") with user/administrator setup instructions.
  - **Verification gap:** compile/migration/import/parser checks passed locally, but actual SSH polling cannot be tested until running on the range network with EBEM credentials and `paramiko` installed/rebuilt.
- **0.16.0 — Ephemeral instant chat:**
  - Added a simple in-memory chat system for logged-in users. It is intentionally **not persisted**: rooms/messages live only in the current Python process and are lost on app restart. There is no chat history after logout/restart.
  - Presence is based on recent authenticated requests/heartbeats (`ONLINE_WINDOW = 45s`) in `app/chat_state.py`; explicit logout removes the user from presence. Closed tabs age out automatically.
  - New router `app/routers/chat.py` exposes JSON endpoints under `/chat`: online/room state, private room creation, group room creation, message send, and message polling. `main.py` registers the router and allows Observer chat writes despite read-only enforcement.
  - Global floating chat UI lives in `base.html`: bottom-right launcher, online user roster, double-click user to open private chat, group creator, floating chat windows, minimise/close, unread badge/alert for minimised windows.
  - Dashboard utility widget type `chat` added to the Widgets menu. It shows online users/open rooms and opens the same floating chat windows. Widget persistence follows existing terminal-local dashboard utility widget storage.
  - Static cache keys bumped to `app.css?v=15` / `app.js?v=15`. New CSS is in `app/static/css/app.css`; client logic is in `app/static/js/app.js`.
  - **Verification gap:** compile, app import, JS syntax, and template parse passed. Needs real browser QA with two logged-in sessions to confirm online presence, private/group room creation, unread alerts, minimised windows, mobile layout, and dashboard widget behaviour.
- **0.16.1 — Chat notification/usability polish:**
  - Chat now polls all rooms the user participates in, not only rooms with an open floating window. If a message arrives while no relevant chat window is open, the launcher unread badge increments and a toast notification appears.
  - Clicking the chat window header now minimises/restores the window; the small dash button remains but is no longer the only target.
  - Online roster, group creator, and dashboard Chat widget now show the user's current duty-role tag when available, falling back to account role.
  - Dashboard Chat widget is now a real embedded chat surface: select/start a private chat, select existing private/group rooms, read messages, and send replies inside the widget without opening a floating bottom chat window. The floating windows remain available from the global launcher.
  - Group chats are implemented as in-memory rooms with 2+ participants via `/chat/rooms/group`; still no persistence/history after restart.
  - Static cache keys bumped to `app.css?v=16` / `app.js?v=16`.
- **0.17.0 — Testing range state + chat/CDA/serial usability fixes:**
  - New range state **Testing** (`RangeState.TESTING`). Only administrators can place the range into Testing or take it out again. Non-administrators who are logged in while the range is Testing stay in Testing and cannot change state.
  - Testing is a separate operational workspace, not a discard mode. Rows created while Testing are saved with `is_testing=True` and hidden from the normal states. Returning to Testing shows the same Testing data again.
  - Scoped/sandboxed models: `SignalPackage`, `Serial`, `SignalLog`, `AuditLog`, `RFDevice`, `DeviceLink`, `CDATable`, `Incident`, and `CeaseEvent`. Additive migrations for all `is_testing` columns are in `init_db.py`.
  - A SQLAlchemy `before_flush` hook in `models.py` automatically marks new scoped rows based on current range state (or a pending range-state transition), so audit/log/config rows do not accidentally leak into the wrong workspace.
  - On first entry to Testing, current operational **RF devices/topology** and **CDA tables/windows** are copied into Testing as editable sandbox rows. Testing edits to devices/CDA do not modify operational rows.
  - Testing scoping is enforced in the main operational views and exports: packages, serials, dashboard status/update endpoints, logs, history, audit, devices, topology, CBM active sync, CDA, incidents, and CEASE. User accounts, Docs, duty-role/admin reference lists, and signal registry remain global.
  - UI shows a yellow Testing range banner and warning on the range-state change screen. Static cache keys bumped to `app.css?v=17` / `app.js?v=17`.
  - Chat fix: opening a chat now loads the full in-memory room history for the current app session, so a message received before the floating window/widget is opened appears with sender and time. Last-seen/unread state is stored in browser `sessionStorage`, preventing the same message notification from replaying on every page change. Messages still live only in the Python process; browser session state is only for notification/read tracking.
  - CDA permissions changed: operators can now add, import, edit, and delete **CDA windows**. CDA table create/edit/delete remains administrator-only. Observer remains read-only via middleware/UI.
  - Serials page no longer shows the New Serial form by default. It now has a top-right **New Serial** button that opens a collapsible form, matching the Packages flow.
- **0.17.1 — Account roles + account archiving/deletion/rename:**
  - Account permission roles are now **Administrator**, **User**, and **Observer**. Duty-role tags remain separate visual position labels and do not grant permissions; their existing Operator/Supervisor/EA Safety-style labels are intentionally unchanged.
  - Additive migration adds `users.is_archived`; `init_db.py` also migrates old role values/names (`SUPERVISOR`/`supervisor`, `OPERATOR`/`operator`, `SAFETY_SUPERVISOR`/`safety_supervisor`) to the new stored values (`administrator`, `user`, `observer`).
  - Admins can rename accounts, change display names, and change account roles, including the default `admin` account. The app prevents removing/downgrading/disabling/archiving the last active Administrator.
  - Admins can archive accounts. Archived accounts are disabled, cannot log in, do not appear in the normal Users list, and are excluded from chat/presence and admin credential checks. They can be viewed/restored from the Archived toggle.
  - Hard delete is available only when no required operational attribution rows depend on the account. If records exist, use Archive instead; nullable references are cleared only for accounts that are safe to delete.
  - Verification passed locally: `init_db.py`, compileall, template parsing, enum/migration checks, archived-login check, foreign-key delete-safety checks, and app import.
- **0.17.2 — Dashboard signal Engaged indicator:**
  - Signal dashboard tables now have an optional **Engaged** column. Operators can toggle it On/Off immediately without using the dashboard **Submit All Changes** bar.
  - `SignalLog.engaged` is a visual mission-system engagement flag only. It does not change signal status, power, buzzer logic, range state, or CBM sync decisions.
  - The toggle updates the latest visible signal log row directly through `POST /dashboard/engaged-toggle` and writes an audit entry (`SIGNAL_ENGAGED_TOGGLE`). The flag is inherited when dashboard quick/bulk updates or CBM automatic sync create a newer log row, so normal status/power updates do not clear it.
  - Additive migration adds `signal_logs.engaged BOOLEAN DEFAULT 0`. The column is included in the dashboard column picker and hidden/shown with the existing dashboard column preferences.
- **0.17.3 — Version badge placement fix:**
  - Moved the app version badge from the fixed bottom-right corner to the topbar near the light/dark theme toggle so the floating chat launcher/windows no longer cover it.
  - Static CSS cache key bumped to `app.css?v=18`.
- **0.17.4 — Form/tab position restore:**
  - Added a global page-state helper in `app.js` that remembers active Bootstrap tabs and scroll position during normal form/select submits, then restores them after the reload. This fixes App Config add/toggle/delete actions jumping back to the Modulation tab/top of page, and applies to the same reload pattern across the app.
  - Static JS cache key bumped to `app.js?v=18`.
- **0.17.5 — CBM-400 signal package import/export format:**
  - Signal package import now accepts CBM-400 `STR_CFG` text exports (`.txt`/`.cfg`/`.conf`), ZIP files containing those configs, and the previous Project Range JSON format for backwards compatibility.
  - CBM imports create package signals using the filename as the signal name and read only the useful Project Range fields: `TXIF_FRQ`, `RXIF_FRQ`, `TXIF_LVL`, `TX_MOD`/`RX_MOD`, `TX_SR`/`RX_SR`, `TX_CODE`/`RX_CODE`, and `CFG_NAME`. Other modem-only fields are ignored except TX/RX/ITA operation values are copied into notes.
  - Signal package export now emits CBM-style modem config files. A one-signal package exports a `.txt`; multi-signal packages export a `.zip` with one modem config text file per signal plus a `project_range_package.json` compatibility snapshot.
  - Local sample modem config exports live under `modem_configs/` and are intentionally gitignored. Do not commit real modem config exports unless explicitly cleared.
- **0.17.6 — Chat duty-role labels + live shared state refresh:**
  - Chat roster and group creator now show only the user's selected duty-role tag, not their account permission role. If no duty role is selected, no role badge is shown.
  - Private chat window headers now show the other user's duty-role tag beside their display name.
  - Range-state banners now poll `/range-state/status` every 5 seconds and update in-place for every logged-in browser. Users get a toast when another operator/admin changes state.
  - Dashboard signal tables now auto-refresh every 5 seconds instead of 10 and also refresh immediately when the global range-state poll detects a state change. HTMX still pauses dashboard polling while a signal quick-edit row is open or staged, to avoid overwriting an operator mid-edit.
  - Testing transitions still trigger a controlled page reload after the toast so users move into/out of the correct Testing workspace data scope automatically.
  - Static cache keys bumped to `app.css?v=19` / `app.js?v=19`.
- **0.17.7 — Source/CBM package import cleanup:**
  - CBM modem devices now appear as automatic Source options in App Config, package signal forms, log forms, and dashboard quick-edit source lists. Package signals no longer have a separate CBM Modem selector; selecting a Source that matches an active modem device links the signal to that modem internally.
  - CBM imports split modem coding fields into separate package columns: `TX_SR/RX_SR` → Symbol Rate, `TX_CODE/RX_CODE` → FEC rate, and `TX_SMOP/RX_SMOP` → Inner Code. Legacy combined values like `1/2TURBO:1024` are split on import.
  - Package signal add/edit now has separate FEC, Inner Code, and Symbol Rate fields. Carrier Label was removed from the UI/export naming path.
  - Eb/No was removed from package signal configuration and serial-start package loading. It remains a signal-log/display field intended to be populated from EBEM/modem reads as an indication of Tx/Rx strength. CBM sync now writes only the FEC rate portion (for example `1/2`) into signal logs when modem codes include inner-code text.
  - Additive migration adds `signal_package_entries.inner_code VARCHAR(32)`.
- **0.17.8 — Dashboard Force CBM Update button:**
  - Active serial dashboard widgets now show a compact **CBM** force-update button when the serial has any package signal mapped to a CBM source/device.
  - The button calls `POST /dashboard/cbm-sync`, runs the existing read-only active CBM sync, writes any automatic signal-log changes, and returns to the dashboard with an update/skipped/issues toast.
  - This dashboard action is available to normal logged-in Users and Administrators; Observer accounts remain blocked by the global read-only middleware.
- **0.17.9 — CBM symbol-rate import/edit fix:**
  - CBM `TX_SR/RX_SR` values are now converted from modem raw units into kbps/ksps display units on import and live CBM sync. For example, `511999.0` imports as `511.999`.
  - CBM package export converts the display value back to modem raw units.
  - Package signal edit now preserves imported dropdown values that are not yet in App Config, so imported configurations can be opened and edited instead of blanking those fields.
- **0.17.10 — CBM force-update issue auditing:**
  - Active CBM sync now writes detailed issue text into the `CBM_SYNC_ACTIVE` audit comment and creates a dedicated `CBM_SYNC_ISSUE` audit record when any mappings fail or are skipped due to a fault.
  - Dashboard Force CBM Update toasts now include the first issue reason instead of only showing the issue count.
  - Previously silent skips such as missing mapped device or CBM sync disabled are now recorded as explicit issue reasons.
- **0.17.11 — Imported package signal edit/source fix:**
  - Package signal edit buttons now store imported row data in a safe `data-entry` payload instead of brittle inline JSON, fixing imported signals that could not be opened for editing.
  - When a package signal Source matches a CBM modem using punctuation-insensitive matching (`CBM400_2` vs `CBM-400-2`), saving the signal now stores the canonical modem Source name and updates the internal `cbm_device_id` mapping.
  - This allows operators to correct imported signals that mapped to the wrong CBM by editing the signal Source and saving.
- **0.17.12 — Package import RF setup/append + delete guard:**
  - New package CBM import now captures the package details first, including band, antenna, TxLO, RxLO, TTF direction/value, and frequency unit, then imports the selected CBM text/zip files.
  - Imported CBM signals that only contain IF frequencies now auto-fill TxRF/RxRF from the package LOs and imported TxIF/RxIF values. Imported signal frequencies are stored in MHz to match modem reads.
  - Existing packages now have **Import CBM** actions on the package list and package edit page, allowing operators to append CBM signal configs into an already-created package using that package's RF setup.
  - Package deletion now checks serial assignments first. If any serial still references the package, the app shows a clear error and writes `PACKAGE_DELETE_BLOCKED` to audit instead of throwing an internal server error.
- **0.17.13 — Dashboard Source edits update package CBM mapping:**
  - Dashboard quick-edit Source changes now persist back to the matching signal package entry/entries for that active serial, including canonical CBM modem matching and `cbm_device_id` updates.
  - The dashboard Source dropdown preserves existing source values that are not currently in App Config, preventing accidental blanking when editing imported or legacy source names.
  - Dashboard updates write an audit comment when a Source change is applied back to package mappings.
- **0.17.14 — Explicit unassigned CBM source option:**
  - Package signal Source and dashboard quick-edit Source now show **No modem assigned** as the blank/default state, so operators no longer need to create a fake `nil` Source.
  - Selecting **No modem assigned** clears the package signal Source and internal `cbm_device_id`. CBM sync intentionally ignores these entries, so only the signal currently mapped to a real CBM is updated from that modem.
  - Operators can assign a CBM Source from the dashboard when a signal is ready to go Up; that Source change persists back to the package mapping from 0.17.13.
- **0.18.0 — Session, dashboard bulk edit, package delete, chat presence, and automatic EBEM sync:**
  - User accounts are now **single-session**. On successful login, `users.active_session_token` is replaced with a fresh token stored in that browser session; older sessions for the same user are redirected to `/login?timeout=1` on their next authenticated request. Logout only clears the token when it belongs to the current session, so an old tab cannot log out a newer login.
  - Dashboard quick-edit rows now stage **all signal parameter changes** into the serial widget's existing bulk submit bar: status, Source/CBM mapping, modulation, symbol rate, FEC, antenna, power/unit, Eb/No, notes, and TxIF/TxRF/RxRF/RxIF. The per-row `Update & Log` submit is gone; operators use one **Submit Widget** / **Submit All Changes** action for the whole widget.
  - Dashboard frequency edits now recalculate the other three frequency fields immediately in the browser from the assigned package TxLO/RxLO/TTF, and the server recalculates again on bulk submit. EBEM/CBM sync also recalculates TxRF/RxRF when modem TxIF/RxIF reads change.
  - Package deletion now blocks only active/pending serial assignments. If all package references are from closed serials in history, the old `serial_packages` links are removed and the package can be deleted; signal log history remains intact.
  - Chat presence now uses a shorter 25-second online window plus a `/chat/offline` `sendBeacon` on browser/page close. This cannot make browser-close detection perfect, but stale users disappear much faster and normal logout still removes them immediately.
  - EBEM/CBM read-only sync now runs automatically every **5 seconds** in a FastAPI background task using the existing `sync_active_cbms` path. Configure with `CBM_AUTO_SYNC_SECONDS` (`0` disables). The task skips overlapping runs and executes polling in a worker thread so SSH reads do not block web requests.
- **0.18.1 — In-app Version History + Observer document edit requests:**
  - Added `docs/VERSION_HISTORY.md` as a chronological release history and exposed it in-app at `/docs/version-history`.
  - Sidebar Records now includes **Version History** for all logged-in users.
  - Observers can now request edits to documentation pages using the existing docs proposal workflow. The global Observer write middleware allows only `POST /docs/{slug}/edit` for this purpose; approvals/rejections/restores/page creation remain administrator-only.
- **0.18.2 — Version History Docker packaging fix:**
  - `.dockerignore` now excludes most docs but explicitly includes `docs/VERSION_HISTORY.md`, because `/docs/version-history` renders that markdown at runtime.
  - This fixes Docker deployments showing "No version history document found" even though the file exists in git.
- **0.18.3 — Chat room inbox + group member management:**
  - Chat launcher now has **Unread** and **Chats** sections, so group/private rooms can be opened from the chat UI after a notification.
  - Unread state tracks room counts plus sender names, so opening the contacts/chat menu shows where notifications came from.
  - Group chat windows now have a member-management panel (`person-plus` button) and call `POST /chat/rooms/{room_id}/members` to add active users after creation.
  - `/chat/state` returns `available_users` and room `participant_details` for richer chat UI rendering.
  - Static cache keys bumped to `app.css?v=21` / `app.js?v=21`.
- **0.18.4 — Chat live delivery + duplicate-send guard:**
  - Group-create and group-member add pickers now show online users first and tuck offline users into a collapsed **Offline** section.
  - Floating chat windows and dashboard chat widgets now guard against overlapping polls and duplicate submits.
  - Message rendering uses server message IDs to skip messages already present on screen, which keeps open chat windows live without duplicate rows.
  - Viewed chat rooms now use one shared unread-clear path, so the bottom-right notification bubble, unread sender list, dashboard dropdown count, and session-stored unread state clear together.
  - Static cache keys bumped to `app.css?v=23` / `app.js?v=23`.
- **0.18.5 — Observer utilities + CDA assignment + calculator usability:**
  - Observer middleware now allows `/calculator/*` POSTs, `/dashboard/engaged-toggle`, and `/incidents/new`; package/serial writes remain blocked.
  - Observer incident submissions are saved with `Incident.approval_status="pending"` and appear in an administrator approval section on `/incidents`; approve/reject routes are `/incidents/{id}/approve` and `/incidents/{id}/reject`.
  - Package and Serial templates show Observer read-only hints and hide create/import/edit/start/end/delete/reconfigure controls for Observers.
  - CDA table detail now lists unassigned active serials and can assign/remove that CDA table directly from `/cda/{table_id}`.
  - Basic Calculator now tracks the "awaiting second operand" state after an operator, so users can type `12 + 7 =` normally.
  - Static cache keys bumped to `app.css?v=24` / `app.js?v=24`.
- **0.18.6 — Calculator keyboard, account permissions view, chat badge + doc conflict fixes:**
  - **Basic Calculator keyboard/numpad input:** a global `keydown` handler in `app.js` routes keys to the active calculator (`activeCalcId()` picks the focus-containing calc, the last-used one via `window._lastCalcId`, or the only calc on the page). `mathCalcBody` now wraps the widget in `.math-calc[data-calc-id]` (focusable) and shows a keyboard hint. Keys: `0-9`, `+ - * /`, `Enter`/`=`, `Backspace`, `Esc`/`Delete` (clear), `.`/`,`, `%`. The handler ignores keys when a real input/textarea/select is focused elsewhere.
  - **Account type + permissions on Preferences:** the Account card (`preferences.html`) is now "Account & Permissions" — shows the signed-in user, their account type badge (Administrator/User/Observer), and a per-role capability table plus a plain-language summary. Read-only from `user.role`; no new route needed.
  - **Chat unread bubble stuck on "1" fix:** chat is ephemeral (in-memory server rooms), but `unread`/`unreadSenders`/`lastMessageIds` persist in `sessionStorage`. After a server restart the rooms vanish but the stale unread survived, and since the roster only renders rooms in `chatState.rooms`, the user could never open the room to clear it → badge stuck. `reconcileChatState(serverRooms)` (called in `refreshChatState` before `mergeChatRooms`) drops local room/unread state for any room the authoritative `/chat/state` no longer returns, then updates the badge.
  - **Document concurrent-edit conflict guard:** two users proposing edits to the same page previously caused a lost update — approving proposal A then B overwrote A (B's snapshot was based on the pre-A content). `DocVersion.base_content` (new nullable TEXT column, additive migration in `init_db.py`) records the page content each edit was drafted against. `_version_has_conflict()` flags a pending edit when `base_content != page.content`. The approval queue (`docs_approval.html`) shows a red **Conflict** badge, proposed-vs-current side-by-side panels, and a required confirmation checkbox; `POST /docs/versions/{vid}/approve` now takes `confirm_conflict` and refuses to publish a conflicting edit without it. Sibling pending edits automatically re-flag as conflicts once one is approved (their base no longer matches the live page). Not a full 3-way merge — it prevents *silent* overwrites and forces informed review.
  - Static cache keys bumped to `app.css?v=25` / `app.js?v=25`.
- **0.18.7 — Chat UI tidy-up:**
  - Reworked the chat roster (`base.html` `#chatDock`) into three clearer sections — **Unread**, **Conversations**, **People online** — inside a flex-column roster (header / scrolling body / fixed footer). Header shows a live online count (`#chatOnlineCount`, set in `renderChatRoster`); footer states messages clear on restart (reduces confusion about the intentionally ephemeral store).
  - Replaced the icon-only group toggle with a labelled **New group** button; the group creator is now its own bordered panel (`.chat-group-creator` restyled) with a header + **Cancel**, an optional group name, and an "Add people" list. `toggleChatGroupCreator()` now focuses the name field when opened.
  - Online user rows gained a hover chat affordance (`.chat-user-go`) and clearer per-user tooltips so it's obvious a click starts a private chat.
  - Friendlier empty states via a shared `.chat-empty` style (no conversations yet; new/empty conversation "say hello"), and the floating window composer placeholder is now "Type a message…". No changes to the polling/unread/window lifecycle logic.
  - Purely presentational — new CSS classes in `app.css`; the `chatState` model, endpoints, and dashboard chat widget are unchanged. Static cache keys bumped to `app.css?v=26` / `app.js?v=26`.
- **0.19.0 — Splitter/combiner live monitoring (SNMP, read-only):**
  - First item of the **range hardware monitoring expansion** (see ROADMAP). Adds read-only SNMP polling of splitter/combiner/switch matrices (ETL Systems **Genus** / **VTR/VTRC**), mirroring the CBM-400 integration pattern.
  - **New modules:** `app/snmp.py` (SNMP client + `MatrixSnapshot` + pure parse/OID helpers) and `app/snmp_sync.py` (`poll_snmp_device`, `poll_active_snmp_devices` — write observed routing onto `DevicePort`, audit on change, Testing-scoped). OIDs are resolved numerically from the ETL MIBs under `System Manuals/` (enterprise `1.3.6.1.4.1.20938`; `genus = …20938.1.7.5`): `hawkOutputRoutingSettings` for the crossbar, `systemSummaryAlarm` + `moduleInfoTable` for health. **No runtime MIB compilation.**
  - **pysnmp is 7.x (asyncio-only).** `poll_genus_matrix` is a **sync wrapper that runs the async pysnmp call on a private event loop in a dedicated thread** (`app/snmp.py::_run_blocking`) so it is safe from both a running FastAPI request handler and the background worker thread. **Do not** replace this with `asyncio.run()` directly — it fails inside the request loop. `requirements.txt` pins `pysnmp>=7.1,<8` (the old 4.x sync API conflicts with `python-jose`'s `pyasn1>=0.5`).
  - **Model:** `RFDevice` gains `snmp_enabled`, `snmp_version` (`2c`/`3`), `snmp_port`, `snmp_community_encrypted`, `snmp_v3_user`/`snmp_v3_auth_encrypted`/`snmp_v3_priv_encrypted` (encrypted via `app/crypto.py`), and `snmp_last_poll_*` + `snmp_system_alarm` cache. `DevicePort` gains `observed_routed_from` / `observed_label` — the **live** routing, kept separate from the manually-entered `routed_from` **plan** so the routing page shows planned-vs-actual with mismatch highlighting. Additive migrations in `init_db.py`.
  - **UI:** Devices page has an SNMP config block (routing devices only), an **SNMP Monitor** status column, a per-device **Test SNMP poll** button, and a **Poll SNMP** bulk action. The routing page shows a live SNMP alarm/health panel and a **Live (SNMP)** column beside the planned routing. Bootstrap-only — **no `app.css`/`app.js` change, so cache keys were NOT bumped.**
  - **Endpoints:** `POST /devices/{id}/snmp/test`, `POST /devices/snmp/poll-active` (both `require_supervisor`; Observer stays blocked). Optional background poller `SNMP_AUTO_SYNC_SECONDS` (default **0 = disabled**, opt-in) in `app/main.py`, mirroring the CBM auto-sync loop.
  - **Read-only by design** (never issues SNMP SET). **Guided state-change presets are deferred** (named presets, read-only guidance — see ROADMAP item 1 follow-up).
  - **Verification gap:** compile, unit tests (`tests/test_snmp.py`), import, init_db idempotency, template parse, boot smoke-test, and poll error-handling (sync + async contexts, v2c + v3) all pass locally — but **actual Genus/VTR SNMP reads are unverified**: SNMP must be enabled on the range devices with real credentials, and `parse_routing`'s row/column→output-index interpretation must be confirmed against the matrix front panel.
- **0.19.1 — SNMP matrix profiles (VTR/VTRC) + acknowledge module faults (from live testing):**
  - Live-hardware testing showed the range's splitter is a **VTR-101** and combiner a **VTRC-101** (not a Hawk matrix), so the single hardcoded Hawk routing OID returned nothing → every output showed "none". Replaced with a **`MatrixProfile` list + auto-detection** in `app/snmp.py`: on poll the client walks each family's routing table (`genusMatrix` indices verified from the MIBs — vtr101=9, vtr100=7, vtr102=11, vtrc100=8, vtrc101=10, vtrc102=12, hawk=2) and uses the first that returns rows. VTR/VTRC tables are **16-column**, Hawk is 8; `parse_routing(varbinds, base_oid, route_cols)` is now parameterised and the detected family is stored on `MatrixSnapshot.profile`.
  - **Acknowledge/mute module faults:** the range's PSUs report a **PSU2 fault** (empty/unpowered redundant slot) which rolled the device's `systemSummaryAlarm` to fault permanently. The effective/displayed alarm is now **derived from `moduleInfoTable`** (per-module status) minus a per-device ignore list (`RFDevice.snmp_ignored_modules`, CSV of module indices), via `effective_alarm_from_modules()`. `moduleInfoSummaryStatus` char meanings are mapped (`'A'`absent/`'0'`ok/`'W'`warn/`'C'/'2'/'3'`fault, etc.); absent/upgrading/invisible are treated as benign. The module table is cached on `RFDevice.snmp_modules_json` for the UI.
  - **Routing page** now shows a **module health panel** with per-module status badges + admin mute checkboxes (`POST /devices/{id}/snmp/ignore-modules`, recomputes the effective alarm immediately from the cache), an admin **Diagnostics** button (`GET /devices/{id}/snmp/diagnostics?base=<oid>` → raw SNMP walk as text, for discovering OIDs), and a clear "no live routing data" note instead of misleading "none" when a device returns no routing.
  - Additive migrations add `rf_devices.snmp_ignored_modules` + `snmp_modules_json`. Confirmed both range matrices are **SNMP v2c, community `public`**. Still needs a final eyeball: compare the Live (SNMP) column against each matrix front panel to confirm output/input numbering.

### ⚠ Outstanding REQUESTED work (NOT yet done — next assistant should pick these up)
1. **Theme QA / refinement** — 0.9.5 made the themes much more distinct and softened light mode, but it still needs a real browser pass with user feedback. If users still find a palette too bright/dim, tune `app/static/css/app.css` theme blocks.
2. **Browser QA of the UI overhaul + new features (0.12.0–0.15.0)** — all verified at compile/template + endpoint level (and CEASE/duty-role flows curl-tested end-to-end), but **not click-tested in a real browser**. Needs a pass over: sidebar collapse/expand + mobile overlay; dashboard grid side-by-side + span toggle persistence; new optional widgets (Range State, Active Signals, Last State Change) + calculator widgets; CDA countdown colour transitions; the CEASE splash appearing/dismissing across two sessions; duty-role badge rendering and colour contrast.
3. **Possible CEASE enhancement** — currently CEASE is a visual/logged all-stop alert only. The user may later want it to also force the range to Standby / record against the range-state log. Not requested yet; confirm before building.
4. **CBM sync hardware test + policy decision** — this is intentionally paused at manual-test stage. Next steps:
   - rebuild/install dependencies so `paramiko` is available in Docker;
   - enter EBEM credentials under Devices for each CBM;
   - use each row's plug/test button to verify SSH login → EBEM menu → ICC (`i`) → `tx_cfg ?`, `rx_cfg ?`, `all_stat ?`;
   - check parsed live values against what the EBEM/LCT GUI shows;
   - map real firmware statuses to Project Range states (`Up`, `Down`, `Configured`, `Standby`) and confirm whether `TX_OP=OFF` should always mean Down;
   - test `Sync Active CBMs` on a non-operational serial/package first;
   - only after proving the above, decide whether to add background polling and at what interval.
5. **CBM sync hardware validation** — the dashboard force button and 5-second automatic background poller are now implemented, but real range-hardware validation is still required before operators fully trust it.
   - Use Devices → Test CBM poll on each modem and compare parsed values against the EBEM/LCT GUI.
   - Confirm status mapping (`TX_OP`, receive lock/link states), timeout/retry behavior, ambiguous mapping safeguards, audit behavior, and Testing-state behavior.
   - If auto-sync is too chatty or too slow during hardware testing, tune `CBM_AUTO_SYNC_SECONDS` in the deployment environment (`0` disables the background task).
6. **Future: voice chat between single and multiple people** — requested as a possible extension to the existing instant chat.
   - Difficulty: **moderate to high** compared with text chat. One-to-one voice can be done with browser WebRTC, but reliable group voice usually needs a Selective Forwarding Unit/media server (for example Janus, mediasoup, LiveKit, or Jitsi components) rather than only FastAPI.
   - Project Range would need signaling endpoints/WebSockets, call UI, microphone permission handling, presence/call state, mute/deafen controls, group room membership, and network/firewall testing on the range LAN.
   - If all clients are on the same LAN, TURN may not be needed, but STUN/TURN planning should still be considered for multi-subnet or locked-down networks. Decide whether voice should be ephemeral only like current chat, whether it needs audit metadata (call started/ended, participants), and whether recording is explicitly out of scope.
   - Recommended implementation path: add WebSocket signaling first, prove one-to-one calls between two browser sessions, then either add small-group mesh for very small groups or introduce an SFU if multi-user voice is operationally important.
7. **Instant chat browser QA** — open two or more logged-in users/sessions and test: presence list updates, double-click private chat, group chat creation, send/receive, minimised-window alert, unread launcher badge, dashboard chat widget, page-change notification replay, logout/age-out behaviour, and mobile bottom-right layout. Decide later whether persistent DB chat history/audit is desired; current implementation is in-memory per app process plus browser `sessionStorage` read/unread tracking.
8. **Testing-state browser QA** — with at least one administrator and one user, test changing into/out of Testing, non-administrator state lock while Testing, creating/editing packages/serials/logs/devices/CDA/incidents/CEASE in Testing, then returning to normal states and confirming those Testing rows are hidden. Re-enter Testing and confirm they return.
9. **Dashboard Engaged column browser QA** — with an active serial, toggle Engaged on/off from the dashboard and confirm it saves immediately without using Submit All Changes, survives the 10-second dashboard refresh, appears/disappears through the Columns menu, and remains set after a status/power update or CBM sync update.

### Also pending (from ROADMAP)
- **Deferred infra (user's call):** HTTPS/TLS, PostgreSQL (+ Alembic). Cookies are TLS-ready (`SESSION_HTTPS_ONLY=1`).
- **1.0.0 gate:** deploy validated on range server, docs complete, backups verified, security Critical items closed (most are — see ROADMAP "Security hardening").

### Model/template changes the next assistant needs to know
- **`AppSetting`** — new key/value table in `models.py`; `init_db.py` seeds `local_timezone=UTC`. Do not make timezone per-user unless the requirement changes.
- **Navigation is a LEFT SIDEBAR now**, not a top navbar (since 0.13.0). The old `base.html` navbar/Settings/Admin dropdowns are gone. New nav links go in the sidebar sections in `base.html`; per-calc highlight uses `page` + `page_name`.
- **`Role` enum has THREE stored values:** `administrator`, `user`, `observer` (read-only). Old aliases `SUPERVISOR`, `OPERATOR`, and `SAFETY_SUPERVISOR` still map to the new values for compatibility with existing internal checks. Read-only is enforced in `main.py` `security_middleware` (blocks non-safe methods; allow-list `SAFETY_SUPERVISOR_ALLOWED_WRITES`). `SessionMiddleware` must stay **added last** (outermost) or `request.session` is empty in that check.
- **New models since 0.11.0:** `CDATable`, `CDAWindow`, `SerialCDATable` (CDA); `CeaseEvent` (CEASE); `DutyRole` + `User.duty_role`/`User.duty_role_color` (duty tags). All tables auto-create via `create_all`; the two `users` columns are additive migrations in `init_db.py`.
- **New routers:** `cda.py`, `cease.py` (both registered in `main.py`). Duty-role CRUD lives in `config.py`; duty-role self-set in `preferences.py`.
- **Static cache-busting is mandatory:** `base.html` references `app.css?v=N` and `app.js?v=N` (both currently **24**). **Bump N on every CSS/JS change** — without it, browsers serve a stale file and new JS handlers silently break (this exact bug hit the 0.13.0 sidebar/span buttons).
- **`partials/dashboard_summary.html` is now dead code** (the hardcoded summary row was removed in 0.13.0). Safe to delete; left in place for now.
- **Settings area** — now reached via the sidebar (user footer → Preferences/Password; administrator → Admin → App Config). The old Settings dropdown is gone.
- **`DeviceLink` and `RFDevice` new columns are fully implemented** — `device_model`, `has_web_gui`, and the `device_links` table are all in place. Device type list now includes `antenna`. No further migration needed for those.
- **CBM sync columns:** `signal_package_entries.cbm_device_id` / `cbm_path` / legacy `cbm_carrier`; `rf_devices.cbm_sync_enabled` / `cbm_username` / `cbm_password_encrypted` / `cbm_last_sync_*`; `users.active_session_token` for single-session enforcement. `cbm_carrier` remains in the DB for backward compatibility but is no longer shown in package signal parameters. Additive migrations are in `init_db.py`.
- **Dashboard Engaged column:** `SignalLog.engaged` is a per-signal visual flag used by operators to mark whether mission systems are affecting that signal. It is intentionally not part of the status enum and should not drive buzzer/range-state behavior.

### Caveats / verification gaps
- Theme switching verified at **build/markup level only** — not click-tested in a real browser. User confirmed themes "don't change enough", so **theme rework is still outstanding** (item 1 above).
- Login throttle is **in-memory** (per-process) — fine for single-container; revisit if multiple workers/HA.
- Topology SVG diagram is rendered entirely client-side in vanilla JS from embedded JSON — positions are auto-calculated by device type layer. No layout persistence; positions reset on page load. Works well for small topologies (< ~20 devices).
- The "Serial created before confirmation" DB artefact still exists: if a user clicks "Create & Start", the serial is committed before the confirmation page, so abandoning that page leaves an `is_started=False` serial in the DB. This is now less of a concern since pending serials are a first-class feature — the user can just delete it from the Pending list. But worth knowing.
- **CEASE / duty-role propagation are eventually-consistent via polling/DB**, not push: the CEASE splash appears on other screens within the **3-second poll** interval; fine for a single container, revisit if you ever run multiple workers behind a load balancer with sticky-less sessions.
- **Duty-role badge** uses white text on the configured colour with a text-shadow — very light colours read poorly. Admins should pick mid/dark colours, or a future tweak could auto-pick text colour by luminance.
- **Read-only Observer** is enforced by HTTP method + path allow-list, not per-endpoint. If you add a new write action an Observer *should* be able to do (like the duty-role tag), add its exact path to `SAFETY_SUPERVISOR_ALLOWED_WRITES` in `main.py`.

### Working conventions
- Each milestone: implement → **build+boot+smoke-test in Docker** → bump `APP_VERSION` in `app/config.py` → tick ROADMAP.md → **commit + push to `main`** (user pulls onto the range server directly; they prefer no PRs/branches — commit straight to `main`).
- **Bump the `?v=N` cache key on `app.css`/`app.js` in `base.html` whenever you touch either file** — browsers cache them aggressively and a stale JS file silently breaks new handlers.
- Keep everything **offline-capable** (no CDNs at all). Keep `docker-entrypoint.sh` LF.
- `init_db.py` migration pattern: new columns use `ALTER TABLE ADD COLUMN` in try/except (silent if already exists); renames use the `_rename_column()` helper that checks existing columns first.

---

## Project Summary

**Project Range** is an internal RF range operations support web application.
It helps range operators manage the "signal package" (active signals on the range), calculate
RF/IF frequencies, convert power units, log all range activity with timestamped audit trails,
and manage range state.

**Stack:** Python · FastAPI · SQLAlchemy (SQLite → PostgreSQL) · Jinja2 · HTMX · Bootstrap 5 (dark)
**Entry point:** `python run.py` (hot-reload dev server on port 8000)
**DB init:** `python init_db.py` (run once — creates tables + default admin user; re-running is safe)
**Default login:** `admin` / `changeme` (administrator role — change immediately)
**Scope document:** `Scope.txt`

---

## Architecture

```
project-range/
├── app/
│   ├── main.py          # FastAPI app, middleware, router registration, error handlers
│   ├── config.py        # SECRET_KEY, DATABASE_URL, SESSION_TIMEOUT_MINUTES, FREQUENCY_BANDS
│   ├── database.py      # SQLAlchemy engine, SessionLocal, Base, get_db()
│   ├── models.py        # All ORM models (see Database Models section)
│   ├── auth.py          # hash_password(), verify_password(), authenticate_user(), session_is_expired()
│   ├── deps.py          # FastAPI dependencies: get_current_user(), require_supervisor(),
│   │                    #   get_current_range_state(), get_active_serials()
│   ├── routers/
│   │   ├── auth.py          # GET/POST /login, GET /logout
│   │   ├── dashboard.py     # GET / (dashboard), GET /dashboard/fragment/{serial_id} (HTMX),
│   │   │                    #   POST /dashboard/quick-update, GET /status/buzzer, GET /status/serials
│   │   ├── calculator.py    # GET/POST /calculator/rf, /calculator/power, /calculator/power/chain,
│   │   │                    #   /calculator/eirp
│   │   ├── logs.py          # GET/POST /logs, /logs/new, /logs/note, /logs/{id}/edit,
│   │   │                    #   /logs/{id}/delete, /logs/{id}/restore, /logs/export/csv, /logs/export/xlsx
│   │   ├── packages.py      # Signal Package CRUD: GET/POST /packages, /packages/new,
│   │   │                    #   /packages/{id}, /packages/{id}/update, /packages/{id}/signals/*,
│   │   │                    #   /packages/{id}/delete, /packages/{id}/export, /packages/import
│   │   ├── serials.py       # Serial lifecycle: GET/POST /serials, /serials/new,
│   │   │                    #   /serials/{id}/start, /serials/{id}/end, /serials/{id}/packages/add
│   │   ├── history.py       # Closed serial history: GET /history, /history/{id},
│   │   │                    #   /history/{id}/export/csv, /history/{id}/export/xlsx
│   │   ├── handover.py      # GET /handover (on-screen shift summary), /handover/print (printable),
│   │   │                    #   /handover/report.xlsx (structured multi-sheet range report)
│   │   ├── range_state.py   # GET/POST /range-state/change
│   │   ├── config.py        # GET/POST /config — mod types, FEC types, signal sources, antennas,
│   │   │                    #   signal registry, frequency templates
│   │   ├── audit.py         # GET /audit — audit log viewer (administrator only)
│   │   ├── sessions.py      # LEGACY — kept for old data; no UI link (sessions replaced by serials)
│   │   ├── docs.py              # GET/POST /docs, /docs/new, /docs/{slug}, /docs/{slug}/edit,
│   │   │                    #   /docs/{slug}/history, /docs/{slug}/print, /docs/proposals,
│   │   │                    #   /docs/versions/{id}/approve|reject|restore
│   │   └── users.py         # GET/POST /users, /users/new, /users/{id}/toggle, /users/{id}/reset-password
│   ├── templates/
│   │   ├── base.html                    # Shared layout: nav, range state banner (HTMX serial badge),
│   │   │                               #   buzzer badge, toast container
│   │   ├── login.html                   # Standalone login page (no base)
│   │   ├── dashboard.html               # Live dashboard: serial widgets (SortableJS drag-to-reorder,
│   │   │                               #   drag-onto-another to tab-merge), summary cards, HTMX 10s poll
│   │   ├── calculator_rf.html           # RF frequency calculator
│   │   ├── calculator_power.html        # Power unit converter + gain/loss chain
│   │   ├── calculator_eirp.html         # EIRP calculator
│   │   ├── logs_list.html               # Log list with serial filter, search, export, narrative rows
│   │   ├── logs_form.html               # Create/edit signal log entry (embedded RF calculator)
│   │   ├── logs_note.html               # Narrative note form
│   │   ├── packages.html                # Signal Package list (card grid with badge counts)
│   │   ├── package_edit.html            # Package detail: metadata + signal table + add/edit form
│   │   ├── package_import.html          # Import package from JSON file
│   │   ├── serials.html                 # Active serials list + create-new form + add-package form
│   │   ├── serial_start.html            # Confirm/preview page before starting a serial
│   │   ├── handover.html                # On-screen shift handover snapshot (summary + per-serial signals)
│   │   ├── handover_print.html          # Printable/PDF shift handover sheet with sign-off lines
│   │   ├── history.html                 # Paginated searchable list of closed serials
│   │   ├── history_detail.html          # All logs for one closed serial, with export
│   │   ├── config.html                  # Administrator: mod types, FEC, sources, antennas, registry, freq templates
│   │   ├── audit_log.html               # Administrator: paginated audit log viewer
│   │   ├── sessions.html                # LEGACY — not linked in nav
│   │   ├── range_state_confirm.html     # State change confirmation form
│   │   ├── users.html                   # Administrator: user list + create + password reset
│   │   ├── devices.html                 # Device registry: status table (name, model, type, host, web GUI link), add/edit forms
│   │   ├── device_routing.html          # Routing matrix for splitter/combiner/switch (input labels, output→input routing, auto-hints from DeviceLink)
│   │   ├── topology.html                # Device topology: tabbed RF/IP/Clock/All views, SVG diagram, connection list, add-link form
│   │   ├── error.html                   # Generic error page (403, etc.)
│   │   └── partials/
│   │       ├── signal_table.html        # HTMX fragment: signal status table with inline quick-edit
│   │       ├── buzzer_badge.html        # HTMX fragment: buzzer badge for nav banner
│   │       └── active_serials_badge.html  # HTMX fragment: active serial count for nav banner
│   └── static/
│       ├── css/app.css    # Custom styles: range banner, blinking Live icon, table sizing
│       └── js/app.js      # Bootstrap tooltip init, toast helper, HTMX after-request hook
├── init_db.py   # DB creation + seed (admin user, initial range state, example signals, mod types)
├── run.py       # Uvicorn dev server launcher
├── requirements.txt
├── range.db     # SQLite database (created by init_db.py — not committed)
└── HANDOVER.md  # This file
```

### Key design decisions

- **Starlette 1.x API**: `TemplateResponse(request, "name.html", context)` — `request` is first positional arg, NOT in context dict.
- **bcrypt direct**: Using `bcrypt` package directly (not `passlib`) due to passlib/bcrypt incompatibility on Python 3.14.
- **SQLAlchemy ambiguous FK**: `SignalLog` has two FKs to `User` (`operator_id`, `updated_by_id`) — relationships specify `foreign_keys="SignalLog.operator_id"` etc. by string reference to avoid `AmbiguousForeignKeysError`.
- **SQLite for Phase 1**: `check_same_thread=False` set in connect_args. Switch DATABASE_URL env var to `postgresql://...` for Phase 2.
- **Session auth**: Cookie-based via `starlette.middleware.sessions.SessionMiddleware`. Session stores `user_id`, `role`, `display_name`, `logged_in_at` (ISO string). `session_is_expired()` checks elapsed time vs `SESSION_TIMEOUT_MINUTES`.
- **Dark mode**: Bootstrap 5 `data-bs-theme="dark"` on `<html>` in `base.html`.
- **SQLite migrations**: `init_db.py` runs `ALTER TABLE ... ADD COLUMN` in a `try/except` (safe to re-run) for any new columns added to existing models.
- **SortableJS 1.15.3** (CDN): dashboard widget drag-to-reorder.
- **localStorage `dashboardLayout_v2`**: dashboard tab-merge state persisted client-side.

---

## Database Models

| Model | Purpose |
|---|---|
| `User` | Auth, roles (user/administrator), active flag |
| `Signal` | Signal registry: named signals with defaults, exclusivity groups, optional `max_power_dbm` ceiling |
| `SignalLog` | Timestamped log of every signal state change (the audit trail + current state source of truth) |
| `RangeStateLog` | Timestamped record of every range state change |
| `ModulationType` | Administrator-managed list of modulation types shown in dropdowns |
| `FecType` | Administrator-managed list of FEC/code rate values shown in dropdowns |
| `SignalSource` | Administrator-managed list of signal sources (modems, signal generators) |
| `AntennaType` | Administrator-managed list of transmit antennas |
| `FrequencyTemplate` | Saved BUC/LO/TTF plans for the RF calculator (managed via Config page) |
| `DocPage` | Documentation wiki page (title, slug, Markdown content, published status) |
| `DocVersion` | Version history for a doc page (content snapshot, approval status, created/approved by) |
| `LogSession` | **LEGACY** — old named sessions; kept for old data compatibility, no active UI |
| `SignalPackage` | Named collection of pre-configured signal definitions (saved as JSON, importable). Now includes package-level RF config: band, antenna, BUC, LO, TTF, TTF direction, freq unit |
| `SignalPackageEntry` | One signal definition within a package (all params: name, band, freq, power, mod, etc.) |
| `Serial` | An operational run: has a title, assigned packages, open/close times, log entries |
| `SerialPackage` | Junction: which packages are assigned to which serial |
| `AuditLog` | System audit trail (login, edits, state changes, etc.) |
| `RFDevice` | Range device registry (name, device_model, type, host, check_port, location, has_web_gui, port counts). Types: modem, splitter, combiner, switch, ip_switch, spectrum_analyser, signal_generator, antenna, power_meter, reference_10mhz, sync_server, dc_injector, other |
| `AppSetting` | Global app settings, currently `local_timezone` for dashboard/log local-time display. Timezone is administrator/admin-managed, not per-user |
| `DevicePort` | Input/output port on a routing device (splitter/combiner/RF switch) — stores per-port label and routed_from index |
| `DeviceLink` | Directed connection between two `RFDevice` instances (from_device → to_device). Fields: from/to port label + port index, link_type (rf/ip/clock/power), label. Port index maps to `DevicePort.idx` for routing page auto-hints |
| `Incident` | Incident/fault report (severity, status, affected equipment, associated serial, resolution) |

### Package-level RF Configuration (IMPORTANT)

`SignalPackage` stores band, antenna, BUC, LO, TTF, TTF direction, and freq unit at the package level — these are shared by **all signals** in the package (all signals go on the same satellite antenna and use the same transponder plan).

**On log form (`/logs/new`)**: when a serial is selected, `GET /serials/{id}/rf-config` is called (JSON) and the response pre-fills BUC/LO/TTF/band/antenna. The user only needs to enter one known frequency; the other three resolve automatically via the existing embedded calculator JS.

**On serial start**: `serial_start` copies `pkg.band` and `pkg.antenna` into the initial `SerialStart` log entries for each signal. Existing per-signal freq values (`tx_if` etc.) on `SignalPackageEntry` are still respected when present.

**On dashboard quick-edit**: the fragment endpoint passes `pkg_rf` to the `signal_table.html` partial; the Antenna select defaults to the package antenna when the log row has no antenna set.

Per-signal band and antenna fields are removed from the package signal add/edit form (but the DB columns remain for backward compatibility). Band and Antenna are now set at the package level only.

---

### Signal Package → Serial → SignalLog data flow (IMPORTANT)

**Signal Package**: A pre-built, reusable set of signal definitions with all parameters. Saved as human-readable JSON (importable). Lives at `/packages`. Built from the signal registry or ad-hoc.

**Serial**: An operational session (replaces `LogSession`). Has a title and is associated with one or more Signal Packages. When a serial is **started**:
1. `SignalLog` entries are created for each unique signal in the assigned packages (status `"Planned"`, `entry_type="SerialStart"`)
2. A narrative `SerialStart` entry is logged

When a serial **ends**, `closed_at` is set and a `SerialEnd` narrative entry is logged. Ended serials appear in **History**.

**Dashboard**: One widget per active serial. `_latest_signal_status(db, serial_id=serial.id)` derives current signal state from the most recent `SignalLog` per signal name filtered to that serial.

**HTMX polling**: Each serial widget polls `/dashboard/fragment/{serial_id}` every 10s independently.

### `Signal.exclusivity_group`
If a signal has an `exclusivity_group` value (any non-null string), then when it is set to `Up` via the dashboard quick-edit, all other signals with the **same** `exclusivity_group` string that are currently `Up` will be automatically set to `Down`. Two log entries are created: one for the auto-down, one for the new up. The auto-down entry has `entry_type="Automatic"` and notes the reason.

---

## entry_type values on SignalLog

| value | Meaning |
|---|---|
| `Manual` | User manually created a log entry via `/logs/new` |
| `Dashboard` | User used the quick-edit panel on the dashboard |
| `Automatic` | Auto-down triggered by exclusivity group enforcement |
| `Narrative` | Plain-text note (`signal_name="[NOTE]"`, `signal_status="Note"`) |
| `SerialStart` | Pre-populated signal entries created when a serial starts |
| `SerialEnd` | Closing note when a serial ends |

---

## RF Frequency Maths

```
TxIF + BUC = TxRF
TxRF ± TTF = RxRF   (TTF direction user-selectable: + or −)
RxRF − LO  = RxIF
```

Given any one of the four frequencies plus BUC, LO, TTF, the calculator solves for all four.
All values are converted to MHz internally, then converted to the selected output unit for display.
Band validation compares TxRF/RxRF in GHz against configured ranges in `config.py → FREQUENCY_BANDS`.
Warnings are displayed but do not block saving.

The last BUC/LO/TTF values from the RF calculator are stored in the user's session and
pre-filled into the "Conversion Values" row on the New Log Entry form.

## EIRP Formula

```
EIRP (dBW) = TxPower (dBW) − CableLoss (dB) + AntennaGain (dBi) − OtherLosses (dB)
```

Input accepts dBm/dBW/W for Tx power; converts to dBW internally. Output shown in dBW, dBm, W, kW.

---

## Implemented Features

- [x] Login / logout with session timeout (8 hours default)
- [x] Two roles: user, administrator
- [x] RF frequency calculator (TxIF/TxRF/RxRF/RxIF from any one known frequency + BUC/LO/TTF)
- [x] Live RF recalculation — changing any frequency or any conversion value instantly recalculates the other three (JS, no page reload)
- [x] Frequency band validation with warnings (C, X, Ku, Ka)
- [x] Frequency template loading (load saved BUC/LO/TTF into calculator)
- [x] Power unit converter (dBm ↔ dBW ↔ W)
- [x] Gain/loss chain calculator with per-stage output
- [x] **EIRP calculator** (`/calculator/eirp`): Tx power + cable/feed loss + antenna gain + other losses → EIRP in dBW/dBm/W with step-by-step breakdown
- [x] New Log Entry form: embedded RF calculator with BUC/LO/TTF pre-filled from last calculator use (session)
- [x] New Log Entry form: enter any one frequency → the other three auto-calculate in real time
- [x] Signal log creation and editing
- [x] Signal log soft-delete and administrator restore
- [x] Log list with search, filter by status/band/date/activity/serial
- [x] Log list pagination (100 records per page)
- [x] Export logs to CSV and XLSX (with active filters applied)
- [x] Audit logging for log create/edit/delete/restore and range state changes
- [x] Range state management (Closed Loop / Live / Standby/Off)
- [x] Range state change requires reason + confirmation
- [x] Live range state banner (blinking red when Live)
- [x] Live dashboard with current signal status table (derived from latest log entry per signal)
- [x] Dashboard HTMX auto-refresh every 10 seconds (per-serial widget)
- [x] Status colour-coding (Up=green, Faulted=red, Standby=amber, Down=grey, Configured=blue, Planned=teal)
- [x] **Dashboard inline quick-edit**: each signal row has a pencil button that expands an edit panel
- [x] **Dashboard poll paused while edit row is open**
- [x] **Signal exclusivity groups**: auto-down siblings in the same group when one goes Up
- [x] **Signal Registry** on Config page: administrators can add, edit, toggle, delete signals and set their exclusivity group
- [x] **Modulation, FEC, Source, Antenna management** on Config page (administrator only)
- [x] **Audit Log Viewer** (`/audit`): administrator-only paginated view
- [x] **Frequency template management** on Config page
- [x] User management (administrator only: create, enable/disable, reset password)
- [x] Dark mode throughout
- [x] Buzzer Active indicator — flashing red "BUZZER ON" banner + badge when range is Live/Closed Loop and any signal is Up; polls every 10s via HTMX
- [x] Toast notifications on log create, edit, delete, restore, range state change, dashboard quick-edit
- [x] **Narrative / manual log notes** (`/logs/note`): plain-text notes appear as amber italic rows in the log list
- [x] **Signal history view**: clicking any signal name on dashboard or log list filters to that signal's full history
- [x] **Dashboard last-state-change card**: 4th summary card shows time and user of most recent range state change
- [x] **Signal Packages** (`/packages`): named collections of pre-configured signals with all parameters. Saved as human-readable JSON, importable. Can be built from signal registry or ad-hoc. Displayed as a card grid with signal count badges.
- [x] **Serials** (`/serials`): operational sessions with title + assigned packages. Starting a serial pre-populates the dashboard with signals at "Planned" status. One widget per active serial on the dashboard. "End Serial" moves to History.
- [x] **Dashboard serial widgets**: one card per active serial; SortableJS drag-to-reorder; drag one widget onto another to merge as a tabbed card. Layout persisted in `localStorage.dashboardLayout_v2`.
- [x] **History** (`/history`): paginated searchable list of closed serials. Click to view all logs for that serial with CSV/XLSX export.
- [x] **Active serial badge in nav banner**: HTMX polls `/status/serials` every 15s — shows "N serials active" or "No active serial" as a link to `/serials`.
- [x] **Package duplicate**: "Duplicate" button on package edit page creates a `{name} (copy)` package with all signals copied.
- [x] **Package signal reorder**: SortableJS drag-to-reorder within package signal list; `fetch` POST to `/packages/{id}/signals/reorder` on drop.
- [x] **Dashboard quick-edit HTMX fix**: per-serial widget containers now have unique IDs (`signalTableContainer-{id}`); quick-edit form targets the correct container and submits `serial_id` hidden field; response returns only that serial's signals.
- [x] **Dashboard layout restore on page load**: `restoreLayout()` runs on `DOMContentLoaded`, re-applies tab merges and drag order from `localStorage.dashboardLayout_v2`.
- [x] **Dashboard "Add signal" button**: each serial widget header has a `+` button linking to `/logs/new?serial_id={id}` which pre-selects that serial on the log form.
- [x] **Log form pre-selects serial via query param**: `GET /logs/new?serial_id=N` pre-selects serial N in the Serial dropdown (without the param, the first active serial is auto-selected).
- [x] **Drop-merge-target visual**: `drop-merge-target` CSS class added; buzzer alert has a pulsing box-shadow animation.
- [x] **HTMX loading spinner**: per-serial widget header shows a spinner while the 10s poll is in flight.
- [x] **Documentation / Wiki module** (`/docs`): Markdown pages with version history, administrator direct edit, user edit proposals, approval queue, printable view. 7 seed pages covering core procedures. Nav link visible to all users; pending-proposal badge for administrators.
- [x] **Package-level RF configuration**: `SignalPackage` now stores band, antenna, BUC, LO, TTF, TTF direction, and freq unit shared by all signals in the package. When a serial's log entry is created, BUC/LO/TTF/band/antenna are auto-populated from the package — operators only enter one known frequency and the rest resolve automatically. Dashboard quick-edit defaults the Antenna select from the package config. Serial start log entries inherit package-level band and antenna.
- [x] **Package signal form real-time RF calc**: on the package signal add/edit form, entering any one frequency (TxIF/TxRF/RxRF/RxIF) auto-calculates the other three from the package's BUC/LO/TTF (read live from the form, before saving). Package and signal freq units are converted independently.
- [x] **Shift Handover module** (`/handover`): point-in-time snapshot of range state, signals-up count, buzzer, and per-serial signal status tables, plus recent range-state changes and notes. `/handover/print` renders a printable/PDF sheet with off-going/on-coming sign-off lines (auto-opens print dialog). Nav link visible to all users.

---

## Not Yet Implemented (Phase 2 and beyond)

### Architecture / Design

- [ ] **Signal architecture refactor**: Currently current signal state is derived from the latest `SignalLog` entry per signal name. The intended design is: `Signal` holds current live state as an entity, `SignalLog` records every change as a history/audit trail.

### Features

- [ ] PostgreSQL migration (switch DATABASE_URL env var, test thoroughly)
- [x] Power warning thresholds per-signal — `Signal.max_power_dbm` (set on the Config → Signal Registry tab). When a log entry records a power above the ceiling (converted to dBm), `SignalLog.warning_flags` is populated and shown in the dashboard "Warn" column. Computed in `app/signal_warnings.py`, wired into manual log create/edit and dashboard quick-update.
- [x] **Band/frequency validation warnings** — the same `warning_flags_for` engine also flags TxRF/RxRF outside the configured `FREQUENCY_BANDS` range for the entry's band (reuses the calculator's `band_warnings`). Power and band warnings are combined into one ` · `-joined `warning_flags` string. Stored on log create/edit and dashboard quick-update (warnings are advisory; they never block saving).
- [x] Formal range report export — structured multi-sheet XLSX via `/handover/report.xlsx` (Summary / Signals / State Changes / Notes), downloadable from the Handover page. PDF still available via the Handover print view (browser "Save as PDF").
- [ ] Device ping / network status checks
- [x] Shift handover module (print/PDF summary of signals and state at shift change) — see Implemented Features
- [ ] Active Directory / SSO authentication
- [x] Session: "remember this terminal" option for thin clients — checkbox on the login page; when set, `session["remember"]` makes `session_is_expired()` skip the inactivity timeout, so a fixed terminal stays signed in up to the cookie lifetime (`SESSION_MAX_AGE_DAYS`, default 30). Normal logins still expire after `SESSION_TIMEOUT_MINUTES` of inactivity.
- [ ] More detailed permissions model beyond user/administrator
- [ ] Backup and restore tooling
- [ ] Windows Server deployment packaging (Waitress/NSSM service)
- [ ] HTTPS/TLS support
- [ ] Dashboard: "Add signal" form directly on dashboard (currently requires /logs/new)
- [x] **Dashboard inline on/off + power controls**: per-signal-row switch to set Up/Down, and −/+ stepper buttons (step 1) plus an editable number field to set power directly, with Submit/Cancel; a log entry is only written on Submit. The 10s poll pauses while any row has unsubmitted changes. Replaces needing the pencil→Status-dropdown path for the common on/off + power changes (full edit panel still available for other fields).
- [x] **Dashboard column show/hide**: a "Columns" dropdown (checkbox per column) toggles visibility of any of the 17 signal-table columns across all widgets at once; choice is saved in `localStorage.dashboardHiddenCols` and re-applied after every 10s poll swap (`data-col` attributes on each th/td; `applyColumnVisibility` on `htmx:afterSwap`).
- [x] **Dashboard widget minimise/expand**: each widget header has a chevron button (`toggleCollapse`) that collapses the body to just the header; per-widget collapsed state is saved in `localStorage.dashboardLayout_v2` and restored on load.
- [x] **Buzzer indicator toned down**: the large pulsing "BUZZER ON" banner is replaced by a compact one-line red bar (`.buzzer-bar`); blinking removed from the nav badge, summary card, and per-widget badge (only the Live range-state indicator still blinks). The big "BUZZER OFF" banner was removed (nav badge + summary card already convey it).
- [x] **Dashboard drag tabbing UX**: each serial's body + header actions live together in a `.serial-body-wrap`. **Merge** = drag a serial's tab onto another widget to combine them into one tabbed card. **Split** = a "Pop out" button in the tabbed card header pops the active tab back into its own standalone widget (dragging a tab to empty space also splits, but the button is the reliable path when widgets fill the screen). Grip icon still reorders widgets (SortableJS). Layout persisted in `localStorage.dashboardLayout_v2`.

---

## QoL / Polish List

- [x] Log list: column sort — `sort` + `sort_dir` query params; sortable columns: timestamp, signal_name, signal_status, band; icon shows current sort direction
- [x] Keyboard shortcut `N` → `/logs/new` (suppressed when focus is in input/textarea/select)
- [x] Calculator: "Create Log Entry" button appears in RF calculator results header after a calculation; links to `/logs/new?tx_if=…&tx_rf=…&rx_rf=…&rx_if=…&freq_unit=…&band=…` which pre-fills the frequency fields on the form
- [ ] Power chain: save/load named templates (model stub ready — `PowerChainTemplate` not yet wired to UI)
- [x] Favicon: SVG signal-arcs icon (`/static/favicon.svg`), served via `<link rel="icon" type="image/svg+xml">`
- [ ] Mobile/tablet responsive polish (currently desktop-first but not broken) — **VERY LOW priority**: this app is almost never used on mobile, so deprioritise mobile/tablet work.
- [ ] **UI refinement pass (raised 2026-06-22, ongoing)**: the interface is starting to feel clunky as features accumulate and needs a consolidation/refinement pass (spacing, density, grouping of controls). Dark-scheme contrast also needs auditing. **Done so far:** buzzer indicator toned down (compact bar, no pulsing box-shadow, blinking removed from all buzzer elements — only the Live range-state still blinks); dashboard widgets are now minimisable/expandable (persisted); first contrast fixes (lighter muted text via `--bs-secondary-color`, lighter standby banner). **Done since:** dashboard signal rows now use subtle dark status tints (`.status-up/-down/-faulted/-standby` via `--bs-table-bg`) instead of Bootstrap's loud light contextual backgrounds — so the light text and inline controls stay readable (this was the main "hard to read" case: `text-muted` cells on light rows); read-only colored tables (log list, history) get a dark muted-text override so their muted cells stay legible on the light rows. **Done since:** Config page split into tabs (Modulation / FEC / Sources / Antennas / Freq Templates / Signal Registry) instead of one long scroll; grey `bg-secondary` badges darkened to #565e64 for AA contrast; log list + serial history signal rows now use the same subtle dark status tints as the dashboard. **Still to do:** density/spacing pass on the remaining forms; input-group text contrast.
- [x] **Navigation consolidation**: top-level nav reduced — RF/Power/EIRP grouped under a **Calculators** dropdown (Power and EIRP were previously unreachable from the nav), and the three administrator links (Users, Audit, Config) grouped under an **Admin** dropdown. Navbar density tightened.
- [x] Loading indicator during HTMX poll refresh (spinner in widget header)
- [x] Dashboard quick-edit: exclusivity group warning — "Auto-downs: X, Y" shown below Status select, visible only when "Up" is chosen (JS show/hide)
- [x] Config drag-to-reorder: SortableJS on all four lists (mod types, FEC, sources, antennas); grip handle column; `fetch` POST to `/config/{type}/reorder` on drop; toast on success. Reorder endpoints added for FEC, sources, antennas (mod already existed).

---

## Known Issues / Bugs

- ~~**Dashboard summary/buzzer stale on poll**~~: Fixed — the 10s poll only swapped each serial's table body, so the summary cards (Active Signals count, Faulted) never updated and the buzzer bar reflected only the last-polled serial's local state (flipping wrongly with multiple serials). Now the poll + quick-update render `partials/dashboard_fragment.html`, which OOB-swaps the global summary cards, the global buzzer bar, and the per-widget buzzer badge. Global aggregates (`up_count`, `faulted_count`, `any_buzzer`) come from `_dashboard_ctx`.
- ~~**Chain calculator stage index**~~: Fixed — `removeStage()` now renumbers all remaining `.stage-row` name attributes to fill gaps and resets `stageCount`.
- **`updated_at` not set by SQLAlchemy `onupdate` on SQLite**: Fixed by setting `log_entry.updated_at = datetime.utcnow()` explicitly in update handlers. Verify behaviour on PostgreSQL.
- **HTTPException 302 handler**: Using HTTPException with status 302 for auth redirects is non-standard. Consider middleware or a custom exception class for cleaner handling.
- **Serial created before confirmation**: When a user uses "Create & Start", the serial is committed to DB before the confirmation page. If they abandon the confirmation page, an `is_started=False` serial sits in the DB. Now lower impact — it appears in the **Pending** section on `/serials` where it can be deleted or started. It won't appear on the dashboard.
- **Dashboard tab-merge order restore**: On page refresh, `restoreLayout()` re-applies tab merges and drag order from localStorage. Works for tab merges; order restore uses `appendChild` which may reorder incorrectly if saved order doesn't match current DOM order exactly.

---

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | `dev-secret-change-in-production-please` | Session signing key |
| `DATABASE_URL` | `sqlite:///range.db` | SQLAlchemy DB connection |
| `SESSION_TIMEOUT_MINUTES` | `480` (8 hours) | Auto-logout after inactivity (skipped for "remember this terminal" sessions) |
| `SESSION_MAX_AGE_DAYS` | `30` | Session cookie lifetime; the ceiling for "remember this terminal" sessions |

---

## Running the App

```bash
# First time only
pip install -r requirements.txt
python init_db.py

# Start dev server
python run.py
# Open http://localhost:8000
# Login: admin / changeme
```

If port 8000 is already in use (previous uvicorn process):
```bash
fuser -k 8000/tcp && python run.py
# or
pkill -f uvicorn && sleep 1 && python run.py
```

For production (Windows Server):
```bash
pip install waitress
waitress-serve --host=0.0.0.0 --port=8000 app.main:app
```

---

## Build Phases (from Scope.txt)

| Phase | Status | Description |
|---|---|---|
| 1 — Linux Prototype | **In progress** | Current build. SQLite, core features working. |
| 2 — MVP Feature Build | Not started | PostgreSQL, docs module, audit viewer, device pings |
| 3 — Windows Server Trial | Not started | Deploy to Windows Server 2025, thin client testing |
| 4 — Operational Hardening | Not started | Backup/restore, HTTPS, service deployment |

---

## Open Questions (from Scope.txt §17 and ongoing)

1. Exact frequency ranges for C, X, Ku, Ka — provisional values in `config.py`, need confirmation.
2. TTF direction — always user-selectable or template-locked?
3. BUC/LO — entered as free values or from equipment templates?
4. Exact modulation type list beyond BPSK/QPSK/8PSK/16APSK/32APSK.
5. Whether PostgreSQL can be installed on the Windows Server.
6. Whether exports need to match an existing official format.
7. Whether device ping checks are permitted on range network.
8. Log retention policy.
9. Whether HTTPS will be required before go-live.
10. **Exclusivity groups**: Should groups be formally managed (with a group name, description, member list) or remain as a simple shared string tag on signals (current implementation)?
