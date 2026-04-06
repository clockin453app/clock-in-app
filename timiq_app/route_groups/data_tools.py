from .utils import add_route
from .. import routes as core


def register_data_tool_routes(app) -> None:
    add_route(app, '/db-test', core.db_test, methods=['GET'])
    add_route(app, '/db/employees', core.db_view_employees, methods=['GET'])
    add_route(app, '/db/workhours', core.db_view_workhours, methods=['GET'])
    add_route(app, '/db/audit', core.db_view_audit, methods=['GET'])
    add_route(app, '/db/payroll', core.db_view_payroll, methods=['GET'])
    add_route(app, '/db/onboarding', core.db_view_onboarding, methods=['GET'])
    add_route(app, '/db/locations', core.db_view_locations, methods=['GET'])
    add_route(app, '/db/settings', core.db_view_settings, methods=['GET'])
    add_route(app, '/db/upgrade-employees-table', core.db_upgrade_employees_table, methods=['POST'])
    add_route(app, '/db/upgrade-onboarding-table', core.db_upgrade_onboarding_table, methods=['POST'])
    add_route(app, '/import-employees', core.import_employees, methods=['POST'])
    add_route(app, '/import-locations', core.import_locations, methods=['POST'])
    add_route(app, '/import-settings', core.import_settings, methods=['POST'])
    add_route(app, '/import-audit', core.import_audit, methods=['POST'])
    add_route(app, '/import-payroll', core.import_payroll, methods=['POST'])
    add_route(app, '/import-onboarding', core.import_onboarding, methods=['POST'])
    add_route(app, '/import-workhours', core.import_workhours, methods=['POST'])
