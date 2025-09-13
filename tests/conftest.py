import tempfile

import pytest

from app import create_app
from app.config import BaseConfig
from app.extensions import db


class TestConfig(BaseConfig):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


class E2ETestConfig(BaseConfig):
    TESTING = True
    WTF_CSRF_ENABLED = False
    # Use a temporary file database that both test process and live server can access
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{tempfile.gettempdir()}/wizarr_e2e_test.db"


@pytest.fixture(scope="session")
def app():
    app = create_app(TestConfig)  # type: ignore[arg-type]
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def runner(app):
    return app.test_cli_runner()


@pytest.fixture
def session(app):
    """Provide a database session for tests."""
    with app.app_context():
        # Clean up any existing data before each test
        from app.models import WizardStep
        WizardStep.query.delete()
        db.session.commit()
        yield db.session
        # Clean up after each test
        db.session.rollback()
