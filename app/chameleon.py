"""Shared naming for "chameleon" signals — duplicates that track a changed
parameter while keeping the original, named with an incrementing ``-N`` suffix.

The next name in a family continues across **both** the Signal registry and
Signal *package* entries, so planned chameleons added to a package (e.g. 201-2,
201-3) are counted when the dashboard later spawns another (→ 201-4).
"""

import re
from typing import Iterable


def chameleon_base_name(signal_name: str) -> str:
    """Strip a trailing ``-N`` suffix to find the family base name."""
    m = re.match(r"^(.*)-(\d+)$", signal_name)
    return m.group(1) if m else signal_name


def next_chameleon_name(signal_name: str, existing_names: Iterable[str]) -> str:
    """Next free ``{base}-{N+1}`` for the family, counting only ``existing_names``.

    Scope is the caller's responsibility (e.g. a single package's signals, or the
    signals in one serial) so the count reflects *that* context rather than every
    similarly-named signal in the database.
    """
    base = chameleon_base_name(signal_name)
    pattern = re.compile(r"^" + re.escape(base) + r"(?:-(\d+))?$")
    max_n = 0
    for name in existing_names:
        m = pattern.match(name or "")
        if m:
            n = int(m.group(1)) if m.group(1) else 0
            max_n = max(max_n, n)
    return f"{base}-{max_n + 1}"
