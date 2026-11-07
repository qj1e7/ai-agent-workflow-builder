from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE builder.team_requests (
            request_id text PRIMARY KEY,
            kind text NOT NULL CHECK (kind IN ('ask_the_team', 'support')),
            about jsonb NOT NULL,
            note text NOT NULL,
            asked_by text NOT NULL,
            asked_by_name text NOT NULL,
            asked_at timestamptz NOT NULL,
            idempotency_key text NOT NULL,
            status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'answered', 'done')),
            done_at timestamptz,
            teams_post text NOT NULL DEFAULT 'failed'
                CHECK (teams_post IN ('posted', 'no_channel', 'failed')),
            UNIQUE (asked_by, idempotency_key),
            CONSTRAINT team_requests_done_has_a_time
                CHECK ((status = 'done') = (done_at IS NOT NULL))
        );

        CREATE INDEX team_requests_by_asker ON builder.team_requests (asked_by, asked_at DESC);

        CREATE TABLE builder.team_request_replies (
            reply_id text PRIMARY KEY,
            request_id text NOT NULL REFERENCES builder.team_requests (request_id),
            replied_by text NOT NULL,
            replied_by_name text NOT NULL,
            replied_at timestamptz NOT NULL,
            text text NOT NULL,
            status text NOT NULL CHECK (status IN ('answered', 'done'))
        );

        CREATE INDEX team_request_replies_by_request
            ON builder.team_request_replies (request_id, replied_at);

        GRANT SELECT, INSERT, UPDATE ON builder.team_requests TO wab_builder;
        GRANT SELECT, INSERT ON builder.team_request_replies TO wab_builder;
    """)


def downgrade() -> None:
    """Drops every team request and reply, so what people asked and what the team answered is
    lost. Take the routes off first and keep the tables (plan item N14's rollback), unless the
    requests are meant to go."""
    op.execute("""
        DROP TABLE builder.team_request_replies;
        DROP TABLE builder.team_requests;
    """)
