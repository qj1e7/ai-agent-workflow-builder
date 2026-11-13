from alembic import op

revision = "0021"
down_revision = "0020"


def upgrade() -> None:
    # The practice copy of the Tell flow keeps each notice as the flow would get it (ENGINE-PLAN
    # E2c). A block tells once per run, so a run and a block make one notice at most.
    op.execute("""
        CREATE TABLE orchestration.tell_practice_messages (
            id text PRIMARY KEY,
            ts timestamptz NOT NULL,
            run_id text NOT NULL REFERENCES orchestration.runs (run_id),
            block text NOT NULL,
            body jsonb NOT NULL,
            UNIQUE (run_id, block)
        );

        GRANT SELECT, INSERT ON orchestration.tell_practice_messages TO wab_orchestration;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE orchestration.tell_practice_messages")
