"""
TDD tests for removing the "Action Required" blue notification bar.

This test suite verifies:
1. The blue notification bar is completely removed from wizard steps
2. Underlying interaction functionality is preserved
3. No regression in wizard step functionality
4. CSS classes and HTML elements related to the notification are removed
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

        # Create admin user for authentication (only if doesn't exist)
        existing_admin = AdminAccount.query.filter_by(username="admin").first()
        if not existing_admin:
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
def wizard_steps_with_interaction(app):
    """Create wizard steps with interaction requirements for testing."""
    with app.app_context():
        # Clear existing steps
        WizardStep.query.delete()
        db.session.commit()

        steps = []

        # Step that requires interaction
        interaction_step = WizardStep(
            server_type="plex",
            phase=WizardPhase.PRE,
            position=0,
            title="Rules and Terms",
            markdown="# Server Rules\n\nPlease read our [terms of service](https://example.com/terms) and [rules](https://example.com/rules) before continuing.",
            require_interaction=True,
        )
        steps.append(interaction_step)

        # Step that does not require interaction
        normal_step = WizardStep(
            server_type="plex",
            phase=WizardPhase.PRE,
            position=1,
            title="Welcome",
            markdown="# Welcome!\n\nThis is a normal step without interaction requirements.",
            require_interaction=False,
        )
        steps.append(normal_step)

        for step in steps:
            db.session.add(step)
        db.session.commit()

        # Create an invitation for testing
        from app.models import Invitation

        # Get the server ID within the same context
        server = MediaServer.query.filter_by(name="Test Plex Server").first()
        if not server:
            server = MediaServer(
                name="Test Plex Server",
                server_type="plex",
                url="http://localhost:32400",
            )
            db.session.add(server)
            db.session.commit()

        invitation = Invitation(
            code="test_invitation_code", server_id=server.id, unlimited=True
        )
        db.session.add(invitation)
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


class TestActionRequiredBarRemoval:
    """Test that the Action Required blue notification bar is completely removed."""

    def test_no_action_required_bar_for_interaction_steps(
        self, authenticated_client, wizard_steps_with_interaction, sample_media_server
    ):
        """Test that no Action Required bar appears even for steps requiring interaction."""
        # Set up wizard session to access the actual wizard (not preview)
        with authenticated_client.session_transaction() as sess:
            sess["wizard_access"] = "test_invitation_code"

        response = authenticated_client.get("/wizard/plex/0")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Should NOT show "Action Required" text anywhere
        assert "Action Required" not in html

        # Should NOT have the blue notification box CSS class
        assert 'class="wizard-interaction-notice' not in html
        assert "wizard-interaction-notice" not in html

        # Should NOT have alert role for the notification
        # (but may have other alert roles for different components)
        import re

        # Look specifically for the notification alert pattern
        notification_alert_pattern = (
            r'<div[^>]*class="[^"]*wizard-interaction-notice[^"]*"[^>]*role="alert"'
        )
        assert not re.search(notification_alert_pattern, html)

    def test_no_action_required_bar_for_normal_steps(
        self, authenticated_client, wizard_steps_with_interaction, sample_media_server
    ):
        """Test that no Action Required bar appears for normal steps (this should already pass)."""
        response = authenticated_client.get("/settings/wizard/preview/plex?step=1")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Should NOT show "Action Required" text
        assert "Action Required" not in html

        # Should NOT have the notification CSS class
        assert 'class="wizard-interaction-notice' not in html
        assert "wizard-interaction-notice" not in html

    def test_no_blue_notification_css_classes_present(
        self, authenticated_client, wizard_steps_with_interaction, sample_media_server
    ):
        """Test that CSS classes related to the blue notification are not present."""
        response = authenticated_client.get("/settings/wizard/preview/plex?step=0")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # CSS classes that were used for the blue notification should not be present
        assert "wizard-interaction-notice" not in html
        assert "bg-blue-50" not in html or "wizard-interaction-notice" not in html
        assert "border-blue-200" not in html or "wizard-interaction-notice" not in html

    def test_interaction_functionality_preserved(
        self, authenticated_client, wizard_steps_with_interaction, sample_media_server
    ):
        """Test that underlying interaction functionality is still working."""
        response = authenticated_client.get("/settings/wizard/preview/plex?step=0")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Should still have data attributes for interaction tracking
        assert 'data-interaction-required="true"' in html

        # Should still load the wizard-steps.js file for interaction logic
        assert "wizard-steps.js" in html or "attachInteractionGating" in html

        # Next button should still be disabled when interaction is required
        assert 'data-disabled="1"' in html or 'aria-disabled="true"' in html

    def test_wizard_card_component_renders_without_notification(
        self, authenticated_client, wizard_steps_with_interaction, sample_media_server
    ):
        """Test that wizard card component renders properly without the notification section."""
        response = authenticated_client.get("/settings/wizard/preview/plex?step=0")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Wizard card should still render
        assert 'class="wizard-card' in html
        assert 'class="wizard-card-content' in html
        assert 'class="wizard-content-area' in html

        # But the notification section should be completely gone
        notification_section_patterns = [
            r'<div[^>]*class="[^"]*wizard-interaction-notice[^"]*"[^>]*>.*?</div>',
            r"<!-- Interaction Required Notice -->",
            r'role="alert"[^>]*>.*?Action Required.*?</div>',
        ]

        import re

        for pattern in notification_section_patterns:
            assert not re.search(pattern, html, re.DOTALL), (
                f"Pattern '{pattern}' should not be found in HTML"
            )

    def test_all_wizard_templates_have_no_action_required_bar(
        self, authenticated_client, wizard_steps_with_interaction, sample_media_server
    ):
        """Test that Action Required bar is removed from all wizard templates."""
        # Test regular wizard steps
        with authenticated_client.session_transaction() as sess:
            sess["wizard_access"] = "test_invitation_code"

        response1 = authenticated_client.get("/wizard/plex/0")
        assert response1.status_code == 200
        html1 = response1.get_data(as_text=True)
        assert "Action Required" not in html1
        assert "wizard-interaction-notice" not in html1

        # Test wizard preview
        response2 = authenticated_client.get("/settings/wizard/preview/plex?step=0")
        assert response2.status_code == 200
        html2 = response2.get_data(as_text=True)
        assert "Action Required" not in html2
        assert "wizard-interaction-notice" not in html2

        # Test pre/post step template if it exists
        # This covers the other template that includes wizard_card.html
        try:
            response3 = authenticated_client.get("/wizard/plex/pre/0")
            if response3.status_code == 200:
                html3 = response3.get_data(as_text=True)
                assert "Action Required" not in html3
                assert "wizard-interaction-notice" not in html3
        except Exception:
            # Pre/post endpoint might not exist or be accessible in test environment
            pass


class TestRegressionPrevention:
    """Test that removing the notification doesn't break other functionality."""

    def test_wizard_navigation_still_works(
        self, authenticated_client, wizard_steps_with_interaction, sample_media_server
    ):
        """Test that wizard navigation is not broken by the removal."""
        # Set up wizard session
        with authenticated_client.session_transaction() as sess:
            sess["wizard_access"] = "test_invitation_code"

        # Should be able to access wizard step
        response = authenticated_client.get("/wizard/plex/0")
        assert response.status_code == 200

        # Should render wizard content
        html = response.get_data(as_text=True)
        assert "Server Rules" in html  # The step title
        assert "terms of service" in html  # The step content

    def test_admin_wizard_preview_still_works(
        self, authenticated_client, wizard_steps_with_interaction, sample_media_server
    ):
        """Test that admin wizard preview functionality is preserved."""
        response = authenticated_client.get("/settings/wizard/preview/plex?step=0")
        assert response.status_code == 200

        html = response.get_data(as_text=True)
        assert "Server Rules" in html  # The step title should be rendered
        assert response.content_type.startswith("text/html")

    def test_wizard_card_structure_intact(
        self, authenticated_client, wizard_steps_with_interaction, sample_media_server
    ):
        """Test that the wizard card structure is not broken by the removal."""
        response = authenticated_client.get("/settings/wizard/preview/plex?step=0")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Essential wizard card elements should still be present
        assert 'class="wizard-card' in html
        assert 'class="wizard-card-content' in html
        assert 'class="wizard-content-area' in html
        assert 'role="main"' in html
        assert 'aria-label="Wizard step content"' in html
