"""
Test for tooltip CSS fix - verifying that disabled buttons can show tooltips.

This test verifies that the CSS no longer sets pointer-events: none on disabled buttons,
allowing tooltips to function properly while still maintaining interaction blocking via JavaScript.
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

        # Create admin user
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
def wizard_step_with_interaction(app):
    """Create wizard step that requires interaction."""
    with app.app_context():
        # Clear existing steps
        WizardStep.query.delete()
        db.session.commit()

        # Create media server
        server = MediaServer(
            name="Test Plex Server", server_type="plex", url="http://localhost:32400"
        )
        db.session.add(server)

        # Create step that requires interaction
        step = WizardStep(
            server_type="plex",
            phase=WizardPhase.PRE,
            position=0,
            title="Terms and Rules",
            markdown="# Server Rules\n\nPlease read our [terms](https://example.com/terms) and agree.",
            require_interaction=True,
        )
        db.session.add(step)
        db.session.commit()

        yield step

        # Cleanup
        db.session.delete(step)
        db.session.delete(server)
        db.session.commit()


class TestTooltipCSSFix:
    """Test that CSS no longer prevents tooltips from working."""

    def test_disabled_button_css_allows_tooltips(
        self, authenticated_client, wizard_step_with_interaction
    ):
        """Test that disabled button CSS doesn't include pointer-events: none."""
        response = authenticated_client.get("/settings/wizard/preview/plex?step=0")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Button should be disabled with tooltip attributes
        assert 'data-disabled="1"' in html
        assert 'aria-disabled="true"' in html
        assert (
            'title="Please read the above information carefully and interact with any links or buttons to continue."'
            in html
        )

        # CSS should NOT contain pointer-events: none for disabled wizard buttons
        # Check specifically for the wizard button CSS rules
        wizard_btn_disabled_css_present = '.wizard-btn[aria-disabled="true"]' in html
        assert wizard_btn_disabled_css_present, (
            "Wizard button disabled CSS rule should be present"
        )

        # Extract the wizard button CSS rule to check it doesn't have pointer-events: none
        if wizard_btn_disabled_css_present:
            lines = html.split("\n")
            in_wizard_btn_rule = False
            wizard_btn_rule_lines = []

            for line in lines:
                if '.wizard-btn[aria-disabled="true"]' in line:
                    in_wizard_btn_rule = True
                    wizard_btn_rule_lines.append(line)
                elif in_wizard_btn_rule:
                    wizard_btn_rule_lines.append(line)
                    if "}" in line:
                        break

            wizard_btn_css = "\n".join(wizard_btn_rule_lines)
            # Should not have pointer-events: none (except in comments)
            active_css = wizard_btn_css.replace(
                "/* pointer-events: none; - Removed to allow tooltips on disabled buttons */",
                "",
            )
            assert "pointer-events: none" not in active_css, (
                f"Wizard button CSS should not disable pointer events: {wizard_btn_css}"
            )

        # Verify that the tooltip elements are present
        assert 'id="next-btn-tooltip"' in html
        assert 'data-popover-target="next-btn-tooltip"' in html

    def test_tooltip_html_structure_is_correct(
        self, authenticated_client, wizard_step_with_interaction
    ):
        """Test that tooltip HTML structure is properly rendered."""
        response = authenticated_client.get("/settings/wizard/preview/plex?step=0")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # Check for Flowbite tooltip structure
        assert "<div data-popover" in html
        assert 'id="next-btn-tooltip"' in html
        assert 'role="tooltip"' in html
        assert 'class="absolute z-10 invisible' in html

        # Check for tooltip content
        assert (
            "Please read the above information carefully and interact with any links or buttons to continue."
            in html
        )

    def test_javascript_tooltip_initialization_present(
        self, authenticated_client, wizard_step_with_interaction
    ):
        """Test that JavaScript for tooltip initialization is present."""
        response = authenticated_client.get("/settings/wizard/preview/plex?step=0")
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        # JavaScript should be present to initialize tooltips
        assert "function initTooltips()" in html
        assert "initFlowbite" in html or "window.Flowbite.init" in html
        assert "htmx:afterSwap" in html  # Re-initialization on HTMX swaps

    def test_enabled_button_has_no_tooltip_attributes(self, authenticated_client):
        """Test that enabled buttons don't have tooltip attributes."""
        # Create a step that doesn't require interaction
        with authenticated_client.application.app_context():
            step = WizardStep(
                server_type="plex",
                phase=WizardPhase.PRE,
                position=0,
                title="Welcome",
                markdown="# Welcome!\n\nThis is a normal step.",
                require_interaction=False,
            )
            db.session.add(step)
            db.session.commit()

            response = authenticated_client.get("/settings/wizard/preview/plex?step=0")
            assert response.status_code == 200

            html = response.get_data(as_text=True)

            # Button should NOT be disabled or have tooltip attributes
            next_button_section = self._extract_next_button_section(html)
            assert 'data-disabled="1"' not in next_button_section
            assert 'aria-disabled="true"' not in next_button_section
            assert "data-popover-target" not in next_button_section
            assert (
                'title="Please read the above information carefully'
                not in next_button_section
            )

            # Cleanup
            db.session.delete(step)
            db.session.commit()

    def _extract_next_button_section(self, html):
        """Helper to extract the Next button section from HTML."""
        lines = html.split("\n")
        for i, line in enumerate(lines):
            if 'id="next-btn"' in line:
                # Get context around the button
                start = max(0, i - 5)
                end = min(len(lines), i + 10)
                return "\n".join(lines[start:end])
        return ""
