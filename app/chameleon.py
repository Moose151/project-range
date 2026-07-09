"""Shared naming for "chameleon" signals — duplicates that track a changed
parameter while keeping the original, named with an incrementing ``-N`` suffix.

The next name in a family continues across **both** the Signal registry and
Signal *package* entries, so planned chameleons added to a package (e.g. 201-2,
201-3) are counted when the dashboard later spawns another (→ 201-4).
"""

import re

from sqlalchemy.orm import Session

from app.models import Signal, SignalPackageEntry


def chameleon_base_name(signal_name: str) -> str:
    """Strip a trailing ``-N`` suffix to find the family base name."""
    m = re.match(r"^(.*)-(\d+)$", signal_name)
    return m.group(1) if m else signal_name


def next_chameleon_name(db: Session, signal_name: str) -> str:
    """Return the next free ``{base}-{N+1}`` across registry + package entries."""
    base = chameleon_base_name(signal_name)
    pattern = re.compile(r"^" + re.escape(base) + r"(?:-(\d+))?$")
    names: set[str] = set()
    for (name,) in db.query(Signal.name).filter(Signal.name.like(f"{base}%")).all():
        names.add(name)
    for (name,) in db.query(SignalPackageEntry.signal_name).filter(
        SignalPackageEntry.signal_name.like(f"{base}%")
    ).all():
        names.add(name)
    max_n = 0
    for name in names:
        m = pattern.match(name)
        if m:
            n = int(m.group(1)) if m.group(1) else 0
            max_n = max(max_n, n)
    return f"{base}-{max_n + 1}"
