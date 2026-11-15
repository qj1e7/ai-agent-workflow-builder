from alembic import op

revision = "0017"
down_revision = "0016"

MADE = (
    "made IN ('published_in_n8n', 'settings_changed_in_n8n', 'rolled_back', 'yes_put_back'{more})"
)
NOBODY = "(made IS NULL OR made IN ('published_in_n8n', 'settings_changed_in_n8n'{more}))"


def upgrade() -> None:
    # The version that moved a workflow off the shared run workflow is the platform's, made by
    # nobody in the Portal (ENGINE-PLAN E10). Bootstrap asks for a restore when it finds n8n
    # empty, and platform-api answers the ask once every workflow n8n lost is back. A workflow
    # that cannot move keeps why, in the words its page shows; one being restored keeps the
    # workflow saved for it until it is live, so a restore cut off is finished by the next.
    op.execute(f"""
        CREATE TABLE builder.n8n_restore (
            id integer PRIMARY KEY CHECK (id = 1),
            asked_at timestamptz NOT NULL,
            missing text[] NOT NULL DEFAULT '{{}}'
        );
        GRANT SELECT, DELETE ON builder.n8n_restore TO wab_builder;
        ALTER TABLE builder.use_cases
            ADD COLUMN move_refused text,
            ADD COLUMN restoring_in_n8n text;
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
        DROP TABLE builder.n8n_restore;
        ALTER TABLE builder.use_cases DROP COLUMN move_refused, DROP COLUMN restoring_in_n8n;
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
