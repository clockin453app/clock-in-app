"""Onboarding helpers."""

from __future__ import annotations


def normalize_checkbox(value) -> str:
    return "yes" if str(value or "").strip().lower() in {"1", "true", "yes", "on"} else ""


def _core():
    import workhours_app.core as core
    return core


def update_or_append_onboarding(*args, **kwargs):
    return _core().update_or_append_onboarding(*args, **kwargs)


def get_onboarding_record(*args, **kwargs):
    return _core().get_onboarding_record(*args, **kwargs)


def _render_onboarding_page(*args, **kwargs):
    return _core()._render_onboarding_page(*args, **kwargs)


def onboarding_details_block(*args, **kwargs):
    return _core().onboarding_details_block(*args, **kwargs)


__all__ = [
    "_render_onboarding_page",
    "get_onboarding_record",
    "normalize_checkbox",
    "onboarding_details_block",
    "update_or_append_onboarding",
]
