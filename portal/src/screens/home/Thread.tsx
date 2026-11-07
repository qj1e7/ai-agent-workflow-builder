import { useState } from 'react'
import { PlannerBot, type BotState } from '../../ui/PlannerBot'
import { Answer, type Page } from './AnswerCards'
import { NewestAnswer } from './primary'
import { sayOf } from './answers'
import { CheckWorkflowsAnswer, NeedsMeAnswer, useSaidOnce, WhyStoppedAnswer, type Say } from './StateAnswers'
import type { Message, Thread as ThreadState } from './threadState'
import styles from './Planner.module.css'

const SORRY = new Set(['cant', 'refused', 'offline'])

interface ThreadProps {
  readonly thread: ThreadState
  readonly now: Date
  readonly page: Page
}

function ReplyBody({ message, now, page, say }: { message: Extract<Message, { kind: 'reply' }>; now: Date; page: Page; say: Say }) {
  const { reply } = message
  const sentence = sayOf(reply)
  useSaidOnce(sentence, say)
  return (
    <div className={styles['reply']}>
      {sentence !== null ? <p>{sentence}</p> : null}
      {reply.answer === 'check_workflows' ? <CheckWorkflowsAnswer useCaseId={reply.use_case_id} now={now} say={say} /> : null}
      {reply.answer === 'why_stopped' ? <WhyStoppedAnswer useCaseId={reply.use_case_id} say={say} /> : null}
      {reply.answer === 'needs_me' ? <NeedsMeAnswer now={now} say={say} /> : null}
      <Answer reply={reply} typed={message.typed} page={page} />
    </div>
  )
}

/**
 * The person's messages and the Planner's answers, newest last. One polite region reads each answer's sentence once, and a
 * newer answer replaces the older one there. The thread lives on the page and is never saved.
 */
export function Thread({ thread, now, page }: ThreadProps) {
  const [said, setSaid] = useState<{ id: number; text: string } | null>(null)
  const newest = thread.messages.at(-1)?.id ?? 0
  const sayFor = (id: number): Say => (text) => setSaid((now) => (now?.id === id ? now : { id, text }))
  return (
    <>
      <h2 className="visually-hidden" id="thread-h">
        Conversation with the Planner
      </h2>
      <ol className={styles['thread']} aria-labelledby="thread-h">
        {thread.messages.map((message) => {
          if (message.kind === 'me') {
            return (
              <li key={message.id} className={styles['me']}>
                <div className={styles['bubble']}>
                  <span className="visually-hidden">You: </span>
                  {message.text}
                </div>
              </li>
            )
          }
          const state: BotState = message.kind === 'thinking' ? 'thinking' : SORRY.has(message.reply.answer) ? 'sorry' : 'idle'
          return (
            <li key={message.id} className={styles['said']} tabIndex={-1} data-answer={message.kind === 'reply' || undefined}>
              <PlannerBot state={state} size={40} />
              <div className={styles['reply']}>
                <span className={styles['who']}>Planner</span>
                {message.kind === 'thinking' ? (
                  <span className={styles['dots']} aria-hidden="true">
                    <i />
                    <i />
                    <i />
                  </span>
                ) : (
                  <NewestAnswer.Provider value={message.id === newest}>
                    <ReplyBody message={message} now={now} page={page} say={message.id === newest ? sayFor(message.id) : () => undefined} />
                  </NewestAnswer.Provider>
                )}
              </div>
            </li>
          )
        })}
      </ol>
      <div className="visually-hidden" role="status" aria-live="polite">
        {thread.messages.at(-1)?.kind === 'thinking' ? 'The Planner is answering' : said?.text ?? ''}
      </div>
    </>
  )
}
