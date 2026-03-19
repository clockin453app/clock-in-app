"""Workplace-scoped helpers."""

from __future__ import annotations

from flask import session


def session_workplace_id() -> str:
    return (session.get("workplace_id") or "default").strip() or "default"


def _core():
    import workhours_app.core as core
    return core


def get_company_settings():
    return _core().get_company_settings()


def _session_workplace_id():
    return _core()._session_workplace_id()


def _row_workplace_id(*args, **kwargs):
    return _core()._row_workplace_id(*args, **kwargs)


def _same_workplace(*args, **kwargs):
    return _core()._same_workplace(*args, **kwargs)


def _employees_usernames_for_workplace(*args, **kwargs):
    return _core()._employees_usernames_for_workplace(*args, **kwargs)


def user_in_same_workplace(*args, **kwargs):
    return _core().user_in_same_workplace(*args, **kwargs)


__all__ = [
    "_employees_usernames_for_workplace",
    "_row_workplace_id",
    "_same_workplace",
    "_session_workplace_id",
    "get_company_settings",
    "session_workplace_id",
    "user_in_same_workplace",
]
