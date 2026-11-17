from alembic import op

revision = "0030"
down_revision = "0029"


def upgrade() -> None:
    # The n8n version the last bootstrap read from n8n itself. The workflow drafter's catalogue
    # names the n8n image it was made from, and drafting pauses while the two differ (ADR 0051,
    # section 8).
    op.execute("ALTER TABLE orchestration.engine_status ADD COLUMN n8n_version text")


def downgrade() -> None:
    op.execute("ALTER TABLE orchestration.engine_status DROP COLUMN n8n_version")
