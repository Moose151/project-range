"""
Initialise the database and create a default administrator account.
Run once: python init_db.py
Re-running is safe — it skips existing data and only adds missing tables/seed rows.
"""
from datetime import datetime

from app.config import AUDIT_ARCHIVE_DIR, DATABASE_URL, SERIAL_ARCHIVE_DIR
from app.database import engine, Base
from app.file_security import harden_sqlite_storage
from app.models import (
    User, RangeStateLog, Signal, ModulationType, FecType, SignalSource, AntennaType,
    LogSession, SignalPackage, SignalPackageEntry, Serial, SerialPackage,
    DocPage, DocVersion, AppSetting, RFDevice, DevicePort, DeviceLink,
    CDATable, CDAWindow, SerialCDATable, Incident, CeaseEvent, DutyRole,
)
from app.auth import hash_password
from sqlalchemy.orm import Session
from sqlalchemy import text

DEFAULT_MOD_TYPES = [
    ("BPSK",   0),
    ("QPSK",   1),
    ("8PSK",   2),
    ("16APSK", 3),
    ("32APSK", 4),
]

DEFAULT_FEC_TYPES = [
    ("1/2",  0),
    ("2/3",  1),
    ("3/4",  2),
    ("5/6",  3),
    ("7/8",  4),
    ("8/9",  5),
    ("9/10", 6),
]

# (name, colour, display_order) — admin-editable duty-position tags.
DEFAULT_DUTY_ROLES = [
    ("Operator",   "#0d6efd", 0),
    ("Supervisor", "#198754", 1),
    ("EA Safety",  "#dc3545", 2),
    ("Observer",   "#6c757d", 3),
]

# Range CBM-400 modems. Seeded idempotently into the device registry so signal
# package entries can be mapped to a modem before the read-only sync poller runs.
DEFAULT_CBM_DEVICES = [
    ("CBM-400-1", "10.74.10.61"),
    ("CBM-400-2", "10.74.10.62"),
    ("CBM-400-3", "10.74.10.63"),
    ("CBM-400-4", "10.74.10.64"),
]

def _columns(conn, table):
    return [row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))]


def _rename_column(conn, table, old, new):
    """Rename old->new if old exists and new does not yet. Safe to re-run."""
    cols = _columns(conn, table)
    if old in cols and new not in cols:
        try:
            conn.execute(text(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}"))
            conn.commit()
        except Exception:
            pass


def _migrate(conn):
    """Apply additive SQLite migrations for new columns. Safe to re-run."""
    # BUC/LO were renamed to TxLO/RxLO. Rename existing columns first so legacy
    # databases keep their data; the additive step below covers brand-new and
    # pre-RF-feature databases.
    for table in ("signal_packages", "frequency_templates"):
        _rename_column(conn, table, "buc", "tx_lo")
        _rename_column(conn, table, "lo", "rx_lo")

    migrations = [
        "ALTER TABLE signals ADD COLUMN exclusivity_group VARCHAR(128)",
        "ALTER TABLE signal_logs ADD COLUMN source VARCHAR(128)",
        "ALTER TABLE signal_logs ADD COLUMN antenna VARCHAR(128)",
        "ALTER TABLE signal_logs ADD COLUMN session_id INTEGER REFERENCES log_sessions(id)",
        "ALTER TABLE signal_logs ADD COLUMN serial_id INTEGER REFERENCES serials(id)",
        "ALTER TABLE serials ADD COLUMN is_started BOOLEAN DEFAULT 0",
        "ALTER TABLE signal_packages ADD COLUMN band VARCHAR(8)",
        "ALTER TABLE signal_packages ADD COLUMN antenna VARCHAR(128)",
        "ALTER TABLE signal_packages ADD COLUMN tx_lo FLOAT",
        "ALTER TABLE signal_packages ADD COLUMN rx_lo FLOAT",
        "ALTER TABLE signal_packages ADD COLUMN ttf FLOAT",
        "ALTER TABLE signal_packages ADD COLUMN ttf_direction VARCHAR(4) DEFAULT '+'",
        "ALTER TABLE signal_packages ADD COLUMN freq_unit VARCHAR(4) DEFAULT 'MHz'",
        "ALTER TABLE signal_package_entries ADD COLUMN cbm_device_id INTEGER REFERENCES rf_devices(id)",
        "ALTER TABLE signal_package_entries ADD COLUMN cbm_path VARCHAR(16)",
        "ALTER TABLE signal_package_entries ADD COLUMN cbm_carrier VARCHAR(64)",
        "ALTER TABLE signal_package_entries ADD COLUMN inner_code VARCHAR(32)",
        "ALTER TABLE signals ADD COLUMN max_power_dbm FLOAT",
        "ALTER TABLE users ADD COLUMN default_freq_unit VARCHAR(4) DEFAULT 'MHz'",
        "ALTER TABLE users ADD COLUMN default_power_unit VARCHAR(4) DEFAULT 'dBm'",
        "ALTER TABLE users ADD COLUMN must_change_password BOOLEAN DEFAULT 0",
        "ALTER TABLE users ADD COLUMN active_session_token VARCHAR(64)",
        "ALTER TABLE rf_devices ADD COLUMN device_model VARCHAR(128)",
        "ALTER TABLE rf_devices ADD COLUMN has_web_gui BOOLEAN DEFAULT 0",
        "ALTER TABLE rf_devices ADD COLUMN cbm_sync_enabled BOOLEAN DEFAULT 0",
        "ALTER TABLE rf_devices ADD COLUMN cbm_username VARCHAR(128)",
        "ALTER TABLE rf_devices ADD COLUMN cbm_password_encrypted TEXT",
        "ALTER TABLE rf_devices ADD COLUMN cbm_last_sync_at DATETIME",
        "ALTER TABLE rf_devices ADD COLUMN cbm_last_sync_status VARCHAR(32)",
        "ALTER TABLE rf_devices ADD COLUMN cbm_last_sync_error TEXT",
        "ALTER TABLE users ADD COLUMN duty_role VARCHAR(64)",
        "ALTER TABLE users ADD COLUMN duty_role_color VARCHAR(16)",
        "ALTER TABLE users ADD COLUMN is_archived BOOLEAN DEFAULT 0",
        "ALTER TABLE signal_packages ADD COLUMN is_testing BOOLEAN DEFAULT 0",
        "ALTER TABLE serials ADD COLUMN is_testing BOOLEAN DEFAULT 0",
        "ALTER TABLE signal_logs ADD COLUMN is_testing BOOLEAN DEFAULT 0",
        "ALTER TABLE signal_logs ADD COLUMN engaged BOOLEAN DEFAULT 0",
        "ALTER TABLE audit_logs ADD COLUMN is_testing BOOLEAN DEFAULT 0",
        "ALTER TABLE rf_devices ADD COLUMN is_testing BOOLEAN DEFAULT 0",
        "ALTER TABLE device_links ADD COLUMN is_testing BOOLEAN DEFAULT 0",
        "ALTER TABLE cda_tables ADD COLUMN is_testing BOOLEAN DEFAULT 0",
        "ALTER TABLE incidents ADD COLUMN is_testing BOOLEAN DEFAULT 0",
        "ALTER TABLE incidents ADD COLUMN approval_status VARCHAR(16) DEFAULT 'approved'",
        "ALTER TABLE incidents ADD COLUMN approved_by_id INTEGER REFERENCES users(id)",
        "ALTER TABLE incidents ADD COLUMN approved_at DATETIME",
        "ALTER TABLE incidents ADD COLUMN rejection_reason TEXT",
        "ALTER TABLE cease_events ADD COLUMN is_testing BOOLEAN DEFAULT 0",
        "ALTER TABLE doc_versions ADD COLUMN base_content TEXT",
        "ALTER TABLE doc_pages ADD COLUMN category VARCHAR(128)",
        "ALTER TABLE doc_pages ADD COLUMN tags VARCHAR(256)",
        "ALTER TABLE rf_devices ADD COLUMN snmp_enabled BOOLEAN DEFAULT 0",
        "ALTER TABLE rf_devices ADD COLUMN snmp_version VARCHAR(4) DEFAULT '2c'",
        "ALTER TABLE rf_devices ADD COLUMN snmp_port INTEGER DEFAULT 161",
        "ALTER TABLE rf_devices ADD COLUMN snmp_community_encrypted TEXT",
        "ALTER TABLE rf_devices ADD COLUMN snmp_v3_user VARCHAR(128)",
        "ALTER TABLE rf_devices ADD COLUMN snmp_v3_auth_encrypted TEXT",
        "ALTER TABLE rf_devices ADD COLUMN snmp_v3_priv_encrypted TEXT",
        "ALTER TABLE rf_devices ADD COLUMN snmp_last_poll_at DATETIME",
        "ALTER TABLE rf_devices ADD COLUMN snmp_last_poll_status VARCHAR(32)",
        "ALTER TABLE rf_devices ADD COLUMN snmp_last_poll_error TEXT",
        "ALTER TABLE rf_devices ADD COLUMN snmp_system_alarm VARCHAR(16)",
        "ALTER TABLE rf_devices ADD COLUMN snmp_ignored_modules TEXT",
        "ALTER TABLE rf_devices ADD COLUMN snmp_modules_json TEXT",
        "ALTER TABLE device_ports ADD COLUMN observed_routed_from INTEGER",
        "ALTER TABLE device_ports ADD COLUMN observed_label VARCHAR(128)",
    ]
    for sql in migrations:
        try:
            conn.execute(text(sql))
            conn.commit()
        except Exception:
            pass  # column already exists
    try:
        conn.execute(text("UPDATE users SET role = 'administrator' WHERE role IN ('SUPERVISOR', 'supervisor')"))
        conn.execute(text("UPDATE users SET role = 'user' WHERE role IN ('OPERATOR', 'operator')"))
        conn.execute(text("UPDATE users SET role = 'observer' WHERE role IN ('SAFETY_SUPERVISOR', 'safety_supervisor')"))
        conn.commit()
    except Exception:
        pass


INITIAL_DOCS = [
    (
        "Range Operations Overview",
        "range-operations-overview",
        """# Range Operations Overview

This page provides a high-level overview of how the range operates and the key concepts used throughout this system.

## Range States

| State | Description |
|---|---|
| **Standby/Off** | Range is inactive. No signals being generated or transmitted. |
| **Closed Loop** | Range is active at IF only. No RF is being transmitted. Used for configuration and testing. |
| **Live** | Range is fully active. RF is being transmitted. All safety procedures must be followed. |

## Signal Status Values

| Status | Colour | Meaning |
|---|---|---|
| Planned | Teal | Signal defined in package but not yet configured. |
| Configured | Blue | Signal has been configured but not yet transmitted. |
| Up | Green | Signal is active and transmitting (or receiving). |
| Standby | Amber | Signal is configured and paused. |
| Faulted | Red | Signal has an error or fault condition. |
| Down | Grey | Signal is inactive/off. |

## Key Workflow

1. Create a **Signal Package** defining the signals for a test or mission.
2. Create a **Serial** and assign one or more packages to it.
3. **Start** the serial — this pre-populates the dashboard with all signals at *Planned* status.
4. Use the **Dashboard** to update signal status in real time.
5. **End** the serial when complete — it moves to **History** where it can be reviewed and exported.
""",
    ),
    (
        "How to Move from Closed Loop to Live",
        "closed-loop-to-live",
        """# How to Move from Closed Loop to Live

Moving the range from Closed Loop to Live means RF will begin transmitting. Follow this procedure carefully.

## Pre-conditions

- All signals must be verified at IF (Closed Loop) before going Live.
- Confirm all personnel are clear of the antenna aperture.
- Confirm the target receiver is ready and expecting signal.
- Administrator must be aware and approve (verbal confirmation required in the MVP).

## Procedure

1. From any page, click **Change State** in the range banner.
2. Select **Live** as the new state.
3. Enter the reason for the state change (e.g. "Moving to Live for Trial XYZ").
4. Click **Confirm Change**.
5. The banner will change to the flashing red **RANGE IS LIVE** indicator.

## After Going Live

- Log each signal's status change (e.g. from Configured to Up) via the dashboard quick-edit or the Signal Logs page.
- Monitor the **Buzzer** indicator — it will activate when any signal is Up while the range is Live.
- Record any anomalies immediately using the **Notes** function in Signal Logs.

## Returning to Closed Loop

Follow the same procedure and select **Closed Loop** as the new state. All active signals should be set to Down or Standby before changing state.
""",
    ),
    (
        "How to Move from Live to Closed Loop",
        "live-to-closed-loop",
        """# How to Move from Live to Closed Loop

Before moving from Live to Closed Loop, ensure all RF transmissions have been safely terminated.

## Procedure

1. Set all active signals to **Down** or **Standby** using the dashboard quick-edit.
2. Confirm the buzzer indicator is no longer active.
3. Click **Change State** in the range banner.
4. Select **Closed Loop** as the new state.
5. Enter the reason (e.g. "Trial XYZ complete — returning to Closed Loop").
6. Click **Confirm Change**.

## Verification

- Confirm the range banner shows **Closed Loop — IF Only**.
- Confirm all signals show Down, Standby, or Configured status on the dashboard.
- Log a narrative note in Signal Logs summarising the session if required.
""",
    ),
    (
        "Signal Setup Procedure",
        "signal-setup",
        """# Signal Setup Procedure

This page describes how to configure and log a new signal on the range.

## Step 1 — Create a Signal Package (if not already done)

1. Go to **Packages** in the navigation.
2. Click **New Package** and give it a descriptive name.
3. Add signals to the package with their expected parameters (band, frequency, modulation, FEC, power).

## Step 2 — Create a Serial

1. Go to **Serials** in the navigation.
2. Click **New Serial** and enter a title (e.g. "Trial 042 — Ku Band Uplink Test").
3. Assign your signal package(s) to the serial.
4. Click **Start Serial** — the dashboard will populate with your signals at *Planned* status.

## Step 3 — Configure Signals

1. Use the **RF Calculator** to verify your frequency plan.
2. From the **Dashboard**, use the quick-edit (pencil icon) on each signal to update its status to *Configured* once set up.
3. Log the configured frequencies, modulation, and power using **New Log Entry** (or the dashboard quick-edit).

## Step 4 — Verify at IF (Closed Loop)

- Confirm signal is present at IF before going Live.
- Set signal status to **Up** once confirmed transmitting (IF only).

## Step 5 — Go Live

- Follow the **Closed Loop to Live** procedure.
- Update signal statuses as they transition to RF transmission.
""",
    ),
    (
        "RF Calculator Guide",
        "rf-calculator-guide",
        """# RF Calculator Guide

The RF Calculator computes all four key frequencies from one known frequency and the conversion values.

## Frequency Relationships

```
TxIF + TxLO = TxRF
TxRF ± TTF  = RxRF   (direction selectable: + or −)
RxRF − RxLO = RxIF
```

Where:
- **TxLO** — Transmit (up-convert) local oscillator frequency (formerly "BUC")
- **TTF** — Transponder Translation Frequency
- **RxLO** — Receive (down-convert) local oscillator frequency (formerly "LO")

## How to Use

1. Go to **Calculators → RF Freq**.
2. Select which frequency you know (TxIF, TxRF, RxRF, or RxIF).
3. Enter the known frequency value and its unit (MHz or GHz).
4. Enter your TxLO, RxLO, and TTF values (same unit as the known frequency).
5. Select the TTF direction (+ or −).
6. Select the output unit.
7. Optionally select a frequency band for validation.
8. Click **Calculate**.

## Frequency Templates

Common TxLO/RxLO/TTF configurations can be saved as **Frequency Templates** on the Config page (administrator only). Templates appear in the dropdown above the calculator and pre-fill all conversion values with a single click.

## Creating a Log Entry from the Calculator

After a successful calculation, click **Create Log Entry** in the results panel. This pre-fills the frequency fields on the New Log Entry form.
""",
    ),
    (
        "Power Calculator Guide",
        "power-calculator-guide",
        """# Power Calculator Guide

The Power Calculator provides unit conversion and a gain/loss chain calculator.

## Unit Converter

Converts between dBm, dBW, and Watts.

**Quick Reference:**
- dBm = dBW + 30
- W = 10^(dBW ÷ 10)
- W = 10^((dBm − 30) ÷ 10)

## Gain / Loss Chain Calculator

Build a chain of gain and loss stages to determine the final output power.

### Example Chain

| Stage | Type | Value |
|---|---|---|
| Modem Output | — | 20 dBm (starting power) |
| Cable Loss | Loss | 2 dB |
| Splitter | Loss | 3.5 dB |
| Amplifier | Gain | 30 dB |

Click **Add Stage** to add each element, select Loss or Gain, and enter the dB value. Click **Calculate Chain** to see per-stage and final output power in dBm, dBW, and Watts.

## EIRP Calculator

Go to **Calculators → EIRP** to calculate Effective Isotropic Radiated Power:

```
EIRP (dBW) = TxPower (dBW) − CableLoss (dB) + AntennaGain (dBi) − OtherLosses (dB)
```
""",
    ),
    (
        "Emergency Shutdown Procedure",
        "emergency-shutdown",
        """# Emergency Shutdown Procedure

> **This procedure is for logging and awareness only. The system does not control RF hardware directly.**

In an emergency requiring immediate cessation of RF transmission, follow your site-specific emergency procedures first. This system should be updated to reflect the range state as soon as it is safe to do so.

## After Emergency Stop

1. Once it is safe to do so, log into the system.
2. Click **Change State** and select **Standby/Off**.
3. Enter the reason (e.g. "Emergency stop — personnel safety").
4. Set all signal statuses to **Down** via the dashboard quick-edit.
5. Add a **Narrative Note** in Signal Logs documenting what happened, when, and who authorised the shutdown.

## Reporting

- Notify the Range Administrator immediately.
- Complete any required incident reports per site procedures.
- The Signal Logs and audit trail in this system can be exported to support any formal incident review.
""",
    ),
]

CBM_SYNC_DOC = (
    "CBM-400 Read-Only Signal Sync",
    "cbm-400-read-only-signal-sync",
    """# CBM-400 Read-Only Signal Sync

This page explains how Project Range is intended to read signal settings from the Viasat CBM-400 EBEM modems so operators do not have to enter the same signal changes twice.

> Current status: this feature is at the setup/manual-test stage. Project Range can store modem mappings and credentials, test a read-only CBM poll, and run a manual active-sync. Automatic timed polling still needs range-network testing before operational use.

## What This Does

Project Range does **not** configure the CBM-400 modem.

The integration is designed to:

- read current modem values from the CBM over the management network;
- compare those values with the active Project Range signal;
- write an automatic Project Range signal log entry when mapped modem values change;
- keep the normal Project Range package and serial workflow as the source of the planned signal list.

The integration is **read-only by policy**. Operators should continue to configure the modem using the approved EBEM/LCT/modem workflow.

## How Project Range Knows Which Signal Belongs To Which Modem

Project Range does not guess from modem state alone.

Each signal in a **Signal Package** can be mapped to a CBM modem through its
Source:

- **Source**: select the physical CBM modem source, such as `CBM-400-1`.
  CBM modem devices automatically appear in the Source list.
- **CBM Path**: which part of the modem to read, such as `Tx`, `Rx`, `Tx/Rx`, or `DVB`.

When a serial starts, Project Range creates the dashboard signals from the package. The CBM sync then only updates the active signal that has a matching package mapping.

Example:

| Package Signal | Source | CBM Path |
|---|---|---|
| S101 | CBM-400-1 | Tx |
| S102 | CBM-400-2 | Tx |

If S101 goes down on its modem and S102 comes up on its modem, Project Range can update S101 and S102 separately because the package tells it which signal owns which modem/path.

If two active signals claim the same modem/path, Project Range skips that mapping instead of guessing.

## Seeded CBM Devices

The following CBMs are seeded into **Devices**:

| Device | Address |
|---|---|
| CBM-400-1 | 10.74.10.61 |
| CBM-400-2 | 10.74.10.62 |
| CBM-400-3 | 10.74.10.63 |
| CBM-400-4 | 10.74.10.64 |

The reachability check uses port `22` because the first implementation targets SSH/ICC polling.

## Administrator Setup

1. Go to **Devices**.
2. Confirm each CBM is present and has the correct IP address.
3. Expand a CBM row with the pencil button.
4. Tick **Enable CBM read-only sync**.
5. Enter the EBEM username and password.
6. Save the device.
7. Press the plug/test button on the CBM row to test a read-only poll.

Passwords are stored encrypted on the server and are not shown back in the browser. If the password field is left blank while editing a device, the stored password is kept.

Important: the server `SECRET_KEY` must remain stable. If `SECRET_KEY` changes, stored modem passwords cannot be decrypted and must be entered again.

## Package Setup

1. Go to **Packages**.
2. Open the relevant package.
3. For each signal, use the edit pencil.
4. Set **Source** to the modem that carries that planned signal.
5. Set **CBM Path** to the path Project Range should read.
6. Save the signal.

Keep package mappings clear and one-to-one for active serials. If the same CBM/path is reused by different signals at different times, update the package or use the package that matches the planned serial.

## Manual Sync

After the CBM devices and package mappings are configured:

1. Start the serial as normal.
2. Go to **Devices**.
3. Click **Sync Active CBMs**.

Project Range will:

- inspect active serials;
- find package signals with CBM mappings;
- poll the enabled CBMs;
- write automatic signal log entries only when values differ;
- skip ambiguous mappings or CBMs that cannot be read.

## Values Read From The CBM

The first implementation uses EBEM ICC query commands over SSH:

```text
tx_cfg ?
rx_cfg ?
all_stat ?
```

These can provide values such as transmit operation, Tx IF frequency, Tx IF power, modulation, symbol rate, FEC/code, Rx IF frequency, receive level, Eb/N0, and modem/link/fault status.

## What Still Needs To Be Proven

Before using this operationally:

1. Install the updated Python dependency (`paramiko`) by rebuilding Docker or running `pip install -r requirements.txt`.
2. Enter real EBEM credentials for each CBM.
3. Test polling each CBM from the range server.
4. Confirm the ICC shell prompt/command flow matches the manual and the live firmware.
5. Confirm field mapping with real modem output.
6. Decide whether `TX_OP=OFF` should always mean Project Range status **Down**, or whether some states should map to **Configured** or **Standby**.
7. Decide whether automatic timed polling should be enabled, and at what interval.

Until those checks are complete, treat CBM sync as a manual test feature, not an operational automation.
""",
)


def _seed_docs(db, admin_id: int):
    from datetime import datetime
    for title, slug, content in INITIAL_DOCS:
        page = DocPage(
            title=title,
            slug=slug,
            content=content,
            is_published=True,
            created_by_id=admin_id,
        )
        db.add(page)
        db.flush()
        db.add(DocVersion(
            page_id=page.id,
            version_number=1,
            content=content,
            change_summary="Initial page created",
            approval_status="approved",
            created_by_id=admin_id,
            approved_by_id=admin_id,
            approved_at=datetime.utcnow(),
        ))
    db.commit()
    print(f"Seeded {len(INITIAL_DOCS)} documentation pages.")


def _ensure_doc(db, admin_id: int, title: str, slug: str, content: str):
    """Create a shipped docs page if it is missing; never overwrite user edits."""
    if db.query(DocPage).filter(DocPage.slug == slug).first():
        return False
    now = datetime.utcnow()
    page = DocPage(
        title=title,
        slug=slug,
        content=content,
        is_published=True,
        created_by_id=admin_id,
    )
    db.add(page)
    db.flush()
    db.add(DocVersion(
        page_id=page.id,
        version_number=1,
        content=content,
        change_summary="Seeded operational guide",
        approval_status="approved",
        created_by_id=admin_id,
        approved_by_id=admin_id,
        approved_at=now,
    ))
    db.commit()
    return True


def main():
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)

    with engine.connect() as conn:
        _migrate(conn)

    permission_errors = harden_sqlite_storage(DATABASE_URL, [AUDIT_ARCHIVE_DIR, SERIAL_ARCHIVE_DIR])
    if permission_errors:
        print("WARNING: could not harden one or more data/archive paths:")
        for error in permission_errors:
            print(f"  - {error}")

    with Session(engine) as db:
        # Default administrator
        if not db.query(User).first():
            admin = User(
                username="admin",
                password_hash=hash_password("changeme"),
                display_name="Administrator",
                role="administrator",
                must_change_password=True,  # force a real password at first login
            )
            db.add(admin)
            db.flush()

            db.add(RangeStateLog(
                previous_state=None,
                new_state="Standby/Off",
                changed_by_id=admin.id,
                reason="System initialisation",
            ))

            for name, desc in [
                ("SIG-01", "Primary uplink signal"),
                ("SIG-02", "Secondary downlink signal"),
            ]:
                db.add(Signal(name=name, description=desc))

            db.commit()
            print("Created default administrator account: admin / changeme")
            print("IMPORTANT: Change the default password immediately after first login.")
        else:
            print("Users already exist — skipping user seed.")

        if not db.query(AppSetting).filter(AppSetting.key == "local_timezone").first():
            db.add(AppSetting(key="local_timezone", value="UTC"))
            db.commit()
            print("Seeded default local timezone: UTC")

        if not db.query(AppSetting).filter(AppSetting.key == "audit_live_record_limit").first():
            db.add(AppSetting(key="audit_live_record_limit", value="1000"))
            db.commit()
            print("Seeded default audit live record limit: 1000")

        # Seed modulation types if table is empty
        if not db.query(ModulationType).first():
            for name, order in DEFAULT_MOD_TYPES:
                db.add(ModulationType(name=name, display_order=order))
            db.commit()
            print(f"Seeded {len(DEFAULT_MOD_TYPES)} modulation types.")
        else:
            print("Modulation types already seeded — skipping.")

        # Seed FEC types if table is empty
        if not db.query(FecType).first():
            for name, order in DEFAULT_FEC_TYPES:
                db.add(FecType(name=name, display_order=order))
            db.commit()
            print(f"Seeded {len(DEFAULT_FEC_TYPES)} FEC types.")
        else:
            print("FEC types already seeded — skipping.")

        # Seed duty-role tags if table is empty
        if not db.query(DutyRole).first():
            for name, color, order in DEFAULT_DUTY_ROLES:
                db.add(DutyRole(name=name, color=color, display_order=order))
            db.commit()
            print(f"Seeded {len(DEFAULT_DUTY_ROLES)} duty roles.")
        else:
            print("Duty roles already seeded — skipping.")

        created_cbms = 0
        for name, host in DEFAULT_CBM_DEVICES:
            existing = db.query(RFDevice).filter(
                (RFDevice.name == name) | (RFDevice.host == host)
            ).first()
            if existing:
                continue
            db.add(RFDevice(
                name=name,
                device_model="CBM-400",
                device_type="modem",
                host=host,
                check_port=22,
                has_web_gui=True,
                cbm_sync_enabled=False,
                notes="Seeded CBM-400 modem for read-only signal sync mapping.",
                num_inputs=1,
                num_outputs=1,
            ))
            created_cbms += 1
        if created_cbms:
            db.commit()
            print(f"Seeded {created_cbms} CBM-400 modem devices.")

        # Seed initial documentation pages if none exist
        if not db.query(DocPage).first():
            admin = db.query(User).filter(User.username == "admin").first()
            if admin:
                _seed_docs(db, admin.id)
        admin = db.query(User).filter(User.username == "admin").first() or db.query(User).first()
        if admin:
            if _ensure_doc(db, admin.id, *CBM_SYNC_DOC):
                print("Seeded CBM-400 read-only signal sync documentation page.")

    print("Done.")

if __name__ == "__main__":
    main()
