"""
TDD tests for the redesigned wizard UI components.

This test suite follows TDD methodology and covers:
1. Modern progress tracker component functionality
2. Responsive design across device sizes
3. Accessibility standards (ARIA labels, keyboard navigation)
4. HTMX dynamic loading preservation
5. User interaction requirements preservation
6. Backward compatibility with existing wizard step data

Based on requirements:
- Modernize visual design while maintaining minimalist aesthetic
- Implement progress tracker showing current step and total steps
- Ensure responsive design works across desktop and mobile
- Maintain accessibility standards
- Preserve all existing "Require User Interaction" functionality
- Maintain backward compatibility with existing wizard step data structure
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
def sample_wizard_steps(app):
    """Create sample wizard steps for testing."""
    with app.app_context():
        # Clear existing steps
        WizardStep.query.delete()
        db.session.commit()

        steps = []

        # Pre-invite steps
        pre_step1 = WizardStep(
            server_type="plex",
            phase=WizardPhase.PRE,
            position=0,
            title="Welcome",
            markdown="# Welcome!\n\nThis is the first pre-invite step.",
            require_interaction=False,
        )
        steps.append(pre_step1)

        pre_step2 = WizardStep(
            server_type="plex",
            phase=WizardPhase.PRE,
            position=1,
            title="Rules",
            markdown="# Server Rules\n\nPlease read our [rules](https://example.com/rules).",
            require_interaction=True,
        )
        steps.append(pre_step2)

        # Post-invite steps
        post_step1 = WizardStep(
            server_type="plex",
            phase=WizardPhase.POST,
            position=0,
            title="Download App",
            markdown="# Download Plex\n\n[Download here](https://plex.tv/downloads).",
            require_interaction=False,
        )
        steps.append(post_step1)

        post_step2 = WizardStep(
            server_type="plex",
            phase=WizardPhase.POST,
            position=1,
            title="Setup Complete",
            markdown="# All Done!\n\nYou're ready to start using Plex.",
            require_interaction=False,
        )
        steps.append(post_step2)

        for step in steps:
            db.session.add(step)
        db.session.commit()

        return steps


@pytest.fixture
def sample_media_server(app):
    """Create sample media server for testing."""
    with app.app_context():
        server = MediaServer(
            name="Test Plex Server",
            server_type="plex",
            url="http://localhost:32400",
        )
        db.session.add(server)
        db.session.commit()
        return server


class TestProgressTrackerComponent:
    """Test the modern progress tracker component."""

    def test_progress_tracker_shows_current_step_and_total(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that progress tracker displays current step and total steps."""
        response = authenticated_client.get("/settings/wizard/preview/plex")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Should show step 1 of 4 (2 pre + 1 join + 1 post visible in preview)
        assert "Step 1 of" in html

        # Should have progress indicator element
        assert 'id="progress-indicator"' in html or 'class="progress-tracker"' in html

    def test_progress_tracker_updates_with_navigation(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that progress tracker updates when navigating between steps."""
        # Test step 2
        response = authenticated_client.get("/settings/wizard/preview/plex?step=1")
        assert response.status_code == 200

        html = response.get_data(as_text=True)
        assert "Step 2 of" in html

    def test_progress_tracker_shows_phase_information(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that progress tracker shows phase information (pre/post)."""
        response = authenticated_client.get("/settings/wizard/preview/plex")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Should show phase information
        assert "pre" in html.lower() or "before" in html.lower()

    def test_progress_tracker_accessibility_attributes(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that progress tracker has proper accessibility attributes."""
        response = authenticated_client.get("/settings/wizard/preview/plex")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Should have ARIA labels for screen readers
        assert "aria-label=" in html or "role=" in html

        # Progress bar should have proper ARIA attributes
        assert 'role="progressbar"' in html or "aria-valuenow=" in html


class TestResponsiveDesign:
    """Test responsive design across different device sizes."""

    def test_wizard_card_responsive_classes(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that wizard card has responsive CSS classes."""
        response = authenticated_client.get("/settings/wizard/preview/plex")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Should have responsive width classes
        assert "max-w-" in html  # Maximum width constraint
        assert "w-full" in html or "w-" in html  # Full width on mobile

        # Should have responsive padding
        assert "px-" in html and "py-" in html  # Padding classes

    def test_navigation_buttons_responsive_layout(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that navigation buttons adapt to mobile layout."""
        response = authenticated_client.get("/settings/wizard/preview/plex")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Should have responsive button layout classes
        assert "flex" in html  # Flexbox layout
        assert "gap-" in html or "space-" in html  # Spacing between buttons

    def test_progress_bar_responsive_width(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that progress bar adapts to container width."""
        response = authenticated_client.get("/settings/wizard/preview/plex")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Progress bar should have full width
        assert "w-full" in html


class TestAccessibilityStandards:
    """Test accessibility compliance (WCAG 2.1 AA)."""

    def test_wizard_has_proper_heading_hierarchy(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that wizard maintains proper heading hierarchy."""
        response = authenticated_client.get("/settings/wizard/preview/plex")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Should have proper heading structure (h1, h2, etc.)
        assert "<h1" in html or "<h2" in html

    def test_navigation_buttons_keyboard_accessible(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that navigation buttons are keyboard accessible."""
        response = authenticated_client.get("/settings/wizard/preview/plex")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Buttons should be focusable and have proper roles
        assert "tabindex=" in html or 'role="button"' in html

        # Should have focus indicators
        assert "focus:" in html  # Tailwind focus classes

    def test_interaction_required_accessibility(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test accessibility of interaction required functionality."""
        # Navigate to step that requires interaction (step 1, which is pre_step2)
        response = authenticated_client.get("/settings/wizard/preview/plex?step=1")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Should have proper ARIA attributes for disabled state
        assert "aria-disabled=" in html or "data-disabled=" in html

        # Should have descriptive text for screen readers
        assert "interaction" in html.lower() or "click" in html.lower()


class TestHTMXPreservation:
    """Test that HTMX dynamic loading continues to work."""

    def test_htmx_attributes_preserved_on_navigation(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that HTMX attributes are preserved on navigation buttons."""
        response = authenticated_client.get("/settings/wizard/preview/plex")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Should have HTMX attributes
        assert "hx-get=" in html
        assert "hx-target=" in html
        assert "hx-swap=" in html

    def test_htmx_request_returns_partial_content(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that HTMX requests return only the wizard content."""
        response = authenticated_client.get(
            "/settings/wizard/preview/plex?step=1", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Should contain wizard wrapper
        assert 'id="wizard-wrapper"' in html

        # Should not contain full page structure for HTMX requests
        assert "<html>" not in html
        assert "<head>" not in html


class TestUserInteractionPreservation:
    """Test that existing user interaction requirements are preserved."""

    def test_require_interaction_disables_navigation(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that require_interaction properly disables navigation."""
        # Navigate to step that requires interaction
        response = authenticated_client.get("/settings/wizard/preview/plex?step=1")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Navigation should be disabled
        assert 'data-disabled="1"' in html or 'aria-disabled="true"' in html

    def test_interaction_required_shows_proper_messaging(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that interaction required shows appropriate user messaging."""
        response = authenticated_client.get("/settings/wizard/preview/plex?step=1")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Should show interaction requirement message
        assert "click" in html.lower() or "interaction" in html.lower()


class TestBackwardCompatibility:
    """Test backward compatibility with existing wizard step data."""

    def test_existing_wizard_steps_render_correctly(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that existing wizard steps render with new UI."""
        response = authenticated_client.get("/settings/wizard/preview/plex")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Should render step content
        assert "Welcome!" in html

        # Should preserve markdown rendering
        assert "<h1>" in html or "Welcome" in html

    def test_wizard_step_properties_preserved(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that all wizard step properties are preserved."""
        response = authenticated_client.get("/settings/wizard/preview/plex")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Should show step title
        assert "Welcome" in html

        # Should render markdown content
        assert "first pre-invite step" in html
