from alembic import op

revision = "0017"
down_revision = "0016"


def upgrade() -> None:
    # The reason an Approver may give when declining (ADR 0043). It is a note on a decline that
    # already happened, so an approval never carries one, and a decision from before has none.
    op.execute(
        "ALTER TABLE orchestration.approval_decisions ADD COLUMN reason text "
        "CONSTRAINT approval_decisions_reason_only_on_a_decline "
        "CHECK (reason IS NULL OR (verdict = 'decline' AND char_length(reason) BETWEEN 1 AND 200));"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE orchestration.approval_decisions DROP COLUMN reason;")
