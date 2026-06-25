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

## 0.7.0 — UI & presentation polish

Theme: make it look and feel like an operations tool. *(User-requested batch.)*

- [ ] **Range logo** — replace the favicon + navbar brand with the supplied logo (awaiting upload); add to login page and browser tab.
- [ ] **Navbar / UI tidy** — tighten nav grouping, spacing, and active states; consistent page headers and card rhythm.
- [ ] **Light / dark mode** — user-toggleable theme (Bootstrap 5.3 `data-bs-theme`), remembered per user/terminal; default dark.
- [ ] **User-selected default units** (MHz/GHz, dBm/dBW) — from Scope §12.5.
- [ ] Centralise the version string into a shared template global (remove the `default('0.6.0')` fallback).

## 0.8.0 — RF distribution & device status

Theme: visibility of the physical signal path. *(User-requested splitter page + Scope §11.9.)*

- [ ] **Splitter / combiner routing page** — model the two 16-port devices (16 in / 18 out each); show how each input/output is routed, editable, with a clear matrix/schematic view. Persisted and audited.
- [ ] **Basic device status checks** — ping-style up/down indicators for modems, splitters, combiners, spectrum analyser, and other configured devices (no hardware control). Scope §11.9.
- [ ] Device registry (name, type, IP/host, location) underpinning both of the above.

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
