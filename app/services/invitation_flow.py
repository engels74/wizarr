"""Invitation flow manager for pre/post wizard system.

This service manages the complete invitation flow including:
- Token validation and session management
- Pre-invite wizard steps
- Invite acceptance
- Post-invite wizard steps
"""

from dataclasses import dataclass

from flask import redirect, render_template, session, url_for

from app.extensions import db
from app.models import Invitation, MediaServer, WizardPhase, WizardStep
from app.services.invites import is_invite_valid


@dataclass
class FlowResult:
    """Result of an invitation flow operation."""

    success: bool
    redirect_url: str | None = None
    template: str | None = None
    context: dict | None = None
    error_message: str | None = None

    def to_flask_response(self):
        """Convert to Flask response."""
        if self.redirect_url:
            return redirect(self.redirect_url)
        if self.template:
            return render_template(self.template, **(self.context or {}))
        # Default fallback
        return render_template(
            "invalid-invite.html", error=self.error_message or "Unknown error"
        )


class InvitationFlowManager:
    """Manages the complete invitation flow with pre/post wizard support."""

    def process_invitation_display(self, code: str) -> FlowResult:
        """Process initial invitation display (/j/<token>).

        Validates token, stores in session, and redirects to /join.
        """
        # Validate invitation
        invitation = Invitation.query.filter(
            db.func.lower(Invitation.code) == code.lower()
        ).first()

        if not invitation:
            return FlowResult(
                success=False,
                template="invalid-invite.html",
                context={"error": "Invitation not found"},
            )

        valid, error_msg = is_invite_valid(code)
        if not valid:
            return FlowResult(
                success=False,
                template="invalid-invite.html",
                context={"error": error_msg},
            )

        # Store token in session and redirect to clean URL
        session["invite_token"] = code
        session["invitation_in_progress"] = True

        return FlowResult(success=True, redirect_url=url_for("public.join"))

    def process_join_request(self) -> FlowResult:
        """Process /join request - route to appropriate flow."""
        # Check for valid session token
        invite_token = session.get("invite_token")
        if not invite_token:
            return FlowResult(
                success=False,
                template="invalid-invite.html",
                context={"error": "No valid invitation token found"},
            )

        # Get invitation and servers
        invitation = Invitation.query.filter_by(code=invite_token).first()
        if not invitation:
            return FlowResult(
                success=False,
                template="invalid-invite.html",
                context={"error": "Invalid invitation"},
            )

        # Determine applicable servers
        servers = self._get_invitation_servers(invitation)
        if not servers:
            return FlowResult(
                success=False,
                template="invalid-invite.html",
                context={"error": "No servers configured for this invitation"},
            )

        # Check for pre-invite steps
        pre_steps = self._get_pre_invite_steps(servers)
        if pre_steps:
            # Store server info in session for wizard
            session["wizard_servers"] = [s.server_type for s in servers]
            return FlowResult(success=True, redirect_url=url_for("public.pre_wizard"))

        # No pre-steps, go directly to invite acceptance
        return self._render_invite_acceptance(invitation, servers)

    def process_pre_wizard_request(self, step: int | None = None) -> FlowResult:
        """Process /pre-wizard request."""
        # Validate session
        invite_token = session.get("invite_token")
        if not invite_token or not session.get("invitation_in_progress"):
            return FlowResult(success=False, redirect_url=url_for("public.root"))

        # Get invitation and servers
        invitation = Invitation.query.filter_by(code=invite_token).first()
        if not invitation:
            return FlowResult(
                success=False,
                template="invalid-invite.html",
                context={"error": "Invalid invitation"},
            )

        servers = self._get_invitation_servers(invitation)
        pre_steps = self._get_pre_invite_steps(servers)

        if not pre_steps:
            # No pre-steps, redirect to invite acceptance
            return self._redirect_to_invite_acceptance()

        # Determine current step
        current_step = step if step is not None else 0
        if current_step >= len(pre_steps):
            # Completed all pre-steps, redirect to invite acceptance
            session["pre_wizard_completed"] = True
            return self._redirect_to_invite_acceptance()

        # Render current step
        wizard_step = pre_steps[current_step]
        return self._render_wizard_step(
            step=wizard_step,
            current_index=current_step,
            total_steps=len(pre_steps),
            phase="pre",
            servers=servers,
        )

    def process_post_wizard_request(self, step: int | None = None) -> FlowResult:
        """Process /post-wizard request."""
        # Validate session - must have accepted invite
        invite_token = session.get("invite_token")
        invite_accepted = session.get("invite_accepted")

        if not invite_token or not invite_accepted:
            return FlowResult(success=False, redirect_url=url_for("public.root"))

        # Get invitation and servers
        invitation = Invitation.query.filter_by(code=invite_token).first()
        if not invitation:
            return FlowResult(
                success=False,
                template="invalid-invite.html",
                context={"error": "Invalid invitation"},
            )

        servers = self._get_invitation_servers(invitation)
        post_steps = self._get_post_invite_steps(servers)

        if not post_steps:
            # No post-steps, redirect to success
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

    def process_invitation_submission(self, form_data: dict) -> FlowResult:
        """Process invitation form submission (OAuth callback, etc.)."""
        # This handles the actual invite acceptance
        # Implementation depends on existing invite acceptance logic
        # For now, just mark as accepted and redirect to post-wizard

        session["invite_accepted"] = True

        # Check if there are post-invite steps
        invite_token = session.get("invite_token")
        if invite_token:
            invitation = Invitation.query.filter_by(code=invite_token).first()
            if invitation:
                servers = self._get_invitation_servers(invitation)
                post_steps = self._get_post_invite_steps(servers)
                if post_steps:
                    return FlowResult(
                        success=True, redirect_url=url_for("public.post_wizard")
                    )

        # No post-steps, complete flow
        return self._complete_wizard_flow()

    def _get_invitation_servers(self, invitation: Invitation) -> list[MediaServer]:
        """Get servers associated with an invitation."""
        servers: list[MediaServer] = []

        # Check new many-to-many relationship first
        if hasattr(invitation, "servers") and invitation.servers:
            try:
                # Type-safe access to SQLAlchemy relationship
                from typing import Any, cast

                servers_relation = invitation.servers
                # Cast to Any to work around SQLAlchemy type issues
                servers = list(cast(Any, servers_relation)) if servers_relation else []
            except (TypeError, AttributeError, ValueError):
                # Fallback if servers is not iterable
                servers = []

        # Fallback to legacy single server relationship
        if not servers and hasattr(invitation, "server") and invitation.server:
            from typing import cast

            # Type cast: ensure invitation.server is treated as MediaServer
            servers = [cast(MediaServer, invitation.server)]

        # Final fallback to first available server
        if not servers:
            default_server = MediaServer.query.first()
            if default_server:
                servers = [default_server]

        return servers

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

    def _render_invite_acceptance(
        self, invitation: Invitation, servers: list[MediaServer]
    ) -> FlowResult:
        """Render the invite acceptance page."""
        # Use existing invite acceptance template logic
        # This is a placeholder - actual implementation depends on current templates

        server_name = servers[0].name if servers else "Media Server"

        return FlowResult(
            success=True,
            template="user-plex-login.html",  # or appropriate template
            context={
                "code": invitation.code,
                "server_name": server_name,
                "servers": servers,
            },
        )

    def _redirect_to_invite_acceptance(self) -> FlowResult:
        """Redirect to invite acceptance flow."""
        return FlowResult(success=True, redirect_url=url_for("public.join"))

    def _render_wizard_step(
        self,
        step: WizardStep,
        current_index: int,
        total_steps: int,
        phase: str,
        servers: list[MediaServer],
    ) -> FlowResult:
        """Render a wizard step."""
        import markdown
        from flask import render_template_string

        # Prepare context for markdown rendering
        context = self._get_wizard_context(servers)

        # Render markdown with context
        try:
            rendered_content = render_template_string(step.markdown, **context)
            html_content = markdown.markdown(
                rendered_content, extensions=["fenced_code", "tables", "attr_list"]
            )
        except Exception:
            html_content = step.markdown  # Fallback to raw markdown

        return FlowResult(
            success=True,
            template="wizard/pre_post_step.html",  # New template for pre/post steps
            context={
                "step": step,
                "body_html": html_content,
                "current_index": current_index,
                "total_steps": total_steps,
                "phase": phase,
                "servers": servers,
            },
        )

    def _get_wizard_context(self, servers: list[MediaServer]) -> dict:
        """Get context variables for wizard step rendering."""
        from app.models import Settings

        # Load settings for template variables
        settings = {s.key: s.value for s in Settings.query.all()}

        # Add server-specific variables
        if servers:
            server = servers[0]  # Use first server for context
            settings.update(
                {
                    "server_type": server.server_type,
                    "server_url": server.external_url or server.url,
                    "external_url": server.external_url,
                    "server_name": getattr(server, "name", ""),
                }
            )

        return {"settings": settings}

    def _complete_wizard_flow(self) -> FlowResult:
        """Complete the wizard flow and clean up session."""
        # Clear session variables
        session.pop("invite_token", None)
        session.pop("invitation_in_progress", None)
        session.pop("invite_accepted", None)
        session.pop("pre_wizard_completed", None)
        session.pop("wizard_servers", None)

        return FlowResult(
            success=True,
            redirect_url=url_for("public.root"),  # Success page
        )
