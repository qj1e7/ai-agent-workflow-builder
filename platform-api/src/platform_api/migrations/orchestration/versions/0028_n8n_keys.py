from alembic import op

revision = "0028"
down_revision = "0027"


def upgrade() -> None:
    # The keys the platform makes in n8n for n8n's own blocks (ADR 0045, ENGINE-PLAN E16, E17).
    # A key is the platform's while n8n holds it as made: made at n8n_created_at and changed last
    # at n8n_updated_at. refused says why the platform holds none now. fingerprint is a salted
    # hash of what n8n was given, so a new secret in Key Vault is noticed; the secret is never
    # kept here.
    #
    # A loan puts a key in the space of whoever holds a workflow that names it. A key sits in one
    # n8n project, so all of a key's loans name one project.
    #
    # A quarantined key is a member's own, which n8n moved to the platform's project as their
    # account ended. It is never the platform's, and the sweep leaves it only while it sits there.
    #
    # A key test is the daily self-test of the credential sweep: a key the platform planted
    # without recording it as its own, which the sweep must delete within a minute.
    op.execute("""
        CREATE TABLE orchestration.n8n_keys (
            id text PRIMARY KEY,
            system text NOT NULL UNIQUE,
            kind text NOT NULL,
            fingerprint text,
            n8n_created_at timestamptz,
            n8n_updated_at timestamptz,
            refused text,
            checked_at timestamptz NOT NULL,
            CONSTRAINT n8n_keys_made_or_refused
                CHECK (refused IS NULL OR n8n_created_at IS NULL)
        );

        CREATE TABLE orchestration.n8n_key_loans (
            key_id text NOT NULL,
            use_case_id text NOT NULL,
            project_id text NOT NULL,
            lent_at timestamptz NOT NULL,
            PRIMARY KEY (key_id, use_case_id)
        );

        CREATE TABLE orchestration.n8n_quarantined_keys (
            key_id text PRIMARY KEY,
            n8n_user_id text NOT NULL,
            quarantined_at timestamptz NOT NULL
        );

        CREATE TABLE orchestration.n8n_key_tests (
            key_id text PRIMARY KEY,
            planted_at timestamptz NOT NULL,
            gone_at timestamptz
        );

        GRANT SELECT, INSERT, UPDATE, DELETE ON orchestration.n8n_keys TO wab_orchestration;
        GRANT SELECT, INSERT, UPDATE, DELETE ON orchestration.n8n_key_loans TO wab_orchestration;
        GRANT SELECT, INSERT ON orchestration.n8n_quarantined_keys TO wab_orchestration;
        GRANT SELECT, INSERT, UPDATE ON orchestration.n8n_key_tests TO wab_orchestration;
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE orchestration.n8n_key_tests;
        DROP TABLE orchestration.n8n_quarantined_keys;
        DROP TABLE orchestration.n8n_key_loans;
        DROP TABLE orchestration.n8n_keys;
    """)
