"""Shared page metadata for consistent TimIQ page headers."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BreadcrumbItem:
    label: str
    href: str | None = None


@dataclass(frozen=True)
class PageMeta:
    title: str
    subtitle: str = ""
    breadcrumbs: tuple[BreadcrumbItem, ...] = field(default_factory=tuple)
    active: str = "dashboard"


PAGE_META: dict[str, PageMeta] = {
    "dashboard": PageMeta(
        title="Dashboard",
        subtitle="Get a real-time overview of your workforce and operations.",
        breadcrumbs=(BreadcrumbItem("Dashboard"),),
        active="dashboard",
    ),
    "management": PageMeta(
        title="Management",
        subtitle="Configure organization settings, manage people, and oversee workplace operations.",
        breadcrumbs=(BreadcrumbItem("Dashboard", "/"), BreadcrumbItem("Management")),
        active="management",
    ),
    "payroll": PageMeta(
        title="Payroll Report",
        subtitle="Review weekly payroll, analyze costs, and export reports with ease.",
        breadcrumbs=(BreadcrumbItem("Dashboard", "/"), BreadcrumbItem("Management", "/admin"), BreadcrumbItem("Payroll Report")),
        active="management",
    ),
    "attendance": PageMeta(
        title="Attendance",
        subtitle="Track clock-ins, shifts, and attendance performance.",
        breadcrumbs=(BreadcrumbItem("Dashboard", "/"), BreadcrumbItem("Attendance")),
        active="current-sessions",
    ),
    "time_records": PageMeta(
        title="Time Records",
        subtitle="Review your clock-in and clock-out history.",
        breadcrumbs=(BreadcrumbItem("Dashboard", "/"), BreadcrumbItem("Time Records")),
        active="time",
    ),
    "timesheets": PageMeta(
        title="Timesheets",
        subtitle="Review weekly reports and timesheet summaries.",
        breadcrumbs=(BreadcrumbItem("Dashboard", "/"), BreadcrumbItem("Timesheets")),
        active="timesheets",
    ),
    "payments": PageMeta(
        title="Pay History",
        subtitle="Review payroll payments and previous pay periods.",
        breadcrumbs=(BreadcrumbItem("Dashboard", "/"), BreadcrumbItem("Pay History")),
        active="payments",
    ),
    "site_progress": PageMeta(
        title="Site Progress",
        subtitle="Track workplace progress, uploads, and site notes.",
        breadcrumbs=(BreadcrumbItem("Dashboard", "/"), BreadcrumbItem("Site Progress")),
        active="work_progress",
    ),
}


def get_page_meta(key: str | None, fallback_title: str = "") -> PageMeta:
    normalized_key = str(key or "").strip().lower()
    if normalized_key in PAGE_META:
        return PAGE_META[normalized_key]

    title = fallback_title or normalized_key.replace("_", " ").title() or "TimIQ"
    return PageMeta(
        title=title,
        breadcrumbs=(BreadcrumbItem("Dashboard", "/"), BreadcrumbItem(title)),
        active=normalized_key or "dashboard",
    )
