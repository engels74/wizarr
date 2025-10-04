"""Invite code management service for pre-wizard and post-wizard flows.

This service manages invite code persistence and validation across the invitation
flow using Flask session storage for security.
"""

from datetime import datetime
from typing import Optional

from flask import session

from app.models import Invitation


class InviteCodeManager:
    """Manages invite code persistence and validation across the invitation flow.

    Uses Flask session (server-side) for secure storage, preventing client-side
    tampering and ensuring invite codes cannot be bypassed.
    """

    STORAGE_KEY = "wizarr_invite_code"
    PRE_WIZARD_COMPLETE_KEY = "wizarr_pre_wizard_complete"

    @staticmethod
    def store_invite_code(code: str) -> None:
        """Store invite code in session for server-side validation.

        Args:
            code: The invitation code to store
        """
        session[InviteCodeManager.STORAGE_KEY] = code

    @staticmethod
    def get_invite_code() -> Optional[str]:
        """Retrieve stored invite code from session.

        Returns:
            The stored invite code, or None if not found
        """
        return session.get(InviteCodeManager.STORAGE_KEY)

    @staticmethod
    def validate_invite_code(code: str) -> tuple[bool, Optional[Invitation]]:
        """Validate invite code and return invitation if valid.

        Checks:
        - Invite code exists in database
        - Invitation has not expired
        - Invitation has not been fully used (if not unlimited)

        Args:
            code: The invitation code to validate

        Returns:
            Tuple of (is_valid, invitation_object)
            - is_valid: True if the invitation is valid and can be used
            - invitation_object: The Invitation model instance, or None if invalid
        """
        if not code:
            return False, None

        invitation = Invitation.query.filter_by(code=code).first()
        if not invitation:
            return False, None

        # Check if invitation has expired
        # Note: Using naive datetime (no timezone) to match SQLite storage
        # This is consistent with the rest of the codebase
        now = datetime.now()
        if invitation.expires and invitation.expires < now:
            return False, None

        # Check if invitation has been used (non-unlimited invitations only)
        if not invitation.unlimited and invitation.used:
            return False, None

        return True, invitation

    @staticmethod
    def mark_pre_wizard_complete() -> None:
        """Mark pre-wizard steps as completed.

        Sets a flag in the session indicating that the user has successfully
        completed all pre-invite wizard steps and can proceed to the join page.
        """
        session[InviteCodeManager.PRE_WIZARD_COMPLETE_KEY] = True

    @staticmethod
    def is_pre_wizard_complete() -> bool:
        """Check if pre-wizard steps have been completed.

        Returns:
            True if the user has completed pre-wizard steps, False otherwise
        """
        return session.get(InviteCodeManager.PRE_WIZARD_COMPLETE_KEY, False)

    @staticmethod
    def clear_invite_data() -> None:
        """Clear all invitation-related session data.

        Should be called when:
        - User completes the entire invitation flow
        - Invitation becomes invalid or expires
        - User needs to start over with a new invitation
        """
        session.pop(InviteCodeManager.STORAGE_KEY, None)
        session.pop(InviteCodeManager.PRE_WIZARD_COMPLETE_KEY, None)
