# Project Range — Handover Document

<!-- IMPORTANT: Update this file whenever features are added, changed, bugs are found, or new requirements arise.
     This is the canonical reference for any assistant continuing work on this project. -->

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
| `Signal` | Signal registry: named signals with defaults and exclusivity groups |
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
- [ ] Power warning thresholds per-signal or per-template
- [x] Formal range report export — structured multi-sheet XLSX via `/handover/report.xlsx` (Summary / Signals / State Changes / Notes), downloadable from the Handover page. PDF still available via the Handover print view (browser "Save as PDF").
- [ ] Device ping / network status checks
- [x] Shift handover module (print/PDF summary of signals and state at shift change) — see Implemented Features
- [ ] Active Directory / SSO authentication
- [ ] Session: "remember this terminal" option for thin clients
- [ ] More detailed permissions model beyond operator/supervisor
- [ ] Backup and restore tooling
- [ ] Windows Server deployment packaging (Waitress/NSSM service)
- [ ] HTTPS/TLS support
- [ ] Dashboard: "Add signal" form directly on dashboard (currently requires /logs/new)
- [x] **Dashboard inline on/off + power controls**: per-signal-row switch to set Up/Down, and −/+ stepper buttons (step 1) plus an editable number field to set power directly, with Submit/Cancel; a log entry is only written on Submit. The 10s poll pauses while any row has unsubmitted changes. Replaces needing the pencil→Status-dropdown path for the common on/off + power changes (full edit panel still available for other fields).
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
- [ ] **UI refinement pass (raised 2026-06-22, ongoing)**: the interface is starting to feel clunky as features accumulate and needs a consolidation/refinement pass (spacing, density, grouping of controls). Dark-scheme contrast also needs auditing. **Done so far:** buzzer indicator toned down (compact bar, no pulsing box-shadow, blinking removed from all buzzer elements — only the Live range-state still blinks); dashboard widgets are now minimisable/expandable (persisted); first contrast fixes (lighter muted text via `--bs-secondary-color`, lighter standby banner). **Still to do:** broader density/spacing cleanup across pages, audit badges / colored table rows / input-group text contrast.
- [x] Loading indicator during HTMX poll refresh (spinner in widget header)
- [x] Dashboard quick-edit: exclusivity group warning — "Auto-downs: X, Y" shown below Status select, visible only when "Up" is chosen (JS show/hide)
- [x] Config drag-to-reorder: SortableJS on all four lists (mod types, FEC, sources, antennas); grip handle column; `fetch` POST to `/config/{type}/reorder` on drop; toast on success. Reorder endpoints added for FEC, sources, antennas (mod already existed).

---

## Known Issues / Bugs

- ~~**Dashboard summary/buzzer stale on poll**~~: Fixed — the 10s poll only swapped each serial's table body, so the summary cards (Active Signals count, Faulted) never updated and the buzzer bar reflected only the last-polled serial's local state (flipping wrongly with multiple serials). Now the poll + quick-update render `partials/dashboard_fragment.html`, which OOB-swaps the global summary cards, the global buzzer bar, and the per-widget buzzer badge. Global aggregates (`up_count`, `faulted_count`, `any_buzzer`) come from `_dashboard_ctx`.
- ~~**Chain calculator stage index**~~: Fixed — `removeStage()` now renumbers all remaining `.stage-row` name attributes to fill gaps and resets `stageCount`.
- **`updated_at` not set by SQLAlchemy `onupdate` on SQLite**: Fixed by setting `log_entry.updated_at = datetime.utcnow()` explicitly in update handlers. Verify behaviour on PostgreSQL.
- **HTTPException 302 handler**: Using HTTPException with status 302 for auth redirects is non-standard. Consider middleware or a custom exception class for cleaner handling.
- **Serial created before confirmation**: When an operator fills in the "Create New Serial" form and is taken to the confirmation/preview page, the serial row is already committed to the DB. If they abandon the page, an empty serial sits in the DB. Low impact — they can end it from the dashboard or it'll show in History.
- **Dashboard tab-merge order restore**: On page refresh, `restoreLayout()` re-applies tab merges and drag order from localStorage. Works for tab merges; order restore uses `appendChild` which may reorder incorrectly if saved order doesn't match current DOM order exactly.

---

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | `dev-secret-change-in-production-please` | Session signing key |
| `DATABASE_URL` | `sqlite:///range.db` | SQLAlchemy DB connection |
| `SESSION_TIMEOUT_MINUTES` | `480` (8 hours) | Auto-logout after inactivity |

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
