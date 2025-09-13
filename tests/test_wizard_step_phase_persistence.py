"""Test wizard step phase persistence after drag-and-drop operations.

This test verifies that when a wizard step is moved between sections (pre/post)
via drag-and-drop, the phase change is correctly persisted and reflected in the
edit form, addressing the issue where the edit modal shows stale phase information.
"""

import pytest
from flask import url_for

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

        # Create admin user for authentication (check if exists first)
        existing_admin = AdminAccount.query.filter_by(username="admin").first()
        if not existing_admin:
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


class TestWizardStepPhasePersistence:
    """Test suite for wizard step phase persistence issues."""

    def test_phase_update_persistence_in_edit_form(self, authenticated_client):
        """Test that phase updates are reflected in the edit form immediately.

        This reproduces the reported bug where:
        1. A step is moved from one section to another via drag-and-drop
        2. The step physically moves and counts update correctly
        3. But the Edit Wizard Step form still shows the old section name
        """
        # Create a test wizard step in the POST phase (After Invite Acceptance)
        step = WizardStep(
            server_type="plex",
            phase=WizardPhase.POST,
            position=0,
            title="Test Step",
            markdown="# Test Step Content",
        )
        db.session.add(step)
        db.session.commit()

        step_id = step.id

        # Simulate drag-and-drop: move step from POST to PRE phase
        # This mimics what the frontend JavaScript does when moving between sections
        response = authenticated_client.post(
            url_for("wizard_admin.update_step_phase", step_id=step_id),
            json={"phase": "pre"},
            headers={"Content-Type": "application/json"},
        )

        # Verify the phase update was successful
        assert response.status_code == 200
        assert response.json == {"status": "ok"}

        # Refresh the session to ensure we get the latest data
        db.session.refresh(step)

        # Verify the step phase was actually updated in the database
        assert step.phase == WizardPhase.PRE

        # Now test the critical part: does the edit form show the correct phase?
        # This simulates what happens when a user clicks "Edit Wizard Step"
        edit_response = authenticated_client.get(
            url_for("wizard_admin.edit_step", step_id=step_id),
            headers={"HX-Request": "true"},  # Simulate HTMX request for modal
        )

        assert edit_response.status_code == 200

        # Parse the response to check if the form shows the correct phase
        edit_html = edit_response.get_data(as_text=True)

        # The form should show "Before Invite Acceptance" (PRE phase) selected
        # and NOT "After Invite Acceptance" (POST phase)

        # Check that PRE option is selected (the HTML shows: <option selected value="pre">)
        assert 'selected value="pre"' in edit_html

        # Check that the text "Before Invite Acceptance" appears as selected
        assert "Before Invite Acceptance" in edit_html

        # Ensure POST is not selected (this was the bug - showing old phase)
        # The bug would manifest as POST phase being selected instead of PRE
        assert 'selected value="post"' not in edit_html, (
            "Found POST phase incorrectly selected"
        )

    def test_multiple_phase_changes_persistence(self, authenticated_client):
        """Test that multiple phase changes are correctly persisted."""
        # Create a test wizard step in POST phase
        step = WizardStep(
            server_type="jellyfin",
            phase=WizardPhase.POST,
            position=0,
            title="Multi-Change Test Step",
            markdown="# Multi-Change Test",
        )
        db.session.add(step)
        db.session.commit()
        step_id = step.id

        # Move from POST to PRE
        response1 = authenticated_client.post(
            url_for("wizard_admin.update_step_phase", step_id=step_id),
            json={"phase": "pre"},
        )
        assert response1.status_code == 200

        # Verify first change
        db.session.refresh(step)
        assert step.phase == WizardPhase.PRE

        # Move back from PRE to POST
        response2 = authenticated_client.post(
            url_for("wizard_admin.update_step_phase", step_id=step_id),
            json={"phase": "post"},
        )
        assert response2.status_code == 200

        # Verify second change
        db.session.refresh(step)
        assert step.phase == WizardPhase.POST

        # Verify edit form shows the final state (POST)
        edit_response = authenticated_client.get(
            url_for("wizard_admin.edit_step", step_id=step_id),
            headers={"HX-Request": "true"},
        )

        assert edit_response.status_code == 200
        edit_html = edit_response.get_data(as_text=True)

        # Should show POST phase selected
        assert 'value="post"' in edit_html
        assert "After Invite Acceptance" in edit_html

    def test_phase_persistence_after_browser_refresh(self, authenticated_client):
        """Test that phase changes persist even after simulated browser refresh."""
        # Create a test wizard step
        step = WizardStep(
            server_type="emby",
            phase=WizardPhase.PRE,
            position=0,
            title="Browser Refresh Test",
            markdown="# Browser Refresh Test",
        )
        db.session.add(step)
        db.session.commit()
        step_id = step.id

        # Move from PRE to POST
        response = authenticated_client.post(
            url_for("wizard_admin.update_step_phase", step_id=step_id),
            json={"phase": "post"},
        )
        assert response.status_code == 200

        # Simulate browser refresh by starting a new request context
        # This ensures we're not relying on any cached data
        with authenticated_client.application.app_context():
            fresh_step = db.session.get(WizardStep, step_id)
            assert fresh_step.phase == WizardPhase.POST

            # Get edit form in fresh context (simulates page refresh)
            edit_response = authenticated_client.get(
                url_for("wizard_admin.edit_step", step_id=step_id),
                headers={"HX-Request": "true"},
            )

            assert edit_response.status_code == 200
            edit_html = edit_response.get_data(as_text=True)

            # Should show POST phase selected
            assert "After Invite Acceptance" in edit_html

            # Should NOT show PRE phase selected
            pre_selected_patterns = [
                'value="pre" selected',
                '<option value="pre" selected>',
                '<option selected value="pre">',
            ]

            for pattern in pre_selected_patterns:
                assert pattern not in edit_html, (
                    f"Found PRE phase incorrectly selected: {pattern}"
                )

    def test_concurrent_operations_data_consistency(self, authenticated_client):
        """Test data consistency when multiple operations happen quickly."""
        # Create a test wizard step
        step = WizardStep(
            server_type="audiobookshelf",
            phase=WizardPhase.POST,
            position=0,
            title="Concurrent Test",
            markdown="# Concurrent Test",
        )
        db.session.add(step)
        db.session.commit()
        step_id = step.id

        # Simulate rapid phase change followed immediately by edit form access
        # This mimics the real-world scenario where a user drags a step and
        # immediately clicks edit before the phase update is fully processed

        # Phase change
        phase_response = authenticated_client.post(
            url_for("wizard_admin.update_step_phase", step_id=step_id),
            json={"phase": "pre"},
        )
        assert phase_response.status_code == 200

        # Immediately try to access edit form (no delay)
        edit_response = authenticated_client.get(
            url_for("wizard_admin.edit_step", step_id=step_id),
            headers={"HX-Request": "true"},
        )

        assert edit_response.status_code == 200
        edit_html = edit_response.get_data(as_text=True)

        # Even with immediate access, the form should show the updated phase
        assert "Before Invite Acceptance" in edit_html

        # Verify the database state is also correct
        db.session.refresh(step)
        assert step.phase == WizardPhase.PRE
