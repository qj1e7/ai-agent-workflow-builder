from alembic import op

revision = "0014"
down_revision = "0013"


def upgrade() -> None:
    # Which engine carries a use case while use cases move to n8n one at a time (ENGINE-PLAN
    # 2.4): the shared run workflow of today, or an n8n workflow of its own. Every use case from
    # before stays on the shared one.
    op.execute("""
        ALTER TABLE builder.use_cases
            ADD COLUMN engine text NOT NULL DEFAULT 'shared_run'
                CHECK (engine IN ('shared_run', 'own'));
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE builder.use_cases DROP COLUMN engine")
