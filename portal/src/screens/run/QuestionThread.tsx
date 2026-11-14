import { useId, useRef } from 'react'
import { newIdempotencyKey } from '../../api/idempotency'
import type { ApprovalView } from '../../api/types'
import { AnswerQuestion } from './AnswerQuestion'
import { openStep } from './decision'
import { MessageBox } from './MessageBox'
import { answeredLine, askedLine, answersNow, EMPTY_QUESTION, NOT_ANSWERED, STILL_WAITING, useFocusAfter, type FocusAfter, type Questions } from './questions'
import type { NameOf } from './words'
import styles from './panels.module.css'

interface ThreadProps {
  readonly approval: ApprovalView
  readonly me: string | undefined
  readonly nameOf: NameOf
  readonly answer: Questions['answer']
  /** The heading a send moves focus to. The gate passes its own, so its Send lands here too. */
  readonly heading?: FocusAfter<HTMLHeadingElement>
  /** Its heading's level, one below the view it sits in. */
  readonly level?: 2 | 3 | 4
}

/**
 * The questions on a request, the first asked first. While it waits, the requester answers under each one. Once it is
 * decided they stay, read only, and one left open says so.
 */
export function QuestionThread({ approval, me, nameOf, answer, heading, level = 2 }: ThreadProps) {
  const own = useFocusAfter<HTMLHeadingElement>()
  const { ref: headingRef, request: focusHeading } = heading ?? own
  const headingId = useId()
  if (approval.questions.length === 0) return null
  const open = openStep(approval) !== null
  const Heading = (['h2', 'h3', 'h4'] as const)[level - 2] ?? 'h2'
  return (
    <section className={styles['asks']} aria-labelledby={headingId}>
      <Heading id={headingId} ref={headingRef} tabIndex={-1}>
        Questions
      </Heading>
      <ul>
        {approval.questions.map((question) => (
          <li key={question.question_id}>
            <p>
              <b>{askedLine(question, approval.requester, me, nameOf)}:</b> {question.text}
            </p>
            {question.answer ? (
              <p>
                <b>{answeredLine(question.answer, me, nameOf)}:</b> {question.answer.text}
              </p>
            ) : answersNow(approval, question, me) ? (
              <AnswerQuestion
                askedBy={nameOf(question.asked_by)}
                pending={answer.questionId === question.question_id && answer.pending}
                error={answer.questionId === question.question_id ? answer.error : null}
                onAnswer={(text) => answer.send(question.question_id, text, focusHeading)}
              />
            ) : (
              <p className={styles['small']}>{open ? STILL_WAITING : NOT_ANSWERED}</p>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}

interface AskBoxProps {
  /** The requester, by name. */
  readonly requester: string
  readonly ask: Questions['ask']
  readonly onSent: () => void
  readonly onCancel: () => void
}

/** "Ask Alice a question", with Back and Send. Sending keeps the request open, and the question shows on it. */
export function AskBox({ requester, ask, onSent, onCancel }: AskBoxProps) {
  // A resend of the same words keeps its key, so a send that landed before its answer was lost is not asked twice. Edited words are a new question.
  const sent = useRef<{ readonly text: string; readonly key: string } | null>(null)
  const keyFor = (text: string) => {
    if (sent.current?.text !== text) sent.current = { text, key: newIdempotencyKey() }
    return sent.current.key
  }
  return (
    <MessageBox
      label={`Ask ${requester} a question`}
      empty={EMPTY_QUESTION}
      send="Send"
      pending={ask.pending}
      error={ask.error}
      onSend={(text) => ask.send(text, keyFor(text), onSent)}
      onCancel={onCancel}
    />
  )
}
