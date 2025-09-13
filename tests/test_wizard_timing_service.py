"""
Tests for wizard_timing service functionality.
"""

import pytest

from app.models import Invitation, MediaServer, WizardStep
from app.services.wizard_timing import (
    get_post_invite_steps_for_invitation,
    get_pre_invite_steps_for_invitation,
    get_steps_by_timing,
    has_pre_invite_steps_for_invitation,
)


class TestWizardTimingService:
    """Test wizard timing service functions."""

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
            code="TEST123",
            used=False,
            unlimited=False,
        )
        session.add(invitation)
        session.commit()
        
        # Link invitation to server
        invitation.servers.append(media_server)
        session.commit()
        return invitation

    @pytest.fixture
    def wizard_steps(self, session):
        """Create test wizard steps with different timings."""
        steps = [
            WizardStep(
                server_type="plex",
                timing="before_invite_acceptance",
                position=0,
                title="Pre-invite Welcome",
                markdown="# Welcome\nPlease read our rules.",
            ),
            WizardStep(
                server_type="plex",
                timing="before_invite_acceptance",
                position=1,
                title="Pre-invite Rules",
                markdown="# Rules\nFollow these rules.",
            ),
            WizardStep(
                server_type="plex",
                timing="after_invite_acceptance",
                position=0,
                title="Post-invite Setup",
                markdown="# Setup\nConfigure your account.",
            ),
            WizardStep(
                server_type="plex",
                timing="after_invite_acceptance",
                position=1,
                title="Post-invite Guide",
                markdown="# Guide\nHow to use the server.",
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
        return steps

    def test_has_pre_invite_steps_for_invitation_true(
        self, session, invitation_with_server, wizard_steps
    ):
        """Test has_pre_invite_steps_for_invitation returns True when pre-invite steps exist."""
        result = has_pre_invite_steps_for_invitation(invitation_with_server)
        assert result is True

    def test_has_pre_invite_steps_for_invitation_false(self, session, media_server):
        """Test has_pre_invite_steps_for_invitation returns False when no pre-invite steps exist."""
        # Create invitation with server that has no pre-invite steps
        server = MediaServer(
            name="Test Emby Server",
            server_type="emby",
            url="http://emby.example.com",
            api_key="emby_key",
        )
        session.add(server)
        
        invitation = Invitation(code="EMBY123", used=False, unlimited=False)
        session.add(invitation)
        session.commit()
        
        invitation.servers.append(server)
        session.commit()

        result = has_pre_invite_steps_for_invitation(invitation)
        assert result is False

    def test_has_pre_invite_steps_for_invitation_no_servers(self, session):
        """Test has_pre_invite_steps_for_invitation with invitation that has no servers."""
        invitation = Invitation(code="NOSERVER", used=False, unlimited=False)
        session.add(invitation)
        session.commit()

        result = has_pre_invite_steps_for_invitation(invitation)
        assert result is False

    def test_get_pre_invite_steps_for_invitation(
        self, session, invitation_with_server, wizard_steps
    ):
        """Test get_pre_invite_steps_for_invitation returns correct steps."""
        steps = get_pre_invite_steps_for_invitation(invitation_with_server)
        
        assert len(steps) == 2
        assert steps[0].title == "Pre-invite Welcome"
        assert steps[0].position == 0
        assert steps[1].title == "Pre-invite Rules"
        assert steps[1].position == 1
        
        # All steps should be pre-invite timing
        for step in steps:
            assert step.timing == "before_invite_acceptance"
            assert step.server_type == "plex"

    def test_get_post_invite_steps_for_invitation(
        self, session, invitation_with_server, wizard_steps
    ):
        """Test get_post_invite_steps_for_invitation returns correct steps."""
        steps = get_post_invite_steps_for_invitation(invitation_with_server)
        
        assert len(steps) == 2
        assert steps[0].title == "Post-invite Setup"
        assert steps[0].position == 0
        assert steps[1].title == "Post-invite Guide"
        assert steps[1].position == 1
        
        # All steps should be post-invite timing
        for step in steps:
            assert step.timing == "after_invite_acceptance"
            assert step.server_type == "plex"

    def test_get_steps_by_timing_before_invite(self, session, wizard_steps):
        """Test get_steps_by_timing for before_invite_acceptance."""
        steps = get_steps_by_timing("plex", "before_invite_acceptance")
        
        assert len(steps) == 2
        assert steps[0].title == "Pre-invite Welcome"
        assert steps[1].title == "Pre-invite Rules"
        
        for step in steps:
            assert step.timing == "before_invite_acceptance"
            assert step.server_type == "plex"

    def test_get_steps_by_timing_after_invite(self, session, wizard_steps):
        """Test get_steps_by_timing for after_invite_acceptance."""
        steps = get_steps_by_timing("plex", "after_invite_acceptance")
        
        assert len(steps) == 2
        assert steps[0].title == "Post-invite Setup"
        assert steps[1].title == "Post-invite Guide"
        
        for step in steps:
            assert step.timing == "after_invite_acceptance"
            assert step.server_type == "plex"

    def test_get_steps_by_timing_no_steps(self, session, wizard_steps):
        """Test get_steps_by_timing when no steps exist for server type."""
        steps = get_steps_by_timing("emby", "before_invite_acceptance")
        assert len(steps) == 0

    def test_get_steps_by_timing_different_server_types(self, session, wizard_steps):
        """Test get_steps_by_timing with different server types."""
        plex_steps = get_steps_by_timing("plex", "before_invite_acceptance")
        jellyfin_steps = get_steps_by_timing("jellyfin", "before_invite_acceptance")
        
        assert len(plex_steps) == 2
        assert len(jellyfin_steps) == 1
        
        assert plex_steps[0].server_type == "plex"
        assert jellyfin_steps[0].server_type == "jellyfin"
        assert jellyfin_steps[0].title == "Jellyfin Pre-step"

    def test_invitation_with_multiple_servers(self, session, wizard_steps):
        """Test invitation with multiple servers - should return steps for all server types."""
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
        
        # Link to both servers
        plex_server = MediaServer.query.filter_by(server_type="plex").first()
        invitation.servers.extend([plex_server, jellyfin_server])
        session.commit()

        # Should have pre-invite steps from both server types
        pre_steps = get_pre_invite_steps_for_invitation(invitation)
        server_types = {step.server_type for step in pre_steps}
        
        assert len(pre_steps) == 3  # 2 plex + 1 jellyfin
        assert server_types == {"plex", "jellyfin"}

    def test_invitation_with_no_matching_steps(self, session):
        """Test invitation with server type that has no wizard steps."""
        # Create server with type that has no wizard steps
        server = MediaServer(
            name="Test Komga Server",
            server_type="komga",
            url="http://komga.example.com",
            api_key="komga_key",
        )
        session.add(server)
        
        invitation = Invitation(code="KOMGA123", used=False, unlimited=False)
        session.add(invitation)
        session.commit()
        
        invitation.servers.append(server)
        session.commit()

        # Should return empty lists
        pre_steps = get_pre_invite_steps_for_invitation(invitation)
        post_steps = get_post_invite_steps_for_invitation(invitation)
        has_pre = has_pre_invite_steps_for_invitation(invitation)
        
        assert len(pre_steps) == 0
        assert len(post_steps) == 0
        assert has_pre is False

    def test_steps_ordered_by_position(self, session, invitation_with_server):
        """Test that steps are returned in correct position order."""
        # Create steps with non-sequential positions
        steps = [
            WizardStep(
                server_type="plex",
                timing="before_invite_acceptance",
                position=5,
                title="Step 5",
                markdown="# Step 5",
            ),
            WizardStep(
                server_type="plex",
                timing="before_invite_acceptance",
                position=1,
                title="Step 1",
                markdown="# Step 1",
            ),
            WizardStep(
                server_type="plex",
                timing="before_invite_acceptance",
                position=3,
                title="Step 3",
                markdown="# Step 3",
            ),
        ]
        session.add_all(steps)
        session.commit()

        pre_steps = get_pre_invite_steps_for_invitation(invitation_with_server)
        
        # Should be ordered by position
        positions = [step.position for step in pre_steps]
        assert positions == sorted(positions)
        
        # Check titles match expected order
        titles = [step.title for step in pre_steps]
        assert titles[0] == "Step 1"
        assert titles[1] == "Step 3"
        assert titles[2] == "Step 5"
