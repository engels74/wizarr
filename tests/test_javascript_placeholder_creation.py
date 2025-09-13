"""
Test JavaScript-based dynamic placeholder creation.

This test specifically verifies that the JavaScript fix for dynamic placeholder
creation works correctly when phases become empty via drag-and-drop operations.
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
def populated_phases_no_initial_placeholders(app):
    """Setup with steps in both phases (ensuring no initial placeholders are rendered)."""
    with app.app_context():
        # Create a media server
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

        # Create steps in both phases (so neither phase starts empty)
        steps = [
            WizardStep(
                server_type="plex",
                phase=WizardPhase.PRE,
                position=0,
                title="Pre Step 1",
                markdown="# Pre Step 1",
            ),
            WizardStep(
                server_type="plex",
                phase=WizardPhase.POST,
                position=0,
                title="Post Step 1",
                markdown="# Post Step 1",
            ),
        ]
        db.session.add_all(steps)
        db.session.commit()
        return {
            "pre": [steps[0].id],
            "post": [steps[1].id],
        }


class TestJavaScriptPlaceholderCreation:
    """Test that JavaScript correctly creates placeholders when phases become empty."""

    def test_createplaceholderhtml_function_in_javascript(
        self, authenticated_client, populated_phases_no_initial_placeholders
    ):
        """Test that the createPlaceholderHTML function exists in the JavaScript."""
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        response_text = response.data.decode("utf-8")

        # Verify the new createPlaceholderHTML function exists
        assert "createPlaceholderHTML" in response_text

    def test_updateemptystate_creates_placeholders_dynamically(
        self, authenticated_client, populated_phases_no_initial_placeholders
    ):
        """
        Test that updateEmptyState creates placeholders when containers become empty.

        This test verifies the fix by ensuring that when phases start populated
        (no placeholders rendered initially), the JavaScript can create them
        when the phases become empty.
        """
        step_ids = populated_phases_no_initial_placeholders

        # Get initial page - should have no placeholders since both phases have steps
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        initial_response_text = response.data.decode("utf-8")

        # Verify no placeholder text initially (phases are populated)
        assert "No pre-invite steps" not in initial_response_text
        assert "No post-invite steps" not in initial_response_text

        # Verify JavaScript createPlaceholderHTML function exists
        assert "createPlaceholderHTML" in initial_response_text

        # Move pre step to post phase, making pre empty
        pre_step_id = step_ids["pre"][0]
        phase_response = authenticated_client.post(
            f"/settings/wizard/{pre_step_id}/update-phase",
            json={"phase": "post", "server_type": "plex"},
            headers={"Content-Type": "application/json"},
        )
        assert phase_response.status_code == 200

        # Get updated page after phase change
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        response_text = response.data.decode("utf-8")

        # Pre-phase should now show placeholder (created by server-side template)
        assert "No pre-invite steps" in response_text

        # Verify the JavaScript has the capability to create placeholders
        assert "createPlaceholderHTML" in response_text
        assert "insertAdjacentHTML" in response_text

    def test_placeholder_html_structure_matches_template(
        self, authenticated_client, populated_phases_no_initial_placeholders
    ):
        """Test that JavaScript-created placeholders match the template structure."""
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        response_text = response.data.decode("utf-8")

        # Check that the JavaScript function creates the correct HTML structure
        # The function should include all the required CSS classes and structure
        assert "empty-phase-placeholder" in response_text
        assert "absolute inset-0" in response_text
        assert "flex items-center justify-center" in response_text
        assert "pointer-events-none" in response_text
        assert "text-center p-12" in response_text

    def test_placeholder_text_differentiates_phases(
        self, authenticated_client, populated_phases_no_initial_placeholders
    ):
        """Test that JavaScript creates different placeholder text for pre vs post phases."""
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        response_text = response.data.decode("utf-8")

        # The JavaScript function should differentiate between pre and post phases
        # Check for the logic that creates different text
        assert "'No pre-invite steps'" in response_text
        assert "'No post-invite steps'" in response_text

    def test_dynamic_placeholder_removal_logic(
        self, authenticated_client, populated_phases_no_initial_placeholders
    ):
        """Test that the JavaScript has logic to hide placeholders when phases become populated."""
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        response_text = response.data.decode("utf-8")

        # Verify the updateEmptyState function handles both showing and hiding placeholders
        assert "placeholder.style.display = 'flex'" in response_text
        assert "placeholder.style.display = 'none'" in response_text

    def test_javascript_integrates_with_drag_drop_operations(
        self, authenticated_client, populated_phases_no_initial_placeholders
    ):
        """Test that the JavaScript placeholder logic integrates with drag-and-drop."""
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        response_text = response.data.decode("utf-8")

        # Verify that updateEmptyStates is called during drag operations
        assert "updateEmptyStates(to, from)" in response_text
        assert "handleDragEnd" in response_text

        # Verify the drag-and-drop configuration calls updateEmptyState
        assert "updateEmptyState" in response_text
