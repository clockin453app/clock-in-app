# Legacy route wrapper. Not part of the active startup path.
from .utils import add_route
from .. import routes as core


def register_auth_routes(app) -> None:
    add_route(app, '/login', core.login, methods=['GET', 'POST'])
    add_route(app, '/logout', core.logout_confirm, methods=['GET'])
    add_route(app, '/logout', core.logout, methods=['POST'])
    add_route(app, '/password', core.change_password, methods=['GET', 'POST'])
