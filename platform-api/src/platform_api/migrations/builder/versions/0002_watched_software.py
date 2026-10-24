from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE builder.watched_software (
            use_case_id text NOT NULL,
            version integer NOT NULL,
            software_id text NOT NULL,
            position integer NOT NULL,
            name text NOT NULL,
            source_kind text NOT NULL CHECK (source_kind = 'github'),
            source_ref text NOT NULL,
            starting_version text,
            added_by text NOT NULL,
            added_at timestamptz NOT NULL,
            PRIMARY KEY (use_case_id, version, software_id),
            FOREIGN KEY (use_case_id, version)
                REFERENCES builder.use_case_versions (use_case_id, version)
        );
        CREATE UNIQUE INDEX watched_software_one_source_per_version
            ON builder.watched_software (use_case_id, version, source_kind, lower(source_ref));

        GRANT SELECT, INSERT, UPDATE, DELETE ON builder.watched_software TO wab_builder;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE builder.watched_software")
