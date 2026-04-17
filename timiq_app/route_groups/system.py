# Legacy route wrapper. Not part of the active startup path.
from .utils import add_route
from .. import routes as core


def register_system_routes(app) -> None:
    add_route(app, '/ping', core.ping, methods=['GET'])
    add_route(app, '/connect-drive', core.connect_drive, methods=['GET'])
    add_route(app, '/oauth2callback', core.oauth2callback, methods=['GET'])
    add_route(app, '/clock-selfie/<path:filename>', core.view_clock_selfie, methods=['GET'])
    add_route(app, '/manifest.webmanifest', core.manifest, methods=['GET'])
