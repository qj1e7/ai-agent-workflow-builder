from alembic import op

revision = "0001"
down_revision = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE orchestration.runs (
            run_id text PRIMARY KEY,
            use_case_id text NOT NULL,
            idempotency_key text NOT NULL,
            spec jsonb NOT NULL,
            started_by text NOT NULL,
            started_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            version integer NOT NULL DEFAULT 1,
            state text NOT NULL,
            state_data jsonb NOT NULL,
            deadline_at timestamptz,
            retried_by jsonb NOT NULL DEFAULT '[]'::jsonb,
            carry_forward jsonb,
            UNIQUE (use_case_id, idempotency_key)
        );
        CREATE INDEX runs_deadline ON orchestration.runs (deadline_at)
            WHERE deadline_at IS NOT NULL;
        CREATE INDEX runs_use_case ON orchestration.runs (use_case_id, started_at DESC);

        CREATE TABLE orchestration.leg_attempts (
            run_id text NOT NULL REFERENCES orchestration.runs (run_id),
            leg text NOT NULL,
            attempt integer NOT NULL,
            n8n_execution_id text,
            recorded_at timestamptz NOT NULL,
            PRIMARY KEY (run_id, leg, attempt)
        );
        CREATE INDEX leg_attempts_execution ON orchestration.leg_attempts (n8n_execution_id);

        CREATE TABLE orchestration.proposals (
            proposal_id text PRIMARY KEY,
            run_id text NOT NULL REFERENCES orchestration.runs (run_id),
            actions jsonb NOT NULL,
            digest text NOT NULL,
            created_at timestamptz NOT NULL
        );

        CREATE TABLE orchestration.approval_requests (
            approval_id text PRIMARY KEY,
            run_id text NOT NULL REFERENCES orchestration.runs (run_id),
            proposal_id text NOT NULL REFERENCES orchestration.proposals (proposal_id),
            digest text NOT NULL,
            policy jsonb NOT NULL,
            parties jsonb NOT NULL,
            created_at timestamptz NOT NULL
        );

        CREATE TABLE orchestration.approval_decisions (
            approval_id text NOT NULL REFERENCES orchestration.approval_requests (approval_id),
            step_index integer NOT NULL,
            decided_by text NOT NULL,
            verdict text NOT NULL,
            seen_digest text NOT NULL,
            decided_at timestamptz NOT NULL,
            PRIMARY KEY (approval_id, step_index)
        );

        CREATE TABLE orchestration.write_executions (
            proposal_id text NOT NULL REFERENCES orchestration.proposals (proposal_id),
            action_index integer NOT NULL,
            run_id text NOT NULL,
            idempotency_key text NOT NULL UNIQUE,
            status text NOT NULL CHECK (status IN ('started', 'done')),
            started_at timestamptz NOT NULL,
            done_at timestamptz,
            external_reference text,
            PRIMARY KEY (proposal_id, action_index)
        );

        CREATE TABLE orchestration.outbox (
            id bigserial PRIMARY KEY,
            run_id text NOT NULL REFERENCES orchestration.runs (run_id),
            kind text NOT NULL,
            payload jsonb NOT NULL,
            attempt integer NOT NULL DEFAULT 0,
            next_at timestamptz NOT NULL,
            status text NOT NULL CHECK (status IN ('pending', 'sent', 'cancelled', 'given_up')),
            last_error text,
            created_at timestamptz NOT NULL
        );
        CREATE INDEX outbox_due ON orchestration.outbox (next_at) WHERE status = 'pending';

        CREATE TABLE orchestration.engine_status (
            id integer PRIMARY KEY CHECK (id = 1),
            loaded_at timestamptz NOT NULL,
            ready boolean NOT NULL,
            detail text NOT NULL,
            workflows jsonb NOT NULL
        );

        CREATE TABLE orchestration.mock_jira_tickets (
            key text PRIMARY KEY,
            number integer NOT NULL UNIQUE,
            project text NOT NULL,
            title text NOT NULL,
            body text NOT NULL,
            created_at timestamptz NOT NULL,
            run_id text NOT NULL,
            proposal_id text NOT NULL,
            idempotency_key text NOT NULL UNIQUE
        );

        CREATE TABLE orchestration.teams_stub_messages (
            id text PRIMARY KEY,
            ts timestamptz NOT NULL,
            channel text NOT NULL,
            text text NOT NULL,
            link text NOT NULL,
            run_id text NOT NULL,
            approval_id text NOT NULL UNIQUE
        );

        GRANT USAGE ON SCHEMA orchestration TO wab_orchestration;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA orchestration
            TO wab_orchestration;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA orchestration TO wab_orchestration;
    """)


def downgrade() -> None:
    op.execute("DROP SCHEMA orchestration CASCADE")
