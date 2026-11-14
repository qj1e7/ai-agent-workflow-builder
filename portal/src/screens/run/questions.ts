import { useEffect, useRef, useState, type RefObject } from 'react'
import { useCacheScope, useErrorWords } from '../../api/context'
import { useLatch } from '../../api/latch'
import { refusalOf, useAnswerQuestion, useAskQuestion } from '../../api/queries'
import type { AnswerView, ApprovalView, QuestionView, Refusal } from '../../api/types'
import { openStep } from './decision'
import type { NameOf } from './words'

/**
 * Questions on a request (spec 10.4, ADR 0043). An Approver asks the requester, who answers on the request. Neither one
 * decides anything: the request keeps waiting for a yes, and the platform refuses an answer once it is decided.
 */
export const EMPTY_QUESTION = 'Type your question.'
export const EMPTY_ANSWER = 'Type your answer.'
export const ANSWER_HELP = 'It shows on this request. It doesn’t decide anything.'
export const STILL_WAITING = 'No reply yet. The request stays open.'
export const NOT_ANSWERED = 'Not answered before the request was decided.'

/** What a question or an answer says once the platform kept it, as the prototype's toast does. */
export const sentWords = (to: string) => `Sent to ${to}. The request is still waiting for a yes.`

/** Why the platform refused a question. Asking follows the rule for deciding, but a question is not a decision. */
export function askRefusalWords(refusal: Refusal): string {
  switch (refusal) {
    case 'own_work':
      return 'This is your own request, so another Approver asks about it.'
    case 'not_an_approver':
      return 'Only an Approver can ask about a request.'
    case 'not_open':
      return 'This request is already decided, so it takes no more questions.'
    case 'decided_earlier_step':
      return 'You decided an earlier step, so the Approver of this step asks.'
    case 'not_eligible':
      return 'Only the people who can decide this step can ask about it.'
    default:
      return 'You can’t ask about this request.'
  }
}

const who = (id: string, me: string | undefined, nameOf: NameOf, first: boolean) => (id === me ? (first ? 'You' : 'you') : nameOf(id))

/** "You asked Carol", "Bob asked you" or "Bob asked Carol", from where the reader stands. */
export function askedLine(question: QuestionView, requester: string, me: string | undefined, nameOf: NameOf): string {
  return `${who(question.asked_by, me, nameOf, true)} asked ${who(requester, me, nameOf, false)}`
}

export function answeredLine(answer: AnswerView, me: string | undefined, nameOf: NameOf): string {
  return `${who(answer.by, me, nameOf, true)} answered`
}

/** The requester answers a question with no answer while the request waits. Anyone else reads it. */
export function answersNow(approval: ApprovalView, question: QuestionView, me: string | undefined): boolean {
  return question.answer === null && me !== undefined && approval.requester === me && openStep(approval) !== null
}

export interface QuestionSend {
  readonly pending: boolean
  readonly error: string | null
}

export interface Questions {
  readonly ask: QuestionSend & { send(this: void, text: string, idempotencyKey: string, onSent: () => void): void }
  /** `pending` and `error` belong to `questionId`, the question last answered on this page. */
  readonly answer: QuestionSend & { readonly questionId: string | null; send(this: void, questionId: string, text: string, onSent: () => void): void }
}

/** Nothing sent and nothing to send, for a gate drawn with no platform behind it. */
export const NO_QUESTIONS: Questions = {
  ask: { pending: false, error: null, send: () => undefined },
  answer: { pending: false, error: null, questionId: null, send: () => undefined },
}

/**
 * A dev user switch starts clean, because each send remembers who sent it. `say` puts the words after the platform kept this person's
 * question or answer in the page's one message at the bottom. Focus stays where the send put it.
 */
export function useQuestions(approval: ApprovalView | undefined, nameOf: NameOf, say: (text: string) => void): Questions {
  const approvalId = approval?.approval_id ?? ''
  const asking = useAskQuestion(approvalId)
  const answering = useAnswerQuestion(approvalId)
  const askLatch = useLatch()
  const answerLatch = useLatch()
  const user = useCacheScope()
  const errorWords = useErrorWords()
  const [askedBy, setAskedBy] = useState<string | null>(null)
  const [answered, setAnswered] = useState<{ by: string; questionId: string } | null>(null)
  const askMine = askedBy === user
  const answerMine = answered !== null && answered.by === user
  const sentTo = (to: string) => say(sentWords(nameOf(to)))

  function askError(): string | null {
    if (!askMine || !asking.isError) return null
    const refusal = refusalOf(asking.error)
    return refusal ? askRefusalWords(refusal.refusal) : errorWords(asking.error)
  }

  return {
    ask: {
      pending: askMine && asking.isPending,
      error: askError(),
      send: (text, idempotencyKey, onSent) => {
        if (!approval) return
        askLatch.run((settled) => {
          setAskedBy(user)
          asking.mutate(
            { text, idempotencyKey },
            {
              onSuccess: () => {
                sentTo(approval.requester)
                onSent()
              },
              onSettled: settled,
            },
          )
        })
      },
    },
    answer: {
      questionId: answerMine ? answered.questionId : null,
      pending: answerMine && answering.isPending,
      error: answerMine && answering.isError ? errorWords(answering.error) : null,
      send: (questionId, text, onSent) => {
        if (!approval) return
        answerLatch.run((settled) => {
          setAnswered({ by: user, questionId })
          answering.mutate(
            { questionId, text },
            {
              onSuccess: (question) => {
                sentTo(question.asked_by)
                onSent()
              },
              onSettled: settled,
            },
          )
        })
      },
    },
  }
}

/** Focus that waits for its target: asked for now, given once the element is drawn, as after a send redraws the thread. */
export interface FocusAfter<T extends HTMLElement> {
  readonly ref: RefObject<T | null>
  request(this: void): void
}

export function useFocusAfter<T extends HTMLElement>(): FocusAfter<T> {
  const ref = useRef<T>(null)
  const wanted = useRef(false)
  useEffect(() => {
    if (!wanted.current || !ref.current) return
    wanted.current = false
    ref.current.focus()
  })
  return {
    ref,
    request: () => {
      wanted.current = true
    },
  }
}
