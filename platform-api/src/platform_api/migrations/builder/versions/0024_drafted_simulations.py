from alembic import op

revision = "0024"
down_revision = "0023"


def upgrade() -> None:
    # A drafted revision tried on practice systems (ADR 0054, PR 7), by the digest of its
    # document, so a changed version needs a new simulation and never shows an older result.
    # A simulation is not a run: it has no run id, and nothing here reaches the run tables or
    # the activity log. state is running from started_at, done with code's grades in result,
    # or not_run with said, why nothing was tried. again says whether trying again may help.
    # A running row past its limit shows as not finished, never as running for good.
    op.execute("""
        CREATE TABLE builder.drafted_simulations (
            drafted_id text NOT NULL REFERENCES builder.drafted_workflows (drafted_id),
            digest text NOT NULL,
            revision integer NOT NULL,
            state text NOT NULL CHECK (state IN ('running', 'done', 'not_run')),
            started_at timestamptz NOT NULL,
            finished_at timestamptz,
            result jsonb,
            said text,
            again boolean NOT NULL DEFAULT false,
            PRIMARY KEY (drafted_id, digest),
            CONSTRAINT drafted_simulations_done_has_a_result
                CHECK ((state = 'done') = (result IS NOT NULL)),
            CONSTRAINT drafted_simulations_not_run_says_why
                CHECK ((state = 'not_run') = (said IS NOT NULL)),
            CONSTRAINT drafted_simulations_finished
                CHECK ((state = 'running') = (finished_at IS NULL))
        );

        GRANT SELECT, INSERT, UPDATE ON builder.drafted_simulations TO wab_builder;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE builder.drafted_simulations;")
