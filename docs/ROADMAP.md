# Project Range — Roadmap to v1.0

**Current version:** `0.9.4` (beta) · shown bottom-right in the UI and in `app/config.py`.

This roadmap takes Project Range from its current beta to a **1.0 operational
release** — a stable, documented system deployed on the range network, meeting
the MVP success criteria in [Scope.txt](Scope.txt), with the day-to-day features
operators have asked for.

## Versioning

We use a simple semantic scheme while in beta:

- **0.x.y** — beta. Minor (`x`) = a milestone of features below; patch (`y`) = fixes/small tweaks.
- **1.0.0** — first release blessed for operational use on the range.
- Bump the single source of truth in `app/config.py` (`APP_VERSION`); the UI badge follows it.

---

## ✅ Already delivered (through 0.9.4)

Core of the MVP scope is in place:

- RF frequency calculator (TxIF/TxRF/RxRF/RxIF from one known value) + frequency templates
- Power converter (dBm/dBW/W), gain/loss chain, EIRP
- Signal logging with per-signal power-warning thresholds + band/frequency validation
- Live dashboard (status, buzzer, drag-tab merge/split, steppers, column toggles, bulk-submit)
- Range state management (Standby/Closed Loop/Live) with reason + two-person supervisor auth
- Package-level RF config (TxLO/RxLO/TTF) with one-frequency auto-calc across signals
- Documentation/wiki module, structured XLSX export, shift handover
- User auth (operator/supervisor), audit log, "remember this terminal"
- Device registry with TCP reachability, routing matrix (splitter/combiner), topology view
- Incident/fault reporting, hard-delete for logs, security hardening (CSRF, headers, throttle, forced PW change)
- Serial pending/pre-create: serials can be saved as pending before starting
- Log readability: signal log rows identify changed parameters and history lifecycle rows use calmer colours
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
- [x] **Device registry** (name, type, host/IP, check port, location, port counts) — supervisor-managed CRUD, audited; underpins both of the above. New "Devices" nav entry.

## 0.9.3 — Device enhancements + serial pre-create ✅ (shipped 2026-06-26)

Theme: richer device modelling and operational pre-planning.

- [x] **Extended device types** — IP Switch, 10MHz Reference, Sync Server, DC Injector added to the registry dropdown. IP Switch is intentionally *not* a routing device (no crossbar matrix) — it gets topology links only.
- [x] **Device name vs model** — `RFDevice` now has `name` (instance, e.g. `CBM-400-1`) and `device_model` (product, e.g. `CBM-400`) as separate fields. Both shown in the devices table. Migration: `ALTER TABLE rf_devices ADD COLUMN device_model VARCHAR(128)`.
- [x] **Web GUI link** — `has_web_gui` boolean per device (checkbox in add/edit). When set, an "Open" link button appears in the devices table pointing to `http://<host>/`. Migration: `ALTER TABLE rf_devices ADD COLUMN has_web_gui BOOLEAN DEFAULT 0`.
- [x] **Topology view** (`/devices/topology`) — tabbed RF / IP / Clock / All views. SVG diagram auto-positioned by device layer type. Colour-coded links (RF=gold, IP=teal, Clock=purple, Power=red). Connection list with delete for supervisors. Supervisor add-connection form with port labels + port index for routing integration.
- [x] **`DeviceLink` model** — directed connection between two RFDevices (from/to device, port label, port index, link_type, label). Port index enables routing page auto-hints.
- [x] **Routing page auto-hints** — the combiner/splitter routing page reads `DeviceLink` records and pre-populates port label fields with the name of the connected device (and shows a "linked: DeviceName" hint below unlabelled ports).
- [x] **Serial pre-create / pending serials** — "Save as Pending" button on the serial create form saves a serial with `is_started=False`. Pending serials appear in their own section at the top of `/serials` with Start and Delete buttons. Serials can now be prepared in advance and started when needed.

## 0.9.4 — Log readability ✅ (shipped 2026-06-26)

Theme: make audit trails easier to scan under pressure.

- [x] **Changed-parameter highlighting** — `/logs` and `/history/{serial_id}` compare each signal log against the previous entry for the same signal in the same serial. A new "Changed" column summarizes changed fields, and visible changed cells are subtly highlighted.
- [x] **Calmer history lifecycle rows** — `SerialStart`, `SerialEnd`, and narrative note rows in serial history now use custom muted colours instead of the bright Bootstrap warning row.

## 0.9.0 — Operational hardening ✅ (security + features shipped; infra deferred)

Theme: ready to trust with real operations. *(Scope §13, Phase 4.)*
See the **Security hardening** section below for the security items shipped in 0.9.0.

- [x] **Soft / hard log delete** — soft delete (recoverable) for everyone; supervisor-only restore and permanent hard-delete (two-step: only on already soft-deleted entries). Audited. Scope §4.10.
- [x] **Supervisor approval for going Live** — going Live requires a safety acknowledgment, and a supervisor must authorise (operators supply a supervisor's credentials = two-person). Approver recorded in the state log + audit. Scope §12.2.
- [x] **Incident / fault reporting** — log incidents (severity/status/affected/serial), update status with resolution, CSV export, audited; new "Incidents" nav with open count. Scope §12.2.
- [ ] **Backups** — scheduled DB backup/restore procedure (scripted). *(manual `docker compose cp` documented in DEPLOY.md for now.)*
- [~] **PostgreSQL option** — **deferred** (your call — no infra to stand up yet). Support Postgres via `DATABASE_URL` with a real migration tool (Alembic).
- [~] **HTTPS/TLS** — **deferred** (your call). Reverse-proxy/self-signed setup for the range network. Session cookies are already `SameSite=Strict` + ready for `Secure` (`SESSION_HTTPS_ONLY=1`).

## 0.10.0 — Dashboard widgets & Settings UX (pre-1.0)

Theme: discoverability and at-a-glance ops info. *(User-requested.)*

- [ ] **Settings area** — a clear, discoverable **Settings** entry (nav item / gear menu) that consolidates configuration in one place:
  - **Per-user (Preferences):** theme + light/dark, default units, time zone (below). *(These live on the existing `/preferences` page today, reached only via the user's name in the navbar — surface it as "Settings".)*
  - **Admin (Config):** the supervisor-only `/config` page (modulation/FEC/sources/antennas/registry/freq templates).
  - Likely a tabbed Settings page (Preferences | Admin) or a Settings dropdown grouping both, so "where do I change X?" is obvious.
- [ ] **Dashboard clock widget** — a **Zulu (UTC) time** clock plus **local time**, where local time follows a **time-zone chosen in Settings** (IANA tz dropdown, stored per user like default units). Implement as a **dashboard widget that can be added and dragged/arranged like the serial widgets** (reuse the existing dashboard widget drag/merge/pop-out system). Updates live (client-side tick; Zulu always shown).

## 1.0.0 — Operational release

Theme: blessed for use. Gate criteria:

- [ ] Deployed and validated on the target Windows Server / range network (Docker or direct).
- [ ] All MVP success criteria in Scope §19 met and signed off.
- [ ] Backups, user accounts, and audit verified in the live environment.
- [ ] Operator + supervisor documentation complete in the wiki module.
- [ ] Password/secret hygiene enforced (no default `admin/changeme`, real `SECRET_KEY`).
- [ ] **Critical** security items below are closed (they gate 1.0.0).

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
- [ ] **Session hardening:** rotate the session ID on login (prevent fixation);
  keep both idle and absolute timeouts; re-review the 30-day "remember this
  terminal" cookie — fine for a locked ops room, risky on any shared/general PC.
- [ ] **Least-privilege data store:** on Postgres use a dedicated app role with
  minimal grants; on SQLite lock down file permissions. Restrict who can read the
  DB/backups (they contain the full audit trail).
- [ ] **Network exposure:** bind the service to the range subnet only, firewall to
  known client hosts, and front it with a reverse proxy. Do not expose it beyond
  the range LAN.

### Medium / ongoing

- [ ] **Dependency & image patching:** pin versions, run `pip-audit` (or similar)
  on a schedule, and rebuild the image regularly to pick up base-image security
  fixes. Track CVEs for FastAPI/Starlette/uvicorn/bcrypt.
- [ ] **Container hardening:** read-only root filesystem where possible,
  `no-new-privileges`, drop unneeded Linux capabilities, set resource limits.
- [ ] **Encrypted, access-controlled backups** with a tested restore procedure.
- [ ] **Finer-grained RBAC** beyond the two current roles; periodic access review.
- [ ] **Upload validation:** enforce type/size limits and validate JSON on package
  import and any doc/file uploads.
- [ ] **Audit log integrity:** make audit records tamper-evident / append-only and
  ensure they cannot be silently deleted.
- [ ] **Pre-deployment review:** a focused security review / light pen test before
  operational sign-off, plus a documented incident-response and patching process.

> Tip: the `/security-review` command can review the pending diff for these
> categories as features land.

---

## Post-1.0 / under investigation

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

### Other future enhancements (Scope §12)

- **Hardware integration:** spectrum analyser screenshot capture, RF switch matrix state, power meters, SNMP/serial/REST devices, auto power/Eb/No readings.
- **Advanced ops:** range booking, job/mission workflow, checklists, maintenance/calibration modes, restricted-access mode.
- **Advanced reporting:** formal PDF range reports, daily/per-mission summaries, signal uptime, fault history, exportable audit packages.
- **Auth:** Active Directory / Windows integrated auth / SSO / MFA; role-based permissions beyond the two roles.
- **UI:** large-screen operations display, customisable widgets, signal card view, range schematic view, power/Eb/No trend graphs.

---

## Suggested near-term sequencing

`0.6.0 (done)` → **0.7.0 UI polish** (quick wins, high visibility) →
**0.8.0 splitter/device status** (your operational ask) →
**0.9.0 hardening** (Postgres/HTTPS/backups) → **1.0.0** —
with the **CBM-400 spike running in parallel** from ~0.8.0 so 1.1 can start on solid findings.
