from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE monitoring.run_events_copied (
            run_id text PRIMARY KEY,
            generation text NOT NULL,
            seq integer NOT NULL CHECK (seq >= 1),
            copied_at timestamptz NOT NULL
        );
        GRANT SELECT, INSERT, UPDATE ON monitoring.run_events_copied TO wab_monitoring;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE monitoring.run_events_copied")
