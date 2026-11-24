from alembic import op

revision = "0025"
down_revision = "0024"

MADE = (
    "made IN ('published_in_n8n', 'settings_changed_in_n8n', 'rolled_back', 'yes_put_back',"
    " 'moved_to_n8n'{more})"
)


def upgrade() -> None:
    # Fix it for me (ADR 0055, PR 6): one row for each fix an Operator asked for on a stopped run
    # of a drafted workflow. platform-api writes the fix's start in the run's log before the row
    # goes in, and mints the fix's token only after both, with the same ends_by.
    #
    # The fixed version is stored here under the fix id, once, with the cause code confirmed:
    # plan, the document code laid out from it, its digest and version, the version it would be
    # once turned on. made_by says who made the change: the Fix drafter, or a person who answered
    # the question a hand-back asked. A stored version waits for a yes only once the fix's
    # proposal named it (proposed_at) and its set-up approval was sent (approval_id), so a store
    # nobody proposed never waits. The next start for the workflow drops it (never_proposed).
    #
    # handed_back_at is when the log took the fix's hand-back. A fix whose deadline passed with
    # neither counts as handed back for time, as the log says. approved_at is when its set-up
    # approval's yes came. dropped_why says why a fix stopped counting: declined, expired, stale
    # (a new version of the workflow came first) or never_proposed. writer_calls and
    # explainer_calls are platform-api's own count of the Scenario writer's and the explainer's
    # model calls for the fix. simulated holds each simulation platform-api ran for it, by the
    # plan's key, so a store needs one that passed. Turn back on records who pressed it and the
    # test run, which writes nothing, then when the fixed version went live, or that the test run
    # failed, or why it couldn't go live (turn_on_problem). stays_paused says a workflow an
    # Operator paused kept paused, with the fix as its version in use. name and stop are the
    # workflow's name
    # and the stop as the run's log held them when the fix was asked for.
    op.execute(f"""
        CREATE TABLE builder.fixes (
            fix_id text PRIMARY KEY,
            run_id text NOT NULL,
            use_case_id text NOT NULL,
            drafted_id text NOT NULL REFERENCES builder.drafted_workflows (drafted_id),
            name text NOT NULL,
            stopped_version integer NOT NULL,
            stopped_at text[] NOT NULL,
            stop jsonb NOT NULL,
            asked_by text NOT NULL,
            asked_by_name text NOT NULL,
            started_at timestamptz NOT NULL,
            ends_by timestamptz NOT NULL,
            plan jsonb,
            document jsonb,
            digest text,
            version integer,
            cause jsonb,
            made_by text CHECK (made_by IN ('fix_drafter', 'answer')),
            answered_by text,
            stored_at timestamptz,
            proposed_at timestamptz,
            approval_id text,
            handed_back_at timestamptz,
            handed_back_why text,
            approved_at timestamptz,
            dropped_at timestamptz,
            dropped_why text
                CHECK (dropped_why IN ('declined', 'expired', 'stale', 'never_proposed')),
            writer_calls integer NOT NULL DEFAULT 0,
            explainer_calls integer NOT NULL DEFAULT 0,
            simulated jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            test_run_id text,
            test_draft text,
            testing_by text,
            testing_at timestamptz,
            turned_on_at timestamptz,
            test_failed_at timestamptz,
            turn_on_problem text,
            stays_paused boolean NOT NULL DEFAULT false,
            CONSTRAINT fixes_stored_whole CHECK (
                (stored_at IS NULL) = (plan IS NULL)
                AND (plan IS NULL) = (document IS NULL)
                AND (document IS NULL) = (digest IS NULL)
                AND (digest IS NULL) = (version IS NULL)
                AND (digest IS NULL) = (made_by IS NULL)
            ),
            CONSTRAINT fixes_proposed_was_stored
                CHECK (proposed_at IS NULL OR stored_at IS NOT NULL),
            CONSTRAINT fixes_dropped_says_why CHECK ((dropped_at IS NULL) = (dropped_why IS NULL))
        );
        CREATE INDEX fixes_use_case ON builder.fixes (use_case_id, started_at DESC);
        GRANT SELECT, INSERT, UPDATE ON builder.fixes TO wab_builder;

        ALTER TABLE builder.use_case_versions
            DROP CONSTRAINT use_case_versions_made_check,
            ADD CONSTRAINT use_case_versions_made_check CHECK ({MADE.format(more=", 'fixed'")});
    """)


def downgrade() -> None:
    op.execute(f"""
        DROP TABLE builder.fixes;
        ALTER TABLE builder.use_case_versions
            DROP CONSTRAINT use_case_versions_made_check,
            ADD CONSTRAINT use_case_versions_made_check CHECK ({MADE.format(more="")});
    """)
