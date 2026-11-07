from alembic import op

revision = "0013"
down_revision = "0012"


def upgrade() -> None:
    # One row per connection: the last result a person is shown. A result that differs from the
    # shown one waits in unconfirmed_state until a second check agrees, so one failed call does
    # not raise an alarm. last_ok_at keeps the last time the connection worked. The AI model is not
    # kept here: it is read from the model settings on every view. source says which copy made the
    # row (the practice copy, or an adapter with a one-way fingerprint of its address). A row made
    # by another source than the current one is never shown, so going live starts clean.
    op.execute("""
        CREATE TABLE orchestration.connection_checks (
            connection text PRIMARY KEY
                CHECK (connection IN ('jira', 'github', 'teams', 'model')),
            source text NOT NULL,
            state text NOT NULL
                CHECK (state IN
                    ('working', 'needs_attention', 'not_answering', 'not_set_up', 'not_checked')),
            problem text,
            checked_at timestamptz NOT NULL,
            last_ok_at timestamptz,
            expires_at timestamptz,
            key_ends_in text,
            unconfirmed_state text
                CHECK (unconfirmed_state IN
                    ('working', 'needs_attention', 'not_answering', 'not_set_up', 'not_checked'))
        );

        GRANT SELECT, INSERT, UPDATE ON orchestration.connection_checks TO wab_orchestration;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE orchestration.connection_checks")
