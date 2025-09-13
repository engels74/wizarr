"""Test wizard admin routes functionality including drag-and-drop and phase management."""

import pytest
from sqlalchemy import select

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


@pytest.fixture
def sample_steps(app):
    """Create sample wizard steps for testing."""
    with app.app_context():
        # Clear existing plex steps to avoid conflicts
        WizardStep.query.filter_by(server_type="plex").delete()
        db.session.commit()

        steps = [
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
                phase=WizardPhase.POST,
                position=0,
                title="Post Step 1",
                markdown="# Post Step 1",
            ),
        ]
        db.session.add_all(steps)
        db.session.commit()

        # Return step IDs for use in tests
        return [step.id for step in steps]


class TestWizardStepReordering:
    """Test wizard step reordering functionality."""

    def test_reorder_steps_within_same_phase(self, authenticated_client, sample_steps):
        """Test reordering steps within the same phase."""
        pre_step_1_id, pre_step_2_id, post_step_1_id = sample_steps

        # Reorder pre-phase steps (swap positions)
        response = authenticated_client.post(
            "/settings/wizard/reorder",
            json={
                "ids": [pre_step_2_id, pre_step_1_id],  # Reversed order
                "server_type": "plex",
                "phase": "pre",
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        assert response.json == {"status": "ok"}

        # Verify positions were updated
        with authenticated_client.application.app_context():
            step_1 = db.session.get(WizardStep, pre_step_1_id)
            step_2 = db.session.get(WizardStep, pre_step_2_id)

            assert step_2.position == 0  # Now first
            assert step_1.position == 1  # Now second

    def test_reorder_steps_empty_list(self, authenticated_client):
        """Test reordering with empty step list."""
        response = authenticated_client.post(
            "/settings/wizard/reorder",
            json={"ids": [], "server_type": "plex", "phase": "pre"},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        assert response.json == {"status": "ok"}

    def test_reorder_steps_invalid_data(self, authenticated_client):
        """Test reordering with invalid data."""
        # Missing server_type
        response = authenticated_client.post(
            "/settings/wizard/reorder",
            json={"ids": [1, 2], "phase": "pre"},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400

        # Invalid data type
        response = authenticated_client.post(
            "/settings/wizard/reorder",
            json="invalid",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400


class TestWizardStepPhaseUpdate:
    """Test wizard step phase update functionality."""

    def test_update_step_phase_pre_to_post(self, authenticated_client, sample_steps):
        """Test moving step from pre-invite to post-invite phase."""
        pre_step_1_id, pre_step_2_id, post_step_1_id = sample_steps

        response = authenticated_client.post(
            f"/settings/wizard/{pre_step_1_id}/update-phase",
            json={"phase": "post", "server_type": "plex"},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        assert response.json == {"status": "ok"}

        # Verify phase and position were updated
        with authenticated_client.application.app_context():
            step = db.session.get(WizardStep, pre_step_1_id)
            assert step.phase == WizardPhase.POST
            # Should be positioned after existing post step
            assert step.position == 1

    def test_update_step_phase_post_to_pre(self, authenticated_client, sample_steps):
        """Test moving step from post-invite to pre-invite phase."""
        pre_step_1_id, pre_step_2_id, post_step_1_id = sample_steps

        response = authenticated_client.post(
            f"/settings/wizard/{post_step_1_id}/update-phase",
            json={"phase": "pre", "server_type": "plex"},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        assert response.json == {"status": "ok"}

        # Verify phase and position were updated
        with authenticated_client.application.app_context():
            step = db.session.get(WizardStep, post_step_1_id)
            assert step.phase == WizardPhase.PRE
            # Should be positioned after existing pre steps
            assert step.position == 2

    def test_update_step_phase_to_empty_phase(self, authenticated_client):
        """Test moving step to an empty phase."""
        with authenticated_client.application.app_context():
            # Create a step in post phase only
            step = WizardStep(
                server_type="jellyfin",
                phase=WizardPhase.POST,
                position=0,
                title="Only Step",
                markdown="# Only Step",
            )
            db.session.add(step)
            db.session.commit()
            step_id = step.id

        # Move to empty pre phase
        response = authenticated_client.post(
            f"/settings/wizard/{step_id}/update-phase",
            json={"phase": "pre", "server_type": "jellyfin"},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        assert response.json == {"status": "ok"}

        # Verify step moved to pre phase with position 0
        with authenticated_client.application.app_context():
            step = db.session.get(WizardStep, step_id)
            assert step.phase == WizardPhase.PRE
            assert step.position == 0

    def test_update_step_phase_same_phase(self, authenticated_client, sample_steps):
        """Test updating step to same phase (should be no-op)."""
        pre_step_1_id, pre_step_2_id, post_step_1_id = sample_steps

        # Get original position
        with authenticated_client.application.app_context():
            original_step = db.session.get(WizardStep, pre_step_1_id)
            original_position = original_step.position

        response = authenticated_client.post(
            f"/settings/wizard/{pre_step_1_id}/update-phase",
            json={"phase": "pre", "server_type": "plex"},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        assert response.json == {"status": "ok"}

        # Verify position unchanged
        with authenticated_client.application.app_context():
            step = db.session.get(WizardStep, pre_step_1_id)
            assert step.phase == WizardPhase.PRE
            assert step.position == original_position

    def test_update_step_phase_invalid_data(self, authenticated_client, sample_steps):
        """Test phase update with invalid data."""
        pre_step_1_id = sample_steps[0]

        # Missing phase
        response = authenticated_client.post(
            f"/settings/wizard/{pre_step_1_id}/update-phase",
            json={"server_type": "plex"},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400

        # Invalid phase value
        response = authenticated_client.post(
            f"/settings/wizard/{pre_step_1_id}/update-phase",
            json={"phase": "invalid", "server_type": "plex"},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400

        # Non-existent step
        response = authenticated_client.post(
            "/settings/wizard/99999/update-phase",
            json={"phase": "post", "server_type": "plex"},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 404


class TestWizardStepConstraintHandling:
    """Test database constraint handling during operations."""

    def test_phase_change_avoids_constraint_violation(self, authenticated_client):
        """Test that phase changes properly handle position conflicts."""
        with authenticated_client.application.app_context():
            # Create steps that would cause constraint violation if not handled properly
            steps = [
                WizardStep(
                    server_type="plex",
                    phase=WizardPhase.PRE,
                    position=0,
                    title="Pre Step",
                    markdown="# Pre Step",
                ),
                WizardStep(
                    server_type="plex",
                    phase=WizardPhase.POST,
                    position=0,
                    title="Post Step",
                    markdown="# Post Step",
                ),
            ]
            db.session.add_all(steps)
            db.session.commit()
            pre_step_id = steps[0].id

        # Move pre step to post phase - this should not cause constraint violation
        response = authenticated_client.post(
            f"/settings/wizard/{pre_step_id}/update-phase",
            json={"phase": "post", "server_type": "plex"},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        assert response.json == {"status": "ok"}

        # Verify both steps exist with different positions
        with authenticated_client.application.app_context():
            stmt = (
                select(WizardStep)
                .where(
                    WizardStep.server_type == "plex",
                    WizardStep.phase == WizardPhase.POST,
                )
                .order_by(WizardStep.position)
            )
            post_steps = db.session.execute(stmt).scalars().all()

            assert len(post_steps) == 2
            assert post_steps[0].position == 0
            assert post_steps[1].position == 1


class TestDragAndDropScenarios:
    """Test drag-and-drop scenarios including empty sections."""

    def test_drag_step_to_empty_pre_phase(self, authenticated_client):
        """Test dragging a step to an empty pre-invite phase."""
        with authenticated_client.application.app_context():
            # Create only post-phase steps
            step = WizardStep(
                server_type="plex",
                phase=WizardPhase.POST,
                position=0,
                title="Post Step",
                markdown="# Post Step",
            )
            db.session.add(step)
            db.session.commit()
            step_id = step.id

        # Simulate drag-and-drop: first update phase, then reorder
        # Step 1: Update phase (simulates updateStepPhase call)
        phase_response = authenticated_client.post(
            f"/settings/wizard/{step_id}/update-phase",
            json={"phase": "pre", "server_type": "plex"},
            headers={"Content-Type": "application/json"},
        )
        assert phase_response.status_code == 200

        # Step 2: Reorder in new phase (simulates reorder call)
        reorder_response = authenticated_client.post(
            "/settings/wizard/reorder",
            json={"ids": [step_id], "server_type": "plex", "phase": "pre"},
            headers={"Content-Type": "application/json"},
        )
        assert reorder_response.status_code == 200

        # Verify step is now in pre phase at position 0
        with authenticated_client.application.app_context():
            step = db.session.get(WizardStep, step_id)
            assert step is not None
            assert step.phase == WizardPhase.PRE
            assert step.position == 0

    def test_drag_step_to_empty_post_phase(self, authenticated_client):
        """Test dragging a step to an empty post-invite phase."""
        with authenticated_client.application.app_context():
            # Create only pre-phase steps
            step = WizardStep(
                server_type="plex",
                phase=WizardPhase.PRE,
                position=0,
                title="Pre Step",
                markdown="# Pre Step",
            )
            db.session.add(step)
            db.session.commit()
            step_id = step.id

        # Simulate drag-and-drop: first update phase, then reorder
        phase_response = authenticated_client.post(
            f"/settings/wizard/{step_id}/update-phase",
            json={"phase": "post", "server_type": "plex"},
            headers={"Content-Type": "application/json"},
        )
        assert phase_response.status_code == 200

        reorder_response = authenticated_client.post(
            "/settings/wizard/reorder",
            json={"ids": [step_id], "server_type": "plex", "phase": "post"},
            headers={"Content-Type": "application/json"},
        )
        assert reorder_response.status_code == 200

        # Verify step is now in post phase at position 0
        with authenticated_client.application.app_context():
            step = db.session.get(WizardStep, step_id)
            assert step is not None
            assert step.phase == WizardPhase.POST
            assert step.position == 0

    def test_drag_multiple_steps_between_phases(
        self, authenticated_client, sample_steps
    ):
        """Test dragging multiple steps between phases."""
        pre_step_1_id, pre_step_2_id, post_step_1_id = sample_steps

        # Move both pre steps to post phase
        for step_id in [pre_step_1_id, pre_step_2_id]:
            phase_response = authenticated_client.post(
                f"/settings/wizard/{step_id}/update-phase",
                json={"phase": "post", "server_type": "plex"},
                headers={"Content-Type": "application/json"},
            )
            assert phase_response.status_code == 200

        # Reorder all post steps
        reorder_response = authenticated_client.post(
            "/settings/wizard/reorder",
            json={
                "ids": [post_step_1_id, pre_step_1_id, pre_step_2_id],
                "server_type": "plex",
                "phase": "post",
            },
            headers={"Content-Type": "application/json"},
        )
        assert reorder_response.status_code == 200

        # Verify all steps are in post phase with correct positions
        with authenticated_client.application.app_context():
            stmt = (
                select(WizardStep)
                .where(
                    WizardStep.server_type == "plex",
                    WizardStep.phase == WizardPhase.POST,
                )
                .order_by(WizardStep.position)
            )
            post_steps = db.session.execute(stmt).scalars().all()

            assert len(post_steps) == 3
            assert post_steps[0].id == post_step_1_id
            assert post_steps[1].id == pre_step_1_id
            assert post_steps[2].id == pre_step_2_id

            # Verify positions are sequential
            for i, step in enumerate(post_steps):
                assert step.position == i


class TestWizardStepModalEditing:
    """Test wizard step editing through modal forms."""

    def test_edit_step_phase_change_through_modal(self, authenticated_client):
        """Test changing step phase through the edit modal form."""
        with authenticated_client.application.app_context():
            # Create test steps
            steps = [
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
                    phase=WizardPhase.POST,
                    position=0,
                    title="Post Step 1",
                    markdown="# Post Step 1",
                ),
            ]
            db.session.add_all(steps)
            db.session.commit()
            step_ids = [step.id for step in steps]

        # Edit Pre Step 1 and change its phase to POST through the modal form
        response = authenticated_client.post(
            f"/settings/wizard/{step_ids[0]}/edit",
            data={
                "server_type": "plex",
                "phase": "post",  # Change from PRE to POST
                "title": "Pre Step 1 (moved to POST)",
                "markdown": "# Pre Step 1 (moved to POST)",
                "require_interaction": False,
            },
            headers={"HX-Request": "true"},  # Simulate HTMX request
        )

        assert response.status_code == 200

        # Verify the step was moved to POST phase with correct position
        with authenticated_client.application.app_context():
            moved_step = db.session.get(WizardStep, step_ids[0])
            assert moved_step is not None
            assert moved_step.phase == WizardPhase.POST
            assert moved_step.position == 1  # Should be after existing POST step
            assert moved_step.title == "Pre Step 1 (moved to POST)"

            # Verify remaining PRE step was repositioned
            remaining_pre_step = db.session.get(WizardStep, step_ids[1])
            assert remaining_pre_step is not None
            assert remaining_pre_step.phase == WizardPhase.PRE
            assert remaining_pre_step.position == 0  # Should move to position 0

            # Verify existing POST step is unchanged
            existing_post_step = db.session.get(WizardStep, step_ids[2])
            assert existing_post_step is not None
            assert existing_post_step.phase == WizardPhase.POST
            assert existing_post_step.position == 0  # Should remain at position 0


class TestWizardPreview:
    """Test wizard preview functionality."""

    def test_preview_wizard_with_pre_and_post_steps(
        self, authenticated_client, sample_steps
    ):
        """Test preview shows both pre and post wizard steps."""
        response = authenticated_client.get("/settings/wizard/preview/plex")
        assert response.status_code == 200

        # Check that response contains preview indicators
        response_text = response.get_data(as_text=True)
        assert "Preview Mode - Plex Wizard Steps" in response_text
        assert "Preview Mode - Plex Wizard Steps" in response_text
        assert "Before Invite Acceptance" in response_text

        # Check that it shows the first pre step by default
        assert "Pre Step 1" in response_text

    def test_preview_wizard_navigation_through_all_steps(
        self, authenticated_client, sample_steps
    ):
        """Test navigating through all steps in preview mode."""
        # Start with step 0 (first pre step)
        response = authenticated_client.get("/settings/wizard/preview/plex?step=0")
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)
        assert "Pre Step 1" in response_text
        assert "Before Invite Acceptance" in response_text

        # Step 1 (second pre step)
        response = authenticated_client.get("/settings/wizard/preview/plex?step=1")
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)
        assert "Pre Step 2" in response_text
        assert "Before Invite Acceptance" in response_text

        # Step 2 (join transition)
        response = authenticated_client.get("/settings/wizard/preview/plex?step=2")
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)
        assert "Accept Invitation" in response_text
        assert "Invite Acceptance" in response_text
        assert "Ready to Join!" in response_text

        # Step 3 (post step)
        response = authenticated_client.get("/settings/wizard/preview/plex?step=3")
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)
        assert "Post Step 1" in response_text
        assert "After Invite Acceptance" in response_text

    def test_preview_wizard_with_only_pre_steps(self, authenticated_client):
        """Test preview with only pre-invite steps."""
        with authenticated_client.application.app_context():
            # Create only pre steps
            step = WizardStep(
                server_type="jellyfin",
                phase=WizardPhase.PRE,
                position=0,
                title="Only Pre Step",
                markdown="# Only Pre Step Content",
            )
            db.session.add(step)
            db.session.commit()

        response = authenticated_client.get("/settings/wizard/preview/jellyfin")
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)

        # Should show pre step
        assert "Only Pre Step" in response_text
        assert "Before Invite Acceptance" in response_text

        # Check total steps count (1 pre + 1 join + 0 post)
        assert "Step 1 of 2" in response_text

    def test_preview_wizard_with_only_post_steps(self, authenticated_client):
        """Test preview with only post-invite steps."""
        with authenticated_client.application.app_context():
            # Create only post steps
            step = WizardStep(
                server_type="emby",
                phase=WizardPhase.POST,
                position=0,
                title="Only Post Step",
                markdown="# Only Post Step Content",
            )
            db.session.add(step)
            db.session.commit()

        # Should show join step first (step 0)
        response = authenticated_client.get("/settings/wizard/preview/emby?step=0")
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)
        assert "Accept Invitation" in response_text

        # Then post step (step 1)
        response = authenticated_client.get("/settings/wizard/preview/emby?step=1")
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)
        assert "Only Post Step" in response_text
        assert "After Invite Acceptance" in response_text

    def test_preview_wizard_with_no_steps(self, authenticated_client):
        """Test preview with no wizard steps."""
        response = authenticated_client.get("/settings/wizard/preview/nonexistent")
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)

        # Should only show join step
        assert "Accept Invitation" in response_text
        assert "Step 1 of 1" in response_text

    def test_preview_wizard_step_bounds_checking(
        self, authenticated_client, sample_steps
    ):
        """Test preview handles step bounds correctly."""
        # Step number too high
        response = authenticated_client.get("/settings/wizard/preview/plex?step=999")
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)
        # Should show last step (post step in this case)
        assert "Post Step 1" in response_text

        # Negative step number
        response = authenticated_client.get("/settings/wizard/preview/plex?step=-1")
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)
        # Should show first step (pre step)
        assert "Pre Step 1" in response_text

    def test_preview_wizard_markdown_rendering(self, authenticated_client):
        """Test that markdown is properly rendered in preview."""
        with authenticated_client.application.app_context():
            # Create step with markdown content
            step = WizardStep(
                server_type="plex",
                phase=WizardPhase.PRE,
                position=0,
                title="Markdown Step",
                markdown="# Heading\n\n**Bold text** and *italic text*\n\n- List item 1\n- List item 2",
            )
            db.session.add(step)
            db.session.commit()

        response = authenticated_client.get("/settings/wizard/preview/plex")
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)

        # Check that markdown was rendered to HTML
        assert "<h1>Heading</h1>" in response_text
        assert "<strong>Bold text</strong>" in response_text
        assert "<em>italic text</em>" in response_text
        assert "<ul>" in response_text
        assert "<li>List item 1</li>" in response_text

    def test_preview_wizard_with_interaction_required(self, authenticated_client):
        """Test preview displays interaction requirements correctly."""
        with authenticated_client.application.app_context():
            # Clear existing plex steps to avoid conflicts
            WizardStep.query.filter_by(server_type="plex").delete()
            db.session.commit()

            # Create step that requires interaction
            step = WizardStep(
                server_type="plex",
                phase=WizardPhase.PRE,
                position=0,
                title="Interactive Step",
                markdown="Please read this carefully.",
                require_interaction=True,
            )
            db.session.add(step)
            db.session.commit()

        response = authenticated_client.get("/settings/wizard/preview/plex")
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)

        # Check interaction preview is shown
        assert "Interaction Required" in response_text
        assert "I Understand (Preview Only)" in response_text

    def test_preview_wizard_server_context_variables(self, authenticated_client):
        """Test that server context variables are available in preview."""
        from app.models import MediaServer

        with authenticated_client.application.app_context():
            # Create a media server
            server = MediaServer(
                server_type="plex",
                name="Test Plex Server",
                url="http://localhost:32400",
                external_url="https://plex.example.com",
            )
            db.session.add(server)

            # Create step that uses server variables
            step = WizardStep(
                server_type="plex",
                phase=WizardPhase.PRE,
                position=0,
                title="Server Info Step",
                markdown="Connect to {{ settings.server_name }} at {{ settings.external_url }}",
            )
            db.session.add(step)
            db.session.commit()

        response = authenticated_client.get("/settings/wizard/preview/plex")
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)

        # Check that template variables were rendered
        assert "Test Plex Server" in response_text
        assert "https://plex.example.com" in response_text

    def test_preview_wizard_navigation_urls(self, authenticated_client, sample_steps):
        """Test that navigation URLs are correct in preview."""
        response = authenticated_client.get("/settings/wizard/preview/plex?step=1")
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)

        # Check previous and next navigation links
        assert (
            'href="/settings/wizard/preview/plex?step=0"' in response_text
        )  # Previous
        assert 'href="/settings/wizard/preview/plex?step=2"' in response_text  # Next

    def test_preview_wizard_breadcrumb_navigation(
        self, authenticated_client, sample_steps
    ):
        """Test breadcrumb navigation in preview."""
        response = authenticated_client.get("/settings/wizard/preview/plex")
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)

        # Check that preview page loads correctly (breadcrumbs removed in recent update)
        assert "<!DOCTYPE html>" in response_text
        assert "preview" in response_text.lower() or "wizard" in response_text.lower()

    def test_preview_wizard_progress_calculation(
        self, authenticated_client, sample_steps
    ):
        """Test progress bar calculation in preview."""
        # Step 0 of 4 total steps (2 pre + 1 join + 1 post)
        response = authenticated_client.get("/settings/wizard/preview/plex?step=0")
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)
        assert "Step 1 of 4" in response_text
        assert 'style="width: 25.0%"' in response_text  # 1/4 = 25%

        # Step 1 of 4
        response = authenticated_client.get("/settings/wizard/preview/plex?step=1")
        assert response.status_code == 200
        response_text = response.get_data(as_text=True)
        assert "Step 2 of 4" in response_text
        assert 'style="width: 50.0%"' in response_text  # 2/4 = 50%

    def test_preview_wizard_requires_authentication(self, client):
        """Test that preview requires admin authentication."""
        response = client.get("/settings/wizard/preview/plex")
        # Should redirect to login page
        assert response.status_code == 302
        assert "/login" in response.location

    def test_preview_wizard_different_server_types(self, authenticated_client):
        """Test preview works with different server types."""
        server_types = ["plex", "jellyfin", "emby", "audiobookshelf"]

        for server_type in server_types:
            with authenticated_client.application.app_context():
                # Clear existing steps for this server type to avoid conflicts
                WizardStep.query.filter_by(server_type=server_type).delete()
                db.session.commit()

                # Create a step for this server type
                step = WizardStep(
                    server_type=server_type,
                    phase=WizardPhase.PRE,
                    position=0,
                    title=f"{server_type.title()} Step",
                    markdown=f"# Welcome to {server_type.title()}",
                )
                db.session.add(step)
                db.session.commit()

            response = authenticated_client.get(
                f"/settings/wizard/preview/{server_type}"
            )
            assert response.status_code == 200
            response_text = response.get_data(as_text=True)
            assert f"{server_type.title()} Step" in response_text
            assert f"Preview Mode - {server_type.title()}" in response_text
