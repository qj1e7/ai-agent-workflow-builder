from alembic import op

revision = "0018"
down_revision = "0017"


def upgrade() -> None:
    # Which rules, and which error workflow, the version's grade was made under (ENGINE-PLAN
    # E11). The versions sweep grades again every version whose mark is another, so a release
    # whose rules changed has every workflow graded under them, however many looks that takes.
    op.execute("ALTER TABLE builder.use_case_versions ADD COLUMN graded_by text")


def downgrade() -> None:
    op.execute("ALTER TABLE builder.use_case_versions DROP COLUMN graded_by")
