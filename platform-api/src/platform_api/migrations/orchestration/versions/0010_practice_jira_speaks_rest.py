"""The practice Jira speaks Jira's REST API (ADR 0035).

Its tickets gain Jira's labels, an issue type and the account that made them. A ticket may now be
made through the API with no run behind it, so its run columns may be empty. Each ticket a run
made gets its write label, and the platform's practice account as its maker.

orchestration.jira_writes is the Jira connector's own record of each write key: when it began to
make the ticket, which try holds it now, and, once Jira answered, the ticket's key. A retry trusts
this record, never a label in Jira that anyone could add.
"""

from alembic import op

revision = "0010"
down_revision = "0009"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE orchestration.mock_jira_tickets
            ADD COLUMN labels text[] NOT NULL DEFAULT '{}',
            ADD COLUMN issue_type text NOT NULL DEFAULT 'Task',
            ADD COLUMN creator text,
            ALTER COLUMN run_id DROP NOT NULL,
            ALTER COLUMN proposal_id DROP NOT NULL,
            ALTER COLUMN idempotency_key DROP NOT NULL;
        UPDATE orchestration.mock_jira_tickets
            SET labels = ARRAY['wab-' || replace(idempotency_key, '/', '-')],
                creator = 'wab-platform'
            WHERE idempotency_key IS NOT NULL;

        CREATE TABLE orchestration.jira_writes (
            idempotency_key text PRIMARY KEY,
            started_at timestamptz NOT NULL,
            ticket_key text,
            claimed_at timestamptz
        );
        INSERT INTO orchestration.jira_writes (idempotency_key, started_at, ticket_key)
            SELECT idempotency_key, started_at, external_reference
            FROM orchestration.write_executions
            WHERE status = 'done' AND idempotency_key IS NOT NULL;
        -- A ticket from a write whose gateway record never said done, as after an old crash,
        -- is that write's ticket too, so a retry does not make a second one.
        INSERT INTO orchestration.jira_writes (idempotency_key, started_at, ticket_key)
            SELECT idempotency_key, created_at, key FROM orchestration.mock_jira_tickets
            WHERE idempotency_key IS NOT NULL
            ON CONFLICT (idempotency_key) DO NOTHING;
        GRANT SELECT, INSERT, UPDATE, DELETE ON orchestration.jira_writes TO wab_orchestration;
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE orchestration.jira_writes;
        UPDATE orchestration.mock_jira_tickets SET
            run_id = coalesce(run_id, ''),
            proposal_id = coalesce(proposal_id, ''),
            idempotency_key = coalesce(idempotency_key, 'practice:' || key);
        ALTER TABLE orchestration.mock_jira_tickets
            DROP COLUMN labels,
            DROP COLUMN issue_type,
            DROP COLUMN creator,
            ALTER COLUMN run_id SET NOT NULL,
            ALTER COLUMN proposal_id SET NOT NULL,
            ALTER COLUMN idempotency_key SET NOT NULL;
    """)
