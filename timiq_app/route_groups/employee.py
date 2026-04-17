# Legacy route wrapper. Not part of the active startup path.
from .utils import add_route
from .. import routes as core


def register_employee_routes(app) -> None:
    add_route(app, '/', core.home, methods=['GET'])
    add_route(app, '/api/dashboard-snapshot', core.api_dashboard_snapshot, methods=['GET'])
    add_route(app, '/clock', core.clock_page, methods=['GET', 'POST'])
    add_route(app, '/my-times', core.my_times, methods=['GET'])
    add_route(app, '/my-reports', core.my_reports, methods=['GET'])
    add_route(app, '/my-week-report', core.my_week_report, methods=['GET'])
    add_route(app, '/payments', core.payments_page, methods=['GET'])
    add_route(app, '/my-reports-print', core.my_reports_print, methods=['GET'])
    add_route(app, '/my-reports.pdf', core.my_reports_pdf, methods=['GET'])
    add_route(app, '/my-reports.csv', core.my_reports_csv, methods=['GET'])
    add_route(app, '/onboarding', core.onboarding, methods=['GET', 'POST'])
