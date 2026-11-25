from alembic import op

revision = "0028"
down_revision = "0027"


def upgrade() -> None:
    # Refining a drafted workflow's Check (ADR 0054, section 7, PR 8): one row for each
    # refinement an Operator asked for, of one revision (revision, digest). platform-api keeps it
    # before it mints the refinement's token, with the same ends_by. Its id has a fix's shape,
    # since the coordinator runs it as a fix of a draft, but it is never in builder.fixes.
    #
    # refined_revision is the revision it kept from the refined plan, with its digest and the
    # plan's key, so asking again with the same plan answers the same. unchanged says every case
    # passed on the draft as checked, so nothing new was kept. proposed_at is when its proposal
    # was taken, and handed_back_at and handed_back_why when its hand-back was. One whose
    # deadline passed with neither counts as given up for time. writer_calls and explainer_calls
    # are platform-api's own count of its model calls, and simulated each simulation
    # platform-api ran for it, by the plan's key, so a refined plan is kept only once one passed.
    #
    # A Check has no run, so a refinement's events are kept here, by the refinement, never in a
    # run's activity log: each kind once for each hand-off or round, as a fix's are on a run.
    #
    # A revision a refinement kept is made by code, with no model: made_by 'refined'.
    op.execute("""
        CREATE TABLE builder.drafted_refinements (
            fix_id text PRIMARY KEY,
            drafted_id text NOT NULL REFERENCES builder.drafted_workflows (drafted_id),
            revision integer NOT NULL,
            digest text NOT NULL,
            asked_by text NOT NULL,
            started_at timestamptz NOT NULL,
            ends_by timestamptz NOT NULL,
            refined_revision integer,
            refined_digest text,
            refined_key text,
            unchanged boolean NOT NULL DEFAULT false,
            proposed_at timestamptz,
            handed_back_at timestamptz,
            handed_back_why text,
            writer_calls integer NOT NULL DEFAULT 0,
            explainer_calls integer NOT NULL DEFAULT 0,
            simulated jsonb NOT NULL DEFAULT '{}'::jsonb,
            UNIQUE (drafted_id, revision)
        );
        CREATE INDEX drafted_refinements_by_drafted
            ON builder.drafted_refinements (drafted_id, started_at DESC);
        CREATE TABLE builder.drafted_refinement_events (
            fix_id text NOT NULL REFERENCES builder.drafted_refinements (fix_id),
            kind text NOT NULL
                CHECK (kind IN ('fix_handoff', 'fix_round', 'fix_proposed', 'fix_handed_back')),
            number integer NOT NULL,
            data jsonb NOT NULL,
            at timestamptz NOT NULL,
            PRIMARY KEY (fix_id, kind, number)
        );
        GRANT SELECT, INSERT, UPDATE ON builder.drafted_refinements TO wab_builder;
        GRANT SELECT, INSERT ON builder.drafted_refinement_events TO wab_builder;
        ALTER TABLE builder.drafted_revisions
            DROP CONSTRAINT drafted_revisions_made_by_check,
            ADD CONSTRAINT drafted_revisions_made_by_check
                CHECK (made_by IN ('drafter', 'answer', 'n8n', 'refined'));
    """)


def downgrade() -> None:
    # A refined revision can't be read by the code before this one, so the downgrade refuses
    # while one is kept, rather than delete it.
    op.execute("""
        ALTER TABLE builder.drafted_revisions
            DROP CONSTRAINT drafted_revisions_made_by_check,
            ADD CONSTRAINT drafted_revisions_made_by_check
                CHECK (made_by IN ('drafter', 'answer', 'n8n'));
        DROP TABLE builder.drafted_refinement_events;
        DROP TABLE builder.drafted_refinements;
    """)
