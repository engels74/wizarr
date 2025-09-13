"""
Shared wizard rendering utilities for DRY compliance.

This module provides common rendering logic used by both the actual wizard flow
and the preview functionality to ensure consistency and avoid code duplication.
"""

import markdown
from flask import render_template_string

from app.models import MediaServer, Settings, WizardStep


class WizardRenderer:
    """Shared wizard rendering logic for actual wizard and preview modes."""

    @staticmethod
    def render_wizard_step_content(step: WizardStep, context: dict) -> str:
        """
        Render wizard step markdown content with context variables.

        Uses the same rendering logic as the actual wizard flow.
        """
        try:
            # Include step title if it exists
            content_with_title = step.markdown
            if step.title:
                content_with_title = f"# {step.title}\n\n{step.markdown}"

            # Render Jinja2 template variables in markdown
            rendered_markdown = render_template_string(content_with_title, **context)

            # Convert markdown to HTML with same extensions as real wizard
            return markdown.markdown(
                rendered_markdown, extensions=["fenced_code", "tables", "attr_list"]
            )

        except Exception:
            # Fallback to raw markdown on error (same as real wizard)
            return step.markdown

    @staticmethod
    def build_wizard_context(
        servers: list[MediaServer] | None = None, server_type: str | None = None
    ) -> dict:
        """
        Build context variables for wizard step rendering.

        Uses the same context building logic as InvitationFlowManager.
        """
        # Load settings for template variables
        settings_dict = {s.key: s.value for s in Settings.query.all()}

        # Add server-specific variables
        if servers and len(servers) > 0:
            server = servers[0]  # Use first server for context
            settings_dict.update(
                {
                    "server_type": server.server_type,
                    "server_url": getattr(server, "external_url", None)
                    or server.url
                    or "",
                    "external_url": getattr(server, "external_url", None) or "",
                    "server_name": getattr(server, "name", "")
                    or server.server_type.capitalize(),
                }
            )
        elif server_type:
            # Try to find server by type
            server = MediaServer.query.filter_by(server_type=server_type).first()
            if server:
                settings_dict.update(
                    {
                        "server_type": server.server_type,
                        "server_url": getattr(server, "external_url", None)
                        or server.url
                        or "",
                        "external_url": getattr(server, "external_url", None) or "",
                        "server_name": getattr(server, "name", "")
                        or server.server_type.capitalize(),
                    }
                )
            else:
                # Fallback values for unknown server types
                settings_dict.update(
                    {
                        "server_type": server_type,
                        "server_url": "https://example.com",
                        "external_url": "https://example.com",
                        "server_name": server_type.capitalize(),
                    }
                )

        return {"settings": settings_dict}

    @staticmethod
    def get_wizard_steps_for_server(
        server_type: str,
    ) -> tuple[list[WizardStep], list[WizardStep]]:
        """
        Get pre and post wizard steps for a server type.

        Returns tuple of (pre_steps, post_steps).
        """
        from app.models import WizardPhase

        pre_steps = (
            WizardStep.query.filter_by(server_type=server_type, phase=WizardPhase.PRE)
            .order_by(WizardStep.position)
            .all()
        )

        post_steps = (
            WizardStep.query.filter_by(server_type=server_type, phase=WizardPhase.POST)
            .order_by(WizardStep.position)
            .all()
        )

        return pre_steps, post_steps

    @staticmethod
    def determine_step_phase_and_content(
        current_step: int, pre_steps: list[WizardStep], post_steps: list[WizardStep]
    ) -> tuple[str, WizardStep | None, str, str]:
        """
        Determine the phase and content for a given step index.

        Returns tuple of (phase, wizard_step, phase_title, step_description).
        """
        total_pre = len(pre_steps)
        join_step_index = total_pre

        if current_step < total_pre:
            # Pre-wizard step
            phase = "pre"
            wizard_step = pre_steps[current_step]
            phase_title = "Before Invite Acceptance"
            step_description = f"Pre-invite step {current_step + 1} of {total_pre}"
        elif current_step == join_step_index:
            # Join transition step
            phase = "join"
            wizard_step = None
            phase_title = "Invite Acceptance"
            step_description = "Invitation acceptance process"
        else:
            # Post-wizard step
            phase = "post"
            post_step_index = current_step - total_pre - 1
            wizard_step = (
                post_steps[post_step_index]
                if post_step_index < len(post_steps)
                else None
            )
            phase_title = "After Invite Acceptance"
            step_description = (
                f"Post-invite step {post_step_index + 1} of {len(post_steps)}"
            )

        return phase, wizard_step, phase_title, step_description
