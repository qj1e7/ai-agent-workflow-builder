from alembic import op

revision = "0015"
down_revision = "0014"


def upgrade() -> None:
    # What GitHub said about the saved repository at the latest check. full_name is the owner/name
    # it answered for, which differs from the saved one after a rename (GitHub redirects the old
    # name). not_found is a 404 for the saved repository, which names no new home. Rows from
    # before this keep both empty, which reads as "not known".
    op.execute("""
        ALTER TABLE orchestration.software_checks
            ADD COLUMN full_name text,
            ADD COLUMN not_found boolean NOT NULL DEFAULT false,
            ADD CONSTRAINT software_checks_not_found
                CHECK (NOT not_found OR (full_name IS NULL AND problem IS NOT NULL));
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE orchestration.software_checks
            DROP CONSTRAINT software_checks_not_found,
            DROP COLUMN not_found,
            DROP COLUMN full_name;
    """)
