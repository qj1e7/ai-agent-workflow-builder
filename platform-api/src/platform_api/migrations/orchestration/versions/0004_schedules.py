from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE orchestration.schedules (
            use_case_id text PRIMARY KEY,
            day text NOT NULL CHECK (day IN ('every_day', 'monday', 'tuesday', 'wednesday',
                'thursday', 'friday', 'saturday', 'sunday')),
            at text NOT NULL CHECK (at ~ '^([01][0-9]|2[0-3]):[0-5][05]$'),
            time_zone text NOT NULL,
            owner_id text NOT NULL,
            owner_name text NOT NULL,
            saved_at timestamptz NOT NULL,
            last_slot_started timestamptz
        );

        GRANT SELECT, INSERT, UPDATE, DELETE ON orchestration.schedules TO wab_orchestration;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE orchestration.schedules")
