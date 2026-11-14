from alembic import op

revision = "0023"
down_revision = "0022"


def upgrade() -> None:
    # Bootstrap sets it when it finds n8n empty, and platform-api clears it once every workflow
    # n8n lost is saved there again from the version the platform kept (ENGINE-PLAN E10).
    op.execute("""
        ALTER TABLE orchestration.engine_status
            ADD COLUMN restore_pending boolean NOT NULL DEFAULT false;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE orchestration.engine_status DROP COLUMN restore_pending;")
