"""
Test to verify the empty drop zone fix is working correctly.

This test verifies that the pointer-events: none CSS rule has been removed
from the .empty-phase-placeholder class, allowing drag-and-drop events
to reach the sortable container.
"""

import pytest
from sqlalchemy import select

from app import create_app
from app.extensions import db
from app.models import AdminAccount, MediaServer, WizardStep


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
def empty_phases_setup(app):
    """Setup with no wizard steps (both phases empty)."""
    with app.app_context():
        # Create a media server so the wizard steps page shows content
        media_server = MediaServer(
            name="Test Plex Server",
            server_type="plex",
            url="http://localhost:32400",
            api_key="test-key",
        )
        db.session.add(media_server)

        # Ensure no steps exist for plex server
        stmt = select(WizardStep).where(WizardStep.server_type == "plex")
        existing_steps = db.session.execute(stmt).scalars().all()
        for step in existing_steps:
            db.session.delete(step)
        db.session.commit()
        return "plex"


class TestEmptyDropZoneFix:
    """Test that the empty drop zone fix is working correctly."""

    def test_pointer_events_none_removed_from_css(
        self, authenticated_client, empty_phases_setup
    ):
        """Test that pointer-events: none has been removed from .empty-phase-placeholder CSS."""
        _ = empty_phases_setup  # Setup ensures empty phases
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Verify the CSS class still exists
        assert ".empty-phase-placeholder" in response_text

        # Verify pointer-events: none has been removed from the CSS rule
        # Look for the specific CSS rule block
        css_rule_start = response_text.find(".empty-phase-placeholder {")
        assert css_rule_start != -1, "CSS rule for .empty-phase-placeholder not found"

        css_rule_end = response_text.find("}", css_rule_start)
        css_rule_block = response_text[css_rule_start : css_rule_end + 1]

        # Verify pointer-events: none is not in the CSS rule block
        assert "pointer-events: none" not in css_rule_block

        # Verify user-select: none is still present (for text selection prevention)
        assert "user-select: none" in css_rule_block

    def test_empty_placeholder_elements_still_render(
        self, authenticated_client, empty_phases_setup
    ):
        """Test that empty placeholder elements still render correctly after the fix."""
        server_type = empty_phases_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Check for pre-phase section with empty class and correct server
        assert f'data-phase="pre" data-server="{server_type}"' in response_text
        assert (
            "wizard-steps empty" in response_text
            or "empty wizard-steps" in response_text
        )

        # Check for empty placeholder in pre-phase
        assert "empty-phase-placeholder" in response_text
        assert "No pre-invite steps" in response_text

        # Check for post-phase section with empty class
        assert f'data-phase="post" data-server="{server_type}"' in response_text

        # Check for empty placeholder in post-phase
        assert "No post-invite steps" in response_text

    def test_sortable_containers_remain_functional(
        self, authenticated_client, empty_phases_setup
    ):
        """Test that sortable containers maintain their functionality after the fix."""
        server_type = empty_phases_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Check for sortable containers with required attributes
        assert f'data-server="{server_type}"' in response_text
        assert 'data-phase="pre"' in response_text
        assert 'data-phase="post"' in response_text
        assert "data-reorder-url" in response_text

        # Container should be properly configured for drag-and-drop
        assert "wizard-steps" in response_text

        # Empty containers should have 'empty' class when placeholder is present
        assert (
            "wizard-steps empty" in response_text
            or "empty wizard-steps" in response_text
        )

    def test_drag_and_drop_css_classes_intact(
        self, authenticated_client, empty_phases_setup
    ):
        """Test that other drag-and-drop related CSS classes are still intact."""
        _ = empty_phases_setup  # Setup ensures empty phases
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Verify other drag-and-drop CSS classes are still present
        assert ".drop-zone" in response_text
        assert ".drag-handle" in response_text
        assert ".step-item.dragging" in response_text
        assert ".wizard-steps.empty" in response_text

        # Verify drag-over styling is present
        assert ".drop-zone.drag-over" in response_text or "drag-over" in response_text
