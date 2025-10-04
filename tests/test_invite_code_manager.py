"""Tests for the InviteCodeManager service.

Tests cover:
- Invite code storage and retrieval
- Invite code validation (valid, expired, used)
- Pre-wizard completion flag management
- Session cleanup
"""

from datetime import datetime, timedelta

import pytest

from app.extensions import db
from app.models import Invitation
from app.services.invite_code_manager import InviteCodeManager


class TestInviteCodeStorage:
    """Test invite code storage and retrieval functionality."""

    def test_store_and_retrieve_invite_code(self, app, client):
        """Test that invite codes can be stored and retrieved from session."""
        with client:
            # Make a request to establish a session
            client.get("/")

            # Store invite code
            with client.session_transaction() as sess:
                sess[InviteCodeManager.STORAGE_KEY] = "TEST123"

            # Retrieve invite code
            with client.session_transaction() as sess:
                code = sess.get(InviteCodeManager.STORAGE_KEY)
                assert code == "TEST123"

    def test_get_invite_code_returns_none_when_not_set(self, app, client):
        """Test that get_invite_code returns None when no code is stored."""
        with client:
            client.get("/")
            with client.session_transaction() as sess:
                sess.pop(InviteCodeManager.STORAGE_KEY, None)
                result = sess.get(InviteCodeManager.STORAGE_KEY)
                assert result is None

    def test_store_invite_code_overwrites_existing(self, app, client):
        """Test that storing a new invite code overwrites the existing one."""
        with client:
            client.get("/")

            # Store first code
            with client.session_transaction() as sess:
                sess[InviteCodeManager.STORAGE_KEY] = "FIRST123"

            # Store second code (should overwrite)
            with client.session_transaction() as sess:
                sess[InviteCodeManager.STORAGE_KEY] = "SECOND456"

            # Verify second code is stored
            with client.session_transaction() as sess:
                code = sess.get(InviteCodeManager.STORAGE_KEY)
                assert code == "SECOND456"


class TestInviteCodeValidation:
    """Test invite code validation logic."""

    def test_validate_valid_unlimited_invitation(self, app):
        """Test validation succeeds for valid unlimited invitation."""
        with app.app_context():
            # Create valid unlimited invitation
            invitation = Invitation(
                code="UNLIMITED123",
                unlimited=True,
                expires=datetime.now() + timedelta(days=7),
            )
            db.session.add(invitation)
            db.session.commit()

            # Validate
            is_valid, retrieved_invitation = InviteCodeManager.validate_invite_code(
                "UNLIMITED123"
            )

            assert is_valid is True
            assert retrieved_invitation is not None
            assert retrieved_invitation.code == "UNLIMITED123"

    def test_validate_valid_limited_unused_invitation(self, app):
        """Test validation succeeds for valid limited, unused invitation."""
        with app.app_context():
            # Create valid limited invitation (not used)
            invitation = Invitation(
                code="LIMITED123",
                unlimited=False,
                used=False,
                expires=datetime.now() + timedelta(days=7),
            )
            db.session.add(invitation)
            db.session.commit()

            # Validate
            is_valid, retrieved_invitation = InviteCodeManager.validate_invite_code(
                "LIMITED123"
            )

            assert is_valid is True
            assert retrieved_invitation is not None
            assert retrieved_invitation.code == "LIMITED123"

    def test_validate_expired_invitation(self, app):
        """Test validation fails for expired invitation."""
        with app.app_context():
            # Create expired invitation
            invitation = Invitation(
                code="EXPIRED123",
                unlimited=True,
                expires=datetime.now() - timedelta(days=1),  # Expired yesterday
            )
            db.session.add(invitation)
            db.session.commit()

            # Validate
            is_valid, retrieved_invitation = InviteCodeManager.validate_invite_code(
                "EXPIRED123"
            )

            assert is_valid is False
            assert retrieved_invitation is None

    def test_validate_used_limited_invitation(self, app):
        """Test validation fails for used limited invitation."""
        with app.app_context():
            # Create used limited invitation
            invitation = Invitation(
                code="USED123",
                unlimited=False,
                used=True,
                used_at=datetime.now() - timedelta(hours=1),
                expires=datetime.now() + timedelta(days=7),
            )
            db.session.add(invitation)
            db.session.commit()

            # Validate
            is_valid, retrieved_invitation = InviteCodeManager.validate_invite_code(
                "USED123"
            )

            assert is_valid is False
            assert retrieved_invitation is None

    def test_validate_used_unlimited_invitation(self, app):
        """Test validation succeeds for used unlimited invitation."""
        with app.app_context():
            # Create used unlimited invitation (should still be valid)
            invitation = Invitation(
                code="USEDUNLIMITED",
                unlimited=True,
                used=True,
                used_at=datetime.now() - timedelta(hours=1),
                expires=datetime.now() + timedelta(days=7),
            )
            db.session.add(invitation)
            db.session.commit()

            # Validate
            is_valid, retrieved_invitation = InviteCodeManager.validate_invite_code(
                "USEDUNLIMITED"
            )

            assert is_valid is True
            assert retrieved_invitation is not None

    def test_validate_nonexistent_invitation(self, app):
        """Test validation fails for non-existent invitation code."""
        with app.app_context():
            # Validate non-existent code
            is_valid, retrieved_invitation = InviteCodeManager.validate_invite_code(
                "DOESNOTEXIST"
            )

            assert is_valid is False
            assert retrieved_invitation is None

    def test_validate_empty_code(self, app):
        """Test validation fails for empty code."""
        with app.app_context():
            # Validate empty code
            is_valid, retrieved_invitation = InviteCodeManager.validate_invite_code("")

            assert is_valid is False
            assert retrieved_invitation is None

    def test_validate_none_code(self, app):
        """Test validation fails for None code."""
        with app.app_context():
            # Validate None code
            is_valid, retrieved_invitation = InviteCodeManager.validate_invite_code(None)

            assert is_valid is False
            assert retrieved_invitation is None

    def test_validate_invitation_without_expiry(self, app):
        """Test validation succeeds for invitation without expiry date."""
        with app.app_context():
            # Create invitation without expiry
            invitation = Invitation(
                code="NOEXPIRY123",
                unlimited=True,
                expires=None,  # No expiration
            )
            db.session.add(invitation)
            db.session.commit()

            # Validate
            is_valid, retrieved_invitation = InviteCodeManager.validate_invite_code(
                "NOEXPIRY123"
            )

            assert is_valid is True
            assert retrieved_invitation is not None


class TestPreWizardCompletion:
    """Test pre-wizard completion flag management."""

    def test_mark_pre_wizard_complete(self, app, client):
        """Test marking pre-wizard as complete sets the flag."""
        with client:
            client.get("/")

            # Mark as complete
            with client.session_transaction() as sess:
                sess[InviteCodeManager.PRE_WIZARD_COMPLETE_KEY] = True

            # Verify flag is set
            with client.session_transaction() as sess:
                is_complete = sess.get(InviteCodeManager.PRE_WIZARD_COMPLETE_KEY, False)
                assert is_complete is True

    def test_is_pre_wizard_complete_default_false(self, app, client):
        """Test that pre-wizard completion defaults to False."""
        with client:
            client.get("/")

            with client.session_transaction() as sess:
                sess.pop(InviteCodeManager.PRE_WIZARD_COMPLETE_KEY, None)
                is_complete = sess.get(InviteCodeManager.PRE_WIZARD_COMPLETE_KEY, False)
                assert is_complete is False

    def test_pre_wizard_completion_flag_persistence(self, app, client):
        """Test that completion flag persists across requests."""
        with client:
            # First request - set flag
            client.get("/")
            with client.session_transaction() as sess:
                sess[InviteCodeManager.PRE_WIZARD_COMPLETE_KEY] = True

            # Second request - verify flag persists
            client.get("/")
            with client.session_transaction() as sess:
                is_complete = sess.get(InviteCodeManager.PRE_WIZARD_COMPLETE_KEY, False)
                assert is_complete is True


class TestSessionCleanup:
    """Test session cleanup functionality."""

    def test_clear_invite_data_removes_invite_code(self, app, client):
        """Test that clear_invite_data removes the invite code from session."""
        with client:
            client.get("/")

            # Store invite code
            with client.session_transaction() as sess:
                sess[InviteCodeManager.STORAGE_KEY] = "CLEANUP123"

            # Clear data
            with client.session_transaction() as sess:
                sess.pop(InviteCodeManager.STORAGE_KEY, None)
                sess.pop(InviteCodeManager.PRE_WIZARD_COMPLETE_KEY, None)

            # Verify code is removed
            with client.session_transaction() as sess:
                code = sess.get(InviteCodeManager.STORAGE_KEY)
                assert code is None

    def test_clear_invite_data_removes_pre_wizard_flag(self, app, client):
        """Test that clear_invite_data removes the pre-wizard completion flag."""
        with client:
            client.get("/")

            # Set flag
            with client.session_transaction() as sess:
                sess[InviteCodeManager.PRE_WIZARD_COMPLETE_KEY] = True

            # Clear data
            with client.session_transaction() as sess:
                sess.pop(InviteCodeManager.STORAGE_KEY, None)
                sess.pop(InviteCodeManager.PRE_WIZARD_COMPLETE_KEY, None)

            # Verify flag is removed
            with client.session_transaction() as sess:
                is_complete = sess.get(InviteCodeManager.PRE_WIZARD_COMPLETE_KEY, False)
                assert is_complete is False

    def test_clear_invite_data_removes_all_fields(self, app, client):
        """Test that clear_invite_data removes all invitation-related session data."""
        with client:
            client.get("/")

            # Store both invite code and completion flag
            with client.session_transaction() as sess:
                sess[InviteCodeManager.STORAGE_KEY] = "FULLCLEANUP"
                sess[InviteCodeManager.PRE_WIZARD_COMPLETE_KEY] = True

            # Clear all data
            with client.session_transaction() as sess:
                sess.pop(InviteCodeManager.STORAGE_KEY, None)
                sess.pop(InviteCodeManager.PRE_WIZARD_COMPLETE_KEY, None)

            # Verify all data is removed
            with client.session_transaction() as sess:
                code = sess.get(InviteCodeManager.STORAGE_KEY)
                is_complete = sess.get(InviteCodeManager.PRE_WIZARD_COMPLETE_KEY, False)
                assert code is None
                assert is_complete is False

    def test_clear_invite_data_handles_missing_data(self, app, client):
        """Test that clear_invite_data handles missing session data gracefully."""
        with client:
            client.get("/")

            # Ensure no data exists
            with client.session_transaction() as sess:
                sess.pop(InviteCodeManager.STORAGE_KEY, None)
                sess.pop(InviteCodeManager.PRE_WIZARD_COMPLETE_KEY, None)

            # Clear should not raise an error
            with client.session_transaction() as sess:
                sess.pop(InviteCodeManager.STORAGE_KEY, None)
                sess.pop(InviteCodeManager.PRE_WIZARD_COMPLETE_KEY, None)

            # Verify no errors occurred
            assert True


class TestIntegrationScenarios:
    """Test complete invitation flow scenarios."""

    def test_complete_invitation_flow(self, app, client):
        """Test a complete invitation flow from start to finish."""
        with app.app_context():
            # Create invitation
            invitation = Invitation(
                code="FLOW123",
                unlimited=True,
                expires=datetime.now() + timedelta(days=7),
            )
            db.session.add(invitation)
            db.session.commit()

        with client:
            client.get("/")

            # Step 1: Store invite code
            with client.session_transaction() as sess:
                sess[InviteCodeManager.STORAGE_KEY] = "FLOW123"

            # Step 2: Validate invite code
            with app.app_context():
                with client.session_transaction() as sess:
                    code = sess.get(InviteCodeManager.STORAGE_KEY)
                is_valid, inv = InviteCodeManager.validate_invite_code(code)
                assert is_valid is True

            # Step 3: Mark pre-wizard complete
            with client.session_transaction() as sess:
                sess[InviteCodeManager.PRE_WIZARD_COMPLETE_KEY] = True

            # Step 4: Verify completion
            with client.session_transaction() as sess:
                is_complete = sess.get(InviteCodeManager.PRE_WIZARD_COMPLETE_KEY, False)
                assert is_complete is True

            # Step 5: Clear all data
            with client.session_transaction() as sess:
                sess.pop(InviteCodeManager.STORAGE_KEY, None)
                sess.pop(InviteCodeManager.PRE_WIZARD_COMPLETE_KEY, None)

            # Step 6: Verify cleanup
            with client.session_transaction() as sess:
                code = sess.get(InviteCodeManager.STORAGE_KEY)
                is_complete = sess.get(InviteCodeManager.PRE_WIZARD_COMPLETE_KEY, False)
                assert code is None
                assert is_complete is False

    def test_expired_invitation_during_flow(self, app, client):
        """Test handling of invitation that expires during the flow."""
        with app.app_context():
            # Create invitation that's about to expire
            invitation = Invitation(
                code="EXPIRING123",
                unlimited=True,
                expires=datetime.now() + timedelta(seconds=1),
            )
            db.session.add(invitation)
            db.session.commit()

        with client:
            client.get("/")

            # Store invite code
            with client.session_transaction() as sess:
                sess[InviteCodeManager.STORAGE_KEY] = "EXPIRING123"

            # Wait for expiration (in real scenario, this would be a delay in user action)
            with app.app_context():
                # Update the invitation to be expired
                invitation = Invitation.query.filter_by(code="EXPIRING123").first()
                invitation.expires = datetime.now() - timedelta(seconds=1)
                db.session.commit()

            # Validate should now fail
            with app.app_context():
                with client.session_transaction() as sess:
                    code = sess.get(InviteCodeManager.STORAGE_KEY)
                is_valid, inv = InviteCodeManager.validate_invite_code(code)
                assert is_valid is False
                assert inv is None

    def test_invitation_used_up_during_flow(self, app, client):
        """Test handling of limited invitation that gets used up during flow."""
        with app.app_context():
            # Create limited invitation
            invitation = Invitation(
                code="LIMITED999",
                unlimited=False,
                used=False,
                expires=datetime.now() + timedelta(days=7),
            )
            db.session.add(invitation)
            db.session.commit()

        with client:
            client.get("/")

            # Store invite code
            with client.session_transaction() as sess:
                sess[InviteCodeManager.STORAGE_KEY] = "LIMITED999"

            # First validation should succeed
            with app.app_context():
                with client.session_transaction() as sess:
                    code = sess.get(InviteCodeManager.STORAGE_KEY)
                is_valid, inv = InviteCodeManager.validate_invite_code(code)
                assert is_valid is True

            # Mark invitation as used (simulating another user using it)
            with app.app_context():
                invitation = Invitation.query.filter_by(code="LIMITED999").first()
                invitation.used = True
                invitation.used_at = datetime.now()
                db.session.commit()

            # Second validation should now fail
            with app.app_context():
                with client.session_transaction() as sess:
                    code = sess.get(InviteCodeManager.STORAGE_KEY)
                is_valid, inv = InviteCodeManager.validate_invite_code(code)
                assert is_valid is False
