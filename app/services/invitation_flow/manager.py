"""
Simple invitation flow manager that integrates with existing routes.
"""

import logging
from typing import Any

from flask import session, url_for
from sqlalchemy import func

from app.models import Invitation, MediaServer, WizardPhase, WizardStep
from app.services.invites import is_invite_valid

from .results import InvitationResult, ProcessingStatus, ServerResult
from .workflows import WorkflowFactory


class InvitationFlowManager:
    """
    Simple manager that can be used as a drop-in replacement for existing invitation processing.

    Usage:
        manager = InvitationFlowManager()
        result = manager.process_invitation_display(code)
        return result.to_flask_response()
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def process_invitation_display(self, code: str) -> InvitationResult:
        """
        Process invitation display (GET /j/<code>).

        Validates token, stores in session, and redirects to /join.
        """
        try:
            # Validate invitation (reuse existing logic)
            valid, message = is_invite_valid(code)
            if not valid:
                return InvitationResult(
                    status=ProcessingStatus.INVALID_INVITATION,
                    message=message,
                    successful_servers=[],
                    failed_servers=[],
                    template_data={
                        "template_name": "invalid-invite.html",
                        "error": message,
                    },
                )

            # Get invitation and servers
            invitation = Invitation.query.filter(
                func.lower(Invitation.code) == code.lower()
            ).first()

            if not invitation:
                return self._create_error_result("Invitation not found")

            # Store token in session and redirect to clean URL
            return InvitationResult(
                status=ProcessingStatus.SUCCESS,
                message="Invitation found, redirecting to join",
                successful_servers=[],
                failed_servers=[],
                redirect_url=url_for("public.join"),
                session_data={
                    "invite_token": code,
                    "invitation_in_progress": True,
                },
            )

        except Exception as e:
            self.logger.error(f"Error displaying invitation {code}: {e}")
            return self._create_error_result(str(e))

    def process_invitation_submission(
        self, form_data: dict[str, Any]
    ) -> InvitationResult:
        """
        Process invitation form submission (POST).

        Drop-in replacement for existing invitation processing logic.
        """
        try:
            code = form_data.get("code")
            if not code:
                return self._create_error_result("Missing invitation code")

            # Validate invitation
            valid, message = is_invite_valid(code)
            if not valid:
                return self._create_error_result(message)

            # Get invitation and servers
            invitation = Invitation.query.filter(
                func.lower(Invitation.code) == code.lower()
            ).first()

            servers = self._get_invitation_servers(invitation)

            # Process with appropriate workflow
            workflow = WorkflowFactory.create_workflow(servers)
            return workflow.process_submission(invitation, servers, form_data)

        except Exception as e:
            self.logger.error(f"Error processing invitation submission: {e}")
            return self._create_error_result(str(e))

    def _get_invitation_servers(self, invitation: Invitation) -> list[MediaServer]:
        """Get servers associated with invitation (same logic as existing system)."""
        servers = []

        # Check new many-to-many relationship first
        if hasattr(invitation, "servers") and invitation.servers:
            try:
                # Cast to Any to work around type checking issues with SQLAlchemy relationships
                from typing import Any, cast

                servers_iter = cast(Any, invitation.servers)
                servers = list(servers_iter)
            except (TypeError, AttributeError):
                # Fallback if servers is not iterable
                servers = []

        # Fallback to legacy single server relationship
        if not servers and hasattr(invitation, "server") and invitation.server:
            servers = [invitation.server]

        # Final fallback to first available server
        if not servers:
            default_server = MediaServer.query.first()
            if default_server:
                servers = [default_server]

        # Ensure Plex servers are first for mixed workflows
        plex_servers = [s for s in servers if s.server_type == "plex"]
        other_servers = [s for s in servers if s.server_type != "plex"]

        return plex_servers + other_servers

    def process_join_request(self, skip_pre_steps: bool = False) -> InvitationResult:
        """Process /join request - route to appropriate flow."""
        # Check for valid session token
        invite_token = session.get("invite_token")
        if not invite_token:
            return self._create_error_result("No valid invitation token found")

        # Get invitation and servers
        invitation = Invitation.query.filter_by(code=invite_token).first()
        if not invitation:
            return self._create_error_result("Invalid invitation")

        servers = self._get_invitation_servers(invitation)
        if not servers:
            return self._create_error_result(
                "No servers configured for this invitation"
            )

        # Check for pre-invite steps (unless explicitly skipping them)
        if not skip_pre_steps:
            pre_steps = self._get_pre_invite_steps(servers)
            if pre_steps:
                # Store server info in session for wizard
                session["wizard_servers"] = [s.server_type for s in servers]
                return InvitationResult(
                    status=ProcessingStatus.SUCCESS,
                    message="Redirecting to pre-wizard",
                    successful_servers=[
                        ServerResult(server=s, success=True, message="Ready")
                        for s in servers
                    ],
                    failed_servers=[],
                    redirect_url=url_for("public.pre_wizard"),
                    session_data={"invitation_in_progress": True},
                )

        # No pre-steps or skipping pre-steps, use existing workflow to show invite acceptance
        workflow = WorkflowFactory.create_workflow(servers)
        return workflow.show_initial_form(invitation, servers)

    def process_pre_wizard_request(self, step: int | None = None) -> InvitationResult:
        """Process /pre-wizard request."""
        # Validate session
        invite_token = session.get("invite_token")
        if not invite_token or not session.get("invitation_in_progress"):
            return InvitationResult(
                status=ProcessingStatus.FAILURE,
                message="Invalid session",
                successful_servers=[],
                failed_servers=[],
                redirect_url=url_for("public.root"),
                session_data={},
            )

        # Get invitation and servers
        invitation = Invitation.query.filter_by(code=invite_token).first()
        if not invitation:
            return self._create_error_result("Invalid invitation")

        servers = self._get_invitation_servers(invitation)
        pre_steps = self._get_pre_invite_steps(servers)

        if not pre_steps:
            # No pre-steps, redirect to invite acceptance
            return InvitationResult(
                status=ProcessingStatus.SUCCESS,
                message="No pre-steps, redirecting to join acceptance",
                successful_servers=[
                    ServerResult(server=s, success=True, message="Ready")
                    for s in servers
                ],
                failed_servers=[],
                redirect_url=url_for("public.join"),
                session_data={"invitation_in_progress": True},
            )

        # Determine current step
        current_step = step if step is not None else 0
        if current_step >= len(pre_steps):
            # Completed all pre-steps, redirect to invite acceptance
            session["pre_wizard_completed"] = True
            return InvitationResult(
                status=ProcessingStatus.SUCCESS,
                message="Pre-wizard completed",
                successful_servers=[
                    ServerResult(server=s, success=True, message="Ready")
                    for s in servers
                ],
                failed_servers=[],
                redirect_url=url_for("public.join"),
                session_data={
                    "invitation_in_progress": True,
                    "pre_wizard_completed": True,
                },
            )

        # Render current step
        wizard_step = pre_steps[current_step]
        return self._render_wizard_step(
            step=wizard_step,
            current_index=current_step,
            total_steps=len(pre_steps),
            phase="pre",
            servers=servers,
        )

    def _get_pre_invite_steps(self, servers: list[MediaServer]) -> list[WizardStep]:
        """Get pre-invite steps for servers."""
        server_types = [s.server_type for s in servers]

        return (
            WizardStep.query.filter(
                WizardStep.server_type.in_(server_types),
                WizardStep.phase == WizardPhase.PRE,
            )
            .order_by(WizardStep.server_type, WizardStep.position)
            .all()
        )

    def _render_wizard_step(
        self,
        step: WizardStep,
        current_index: int,
        total_steps: int,
        phase: str,
        servers: list[MediaServer],
    ) -> InvitationResult:
        """Render a wizard step using shared rendering utilities."""
        from app.services.wizard_rendering import WizardRenderer

        # Use shared context building logic (DRY compliance)
        context = WizardRenderer.build_wizard_context(servers=servers)

        # Use shared markdown rendering logic (DRY compliance)
        html_content = WizardRenderer.render_wizard_step_content(step, context)

        # Determine interaction gating: prefer DB flag, fallback to disabled
        require_interaction = bool(getattr(step, "require_interaction", False))

        # Build unified navigation URLs targeting the public endpoints
        from flask import url_for

        if phase == "pre":
            next_url = url_for("public.pre_wizard", step=current_index + 1)
            prev_url = (
                url_for("public.pre_wizard", step=current_index - 1)
                if current_index > 0
                else None
            )
            server_type = "pre"
        else:
            next_url = url_for("public.post_wizard", step=current_index + 1)
            prev_url = (
                url_for("public.post_wizard", step=current_index - 1)
                if current_index > 0
                else None
            )
            server_type = "post"

        return InvitationResult(
            status=ProcessingStatus.SUCCESS,
            message="Showing wizard step",
            successful_servers=[
                ServerResult(server=s, success=True, message="Ready") for s in servers
            ],
            failed_servers=[],
            template_data={
                "template_name": "wizard/frame.html",
                # templates/wizard/frame.html includes templates/wizard/steps.html
                # We pass the exact same context keys as the original /wizard route
                "body_html": html_content,
                "idx": current_index,
                "max_idx": total_steps - 1,
                "server_type": server_type,
                "direction": "",
                "require_interaction": require_interaction,
                # Navigation overrides so steps.html targets pre/post-wizard URLs
                "next_url": next_url,
                # Omit prev_url on first step; steps.html hides Prev when idx == 0
                **({"prev_url": prev_url} if prev_url else {}),
            },
            session_data={"invitation_in_progress": True},
        )

    def process_post_wizard_request(self, step: int | None = None) -> InvitationResult:
        """Process /post-wizard request."""
        # Validate session - must have accepted invite
        invite_token = session.get("invite_token")
        invite_accepted = session.get("invite_accepted")

        if not invite_token or not invite_accepted:
            return InvitationResult(
                status=ProcessingStatus.FAILURE,
                message="Invalid session - invite not accepted",
                successful_servers=[],
                failed_servers=[],
                redirect_url=url_for("public.root"),
                session_data={},
            )

        # Get invitation and servers
        invitation = Invitation.query.filter_by(code=invite_token).first()
        if not invitation:
            return self._create_error_result("Invalid invitation")

        servers = self._get_invitation_servers(invitation)
        post_steps = self._get_post_invite_steps(servers)

        if not post_steps:
            # No post-steps, complete the flow
            return self._complete_wizard_flow()

        # Determine current step
        current_step = step if step is not None else 0
        if current_step >= len(post_steps):
            # Completed all post-steps
            return self._complete_wizard_flow()

        # Render current step
        wizard_step = post_steps[current_step]
        return self._render_wizard_step(
            step=wizard_step,
            current_index=current_step,
            total_steps=len(post_steps),
            phase="post",
            servers=servers,
        )

    def _get_post_invite_steps(self, servers: list[MediaServer]) -> list[WizardStep]:
        """Get post-invite steps for servers."""
        server_types = [s.server_type for s in servers]

        return (
            WizardStep.query.filter(
                WizardStep.server_type.in_(server_types),
                WizardStep.phase == WizardPhase.POST,
            )
            .order_by(WizardStep.server_type, WizardStep.position)
            .all()
        )

    def _complete_wizard_flow(self) -> InvitationResult:
        """Complete the wizard flow and clean up session."""
        return InvitationResult(
            status=ProcessingStatus.SUCCESS,
            message="Wizard flow completed",
            successful_servers=[],
            failed_servers=[],
            redirect_url=url_for("public.root"),  # Success page
            session_data={
                "invite_token": None,
                "invitation_in_progress": None,
                "invite_accepted": None,
                "pre_wizard_completed": None,
                "wizard_servers": None,
            },
        )

    def _create_error_result(self, message: str) -> InvitationResult:
        """Create generic error result."""
        return InvitationResult(
            status=ProcessingStatus.FAILURE,
            message=message,
            successful_servers=[],
            failed_servers=[],
            template_data={"template_name": "invalid-invite.html", "error": message},
            session_data={"invitation_in_progress": True},
        )
