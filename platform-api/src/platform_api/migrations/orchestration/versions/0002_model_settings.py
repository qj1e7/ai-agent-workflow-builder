from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE orchestration.model_setting (
            slot text PRIMARY KEY CHECK (slot IN ('active', 'pending')),
            provider text NOT NULL,
            style text NOT NULL,
            base_url text NOT NULL,
            model text NOT NULL,
            sealed_key text NOT NULL,
            key_hint text NOT NULL,
            test_seconds real NOT NULL,
            saved_by text NOT NULL,
            saved_by_name text NOT NULL,
            saved_at timestamptz NOT NULL
        );

        CREATE TABLE orchestration.model_hosts (
            host text PRIMARY KEY,
            confirmed_by text NOT NULL,
            confirmed_at timestamptz NOT NULL
        );

        CREATE TABLE orchestration.model_setting_changes (
            id bigserial PRIMARY KEY,
            changed_at timestamptz NOT NULL,
            changed_by text NOT NULL,
            summary text NOT NULL
        );

        GRANT SELECT, INSERT, UPDATE, DELETE ON orchestration.model_setting,
            orchestration.model_hosts, orchestration.model_setting_changes TO wab_orchestration;
        GRANT USAGE, SELECT ON SEQUENCE orchestration.model_setting_changes_id_seq
            TO wab_orchestration;
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE orchestration.model_setting_changes;
        DROP TABLE orchestration.model_hosts;
        DROP TABLE orchestration.model_setting;
    """)
