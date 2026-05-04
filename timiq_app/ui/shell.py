"""Shared shell helpers for TimIQ.

This module contains the reusable shell/layout rendering code.  Step 2 keeps
existing page output stable by exposing legacy-compatible helpers that are
called from small wrappers in ``routes.py``.
"""

from __future__ import annotations

import html as html_lib
import re
from collections.abc import Callable, Mapping
from html import escape
from typing import Any

from flask import render_template

from .navigation import visible_nav_items
from .page_meta import PageMeta, get_page_meta


def initials_for_name(name: str | None, fallback: str = "AD") -> str:
    parts = [part for part in str(name or "").strip().split() if part]
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    if parts:
        return parts[0][:2].upper()
    return fallback


def normalize_role_label(role: str | None) -> str:
    return str(role or "employee").replace("_", " ").title()


def build_shell_context(
    *,
    active: str,
    role: str,
    display_name: str,
    username: str,
    page_meta: PageMeta | None = None,
    company_name: str = "TimIQ",
    content_html: str = "",
    shell_class: str = "",
) -> dict[str, Any]:
    meta = page_meta or get_page_meta(active)
    return {
        "active": active,
        "role": role,
        "role_label": normalize_role_label(role),
        "display_name": display_name or username or "admin",
        "username": username or "admin",
        "user_initials": initials_for_name(display_name or username),
        "company_name": company_name or "TimIQ",
        "nav_items": visible_nav_items(role),
        "page_meta": meta,
        "content_html": content_html,
        "shell_class": shell_class,
    }


def render_admin_shell(**context: Any) -> str:
    return render_template("layouts/admin_shell.html", **context)


# ---------------------------------------------------------------------------
# Legacy-compatible shell helpers
# ---------------------------------------------------------------------------
# These preserve the existing HTML output while moving shell responsibilities
# away from routes.py.  They intentionally accept dependencies from routes.py
# to avoid circular imports and to keep this migration low-risk.


def timiq_logo_html(extra_class: str = "") -> str:
    cls = f"timiqAppLogo {extra_class}".strip()
    return f"""
      <span class="{cls}" aria-label="TimIQ">
        <svg class="timiqAppLogoClock" viewBox="0 0 64 64" fill="none" aria-hidden="true">
          <path d="M7 25H26" stroke="#7FC7EE" stroke-width="5.5" stroke-linecap="round"/>
          <path d="M10 34H24" stroke="#7FC7EE" stroke-width="5.5" stroke-linecap="round"/>
          <path d="M16 43H22" stroke="#7FC7EE" stroke-width="5.5" stroke-linecap="round"/>

          <rect x="31" y="8" width="11" height="6" rx="2" fill="#7FC7EE"/>
          <rect x="47.5" y="14" width="6" height="6" rx="1.5" transform="rotate(45 47.5 14)" fill="#7FC7EE"/>

          <circle cx="36" cy="32" r="18" stroke="#7FC7EE" stroke-width="5.5"/>
          <path d="M36 32V18A14 14 0 0 1 50 32H36Z" fill="#4B83C6"/>
        </svg>

        <span class="timiqAppLogoWord">
          <span class="timiqAppLogoTim">Tim</span><span class="timiqAppLogoIQ">IQ</span>
        </span>
      </span>
    """


def legacy_sidebar_html(
    active: str,
    role: str,
    *,
    get_company_settings: Callable[[], Mapping[str, Any]],
    icon_dashboard: Callable[[int], str],
    icon_clock: Callable[[int], str],
    icon_timelogs: Callable[[int], str],
    icon_timesheets: Callable[[int], str],
    icon_payments: Callable[[int], str],
    icon_work_progress: Callable[[int], str],
    icon_admin: Callable[[int], str],
    icon_workplaces: Callable[[int], str],
    icon_current_sessions: Callable[[int], str],
    svg_shield: Callable[[], str],
) -> str:
    role_l = (role or "").strip().lower()

    items = [
        ("home", "/", "Dashboard", icon_dashboard(28)),
        ("clock", "/clock", "Attendance", icon_clock(28)),
        ("times", "/my-times", "Time Records", icon_timelogs(28)),
        ("reports", "/my-reports", "Timesheets", icon_timesheets(28)),
        ("payments", "/payments", "Pay History", icon_payments(28)),
        ("work-progress", "/work-progress", "Site Progress", icon_work_progress(28)),
    ]

    if role_l == "site_manager":
        items.append(("site-manager", "/site-manager", "Site Manager", icon_admin(28)))

    if role_l in ("admin", "master_admin"):
        items.append(("admin", "/admin", "Management", svg_shield()))

    if role_l in ("admin", "master_admin"):
        items.append(("current-sessions", "/admin/current-sessions", "Live Attendance", icon_current_sessions(28)))

    if role_l == "master_admin":
        items.append(("workplaces", "/admin/workplaces", "Companies", icon_workplaces(28)))

    links = []
    for key, href, label, icon in items:
        links.append(f"""
          <a class="sideItem nav-{key} {'active' if active == key else ''}" href="{href}">
            <div class="sideLeft">
              <div class="sideIcon">{icon}</div>
              <div class="sideText">{escape(label)}</div>
            </div>
          </a>
        """)

    try:
        company_name = (get_company_settings().get("Company_Name") or "").strip() or "Main"
    except Exception:
        company_name = "Main"

    return f"""
      <aside class="sidebar refSidebar">
        <div class="refSidebarLogo">
          {timiq_logo_html()}
        </div>

        <nav class="refSidebarNav">
          {''.join(links)}
        </nav>

        <div class="refSidebarCompany">
          <div class="refSidebarCompanyIcon">▦</div>
          <div class="refSidebarCompanyName">{escape(company_name)}</div>
          <div class="refSidebarCompanyChevron">⌄</div>
        </div>

        <div class="refSidebarCollapse">
          <span>‹</span>
          <span>Collapse</span>
        </div>
      </aside>
    """


def legacy_page_back_button(href: str | None = None, label: str = "← Back") -> str:
    text = escape(label or "Back")

    if href:
        safe_href = escape(href)
        return f'''
        <div class="pageBackRow"
             data-shell-back="1"
             data-shell-back-href="{safe_href}"
             data-shell-back-label="{text}">
          <a class="pageBackLink" href="{safe_href}" aria-label="{text}" title="{text}">
  ← Back
</a>
        </div>
        '''

    return f'''
    <div class="pageBackRow"
         data-shell-back="1"
         data-shell-back-history="1"
         data-shell-back-label="{text}">
      <button type="button"
        class="pageBackLink"
        aria-label="{text}"
        title="{text}"
        onclick="window.history.back()">
  ← Back
</button>
    </div>
    '''


def legacy_layout_shell(
    active: str,
    role: str,
    content_html: str,
    shell_class: str = "",
    *,
    get_company_settings: Callable[[], Mapping[str, Any]],
    get_employee_display_name: Callable[[str], str],
    sidebar_renderer: Callable[[str, str], str],
    session_data: Mapping[str, Any],
) -> str:
    extra = f" {shell_class}" if shell_class else ""

    mobile_current_sessions_link = (
        '<a class="topAccountMenuItem" href="/admin/current-sessions"><span>Live Attendance</span><span class="topAccountMenuMark">›</span></a>'
        if str(role or "").strip().lower() in ("admin", "master_admin") else ""
    )

    mobile_work_progress_link = (
        '<a class="topAccountMenuItem" href="/work-progress"><span>Site Progress</span><span class="topAccountMenuMark">›</span></a>'
    )

    breadcrumb_labels = {
        "dashboard": "Dashboard",
        "attendance": "Attendance",
        "home": "Dashboard",
        "clock": "Attendance",
        "times": "Time Records",
        "reports": "Timesheets",
        "payments": "Pay History",
        "work-progress": "Site Progress",
        "admin": "Management",
        "current-sessions": "Attendance",
        "workplaces": "Companies",
        "time": "Time Records",
        "timesheets": "Timesheets",
        "site_progress": "Site Progress",
        "management": "Management",
        "live_attendance": "Attendance",
        "companies": "Companies",
        "profile": "Profile",
        "agreements": "Starter Form",
        "site-manager": "Site Manager",
    }

    breadcrumb_current = breadcrumb_labels.get(str(active or "").strip(), "")

    def _shell_breadcrumb_from_active() -> str:
        if not breadcrumb_current:
            return '<span class="topShellBackPlaceholder"></span>'

        if breadcrumb_current == "Dashboard":
            return (
                '<nav class="topShellBreadcrumb" aria-label="Breadcrumb">'
                '<strong>Dashboard</strong>'
                '</nav>'
            )

        return (
            '<nav class="topShellBreadcrumb" aria-label="Breadcrumb">'
            '<a href="/">Dashboard</a>'
            '<span>›</span>'
            f'<strong>{escape(breadcrumb_current)}</strong>'
            '</nav>'
        )

    shell_back_html = _shell_breadcrumb_from_active()

    # Move any page-owned breadcrumb into the shell top row.
    # This keeps the breadcrumb aligned with the bell/help/avatar row on every page.
    page_breadcrumb_match = re.search(
        r'<(?P<tag>nav|div)\s+class=(?P<quote>["\'])'
        r'(?P<class>[^"\']*(?:topShellBreadcrumb|timiqBreadcrumb|attBreadcrumb|companiesBreadcrumb|employeesBreadcrumb|locationsBreadcrumb|siteAccessBreadcrumb|refBreadcrumb|mgRefCrumbs|prRefCrumbs)[^"\']*)'
        r'(?P=quote)(?P<attrs>[^>]*)>'
        r'(?P<html>.*?)'
        r'</(?P=tag)>\s*',
        content_html,
        flags=re.DOTALL,
    )

    if page_breadcrumb_match:
        breadcrumb_inner_html = (page_breadcrumb_match.group("html") or "").strip()
        if breadcrumb_inner_html:
            shell_back_html = (
                '<nav class="topShellBreadcrumb" aria-label="Breadcrumb">'
                f'{breadcrumb_inner_html}'
                '</nav>'
            )

        content_html = (
            content_html[:page_breadcrumb_match.start()]
            + content_html[page_breadcrumb_match.end():]
        )

    # Remove old back rows from pages that already migrated to shell breadcrumb.
    back_match = re.search(
        r'<div\s+class="pageBackRow"(?P<attrs>[^>]*)>.*?</div>\s*',
        content_html,
        flags=re.DOTALL,
    )

    if back_match:
        content_html = content_html[:back_match.start()] + content_html[back_match.end():]

    username = str(session_data.get("username") or "admin").strip() or "admin"

    try:
        display_name = get_employee_display_name(username)
    except Exception:
        display_name = username

    role_text = str(role or "admin").replace("_", " ").title()

    name_parts = [p for p in str(display_name or username).split() if p]
    if len(name_parts) >= 2:
        user_initials = (name_parts[0][0] + name_parts[-1][0]).upper()
    elif name_parts:
        user_initials = name_parts[0][:2].upper()
    else:
        user_initials = "AD"

    company_bar = f"""
      <div class="pageTopActions">
        {shell_back_html}

        <div class="topShellUserTools">
          <button class="topShellIconButton topShellBell" type="button" aria-label="Notifications">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 4a4 4 0 0 1 4 4v2.35c0 .82.22 1.63.64 2.33L18 15H6l1.36-2.32A4.45 4.45 0 0 0 8 10.35V8a4 4 0 0 1 4-4Z"></path>
              <path d="M10 18a2 2 0 0 0 4 0"></path>
            </svg>
            <i>2</i>
          </button>

          <button class="topShellIconButton" type="button" aria-label="Help">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="12" cy="12" r="9"></circle>
              <path d="M9.2 9a3 3 0 1 1 5.6 1.5c-.5.78-1.4 1.12-2 1.78-.43.44-.62.88-.62 1.72"></path>
              <path d="M12 17h.01"></path>
            </svg>
          </button>

          <div class="topShellUser">
            <div class="topShellAvatar">{escape(user_initials)}</div>
            <div class="topShellUserText">
              <strong>{escape(display_name)}</strong>
              <span>{escape(role_text)}</span>
            </div>
            <div class="topShellChevron">⌄</div>
          </div>

          <div class="topAccountWrap">
            <button type="button" class="topAccountTrigger" aria-label="Account menu" onclick="(function(btn){{var wrap=btn.closest('.topAccountWrap'); if(!wrap) return; document.querySelectorAll('.topAccountWrap.open').forEach(function(el){{if(el!==wrap) el.classList.remove('open');}}); wrap.classList.toggle('open');}})(this)">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <circle cx="12" cy="5" r="1.5"></circle>
                <circle cx="12" cy="12" r="1.5"></circle>
                <circle cx="12" cy="19" r="1.5"></circle>
              </svg>
            </button>

            <div class="topAccountMenu">
              <a class="topAccountMenuItem" href="/onboarding"><span>Starter Form</span><span class="topAccountMenuMark">›</span></a>
              {mobile_current_sessions_link}
              {mobile_work_progress_link}
              <a class="topAccountMenuItem" href="/password"><span>Profile</span><span class="topAccountMenuMark">›</span></a>
              <a class="topAccountMenuItem danger" href="/logout"><span>Log out</span><span class="topAccountMenuMark">›</span></a>
            </div>
          </div>
        </div>
      </div>

      <script>
      (function(){{
        if (window.__topAccountMenuBound) return;
        window.__topAccountMenuBound = true;

        document.addEventListener('click', function(e){{
          document.querySelectorAll('.topAccountWrap.open').forEach(function(wrap){{
            if (!wrap.contains(e.target)) wrap.classList.remove('open');
          }});
        }});

        document.addEventListener('keydown', function(e){{
          if (e.key === 'Escape') {{
            document.querySelectorAll('.topAccountWrap.open').forEach(function(wrap){{
              wrap.classList.remove('open');
            }});
          }}
        }});
      }})();
      </script>
    """

    heartbeat_script = """
      <script>
      (function(){
        if (window.__sessionHeartbeatBound) return;
        window.__sessionHeartbeatBound = true;

        function beat(){
          fetch('/api/session-heartbeat', {
            method: 'GET',
            credentials: 'same-origin',
            cache: 'no-store'
          }).catch(function(){});
        }

        beat();
        window.setInterval(beat, 45000);
      })();
      </script>
    """

    return f"""
      <div class="shell{extra}">
        {sidebar_renderer(active, role)}
        <div class="main">
          {company_bar}
          {content_html}
          <div class="safeBottom"></div>
        </div>
      </div>
      {heartbeat_script}
    """
