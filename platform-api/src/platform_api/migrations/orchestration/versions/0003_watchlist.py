from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    # Local stacks hold runs saved with the repository at the top of the spec. They move
    # under a release task, so one loader reads old and new runs alike.
    op.execute("""
        UPDATE orchestration.runs
        SET spec = (spec - 'repo' - 'tag_pattern' - 'last_known_tag')
            || jsonb_build_object('task', jsonb_build_object(
                'kind', 'release',
                'repo', spec -> 'repo',
                'tag_pattern', spec -> 'tag_pattern',
                'last_known_tag', spec -> 'last_known_tag'))
        WHERE spec ? 'repo' AND NOT spec ? 'task';

        CREATE TABLE orchestration.software_checks (
            use_case_id text NOT NULL,
            software_id text NOT NULL,
            run_id text NOT NULL REFERENCES orchestration.runs (run_id),
            checked_at timestamptz NOT NULL,
            newest_version text,
            problem text,
            PRIMARY KEY (use_case_id, software_id),
            CHECK ((newest_version IS NULL) <> (problem IS NULL))
        );

        CREATE TABLE orchestration.our_versions (
            use_case_id text NOT NULL,
            software_id text NOT NULL,
            version text NOT NULL,
            source text NOT NULL CHECK (source IN ('first_check', 'ticket_done')),
            learned_at timestamptz NOT NULL,
            ticket_key text,
            PRIMARY KEY (use_case_id, software_id),
            CHECK ((source = 'ticket_done') = (ticket_key IS NOT NULL))
        );

        CREATE TABLE orchestration.proposed_tickets (
            proposal_id text NOT NULL REFERENCES orchestration.proposals (proposal_id),
            action_index integer NOT NULL,
            run_id text NOT NULL REFERENCES orchestration.runs (run_id),
            use_case_id text NOT NULL,
            software_id text NOT NULL,
            version text NOT NULL,
            status text NOT NULL
                CHECK (status IN ('proposed', 'written', 'done', 'dropped')),
            ticket_key text,
            done_at timestamptz,
            PRIMARY KEY (proposal_id, action_index),
            CHECK ((status IN ('written', 'done')) = (ticket_key IS NOT NULL)),
            CHECK ((status = 'done') = (done_at IS NOT NULL))
        );
        CREATE INDEX proposed_tickets_software
            ON orchestration.proposed_tickets (use_case_id, software_id);
        CREATE INDEX proposed_tickets_run ON orchestration.proposed_tickets (run_id);

        ALTER TABLE orchestration.mock_jira_tickets
            ADD COLUMN status text NOT NULL DEFAULT 'To Do'
                CHECK (status IN ('To Do', 'Done')),
            ADD COLUMN done_at timestamptz,
            ADD CONSTRAINT mock_jira_tickets_done_at
                CHECK ((status = 'Done') = (done_at IS NOT NULL));

        GRANT SELECT, INSERT, UPDATE, DELETE ON orchestration.software_checks,
            orchestration.our_versions, orchestration.proposed_tickets TO wab_orchestration;
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE orchestration.proposed_tickets;
        DROP TABLE orchestration.our_versions;
        DROP TABLE orchestration.software_checks;
        ALTER TABLE orchestration.mock_jira_tickets
            DROP CONSTRAINT mock_jira_tickets_done_at,
            DROP COLUMN status,
            DROP COLUMN done_at;

        UPDATE orchestration.runs
        SET spec = (spec - 'task') || jsonb_build_object(
                'repo', spec -> 'task' -> 'repo',
                'tag_pattern', spec -> 'task' -> 'tag_pattern',
                'last_known_tag', spec -> 'task' -> 'last_known_tag')
        WHERE spec -> 'task' ->> 'kind' = 'release';
    """)
