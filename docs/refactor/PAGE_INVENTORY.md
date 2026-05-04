# TimIQ Page Inventory

## Already template-backed

- `timiq_app/templates/admin/dashboard.html`
- `timiq_app/templates/admin/management.html`
- `timiq_app/templates/admin/payroll.html`
- `timiq_app/templates/admin/live_attendance.html`
- `timiq_app/templates/admin/employees.html`
- `timiq_app/templates/admin/companies.html`
- `timiq_app/templates/admin/locations.html`
- `timiq_app/templates/admin/site_access.html`
- `timiq_app/templates/admin/system_health.html`

## To migrate from Python-generated HTML into templates later

- Time Records: `services/my_times_route.py` -> `templates/employee/time_records.html`
- Timesheets: `services/my_reports_route.py` -> `templates/employee/timesheets.html`
- Pay History: `services/payments_page_route.py` -> `templates/employee/pay_history.html`
- Site Progress: `services/work_progress_route.py` -> `templates/admin_tools/work_progress.html`
- Company Settings: `services/admin_company_route.py` -> `templates/admin_tools/company_settings.html`
- Audit Log: `services/admin_audit_route.py` -> `templates/admin_tools/audit_log.html`
- Admin Log Activities: `services/admin_log_activities_route.py` -> `templates/admin_tools/log_activities.html`
- Admin Onboarding List: `services/admin_onboarding_list_route.py` -> `templates/admin_tools/onboarding_list.html`
- Admin Onboarding Detail: `services/admin_onboarding_detail_route.py` -> `templates/admin_tools/onboarding_detail.html`
- Clock Selfies: `services/admin_clock_selfies_route.py` -> `templates/admin_tools/clock_selfies.html`
- Recalculate Shifts: `services/admin_recalculate_shifts_route.py` -> `templates/admin_tools/recalculate_shifts.html`
- Site Manager: `services/site_manager_route.py` -> `templates/admin_tools/site_manager.html`
- Change Password: `services/change_password_route.py` -> `templates/account/change_password.html`
- Employee Onboarding: `services/onboarding_route.py` -> `templates/employee/onboarding.html`
- Clock Page: `services/clock_page_route.py` -> `templates/employee/clock.html`
