from alembic import op

revision = "0016"
down_revision = "0015"


def upgrade() -> None:
    # How a version that is not a schedule change came about (ENGINE-PLAN 2.5): published in n8n
    # by a person there, its settings changed in n8n with no publish (n8n runs the live version
    # with the workflow's settings now), a roll back, or the yes put back from the Portal, with
    # who did it from
    # the Portal and where. A version that republishes another's workflow keeps every author of
    # that workflow, its publisher and theirs before it, because a run of it is their work as
    # well (ADR 0026); each copy of a version row carries them on. A version that
    # did not grade safe keeps the safety checker's words for why. A workflow n8n no
    # longer has is marked, and its runs and versions are kept (D7). Publishing an earlier
    # version leaves n8n's draft where it was, so the draft the platform last saw is kept apart
    # from the version in use, and the version compare checks the draft against it.
    op.execute("""
        ALTER TABLE builder.use_case_versions
            ADD COLUMN made text
                CHECK (made IN (
                    'published_in_n8n', 'settings_changed_in_n8n', 'rolled_back', 'yes_put_back'
                )),
            ADD COLUMN made_by text,
            ADD COLUMN made_via text CHECK (made_via IN ('page', 'chat')),
            ADD COLUMN back_to integer CHECK (back_to > 0 AND back_to < version),
            ADD COLUMN also jsonb NOT NULL DEFAULT '[]'::jsonb
                CHECK (jsonb_typeof(also) = 'array'),
            ADD COLUMN findings jsonb,
            ADD CONSTRAINT use_case_versions_made_whole CHECK (
                (made IS NULL OR made IN ('published_in_n8n', 'settings_changed_in_n8n'))
                    = (made_by IS NULL)
                AND (made IS NULL OR made IN ('published_in_n8n', 'settings_changed_in_n8n'))
                    = (made_via IS NULL)
                AND (made = 'rolled_back') = (back_to IS NOT NULL)
            );
        ALTER TABLE builder.use_cases
            ADD COLUMN deleted_in_n8n_at timestamptz,
            ADD COLUMN n8n_draft_id text;
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE builder.use_cases
            DROP COLUMN n8n_draft_id,
            DROP COLUMN deleted_in_n8n_at;
        ALTER TABLE builder.use_case_versions
            DROP CONSTRAINT use_case_versions_made_whole,
            DROP COLUMN findings,
            DROP COLUMN also,
            DROP COLUMN back_to,
            DROP COLUMN made_via,
            DROP COLUMN made_by,
            DROP COLUMN made;
    """)
