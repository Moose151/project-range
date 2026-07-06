"""Shared upload validation helpers.

Uploads in this app are small operator config files, not arbitrary storage.
Keeping limits central makes the import routes easier to audit.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from app.config import MAX_UPLOAD_BYTES, MAX_UPLOAD_TOTAL_BYTES, MAX_UPLOAD_ZIP_MEMBERS


def clean_upload_name(filename: str | None) -> str:
    name = PurePosixPath((filename or "").replace("\\", "/")).name.strip()
    if not name or name in {".", ".."}:
        raise ValueError("Uploaded file must have a valid filename.")
    return name


def extension_allowed(filename: str, allowed: set[str]) -> bool:
    suffix = PurePosixPath(filename).suffix.lower().lstrip(".")
    return suffix in allowed


def validate_upload_file(
    filename: str | None,
    content: bytes,
    *,
    allowed_extensions: set[str],
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> str:
    name = clean_upload_name(filename)
    if not extension_allowed(name, allowed_extensions):
        allowed = ", ".join(f".{ext}" for ext in sorted(allowed_extensions))
        raise ValueError(f"{name} is not an allowed upload type. Use {allowed}.")
    if len(content) > max_bytes:
        raise ValueError(f"{name} is too large. Maximum size is {max_bytes // 1024} KB.")
    return name


def validate_total_upload_size(total_bytes: int, *, max_bytes: int = MAX_UPLOAD_TOTAL_BYTES) -> None:
    if total_bytes > max_bytes:
        raise ValueError(f"Upload is too large. Maximum combined size is {max_bytes // 1024} KB.")


def validate_zip_member_count(count: int) -> None:
    if count > MAX_UPLOAD_ZIP_MEMBERS:
        raise ValueError(f"Zip contains too many files. Maximum is {MAX_UPLOAD_ZIP_MEMBERS}.")
