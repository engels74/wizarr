"""
TDD tests to reproduce and verify fix for wizard preview header duplication bug.

The bug occurs when users navigate wizard steps in preview mode using Next/Previous buttons.
Each navigation causes the header section to duplicate because HTMX receives the full template
instead of just the wizard steps partial.
"""

import pytest

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
def sample_wizard_steps():
    """Create sample wizard steps for testing."""
    steps = []

    # Pre-invite steps
    pre_step1 = WizardStep(
        server_type="plex",
        phase=WizardPhase.PRE,
        position=0,
        title="Welcome",
        markdown="# Welcome!\n\nThis is step 1.",
        require_interaction=False,
    )
    steps.append(pre_step1)

    pre_step2 = WizardStep(
        server_type="plex",
        phase=WizardPhase.PRE,
        position=1,
        title="Rules",
        markdown="# Server Rules\n\nThis is step 2.",
        require_interaction=True,
    )
    steps.append(pre_step2)

    # Post-invite step
    post_step1 = WizardStep(
        server_type="plex",
        phase=WizardPhase.POST,
        position=0,
        title="Complete",
        markdown="# Setup Complete!\n\nThis is the final step.",
        require_interaction=False,
    )
    steps.append(post_step1)

    for step in steps:
        db.session.add(step)
    db.session.commit()

    return steps


@pytest.fixture
def sample_media_server():
    """Create a sample media server."""
    server = MediaServer(
        server_type="plex",
        name="Test Plex Server",
        url="http://localhost:32400",
        external_url="https://plex.example.com",
    )
    db.session.add(server)
    db.session.commit()
    return server


class TestWizardPreviewHeaderDuplicationBug:
    """Test cases to reproduce the header duplication bug in wizard preview."""

    def test_initial_preview_load_shows_single_header(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that initial preview load shows only one header section."""
        response = authenticated_client.get("/settings/wizard/preview/plex")
        assert response.status_code == 200

        response_text = response.get_data(as_text=True)

        # Should have exactly one preview mode banner
        banner_count = response_text.count(
            "Preview Mode - Test Plex Server Wizard Steps"
        )
        assert banner_count == 1, f"Expected 1 preview banner, found {banner_count}"

        # Should have no breadcrumb section (breadcrumb has been removed)
        breadcrumb_count = response_text.count('<div class="preview-breadcrumb">')
        assert breadcrumb_count == 0, (
            f"Expected 0 breadcrumb div (removed), found {breadcrumb_count}"
        )

        # Should have exactly one progress indicator (look for the actual HTML div)
        progress_count = response_text.count("preview-progress")
        assert progress_count >= 1, (
            f"Expected at least 1 progress div, found {progress_count}"
        )

    def test_htmx_navigation_request_causes_header_duplication(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that HTMX navigation requests cause header duplication (reproduces bug)."""
        # Simulate HTMX request (like clicking Next button)
        response = authenticated_client.get(
            "/settings/wizard/preview/plex?step=1", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.get_data(as_text=True)

        # BUG: HTMX request should return only wizard steps, but currently returns full template
        # This causes header duplication when HTMX swaps the content

        # The bug is that we get the full template with headers in HTMX response
        banner_count = response_text.count(
            "Preview Mode - Test Plex Server Wizard Steps"
        )
        breadcrumb_count = response_text.count('<div class="preview-breadcrumb">')
        progress_count = response_text.count("preview-progress")

        # After fix: HTMX requests should return 0 headers (bug is fixed)
        assert banner_count == 0, (
            "Fix verification: HTMX response should not contain headers"
        )
        assert breadcrumb_count == 0, (
            "Fix verification: HTMX response should not contain headers"
        )
        assert progress_count == 0, (
            "Fix verification: HTMX response should not contain headers"
        )

    def test_htmx_request_should_return_only_wizard_steps(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that HTMX requests should return only wizard steps (this will fail until fixed)."""
        # This test shows what the behavior SHOULD be after the fix
        response = authenticated_client.get(
            "/settings/wizard/preview/plex?step=1", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.get_data(as_text=True)

        # After fix: HTMX requests should return only the wizard steps content
        # Should have wizard-wrapper div
        assert 'id="wizard-wrapper"' in response_text

        # Should NOT have preview headers in HTMX response
        banner_count = response_text.count(
            "Preview Mode - Test Plex Server Wizard Steps"
        )
        breadcrumb_count = response_text.count('<div class="preview-breadcrumb">')
        progress_count = response_text.count("preview-progress")

        # After fix: HTMX requests should return 0 headers
        assert banner_count == 0, (
            f"HTMX response should not contain banner, found {banner_count}"
        )
        assert breadcrumb_count == 0, (
            f"HTMX response should not contain breadcrumb, found {breadcrumb_count}"
        )
        assert progress_count == 0, (
            f"HTMX response should not contain progress, found {progress_count}"
        )

    def test_regular_navigation_preserves_single_header(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that regular (non-HTMX) navigation preserves single header."""
        # Regular navigation to step 1
        response = authenticated_client.get("/settings/wizard/preview/plex?step=1")
        assert response.status_code == 200

        response_text = response.get_data(as_text=True)

        # Should still have exactly one of each header element
        banner_count = response_text.count(
            "Preview Mode - Test Plex Server Wizard Steps"
        )
        assert banner_count == 1, f"Expected 1 preview banner, found {banner_count}"

        breadcrumb_count = response_text.count('<div class="preview-breadcrumb">')
        assert breadcrumb_count == 0, (
            f"Expected 0 breadcrumb div (removed), found {breadcrumb_count}"
        )

        progress_count = response_text.count("preview-progress")
        assert progress_count >= 1, (
            f"Expected at least 1 progress div, found {progress_count}"
        )

    def test_wizard_steps_template_structure_in_htmx_response(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that HTMX response contains proper wizard steps structure."""
        response = authenticated_client.get(
            "/settings/wizard/preview/plex?step=0", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.get_data(as_text=True)

        # Should contain wizard steps structure
        assert 'id="wizard-wrapper"' in response_text
        assert "prose prose-slate dark:prose-invert" in response_text
        assert 'hx-target="#wizard-wrapper"' in response_text
        assert 'hx-swap="outerHTML"' in response_text

        # Should contain step content
        assert "Welcome!" in response_text

    def test_navigation_urls_in_preview_mode(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that navigation URLs in preview mode point to preview endpoints."""
        response = authenticated_client.get("/settings/wizard/preview/plex?step=1")
        assert response.status_code == 200

        response_text = response.get_data(as_text=True)

        # Navigation URLs should point to preview endpoints
        assert (
            'hx-get="/settings/wizard/preview/plex?step=0"' in response_text
        )  # Previous
        assert 'hx-get="/settings/wizard/preview/plex?step=2"' in response_text  # Next


class TestWizardPreviewHTMXBehavior:
    """Test HTMX behavior in wizard preview to understand the duplication mechanism."""

    def test_htmx_target_and_swap_attributes(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that HTMX attributes are correctly set for navigation."""
        response = authenticated_client.get("/settings/wizard/preview/plex")
        assert response.status_code == 200

        response_text = response.get_data(as_text=True)

        # Check HTMX attributes on navigation buttons
        assert 'hx-target="#wizard-wrapper"' in response_text
        assert 'hx-swap="outerHTML"' in response_text

        # The issue is that when HTMX makes the request, it gets the full template
        # and swaps the entire content into #wizard-wrapper, including headers

    def test_response_content_type_for_htmx_requests(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test response content type for HTMX requests."""
        response = authenticated_client.get(
            "/settings/wizard/preview/plex?step=1", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        # Should return HTML content
        assert response.content_type.startswith("text/html")


class TestWizardPreviewIntegration:
    """Integration tests to verify the complete fix works end-to-end."""

    def test_preview_navigation_flow_no_header_duplication(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test complete navigation flow to ensure no header duplication occurs."""
        # Step 1: Load initial preview (should have headers)
        response = authenticated_client.get("/settings/wizard/preview/plex")
        assert response.status_code == 200
        initial_html = response.get_data(as_text=True)

        # Verify initial state has headers (except breadcrumb which was removed)
        assert '<div class="preview-mode-banner">' in initial_html
        assert (
            '<div class="preview-breadcrumb">' not in initial_html
        )  # Breadcrumb removed
        assert "preview-progress" in initial_html

        # Step 2: Simulate HTMX navigation (Next button click)
        htmx_response = authenticated_client.get(
            "/settings/wizard/preview/plex?step=1", headers={"HX-Request": "true"}
        )
        assert htmx_response.status_code == 200
        htmx_html = htmx_response.get_data(as_text=True)

        # Verify HTMX response has NO headers (prevents duplication)
        assert '<div class="preview-mode-banner">' not in htmx_html
        assert '<div class="preview-breadcrumb">' not in htmx_html
        assert "preview-progress" not in htmx_html

        # But should have wizard content
        assert 'id="wizard-wrapper"' in htmx_html
        assert "Server Rules" in htmx_html  # Step 2 content

        # Step 3: Simulate another HTMX navigation (Previous button)
        htmx_prev_response = authenticated_client.get(
            "/settings/wizard/preview/plex?step=0", headers={"HX-Request": "true"}
        )
        assert htmx_prev_response.status_code == 200
        htmx_prev_html = htmx_prev_response.get_data(as_text=True)

        # Still no headers in HTMX response
        assert '<div class="preview-mode-banner">' not in htmx_prev_html
        assert '<div class="preview-breadcrumb">' not in htmx_prev_html
        assert "preview-progress" not in htmx_prev_html

        # Should have step 1 content
        assert "Welcome!" in htmx_prev_html

        # Step 4: Regular navigation should still work with headers
        regular_response = authenticated_client.get(
            "/settings/wizard/preview/plex?step=2"
        )
        assert regular_response.status_code == 200
        regular_html = regular_response.get_data(as_text=True)

        # Regular response should have headers (except breadcrumb which was removed)
        assert '<div class="preview-mode-banner">' in regular_html
        assert (
            '<div class="preview-breadcrumb">' not in regular_html
        )  # Breadcrumb removed
        assert "preview-progress" in regular_html
