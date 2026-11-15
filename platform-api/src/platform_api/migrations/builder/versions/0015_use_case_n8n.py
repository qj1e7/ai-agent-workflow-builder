from alembic import op

revision = "0015"
down_revision = "0014"


def upgrade() -> None:
    # Each use case's own n8n workflow, and who has it open in n8n (ENGINE-PLAN 2.4). Each
    # version keeps n8n's version id, who published it and where, the safety checker's grade, and
    # the workflow itself: n8n Community keeps history for a day only, so this is the record.
    op.execute("""
        ALTER TABLE builder.use_cases
            ADD COLUMN n8n_workflow_id text UNIQUE,
            ADD COLUMN held_by text,
            ADD COLUMN held_since timestamptz,
            ADD CONSTRAINT use_cases_own_has_workflow
                CHECK (engine = 'shared_run' OR n8n_workflow_id IS NOT NULL);
        ALTER TABLE builder.use_case_versions
            ADD COLUMN n8n_version_id text,
            ADD COLUMN published_by text,
            ADD COLUMN published_in text CHECK (published_in IN ('portal', 'n8n')),
            ADD COLUMN grade text CHECK (grade IN ('safe', 'writes_refused', 'needs_a_fix')),
            ADD COLUMN document jsonb,
            ADD CONSTRAINT use_case_versions_n8n_whole
                CHECK ((n8n_version_id IS NULL) = (document IS NULL)
                    AND (n8n_version_id IS NULL) = (grade IS NULL));
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE builder.use_case_versions
            DROP CONSTRAINT use_case_versions_n8n_whole,
            DROP COLUMN document,
            DROP COLUMN grade,
            DROP COLUMN published_in,
            DROP COLUMN published_by,
            DROP COLUMN n8n_version_id;
        ALTER TABLE builder.use_cases
            DROP CONSTRAINT use_cases_own_has_workflow,
            DROP COLUMN held_since,
            DROP COLUMN held_by,
            DROP COLUMN n8n_workflow_id;
    """)
