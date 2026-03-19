"""Route registration helpers."""

from __future__ import annotations


def register_routes() -> None:
    """Import route modules for registration side effects."""
    from workhours_app.routes import admin_routes as _admin_routes  # noqa: F401
    from workhours_app.routes import debug_routes as _debug_routes  # noqa: F401
    from workhours_app.routes import public_routes as _public_routes  # noqa: F401


__all__ = ["register_routes"]
