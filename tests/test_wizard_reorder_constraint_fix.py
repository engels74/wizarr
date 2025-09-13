"""
Test cases to reproduce and verify the fix for SQLite UNIQUE constraint violation
during wizard step drag-and-drop reordering between phases.

These tests follow TDD methodology to ensure the constraint violation is properly
handled when moving steps between pre-invite and post-invite phases.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app import create_app
from app.extensions import db
from app.models import AdminAccount, WizardPhase, WizardStep


@pytest.fixture
def app():
    """Create application for testing."""
    app = create_app()
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["WTF_CSRF_ENABLED"] = False  # Disable CSRF for testing

    with app.app_context():
        db.create_all()

        # Create admin user for authentication
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
    # Login as admin
    client.post("/login", data={"username": "admin", "password": "password"})
    return client


@pytest.fixture
def complex_wizard_setup(app):
    """Create a complex wizard setup with multiple steps in both phases."""
    with app.app_context():
        # Clean up any existing data
        db.session.query(WizardStep).delete()
        db.session.commit()

        steps = [
            # Pre-invite phase steps
            WizardStep(
                server_type="plex",
                phase=WizardPhase.PRE,
                position=0,
                title="Pre Step 1",
                markdown="# Pre Step 1",
            ),
            WizardStep(
                server_type="plex",
                phase=WizardPhase.PRE,
                position=1,
                title="Pre Step 2",
                markdown="# Pre Step 2",
            ),
            WizardStep(
                server_type="plex",
                phase=WizardPhase.PRE,
                position=2,
                title="Pre Step 3",
                markdown="# Pre Step 3",
            ),
            # Post-invite phase steps
            WizardStep(
                server_type="plex",
                phase=WizardPhase.POST,
                position=0,
                title="Post Step 1",
                markdown="# Post Step 1",
            ),
            WizardStep(
                server_type="plex",
                phase=WizardPhase.POST,
                position=1,
                title="Post Step 2",
                markdown="# Post Step 2",
            ),
        ]

        db.session.add_all(steps)
        db.session.commit()

        # Return step IDs for use in tests
        return {
            "pre_steps": [steps[0].id, steps[1].id, steps[2].id],
            "post_steps": [steps[3].id, steps[4].id],
        }


class TestConstraintViolationReproduction:
    """Test cases that reproduce the UNIQUE constraint violation."""

    def test_javascript_drag_drop_race_condition(
        self, authenticated_client, complex_wizard_setup
    ):
        """
        Test the exact race condition that occurs in JavaScript drag-and-drop:
        1. User drags step from pre to post phase
        2. JavaScript calls updateStepPhase()
        3. JavaScript immediately calls reorder with ALL steps in target phase
        4. The reorder call may include steps that were just moved and have conflicting positions
        """
        step_ids = complex_wizard_setup
        pre_step_1_id = step_ids["pre_steps"][0]
        post_step_1_id, post_step_2_id = step_ids["post_steps"]

        # Simulate the exact JavaScript flow from wizard-steps.js
        # Step 1: updateStepPhase is called (this works fine)
        phase_response = authenticated_client.post(
            f"/settings/wizard/{pre_step_1_id}/update-phase",
            json={"phase": "post", "server_type": "plex"},
            headers={"Content-Type": "application/json"},
        )
        assert phase_response.status_code == 200

        # Step 2: JavaScript immediately calls reorder with the new order
        # This includes the step that was just moved, which might cause position conflicts
        # The JavaScript gets ALL children from the target container and sends their IDs
        reorder_response = authenticated_client.post(
            "/settings/wizard/reorder",
            json={
                "ids": [
                    pre_step_1_id,
                    post_step_1_id,
                    post_step_2_id,
                ],  # Moved step first
                "server_type": "plex",
                "phase": "post",
            },
            headers={"Content-Type": "application/json"},
        )

        # This should NOT cause a constraint violation
        assert reorder_response.status_code == 200
        assert reorder_response.json == {"status": "ok"}

        # Verify the final state is correct
        with authenticated_client.application.app_context():
            post_steps = (
                db.session.query(WizardStep)
                .filter_by(server_type="plex", phase=WizardPhase.POST)
                .order_by(WizardStep.position)
                .all()
            )

            assert len(post_steps) == 3
            assert post_steps[0].id == pre_step_1_id  # Moved step is first
            assert post_steps[1].id == post_step_1_id
            assert post_steps[2].id == post_step_2_id

            # Verify positions are sequential
            for i, step in enumerate(post_steps):
                assert step.position == i

    def test_constraint_violation_with_manual_position_conflict(
        self, authenticated_client, complex_wizard_setup
    ):
        """
        Test that demonstrates the constraint violation by manually creating conflicting positions.
        This helps us understand what the reorder function needs to handle.
        """
        step_ids = complex_wizard_setup
        post_step_1_id, post_step_2_id = step_ids["post_steps"]

        # Manually create a position conflict to see the constraint in action
        with authenticated_client.application.app_context():
            # Try to create a step with the same position as an existing step
            conflicting_step = WizardStep(
                server_type="plex",
                phase=WizardPhase.POST,
                position=0,  # Same position as existing post step
                title="Conflicting Step",
                markdown="# Conflict",
            )

            # This should cause a constraint violation
            db.session.add(conflicting_step)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()

        # Now test that reorder handles this scenario gracefully
        reorder_response = authenticated_client.post(
            "/settings/wizard/reorder",
            json={
                "ids": [post_step_2_id, post_step_1_id],  # Reverse order
                "server_type": "plex",
                "phase": "post",
            },
            headers={"Content-Type": "application/json"},
        )

        assert reorder_response.status_code == 200

    def test_rapid_cross_phase_reorder_constraint_violation(
        self, authenticated_client, complex_wizard_setup
    ):
        """
        Test that reproduces the constraint violation when rapidly reordering
        steps between phases without proper constraint handling.

        This test simulates the exact scenario that causes the SQLite error:
        1. Move a step from pre to post phase
        2. Immediately reorder all post steps including the moved step
        """
        step_ids = complex_wizard_setup
        pre_step_1_id = step_ids["pre_steps"][0]
        post_step_1_id, post_step_2_id = step_ids["post_steps"]

        # Step 1: Move pre step to post phase (this works)
        phase_response = authenticated_client.post(
            f"/settings/wizard/{pre_step_1_id}/update-phase",
            json={"phase": "post", "server_type": "plex"},
            headers={"Content-Type": "application/json"},
        )
        assert phase_response.status_code == 200

        # Step 2: Immediately reorder all post steps including the moved one
        # This should NOT cause a constraint violation
        reorder_response = authenticated_client.post(
            "/settings/wizard/reorder",
            json={
                "ids": [
                    pre_step_1_id,
                    post_step_1_id,
                    post_step_2_id,
                ],  # Moved step first
                "server_type": "plex",
                "phase": "post",
            },
            headers={"Content-Type": "application/json"},
        )

        # This should succeed without constraint violations
        assert reorder_response.status_code == 200
        assert reorder_response.json == {"status": "ok"}

        # Verify final state
        with authenticated_client.application.app_context():
            post_steps = (
                db.session.query(WizardStep)
                .filter_by(server_type="plex", phase=WizardPhase.POST)
                .order_by(WizardStep.position)
                .all()
            )

            assert len(post_steps) == 3
            assert post_steps[0].id == pre_step_1_id  # Moved step is first
            assert post_steps[1].id == post_step_1_id
            assert post_steps[2].id == post_step_2_id

            # Verify positions are sequential without gaps
            for i, step in enumerate(post_steps):
                assert step.position == i

    def test_reorder_function_with_position_gaps(
        self, authenticated_client, complex_wizard_setup
    ):
        """
        Test reordering when there are position gaps that could cause constraint violations.
        This simulates what happens when the reorder function receives steps that have
        non-sequential positions due to rapid phase changes.
        """
        step_ids = complex_wizard_setup
        pre_step_1_id = step_ids["pre_steps"][0]
        post_step_1_id, post_step_2_id = step_ids["post_steps"]

        # First, manually create a gap in positions to simulate the race condition
        with authenticated_client.application.app_context():
            # Move pre step to post phase - this will place it at the end
            phase_response = authenticated_client.post(
                f"/settings/wizard/{pre_step_1_id}/update-phase",
                json={"phase": "post", "server_type": "plex"},
                headers={"Content-Type": "application/json"},
            )
            assert phase_response.status_code == 200

            # Now we have positions: 0, 1, 2 in post phase
            # Let's manually create a scenario where reorder gets called with
            # steps that have conflicting positions

            # Get the current state
            post_steps = (
                db.session.query(WizardStep)
                .filter_by(server_type="plex", phase=WizardPhase.POST)
                .order_by(WizardStep.position)
                .all()
            )

            # Manually set positions to create a conflict scenario
            # This simulates what could happen during rapid drag-and-drop
            post_steps[0].position = 1  # Create conflict
            post_steps[
                1
            ].position = 1  # Same position - should cause constraint violation

            # Try to commit this - should fail
            try:
                db.session.commit()
                raise AssertionError("Expected constraint violation")
            except IntegrityError:
                db.session.rollback()
                # This is expected
                pass

        # Now test that the reorder function handles this gracefully
        # by using the two-phase approach
        reorder_response = authenticated_client.post(
            "/settings/wizard/reorder",
            json={
                "ids": [post_step_2_id, pre_step_1_id, post_step_1_id],  # New order
                "server_type": "plex",
                "phase": "post",
            },
            headers={"Content-Type": "application/json"},
        )

        assert reorder_response.status_code == 200

        # Verify final state
        with authenticated_client.application.app_context():
            post_steps = (
                db.session.query(WizardStep)
                .filter_by(server_type="plex", phase=WizardPhase.POST)
                .order_by(WizardStep.position)
                .all()
            )

            assert len(post_steps) == 3
            assert post_steps[0].id == post_step_2_id
            assert post_steps[1].id == pre_step_1_id
            assert post_steps[2].id == post_step_1_id

            # Verify positions are sequential
            for i, step in enumerate(post_steps):
                assert step.position == i

    def test_multiple_rapid_cross_phase_moves(
        self, authenticated_client, complex_wizard_setup
    ):
        """
        Test multiple rapid cross-phase moves that could cause constraint violations.
        """
        step_ids = complex_wizard_setup
        pre_step_1_id, pre_step_2_id = step_ids["pre_steps"][:2]
        post_step_1_id = step_ids["post_steps"][0]

        # Move multiple pre steps to post phase rapidly
        for step_id in [pre_step_1_id, pre_step_2_id]:
            phase_response = authenticated_client.post(
                f"/settings/wizard/{step_id}/update-phase",
                json={"phase": "post", "server_type": "plex"},
                headers={"Content-Type": "application/json"},
            )
            assert phase_response.status_code == 200

        # Reorder all post steps including the moved ones
        reorder_response = authenticated_client.post(
            "/settings/wizard/reorder",
            json={
                "ids": [pre_step_2_id, post_step_1_id, pre_step_1_id],
                "server_type": "plex",
                "phase": "post",
            },
            headers={"Content-Type": "application/json"},
        )

        assert reorder_response.status_code == 200

        # Verify final positions
        with authenticated_client.application.app_context():
            post_steps = (
                db.session.query(WizardStep)
                .filter_by(server_type="plex", phase=WizardPhase.POST)
                .order_by(WizardStep.position)
                .all()
            )

            assert len(post_steps) == 4  # 2 original + 2 moved
            expected_order = [pre_step_2_id, post_step_1_id, pre_step_1_id]
            for i, expected_id in enumerate(expected_order):
                assert post_steps[i].id == expected_id
                assert post_steps[i].position == i

    def test_reorder_with_mixed_phase_steps_in_ids(
        self, authenticated_client, complex_wizard_setup
    ):
        """
        Test reordering when the IDs list contains steps from different phases.
        This should handle the case gracefully by only reordering steps in the target phase.
        """
        step_ids = complex_wizard_setup
        pre_step_1_id = step_ids["pre_steps"][0]
        post_step_1_id, post_step_2_id = step_ids["post_steps"]

        # Try to reorder with mixed phase step IDs
        # This should only reorder the steps that are actually in the post phase
        reorder_response = authenticated_client.post(
            "/settings/wizard/reorder",
            json={
                "ids": [pre_step_1_id, post_step_2_id, post_step_1_id],  # Mixed phases
                "server_type": "plex",
                "phase": "post",
            },
            headers={"Content-Type": "application/json"},
        )

        assert reorder_response.status_code == 200

        # Verify only post-phase steps were reordered
        with authenticated_client.application.app_context():
            post_steps = (
                db.session.query(WizardStep)
                .filter_by(server_type="plex", phase=WizardPhase.POST)
                .order_by(WizardStep.position)
                .all()
            )

            assert len(post_steps) == 2
            assert post_steps[0].id == post_step_2_id  # Reordered
            assert post_steps[1].id == post_step_1_id  # Reordered

            # Pre step should remain unchanged
            pre_step = db.session.get(WizardStep, pre_step_1_id)
            assert pre_step is not None
            assert pre_step.phase == WizardPhase.PRE
            assert pre_step.position == 0

    def test_reorder_with_duplicate_positions_scenario(
        self, authenticated_client, complex_wizard_setup
    ):
        """
        Test a scenario that could cause the exact constraint violation reported.
        This test tries to reproduce the issue by creating a situation where
        the reorder function might assign duplicate positions.
        """
        step_ids = complex_wizard_setup
        post_step_1_id, post_step_2_id = step_ids["post_steps"]

        # Create a scenario where we have steps with potentially conflicting positions
        with authenticated_client.application.app_context():
            # Add a third step to post phase to make reordering more complex
            extra_step = WizardStep(
                server_type="plex",
                phase=WizardPhase.POST,
                position=2,  # Next available position
                title="Extra Post Step",
                markdown="# Extra",
            )
            db.session.add(extra_step)
            db.session.commit()
            extra_step_id = extra_step.id

        # Now try to reorder all three steps in a way that might cause conflicts
        # This simulates the JavaScript sending a reorder request after drag-and-drop
        reorder_response = authenticated_client.post(
            "/settings/wizard/reorder",
            json={
                "ids": [extra_step_id, post_step_1_id, post_step_2_id],  # New order
                "server_type": "plex",
                "phase": "post",
            },
            headers={"Content-Type": "application/json"},
        )

        # This should succeed without constraint violations
        assert reorder_response.status_code == 200
        assert reorder_response.json == {"status": "ok"}

        # Verify the final order is correct
        with authenticated_client.application.app_context():
            post_steps = (
                db.session.query(WizardStep)
                .filter_by(server_type="plex", phase=WizardPhase.POST)
                .order_by(WizardStep.position)
                .all()
            )

            assert len(post_steps) == 3
            assert post_steps[0].id == extra_step_id
            assert post_steps[1].id == post_step_1_id
            assert post_steps[2].id == post_step_2_id

            # Verify positions are sequential
            for i, step in enumerate(post_steps):
                assert step.position == i

    def test_exact_javascript_race_condition_simulation(
        self, authenticated_client, complex_wizard_setup
    ):
        """
        Test that simulates the exact race condition from the JavaScript code.
        The JS calls updateStepPhase() and then immediately calls reorder without waiting.
        """
        step_ids = complex_wizard_setup
        pre_step_1_id = step_ids["pre_steps"][0]
        post_step_1_id, post_step_2_id = step_ids["post_steps"]

        # Simulate the exact JavaScript behavior: rapid sequential calls
        # This is what happens in wizard-steps.js lines 24-38

        # Call 1: updateStepPhase (this should work)
        phase_response = authenticated_client.post(
            f"/settings/wizard/{pre_step_1_id}/update-phase",
            json={"phase": "post", "server_type": "plex"},
            headers={"Content-Type": "application/json"},
        )
        assert phase_response.status_code == 200

        # Call 2: Immediately call reorder (this is where the race condition could occur)
        # The JavaScript gets the IDs from the DOM, which includes the step that was just moved
        reorder_response = authenticated_client.post(
            "/settings/wizard/reorder",
            json={
                "ids": [pre_step_1_id, post_step_1_id, post_step_2_id],
                "server_type": "plex",
                "phase": "post",
            },
            headers={"Content-Type": "application/json"},
        )

        # This should NOT cause a constraint violation
        assert reorder_response.status_code == 200

        # Verify the final state
        with authenticated_client.application.app_context():
            post_steps = (
                db.session.query(WizardStep)
                .filter_by(server_type="plex", phase=WizardPhase.POST)
                .order_by(WizardStep.position)
                .all()
            )

            assert len(post_steps) == 3
            # The moved step should be first in the new order
            assert post_steps[0].id == pre_step_1_id
            assert post_steps[1].id == post_step_1_id
            assert post_steps[2].id == post_step_2_id


class TestConstraintSafeReordering:
    """Test cases that verify constraint-safe reordering algorithms."""

    def test_transaction_safe_position_updates(
        self, authenticated_client, complex_wizard_setup
    ):
        """
        Test that position updates are transaction-safe and don't cause constraint violations
        even when intermediate states would violate constraints.
        """
        step_ids = complex_wizard_setup
        post_step_1_id, post_step_2_id = step_ids["post_steps"]

        # Reverse the order of post steps
        reorder_response = authenticated_client.post(
            "/settings/wizard/reorder",
            json={
                "ids": [post_step_2_id, post_step_1_id],  # Reversed
                "server_type": "plex",
                "phase": "post",
            },
            headers={"Content-Type": "application/json"},
        )

        assert reorder_response.status_code == 200

        # Verify the reordering worked correctly
        with authenticated_client.application.app_context():
            post_steps = (
                db.session.query(WizardStep)
                .filter_by(server_type="plex", phase=WizardPhase.POST)
                .order_by(WizardStep.position)
                .all()
            )

            assert len(post_steps) == 2
            assert post_steps[0].id == post_step_2_id
            assert post_steps[0].position == 0
            assert post_steps[1].id == post_step_1_id
            assert post_steps[1].position == 1

    def test_concurrent_reorder_operations(
        self, authenticated_client, complex_wizard_setup
    ):
        """
        Test that concurrent reorder operations don't cause constraint violations.
        This simulates rapid user interactions.
        """
        step_ids = complex_wizard_setup
        pre_steps = step_ids["pre_steps"]

        # Simulate rapid reordering operations
        orders = [
            [pre_steps[2], pre_steps[0], pre_steps[1]],  # 3, 1, 2
            [pre_steps[1], pre_steps[2], pre_steps[0]],  # 2, 3, 1
            [pre_steps[0], pre_steps[1], pre_steps[2]],  # 1, 2, 3 (original)
        ]

        for order in orders:
            reorder_response = authenticated_client.post(
                "/settings/wizard/reorder",
                json={"ids": order, "server_type": "plex", "phase": "pre"},
                headers={"Content-Type": "application/json"},
            )
            assert reorder_response.status_code == 200

            # Verify positions are always sequential
            with authenticated_client.application.app_context():
                pre_steps_ordered = (
                    db.session.query(WizardStep)
                    .filter_by(server_type="plex", phase=WizardPhase.PRE)
                    .order_by(WizardStep.position)
                    .all()
                )

                for i, step in enumerate(pre_steps_ordered):
                    assert step.position == i
