from alembic import op

revision = "0022"
down_revision = "0021"

ALLOWED = "connection IN ('jira', 'github', 'teams', 'model'{more})"


def upgrade() -> None:
    # Confluence's checks are kept as Jira's are (ENGINE-PLAN E12).
    op.execute(f"""
        ALTER TABLE orchestration.connection_checks
            DROP CONSTRAINT connection_checks_connection_check,
            ADD CONSTRAINT connection_checks_connection_check
                CHECK ({ALLOWED.format(more=", 'confluence'")});
    """)


def downgrade() -> None:
    op.execute(f"""
        DELETE FROM orchestration.connection_checks WHERE connection = 'confluence';
        ALTER TABLE orchestration.connection_checks
            DROP CONSTRAINT connection_checks_connection_check,
            ADD CONSTRAINT connection_checks_connection_check CHECK ({ALLOWED.format(more="")});
    """)
