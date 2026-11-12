import { useState } from 'react'
import { PlannerBot, type BotState } from '../../ui/PlannerBot'
import { Answer, type Page } from './AnswerCards'
import { EditCard } from './EditCard'
import { CardMemoryContext, NO_MEMORY, type CardMemory } from './cardMemory'
import { Leftovers } from './PartsList'
import { CardLive, NewestAnswer } from './primary'
import { SetupCard } from './SetupCard'
import { sayOf } from './answers'
import { useAsker } from './asker'
import { CheckWorkflowsAnswer, DecideAnswer, DecidedAnswer, IdeasSentence, NeedsMeAnswer, OperatorsAnswer, RequestsToOpen, useSaidOnce, WhyStoppedAnswer, type Say } from './StateAnswers'
import type { Message, Thread as ThreadState } from './threadState'
import { Waiting } from './Waiting'
import styles from './Planner.module.css'

const SORRY = new Set(['cant', 'refused', 'offline', 'operators'])
const RESUMED = 'Here’s your draft. Pick up where you left off.'

interface ThreadProps {
  readonly thread: ThreadState
  readonly now: Date
  readonly page: Page
  /** What each message's card remembers when the page is left. Without it a card starts afresh whenever it is drawn. */
  readonly memory?: (messageId: number) => CardMemory
}

/**
 * The one workflow an answer was about, which "it" in the next request means: the one it named, or the one she picked on its
 * edit card. A card in between, such as a draft, means no one workflow.
 */
function aboutBefore(messages: readonly Message[], index: number, memory: ThreadProps['memory']): string | null {
  const before = messages.slice(0, index).findLast((message) => message.kind !== 'me' && message.kind !== 'thinking')
  if (before?.kind !== 'reply') return null
  const { reply } = before
  if (reply.answer === 'edit') return reply.use_case_id ?? memory?.(before.id).edit.kept()?.picks.useCaseId ?? null
  return reply.answer === 'why_stopped' || reply.answer === 'check_workflows' ? reply.use_case_id : null
}

function ReplyBody({ message, now, page, say, about }: { message: Extract<Message, { kind: 'reply' }>; now: Date; page: Page; say: Say; about: string | null }) {
  const { reply } = message
  const asker = useAsker()
  const sentence = sayOf(reply, asker)
  useSaidOnce(sentence, say)
  return (
    <div className={styles['reply']}>
      {sentence !== null ? <p>{sentence}</p> : null}
      <Leftovers reply={reply} />
      {reply.answer === 'check_workflows' ? <CheckWorkflowsAnswer useCaseId={reply.use_case_id} now={now} say={say} /> : null}
      {reply.answer === 'why_stopped' ? <WhyStoppedAnswer useCaseId={reply.use_case_id} say={say} /> : null}
      {reply.answer === 'ideas' ? <IdeasSentence say={say} /> : null}
      {reply.answer === 'needs_me' ? <NeedsMeAnswer now={now} say={say} /> : null}
      {reply.answer === 'edit' ? <EditCard reply={reply} typed={message.typed} page={page} say={say} now={now} about={about} /> : null}
      {reply.answer === 'operators' ? <OperatorsAnswer say={say} /> : null}
      {reply.answer === 'decided' ? <DecidedAnswer only={reply.only} now={now} say={say} /> : null}
      {reply.answer === 'decide' ? <DecideAnswer now={now} say={say} /> : null}
      <Answer reply={reply} typed={message.typed} page={page} />
      {reply.answer === 'refused' && asker === 'approver' ? <RequestsToOpen now={now} /> : null}
    </div>
  )
}

/**
 * The person's messages and the Planner's answers, newest last. One polite region reads each answer's sentence once, and a
 * newer answer replaces the older one there. The thread lives on the page and is never saved.
 */
export function Thread({ thread, now, page, memory }: ThreadProps) {
  const [said, setSaid] = useState<{ id: number; text: string } | null>(null)
  const newest = thread.messages.at(-1)?.id ?? 0
  const sayFor = (id: number): Say => (text) => setSaid((now) => (now?.id === id ? now : { id, text }))
  return (
    <>
      <h2 className="visually-hidden" id="thread-h">
        Conversation with the Planner
      </h2>
      <ol className={styles['thread']} aria-labelledby="thread-h">
        {thread.messages.map((message, index) => {
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
          const state: BotState = message.kind === 'thinking' ? 'thinking' : message.kind === 'reply' && SORRY.has(message.reply.answer) ? 'sorry' : 'idle'
          return (
            <li key={message.id} className={styles['said']} tabIndex={-1} data-answer={message.kind === 'reply' || undefined}>
              <PlannerBot state={state} size={40} />
              <CardMemoryContext.Provider value={memory?.(message.id) ?? NO_MEMORY}>
                <div className={styles['reply']}>
                  <span className={styles['who']}>Planner</span>
                  {message.kind === 'card' ? (
                    <CardLive.Provider value={message.id === newest}>
                      <>
                        <p>{RESUMED}</p>
                        <SetupCard start={message.start} />
                      </>
                    </CardLive.Provider>
                  ) : message.kind === 'thinking' ? (
                    <>
                      <span className={styles['dots']} aria-hidden="true">
                        <i />
                        <i />
                        <i />
                      </span>
                      <Waiting />
                    </>
                  ) : (
                    <NewestAnswer.Provider value={message.id === newest}>
                      <CardLive.Provider value={message.id === newest}>
                        <ReplyBody message={message} now={now} page={page} say={message.id === newest ? sayFor(message.id) : () => undefined} about={aboutBefore(thread.messages, index, memory)} />
                      </CardLive.Provider>
                    </NewestAnswer.Provider>
                  )}
                </div>
              </CardMemoryContext.Provider>
            </li>
          )
        })}
      </ol>
      <div className="visually-hidden" role="status" aria-live="polite">
        {thread.messages.at(-1)?.kind === 'thinking' ? '' : said?.text ?? ''}
      </div>
    </>
  )
}
