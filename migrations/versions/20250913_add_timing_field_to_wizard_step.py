"""Add timing field to wizard_step table

Revision ID: 20250913_add_timing_field_to_wizard_step
Revises: 39514b0aaad9
Create Date: 2025-09-13 14:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20250913_add_timing_field_to_wizard_step"
down_revision = "39514b0aaad9"
branch_labels = None
depends_on = None


def upgrade():
    """Add timing field to wizard_step table and update unique constraint."""
    # Add timing column with default value for backward compatibility
    with op.batch_alter_table("wizard_step", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "timing",
                sa.String(),
                nullable=False,
                server_default="after_invite_acceptance",
            )
        )
    
    # Remove server_default to avoid future inserts locking a default at DB level
    with op.batch_alter_table("wizard_step", schema=None) as batch_op:
        batch_op.alter_column("timing", server_default=None)
    
    # Drop the old unique constraint
    with op.batch_alter_table("wizard_step", schema=None) as batch_op:
        batch_op.drop_constraint("uq_step_server_pos", type_="unique")
    
    # Add new unique constraint that includes timing
    with op.batch_alter_table("wizard_step", schema=None) as batch_op:
        batch_op.create_unique_constraint(
            "uq_step_server_timing_pos", 
            ["server_type", "timing", "position"]
        )


def downgrade():
    """Remove timing field and restore original unique constraint."""
    # Drop the new unique constraint
    with op.batch_alter_table("wizard_step", schema=None) as batch_op:
        batch_op.drop_constraint("uq_step_server_timing_pos", type_="unique")
    
    # Restore original unique constraint
    with op.batch_alter_table("wizard_step", schema=None) as batch_op:
        batch_op.create_unique_constraint(
            "uq_step_server_pos", 
            ["server_type", "position"]
        )
    
    # Remove timing column
    with op.batch_alter_table("wizard_step", schema=None) as batch_op:
        batch_op.drop_column("timing")
