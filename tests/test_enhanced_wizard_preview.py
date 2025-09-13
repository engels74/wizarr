"""
Tests for enhanced wizard preview functionality that uses actual wizard templates.

This test suite ensures the preview system:
1. Uses the exact same templates as the real wizard flow
2. Provides identical appearance to actual user experience
3. Includes subtle preview mode indicators
4. Automatically inherits future wizard design changes
5. Follows DRY principles with shared rendering logic
"""

import pytest

from app import create_app
from app.extensions import db
from app.models import MediaServer, WizardPhase, WizardStep


@pytest.fixture
def app():
    """Create application for testing."""
    app = create_app()
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["WTF_CSRF_ENABLED"] = False  # Disable CSRF for testing

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture
def authenticated_client(client, app):
    """Create authenticated test client."""
    # Ensure admin user exists in database
    with app.app_context():
        from app.extensions import db
        from app.models import AdminAccount

        admin = AdminAccount.query.filter_by(username="admin").first()
        if not admin:
            admin = AdminAccount(username="admin")
            admin.set_password("password")
            db.session.add(admin)
            db.session.commit()

    # Login as admin
    response = client.post("/login", data={"username": "admin", "password": "password"})
    assert response.status_code in [200, 302], (
        f"Login failed with status {response.status_code}"
    )
    return client


class TestEnhancedWizardPreview:
    """Test enhanced wizard preview functionality with template reuse."""

    @pytest.fixture
    def sample_wizard_steps(self):
        """Get or create sample wizard steps for testing."""
        # Check if wizard steps already exist (from seeding)
        existing_steps = WizardStep.query.filter_by(server_type="plex").all()

        if existing_steps:
            return existing_steps

        # Create wizard steps if they don't exist
        steps = []

        # Pre-invite steps
        pre_step1 = WizardStep(
            server_type="plex",
            phase=WizardPhase.PRE,
            position=0,
            title="Welcome to Plex",
            markdown="# Welcome!\n\nPlease read our rules before joining {{ settings.server_name }}.",
            require_interaction=False,
        )
        pre_step2 = WizardStep(
            server_type="plex",
            phase=WizardPhase.PRE,
            position=1,
            title="Server Rules",
            markdown="# Server Rules\n\nPlease follow these rules:",
            require_interaction=False,
        )

        # Post-invite step
        post_step1 = WizardStep(
            server_type="plex",
            phase=WizardPhase.POST,
            position=0,
            title="Welcome to Server",
            markdown="# Welcome to {{ settings.server_name }}!\n\nEnjoy your stay!",
            require_interaction=False,
        )

        steps.extend([pre_step1, pre_step2, post_step1])

        for step in steps:
            db.session.add(step)
        db.session.commit()

        return steps

    @pytest.fixture
    def sample_media_server(self):
        """Create a sample media server for context."""
        server = MediaServer(
            server_type="plex",
            name="Test Plex Server",
            url="http://localhost:32400",
            external_url="https://plex.example.com",
        )
        db.session.add(server)
        db.session.commit()
        return server

    def test_preview_uses_actual_wizard_templates(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that preview uses the same templates as actual wizard flow."""
        response = authenticated_client.get("/settings/wizard/preview/plex")
        assert response.status_code == 200

        response_text = response.get_data(as_text=True)

        # Should use wizard/frame.html structure (same as real wizard)
        assert 'id="wizard-wrapper"' in response_text
        assert "prose prose-slate dark:prose-invert" in response_text

        # Should have the same card styling as real wizard (updated for current template)
        assert (
            "bg-white dark:bg-gray-800 rounded-xl shadow-lg border border-gray-200 dark:border-gray-700"
            in response_text
        )

    def test_preview_mode_visual_indicators(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that preview mode has subtle visual indicators."""
        response = authenticated_client.get("/settings/wizard/preview/plex")
        assert response.status_code == 200

        response_text = response.get_data(as_text=True)

        # Should have preview mode banner/indicator
        assert "PREVIEW MODE" in response_text or "Preview Mode" in response_text

        # Should indicate this is not the real wizard
        assert "preview" in response_text.lower()

    def test_preview_template_context_matches_real_wizard(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that preview uses same context variables as real wizard."""
        # Ensure fixtures are used (they create the data)
        assert len(sample_wizard_steps) > 0
        assert sample_media_server.name == "Test Plex Server"

        response = authenticated_client.get("/settings/wizard/preview/plex")
        assert response.status_code == 200

        response_text = response.get_data(as_text=True)

        # First check if we have the wizard step content
        assert "Welcome!" in response_text  # From the markdown content

        # Template variables should be rendered (from sample_media_server)
        # The markdown uses {{ settings.server_name }} which should render as "Test Plex Server"
        assert "Test Plex Server" in response_text

        # Check that template variables are being processed
        # The markdown should NOT contain the raw template syntax
        assert "{{ settings.server_name }}" not in response_text

    def test_preview_interaction_requirements_displayed(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that interaction requirements are shown in preview mode."""
        # Navigate to step with interaction requirement (step 1)
        response = authenticated_client.get("/settings/wizard/preview/plex?step=1")
        assert response.status_code == 200

        response_text = response.get_data(as_text=True)

        # Should show interaction requirement in preview mode
        assert (
            "require_interaction" in response_text.lower()
            or "interaction" in response_text.lower()
        )

        # Should indicate this is preview-only
        assert "preview" in response_text.lower()

    def test_preview_navigation_preserves_wizard_flow(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that preview navigation matches real wizard flow."""
        # Test navigation through all phases
        phases_and_steps = [
            (0, "pre", "Welcome!"),  # Pre step 1 - from markdown content
            (1, "pre", "Server Rules"),  # Pre step 2 - from title
            (2, "join", "Ready to Join!"),  # Join transition - from mock content
            (
                3,
                "post",
                "Welcome to Test Plex Server!",
            ),  # Post step 1 - from rendered markdown
        ]

        for step_num, _expected_phase, expected_content in phases_and_steps:
            response = authenticated_client.get(
                f"/settings/wizard/preview/plex?step={step_num}"
            )
            assert response.status_code == 200

            response_text = response.get_data(as_text=True)

            # Debug output for failing step
            if expected_content not in response_text:
                print(f"Step {step_num} failed. Looking for: '{expected_content}'")
                print(
                    f"Response contains: {response_text[2000:3000]}"
                )  # Show middle part

            assert expected_content in response_text

    def test_preview_step_bounds_handling(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test preview handles step bounds correctly."""
        # Test negative step
        response = authenticated_client.get("/settings/wizard/preview/plex?step=-1")
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)
        assert "Welcome!" in response_text  # Should show first step

        # Test step beyond bounds
        response = authenticated_client.get("/settings/wizard/preview/plex?step=999")
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)
        assert "Welcome to Test Plex Server!" in response_text  # Should show last step

    def test_preview_markdown_rendering_matches_real_wizard(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that markdown rendering in preview matches real wizard."""
        response = authenticated_client.get("/settings/wizard/preview/plex")
        assert response.status_code == 200

        response_text = response.get_data(as_text=True)

        # Markdown should be rendered to HTML (same as real wizard)
        assert "<h1>Welcome!</h1>" in response_text
        assert "<p>Please read our rules" in response_text

    def test_preview_requires_authentication(self, client):
        """Test that preview requires admin authentication."""
        response = client.get("/settings/wizard/preview/plex")
        # Should redirect to login
        assert response.status_code == 302
        assert "/login" in response.location

    def test_preview_different_server_types(
        self, authenticated_client, sample_media_server
    ):
        """Test preview works with different server types."""
        server_types = ["plex", "jellyfin", "emby", "audiobookshelf"]

        for server_type in server_types:
            # Create a step for this server type
            step = WizardStep(
                server_type=server_type,
                phase=WizardPhase.PRE,
                position=0,
                title=f"{server_type.title()} Welcome",
                markdown=f"# Welcome to {server_type.title()}",
            )
            db.session.add(step)
            db.session.commit()

            response = authenticated_client.get(
                f"/settings/wizard/preview/{server_type}"
            )
            assert response.status_code == 200

            response_text = response.get_data(as_text=True)
            assert f"Welcome to {server_type.title()}" in response_text

    def test_preview_with_no_steps_shows_join_only(
        self, authenticated_client, sample_media_server
    ):
        """Test preview with no wizard steps shows only join transition."""
        response = authenticated_client.get("/settings/wizard/preview/nonexistent")
        assert response.status_code == 200

        response_text = response.get_data(as_text=True)

        # Should show join step only
        assert "Accept Invitation" in response_text or "join" in response_text.lower()
        assert "Step 1 of 1" in response_text

    def test_preview_progress_calculation(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test progress calculation in preview mode."""
        # Total: 2 pre + 1 join + 1 post = 4 steps

        # Step 1 of 4 (25%)
        response = authenticated_client.get("/settings/wizard/preview/plex?step=0")
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)
        assert "Step 1 of 4" in response_text

        # Step 2 of 4 (50%)
        response = authenticated_client.get("/settings/wizard/preview/plex?step=1")
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)
        assert "Step 2 of 4" in response_text


class TestPreviewTemplateReuse:
    """Test that preview reuses actual wizard templates and rendering logic."""

    @pytest.fixture
    def sample_wizard_steps(self):
        """Create sample wizard steps for testing."""
        steps = []

        # Pre-invite steps
        pre_step1 = WizardStep(
            server_type="plex",
            phase=WizardPhase.PRE,
            position=0,
            title="Welcome to Plex",
            markdown="# Welcome!\n\nPlease read our rules before joining {{ settings.server_name }}.",
            require_interaction=False,
        )
        steps.append(pre_step1)

        for step in steps:
            db.session.add(step)
        db.session.commit()

        return steps

    @pytest.fixture
    def sample_media_server(self):
        """Create a sample media server for context."""
        server = MediaServer(
            server_type="plex",
            name="Test Plex Server",
            url="http://localhost:32400",
            external_url="https://plex.example.com",
        )
        db.session.add(server)
        db.session.commit()
        return server

    def test_preview_uses_wizard_frame_template(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that preview uses wizard/frame.html template structure."""
        response = authenticated_client.get("/settings/wizard/preview/plex")
        assert response.status_code == 200

        response_text = response.get_data(as_text=True)

        # Should have the same structure as wizard/frame.html
        assert 'class="overflow-x-hidden min-h-screen"' in response_text

    def test_preview_uses_wizard_steps_template_structure(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that preview uses wizard/steps.html template structure."""
        response = authenticated_client.get("/settings/wizard/preview/plex")
        assert response.status_code == 200

        response_text = response.get_data(as_text=True)

        # Should have same structure as wizard/steps.html
        assert 'id="wizard-wrapper"' in response_text
        assert (
            'class="min-h-screen flex flex-col justify-center items-center'
            in response_text
        )
        assert 'class="wizard-card-content p-6' in response_text

    def test_preview_navigation_buttons_match_wizard(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that preview navigation buttons match real wizard."""
        response = authenticated_client.get("/settings/wizard/preview/plex?step=1")
        assert response.status_code == 200

        response_text = response.get_data(as_text=True)

        # Should have navigation buttons like real wizard
        assert "Previous" in response_text or "‹" in response_text
        assert (
            "Next" in response_text
            or "›" in response_text
            or "Continue" in response_text
        )


class TestPreviewDRYCompliance:
    """Test that preview follows DRY principles and reuses existing logic."""

    @pytest.fixture
    def sample_wizard_steps(self):
        """Create sample wizard steps for testing."""
        steps = []

        # Pre-invite steps
        pre_step1 = WizardStep(
            server_type="plex",
            phase=WizardPhase.PRE,
            position=0,
            title="Welcome to Plex",
            markdown="# Welcome!\n\nPlease read our rules before joining {{ settings.server_name }}.",
            require_interaction=False,
        )
        steps.append(pre_step1)

        for step in steps:
            db.session.add(step)
        db.session.commit()

        return steps

    @pytest.fixture
    def sample_media_server(self):
        """Create a sample media server for context."""
        server = MediaServer(
            server_type="plex",
            name="Test Plex Server",
            url="http://localhost:32400",
            external_url="https://plex.example.com",
        )
        db.session.add(server)
        db.session.commit()
        return server

    def test_preview_reuses_markdown_rendering_logic(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that preview reuses the same markdown rendering as real wizard."""
        response = authenticated_client.get("/settings/wizard/preview/plex")
        assert response.status_code == 200

        response_text = response.get_data(as_text=True)

        # Should use same markdown extensions as real wizard
        # (fenced_code, tables, attr_list)
        assert "<h1>" in response_text  # Basic markdown rendering

    def test_preview_reuses_context_building_logic(
        self, authenticated_client, sample_wizard_steps, sample_media_server
    ):
        """Test that preview reuses same context building as real wizard."""
        response = authenticated_client.get("/settings/wizard/preview/plex")
        assert response.status_code == 200

        response_text = response.get_data(as_text=True)

        # Context variables should be available (same as real wizard)
        assert "Test Plex Server" in response_text  # server_name from context

        # Check that template variables are being processed (DRY compliance)
        # The markdown should NOT contain the raw template syntax
        assert "{{ settings.server_name }}" not in response_text
