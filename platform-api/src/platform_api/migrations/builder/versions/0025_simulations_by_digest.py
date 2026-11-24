from alembic import op

revision = "0025"
down_revision = "0024"


def upgrade() -> None:
    # Every version tried on practice systems, by its digest alone (ADR 0054, "What every version
    # chose"): a drafted revision's, and the version of a workflow the Planner built from our
    # blocks. The same digest is the same workflow, so a digest is tried once, whichever
    # workflow holds it. The columns mean what they meant in 0024. A digest two drafted
    # workflows shared keeps its newest try. builder.drafted_simulations stays as it is, unused:
    # dropping it deletes data, which waits for the team lead's OK.
    op.execute("""
        CREATE TABLE builder.simulations (
            digest text PRIMARY KEY,
            state text NOT NULL CHECK (state IN ('running', 'done', 'not_run')),
            started_at timestamptz NOT NULL,
            finished_at timestamptz,
            result jsonb,
            said text,
            again boolean NOT NULL DEFAULT false,
            CONSTRAINT simulations_done_has_a_result
                CHECK ((state = 'done') = (result IS NOT NULL)),
            CONSTRAINT simulations_not_run_says_why
                CHECK ((state = 'not_run') = (said IS NOT NULL)),
            CONSTRAINT simulations_finished
                CHECK ((state = 'running') = (finished_at IS NULL))
        );

        INSERT INTO builder.simulations
            (digest, state, started_at, finished_at, result, said, again)
        SELECT DISTINCT ON (digest)
            digest, state, started_at, finished_at, result, said, again
        FROM builder.drafted_simulations
        ORDER BY digest, started_at DESC;

        GRANT SELECT, INSERT, UPDATE ON builder.simulations TO wab_builder;
    """)


def downgrade() -> None:
    # builder.drafted_simulations was kept, so it holds every try from before 0025.
    op.execute("DROP TABLE builder.simulations;")
