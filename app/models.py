import enum
from datetime import datetime
from sqlalchemy import (
    Boolean, DateTime, Enum, Float, ForeignKey,
    Integer, String, Text, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Role(str, enum.Enum):
    OPERATOR = "operator"
    SUPERVISOR = "supervisor"


class RangeState(str, enum.Enum):
    CLOSED_LOOP = "Closed Loop"
    LIVE = "Live"
    STANDBY = "Standby/Off"


class SignalStatus(str, enum.Enum):
    PLANNED = "Planned"
    CONFIGURED = "Configured"
    UP = "Up"
    DOWN = "Down"
    FAULTED = "Faulted"
    STANDBY = "Standby"


class EntryType(str, enum.Enum):
    MANUAL = "Manual"
    AUTOMATIC = "Automatic"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[Role] = mapped_column(Enum(Role), nullable=False, default=Role.OPERATOR)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # User preferences
    default_freq_unit: Mapped[str] = mapped_column(String(4), default="MHz")
    default_power_unit: Mapped[str] = mapped_column(String(4), default="dBm")
    # Force a password change at next login (e.g. seeded/reset accounts)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)

    signal_logs: Mapped[list["SignalLog"]] = relationship("SignalLog", foreign_keys="SignalLog.operator_id", back_populates="operator")
    range_state_changes: Mapped[list["RangeStateLog"]] = relationship("RangeStateLog", back_populates="changed_by_user")
    audit_entries: Mapped[list["AuditLog"]] = relationship("AuditLog", back_populates="user")


class RangeStateLog(Base):
    __tablename__ = "range_state_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    previous_state: Mapped[str] = mapped_column(String(32), nullable=True)
    new_state: Mapped[str] = mapped_column(String(32), nullable=False)
    changed_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    changed_by_user: Mapped[User] = relationship("User", back_populates="range_state_changes")


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    exclusivity_group: Mapped[str | None] = mapped_column(String(128), nullable=True)
    default_band: Mapped[str | None] = mapped_column(String(8), nullable=True)
    default_modulation: Mapped[str | None] = mapped_column(String(64), nullable=True)
    default_symbol_rate: Mapped[str | None] = mapped_column(String(32), nullable=True)
    default_fec: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Optional safe-power ceiling (dBm); logged power above this raises a warning
    max_power_dbm: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    signal_logs: Mapped[list["SignalLog"]] = relationship("SignalLog", back_populates="signal")


# ── Signal Packages ────────────────────────────────────────────────────────────

class SignalPackage(Base):
    __tablename__ = "signal_packages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Package-level RF configuration — shared by all signals in this package
    band: Mapped[str | None] = mapped_column(String(8), nullable=True)
    antenna: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tx_lo: Mapped[float | None] = mapped_column(Float, nullable=True)  # was "buc"
    rx_lo: Mapped[float | None] = mapped_column(Float, nullable=True)  # was "lo"
    ttf: Mapped[float | None] = mapped_column(Float, nullable=True)
    ttf_direction: Mapped[str] = mapped_column(String(4), default="+")
    freq_unit: Mapped[str] = mapped_column(String(4), default="MHz")

    created_by: Mapped[User] = relationship("User", foreign_keys="SignalPackage.created_by_id")
    signals: Mapped[list["SignalPackageEntry"]] = relationship(
        "SignalPackageEntry", back_populates="package",
        cascade="all, delete-orphan",
        order_by="SignalPackageEntry.display_order",
    )
    serial_links: Mapped[list["SerialPackage"]] = relationship("SerialPackage", back_populates="package")


class SignalPackageEntry(Base):
    __tablename__ = "signal_package_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    package_id: Mapped[int] = mapped_column(ForeignKey("signal_packages.id"), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    signal_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(256), nullable=True)
    band: Mapped[str | None] = mapped_column(String(16), nullable=True)
    tx_if: Mapped[float | None] = mapped_column(Float, nullable=True)
    tx_rf: Mapped[float | None] = mapped_column(Float, nullable=True)
    rx_rf: Mapped[float | None] = mapped_column(Float, nullable=True)
    rx_if: Mapped[float | None] = mapped_column(Float, nullable=True)
    freq_unit: Mapped[str] = mapped_column(String(4), default="MHz")
    modulation: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fec: Mapped[str | None] = mapped_column(String(32), nullable=True)
    symbol_rate: Mapped[str | None] = mapped_column(String(32), nullable=True)
    power: Mapped[float | None] = mapped_column(Float, nullable=True)
    power_unit: Mapped[str] = mapped_column(String(8), default="dBm")
    eb_no: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    antenna: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    package: Mapped["SignalPackage"] = relationship("SignalPackage", back_populates="signals")


# ── Serials ────────────────────────────────────────────────────────────────────

class Serial(Base):
    __tablename__ = "serials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    opened_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    closed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_started: Mapped[bool] = mapped_column(Boolean, default=False)

    opened_by: Mapped[User] = relationship("User", foreign_keys="Serial.opened_by_id")
    closed_by: Mapped[User | None] = relationship("User", foreign_keys="Serial.closed_by_id")
    package_links: Mapped[list["SerialPackage"]] = relationship(
        "SerialPackage", back_populates="serial", cascade="all, delete-orphan",
    )
    signal_logs: Mapped[list["SignalLog"]] = relationship("SignalLog", back_populates="serial")

    @property
    def display_title(self) -> str:
        return f"{self.opened_at.strftime('%Y-%m-%d')} — {self.title}"


class SerialPackage(Base):
    """Junction between Serial and SignalPackage."""
    __tablename__ = "serial_packages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    serial_id: Mapped[int] = mapped_column(ForeignKey("serials.id"), nullable=False)
    package_id: Mapped[int] = mapped_column(ForeignKey("signal_packages.id"), nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    serial: Mapped["Serial"] = relationship("Serial", back_populates="package_links")
    package: Mapped["SignalPackage"] = relationship("SignalPackage", back_populates="serial_links")


# ── Signal Logs ────────────────────────────────────────────────────────────────

class SignalLog(Base):
    __tablename__ = "signal_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    operator_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    range_state: Mapped[str] = mapped_column(String(32), nullable=False)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"), nullable=True)
    signal_name: Mapped[str] = mapped_column(String(128), nullable=False)
    signal_status: Mapped[str] = mapped_column(String(32), nullable=False)

    tx_if: Mapped[float | None] = mapped_column(Float, nullable=True)
    tx_rf: Mapped[float | None] = mapped_column(Float, nullable=True)
    rx_rf: Mapped[float | None] = mapped_column(Float, nullable=True)
    rx_if: Mapped[float | None] = mapped_column(Float, nullable=True)
    freq_unit: Mapped[str] = mapped_column(String(4), default="MHz")
    band: Mapped[str | None] = mapped_column(String(16), nullable=True)
    modulation: Mapped[str | None] = mapped_column(String(64), nullable=True)
    symbol_rate: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fec: Mapped[str | None] = mapped_column(String(32), nullable=True)
    power: Mapped[float | None] = mapped_column(Float, nullable=True)
    power_unit: Mapped[str] = mapped_column(String(8), default="dBm")
    eb_no: Mapped[float | None] = mapped_column(Float, nullable=True)

    source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    antenna: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # serial_id replaces session_id; session_id kept as nullable for old data
    serial_id: Mapped[int | None] = mapped_column(ForeignKey("serials.id"), nullable=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("log_sessions.id"), nullable=True)

    activity_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    entry_type: Mapped[str] = mapped_column(String(16), default="Manual")
    warning_flags: Mapped[str | None] = mapped_column(Text, nullable=True)

    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, onupdate=func.now())
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    operator: Mapped[User] = relationship("User", foreign_keys="SignalLog.operator_id", back_populates="signal_logs")
    signal: Mapped[Signal | None] = relationship("Signal", back_populates="signal_logs")
    updated_by: Mapped[User | None] = relationship("User", foreign_keys="SignalLog.updated_by_id")
    serial: Mapped["Serial | None"] = relationship("Serial", foreign_keys="SignalLog.serial_id", back_populates="signal_logs")
    session: Mapped["LogSession | None"] = relationship("LogSession", foreign_keys="SignalLog.session_id", back_populates="signal_logs")


# ── Legacy LogSession (kept for old data, no longer in UI) ────────────────────

class LogSession(Base):
    __tablename__ = "log_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    opened_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    closed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    opened_by: Mapped[User] = relationship("User", foreign_keys="LogSession.opened_by_id")
    closed_by: Mapped[User | None] = relationship("User", foreign_keys="LogSession.closed_by_id")
    signal_logs: Mapped[list["SignalLog"]] = relationship("SignalLog", back_populates="session")


# ── Frequency Templates ───────────────────────────────────────────────────────

class FrequencyTemplate(Base):
    __tablename__ = "frequency_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    band: Mapped[str | None] = mapped_column(String(8), nullable=True)
    tx_lo: Mapped[float | None] = mapped_column(Float, nullable=True)  # was "buc"
    rx_lo: Mapped[float | None] = mapped_column(Float, nullable=True)  # was "lo"
    ttf: Mapped[float | None] = mapped_column(Float, nullable=True)
    ttf_direction: Mapped[str] = mapped_column(String(4), default="+")
    default_unit: Mapped[str] = mapped_column(String(4), default="MHz")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ── Documentation / Wiki ──────────────────────────────────────────────────────

class DocPage(Base):
    __tablename__ = "doc_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    slug: Mapped[str] = mapped_column(String(256), nullable=False, unique=True, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_published: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_by: Mapped[User] = relationship("User", foreign_keys="DocPage.created_by_id")
    updated_by: Mapped[User | None] = relationship("User", foreign_keys="DocPage.updated_by_id")
    versions: Mapped[list["DocVersion"]] = relationship(
        "DocVersion", back_populates="page",
        cascade="all, delete-orphan",
        order_by="DocVersion.version_number.desc()",
    )


class DocVersion(Base):
    __tablename__ = "doc_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("doc_pages.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    change_summary: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # approval_status: approved | pending | rejected
    approval_status: Mapped[str] = mapped_column(String(16), nullable=False, default="approved")
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    page: Mapped[DocPage] = relationship("DocPage", back_populates="versions")
    created_by: Mapped[User] = relationship("User", foreign_keys="DocVersion.created_by_id")
    approved_by: Mapped[User | None] = relationship("User", foreign_keys="DocVersion.approved_by_id")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    previous_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User | None] = relationship("User", back_populates="audit_entries")


class ModulationType(Base):
    __tablename__ = "modulation_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class FecType(Base):
    __tablename__ = "fec_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SignalSource(Base):
    __tablename__ = "signal_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(256), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AntennaType(Base):
    __tablename__ = "antenna_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(256), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RFDevice(Base):
    """A range device (modem, splitter, combiner, spectrum analyser, ...).

    Splitter/combiner-type devices also carry a routing matrix via DevicePort:
    each output port can be routed from an input port, and every port has a
    free-text label describing what is physically cabled to it.
    """
    __tablename__ = "rf_devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)          # unique instance name, e.g. "CBM-400-1"
    device_model: Mapped[str | None] = mapped_column(String(128), nullable=True)  # product model, e.g. "CBM-400"
    device_type: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    host: Mapped[str | None] = mapped_column(String(128), nullable=True)        # IP / hostname
    check_port: Mapped[int | None] = mapped_column(Integer, nullable=True)      # TCP port for reachability
    has_web_gui: Mapped[bool] = mapped_column(Boolean, default=False)           # exposes a web GUI at http://<host>/
    location: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    num_inputs: Mapped[int] = mapped_column(Integer, default=16)
    num_outputs: Mapped[int] = mapped_column(Integer, default=16)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    ports: Mapped[list["DevicePort"]] = relationship(
        "DevicePort", back_populates="device",
        cascade="all, delete-orphan", order_by="DevicePort.idx",
    )

    @property
    def is_routing(self) -> bool:
        return self.device_type in ("splitter", "combiner", "switch")

    @property
    def web_gui_url(self) -> str | None:
        return f"http://{self.host}/" if self.has_web_gui and self.host else None


class DevicePort(Base):
    """One input or output port on an RFDevice."""
    __tablename__ = "device_ports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("rf_devices.id"), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(3), nullable=False)   # 'in' or 'out'
    idx: Mapped[int] = mapped_column(Integer, nullable=False)           # 1-based port number
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    routed_from: Mapped[int | None] = mapped_column(Integer, nullable=True)  # input idx feeding an output

    device: Mapped["RFDevice"] = relationship("RFDevice", back_populates="ports")


class DeviceLink(Base):
    """A physical or logical connection between two devices.

    link_type: 'rf' (coax/waveguide), 'ip' (ethernet), 'clock' (timing ref), 'power' (DC)
    from_port_idx / to_port_idx: port number on routing devices (splitter/combiner/switch);
        used to auto-populate labels on the routing page.
    """
    __tablename__ = "device_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_device_id: Mapped[int] = mapped_column(ForeignKey("rf_devices.id"), nullable=False)
    from_port: Mapped[str | None] = mapped_column(String(64), nullable=True)       # free-text port label
    from_port_idx: Mapped[int | None] = mapped_column(Integer, nullable=True)      # port number for routing devices
    to_device_id: Mapped[int] = mapped_column(ForeignKey("rf_devices.id"), nullable=False)
    to_port: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_port_idx: Mapped[int | None] = mapped_column(Integer, nullable=True)
    link_type: Mapped[str] = mapped_column(String(16), default="rf")   # rf|ip|clock|power
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    from_device: Mapped["RFDevice"] = relationship("RFDevice", foreign_keys=[from_device_id])
    to_device: Mapped["RFDevice"] = relationship("RFDevice", foreign_keys=[to_device_id])


class Incident(Base):
    """A fault / incident report. Logging + awareness only (no hardware control)."""
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(16), default="medium")   # low|medium|high|critical
    status: Mapped[str] = mapped_column(String(16), default="open")       # open|investigating|resolved|closed
    affected: Mapped[str | None] = mapped_column(String(200), nullable=True)  # signal/device/area
    serial_id: Mapped[int | None] = mapped_column(ForeignKey("serials.id"), nullable=True)
    reported_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    reported_by: Mapped["User"] = relationship("User", foreign_keys="Incident.reported_by_id")
    resolved_by: Mapped["User | None"] = relationship("User", foreign_keys="Incident.resolved_by_id")
