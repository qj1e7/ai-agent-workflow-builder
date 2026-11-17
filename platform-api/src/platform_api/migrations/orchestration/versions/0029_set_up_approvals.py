from alembic import op

revision = "0029"
down_revision = "0028"


def upgrade() -> None:
    # Set-up approvals (ADR 0051): an Approver's yes to set up one revision of a drafted workflow.
    # The same gate decides them as a run's requests (approvals.py), with the same parties and
    # steps, so they are kept apart from approval_requests, which every run path reads. digest is
    # the revision's workflow digest: only that exact document may be set up. ended says why a
    # request ended with no answer: nobody answered by expires_at (ADR 0024), or a new revision
    # replaced it. A request with no decision and no end still waits.
    #
    # Jobs are what the platform does for a request after the person's own step: post it in
    # Teams, show its outcome there, and set the approved revision up in n8n. One job of each kind
    # for a request, keyed by our request id, never n8n's. Each is retried on the run outbox's
    # delays and given up after its last try.
    #
    # A Teams message for a set-up approval has no run, so the practice copy's run_id may be empty.
    op.execute("""
        CREATE TABLE orchestration.setup_requests (
            approval_id text PRIMARY KEY,
            drafted_id text NOT NULL,
            revision integer NOT NULL,
            digest text NOT NULL,
            name text NOT NULL,
            in_short text NOT NULL,
            policy jsonb NOT NULL,
            parties jsonb NOT NULL,
            sent_by text NOT NULL,
            created_at timestamptz NOT NULL,
            expires_at timestamptz NOT NULL,
            ended text CHECK (ended IN ('expired', 'replaced')),
            ended_at timestamptz,
            message jsonb,
            CONSTRAINT setup_requests_ended_has_its_time
                CHECK ((ended IS NULL) = (ended_at IS NULL))
        );
        CREATE INDEX setup_requests_of_drafted ON orchestration.setup_requests (drafted_id);

        CREATE TABLE orchestration.setup_decisions (
            approval_id text NOT NULL REFERENCES orchestration.setup_requests (approval_id),
            step_index integer NOT NULL,
            by text NOT NULL,
            verdict text NOT NULL CHECK (verdict IN ('approve', 'decline')),
            seen_digest text NOT NULL,
            at timestamptz NOT NULL,
            reason text,
            PRIMARY KEY (approval_id, step_index),
            CONSTRAINT setup_decisions_a_decline_says_why
                CHECK ((verdict = 'decline') = (reason IS NOT NULL))
        );

        CREATE TABLE orchestration.setup_jobs (
            approval_id text NOT NULL REFERENCES orchestration.setup_requests (approval_id),
            kind text NOT NULL CHECK (kind IN ('announce', 'outcome', 'set_up')),
            next_at timestamptz NOT NULL,
            attempt integer NOT NULL DEFAULT 0,
            done_at timestamptz,
            gave_up_at timestamptz,
            error text,
            PRIMARY KEY (approval_id, kind)
        );
        CREATE INDEX setup_jobs_due ON orchestration.setup_jobs (next_at)
            WHERE done_at IS NULL AND gave_up_at IS NULL;

        ALTER TABLE orchestration.teams_stub_messages ALTER COLUMN run_id DROP NOT NULL;

        GRANT SELECT, INSERT, UPDATE ON orchestration.setup_requests TO wab_orchestration;
        GRANT SELECT, INSERT ON orchestration.setup_decisions TO wab_orchestration;
        GRANT SELECT, INSERT, UPDATE ON orchestration.setup_jobs TO wab_orchestration;
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM orchestration.teams_stub_messages WHERE run_id IS NULL;
        ALTER TABLE orchestration.teams_stub_messages ALTER COLUMN run_id SET NOT NULL;
        DROP TABLE orchestration.setup_jobs;
        DROP TABLE orchestration.setup_decisions;
        DROP TABLE orchestration.setup_requests;
    """)
