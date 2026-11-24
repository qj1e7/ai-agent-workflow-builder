from alembic import op

revision = "0025"
down_revision = "0024"


def upgrade() -> None:
    # Every version tried on practice systems, by its digest alone (ADR 0054, "What every version
    # chose"): a drafted revision's, and the version of a workflow the Planner built from our
    # blocks. The same digest is the same workflow, so a digest is tried once, whichever
    # workflow holds it. The columns mean what they meant in 0024. A digest two drafted
    # workflows shared keeps its newest try.
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

        DROP TABLE builder.drafted_simulations;

        GRANT SELECT, INSERT, UPDATE ON builder.simulations TO wab_builder;
    """)


def downgrade() -> None:
    # Only a drafted revision's try goes back, to each drafted revision with its digest.
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

        INSERT INTO builder.drafted_simulations
            (drafted_id, digest, revision, state, started_at, finished_at, result, said, again)
        SELECT DISTINCT ON (r.drafted_id, r.digest)
            r.drafted_id, s.digest, r.revision, s.state, s.started_at, s.finished_at, s.result,
            s.said, s.again
        FROM builder.simulations s
        JOIN builder.drafted_revisions r ON r.digest = s.digest
        ORDER BY r.drafted_id, r.digest, r.revision DESC;

        DROP TABLE builder.simulations;

        GRANT SELECT, INSERT, UPDATE ON builder.drafted_simulations TO wab_builder;
    """)
