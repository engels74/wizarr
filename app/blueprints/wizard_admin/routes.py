from __future__ import annotations

import json
import re
import tempfile
from datetime import datetime
from typing import cast

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_babel import gettext as _
from flask_login import login_required
from sqlalchemy import func, select

from app.extensions import db
from app.forms.wizard import (
    SimpleWizardStepForm,
    WizardBundleForm,
    WizardImportForm,
    WizardPresetForm,
    WizardStepForm,
)
from app.models import (
    MediaServer,
    WizardBundle,
    WizardBundleStep,
    WizardPhase,
    WizardStep,
)
from app.services.wizard_export_import import WizardExportImportService
from app.services.wizard_presets import (
    create_step_from_preset,
    get_available_presets,
    get_preset_title,
)
from app.utils.position_manager import WizardStepPositionManager

wizard_admin_bp = Blueprint(
    "wizard_admin",
    __name__,
    url_prefix="/settings/wizard",
)


def _handle_wizard_step_phase_change(step: WizardStep, new_phase: WizardPhase) -> None:
    """
    Handle phase change for a wizard step, including position conflict resolution.

    This function safely moves a step from one phase to another while:
    1. Avoiding database constraint violations
    2. Properly positioning the step in the new phase
    3. Reordering remaining steps in the old phase to close gaps

    Args:
        step: The WizardStep to move
        new_phase: The target phase (WizardPhase.PRE or WizardPhase.POST)
    """
    if step.phase == new_phase:
        return  # No change needed

    old_phase = step.phase
    old_position = step.position

    # Use no_autoflush to prevent premature constraint violations during queries
    with db.session.no_autoflush:
        # Get remaining steps in old phase that need to be reordered
        stmt = (
            select(WizardStep)
            .where(
                WizardStep.server_type == step.server_type,
                WizardStep.phase == old_phase,
                WizardStep.position > old_position,
            )
            .order_by(WizardStep.position)
        )
        remaining_steps = db.session.execute(stmt).scalars().all()

    # Use the position manager for safe phase change
    position_manager = WizardStepPositionManager(db.session)
    position_manager.move_step_to_phase(step, new_phase, remaining_steps, old_position)


# Matches {{ _( "Some text" ) }} or {{ _( 'Some text' ) }} with arbitrary
# whitespace.
_I18N_PATTERN = re.compile(r"{{\s*_\(\s*(['\"])(.*?)\1\s*\)\s*}}", re.DOTALL)


def _strip_localization(md: str) -> str:
    """Remove Jinja gettext wrappers from markdown, leaving plain text."""
    return _I18N_PATTERN.sub(lambda m: m.group(2), md)


@wizard_admin_bp.route("/", methods=["GET"])
@login_required
def list_steps():
    # Group steps by server_type and phase for display
    # Exclude custom steps (managed via Wizard Bundles) from the default view
    stmt = (
        select(WizardStep)
        .where(WizardStep.server_type != "custom")
        .order_by(WizardStep.server_type, WizardStep.phase, WizardStep.position)
    )
    rows = db.session.execute(stmt).scalars().all()

    # Get all active server types first
    stmt = select(MediaServer)
    active_types = {srv.server_type for srv in db.session.execute(stmt).scalars().all()}

    # Initialize grouped data with all active server types (even if they have no steps)
    grouped_by_server_and_phase: dict[str, dict[str, list[WizardStep]]] = {
        server_type: {"pre": [], "post": []} for server_type in active_types
    }

    # Group existing steps by server_type and phase
    for row in rows:
        phase_str = row.phase.value if row.phase else "post"
        if row.server_type in grouped_by_server_and_phase:
            grouped_by_server_and_phase[row.server_type][phase_str].append(row)

    # When requested via HTMX we return only the inner fragment that is meant
    # to be swapped into the <div id="tab-body"> container on the settings
    # page.  For a normal full-page navigation we extend the base layout so
    # the <head> section is populated and styling/scripts remain intact.
    tmpl = (
        "settings/wizard/steps.html"
        if request.headers.get("HX-Request")
        else "settings/page.html"  # fallback renders full settings page
    )

    # For the full page fallback we have to render the *entire* settings page
    # with the wizard tab pre-selected.  Rather than duplicating that layout
    # we reuse the existing generic settings page helper and pass a query
    # parameter that the template looks for to auto-open the correct tab.
    if tmpl == "settings/page.html":
        return redirect(url_for("settings.page") + "#wizard")

    return render_template(
        tmpl, grouped_by_server_and_phase=grouped_by_server_and_phase
    )


# ─── Bundles view ─────────────────────────────────────────────────────


@wizard_admin_bp.route("/bundles", methods=["GET"])
@login_required
def list_bundles():
    # Clean up orphaned bundle steps before displaying
    orphaned_steps = (
        db.session.query(WizardBundleStep)
        .outerjoin(WizardStep, WizardBundleStep.step_id == WizardStep.id)
        .filter(WizardStep.id.is_(None))
        .all()
    )

    if orphaned_steps:
        for orphaned in orphaned_steps:
            db.session.delete(orphaned)
        db.session.commit()
        flash(_("Cleaned up {} orphaned step(s)").format(len(orphaned_steps)), "info")

    stmt = select(WizardBundle).order_by(WizardBundle.id)
    bundles = db.session.execute(stmt).scalars().all()

    tmpl = (
        "settings/wizard/bundles.html"
        if request.headers.get("HX-Request")
        else "settings/page.html"
    )

    if tmpl == "settings/page.html":
        return redirect(url_for("settings.page") + "#wizard")

    return render_template(tmpl, bundles=bundles)


@wizard_admin_bp.route("/create", methods=["GET", "POST"])
@login_required
def create_step():
    bundle_id = request.args.get("bundle_id", type=int)
    simple = request.args.get("simple") == "1" or bundle_id is not None

    FormCls = SimpleWizardStepForm if simple else WizardStepForm
    form = FormCls(request.form if request.method == "POST" else None)

    if form.validate_on_submit():
        # When using the simple form we slot the step into a synthetic 'custom'
        # server_type so ordering is still unique and existing wizard logic is
        # unaffected.
        server_type_attr = getattr(form, "server_type", None)
        stype = "custom" if simple else (server_type_attr and server_type_attr.data)

        # Get phase from form or default to 'post'
        phase_str = "post"
        if not simple and hasattr(form, "phase"):
            phase_field = getattr(form, "phase", None)
            if phase_field and hasattr(phase_field, "data") and phase_field.data:
                phase_str = phase_field.data
        phase_enum = WizardPhase.PRE if phase_str == "pre" else WizardPhase.POST

        max_pos = (
            db.session.query(func.max(WizardStep.position))
            .filter_by(server_type=stype, phase=phase_enum)
            .scalar()
        )
        next_pos = (max_pos or 0) + 1

        cleaned_md = _strip_localization(form.markdown.data or "")

        step = WizardStep(
            server_type=stype,
            phase=phase_enum,
            position=next_pos,
            title=getattr(form, "title", None) and form.title.data or None,
            markdown=cleaned_md,
            require_interaction=(
                getattr(form, "require_interaction", None) is not None
                and bool(form.require_interaction.data)
            ),
        )
        db.session.add(step)
        db.session.flush()  # get step.id

        # If created from a bundle context attach immediately
        if bundle_id:
            max_bpos = (
                db.session.query(func.max(WizardBundleStep.position))
                .filter_by(bundle_id=bundle_id)
                .scalar()
            )
            next_bpos = (max_bpos or 0) + 1
            db.session.add(
                WizardBundleStep(
                    bundle_id=bundle_id, step_id=step.id, position=next_bpos
                )
            )

        db.session.commit()
        flash(_("Step created"), "success")

        # HTMX target refresh depending on origin
        if request.headers.get("HX-Request"):
            return list_bundles() if bundle_id else list_steps()

        return redirect(
            url_for(
                "wizard_admin.list_bundles" if bundle_id else "wizard_admin.list_steps"
            )
        )

    # GET – choose modal / full template based on form type
    if simple:
        modal_tmpl = "modals/wizard-simple-step-form.html"
        page_tmpl = "settings/wizard/simple_form.html"
    else:
        modal_tmpl = "modals/wizard-step-form.html"
        page_tmpl = "settings/wizard/form.html"

    tmpl = modal_tmpl if request.headers.get("HX-Request") else page_tmpl
    return render_template(tmpl, form=form, action="create", bundle_id=bundle_id)


@wizard_admin_bp.route("/create-preset", methods=["GET", "POST"])
@login_required
def create_preset():
    """Create wizard step from preset template."""
    form = WizardPresetForm(request.form if request.method == "POST" else None)

    # Populate preset choices
    presets = get_available_presets()
    form.preset_id.choices = [(p.id, p.name) for p in presets]

    if form.validate_on_submit():
        preset_id = form.preset_id.data
        server_type = form.server_type.data

        # Type check: these should not be None after validation
        if not preset_id or not server_type:
            flash("Preset ID and server type are required", "danger")
            return redirect(url_for("wizard_admin.create_preset"))

        # Prepare template variables
        template_vars = {}
        if form.discord_id.data:
            template_vars["discord_id"] = form.discord_id.data
        if form.overseerr_url.data:
            template_vars["overseerr_url"] = form.overseerr_url.data

        try:
            # Create step content from preset
            markdown_content = create_step_from_preset(preset_id, **template_vars)
            title = get_preset_title(preset_id)

            # Find next position for this server type
            max_pos = (
                db.session.query(func.max(WizardStep.position))
                .filter_by(server_type=server_type)
                .scalar()
            )
            next_pos = (max_pos or 0) + 1

            # Create the step
            step = WizardStep(
                server_type=server_type,
                position=next_pos,
                title=title,
                markdown=markdown_content,
            )
            db.session.add(step)
            db.session.commit()

            flash(_("Preset step created successfully"), "success")

            # HTMX refresh
            if request.headers.get("HX-Request"):
                return list_steps()
            return redirect(url_for("wizard_admin.list_steps"))

        except KeyError as e:
            flash(_("Error creating preset: {}").format(str(e)), "error")

    modal_tmpl = "modals/wizard-preset-form.html"
    page_tmpl = "settings/wizard/preset_form.html"
    tmpl = modal_tmpl if request.headers.get("HX-Request") else page_tmpl

    return render_template(tmpl, form=form, presets=presets, action="create")


@wizard_admin_bp.route("/<int:step_id>/edit", methods=["GET", "POST"])
@login_required
def edit_step(step_id: int):
    step = db.session.get(WizardStep, step_id)
    if not step:
        abort(404)

    # Refresh the step object to ensure we have the most current data
    # This is especially important after drag-and-drop phase changes
    db.session.refresh(step)

    simple = step.server_type == "custom"
    FormCls = SimpleWizardStepForm if simple else WizardStepForm
    form = FormCls(request.form if request.method == "POST" else None, obj=step)

    if form.validate_on_submit():
        if not simple:
            server_type_attr = getattr(form, "server_type", None)
            step.server_type = server_type_attr.data if server_type_attr else "custom"

            # Update phase if present on form
            if hasattr(form, "phase"):
                phase_field = getattr(form, "phase", None)
                if phase_field and hasattr(phase_field, "data") and phase_field.data:
                    phase_str = phase_field.data
                    new_phase = (
                        WizardPhase.PRE if phase_str == "pre" else WizardPhase.POST
                    )

                    # Handle phase change using the shared utility function
                    _handle_wizard_step_phase_change(step, new_phase)

        step.title = getattr(form, "title", None) and form.title.data or None
        cleaned_md = _strip_localization(form.markdown.data or "")
        step.markdown = cleaned_md

        # Update interaction requirement if present on this form
        if getattr(form, "require_interaction", None) is not None:
            step.require_interaction = bool(form.require_interaction.data)

        db.session.commit()
        flash(_("Step updated"), "success")

        # HTMX refresh
        if request.headers.get("HX-Request"):
            return list_bundles() if simple else list_steps()

        return redirect(
            url_for(
                "wizard_admin.list_bundles" if simple else "wizard_admin.list_steps"
            )
        )

    # GET: populate fields
    if request.method == "GET":
        form.markdown.data = _strip_localization(step.markdown)

        # Ensure phase field is correctly populated from enum to string
        if not simple and hasattr(form, "phase") and step.phase:
            # Type: WizardStepForm has phase field, SimpleWizardStepForm does not
            from typing import cast

            wizard_form = cast(WizardStepForm, form)
            wizard_form.phase.data = step.phase.value

    modal_tmpl = (
        "modals/wizard-simple-step-form.html"
        if simple
        else "modals/wizard-step-form.html"
    )
    page_tmpl = (
        "settings/wizard/simple_form.html" if simple else "settings/wizard/form.html"
    )
    tmpl = modal_tmpl if request.headers.get("HX-Request") else page_tmpl
    return render_template(tmpl, form=form, action="edit", step=step)


@wizard_admin_bp.route("/<int:step_id>/delete", methods=["POST"])
@login_required
def delete_step(step_id: int):
    step = db.session.get(WizardStep, step_id)
    if not step:
        abort(404)

    # Check if this is a custom step (from bundle context)
    is_custom_step = step.server_type == "custom"

    db.session.delete(step)
    db.session.commit()
    flash(_("Step deleted"), "success")

    # For HTMX requests return the updated steps list fragment so the client
    # can refresh the table without a full page reload. Otherwise fall back
    # to a normal redirect which lands on the full settings page (wizard tab
    # pre-selected) to keep the UI consistent and fully styled.
    if request.headers.get("HX-Request"):
        return list_bundles() if is_custom_step else list_steps()

    return redirect(url_for("settings.page") + "#wizard")


@wizard_admin_bp.route("/reorder", methods=["POST"])
@login_required
def reorder_steps():
    """Accept JSON object with step IDs, server_type, and phase for reordering."""
    data = request.json
    if not isinstance(data, dict):
        abort(400)

    # Type guard ensures data is dict[str, Any]
    assert isinstance(data, dict)
    order_raw = data.get("ids", [])
    server_type = data.get("server_type")
    phase_str = data.get("phase", "post")

    if not isinstance(order_raw, list) or not server_type:
        abort(400)

    order = cast(list[int], order_raw)
    phase_enum = WizardPhase.PRE if phase_str == "pre" else WizardPhase.POST

    # Use no_autoflush to prevent premature constraint violations during queries
    with db.session.no_autoflush:
        # Only get steps for the specific server_type and phase
        stmt = select(WizardStep).where(
            WizardStep.id.in_(order),
            WizardStep.server_type == server_type,
            WizardStep.phase == phase_enum,
        )
        rows = db.session.execute(stmt).scalars().all()
        id_to_row = {r.id: r for r in rows}

        # Get ALL other steps in the same phase that are NOT being reordered
        # These need to be moved out of the way to avoid position conflicts
        stmt = select(WizardStep).where(
            WizardStep.server_type == server_type,
            WizardStep.phase == phase_enum,
            ~WizardStep.id.in_(order),  # Exclude steps being reordered
        )
        other_steps = db.session.execute(stmt).scalars().all()

    # Use the position manager for safe reordering
    position_manager = WizardStepPositionManager(db.session)

    # Get the steps to reorder in the correct order
    steps_to_reorder = []
    for step_id in order:
        step = id_to_row.get(step_id)
        if step is not None:
            steps_to_reorder.append(step)

    # Reorder using the position manager
    position_manager.reorder_items(steps_to_reorder, list(other_steps))

    db.session.commit()
    return jsonify({"status": "ok"})


@wizard_admin_bp.route("/<int:step_id>/update-phase", methods=["POST"])
@login_required
def update_step_phase(step_id: int):
    """Update the phase of a wizard step when moved between pre/post sections."""
    step = db.session.get(WizardStep, step_id)
    if not step:
        abort(404)
    data = request.json

    if not data or "phase" not in data:
        abort(400)

    # Type guard ensures data is not None
    assert data is not None
    phase_str = data["phase"]
    if phase_str not in ["pre", "post"]:
        abort(400)

    # Update the phase using the shared utility function
    new_phase = WizardPhase.PRE if phase_str == "pre" else WizardPhase.POST
    _handle_wizard_step_phase_change(step, new_phase)

    db.session.commit()
    return jsonify({"status": "ok"})


@wizard_admin_bp.route("/preview", methods=["POST"])
@login_required
def preview_markdown():
    from markdown import markdown as md_to_html

    raw = request.form.get("markdown", "")
    return md_to_html(raw, extensions=["fenced_code", "tables", "attr_list"])


# ─── bundle CRUD ─────────────────────────────────────────────────
@wizard_admin_bp.route("/bundle/create", methods=["GET", "POST"])
@login_required
def create_bundle():
    form = WizardBundleForm(request.form if request.method == "POST" else None)

    if form.validate_on_submit():
        bundle = WizardBundle(
            name=form.name.data, description=form.description.data or None
        )
        db.session.add(bundle)
        db.session.commit()
        flash(_("Bundle created"), "success")

        # For HTMX requests return the updated bundles list fragment so the client
        # can refresh the table without a full page reload. Otherwise fall back
        # to a normal redirect.
        if request.headers.get("HX-Request"):
            return list_bundles()

        return redirect(url_for("wizard_admin.list_bundles"))

    tmpl = (
        "modals/wizard-bundle-form.html"
        if request.headers.get("HX-Request")
        else "settings/wizard/bundle_form.html"
    )
    return render_template(tmpl, form=form, action="create")


@wizard_admin_bp.route("/bundle/<int:bundle_id>/edit", methods=["GET", "POST"])
@login_required
def edit_bundle(bundle_id: int):
    bundle = db.session.get(WizardBundle, bundle_id)
    if not bundle:
        abort(404)
    form = WizardBundleForm(
        request.form if request.method == "POST" else None, obj=bundle
    )

    if form.validate_on_submit():
        bundle.name = form.name.data
        bundle.description = form.description.data or None
        db.session.commit()
        flash(_("Bundle updated"), "success")

        # For HTMX requests return the updated bundles list fragment so the client
        # can refresh the table without a full page reload. Otherwise fall back
        # to a normal redirect.
        if request.headers.get("HX-Request"):
            return list_bundles()

        return redirect(url_for("wizard_admin.list_bundles"))

    tmpl = (
        "modals/wizard-bundle-form.html"
        if request.headers.get("HX-Request")
        else "settings/wizard/bundle_form.html"
    )
    return render_template(tmpl, form=form, action="edit", bundle=bundle)


@wizard_admin_bp.route("/bundle/<int:bundle_id>/delete", methods=["POST"])
@login_required
def delete_bundle(bundle_id: int):
    bundle = db.session.get(WizardBundle, bundle_id)
    if not bundle:
        abort(404)
    db.session.delete(bundle)
    db.session.commit()
    flash(_("Bundle deleted"), "success")

    if request.headers.get("HX-Request"):
        return list_bundles()
    return redirect(url_for("wizard_admin.list_bundles"))


@wizard_admin_bp.route("/bundle/<int:bundle_id>/reorder", methods=["POST"])
@login_required
def reorder_bundle(bundle_id: int):
    order_raw = request.json  # expects list of step IDs in new order
    if not isinstance(order_raw, list):
        abort(400)
    order = cast(list[int], order_raw)

    stmt = select(WizardBundleStep).where(
        WizardBundleStep.bundle_id == bundle_id,
        WizardBundleStep.step_id.in_(order),
    )
    rows = db.session.execute(stmt).scalars().all()
    id_to_row = {r.step_id: r for r in rows}

    # Phase 1 – temporary negative positions to satisfy unique constraint
    for tmp_pos, step_id in enumerate(order, start=1):
        row = id_to_row.get(step_id)
        if row is None:
            continue
        row.position = -tmp_pos
    db.session.flush()

    # Phase 2 – final 0-based positions
    for final_pos, step_id in enumerate(order):
        row = id_to_row.get(step_id)
        if row is None:
            continue
        row.position = final_pos
    db.session.commit()
    return jsonify({"status": "ok"})


# ─── add steps modal & handler ───────────────────────────────────
@wizard_admin_bp.route("/bundle/<int:bundle_id>/add-steps-modal", methods=["GET"])
@login_required
def add_steps_modal(bundle_id: int):
    bundle = db.session.get(WizardBundle, bundle_id)
    if not bundle:
        abort(404)
    # steps not yet in bundle
    from typing import Any, cast

    # Type cast to work around SQLAlchemy relationship type issues
    bundle_steps = cast(Any, bundle.steps)
    existing_ids = {bs.step_id for bs in bundle_steps}
    stmt = (
        select(WizardStep)
        .where(~WizardStep.id.in_(existing_ids))
        .order_by(WizardStep.server_type, WizardStep.position)
    )
    available = db.session.execute(stmt).scalars().all()
    return render_template(
        "modals/bundle-add-steps.html", bundle=bundle, steps=available
    )


@wizard_admin_bp.route("/bundle/<int:bundle_id>/add-steps", methods=["POST"])
@login_required
def add_steps(bundle_id: int):
    bundle = db.session.get(WizardBundle, bundle_id)
    if not bundle:
        abort(404)
    ids = request.form.getlist("step_ids")
    if not ids:
        abort(400)
    # Determine next position value
    max_pos = (
        db.session.query(func.max(WizardBundleStep.position))
        .filter_by(bundle_id=bundle_id)
        .scalar()
    )
    next_pos = (max_pos or 0) + 1
    for sid in ids:
        try:
            sid_int = int(sid)
        except ValueError:
            continue
        bundle.steps.append(WizardBundleStep(step_id=sid_int, position=next_pos))
        next_pos += 1
    db.session.commit()
    flash(_("Steps added"), "success")
    if request.headers.get("HX-Request"):
        return list_bundles()
    return redirect(url_for("wizard_admin.list_bundles"))


@wizard_admin_bp.route("/bundle-step/<int:bundle_step_id>/delete", methods=["POST"])
@login_required
def delete_bundle_step(bundle_step_id: int):
    bundle_step = db.session.get(WizardBundleStep, bundle_step_id)
    if not bundle_step:
        abort(404)
    db.session.delete(bundle_step)
    db.session.commit()
    flash(_("Orphaned step removed"), "success")

    if request.headers.get("HX-Request"):
        return list_bundles()
    return redirect(url_for("wizard_admin.list_bundles"))


# ─── Export/Import functionality ─────────────────────────────────────
@wizard_admin_bp.route("/export/<server_type>", methods=["GET"])
@login_required
def export_server_steps(server_type: str):
    """Export wizard steps for a specific server type as JSON file."""
    try:
        service = WizardExportImportService()
        export_data = service.export_steps_by_server_type(server_type)

        if not export_data.steps:
            flash(
                _("No steps found for server type: {}").format(server_type), "warning"
            )
            if request.headers.get("HX-Request"):
                return list_steps()
            return redirect(url_for("wizard_admin.list_steps"))

        # Create temporary file for download
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as temp_file:
            json.dump(export_data.to_dict(), temp_file, indent=2, ensure_ascii=False)
            temp_file_path = temp_file.name

        # Generate filename with server type and current date
        filename = f"wizard_steps_{server_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        return send_file(
            temp_file_path,
            as_attachment=True,
            download_name=filename,
            mimetype="application/json",
        )

    except Exception as e:
        flash(_("Export failed: {}").format(str(e)), "error")
        if request.headers.get("HX-Request"):
            return list_steps()
        return redirect(url_for("wizard_admin.list_steps"))


@wizard_admin_bp.route("/export/bundle/<int:bundle_id>", methods=["GET"])
@login_required
def export_bundle(bundle_id: int):
    """Export a wizard bundle as JSON file."""
    try:
        service = WizardExportImportService()
        export_data = service.export_bundle(bundle_id)

        # Create temporary file for download
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as temp_file:
            json.dump(export_data.to_dict(), temp_file, indent=2, ensure_ascii=False)
            temp_file_path = temp_file.name

        # Generate filename with bundle name and current date
        bundle_name = (
            export_data.bundle.name.replace(" ", "_").lower()
            if export_data.bundle
            else "unknown_bundle"
        )
        filename = f"wizard_bundle_{bundle_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        return send_file(
            temp_file_path,
            as_attachment=True,
            download_name=filename,
            mimetype="application/json",
        )

    except ValueError as e:
        flash(_("Export failed: {}").format(str(e)), "error")
        if request.headers.get("HX-Request"):
            return list_bundles()
        return redirect(url_for("wizard_admin.list_bundles"))
    except Exception as e:
        flash(_("Export failed: {}").format(str(e)), "error")
        if request.headers.get("HX-Request"):
            return list_bundles()
        return redirect(url_for("wizard_admin.list_bundles"))


@wizard_admin_bp.route("/import", methods=["GET", "POST"])
@login_required
def import_steps():
    """Import wizard steps from uploaded JSON file."""
    form = WizardImportForm()

    if request.method == "GET":
        # Show import form/modal
        tmpl = (
            "modals/wizard-import-form.html"
            if request.headers.get("HX-Request")
            else "settings/wizard/import_form.html"
        )
        return render_template(tmpl, form=form)

    # POST - handle file upload using form validation
    if not form.validate_on_submit():
        # Form validation failed
        tmpl = (
            "modals/wizard-import-form.html"
            if request.headers.get("HX-Request")
            else "settings/wizard/import_form.html"
        )
        return render_template(tmpl, form=form)

    try:
        # Read and parse JSON
        file = form.file.data
        content = file.read().decode("utf-8")
        import_data = json.loads(content)

        # Check for replace existing flag
        replace_existing = form.replace_existing.data

        # Import data (steps or bundle)
        service = WizardExportImportService()
        result = service.import_data(import_data, replace_existing=replace_existing)

        if result.success:
            success_msg = _("Successfully imported {} items").format(
                result.imported_count
            )
            if result.updated_count > 0:
                success_msg += _(" and updated {} existing items").format(
                    result.updated_count
                )
            flash(success_msg, "success")
        else:
            flash(_("Import failed: {}").format(result.message), "error")
            for error in result.errors:
                flash(error, "error")

    except json.JSONDecodeError:
        flash(_("Invalid JSON file"), "error")
    except Exception as e:
        flash(_("Import failed: {}").format(str(e)), "error")

    # Return updated view
    if request.headers.get("HX-Request"):
        return list_steps()
    return redirect(url_for("wizard_admin.list_steps"))


# ─── Enhanced Wizard Preview functionality ─────────────────────────────────────
@wizard_admin_bp.route("/preview/<server_type>", methods=["GET"])
@login_required
def preview_wizard(server_type: str):
    """
    Enhanced preview that uses actual wizard templates for identical appearance.

    Shows the complete user journey: pre-wizard steps → join transition → post-wizard steps
    Uses the same templates and rendering logic as the real wizard flow.
    """
    from app.services.wizard_rendering import WizardRenderer

    # Get current step from query parameter (default to 0)
    current_step = request.args.get("step", 0, type=int)

    # Get wizard steps using shared utility
    pre_steps, post_steps = WizardRenderer.get_wizard_steps_for_server(server_type)

    # Calculate total steps (pre + join + post)
    total_steps = len(pre_steps) + 1 + len(post_steps)

    # Bounds checking
    if current_step >= total_steps:
        current_step = total_steps - 1
    elif current_step < 0:
        current_step = 0

    # Determine phase and content using shared utility
    phase, wizard_step, phase_title, step_description = (
        WizardRenderer.determine_step_phase_and_content(
            current_step, pre_steps, post_steps
        )
    )

    # Build context using shared utility (same as real wizard)
    context = WizardRenderer.build_wizard_context(server_type=server_type)

    # Render step content
    rendered_content = None
    require_interaction = False
    step_title = None

    if wizard_step:
        # Use shared rendering logic (same as real wizard)
        rendered_content = WizardRenderer.render_wizard_step_content(
            wizard_step, context
        )
        require_interaction = bool(getattr(wizard_step, "require_interaction", False))
        step_title = wizard_step.title
    elif phase == "join":
        # Mock content for join transition
        step_title = "Accept Invitation"
        rendered_content = f"""
        <h2>{step_title}</h2>
        <h3>🎉 Ready to Join!</h3>
        <p>This is where users would accept their invitation and create their account.</p>
        <p>The actual process varies by server type (Plex OAuth, username/password forms, etc.)</p>
        """

    # Build navigation URLs for preview
    prev_url = None
    next_url = None

    if current_step > 0:
        prev_url = url_for(
            "wizard_admin.preview_wizard",
            server_type=server_type,
            step=current_step - 1,
        )

    if current_step < total_steps - 1:
        next_url = url_for(
            "wizard_admin.preview_wizard",
            server_type=server_type,
            step=current_step + 1,
        )

    # Calculate progress
    progress_percentage = (
        ((current_step + 1) / total_steps * 100) if total_steps > 0 else 0
    )

    # Get server information for context
    server = MediaServer.query.filter_by(server_type=server_type).first()
    server_name = server.name if server else server_type.capitalize()

    # Apply the same DRY pattern as other wizard routes:
    # Return full preview template for regular requests, wizard steps only for HTMX
    if not request.headers.get("HX-Request"):
        # Full page request - return complete preview template with headers
        template = "wizard/preview_frame.html"
        context = {
            # Context for preview frame
            "server_type": server_type,
            "server_name": server_name,
            "phase": phase,
            "phase_title": phase_title,
            "step_description": step_description,
            "step_title": step_title,
            "current_step": current_step,
            "total_steps": total_steps,
            "progress_percentage": progress_percentage,
            # Context for wizard/steps.html (included template)
            "body_html": rendered_content,
            "idx": current_step,
            "max_idx": total_steps - 1,
            "direction": "",  # No animation in preview
            "require_interaction": require_interaction,
            "prev_url": prev_url,
            "next_url": next_url,
            # Additional context
            "pre_steps_count": len(pre_steps),
            "post_steps_count": len(post_steps),
        }
    else:
        # HTMX request - return wizard steps with out-of-band progress update
        template = "wizard/steps_with_progress.html"
        context = {
            # Context for wizard/steps.html
            "body_html": rendered_content,
            "idx": current_step,
            "max_idx": total_steps - 1,
            "server_type": server_type,  # Needed for completion button logic
            "direction": request.values.get("dir", ""),  # Animation direction
            "require_interaction": require_interaction,
            "prev_url": prev_url,
            "next_url": next_url,
            # Context for progress indicator (out-of-band swap)
            "current_step": current_step,
            "total_steps": total_steps,
            "phase": phase,
            "phase_title": phase_title,
            "step_description": step_description,
            "progress_percentage": progress_percentage,
        }

    return render_template(template, **context)
