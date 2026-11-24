"""ASGI entry point: ``uvicorn commerce_agent.api.main:app``."""

from commerce_agent.api.app import create_app

app = create_app()
