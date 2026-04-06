import os

from timiq_app import create_app
from timiq_app.config import Settings

app = create_app()
DEBUG_MODE = Settings.DEBUG_MODE


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=DEBUG_MODE)
