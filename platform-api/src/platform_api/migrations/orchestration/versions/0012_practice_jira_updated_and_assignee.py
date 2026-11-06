"""The practice Jira keeps each ticket's last update and its assignee.

Jira shows both on every ticket. Until now the practice copy answered `updated` from the done
time, so a label change did not move it, and it had no assignee at all.
"""

from alembic import op

revision = "0012"
down_revision = "0011"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE orchestration.mock_jira_tickets
            ADD COLUMN updated_at timestamptz,
            ADD COLUMN assignee text;
        UPDATE orchestration.mock_jira_tickets SET updated_at = coalesce(done_at, created_at);
        ALTER TABLE orchestration.mock_jira_tickets ALTER COLUMN updated_at SET NOT NULL;
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE orchestration.mock_jira_tickets
            DROP COLUMN assignee,
            DROP COLUMN updated_at;
    """)
