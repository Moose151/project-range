# Project Range — Roadmap to v1.0

**Current version:** `0.6.0` (beta) · shown bottom-right in the UI and in `app/config.py`.

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

## ✅ Already delivered (through 0.6.0)

Core of the MVP scope is in place:

- RF frequency calculator (TxIF/TxRF/RxRF/RxIF from one known value) + frequency templates
- Power converter (dBm/dBW/W), gain/loss chain, EIRP
- Signal logging with per-signal power-warning thresholds + band/frequency validation
- Live dashboard (status, buzzer, drag-tab merge/split, steppers, column toggles)
- Range state management (Standby/Closed Loop/Live) with reason + audit
- Package-level RF config (TxLO/RxLO/TTF) with one-frequency auto-calc across signals
- Documentation/wiki module, structured XLSX export, shift handover
- User auth (operator/supervisor), audit log, "remember this terminal"
- **0.6.0:** TxLO/RxLO naming, version badge, fully offline (LAN) styling, Docker deploy on port 7474

---

## 0.7.0 — UI & presentation polish ✅ (shipped, except logo)

Theme: make it look and feel like an operations tool. *(User-requested batch.)*

- [ ] **Range logo** — replace the favicon + navbar brand with the supplied logo; add to login page and browser tab. **Blocked: awaiting logo file upload.**
- [x] **Navbar / UI tidy** — grouped right-side controls (preferences link, theme toggle, logout); user name now links to preferences.
- [x] **Light / dark mode** — toggle in the navbar (Bootstrap 5.3 `data-bs-theme`), remembered per terminal via localStorage, applied pre-paint to avoid flash; default dark; works on login too.
- [x] **User-selected default units** (MHz/GHz, dBm/dBW) — stored per user, set on the Preferences page, applied to the RF and Power calculators. Scope §12.5.
- [x] Centralise the version string into a shared template global (`app/templating.py`); removed the hard-coded fallback.

## 0.8.0 — RF distribution & device status ✅ (shipped)

Theme: visibility of the physical signal path. *(User-requested splitter page + Scope §11.9.)*

- [x] **Splitter / combiner routing page** — crossbar matrix (each output routed from an input) **plus** a free-text label on every input/output port. Port counts configurable per device (default 16/16). Persisted and audited (`DEVICE_ROUTING`).
- [x] **Basic device status checks** — live up/down/no-check badges via a non-blocking concurrent TCP reachability probe (`/devices/status`, polled every 15s); no hardware control. Scope §11.9.
- [x] **Device registry** (name, type, host/IP, check port, location, port counts) — supervisor-managed CRUD, audited; underpins both of the above. New "Devices" nav entry.

## 0.9.0 — Operational hardening

Theme: ready to trust with real operations. *(Scope §13, Phase 4.)*

- [ ] **PostgreSQL option** — support Postgres via `DATABASE_URL` for multi-user concurrency (replace SQLite-specific migration with a proper migration tool, e.g. Alembic).
- [ ] **HTTPS/TLS** — optional reverse-proxy/self-signed setup for the range network.
- [ ] **Backups** — scheduled DB backup/restore procedure (documented + scripted).
- [ ] **Soft / hard log delete** — soft delete (recoverable) for operators, hard delete for supervisors. Scope §4.10.
- [ ] **Supervisor approval for going Live** + optional two-person confirmation for high-risk actions. Scope §12.2.
- [ ] **Incident / fault reporting** — capture, list, and export faults. Scope §12.2.

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

- [ ] **Enforce a real `SECRET_KEY`.** Today `app/config.py` falls back to a
  hard-coded dev secret if the env var is unset — anyone who knows it can forge
  session cookies. Fail closed (refuse to start) when `SECRET_KEY` is missing or
  is the known default. *(Docker compose already requires it; the app itself should too.)*
- [ ] **Remove default credentials.** The seed creates `admin` / `changeme`.
  Force a password change on first login (or a guided first-run admin setup) and
  never leave the default usable in a deployed instance.
- [ ] **HTTPS/TLS + `Secure` cookies.** Serve over TLS (reverse proxy or app-level)
  and set the session cookie `Secure`, `HttpOnly` (already on), `SameSite=Strict`.
  Currently cookies are sent without `Secure`, so on a plain-HTTP LAN they can be
  sniffed.
- [ ] **CSRF protection.** There is none today; every state-changing `POST`
  (logs, range state, users, config, packages) is vulnerable to cross-site request
  forgery. Add CSRF tokens (or strict `SameSite` + origin checks) to all forms.
- [ ] **Login brute-force protection.** No throttling or lockout exists. Add rate
  limiting / temporary lockout on repeated failed logins, and log auth
  success/failure events to the audit trail.
- [ ] **Password policy.** No minimum length/complexity is enforced. Add a sane
  policy on create/change, and block obviously weak passwords.

### High

- [ ] **Security headers** via middleware: `Content-Security-Policy` (now feasible
  since all assets are local/first-party), `X-Frame-Options: DENY` (clickjacking),
  `X-Content-Type-Options: nosniff`, `Referrer-Policy`, and `Strict-Transport-Security`
  once TLS is in place.
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
