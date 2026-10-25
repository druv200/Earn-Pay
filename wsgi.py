"""Production WSGI entry point for Gunicorn (`gunicorn wsgi:app`)."""

from __future__ import annotations

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run()
