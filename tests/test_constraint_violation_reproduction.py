"""
Test to reproduce the exact SQLite UNIQUE constraint violation error
reported in the issue: sqlite3.IntegrityError: UNIQUE constraint failed: wizard_step.server_type, wizard_step.phase, wizard_step.position
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
    app.config["WTF_CSRF_ENABLED"] = False

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
    client.post("/login", data={"username": "admin", "password": "password"})
    return client


def test_exact_constraint_violation_scenario(authenticated_client, app):
    """
    Test the exact scenario that causes the constraint violation.
    Based on the error: UPDATE wizard_step SET position=?, updated_at=? WHERE wizard_step.id = ?
    Failed Parameters: [(0, '2025-09-13 22:36:17.034989', 2), (2, '2025-09-13 22:36:17.034991', 3)]

    This suggests two steps are being assigned positions 0 and 2, but there might be
    an intermediate state where both try to get position 0 or 2.
    """
    with app.app_context():
        # Clean up any existing data
        db.session.query(WizardStep).delete()
        db.session.commit()

        # Create the exact scenario that might cause the issue
        steps = [
            WizardStep(
                id=2,  # Using the exact IDs from the error
                server_type="plex",
                phase=WizardPhase.POST,
                position=0,
                title="Step 2",
                markdown="# Step 2",
            ),
            WizardStep(
                id=3,  # Using the exact IDs from the error
                server_type="plex",
                phase=WizardPhase.POST,
                position=1,
                title="Step 3",
                markdown="# Step 3",
            ),
        ]

        db.session.add_all(steps)
        db.session.commit()

    # Try the reorder operation that might cause the constraint violation
    # The error suggests step 2 gets position 0 and step 3 gets position 2
    reorder_response = authenticated_client.post(
        "/settings/wizard/reorder",
        json={
            "ids": [2, 3],  # Same order, but this might trigger the issue
            "server_type": "plex",
            "phase": "post",
        },
        headers={"Content-Type": "application/json"},
    )

    # This should not cause a constraint violation
    assert reorder_response.status_code == 200


def test_rapid_reorder_operations(authenticated_client, app):
    """
    Test rapid reorder operations that might cause race conditions.
    """
    with app.app_context():
        # Clean up any existing data
        db.session.query(WizardStep).delete()
        db.session.commit()

        # Create multiple steps
        steps = []
        for i in range(5):
            step = WizardStep(
                server_type="plex",
                phase=WizardPhase.POST,
                position=i,
                title=f"Step {i}",
                markdown=f"# Step {i}",
            )
            steps.append(step)

        db.session.add_all(steps)
        db.session.commit()

        step_ids = [step.id for step in steps]

    # Perform multiple rapid reorder operations
    orders = [
        [
            step_ids[4],
            step_ids[0],
            step_ids[1],
            step_ids[2],
            step_ids[3],
        ],  # Move last to first
        [step_ids[0], step_ids[4], step_ids[1], step_ids[2], step_ids[3]],  # Move back
        [step_ids[1], step_ids[2], step_ids[3], step_ids[4], step_ids[0]],  # Rotate
    ]

    for order in orders:
        reorder_response = authenticated_client.post(
            "/settings/wizard/reorder",
            json={"ids": order, "server_type": "plex", "phase": "post"},
            headers={"Content-Type": "application/json"},
        )

        assert reorder_response.status_code == 200


def test_cross_phase_move_with_immediate_reorder(authenticated_client, app):
    """
    Test the exact JavaScript flow that might cause the constraint violation.
    """
    with app.app_context():
        # Clean up any existing data
        db.session.query(WizardStep).delete()
        db.session.commit()

        # Create steps in both phases
        pre_step = WizardStep(
            server_type="plex",
            phase=WizardPhase.PRE,
            position=0,
            title="Pre Step",
            markdown="# Pre Step",
        )

        post_steps = [
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

        db.session.add(pre_step)
        db.session.add_all(post_steps)
        db.session.commit()

        pre_step_id = pre_step.id
        post_step_ids = [step.id for step in post_steps]

    # Step 1: Move pre step to post phase
    phase_response = authenticated_client.post(
        f"/settings/wizard/{pre_step_id}/update-phase",
        json={"phase": "post", "server_type": "plex"},
        headers={"Content-Type": "application/json"},
    )
    assert phase_response.status_code == 200

    # Step 2: Immediately reorder all post steps (this is where the race condition occurs)
    # The JavaScript gets ALL children from the target container
    all_post_ids = [pre_step_id] + post_step_ids

    reorder_response = authenticated_client.post(
        "/settings/wizard/reorder",
        json={"ids": all_post_ids, "server_type": "plex", "phase": "post"},
        headers={"Content-Type": "application/json"},
    )

    # This should not cause a constraint violation
    assert reorder_response.status_code == 200


def test_constraint_violation_with_manual_position_assignment(app):
    """
    Test that manually assigning duplicate positions causes the constraint violation.
    This helps us understand what the reorder function needs to prevent.
    """
    with app.app_context():
        # Clean up any existing data
        db.session.query(WizardStep).delete()
        db.session.commit()

        # Create two steps
        step1 = WizardStep(
            server_type="plex",
            phase=WizardPhase.POST,
            position=0,
            title="Step 1",
            markdown="# Step 1",
        )

        step2 = WizardStep(
            server_type="plex",
            phase=WizardPhase.POST,
            position=1,
            title="Step 2",
            markdown="# Step 2",
        )

        db.session.add_all([step1, step2])
        db.session.commit()

        # Now try to assign the same position to both steps
        step1.position = 0
        step2.position = 0  # This should cause a constraint violation

        with pytest.raises(IntegrityError):
            db.session.commit()

        db.session.rollback()


def test_reorder_with_gaps_in_positions(authenticated_client, app):
    """
    Test reordering when there are gaps in positions that might cause issues.
    """
    with app.app_context():
        # Clean up any existing data
        db.session.query(WizardStep).delete()
        db.session.commit()

        # Create steps with gaps in positions (simulating after deletions)
        steps = [
            WizardStep(
                server_type="plex",
                phase=WizardPhase.POST,
                position=0,
                title="Step 0",
                markdown="# Step 0",
            ),
            WizardStep(
                server_type="plex",
                phase=WizardPhase.POST,
                position=2,  # Gap at position 1
                title="Step 2",
                markdown="# Step 2",
            ),
            WizardStep(
                server_type="plex",
                phase=WizardPhase.POST,
                position=5,  # Larger gap
                title="Step 5",
                markdown="# Step 5",
            ),
        ]

        db.session.add_all(steps)
        db.session.commit()

        step_ids = [step.id for step in steps]

    # Reorder these steps - this should normalize the positions
    reorder_response = authenticated_client.post(
        "/settings/wizard/reorder",
        json={
            "ids": [step_ids[2], step_ids[0], step_ids[1]],  # Reverse order
            "server_type": "plex",
            "phase": "post",
        },
        headers={"Content-Type": "application/json"},
    )

    assert reorder_response.status_code == 200

    # Verify positions are now sequential
    with app.app_context():
        reordered_steps = (
            db.session.query(WizardStep)
            .filter_by(server_type="plex", phase=WizardPhase.POST)
            .order_by(WizardStep.position)
            .all()
        )

        assert len(reordered_steps) == 3
        for i, step in enumerate(reordered_steps):
            assert step.position == i


def test_phase_change_missing_flush_bug(authenticated_client, app):
    """
    Test the potential bug in _handle_wizard_step_phase_change where
    the final flush() call might be missing after setting final positions.
    """
    with app.app_context():
        # Clean up any existing data
        db.session.query(WizardStep).delete()
        db.session.commit()

        # Create steps in pre phase with specific positions
        pre_steps = [
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
        ]

        # Create a step in post phase
        post_step = WizardStep(
            server_type="plex",
            phase=WizardPhase.POST,
            position=0,
            title="Post Step 1",
            markdown="# Post Step 1",
        )

        db.session.add_all(pre_steps + [post_step])
        db.session.commit()

        pre_step_ids = [step.id for step in pre_steps]
        post_step_id = post_step.id

    # Move the middle pre step (position 1) to post phase
    # This should trigger the gap-closing logic in _handle_wizard_step_phase_change
    phase_response = authenticated_client.post(
        f"/settings/wizard/{pre_step_ids[1]}/update-phase",
        json={"phase": "post", "server_type": "plex"},
        headers={"Content-Type": "application/json"},
    )
    assert phase_response.status_code == 200

    # Immediately try to reorder the post steps
    # This might cause a constraint violation if the phase change didn't flush properly
    reorder_response = authenticated_client.post(
        "/settings/wizard/reorder",
        json={
            "ids": [pre_step_ids[1], post_step_id],  # Moved step first
            "server_type": "plex",
            "phase": "post",
        },
        headers={"Content-Type": "application/json"},
    )

    assert reorder_response.status_code == 200

    # Verify the final state
    with app.app_context():
        # Check post phase steps
        post_steps = (
            db.session.query(WizardStep)
            .filter_by(server_type="plex", phase=WizardPhase.POST)
            .order_by(WizardStep.position)
            .all()
        )

        assert len(post_steps) == 2
        assert post_steps[0].id == pre_step_ids[1]  # Moved step is first
        assert post_steps[1].id == post_step_id

        # Check that pre phase steps have been reordered to close the gap
        remaining_pre_steps = (
            db.session.query(WizardStep)
            .filter_by(server_type="plex", phase=WizardPhase.PRE)
            .order_by(WizardStep.position)
            .all()
        )

        assert len(remaining_pre_steps) == 2
        assert remaining_pre_steps[0].id == pre_step_ids[0]  # position 0
        assert remaining_pre_steps[1].id == pre_step_ids[2]  # should now be position 1
        assert remaining_pre_steps[0].position == 0
        assert remaining_pre_steps[1].position == 1  # Gap should be closed


def test_concurrent_phase_change_and_reorder(authenticated_client, app):
    """
    Test the race condition between phase change and reorder operations.
    This simulates what happens when JavaScript makes rapid sequential calls.
    """
    with app.app_context():
        # Clean up any existing data
        db.session.query(WizardStep).delete()
        db.session.commit()

        # Create a complex setup with multiple steps
        steps = []
        for i in range(3):
            steps.append(
                WizardStep(
                    server_type="plex",
                    phase=WizardPhase.PRE,
                    position=i,
                    title=f"Pre Step {i + 1}",
                    markdown=f"# Pre Step {i + 1}",
                )
            )

        for i in range(2):
            steps.append(
                WizardStep(
                    server_type="plex",
                    phase=WizardPhase.POST,
                    position=i,
                    title=f"Post Step {i + 1}",
                    markdown=f"# Post Step {i + 1}",
                )
            )

        db.session.add_all(steps)
        db.session.commit()

        pre_step_ids = [steps[i].id for i in range(3)]
        post_step_ids = [steps[i].id for i in range(3, 5)]

    # Simulate the exact JavaScript race condition:
    # 1. Move a step from pre to post
    # 2. Immediately reorder all post steps including the moved one

    # This is the exact sequence that causes the constraint violation
    phase_response = authenticated_client.post(
        f"/settings/wizard/{pre_step_ids[0]}/update-phase",
        json={"phase": "post", "server_type": "plex"},
        headers={"Content-Type": "application/json"},
    )
    assert phase_response.status_code == 200

    # Immediately reorder - this is where the constraint violation occurs
    # The JavaScript gets ALL post steps including the one that was just moved
    all_post_ids = [pre_step_ids[0]] + post_step_ids

    reorder_response = authenticated_client.post(
        "/settings/wizard/reorder",
        json={"ids": all_post_ids, "server_type": "plex", "phase": "post"},
        headers={"Content-Type": "application/json"},
    )

    # This should NOT cause a constraint violation
    assert reorder_response.status_code == 200
