from pathlib import Path

import frontmatter
import markdown
from flask import Blueprint, abort, redirect, render_template, request, session, url_for
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


def _steps(server: str, cfg: dict):
    """Return ordered wizard steps for *server* filtered by eligibility.

    Preference order:
        1. Rows from the new *wizard_step* table (if any exist for the given
           server_type).
        2. Legacy markdown files shipped in the repository (fallback).
    """

    # ─── 1) DB-backed steps ────────────────────────────────────────────────
    try:
        db_rows = (
            WizardStep.query.filter_by(server_type=server)
            .order_by(WizardStep.position)
            .all()
        )
    except Exception:
        db_rows = []  # table may not exist during migrations/tests

    if db_rows:
        from app.utils.wizard_rendering import adapt_wizard_steps
        steps = adapt_wizard_steps(db_rows)
        if steps:
            return steps

    # ─── 2) Fallback to bundled markdown files ─────────────────────────────
    files = sorted((BASE_DIR / server).glob("*.md"))
    return [frontmatter.load(str(f)) for f in files]


def _render(post, ctx: dict, server_type: str | None = None) -> str:
    """Render a post (frontmatter.Post or _RowAdapter) with context."""
    from flask import render_template_string

    # Jinja templates inside the markdown files expect a top-level `settings` variable.
    # Build a context copy that exposes the current config dictionary via this key
    # while still passing through all existing entries and utilities (e.g. the _() gettext).
    render_ctx = ctx.copy()
    render_ctx["settings"] = ctx

    # Add server_type to context if provided and not None
    if server_type is not None:
        render_ctx["server_type"] = server_type

    return markdown.markdown(
        render_template_string(post.content, **render_ctx),
        extensions=["fenced_code", "tables", "attr_list"],
    )


def _serve(server: str, idx: int):
    cfg = _settings()
    steps = _steps(server, cfg)
    if not steps:
        abort(404)

    # read the dir flag HTMX sends ('' | 'prev' | 'next')
    direction = request.values.get("dir", "")

    idx = max(0, min(idx, len(steps) - 1))
    post = steps[idx]
    html = _render(post, cfg | {"_": _}, server_type=server)

    # Determine if this step requires interaction (front matter `require: true` or DB flag)
    require_interaction = False
    try:
        require_interaction = bool(
            getattr(post, "get", lambda k, d=None: None)("require", False)
        )
    except Exception:
        require_interaction = False

    if not request.headers.get("HX-Request"):
        page = "wizard/frame.html"
    else:
        page = "wizard/steps.html"

    return render_template(
        page,
        body_html=html,
        idx=idx,
        max_idx=len(steps) - 1,
        server_type=server,
        direction=direction,  # ← NEW
        require_interaction=require_interaction,
    )


# ─── routes ─────────────────────────────────────────────────────
@wizard_bp.route("/")
def start():
    """Entry point – choose wizard folder based on invitation or global settings."""
    run_all_importers()

    inv_code = session.get("wizard_access")
    server_type = None
    if inv_code:
        inv = Invitation.query.filter_by(code=inv_code).first()

        # ── 1️⃣ explicit bundle override ───────────────────────────
        if inv and inv.wizard_bundle_id:
            session["wizard_bundle_id"] = inv.wizard_bundle_id
            # drop any server order session var to avoid conflicts
            session.pop("wizard_server_order", None)
            return redirect(url_for("wizard.bundle_view", idx=0))

        # ── 2️⃣ multi-server combo logic ───────────────────────────
        if inv and inv.servers:
            server_order = sorted(inv.servers, key=lambda s: s.server_type)
            if len(server_order) > 1:
                # store ordered list in session and redirect to combo route
                session["wizard_server_order"] = [s.server_type for s in server_order]
                return redirect(url_for("wizard.combo", idx=0))
            server_type = server_order[0].server_type

    if not server_type:
        first_srv = MediaServer.query.first()
        server_type = first_srv.server_type if first_srv else "plex"

    return _serve(server_type, 0)


@wizard_bp.route("/<server>/<int:idx>")
def step(server, idx):
    return _serve(server, idx)


# ─── combined wizard for multi-server invites ─────────────────────────────


@wizard_bp.route("/combo/<int:idx>")
def combo(idx: int):
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

    if not request.headers.get("HX-Request"):
        page = "wizard/frame.html"
    else:
        page = "wizard/steps.html"

    return render_template(
        page,
        body_html=html,
        idx=idx,
        max_idx=len(steps) - 1,
        server_type="combo",
        direction=request.values.get("dir", ""),
        require_interaction=require_interaction,
    )


# ─── bundle-specific wizard route ──────────────────────────────


@wizard_bp.route("/bundle/<int:idx>")
def bundle_view(idx: int):
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
    from app.utils.wizard_rendering import adapt_wizard_steps
    steps = adapt_wizard_steps(steps_raw)
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

    if not request.headers.get("HX-Request"):
        page = "wizard/frame.html"
    else:
        page = "wizard/steps.html"

    return render_template(
        page,
        body_html=html,
        idx=idx,
        max_idx=len(steps) - 1,
        server_type="bundle",
        direction=request.values.get("dir", ""),
        require_interaction=require_interaction,
    )


# ─── pre-wizard routes for before invite acceptance ─────────────────────────
@wizard_bp.route("/pre-wizard/<code>")
def pre_wizard_start(code):
    """Entry point for pre-invite wizard steps."""
    from app.services.wizard_timing import get_pre_invite_steps_for_invitation
    from sqlalchemy import func

    # Get invitation
    invitation = Invitation.query.filter(
        func.lower(Invitation.code) == code.lower()
    ).first()

    if not invitation:
        abort(404)

    # Get pre-invite steps
    steps = get_pre_invite_steps_for_invitation(invitation)
    if not steps:
        # No pre-invite steps, redirect to main invitation page
        return redirect(url_for("public.invite", code=code))

    # Store invitation code in session for clean URLs
    session["invite_code"] = code
    session["current_pre_wizard_step"] = 0

    return _render_timing_wizard_step(code, 0, "before_invite_acceptance")


@wizard_bp.route("/pre-wizard/<code>/<int:idx>")
def pre_wizard_step(code, idx):
    """Individual pre-invite wizard step."""
    return _render_timing_wizard_step(code, idx, "before_invite_acceptance")


@wizard_bp.route("/pre-wizard/<code>/complete", methods=["POST"])
def pre_wizard_complete(code):
    """Complete pre-wizard and redirect to invitation page."""
    session["pre_wizard_completed"] = True
    session["current_pre_wizard_step"] = None

    # Redirect to invitation page
    return redirect(url_for("public.invite", code=code))


# ─── post-wizard routes for after invite acceptance ─────────────────────────
@wizard_bp.route("/post-wizard")
def post_wizard_start():
    """Entry point for post-invite wizard steps."""
    # Check session for wizard access
    inv_code = session.get("wizard_access")
    if not inv_code:
        return redirect("/")

    return _render_post_wizard_step(0)


@wizard_bp.route("/post-wizard/<int:idx>")
def post_wizard_step(idx):
    """Individual post-invite wizard step."""
    return _render_post_wizard_step(idx)


@wizard_bp.route("/post-wizard/complete", methods=["POST"])
def post_wizard_complete():
    """Complete post-wizard and redirect to completion page."""
    # Clear wizard session data
    session.pop("wizard_access", None)
    session.pop("invitation_completed", None)

    # Redirect to completion page or dashboard
    return redirect("/")


# ─── helper functions for timing-based wizard rendering ─────────────────────
def _render_timing_wizard_step(code: str, idx: int, timing: str):
    """Render a wizard step for a specific timing (pre or post invite)."""
    from app.services.wizard_timing import get_pre_invite_steps_for_invitation, get_post_invite_steps_for_invitation
    from sqlalchemy import func

    # Get invitation
    invitation = Invitation.query.filter(
        func.lower(Invitation.code) == code.lower()
    ).first()

    if not invitation:
        abort(404)

    # Get steps based on timing
    if timing == "before_invite_acceptance":
        steps_raw = get_pre_invite_steps_for_invitation(invitation)
        template_prefix = "pre-invite"
    else:
        steps_raw = get_post_invite_steps_for_invitation(invitation)
        template_prefix = "post-invite"

    if not steps_raw:
        abort(404)

    # Convert to adapter format for compatibility with existing rendering
    from app.utils.wizard_rendering import adapt_wizard_steps
    steps = adapt_wizard_steps(steps_raw)
    idx = max(0, min(idx, len(steps) - 1))

    # Update session with current step
    if timing == "before_invite_acceptance":
        session["current_pre_wizard_step"] = idx

    # Render step
    post = steps[idx]
    current_server_type = steps_raw[idx].server_type if idx < len(steps_raw) else None
    html = _render(post, _settings() | {"_": _}, server_type=current_server_type)

    # Check interaction requirement
    require_interaction = False
    try:
        require_interaction = bool(
            getattr(post, "get", lambda k, d=None: None)("require", False)
        )
    except Exception:
        require_interaction = False

    # Choose template based on request type
    if not request.headers.get("HX-Request"):
        page = f"wizard/{template_prefix}-frame.html"
    else:
        page = f"wizard/{template_prefix}-steps.html"

    return render_template(
        page,
        body_html=html,
        idx=idx,
        max_idx=len(steps) - 1,
        server_type=current_server_type,
        direction=request.values.get("dir", ""),
        require_interaction=require_interaction,
        code=code,
        timing=timing,
    )


def _render_post_wizard_step(idx: int):
    """Render a post-invite wizard step."""
    from app.services.wizard_timing import get_post_invite_steps_for_invitation

    # Get invitation from session
    inv_code = session.get("wizard_access")
    if not inv_code:
        abort(403)

    invitation = Invitation.query.filter_by(code=inv_code).first()
    if not invitation:
        abort(404)

    # Get post-invite steps
    steps_raw = get_post_invite_steps_for_invitation(invitation)
    if not steps_raw:
        # No post-invite steps, redirect to completion
        return redirect("/")

    # Convert to adapter format
    from app.utils.wizard_rendering import adapt_wizard_steps
    steps = adapt_wizard_steps(steps_raw)
    idx = max(0, min(idx, len(steps) - 1))

    # Render step
    post = steps[idx]
    current_server_type = steps_raw[idx].server_type if idx < len(steps_raw) else None
    html = _render(post, _settings() | {"_": _}, server_type=current_server_type)

    # Check interaction requirement
    require_interaction = False
    try:
        require_interaction = bool(
            getattr(post, "get", lambda k, d=None: None)("require", False)
        )
    except Exception:
        require_interaction = False

    # Choose template
    if not request.headers.get("HX-Request"):
        page = "wizard/post-invite-frame.html"
    else:
        page = "wizard/post-invite-steps.html"

    return render_template(
        page,
        body_html=html,
        idx=idx,
        max_idx=len(steps) - 1,
        server_type=current_server_type,
        direction=request.values.get("dir", ""),
        require_interaction=require_interaction,
        timing="after_invite_acceptance",
    )
