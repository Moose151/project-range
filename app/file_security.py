"""Filesystem permission helpers for SQLite data and server-side archives."""

from __future__ import annotations

import stat
from pathlib import Path


def sqlite_path_from_url(database_url: str) -> Path | None:
    if not database_url.startswith("sqlite:///"):
        return None
    return Path(database_url.removeprefix("sqlite:///"))


def mode_string(path: Path) -> str:
    return stat.filemode(path.stat().st_mode)


def permission_status(path: Path, *, directory: bool = False) -> dict:
    if not path.exists():
        return {"exists": False, "secure": False, "mode": "missing", "note": "Path does not exist."}
    mode = stat.S_IMODE(path.stat().st_mode)
    allowed = 0o700 if directory else 0o600
    too_open = bool(mode & ~allowed)
    return {
        "exists": True,
        "secure": not too_open,
        "mode": mode_string(path),
        "note": "Owner-only permissions." if not too_open else "Group/other permissions are present.",
    }


def harden_path(path: Path, *, directory: bool = False) -> str | None:
    """Best-effort chmod to owner-only permissions.

    Returns an error string when chmod fails; otherwise None.
    """
    if not path.exists():
        return None
    try:
        path.chmod(0o700 if directory else 0o600)
    except OSError as exc:
        return str(exc)
    return None


def harden_sqlite_storage(database_url: str, archive_dirs: list[Path] | None = None) -> list[str]:
    errors: list[str] = []
    db_path = sqlite_path_from_url(database_url)
    if db_path:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        err = harden_path(db_path)
        if err:
            errors.append(f"{db_path}: {err}")
    for directory in archive_dirs or []:
        directory.mkdir(parents=True, exist_ok=True)
        err = harden_path(directory, directory=True)
        if err:
            errors.append(f"{directory}: {err}")
    return errors
