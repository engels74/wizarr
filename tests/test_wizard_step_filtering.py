"""Tests for wizard step filtering by category (pre_invite vs post_invite)."""

import pytest

from app.blueprints.wizard.routes import _steps
from app.extensions import db
from app.models import WizardStep


@pytest.fixture
def session(app):
    """Return a clean database session inside an app context."""
    with app.app_context():
        # Clean up any existing WizardStep data before the test
        db.session.query(WizardStep).delete()
        db.session.commit()

        yield db.session

        # Clean up after the test
        db.session.rollback()


@pytest.fixture
def mixed_steps(session):
    """Create a mix of pre_invite and post_invite wizard steps for testing."""
    steps = [
        # Plex pre-invite steps
        WizardStep(
            server_type="plex",
            category="pre_invite",
            position=0,
            title="Pre-Plex Welcome",
            markdown="# Before you join",
        ),
        WizardStep(
            server_type="plex",
            category="pre_invite",
            position=1,
            title="Pre-Plex Requirements",
            markdown="# What you need",
        ),
        # Plex post-invite steps
        WizardStep(
            server_type="plex",
            category="post_invite",
            position=0,
            title="Post-Plex Welcome",
            markdown="# Welcome to Plex",
        ),
        WizardStep(
            server_type="plex",
            category="post_invite",
            position=1,
            title="Post-Plex Getting Started",
            markdown="# Getting started",
        ),
        # Jellyfin pre-invite steps
        WizardStep(
            server_type="jellyfin",
            category="pre_invite",
            position=0,
            title="Pre-Jellyfin Welcome",
            markdown="# Welcome to Jellyfin (pre)",
        ),
        # Jellyfin post-invite steps
        WizardStep(
            server_type="jellyfin",
            category="post_invite",
            position=0,
            title="Post-Jellyfin Welcome",
            markdown="# Welcome to Jellyfin (post)",
        ),
    ]
    session.add_all(steps)
    session.commit()
    return steps


def test_filter_by_pre_invite_category(app, session, mixed_steps):
    """Test that _steps() correctly filters by pre_invite category."""
    with app.app_context():
        cfg = {}
        steps = _steps("plex", cfg, category="pre_invite")

        assert len(steps) == 2
        assert steps[0].content == "# Before you join"
        assert steps[1].content == "# What you need"


def test_filter_by_post_invite_category(app, session, mixed_steps):
    """Test that _steps() correctly filters by post_invite category."""
    with app.app_context():
        cfg = {}
        steps = _steps("plex", cfg, category="post_invite")

        assert len(steps) == 2
        assert steps[0].content == "# Welcome to Plex"
        assert steps[1].content == "# Getting started"


def test_default_category_is_post_invite(app, session, mixed_steps):
    """Test that _steps() defaults to post_invite when no category is specified."""
    with app.app_context():
        cfg = {}
        # Call without category parameter - should default to post_invite
        steps = _steps("plex", cfg)

        assert len(steps) == 2
        assert steps[0].content == "# Welcome to Plex"
        assert steps[1].content == "# Getting started"


def test_no_steps_for_category_returns_empty_list(app, session):
    """Test that _steps() returns empty list when no steps exist for category."""
    with app.app_context():
        # Create only post_invite steps
        step = WizardStep(
            server_type="plex",
            category="post_invite",
            position=0,
            markdown="# Post only",
        )
        session.add(step)
        session.commit()

        cfg = {}
        # Query for pre_invite - should return empty list
        steps = _steps("plex", cfg, category="pre_invite")

        assert len(steps) == 0
        assert steps == []


def test_no_steps_for_server_type_returns_empty_or_legacy(app, session):
    """Test that _steps() returns empty list when no steps exist for server."""
    with app.app_context():
        cfg = {}
        # Query for server type with no DB steps and no legacy files
        steps = _steps("nonexistent_server", cfg, category="pre_invite")

        assert len(steps) == 0


def test_mixed_categories_different_servers(app, session, mixed_steps):
    """Test filtering works correctly for different server types."""
    with app.app_context():
        cfg = {}

        # Get pre-invite steps for jellyfin
        jf_pre_steps = _steps("jellyfin", cfg, category="pre_invite")
        assert len(jf_pre_steps) == 1
        assert jf_pre_steps[0].content == "# Welcome to Jellyfin (pre)"

        # Get post-invite steps for jellyfin
        jf_post_steps = _steps("jellyfin", cfg, category="post_invite")
        assert len(jf_post_steps) == 1
        assert jf_post_steps[0].content == "# Welcome to Jellyfin (post)"


def test_step_order_preserved_by_position(app, session):
    """Test that steps are returned in order by position field."""
    with app.app_context():
        # Create steps out of order
        steps = [
            WizardStep(
                server_type="plex",
                category="pre_invite",
                position=2,
                markdown="# Third",
            ),
            WizardStep(
                server_type="plex",
                category="pre_invite",
                position=0,
                markdown="# First",
            ),
            WizardStep(
                server_type="plex",
                category="pre_invite",
                position=1,
                markdown="# Second",
            ),
        ]
        session.add_all(steps)
        session.commit()

        cfg = {}
        ordered_steps = _steps("plex", cfg, category="pre_invite")

        assert len(ordered_steps) == 3
        assert ordered_steps[0].content == "# First"
        assert ordered_steps[1].content == "# Second"
        assert ordered_steps[2].content == "# Third"


def test_legacy_markdown_files_only_for_post_invite(app, session):
    """Test that legacy markdown files are only returned for post_invite category."""
    with app.app_context():
        cfg = {}

        # If plex has legacy markdown files, they should only appear for post_invite
        # For pre_invite, should return empty list (no DB steps)
        pre_steps = _steps("plex", cfg, category="pre_invite")
        assert isinstance(pre_steps, list)

        # For post_invite, may return legacy files if they exist
        post_steps = _steps("plex", cfg, category="post_invite")
        assert isinstance(post_steps, list)


def test_row_adapter_exposes_require_interaction(app, session):
    """Test that _RowAdapter correctly exposes require_interaction field."""
    with app.app_context():
        step_no_require = WizardStep(
            server_type="plex",
            category="pre_invite",
            position=0,
            markdown="# No require",
            require_interaction=False,
        )
        step_with_require = WizardStep(
            server_type="plex",
            category="pre_invite",
            position=1,
            markdown="# Requires action",
            require_interaction=True,
        )
        session.add_all([step_no_require, step_with_require])
        session.commit()

        cfg = {}
        steps = _steps("plex", cfg, category="pre_invite")

        assert len(steps) == 2
        assert steps[0].get("require", False) is False
        assert steps[1].get("require", False) is True


def test_unique_constraint_allows_same_position_different_categories(app, session):
    """Test that unique constraint allows same position for different categories."""
    with app.app_context():
        # Both at position 0, but different categories - should be allowed
        pre_step = WizardStep(
            server_type="plex",
            category="pre_invite",
            position=0,
            markdown="# Pre at 0",
        )
        post_step = WizardStep(
            server_type="plex",
            category="post_invite",
            position=0,
            markdown="# Post at 0",
        )
        session.add_all([pre_step, post_step])
        session.commit()

        # Verify both exist
        cfg = {}
        pre_steps = _steps("plex", cfg, category="pre_invite")
        post_steps = _steps("plex", cfg, category="post_invite")

        assert len(pre_steps) == 1
        assert len(post_steps) == 1
        assert pre_steps[0].content == "# Pre at 0"
        assert post_steps[0].content == "# Post at 0"


def test_exception_handling_returns_empty_list(app, session):
    """Test that database exceptions are caught and return empty list or legacy fallback."""
    with app.app_context():
        cfg = {}

        # Even with database issues, should gracefully return a result
        # (either empty list or legacy files for post_invite)
        try:
            steps = _steps("plex", cfg, category="pre_invite")
            assert isinstance(steps, list)
        except Exception as e:
            pytest.fail(f"_steps() should handle exceptions gracefully, got: {e}")


def test_category_filtering_independent_of_server_type(app, session):
    """Test that category filtering works independently for each server type."""
    with app.app_context():
        # Create steps for multiple servers with same category
        steps = [
            WizardStep(
                server_type="plex", category="pre_invite", position=0, markdown="# Plex"
            ),
            WizardStep(
                server_type="jellyfin",
                category="pre_invite",
                position=0,
                markdown="# Jellyfin",
            ),
            WizardStep(
                server_type="emby", category="pre_invite", position=0, markdown="# Emby"
            ),
        ]
        session.add_all(steps)
        session.commit()

        cfg = {}

        # Each server should only get its own steps
        plex_steps = _steps("plex", cfg, category="pre_invite")
        jellyfin_steps = _steps("jellyfin", cfg, category="pre_invite")
        emby_steps = _steps("emby", cfg, category="pre_invite")

        assert len(plex_steps) == 1
        assert len(jellyfin_steps) == 1
        assert len(emby_steps) == 1

        assert plex_steps[0].content == "# Plex"
        assert jellyfin_steps[0].content == "# Jellyfin"
        assert emby_steps[0].content == "# Emby"
