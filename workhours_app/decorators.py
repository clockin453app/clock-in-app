"""Access-control decorators and guards."""

from workhours_app.core import (
    require_login,
    require_admin,
    require_master_admin,
    require_sensitive_tools_admin,
    require_destructive_admin_post,
)

__all__ = [
    "require_login",
    "require_admin",
    "require_master_admin",
    "require_sensitive_tools_admin",
    "require_destructive_admin_post",
]
