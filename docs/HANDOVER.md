# Project Range — Handover Document

<!-- IMPORTANT: Update this file whenever features are added, changed, bugs are found, or new requirements arise.
     This is the canonical reference for any assistant continuing work on this project. -->

---

## ⚑ Current Status & Handover — 2026-06-26 (READ THIS FIRST)

> The detailed sections **below this block predate a large body of work** and are
> partially stale (e.g. port, model/router lists, "dark only"). For *planned* work
> the source of truth is **[ROADMAP.md](ROADMAP.md)**; for *current behaviour* trust
> the code. This block summarises where things actually are.

**App name:** "SEW Range" (re-branded from "Project Range"). **Version:** `0.10.1` (single source: `app/config.py` `APP_VERSION`, shown bottom-right in UI).
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
- **Logs:** hard-delete added (supervisor, only on soft-deleted rows) alongside existing soft-delete/restore.
- **Range state:** going **Live** requires safety acknowledgment + supervisor authorisation (operators enter a supervisor's credentials = two-person).
- **Dashboard bulk-submit** (0.9.2): per-row green tick replaced with a single "Submit All Changes" bar at the bottom of each serial widget. All staged signal changes in that widget are sent in one `POST /dashboard/bulk-update` (JSON body) and committed in a single DB transaction — staging multiple signals then submitting no longer wipes other staged rows.
- **0.9.2 bug fixes:**
  - Password minimum length set consistently to **6** across config, server validation (`auth.py → validate_password`), and all HTML `minlength` attributes. Previously the server enforced 10 but the form showed 8. `MIN_PASSWORD_LENGTH` is envvar-overridable.
  - **HTMX chaos on forced password-change page fixed:** When a new user logs in and must change their password, the range-state banner HTMX pollers in `base.html` were firing on page load and following the `must_change_password` redirect, injecting a full HTML page into tiny `<span>` elements — causing the card to visually jump and inputs to be unresponsive. Fixed by wrapping both poller spans in `{% if not user.must_change_password %}` guards.
- **0.9.3 — Device page enhancements + Serial pending:**
  - **New device types:** IP Switch, 10MHz Reference, Sync Server, DC Injector added to the device type dropdown (alongside existing Modem, Splitter, Combiner, RF Switch, Spectrum Analyser, Signal Generator, Power Meter, Other).
  - **Device name vs model:** `RFDevice` now has two separate text fields — `name` (unique instance name, e.g. `CBM-400-1`) and `device_model` (product model, e.g. `CBM-400`). Both shown in the devices table. Migration adds `device_model VARCHAR(128)`.
  - **Web GUI link:** `RFDevice.has_web_gui` boolean (checkbox in add/edit form). When set, a "Open" link button appears in the devices table pointing to `http://<host>/`. `web_gui_url` is a Python property on the model.  Migration adds `has_web_gui BOOLEAN DEFAULT 0`.
  - **Topology page** (`/devices/topology`, `app/templates/topology.html`): tabbed view (RF / IP / Clock / All), SVG diagram auto-arranged by device layer type (modems/generators at top, switches/combiners in middle, instruments at bottom), colour-coded connections (RF=gold, IP=teal, Clock=purple, Power=red). Connection list table with delete for supervisors. Add-connection form for supervisors (from device / port / port index → to device / port / port index / type / label). "Topology" button in devices page header.
  - **`DeviceLink` model** (`app/models.py`): stores directed connections between `RFDevice` instances. Fields: `from_device_id`, `from_port` (label), `from_port_idx` (integer, for routing matrix integration), `to_device_id`, `to_port`, `to_port_idx`, `link_type` (rf/ip/clock/power), `label`. Table auto-created by `Base.metadata.create_all`.
  - **Routing page auto-hints:** When a `DeviceLink` has `to_port_idx` matching a combiner/splitter port, the routing page (`/devices/{id}/routing`) pre-populates that port's label with the connected device's name and shows a "linked: DeviceName" hint. Input hints from the `to` side of links; output hints from the `from` side.
  - **Serial pending / pre-create:** The serial create form (`/serials`) now has two buttons — **Save as Pending** (creates the serial with packages attached, `is_started=False`, redirects to serials list) and **Create & Start** (existing behaviour, goes to start confirmation). Pending serials appear in a "Pending — not yet started" section at the top of the serials page with Start and Delete buttons. `Serial.is_started` and the pending/active separation already existed in the DB and router; the only change was adding the `action` form param and the second button.
- **0.9.4 — Log readability:** `/logs` and `/history/{serial_id}` now compare each signal log entry with the previous entry for that signal in the same serial. Changed fields are summarized in a new "Changed" column and visible changed cells get a subtle accent highlight. Serial history lifecycle rows now use calmer custom colours for `SerialStart`, `SerialEnd`, and narrative notes instead of the bright warning-yellow row.
- **0.9.5 — Settings/theme polish:**
  - **Settings discoverability:** main navbar now has a visible **Settings** dropdown with Your Preferences, Password, and supervisor-only Admin Config. User display name still links to preferences.
  - **Theme rework:** palettes now change body canvas, navbar, cards, borders, and muted panel surfaces, not just button/link accents. Light mode is softened from Bootstrap's stark white with darker text and stronger borders. CSS cache key bumped to `app.css?v=11`.
  - **Login theme toggle polish:** login page now syncs the sun/moon icon with the saved light/dark mode on load.
- **0.10.0 — Dashboard clock + timezone/log time polish:**
  - **Dashboard Zulu/local clock widget:** dashboard now has a draggable, hideable clock widget showing Zulu (UTC) and the configured local timezone. It uses the existing dashboard widget container, grip reorder, collapse, and localStorage layout persistence. The widget can be re-shown from the dashboard "Clock" button.
  - **Global local timezone:** timezone is **not per-user**. Supervisors set it under `/config` → System. Stored in new `AppSetting` table (`key="local_timezone"`, default `"UTC"` seeded by `init_db.py`).
  - **Logs are Zulu-first:** `/logs` and `/history/{serial_id}` always show timestamps with `Z`. Optional "Show local time" checkbox adds a second local-time line using the configured timezone. CSV/XLSX exports now label timestamp columns as "Timestamp (Zulu)" and include `Z`.
  - **Device type:** "Antenna" added as a selectable device type in the Devices registry and topology layering.
- **0.10.1 — Backup script:** Added `scripts/backup_db.py`, a Docker Compose friendly SQLite backup script that copies `/app/data/range.db` to `./backups/range-<UTC>.db` and prunes old backups with `--keep`. `docs/DEPLOY.md` now documents backup scheduling and restore steps. `backups/` is gitignored.

### ⚠ Outstanding REQUESTED work (NOT yet done — next assistant should pick these up)
1. **Theme QA / refinement** — 0.9.5 made the themes much more distinct and softened light mode, but it still needs a real browser pass with operator feedback. If users still find a palette too bright/dim, tune `app/static/css/app.css` theme blocks.
2. **Dashboard clock browser QA** — 0.10.0 implementation was verified at compile/template level only. Needs a browser pass for drag/order persistence, hide/show, and timezone rendering.

### Also pending (from ROADMAP)
- **Deferred infra (user's call):** HTTPS/TLS, PostgreSQL (+ Alembic). Cookies are TLS-ready (`SESSION_HTTPS_ONLY=1`).
- **1.0.0 gate:** deploy validated on range server, docs complete, backups verified, security Critical items closed (most are — see ROADMAP "Security hardening").

### Model/template changes the next assistant needs to know
- **`AppSetting`** — new key/value table in `models.py`; `init_db.py` seeds `local_timezone=UTC`. Do not make timezone per-user unless the requirement changes.
- **Settings area** — visible Settings dropdown is shipped in `base.html` (Preferences, Password, supervisor Admin Config). A dedicated tabbed `/settings` page is still optional if the nav dropdown is not enough.
- **`DeviceLink` and `RFDevice` new columns are fully implemented** — `device_model`, `has_web_gui`, and the `device_links` table are all in place. Device type list now includes `antenna`. No further migration needed for those.

### Caveats / verification gaps
- Theme switching verified at **build/markup level only** — not click-tested in a real browser. User confirmed themes "don't change enough", so **theme rework is still outstanding** (item 1 above).
- Login throttle is **in-memory** (per-process) — fine for single-container; revisit if multiple workers/HA.
- Topology SVG diagram is rendered entirely client-side in vanilla JS from embedded JSON — positions are auto-calculated by device type layer. No layout persistence; positions reset on page load. Works well for small topologies (< ~20 devices).
- The "Serial created before confirmation" DB artefact still exists: if an operator clicks "Create & Start", the serial is committed before the confirmation page, so abandoning that page leaves an `is_started=False` serial in the DB. This is now less of a concern since pending serials are a first-class feature — the operator can just delete it from the Pending list. But worth knowing.

### Working conventions
- Each milestone: implement → **build+boot+smoke-test in Docker** → bump `APP_VERSION` in `app/config.py` → tick ROADMAP.md → **commit + push to `main`** (user pulls onto the range server directly; they prefer no PRs/branches — commit straight to `main`).
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
**Default login:** `admin` / `changeme` (supervisor role — change immediately)
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
│   │   ├── audit.py         # GET /audit — audit log viewer (supervisor only)
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
│   │   ├── config.html                  # Supervisor: mod types, FEC, sources, antennas, registry, freq templates
│   │   ├── audit_log.html               # Supervisor: paginated audit log viewer
│   │   ├── sessions.html                # LEGACY — not linked in nav
│   │   ├── range_state_confirm.html     # State change confirmation form
│   │   ├── users.html                   # Supervisor: user list + create + password reset
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
| `User` | Auth, roles (operator/supervisor), active flag |
| `Signal` | Signal registry: named signals with defaults, exclusivity groups, optional `max_power_dbm` ceiling |
| `SignalLog` | Timestamped log of every signal state change (the audit trail + current state source of truth) |
| `RangeStateLog` | Timestamped record of every range state change |
| `ModulationType` | Supervisor-managed list of modulation types shown in dropdowns |
| `FecType` | Supervisor-managed list of FEC/code rate values shown in dropdowns |
| `SignalSource` | Supervisor-managed list of signal sources (modems, signal generators) |
| `AntennaType` | Supervisor-managed list of transmit antennas |
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
| `AppSetting` | Global app settings, currently `local_timezone` for dashboard/log local-time display. Timezone is supervisor/admin-managed, not per-user |
| `DevicePort` | Input/output port on a routing device (splitter/combiner/RF switch) — stores per-port label and routed_from index |
| `DeviceLink` | Directed connection between two `RFDevice` instances (from_device → to_device). Fields: from/to port label + port index, link_type (rf/ip/clock/power), label. Port index maps to `DevicePort.idx` for routing page auto-hints |
| `Incident` | Incident/fault report (severity, status, affected equipment, associated serial, resolution) |

### Package-level RF Configuration (IMPORTANT)

`SignalPackage` stores band, antenna, BUC, LO, TTF, TTF direction, and freq unit at the package level — these are shared by **all signals** in the package (all signals go on the same satellite antenna and use the same transponder plan).

**On log form (`/logs/new`)**: when a serial is selected, `GET /serials/{id}/rf-config` is called (JSON) and the response pre-fills BUC/LO/TTF/band/antenna. The operator only needs to enter one known frequency; the other three resolve automatically via the existing embedded calculator JS.

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
| `Manual` | Operator manually created a log entry via `/logs/new` |
| `Dashboard` | Operator used the quick-edit panel on the dashboard |
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
- [x] Two roles: operator, supervisor
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
- [x] Signal log soft-delete and supervisor restore
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
- [x] **Signal Registry** on Config page: supervisors can add, edit, toggle, delete signals and set their exclusivity group
- [x] **Modulation, FEC, Source, Antenna management** on Config page (supervisor only)
- [x] **Audit Log Viewer** (`/audit`): supervisor-only paginated view
- [x] **Frequency template management** on Config page
- [x] User management (supervisor only: create, enable/disable, reset password)
- [x] Dark mode throughout
- [x] Buzzer Active indicator — flashing red "BUZZER ON" banner + badge when range is Live/Closed Loop and any signal is Up; polls every 10s via HTMX
- [x] Toast notifications on log create, edit, delete, restore, range state change, dashboard quick-edit
- [x] **Narrative / manual log notes** (`/logs/note`): plain-text notes appear as amber italic rows in the log list
- [x] **Signal history view**: clicking any signal name on dashboard or log list filters to that signal's full history
- [x] **Dashboard last-state-change card**: 4th summary card shows time and operator of most recent range state change
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
- [x] **Documentation / Wiki module** (`/docs`): Markdown pages with version history, supervisor direct edit, operator edit proposals, approval queue, printable view. 7 seed pages covering core procedures. Nav link visible to all users; pending-proposal badge for supervisors.
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
- [ ] More detailed permissions model beyond operator/supervisor
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
- [x] **Navigation consolidation**: top-level nav reduced — RF/Power/EIRP grouped under a **Calculators** dropdown (Power and EIRP were previously unreachable from the nav), and the three supervisor links (Users, Audit, Config) grouped under an **Admin** dropdown. Navbar density tightened.
- [x] Loading indicator during HTMX poll refresh (spinner in widget header)
- [x] Dashboard quick-edit: exclusivity group warning — "Auto-downs: X, Y" shown below Status select, visible only when "Up" is chosen (JS show/hide)
- [x] Config drag-to-reorder: SortableJS on all four lists (mod types, FEC, sources, antennas); grip handle column; `fetch` POST to `/config/{type}/reorder` on drop; toast on success. Reorder endpoints added for FEC, sources, antennas (mod already existed).

---

## Known Issues / Bugs

- ~~**Dashboard summary/buzzer stale on poll**~~: Fixed — the 10s poll only swapped each serial's table body, so the summary cards (Active Signals count, Faulted) never updated and the buzzer bar reflected only the last-polled serial's local state (flipping wrongly with multiple serials). Now the poll + quick-update render `partials/dashboard_fragment.html`, which OOB-swaps the global summary cards, the global buzzer bar, and the per-widget buzzer badge. Global aggregates (`up_count`, `faulted_count`, `any_buzzer`) come from `_dashboard_ctx`.
- ~~**Chain calculator stage index**~~: Fixed — `removeStage()` now renumbers all remaining `.stage-row` name attributes to fill gaps and resets `stageCount`.
- **`updated_at` not set by SQLAlchemy `onupdate` on SQLite**: Fixed by setting `log_entry.updated_at = datetime.utcnow()` explicitly in update handlers. Verify behaviour on PostgreSQL.
- **HTTPException 302 handler**: Using HTTPException with status 302 for auth redirects is non-standard. Consider middleware or a custom exception class for cleaner handling.
- **Serial created before confirmation**: When an operator uses "Create & Start", the serial is committed to DB before the confirmation page. If they abandon the confirmation page, an `is_started=False` serial sits in the DB. Now lower impact — it appears in the **Pending** section on `/serials` where it can be deleted or started. It won't appear on the dashboard.
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
