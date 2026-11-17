from alembic import op

revision = "0023"
down_revision = "0022"


def upgrade() -> None:
    # A drafted workflow's settings and Edit in n8n (ADR 0051, build step 7). made_by says how a
    # revision was made: by the drafter from someone's words, by code from an answer to one of its
    # questions, or read back from n8n after Edit in n8n. Only the drafter's revisions use a
    # model. sources says, for each setting with a value, where the value came from and who gave
    # it: their words, a choice, what they typed, or what they typed in n8n. It holds the
    # Approvers too, which are not the plan's. No key's secret is ever here: a key setting holds
    # only a key's name, which build step 13 fills.
    #
    # in_n8n_id is the workflow n8n holds while someone has the drafted workflow open in their
    # own n8n space, without its keys: in_n8n_by opened it at in_n8n_since, from revision
    # in_n8n_revision. All four are set together, or none.
    op.execute("""
        ALTER TABLE builder.drafted_revisions
            ADD COLUMN made_by text NOT NULL DEFAULT 'drafter'
                CHECK (made_by IN ('drafter', 'answer', 'n8n')),
            ADD COLUMN sources jsonb NOT NULL DEFAULT '{}';

        ALTER TABLE builder.drafted_workflows
            ADD COLUMN in_n8n_id text,
            ADD COLUMN in_n8n_by text,
            ADD COLUMN in_n8n_since timestamptz,
            ADD COLUMN in_n8n_revision integer,
            ADD CONSTRAINT drafted_workflows_in_n8n_whole CHECK (
                (in_n8n_id IS NULL) = (in_n8n_by IS NULL)
                AND (in_n8n_id IS NULL) = (in_n8n_since IS NULL)
                AND (in_n8n_id IS NULL) = (in_n8n_revision IS NULL)
            );
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE builder.drafted_workflows
            DROP CONSTRAINT drafted_workflows_in_n8n_whole,
            DROP COLUMN in_n8n_revision,
            DROP COLUMN in_n8n_since,
            DROP COLUMN in_n8n_by,
            DROP COLUMN in_n8n_id;

        ALTER TABLE builder.drafted_revisions
            DROP COLUMN sources,
            DROP COLUMN made_by;
    """)
