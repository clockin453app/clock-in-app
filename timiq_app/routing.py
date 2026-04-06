from __future__ import annotations

from collections.abc import Callable
from typing import Any


class DeferredRouteRegistry:
    """Collect route declarations before a Flask app exists, then register them later."""

    def __init__(self) -> None:
        self._registrations: list[tuple[str, str, Callable[..., Any], dict[str, Any]]] = []

    def route(self, rule: str, **options: Any):
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self._registrations.append((rule, func.__name__, func, dict(options)))
            return func
        return decorator

    def get(self, rule: str, **options: Any):
        methods = list(options.pop("methods", [])) or ["GET"]
        return self.route(rule, methods=methods, **options)

    def post(self, rule: str, **options: Any):
        methods = list(options.pop("methods", [])) or ["POST"]
        return self.route(rule, methods=methods, **options)

    def register(self, app) -> None:
        for rule, endpoint, func, options in self._registrations:
            app.add_url_rule(rule, endpoint=endpoint, view_func=func, **options)
