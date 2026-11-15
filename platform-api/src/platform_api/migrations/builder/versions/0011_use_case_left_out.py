from alembic import op

revision = "0011"
down_revision = "0010"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE builder.use_cases
            ADD COLUMN left_out text[] NOT NULL DEFAULT '{}';
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE builder.use_cases DROP COLUMN left_out")
