from alembic import op

revision = "0027"
down_revision = "0026"


def upgrade() -> None:
    # Who made each workflow that leaves a member's own n8n space without being registered
    # (ENGINE-PLAN E15): the ones still in a person's space when their account ends, which n8n
    # moves to the platform's project, and one a registration is moving. n8n keeps no maker of
    # its own, and empties the publish timeline's user once an account is deleted, so this is the
    # only record of whose work such a workflow is. The first maker noted stays.
    op.execute("""
        CREATE TABLE orchestration.n8n_makers (
            workflow_id text PRIMARY KEY,
            made_by text NOT NULL,
            n8n_user_id text NOT NULL,
            noted_at timestamptz NOT NULL
        );

        GRANT SELECT, INSERT ON orchestration.n8n_makers TO wab_orchestration;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE orchestration.n8n_makers")
