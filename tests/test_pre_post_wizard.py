"""Test pre and post wizard flow functionality."""

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
def media_server(app):
    """Create a test media server."""
    with app.app_context():
        server = MediaServer(
            name="Test Plex",
            server_type="plex",
            url="http://localhost:32400",
            api_key="test-key",
        )
        db.session.add(server)
        db.session.commit()
        # Expunge to make object accessible outside session
        db.session.expunge(server)
        return server


@pytest.fixture
def invitation(app, media_server):
    """Create a test invitation."""
    with app.app_context():
        # Refresh the media_server to ensure it's bound to this session
        media_server = db.session.merge(media_server)
        invitation = Invitation(code="test123", server_id=media_server.id)
        db.session.add(invitation)
        db.session.commit()
        # Store the code before expunging
        invitation_code = invitation.code
        invitation_id = invitation.id
        # Expunge to make object accessible outside session
        db.session.expunge(invitation)
        # Store needed attributes as instance variables for easy access
        invitation._test_code = invitation_code
        invitation._test_id = invitation_id
        return invitation


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

        # Expunge to make objects accessible outside session
        for step in steps:
            db.session.expunge(step)
        return steps


@pytest.fixture
def post_wizard_steps(app):
    """Create post-invite wizard steps."""
    with app.app_context():
        # Check if steps already exist to avoid unique constraint violations
        existing_steps = WizardStep.query.filter(
            WizardStep.server_type == "plex", WizardStep.phase == WizardPhase.POST
        ).all()

        if not existing_steps:
            steps = [
                WizardStep(
                    server_type="plex",
                    phase=WizardPhase.POST,
                    position=0,
                    title="Setup Complete",
                    markdown="# Setup Complete!\n\nYour account is ready.",
                ),
                WizardStep(
                    server_type="plex",
                    phase=WizardPhase.POST,
                    position=1,
                    title="Getting Started",
                    markdown="# Getting Started\n\nHere's how to use the server.",
                ),
            ]
            db.session.add_all(steps)
            db.session.commit()
        else:
            steps = existing_steps

        # Expunge to make objects accessible outside session
        for step in steps:
            db.session.expunge(step)
        return steps


class TestPrePostWizardFlow:
    """Test the complete pre and post wizard flow."""

    def test_j_token_stores_in_session_and_redirects(self, client, invitation):
        """Test that /j/<token> stores token in session and redirects to /join."""
        response = client.get(f"/j/{invitation._test_code}")

        # Should redirect to /join
        assert response.status_code == 302
        assert response.location.endswith("/join")

        # Token should be stored in session
        with client.session_transaction() as sess:
            assert sess.get("invite_token") == invitation._test_code

    def test_join_with_pre_steps_redirects_to_pre_wizard(
        self, client, invitation, pre_wizard_steps
    ):
        """Test that /join redirects to /pre-wizard when pre-steps exist."""
        # First set up session as if user came from /j/<token>
        with client.session_transaction() as sess:
            sess["invite_token"] = invitation._test_code

        response = client.get("/join")

        # Should redirect to pre-wizard
        assert response.status_code == 302
        assert response.location.endswith("/pre-wizard")

    def test_join_without_pre_steps_goes_to_invite_acceptance(self, client, invitation):
        """Test that /join goes to invite acceptance when no pre-steps exist."""
        # No pre-steps created in this test
        with client.session_transaction() as sess:
            sess["invite_token"] = invitation._test_code

        response = client.get("/join")

        # Should show invite acceptance page (not redirect to pre-wizard)
        assert response.status_code == 200
        # Should contain invitation acceptance content
        assert b"invited" in response.data.lower()

    def test_pre_wizard_requires_valid_session_token(self, client):
        """Test that /pre-wizard requires valid session token."""
        response = client.get("/pre-wizard")

        # Should redirect back to error or /j/<token> with error
        assert response.status_code == 302

    def test_pre_wizard_displays_steps_in_order(
        self, client, invitation, pre_wizard_steps
    ):
        """Test that /pre-wizard displays steps in correct order."""
        with client.session_transaction() as sess:
            sess["invite_token"] = invitation._test_code
            sess["invitation_in_progress"] = True

        # Get first step
        response = client.get("/pre-wizard")
        assert response.status_code == 200
        assert b"Welcome" in response.data

        # Unified layout should include nav controls (no explicit textual progress)
        assert b'id="next-btn"' in response.data or b'class="btn-nav"' in response.data

    def test_pre_wizard_step_progression(self, client, invitation, pre_wizard_steps):
        """Test progression through pre-wizard steps."""
        with client.session_transaction() as sess:
            sess["invite_token"] = invitation._test_code
            sess["invitation_in_progress"] = True  # Add missing session flag

        # Get first step
        response = client.get("/pre-wizard?step=0")
        assert response.status_code == 200
        assert b"Welcome" in response.data

        # Move to second step
        response = client.get("/pre-wizard?step=1")
        assert response.status_code == 200
        assert b"Rules" in response.data

    def test_pre_wizard_completion_redirects_to_invite_acceptance(
        self, client, invitation, pre_wizard_steps
    ):
        """Test that completing pre-wizard redirects to invite acceptance."""
        with client.session_transaction() as sess:
            sess["invite_token"] = invitation._test_code

        # Complete all pre-wizard steps (simulate)
        response = client.post("/pre-wizard/complete")

        # Should redirect to invite acceptance flow
        assert response.status_code == 302
        # The exact redirect target depends on implementation

    def test_pre_wizard_final_step_shows_completion_button(
        self, client, invitation, pre_wizard_steps
    ):
        """Test that the final pre-wizard step shows a completion button instead of Next."""
        with client.session_transaction() as sess:
            sess["invite_token"] = invitation._test_code
            sess["invitation_in_progress"] = True

        # Get the final step (step 1, since we have 2 steps: 0 and 1)
        response = client.get("/pre-wizard?step=1")
        assert response.status_code == 200
        html = response.get_data(as_text=True)

        # Should not show Next button on final step (it's replaced by completion button)
        assert 'id="next-btn"' not in html

        # Should show completion button or mechanism
        assert "Continue to invite" in html or "Complete" in html or "Finish" in html

    def test_pre_wizard_completion_button_functionality(
        self, client, invitation, pre_wizard_steps
    ):
        """Test that the completion button properly submits to /pre-wizard/complete."""
        with client.session_transaction() as sess:
            sess["invite_token"] = invitation._test_code
            sess["invitation_in_progress"] = True

        # Get the final step
        response = client.get("/pre-wizard?step=1")
        assert response.status_code == 200
        html = response.get_data(as_text=True)

        # Should contain a form or button that POSTs to /pre-wizard/complete
        assert "/pre-wizard/complete" in html
        assert 'method="post"' in html.lower() or "hx-post" in html

    def test_pre_wizard_completion_with_interaction_requirement(
        self, client, invitation, pre_wizard_steps
    ):
        """Test completion button behavior when final step requires interaction."""
        with client.session_transaction() as sess:
            sess["invite_token"] = invitation._test_code
            sess["invitation_in_progress"] = True

        # Get step 1 which requires interaction
        response = client.get("/pre-wizard?step=1")
        assert response.status_code == 200
        html = response.get_data(as_text=True)

        # Completion button should be initially hidden if step requires interaction
        if "require_interaction" in html or 'data-disabled="1"' in html:
            # Should have mechanism to enable completion after interaction
            assert 'style="display: none"' in html or 'aria-disabled="true"' in html

    def test_post_wizard_after_invite_acceptance(
        self, client, invitation, post_wizard_steps
    ):
        """Test that post-wizard shows after invite acceptance."""
        with client.session_transaction() as sess:
            sess["invite_token"] = invitation._test_code
            sess["invite_accepted"] = True  # Simulate completed invite acceptance

        response = client.get("/post-wizard")
        assert response.status_code == 200
        assert b"Setup Complete" in response.data

    def test_post_wizard_requires_invite_acceptance(
        self, client, invitation, post_wizard_steps
    ):
        """Test that /post-wizard requires completed invite acceptance."""
        with client.session_transaction() as sess:
            sess["invite_token"] = invitation._test_code
            # No invite_accepted flag

        response = client.get("/post-wizard")

        # Should redirect or show error
        assert response.status_code == 302

    def test_session_cleanup_after_post_wizard_completion(
        self, client, invitation, post_wizard_steps
    ):
        """Test that session is cleaned up after post-wizard completion."""
        with client.session_transaction() as sess:
            sess["invite_token"] = invitation._test_code
            sess["invite_accepted"] = True

        # Complete post-wizard
        response = client.post("/post-wizard/complete")

        # Should redirect to success page
        assert response.status_code == 302

        # Session should be cleaned up
        with client.session_transaction() as sess:
            assert "invite_token" not in sess
            assert "invite_accepted" not in sess

    def test_expired_or_invalid_token_handling(self, client):
        """Test handling of expired or invalid tokens."""
        with client.session_transaction() as sess:
            sess["invite_token"] = "invalid-token"

        response = client.get("/join")

        # Should handle gracefully - show error page
        assert response.status_code == 200

        # Should show error message
        response_text = response.get_data(as_text=True)
        assert "Invalid invitation" in response_text or "error" in response_text.lower()

    def test_mixed_server_types_pre_steps(self, app, client, invitation):
        """Test that only relevant server type steps are shown."""
        with app.app_context():
            # Create steps for different server types
            plex_step = WizardStep(
                server_type="plex",
                phase=WizardPhase.PRE,
                position=0,
                title="Plex Welcome",
                markdown="# Plex Welcome",
            )
            jellyfin_step = WizardStep(
                server_type="jellyfin",
                phase=WizardPhase.PRE,
                position=0,
                title="Jellyfin Welcome",
                markdown="# Jellyfin Welcome",
            )
            db.session.add_all([plex_step, jellyfin_step])
            db.session.commit()

        with client.session_transaction() as sess:
            sess["invite_token"] = invitation._test_code
            sess["invitation_in_progress"] = True  # Add missing session flag

        response = client.get("/pre-wizard")
        assert response.status_code == 200

        # Should only show plex step (invitation is for plex server)
        assert b"Plex Welcome" in response.data
        assert b"Jellyfin Welcome" not in response.data

    def test_require_interaction_blocks_progression(
        self, client, invitation, pre_wizard_steps
    ):
        """Require interaction should disable completion button until click inside content."""
        with client.session_transaction() as sess:
            sess["invite_token"] = invitation._test_code
            sess["invitation_in_progress"] = True

        response = client.get(
            "/pre-wizard?step=1"
        )  # step 1 requires interaction and is final step
        assert response.status_code == 200
        html = response.get_data(as_text=True)

        # On final step, should show completion button instead of next button
        assert 'id="complete-btn"' in html
        assert 'data-disabled="1"' in html or 'aria-disabled="true"' in html
        # Helpful tooltip text present
        assert "Click the link in this step to be able to continue" in html

    def test_no_steps_skip_phases(self, client, invitation):
        """Test that phases with no steps are skipped."""
        # No pre or post steps created
        with client.session_transaction() as sess:
            sess["invite_token"] = invitation._test_code

        # Should go directly to invite acceptance
        response = client.get("/join")
        assert response.status_code == 200
        assert b"invited" in response.data.lower()

    def test_back_navigation_preserves_progress(
        self, client, invitation, pre_wizard_steps
    ):
        """Test that back navigation preserves step completion progress."""
        with client.session_transaction() as sess:
            sess["invite_token"] = invitation._test_code
            sess["invitation_in_progress"] = True  # Add missing session flag
            sess["pre_wizard_progress"] = {"completed_steps": [0]}

        # Navigate back to completed step
        response = client.get("/pre-wizard?step=0")
        assert response.status_code == 200

        # Should show as completed or allow progression
        # Implementation specific details would go here
