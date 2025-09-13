"""Test wizard phase model functionality."""

import pytest
from sqlalchemy.exc import IntegrityError

from app import create_app
from app.extensions import db
from app.models import WizardPhase, WizardStep


@pytest.fixture
def app():
    """Create application for testing."""
    app = create_app()
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


class TestWizardPhaseModel:
    """Test WizardPhase enum and WizardStep model with phases."""

    def test_wizard_phase_enum_values(self, app):
        """Test that WizardPhase enum has correct values."""
        assert WizardPhase.PRE.value == "pre"
        assert WizardPhase.POST.value == "post"

    def test_wizard_step_default_phase(self, app):
        """Test that WizardStep defaults to POST phase."""
        with app.app_context():
            step = WizardStep(
                server_type="plex", position=0, title="Test Step", markdown="# Test"
            )
            db.session.add(step)
            db.session.commit()

            assert step.phase == WizardPhase.POST

    def test_wizard_step_explicit_phase(self, app):
        """Test setting explicit phase on WizardStep."""
        with app.app_context():
            pre_step = WizardStep(
                server_type="plex",
                phase=WizardPhase.PRE,
                position=0,
                title="Pre Step",
                markdown="# Pre",
            )

            post_step = WizardStep(
                server_type="plex",
                phase=WizardPhase.POST,
                position=0,
                title="Post Step",
                markdown="# Post",
            )

            db.session.add_all([pre_step, post_step])
            db.session.commit()

            assert pre_step.phase == WizardPhase.PRE
            assert post_step.phase == WizardPhase.POST

    def test_wizard_step_unique_constraint_with_phase(self, app):
        """Test that unique constraint includes phase."""
        with app.app_context():
            # Should be able to create steps with same server_type and position
            # but different phases
            pre_step = WizardStep(
                server_type="plex",
                phase=WizardPhase.PRE,
                position=0,
                title="Pre Step",
                markdown="# Pre",
            )

            post_step = WizardStep(
                server_type="plex",
                phase=WizardPhase.POST,
                position=0,
                title="Post Step",
                markdown="# Post",
            )

            db.session.add_all([pre_step, post_step])
            db.session.commit()

            # Both should be successfully created
            assert pre_step.id is not None
            assert post_step.id is not None

    def test_wizard_step_unique_constraint_violation(self, app):
        """Test that duplicate (server_type, phase, position) is not allowed."""
        with app.app_context():
            step1 = WizardStep(
                server_type="plex",
                phase=WizardPhase.PRE,
                position=0,
                title="Step 1",
                markdown="# Step 1",
            )

            step2 = WizardStep(
                server_type="plex",
                phase=WizardPhase.PRE,
                position=0,
                title="Step 2",
                markdown="# Step 2",
            )

            db.session.add(step1)
            db.session.commit()

            # This should fail due to unique constraint
            db.session.add(step2)
            with pytest.raises((IntegrityError, Exception)):  # SQLAlchemy will raise an IntegrityError
                db.session.commit()

    def test_wizard_step_to_dict_includes_phase(self, app):
        """Test that to_dict() includes phase information."""
        with app.app_context():
            pre_step = WizardStep(
                server_type="plex",
                phase=WizardPhase.PRE,
                position=0,
                title="Pre Step",
                markdown="# Pre",
            )
            db.session.add(pre_step)
            db.session.commit()

            step_dict = pre_step.to_dict()
            assert step_dict["phase"] == "pre"
            assert step_dict["server_type"] == "plex"
            assert step_dict["position"] == 0

    def test_filter_steps_by_phase(self, app):
        """Test filtering steps by phase."""
        with app.app_context():
            # Create steps for both phases
            pre_steps = [
                WizardStep(
                    server_type="plex",
                    phase=WizardPhase.PRE,
                    position=i,
                    title=f"Pre Step {i}",
                    markdown=f"# Pre Step {i}",
                )
                for i in range(3)
            ]

            post_steps = [
                WizardStep(
                    server_type="plex",
                    phase=WizardPhase.POST,
                    position=i,
                    title=f"Post Step {i}",
                    markdown=f"# Post Step {i}",
                )
                for i in range(2)
            ]

            db.session.add_all(pre_steps + post_steps)
            db.session.commit()

            # Test filtering
            pre_results = (
                WizardStep.query.filter_by(server_type="plex", phase=WizardPhase.PRE)
                .order_by(WizardStep.position)
                .all()
            )

            post_results = (
                WizardStep.query.filter_by(server_type="plex", phase=WizardPhase.POST)
                .order_by(WizardStep.position)
                .all()
            )

            assert len(pre_results) == 3
            assert len(post_results) == 2

            # Verify order
            for i, step in enumerate(pre_results):
                assert step.position == i
                assert step.phase == WizardPhase.PRE

            for i, step in enumerate(post_results):
                assert step.position == i
                assert step.phase == WizardPhase.POST
