"""
Tests for wizard preview functionality fixes.

This test suite ensures the preview functionality fixes work correctly:
1. Preview button opens in new browser tab (target="_blank")
2. Broken breadcrumb is removed from preview mode
3. Dynamic content updates work correctly (step counters, phase indicators)
4. Out-of-band HTMX swapping works for progress indicators
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
    app.config["WTF_CSRF_ENABLED"] = False  # Disable CSRF for testing

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
    # Login as admin
    client.post("/login", data={"username": "admin", "password": "password"})
    return client


def create_test_wizard_steps():
    """Create sample wizard steps for testing."""

    # Create media server first
    server = MediaServer(
        server_type="plex",
        name="Test Plex Server",
        url="http://localhost:32400",
        external_url="https://plex.example.com",
    )
    db.session.add(server)

    # Create wizard steps
    steps = []

    # Pre-invite steps
    pre_step1 = WizardStep(
        server_type="plex",
        phase=WizardPhase.PRE,
        position=0,
        title="Welcome Step",
        markdown="# Welcome!\n\nThis is step 1 of the pre-wizard.",
        require_interaction=False,
    )
    steps.append(pre_step1)

    pre_step2 = WizardStep(
        server_type="plex",
        phase=WizardPhase.PRE,
        position=1,
        title="Rules Step",
        markdown="# Server Rules\n\nThis is step 2 of the pre-wizard.",
        require_interaction=True,
    )
    steps.append(pre_step2)

    # Post-invite steps
    post_step1 = WizardStep(
        server_type="plex",
        phase=WizardPhase.POST,
        position=0,
        title="Setup Complete",
        markdown="# Setup Complete!\n\nThis is step 1 of the post-wizard.",
        require_interaction=False,
    )
    steps.append(post_step1)

    for step in steps:
        db.session.add(step)
    db.session.commit()

    return steps, server


class TestPreviewButtonFix:
    """Test that preview button opens in new browser tab."""

    def test_preview_button_has_target_blank(self, authenticated_client):
        """Test that preview button includes target='_blank' attribute."""
        create_test_wizard_steps()  # Set up test data
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.get_data(as_text=True)

        # Should have preview button with target="_blank"
        assert 'target="_blank"' in response_text

        # Should be on the preview link specifically
        assert 'href="/settings/wizard/preview/plex"' in response_text

        # Both attributes should exist near each other in the HTML
        # Find the position of the preview URL
        preview_url_pos = response_text.find('href="/settings/wizard/preview/plex"')
        target_blank_pos = response_text.find('target="_blank"')

        assert preview_url_pos != -1, "Preview URL not found"
        assert target_blank_pos != -1, "target='_blank' not found"

        # They should be reasonably close to each other (within 200 characters)
        assert abs(preview_url_pos - target_blank_pos) < 200, (
            "target='_blank' should be near preview URL"
        )


class TestBreadcrumbRemoval:
    """Test that broken breadcrumb is removed from preview mode."""

    def test_breadcrumb_not_present_in_preview(self, authenticated_client):
        """Test that breadcrumb navigation is not present in preview mode."""
        create_test_wizard_steps()  # Set up test data
        response = authenticated_client.get("/settings/wizard/preview/plex")
        assert response.status_code == 200

        response_text = response.get_data(as_text=True)

        # Should not have breadcrumb navigation
        assert "preview-breadcrumb" not in response_text
        assert "Settings → Wizard Steps → Preview" not in response_text

        # Should not have the specific breadcrumb structure
        assert (
            'href="/settings/wizard/"' not in response_text
            or "Wizard Steps" not in response_text
        )


class TestDynamicContentUpdates:
    """Test that dynamic content updates work correctly."""

    def test_progress_indicator_shows_correct_step_count(self, authenticated_client):
        """Test that progress indicator shows correct step counts."""
        create_test_wizard_steps()  # Set up test data
        # Total steps: 2 pre + 1 join + 1 post = 4 steps

        # Test step 1 of 4
        response = authenticated_client.get("/settings/wizard/preview/plex?step=0")
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)
        assert "Step 1 of 4" in response_text

        # Test step 2 of 4
        response = authenticated_client.get("/settings/wizard/preview/plex?step=1")
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)
        assert "Step 2 of 4" in response_text

        # Test step 3 of 4 (join phase)
        response = authenticated_client.get("/settings/wizard/preview/plex?step=2")
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)
        assert "Step 3 of 4" in response_text

        # Test step 4 of 4 (post phase)
        response = authenticated_client.get("/settings/wizard/preview/plex?step=3")
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)
        assert "Step 4 of 4" in response_text

    def test_phase_indicator_shows_correct_phase(self, authenticated_client):
        """Test that phase indicator shows correct phase."""
        create_test_wizard_steps()  # Set up test data
        # Pre phase
        response = authenticated_client.get("/settings/wizard/preview/plex?step=0")
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)
        assert "phase-pre" in response_text
        assert "Before Invite" in response_text

        # Join phase
        response = authenticated_client.get("/settings/wizard/preview/plex?step=2")
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)
        assert "phase-join" in response_text
        assert "Invite Acceptance" in response_text

        # Post phase
        response = authenticated_client.get("/settings/wizard/preview/plex?step=3")
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)
        assert "phase-post" in response_text
        assert "After Invite" in response_text

    def test_progress_indicator_has_id_for_htmx_targeting(self, authenticated_client):
        """Test that progress indicator has ID for HTMX targeting."""
        create_test_wizard_steps()  # Set up test data
        response = authenticated_client.get("/settings/wizard/preview/plex")
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)

        # Should have progress indicator with ID
        assert 'id="progress-indicator"' in response_text


class TestHTMXOutOfBandSwapping:
    """Test that HTMX out-of-band swapping works for progress updates."""

    def test_htmx_request_returns_out_of_band_progress_update(
        self, authenticated_client
    ):
        """Test that HTMX requests include out-of-band progress updates."""
        create_test_wizard_steps()  # Set up test data
        # Make HTMX request (simulated with HX-Request header)
        response = authenticated_client.get(
            "/settings/wizard/preview/plex?step=1", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)

        # Should include out-of-band swap for progress indicator
        assert 'hx-swap-oob="innerHTML:#progress-indicator"' in response_text

        # Should still have the wizard content
        assert 'id="wizard-wrapper"' in response_text

        # Should have correct step count in the out-of-band content
        assert "Step 2 of 4" in response_text

    def test_regular_request_does_not_include_oob_swap(self, authenticated_client):
        """Test that regular (non-HTMX) requests don't include out-of-band swaps."""
        create_test_wizard_steps()  # Set up test data
        response = authenticated_client.get("/settings/wizard/preview/plex?step=1")
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)

        # Should NOT include out-of-band swap
        assert "hx-swap-oob=" not in response_text

        # Should have full page template
        assert "Preview Mode -" in response_text

    def test_htmx_navigation_updates_progress_correctly(self, authenticated_client):
        """Test that HTMX navigation between steps updates progress correctly."""
        create_test_wizard_steps()  # Set up test data
        # Navigate to different steps via HTMX and verify progress updates
        test_cases = [
            (0, "Step 1 of 4", "phase-pre"),
            (1, "Step 2 of 4", "phase-pre"),
            (2, "Step 3 of 4", "phase-join"),
            (3, "Step 4 of 4", "phase-post"),
        ]

        for step, expected_count, expected_phase in test_cases:
            response = authenticated_client.get(
                f"/settings/wizard/preview/plex?step={step}",
                headers={"HX-Request": "true"},
            )
            assert response.status_code == 200
            response_text = response.get_data(as_text=True)

            # Check step count in out-of-band content
            assert expected_count in response_text

            # Check phase indicator in out-of-band content
            assert expected_phase in response_text


class TestProgressBarCalculation:
    """Test that progress bar percentage calculation works correctly."""

    def test_progress_percentage_calculation(self, authenticated_client):
        """Test that progress percentage is calculated correctly."""
        create_test_wizard_steps()  # Set up test data
        # Total steps: 4, so each step should be 25%
        test_cases = [
            (0, "25.0%"),  # Step 1 of 4 = 25%
            (1, "50.0%"),  # Step 2 of 4 = 50%
            (2, "75.0%"),  # Step 3 of 4 = 75%
            (3, "100.0%"),  # Step 4 of 4 = 100%
        ]

        for step, expected_percentage in test_cases:
            response = authenticated_client.get(
                f"/settings/wizard/preview/plex?step={step}"
            )
            assert response.status_code == 200
            response_text = response.get_data(as_text=True)

            # Check that the progress bar width is set correctly
            assert f"width: {expected_percentage}" in response_text
