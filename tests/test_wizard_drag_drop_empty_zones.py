"""
Comprehensive tests for wizard step drag-and-drop functionality, focusing on empty drop zones.

This test suite follows TDD methodology and covers:
1. Empty drop zones accepting dragged items
2. Populated drop zones functionality
3. Cross-section dragging between pre/post phases
4. CSS styling and pointer events handling
5. Edge cases and error scenarios
"""

import pytest
from sqlalchemy import select

from app import create_app
from app.extensions import db
from app.models import AdminAccount, WizardPhase, WizardStep


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
        from app.models import MediaServer

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


@pytest.fixture
def pre_only_setup(app):
    """Setup with steps only in pre-invite phase."""
    with app.app_context():
        # Create a media server so the wizard steps page shows content
        from app.models import MediaServer

        media_server = MediaServer(
            name="Test Jellyfin Server",
            server_type="jellyfin",
            url="http://localhost:8096",
            api_key="test-key",
        )
        db.session.add(media_server)

        # Clear existing steps
        stmt = select(WizardStep).where(WizardStep.server_type == "jellyfin")
        existing_steps = db.session.execute(stmt).scalars().all()
        for step in existing_steps:
            db.session.delete(step)
        db.session.commit()

        # Create pre-phase steps only
        steps = [
            WizardStep(
                server_type="jellyfin",
                phase=WizardPhase.PRE,
                position=0,
                title="Pre Step 1",
                markdown="# Pre Step 1",
            ),
            WizardStep(
                server_type="jellyfin",
                phase=WizardPhase.PRE,
                position=1,
                title="Pre Step 2",
                markdown="# Pre Step 2",
            ),
        ]
        db.session.add_all(steps)
        db.session.commit()
        return [step.id for step in steps]


@pytest.fixture
def post_only_setup(app):
    """Setup with steps only in post-invite phase."""
    with app.app_context():
        # Create a media server so the wizard steps page shows content
        from app.models import MediaServer

        media_server = MediaServer(
            name="Test Emby Server",
            server_type="emby",
            url="http://localhost:8096",
            api_key="test-key",
        )
        db.session.add(media_server)

        # Clear existing steps
        stmt = select(WizardStep).where(WizardStep.server_type == "emby")
        existing_steps = db.session.execute(stmt).scalars().all()
        for step in existing_steps:
            db.session.delete(step)
        db.session.commit()

        # Create post-phase steps only
        steps = [
            WizardStep(
                server_type="emby",
                phase=WizardPhase.POST,
                position=0,
                title="Post Step 1",
                markdown="# Post Step 1",
            ),
        ]
        db.session.add_all(steps)
        db.session.commit()
        return [step.id for step in steps]


class TestEmptyDropZoneRendering:
    """Test how empty drop zones are rendered in the HTML."""

    def test_empty_phases_render_placeholder_elements(
        self, authenticated_client, empty_phases_setup
    ):
        """Test that empty phases render placeholder elements with correct classes."""
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

    def test_empty_placeholder_has_pointer_events_none(
        self, authenticated_client, empty_phases_setup
    ):
        """Test that empty placeholders no longer have pointer-events: none in CSS (fixed)."""
        _ = empty_phases_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        # Check that the CSS class exists but pointer-events: none has been removed
        response_text = response.data.decode("utf-8")
        assert ".empty-phase-placeholder" in response_text

        # Verify pointer-events: none has been removed from the CSS rule
        css_rule_start = response_text.find(".empty-phase-placeholder {")
        assert css_rule_start != -1, "CSS rule for .empty-phase-placeholder not found"
        css_rule_end = response_text.find("}", css_rule_start)
        css_rule_block = response_text[css_rule_start : css_rule_end + 1]
        assert "pointer-events: none" not in css_rule_block

    def test_populated_phase_hides_placeholder(
        self, authenticated_client, pre_only_setup
    ):
        """Test that populated phases hide the placeholder element."""
        _ = pre_only_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Check for pre-phase section (should have steps, not empty)
        assert 'data-phase="pre" data-server="jellyfin"' in response_text
        # Pre-phase should NOT be empty since we have steps
        jellyfin_pre_start = response_text.find(
            'data-phase="pre" data-server="jellyfin"'
        )
        if jellyfin_pre_start != -1:
            # Look for class definition around this area to check it's not empty
            pre_section = response_text[
                jellyfin_pre_start - 200 : jellyfin_pre_start + 200
            ]
            assert (
                "wizard-steps empty" not in pre_section
                and "empty wizard-steps" not in pre_section
            )

        # Check that actual steps are rendered
        assert "step-item" in response_text

        # Check for post-phase section (should be empty)
        assert 'data-phase="post" data-server="jellyfin"' in response_text

        # Check for empty placeholder in post-phase only
        assert "empty-phase-placeholder" in response_text


class TestEmptyDropZoneFunctionality:
    """Test the functional behavior of empty drop zones."""

    def test_drag_to_empty_pre_phase_backend(
        self, authenticated_client, post_only_setup
    ):
        """Test dragging a step to empty pre-phase (backend API calls)."""
        step_ids = post_only_setup
        step_id = step_ids[0]

        # Simulate drag-and-drop: update phase first
        phase_response = authenticated_client.post(
            f"/settings/wizard/{step_id}/update-phase",
            json={"phase": "pre", "server_type": "emby"},
            headers={"Content-Type": "application/json"},
        )
        assert phase_response.status_code == 200

        # Then reorder in new phase
        reorder_response = authenticated_client.post(
            "/settings/wizard/reorder",
            json={"ids": [step_id], "server_type": "emby", "phase": "pre"},
            headers={"Content-Type": "application/json"},
        )
        assert reorder_response.status_code == 200

        # Verify step moved to pre-phase
        with authenticated_client.application.app_context():
            step = db.session.get(WizardStep, step_id)
            assert step is not None
            assert step.phase == WizardPhase.PRE
            assert step.position == 0

    def test_drag_to_empty_post_phase_backend(
        self, authenticated_client, pre_only_setup
    ):
        """Test dragging a step to empty post-phase (backend API calls)."""
        step_ids = pre_only_setup
        step_id = step_ids[0]  # Take first pre-phase step

        # Simulate drag-and-drop: update phase first
        phase_response = authenticated_client.post(
            f"/settings/wizard/{step_id}/update-phase",
            json={"phase": "post", "server_type": "jellyfin"},
            headers={"Content-Type": "application/json"},
        )
        assert phase_response.status_code == 200

        # Then reorder in new phase
        reorder_response = authenticated_client.post(
            "/settings/wizard/reorder",
            json={"ids": [step_id], "server_type": "jellyfin", "phase": "post"},
            headers={"Content-Type": "application/json"},
        )
        assert reorder_response.status_code == 200

        # Verify step moved to post-phase
        with authenticated_client.application.app_context():
            step = db.session.get(WizardStep, step_id)
            assert step is not None
            assert step.phase == WizardPhase.POST
            assert step.position == 0


class TestDropZoneStyling:
    """Test CSS styling and visual aspects of drop zones."""

    def test_drop_zone_classes_present(self, authenticated_client, empty_phases_setup):
        """Test that drop zones have the correct CSS classes."""
        _ = empty_phases_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Check for drop zone containers
        assert (
            'class="drop-zone"' in response_text or "class='drop-zone'" in response_text
        )

        # Each drop zone should have data attributes
        assert 'data-phase="pre"' in response_text
        assert 'data-phase="post"' in response_text
        assert "data-server" in response_text

    def test_wizard_steps_container_classes(
        self, authenticated_client, empty_phases_setup
    ):
        """Test that wizard-steps containers have correct classes."""
        _ = empty_phases_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Check for wizard-steps containers
        assert "wizard-steps" in response_text

        # Empty containers should have 'empty' class when placeholder is present
        if "empty-phase-placeholder" in response_text:
            assert (
                "wizard-steps empty" in response_text
                or "empty wizard-steps" in response_text
            )


class TestCrossPhaseDragDrop:
    """Test dragging steps between pre and post phases."""

    def test_cross_phase_drag_maintains_positions(
        self, authenticated_client, pre_only_setup
    ):
        """Test that cross-phase dragging maintains correct positions."""
        step_ids = pre_only_setup

        # Move second pre-step to post-phase
        step_id = step_ids[1]

        phase_response = authenticated_client.post(
            f"/settings/wizard/{step_id}/update-phase",
            json={"phase": "post", "server_type": "jellyfin"},
            headers={"Content-Type": "application/json"},
        )
        assert phase_response.status_code == 200

        # Verify positions are correct
        with authenticated_client.application.app_context():
            # Remaining pre-step should be at position 0
            remaining_pre = db.session.get(WizardStep, step_ids[0])
            assert remaining_pre is not None
            assert remaining_pre.phase == WizardPhase.PRE
            assert remaining_pre.position == 0

            # Moved step should be at position 0 in post-phase
            moved_step = db.session.get(WizardStep, step_id)
            assert moved_step is not None
            assert moved_step.phase == WizardPhase.POST
            assert moved_step.position == 0


class TestEdgeCases:
    """Test edge cases and error scenarios."""

    def test_empty_reorder_request(self, authenticated_client):
        """Test reordering with empty step list."""
        response = authenticated_client.post(
            "/settings/wizard/reorder",
            json={"ids": [], "server_type": "plex", "phase": "pre"},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200

    def test_invalid_phase_in_reorder(self, authenticated_client):
        """Test reordering with invalid phase."""
        response = authenticated_client.post(
            "/settings/wizard/reorder",
            json={"ids": [1], "server_type": "plex", "phase": "invalid"},
            headers={"Content-Type": "application/json"},
        )
        # Should still work as phase defaults to "post"
        assert response.status_code == 200

    def test_nonexistent_step_phase_update(self, authenticated_client):
        """Test updating phase of non-existent step."""
        response = authenticated_client.post(
            "/settings/wizard/99999/update-phase",
            json={"phase": "post", "server_type": "plex"},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 404


class TestPointerEventsIssue:
    """Test the specific pointer-events issue that prevents drag-and-drop."""

    def test_empty_placeholder_blocks_drop_events(
        self, authenticated_client, empty_phases_setup
    ):
        """Test that empty placeholders no longer block drop events (fixed)."""
        _ = empty_phases_setup  # Setup ensures empty phases
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        # This test verifies the fix - pointer-events: none has been removed
        # from .empty-phase-placeholder so drag-and-drop events can reach the sortable container
        response_text = response.data.decode("utf-8")

        # Verify the CSS class exists but the problematic rule has been removed
        assert ".empty-phase-placeholder" in response_text

        # Verify pointer-events: none has been removed from the CSS rule
        css_rule_start = response_text.find(".empty-phase-placeholder {")
        assert css_rule_start != -1, "CSS rule for .empty-phase-placeholder not found"
        css_rule_end = response_text.find("}", css_rule_start)
        css_rule_block = response_text[css_rule_start : css_rule_end + 1]
        assert "pointer-events: none" not in css_rule_block

        # The fix allows drag-and-drop events to reach the sortable container
        # even when the placeholder covers the drop zone area

    def test_sortable_containers_have_correct_attributes(
        self, authenticated_client, empty_phases_setup
    ):
        """Test that sortable containers have the required data attributes."""
        _ = empty_phases_setup  # Setup ensures empty phases
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Check for sortable containers with required attributes
        assert "wizard-steps" in response_text

        # Each container should have required data attributes for Sortable.js
        assert "data-server" in response_text
        assert 'data-phase="pre"' in response_text
        assert 'data-phase="post"' in response_text
        assert "data-reorder-url" in response_text


class TestJavaScriptIntegration:
    """Test JavaScript integration aspects that can be verified server-side."""

    def test_wizard_steps_js_included(self, authenticated_client, empty_phases_setup):
        """Test that the inline JavaScript functions are included in the page."""
        _ = empty_phases_setup  # Setup ensures empty phases
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Check that the wizard-steps.js script is included
        assert 'src="/static/js/wizard-steps.js"' in response_text or 'wizard-steps.js' in response_text

        # Verify that functions are not duplicated as actual inline implementations
        # (Function signatures in comments for test compatibility are allowed)
        import re
        # Remove comment blocks first, then check for actual function implementations
        text_without_comments = re.sub(r'/\*.*?\*/', '', response_text, flags=re.DOTALL)
        actual_function_pattern = r'^\s*function\s+updateEmptyState\s*\('
        assert not re.search(actual_function_pattern, text_without_comments, re.MULTILINE)

        # The functions should be available from the external script, not implemented inline

    def test_sortable_group_configuration(
        self, authenticated_client, empty_phases_setup
    ):
        """Test that sortable containers are configured for cross-phase dragging."""
        # This test verifies the HTML structure that JavaScript will use
        server_type = empty_phases_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Should have at least pre and post containers for the server
        assert f'data-phase="pre" data-server="{server_type}"' in response_text
        assert f'data-phase="post" data-server="{server_type}"' in response_text

        # Check for wizard-steps containers
        assert "wizard-steps" in response_text
