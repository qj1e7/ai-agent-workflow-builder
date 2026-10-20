from alembic import op

revision = "0001"
down_revision = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE monitoring.run_events (
            run_id text NOT NULL,
            seq integer NOT NULL CHECK (seq >= 1),
            ts timestamptz NOT NULL,
            actor jsonb NOT NULL,
            kind text NOT NULL,
            summary text NOT NULL,
            data jsonb NOT NULL,
            dedupe_key text NOT NULL,
            PRIMARY KEY (run_id, seq),
            UNIQUE (run_id, dedupe_key)
        );
        GRANT USAGE ON SCHEMA monitoring TO wab_monitoring, wab_orchestration;
        GRANT SELECT, INSERT ON monitoring.run_events TO wab_monitoring;
        GRANT SELECT, INSERT ON monitoring.run_events TO wab_orchestration;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE monitoring.run_events")
