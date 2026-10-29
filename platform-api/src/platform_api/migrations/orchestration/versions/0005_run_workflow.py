from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    # Every run used the n8n workflow release_check. It is now called run, and a waiting run
    # names its workflow when it is approved or retried, so the saved name moves with it.
    op.execute("""
        UPDATE orchestration.runs
        SET spec = jsonb_set(spec, '{workflow}', '"run"')
        WHERE spec ->> 'workflow' = 'release_check';

        UPDATE orchestration.outbox
        SET payload = jsonb_set(payload, '{workflow}', '"run"')
        WHERE status = 'pending' AND payload ->> 'workflow' = 'release_check';
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE orchestration.runs
        SET spec = jsonb_set(spec, '{workflow}', '"release_check"')
        WHERE spec ->> 'workflow' = 'run';

        UPDATE orchestration.outbox
        SET payload = jsonb_set(payload, '{workflow}', '"release_check"')
        WHERE status = 'pending' AND payload ->> 'workflow' = 'run';
    """)
