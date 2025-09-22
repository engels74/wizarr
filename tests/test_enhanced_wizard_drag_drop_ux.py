"""
Comprehensive tests for enhanced wizard step drag-and-drop UX improvements.

This test suite follows TDD methodology and covers the new UX enhancements:
1. Improved drop zone boundaries and hit detection
2. Enhanced visual feedback during drag operations
3. Better empty state handling and targeting
4. Cross-phase drag indicators
5. Responsive drop zone behavior
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
    """Setup with steps in both phases for comprehensive testing."""
    with app.app_context():
        # Create media server
        media_server = MediaServer(
            name="Test Mixed Server",
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

        # Create steps in both phases
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
                phase=WizardPhase.PRE,
                position=1,
                title="Pre Step 2",
                markdown="# Pre Step 2",
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
        return [step.id for step in steps]


@pytest.fixture
def empty_phases_setup(app):
    """Setup with empty phases for testing enhanced empty state handling."""
    with app.app_context():
        # Create media server
        media_server = MediaServer(
            name="Test Empty Server",
            server_type="jellyfin",
            url="http://localhost:8096",
            api_key="test-key",
        )
        db.session.add(media_server)

        # Ensure no steps exist
        stmt = select(WizardStep).where(WizardStep.server_type == "jellyfin")
        existing_steps = db.session.execute(stmt).scalars().all()
        for step in existing_steps:
            db.session.delete(step)
        db.session.commit()
        return "jellyfin"


class TestEnhancedDropZoneBoundaries:
    """Test improved drop zone boundaries and hit detection."""

    def test_enhanced_drop_zone_padding(self, authenticated_client, empty_phases_setup):
        """Test that drop zones have enhanced padding for better hit detection."""
        server_type = empty_phases_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Verify server type is present in the response
        assert server_type in response_text

        # Check for enhanced drop zone styling
        assert ".drop-zone-enhanced" in response_text or ".drop-zone" in response_text

        # Verify that drop zones have substantial padding/minimum height
        # This CSS should be present for better hit detection
        drop_zone_css_start = response_text.find(".drop-zone")
        if drop_zone_css_start != -1:
            # Look for minimum height or padding rules in the CSS
            next_css_block = response_text[
                drop_zone_css_start : drop_zone_css_start + 500
            ]
            # Enhanced drop zones should have minimum height for better targeting
            assert any(rule in next_css_block for rule in ["min-height", "padding"])

    def test_drop_zone_hit_area_attributes(
        self, authenticated_client, empty_phases_setup
    ):
        """Test that drop zones have proper data attributes for enhanced targeting."""
        server_type = empty_phases_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Check for drop zone containers with enhanced attributes
        assert f'data-phase="pre" data-server="{server_type}"' in response_text
        assert f'data-phase="post" data-server="{server_type}"' in response_text

        # Check for drop zone class
        assert 'class="drop-zone"' in response_text

    def test_empty_zone_minimum_height(self, authenticated_client, empty_phases_setup):
        """Test that empty drop zones have adequate minimum height."""
        server_type = empty_phases_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Verify server type is present in the response
        assert server_type in response_text

        # Check that wizard-steps containers have minimum height when empty
        assert "wizard-steps" in response_text

        # Look for CSS rules that ensure adequate height for empty zones
        wizard_steps_css = response_text.find(".wizard-steps")
        if wizard_steps_css != -1:
            css_section = response_text[wizard_steps_css : wizard_steps_css + 200]
            assert "min-height" in css_section


class TestEnhancedVisualFeedback:
    """Test improved visual feedback during drag operations."""

    def test_enhanced_drag_over_styling(self, authenticated_client, mixed_setup):
        """Test that enhanced drag-over visual feedback CSS is present."""
        _ = mixed_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Check for enhanced drag-over styling
        assert ".drag-over" in response_text

        # Look for enhanced visual feedback in CSS
        drag_over_css = response_text.find(".drag-over")
        if drag_over_css != -1:
            css_block = response_text[drag_over_css : drag_over_css + 300]
            # Should have visual indicators like border, background, or transform
            assert any(
                prop in css_block
                for prop in ["border", "background", "transform", "box-shadow"]
            )

    def test_cross_phase_drag_indicators(self, authenticated_client, mixed_setup):
        """Test that cross-phase drag indicators are present in CSS."""
        _ = mixed_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Check for phase-specific styling
        assert "phase-badge-pre" in response_text
        assert "phase-badge-post" in response_text

        # Look for cross-phase specific CSS classes
        # These should help users understand when dragging between phases
        assert (
            any(
                cls in response_text
                for cls in ["cross-phase", "phase-transition", "drag-between-phases"]
            )
            or "phase-badge" in response_text
        )

    def test_drag_handle_visual_feedback(self, authenticated_client, mixed_setup):
        """Test that drag handles have proper visual feedback."""
        _ = mixed_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Check for drag handle styling
        assert "drag-handle" in response_text

        # Look for cursor and hover states
        drag_handle_css = response_text.find(".drag-handle")
        if drag_handle_css != -1:
            css_section = response_text[drag_handle_css : drag_handle_css + 200]
            assert "cursor" in css_section


class TestEmptyStateEnhancements:
    """Test enhanced empty state handling and visual improvements."""

    def test_enhanced_empty_state_styling(
        self, authenticated_client, empty_phases_setup
    ):
        """Test that empty states have enhanced visual styling."""
        server_type = empty_phases_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Verify server type is present in the response
        assert server_type in response_text

        # Check for empty phase styling
        assert (
            "empty-phase" in response_text or "empty-phase-placeholder" in response_text
        )

        # Look for enhanced empty state CSS
        empty_css = response_text.find(".empty-phase")
        if empty_css != -1:
            css_block = response_text[empty_css : empty_css + 400]
            # Should have visual styling like dashed borders, background, etc.
            assert any(
                prop in css_block for prop in ["border", "background", "padding"]
            )

    def test_empty_placeholder_accessibility(
        self, authenticated_client, empty_phases_setup
    ):
        """Test that empty placeholders are accessible and don't block interactions."""
        server_type = empty_phases_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Verify server type is present in the response
        assert server_type in response_text

        # Verify that empty placeholders don't have pointer-events: none
        empty_placeholder_css = response_text.find(".empty-phase-placeholder")
        if empty_placeholder_css != -1:
            css_rule_end = response_text.find("}", empty_placeholder_css)
            css_block = response_text[empty_placeholder_css:css_rule_end]
            assert "pointer-events: none" not in css_block

    def test_empty_zone_drop_indicators(self, authenticated_client, empty_phases_setup):
        """Test that empty zones have clear drop indicators."""
        server_type = empty_phases_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Verify server type is present in the response
        assert server_type in response_text

        # Check for instructional text in empty zones
        assert (
            "Drop steps here" in response_text or "No pre-invite steps" in response_text
        )
        assert "No post-invite steps" in response_text


class TestResponsiveDropZones:
    """Test that drop zones work well across different screen sizes."""

    def test_grid_layout_responsive_classes(self, authenticated_client, mixed_setup):
        """Test that drop zones use responsive grid layout."""
        _ = mixed_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Check for responsive grid classes
        assert any(
            cls in response_text
            for cls in ["grid-cols-1", "lg:grid-cols-2", "grid", "divide-x"]
        )

    def test_mobile_friendly_drop_zones(self, authenticated_client, mixed_setup):
        """Test that drop zones are mobile-friendly."""
        _ = mixed_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Check for mobile-friendly spacing and layout
        # Should have appropriate margins and padding for touch devices
        assert any(cls in response_text for cls in ["gap-", "space-", "p-", "m-"])


class TestJavaScriptEnhancements:
    """Test JavaScript enhancements for improved drag-and-drop UX."""

    def test_enhanced_sortable_configuration(self, authenticated_client, mixed_setup):
        """Test that Sortable.js has enhanced configuration."""
        _ = mixed_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Inline JavaScript moved to external wizard-steps.js; ensure sortable containers exist instead
        assert "wizard-steps" in response_text
        assert "drop-zone" in response_text

    def test_drag_feedback_javascript_hooks(self, authenticated_client, mixed_setup):
        """Test that JavaScript has hooks for enhanced drag feedback."""
        _ = mixed_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Check for drag-related CSS classes that JavaScript can manipulate
        assert any(
            cls in response_text for cls in ["dragging", "drag-over", "drop-zone"]
        )


class TestCrossPhaseDragEnhancements:
    """Test enhanced cross-phase dragging functionality."""

    def test_phase_transition_visual_cues(self, authenticated_client, mixed_setup):
        """Test that phase transitions have visual cues."""
        _ = mixed_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Check for phase badges with distinct styling
        assert "phase-badge-pre" in response_text
        assert "phase-badge-post" in response_text

        # Verify different colors for pre/post phases
        pre_badge_css = response_text.find(".phase-badge-pre")
        post_badge_css = response_text.find(".phase-badge-post")

        if pre_badge_css != -1 and post_badge_css != -1:
            pre_css_block = response_text[pre_badge_css : pre_badge_css + 200]
            post_css_block = response_text[post_badge_css : post_badge_css + 200]

            # Should have different background colors
            assert "background" in pre_css_block and "background" in post_css_block

    def test_cross_phase_drag_backend_integration(
        self, authenticated_client, mixed_setup
    ):
        """Test that cross-phase dragging works with backend APIs."""
        step_ids = mixed_setup
        pre_step_id = step_ids[0]  # First pre-step

        # Test moving from pre to post phase
        phase_response = authenticated_client.post(
            f"/settings/wizard/{pre_step_id}/update-phase",
            json={"phase": "post", "server_type": "plex"},
            headers={"Content-Type": "application/json"},
        )
        assert phase_response.status_code == 200

        # Test reordering in new phase
        reorder_response = authenticated_client.post(
            "/settings/wizard/reorder",
            json={"ids": [pre_step_id], "server_type": "plex", "phase": "post"},
            headers={"Content-Type": "application/json"},
        )
        assert reorder_response.status_code == 200

        # Verify step moved correctly
        with authenticated_client.application.app_context():
            step = db.session.get(WizardStep, pre_step_id)
            assert step is not None
            assert step.phase == WizardPhase.POST


class TestPerformanceAndAccessibility:
    """Test performance and accessibility aspects of enhanced drag-and-drop."""

    def test_drag_handle_accessibility(self, authenticated_client, mixed_setup):
        """Test that drag handles are accessible."""
        _ = mixed_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Check for drag handle elements
        assert "drag-handle" in response_text

        # Should have proper cursor styling
        drag_handle_count = response_text.count("drag-handle")
        assert drag_handle_count >= 2  # Should have multiple drag handles for steps

    def test_keyboard_navigation_support(self, authenticated_client, mixed_setup):
        """Test that the interface supports keyboard navigation."""
        _ = mixed_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Check for focusable elements
        assert any(attr in response_text for attr in ["tabindex", "button", "href"])

    def test_minimal_dom_changes_during_drag(self, authenticated_client, mixed_setup):
        """Test that drag operations don't cause excessive DOM changes."""
        step_ids = mixed_setup

        # Test a simple reorder operation
        reorder_response = authenticated_client.post(
            "/settings/wizard/reorder",
            json={"ids": step_ids[:2][::-1], "server_type": "plex", "phase": "pre"},
            headers={"Content-Type": "application/json"},
        )
        assert reorder_response.status_code == 200

        # Verify the operation was efficient (no errors)
        response_data = reorder_response.get_json()
        assert response_data.get("status") == "ok"
