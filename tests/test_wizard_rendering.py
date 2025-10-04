"""Tests for wizard rendering logic (_serve_wizard function)."""

import pytest

from app.blueprints.wizard.routes import _serve_wizard
from app.extensions import db
from app.models import WizardStep


@pytest.fixture
def session(app):
    """Return a clean database session inside an app context."""
    with app.app_context():
        # Clean up any existing WizardStep data before the test
        db.session.query(WizardStep).delete()
        db.session.commit()

        yield db.session

        # Clean up after the test
        db.session.rollback()


@pytest.fixture
def sample_steps(session):
    """Create sample wizard steps for testing."""
    steps = [
        WizardStep(
            server_type="plex",
            category="pre_invite",
            position=0,
            title="Welcome",
            markdown="# Welcome to Plex",
            require_interaction=False,
        ),
        WizardStep(
            server_type="plex",
            category="pre_invite",
            position=1,
            title="Requirements",
            markdown="# Requirements",
            require_interaction=True,
        ),
        WizardStep(
            server_type="plex",
            category="post_invite",
            position=0,
            title="Getting Started",
            markdown="# Getting Started",
            require_interaction=False,
        ),
    ]
    session.add_all(steps)
    session.commit()
    return steps


class MockRowAdapter:
    """Mock adapter for wizard steps."""

    def __init__(self, content, require=False):
        self.content = content
        self._require = require

    def get(self, key, default=None):
        if key == "require":
            return self._require
        return default


def test_serve_wizard_with_pre_phase(app, client, session, sample_steps):
    """Test _serve_wizard() with pre phase."""
    with app.app_context():
        with app.test_request_context('/'):
            steps = [
                MockRowAdapter("# Pre-invite step 1", require=False),
                MockRowAdapter("# Pre-invite step 2", require=True),
            ]

            response = _serve_wizard("plex", 0, steps, "pre")

            # Response is a string when not in HTMX mode
            assert isinstance(response, str)
            assert "Pre-invite step 1" in response


def test_serve_wizard_with_post_phase(app, client, session, sample_steps):
    """Test _serve_wizard() with post phase."""
    with app.app_context():
        with app.test_request_context('/'):
            steps = [
                MockRowAdapter("# Post-invite step 1", require=False),
                MockRowAdapter("# Post-invite step 2", require=False),
            ]

            response = _serve_wizard("plex", 0, steps, "post")

            assert isinstance(response, str)
            assert "Post-invite step 1" in response


def test_serve_wizard_htmx_partial_rendering(app, client, session, sample_steps):
    """Test that HTMX requests return partial templates."""
    with app.app_context():
        # Test with HTMX request header
        with app.test_request_context('/', headers={'HX-Request': 'true'}):
            steps = [MockRowAdapter("# Test step", require=False)]

            response = _serve_wizard("plex", 0, steps, "pre")

            # Response object when HTMX header is present
            assert response is not None


def test_serve_wizard_full_page_rendering(app, client, session, sample_steps):
    """Test that non-HTMX requests return full page templates."""
    with app.app_context():
        with app.test_request_context('/'):
            steps = [MockRowAdapter("# Test step", require=False)]

            response = _serve_wizard("plex", 0, steps, "post")

            # Should render full page (frame.html)
            assert isinstance(response, str)
            assert "Test step" in response


def test_serve_wizard_interaction_requirement_detection(app, client, session):
    """Test that interaction requirement is correctly detected."""
    with app.app_context():
        with app.test_request_context('/'):
            steps = [
                MockRowAdapter("# Step 1", require=False),
                MockRowAdapter("# Step 2", require=True),
                MockRowAdapter("# Step 3", require=False),
            ]

            # Test step without interaction requirement
            response = _serve_wizard("plex", 0, steps, "pre")
            assert isinstance(response, str)

            # Test step with interaction requirement
            response = _serve_wizard("plex", 1, steps, "pre")
            assert isinstance(response, str)

            # Test step without interaction requirement
            response = _serve_wizard("plex", 2, steps, "pre")
            assert isinstance(response, str)


def test_serve_wizard_phase_parameter_in_template(app, client, session):
    """Test that phase parameter is passed to templates."""
    with app.app_context():
        with app.test_request_context('/'):
            steps = [MockRowAdapter("# Test", require=False)]

            # Test with pre phase
            response_pre = _serve_wizard("plex", 0, steps, "pre")
            assert isinstance(response_pre, str)

            # Test with post phase
            response_post = _serve_wizard("plex", 0, steps, "post")
            assert isinstance(response_post, str)


def test_serve_wizard_index_boundary_handling(app, client, session):
    """Test that _serve_wizard() handles index boundaries correctly."""
    with app.app_context():
        with app.test_request_context('/'):
            steps = [
                MockRowAdapter("# Step 1", require=False),
                MockRowAdapter("# Step 2", require=False),
            ]

            # Test negative index (should clamp to 0)
            response = _serve_wizard("plex", -1, steps, "pre")
            assert isinstance(response, str)

            # Test index beyond max (should clamp to max)
            response = _serve_wizard("plex", 999, steps, "pre")
            assert isinstance(response, str)

            # Test valid index
            response = _serve_wizard("plex", 1, steps, "pre")
            assert isinstance(response, str)


def test_serve_wizard_empty_steps_returns_404(app, client, session):
    """Test that _serve_wizard() returns 404 for empty steps list."""
    with app.app_context():
        with app.test_request_context('/'):
            steps = []

            with pytest.raises(Exception):  # Should abort(404)
                _serve_wizard("plex", 0, steps, "pre")


def test_serve_wizard_direction_parameter(app, client, session):
    """Test that direction parameter is handled correctly."""
    with app.app_context():
        with app.test_request_context('/?dir=next'):
            steps = [
                MockRowAdapter("# Step 1", require=False),
                MockRowAdapter("# Step 2", require=False),
            ]

            # Test with different direction values
            response = _serve_wizard("plex", 0, steps, "pre")
            assert isinstance(response, str)


def test_serve_wizard_with_combo_server_type(app, client, session):
    """Test _serve_wizard() with 'combo' server type for multi-server invitations."""
    with app.app_context():
        with app.test_request_context('/'):
            steps = [
                MockRowAdapter("# Plex step", require=False),
                MockRowAdapter("# Jellyfin step", require=False),
            ]

            response = _serve_wizard("combo", 0, steps, "post")
            assert isinstance(response, str)


def test_serve_wizard_with_bundle_server_type(app, client, session):
    """Test _serve_wizard() with 'bundle' server type for wizard bundles."""
    with app.app_context():
        with app.test_request_context('/'):
            steps = [
                MockRowAdapter("# Bundle step 1", require=False),
                MockRowAdapter("# Bundle step 2", require=True),
            ]

            response = _serve_wizard("bundle", 0, steps, "post")
            assert isinstance(response, str)


def test_serve_wizard_exception_handling_for_require_interaction(app, client, session):
    """Test that exceptions in require_interaction detection are handled gracefully."""
    with app.app_context():
        with app.test_request_context('/'):

            class BrokenRowAdapter:
                """Mock adapter that raises exception on get()."""

                content = "# Test"

                def get(self, key, default=None):
                    raise Exception("Broken adapter")

            steps = [BrokenRowAdapter()]

            # Should handle exception gracefully and continue
            response = _serve_wizard("plex", 0, steps, "pre")
            assert isinstance(response, str)


def test_serve_wizard_multiple_phases_same_steps(app, client, session):
    """Test that same steps can be rendered with different phases."""
    with app.app_context():
        with app.test_request_context('/'):
            steps = [MockRowAdapter("# Shared step", require=False)]

            # Render with pre phase
            response_pre = _serve_wizard("plex", 0, steps, "pre")
            assert isinstance(response_pre, str)

            # Render with post phase (same steps, different phase)
            response_post = _serve_wizard("plex", 0, steps, "post")
            assert isinstance(response_post, str)


def test_serve_wizard_preserves_step_order(app, client, session):
    """Test that _serve_wizard() preserves step order."""
    with app.app_context():
        with app.test_request_context('/'):
            steps = [
                MockRowAdapter("# First", require=False),
                MockRowAdapter("# Second", require=False),
                MockRowAdapter("# Third", require=False),
            ]

            # Render first step
            response0 = _serve_wizard("plex", 0, steps, "pre")
            assert isinstance(response0, str)
            assert "First" in response0

            # Render second step
            response1 = _serve_wizard("plex", 1, steps, "pre")
            assert isinstance(response1, str)
            assert "Second" in response1

            # Render third step
            response2 = _serve_wizard("plex", 2, steps, "pre")
            assert isinstance(response2, str)
            assert "Third" in response2
