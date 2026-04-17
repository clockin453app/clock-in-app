from html import escape
# ================= ICONS =================
def _svg_clock():
    return """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <circle cx="12" cy="12" r="9"></circle><path d="M12 7v6l4 2"></path></svg>"""


def _svg_clipboard():
    return """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <rect x="8" y="2" width="8" height="4" rx="1"></rect>
      <path d="M9 4H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-3"></path></svg>"""


def _svg_chart():
    return """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M4 19V5"></path><path d="M4 19h16"></path>
      <path d="M8 17V9"></path><path d="M12 17V7"></path><path d="M16 17v-4"></path></svg>"""


def _svg_doc():
    return """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6"></path></svg>"""


def _svg_user():
    return """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M20 21a8 8 0 1 0-16 0"></path><circle cx="12" cy="7" r="4"></circle></svg>"""


def _svg_grid():
    return """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M4 4h7v7H4z"></path><path d="M13 4h7v7h-7z"></path>
      <path d="M4 13h7v7H4z"></path><path d="M13 13h7v7h-7z"></path></svg>"""


def _svg_logout():
    return """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M10 17l5-5-5-5"></path><path d="M15 12H3"></path>
      <path d="M21 3v18"></path></svg>"""


def _svg_shield():
    return """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M12 3l7 3v6c0 5-3.5 8-7 9-3.5-1-7-4-7-9V6l7-3z"></path>
    </svg>"""


# ================= CONTRACT TEXT =================

def _app_icon(file_name: str, size: int = 22, alt: str = ""):
    return (
        f'<img src="/static/modern_icons/{file_name}" '
        f'alt="{escape(alt)}" '
        f'width="{size}" height="{size}" '
        f'style="width:{size}px;height:{size}px;object-fit:contain;display:block;">'
    )


def _icon_dashboard(size=22): return _app_icon("dashboard.png", size, "Dashboard")


def _icon_clock(size=22): return _app_icon("clock.png", size, "Clock In & Out")


def _icon_timelogs(size=22): return _app_icon("timelogs.png", size, "Time Logs")


def _icon_timesheets(size=22): return _app_icon("timesheets.png", size, "Timesheets")


def _icon_payments(size=22):
    return f'''
    <div style="
      width:{size}px;
      height:{size}px;
      display:flex;
      align-items:center;
      justify-content:center;
      font-size:{max(12, int(size * 0.82))}px;
      font-weight:900;
      line-height:1;
      color:currentColor;
    ">£</div>
    '''


def _icon_starter_form(size=22): return _app_icon("starter_form.png", size, "Starter Form")


def _icon_admin(size=22): return _app_icon("admin.png", size, "Admin")


def _icon_workplaces(size=22): return _app_icon("workplaces.png", size, "Workplaces")


def _icon_profile(size=22): return _app_icon("profile.png", size, "Profile")


def _icon_onboarding(size=22): return _app_icon("onboarding.png", size, "Onboarding")


def _icon_payroll_report(size=22): return _app_icon("payroll_report.png", size, "Payroll Report")


def _icon_company_settings(size=22): return _app_icon("company_settings.png", size, "Company Settings")


def _icon_employee_sites(size=22): return _app_icon("employee_sites.png", size, "Employee Sites")


def _icon_employees(size=22): return _app_icon("employees.png", size, "Employees")


def _icon_connect_drive(size=22): return _app_icon("connect_drive.png", size, "Connect Drive")


def _icon_locations(size=22): return _app_icon("locations.png", size, "Locations")
