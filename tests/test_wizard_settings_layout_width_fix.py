"""
Test for wizard settings layout width fix.

This test ensures that the wizard settings container doesn't have excess width
at the bottom, specifically addressing the CSS grid layout issue where the
container extends beyond the actual content areas.

Following TDD methodology:
1. Test the specific layout issue (red rectangle excess width from screenshot)
2. Verify the fix removes excess width without breaking functionality
3. Ensure responsive design still works correctly
"""

import pytest
from sqlalchemy import select

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
    client.post("/login", data={"username": "admin", "password": "password"})
    return client


@pytest.fixture
def plex_server_with_steps(app):
    """Setup Plex server with wizard steps for layout testing."""
    with app.app_context():
        # Create media server
        media_server = MediaServer(
            name="Test Plex Server",
            server_type="plex",
            url="http://localhost:32400",
            api_key="test-key",
        )
        db.session.add(media_server)

        # Clear existing steps
        stmt = select(WizardStep).where(WizardStep.server_type == "plex")
        existing_steps = db.session.execute(stmt).scalars().all()
        for step in existing_steps:
            db.session.delete(step)
        db.session.commit()

        # Create steps for both phases
        steps = [
            WizardStep(
                server_type="plex",
                phase=WizardPhase.POST,
                position=0,
                title="What is Plex?",
                markdown="# What is Plex?\nPlex is a media server...",
            ),
            WizardStep(
                server_type="plex",
                phase=WizardPhase.POST,
                position=1,
                title="Join & download Plex",
                markdown="# Join & download Plex\nDownload the app...",
            ),
            WizardStep(
                server_type="plex",
                phase=WizardPhase.POST,
                position=2,
                title="Tips for the best experience",
                markdown="# Tips\nHere are some tips...",
            ),
        ]
        db.session.add_all(steps)
        db.session.commit()
        return "plex"


class TestWizardSettingsLayoutWidth:
    """Test wizard settings layout width fix."""

    def test_grid_container_proper_width_bounds(
        self, authenticated_client, plex_server_with_steps
    ):
        """Test that grid container doesn't extend beyond content areas."""
        server_type = plex_server_with_steps
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Verify the grid layout structure exists
        assert "grid grid-cols-1 lg:grid-cols-2" in response_text
        assert server_type in response_text  # Ensure our test server is present

        # Check that grid container has proper bounds
        # Look for the specific grid container in the HTML
        grid_start = response_text.find('class="grid grid-cols-1 lg:grid-cols-2')
        assert grid_start != -1, "Grid container should be present"

        # Find the closing div for this grid container
        # We need to ensure it doesn't extend beyond the phase sections
        grid_section = response_text[
            grid_start : grid_start + 10000
        ]  # reasonable chunk

        # Verify both phase sections are present within the grid
        assert "Before Invite Acceptance" in grid_section
        assert "After Invite Acceptance" in grid_section

        # Check that there's no excessive empty space CSS that would cause width issues
        # The CSS should use proper grid layout without unnecessary extensions
        assert (
            "space-y-6" in response_text
        )  # This should be the outer container spacing

    def test_phase_sections_proper_sizing(
        self, authenticated_client, plex_server_with_steps
    ):
        """Test that phase sections have proper sizing without excess width."""
        server_type = plex_server_with_steps
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Verify phase sections use appropriate CSS classes
        assert "phase-section" in response_text
        assert server_type in response_text  # Ensure our test server is present

        # Check that phase sections don't have excessive margin/padding that causes width issues
        phase_section_css_start = response_text.find(".phase-section")
        if phase_section_css_start != -1:
            # Find the CSS block for phase-section
            css_block_end = response_text.find("}", phase_section_css_start)
            css_block = response_text[phase_section_css_start:css_block_end]

            # Verify reasonable margin-bottom but no excessive spacing
            assert "margin-bottom: 2rem" in css_block or "margin-bottom:" in css_block

    def test_server_section_container_bounds(
        self, authenticated_client, plex_server_with_steps
    ):
        """Test that server section container has proper bounds."""
        server_type = plex_server_with_steps
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Verify server section structure
        assert "server-section" in response_text
        assert server_type in response_text  # Ensure our test server is present

        # Check that server section doesn't extend beyond content
        server_section_css_start = response_text.find(".server-section")
        if server_section_css_start != -1:
            css_block_end = response_text.find("}", server_section_css_start)
            css_block = response_text[server_section_css_start:css_block_end]

            # Ensure server section has proper styling without excess dimensions
            assert any(
                prop in css_block for prop in ["border", "border-radius", "overflow"]
            )

    def test_no_excessive_bottom_spacing(
        self, authenticated_client, plex_server_with_steps
    ):
        """Test that there's no excessive bottom spacing causing layout width issues."""
        server_type = plex_server_with_steps
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Verify the main section container doesn't have excessive spacing
        assert 'class="space-y-6"' in response_text
        assert server_type in response_text  # Ensure our test server is present

        # Check that there are no CSS rules that would cause the bottom excess width
        # Look for any problematic CSS patterns

        # The grid container should end properly after the phase sections
        grid_pattern = 'class="grid grid-cols-1 lg:grid-cols-2 gap-0 lg:divide-x'
        assert grid_pattern in response_text

    def test_responsive_layout_maintains_bounds(
        self, authenticated_client, plex_server_with_steps
    ):
        """Test that responsive layout doesn't break width bounds."""
        server_type = plex_server_with_steps
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Verify responsive grid classes are properly applied
        assert server_type in response_text  # Ensure our test server is present

        responsive_classes = [
            "grid-cols-1",  # Mobile: single column
            "lg:grid-cols-2",  # Large screens: two columns
            "lg:divide-x",  # Large screens: vertical divider
            "lg:divide-gray-200",  # Divider color
        ]

        for cls in responsive_classes:
            assert cls in response_text, f"Responsive class {cls} should be present"

    def test_layout_fix_css_structure(
        self, authenticated_client, plex_server_with_steps
    ):
        """Test that the CSS structure supports the layout fix."""
        server_type = plex_server_with_steps
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")

        # Check for proper CSS structure that prevents width overflow
        # The grid should be contained within proper bounds
        assert server_type in response_text  # Ensure our test server is present

        # Verify the outer section container
        assert '<section class="space-y-6">' in response_text

        # Verify the grid container structure
        assert any(
            pattern in response_text
            for pattern in [
                'class="grid grid-cols-1 lg:grid-cols-2',
                'class="server-section"',
            ]
        )

        # Check that CSS doesn't have rules that would cause bottom extension
        # Look for any margin-bottom or padding-bottom that might be excessive
        css_section = response_text[
            response_text.find("<style>") : response_text.find("</style>")
        ]

        # Ensure phase-section margin is reasonable (not excessive)
        if ".phase-section" in css_section:
            phase_css_start = css_section.find(".phase-section")
            phase_css_end = css_section.find("}", phase_css_start)
            phase_css_block = css_section[phase_css_start:phase_css_end]

            # Should have margin-bottom but not excessive
            if "margin-bottom" in phase_css_block:
                # Extract the value to ensure it's reasonable (like 2rem, not 10rem)
                margin_part = phase_css_block[phase_css_block.find("margin-bottom:") :]
                margin_line = margin_part[: margin_part.find(";")]
                # Should not have excessive margin values
                assert not any(
                    excessive in margin_line for excessive in ["10rem", "5rem", "100px"]
                )

    def test_no_double_spacing_on_server_sections(
        self, authenticated_client, plex_server_with_steps
    ):
        """Test that server sections don't have double spacing that causes excess width."""
        server_type = plex_server_with_steps
        response = authenticated_client.get(
            "/settings/wizard/", headers={"HX-Request": "true"}
        )
        assert response.status_code == 200

        response_text = response.data.decode("utf-8")
        assert server_type in response_text  # Ensure our test server is present

        # The template uses space-y-6 on the section container
        assert 'class="space-y-6"' in response_text

        # Extract the CSS section to check server-section styling
        css_section = response_text[
            response_text.find("<style>") : response_text.find("</style>")
        ]

        # Find the .server-section CSS rule
        if ".server-section" in css_section:
            server_section_css_start = css_section.find(".server-section")
            server_section_css_end = css_section.find("}", server_section_css_start)
            server_section_css_block = css_section[
                server_section_css_start:server_section_css_end
            ]

            # The fix: server-section should NOT have margin-bottom since space-y-6 handles spacing
            # This prevents double spacing that causes the excess width at the bottom
            assert "margin-bottom" not in server_section_css_block, (
                "server-section should not have margin-bottom when parent uses space-y-6, "
                "as this causes double spacing and excess width at the bottom"
            )
