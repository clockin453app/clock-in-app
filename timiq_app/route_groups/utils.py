from __future__ import annotations

from collections.abc import Iterable


def add_route(app, rule: str, view_func, methods: Iterable[str] | None = None) -> None:
    options = {"endpoint": view_func.__name__, "view_func": view_func}
    if methods is not None:
        options["methods"] = list(methods)
    app.add_url_rule(rule, **options)
