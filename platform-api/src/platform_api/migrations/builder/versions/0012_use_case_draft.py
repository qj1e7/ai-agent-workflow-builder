from alembic import op

revision = "0012"
down_revision = "0011"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE builder.use_cases
            ADD COLUMN draft boolean NOT NULL DEFAULT false,
            ADD CONSTRAINT use_cases_a_draft_is_never_paused
                CHECK (NOT (draft AND paused_at IS NOT NULL));
    """)


def downgrade() -> None:
    """The old code has no drafts, so each one comes back paused by its owner and never starts
    running on its own."""
    op.execute("""
        ALTER TABLE builder.use_cases DROP CONSTRAINT use_cases_a_draft_is_never_paused;
        UPDATE builder.use_cases SET paused_at = created_at, paused_by = owner WHERE draft;
        ALTER TABLE builder.use_cases DROP COLUMN draft;
    """)
