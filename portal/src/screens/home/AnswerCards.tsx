import { useId, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import type { CantReply, OfflineReply, PartReply, PlannerReply, QuestionReply, SetupCardReply, WatchlistReply } from '../../api/types'
import { useCapabilities } from '../../api/plannerQueries'
import { Button, ButtonLink } from '../../ui/Button'
import { AskTheTeam } from './AskTheTeam'
import { cantLines, refusalNext, SAY_ANOTHER_WAY, startingPoints, TAG_CANT, TAG_CHOICE } from './answers'
import { cardFrom } from './card'
import { SetupCard, type CardStart } from './SetupCard'
import { CapabilityLists } from './CapabilityLists'
import { NewestAnswer, useMainButton } from './primary'
import { AddToWatchlist, WhichSoftware } from './WatchlistCard'
import styles from './Planner.module.css'

/** What a card can ask the page to do. Both go through the Planner or the box, so nothing here reaches a set-up on its own. */
export interface Page {
  /** Sends words to the Planner as a new question. */
  readonly ask: (text: string) => void
  /** Puts words back in the box for the person to change. */
  readonly edit: (text: string) => void
}


/** A set-up card from the Planner’s rows. The person’s own words go with it, so a saved draft keeps them. */
function startOf(reply: SetupCardReply | PartReply, typed: string): CardStart {
  return { form: cardFrom(reply.name, reply.rows, typed), plan: null, draftId: null, similar: reply.similar }
}

function tagClass(tag: string): string {
  return [styles['tag'], tag === TAG_CHOICE ? styles['tagChoice'] : undefined, tag === TAG_CANT ? styles['tagCant'] : undefined].filter(Boolean).join(' ')
}

function Card({ title, tag, children }: { title: string; tag?: string; children: ReactNode }) {
  const id = useId()
  return (
    <section className={styles['pcard']} aria-labelledby={id}>
      <div className={styles['pcardHead']}>
        <h3 id={id}>{title}</h3>
        {tag ? <span className={tagClass(tag)}>{tag}</span> : null}
      </div>
      {children}
    </section>
  )
}

export function SetupCardAnswer({ reply, typed }: { reply: SetupCardReply | PartReply; typed: string }) {
  const left = reply.answer === 'part' ? cantLines(reply.cant) : []
  return (
    <>
      <SetupCard start={startOf(reply, typed)} />
      {left.length > 0 ? (
        <Card title="What I can’t do yet">
          <div className={styles['pcardPart']}>
            <ul className={styles['lines']}>
              {left.map((line) => (
                <li key={line.text}>
                  {line.text}
                  {line.note ? <span className={styles['note']}>{line.note}</span> : null}
                </li>
              ))}
            </ul>
            {reply.answer === 'part' ? (
              <div className={styles['buttons']}>
                <AskTheTeam capability={reply.cant[0]?.system ?? left[0]?.text ?? 'part of a request'} starter={`I asked the Planner for: ${typed}\n\nWhat it can't do yet: ${left.map((line) => line.text).join('; ')}`} />
              </div>
            ) : null}
          </div>
        </Card>
      ) : null}
    </>
  )
}

export function CantAnswer({ reply, typed }: { reply: CantReply; typed: string }) {
  const rows = cantLines(reply.cant)
  const alternative = reply.alternative
  return (
    <>
      <Card title="What I can’t do yet">
        <ul className={styles['lines']}>
          {rows.map((line) => (
            <li key={line.text}>
              <b>{line.text}</b>
              {line.note ? <span className={styles['note']}>{line.note}</span> : null}
            </li>
          ))}
        </ul>
        <div className={styles['footer']}>
          <AskTheTeam
            capability={reply.cant.find((row) => row.system)?.system ?? rows[0]?.text ?? 'something new'}
            starter={`I asked the Planner for: ${typed}\n\nIt can't do this yet: ${rows.map((line) => line.text).join('; ')}`}
            secondary={alternative !== null}
          />
        </div>
      </Card>
      {alternative?.answer === 'setup_card' ? (
        <>
          <h3 className={styles['altHeading']}>What I can do instead</h3>
          <SetupCard start={startOf(alternative, typed)} />
        </>
      ) : null}
      {alternative?.answer === 'watchlist' ? <WatchlistAnswer reply={alternative} typed={typed} /> : null}
    </>
  )
}

export function WatchlistAnswer({ reply, typed }: { reply: WatchlistReply; typed: string }) {
  const listed = reply.already_listed
  const main = useMainButton()
  return (
    <>
      <Card title={listed ? 'Already on the watchlist' : 'The Software watchlist'}>
        <div className={styles['pcardPart']}>
          {listed ? (
            <>
              <p>{listed.name} is on the Software watchlist.</p>
              <div className={styles['buttons']}>
                <ButtonLink variant={main} to={`/software?row=${encodeURIComponent(listed.software_id)}`}>
                  Open it
                </ButtonLink>
              </div>
            </>
          ) : reply.software ? (
            <AddToWatchlist name={reply.software} />
          ) : (
            <div className={styles['buttons']}>
              <ButtonLink variant={main} to="/software">
                Open the Software watchlist
              </ButtonLink>
            </div>
          )}
        </div>
      </Card>
      {reply.also ? (
        <>
          <p>The rest of your request:</p>
          <NewestAnswer.Provider value={false}>
            <Answer reply={reply.also} typed={typed} page={NO_PAGE} />
          </NewestAnswer.Provider>
        </>
      ) : null}
    </>
  )
}

const NO_PAGE: Page = { ask: () => undefined, edit: () => undefined }

function RefusedAnswer({ reply, typed, page }: { reply: Extract<PlannerReply, { answer: 'refused' }>; typed: string; page: Page }) {
  const { rest } = refusalNext(reply)
  const main = useMainButton()
  return (
    <Card title="How approvals work">
      <div className={styles['pcardPart']}>
        <p>
          You asked me to skip a yes: <q>{reply.said}</q>. Any Approver on your team except you decides on your requests, in Teams. Nobody approves their own work, and nothing approves itself.
        </p>
        <p className="muted">{SAY_ANOTHER_WAY}</p>
        <div className={styles['buttons']}>
          {rest ? (
            <Button variant={main} onClick={() => page.ask(rest)}>
              Set it up with a yes
            </Button>
          ) : null}
          <Button variant={rest ? 'secondary' : main} onClick={() => page.edit(typed)}>
            Say it another way
          </Button>
        </div>
      </div>
    </Card>
  )
}

function AbilitiesAnswer() {
  const capabilities = useCapabilities()
  return (
    <>
      {capabilities.data ? (
        <CapabilityLists view={capabilities.data} />
      ) : (
        <p className="muted" role="status">
          {capabilities.isError ? 'I couldn’t load what I can do just now.' : 'Loading what I can do'}
        </p>
      )}
    </>
  )
}

function IdeasAnswer({ page }: { page: Page }) {
  const capabilities = useCapabilities()
  if (!capabilities.data) {
    return (
      <p className="muted" role="status">
        {capabilities.isError ? 'I couldn’t load the ideas just now.' : 'Loading ideas'}
      </p>
    )
  }
  return (
    <ul className={styles['starters']}>
      {startingPoints(capabilities.data).map((text) => (
        <li key={text} className={styles['starter']}>
          <div>
            <b>{text}</b>
          </div>
          <Button onClick={() => page.ask(text)}>Use this</Button>
        </li>
      ))}
    </ul>
  )
}

export function OfflineAnswer({ reply }: { reply: OfflineReply }) {
  const main = useMainButton()
  return (
    <>
      <ul className={styles['starters']}>
        {reply.starters.map((starter) => (
          <li key={starter.name} className={styles['starter']}>
            <div>
              <b>{starter.name}</b>
              <span className={styles['note']}>{starter.what}</span>
            </div>
            {starter.opens === 'software_watchlist' ? <ButtonLink to="/software">Open the Software watchlist</ButtonLink> : null}
          </li>
        ))}
      </ul>
      <div className={styles['buttons']}>
        <ButtonLink variant={main} to="/settings?tab=model">
          Connect a model
        </ButtonLink>
      </div>
    </>
  )
}

/** Where each section of a question answer lives. */
const LOOKED_AT = {
  watchlist: { label: 'Software', to: '/software' },
  workflows: { label: 'Workflows', to: '/workflows' },
  // The Workflows page leads with Needs you, the same place the Home tab count leads.
  needs_you: { label: 'Needs you', to: '/workflows' },
} as const

export const NEEDS_YOU_ANCHOR = 'needs-you'

/** The sections a question answer used, each a link to the screen it was read from. */
export function LookedAt({ sections }: { sections: QuestionReply['looked_at'] }) {
  if (sections.length === 0) return null
  return (
    <p className={styles['lookedAt']}>
      <span>Looked at</span>
      {sections.map((section) => (
        <Link key={section} to={LOOKED_AT[section].to}>
          {LOOKED_AT[section].label}
        </Link>
      ))}
    </p>
  )
}

function Dismissable({ children }: { children: (never: () => void) => ReactNode }) {
  const [gone, setGone] = useState(false)
  return gone ? <p className="muted">All right, never mind.</p> : children(() => setGone(true))
}

interface AnswerProps {
  readonly reply: PlannerReply
  readonly typed: string
  readonly page: Page
}

/** The body of one Planner answer, past its sentence. The three state answers are in StateAnswers. */
export function Answer({ reply, typed, page }: AnswerProps) {
  switch (reply.answer) {
    case 'setup_card':
    case 'part':
      return <SetupCardAnswer reply={reply} typed={typed} />
    case 'cant':
      return <CantAnswer reply={reply} typed={typed} />
    case 'watchlist':
      return <WatchlistAnswer reply={reply} typed={typed} />
    case 'which_software':
      return <Dismissable>{(never) => <WhichSoftware onNever={never} />}</Dismissable>
    case 'refused':
      return <RefusedAnswer reply={reply} typed={typed} page={page} />
    case 'abilities':
      return <AbilitiesAnswer />
    case 'ideas':
      return <IdeasAnswer page={page} />
    case 'offline':
      return <OfflineAnswer reply={reply} />
    case 'question':
      return <LookedAt sections={reply.looked_at} />
    case 'check_workflows':
    case 'why_stopped':
    case 'needs_me':
      return null
  }
}

