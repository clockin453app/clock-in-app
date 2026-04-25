from html import escape

# ================= BASE SVG ICONS =================

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


# ================= IMAGE ICON HELPER =================
# Kept for admin cards and other non-sidebar areas that still use image icons.

def _app_icon(file_name: str, size: int = 22, alt: str = ""):
    return (
        f'<img src="/static/modern_icons/{file_name}" '
        f'alt="{escape(alt)}" '
        f'width="{size}" height="{size}" '
        f'style="width:{size}px;height:{size}px;object-fit:contain;display:block;">'
    )


# ================= CLEAN SIDEBAR / NAV SVG ICONS =================

def _icon_dashboard(size=22):
    return f"""
    <svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none"
         xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <rect x="3.5" y="4.5" width="7" height="6" rx="1.2" stroke="currentColor" stroke-width="2"/>
      <rect x="13.5" y="4.5" width="7" height="6" rx="1.2" stroke="currentColor" stroke-width="2"/>
      <rect x="3.5" y="13.5" width="7" height="6" rx="1.2" stroke="currentColor" stroke-width="2"/>
      <rect x="13.5" y="13.5" width="7" height="6" rx="1.2" stroke="currentColor" stroke-width="2"/>
    </svg>
    """


def _icon_clock(size=22):
    return f"""
    <svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none"
         xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <circle cx="12" cy="12" r="8" stroke="currentColor" stroke-width="2"/>
      <path d="M12 8V12L15 14" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
    """


def _icon_timelogs(size=22):
    return f"""
    <svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none"
         xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M8 3.5H14L19.5 9V19A1.5 1.5 0 0 1 18 20.5H8A1.5 1.5 0 0 1 6.5 19V5A1.5 1.5 0 0 1 8 3.5Z"
            stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
      <path d="M14 3.5V9H19.5" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
      <path d="M9 13H16" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
      <path d="M9 17H14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
    </svg>
    """


def _icon_timesheets(size=22):
    return f"""
    <svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none"
         xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <rect x="3.5" y="5.5" width="17" height="15" rx="2" stroke="currentColor" stroke-width="2"/>
      <path d="M7 3.5V7.5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
      <path d="M17 3.5V7.5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
      <path d="M3.5 9.5H20.5" stroke="currentColor" stroke-width="2"/>
    </svg>
    """


def _icon_payments(size=22):
    return f"""
    <svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none"
         xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M14.5 5.5H10A3 3 0 1 0 10 11.5H14A3 3 0 1 1 14 17.5H8.5"
            stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
      <path d="M11.5 3.5V20.5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
    </svg>
    """


def _icon_work_progress(size=22):
    return f"""
    <svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none"
         xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <rect x="3.5" y="4.5" width="17" height="15" rx="2" stroke="currentColor" stroke-width="2"/>
      <path d="M7 15L10 12L13 14L17 9" stroke="currentColor" stroke-width="2"
            stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
    """


def _icon_admin(size=22):
    return f"""
    <svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none"
         xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M12 3.5L18.5 6V11.5C18.5 15.5 15.9 18.8 12 20.5C8.1 18.8 5.5 15.5 5.5 11.5V6L12 3.5Z"
            stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
    </svg>
    """


def _icon_workplaces(size=22):
    return f"""
    <svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none"
         xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M4.5 19.5H19.5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
      <rect x="6.5" y="10.5" width="4" height="9" stroke="currentColor" stroke-width="2"/>
      <rect x="13.5" y="6.5" width="4" height="13" stroke="currentColor" stroke-width="2"/>
      <path d="M8.5 13.5H8.51" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
      <path d="M15.5 9.5H15.51" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
      <path d="M15.5 12.5H15.51" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
    </svg>
    """


def _icon_current_sessions(size=22):
    return f"""
    <svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none"
         xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <circle cx="9" cy="9" r="3" stroke="currentColor" stroke-width="2"/>
      <circle cx="17" cy="10" r="2.5" stroke="currentColor" stroke-width="2"/>
      <path d="M4.5 18.5C5.2 15.9 7 14.5 9 14.5C11 14.5 12.8 15.9 13.5 18.5"
            stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
      <path d="M14.5 18.5C15 17 16 16 17.5 15.7"
            stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
    </svg>
    """


# ================= OTHER APP / ADMIN CARD ICONS =================
# These are kept as image icons because admin cards use them.

def _icon_starter_form(size=22):
    return _app_icon("starter_form.png", size, "Starter Form")


def _icon_profile(size=22):
    return _app_icon("profile.png", size, "Profile")


def _icon_onboarding(size=22):
    return _app_icon("onboarding.png", size, "Onboarding")


def _icon_payroll_report(size=22):
    return _app_icon("payroll_report.png", size, "Payroll Report")


def _icon_company_settings(size=22):
    return _app_icon("company_settings.png", size, "Company Settings")


def _icon_employee_sites(size=22):
    return _app_icon("employee_sites.png", size, "Employee Sites")


def _icon_employees(size=22):
    return _app_icon("employees.png", size, "Employees")


def _icon_connect_drive(size=22):
    return _app_icon("connect_drive.png", size, "Connect Drive")


def _icon_locations(size=22):
    return _app_icon("locations.png", size, "Locations")


def _icon_clock_selfies(size=45):
    return f"""
    <svg width="{size}" height="{size}" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="7" y="12" width="34" height="24" rx="4" fill="#F8FAFF" stroke="#C9D6EA"/>
      <path d="M16 12.5L18.6 9H29.4L32 12.5" fill="#EAF2FF" stroke="#C9D6EA"/>
      <circle cx="24" cy="24" r="7.5" fill="#DCEBFF" stroke="#2D3A74" stroke-width="2"/>
      <circle cx="24" cy="24" r="3.2" fill="#4F89C7"/>
      <circle cx="13.5" cy="17.5" r="1.8" fill="#EF4444"/>
      <circle cx="35.5" cy="33.5" r="7" fill="#EAF8EF" stroke="#8FD19E"/>
      <path d="M32.5 33.5L34.6 35.6L38.6 31.6" stroke="#16A34A" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
    """