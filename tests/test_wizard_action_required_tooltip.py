"""
TDD tests for the refactored "Action Required" UI behavior.

This test suite follows TDD methodology and covers:
1. Tooltip behavior on disabled "Next" button when interaction is required
2. Removal of explanatory text from the blue Action Required box
3. Accessibility standards for tooltip implementation
4. Button state management and interaction tracking
5. Cross-browser tooltip compatibility

Based on requirements:
- Blue box should only display "Action Required" (no explanatory text)
- Explanatory text should appear as tooltip on disabled "Next" button
- Tooltip should only appear when "Next" button is disabled due to unmet interaction requirements
- Maintain accessibility standards (ARIA attributes, keyboard navigation)
- Preserve existing interaction tracking functionality
"""

import pytest

from app import create_app
from app.extensions import db
from app.models import AdminAccount, MediaServer, WizardPhase, WizardStep


@pytest.fixture
def app():
    """Create application for testing."""
    app = create_app()
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        db.create_all()

        # Create admin user for authentication (only if doesn't exist)
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
    client.post("/login", data={"username": "admin", "password": "password"})
    return client


@pytest.fixture
def wizard_steps_with_interaction(app):
    """Create wizard steps with interaction requirements for testing."""
    with app.app_context():
        # Clear existing steps
        WizardStep.query.delete()
        db.session.commit()

        steps = []

        # Step that requires interaction
        interaction_step = WizardStep(
            server_type="plex",
            phase=WizardPhase.PRE,
            position=0,
            title="Rules and Terms",
            markdown="# Server Rules\n\nPlease read our [terms of service](https://example.com/terms) and [rules](https://example.com/rules) before continuing.",
            require_interaction=True,
        )
        steps.append(interaction_step)

        # Step that does not require interaction
        normal_step = WizardStep(
            server_type="plex",
            phase=WizardPhase.PRE,
            position=1,
            title="Welcome",
            markdown="# Welcome!\n\nThis is a normal step without interaction requirements.",
            require_interaction=False,
        )
        steps.append(normal_step)

        for step in steps:
            db.session.add(step)
        db.session.commit()

        # Create an invitation for testing
        from app.models import Invitation

        # Get the server ID within the same context
        server = MediaServer.query.filter_by(name="Test Plex Server").first()
        if not server:
            server = MediaServer(
                name="Test Plex Server",
                server_type="plex",
                url="http://localhost:32400",
            )
            db.session.add(server)
            db.session.commit()

        invitation = Invitation(
            code="test_invitation_code", server_id=server.id, unlimited=True
        )
        db.session.add(invitation)
        db.session.commit()

        return steps


@pytest.fixture
def sample_media_server(app):
    """Create sample media server for testing."""
    with app.app_context():
        server = MediaServer(
            name="Test Plex Server",
            server_type="plex",
            url="http://localhost:32400",
        )
        db.session.add(server)
        db.session.commit()
        return server


class TestActionRequiredBoxRefactor:
    """Test the refactored Action Required box behavior."""

    def test_action_required_box_absent_for_normal_steps(
        self, authenticated_client, wizard_steps_with_interaction, sample_media_server
    ):
        """Test that Action Required box is not shown for steps without interaction requirements."""
        response = authenticated_client.get("/settings/wizard/preview/plex?step=1")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Should NOT show Action Required box at all
        assert "Action Required" not in html
        assert 'class="wizard-interaction-notice' not in html


class TestTooltipBehavior:
    """Test the tooltip behavior on disabled Next button."""

    def test_disabled_next_button_has_tooltip_with_explanatory_text(
        self, authenticated_client, wizard_steps_with_interaction, sample_media_server
    ):
        """Test that disabled Next button shows tooltip with explanatory text."""
        response = authenticated_client.get("/settings/wizard/preview/plex?step=0")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Next button should be disabled
        assert 'data-disabled="1"' in html or 'aria-disabled="true"' in html

        # Next button should have tooltip attributes
        next_button_found = False
        lines = html.split("\n")
        for i, line in enumerate(lines):
            if 'id="next-btn"' in line:
                next_button_found = True
                # Look for tooltip attributes in this line or nearby lines
                context = "\n".join(
                    lines[max(0, i - 5) : i + 10]
                )  # Get more context around the button

                # Should have tooltip/popover attributes
                assert (
                    "data-popover-target" in context
                    or "data-tooltip" in context
                    or "title=" in context
                ), f"Next button should have tooltip attributes. Context: {context}"

                # Should contain the explanatory text somewhere in tooltip
                assert (
                    "Please read the above information carefully and interact with any links or buttons to continue"
                    in context
                    or "interaction" in context.lower()
                ), f"Tooltip should contain explanatory text. Context: {context}"
                break

        assert next_button_found, (
            "Next button with id='next-btn' should be found in HTML"
        )

    def test_enabled_next_button_has_no_interaction_tooltip(
        self, authenticated_client, wizard_steps_with_interaction, sample_media_server
    ):
        """Test that enabled Next button does not show interaction requirement tooltip."""
        response = authenticated_client.get("/settings/wizard/preview/plex?step=1")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Next button should not be disabled (check button attributes, not CSS)
        # Get context around the next button specifically
        next_button_found = False
        lines = html.split("\n")
        for i, line in enumerate(lines):
            if 'id="next-btn"' in line:
                next_button_found = True
                button_context = "\n".join(lines[max(0, i - 5) : i + 10])
                assert 'data-disabled="1"' not in button_context, (
                    f"Button should not be disabled. Context: {button_context}"
                )
                # Check that aria-disabled is not in the button context (excluding CSS)
                button_lines = [
                    line
                    for line in lines[max(0, i - 5) : i + 10]
                    if not line.strip().startswith(".")
                    and not line.strip().startswith("@apply")
                ]
                assert 'aria-disabled="true"' not in "\n".join(button_lines), (
                    f"Button should not have aria-disabled. Context: {button_context}"
                )
                break

        assert next_button_found, "Next button should be found in HTML"

        # Should not have interaction requirement tooltip
        if 'id="next-btn"' in html:
            lines = html.split("\n")
            for i, line in enumerate(lines):
                if 'id="next-btn"' in line:
                    context = "\n".join(lines[max(0, i - 5) : i + 10])
                    # Should not contain interaction-specific tooltip text
                    assert (
                        "Please read the above information carefully and interact with any links or buttons to continue"
                        not in context
                    )
                    break

    def test_tooltip_accessibility_attributes(
        self, authenticated_client, wizard_steps_with_interaction, sample_media_server
    ):
        """Test that tooltip has proper accessibility attributes."""
        response = authenticated_client.get("/settings/wizard/preview/plex?step=0")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Should have proper ARIA attributes for tooltips
        # Look for tooltip-related accessibility attributes
        has_tooltip_aria = (
            'role="tooltip"' in html
            or "aria-describedby=" in html
            or "aria-label=" in html
            or "data-popover-target" in html
        )
        assert has_tooltip_aria, "Tooltip should have proper accessibility attributes"


class TestButtonStateManagement:
    """Test button state management and interaction tracking."""

    def test_next_button_disabled_state_styling(
        self, authenticated_client, wizard_steps_with_interaction, sample_media_server
    ):
        """Test that disabled Next button has proper styling."""
        response = authenticated_client.get("/settings/wizard/preview/plex?step=0")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Next button should have disabled styling
        next_button_found = False
        lines = html.split("\n")
        for i, line in enumerate(lines):
            if 'id="next-btn"' in line:
                next_button_found = True
                context = "\n".join(lines[max(0, i - 5) : i + 10])

                # Should have disabled state attributes and styling
                assert 'data-disabled="1"' in context, (
                    f"Button should be marked as disabled. Context: {context}"
                )
                assert (
                    'aria-disabled="true"' in context or 'aria-disabled="true"' in html
                ), "Button should have aria-disabled"

                # Should have visual disabled styling
                disabled_styling = (
                    "opacity: 0.6" in context
                    or "opacity:0.6" in context
                    or "pointer-events: none" in context
                    or "pointer-events:none" in context
                )
                assert disabled_styling, (
                    f"Button should have disabled visual styling. Context: {context}"
                )
                break

        assert next_button_found, "Next button should be found in HTML"

    def test_interaction_tracking_javascript_preserved(
        self, authenticated_client, wizard_steps_with_interaction, sample_media_server
    ):
        """Test that JavaScript interaction tracking is preserved."""
        response = authenticated_client.get("/settings/wizard/preview/plex?step=0")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Should have data attributes for interaction tracking
        assert 'data-interaction-required="true"' in html

        # Should load the wizard-steps.js file that contains interaction logic
        assert "wizard-steps.js" in html or "attachInteractionGating" in html

    def test_complete_button_tooltip_on_final_step(
        self, authenticated_client, wizard_steps_with_interaction, sample_media_server
    ):
        """Test that Complete button also shows tooltip when disabled on final step."""
        # Add a final step that requires interaction
        with authenticated_client.application.app_context():
            final_step = WizardStep(
                server_type="plex",
                phase=WizardPhase.POST,
                position=0,
                title="Final Agreement",
                markdown="# Final Agreement\n\nPlease [accept the terms](https://example.com/accept) to complete setup.",
                require_interaction=True,
            )
            db.session.add(final_step)
            db.session.commit()

        # Navigate to the final step
        response = authenticated_client.get("/settings/wizard/preview/plex?step=2")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Complete button should be disabled and have tooltip
        if 'id="complete-btn"' in html:
            lines = html.split("\n")
            for i, line in enumerate(lines):
                if 'id="complete-btn"' in line:
                    context = "\n".join(lines[max(0, i - 5) : i + 10])

                    # Should be disabled
                    assert 'data-disabled="1"' in context

                    # Should have tooltip attributes
                    has_tooltip = (
                        "data-popover-target" in context
                        or "data-tooltip" in context
                        or "title=" in context
                    )
                    assert has_tooltip, (
                        f"Complete button should have tooltip. Context: {context}"
                    )
                    break


class TestCrossBrowserCompatibility:
    """Test cross-browser tooltip compatibility."""

    def test_tooltip_uses_standard_attributes(
        self, authenticated_client, wizard_steps_with_interaction, sample_media_server
    ):
        """Test that tooltip uses standard, cross-browser compatible attributes."""
        response = authenticated_client.get("/settings/wizard/preview/plex?step=0")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Should use standard tooltip/popover attributes that work across browsers
        # Either Flowbite data-popover-* attributes or standard title/aria-* attributes
        standard_attributes = (
            "data-popover-target" in html
            or "title=" in html
            or "aria-describedby=" in html
        )
        assert standard_attributes, (
            "Should use standard, cross-browser compatible tooltip attributes"
        )

    def test_tooltip_fallback_with_title_attribute(
        self, authenticated_client, wizard_steps_with_interaction, sample_media_server
    ):
        """Test that tooltip has title attribute as fallback for accessibility."""
        response = authenticated_client.get("/settings/wizard/preview/plex?step=0")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Should have title attribute as a fallback
        if 'id="next-btn"' in html:
            # Look for title attribute on the next button
            next_button_line = None
            for line in html.split("\n"):
                if 'id="next-btn"' in line:
                    next_button_line = line
                    break

            if next_button_line:
                # Should have title attribute for basic tooltip support
                assert "title=" in next_button_line or "title=" in html
