"""
Tests for invitation flow with pre/post wizard timing functionality.
"""

import pytest
from flask import session, url_for

from app.models import Invitation, MediaServer, WizardStep
from app.services.invitation_flow import InvitationFlowManager
from app.services.invitation_flow.results import ProcessingStatus


class TestInvitationFlowTiming:
    """Test invitation flow with timing-based wizard steps."""

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
            code="FLOW123",
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
                title="Welcome",
                markdown="# Welcome\nPlease read our rules.",
            ),
            WizardStep(
                server_type="plex",
                timing="before_invite_acceptance",
                position=1,
                title="Rules",
                markdown="# Rules\nFollow these guidelines.",
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
                title="Setup",
                markdown="# Setup\nConfigure your account.",
            ),
            WizardStep(
                server_type="plex",
                timing="after_invite_acceptance",
                position=1,
                title="Guide",
                markdown="# Guide\nHow to use the server.",
            ),
        ]
        session.add_all(steps)
        session.commit()
        return steps

    def test_invitation_display_with_pre_invite_steps(
        self, app, session, invitation_with_server, pre_invite_steps
    ):
        """Test invitation display redirects to pre-wizard when pre-invite steps exist."""
        with app.test_request_context():
            manager = InvitationFlowManager()
            result = manager.process_invitation_display("FLOW123")
            
            # Should redirect to pre-wizard
            assert result.redirect_url is not None
            assert "/wizard/pre-wizard/FLOW123" in result.redirect_url
            
            # Should set session data
            assert result.session_data is not None
            assert result.session_data.get("invite_code") == "FLOW123"

    def test_invitation_display_without_pre_invite_steps(
        self, app, session, invitation_with_server, post_invite_steps
    ):
        """Test invitation display shows normal invite page when no pre-invite steps exist."""
        with app.test_request_context():
            manager = InvitationFlowManager()
            result = manager.process_invitation_display("FLOW123")
            
            # Should show authentication form (Plex OAuth in this case)
            assert result.status == ProcessingStatus.OAUTH_PENDING
            assert result.template_data is not None
            assert result.redirect_url is None

    def test_invitation_display_no_wizard_steps(
        self, app, session, invitation_with_server
    ):
        """Test invitation display with no wizard steps at all."""
        with app.test_request_context():
            manager = InvitationFlowManager()
            result = manager.process_invitation_display("FLOW123")
            
            # Should show normal authentication form (Plex OAuth in this case)
            assert result.status == ProcessingStatus.OAUTH_PENDING
            assert result.template_data is not None
            assert result.redirect_url is None

    def test_successful_invitation_redirects_to_post_wizard(
        self, app, session, invitation_with_server, post_invite_steps
    ):
        """Test successful invitation processing redirects to post-wizard."""
        with app.test_request_context():
            manager = InvitationFlowManager()
            
            # Mock form data for successful submission
            form_data = {
                "code": "FLOW123",
                "username": "testuser",
                "password": "testpass",
                "email": "test@example.com",
            }
            
            # Mock the invitation processing to return success
            # In real implementation, this would create the user account
            with pytest.MonkeyPatch().context() as m:
                def mock_process_servers(self, servers, form_data, code):
                    from app.services.invitation_flow.results import ServerResult
                    return [ServerResult(servers[0], True, "Success", True)], []
                
                m.setattr(
                    "app.services.invitation_flow.workflows.FormBasedWorkflow._process_servers",
                    mock_process_servers
                )
                
                result = manager.process_invitation_submission(form_data)
                
                # Should redirect to post-wizard
                assert result.redirect_url == "/wizard/post-wizard"
                assert result.session_data is not None
                assert result.session_data.get("wizard_access") == "FLOW123"

    def test_successful_invitation_without_post_steps_redirects_to_completion(
        self, app, session, invitation_with_server
    ):
        """Test successful invitation without post-invite steps redirects to completion."""
        with app.test_request_context():
            manager = InvitationFlowManager()
            
            form_data = {
                "code": "FLOW123",
                "username": "testuser",
                "password": "testpass",
                "email": "test@example.com",
            }
            
            with pytest.MonkeyPatch().context() as m:
                def mock_process_servers(self, servers, form_data, code):
                    from app.services.invitation_flow.results import ServerResult
                    return [ServerResult(servers[0], True, "Success", True)], []
                
                m.setattr(
                    "app.services.invitation_flow.workflows.FormBasedWorkflow._process_servers",
                    mock_process_servers
                )
                
                result = manager.process_invitation_submission(form_data)
                
                # Should redirect to completion page or dashboard
                assert result.redirect_url in ["/wizard/completion", "/"]
                assert result.session_data is not None

    def test_invitation_flow_session_management(
        self, app, session, invitation_with_server, pre_invite_steps
    ):
        """Test session management during invitation flow."""
        with app.test_request_context():
            with app.test_client() as client:
                # Simulate accessing invite URL
                response = client.get("/j/FLOW123")
                
                # Should redirect to pre-wizard
                assert response.status_code == 302
                assert "/wizard/pre-wizard/FLOW123" in response.location
                
                # Session should contain invite code
                with client.session_transaction() as sess:
                    assert sess.get("invite_code") == "FLOW123"

    def test_pre_wizard_completion_redirects_to_invite_page(
        self, app, session, invitation_with_server, pre_invite_steps
    ):
        """Test completing pre-wizard redirects to invitation page."""
        with app.test_request_context():
            with app.test_client() as client:
                # Set up session as if user is in pre-wizard
                with client.session_transaction() as sess:
                    sess["invite_code"] = "FLOW123"
                    sess["pre_wizard_completed"] = True
                
                # Access the invitation page after pre-wizard completion
                response = client.get("/j/FLOW123")
                
                # Should show the invitation form, not redirect to pre-wizard again
                assert response.status_code == 200
                # Should contain invitation form elements
                assert b"Join Server" in response.data or b"Create Account" in response.data

    def test_invitation_flow_with_mixed_timing_steps(
        self, app, session, invitation_with_server, pre_invite_steps, post_invite_steps
    ):
        """Test invitation flow with both pre and post invite steps."""
        with app.test_request_context():
            manager = InvitationFlowManager()
            
            # Initial display should redirect to pre-wizard
            result = manager.process_invitation_display("FLOW123")
            assert "/wizard/pre-wizard/FLOW123" in result.redirect_url
            
            # After successful invitation, should redirect to post-wizard
            form_data = {
                "code": "FLOW123",
                "username": "testuser",
                "password": "testpass",
                "email": "test@example.com",
            }
            
            with pytest.MonkeyPatch().context() as m:
                def mock_process_servers(self, servers, form_data, code):
                    from app.services.invitation_flow.results import ServerResult
                    return [ServerResult(servers[0], True, "Success", True)], []
                
                m.setattr(
                    "app.services.invitation_flow.workflows.FormBasedWorkflow._process_servers",
                    mock_process_servers
                )
                
                result = manager.process_invitation_submission(form_data)
                assert result.redirect_url == "/wizard/post-wizard"

    def test_invitation_flow_invalid_code(self, app, session):
        """Test invitation flow with invalid invitation code."""
        with app.test_request_context():
            manager = InvitationFlowManager()
            result = manager.process_invitation_display("INVALID")
            
            assert result.status == ProcessingStatus.INVALID_INVITATION
            assert result.template_data is not None
            assert result.template_data["template_name"] == "invalid-invite.html"

    def test_invitation_flow_multiple_servers_with_different_steps(self, session):
        """Test invitation flow with multiple servers having different timing steps."""
        # Create additional server
        jellyfin_server = MediaServer(
            name="Test Jellyfin Server",
            server_type="jellyfin",
            url="http://jellyfin.example.com",
            api_key="jellyfin_key",
        )
        session.add(jellyfin_server)
        
        # Create invitation with multiple servers
        invitation = Invitation(code="MULTI123", used=False, unlimited=False)
        session.add(invitation)
        session.commit()
        
        plex_server = MediaServer.query.filter_by(server_type="plex").first()
        invitation.servers.extend([plex_server, jellyfin_server])
        session.commit()
        
        # Create steps for different servers
        steps = [
            WizardStep(
                server_type="plex",
                timing="before_invite_acceptance",
                position=0,
                title="Plex Pre-step",
                markdown="# Plex Welcome",
            ),
            WizardStep(
                server_type="jellyfin",
                timing="before_invite_acceptance",
                position=0,
                title="Jellyfin Pre-step",
                markdown="# Jellyfin Welcome",
            ),
        ]
        session.add_all(steps)
        session.commit()
        
        with app.test_request_context():
            manager = InvitationFlowManager()
            result = manager.process_invitation_display("MULTI123")
            
            # Should redirect to pre-wizard since both servers have pre-invite steps
            assert "/wizard/pre-wizard/MULTI123" in result.redirect_url

    def test_session_cleanup_after_invitation_completion(
        self, app, session, invitation_with_server, post_invite_steps
    ):
        """Test session cleanup after completing invitation flow."""
        with app.test_request_context():
            with app.test_client() as client:
                # Set up session with invitation data
                with client.session_transaction() as sess:
                    sess["invite_code"] = "FLOW123"
                    sess["pre_wizard_completed"] = True
                    sess["invitation_in_progress"] = True
                
                # Complete the invitation process
                form_data = {
                    "code": "FLOW123",
                    "username": "testuser",
                    "password": "testpass",
                    "email": "test@example.com",
                }
                
                response = client.post("/invitation/process", data=form_data)
                
                # Should redirect to post-wizard
                assert response.status_code == 302
                assert "/wizard/post-wizard" in response.location
                
                # Session should be updated with wizard access
                with client.session_transaction() as sess:
                    assert sess.get("wizard_access") == "FLOW123"
                    # invitation_in_progress might still be set for wizard access
