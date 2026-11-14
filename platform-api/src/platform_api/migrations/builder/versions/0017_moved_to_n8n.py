from alembic import op

revision = "0017"
down_revision = "0016"

MADE = "made IN ('published_in_n8n', 'rolled_back', 'yes_put_back'{more})"
NOBODY = "(made IS NULL OR made IN ('published_in_n8n'{more}))"


def upgrade() -> None:
    # The version that moved a workflow off the shared run workflow is the platform's, made by
    # nobody in the Portal (ENGINE-PLAN E10).
    op.execute(f"""
        ALTER TABLE builder.use_case_versions
            DROP CONSTRAINT use_case_versions_made_check,
            ADD CONSTRAINT use_case_versions_made_check
                CHECK ({MADE.format(more=", 'moved_to_n8n'")}),
            DROP CONSTRAINT use_case_versions_made_whole,
            ADD CONSTRAINT use_case_versions_made_whole CHECK (
                {NOBODY.format(more=", 'moved_to_n8n'")} = (made_by IS NULL)
                AND {NOBODY.format(more=", 'moved_to_n8n'")} = (made_via IS NULL)
                AND (made = 'rolled_back') = (back_to IS NOT NULL)
            );
    """)


def downgrade() -> None:
    op.execute(f"""
        UPDATE builder.use_case_versions SET made = NULL WHERE made = 'moved_to_n8n';
        ALTER TABLE builder.use_case_versions
            DROP CONSTRAINT use_case_versions_made_check,
            ADD CONSTRAINT use_case_versions_made_check CHECK ({MADE.format(more="")}),
            DROP CONSTRAINT use_case_versions_made_whole,
            ADD CONSTRAINT use_case_versions_made_whole CHECK (
                {NOBODY.format(more="")} = (made_by IS NULL)
                AND {NOBODY.format(more="")} = (made_via IS NULL)
                AND (made = 'rolled_back') = (back_to IS NOT NULL)
            );
    """)
