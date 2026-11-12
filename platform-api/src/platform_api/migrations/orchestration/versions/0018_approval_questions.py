from alembic import op

revision = "0018"
down_revision = "0017"


def upgrade() -> None:
    # Questions on a request (ADR 0043): an Approver asks the requester, who may answer once. A
    # question is a message on the request. It has no part in the gate, so no decision reads
    # this table. An answer is all three of its columns or none of them. The asker's own key
    # makes a repeated send return the question already asked.
    op.execute("""
        CREATE TABLE orchestration.approval_questions (
            question_id text PRIMARY KEY,
            approval_id text NOT NULL
                REFERENCES orchestration.approval_requests (approval_id),
            asked_by text NOT NULL,
            asked_at timestamptz NOT NULL,
            text text NOT NULL CHECK (char_length(text) BETWEEN 1 AND 1000),
            idempotency_key text NOT NULL,
            answer text CHECK (char_length(answer) BETWEEN 1 AND 1000),
            answered_by text,
            answered_at timestamptz,
            CONSTRAINT approval_questions_an_answer_is_whole CHECK (
                (answer IS NULL) = (answered_by IS NULL)
                AND (answer IS NULL) = (answered_at IS NULL)
            ),
            UNIQUE (approval_id, asked_by, idempotency_key)
        );
        CREATE INDEX approval_questions_by_approval
            ON orchestration.approval_questions (approval_id, asked_at);

        GRANT SELECT, INSERT, UPDATE ON orchestration.approval_questions TO wab_orchestration;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE orchestration.approval_questions")
