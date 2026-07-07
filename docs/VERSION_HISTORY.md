# SEW Range — Version History

This document records the major user-facing changes shipped in each beta version.
Current version: **0.25.0**

---

## 0.25.0 — Symbol Rate Enforcement + Spectrum Occupancy Chart

- **Symbol rate is now required on all signal package entries.** The Add / Edit Signal form marks the field with a required asterisk and will not submit without a value. Server-side validation on both add and update endpoints rejects empty symbol rates with a clear error message. Existing signals that were created without a symbol rate show a **Missing** warning badge in the signal table so operators know which entries need to be updated.
- **Spectrum Plan on signal package page:** A collapsible **Spectrum Plan** section appears on the package edit page whenever the package has signals. It renders a canvas chart showing each signal as an occupied-bandwidth block — centred on its TX or RX RF frequency, width determined by `(symbol rate ÷ modulation rate) × (1 + rolloff 0.25) / 1000 MHz`, and height by power (dBm). Controls: **Centre (MHz)** to pan, **Span (MHz)** to zoom, **Guard Left / Guard Right** frequency markers, and a **TX + RX / TX only / RX only** view selector. Guard band boundaries draw amber dashed lines and shade areas outside the permitted range in red. All settings are saved per-package in the browser.
- **Spectrum Plan on serial history page:** The same collapsible chart appears on the serial history detail page for any serial with signal packages assigned. It combines all signals from all packages assigned to that serial in one view. Settings are saved per-serial in the browser.
- **Live Spectrum dashboard widget:** A new optional dashboard widget (**Widgets → Live Spectrum**) draws a live spectrum of transmitted signals from active serials. It now refreshes from the active serial signal-table update flow and immediately after dashboard bulk-submit changes, rather than using a separate 30-second timer. Only signals currently **Up** are shown. The same centre freq, span, and guard band controls are available per widget instance.
- **Spectrum occupied bandwidth fix:** Package, history, and live spectrum views now pass modulation into the shared chart and calculate occupied bandwidth from both modulation rate and symbol rate. Auto centre/span also accounts for occupied-bandwidth edges so signals do not appear clipped around the wrong centre.

## 0.24.1 — Navigation Restructure + Activity Badge on Dashboard

- **Sidebar navigation restructured into four logical sections** matching the operational workflow:
  - **Planning** — Activities → Serials → Signal Packages (prep order: plan the exercise, create serials, configure signal packages)
  - **Operations** — Signal Logs, CDA, Incidents, Handover (day-to-day range running)
  - **Records** — History, Documentation (post-operational reference; Version History removed as a separate sidebar link — accessible via Documentation)
  - **Tools** — Devices, RF Calculator, Power Converter, EIRP, Basic Calculator (support tools grouped together)
- **Activities now appears above Serials** in the sidebar as the parent planning concept.
- **Signal Packages moved** from the old "Resources" section into Planning, so the package → serial → activity preparation flow is contiguous in the nav.
- **Activity badge on dashboard serial widget:** When a serial is assigned to an activity, a small linked badge (calendar icon + activity name) appears in the widget header. Clicking it navigates directly to the activity detail page.

## 0.24.0 — Activities / Exercises

- **Activities:** A new top-level grouping concept sits above serials. An **Activity** has a name, an admin-configured type label (Exercise, Training, Maintenance, etc.), and an optional description. Multiple serials can be assigned to one activity; a serial can also remain standalone with no activity.
- **Admin-configurable activity types:** Administrators manage the type list under **Admin → Config → Activity Types** — add, rename, enable/disable, delete (blocked if in use), and drag-reorder, exactly like modulation types or duty roles.
- **Activity list (`/activities`):** Shows all activities for the current workspace grouped by status — **Active** (has at least one open serial), **Planned** (no serials started yet), **Completed** (all serials closed). Each entry shows the type badge, date range (derived from serials — no separate date fields to maintain), serial count, and CSV/XLSX export buttons.
- **Activity detail page:** Groups assigned serials into Pending / Active / Completed sections with links to their history. Inline edit panel for name, type, and description. Assign any unassigned serial in the current workspace via a dropdown; unassign with a single button.
- **Activity export:** Download all signal logs across every serial in the activity as a single **CSV** or **XLSX** file. Logs include a **Serial** column so rows from different serials are distinguishable. Individual serial exports remain available from the history page.
- **Serial create form** now has an optional **Activity** picker (after the Notes field). Pending and active serial cards show an activity badge/link when one is assigned.
- **History filter:** The history list has an **Activity** dropdown filter to show only serials belonging to a specific activity. The serial history detail page shows a breadcrumb back to the parent activity.
- **Activities link** added to the Operations section of the left sidebar.

## 0.23.0 — Eb/No Dashboard Live Update, Eb/No Log Toggle, CEASE Permissions

- **Eb/No always reflects the live modem reading on the dashboard:** Previously, Eb/No only updated on the dashboard when the change exceeded the ±3 dB log threshold. Now the dashboard always shows the current Eb/No from the modem — even sub-threshold drifts — by updating the existing log row in-place rather than creating a new entry. Log creation still only occurs when the threshold is crossed.
- **Admin toggle to disable Eb/No log entries:** A new **Record Eb/No changes in log** toggle has been added to **Admin → Config → System**. When turned off, Eb/No changes (even large ones) are never written as new log entries. The dashboard reading still updates in-place. The existing ±3 dB threshold continues to apply when the toggle is on.
- **CEASE dismiss restricted to users and administrators:** Observers can still raise a range-wide CEASE alert, but only Users and Administrators can dismiss it. The CEASE splash shown to observers omits the Dismiss button and explains that only users/admins can dismiss. The `/cease/dismiss` endpoint returns a 403 for observer accounts.

## 0.22.0 — EBEM LED Indicators, Cross-Workspace Copy, Routing Presets

- **EBEM LED status indicators on the dashboard:** The dashboard signal table now has a selectable **EBEM Sync** column showing three coloured LED dots (green/red/grey) for Embedded Channel Sync, Carrier Lock, and Bit Sync on CBM/EBEM modem signals. The LED states are polled automatically during the existing 5-second CBM auto-sync cycle. Non-CBM/EBEM signals show **N/A** in this column.
- **Cross-workspace copy (Live ↔ Sandbox):** Signal Packages, CDA Tables, and Serials can now be copied between the Live and Sandbox (Testing) workspaces with a single button. Copying a serial also carries its assigned packages across, reusing any existing package with the same name or creating a copy. Copied serials arrive as Pending in the target workspace.
- **Routing presets tied to range states:** Administrators can now save the current SNMP-observed routing of any splitter/combiner as a **named preset** for each range state (Standby/Off, Closed Loop, Live). When changing range state, the app compares live observed routing against the preset for the target state and shows a warning panel listing which ports need to change and what they need to be changed to. The operator can fix the hardware and re-submit, or confirm they have reviewed the mismatch and proceed anyway. Advisory only — routing checks never block the state change.

## 0.21.0 — Documentation Wiki Lite, CBM/CDM Sync Fix, Readability

- **Documentation Wiki Lite:** docs now support `[[Page Title]]` / `[[Page Title|label]]` wiki links, missing-page links, backlinks/related pages, a wanted-pages view, aliases/redirects, admin-managed page **visibility** (all logged-in users / users + administrators / administrators only), new-page **templates** (Blank, Device, Procedure, Troubleshooting, Configuration, Range Rule), and a denser wiki-style home page. Visibility is enforced across docs home/search, recent/wanted pages, wiki-link resolution, backlinks, direct URLs, and print/edit/history routes.
- **CBM/CDM modem fix:** only modems explicitly ticked as **CBM/EBEM sync** are polled. Other modems (e.g. CDM-600Ls, which aren't reachable over IP) can still be selected as a signal **Source** but are never treated as CBM poll targets, so they no longer generate failed-sync errors. The Devices form shows the CBM/EBEM sync checkbox for any modem (tick it only for real CBM/EBEM units); the Sources list in App Config now labels non-CBM modems as plain **Modem** instead of "CBM modem".
- Fixed remaining **light-mode table readability** where dashboard signal lists, Signal Logs, history, and audit/config tables still used dark table backgrounds.
- Renamed user-facing signal-active indicators to **Transmitting / Not transmitting** on the dashboard, banner badge, widgets, and handover exports.
- Fixed live splitter/combiner routing display so explicit matrix **terminated** states stay distinct from ports with no observed route.
- Static cache key bumped to `app.css?v=30`.

## 0.20.2 — Light Mode Readability Fix

- Fixed all **light-mode** themes where the left sidebar and top bar text was unreadable (dark text on the dark sidebar/topbar). Those surfaces keep a dark background in light mode by design, so their text is now always light regardless of the light/dark toggle. Applies to Classic, SEW Gold, Night Ops, and Spectrum.

## 0.20.1 — Chat Receipts and Typing Indicator

- Chat messages now show sender-side delivery state: **Sent**, **Received**, and **Read**. Group chats show receipt counts when only some members have received/read the message.
- Floating chat windows and dashboard chat widgets now show a live typing indicator when another participant is composing a message.
- Static cache keys bumped to `app.css?v=27` and `app.js?v=27`.

## 0.20.0 — Closed-Loop (IF-only) Packages + Eb/No Logging Controls

- **Closed loop vs Live (RF) packages:** a signal package now has an **Environment** toggle. Closed-loop packages are **IF-only** — no band, antenna, TxLO/RxLO or TTF, and no out-of-band warnings. The RF fields are hidden in the editor and cleared when a package is set to closed loop.
- Serials show as **Closed loop** automatically when all their packages are IF-only (packages drive it). Closed-loop / Live badges appear on the packages list, serials, the dashboard serial widget, and the **add-package picker** on serials.
- **Dashboard** hides the RF-only columns (TxRF, RxRF, Band, Antenna) for closed-loop serials, showing only IF frequencies.
- **Eb/No logging is now less noisy:** during CBM/EBEM sync, small Eb/No drifts no longer create a new log every poll. Only changes beyond a threshold — **default ±3 dB**, configurable in **Admin → Config → System** — are logged. A carrier appearing or disappearing always logs.
- **Eb/No now clears when the modem stops transmitting/receiving** (reports "No Carrier"), instead of keeping the last value. This, together with the threshold, fixes the CBM sync writing a signal-log entry on every poll.

## 0.19.10 — EBEM ICC Parser Fix (Status + Eb/No)

- Fixed the root cause of EBEM/CBM signal status not going **Up** when transmitting: the modem echoes the query command (e.g. `tx_cfg ?`) before its `TX_CFG TX_OP=ON,…` reply, and the parser was locking onto the lowercase echo and corrupting the first field (`TX_OP`). It now skips the echoed line and reads `TX_OP` correctly, so `TX_OP=ON` maps to **Up**.
- **Eb/No** is now read from the modem's `RX_EBNO` on any mapping (not only receive paths) whenever the modem reports a real value, and stays blank when the modem reports "No Carrier".
- Added an admin **CBM diagnostics** button (raw ICC output + how each field parsed) on the Devices page, so modem responses can be verified without guessing field names.

## 0.19.9 — EBEM Sync Status Fix

- EBEM/CBM sync now treats active/enabled/engaged modem state variants as signal **Up**, instead of requiring only exact `TX_OP=ON`.
- EBEM/CBM sync no longer forces a dashboard signal **Down** when the modem poll does not return a confident Tx/Rx state; it preserves the latest dashboard status while still applying telemetry updates.
- Eb/No parsing now accepts modem values with units and common EBEM field aliases such as `EBNO`, `EBN0`, `EB_N0`, and `EB_NO` as well as `RX_EBNO`.

## 0.19.8 — Session Hardening

- Login now clears any pre-auth session state before writing authenticated claims, which hardens the signed-cookie session flow against fixation-style reuse.
- Sessions now carry `session_issued_at`; malformed timestamps expire safely, and the absolute cookie-age ceiling is enforced server-side as well as by the browser cookie.
- SQLite data, audit/serial archive directories, and generated backup files now get best-effort owner-only filesystem permissions.
- Admin Config → System Health now reports database and archive permission modes so overly broad file access is visible.
- Package/CBM imports and CDA CSV imports now enforce upload type and size limits; legacy package JSON imports validate their structure before processing.
- Docker Compose now hardens the app container with a read-only root filesystem, `/tmp` tmpfs, no-new-privileges, dropped Linux capabilities, and memory/process limits.
- Audit records now form a tamper-evident HMAC-SHA-256 hash chain. The Audit page shows integrity status, existing rows are backfilled as a baseline, and audit archive spreadsheets include hash fields.

## 0.19.7 — QoL Navigation and Admin Tools

- Added a global `Ctrl+K` command palette with search/jump results for pages, devices, serials, packages, docs, signals, calculators, and admin destinations.
- Added terminal-local recently viewed shortcuts inside the command palette.
- Added dashboard layout controls: searchable widget picker, collapse all, expand all, and reset layout.
- Added log quick filters for Today, Yesterday, Last 7 days, Faulted, and Current serial, plus terminal-local saved log filter presets.
- Admin Config → System now shows database/audit/archive health and lets administrators download audit and serial archive spreadsheets from the server.
- Topology now has search/highlight plus visibility toggles for manual links, auto-inferred links, and live routed paths.
- Topology live routes now include an explanation row showing source, matrix device, observed input/output ports, destination, and data source.
- Documentation pages now support categories and comma-separated tags, category filtering, related-doc suggestions, and an administrator recycle bin for deleted pages.
- The top of the in-app Version History no longer links out to Roadmap/Handover.
- The New Package screen now has a "Start from existing" duplicate shortcut.

## 0.19.6 — Audit Retention and Serial History Archiving

- Audit Log now automatically applies retention before listing records. Live audit records keep the newest configured amount and archive older rows to server-side `.xlsx` files; Testing/Sandbox audit records keep the newest configured amount and simply prune older rows.
- Admin Config → System now controls how many audit records stay live in the app. Default is `1000`, minimum `250`, maximum `10000`.
- Closed serial history can now be archived by administrators. Archiving exports the serial summary and all signal log rows to a server-side `.xlsx`, then removes that closed serial history from the app database.
- Administrators can now delete documentation pages directly from the documentation page toolbar.
- The dashboard Widgets dropdown now shows checked widgets that are already visible and can remove widgets by deselecting them.

## 0.19.5 — Device Form Shows Relevant Fields Only

- The Add/Edit Device form now shows matrix input/output counts only for routing devices, so modem entries such as CBM-400 units no longer show redundant matrix sizing fields.
- EBEM/CBM read-only sync settings now appear only for CBM/EBEM modem devices and are cleared/ignored server-side for other device types.
- SNMP monitoring settings now appear only for splitter/combiner matrices, and SNMP polling ignores other device types until support is explicitly added.

## 0.19.4 — Topology Auto Links + Live Matrix Routes

- The Topology page now auto-infers RF links from splitter/combiner/switch port names. If a matrix port alias contains a registered device name, such as `CBM-400 1 Tx`, the diagram can show that device connected to the matrix without requiring a manually-created topology link.
- The Topology page now derives **live routed paths** through splitter/combiner/switch matrices by combining physical topology links with the latest SNMP observed routing.
- Added a **Live Routed Paths** table showing source device, matrix, input-to-output route, and downstream device.
- The topology diagram now overlays dashed live RF paths so operators can see where signals are actually routed through the splitter/combiner, not just what is physically cabled.

## 0.19.3 — VTRC Combiner Routing and Alias Fix

- Fixed VTRC combiner live routing so the app follows the MIB's combiner semantics: **inputs route to outputs**. The routing page now shows many inputs correctly combining into one output instead of transposing that as every output being fed from one input.
- Combiner SNMP aliases now count as observed-state changes during polling, so real input/output names are persisted and shown instead of falling back to generic labels.
- Stale splitter-style observed routing is cleared from combiner output ports on the next successful poll.

## 0.19.2 — Clearer Routing Page + Input Routing + Real Device Names

- **Redesigned the routing page** to be much easier to read: a live status bar, a read-only **Outputs** view (each output → the input feeding it) and a new **Inputs** view (each input → the outputs it feeds), with module health and the manual planning/labels tucked into collapsible sections.
- **Real device port names** are now read from the matrix over SNMP (e.g. "CBM-400 1 Rx", "Mission System 3 Tx") and shown automatically, instead of bare port numbers.
- **See what inputs are routed to** — the Inputs panel shows each input's live fan-out (which outputs are drawing from it).
- Fixed **Refresh/Poll now** on the routing page bouncing back to the Devices list — it now stays on the routing page.

## 0.19.1 — SNMP Matrix Support (VTR/VTRC) + Acknowledge Module Faults

- **Live routing now works on VTR-101 / VTRC-101 matrices** (and VTR-100/102, VTRC-100/102, Hawk). The client auto-detects the matrix family and reads its routing table, fixing the "all outputs show none" issue on those units.
- **Acknowledge/ignore module faults:** the routing page now shows a per-module health panel (e.g. SLOT/CPU/PSU1/PSU2). You can tick a module — such as an empty or unpowered **PSU2 slot** — to acknowledge its fault so it no longer drives the system status to red. The displayed system status is derived from the non-ignored modules.
- Added an admin **Diagnostics** button (raw SNMP walk) on the routing page to inspect exactly what a device exposes.
- The Live (SNMP) routing column now shows a clear note instead of misleading "none" when a device returns no routing data.

## 0.19.0 — Splitter/Combiner Live Monitoring (SNMP)

- Added read-only **SNMP monitoring** for splitter/combiner/switch matrices (ETL Systems Genus / VTR).
- Routing devices now have SNMP settings (v2c community or v3 user, encrypted at rest) with a **Test SNMP poll** button and a **Poll SNMP** bulk action on the Devices page.
- The routing page now shows the **live observed routing** read from the matrix beside the planned routing and highlights any mismatch, plus a system alarm/health panel.
- Optional background polling via `SNMP_AUTO_SYNC_SECONDS` (default `0` = disabled).
- Read-only by design: the app never changes matrix routing. This is the first item of the range hardware monitoring expansion; **guided state-change presets are a planned follow-up**.
- **Not yet hardware-validated** — real Genus/VTR SNMP reads must be confirmed on the range once SNMP is enabled and credentials are available.

## 0.18.7 — Chat UI Tidy-Up

- Reorganised the chat panel with clearer sections: **Unread**, **Conversations**, and **People online**.
- The panel header now shows how many people are online, and a footer reminds you that messages clear when the app restarts.
- Replaced the icon-only group button with a labelled **New group** button, and gave the group creator its own tidy panel with a Cancel option and clearer "Add people" wording.
- Online users now show a chat affordance on hover and clearer tooltips so it's obvious clicking starts a private chat.
- Friendlier empty states for "no conversations yet" and brand-new chats, plus a clearer message composer.
- Static cache keys bumped to `app.css?v=26` and `app.js?v=26`.

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
