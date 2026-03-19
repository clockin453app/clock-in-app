"""Payroll domain helpers.

These helpers are intentionally importable without pulling in the entire route
layer, which makes them testable and reusable from routes and admin actions.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta


def safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def money(value) -> str:
    return f"{safe_float(value, 0.0):.2f}"


def fmt_hours(value) -> str:
    return f"{safe_float(value, 0.0):.2f}"


def get_week_range(target: date | datetime | None = None) -> tuple[date, date]:
    current = target.date() if isinstance(target, datetime) else (target or date.today())
    week_start = current - timedelta(days=current.weekday())
    week_end = week_start + timedelta(days=6)
    return week_start, week_end


# Legacy-compatible lazy imports for existing route helpers.
def _core():
    import workhours_app.core as core

    return core


def _is_paid_for_week(week_start: str, week_end: str, username: str):
    return _core()._is_paid_for_week(week_start, week_end, username)


def _append_paid_record_safe(week_start: str, week_end: str, username: str, gross: float, tax: float, net: float, paid_by: str):
    return _core()._append_paid_record_safe(week_start, week_end, username, gross, tax, net, paid_by)


def _get_user_rate(username: str):
    return _core()._get_user_rate(username)


__all__ = [
    "_append_paid_record_safe",
    "_get_user_rate",
    "_is_paid_for_week",
    "fmt_hours",
    "get_week_range",
    "money",
    "safe_float",
]
