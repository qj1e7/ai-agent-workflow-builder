from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE builder.cards (
            card_id text PRIMARY KEY,
            owner text NOT NULL,
            created_at timestamptz NOT NULL,
            current_version integer NOT NULL
        );

        CREATE TABLE builder.card_versions (
            card_id text NOT NULL REFERENCES builder.cards (card_id),
            version integer NOT NULL,
            name text NOT NULL,
            purpose text NOT NULL,
            good_for jsonb NOT NULL,
            inputs jsonb NOT NULL,
            blocks jsonb NOT NULL,
            approvals jsonb NOT NULL,
            created_by text NOT NULL,
            created_at timestamptz NOT NULL,
            PRIMARY KEY (card_id, version)
        );

        -- card_id is not a foreign key: a starter card lives in code, not in builder.cards.
        CREATE TABLE builder.use_case_cards (
            use_case_id text NOT NULL,
            version integer NOT NULL,
            position integer NOT NULL,
            card_id text NOT NULL,
            card_version integer NOT NULL,
            "values" jsonb NOT NULL,
            PRIMARY KEY (use_case_id, version, position),
            UNIQUE (use_case_id, version, card_id),
            FOREIGN KEY (use_case_id, version)
                REFERENCES builder.use_case_versions (use_case_id, version)
        );

        GRANT SELECT, INSERT, UPDATE ON builder.cards TO wab_builder;
        GRANT SELECT, INSERT ON builder.card_versions TO wab_builder;
        GRANT SELECT, INSERT, UPDATE, DELETE ON builder.use_case_cards TO wab_builder;
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE builder.use_case_cards;
        DROP TABLE builder.card_versions;
        DROP TABLE builder.cards;
    """)
