"""Production WSGI entry point for Gunicorn (`gunicorn wsgi:app`)."""

from __future__ import annotations

import os

from app import create_app

# The WSGI server is a production entry point. Local development remains
# available by explicitly setting FLASK_ENV=development in .env.
app = create_app(os.getenv("FLASK_ENV", "production"))

if __name__ == "__main__":
    app.run()
