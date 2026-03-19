"""Clocking and attendance helpers."""

from __future__ import annotations


def apply_unpaid_break(hours_value: float, break_hours: float = 0.5, threshold_hours: float = 6.0) -> float:
    hours_value = float(hours_value or 0.0)
    if hours_value >= threshold_hours:
        return max(0.0, hours_value - break_hours)
    return hours_value


def _core():
    import workhours_app.core as core

    return core


def normalized_clock_in_time(now_dt, early_access: bool):
    return _core().normalized_clock_in_time(now_dt, early_access)


def has_any_row_today(rows, username):
    return _core().has_any_row_today(rows, username)


def find_open_shift(rows, username):
    return _core().find_open_shift(rows, username)


def _apply_unpaid_break(hours_value):
    return _core()._apply_unpaid_break(hours_value)


def _sanitize_clock_geo(*args, **kwargs):
    return _core()._sanitize_clock_geo(*args, **kwargs)


def _validate_recent_clock_capture(*args, **kwargs):
    return _core()._validate_recent_clock_capture(*args, **kwargs)


def _validate_user_location(*args, **kwargs):
    return _core()._validate_user_location(*args, **kwargs)


def _store_clock_selfie(*args, **kwargs):
    return _core()._store_clock_selfie(*args, **kwargs)


def _db_workhour_metrics(*args, **kwargs):
    return _core()._db_workhour_metrics(*args, **kwargs)


__all__ = [
    "_apply_unpaid_break",
    "_db_workhour_metrics",
    "_sanitize_clock_geo",
    "_store_clock_selfie",
    "_validate_recent_clock_capture",
    "_validate_user_location",
    "apply_unpaid_break",
    "find_open_shift",
    "has_any_row_today",
    "normalized_clock_in_time",
]
