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
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE orchestration.runs
        SET spec = (spec - 'task') || jsonb_build_object(
                'repo', spec -> 'task' -> 'repo',
                'tag_pattern', spec -> 'task' -> 'tag_pattern',
                'last_known_tag', spec -> 'task' -> 'last_known_tag')
        WHERE spec -> 'task' ->> 'kind' = 'release';
    """)
