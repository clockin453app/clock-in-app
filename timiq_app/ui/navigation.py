"""Shared navigation definitions for TimIQ shell layouts.

This module has no Flask side effects. It only centralizes labels, URLs,
icons, and active keys used by the admin/employee shell.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    href: str
    icon_key: str
    roles: tuple[str, ...] = ("employee", "admin", "master_admin")


PRIMARY_NAV: tuple[NavItem, ...] = (
    NavItem("dashboard", "Dashboard", "/", "dashboard", ("employee", "admin", "master_admin")),
    NavItem("clock", "Clock In / Out", "/clock", "clock", ("employee", "admin", "master_admin")),
    NavItem("time", "Time Records", "/my-times", "timelogs", ("employee", "admin", "master_admin")),
    NavItem("timesheets", "Timesheets", "/my-reports", "timesheets", ("employee", "admin", "master_admin")),
    NavItem("payments", "Pay History", "/payments", "payments", ("employee", "admin", "master_admin")),
    NavItem("onboarding", "Starter Form", "/onboarding", "starter_form", ("employee", "admin", "master_admin")),
    NavItem("management", "Management", "/admin", "admin", ("admin", "master_admin")),
    NavItem("current-sessions", "Live Attendance", "/admin/current-sessions", "current_sessions", ("admin", "master_admin")),
    NavItem("work_progress", "Site Progress", "/work-progress", "work_progress", ("employee", "admin", "master_admin")),
    NavItem("profile", "Profile", "/password", "profile", ("employee", "admin", "master_admin")),
)


ADMIN_MANAGEMENT_NAV: tuple[NavItem, ...] = (
    NavItem("employees", "Employees", "/admin/employees", "employees", ("admin", "master_admin")),
    NavItem("companies", "Companies", "/admin/workplaces", "workplaces", ("master_admin",)),
    NavItem("locations", "Locations", "/admin/locations", "locations", ("admin", "master_admin")),
    NavItem("site_access", "Site Access", "/admin/employee-sites", "employee_sites", ("admin", "master_admin")),
    NavItem("payroll", "Payroll Report", "/admin/payroll", "payroll_report", ("admin", "master_admin")),
    NavItem("system_health", "System Health", "/admin/system-health", "admin", ("master_admin",)),
)


def visible_nav_items(role: str | None) -> list[NavItem]:
    normalized_role = str(role or "employee").strip().lower()
    return [item for item in PRIMARY_NAV if normalized_role in item.roles]
