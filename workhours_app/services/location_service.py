"""Location and geofence helpers."""

from __future__ import annotations

import math


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1 = math.radians(float(lat1))
    p2 = math.radians(float(lat2))
    dp = math.radians(float(lat2) - float(lat1))
    dl = math.radians(float(lon2) - float(lon1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _core():
    import workhours_app.core as core
    return core


def get_locations():
    return _core().get_locations()


def _get_employee_sites(*args, **kwargs):
    return _core()._get_employee_sites(*args, **kwargs)


def _get_employee_site(*args, **kwargs):
    return _core()._get_employee_site(*args, **kwargs)


def _get_active_locations(*args, **kwargs):
    return _core()._get_active_locations(*args, **kwargs)


def _get_site_config(*args, **kwargs):
    return _core()._get_site_config(*args, **kwargs)


def _haversine_m(*args, **kwargs):
    return _core()._haversine_m(*args, **kwargs)


__all__ = [
    "_get_active_locations",
    "_get_employee_site",
    "_get_employee_sites",
    "_get_site_config",
    "_haversine_m",
    "get_locations",
    "haversine_m",
]
