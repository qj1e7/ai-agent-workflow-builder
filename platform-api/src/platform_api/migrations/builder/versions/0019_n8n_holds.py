from alembic import op

revision = "0019"
down_revision = "0018"


def upgrade() -> None:
    # Who opened each workflow in n8n, and who took it back and when (ENGINE-PLAN D14). The use
    # case's held_by says who holds it now; this keeps every hold. taken_back_by is empty when the
    # platform took it back itself, as when the holder's n8n access ended. n8n_stranded_at marks a
    # workflow a failed move may have left outside the platform's project with nobody holding it:
    # the platform moves it back until that works, and changes nothing else in it meanwhile.
    op.execute("""
        CREATE TABLE builder.n8n_holds (
            use_case_id text NOT NULL REFERENCES builder.use_cases (use_case_id),
            held_by text NOT NULL,
            opened_at timestamptz NOT NULL,
            taken_back_by text,
            taken_back_at timestamptz,
            CHECK (taken_back_by IS NULL OR taken_back_at IS NOT NULL)
        );
        CREATE UNIQUE INDEX n8n_holds_one_open
            ON builder.n8n_holds (use_case_id) WHERE taken_back_at IS NULL;

        ALTER TABLE builder.use_cases
            ADD COLUMN n8n_stranded_at timestamptz,
            ADD CONSTRAINT use_cases_a_hold_has_its_time
                CHECK ((held_by IS NULL) = (held_since IS NULL));

        GRANT SELECT, INSERT, UPDATE ON builder.n8n_holds TO wab_builder;
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE builder.use_cases
            DROP CONSTRAINT use_cases_a_hold_has_its_time,
            DROP COLUMN n8n_stranded_at;
        DROP TABLE builder.n8n_holds;
    """)
