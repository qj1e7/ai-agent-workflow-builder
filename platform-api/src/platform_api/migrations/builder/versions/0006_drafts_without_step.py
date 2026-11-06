from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade() -> None:
    op.execute("ALTER TABLE builder.drafts ALTER COLUMN step DROP NOT NULL")


def downgrade() -> None:
    """Puts a step on every draft saved without one (step 1), then makes the step required."""
    op.execute("""
        UPDATE builder.drafts SET step = 1 WHERE step IS NULL;
        ALTER TABLE builder.drafts ALTER COLUMN step SET NOT NULL;
    """)
