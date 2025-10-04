"""Add category field to wizard_step table

Revision ID: 20251004_add_category_to_wizard_step
Revises: 08a6c8fb44db
Create Date: 2025-10-04 11:40:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20251004_add_category_to_wizard_step"
down_revision = "08a6c8fb44db"
branch_labels = None
depends_on = None


def upgrade():
    """Add category column and update unique constraint.

    SQLite doesn't support ALTER TABLE modifications for constraints,
    so we need to recreate the table with the new schema.
    """
    # Create new wizard_step table with category column and updated constraint
    op.create_table(
        "wizard_step_new",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("server_type", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("requires", sa.JSON(), nullable=True),
        sa.Column("require_interaction", sa.Boolean(), nullable=True, default=False),
        sa.Column(
            "category",
            sa.String(),
            nullable=False,
            server_default="post_invite",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "server_type", "category", "position", name="uq_step_server_category_pos"
        ),
    )

    # Copy data from old table to new table, setting category to 'post_invite' for all existing rows
    op.execute(
        """
        INSERT INTO wizard_step_new (
            id, server_type, position, title, markdown, requires,
            require_interaction, category, created_at, updated_at
        )
        SELECT
            id, server_type, position, title, markdown, requires,
            require_interaction, 'post_invite', created_at, updated_at
        FROM wizard_step
        """
    )

    # Drop old table
    op.drop_table("wizard_step")

    # Rename new table to original name
    op.rename_table("wizard_step_new", "wizard_step")


def downgrade():
    """Remove category column and restore old unique constraint."""
    # Create old wizard_step table without category column
    op.create_table(
        "wizard_step_old",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("server_type", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("requires", sa.JSON(), nullable=True),
        sa.Column("require_interaction", sa.Boolean(), nullable=True, default=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_type", "position", name="uq_step_server_pos"),
    )

    # Copy data from current table to old table (dropping category column)
    # Note: This only preserves the first step at each position since we're
    # losing the category dimension
    op.execute(
        """
        INSERT INTO wizard_step_old (
            id, server_type, position, title, markdown, requires,
            require_interaction, created_at, updated_at
        )
        SELECT
            id, server_type, position, title, markdown, requires,
            require_interaction, created_at, updated_at
        FROM wizard_step
        WHERE category = 'post_invite'
        """
    )

    # Drop current table
    op.drop_table("wizard_step")

    # Rename old table to original name
    op.rename_table("wizard_step_old", "wizard_step")
