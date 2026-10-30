from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade() -> None:
    # A check that cannot read a software keeps the newest version an earlier check read, and
    # when, beside the problem.
    op.execute("""
        ALTER TABLE orchestration.software_checks
            DROP CONSTRAINT software_checks_check,
            ADD COLUMN newest_at timestamptz;
        UPDATE orchestration.software_checks SET newest_at = checked_at
            WHERE newest_version IS NOT NULL;
        ALTER TABLE orchestration.software_checks
            ADD CONSTRAINT software_checks_read
                CHECK (newest_version IS NOT NULL OR problem IS NOT NULL),
            ADD CONSTRAINT software_checks_newest_at
                CHECK ((newest_version IS NULL) = (newest_at IS NULL));
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE orchestration.software_checks
            DROP CONSTRAINT software_checks_newest_at,
            DROP CONSTRAINT software_checks_read;
        UPDATE orchestration.software_checks SET newest_version = NULL
            WHERE problem IS NOT NULL;
        ALTER TABLE orchestration.software_checks
            DROP COLUMN newest_at,
            ADD CONSTRAINT software_checks_check
                CHECK ((newest_version IS NULL) <> (problem IS NULL));
    """)
