from alembic import op

revision = "0019"
down_revision = "0018"


def upgrade() -> None:
    # n8n carries each run of a workflow on its own (ENGINE-PLAN 2.3). A start is a nonce our API
    # gives one run of one workflow, used once. An execution joins exactly one run, on its first
    # node call. Each block's first answer or refusal is kept by (execution, block), because n8n
    # repeats a call, a refused one too. A refusal can come before there is any run. A call still
    # working is a claim. joined_by holds whoever joined the run in n8n, such as the holder of a
    # run started by hand there, who may not approve it.
    op.execute("""
        CREATE TABLE orchestration.starts (
            nonce text PRIMARY KEY,
            run_id text NOT NULL REFERENCES orchestration.runs (run_id),
            kind text NOT NULL CHECK (kind IN ('run_now', 'test', 'retry')),
            n8n_workflow_id text NOT NULL,
            issued_at timestamptz NOT NULL,
            expires_at timestamptz NOT NULL,
            used_at timestamptz,
            used_by text,
            CONSTRAINT starts_a_use_names_its_execution
                CHECK ((used_at IS NULL) = (used_by IS NULL))
        );

        CREATE TABLE orchestration.executions (
            execution_id text PRIMARY KEY,
            run_id text NOT NULL REFERENCES orchestration.runs (run_id),
            n8n_workflow_id text NOT NULL,
            mode text NOT NULL,
            retry_of text,
            version_id text,
            linked_at timestamptz NOT NULL
        );
        CREATE INDEX executions_by_run ON orchestration.executions (run_id, linked_at);

        CREATE TABLE orchestration.node_calls (
            execution_id text NOT NULL,
            node_name text NOT NULL,
            run_id text REFERENCES orchestration.runs (run_id),
            kind text NOT NULL
                CHECK (kind IN ('read', 'agent', 'propose', 'ask', 'write', 'tell')),
            attempts integer NOT NULL CHECK (attempts >= 1),
            outcome text NOT NULL CHECK (outcome IN ('working', 'answered', 'refused')),
            call_id text NOT NULL UNIQUE,
            claimed_at timestamptz NOT NULL,
            status integer CHECK (status BETWEEN 400 AND 499),
            answer jsonb,
            actions jsonb NOT NULL DEFAULT '[]',
            answered_at timestamptz,
            PRIMARY KEY (execution_id, node_name),
            CONSTRAINT node_calls_work_has_a_run CHECK (outcome = 'refused' OR run_id IS NOT NULL),
            CONSTRAINT node_calls_only_a_refusal_has_a_status
                CHECK ((outcome = 'refused') = (status IS NOT NULL)),
            CONSTRAINT node_calls_an_answer_has_its_time CHECK (
                (outcome = 'working') = (answer IS NULL)
                AND (outcome = 'working') = (answered_at IS NULL)
            )
        );
        CREATE INDEX node_calls_by_run ON orchestration.node_calls (run_id, node_name);

        ALTER TABLE orchestration.runs ADD COLUMN joined_by jsonb NOT NULL DEFAULT '[]';

        GRANT SELECT, INSERT, UPDATE ON orchestration.starts, orchestration.executions
            TO wab_orchestration;
        GRANT SELECT, INSERT, UPDATE, DELETE ON orchestration.node_calls TO wab_orchestration;
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE orchestration.node_calls;
        DROP TABLE orchestration.executions;
        DROP TABLE orchestration.starts;
        ALTER TABLE orchestration.runs DROP COLUMN joined_by;
    """)
