"""
Integration test for drag-and-drop functionality with empty drop zones.

This test verifies that the fix for empty drop zones works correctly
by creating actual wizard steps and testing the drag-and-drop behavior.
"""

import pytest
from sqlalchemy import select

from app import create_app
from app.extensions import db
from app.models import AdminAccount, MediaServer, WizardPhase, WizardStep


@pytest.fixture
def app():
    """Create application for testing."""
    app = create_app()
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        db.create_all()

        # Create admin user for authentication
        admin = AdminAccount(username="admin")
        admin.set_password("password")
        db.session.add(admin)
        db.session.commit()

        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture
def authenticated_client(client):
    """Create authenticated test client."""
    client.post("/login", data={"username": "admin", "password": "password"})
    return client


@pytest.fixture
def plex_server_with_steps(app):
    """Create a Plex server with some wizard steps."""
    with app.app_context():
        # Create media server
        server = MediaServer(
            name="Test Plex Server",
            server_type="plex",
            url="http://localhost:32400",
            api_key="test-key",
        )
        db.session.add(server)

        # Create some wizard steps for pre-phase
        pre_step1 = WizardStep(
            server_type="plex",
            phase=WizardPhase.PRE,
            position=1,
            title="Welcome Step",
            markdown="# Welcome to our server!",
        )
        pre_step2 = WizardStep(
            server_type="plex",
            phase=WizardPhase.PRE,
            position=2,
            title="Rules Step",
            markdown="# Please follow our rules.",
        )

        # Create one step for post-phase (leaving it mostly empty)
        post_step1 = WizardStep(
            server_type="plex",
            phase=WizardPhase.POST,
            position=1,
            title="Thank You Step",
            markdown="# Thanks for joining!",
        )

        db.session.add_all([pre_step1, pre_step2, post_step1])
        db.session.commit()

        return "plex"


@pytest.fixture
def empty_plex_server(app):
    """Create a Plex server with no wizard steps."""
    with app.app_context():
        # Create media server
        server = MediaServer(
            name="Empty Plex Server",
            server_type="plex",
            url="http://localhost:32400",
            api_key="test-key",
        )
        db.session.add(server)

        # Ensure no wizard steps exist
        stmt = select(WizardStep).where(WizardStep.server_type == "plex")
        existing_steps = db.session.execute(stmt).scalars().all()
        for step in existing_steps:
            db.session.delete(step)

        db.session.commit()
        return "plex"


class TestDragDropIntegration:
    """Integration tests for drag-and-drop functionality."""

    def test_populated_phases_render_correctly(
        self, authenticated_client, plex_server_with_steps
    ):
        """Test that populated phases render step items correctly."""
        server_type = plex_server_with_steps
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Check for pre-phase section with correct attributes
        assert f'data-phase="pre" data-server="{server_type}"' in response_text

        # Should have step items (class="step-item"), not empty placeholder
        assert "step-item" in response_text

        # Should not have empty placeholder elements (only CSS class definition is OK)
        assert 'class="empty-phase-placeholder"' not in response_text

    def test_empty_phases_show_placeholder_without_pointer_events_none(
        self, authenticated_client, empty_plex_server
    ):
        """Test that empty phases show placeholder without pointer-events: none."""
        # Use the empty_plex_server fixture
        _ = empty_plex_server
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Verify the CSS fix is applied
        css_rule_start = response_text.find(".empty-phase-placeholder {")
        assert css_rule_start != -1

        css_rule_end = response_text.find("}", css_rule_start)
        css_rule_block = response_text[css_rule_start : css_rule_end + 1]

        # The fix: pointer-events: none should be removed
        assert "pointer-events: none" not in css_rule_block

        # But user-select: none should still be there
        assert "user-select: none" in css_rule_block

    def test_sortable_containers_have_correct_attributes(
        self, authenticated_client, plex_server_with_steps
    ):
        """Test that sortable containers have the correct data attributes for drag-and-drop."""
        server_type = plex_server_with_steps
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Check for sortable containers with wizard-steps class
        assert "wizard-steps" in response_text

        # Check for required data attributes
        assert f'data-server="{server_type}"' in response_text
        assert 'data-phase="pre"' in response_text
        assert 'data-phase="post"' in response_text
        assert "data-reorder-url" in response_text

    def test_drag_and_drop_javascript_loads(
        self, authenticated_client, plex_server_with_steps
    ):
        """Test that the drag-and-drop JavaScript file is included."""
        # Use the plex_server_with_steps fixture
        _ = plex_server_with_steps
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Verify the JavaScript file is included
        assert "wizard-steps.js" in response_text
        assert '<script src="/static/js/wizard-steps.js"></script>' in response_text

    def test_css_classes_for_drag_and_drop_present(
        self, authenticated_client, plex_server_with_steps
    ):
        """Test that all necessary CSS classes for drag-and-drop are present."""
        _ = plex_server_with_steps
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Check for essential drag-and-drop CSS classes
        assert ".drag-handle" in response_text
        assert ".step-item" in response_text
        assert ".wizard-steps" in response_text
        assert ".drop-zone" in response_text

        # Check for empty state styling
        assert ".empty-phase-placeholder" in response_text
        assert ".wizard-steps.empty" in response_text
