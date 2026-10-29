from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE builder.use_cases
            ADD COLUMN paused_at timestamptz,
            ADD COLUMN paused_by text,
            ADD COLUMN deleted_at timestamptz,
            ADD COLUMN deleted_by text,
            ADD CONSTRAINT use_cases_paused_by_someone
                CHECK ((paused_at IS NULL) = (paused_by IS NULL)),
            ADD CONSTRAINT use_cases_deleted_by_someone
                CHECK ((deleted_at IS NULL) = (deleted_by IS NULL));

        -- Nothing is hard-deleted: a deleted use case keeps its rows, so it can be restored.
        REVOKE DELETE ON builder.use_cases, builder.use_case_versions FROM wab_builder;

        CREATE TABLE builder.drafts (
            author text NOT NULL,
            draft_id text NOT NULL,
            step integer NOT NULL CHECK (step BETWEEN 1 AND 4),
            content jsonb NOT NULL,
            created_at timestamptz NOT NULL,
            saved_at timestamptz NOT NULL,
            PRIMARY KEY (author, draft_id)
        );

        GRANT SELECT, INSERT, UPDATE, DELETE ON builder.drafts TO wab_builder;
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE builder.drafts;
        GRANT DELETE ON builder.use_cases, builder.use_case_versions TO wab_builder;
        ALTER TABLE builder.use_cases
            DROP CONSTRAINT use_cases_deleted_by_someone,
            DROP CONSTRAINT use_cases_paused_by_someone,
            DROP COLUMN deleted_by,
            DROP COLUMN deleted_at,
            DROP COLUMN paused_by,
            DROP COLUMN paused_at;
    """)
