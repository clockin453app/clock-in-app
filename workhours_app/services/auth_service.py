"""Authentication helpers."""

from __future__ import annotations

from flask import abort, request, session


def get_csrf() -> str:
    token = session.get("csrf")
    if not token:
        import secrets

        token = secrets.token_urlsafe(24)
        session["csrf"] = token
    return token


def require_csrf() -> None:
    sent = (request.form.get("csrf") or request.headers.get("X-CSRF-Token") or "").strip()
    expected = (session.get("csrf") or "").strip()
    if not sent or not expected or sent != expected:
        abort(400)


# Legacy-compatible lazy imports for the rest.
def _core():
    import workhours_app.core as core

    return core


def _issue_active_session_token(username: str, workplace_id: str = "default"):
    return _core()._issue_active_session_token(username, workplace_id)


def _clear_active_session_token(username: str, workplace_id: str = "default"):
    return _core()._clear_active_session_token(username, workplace_id)


def _validate_active_session(username: str, workplace_id: str = "default", token: str = ""):
    return _core()._validate_active_session(username, workplace_id, token)


def is_password_valid(stored_password: str, candidate_password: str) -> bool:
    return _core().is_password_valid(stored_password, candidate_password)


def migrate_password_if_plain(username: str, stored_password: str, candidate_password: str, workplace_id: str = "default"):
    return _core().migrate_password_if_plain(username, stored_password, candidate_password, workplace_id=workplace_id)


def update_employee_password(username: str, new_password: str, workplace_id: str = "default"):
    return _core().update_employee_password(username, new_password, workplace_id=workplace_id)


def _login_rate_limit_check(ip: str):
    return _core()._login_rate_limit_check(ip)


def _login_rate_limit_hit(ip: str):
    return _core()._login_rate_limit_hit(ip)


def _login_rate_limit_clear(ip: str):
    return _core()._login_rate_limit_clear(ip)


__all__ = [
    "_clear_active_session_token",
    "_issue_active_session_token",
    "_login_rate_limit_check",
    "_login_rate_limit_clear",
    "_login_rate_limit_hit",
    "_validate_active_session",
    "get_csrf",
    "is_password_valid",
    "migrate_password_if_plain",
    "require_csrf",
    "update_employee_password",
]
