# Legacy route wrapper. Not part of the active startup path.
from .utils import add_route
from .. import routes as core

def register_admin_routes(app) -> None:
    add_route(app, '/admin', core.admin, methods=['GET'])
    add_route(app, '/admin/company', core.admin_company, methods=['GET', 'POST'])
    add_route(app, '/admin/save-shift', core.admin_save_shift, methods=['POST'])
    add_route(app, '/admin/force-clockin', core.admin_force_clockin, methods=['POST'])
    add_route(app, '/admin/force-clockout', core.admin_force_clockout, methods=['POST'])
    add_route(app, '/admin/mark-paid', core.admin_mark_paid, methods=['POST'])
    add_route(app, '/admin/payroll', core.admin_payroll, methods=['GET'])
    add_route(app, '/admin/payroll-report.csv', core.admin_payroll_report_csv, methods=['GET'])
    add_route(app, '/admin/onboarding', core.admin_onboarding_list, methods=['GET'])
    add_route(app, '/admin/onboarding/<username>', core.admin_onboarding_detail, methods=['GET'])
    add_route(app, '/admin/onboarding/<username>/download', core.admin_onboarding_download, methods=['GET'])
    add_route(app, '/admin/locations', core.admin_locations, methods=['GET'])
    add_route(app, '/admin/locations/save', core.admin_locations_save, methods=['POST'])
    add_route(app, '/admin/locations/deactivate', core.admin_locations_deactivate, methods=['POST'])
    add_route(app, '/admin/employee-sites', core.admin_employee_sites, methods=['GET'])
    add_route(app, '/admin/employee-sites/save', core.admin_employee_sites_save, methods=['POST'])
    add_route(app, '/admin/employees', core.admin_employees, methods=['GET', 'POST'])
    add_route(app, '/admin/employees/reset-password', core.admin_employee_reset_password, methods=['POST'])
    add_route(app, '/admin/employees/clear-history', core.admin_clear_employee_history, methods=['POST'])
    add_route(app, '/admin/employees/delete', core.admin_delete_employee, methods=['POST'])
    add_route(app, '/admin/migrate-workplace-id', core.admin_migrate_workplace_id, methods=['GET', 'POST'])
    add_route(app, '/admin/workplaces', core.admin_workplaces, methods=['GET', 'POST'])
