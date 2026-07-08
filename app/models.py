import enum
from datetime import datetime
from sqlalchemy import (
    Boolean, DateTime, Enum, Float, ForeignKey, event,
    Integer, String, Text, func
)
from sqlalchemy.orm import Mapped, Session as SASession, mapped_column, relationship
from app.database import Base


class Role(str, enum.Enum):
    ADMINISTRATOR = "administrator"
    USER = "user"
    OBSERVER = "observer"
    # Backwards-compatible internal aliases for older permission checks.
    SUPERVISOR = "administrator"
    OPERATOR = "user"
    SAFETY_SUPERVISOR = "observer"


class RangeState(str, enum.Enum):
    CLOSED_LOOP = "Closed Loop"
    LIVE = "Live"
    STANDBY = "Standby/Off"
    TESTING = "Testing"


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
    role: Mapped[Role] = mapped_column(
        Enum(
            Role,
            values_callable=lambda enum_cls: [role.value for role in enum_cls],
            native_enum=False,
        ),
        nullable=False,
        default=Role.USER,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    active_session_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # User preferences
    default_freq_unit: Mapped[str] = mapped_column(String(4), default="MHz")
    default_power_unit: Mapped[str] = mapped_column(String(4), default="dBm")
    # Force a password change at next login (e.g. seeded/reset accounts)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    # Current duty-role tag (a visual position indicator, separate from the
    # permission `role` above). Self-selected by the user from the admin-managed
    # DutyRole list; name + colour are denormalised here so the badge can render
    # anywhere without a lookup. Cleared = no tag shown.
    duty_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duty_role_color: Mapped[str | None] = mapped_column(String(16), nullable=True)

    signal_logs: Mapped[list["SignalLog"]] = relationship("SignalLog", foreign_keys="SignalLog.operator_id", back_populates="operator")
    range_state_changes: Mapped[list["RangeStateLog"]] = relationship("RangeStateLog", back_populates="changed_by_user")
    audit_entries: Mapped[list["AuditLog"]] = relationship("AuditLog", back_populates="user")

    @property
    def role_label(self) -> str:
        labels = {
            Role.ADMINISTRATOR: "Administrator",
            Role.USER: "User",
            Role.OBSERVER: "Observer",
        }
        return labels.get(self.role, str(self.role).replace("_", " ").title())


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
    is_testing: Mapped[bool] = mapped_column(Boolean, default=False)

    # "live" = normal RF package; "closed" = closed-loop / IF-only (no band, antenna,
    # TxLO/RxLO or TTF — only IF frequencies are meaningful).
    loop_mode: Mapped[str] = mapped_column(String(8), default="live")

    # Package-level RF configuration — shared by all signals in this package
    band: Mapped[str | None] = mapped_column(String(8), nullable=True)
    antenna: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tx_lo: Mapped[float | None] = mapped_column(Float, nullable=True)  # was "buc"
    rx_lo: Mapped[float | None] = mapped_column(Float, nullable=True)  # was "lo"
    ttf: Mapped[float | None] = mapped_column(Float, nullable=True)
    ttf_direction: Mapped[str] = mapped_column(String(4), default="+")
    freq_unit: Mapped[str] = mapped_column(String(4), default="MHz")

    @property
    def is_closed_loop(self) -> bool:
        return self.loop_mode == "closed"

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
    inner_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    symbol_rate: Mapped[str | None] = mapped_column(String(32), nullable=True)
    power: Mapped[float | None] = mapped_column(Float, nullable=True)
    power_unit: Mapped[str] = mapped_column(String(8), default="dBm")
    eb_no: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    antenna: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cbm_device_id: Mapped[int | None] = mapped_column(ForeignKey("rf_devices.id"), nullable=True)
    cbm_path: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cbm_carrier: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    package: Mapped["SignalPackage"] = relationship("SignalPackage", back_populates="signals")
    cbm_device: Mapped["RFDevice | None"] = relationship("RFDevice", foreign_keys="SignalPackageEntry.cbm_device_id")


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
    is_testing: Mapped[bool] = mapped_column(Boolean, default=False)

    activity_id: Mapped[int | None] = mapped_column(ForeignKey("activities.id"), nullable=True)

    opened_by: Mapped[User] = relationship("User", foreign_keys="Serial.opened_by_id")
    closed_by: Mapped[User | None] = relationship("User", foreign_keys="Serial.closed_by_id")
    activity: Mapped["Activity | None"] = relationship("Activity", back_populates="serials", foreign_keys="Serial.activity_id")
    package_links: Mapped[list["SerialPackage"]] = relationship(
        "SerialPackage", back_populates="serial", cascade="all, delete-orphan",
    )
    signal_logs: Mapped[list["SignalLog"]] = relationship("SignalLog", back_populates="serial")
    cda_links: Mapped[list["SerialCDATable"]] = relationship("SerialCDATable", back_populates="serial", cascade="all, delete-orphan")

    @property
    def display_title(self) -> str:
        return f"{self.opened_at.strftime('%Y-%m-%d')} — {self.title}"

    @property
    def is_closed_loop(self) -> bool:
        """Derived (packages drive it): closed-loop when the serial has packages and
        every assigned package is closed-loop / IF-only."""
        packages = [link.package for link in self.package_links if link.package]
        return bool(packages) and all(p.is_closed_loop for p in packages)


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
    engaged: Mapped[bool] = mapped_column(Boolean, default=False)

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
    is_testing: Mapped[bool] = mapped_column(Boolean, default=False)

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
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tags: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # all = observers/users/admins, users = users/admins, admins = administrators only.
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="all")
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
    outgoing_links: Mapped[list["DocLink"]] = relationship(
        "DocLink",
        back_populates="from_page",
        cascade="all, delete-orphan",
        foreign_keys="DocLink.from_page_id",
    )
    aliases: Mapped[list["DocAlias"]] = relationship(
        "DocAlias",
        back_populates="page",
        cascade="all, delete-orphan",
        order_by="DocAlias.alias_title",
    )


class DocAlias(Base):
    __tablename__ = "doc_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("doc_pages.id"), nullable=False, index=True)
    alias_title: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    alias_slug: Mapped[str] = mapped_column(String(256), nullable=False, unique=True, index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    page: Mapped[DocPage] = relationship("DocPage", back_populates="aliases")
    created_by: Mapped[User | None] = relationship("User", foreign_keys=[created_by_id])


class DocLink(Base):
    __tablename__ = "doc_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_page_id: Mapped[int] = mapped_column(ForeignKey("doc_pages.id"), nullable=False, index=True)
    target_title: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    target_slug: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    target_page_id: Mapped[int | None] = mapped_column(ForeignKey("doc_pages.id"), nullable=True, index=True)
    is_missing: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    from_page: Mapped[DocPage] = relationship(
        "DocPage",
        back_populates="outgoing_links",
        foreign_keys=[from_page_id],
    )
    target_page: Mapped[DocPage | None] = relationship(
        "DocPage",
        foreign_keys=[target_page_id],
    )


class DocVersion(Base):
    __tablename__ = "doc_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("doc_pages.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Snapshot of the page content this edit was drafted against. Used to detect
    # concurrent-edit conflicts when approving pending proposals (a proposal whose
    # base no longer matches the live page would silently overwrite newer changes).
    base_content: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    is_testing: Mapped[bool] = mapped_column(Boolean, default=False)
    previous_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    record_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hash_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

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


class DutyRole(Base):
    """An admin-configurable duty-position tag (e.g. Operator, Supervisor,
    EA Safety). Purely a visual indicator of what position a user is filling
    right now — it grants no permissions. Users pick their own from the active
    list; the chosen name + colour are copied onto the User row.
    """
    __tablename__ = "duty_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    color: Mapped[str] = mapped_column(String(16), nullable=False, default="#0d6efd")
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(256), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, onupdate=func.now())


class ActivityType(Base):
    __tablename__ = "activity_types"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CallType(Base):
    """Admin-configurable list of call types for the dashboard Call button."""
    __tablename__ = "call_types"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Activity(Base):
    __tablename__ = "activities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    activity_type_id: Mapped[int | None] = mapped_column(ForeignKey("activity_types.id"), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_testing: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    activity_type: Mapped["ActivityType | None"] = relationship("ActivityType")
    created_by: Mapped["User"] = relationship("User", foreign_keys="Activity.created_by_id")
    serials: Mapped[list["Serial"]] = relationship("Serial", back_populates="activity", foreign_keys="Serial.activity_id")

    @property
    def started_at(self):
        dates = [s.opened_at for s in self.serials if s.opened_at and s.is_started]
        return min(dates) if dates else None

    @property
    def closed_at(self):
        all_closed = all(s.closed_at is not None for s in self.serials if s.is_started)
        if not self.serials or not all_closed:
            return None
        dates = [s.closed_at for s in self.serials if s.closed_at]
        return max(dates) if dates else None

    @property
    def status(self) -> str:
        started = [s for s in self.serials if s.is_started]
        if not started:
            return "Planned"
        if any(s.closed_at is None for s in started):
            return "Active"
        return "Completed"


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
    cbm_sync_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    cbm_username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cbm_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    cbm_last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cbm_last_sync_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cbm_last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # SNMP read-only monitoring (splitter/combiner/switch matrices, e.g. ETL Genus).
    # Secrets are encrypted at rest via app.crypto (Fernet from SECRET_KEY).
    snmp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    snmp_version: Mapped[str] = mapped_column(String(4), default="2c")   # '2c' | '3'
    snmp_port: Mapped[int] = mapped_column(Integer, default=161)
    snmp_community_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    snmp_v3_user: Mapped[str | None] = mapped_column(String(128), nullable=True)
    snmp_v3_auth_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    snmp_v3_priv_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    snmp_last_poll_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    snmp_last_poll_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    snmp_last_poll_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    snmp_system_alarm: Mapped[str | None] = mapped_column(String(16), nullable=True)  # effective: ok|warning|fault
    # Module indices (CSV) whose fault is acknowledged/ignored (e.g. an empty PSU slot),
    # and a JSON cache of the last-polled module table for the health panel + mute UI.
    snmp_ignored_modules: Mapped[str | None] = mapped_column(Text, nullable=True)
    snmp_modules_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON cache of the last-polled EBEM sync LED states (for dashboard display).
    # Format: {"ebem_sync": true|false|null, "carrier_lock": true|false|null, "bit_sync": true|false|null}
    cbm_sync_state_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    num_inputs: Mapped[int] = mapped_column(Integer, default=16)
    num_outputs: Mapped[int] = mapped_column(Integer, default=16)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_testing: Mapped[bool] = mapped_column(Boolean, default=False)
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
    routed_from: Mapped[int | None] = mapped_column(Integer, nullable=True)  # planned input idx feeding an output
    # SNMP-observed (live) routing, kept separate from the manually-entered plan so the
    # routing page can show planned-vs-actual and highlight mismatches.
    # None = no observed route; 0 = explicitly terminated by the matrix.
    observed_routed_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observed_label: Mapped[str | None] = mapped_column(String(128), nullable=True)

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
    is_testing: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    from_device: Mapped["RFDevice"] = relationship("RFDevice", foreign_keys=[from_device_id])
    to_device: Mapped["RFDevice"] = relationship("RFDevice", foreign_keys=[to_device_id])


# ── CDA (Controlled Data Area) Windows ───────────────────────────────────────

class CDATable(Base):
    """A named schedule of CDA time windows (daily, Zulu). Can be assigned to many serials."""
    __tablename__ = "cda_tables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    is_testing: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    created_by: Mapped["User"] = relationship("User", foreign_keys=[created_by_id])
    windows: Mapped[list["CDAWindow"]] = relationship(
        "CDAWindow", back_populates="cda_table",
        cascade="all, delete-orphan",
        order_by="CDAWindow.start_zulu",
    )
    serial_links: Mapped[list["SerialCDATable"]] = relationship("SerialCDATable", back_populates="cda_table")


class CDAWindow(Base):
    """A single time window within a CDA table.

    start_zulu / end_zulu are stored as 'HH:MM' strings (always Zulu).
    max_power_dbm == None  → no-fire window (transmit prohibited).
    max_power_dbm == value → reduced-power window (max transmit power limit).
    """
    __tablename__ = "cda_windows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cda_table_id: Mapped[int] = mapped_column(ForeignKey("cda_tables.id"), nullable=False, index=True)
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    start_zulu: Mapped[str] = mapped_column(String(5), nullable=False)   # 'HH:MM'
    end_zulu: Mapped[str] = mapped_column(String(5), nullable=False)     # 'HH:MM'
    max_power_dbm: Mapped[float | None] = mapped_column(Float, nullable=True)

    cda_table: Mapped["CDATable"] = relationship("CDATable", back_populates="windows")

    @property
    def window_type(self) -> str:
        return "reduced_power" if self.max_power_dbm is not None else "no_fire"

    @property
    def window_type_label(self) -> str:
        if self.max_power_dbm is not None:
            return f"Reduced Power (max {self.max_power_dbm:.1f} dBm)"
        return "No Fire"


class SerialCDATable(Base):
    """Junction: a CDA table assigned to a serial."""
    __tablename__ = "serial_cda_tables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    serial_id: Mapped[int] = mapped_column(ForeignKey("serials.id"), nullable=False, index=True)
    cda_table_id: Mapped[int] = mapped_column(ForeignKey("cda_tables.id"), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    serial: Mapped["Serial"] = relationship("Serial", back_populates="cda_links")
    cda_table: Mapped["CDATable"] = relationship("CDATable", back_populates="serial_links")


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
    is_testing: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    approval_status: Mapped[str] = mapped_column(String(16), default="approved")  # approved|pending|rejected
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    reported_by: Mapped["User"] = relationship("User", foreign_keys="Incident.reported_by_id")
    approved_by: Mapped["User | None"] = relationship("User", foreign_keys="Incident.approved_by_id")
    resolved_by: Mapped["User | None"] = relationship("User", foreign_keys="Incident.resolved_by_id")


class CeaseEvent(Base):
    """A range-wide CEASE alert.

    Any logged-in user (including a read-only Observer) may raise one,
    and must supply a reason. It splashes a full-screen CEASE over every user's
    screen until any user dismisses it. Both actions are audit-logged. The
    currently active cease is the most recent row with dismissed_at IS NULL.
    """
    __tablename__ = "cease_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    raised_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    is_testing: Mapped[bool] = mapped_column(Boolean, default=False)
    raised_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    dismissed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    raised_by: Mapped["User"] = relationship("User", foreign_keys=[raised_by_id])
    dismissed_by: Mapped["User | None"] = relationship("User", foreign_keys=[dismissed_by_id])

    @property
    def is_active(self) -> bool:
        return self.dismissed_at is None


class RoutingPreset(Base):
    """Desired routing configuration for a splitter/combiner matrix at a given range state.

    routes_json stores the target routing as a JSON dict keyed by the primary port index
    (str) → the port it routes from/to (int).
      - Splitters (output_to_input): key = output port idx, value = input port idx to route from.
      - Combiners  (input_to_output): key = input port idx, value = output port idx to route to.
    Only ports that should have a specific route need to be listed; unspecified ports are ignored
    in the comparison. This lets admins define a partial preset (e.g. "only these outputs must
    route from these inputs") without specifying every port.
    """
    __tablename__ = "routing_presets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("rf_devices.id"), nullable=False, index=True)
    range_state: Mapped[str] = mapped_column(String(32), nullable=False)  # "Live", "Closed Loop", etc.
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    routes_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    device: Mapped["RFDevice"] = relationship("RFDevice")
    created_by: Mapped["User"] = relationship("User", foreign_keys=[created_by_id])


def _session_testing_state(session: SASession) -> bool:
    for obj in session.new:
        if isinstance(obj, RangeStateLog) and (
            obj.new_state == RangeState.TESTING.value
            or obj.previous_state == RangeState.TESTING.value
        ):
            return True
    latest = session.query(RangeStateLog).order_by(RangeStateLog.id.desc()).first()
    return bool(latest and latest.new_state == RangeState.TESTING.value)


@event.listens_for(SASession, "before_flush")
def _mark_testing_scoped_rows(session: SASession, flush_context, instances) -> None:
    scoped_models = (
        SignalPackage, Serial, SignalLog, AuditLog, RFDevice, DeviceLink,
        CDATable, Incident, CeaseEvent, Activity,
    )
    new_scoped = [obj for obj in session.new if isinstance(obj, scoped_models)]
    if not new_scoped:
        return
    testing = _session_testing_state(session)
    for obj in new_scoped:
        if getattr(obj, "_preserve_testing_scope", False):
            continue
        obj.is_testing = testing


@event.listens_for(SASession, "before_flush")
def _sign_new_audit_rows(session: SASession, flush_context, instances) -> None:
    new_audits = [obj for obj in session.new if isinstance(obj, AuditLog) and not obj.record_hash]
    if not new_audits:
        return

    from app.audit_integrity import sign_audit_row

    latest_hash_by_scope: dict[bool, str | None] = {}
    for audit in new_audits:
        if audit.timestamp is None:
            audit.timestamp = datetime.utcnow()
        scope = bool(audit.is_testing)
        if scope not in latest_hash_by_scope:
            latest = (
                session.query(AuditLog)
                .filter(AuditLog.is_testing == scope, AuditLog.record_hash.isnot(None))
                .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
                .first()
            )
            latest_hash_by_scope[scope] = latest.record_hash if latest else None
        sign_audit_row(audit, latest_hash_by_scope[scope])
        latest_hash_by_scope[scope] = audit.record_hash
