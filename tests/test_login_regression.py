"""
Test for login page regression where title displays "None" and JavaScript errors occur.

This test reproduces the bug introduced in commits 83a40b8 and 7626e67 where:
1. Login page title shows "None" instead of proper server name
2. JavaScript error: "can't access property 'addEventListener', passkeyLoginBtn is null"

Following TDD methodology - these tests should fail initially, then pass after fixes.
"""

from unittest.mock import patch

import pytest

from app import create_app
from app.extensions import db
from app.models import AdminAccount, Settings, WebAuthnCredential


@pytest.fixture
def app():
    """Create application for testing."""
    app = create_app()
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture
def admin_user(app):
    """Create admin user for testing."""
    with app.app_context():
        admin = AdminAccount(username="admin")
        admin.set_password("password")
        db.session.add(admin)
        db.session.commit()
        return admin


class TestLoginPageTitleRegression:
    """Test the login page title regression issue."""

    def test_login_page_title_with_none_server_name(self, client, app):
        """Test that login page handles None server_name gracefully."""
        with (
            app.app_context(),
            patch("app.context_processors.inject_server_name") as mock_inject,
        ):
                mock_inject.return_value = {"server_name": None}

                response = client.get("/login")
                assert response.status_code == 200

                html = response.get_data(as_text=True)

                # Should NOT display "None" in the title area
                assert "None" not in html

                # Should have a fallback title
                assert "Wizarr" in html or "Login" in html

    def test_login_page_title_with_empty_server_name(self, client, app):
        """Test that login page handles empty server_name gracefully."""
        with (
            app.app_context(),
            patch("app.context_processors.inject_server_name") as mock_inject,
        ):
                mock_inject.return_value = {"server_name": ""}

                response = client.get("/login")
                assert response.status_code == 200

                html = response.get_data(as_text=True)

                # Should NOT display empty string or "None"
                assert (
                    'class="flex items-center mb-6 text-2xl font-semibold text-gray-900 dark:text-white">'
                    in html
                )
                # Should have some fallback text
                title_section = html[
                    html.find('class="flex items-center mb-6') : html.find(
                        "</a>", html.find('class="flex items-center mb-6')
                    )
                ]
                assert title_section.strip() != ""

    def test_login_page_title_with_valid_server_name(self, client, app):
        """Test that login page displays valid server_name correctly."""
        with app.app_context():
            # Create a server_name setting
            setting = Settings(key="server_name", value="My Media Server")
            db.session.add(setting)
            db.session.commit()

            response = client.get("/login")
            assert response.status_code == 200

            html = response.get_data(as_text=True)

            # Should display the server name
            assert "My Media Server" in html

    def test_login_page_title_with_database_error(self, client, app):
        """Test that login page handles database errors gracefully."""
        with app.app_context():
            # Create admin setting to bypass onboarding
            admin_setting = Settings(key="admin_username", value="admin")
            db.session.add(admin_setting)
            db.session.commit()

            # Test that the context processor handles database errors gracefully
            # by testing the function directly
            from app.context_processors import inject_server_name

            # Mock the Settings query to raise an exception
            with patch("app.context_processors.Settings") as mock_settings:
                mock_settings.query.filter_by.return_value.first.side_effect = (
                    Exception("Database error")
                )

                # This should not crash and should return a fallback
                result = inject_server_name()
                assert result == {"server_name": "Wizarr"}

                # The login page should still work
                response = client.get("/login")
                assert response.status_code == 200


class TestLoginPageJavaScriptRegression:
    """Test the JavaScript error regression issue."""

    def test_login_page_javascript_without_passkeys(self, client, app):
        """Test that JavaScript doesn't error when no passkeys exist."""
        with app.app_context():
            # Create admin setting to bypass onboarding
            admin_setting = Settings(key="admin_username", value="admin")
            db.session.add(admin_setting)
            db.session.commit()

            response = client.get("/login")
            assert response.status_code == 200

            html = response.get_data(as_text=True)

            # Should contain the JavaScript
            assert "passkeyLoginBtn" in html

            # Should have proper null checking for passkeyLoginBtn
            # The JavaScript should check if the element exists before adding event listener
            assert "addEventListener" in html

            # Should not have passkey button when no passkeys exist
            assert 'id="passkey-login"' not in html

    def test_login_page_javascript_with_passkeys(self, client, app):
        """Test that JavaScript works correctly when passkeys exist."""
        with app.app_context():
            # Create admin setting to bypass onboarding
            admin_setting = Settings(key="admin_username", value="admin")
            db.session.add(admin_setting)

            # Create admin user
            admin = AdminAccount(username="admin")
            admin.set_password("password")
            db.session.add(admin)
            db.session.flush()  # Flush to get the ID

            # Create a passkey credential
            credential = WebAuthnCredential(
                admin_account_id=admin.id,
                credential_id=b"test_credential_id",
                public_key=b"test_public_key",
                sign_count=0,
                name="Test Passkey",
            )
            db.session.add(credential)
            db.session.commit()

            response = client.get("/login")
            assert response.status_code == 200

            html = response.get_data(as_text=True)

            # Should contain the passkey button when passkeys exist
            assert 'id="passkey-login"' in html
            assert "Sign in with Passkey" in html

            # Should contain the JavaScript
            assert "passkeyLoginBtn" in html
            assert "addEventListener" in html

    def test_login_page_javascript_element_checking_pattern(self, client, app):
        """Test that JavaScript follows proper element existence checking pattern."""
        with app.app_context():
            response = client.get("/login")
            assert response.status_code == 200

            html = response.get_data(as_text=True)

            # Should check if passkeyLoginBtn exists before using it
            # This is the pattern we need to implement to fix the bug
            import re

            script_matches = re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL)

            # Find the script that contains passkeyLoginBtn
            passkey_script = None
            for script in script_matches:
                if "passkeyLoginBtn" in script:
                    passkey_script = script
                    break

            assert passkey_script is not None, "Script with passkeyLoginBtn not found"

            # The fix should include checking if the element exists
            # This test will fail initially and pass after the fix
            assert (
                "if (passkeyLoginBtn)" in passkey_script
                or "passkeyLoginBtn &&" in passkey_script
            )

    def test_login_page_handles_missing_elements_gracefully(self, client, app):
        """Test that login page JavaScript handles missing DOM elements gracefully."""
        with app.app_context():
            response = client.get("/login")
            assert response.status_code == 200

            html = response.get_data(as_text=True)

            # Should have defensive programming for all elements
            import re

            script_matches = re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL)

            # Find the script that contains backToLoginBtn
            back_to_login_script = None
            for script in script_matches:
                if "backToLoginBtn" in script:
                    back_to_login_script = script
                    break

            assert back_to_login_script is not None, (
                "Script with backToLoginBtn not found"
            )

            # Should check for backToLoginBtn existence
            assert (
                "if (backToLoginBtn)" in back_to_login_script
                or "backToLoginBtn &&" in back_to_login_script
            )


class TestLoginPageIntegration:
    """Integration tests for the complete login page functionality."""

    def test_login_page_renders_without_errors(self, client, app):
        """Test that login page renders completely without any errors."""
        with app.app_context():
            response = client.get("/login")
            assert response.status_code == 200

            html = response.get_data(as_text=True)

            # Basic structure should be present
            assert "<html>" in html or "<!DOCTYPE html>" in html
            assert "<title>" in html
            assert "Login" in html
            assert "<script>" in html
            assert "</script>" in html

    def test_login_page_title_in_browser_tab(self, client, app):
        """Test that browser tab title is correct."""
        with app.app_context():
            # Create admin setting to bypass onboarding
            admin_setting = Settings(key="admin_username", value="admin")
            db.session.add(admin_setting)

            # Set up a server name
            setting = Settings(key="server_name", value="Test Server")
            db.session.add(setting)
            db.session.commit()

            response = client.get("/login")
            assert response.status_code == 200

            html = response.get_data(as_text=True)

            # Browser tab title should be "Login - Test Server"
            # Note: The title might have whitespace, so we check for the content
            assert "Login" in html and "Test Server" in html
            title_match = html.find("<title>") != -1 and html.find("</title>") != -1
            assert title_match

    def test_login_page_fallback_title_in_browser_tab(self, client, app):
        """Test that browser tab title has proper fallback."""
        with app.app_context():
            # Create admin setting to bypass onboarding
            admin_setting = Settings(key="admin_username", value="admin")
            db.session.add(admin_setting)
            db.session.commit()

            # Simulate no server name setting (should fallback to Wizarr)
            response = client.get("/login")
            assert response.status_code == 200

            html = response.get_data(as_text=True)

            # Browser tab title should have fallback
            assert "Login" in html and "Wizarr" in html
            # Should NOT be "Login - None"
            assert "None" not in html
