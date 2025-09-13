"""
Test to reproduce and verify the fix for the exact SQLite UNIQUE constraint violation
reported in the issue.

Error: sqlite3.IntegrityError: UNIQUE constraint failed: wizard_step.server_type, wizard_step.phase, wizard_step.position
Location: /settings/wizard/reorder endpoint at line 518 (db.session.commit())
SQL: UPDATE wizard_step SET position=?, updated_at=? WHERE wizard_step.id = ?
Parameters: [(0, '2025-09-13 22:36:17.034989', 2), (2, '2025-09-13 22:36:17.034991', 3)]
"""

import pytest

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


def test_exact_error_scenario_reproduction(authenticated_client, app):
    """
    Test the exact scenario that causes the constraint violation based on the error report.

    The error shows:
    - Step ID 2 being assigned position 0
    - Step ID 3 being assigned position 2

    This suggests there might be a gap or conflict in position assignment.
    """
    with app.app_context():
        # Clean up any existing data
        db.session.query(WizardStep).delete()
        db.session.commit()

        # Create the exact scenario that might cause the issue
        # Based on the error, we have steps with IDs 2 and 3
        steps = [
            WizardStep(
                server_type="plex",
                phase=WizardPhase.POST,
                position=0,
                title="Step A",
                markdown="# Step A",
            ),
            WizardStep(
                server_type="plex",
                phase=WizardPhase.POST,
                position=1,
                title="Step B",
                markdown="# Step B",
            ),
            WizardStep(
                server_type="plex",
                phase=WizardPhase.POST,
                position=2,
                title="Step C",
                markdown="# Step C",
            ),
        ]

        db.session.add_all(steps)
        db.session.commit()

        step_ids = [step.id for step in steps]

    # Try various reordering scenarios that might cause the constraint violation

    # Scenario 1: Simple reorder that might cause position conflicts
    reorder_response = authenticated_client.post(
        "/settings/wizard/reorder",
        json={
            "ids": [step_ids[2], step_ids[0], step_ids[1]],  # Move last to first
            "server_type": "plex",
            "phase": "post",
        },
        headers={"Content-Type": "application/json"},
    )

    assert reorder_response.status_code == 200

    # Scenario 2: Rapid sequential reorders (simulating user drag-and-drop)
    orders = [
        [step_ids[1], step_ids[2], step_ids[0]],  # Different order
        [step_ids[0], step_ids[1], step_ids[2]],  # Back to original
        [step_ids[2], step_ids[1], step_ids[0]],  # Reverse
    ]

    for order in orders:
        reorder_response = authenticated_client.post(
            "/settings/wizard/reorder",
            json={"ids": order, "server_type": "plex", "phase": "post"},
            headers={"Content-Type": "application/json"},
        )

        assert reorder_response.status_code == 200

        # Verify positions are always sequential
        with app.app_context():
            steps_ordered = (
                db.session.query(WizardStep)
                .filter_by(server_type="plex", phase=WizardPhase.POST)
                .order_by(WizardStep.position)
                .all()
            )

            assert len(steps_ordered) == 3
            for i, step in enumerate(steps_ordered):
                assert step.position == i, (
                    f"Step {step.id} has position {step.position}, expected {i}"
                )


def test_constraint_violation_with_position_gaps(authenticated_client, app):
    """
    Test reordering when there are position gaps that could cause the exact constraint violation.

    This test creates a scenario where intermediate position assignments might conflict
    with the unique constraint.
    """
    with app.app_context():
        # Clean up any existing data
        db.session.query(WizardStep).delete()
        db.session.commit()

        # Create steps with specific positions that might cause conflicts
        steps = [
            WizardStep(
                server_type="plex",
                phase=WizardPhase.POST,
                position=0,
                title="Step 1",
                markdown="# Step 1",
            ),
            WizardStep(
                server_type="plex",
                phase=WizardPhase.POST,
                position=2,  # Gap at position 1
                title="Step 2",
                markdown="# Step 2",
            ),
        ]

        db.session.add_all(steps)
        db.session.commit()

        step_ids = [step.id for step in steps]

    # Try to reorder these steps - this might trigger the constraint violation
    # if the reorder logic doesn't handle gaps properly
    reorder_response = authenticated_client.post(
        "/settings/wizard/reorder",
        json={
            "ids": [step_ids[1], step_ids[0]],  # Reverse order
            "server_type": "plex",
            "phase": "post",
        },
        headers={"Content-Type": "application/json"},
    )

    assert reorder_response.status_code == 200

    # Verify the final state has no gaps
    with app.app_context():
        steps_ordered = (
            db.session.query(WizardStep)
            .filter_by(server_type="plex", phase=WizardPhase.POST)
            .order_by(WizardStep.position)
            .all()
        )

        assert len(steps_ordered) == 2
        assert steps_ordered[0].position == 0
        assert steps_ordered[1].position == 1  # Gap should be closed


def test_concurrent_phase_change_and_reorder_race_condition(authenticated_client, app):
    """
    Test the race condition that occurs when JavaScript makes rapid sequential calls
    for phase change and reorder operations.

    This is the most likely scenario to cause the constraint violation.
    """
    with app.app_context():
        # Clean up any existing data
        db.session.query(WizardStep).delete()
        db.session.commit()

        # Create a realistic scenario with steps in both phases
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
        ]

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

        db.session.add_all(pre_steps + post_steps)
        db.session.commit()

        pre_step_ids = [step.id for step in pre_steps]
        post_step_ids = [step.id for step in post_steps]

    # Simulate the exact JavaScript race condition:
    # 1. Move a step from pre to post phase
    # 2. Immediately reorder all post steps including the moved one

    # This sequence is what causes the constraint violation
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

    # Verify the final state is correct
    with app.app_context():
        post_steps_final = (
            db.session.query(WizardStep)
            .filter_by(server_type="plex", phase=WizardPhase.POST)
            .order_by(WizardStep.position)
            .all()
        )

        assert len(post_steps_final) == 3  # 2 original + 1 moved

        # Verify positions are sequential without gaps
        for i, step in enumerate(post_steps_final):
            assert step.position == i, (
                f"Step {step.id} has position {step.position}, expected {i}"
            )

        # Verify the moved step is in the correct position (first)
        assert post_steps_final[0].id == pre_step_ids[0]


def test_stress_test_rapid_reorders(authenticated_client, app):
    """
    Stress test with rapid reorder operations to catch any race conditions.
    """
    with app.app_context():
        # Clean up any existing data
        db.session.query(WizardStep).delete()
        db.session.commit()

        # Create multiple steps for stress testing
        steps = []
        for i in range(5):
            step = WizardStep(
                server_type="plex",
                phase=WizardPhase.POST,
                position=i,
                title=f"Step {i + 1}",
                markdown=f"# Step {i + 1}",
            )
            steps.append(step)

        db.session.add_all(steps)
        db.session.commit()

        step_ids = [step.id for step in steps]

    # Perform many rapid reorder operations
    import random

    for _ in range(10):  # 10 rapid reorders
        # Shuffle the order randomly
        random_order = step_ids.copy()
        random.shuffle(random_order)

        reorder_response = authenticated_client.post(
            "/settings/wizard/reorder",
            json={"ids": random_order, "server_type": "plex", "phase": "post"},
            headers={"Content-Type": "application/json"},
        )

        assert reorder_response.status_code == 200

        # Verify positions are always sequential after each reorder
        with app.app_context():
            steps_ordered = (
                db.session.query(WizardStep)
                .filter_by(server_type="plex", phase=WizardPhase.POST)
                .order_by(WizardStep.position)
                .all()
            )

            assert len(steps_ordered) == 5
            for i, step in enumerate(steps_ordered):
                assert step.position == i, (
                    f"After reorder, step {step.id} has position {step.position}, expected {i}"
                )
