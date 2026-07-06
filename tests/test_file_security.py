"""Standalone checks for SQLite/archive file permission helpers.

Run: venv/bin/python tests/test_file_security.py
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.file_security import (  # noqa: E402
    harden_sqlite_storage,
    permission_status,
    sqlite_path_from_url,
)


def test_sqlite_path_from_url():
    assert sqlite_path_from_url("sqlite:////app/data/range.db") == Path("/app/data/range.db")
    assert sqlite_path_from_url("postgresql://example") is None


def test_harden_sqlite_storage_sets_owner_only_modes():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        db = base / "range.db"
        db.write_text("db")
        db.chmod(0o666)
        archive = base / "audit_archives"

        errors = harden_sqlite_storage(f"sqlite:///{db}", [archive])

        assert errors == []
        assert permission_status(db)["secure"] is True
        assert permission_status(archive, directory=True)["secure"] is True


def test_permission_status_flags_open_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "open.db"
        path.write_text("db")
        path.chmod(0o644)

        status = permission_status(path)

        assert status["exists"] is True
        assert status["secure"] is False
        assert "Group/other" in status["note"]


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} file security tests passed.")


if __name__ == "__main__":
    main()
