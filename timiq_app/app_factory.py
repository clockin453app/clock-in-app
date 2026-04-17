from pathlib import Path

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Settings
from .extensions import db
from .routes import init_app


def create_app() -> Flask:
    base_dir = Path(__file__).resolve().parent.parent

    app = Flask(
        __name__,
        static_folder=str(base_dir / "static"),
        static_url_path="/static",
    )
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
    app.config.from_object(Settings)

    db.init_app(app)
    _register_security_headers(app)
    init_app(app)
    return app


def _register_security_headers(app: Flask) -> None:
    @app.after_request
    def _set_security_headers(response):
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "geolocation=(self), camera=(self)")
        if app.config.get("PREFERRED_URL_SCHEME") == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response