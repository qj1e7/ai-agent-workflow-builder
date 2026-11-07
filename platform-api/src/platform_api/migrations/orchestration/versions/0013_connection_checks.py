from alembic import op

revision = "0013"
down_revision = "0012"


def upgrade() -> None:
    # One row per connection and identity: the last result a person is shown. The identity is the
    # practice copy, or the adapter with a one-way fingerprint of the address and the key, never
    # either one. Only the rows of each connection's identity now are read, so a new address or
    # key starts with no history. A result that differs from the shown one waits in
    # unconfirmed_state until a second agrees, so one failed call does not raise an alarm.
    # last_ok_at keeps the last time it worked. Nothing is kept until something was tried, so
    # "not checked" is never a stored state. The AI model is not kept here: it is read from the
    # model settings on every view.
    op.execute("""
        CREATE TABLE orchestration.connection_checks (
            connection text NOT NULL
                CHECK (connection IN ('jira', 'github', 'teams', 'model')),
            identity text NOT NULL,
            state text NOT NULL
                CHECK (state IN ('working', 'needs_attention', 'not_answering', 'not_set_up')),
            problem text,
            checked_at timestamptz NOT NULL,
            last_ok_at timestamptz,
            expires_at timestamptz,
            key_ends_in text,
            unconfirmed_state text
                CHECK (unconfirmed_state IN
                    ('working', 'needs_attention', 'not_answering', 'not_set_up')),
            PRIMARY KEY (connection, identity)
        );

        GRANT SELECT, INSERT, UPDATE ON orchestration.connection_checks TO wab_orchestration;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE orchestration.connection_checks")
