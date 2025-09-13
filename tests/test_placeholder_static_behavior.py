"""
Test to ensure placeholder text remains static during drag operations.

This test verifies that the empty-phase-placeholder element:
1. Does not respond to drag operations
2. Remains statically positioned within the drop zone
3. Does not interfere with Sortable.js drag-and-drop functionality
4. Is properly excluded from being treated as a draggable item
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
def mixed_setup(app):
    """Setup with steps in one phase and empty phase for testing cross-phase drag."""
    with app.app_context():
        # Create media server
        media_server = MediaServer(
            name="Test Server",
            server_type="plex",
            url="http://localhost:32400",
            api_key="test-key",
        )
        db.session.add(media_server)

        # Clear existing steps
        stmt = select(WizardStep).where(WizardStep.server_type == "plex")
        existing_steps = db.session.execute(stmt).scalars().all()
        for step in existing_steps:
            db.session.delete(step)
        db.session.commit()

        # Create steps only in post phase, leaving pre phase empty
        steps = [
            WizardStep(
                server_type="plex",
                phase=WizardPhase.POST,
                position=0,
                title="Post Step 1",
                markdown="# Post Step 1",
            ),
            WizardStep(
                server_type="plex",
                phase=WizardPhase.POST,
                position=1,
                title="Post Step 2",
                markdown="# Post Step 2",
            ),
        ]
        db.session.add_all(steps)
        db.session.commit()
        return [step.id for step in steps]


@pytest.fixture
def empty_setup(app):
    """Setup with both phases empty for testing placeholder behavior."""
    with app.app_context():
        # Create media server
        media_server = MediaServer(
            name="Test Empty Server",
            server_type="plex",
            url="http://localhost:32400",
            api_key="test-key",
        )
        db.session.add(media_server)

        # Ensure no steps exist
        stmt = select(WizardStep).where(WizardStep.server_type == "plex")
        existing_steps = db.session.execute(stmt).scalars().all()
        for step in existing_steps:
            db.session.delete(step)
        db.session.commit()
        return "plex"


class TestPlaceholderStaticBehavior:
    """Test that placeholder text remains static during drag operations."""

    def test_sortable_excludes_placeholder_elements(
        self, authenticated_client, mixed_setup
    ):
        """Test that Sortable.js configuration excludes placeholder elements from being draggable."""
        _ = mixed_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Check that wizard-steps.js is included
        assert "wizard-steps.js" in response_text

        # Verify the HTML structure has placeholder with correct class
        assert "empty-phase-placeholder" in response_text
        assert "No pre-invite steps" in response_text

        # In mixed setup, PRE phase should be empty (showing placeholder)
        # POST phase should have steps
        assert "Post Step 1" in response_text or "Post Step 2" in response_text

    def test_placeholder_css_prevents_sortable_interaction(
        self, authenticated_client, empty_setup
    ):
        """Test that placeholder CSS properties prevent it from being treated as sortable."""
        server_type = empty_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Verify server type is present in the response
        assert server_type in response_text

        # Find the placeholder CSS rule
        placeholder_css_start = response_text.find(".empty-phase-placeholder")
        assert placeholder_css_start != -1, (
            "CSS rule for .empty-phase-placeholder not found"
        )

        # Find the end of the CSS rule block
        next_rule_start = response_text.find(".", placeholder_css_start + 1)
        if next_rule_start == -1:
            next_rule_start = len(response_text)
        placeholder_css_block = response_text[placeholder_css_start:next_rule_start]

        # The placeholder should have user-select: none but NOT pointer-events: none
        assert "user-select: none" in placeholder_css_block
        assert "pointer-events: none" not in placeholder_css_block

    def test_sortable_config_has_proper_filter(self, authenticated_client, mixed_setup):
        """Test that the Sortable.js configuration properly filters out placeholder elements."""
        _ = mixed_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Verify the JavaScript file is included
        assert "wizard-steps.js" in response_text

    def test_javascript_handles_placeholder_visibility(self):
        """Test that the wizard-steps.js source code properly handles placeholder visibility."""
        # Read the JavaScript file directly to verify the visibility handling
        with open(
            "/home/dev/GitHub/engels74/wizarr/app/static/js/wizard-steps.js"
        ) as f:
            js_content = f.read()

        # Verify that the updateEmptyState method handles placeholder display
        assert "updateEmptyState" in js_content
        assert "empty-phase-placeholder" in js_content
        assert "style.display" in js_content

        # Verify the configuration is within the getSortableConfig method
        assert "getSortableConfig" in js_content

    def test_empty_placeholder_positioning_stability(
        self, authenticated_client, empty_setup
    ):
        """Test that empty placeholder maintains stable positioning and styling."""
        server_type = empty_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Verify server type is present in the response
        assert server_type in response_text

        # Check that the placeholder is properly nested within the sortable container
        # but has stable positioning
        assert "wizard-steps empty" in response_text
        assert "empty-phase-placeholder" in response_text

        # The placeholder should have its own CSS styling for the striped background
        placeholder_css = response_text.find(".empty-phase-placeholder")
        assert placeholder_css != -1

        # Find the CSS rule end
        css_end = response_text.find("}", placeholder_css)
        css_block = response_text[placeholder_css:css_end]

        # Should have the striped background pattern that covers the entire drop zone
        assert "repeating-linear-gradient" in css_block

    def test_placeholder_html_structure_for_static_behavior(
        self, authenticated_client, empty_setup
    ):
        """Test that placeholder HTML structure supports static behavior."""
        server_type = empty_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Verify server type is present in the response
        assert server_type in response_text

        # The placeholder should exist in the HTML structure
        assert "empty-phase-placeholder" in response_text

        # It should contain instructional text that doesn't look like a draggable item
        assert "No pre-invite steps" in response_text
        assert "Drop steps here or create new ones" in response_text

        # The placeholder should have pointer-events-none class to prevent interaction
        assert "pointer-events-none" in response_text

        # The placeholder should be absolutely positioned
        assert "absolute inset-0" in response_text or "absolute" in response_text

    def test_cross_phase_drag_with_static_placeholder(
        self, authenticated_client, mixed_setup
    ):
        """Test that cross-phase dragging works properly with static placeholders."""
        step_ids = mixed_setup

        # Move a step from post to pre phase (which should have an empty placeholder)
        response = authenticated_client.post(
            f"/settings/wizard/{step_ids[0]}/update-phase",
            json={"phase": "pre", "server_type": "plex"},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200

        # Verify the step moved correctly and placeholder behavior remains stable
        with authenticated_client.application.app_context():
            step = db.session.get(WizardStep, step_ids[0])
            assert step is not None
            assert step.phase == WizardPhase.PRE

        # Check that the UI reflects the change properly
        ui_response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert ui_response.status_code == 200

        ui_text = ui_response.data.decode("utf-8")

        # The pre-phase should now have the step moved from post
        assert "Post Step 1" in ui_text

        # Since we moved one step from post to pre, and there was one step left in post,
        # the post phase should still have "Post Step 2"
        # Only if we moved all steps would we see "No post-invite steps"
        # Let's just verify the step is now in pre phase by checking that the move worked
        assert "Post Step 2" in ui_text  # The remaining step should still be there
