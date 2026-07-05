# SEW Range — Version History

This document records the major user-facing changes shipped in each beta version.
For planned work, see [ROADMAP.md](ROADMAP.md). For deep implementation notes and
handover details, see [HANDOVER.md](HANDOVER.md).

Current version: **0.18.6**

---

## 0.18.6 — Calculator Keyboard, Account Permissions View, Chat Badge and Doc Conflict Fixes

- Basic Calculator (dashboard widget and standalone page) now accepts keyboard and numpad input: digits, `+ - * /`, `Enter`/`=`, `Backspace`, and `Esc`/`Delete` to clear.
- Preferences now shows your account type (Administrator / User / Observer) and a clear permissions table describing what each account type can and cannot do.
- Fixed the chat launcher unread bubble getting stuck on a number for a room that no longer exists (for example after a server restart clears ephemeral chat rooms). Stale unread counts are now reconciled against the live room list.
- Fixed lost document edits when two people propose changes to the same page: the approval queue now flags a **Conflict** when the live page changed since an edit was drafted, shows the proposed vs current content side by side, and requires the administrator to explicitly confirm before overwriting newer changes.
- Static cache keys bumped to `app.css?v=25` and `app.js?v=25`.

## 0.18.5 — Observer Utilities, CDA Assignment, and Calculator Usability

- Observers can use calculator POST actions and toggle dashboard signal **Engaged** states while remaining blocked from package/serial configuration.
- Observers can submit incident/fault reports for administrator approval; approved reports then appear in the active incident list.
- Package and Serial pages now show Observer read-only hints and hide create/import/edit/start/end/delete controls from Observer accounts.
- CDA table detail pages can now assign or remove the table from active serials after the CDA table/windows have been created.
- Improved the Basic Calculator so pressing an operator prepares entry of the second number instead of appending digits to the first number.
- Static cache keys bumped to `app.css?v=24` and `app.js?v=24`.

## 0.18.4 — Chat Live Delivery and Member Picker Fixes

- Group chat member pickers now show online users first, with offline users in a collapsed **Offline** list.
- Fixed open chat windows missing new messages until the window was closed and reopened.
- Added per-room polling guards and message-id de-duplication so overlapping refreshes do not render repeats.
- Added send guards to floating chat windows and dashboard chat widgets so one click/Enter press creates one message.
- Fixed the bottom-right chat notification bubble so it clears as soon as all messages in a room have been viewed.
- Static cache keys bumped to `app.css?v=23` and `app.js?v=23`.

## 0.18.3 — Chat Room Inbox, Group Member Management, and Notification Clarity

- Fixed group chat usability by adding visible **Unread** and **Chats** lists to the chat launcher.
- Users can now open group/private rooms from the chat launcher instead of relying on a toast or dashboard widget.
- Unread notifications now show which chat room has unread messages and who sent them.
- Added group member management from an open group chat window.
- Group creators/members can add active users to an existing group chat after it has been created.
- Dashboard chat room dropdowns now show unread counts.

## 0.18.2 — Version History Docker Packaging Fix

- Fixed the in-app Version History page in Docker deployments by allowing `docs/VERSION_HISTORY.md` into the image.
- Previously the app route worked, but `.dockerignore` excluded the `docs/` folder, so the page showed "No version history document found."

## 0.18.1 — In-App Version History and Observer Document Edit Requests

- Added this Version History document.
- Added an in-app Version History page at `/docs/version-history`.
- Added a sidebar link under Records so operators can view release history from inside SEW Range.
- Allowed Observers to request documentation edits through the existing proposal workflow.
- Observer document edit requests go to the administrator approval queue and do not publish until approved.

## 0.18.0 — Session, Dashboard Bulk Edit, Package Delete, Chat Presence, EBEM Auto-Sync

- Added single-session enforcement: when a user logs in somewhere else, their older session is invalidated.
- Changed dashboard quick-edit so all signal parameters and frequencies stage into one serial-widget submit.
- Added dashboard frequency recalculation for TxIF, TxRF, RxRF, and RxIF from the package TxLO, RxLO, and TTF plan.
- Added server-side frequency recalculation for dashboard bulk submits and EBEM/CBM sync updates.
- Allowed signal packages to be deleted when their only serial references are closed/history serials.
- Improved chat presence with a shorter online window and an offline beacon when the browser/page closes.
- Added automatic EBEM/CBM read-only sync every 5 seconds by default. `CBM_AUTO_SYNC_SECONDS=0` disables it.

## 0.17.14 — Explicit Unassigned CBM Source

- Added **No modem assigned** as the blank/default Source state in package and dashboard Source controls.
- Clearing Source now clears the internal CBM device mapping.
- CBM sync ignores unassigned package signals, so only deliberately mapped signals are updated.

## 0.17.13 — Dashboard Source Edits Update Package Mapping

- Dashboard Source changes now update the matching package signal CBM mapping for the active serial.
- Dashboard Source dropdowns preserve imported or legacy Source values that are not currently in App Config.
- Dashboard updates audit when a Source change is applied back to package mappings.

## 0.17.12 — Package Import RF Setup, Append Import, Delete Guard

- CBM import now captures package RF details before file selection: band, antenna, TxLO, RxLO, TTF, direction, and unit.
- Imported CBM signals with IF frequencies can auto-fill TxRF/RxRF from package RF settings.
- Existing packages can append CBM config imports from the package list or edit page.
- Package deletion now gives a clear blocked message instead of an internal error when a package is still assigned.

## 0.17.11 — Imported Package Edit and Source Mapping Fix

- Fixed imported package signal edit buttons by replacing brittle inline JSON with safe `data-entry` payloads.
- Added punctuation-insensitive CBM Source matching, such as `CBM400_2` matching `CBM-400-2`.
- Editing a package signal Source can correct and persist the internal CBM mapping.

## 0.17.10 — CBM Force-Update Issue Auditing

- CBM sync issues are now written into audit comments.
- Added dedicated `CBM_SYNC_ISSUE` audit records when mappings fail or are skipped.
- Dashboard Force CBM Update toasts now show the first issue reason.

## 0.17.9 — CBM Symbol-Rate Import/Edit Fix

- Converted CBM raw symbol-rate values into display kbps/ksps units on import and live sync.
- CBM package export converts display values back to modem raw units.
- Package signal edit preserves imported dropdown values not yet listed in App Config.

## 0.17.8 — Dashboard Force CBM Update

- Added a compact dashboard **CBM** force-update button on active serial widgets with mapped CBM signals.
- The button runs the existing read-only active CBM sync and reports updated/skipped/issues via toast.
- Available to normal Users and Administrators; Observers remain read-only.

## 0.17.7 — Source and CBM Package Import Cleanup

- CBM modem devices now appear automatically as Source options.
- Removed the separate package-signal CBM modem selector; Source is now the user-facing modem selector.
- CBM imports split FEC, Inner Code, and Symbol Rate into separate package fields.
- Carrier Label was removed from package signal UI/export naming.
- Eb/No was removed from package configuration and reserved for modem-derived reads.

## 0.17.6 — Chat Duty Roles and Live Shared State Refresh

- Chat roster, group creator, and private chat headers now show duty-role tags instead of account permission roles.
- Range-state banners poll every 5 seconds and update across logged-in browsers.
- Dashboard signal tables poll every 5 seconds and refresh immediately on range-state change.
- Testing transitions trigger a controlled reload so users enter/leave the correct data scope.
- Static cache keys bumped to `app.css?v=19` and `app.js?v=19`.

## 0.17.5 — CBM-400 Package Import/Export Format

- Package import accepts CBM-400 `STR_CFG` text exports, ZIP files containing configs, and legacy Project Range JSON.
- CBM imports read Project Range-relevant fields such as IF frequency, power, modulation, symbol rate, FEC, and config name.
- Package export emits CBM-style modem config files: `.txt` for one signal or `.zip` for multiple signals.
- Local modem config samples remain under ignored `modem_configs/`.

## 0.17.4 — Form and Tab Position Restore

- Added global page-state restoration for active Bootstrap tabs and scroll position after normal form/select submits.
- Fixed App Config actions jumping back to the first tab/top of page.
- Static JS cache key bumped to `app.js?v=18`.

## 0.17.3 — Version Badge Placement

- Moved the app version badge from the fixed bottom-right corner to the topbar near the light/dark toggle.
- Prevented the chat launcher/windows from covering the version badge.
- Static CSS cache key bumped to `app.css?v=18`.

## 0.17.2 — Dashboard Engaged Indicator

- Added optional **Engaged** dashboard column.
- Operators can toggle Engaged On/Off immediately without the dashboard bulk submit bar.
- `SignalLog.engaged` is a visual mission-system flag only; it does not drive status, buzzer, range state, or CBM decisions.
- Engaged state is inherited by newer dashboard or CBM-created log rows.

## 0.17.1 — Account Roles, Rename, Archive, Delete

- Account permission roles are now Administrator, User, and Observer.
- Added migration from old role values to the new stored values.
- Admins can rename accounts, change display names, and change account roles.
- Added account archiving. Archived accounts cannot log in and are excluded from normal user lists and chat.
- Hard delete is available only when no required operational attribution rows depend on the account.

## 0.17.0 — Testing Range State and Usability Fixes

- Added administrator-only **Testing** range state with isolated packages, serials, logs, devices, CDA windows, incidents, and CEASE records.
- Improved chat notifications and read/unread state across page changes.
- Operators can manage CDA windows while CDA table management remains administrator-only.
- Serials page now hides the New Serial form by default behind a New Serial button.

## 0.16.1 — Chat Notification and Usability Polish

- Improved private/group chat notification behavior.
- Added unread alert handling for minimized windows and the chat launcher.
- Stored chat read/unread state in browser `sessionStorage` to avoid replaying notifications on every page change.

## 0.16.0 — Ephemeral Instant Chat

- Added in-memory instant chat for logged-in users.
- Supports online user list, private rooms, group rooms, message send, and message polling.
- Chat is intentionally ephemeral: messages and rooms are lost on app restart.
- Presence originally used recent authenticated requests/heartbeats plus explicit logout.

## 0.15.0 — Configurable Duty-Role Tags

- Added duty-role tags as visual position indicators separate from account permissions.
- Admins can manage duty roles under App Config: add, rename, recolour, enable/disable, reorder, and delete.
- Users self-select duty-role tags on Preferences.
- Duty-role name and colour are denormalised onto the user record for fast rendering.
- Seeded default tags: Operator, Supervisor, EA Safety, Observer.

## 0.14.0 — Observer Role and Range-Wide CEASE Alert

- Added read-only Observer account role.
- Central middleware blocks Observer writes except explicitly allowed actions.
- Added range-wide CEASE button available on every screen.
- CEASE creates a full-screen alert across connected screens with reason, raiser, time, and dismiss action.
- CEASE is visual/logged only; it does not control hardware or force range state.

## 0.13.0 — Navigation and Dashboard Overhaul

- Replaced the top navbar with a collapsible left sidebar.
- Added mobile sidebar overlay behavior and desktop collapsed icon-only mode.
- Dashboard became a two-column widget grid with half/full span toggle.
- Removed hardcoded summary cards and made Range State, Active Signals, and Last State Change optional widgets.
- Added dashboard calculator widgets: Basic Calculator, RF Frequency, and Power Converter.
- Added a standalone Basic Calculator page.
- Added static cache-busting after stale JS caused sidebar/span controls to fail.

## 0.12.0 — CDA Windows

- Added Controlled Data Area schedules with daily Zulu windows.
- Windows support **No Fire** or **Reduced Power** behavior.
- CDA tables can be assigned to serials.
- Dashboard CDA widget shows schedules and live countdown timers.
- Handles colour-coded countdowns, windows spanning midnight, and next-day wrap.
- Added CDA CSV import/export.

## 0.11.0 — Dashboard Utility Widgets

- Added Quick Notes widget with local scratchpad and `.txt` download.
- Added Docs Reference widget for viewing published docs inside the dashboard.
- Added multiple configurable clock widgets.
- Added Quick Links widget for common operator actions.
- Utility widgets use dashboard drag, collapse, remove, and localStorage layout persistence.

## 0.10.1 — Backup Script

- Added `scripts/backup_db.py` for Docker-hosted SQLite backups.
- Backups are copied to `./backups/range-<UTC>.db`.
- Added retention pruning with `--keep`.
- Documented backup and restore steps in `docs/DEPLOY.md`.

## 0.10.0 — Dashboard Clock, Timezone, and Log Time Polish

- Added dashboard Zulu/local clock widget.
- Added global administrator-managed local timezone under App Config.
- Logs and history are Zulu-first.
- Optional local-time display can be enabled in logs/history.
- CSV/XLSX exports label timestamp columns as Zulu.
- Added Antenna as a device type.

## 0.9.5 — Settings and Theme Polish

- Added visible Settings dropdown with Preferences, Password, and administrator App Config.
- Reworked themes so palettes affect canvas, nav, cards, borders, and muted surfaces.
- Softened light mode.
- Improved login theme toggle icon behavior.

## 0.9.4 — Log Readability

- Logs and serial history now compare each signal log entry with the previous entry for that signal.
- Added a Changed column summarizing changed parameters.
- Highlighted changed cells subtly.
- Calmed lifecycle row colours for SerialStart, SerialEnd, and narrative notes.

## 0.9.3 — Device Enhancements and Serial Pre-Create

- Added device types: IP Switch, 10MHz Reference, Sync Server, DC Injector.
- Split RFDevice name and device model into separate fields.
- Added web GUI link support for devices.
- Added topology page with RF/IP/Clock/Power link views.
- Added `DeviceLink` model for directed connections between devices.
- Routing pages now show auto-hints from topology links.
- Added pending serials: Save as Pending and Create & Start flows.

## 0.9.2 — Dashboard Bulk Submit and Password/HTMX Fixes

- Replaced per-row dashboard green tick with a single **Submit All Changes** bar per serial widget.
- Bulk dashboard updates commit staged signal changes in one transaction.
- Fixed password minimum length consistency across config, server validation, and forms.
- Fixed forced-password-change page instability caused by HTMX pollers injecting redirects into small fragments.

## 0.9.1 — Theme System

- Added two-axis theme system: light/dark mode plus named palette.
- Added named palettes: Classic, SEW Gold, Night Ops, and Spectrum.
- Preferences persist theme, light/dark mode, and default RF/power units.
- Theme is applied pre-paint to avoid flash.

## 0.9.0 — Operational Hardening

- Removed static default `SECRET_KEY`; unset keys use ephemeral random values with warning.
- Forced password change for seeded/reset accounts.
- Added password policy and login throttle.
- Added auth audit records for login success, failed login, and lockout.
- Added session cookies with `SameSite=Strict` and optional HTTPS-only mode.
- Added CSRF same-origin checks on unsafe methods.
- Added security headers.
- Added soft/hard log delete flow.
- Going Live requires safety acknowledgement and administrator authorization.
- Added incident/fault reporting with CSV export.
- PostgreSQL and HTTPS/TLS remained deferred infrastructure items.

## 0.8.0 — RF Distribution and Device Status

- Added splitter/combiner routing matrix.
- Added per-port labels and configurable port counts.
- Added device TCP reachability checks.
- Added administrator-managed device registry.

## 0.7.0 — UI and Presentation Polish

- Added SEW Range branding/logo and gold accent.
- Added theme and light/dark mode groundwork.
- Added user-selected default frequency and power units.
- Centralised app version display through shared templating.

## 0.6.0 — Offline LAN Deployment and Naming Cleanup

- Renamed BUC/LO terminology to TxLO/RxLO across database, calculators, package/log auto-calc, and exports.
- Added version badge.
- Vendored frontend assets for fully offline/LAN operation.
- Added Docker deployment on external port `7474`.

## Pre-0.6 Foundation

- Built core FastAPI/SQLAlchemy application structure.
- Added user login, roles, sessions, and audit trail foundation.
- Added signal logging and dashboard basics.
- Added RF frequency calculator, power converter, gain/loss chain, and EIRP calculator.
- Added signal packages, serials, documentation/wiki, shift handover, and initial operational workflows.
