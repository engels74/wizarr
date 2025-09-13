"""
Comprehensive test suite for Plex OAuth invitation flow.
Tests both success and failure scenarios to identify and prevent intermittent failures.
"""

from unittest.mock import Mock, patch

import pytest

from app.extensions import db
from app.models import Invitation, MediaServer, User
from app.services.media.plex import PlexInvitationError, handle_oauth_token


class TestPlexOAuthFlow:
    """Test the complete Plex OAuth invitation flow."""

    @pytest.fixture
    def plex_server(self):
        """Create a test Plex server."""
        server = MediaServer(
            name="Test Plex Server",
            server_type="plex",
            url="http://localhost:32400",
            api_key="test_admin_token",
        )
        db.session.add(server)
        db.session.commit()
        return server

    @pytest.fixture
    def plex_invitation(self, plex_server):
        """Create a test invitation for Plex server."""
        invitation = Invitation(code="PLEX123", used=False, unlimited=False)
        db.session.add(invitation)
        db.session.commit()

        # Link invitation to server
        invitation.servers.append(plex_server)
        db.session.commit()
        return invitation

    @pytest.fixture
    def mock_plex_account(self):
        """Mock MyPlexAccount for testing."""
        with patch("app.services.media.plex.MyPlexAccount") as mock:
            account = Mock()
            account.email = "test@example.com"
            account.username = "testuser"
            mock.return_value = account
            yield account

    def test_successful_oauth_flow(self, client, plex_invitation, mock_plex_account):
        """Test successful OAuth flow from start to finish."""
        with client.session_transaction() as sess:
            sess["invite_token"] = plex_invitation.code
            sess["invitation_in_progress"] = True

        # Mock PlexClient and its methods
        with patch("app.services.media.plex.PlexClient") as mock_client_class:
            mock_client = Mock()
            mock_client._create_user_with_identity_linking.return_value = Mock(id=1)
            mock_client_class.return_value = mock_client

            # Mock all necessary functions
            with (
                patch("app.services.media.plex._invite_user") as mock_invite,
                patch("app.services.invites.mark_server_used") as mock_mark_used,
                patch("app.services.media.plex.notify") as mock_notify,
                patch("app.services.media.plex.threading.Thread"),
            ):
                            # Test the POST request with OAuth token
                            response = client.post(
                                "/join",
                                data={
                                    "code": plex_invitation.code,
                                    "token": "valid_oauth_token",
                                },
                            )

                            # Should redirect to post-wizard or success page
                            assert response.status_code in [200, 302]

                            # Verify user was created
                            mock_client._create_user_with_identity_linking.assert_called_once()

                            # Verify invitation was processed
                            mock_invite.assert_called_once()
                            mock_mark_used.assert_called_once()
                            mock_notify.assert_called_once()

    def test_oauth_token_validation_failure(self, client, plex_invitation):
        """Test OAuth flow when token validation fails."""
        with client.session_transaction() as sess:
            sess["invite_token"] = plex_invitation.code
            sess["invitation_in_progress"] = True

        # Mock MyPlexAccount to raise an exception
        with patch("app.services.media.plex.MyPlexAccount") as mock_account:
            mock_account.side_effect = Exception("Invalid token")

            response = client.post(
                "/join",
                data={"code": plex_invitation.code, "token": "invalid_oauth_token"},
            )

            # Should return error page with Plex invitation failed message
            assert response.status_code == 200
            assert b"Plex invitation failed" in response.data

    def test_oauth_flow_with_plex_api_error(
        self, client, plex_invitation, mock_plex_account
    ):
        """Test OAuth flow when Plex API returns an error."""
        with client.session_transaction() as sess:
            sess["invite_token"] = plex_invitation.code
            sess["invitation_in_progress"] = True

        # Mock PlexClient to raise PlexInvitationError
        with patch("app.services.media.plex.PlexClient") as mock_client_class:
            mock_client = Mock()
            mock_client._create_user_with_identity_linking.side_effect = (
                PlexInvitationError("User already exists")
            )
            mock_client_class.return_value = mock_client

            # Mock _invite_user to raise PlexInvitationError
            with patch("app.services.media.plex._invite_user") as mock_invite:
                mock_invite.side_effect = PlexInvitationError("User already exists")

                response = client.post(
                    "/join",
                    data={"code": plex_invitation.code, "token": "valid_oauth_token"},
                )

                # Should return error page with specific error message
                assert response.status_code == 200
                assert b"Plex invitation failed" in response.data

    def test_oauth_flow_missing_token(self, client, plex_invitation):
        """Test OAuth flow when token is missing."""
        with client.session_transaction() as sess:
            sess["invite_token"] = plex_invitation.code
            sess["invitation_in_progress"] = True

        response = client.post(
            "/join",
            data={
                "code": plex_invitation.code
                # Missing token
            },
        )

        # Should redirect to post-wizard (no token means no Plex processing)
        assert response.status_code in [200, 302]

    def test_oauth_flow_invalid_invitation(self, client):
        """Test OAuth flow with invalid invitation code."""
        response = client.post(
            "/join", data={"code": "INVALID", "token": "valid_oauth_token"}
        )

        # Should return error page
        assert response.status_code == 200
        assert b"code_error" in response.data or b"Invalid" in response.data

    def test_oauth_flow_database_error(
        self, client, plex_invitation, mock_plex_account
    ):
        """Test OAuth flow when database operations fail."""
        with client.session_transaction() as sess:
            sess["invite_token"] = plex_invitation.code
            sess["invitation_in_progress"] = True

        # Mock database commit to fail
        with patch("app.extensions.db.session.commit") as mock_commit:
            mock_commit.side_effect = Exception("Database error")

            response = client.post(
                "/join",
                data={"code": plex_invitation.code, "token": "valid_oauth_token"},
            )

            # Should handle database error gracefully
            assert response.status_code == 200

    def test_oauth_flow_concurrent_requests(
        self, client, plex_invitation, mock_plex_account
    ):
        """Test OAuth flow with concurrent requests (race condition test)."""
        with client.session_transaction() as sess:
            sess["invite_token"] = plex_invitation.code
            sess["invitation_in_progress"] = True

        # Simplified concurrent test - just make multiple sequential requests
        # to test that the system handles multiple requests gracefully
        with patch("app.services.media.plex.PlexClient") as mock_client_class:
            mock_client = Mock()
            mock_client._create_user_with_identity_linking.return_value = Mock(id=1)
            mock_client_class.return_value = mock_client

            with (
                patch("app.services.media.plex._invite_user"),
                patch("app.services.invites.mark_server_used"),
                patch("app.services.media.plex.notify"),
                patch("app.services.media.plex.threading.Thread"),
            ):
                            # Make multiple requests sequentially
                            results = []
                            for i in range(3):
                                response = client.post(
                                    "/join",
                                    data={
                                        "code": plex_invitation.code,
                                        "token": f"valid_oauth_token_{i}",
                                    },
                                )
                                results.append(response.status_code)

        # All requests should complete successfully
        assert len(results) == 3
        assert all(status in [200, 302] for status in results)

    def test_handle_oauth_token_function_directly(
        self, app, plex_invitation, mock_plex_account
    ):
        """Test the handle_oauth_token function directly."""
        with patch("app.services.media.plex.PlexClient") as mock_client_class:
            mock_client = Mock()
            mock_user = Mock()
            mock_user.id = 1
            mock_client._create_user_with_identity_linking.return_value = mock_user
            mock_client_class.return_value = mock_client

            with (
                patch("app.services.media.plex._invite_user") as mock_invite,
                patch("app.services.invites.mark_server_used") as mock_mark_used,
                patch("app.services.media.plex.notify") as mock_notify,
                patch("app.services.media.plex.threading.Thread") as mock_thread,
            ):
                            # Call handle_oauth_token directly
                            handle_oauth_token(app, "valid_token", plex_invitation.code)

                            # Verify all expected calls were made
                            mock_client._create_user_with_identity_linking.assert_called_once()
                            mock_invite.assert_called_once()
                            mock_mark_used.assert_called_once()
                            mock_notify.assert_called_once()
                            mock_thread.assert_called_once()

    def test_session_state_persistence(self, client, plex_invitation):
        """Test that session state is properly maintained throughout the OAuth flow."""
        # Set initial session state
        with client.session_transaction() as sess:
            sess["invite_token"] = plex_invitation.code
            sess["invitation_in_progress"] = True
            sess["test_data"] = "should_persist"

        # Make request
        client.post(
            "/join", data={"code": plex_invitation.code, "token": "valid_oauth_token"}
        )

        # Check that session state is maintained
        with client.session_transaction() as sess:
            assert sess.get("invite_token") == plex_invitation.code
            assert sess.get("test_data") == "should_persist"


class TestPlexOAuthErrorHandling:
    """Test error handling and edge cases in Plex OAuth flow."""

    @pytest.fixture
    def plex_server(self):
        """Create a test Plex server."""
        server = MediaServer(
            name="Test Plex Server",
            server_type="plex",
            url="http://localhost:32400",
            api_key="test_admin_token",
        )
        db.session.add(server)
        db.session.commit()
        return server

    @pytest.fixture
    def plex_invitation(self, plex_server):
        """Create a test invitation for Plex server."""
        invitation = Invitation(code="PLEX456", used=False, unlimited=False)
        db.session.add(invitation)
        db.session.commit()

        invitation.servers.append(plex_server)
        db.session.commit()
        return invitation

    def test_oauth_flow_network_error(self, client, plex_invitation):
        """Test OAuth flow when network requests fail."""
        with client.session_transaction() as sess:
            sess["invite_token"] = plex_invitation.code
            sess["invitation_in_progress"] = True

        # Mock MyPlexAccount to raise a network exception
        with patch("app.services.media.plex.MyPlexAccount") as mock_account:
            from requests.exceptions import RequestException

            mock_account.side_effect = RequestException("Network error")

            response = client.post(
                "/join",
                data={"code": plex_invitation.code, "token": "valid_oauth_token"},
            )

            # Should handle network error gracefully
            assert response.status_code == 200
            assert b"Plex invitation failed" in response.data

    def test_oauth_flow_server_not_found(self, client):
        """Test OAuth flow when no media server is found."""
        # Create invitation without any servers
        invitation = Invitation(code="NOSERVER", used=False, unlimited=False)
        db.session.add(invitation)
        db.session.commit()

        with client.session_transaction() as sess:
            sess["invite_token"] = invitation.code
            sess["invitation_in_progress"] = True

        # Mock MediaServer.query.first() to return None
        with patch("app.models.MediaServer.query") as mock_query:
            mock_query.first.return_value = None

            response = client.post(
                "/join", data={"code": invitation.code, "token": "valid_oauth_token"}
            )

            # Should handle missing server gracefully
            assert response.status_code == 200

    def test_oauth_flow_partial_failure_recovery(self, client, plex_invitation):
        """Test OAuth flow recovery from partial failures."""
        with client.session_transaction() as sess:
            sess["invite_token"] = plex_invitation.code
            sess["invitation_in_progress"] = True

        with patch("app.services.media.plex.MyPlexAccount") as mock_account:
            account = Mock()
            account.email = "test@example.com"
            account.username = "testuser"
            mock_account.return_value = account

            # Mock PlexClient to succeed
            with patch("app.services.media.plex.PlexClient") as mock_client_class:
                mock_client = Mock()
                mock_user = Mock()
                mock_user.id = 1
                mock_client._create_user_with_identity_linking.return_value = mock_user
                mock_client_class.return_value = mock_client

                # Mock _invite_user to fail first, then succeed
                with patch("app.services.media.plex._invite_user") as mock_invite:
                    mock_invite.side_effect = [Exception("Temporary failure"), None]

                    # First request should succeed despite partial failure
                    response1 = client.post(
                        "/join",
                        data={
                            "code": plex_invitation.code,
                            "token": "valid_oauth_token",
                        },
                    )
                    assert response1.status_code in [200, 302]

                    # Reset the mock for second attempt
                    mock_invite.side_effect = None
                    mock_invite.return_value = None

                    with (
                        patch("app.services.invites.mark_server_used"),
                        patch("app.services.media.plex.notify"),
                        patch("app.services.media.plex.threading.Thread"),
                    ):
                                # Second request should succeed
                                response2 = client.post(
                                    "/join",
                                    data={
                                        "code": plex_invitation.code,
                                        "token": "valid_oauth_token",
                                    },
                                )
                                assert response2.status_code in [200, 302]

    def test_oauth_flow_background_thread_failure(self, client, plex_invitation):
        """Test OAuth flow when background thread setup fails."""
        with client.session_transaction() as sess:
            sess["invite_token"] = plex_invitation.code
            sess["invitation_in_progress"] = True

        with patch("app.services.media.plex.MyPlexAccount") as mock_account:
            account = Mock()
            account.email = "test@example.com"
            account.username = "testuser"
            mock_account.return_value = account

            with patch("app.services.media.plex.PlexClient") as mock_client_class:
                mock_client = Mock()
                mock_user = Mock()
                mock_user.id = 1
                mock_client._create_user_with_identity_linking.return_value = mock_user
                mock_client_class.return_value = mock_client

                with (
                    patch("app.services.media.plex._invite_user"),
                    patch("app.services.invites.mark_server_used"),
                    patch("app.services.media.plex.notify"),
                    patch("app.services.media.plex.threading.Thread") as mock_thread,
                ):
                                mock_thread_instance = Mock()
                                mock_thread_instance.start.side_effect = Exception(
                                    "Thread failed"
                                )
                                mock_thread.return_value = mock_thread_instance

                                # Should still complete main flow even if background thread fails
                                response = client.post(
                                    "/join",
                                    data={
                                        "code": plex_invitation.code,
                                        "token": "valid_oauth_token",
                                    },
                                )

                                # Main flow should succeed despite background thread failure
                                assert response.status_code in [200, 302]

    def test_oauth_flow_duplicate_user_handling(self, client, plex_invitation):
        """Test OAuth flow when user already exists."""
        # Create existing user
        existing_user = User(
            email="test@example.com",
            username="testuser",
            token="existing_token",
            code=plex_invitation.code,
            server_id=plex_invitation.servers[0].id,
        )
        db.session.add(existing_user)
        db.session.commit()

        with client.session_transaction() as sess:
            sess["invite_token"] = plex_invitation.code
            sess["invitation_in_progress"] = True

        with patch("app.services.media.plex.MyPlexAccount") as mock_account:
            account = Mock()
            account.email = "test@example.com"
            account.username = "testuser"
            mock_account.return_value = account

            with patch("app.services.media.plex.PlexClient") as mock_client_class:
                mock_client = Mock()
                mock_client._create_user_with_identity_linking.return_value = (
                    existing_user
                )
                mock_client_class.return_value = mock_client

                with (
                    patch("app.services.media.plex._invite_user"),
                    patch("app.services.invites.mark_server_used"),
                    patch("app.services.media.plex.notify"),
                    patch("app.services.media.plex.threading.Thread"),
                ):
                                response = client.post(
                                    "/join",
                                    data={
                                        "code": plex_invitation.code,
                                        "token": "valid_oauth_token",
                                    },
                                )

                                # Should handle duplicate user gracefully
                                assert response.status_code in [200, 302]

    def test_oauth_flow_session_expiry(self, client, plex_invitation):
        """Test OAuth flow when session expires during processing."""
        # Don't set session data to simulate expired session
        response = client.post(
            "/join", data={"code": plex_invitation.code, "token": "valid_oauth_token"}
        )

        # Should handle missing session gracefully
        assert response.status_code == 200
