from alembic import op

revision = "0008"
down_revision = "0007"

DAYS = "'every_day', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'"


def upgrade() -> None:
    op.execute(f"""
        ALTER TABLE orchestration.schedules DROP CONSTRAINT schedules_day_check;
        ALTER TABLE orchestration.schedules ADD CONSTRAINT schedules_day_check
            CHECK (day IN ('weekdays', {DAYS}));
    """)


def downgrade() -> None:
    op.execute(f"""
        DELETE FROM orchestration.schedules WHERE day = 'weekdays';
        ALTER TABLE orchestration.schedules DROP CONSTRAINT schedules_day_check;
        ALTER TABLE orchestration.schedules ADD CONSTRAINT schedules_day_check
            CHECK (day IN ({DAYS}));
    """)
