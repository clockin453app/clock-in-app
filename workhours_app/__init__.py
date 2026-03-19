"""Application package entrypoint."""

from workhours_app.core import app as _app, initialize_runtime
from workhours_app.routes import register_routes

_BOOTSTRAPPED = False


def bootstrap_app():
    """Register routes and runtime adapters exactly once."""
    global _BOOTSTRAPPED
    if not _BOOTSTRAPPED:
        register_routes()
        initialize_runtime()
        _BOOTSTRAPPED = True
    return _app


def create_app():
    return bootstrap_app()


app = bootstrap_app()

__all__ = ["app", "bootstrap_app", "create_app"]
