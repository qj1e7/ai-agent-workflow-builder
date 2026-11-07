from alembic import op

revision = "0008"
down_revision = "0007"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE builder.team_requests ADD COLUMN asker_seen_at timestamptz;

        UPDATE builder.team_requests SET asker_seen_at = now();

        GRANT UPDATE (asker_seen_at) ON builder.team_requests TO wab_builder;
    """)


def downgrade() -> None:
    """Forgets which replies the askers have opened. Every reply then reads as new to its asker
    if the column comes back."""
    op.execute("ALTER TABLE builder.team_requests DROP COLUMN asker_seen_at")
