"""
Tests for backward compatibility of wizard timing functionality.
"""

import pytest
from flask import session

from app.models import Invitation, MediaServer, WizardStep
from app.services.invitation_flow import InvitationFlowManager


class TestWizardTimingBackwardCompatibility:
    """Test backward compatibility for existing wizard functionality."""

    @pytest.fixture
    def media_server(self, session):
        """Create a test media server."""
        server = MediaServer(
            name="Legacy Plex Server",
            server_type="plex",
            url="http://legacy.example.com",
            api_key="legacy_key",
        )
        session.add(server)
        session.commit()
        return server

    @pytest.fixture
    def legacy_invitation(self, session, media_server):
        """Create a legacy invitation (pre-timing implementation)."""
        invitation = Invitation(
            code="LEGACY123",
            used=False,
            unlimited=False,
        )
        session.add(invitation)
        session.commit()
        
        invitation.servers.append(media_server)
        session.commit()
        return invitation

    @pytest.fixture
    def legacy_wizard_steps(self, session):
        """Create legacy wizard steps (without explicit timing)."""
        # These steps simulate existing data that would have been created
        # before the timing field was added
        steps = [
            WizardStep(
                server_type="plex",
                position=0,
                title="Legacy Welcome",
                markdown="# Welcome\nThis is a legacy step.",
            ),
            WizardStep(
                server_type="plex",
                position=1,
                title="Legacy Setup",
                markdown="# Setup\nLegacy setup instructions.",
            ),
        ]
        session.add_all(steps)
        session.commit()
        
        # Verify they got the default timing value
        for step in steps:
            assert step.timing == "after_invite_acceptance"
        
        return steps

    def test_legacy_wizard_steps_default_timing(self, session, legacy_wizard_steps):
        """Test that legacy wizard steps get default timing value."""
        for step in legacy_wizard_steps:
            assert step.timing == "after_invite_acceptance"
            assert step.server_type == "plex"

    def test_legacy_invitation_flow_unchanged(
        self, app, session, legacy_invitation, legacy_wizard_steps
    ):
        """Test that legacy invitation flow continues to work unchanged."""
        with app.test_request_context():
            manager = InvitationFlowManager()
            result = manager.process_invitation_display("LEGACY123")
            
            # Should show normal authentication form (no pre-invite steps)
            from app.services.invitation_flow.results import ProcessingStatus
            assert result.status == ProcessingStatus.AUTHENTICATION_REQUIRED
            assert result.template_data is not None
            assert result.redirect_url is None  # No redirect to pre-wizard

    def test_legacy_wizard_route_still_works(
        self, app, session, legacy_invitation, legacy_wizard_steps
    ):
        """Test that existing /wizard/ route continues to work."""
        with app.test_client() as client:
            # Set up session as legacy invitation would
            with client.session_transaction() as sess:
                sess["wizard_access"] = "LEGACY123"
            
            response = client.get("/wizard/")
            
            assert response.status_code == 200
            # Should show first legacy step
            assert b"Legacy Welcome" in response.data

    def test_legacy_wizard_step_navigation(
        self, app, session, legacy_invitation, legacy_wizard_steps
    ):
        """Test that legacy wizard step navigation continues to work."""
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["wizard_access"] = "LEGACY123"
            
            # Access specific step using legacy route
            response = client.get("/wizard/plex/1")
            
            assert response.status_code == 200
            assert b"Legacy Setup" in response.data

    def test_legacy_steps_appear_in_post_wizard(
        self, app, session, legacy_invitation, legacy_wizard_steps
    ):
        """Test that legacy steps appear in post-wizard flow."""
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["wizard_access"] = "LEGACY123"
            
            # Access post-wizard route
            response = client.get("/wizard/post-wizard")
            
            assert response.status_code == 200
            # Should show legacy steps since they default to after_invite_acceptance
            assert b"Legacy Welcome" in response.data

    def test_mixed_legacy_and_new_steps(self, session, legacy_wizard_steps):
        """Test mixing legacy steps with new timing-aware steps."""
        # Add new timing-aware steps
        new_steps = [
            WizardStep(
                server_type="plex",
                timing="before_invite_acceptance",
                position=0,
                title="New Pre-step",
                markdown="# New Pre-step",
            ),
            WizardStep(
                server_type="plex",
                timing="after_invite_acceptance",
                position=2,  # After legacy steps
                title="New Post-step",
                markdown="# New Post-step",
            ),
        ]
        session.add_all(new_steps)
        session.commit()
        
        # Query all plex steps
        all_steps = WizardStep.query.filter_by(server_type="plex").order_by(
            WizardStep.timing, WizardStep.position
        ).all()
        
        # Should have 1 pre-invite step and 3 post-invite steps
        pre_steps = [s for s in all_steps if s.timing == "before_invite_acceptance"]
        post_steps = [s for s in all_steps if s.timing == "after_invite_acceptance"]
        
        assert len(pre_steps) == 1
        assert len(post_steps) == 3  # 2 legacy + 1 new
        
        assert pre_steps[0].title == "New Pre-step"
        post_titles = [s.title for s in post_steps]
        assert "Legacy Welcome" in post_titles
        assert "Legacy Setup" in post_titles
        assert "New Post-step" in post_titles

    def test_legacy_invitation_with_new_pre_steps(
        self, app, session, legacy_invitation, legacy_wizard_steps
    ):
        """Test legacy invitation when new pre-invite steps are added."""
        # Add a pre-invite step
        pre_step = WizardStep(
            server_type="plex",
            timing="before_invite_acceptance",
            position=0,
            title="New Pre-step",
            markdown="# New Pre-step",
        )
        session.add(pre_step)
        session.commit()
        
        with app.test_request_context():
            manager = InvitationFlowManager()
            result = manager.process_invitation_display("LEGACY123")
            
            # Should now redirect to pre-wizard because pre-invite step exists
            assert result.redirect_url is not None
            assert "/wizard/pre-wizard/LEGACY123" in result.redirect_url

    def test_legacy_session_data_compatibility(
        self, app, session, legacy_invitation, legacy_wizard_steps
    ):
        """Test that legacy session data continues to work."""
        with app.test_client() as client:
            # Set up session with legacy data structure
            with client.session_transaction() as sess:
                sess["wizard_access"] = "LEGACY123"
                # Legacy sessions might not have timing-related keys
                # Should still work
            
            response = client.get("/wizard/")
            assert response.status_code == 200
            
            # Should be able to navigate normally
            response = client.get("/wizard/plex/0")
            assert response.status_code == 200
            assert b"Legacy Welcome" in response.data

    def test_legacy_form_data_handling(self, app, session):
        """Test that forms handle legacy data without timing field."""
        from app.forms.wizard import WizardStepForm
        
        with app.test_request_context():
            # Simulate form data that might come from legacy forms
            legacy_form_data = {
                "server_type": "plex",
                "title": "Legacy Form Step",
                "markdown": "# Legacy Form Content",
                # No timing field - should use default
            }
            
            form = WizardStepForm(data=legacy_form_data)
            
            # Form should not validate because timing is now required
            assert not form.validate()
            assert "timing" in form.errors
            
            # But if we add the default timing, it should work
            legacy_form_data["timing"] = "after_invite_acceptance"
            form = WizardStepForm(data=legacy_form_data)
            assert form.validate()

    def test_legacy_database_migration_simulation(self, session):
        """Test that database migration properly handles existing data."""
        # This test simulates what happens during migration
        # Create a step without timing (simulating pre-migration data)
        
        # In real migration, this would be handled by the migration script
        # Here we test that the default value works correctly
        step = WizardStep(
            server_type="jellyfin",
            position=0,
            title="Migration Test Step",
            markdown="# Migration Test",
            # timing will get default value
        )
        session.add(step)
        session.commit()
        
        # Verify default timing was applied
        fetched = WizardStep.query.filter_by(title="Migration Test Step").first()
        assert fetched.timing == "after_invite_acceptance"

    def test_legacy_api_compatibility(self, session, legacy_wizard_steps):
        """Test that existing API endpoints continue to work."""
        # Test to_dict() method includes timing field
        step = legacy_wizard_steps[0]
        step_dict = step.to_dict()
        
        assert "timing" in step_dict
        assert step_dict["timing"] == "after_invite_acceptance"
        
        # All other fields should still be present
        assert "id" in step_dict
        assert "server_type" in step_dict
        assert "position" in step_dict
        assert "title" in step_dict
        assert "markdown" in step_dict

    def test_legacy_wizard_bundle_compatibility(self, session):
        """Test that wizard bundles work with timing field."""
        from app.models import WizardBundle, WizardBundleStep
        
        # Create a bundle with legacy steps
        bundle = WizardBundle(
            name="Legacy Bundle",
            description="Bundle with legacy steps",
        )
        session.add(bundle)
        session.commit()
        
        # Create steps for the bundle
        step = WizardStep(
            server_type="custom",  # Bundle steps use custom server type
            timing="after_invite_acceptance",  # Should work with timing
            position=0,
            title="Bundle Step",
            markdown="# Bundle Content",
        )
        session.add(step)
        session.commit()
        
        # Link step to bundle
        bundle_step = WizardBundleStep(
            bundle_id=bundle.id,
            step_id=step.id,
            position=0,
        )
        session.add(bundle_step)
        session.commit()
        
        # Verify bundle works with timing
        assert len(bundle.steps) == 1
        assert bundle.steps[0].step.timing == "after_invite_acceptance"

    def test_existing_installation_upgrade_path(
        self, app, session, legacy_invitation, legacy_wizard_steps
    ):
        """Test complete upgrade path for existing installation."""
        # Simulate existing installation with legacy data
        with app.test_client() as client:
            # 1. Legacy invitation flow should work
            with client.session_transaction() as sess:
                sess["wizard_access"] = "LEGACY123"
            
            response = client.get("/wizard/")
            assert response.status_code == 200
            
            # 2. Add new pre-invite step
            pre_step = WizardStep(
                server_type="plex",
                timing="before_invite_acceptance",
                position=0,
                title="Upgrade Pre-step",
                markdown="# Upgrade Pre-step",
            )
            session.add(pre_step)
            session.commit()
            
            # 3. New invitations should use new flow
            with app.test_request_context():
                manager = InvitationFlowManager()
                result = manager.process_invitation_display("LEGACY123")
                
                # Should redirect to pre-wizard
                assert "/wizard/pre-wizard/LEGACY123" in result.redirect_url
            
            # 4. Legacy wizard access should still work for post-invite
            response = client.get("/wizard/post-wizard")
            assert response.status_code == 200
            assert b"Legacy Welcome" in response.data
