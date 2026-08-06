"""ASGI entry point for local development and deployment."""

from inc.api.app import create_app

app = create_app()
