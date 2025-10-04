from pathlib import Path

import frontmatter
import markdown
from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_babel import _
from flask_login import current_user

from app.models import (
    Invitation,
    MediaServer,
    Settings,
    WizardBundle,
    WizardBundleStep,
    WizardStep,
)
from app.services.invite_code_manager import InviteCodeManager
from app.services.ombi_client import run_all_importers

wizard_bp = Blueprint("wizard", __name__, url_prefix="/wizard")
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "wizard_steps"


# Only allow access right after signup or when logged in
@wizard_bp.before_request
def restrict_wizard():
    # Determine if the Wizard ACL is enabled (default: True)
    acl_row = Settings.query.filter_by(key="wizard_acl_enabled").first()
    acl_enabled = True  # default behaviour – restrict access
    if acl_row and acl_row.value is not None:
        acl_enabled = str(acl_row.value).lower() != "false"

    # Skip further checks if the ACL feature is disabled
    if not acl_enabled:
        return None  # Allow everyone

    # Enforce ACL: allow only authenticated users or invited sessions
    if current_user.is_authenticated:
        return None
    if not session.get("wizard_access"):
        # Check if this is coming from an invitation process
        # Allow access if they have recently used an invitation
        if (
            session.get("invitation_in_progress")
            or request.referrer
            and "/j/" in request.referrer
        ):
            return None
        return redirect("/")
    return None


# ─── helpers ────────────────────────────────────────────────────
def _get_server_context(server_type: str) -> dict[str, str | None]:
    """Get server-specific context variables for a given server type"""
    # Find the server for this specific server type
    # Priority: 1) From invitation servers, 2) First server of this type

    server = None

    # 1️⃣ Check if we have an invitation with specific servers
    inv_code = session.get("wizard_access")
    if inv_code:
        inv = Invitation.query.filter_by(code=inv_code).first()
        if inv and inv.servers:
            # Find the server of the requested type
            server = next(
                (s for s in inv.servers if s.server_type == server_type), None
            )

    # 2️⃣ Fallback to first server of this type
    if server is None:
        server = MediaServer.query.filter_by(server_type=server_type).first()

    # 3️⃣ Last resort: any server
    if server is None:
        server = MediaServer.query.first()

    context = {}
    if server:
        # Server-specific variables that steps can use
        context["external_url"] = server.external_url or server.url or ""
        context["server_url"] = server.url or ""
        context["server_name"] = getattr(server, "name", "") or ""
        context["server_type"] = server.server_type
    else:
        # Fallback values to prevent template errors
        context["external_url"] = ""
        context["server_url"] = ""
        context["server_name"] = ""
        context["server_type"] = server_type

    return context


def _settings() -> dict[str, str | None]:
    # Load all Settings rows **except** legacy server-specific keys. Those have
    # been migrated to the dedicated ``MediaServer`` table and should no longer
    # be sourced from the generic key/value store.
    LEGACY_KEYS: set[str] = {
        "server_type",
        "server_url",
        "external_url",
        "api_key",
        "server_name",
    }

    data: dict[str, str | None] = {
        s.key: s.value for s in Settings.query.all() if s.key not in LEGACY_KEYS
    }

    # ------------------------------------------------------------------
    # Determine the *active* server context in the following order of
    # precedence:
    #   1️⃣  Explicit invitation (wizard_access session key)
    #   2️⃣  First configured MediaServer row (arbitrary default)
    # If neither exists, the Wizard still needs sensible fallbacks so the
    # markdown templates render without errors.
    # ------------------------------------------------------------------

    srv = None

    # 1️⃣  Invitation override
    inv_code = session.get("wizard_access")
    if inv_code:
        inv = Invitation.query.filter_by(code=inv_code).first()
        if inv and inv.server:
            srv = inv.server

    # 2️⃣  Fallback to the first MediaServer row (if any)
    if srv is None:
        srv = MediaServer.query.first()

    # Populate the derived server fields so that existing Jinja templates that
    # reference ``settings.server_*`` continue to work seamlessly.
    if srv is not None:
        data["server_type"] = srv.server_type
        data["server_url"] = srv.external_url or srv.url
        if srv.external_url:
            data["external_url"] = srv.external_url
        if getattr(srv, "name", None):
            data["server_name"] = srv.name

    # If still missing, supply sane defaults to avoid KeyErrors in templates.
    data.setdefault("server_type", "plex")
    data.setdefault("server_url", "")

    return data


# Removed _eligible function as part of requires system overhaul


def _steps(server: str, cfg: dict, category: str = "post_invite"):
    """Return ordered wizard steps for *server* and *category* filtered by eligibility.

    Args:
        server: Server type (plex, jellyfin, etc.)
        cfg: Configuration dictionary
        category: Step category ('pre_invite' or 'post_invite'), defaults to 'post_invite'

    Preference order:
        1. Rows from the new *wizard_step* table (if any exist for the given
           server_type and category).
        2. Legacy markdown files shipped in the repository (fallback, post_invite only).

    Returns:
        List of wizard steps (frontmatter.Post or _RowAdapter objects)
    """

    # ─── 1) DB-backed steps ────────────────────────────────────────────────
    try:
        db_rows = (
            WizardStep.query.filter_by(server_type=server, category=category)
            .order_by(WizardStep.position)
            .all()
        )
    except Exception:
        db_rows = []  # table may not exist during migrations/tests

    if db_rows:

        class _RowAdapter:
            """Lightweight shim exposing the subset of frontmatter.Post API
            used by helper functions: `.content` property and `.get()`.
            """

            __slots__ = ("content", "_require")

            def __init__(self, row: "WizardStep"):
                self.content = row.markdown
                # Mirror frontmatter key `require` from DB boolean
                self._require = bool(getattr(row, "require_interaction", False))

            # frontmatter.Post.get(key, default)
            def get(self, key, default=None):
                if key == "require":
                    return self._require
                return default

            def __iter__(self):
                """Make _RowAdapter iterable for compatibility."""
                return iter([self])

        steps = [_RowAdapter(r) for r in db_rows]
        if steps:
            return steps

    # ─── 2) Fallback to bundled markdown files ─────────────────────────────
    # Legacy markdown files are always treated as post_invite only
    if category == "post_invite":
        files = sorted((BASE_DIR / server).glob("*.md"))
        return [frontmatter.load(str(f)) for f in files]

    # No pre_invite steps in legacy files
    return []


def _render(post, ctx: dict, server_type: str | None = None) -> str:
    """Render a post (frontmatter.Post or _RowAdapter) with context."""
    from app.services.wizard_widgets import (
        process_card_delimiters,
        process_widget_placeholders,
    )

    # Jinja templates inside the markdown files expect a top-level `settings` variable.
    # Build a context copy that exposes the current config dictionary via this key
    # while still passing through all existing entries and utilities (e.g. the _() gettext).
    render_ctx = ctx.copy()
    render_ctx["settings"] = ctx

    # Add server_type to context if provided and not None
    if server_type is not None:
        render_ctx["server_type"] = server_type

    # FIRST: Process card delimiters (|||) BEFORE widget placeholders
    content_with_cards = process_card_delimiters(post.content)

    # SECOND: Process widget placeholders BEFORE Jinja rendering
    # This prevents Jinja from trying to parse {{ widget:... }} syntax
    content_with_widgets = content_with_cards
    if server_type:
        content_with_widgets = process_widget_placeholders(
            content_with_cards, server_type, context=render_ctx
        )

    # THEN: Render Jinja templates in the processed content
    env = current_app.jinja_env.overlay(autoescape=False)
    template = env.from_string(content_with_widgets)
    rendered_content = template.render(**render_ctx)

    # Use simple markdown configuration - HTML should pass through by default
    return markdown.markdown(
        rendered_content, extensions=["fenced_code", "tables", "attr_list"]
    )


def _serve_wizard(server: str, idx: int, steps: list, phase: str):
    """Common wizard rendering logic for both pre and post-wizard.

    Args:
        server: Server type (plex, jellyfin, etc.)
        idx: Current step index
        steps: List of wizard steps (frontmatter.Post or _RowAdapter objects)
        phase: 'pre' or 'post' to indicate which phase

    Returns:
        Rendered template response with appropriate headers
    """
    if not steps:
        abort(404)

    cfg = _settings()
    # read the dir flag HTMX sends ('' | 'prev' | 'next')
    direction = request.values.get("dir", "")

    idx = max(0, min(idx, len(steps) - 1))
    post = steps[idx]

    # Merge server-specific context (external_url, server_url, etc.) into config
    server_ctx = _get_server_context(server)
    html = _render(post, cfg | server_ctx | {"_": _}, server_type=server)

    # Determine if this step requires interaction (front matter `require: true` or DB flag)
    require_interaction = False
    try:
        require_interaction = bool(
            getattr(post, "get", lambda k, d=None: None)("require", False)
        )
    except Exception:
        require_interaction = False

    # Determine which template to use based on request type
    if not request.headers.get("HX-Request"):
        # Initial page load - full wrapper with UI chrome
        page = "wizard/frame.html"
    else:
        # HTMX request - content-only partial
        page = "wizard/_content.html"

    response = render_template(
        page,
        body_html=html,
        idx=idx,
        max_idx=len(steps) - 1,
        server_type=server,
        direction=direction,
        require_interaction=require_interaction,
        phase=phase,  # NEW: Pass phase to template
    )

    # Add custom headers for client-side updates (HTMX requests only)
    if request.headers.get("HX-Request"):
        from flask import make_response

        resp = make_response(response)
        resp.headers["X-Wizard-Idx"] = str(idx)
        resp.headers["X-Require-Interaction"] = (
            "true" if require_interaction else "false"
        )
        return resp

    return response


def _serve(server: str, idx: int):
    """Legacy serve function - maintained for backward compatibility.

    This function now delegates to _serve_wizard() with default post_invite phase.
    """
    cfg = _settings()
    steps = _steps(server, cfg, category="post_invite")
    return _serve_wizard(server, idx, steps, phase="post")


def _get_server_type_from_invitation(invitation: Invitation) -> str | None:
    """Get server type from invitation.

    Args:
        invitation: Invitation object

    Returns:
        Server type string (e.g., 'plex', 'jellyfin') or None if no servers configured

    Note:
        This function maintains server-agnostic architecture by never hardcoding
        a specific server type as a fallback. If no servers are configured,
        it returns None and the caller should handle this appropriately.
    """
    # Priority 1: Check new many-to-many relationship
    if hasattr(invitation, "servers") and invitation.servers:
        return invitation.servers[0].server_type

    # Priority 2: Check legacy single server relationship (backward compatibility)
    if hasattr(invitation, "server") and invitation.server:
        return invitation.server.server_type

    # Priority 3: Fallback to first configured server in the system
    first_srv = MediaServer.query.first()
    if first_srv:
        return first_srv.server_type

    # No servers configured - return None to signal error condition
    return None


# ─── routes ─────────────────────────────────────────────────────
@wizard_bp.route("/pre-wizard")
@wizard_bp.route("/pre-wizard/<int:idx>")
def pre_wizard(idx: int = 0):
    """Display pre-invite wizard steps before user accepts invitation.

    This endpoint shows wizard steps that should be viewed before the user
    accepts an invitation and creates their account. It validates the invite
    code on each request and redirects appropriately if:
    - Invite code is invalid/expired
    - No pre-invite steps exist for the invitation's service
    - No media servers are configured

    Args:
        idx: Current step index (default: 0)

    Returns:
        Rendered wizard template or redirect response
    """
    # Validate invite code from session
    invite_code = InviteCodeManager.get_invite_code()
    if not invite_code:
        flash(_("Invalid or expired invitation"), "error")
        return redirect(url_for("public.index"))

    is_valid, invitation = InviteCodeManager.validate_invite_code(invite_code)

    if not is_valid or not invitation:
        flash(_("Invalid or expired invitation"), "error")
        return redirect(url_for("public.index"))

    # Determine server type from invitation
    server_type = _get_server_type_from_invitation(invitation)

    # Handle case where no servers are configured
    if not server_type:
        flash(
            _(
                "No media servers are configured. Please contact the administrator to set up a media server."
            ),
            "error",
        )
        return redirect(url_for("public.index"))

    # Get pre-invite steps
    cfg = _settings()
    steps = _steps(server_type, cfg, category="pre_invite")

    if not steps:
        # No pre-invite steps, mark as complete and redirect to join
        InviteCodeManager.mark_pre_wizard_complete()
        return redirect(url_for("public.invite", code=invite_code))

    # Check if we're on the last step and moving forward
    direction = request.values.get("dir", "")
    if direction == "next" and idx >= len(steps) - 1:
        # User completed all pre-wizard steps
        InviteCodeManager.mark_pre_wizard_complete()
        return redirect(url_for("public.invite", code=invite_code))

    # Render wizard using existing _serve_wizard logic
    return _serve_wizard(server_type, idx, steps, "pre")


@wizard_bp.route("/post-wizard")
@wizard_bp.route("/post-wizard/<int:idx>")
def post_wizard(idx: int = 0):
    """Display post-invite wizard steps after user accepts invitation.

    This endpoint shows wizard steps that should be viewed after the user
    accepts an invitation and creates their account. It validates authentication
    and redirects appropriately if:
    - User is not authenticated and has no wizard_access session
    - No post-invite steps exist for the service
    - No media servers are configured

    Args:
        idx: Current step index (default: 0)

    Returns:
        Rendered wizard template or redirect response
    """
    # Check authentication (user must have accepted invitation)
    # Allow access if user is authenticated OR has wizard_access session
    if not current_user.is_authenticated and not session.get("wizard_access"):
        flash(_("Please log in to continue"), "warning")
        return redirect(url_for("auth.login"))

    # Determine server type from invitation or first configured server
    server_type = None
    inv_code = session.get("wizard_access")

    if inv_code:
        inv = Invitation.query.filter_by(code=inv_code).first()
        if inv:
            server_type = _get_server_type_from_invitation(inv)

    # Fallback to first configured server if no invitation context
    if not server_type:
        first_srv = MediaServer.query.first()
        if first_srv:
            server_type = first_srv.server_type
        else:
            # No servers configured - show error message
            flash(
                _(
                    "No media servers are configured. Please contact the administrator to set up a media server."
                ),
                "error",
            )
            return redirect(url_for("public.root"))

    # Check for database-backed post-invite steps specifically
    # We don't want to fall back to legacy markdown files for post-wizard
    try:
        db_steps = (
            WizardStep.query.filter_by(server_type=server_type, category="post_invite")
            .order_by(WizardStep.position)
            .all()
        )
    except Exception:
        db_steps = []

    if not db_steps:
        # No post-invite steps in database, clear invite data and redirect to completion
        InviteCodeManager.clear_invite_data()
        # Clear wizard_access session as well
        session.pop("wizard_access", None)
        flash(_("Setup complete! Welcome to your media server."), "success")
        return redirect(url_for("public.root"))

    # Get post-invite steps (will use db_steps or fall back to legacy files)
    cfg = _settings()
    steps = _steps(server_type, cfg, category="post_invite")

    # Check if we're on the last step and moving forward
    direction = request.values.get("dir", "")
    if direction == "next" and idx >= len(steps) - 1:
        # User completed all post-wizard steps
        InviteCodeManager.clear_invite_data()
        # Clear wizard_access session as well
        session.pop("wizard_access", None)
        flash(_("Setup complete! Welcome to your media server."), "success")
        return redirect(url_for("public.root"))

    # Render wizard using existing _serve_wizard logic
    return _serve_wizard(server_type, idx, steps, "post")


@wizard_bp.route("/")
def start():
    """Entry point – redirect to appropriate wizard based on context.

    This endpoint provides backward compatibility with the old /wizard URL.
    It intelligently redirects users to the appropriate wizard phase:

    - Authenticated users → /post-wizard (they've already accepted an invitation)
    - Users with invite code → /pre-wizard (they're in the invitation flow)
    - Others → home page (no context available)

    Requirements: 8.8, 12.4, 12.5
    """
    run_all_importers()

    # Priority 1: Check if user is authenticated or has wizard_access session
    # These users should see post-wizard steps
    if current_user.is_authenticated or session.get("wizard_access"):
        return redirect(url_for("wizard.post_wizard"))

    # Priority 2: Check for invite code in session (from InviteCodeManager)
    # These users should see pre-wizard steps
    invite_code = InviteCodeManager.get_invite_code()
    if invite_code:
        # Validate the invite code before redirecting
        is_valid, invitation = InviteCodeManager.validate_invite_code(invite_code)
        if is_valid and invitation:
            return redirect(url_for("wizard.pre_wizard"))
        else:
            # Invalid invite code - clear it and fall through to home redirect
            InviteCodeManager.clear_invite_data()

    # Priority 3: No context available - redirect to home page
    return redirect(url_for("public.index"))


@wizard_bp.route("/<server>/<int:idx>")
def step(server, idx):
    return _serve(server, idx)


# ─── combined wizard for multi-server invites ─────────────────────────────


@wizard_bp.route("/combo/<int:idx>")
def combo(idx: int):
    """Combined wizard for multi-server invites.

    Note: This function has custom logic for concatenating steps from multiple servers,
    so it doesn't use _serve_wizard() directly. However, it maintains the same
    rendering logic and template structure.
    """
    cfg = _settings()
    order = session.get("wizard_server_order") or []
    if not order:
        # fallback to normal wizard
        return redirect(url_for("wizard.start"))

    # concatenate steps preserving order AND track which server each step belongs to
    steps: list = []
    step_server_mapping: list = []  # Track which server type each step belongs to

    for stype in order:
        server_steps = _steps(stype, cfg)
        steps.extend(server_steps)
        # Add server type for each step
        step_server_mapping.extend([stype] * len(server_steps))

    if not steps:
        abort(404)

    idx = max(0, min(idx, len(steps) - 1))

    # Get the server type for the current step
    current_server_type = (
        step_server_mapping[idx] if idx < len(step_server_mapping) else order[0]
    )

    post = steps[idx]
    html = _render(post, cfg | {"_": _}, server_type=current_server_type)

    require_interaction = False
    try:
        require_interaction = bool(
            getattr(post, "get", lambda k, d=None: None)("require", False)
        )
    except Exception:
        require_interaction = False

    # Determine which template to use based on request type
    if not request.headers.get("HX-Request"):
        # Initial page load - full wrapper with UI chrome
        page = "wizard/frame.html"
    else:
        # HTMX request - content-only partial
        page = "wizard/_content.html"

    response = render_template(
        page,
        body_html=html,
        idx=idx,
        max_idx=len(steps) - 1,
        server_type="combo",
        direction=request.values.get("dir", ""),
        require_interaction=require_interaction,
        phase="post",  # Combo wizard is always post-invite
    )

    # Add custom headers for client-side updates (HTMX requests only)
    if request.headers.get("HX-Request"):
        from flask import make_response

        resp = make_response(response)
        resp.headers["X-Wizard-Idx"] = str(idx)
        resp.headers["X-Require-Interaction"] = (
            "true" if require_interaction else "false"
        )
        return resp

    return response


# ─── bundle-specific wizard route ──────────────────────────────


@wizard_bp.route("/bundle/<int:idx>")
def bundle_view(idx: int):
    """Bundle-specific wizard route.

    Note: This function has custom logic for loading steps from bundles,
    so it doesn't use _serve_wizard() directly. However, it maintains the same
    rendering logic and template structure.
    """
    bundle_id = session.get("wizard_bundle_id")
    if not bundle_id:
        return redirect(url_for("wizard.start"))

    bundle = WizardBundle.query.get(bundle_id)
    if not bundle:
        abort(404)

    # ordered steps via association table
    ordered = (
        WizardBundleStep.query.filter_by(bundle_id=bundle_id)
        .order_by(WizardBundleStep.position)
        .all()
    )
    steps_raw = [r.step for r in ordered]

    # adapt to frontmatter-like interface
    class _RowAdapter:
        __slots__ = ("content", "_require")

        def __init__(self, row: WizardStep):
            self.content = row.markdown
            self._require = bool(getattr(row, "require_interaction", False))

        def get(self, key, default=None):
            if key == "require":
                return self._require
            return default

    steps = [_RowAdapter(s) for s in steps_raw]
    if not steps:
        abort(404)

    idx = max(0, min(idx, len(steps) - 1))

    # Get the server type for the current step from the WizardStep
    current_server_type = steps_raw[idx].server_type if idx < len(steps_raw) else None

    post = steps[idx]
    html = _render(post, _settings() | {"_": _}, server_type=current_server_type)

    require_interaction = False
    try:
        require_interaction = bool(
            getattr(post, "get", lambda k, d=None: None)("require", False)
        )
    except Exception:
        require_interaction = False

    # Determine which template to use based on request type
    if not request.headers.get("HX-Request"):
        # Initial page load - full wrapper with UI chrome
        page = "wizard/frame.html"
    else:
        # HTMX request - content-only partial
        page = "wizard/_content.html"

    response = render_template(
        page,
        body_html=html,
        idx=idx,
        max_idx=len(steps) - 1,
        server_type="bundle",
        direction=request.values.get("dir", ""),
        require_interaction=require_interaction,
        phase="post",  # Bundles are always post-invite (for now)
    )

    # Add custom headers for client-side updates (HTMX requests only)
    if request.headers.get("HX-Request"):
        from flask import make_response

        resp = make_response(response)
        resp.headers["X-Wizard-Idx"] = str(idx)
        resp.headers["X-Require-Interaction"] = (
            "true" if require_interaction else "false"
        )
        return resp

    return response
