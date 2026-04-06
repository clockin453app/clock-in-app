from .admin import register_admin_routes
from .auth import register_auth_routes
from .data_tools import register_data_tool_routes
from .employee import register_employee_routes
from .system import register_system_routes


def register_all_routes(app) -> None:
    register_system_routes(app)
    register_auth_routes(app)
    register_employee_routes(app)
    register_admin_routes(app)
    register_data_tool_routes(app)
