"""Compatibility entrypoint for Render / Gunicorn."""

import os

from workhours_app import create_app
from workhours_app.config import DEBUG_MODE

app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=DEBUG_MODE)
