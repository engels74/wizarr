"""Test pre-wizard page styling and CSS loading."""

import pytest

from app import create_app
from app.extensions import db
from app.models import Invitation, MediaServer, WizardPhase, WizardStep


@pytest.fixture
def app():
    """Create application for testing."""
    app = create_app()
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SECRET_KEY"] = "test-secret-key"
    app.config["WTF_CSRF_ENABLED"] = False

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
def authenticated_client(client):
    """Create authenticated test client."""
    client.post("/login", data={"username": "admin", "password": "password"})
    return client


@pytest.fixture
def media_server(app):
    """Create a media server for testing."""
    with app.app_context():
        server = MediaServer(
            name="Test Plex Server",
            server_type="plex",
            url="http://localhost:32400",
            external_url="https://plex.example.com",
        )
        db.session.add(server)
        db.session.commit()
        return server


@pytest.fixture
def invitation(app, media_server):
    """Create an invitation for testing."""
    with app.app_context():
        invitation = Invitation(
            code="TESTCODE123",
            expires=None,
            unlimited=True,
        )
        db.session.add(invitation)
        db.session.flush()  # Get the ID

        # Add the server relationship
        invitation.servers.append(media_server)
        db.session.commit()

        # Return the code instead of the object to avoid session issues
        return "TESTCODE123"


@pytest.fixture
def pre_wizard_steps(app):
    """Create pre-invite wizard steps."""
    with app.app_context():
        # Check if steps already exist to avoid unique constraint violations
        existing_steps = WizardStep.query.filter(
            WizardStep.server_type == "plex", WizardStep.phase == WizardPhase.PRE
        ).all()

        if not existing_steps:
            steps = [
                WizardStep(
                    server_type="plex",
                    phase=WizardPhase.PRE,
                    position=0,
                    title="Welcome",
                    markdown="# Welcome to our server!\n\nPlease read our rules.",
                ),
                WizardStep(
                    server_type="plex",
                    phase=WizardPhase.PRE,
                    position=1,
                    title="Rules",
                    markdown="# Server Rules\n\n1. Be nice\n2. No spam",
                    require_interaction=True,
                ),
            ]
            db.session.add_all(steps)
            db.session.commit()
        else:
            steps = existing_steps

        return steps


class TestPreWizardStyling:
    """Test pre-wizard page styling and CSS loading."""

    def test_pre_wizard_page_loads_css_assets(
        self, client, invitation, pre_wizard_steps
    ):
        """Test that pre-wizard page loads required CSS assets."""
        with client.session_transaction() as sess:
            sess["invite_token"] = invitation
            sess["invitation_in_progress"] = True

        response = client.get("/pre-wizard")
        assert response.status_code == 200

        html_content = response.data.decode("utf-8")

        # Check that base.html CSS assets are loaded
        assert "main.css" in html_content, "main.css should be loaded"
        assert "animate.css" in html_content, "animate.css should be loaded"

        # Check for CSS link tags
        assert '<link rel="stylesheet"' in html_content, "Should have CSS link tags"

    def test_pre_wizard_template_extends_base(
        self, client, invitation, pre_wizard_steps
    ):
        """Test that pre-wizard template properly extends base.html."""
        with client.session_transaction() as sess:
            sess["invite_token"] = invitation
            sess["invitation_in_progress"] = True

        response = client.get("/pre-wizard")
        assert response.status_code == 200

        html_content = response.data.decode("utf-8")

        # Should have proper HTML structure from base.html
        assert "<html>" in html_content, "Should have html tag"
        assert "<head>" in html_content, "Should have head tag"
        assert "<body" in html_content, "Should have body tag"

        # Should have body class from base.html
        assert "bg-gray-50" in html_content or "dark:bg-gray-900" in html_content, (
            "Should have body background classes"
        )

    def test_pre_wizard_has_required_css_classes(
        self, client, invitation, pre_wizard_steps
    ):
        """Test that pre-wizard page contains required CSS classes."""
        with client.session_transaction() as sess:
            sess["invite_token"] = invitation
            sess["invitation_in_progress"] = True

        response = client.get("/pre-wizard")
        assert response.status_code == 200

        html_content = response.data.decode("utf-8")

        # Unified wizard layout elements
        assert 'id="wizard-wrapper"' in html_content, (
            "Should render unified wizard wrapper"
        )
        assert "prose" in html_content, "Should use prose typography container"
        assert "wizard-btn" in html_content, "Should include unified nav button classes"

    def test_pre_wizard_uses_unified_wizard_layout(
        self, client, invitation, pre_wizard_steps
    ):
        """Pre-wizard should use the same layout as /wizard (frame.html + steps.html)."""
        with client.session_transaction() as sess:
            sess["invite_token"] = invitation
            sess["invitation_in_progress"] = True

        response = client.get("/pre-wizard")
        assert response.status_code == 200
        html_content = response.data.decode("utf-8")

        # Key elements from templates/wizard/steps.html
        assert 'id="wizard-wrapper"' in html_content
        assert "wizard-btn" in html_content
        assert 'hx-target="#wizard-wrapper"' in html_content

    def test_pre_wizard_navigation_controls(self, client, invitation, pre_wizard_steps):
        """Unified navigation should be present with previous/next buttons and htmx attrs."""
        with client.session_transaction() as sess:
            sess["invite_token"] = invitation
            sess["invitation_in_progress"] = True

        response = client.get("/pre-wizard?step=0")
        assert response.status_code == 200
        html = response.get_data(as_text=True)

        # Prev hidden on first step
        assert "hx-vals=" in html and 'hx-swap="outerHTML"' in html
        # Next button present with id="next-btn"
        assert 'id="next-btn"' in html

    def test_pre_wizard_nav_buttons_unified(self, client, invitation, pre_wizard_steps):
        """Navigation buttons should use unified 'btn-nav' style like /wizard."""
        with client.session_transaction() as sess:
            sess["invite_token"] = invitation
            sess["invitation_in_progress"] = True

        response = client.get("/pre-wizard?step=0")
        assert response.status_code == 200
        html = response.get_data(as_text=True)

        assert "wizard-btn" in html
        # Previous hidden at first step
        assert 'hx-get="/pre-wizard?step=-1"' not in html

    def test_pre_wizard_hx_links_point_to_pre_wizard(
        self, client, invitation, pre_wizard_steps
    ):
        """Next/Prev links should target /pre-wizard with appropriate step param."""
        with client.session_transaction() as sess:
            sess["invite_token"] = invitation
            sess["invitation_in_progress"] = True

        response = client.get("/pre-wizard?step=0")
        assert response.status_code == 200
        html = response.get_data(as_text=True)

        assert (
            'hx-get="/pre-wizard?step=1"' in html
            or 'hx-get="/pre-wizard?step=1"' in html
        )

    def test_pre_wizard_responsive_styling(self, client, invitation, pre_wizard_steps):
        """Test that pre-wizard page includes responsive styling."""
        with client.session_transaction() as sess:
            sess["invite_token"] = invitation
            sess["invitation_in_progress"] = True

        response = client.get("/pre-wizard")
        assert response.status_code == 200

        html_content = response.data.decode("utf-8")

        # Check for responsive meta tag
        assert 'name="viewport"' in html_content, "Should have viewport meta tag"

        # Unified layout relies on external CSS; viewport meta validation is sufficient
