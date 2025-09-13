"""
Tests for wizard routes with pre/post timing functionality.
"""

import pytest
from flask import session, url_for

from app.models import Invitation, MediaServer, WizardStep


class TestWizardRoutesTiming:
    """Test wizard routes with timing-based functionality."""

    @pytest.fixture
    def media_server(self, session):
        """Create a test media server."""
        server = MediaServer(
            name="Test Plex Server",
            server_type="plex",
            url="http://test.example.com",
            api_key="test_key",
        )
        session.add(server)
        session.commit()
        return server

    @pytest.fixture
    def invitation_with_server(self, session, media_server):
        """Create a test invitation linked to a server."""
        invitation = Invitation(
            code="ROUTE123",
            used=False,
            unlimited=False,
        )
        session.add(invitation)
        session.commit()
        
        invitation.servers.append(media_server)
        session.commit()
        return invitation

    @pytest.fixture
    def pre_invite_steps(self, session):
        """Create pre-invite wizard steps."""
        steps = [
            WizardStep(
                server_type="plex",
                timing="before_invite_acceptance",
                position=0,
                title="Pre-invite Welcome",
                markdown="# Welcome\nPlease read our rules before joining.",
            ),
            WizardStep(
                server_type="plex",
                timing="before_invite_acceptance",
                position=1,
                title="Pre-invite Rules",
                markdown="# Rules\nPlease follow these guidelines.",
            ),
        ]
        session.add_all(steps)
        session.commit()
        return steps

    @pytest.fixture
    def post_invite_steps(self, session):
        """Create post-invite wizard steps."""
        steps = [
            WizardStep(
                server_type="plex",
                timing="after_invite_acceptance",
                position=0,
                title="Post-invite Setup",
                markdown="# Setup\nConfigure your account settings.",
            ),
            WizardStep(
                server_type="plex",
                timing="after_invite_acceptance",
                position=1,
                title="Post-invite Guide",
                markdown="# Guide\nLearn how to use the server.",
            ),
        ]
        session.add_all(steps)
        session.commit()
        return steps

    def test_pre_wizard_route_entry_point(
        self, app, session, invitation_with_server, pre_invite_steps
    ):
        """Test /wizard/pre-wizard/<code> route entry point."""
        with app.test_client() as client:
            response = client.get("/wizard/pre-wizard/ROUTE123")
            
            assert response.status_code == 200
            assert b"Pre-invite Welcome" in response.data
            
            # Should set session data
            with client.session_transaction() as sess:
                assert sess.get("invite_code") == "ROUTE123"
                assert sess.get("current_pre_wizard_step") == 0

    def test_pre_wizard_route_specific_step(
        self, app, session, invitation_with_server, pre_invite_steps
    ):
        """Test /wizard/pre-wizard/<code>/<int:idx> route."""
        with app.test_client() as client:
            # Set up session
            with client.session_transaction() as sess:
                sess["invite_code"] = "ROUTE123"
            
            response = client.get("/wizard/pre-wizard/ROUTE123/1")
            
            assert response.status_code == 200
            assert b"Pre-invite Rules" in response.data

    def test_pre_wizard_route_invalid_code(self, app, session):
        """Test pre-wizard route with invalid invitation code."""
        with app.test_client() as client:
            response = client.get("/wizard/pre-wizard/INVALID")
            
            assert response.status_code == 404 or response.status_code == 302
            # Should redirect to invalid invite page or return 404

    def test_pre_wizard_route_no_pre_steps(
        self, app, session, invitation_with_server
    ):
        """Test pre-wizard route when no pre-invite steps exist."""
        with app.test_client() as client:
            response = client.get("/wizard/pre-wizard/ROUTE123")
            
            # Should redirect to main invitation page or show empty wizard
            assert response.status_code in [302, 404]

    def test_pre_wizard_route_step_navigation(
        self, app, session, invitation_with_server, pre_invite_steps
    ):
        """Test navigation between pre-wizard steps."""
        with app.test_client() as client:
            # Start at first step
            response = client.get("/wizard/pre-wizard/ROUTE123/0")
            assert response.status_code == 200
            assert b"Pre-invite Welcome" in response.data
            
            # Navigate to second step
            response = client.get("/wizard/pre-wizard/ROUTE123/1")
            assert response.status_code == 200
            assert b"Pre-invite Rules" in response.data
            
            # Try to access non-existent step
            response = client.get("/wizard/pre-wizard/ROUTE123/99")
            assert response.status_code == 404

    def test_pre_wizard_completion_redirect(
        self, app, session, invitation_with_server, pre_invite_steps
    ):
        """Test pre-wizard completion redirects to invitation page."""
        with app.test_client() as client:
            # Set up session as if user completed pre-wizard
            with client.session_transaction() as sess:
                sess["invite_code"] = "ROUTE123"
                sess["pre_wizard_completed"] = True
            
            # Access completion endpoint
            response = client.post("/wizard/pre-wizard/ROUTE123/complete")
            
            assert response.status_code == 302
            assert "/j/ROUTE123" in response.location

    def test_post_wizard_route_entry_point(
        self, app, session, invitation_with_server, post_invite_steps
    ):
        """Test /wizard/post-wizard route entry point."""
        with app.test_client() as client:
            # Set up session as if user just completed invitation
            with client.session_transaction() as sess:
                sess["wizard_access"] = "ROUTE123"
                sess["invitation_completed"] = True
            
            response = client.get("/wizard/post-wizard")
            
            assert response.status_code == 200
            assert b"Post-invite Setup" in response.data

    def test_post_wizard_route_specific_step(
        self, app, session, invitation_with_server, post_invite_steps
    ):
        """Test /wizard/post-wizard/<int:idx> route."""
        with app.test_client() as client:
            # Set up session
            with client.session_transaction() as sess:
                sess["wizard_access"] = "ROUTE123"
            
            response = client.get("/wizard/post-wizard/1")
            
            assert response.status_code == 200
            assert b"Post-invite Guide" in response.data

    def test_post_wizard_route_no_session(self, app, session):
        """Test post-wizard route without proper session."""
        with app.test_client() as client:
            response = client.get("/wizard/post-wizard")
            
            # Should redirect to login or home page
            assert response.status_code == 302

    def test_post_wizard_route_no_post_steps(
        self, app, session, invitation_with_server
    ):
        """Test post-wizard route when no post-invite steps exist."""
        with app.test_client() as client:
            # Set up session
            with client.session_transaction() as sess:
                sess["wizard_access"] = "ROUTE123"
            
            response = client.get("/wizard/post-wizard")
            
            # Should redirect to completion page or show empty wizard
            assert response.status_code in [302, 404]

    def test_post_wizard_completion(
        self, app, session, invitation_with_server, post_invite_steps
    ):
        """Test post-wizard completion."""
        with app.test_client() as client:
            # Set up session
            with client.session_transaction() as sess:
                sess["wizard_access"] = "ROUTE123"
            
            # Complete post-wizard
            response = client.post("/wizard/post-wizard/complete")
            
            assert response.status_code == 302
            # Should redirect to completion page or dashboard
            assert response.location in ["/wizard/completion", "/"]

    def test_wizard_route_htmx_requests(
        self, app, session, invitation_with_server, pre_invite_steps
    ):
        """Test wizard routes handle HTMX requests correctly."""
        with app.test_client() as client:
            # HTMX request for pre-wizard step
            response = client.get(
                "/wizard/pre-wizard/ROUTE123/0",
                headers={"HX-Request": "true"}
            )
            
            assert response.status_code == 200
            # Should return partial template for HTMX
            assert b"Pre-invite Welcome" in response.data
            # Should not include full page layout for HTMX requests

    def test_wizard_route_step_progression(
        self, app, session, invitation_with_server, pre_invite_steps
    ):
        """Test step progression tracking in session."""
        with app.test_client() as client:
            # Access first step
            response = client.get("/wizard/pre-wizard/ROUTE123/0")
            assert response.status_code == 200
            
            with client.session_transaction() as sess:
                assert sess.get("current_pre_wizard_step") == 0
            
            # Progress to next step
            response = client.post("/wizard/pre-wizard/ROUTE123/0/next")
            assert response.status_code == 302
            assert "/wizard/pre-wizard/ROUTE123/1" in response.location
            
            with client.session_transaction() as sess:
                assert sess.get("current_pre_wizard_step") == 1

    def test_wizard_route_step_validation(
        self, app, session, invitation_with_server, pre_invite_steps
    ):
        """Test step validation and interaction requirements."""
        # Create step that requires interaction
        interaction_step = WizardStep(
            server_type="plex",
            timing="before_invite_acceptance",
            position=2,
            title="Interactive Step",
            markdown="# Interactive\nClick the button to continue.",
            require_interaction=True,
        )
        session.add(interaction_step)
        session.commit()
        
        with app.test_client() as client:
            # Access interactive step
            response = client.get("/wizard/pre-wizard/ROUTE123/2")
            assert response.status_code == 200
            assert b"Interactive Step" in response.data
            
            # Try to proceed without interaction
            response = client.post("/wizard/pre-wizard/ROUTE123/2/next")
            # Should not allow progression without interaction
            assert response.status_code in [400, 422]  # Bad request or validation error

    def test_wizard_route_session_security(self, app, session, invitation_with_server):
        """Test wizard routes properly validate session data."""
        with app.test_client() as client:
            # Try to access pre-wizard without proper session
            response = client.get("/wizard/pre-wizard/ROUTE123/0")
            
            # Should either redirect or require proper session setup
            if response.status_code == 200:
                # If allowed, should set up session properly
                with client.session_transaction() as sess:
                    assert sess.get("invite_code") == "ROUTE123"
            else:
                # Should redirect to proper entry point
                assert response.status_code == 302

    def test_wizard_route_error_handling(self, app, session):
        """Test wizard routes handle errors gracefully."""
        with app.test_client() as client:
            # Non-existent invitation
            response = client.get("/wizard/pre-wizard/NONEXISTENT/0")
            assert response.status_code in [404, 302]
            
            # Invalid step index
            response = client.get("/wizard/pre-wizard/ROUTE123/-1")
            assert response.status_code == 404
            
            # Malformed URLs
            response = client.get("/wizard/pre-wizard/")
            assert response.status_code == 404

    def test_wizard_route_mixed_timing_flow(
        self, app, session, invitation_with_server, pre_invite_steps, post_invite_steps
    ):
        """Test complete flow from pre-wizard through post-wizard."""
        with app.test_client() as client:
            # Start with pre-wizard
            response = client.get("/wizard/pre-wizard/ROUTE123")
            assert response.status_code == 200
            
            # Complete pre-wizard steps
            response = client.post("/wizard/pre-wizard/ROUTE123/complete")
            assert response.status_code == 302
            assert "/j/ROUTE123" in response.location
            
            # After invitation acceptance, should access post-wizard
            with client.session_transaction() as sess:
                sess["wizard_access"] = "ROUTE123"
                sess["invitation_completed"] = True
            
            response = client.get("/wizard/post-wizard")
            assert response.status_code == 200
            assert b"Post-invite Setup" in response.data
