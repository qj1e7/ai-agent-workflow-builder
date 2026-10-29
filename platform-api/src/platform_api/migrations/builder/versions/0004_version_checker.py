from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    op.execute("""
        UPDATE builder.use_case_cards
        SET card_id = 'crd_version_checker'
        WHERE card_id = 'crd_release_checker';
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE builder.use_case_cards
        SET card_id = 'crd_release_checker'
        WHERE card_id = 'crd_version_checker';
    """)
