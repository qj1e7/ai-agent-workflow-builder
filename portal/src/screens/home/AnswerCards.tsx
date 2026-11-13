import { useId, useState, type ReactNode } from 'react'
import { Link } from '../../ui/Link'
import type { CantReply, CantRowView, OfflineReply, PartReply, PartView, PauseReply, PlannerReply, QuestionReply, ResumeReply, SetupCardReply, SwitchChoice, WatchlistReply } from '../../api/types'
import { useErrorWords } from '../../api/context'
import { useCapabilities } from '../../api/plannerQueries'
import { useMoveWorkflow } from '../../api/workflowQueries'
import { Button, ButtonLink } from '../../ui/Button'
import { OpenButton } from '../../ui/OpenItem'
import { AskTheTeam } from './AskTheTeam'
import { useAsker } from './asker'
import { cantLines, capabilityCard, oneLine, refusalNext, SAY_ANOTHER_WAY, startingPoints, stateWords, switchedSay, TAG_CANT, TAG_CHOICE, type Asker } from './answers'
import { cardFrom } from './card'
import { asksOnCard, cantOnCard, crossesInstead, crossesOnCard, followedNothing } from './parts'
import { SetupCard, type CardStart } from './SetupCard'
import { NewestAnswer, useMainButton } from './primary'
import { AddToWatchlist, WhichSoftware } from './WatchlistCard'
import { SoftwareActions } from './WatchlistActions'
import styles from './Planner.module.css'
import setup from './SetupCard.module.css'

/** What a card can ask the page to do. Both go through the Planner or the box, so nothing here reaches a set-up on its own. */
export interface Page {
  /** Sends words to the Planner as a new question. */
  readonly ask: (text: string) => void
  /** Puts words back in the box for the person to change. */
  readonly edit: (text: string) => void
  /** Puts focus back in the box, as when she backs out of a card. */
  readonly box: () => void
}


/** The parts of a reply, with each can’t row of a part answer kept as a cross even if no part names it, so none is dropped. */
function partsOf(reply: SetupCardReply | PartReply): readonly PartView[] {
  if (reply.answer !== 'part' || reply.parts.some((part) => part.reason === 'cant_do')) return reply.parts
  const crosses = cantLines(reply.cant).map((line): PartView => ({ text: line.text, mark: 'cant', reason: 'cant_do', note: line.note || null, choices: [] }))
  return [...reply.parts, ...crosses]
}

/** An answer inside another keeps the whole request’s crosses that `keep` picks, so its card still marks them and keeps them as left out. */
const withCrosses = <T extends PlannerReply>(inner: T, outer: PlannerReply, keep: (part: PartView) => boolean): T => ({ ...inner, parts: outer.parts.filter(keep) })

/** A set-up card from the Planner’s rows and parts. The person’s own words go with it, so a saved draft keeps them. */
function startOf(reply: SetupCardReply | PartReply, typed: string): CardStart {
  return { form: cardFrom(reply.name, reply.rows, typed, partsOf(reply)), plan: null, draftId: null, similar: reply.similar }
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

/** A set-up card, and a part answer as one: what it can’t do is a cross on the card itself, with Ask the team. */
export function SetupCardAnswer({ reply, typed }: { reply: SetupCardReply | PartReply; typed: string }) {
  return <SetupCard start={startOf(reply, typed)} />
}

/** A can’t the registry says in one line: the line as the head, what she has instead under it, and Ask the team unless the platform won’t do it. */
function OneLineCant({ row, typed, secondary }: { row: CantRowView; typed: string; secondary: boolean }) {
  return (
    <Card title={row.note.replace(/\.$/, '')}>
      <div className={styles['pcardPart']}>
        <p className="muted">{row.instead}</p>
      </div>
      {row.unsupported ? null : (
        <div className={styles['footer']}>
          <AskTheTeam capability={row.system ?? row.text} starter={`I asked the Planner for: ${typed}\n\nIt can't do this yet: ${row.text}`} secondary={secondary} />
        </div>
      )}
    </Card>
  )
}

/**
 * A can’t answer names only a place the platform can’t send to. Anything else it can’t do, or a clause it didn’t follow, is a
 * cross on the card that sets up the part it can (spec 6.3 and 6.5). A can’t the registry says in one line gets a card of its own.
 */
export function CantAnswer({ reply, typed }: { reply: CantReply; typed: string }) {
  const alternative = reply.alternative
  if (cantOnCard(reply) && alternative?.answer === 'setup_card') return <SetupCard start={startOf(withCrosses(alternative, reply, crossesOnCard), typed)} />
  const named = reply.cant.filter((row) => row.needs !== null)
  const rows = cantLines(named.filter((row) => !oneLine(row)))
  const card = alternative?.answer === 'setup_card' ? <SetupCard start={startOf(withCrosses(alternative, reply, crossesInstead), typed)} /> : null
  const watch = alternative?.answer === 'watchlist' ? <WatchlistAnswer reply={withCrosses(alternative, reply, asksOnCard)} typed={typed} /> : null
  // With no can’t of its own, the card would be empty: the clauses it didn’t follow are drawn above it.
  if (named.length === 0) return card ?? watch
  return (
    <>
      {named.filter(oneLine).map((row) => (
        <OneLineCant key={row.text} row={row} typed={typed} secondary={alternative !== null} />
      ))}
      {rows.length > 0 ? (
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
              capability={reply.cant.find((row) => row.system && !oneLine(row))?.system ?? rows[0]?.text ?? 'something new'}
              starter={`I asked the Planner for: ${typed}\n\nIt can't do this yet: ${rows.map((line) => line.text).join('; ')}`}
              secondary={alternative !== null}
            />
          </div>
        </Card>
      ) : null}
      {card ? (
        <>
          <h3 className={styles['altHeading']}>What I can do instead</h3>
          {card}
        </>
      ) : null}
      {watch}
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
                <OpenButton variant={main} item={{ kind: 'software', id: listed.software_id }} to={`/software?row=${encodeURIComponent(listed.software_id)}`}>
                  Open it
                </OpenButton>
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
            <Answer reply={withCrosses(reply.also, reply, asksOnCard)} typed={typed} page={NO_PAGE} />
          </NewestAnswer.Provider>
        </>
      ) : null}
    </>
  )
}

const NO_PAGE: Page = { ask: () => undefined, edit: () => undefined, box: () => undefined }

function RefusedAnswer({ reply, typed, page }: { reply: Extract<PlannerReply, { answer: 'refused' }>; typed: string; page: Page }) {
  // Someone who isn't an Operator sets nothing up, so the refusal offers them no set-up with a yes. Their main button is the request
  // to open, drawn under the card.
  const operator = useAsker() === 'operator'
  const { rest } = operator ? refusalNext(reply) : { rest: null }
  const newest = useMainButton()
  const main = operator ? newest : 'secondary'
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

/** What someone who isn't an Operator can ask, each a question the Planner answers (ADR 0043). */
export const APPROVER_CAN = ['Show what waits for your yes', 'Show exactly what a change will write', 'Show your past decisions'] as const

const FOLLOWED_NOTHING: Readonly<Record<Asker, string>> = {
  operator: 'I can watch software releases, fix stopped runs and change your workflows.',
  approver: 'I can show what waits for your yes, and your past decisions.',
}

function WhatICanDo({ lines, notYet = [] }: { lines: readonly { key: string; text: string; state: string | null }[]; notYet?: readonly string[] }) {
  return (
    <Card title="What I can do">
      <ul className={styles['lines']}>
        {lines.map((line) => (
          <li key={line.key}>
            {line.text}
            {line.state ? <span className={styles['note']}>{line.state}</span> : null}
          </li>
        ))}
      </ul>
      {notYet.length > 0 ? (
        <div className={styles['footer']}>
          <p>Not yet: {notYet.join(', ')}.</p>
        </div>
      ) : null}
    </Card>
  )
}

/** What I can do, in the registry’s short words with the platform’s state of each, or that it followed none of the request. */
function AbilitiesAnswer({ reply }: { reply: PlannerReply }) {
  const asker = useAsker()
  const nothing = followedNothing(reply)
  const capabilities = useCapabilities({ enabled: asker === 'operator' && !nothing })
  if (nothing) {
    return (
      <Card title="I didn’t follow that">
        <div className={styles['pcardPart']}>
          <p className="muted">{FOLLOWED_NOTHING[asker]}</p>
        </div>
      </Card>
    )
  }
  if (asker === 'approver') return <WhatICanDo lines={APPROVER_CAN.map((text) => ({ key: text, text, state: null }))} />
  if (!capabilities.data) {
    return (
      <p className="muted" role="status">
        {capabilities.isError ? 'I couldn’t load what I can do just now.' : 'Loading what I can do'}
      </p>
    )
  }
  const { can, notYet } = capabilityCard(capabilities.data)
  return <WhatICanDo lines={can.map((entry) => ({ key: entry.id, text: entry.short, state: stateWords(entry) }))} notYet={notYet} />
}

/**
 * Which workflow a pause or a resume means, when the words fit several, none, or a watched software’s check, which is the whole
 * Software watchlist. Nothing changed yet: the one she picks is paused or resumed through its own route, and the line says so.
 */
function SwitchChoices({ reply }: { reply: PauseReply | ResumeReply }) {
  const move = useMoveWorkflow()
  const errorWords = useErrorWords()
  const [picked, setPicked] = useState<SwitchChoice | null>(null)
  if (reply.choices.length === 0) return null
  if (picked && move.isSuccess) {
    const wanted = reply.answer === 'pause' ? 'paused' : 'on'
    return <p role="status">{switchedSay(reply.answer, picked.name, picked.state === wanted)}</p>
  }
  const pick = (choice: SwitchChoice) => {
    setPicked(choice)
    move.mutate({ move: reply.answer, useCaseId: choice.use_case_id })
  }
  return (
    <>
      <div className={styles['buttons']}>
        {reply.choices.map((choice) => (
          <button key={choice.use_case_id} type="button" className={setup['choice']} disabled={move.isPending} onClick={() => pick(choice)}>
            {choice.name}
          </button>
        ))}
      </div>
      {move.isError ? (
        <p className={styles['problem']} role="alert">
          {errorWords(move.error)}
        </p>
      ) : null}
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

/** The body of one Planner answer, past its sentence. The state answers are in StateAnswers, and the edit card draws its own sentence. */
export function Answer({ reply, typed, page }: AnswerProps) {
  const asker = useAsker()
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
      return <AbilitiesAnswer reply={reply} />
    case 'pause':
    case 'resume':
      return <SwitchChoices reply={reply} />
    case 'ideas':
      return <IdeasAnswer page={page} />
    case 'offline':
      return asker === 'operator' ? <OfflineAnswer reply={reply} /> : null
    case 'question':
      return (
        <>
          <LookedAt sections={reply.looked_at} />
          {(reply.about_software ?? []).length > 0 ? <SoftwareActions names={reply.about_software ?? []} /> : null}
        </>
      )
    case 'edit':
    case 'check_workflows':
    case 'why_stopped':
    case 'needs_me':
    case 'operators':
    case 'decided':
    case 'decide':
      return null
  }
}

