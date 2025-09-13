"""
Tests for wizard forms with timing field functionality.
"""

import pytest
from flask import Flask

from app.forms.wizard import SimpleWizardStepForm, WizardStepForm


class TestWizardFormsTiming:
    """Test wizard forms with timing field."""

    @pytest.fixture
    def app_context(self):
        """Create Flask app context for form testing."""
        app = Flask(__name__)
        app.config["SECRET_KEY"] = "test-secret-key"
        app.config["WTF_CSRF_ENABLED"] = False
        
        with app.app_context():
            yield app

    def test_wizard_step_form_has_timing_field(self, app_context):
        """Test that WizardStepForm includes timing field."""
        form = WizardStepForm()
        
        assert hasattr(form, "timing")
        assert form.timing.label.text == "Timing"
        
        # Check choices
        choices = [choice[0] for choice in form.timing.choices]
        assert "before_invite_acceptance" in choices
        assert "after_invite_acceptance" in choices

    def test_wizard_step_form_timing_choices(self, app_context):
        """Test timing field choices and labels."""
        form = WizardStepForm()
        
        expected_choices = [
            ("before_invite_acceptance", "Before Invite Acceptance"),
            ("after_invite_acceptance", "After Invite Acceptance"),
        ]
        
        assert form.timing.choices == expected_choices

    def test_wizard_step_form_timing_default(self, app_context):
        """Test timing field default value."""
        form = WizardStepForm()
        
        # Default should be after_invite_acceptance
        assert form.timing.default == "after_invite_acceptance"

    def test_wizard_step_form_timing_validation_valid(self, app_context):
        """Test timing field validation with valid values."""
        valid_data = {
            "server_type": "plex",
            "timing": "before_invite_acceptance",
            "title": "Test Step",
            "markdown": "# Test Content",
        }
        
        form = WizardStepForm(data=valid_data)
        assert form.validate()
        assert form.timing.data == "before_invite_acceptance"

    def test_wizard_step_form_timing_validation_invalid(self, app_context):
        """Test timing field validation with invalid values."""
        invalid_data = {
            "server_type": "plex",
            "timing": "invalid_timing",
            "title": "Test Step",
            "markdown": "# Test Content",
        }
        
        form = WizardStepForm(data=invalid_data)
        assert not form.validate()
        assert "timing" in form.errors

    def test_wizard_step_form_timing_uses_default(self, app_context):
        """Test that timing field uses default when not provided."""
        data_without_timing = {
            "server_type": "plex",
            "title": "Test Step",
            "markdown": "# Test Content",
        }

        form = WizardStepForm(data=data_without_timing)
        assert form.validate()  # Should validate with default timing
        assert form.timing.data == "after_invite_acceptance"  # Should use default

    def test_simple_wizard_step_form_has_timing_field(self, app_context):
        """Test that SimpleWizardStepForm includes timing field."""
        form = SimpleWizardStepForm()
        
        assert hasattr(form, "timing")
        assert form.timing.label.text == "Timing"

    def test_simple_wizard_step_form_timing_choices(self, app_context):
        """Test SimpleWizardStepForm timing field choices."""
        form = SimpleWizardStepForm()
        
        expected_choices = [
            ("before_invite_acceptance", "Before Invite Acceptance"),
            ("after_invite_acceptance", "After Invite Acceptance"),
        ]
        
        assert form.timing.choices == expected_choices

    def test_simple_wizard_step_form_timing_validation(self, app_context):
        """Test SimpleWizardStepForm timing field validation."""
        valid_data = {
            "timing": "after_invite_acceptance",
            "title": "Simple Step",
            "markdown": "# Simple Content",
        }
        
        form = SimpleWizardStepForm(data=valid_data)
        assert form.validate()
        assert form.timing.data == "after_invite_acceptance"

    def test_wizard_step_form_complete_validation(self, app_context):
        """Test complete form validation with all required fields including timing."""
        complete_data = {
            "server_type": "jellyfin",
            "timing": "before_invite_acceptance",
            "position": "0",
            "title": "Welcome to Jellyfin",
            "markdown": "# Welcome\nPlease read our guidelines before joining.",
            "require_interaction": True,
        }
        
        form = WizardStepForm(data=complete_data)
        assert form.validate()
        
        assert form.server_type.data == "jellyfin"
        assert form.timing.data == "before_invite_acceptance"
        assert form.title.data == "Welcome to Jellyfin"
        assert form.require_interaction.data is True

    def test_wizard_step_form_timing_with_different_server_types(self, app_context):
        """Test timing field works with different server types."""
        server_types = ["plex", "jellyfin", "emby", "audiobookshelf"]
        timings = ["before_invite_acceptance", "after_invite_acceptance"]
        
        for server_type in server_types:
            for timing in timings:
                data = {
                    "server_type": server_type,
                    "timing": timing,
                    "title": f"{server_type.title()} {timing.replace('_', ' ').title()}",
                    "markdown": f"# {server_type.title()} Content",
                }
                
                form = WizardStepForm(data=data)
                assert form.validate(), f"Failed for {server_type} with {timing}"
                assert form.server_type.data == server_type
                assert form.timing.data == timing

    def test_wizard_step_form_backward_compatibility(self, app_context):
        """Test form works when timing is not provided (backward compatibility)."""
        # This simulates old forms that don't include timing
        data_without_timing = {
            "server_type": "plex",
            "title": "Legacy Step",
            "markdown": "# Legacy Content",
        }

        form = WizardStepForm(data=data_without_timing)

        # Form should validate with default timing (backward compatibility)
        assert form.validate()
        assert form.timing.data == "after_invite_acceptance"  # Should use default

        # Explicitly providing timing should also work
        data_with_timing = data_without_timing.copy()
        data_with_timing["timing"] = "before_invite_acceptance"

        form_with_timing = WizardStepForm(data=data_with_timing)
        assert form_with_timing.validate()
        assert form_with_timing.timing.data == "before_invite_acceptance"

    def test_simple_wizard_step_form_minimal_data(self, app_context):
        """Test SimpleWizardStepForm with minimal required data."""
        minimal_data = {
            "timing": "before_invite_acceptance",
            "markdown": "# Minimal Step",
        }
        
        form = SimpleWizardStepForm(data=minimal_data)
        assert form.validate()
        assert form.timing.data == "before_invite_acceptance"
        assert form.markdown.data == "# Minimal Step"
        assert form.title.data is None  # Optional field

    def test_wizard_step_form_timing_field_attributes(self, app_context):
        """Test timing field has correct attributes."""
        form = WizardStepForm()
        
        # Check field type
        from wtforms.fields import SelectField
        assert isinstance(form.timing, SelectField)
        
        # Check validators
        from wtforms.validators import DataRequired
        validator_types = [type(v) for v in form.timing.validators]
        assert DataRequired in validator_types

    def test_form_data_extraction(self, app_context):
        """Test extracting form data including timing field."""
        form_data = {
            "server_type": "emby",
            "timing": "before_invite_acceptance",
            "position": "1",
            "title": "Pre-invite Setup",
            "markdown": "# Setup\nPlease configure your settings.",
            "require_interaction": False,
        }
        
        form = WizardStepForm(data=form_data)
        assert form.validate()
        
        # Test data extraction
        extracted_data = {
            "server_type": form.server_type.data,
            "timing": form.timing.data,
            "position": int(form.position.data or 0),
            "title": form.title.data,
            "markdown": form.markdown.data,
            "require_interaction": form.require_interaction.data,
        }
        
        assert extracted_data["server_type"] == "emby"
        assert extracted_data["timing"] == "before_invite_acceptance"
        assert extracted_data["position"] == 1
        assert extracted_data["title"] == "Pre-invite Setup"
        assert extracted_data["require_interaction"] is False

    def test_form_choices_consistency(self, app_context):
        """Test that timing choices are consistent between forms."""
        wizard_form = WizardStepForm()
        simple_form = SimpleWizardStepForm()
        
        assert wizard_form.timing.choices == simple_form.timing.choices
        
        # Both should have the same timing options
        for choice_value, choice_label in wizard_form.timing.choices:
            assert choice_value in ["before_invite_acceptance", "after_invite_acceptance"]
            assert choice_label in ["Before Invite Acceptance", "After Invite Acceptance"]
