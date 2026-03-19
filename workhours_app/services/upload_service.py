"""Upload helpers."""

from __future__ import annotations

from werkzeug.utils import secure_filename


def safe_upload_name(filename: str) -> str:
    return secure_filename(filename or "upload") or "upload"


def _core():
    import workhours_app.core as core
    return core


def _detect_upload_kind(*args, **kwargs):
    return _core()._detect_upload_kind(*args, **kwargs)


def _validate_upload_file(*args, **kwargs):
    return _core()._validate_upload_file(*args, **kwargs)


def upload_to_drive(*args, **kwargs):
    return _core().upload_to_drive(*args, **kwargs)


def _upload_bytes_to_drive(*args, **kwargs):
    return _core()._upload_bytes_to_drive(*args, **kwargs)


__all__ = [
    "_detect_upload_kind",
    "_upload_bytes_to_drive",
    "_validate_upload_file",
    "safe_upload_name",
    "upload_to_drive",
]
