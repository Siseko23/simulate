import pytest
from app import create_app
from app.models import db

@pytest.fixture()
def app():
    app = create_app("development")
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return app

@pytest.fixture()
def client(app):
    return app.test_client()
