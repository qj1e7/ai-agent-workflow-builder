from alembic import op

revision = "0013"
down_revision = "0012"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE builder.use_case_moves (
            use_case_id text NOT NULL REFERENCES builder.use_cases (use_case_id),
            move text NOT NULL CHECK (move IN ('pause', 'resume')),
            moved_by text NOT NULL,
            via text NOT NULL CHECK (via IN ('page', 'chat')),
            moved_at timestamptz NOT NULL
        );

        CREATE INDEX use_case_moves_by_use_case ON builder.use_case_moves (use_case_id, moved_at);

        GRANT SELECT, INSERT ON builder.use_case_moves TO wab_builder;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE builder.use_case_moves")
