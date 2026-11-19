import { useContext, useEffect, useState, type ReactNode } from 'react'
import { Link } from '../../ui/Link'
import type { AbilitiesReply, N8nReply, CantReply, CantRowView, CapabilitiesView, FreeReply, OfflineReply, PartReply, PartView, PauseReply, PlannerReply, QuestionReply, ResumeReply, SetupCardReply, SwitchChoice, WatchlistReply } from '../../api/types'
import { useErrorWords } from '../../api/context'
import { useCapabilities } from '../../api/plannerQueries'
import { useMoveWorkflow } from '../../api/workflowQueries'
import { Button, ButtonLink } from '../../ui/Button'
import { Card } from '../../ui/Card'
import { OpenButton } from '../../ui/OpenItem'
import { useWatchlist } from '../../api/queries'
import { sentenceFor, softwarePath, stateOf } from '../software/software'
import softwareStyles from '../software/Software.module.css'
import { ChangedInN8nAnswer } from './ChangedCard'
import { AskTheTeam } from './AskTheTeam'
import { useAsker } from './asker'
import { cantLines, capabilityCard, offerLabel, oneLine, questionActions, refusalNext, SAY_ANOTHER_WAY, START_LEAD, startingPoints, startSteps, stateWords, switchedSay, unwatchedSay, watchlistSwitchNote, type Asker } from './answers'
import { cardFrom } from './card'
import { asksOnCard, cantOnCard, crossesInstead, crossesOnCard, followedNothing } from './parts'
import { SetupCard, type CardStart } from './SetupCard'
import { CardLive, NewestAnswer, useMainButton } from './primary'
import { CardMemoryContext } from './cardMemory'
import { useChatNavigate } from '../../ui/fromChat'
import { AddToWatchlist, WhichSoftware } from './WatchlistCard'
import { SoftwareActions } from './WatchlistActions'
import { ExplainAnswer } from '../explain/ExplainAnswer'
import { RemoveSoftwareAnswer } from './RemoveSoftware'
import { DraftButton } from '../drafted/DraftButton'
import { DraftedCard } from '../drafted/DraftedCard'
import styles from './Planner.module.css'

/** What a card can ask the page to do. Both go through the Planner or the box, so nothing here reaches a set-up on its own. */
export interface Page {
  /** Sends words to the Planner as a new question. */
  readonly ask: (text: string) => void
  /** Puts words back in the box for the person to change. */
  readonly edit: (text: string) => void
  /** Puts focus back in the box, as when they back out of a card. */
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

/** A set-up card, and a part answer as one: what it can’t do is a cross on the card itself, with Ask the team. */
export function SetupCardAnswer({ reply, typed }: { reply: SetupCardReply | PartReply; typed: string }) {
  return <SetupCard start={startOf(reply, typed)} />
}

/**
 * A can’t the registry says in one line: the line as the head, what they have instead under it, and Ask the team. Even what the
 * platform won’t do gets Ask the team, so no can’t is ever bare (ADR 0047): the team can still hear that someone needs it.
 */
function OneLineCant({ row, typed }: { row: CantRowView; typed: string }) {
  const why = row.unsupported ? 'It won\'t do this' : 'It can\'t do this yet'
  return (
    <Card title={row.note.replace(/\.$/, '')} foot={<AskTheTeam capability={row.system ?? row.text} starter={`I asked the Planner for: ${typed}\n\n${why}: ${row.text}`} />}>
      <p className="muted">{row.instead}</p>
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
        <OneLineCant key={row.text} row={row} typed={typed} />
      ))}
      {rows.length > 0 ? (
        <Card
          title="What I can’t do yet"
          foot={
            <AskTheTeam
              capability={reply.cant.find((row) => row.system && !oneLine(row))?.system ?? rows[0]?.text ?? 'something new'}
              starter={`I asked the Planner for: ${typed}\n\nIt can't do this yet: ${rows.map((line) => line.text).join('; ')}`}
              secondary={alternative !== null}
            />
          }
        >
          <ul className={styles['lines']}>
            {rows.map((line) => (
              <li key={line.text}>
                <b>{line.text}</b>
                {line.note ? <span className={styles['note']}>{line.note}</span> : null}
              </li>
            ))}
          </ul>
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

/**
 * The sketch's software card: a watched software's name, its pill and where it stands, in the watchlist's own words, or that it
 * isn't on the watchlist yet, with Watch it. Asked about its version, it also says the version they run isn't known. Watch it adds
 * it to the Software watchlist, which is where watched software lives here, after finding its GitHub project.
 */
function SoftwareCard({ name, listed, word }: { name: string; listed: WatchlistReply['already_listed']; word: string }) {
  const main = useMainButton()
  const operator = useAsker() === 'operator'
  const watchlist = useWatchlist({ enabled: listed !== null })
  const [watching, setWatching] = useState(false)
  const row = listed ? watchlist.data?.software.find((software) => software.id === listed.software_id) : undefined
  const state = row ? stateOf(row) : null
  if (listed) {
    return (
      <Card
        title={row?.name ?? listed.name}
        pill={
          state ? (
            <span className={softwareStyles['pill']} data-tone={state.tone}>
              {state.words}
            </span>
          ) : undefined
        }
        actions={
          <OpenButton variant={main} item={{ kind: 'software', id: listed.software_id }} to={softwarePath(listed.software_id)}>
            Open it
          </OpenButton>
        }
      >
        <p>{row ? sentenceFor(row) : `${listed.name} is on the Software watchlist.`}</p>
      </Card>
    )
  }
  return (
    <Card
      title={name}
      actions={
        operator && !watching ? (
          <Button variant={main} onClick={() => setWatching(true)}>
            Watch it
          </Button>
        ) : undefined
      }
    >
      <p className="muted">{unwatchedSay(word)}</p>
      {watching ? <AddToWatchlist name={name} /> : null}
    </Card>
  )
}

export function WatchlistAnswer({ reply, typed }: { reply: WatchlistReply; typed: string }) {
  const listed = reply.already_listed
  const main = useMainButton()
  return (
    <>
      {listed || reply.software ? (
        <SoftwareCard name={listed?.name ?? reply.software ?? ''} listed={listed} word={reply.word} />
      ) : (
        <Card title="The Software watchlist" actions={<ButtonLink variant={main} to="/software">Open the Software watchlist</ButtonLink>} />
      )}
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
    <Card
      title="How approvals work"
      actions={
        <>
          {rest ? (
            <Button variant={main} onClick={() => page.ask(rest)}>
              Set it up with a yes
            </Button>
          ) : null}
          <Button variant={rest ? 'secondary' : main} onClick={() => page.edit(typed)}>
            Say it another way
          </Button>
        </>
      }
    >
      <p>
        You asked me to skip a yes: <q>{reply.said}</q>. Any Approver on your team except you decides on your requests, in Teams. Nobody approves their own work, and nothing approves itself.
      </p>
      <p className="muted">{SAY_ANOTHER_WAY}</p>
    </Card>
  )
}

/** What someone who isn't an Operator can ask, each a question the Planner answers (ADR 0043). */
export const APPROVER_CAN = ['Show what waits for your yes', 'Show exactly what a change will write', 'Show your past decisions'] as const

export const FOLLOWED_NOTHING: Readonly<Record<Asker, string>> = {
  operator: 'I can watch software releases, fix stopped runs and change your workflows.',
  approver: 'I can show what waits for your yes, and your past decisions.',
}

function WhatICanDo({ lines, notYet = [] }: { lines: readonly { key: string; text: string; state: string | null }[]; notYet?: readonly string[] }) {
  return (
    <Card title="What I can do">
      <ul className={styles['caps']}>
        {lines.map((line) => (
          <li key={line.key}>
            {line.text}
            {line.state ? <span className={styles['note']}>{line.state}</span> : null}
          </li>
        ))}
      </ul>
      {notYet.length > 0 ? <p className={styles['note']}>Not yet: {notYet.join(', ')}.</p> : null}
    </Card>
  )
}

export function SayItAnotherWay({ typed, page, variant }: { typed: string; page: Page; variant: 'primary' | 'secondary' }) {
  return (
    <Button variant={variant} onClick={() => page.edit(typed)}>
      Say it another way
    </Button>
  )
}

/** The sketch’s I didn’t follow that card: what the role can ask, and the way back to the box to say it another way. Never a bare cross. */
export function DidntFollowCard({ typed, page }: { typed: string; page: Page }) {
  const asker = useAsker()
  const main = useMainButton()
  return (
    <Card
      title="I didn’t follow that"
      actions={<SayItAnotherWay typed={typed} page={page} variant={main} />}
    >
      <p className="muted">{FOLLOWED_NOTHING[asker]}</p>
    </Card>
  )
}

/** How to start: what the app is for, the steps from their words to the yes, then the registry’s examples as chips that ask the Planner for them. */
function HowToStart({ view, page }: { view: CapabilitiesView; page: Page }) {
  const examples = startingPoints(view)
  return (
    <Card title="How to start">
      <p>{START_LEAD}</p>
      <ol className={styles['steps']}>
        {startSteps(view).map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
      {examples.length > 0 ? (
        <div className={styles['chips']} role="group" aria-label="Try one">
          {examples.map((text) => (
            <button key={text} type="button" className={styles['chip']} onClick={() => page.ask(text)}>
              {text}
            </button>
          ))}
        </div>
      ) : null}
    </Card>
  )
}

/** What I can do, in the registry’s short words with the platform’s state of each, or how to start when that was asked, or that it followed none of the request. */
function AbilitiesAnswer({ reply, typed, page }: { reply: AbilitiesReply; typed: string; page: Page }) {
  const asker = useAsker()
  const nothing = followedNothing(reply)
  const capabilities = useCapabilities({ enabled: asker === 'operator' && !nothing })
  if (nothing) return <DidntFollowCard typed={typed} page={page} />
  if (asker === 'approver') return <WhatICanDo lines={APPROVER_CAN.map((text) => ({ key: text, text, state: null }))} />
  if (!capabilities.data) {
    return (
      <p className="muted" role="status">
        {capabilities.isError ? 'I couldn’t load what I can do just now.' : 'Loading what I can do'}
      </p>
    )
  }
  if (reply.how_to_start) return <HowToStart view={capabilities.data} page={page} />
  const { can, notYet } = capabilityCard(capabilities.data)
  return <WhatICanDo lines={can.map((entry) => ({ key: entry.id, text: entry.short, state: stateWords(entry) }))} notYet={notYet} />
}

const MOST_CHOICES = 5

/**
 * Which workflow a pause or a resume means, when the words fit several, none, or a watched software’s check, which is the whole
 * Software watchlist. Nothing changed yet: the one they pick is paused or resumed through its own route, and the line says so.
 */
function SwitchChoices({ reply }: { reply: PauseReply | ResumeReply }) {
  const move = useMoveWorkflow()
  const errorWords = useErrorWords()
  const [picked, setPicked] = useState<SwitchChoice | null>(null)
  if (reply.choices.length === 0) return null
  const title = reply.answer === 'pause' ? 'Pause a workflow' : 'Turn a workflow back on'
  if (picked && move.isSuccess) {
    const wanted = reply.answer === 'pause' ? 'paused' : 'on'
    return (
      <Card title={title}>
        <p role="status">{switchedSay(reply.answer, picked.name, picked.state === wanted)}</p>
      </Card>
    )
  }
  const pick = (choice: SwitchChoice) => {
    setPicked(choice)
    move.mutate({ move: reply.answer, useCaseId: choice.use_case_id })
  }
  const shown = reply.choices.slice(0, MOST_CHOICES)
  const more = reply.choices.length - shown.length
  // The sketch's 36 px chips, one per workflow, as on Home.
  return (
    <Card title={title}>
      <div className={styles['chips']}>
        {shown.map((choice) => (
          <button key={choice.use_case_id} type="button" className={styles['chip']} aria-disabled={move.isPending || undefined} onClick={() => !move.isPending && pick(choice)}>
            {choice.name}
          </button>
        ))}
        {more > 0 ? (
          <Link to="/workflows" className={styles['moreChoices']}>
            and {more} more
          </Link>
        ) : null}
      </div>
      {reply.choices.some((choice) => choice.watchlist) ? <p className={styles['note']}>{watchlistSwitchNote(reply.answer)}</p> : null}
      {move.isError ? (
        <p className={styles['problem']} role="alert">
          {errorWords(move.error)}
        </p>
      ) : null}
    </Card>
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

/** A free reply’s choices as the sketch’s 36 px chips. Each is sent to the Planner as the person’s next message. */
export function ReplyChoices({ choices, ask }: { choices: readonly string[]; ask: (text: string) => void }) {
  return (
    <div className={styles['chips']}>
      {choices.map((choice) => (
        <button key={choice} type="button" className={styles['chip']} onClick={() => ask(choice)}>
          {choice}
        </button>
      ))}
    </div>
  )
}

/** The one button under a free reply that can’t: its offer, which says the request it sends, or Ask the team when nothing is close. */
export function ReplyCant({ reply, typed, ask, variant }: { reply: FreeReply; typed: string; ask: (text: string) => void; variant: 'primary' | 'secondary' }) {
  const offer = reply.offer
  if (offer) return <Button variant={variant} onClick={() => ask(offer.request)}>{offerLabel(offer.request)}</Button>
  return <AskTheTeam capability={typed} starter={`I asked the Planner for: ${typed}`} secondary={variant === 'secondary'} />
}

/** What sits under a free reply’s words, one case for each form. The words themselves are drawn as the answer’s sentence, as plain text. */
function FreeReplyAnswer({ reply, typed, page }: { reply: FreeReply; typed: string; page: Page }) {
  const main = useMainButton()
  const looked = <LookedAt sections={reply.looked_at} />
  switch (reply.form) {
    case 'answer':
      return looked
    case 'clarify':
      return (
        <>
          {looked}
          <ReplyChoices choices={reply.choices} ask={page.ask} />
        </>
      )
    case 'cant':
      return (
        <>
          {looked}
          <div className={styles['buttons']}>
            <ReplyCant reply={reply} typed={typed} ask={page.ask} variant={main} />
          </div>
        </>
      )
    default:
      return reply.form satisfies never
  }
}

function Dismissable({ children }: { children: (never: () => void) => ReactNode }) {
  const [gone, setGone] = useState(false)
  return gone ? <p className="muted">All right, never mind.</p> : children(() => setGone(true))
}

/** Where the Planner's n8n answer opens: the workflow's page on its In n8n tab, or nowhere when it named none it may open. */
export function n8nTabOf(reply: N8nReply): string | null {
  return reply.can_open && reply.use_case_id !== null ? `/workflows/${reply.use_case_id}?view=n8n` : null
}

/** The sketch's "Here it is in n8n.": the newest such answer opens its workflow's In n8n tab, once. Coming back to the chat never opens it again. */
function N8nAnswer({ reply }: { reply: N8nReply }) {
  const memory = useContext(CardMemoryContext)
  const newest = useContext(CardLive)
  const go = useChatNavigate()
  const to = n8nTabOf(reply)
  useEffect(() => {
    if (to === null || !newest || memory.beside.kept()) return
    memory.beside.keep(true)
    go(to)
  }, [to, newest, memory, go])
  return null
}

interface AnswerProps {
  readonly reply: PlannerReply
  readonly typed: string
  readonly page: Page
  readonly focus?: string | null
}

/** The body of one Planner answer, past its sentence. The state answers are in StateAnswers, and the edit card draws its own sentence. */
export function Answer({ reply, typed, page, focus = null }: AnswerProps) {
  const asker = useAsker()
  switch (reply.answer) {
    case 'setup_card':
      return <SetupCardAnswer reply={reply} typed={typed} />
    case 'part':
      return (
        <>
          <SetupCardAnswer reply={reply} typed={typed} />
          <DraftButton words={reply.draft_words} />
        </>
      )
    case 'cant':
      return (
        <>
          <CantAnswer reply={reply} typed={typed} />
          <DraftButton words={reply.draft_words} />
        </>
      )
    case 'watchlist':
      return <WatchlistAnswer reply={reply} typed={typed} />
    case 'which_software':
      return <Dismissable>{(never) => <WhichSoftware onNever={never} />}</Dismissable>
    case 'refused':
      return <RefusedAnswer reply={reply} typed={typed} page={page} />
    case 'abilities':
      return <AbilitiesAnswer reply={reply} typed={typed} page={page} />
    case 'pause':
    case 'resume':
      return <SwitchChoices reply={reply} />
    case 'remove_software':
      return <RemoveSoftwareAnswer reply={reply} />
    case 'explain':
      return <ExplainAnswer reply={reply} focus={focus} page={page} />
    case 'ideas':
      return <IdeasAnswer page={page} />
    case 'offline':
      return asker === 'operator' ? <OfflineAnswer reply={reply} /> : null
    case 'question': {
      const names = questionActions(reply, asker)
      if (names.length === 0) return <LookedAt sections={reply.looked_at} />
      return (
        <Card title={names.length === 1 ? names[0] : 'On your watchlist'}>
          <LookedAt sections={reply.looked_at} />
          <SoftwareActions names={names} named={names.length > 1} />
        </Card>
      )
    }
    case 'reply':
      return <FreeReplyAnswer reply={reply} typed={typed} page={page} />
    case 'didnt_follow':
      return <DidntFollowCard typed={typed} page={page} />
    case 'changed_in_n8n':
      return <ChangedInN8nAnswer reply={reply} />
    case 'n8n':
      return <N8nAnswer reply={reply} />
    case 'edit':
    case 'check_workflows':
    case 'why_stopped':
    case 'needs_me':
    case 'operators':
    case 'decided':
    case 'decide':
      return null
    case 'draft_started':
      return reply.drafted_id === null ? null : <DraftedCard draftedId={reply.drafted_id} revision={1} />
  }
}

