"""Standalone checks for upload validation guardrails.

Run: venv/bin/python tests/test_upload_validation.py
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.routers.packages import _uploaded_signal_files, _validated_json_package  # noqa: E402
from app.upload_validation import validate_upload_file  # noqa: E402


class UploadStub:
    def __init__(self, filename: str, content: bytes):
        self.filename = filename
        self._content = content

    async def read(self) -> bytes:
        return self._content


class FormStub:
    def __init__(self, uploads: list[UploadStub]):
        self._uploads = uploads

    def multi_items(self):
        return [(f"files_{i}", upload) for i, upload in enumerate(self._uploads)]


class RequestStub:
    def __init__(self, uploads: list[UploadStub]):
        self._uploads = uploads

    async def form(self):
        return FormStub(self._uploads)


def test_rejects_unexpected_extension():
    try:
        validate_upload_file("payload.exe", b"x", allowed_extensions={"txt"})
    except ValueError as exc:
        assert "not an allowed upload type" in str(exc)
    else:
        raise AssertionError("unexpected extension was accepted")


def test_package_upload_rejects_unexpected_extension():
    request = RequestStub([UploadStub("payload.exe", b"x")])
    try:
        asyncio.run(_uploaded_signal_files(request))
    except ValueError as exc:
        assert "not an allowed upload type" in str(exc)
    else:
        raise AssertionError("unexpected package upload was accepted")


def test_package_zip_filters_to_cbm_text_members():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("signal_one.txt", "CFG_NAME=Signal One\n")
        zf.writestr("ignored.bin", b"\x00\x01")

    request = RequestStub([UploadStub("configs.zip", buf.getvalue())])
    files = asyncio.run(_uploaded_signal_files(request))

    assert files == [("signal_one.txt", b"CFG_NAME=Signal One\n")]


def test_json_package_shape_is_validated():
    valid = _validated_json_package(json.dumps({"signals": [{"name": "A"}]}).encode())
    assert valid["signals"][0]["name"] == "A"

    try:
        _validated_json_package(json.dumps({"signals": ["bad"]}).encode())
    except ValueError as exc:
        assert "must be an object" in str(exc)
    else:
        raise AssertionError("malformed JSON package was accepted")


if __name__ == "__main__":
    tests = [
        test_rejects_unexpected_extension,
        test_package_upload_rejects_unexpected_extension,
        test_package_zip_filters_to_cbm_text_members,
        test_json_package_shape_is_validated,
    ]
    for test in tests:
        test()
    print(f"\n{len(tests)} upload validation tests passed.")
