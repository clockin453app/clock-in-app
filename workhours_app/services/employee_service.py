"""Employee-domain helpers."""

from __future__ import annotations


def split_name(full_name: str) -> tuple[str, str]:
    parts = [p for p in str(full_name or "").strip().split() if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _core():
    import workhours_app.core as core
    return core


def _find_employee_record(*args, **kwargs):
    return _core()._find_employee_record(*args, **kwargs)


def _list_employee_records_for_workplace(*args, **kwargs):
    return _core()._list_employee_records_for_workplace(*args, **kwargs)


def get_employee_display_name(*args, **kwargs):
    return _core().get_employee_display_name(*args, **kwargs)


def set_employee_field(*args, **kwargs):
    return _core().set_employee_field(*args, **kwargs)


def set_employee_first_last(*args, **kwargs):
    return _core().set_employee_first_last(*args, **kwargs)


def _sanitize_requested_role(*args, **kwargs):
    return _core()._sanitize_requested_role(*args, **kwargs)


def _allowed_assignable_roles_for_actor(*args, **kwargs):
    return _core()._allowed_assignable_roles_for_actor(*args, **kwargs)


__all__ = [
    "_allowed_assignable_roles_for_actor",
    "_find_employee_record",
    "_list_employee_records_for_workplace",
    "_sanitize_requested_role",
    "get_employee_display_name",
    "set_employee_field",
    "set_employee_first_last",
    "split_name",
]
