from alembic import op

revision = "0023"
down_revision = "0022"


def upgrade() -> None:
    # The daily self-test (ENGINE-PLAN E3): when its Read reached our API and was refused on
    # purpose, and when the error workflow's report of it arrived. One row a day, kept 90 days.
    op.execute("""
        CREATE TABLE orchestration.self_tests (
            execution_id text PRIMARY KEY,
            workflow_id text NOT NULL,
            sent_at timestamptz,
            arrived_at timestamptz,
            CHECK (sent_at IS NOT NULL OR arrived_at IS NOT NULL)
        );

        GRANT SELECT, INSERT, UPDATE, DELETE ON orchestration.self_tests TO wab_orchestration;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE orchestration.self_tests")
