from alembic import op

revision = "0010"
down_revision = "0009"

# ADR 0025: a watched software can be read from Maven Central or npm, not only GitHub.


def upgrade() -> None:
    op.execute("""
        ALTER TABLE builder.watched_software
            DROP CONSTRAINT watched_software_source_kind_check,
            ADD CONSTRAINT watched_software_source_kind_check
                CHECK (source_kind IN ('github', 'maven', 'npm'));
    """)


def downgrade() -> None:
    # A list version that watches a package cannot go back to GitHub only, so the downgrade
    # refuses while one is saved instead of dropping it.
    op.execute("""
        ALTER TABLE builder.watched_software
            DROP CONSTRAINT watched_software_source_kind_check,
            ADD CONSTRAINT watched_software_source_kind_check CHECK (source_kind = 'github');
    """)
