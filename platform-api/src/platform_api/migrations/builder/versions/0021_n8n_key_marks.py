from alembic import op

revision = "0021"
down_revision = "0020"


def upgrade() -> None:
    # What the credential sweep found while someone held the workflow in n8n (ENGINE-PLAN E17):
    # a key added in their n8n space, or one of the platform's keys changed there. The sweep
    # deleted the key; this says so on the workflow as Needs a fix, until the hold ends.
    op.execute("""
        ALTER TABLE builder.use_cases
            ADD COLUMN n8n_key_finding text,
            ADD COLUMN n8n_key_found_at timestamptz,
            ADD CONSTRAINT use_cases_key_finding_found
                CHECK ((n8n_key_finding IS NULL) = (n8n_key_found_at IS NULL));
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE builder.use_cases
            DROP CONSTRAINT use_cases_key_finding_found,
            DROP COLUMN n8n_key_found_at,
            DROP COLUMN n8n_key_finding;
    """)
