from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE orchestration.people (
            id text PRIMARY KEY,
            entra_oid text UNIQUE,
            email text NOT NULL,
            display text NOT NULL,
            is_operator boolean NOT NULL,
            is_approver boolean NOT NULL,
            added_by text NOT NULL,
            added_at timestamptz NOT NULL,
            bound_at timestamptz,
            removed_at timestamptz
        );
        CREATE UNIQUE INDEX people_email_key ON orchestration.people (lower(email));

        CREATE TABLE orchestration.confirmations (
            id text PRIMARY KEY,
            kind text NOT NULL CHECK (kind IN ('approver', 'model_address')),
            about text REFERENCES orchestration.people (id),
            change jsonb NOT NULL,
            digest text NOT NULL,
            asked_by text NOT NULL,
            asked_at timestamptz NOT NULL,
            decided_by text,
            decision text CHECK (decision IN ('confirmed', 'not_now', 'closed')),
            decided_at timestamptz,
            CHECK (
                (decided_by IS NULL AND decision IS NULL AND decided_at IS NULL)
                OR (decided_by IS NOT NULL AND decision IS NOT NULL AND decided_at IS NOT NULL)
            )
        );
        CREATE UNIQUE INDEX confirmations_one_open_key
            ON orchestration.confirmations (kind, coalesce(about, ''))
            WHERE decided_at IS NULL;

        CREATE TABLE orchestration.settings_changes (
            id bigserial PRIMARY KEY,
            changed_at timestamptz NOT NULL,
            area text NOT NULL CHECK (area IN ('people', 'model')),
            changed_by text NOT NULL,
            confirmed_by text,
            confirmation_id text REFERENCES orchestration.confirmations (id),
            summary text NOT NULL
        );

        INSERT INTO orchestration.settings_changes (changed_at, area, changed_by, summary)
        SELECT changed_at, 'model', changed_by, summary
        FROM orchestration.model_setting_changes ORDER BY id;
        DROP TABLE orchestration.model_setting_changes;

        -- A waiting address from before this migration has no confirmation record. Its asker
        -- saves it again.
        DELETE FROM orchestration.model_setting WHERE slot = 'pending';

        GRANT SELECT, INSERT, UPDATE ON orchestration.people TO wab_orchestration;
        GRANT SELECT, INSERT, UPDATE ON orchestration.confirmations TO wab_orchestration;
        GRANT SELECT, INSERT ON orchestration.settings_changes TO wab_orchestration;
        GRANT USAGE, SELECT ON SEQUENCE orchestration.settings_changes_id_seq
            TO wab_orchestration;
    """)


def downgrade() -> None:
    op.execute("""
        CREATE TABLE orchestration.model_setting_changes (
            id bigserial PRIMARY KEY,
            changed_at timestamptz NOT NULL,
            changed_by text NOT NULL,
            summary text NOT NULL
        );
        INSERT INTO orchestration.model_setting_changes (changed_at, changed_by, summary)
        SELECT changed_at, changed_by, summary FROM orchestration.settings_changes
        WHERE area = 'model' ORDER BY id;
        GRANT SELECT, INSERT, UPDATE, DELETE ON orchestration.model_setting_changes
            TO wab_orchestration;
        GRANT USAGE, SELECT ON SEQUENCE orchestration.model_setting_changes_id_seq
            TO wab_orchestration;

        DROP TABLE orchestration.settings_changes;
        DROP TABLE orchestration.confirmations;
        DROP TABLE orchestration.people;
    """)
