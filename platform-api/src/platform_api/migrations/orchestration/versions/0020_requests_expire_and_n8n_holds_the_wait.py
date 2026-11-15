from alembic import op

revision = "0020"
down_revision = "0019"


def upgrade() -> None:
    # A request keeps the expiry it was made with (ADR 0024), and ends undecided when it passes or
    # its workflow is deleted (ENGINE-PLAN D7). A request made before has no expiry. When n8n holds
    # the wait, the request names the waiting execution and keeps its resume address sealed. A wake
    # is one outbox row per request: the key makes a second row impossible.
    op.execute("""
        ALTER TABLE orchestration.approval_requests
            ADD COLUMN expires_at timestamptz,
            ADD COLUMN ended text CHECK (ended IN ('expired', 'cancelled')),
            ADD COLUMN ended_at timestamptz,
            ADD COLUMN execution_id text,
            ADD COLUMN resume_url text,
            ADD CONSTRAINT approval_requests_an_end_has_its_time
                CHECK ((ended IS NULL) = (ended_at IS NULL)),
            ADD CONSTRAINT approval_requests_a_held_wait_is_whole
                CHECK ((execution_id IS NULL) = (resume_url IS NULL));
        CREATE INDEX approval_requests_waiting_to_expire
            ON orchestration.approval_requests (expires_at)
            WHERE ended IS NULL AND expires_at IS NOT NULL;

        ALTER TABLE orchestration.outbox ADD COLUMN idempotency_key text;
        CREATE UNIQUE INDEX outbox_once ON orchestration.outbox (idempotency_key)
            WHERE idempotency_key IS NOT NULL;
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX orchestration.outbox_once;
        ALTER TABLE orchestration.outbox DROP COLUMN idempotency_key;
        DROP INDEX orchestration.approval_requests_waiting_to_expire;
        ALTER TABLE orchestration.approval_requests
            DROP COLUMN resume_url,
            DROP COLUMN execution_id,
            DROP COLUMN ended_at,
            DROP COLUMN ended,
            DROP COLUMN expires_at;
    """)
