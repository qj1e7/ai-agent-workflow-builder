from alembic import op

revision = "0011"
down_revision = "0010"


def upgrade() -> None:
    # A tick leases the rows it takes, so two replicas never send the same one, and each posted
    # approval request records which adapter posted it (ADR 0036). Every message so far came from
    # the practice copy, because no webhook was set before this migration.
    op.execute("""
        ALTER TABLE orchestration.outbox ADD COLUMN leased_until timestamptz;
        ALTER TABLE orchestration.approval_messages
            ADD COLUMN adapter text NOT NULL DEFAULT 'practice';
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE orchestration.approval_messages DROP COLUMN adapter;
        ALTER TABLE orchestration.outbox DROP COLUMN leased_until;
    """)
