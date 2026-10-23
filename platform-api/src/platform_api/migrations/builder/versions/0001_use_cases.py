from alembic import op

revision = "0001"
down_revision = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE builder.use_cases (
            use_case_id text PRIMARY KEY,
            owner text NOT NULL,
            created_at timestamptz NOT NULL,
            current_version integer NOT NULL
        );

        CREATE TABLE builder.use_case_versions (
            use_case_id text NOT NULL REFERENCES builder.use_cases (use_case_id),
            version integer NOT NULL,
            template text NOT NULL,
            name text NOT NULL,
            instruction text NOT NULL,
            params jsonb NOT NULL,
            created_at timestamptz NOT NULL,
            PRIMARY KEY (use_case_id, version)
        );

        GRANT USAGE ON SCHEMA builder TO wab_builder;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA builder TO wab_builder;
    """)


def downgrade() -> None:
    op.execute("DROP SCHEMA builder CASCADE")
