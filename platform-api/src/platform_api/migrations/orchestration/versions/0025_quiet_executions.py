from alembic import op

revision = "0025"
down_revision = "0024"


def upgrade() -> None:
    # An execution our API ended quietly, because its workflow had nothing to run then: an empty
    # watchlist, or a held schedule. Every later block of it gets the same quiet answer, so a
    # change made meanwhile never starts a run from the middle of it.
    op.execute("""
        CREATE TABLE orchestration.quiet_executions (
            execution_id text PRIMARY KEY,
            why text NOT NULL,
            quiet_at timestamptz NOT NULL
        );

        GRANT SELECT, INSERT ON orchestration.quiet_executions TO wab_orchestration;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE orchestration.quiet_executions")
