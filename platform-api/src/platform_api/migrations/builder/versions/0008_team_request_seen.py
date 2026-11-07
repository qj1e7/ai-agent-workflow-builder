from alembic import op

revision = "0008"
down_revision = "0007"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE builder.team_requests ADD COLUMN asker_seen_at timestamptz;

        UPDATE builder.team_requests SET asker_seen_at = now();

        GRANT UPDATE (asker_seen_at) ON builder.team_requests TO wab_builder;

        ALTER TABLE builder.team_request_replies
            DROP CONSTRAINT team_request_replies_status_check;
        ALTER TABLE builder.team_request_replies
            ADD CONSTRAINT team_request_replies_status_check
            CHECK (status IN ('answered', 'done', 'added'));
        UPDATE builder.team_request_replies p SET status = 'added'
            FROM builder.team_requests r
            WHERE p.request_id = r.request_id AND p.replied_by = r.asked_by
                AND p.status = 'answered';
    """)


def downgrade() -> None:
    """Forgets which replies the askers have opened. Every reply then reads as new to its asker
    if the column comes back. A note an asker added to their own request goes back to
    `answered`, as 0007 stored it."""
    op.execute("""
        UPDATE builder.team_request_replies SET status = 'answered' WHERE status = 'added';
        ALTER TABLE builder.team_request_replies
            DROP CONSTRAINT team_request_replies_status_check;
        ALTER TABLE builder.team_request_replies
            ADD CONSTRAINT team_request_replies_status_check
            CHECK (status IN ('answered', 'done'));
        ALTER TABLE builder.team_requests DROP COLUMN asker_seen_at;
    """)
