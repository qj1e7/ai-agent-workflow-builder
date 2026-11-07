from alembic import op

revision = "0009"
down_revision = "0008"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE builder.software_address_changes (
            change_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            use_case_id text NOT NULL,
            software_id text NOT NULL,
            kind text NOT NULL CHECK (kind IN ('use', 'undo')),
            from_ref text NOT NULL,
            to_ref text NOT NULL,
            changed_by text NOT NULL,
            changed_at timestamptz NOT NULL
        );
        CREATE INDEX software_address_changes_by_use_case
            ON builder.software_address_changes (use_case_id, software_id, change_id);

        GRANT SELECT, INSERT ON builder.software_address_changes TO wab_builder;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE builder.software_address_changes")
