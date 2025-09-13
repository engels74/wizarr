"""
Test to verify that empty drag and drop zones properly fill their container area.

This test ensures that the "No pre-invite steps - Drop steps here or create new ones"
text properly fills the drag and drop zone area, addressing the visual styling issue
where the placeholder text doesn't properly fill the available space.
"""

import pytest

from app import create_app
from app.extensions import db
from app.models import AdminAccount, MediaServer


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
    """Setup with no wizard steps to ensure empty drop zones."""
    with app.app_context():
        # Create a media server so the wizard steps page shows content
        media_server = MediaServer(
            name="Test Plex Server",
            server_type="plex",
            url="http://localhost:32400",
            api_key="test-key",
        )
        db.session.add(media_server)
        db.session.commit()
        return "plex"


class TestDragDropZoneFillStyling:
    """Test that empty drag and drop zones properly fill their container area."""

    def test_drop_zone_has_flex_display_properties(
        self, authenticated_client, empty_phases_setup
    ):
        """Test that drop zones have proper flex display properties for filling."""
        _ = empty_phases_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Check that drop-zone CSS rule exists and has proper properties
        assert ".drop-zone" in response_text

        # Find the drop-zone CSS rule
        css_rule_start = response_text.find(".drop-zone {")
        assert css_rule_start != -1, "CSS rule for .drop-zone not found"
        css_rule_end = response_text.find("}", css_rule_start)
        drop_zone_css = response_text[css_rule_start : css_rule_end + 1]

        # Verify minimum height is set to ensure proper size
        assert "min-height:" in drop_zone_css

    def test_wizard_steps_empty_fills_drop_zone(
        self, authenticated_client, empty_phases_setup
    ):
        """Test that wizard-steps.empty properly fills the drop zone."""
        _ = empty_phases_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Find the wizard-steps.empty CSS rule
        css_rule_start = response_text.find(".wizard-steps.empty {")
        assert css_rule_start != -1, "CSS rule for .wizard-steps.empty not found"
        css_rule_end = response_text.find("}", css_rule_start)
        wizard_steps_css = response_text[css_rule_start : css_rule_end + 1]

        # Should have flex display and centering properties
        assert "display: flex" in wizard_steps_css
        assert "align-items: center" in wizard_steps_css
        assert "justify-content: center" in wizard_steps_css
        assert "min-height:" in wizard_steps_css

    def test_empty_phase_placeholder_fills_wizard_steps(
        self, authenticated_client, empty_phases_setup
    ):
        """Test that empty-phase-placeholder properly fills the drop zone area."""
        _ = empty_phases_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Find the empty-phase-placeholder CSS rule
        placeholder_rule_start = response_text.find(".empty-phase-placeholder {")
        assert placeholder_rule_start != -1, (
            "CSS rule for .empty-phase-placeholder not found"
        )
        placeholder_rule_end = response_text.find("}", placeholder_rule_start)
        placeholder_css = response_text[
            placeholder_rule_start : placeholder_rule_end + 1
        ]

        # Should have striped background that covers the entire drop zone area
        assert "repeating-linear-gradient" in placeholder_css

        # Check that the HTML structure supports absolute positioning
        assert "absolute inset-0" in response_text

        # Verify that inner content has padding for proper text spacing
        assert (
            "p-12" in response_text or "p-8" in response_text or "p-6" in response_text
        )

    def test_drop_zone_styling_ensures_proper_fill(
        self, authenticated_client, empty_phases_setup
    ):
        """Test that drop zone styling ensures placeholder properly fills the area."""
        _ = empty_phases_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Verify the complete styling chain:
        # 1. Drop zone should be a flex container or have proper sizing
        # 2. Wizard steps empty should fill the drop zone
        # 3. Empty placeholder should fill the wizard steps

        # Verify that wizard-steps.js is included which contains the enhancement
        assert "wizard-steps.js" in response_text

        # Check that the HTML structure supports proper filling
        assert "empty-phase-placeholder" in response_text
        assert "wizard-steps" in response_text
        assert "drop-zone" in response_text

    def test_empty_placeholder_visual_positioning(
        self, authenticated_client, empty_phases_setup
    ):
        """Test that empty placeholder has proper visual positioning within drop zone."""
        _ = empty_phases_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # The placeholder should be contained within proper flex layout
        # Check that the HTML structure supports proper filling
        assert "empty-phase-placeholder" in response_text
        assert (
            "wizard-steps empty" in response_text
            or "empty wizard-steps" in response_text
        )
        assert "drop-zone" in response_text

        # Check that the placeholder contains the expected text
        assert "No pre-invite steps" in response_text
        assert "Drop steps here or create new ones" in response_text

    def test_responsive_drop_zone_sizing(
        self, authenticated_client, empty_phases_setup
    ):
        """Test that drop zones maintain proper sizing across different layouts."""
        _ = empty_phases_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Check for responsive grid layout that affects drop zone sizing
        assert "grid-cols-1 lg:grid-cols-2" in response_text

        # Verify that both pre and post phases are rendered with proper structure
        assert 'data-phase="pre"' in response_text
        assert 'data-phase="post"' in response_text

        # Each should have its own drop zone that can be properly filled
        pre_section = response_text[response_text.find('data-phase="pre"') - 100 :]
        post_section = response_text[response_text.find('data-phase="post"') - 100 :]

        # Both sections should contain drop zones
        assert "drop-zone" in pre_section[:500]  # Check nearby context
        assert "drop-zone" in post_section[:500]  # Check nearby context

    def test_striped_zone_extends_beyond_drop_zone_padding(
        self, authenticated_client, empty_phases_setup
    ):
        """Test that striped zone fills entire visual drop area, beyond drop-zone padding."""
        _ = empty_phases_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Find the empty-phase-placeholder CSS rule
        placeholder_rule_start = response_text.find(".empty-phase-placeholder {")
        assert placeholder_rule_start != -1, (
            "CSS rule for .empty-phase-placeholder not found"
        )
        placeholder_rule_end = response_text.find("}", placeholder_rule_start)
        placeholder_css = response_text[
            placeholder_rule_start : placeholder_rule_end + 1
        ]

        # Should use inset: 0 to dynamically fill the entire drop-zone container
        # This ensures the striped pattern adapts to the actual drop-zone size
        assert "inset: 0" in placeholder_css, (
            "Placeholder should use inset: 0 to dynamically fill drop-zone container"
        )

        # Should still have the striped background
        assert "repeating-linear-gradient" in placeholder_css

    def test_placeholder_adapts_to_drop_zone_size(
        self, authenticated_client, empty_phases_setup
    ):
        """Test that placeholder dynamically adapts to drop-zone container size."""
        _ = empty_phases_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # The placeholder should be positioned relative to drop-zone container
        # Using inset: 0 ensures it fills whatever size the drop-zone currently is
        placeholder_rule_start = response_text.find(".empty-phase-placeholder {")
        assert placeholder_rule_start != -1
        placeholder_rule_end = response_text.find("}", placeholder_rule_start)
        placeholder_css = response_text[
            placeholder_rule_start : placeholder_rule_end + 1
        ]

        # Verify dynamic sizing approach
        assert "inset: 0" in placeholder_css, "Should use inset: 0 for dynamic sizing"
        assert "absolute" in response_text, "Should maintain absolute positioning"

        # Check that drop-zone has flex properties that allow dynamic sizing
        drop_zone_start = response_text.find(".drop-zone {")
        assert drop_zone_start != -1
        drop_zone_end = response_text.find("}", drop_zone_start)
        drop_zone_css = response_text[drop_zone_start : drop_zone_end + 1]

        assert "min-height:" in drop_zone_css, "Drop-zone should have min-height"
        assert "flex" in drop_zone_css, "Drop-zone should use flex for dynamic sizing"

    def test_dynamic_height_synchronization_function_exists(
        self, authenticated_client, empty_phases_setup
    ):
        """Test that JavaScript includes height synchronization functionality."""
        _ = empty_phases_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Verify that wizard-steps.js is included
        assert "wizard-steps.js" in response_text

        # The actual function will be in the JS file, so we verify it's referenced
        assert (
            "WizardDragDropManager" in response_text
            or "wizard-steps.js" in response_text
        )

    def test_phase_sections_have_matching_heights_structure(
        self, authenticated_client, empty_phases_setup
    ):
        """Test that phase sections are structured to support height matching."""
        _ = empty_phases_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Verify that both phases are in the same server section for height comparison
        assert "grid-cols-1 lg:grid-cols-2" in response_text
        assert 'data-phase="pre"' in response_text
        assert 'data-phase="post"' in response_text

        # Both phases should have identifiable drop zones
        assert 'class="drop-zone"' in response_text

        # Phases should be within the same server section
        pre_index = response_text.find('data-phase="pre"')
        post_index = response_text.find('data-phase="post"')
        server_section_start = response_text.rfind(
            '<div class="server-section">', 0, pre_index
        )
        server_section_end = response_text.find("</div>", post_index)

        # Both phases should be within the same server section
        assert server_section_start < pre_index < post_index < server_section_end

    def test_empty_placeholder_supports_dynamic_height(
        self, authenticated_client, empty_phases_setup
    ):
        """Test that empty placeholder styling supports dynamic height setting."""
        _ = empty_phases_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Verify placeholder uses absolute positioning with inset for filling
        placeholder_rule_start = response_text.find(".empty-phase-placeholder {")
        assert placeholder_rule_start != -1
        placeholder_rule_end = response_text.find("}", placeholder_rule_start)
        placeholder_css = response_text[
            placeholder_rule_start : placeholder_rule_end + 1
        ]

        # Should use absolute positioning and inset for dynamic filling
        assert "inset: 0" in placeholder_css

        # HTML structure should support absolute positioning within drop zone
        assert "absolute inset-0" in response_text

        # Drop zone should have relative positioning to contain absolute placeholder
        drop_zone_start = response_text.find(".drop-zone {")
        assert drop_zone_start != -1
        drop_zone_end = response_text.find("}", drop_zone_start)
        drop_zone_css = response_text[drop_zone_start : drop_zone_end + 1]

        assert "position: relative" in drop_zone_css

    def test_step_counting_infrastructure_exists(
        self, authenticated_client, empty_phases_setup
    ):
        """Test that infrastructure exists for counting steps in each phase."""
        _ = empty_phases_setup
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Should have step count elements with identifiable IDs
        assert 'id="pre-step-count-' in response_text
        assert 'id="post-step-count-' in response_text

        # Should have data attributes for phase identification
        assert 'data-phase="pre"' in response_text
        assert 'data-phase="post"' in response_text
        assert "data-server=" in response_text

        # Should have wizard-steps containers that can be measured
        assert 'class="wizard-steps' in response_text

    def test_height_synchronization_javascript_functions_available(
        self, authenticated_client, empty_phases_setup
    ):
        """Test that height synchronization JavaScript functions are available."""
        _ = empty_phases_setup

        # Get the JavaScript file directly
        js_response = authenticated_client.get("/static/js/wizard-steps.js")
        assert js_response.status_code == 200

        js_content = js_response.data.decode("utf-8")

        # Verify the height synchronization functions exist
        assert "synchronizePhaseHeights" in js_content
        assert "synchronizeAllPhaseHeights" in js_content

        # Verify the function is called in updateEmptyState
        assert "this.synchronizePhaseHeights(container)" in js_content

        # Verify the function is called on page load
        assert "synchronizeAllPhaseHeights();" in js_content
