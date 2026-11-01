"""The practice Jira speaks Jira's REST API (ADR 0035).

Its tickets gain Jira's labels and an issue type. A ticket may now be made through the API with
no run behind it, so its run columns may be empty. Each ticket a run made gets the write label the
adapter now looks for, so a retry of an old write finds its ticket.
"""

from alembic import op

revision = "0009"
down_revision = "0008"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE orchestration.mock_jira_tickets
            ADD COLUMN labels text[] NOT NULL DEFAULT '{}',
            ADD COLUMN issue_type text NOT NULL DEFAULT 'Task',
            ALTER COLUMN run_id DROP NOT NULL,
            ALTER COLUMN proposal_id DROP NOT NULL,
            ALTER COLUMN idempotency_key DROP NOT NULL;
        UPDATE orchestration.mock_jira_tickets
            SET labels = ARRAY['wab-' || replace(idempotency_key, '/', '-')]
            WHERE idempotency_key IS NOT NULL;
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE orchestration.mock_jira_tickets SET
            run_id = coalesce(run_id, ''),
            proposal_id = coalesce(proposal_id, ''),
            idempotency_key = coalesce(idempotency_key, 'practice:' || key);
        ALTER TABLE orchestration.mock_jira_tickets
            DROP COLUMN labels,
            DROP COLUMN issue_type,
            ALTER COLUMN run_id SET NOT NULL,
            ALTER COLUMN proposal_id SET NOT NULL,
            ALTER COLUMN idempotency_key SET NOT NULL;
    """)
