"""Small helpers for encrypting device integration secrets at rest."""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import SECRET_KEY


def _fernet() -> Fernet:
    digest = hashlib.sha256(SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        return None


# ── Documentation content at rest ────────────────────────────────────────────
# Admin-only doc pages (visibility == "admins") have their body encrypted in the
# database so it is not stored in plain text. A marker prefix lets us tell an
# encrypted body from a plain one, so decrypt is a safe no-op on legacy/plain
# content and the two states can coexist. NOTE: relies on a stable SECRET_KEY
# (same caveat as modem passwords); encrypted bodies are not full-text-searchable.
DOC_ENC_PREFIX = "enc:fernet:v1:"


def encrypt_doc_content(content: str | None, visibility: str | None) -> str | None:
    """Encrypt a doc body iff the page is admin-only; otherwise store as-is."""
    if visibility == "admins" and content:
        token = encrypt_secret(content)
        if token:
            return DOC_ENC_PREFIX + token
    return content


def decrypt_doc_content(stored: str | None) -> str | None:
    """Return the plaintext body. No-op when the stored value isn't encrypted."""
    if isinstance(stored, str) and stored.startswith(DOC_ENC_PREFIX):
        return decrypt_secret(stored[len(DOC_ENC_PREFIX):]) or ""
    return stored
