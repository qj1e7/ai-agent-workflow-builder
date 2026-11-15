from alembic import op

revision = "0010"
down_revision = "0009"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE builder.use_case_version_changes (
            use_case_id text NOT NULL,
            version integer NOT NULL,
            changed_by text NOT NULL,
            via text NOT NULL CHECK (via IN ('page', 'chat')),
            schedule_before jsonb,
            schedule_after jsonb,
            undid integer CHECK (undid > 0 AND undid < version),
            PRIMARY KEY (use_case_id, version),
            FOREIGN KEY (use_case_id, version)
                REFERENCES builder.use_case_versions (use_case_id, version)
        );

        GRANT SELECT, INSERT ON builder.use_case_version_changes TO wab_builder;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE builder.use_case_version_changes")
