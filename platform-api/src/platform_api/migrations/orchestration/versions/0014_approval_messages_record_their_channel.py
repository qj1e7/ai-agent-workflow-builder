from alembic import op

revision = "0014"
down_revision = "0013"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE orchestration.approval_messages RENAME COLUMN adapter TO identity;
        ALTER TABLE orchestration.approval_messages ALTER COLUMN identity DROP DEFAULT;
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE orchestration.approval_messages SET identity = split_part(identity, ':', 1);
        ALTER TABLE orchestration.approval_messages ALTER COLUMN identity SET DEFAULT 'practice';
        ALTER TABLE orchestration.approval_messages RENAME COLUMN identity TO adapter;
    """)
