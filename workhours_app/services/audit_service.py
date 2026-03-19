"""Audit helpers."""

from __future__ import annotations

from datetime import datetime


def audit_timestamp(now: datetime | None = None) -> str:
    return (now or datetime.utcnow()).strftime("%Y-%m-%d %H:%M:%S")


def _core():
    import workhours_app.core as core
    return core


def log_audit(*args, **kwargs):
    return _core().log_audit(*args, **kwargs)


def _ensure_audit_headers(*args, **kwargs):
    return _core()._ensure_audit_headers(*args, **kwargs)


def _legacy_log_audit_before_db_patch(*args, **kwargs):
    return _core()._legacy_log_audit_before_db_patch(*args, **kwargs)


__all__ = [
    "_ensure_audit_headers",
    "_legacy_log_audit_before_db_patch",
    "audit_timestamp",
    "log_audit",
]
