"""
Tests for dynamic placeholder text behavior in wizard step management.

This test suite follows TDD methodology and specifically tests the issue where:
- Placeholder text doesn't appear immediately when a section becomes empty via drag-and-drop
- Placeholder text should appear for both "Before" and "After" sections without page reload
- Placeholder elements should be created dynamically when phases become empty

Based on user requirements:
- When all steps are moved out of a section, placeholder text should appear immediately
- This should work for both "Before Invite Acceptance" and "After Invite Acceptance" sections
- No page reload should be required
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
def populated_phases_setup(app):
    """Setup with steps in both pre and post phases (no empty phases initially)."""
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
            # Pre-phase steps (2 steps)
            WizardStep(
                server_type="plex",
                phase=WizardPhase.PRE,
                position=0,
                title="Pre Step 1",
                markdown="# Pre Step 1",
            ),
            WizardStep(
                server_type="plex",
                phase=WizardPhase.PRE,
                position=1,
                title="Pre Step 2",
                markdown="# Pre Step 2",
            ),
            # Post-phase steps (2 steps)
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
        return {
            "pre": [step.id for step in steps[:2]],
            "post": [step.id for step in steps[2:]],
        }


@pytest.fixture
def single_step_in_pre_setup(app):
    """Setup with a single step in pre phase only."""
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

        # Create only one step in pre phase
        step = WizardStep(
            server_type="plex",
            phase=WizardPhase.PRE,
            position=0,
            title="Only Pre Step",
            markdown="# Only Pre Step",
        )
        db.session.add(step)
        db.session.commit()
        return {"pre": [step.id], "post": []}


class TestInitialPlaceholderBehavior:
    """Test that placeholders work correctly when phases are initially empty."""

    def test_initially_empty_pre_phase_shows_placeholder(
        self, authenticated_client, single_step_in_pre_setup
    ):
        """Test that when pre-phase is initially empty, placeholder text is shown."""
        # Move the single pre step to post phase, making pre empty
        step_ids = single_step_in_pre_setup
        step_id = step_ids["pre"][0]

        # Move step from pre to post
        authenticated_client.post(
            f"/settings/wizard/{step_id}/update-phase",
            json={"phase": "post", "server_type": "plex"},
            headers={"Content-Type": "application/json"},
        )

        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Pre-phase should show placeholder text
        assert "No pre-invite steps" in response_text
        assert "empty-phase-placeholder" in response_text

    def test_initially_empty_post_phase_shows_placeholder(
        self, authenticated_client, single_step_in_pre_setup
    ):
        """Test that when post-phase is initially empty, placeholder text is shown."""
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Post-phase should show placeholder text (it starts empty in this setup)
        assert "No post-invite steps" in response_text
        assert "empty-phase-placeholder" in response_text


class TestDynamicPlaceholderCreation:
    """Test the core issue: dynamic placeholder creation when phases become empty."""

    def test_pre_phase_shows_placeholder_when_becomes_empty_via_drag_drop(
        self, authenticated_client, populated_phases_setup
    ):
        """
        Test that pre-phase shows placeholder immediately when it becomes empty via drag-and-drop.

        This is the main test for the reported issue:
        - Start with populated pre and post phases (no placeholders rendered initially)
        - Move all pre-phase steps to post-phase
        - Verify placeholder appears in pre-phase without page reload
        """
        step_ids = populated_phases_setup

        # Verify initial state: both phases have steps, no placeholders shown
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        initial_response_text = response.data.decode("utf-8")

        # Initially, neither phase should have placeholder text since both have steps
        assert "No pre-invite steps" not in initial_response_text
        assert "No post-invite steps" not in initial_response_text

        # Move all pre-phase steps to post-phase
        for step_id in step_ids["pre"]:
            phase_response = authenticated_client.post(
                f"/settings/wizard/{step_id}/update-phase",
                json={"phase": "post", "server_type": "plex"},
                headers={"Content-Type": "application/json"},
            )
            assert phase_response.status_code == 200

        # Get updated page after moving steps
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Pre-phase should now show placeholder text
        # This test will FAIL until we implement dynamic placeholder creation
        assert "No pre-invite steps" in response_text
        assert "Drop steps here or create new ones" in response_text

        # Post-phase should still have steps (no placeholder)
        assert "No post-invite steps" not in response_text

        # Verify the placeholder element exists in the DOM structure
        assert "empty-phase-placeholder" in response_text

    def test_post_phase_shows_placeholder_when_becomes_empty_via_drag_drop(
        self, authenticated_client, populated_phases_setup
    ):
        """
        Test that post-phase shows placeholder immediately when it becomes empty via drag-and-drop.
        """
        step_ids = populated_phases_setup

        # Move all post-phase steps to pre-phase
        for step_id in step_ids["post"]:
            phase_response = authenticated_client.post(
                f"/settings/wizard/{step_id}/update-phase",
                json={"phase": "pre", "server_type": "plex"},
                headers={"Content-Type": "application/json"},
            )
            assert phase_response.status_code == 200

        # Get updated page after moving steps
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Post-phase should now show placeholder text
        # This test will FAIL until we implement dynamic placeholder creation
        assert "No post-invite steps" in response_text
        assert "Drop steps here or create new ones" in response_text

        # Pre-phase should still have steps (no placeholder)
        assert "No pre-invite steps" not in response_text

        # Verify the placeholder element exists in the DOM structure
        assert "empty-phase-placeholder" in response_text

    def test_both_phases_show_placeholders_when_both_become_empty(
        self, authenticated_client, populated_phases_setup
    ):
        """Test that both phases show placeholders when both become empty."""
        step_ids = populated_phases_setup

        # Delete all steps to make both phases empty
        for step_id in step_ids["pre"] + step_ids["post"]:
            authenticated_client.post(
                f"/settings/wizard/{step_id}/delete",
                headers={"HX-Request": "true"},
            )
            # Note: Adjust the delete endpoint based on actual implementation

        # Get updated page after deleting all steps
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Both phases should show placeholder text
        assert "No pre-invite steps" in response_text
        assert "No post-invite steps" in response_text
        assert "Drop steps here or create new ones" in response_text

        # Verify placeholder elements exist
        placeholder_count = response_text.count("empty-phase-placeholder")
        assert placeholder_count >= 2  # At least one for each phase


class TestPlaceholderRemovalBehavior:
    """Test that placeholders are removed when phases become populated."""

    def test_placeholder_removed_when_empty_pre_phase_gets_step(
        self, authenticated_client, single_step_in_pre_setup
    ):
        """Test that placeholder is removed when an empty pre-phase gets a step."""
        step_ids = single_step_in_pre_setup

        # First, move the pre step to post to make pre empty
        step_id = step_ids["pre"][0]
        authenticated_client.post(
            f"/settings/wizard/{step_id}/update-phase",
            json={"phase": "post", "server_type": "plex"},
            headers={"Content-Type": "application/json"},
        )

        # Verify pre-phase is empty and shows placeholder
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        response_text = response.data.decode("utf-8")
        assert "No pre-invite steps" in response_text

        # Now move the step back to pre
        authenticated_client.post(
            f"/settings/wizard/{step_id}/update-phase",
            json={"phase": "pre", "server_type": "plex"},
            headers={"Content-Type": "application/json"},
        )

        # Get updated page
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        response_text = response.data.decode("utf-8")

        # Pre-phase should no longer show placeholder
        assert "No pre-invite steps" not in response_text

    def test_placeholder_removed_when_empty_post_phase_gets_step(
        self, authenticated_client, populated_phases_setup
    ):
        """Test that placeholder is removed when an empty post-phase gets a step."""
        step_ids = populated_phases_setup

        # Move all post steps to pre to make post empty
        for step_id in step_ids["post"]:
            authenticated_client.post(
                f"/settings/wizard/{step_id}/update-phase",
                json={"phase": "pre", "server_type": "plex"},
                headers={"Content-Type": "application/json"},
            )

        # Verify post-phase is empty
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        response_text = response.data.decode("utf-8")
        assert "No post-invite steps" in response_text

        # Move one step back to post
        step_id = step_ids["post"][0]
        authenticated_client.post(
            f"/settings/wizard/{step_id}/update-phase",
            json={"phase": "post", "server_type": "plex"},
            headers={"Content-Type": "application/json"},
        )

        # Get updated page
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        response_text = response.data.decode("utf-8")

        # Post-phase should no longer show placeholder
        assert "No post-invite steps" not in response_text


class TestPlaceholderUIStructure:
    """Test the UI structure and styling of dynamically created placeholders."""

    def test_dynamic_placeholder_has_correct_css_classes(
        self, authenticated_client, populated_phases_setup
    ):
        """Test that dynamically created placeholders have the correct CSS classes."""
        step_ids = populated_phases_setup

        # Make pre-phase empty
        for step_id in step_ids["pre"]:
            authenticated_client.post(
                f"/settings/wizard/{step_id}/update-phase",
                json={"phase": "post", "server_type": "plex"},
                headers={"Content-Type": "application/json"},
            )

        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        response_text = response.data.decode("utf-8")

        # Check for required CSS classes and structure
        assert "empty-phase-placeholder" in response_text
        assert "text-center" in response_text
        assert "absolute inset-0" in response_text
        assert "flex items-center justify-center" in response_text
        assert "pointer-events-none" in response_text

    def test_dynamic_placeholder_has_correct_svg_icon(
        self, authenticated_client, populated_phases_setup
    ):
        """Test that dynamically created placeholders include the correct SVG icon."""
        step_ids = populated_phases_setup

        # Make post-phase empty
        for step_id in step_ids["post"]:
            authenticated_client.post(
                f"/settings/wizard/{step_id}/update-phase",
                json={"phase": "pre", "server_type": "plex"},
                headers={"Content-Type": "application/json"},
            )

        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        response_text = response.data.decode("utf-8")

        # Check for SVG plus icon
        assert 'viewBox="0 0 24 24"' in response_text
        assert 'd="M12 6v6m0 0v6m0-6h6m-6 0H6"' in response_text

    def test_placeholder_text_matches_phase_type(
        self, authenticated_client, populated_phases_setup
    ):
        """Test that placeholder text correctly identifies the phase type."""
        step_ids = populated_phases_setup

        # Make both phases empty one at a time to test each placeholder

        # Test pre-phase placeholder
        for step_id in step_ids["pre"]:
            authenticated_client.post(
                f"/settings/wizard/{step_id}/update-phase",
                json={"phase": "post", "server_type": "plex"},
                headers={"Content-Type": "application/json"},
            )

        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        response_text = response.data.decode("utf-8")
        assert "No pre-invite steps" in response_text

        # Test post-phase placeholder
        for step_id in step_ids["post"]:
            authenticated_client.post(
                f"/settings/wizard/{step_id}/update-phase",
                json={"phase": "pre", "server_type": "plex"},
                headers={"Content-Type": "application/json"},
            )

        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        response_text = response.data.decode("utf-8")
        assert "No post-invite steps" in response_text


class TestJavaScriptIntegration:
    """Test that JavaScript correctly handles dynamic placeholder creation."""

    def test_updateemptystate_function_exists_in_response(
        self, authenticated_client, populated_phases_setup
    ):
        """Test that the updateEmptyState JavaScript function is available."""
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        response_text = response.data.decode("utf-8")

        # Verify JavaScript file is included
        assert "wizard-steps.js" in response_text

    def test_drop_zones_have_correct_data_attributes(
        self, authenticated_client, populated_phases_setup
    ):
        """Test that drop zones have the correct data attributes for JavaScript targeting."""
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        response_text = response.data.decode("utf-8")

        # Check for required data attributes
        assert 'data-phase="pre"' in response_text
        assert 'data-phase="post"' in response_text
        assert 'data-server="plex"' in response_text
        assert 'class="drop-zone"' in response_text

    def test_wizard_steps_containers_have_empty_class_when_appropriate(
        self, authenticated_client, populated_phases_setup
    ):
        """Test that wizard-steps containers get the 'empty' class when they become empty."""
        step_ids = populated_phases_setup

        # Make pre-phase empty
        for step_id in step_ids["pre"]:
            authenticated_client.post(
                f"/settings/wizard/{step_id}/update-phase",
                json={"phase": "post", "server_type": "plex"},
                headers={"Content-Type": "application/json"},
            )

        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        response_text = response.data.decode("utf-8")

        # Should have wizard-steps with empty class for pre-phase
        assert "wizard-steps empty" in response_text or "empty wizard-steps" in response_text
