from alembic import op

revision = "0009"
down_revision = "0008"


def upgrade() -> None:
    # The practice copy keeps the Adaptive Card a real channel gets, and the outcome a bot would
    # edit onto it (ADR 0036). A message posted before cards has neither.
    op.execute("""
        ALTER TABLE orchestration.teams_stub_messages
            ADD COLUMN card jsonb,
            ADD COLUMN outcome jsonb;

        CREATE TABLE orchestration.approval_messages (
            approval_id text PRIMARY KEY
                REFERENCES orchestration.approval_requests (approval_id),
            channel text NOT NULL,
            message_id text NOT NULL,
            posted_at timestamptz NOT NULL
        );
        GRANT SELECT, INSERT, UPDATE ON orchestration.approval_messages TO wab_orchestration;
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE orchestration.approval_messages;
        ALTER TABLE orchestration.teams_stub_messages DROP COLUMN outcome, DROP COLUMN card;
    """)
