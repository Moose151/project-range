"""Standalone checks for login session hardening.

Run: venv/bin/python tests/test_session_hardening.py
"""

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.auth import session_is_expired, start_authenticated_session  # noqa: E402
from app.config import SESSION_MAX_AGE_DAYS  # noqa: E402
from app.models import Role  # noqa: E402


class UserStub:
    id = 7
    username = "operator"
    display_name = "Operator"
    role = Role.OPERATOR


def test_start_authenticated_session_clears_existing_state():
    session = {"user_id": 99, "csrf": "old", "anonymous_pref": "stale"}

    start_authenticated_session(session, UserStub(), "token-123", remember=True)

    assert session["user_id"] == 7
    assert session["username"] == "operator"
    assert session["display_name"] == "Operator"
    assert session["role"] == "user"
    assert session["remember"] is True
    assert session["session_token"] == "token-123"
    assert "session_issued_at" in session
    assert "csrf" not in session
    assert "anonymous_pref" not in session


def test_session_expiry_handles_bad_and_old_timestamps():
    assert session_is_expired({"logged_in_at": "not-a-date"}) is True
    old = datetime.utcnow() - timedelta(days=SESSION_MAX_AGE_DAYS + 1)
    assert session_is_expired({
        "logged_in_at": datetime.utcnow().isoformat(),
        "session_issued_at": old.isoformat(),
        "remember": True,
    }) is True


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} session hardening tests passed.")


if __name__ == "__main__":
    main()
