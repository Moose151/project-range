"""
Initialise the database and create a default supervisor account.
Run once: python init_db.py
Re-running is safe — it skips existing data and only adds missing tables/seed rows.
"""
from app.database import engine, Base
from app.models import (
    User, RangeStateLog, Signal, ModulationType, FecType, SignalSource, AntennaType,
    LogSession, SignalPackage, SignalPackageEntry, Serial, SerialPackage,
    DocPage, DocVersion,
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

def _migrate(conn):
    """Apply additive SQLite migrations for new columns. Safe to re-run."""
    migrations = [
        "ALTER TABLE signals ADD COLUMN exclusivity_group VARCHAR(128)",
        "ALTER TABLE signal_logs ADD COLUMN source VARCHAR(128)",
        "ALTER TABLE signal_logs ADD COLUMN antenna VARCHAR(128)",
        "ALTER TABLE signal_logs ADD COLUMN session_id INTEGER REFERENCES log_sessions(id)",
        "ALTER TABLE signal_logs ADD COLUMN serial_id INTEGER REFERENCES serials(id)",
        "ALTER TABLE serials ADD COLUMN is_started BOOLEAN DEFAULT 0",
    ]
    for sql in migrations:
        try:
            conn.execute(text(sql))
            conn.commit()
        except Exception:
            pass  # column already exists


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
- Supervisor must be aware and approve (verbal confirmation required in the MVP).

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
TxIF + BUC = TxRF
TxRF ± TTF = RxRF   (direction selectable: + or −)
RxRF − LO  = RxIF
```

Where:
- **BUC** — Block Up Converter offset frequency
- **TTF** — Transponder Translation Frequency
- **LO** — Local Oscillator frequency

## How to Use

1. Go to **Calculators → RF Freq**.
2. Select which frequency you know (TxIF, TxRF, RxRF, or RxIF).
3. Enter the known frequency value and its unit (MHz or GHz).
4. Enter your BUC, LO, and TTF values (same unit as the known frequency).
5. Select the TTF direction (+ or −).
6. Select the output unit.
7. Optionally select a frequency band for validation.
8. Click **Calculate**.

## Frequency Templates

Common BUC/LO/TTF configurations can be saved as **Frequency Templates** on the Config page (supervisor only). Templates appear in the dropdown above the calculator and pre-fill all conversion values with a single click.

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

- Notify the Range Supervisor immediately.
- Complete any required incident reports per site procedures.
- The Signal Logs and audit trail in this system can be exported to support any formal incident review.
""",
    ),
]


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


def main():
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)

    with engine.connect() as conn:
        _migrate(conn)

    with Session(engine) as db:
        # Default supervisor
        if not db.query(User).first():
            admin = User(
                username="admin",
                password_hash=hash_password("changeme"),
                display_name="Administrator",
                role="supervisor",
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
            print("Created default supervisor account: admin / changeme")
            print("IMPORTANT: Change the default password immediately after first login.")
        else:
            print("Users already exist — skipping user seed.")

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

        # Seed initial documentation pages if none exist
        if not db.query(DocPage).first():
            admin = db.query(User).filter(User.username == "admin").first()
            if admin:
                _seed_docs(db, admin.id)

    print("Done.")

if __name__ == "__main__":
    main()
