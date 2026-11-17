from alembic import op

revision = "0022"
down_revision = "0021"


def upgrade() -> None:
    # Drafted workflows (ADR 0051): what the workflow drafter wrote, with every change made to it,
    # before it is set up. Not builder.drafts, which keeps a set-up card someone saved to come back
    # to. use_case_id is the id the workflow gets once it is set up, kept from the first draft so
    # its Sticky Note can link to it and its blocks' ids never change. set_up_at says the approved
    # revision is set up as that use case; set_up_problem says why the last try to set it up did
    # not, in words to show.
    #
    # Each revision is one whole plan, in its own row, never changed once drafted. A revision is
    # drafting while the drafter works, drafted with its plan and the document code laid out from
    # it, or not_drafted with the words the person sees. digest binds a set-up approval to the
    # document (orchestration.workflow_digest). asked_by is who asked for it: the first is the
    # person who described the task, each later one the person who asked for a change. Both are
    # parties to its set-up approval.
    op.execute("""
        CREATE TABLE builder.drafted_workflows (
            drafted_id text PRIMARY KEY,
            owner text NOT NULL,
            created_at timestamptz NOT NULL,
            use_case_id text NOT NULL UNIQUE,
            set_up_at timestamptz,
            set_up_problem text,
            idempotency_key text,
            UNIQUE (owner, idempotency_key)
        );

        CREATE TABLE builder.drafted_revisions (
            drafted_id text NOT NULL REFERENCES builder.drafted_workflows (drafted_id),
            revision integer NOT NULL CHECK (revision >= 1),
            asked_by text NOT NULL,
            words text NOT NULL,
            started_at timestamptz NOT NULL,
            state text NOT NULL CHECK (state IN ('drafting', 'drafted', 'not_drafted')),
            finished_at timestamptz,
            plan jsonb,
            catalogue text,
            document jsonb,
            digest text,
            grade text,
            findings jsonb,
            said text,
            PRIMARY KEY (drafted_id, revision),
            CONSTRAINT drafted_revisions_drafted_has_its_document
                CHECK ((state = 'drafted') = (document IS NOT NULL AND digest IS NOT NULL)),
            CONSTRAINT drafted_revisions_not_drafted_says_why
                CHECK ((state = 'not_drafted') = (said IS NOT NULL)),
            CONSTRAINT drafted_revisions_finished
                CHECK ((state = 'drafting') = (finished_at IS NULL))
        );

        GRANT SELECT, INSERT, UPDATE ON builder.drafted_workflows TO wab_builder;
        GRANT SELECT, INSERT, UPDATE ON builder.drafted_revisions TO wab_builder;
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE builder.drafted_revisions;
        DROP TABLE builder.drafted_workflows;
    """)
