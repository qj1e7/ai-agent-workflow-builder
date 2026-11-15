from alembic import op

revision = "0020"
down_revision = "0019"


def upgrade() -> None:
    # A workflow someone made in n8n and an Operator with n8n access registered (ENGINE-PLAN E15,
    # ADR 0027): who made it, matched by the n8n account the platform made for them. Its runs
    # are their work too, so they never approve them. Empty for a workflow the Planner laid out.
    op.execute("""
        ALTER TABLE builder.use_cases
            ADD COLUMN made_in_n8n_by text,
            ADD CONSTRAINT use_cases_made_in_n8n_is_own
                CHECK (made_in_n8n_by IS NULL OR engine = 'own');
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE builder.use_cases
            DROP CONSTRAINT use_cases_made_in_n8n_is_own,
            DROP COLUMN made_in_n8n_by;
    """)
