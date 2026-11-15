from alembic import op

revision = "0026"
down_revision = "0025"


def upgrade() -> None:
    # n8n access per person (ENGINE-PLAN 2.9, E7). Only an Operator who is no Approver may hold
    # it, so the table refuses any other row. The platform makes the person's n8n account and
    # keeps its user id, which every later match uses, never the email. The invite link is a
    # password-set link, so it is kept sealed, and only until the person has used it. n8n's link
    # never runs out, so the platform makes a new account and link once the old one is a week
    # old and still unused.
    op.execute("""
        ALTER TABLE orchestration.people
            ADD COLUMN n8n_access boolean NOT NULL DEFAULT false,
            ADD COLUMN n8n_user_id text UNIQUE,
            ADD COLUMN n8n_invite text,
            ADD COLUMN n8n_invited_at timestamptz,
            ADD CONSTRAINT people_n8n_access_is_an_operators_only CHECK (
                NOT n8n_access OR (is_operator AND NOT is_approver AND removed_at IS NULL)
            ),
            ADD CONSTRAINT people_an_invite_has_its_account
                CHECK (n8n_invite IS NULL OR n8n_user_id IS NOT NULL),
            ADD CONSTRAINT people_an_invite_has_its_time
                CHECK ((n8n_invite IS NULL) = (n8n_invited_at IS NULL));
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE orchestration.people
            DROP CONSTRAINT people_an_invite_has_its_time,
            DROP CONSTRAINT people_an_invite_has_its_account,
            DROP COLUMN n8n_invited_at,
            DROP CONSTRAINT people_n8n_access_is_an_operators_only,
            DROP COLUMN n8n_invite,
            DROP COLUMN n8n_user_id,
            DROP COLUMN n8n_access;
    """)
