from alembic import op

revision = "0024"
down_revision = "0023"


def upgrade() -> None:
    # A request can also end closed: an update ended the shared run workflow its run waited in
    # (ENGINE-PLAN E11). Nothing is written, as with an expiry or a delete.
    op.execute("""
        ALTER TABLE orchestration.approval_requests
            DROP CONSTRAINT approval_requests_ended_check,
            ADD CONSTRAINT approval_requests_ended_check
                CHECK (ended IN ('expired', 'cancelled', 'closed'));
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE orchestration.approval_requests SET ended = 'cancelled' WHERE ended = 'closed';
        ALTER TABLE orchestration.approval_requests
            DROP CONSTRAINT approval_requests_ended_check,
            ADD CONSTRAINT approval_requests_ended_check
                CHECK (ended IN ('expired', 'cancelled'));
    """)
