"""
Initialise the database and create a default supervisor account.
Run once: python init_db.py
Re-running is safe — it skips existing data and only adds missing tables/seed rows.
"""
from app.database import engine, Base
from app.models import (
    User, RangeStateLog, Signal, ModulationType, FecType, SignalSource, AntennaType,
    LogSession, SignalPackage, SignalPackageEntry, Serial, SerialPackage,
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

    print("Done.")

if __name__ == "__main__":
    main()
