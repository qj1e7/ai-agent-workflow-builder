from alembic import op

revision = "0016"
down_revision = "0015"


def upgrade() -> None:
    # The Jira site each ticket was proposed for, the only one it can be written in (ADR 0041).
    # Rows from before this have none. They are not filled in as the practice Jira: the watchlist
    # asks no Jira about them, as the safety checker refuses a write with no site.
    op.execute("ALTER TABLE orchestration.proposed_tickets ADD COLUMN site text;")


def downgrade() -> None:
    op.execute("ALTER TABLE orchestration.proposed_tickets DROP COLUMN site;")
