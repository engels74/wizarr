"""
Tests for WizardStep model with timing field functionality.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import WizardStep


class TestWizardStepTiming:
    """Test WizardStep model with timing field."""

    def test_wizard_step_with_timing_field(self, session):
        """Test creating WizardStep with timing field."""
        step = WizardStep(
            server_type="plex",
            timing="before_invite_acceptance",
            position=0,
            title="Pre-invite Welcome",
            markdown="# Welcome\nPlease read our rules before joining.",
        )
        session.add(step)
        session.commit()

        fetched = WizardStep.query.first()
        assert fetched is not None
        assert fetched.timing == "before_invite_acceptance"
        assert fetched.server_type == "plex"
        assert fetched.position == 0

    def test_wizard_step_timing_default_value(self, session):
        """Test that timing defaults to 'after_invite_acceptance'."""
        step = WizardStep(
            server_type="jellyfin",
            position=0,
            title="Default Timing",
            markdown="# Default timing test",
        )
        session.add(step)
        session.commit()

        fetched = WizardStep.query.first()
        assert fetched.timing == "after_invite_acceptance"

    def test_wizard_step_timing_choices_validation(self, session):
        """Test that only valid timing values are accepted."""
        # Valid timing values should work
        valid_timings = ["before_invite_acceptance", "after_invite_acceptance"]
        
        for timing in valid_timings:
            step = WizardStep(
                server_type="plex",
                timing=timing,
                position=0,
                title=f"Test {timing}",
                markdown="# Test",
            )
            session.add(step)
            session.commit()
            
            fetched = WizardStep.query.filter_by(timing=timing).first()
            assert fetched is not None
            assert fetched.timing == timing
            
            # Clean up for next iteration
            session.delete(fetched)
            session.commit()

    def test_wizard_step_unique_constraint_with_timing(self, session):
        """Test unique constraint includes timing field."""
        # Create first step
        step1 = WizardStep(
            server_type="plex",
            timing="before_invite_acceptance",
            position=0,
            title="Pre-invite Step",
            markdown="# Pre-invite",
        )
        session.add(step1)
        session.commit()

        # Same server_type and position but different timing should work
        step2 = WizardStep(
            server_type="plex",
            timing="after_invite_acceptance",
            position=0,
            title="Post-invite Step",
            markdown="# Post-invite",
        )
        session.add(step2)
        session.commit()

        # Same server_type, timing, and position should fail
        step3 = WizardStep(
            server_type="plex",
            timing="before_invite_acceptance",
            position=0,
            title="Duplicate Step",
            markdown="# Duplicate",
        )
        session.add(step3)
        
        with pytest.raises(IntegrityError):
            session.commit()

    def test_wizard_step_to_dict_includes_timing(self, session):
        """Test that to_dict() includes timing field."""
        step = WizardStep(
            server_type="emby",
            timing="before_invite_acceptance",
            position=1,
            title="Pre-invite Rules",
            markdown="# Rules\nPlease follow these rules.",
            requires=["server_url"],
            require_interaction=True,
        )
        session.add(step)
        session.commit()

        step_dict = step.to_dict()
        assert "timing" in step_dict
        assert step_dict["timing"] == "before_invite_acceptance"
        assert step_dict["server_type"] == "emby"
        assert step_dict["position"] == 1
        assert step_dict["title"] == "Pre-invite Rules"
        assert step_dict["requires"] == ["server_url"]
        assert step_dict["require_interaction"] is True

    def test_wizard_step_query_by_timing(self, session):
        """Test querying wizard steps by timing."""
        # Create pre-invite steps
        pre_step1 = WizardStep(
            server_type="plex",
            timing="before_invite_acceptance",
            position=0,
            title="Pre-step 1",
            markdown="# Pre 1",
        )
        pre_step2 = WizardStep(
            server_type="plex",
            timing="before_invite_acceptance",
            position=1,
            title="Pre-step 2",
            markdown="# Pre 2",
        )
        
        # Create post-invite steps
        post_step1 = WizardStep(
            server_type="plex",
            timing="after_invite_acceptance",
            position=0,
            title="Post-step 1",
            markdown="# Post 1",
        )
        
        session.add_all([pre_step1, pre_step2, post_step1])
        session.commit()

        # Query pre-invite steps
        pre_steps = (
            WizardStep.query
            .filter_by(server_type="plex", timing="before_invite_acceptance")
            .order_by(WizardStep.position)
            .all()
        )
        assert len(pre_steps) == 2
        assert pre_steps[0].title == "Pre-step 1"
        assert pre_steps[1].title == "Pre-step 2"

        # Query post-invite steps
        post_steps = (
            WizardStep.query
            .filter_by(server_type="plex", timing="after_invite_acceptance")
            .order_by(WizardStep.position)
            .all()
        )
        assert len(post_steps) == 1
        assert post_steps[0].title == "Post-step 1"

    def test_wizard_step_mixed_server_types_and_timings(self, session):
        """Test wizard steps with different server types and timings."""
        steps = [
            WizardStep(
                server_type="plex",
                timing="before_invite_acceptance",
                position=0,
                title="Plex Pre",
                markdown="# Plex Pre",
            ),
            WizardStep(
                server_type="plex",
                timing="after_invite_acceptance",
                position=0,
                title="Plex Post",
                markdown="# Plex Post",
            ),
            WizardStep(
                server_type="jellyfin",
                timing="before_invite_acceptance",
                position=0,
                title="Jellyfin Pre",
                markdown="# Jellyfin Pre",
            ),
            WizardStep(
                server_type="jellyfin",
                timing="after_invite_acceptance",
                position=0,
                title="Jellyfin Post",
                markdown="# Jellyfin Post",
            ),
        ]
        
        session.add_all(steps)
        session.commit()

        # Test filtering by server type and timing
        plex_pre = WizardStep.query.filter_by(
            server_type="plex", timing="before_invite_acceptance"
        ).first()
        assert plex_pre.title == "Plex Pre"

        jellyfin_post = WizardStep.query.filter_by(
            server_type="jellyfin", timing="after_invite_acceptance"
        ).first()
        assert jellyfin_post.title == "Jellyfin Post"

        # Test counting steps by timing
        pre_count = WizardStep.query.filter_by(timing="before_invite_acceptance").count()
        post_count = WizardStep.query.filter_by(timing="after_invite_acceptance").count()
        
        assert pre_count == 2
        assert post_count == 2

    def test_wizard_step_backward_compatibility(self, session):
        """Test that existing wizard steps work without timing field."""
        # This test simulates existing data that might not have timing set
        # In practice, the migration will set default values
        step = WizardStep(
            server_type="emby",
            position=0,
            title="Legacy Step",
            markdown="# Legacy",
        )
        # Don't explicitly set timing - should get default
        session.add(step)
        session.commit()

        fetched = WizardStep.query.first()
        assert fetched.timing == "after_invite_acceptance"  # Default value
        
        # Should be able to query normally
        legacy_steps = WizardStep.query.filter_by(
            server_type="emby", timing="after_invite_acceptance"
        ).all()
        assert len(legacy_steps) == 1
        assert legacy_steps[0].title == "Legacy Step"
