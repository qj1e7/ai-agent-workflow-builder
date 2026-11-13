import { useEffect, useMemo, useRef, useState } from 'react'
import { flushSync } from 'react-dom'
import { useSearchParams } from 'react-router'
import { Link } from '../../ui/Link'
import { useCacheScope } from '../../api/context'
import { useHome } from '../../api/homeQueries'
import { isOperator } from '../../api/me'
import { useCapabilities, useDrafts } from '../../api/plannerQueries'
import { useMe, useModelSettings, useWatchlist } from '../../api/queries'
import type { HomeOut, PlannerReply } from '../../api/types'
import { PageHead } from '../../shell/PageHead'
import { Button, ButtonLink } from '../../ui/Button'
import { useMediaQuery } from '../../ui/media'
import { motionAllowed } from '../../ui/motion'
import { Toast } from '../../ui/Toast'
import { PlannerBot, type BotState } from '../../ui/PlannerBot'
import { restoreDraft } from './card'
import { NEEDS_YOU_ANCHOR, type Page } from './AnswerCards'
import { CapabilityLists } from './CapabilityLists'
import { APPROVER_SUGGESTIONS, approverLine, HOME_NEEDS_SHOWN, moreWords, needsOf, needsTotal, SEE_ALL_WORDS, suggestionsOf, type Needs } from './home'
import { NeedRows, NeedsSection, useArrival } from './NeedsSection'
import { ChatView, NEWEST } from './ChatView'
import { useChat } from './ChatProvider'
import { PlannerBox } from './PlannerBox'
import homeStyles from './Home.module.css'
import styles from './Planner.module.css'

interface HomePageProps {
  /** "Good afternoon, Alice": the small line above Home's question, and the heading while Home can't load. */
  readonly greeting: string
  readonly today: string
  readonly now: Date
}

export function HomePage({ greeting, today, now }: HomePageProps) {
  const home = useHome()
  const loaded = home.data
  return (
    <div className={homeStyles['home']}>
      {loaded && home.isError ? (
        <p className="muted" role="status">
          Could not refresh. Trying again in a moment.
        </p>
      ) : null}
      {loaded ? (
        <HomeBody greeting={greeting} home={loaded} now={now} />
      ) : home.isError ? (
        <>
          <PageHead heading={greeting} lead={today} />
          <p role="alert">Home could not be loaded.</p>
          <Button onClick={() => void home.refetch()}>Try again</Button>
        </>
      ) : (
        <p className="muted" role="status">
          Loading what needs you
        </p>
      )}
    </div>
  )
}

/**
 * One heading for the whole visit, so the shell's focus stays on it. Home draws no heading while it loads, and the shell moves focus to the first one drawn.
 * Each person gets their own Home, so nothing one person had on a card is ever drawn, or saved, for the next.
 */
export function HomeBody({ greeting, home, now }: { greeting: string; home: HomeOut; now: Date }) {
  const operator = isOperator(useMe().data)
  const person = useCacheScope()
  return <PlannerHome key={person} greeting={greeting} home={home} now={now} operator={operator} />
}

const PHONE = '(max-width: 600px)'

const DRAFT_GONE = 'That draft is gone. Ask for it again below.'
/** Answers that are a card to work on. Focus goes to the card's heading; any other answer hands it back to the box. */
const CARD_ANSWERS: ReadonlySet<PlannerReply['answer']> = new Set(['setup_card', 'part', 'watchlist', 'edit'])
/** An Operator's question on Home, day one included (the sketch's heading). */
export const OPERATOR_HEADING = 'What should run by itself?'
const OFFLINE_HEADING = 'I can’t read new requests until an AI model is connected'
const OFFLINE_LEAD =
  'Without an AI model, the Planner can’t answer questions. The Software watchlist keeps checking for new releases.'
const APPROVER_OFFLINE_HEADING = 'I can’t answer questions until an AI model is connected'
const APPROVER_OFFLINE_LEAD = 'An Operator can connect one in Settings.'
const APPROVER_NOTE = 'You’re an Approver, so you decide on requests. Operators set up workflows.'

/** Needs you on Home: the most urgent few of the grouped list. The count is the platform’s, and the model’s row stays, so every row counted is listed. */
function needsHere(home: HomeOut): Needs {
  return { ...needsOf(home, HOME_NEEDS_SHOWN), total: needsTotal(home) }
}

/**
 * The first message folds the hero into the chat: the box and its chips glide to the bottom, as a view transition, unless motion
 * is reduced or the browser has none.
 */
function fold(change: () => void): void {
  if (typeof document.startViewTransition !== 'function' || !motionAllowed()) {
    change()
    return
  }
  document.startViewTransition(() => flushSync(change))
}

/**
 * Home, the chat with the Planner (spec 5). An Operator asks for anything. Someone who isn’t an Operator gets the same calm Home with
 * the box for questions only, their three questions as suggestions and Needs you in full (spec 5.3). The server refuses them every
 * change, so the Portal only draws no control that changes anything.
 */
function PlannerHome({ greeting, home, now, operator }: { greeting: string; home: HomeOut; now: Date; operator: boolean }) {
  const model = useModelSettings()
  const capabilities = useCapabilities({ enabled: operator })
  const chat = useChat()
  const { thread, text, problem, busy } = chat
  const [keys, setKeys] = useState(0)
  const boxRef = useRef<HTMLTextAreaElement>(null)
  const focusOn = useRef<number | null>(null)
  const phone = useMediaQuery(PHONE)
  const [params, setParams] = useSearchParams()
  const wanted = operator ? params.get('draft') : null
  const drafts = useDrafts(wanted !== null)
  const reopened = useRef<string | null>(null)
  /** The draft id the newest card wrote in the address, as opposed to one Resume brought here. */
  const written = useRef<string | null>(null)
  const offline = model.data !== undefined && model.data.active === null
  const empty = thread.messages.length === 0
  const needs = useMemo(() => (operator ? needsHere(home) : needsOf(home)), [home, operator])
  const arrival = useArrival(needs.shown.map((need) => need.key))
  const watching = useWatchlist({ enabled: operator }).data?.software.length
  const watched = !operator || (watching !== undefined && watching > 0)
  const suggestions = useMemo(() => (operator ? suggestionsOf(watching, capabilities.data) : APPROVER_SUGGESTIONS), [operator, watching, capabilities.data])
  const { resume, type, setProblem } = chat

  // Resume on Workflows lands here with the draft's id in the address, and the draft opens as the card it was, after any
  // conversation. The newest card writes its own draft's id there too, and that card is already shown.
  const newest = thread.messages.at(-1)
  const newestDraft = newest ? chat.cardMemory(newest.id).kept()?.draft : undefined
  useEffect(() => {
    if (wanted === null) {
      reopened.current = null
      written.current = null
      return
    }
    if (newestDraft === wanted) {
      written.current = wanted
      return
    }
    if (reopened.current === wanted) return
    // The card that wrote it is still shown above, now that a newer answer came, so the address goes back to the chat.
    if (written.current === wanted) {
      written.current = null
      setParams({}, { replace: true })
      return
    }
    if (!drafts.data || (drafts.isStale && !drafts.isFetchedAfterMount)) return
    reopened.current = wanted
    setParams({}, { replace: true })
    const found = drafts.data.find((saved) => saved.draft_id === wanted)
    const { form, plan } = found ? restoreDraft(found) : { form: null, plan: null }
    if (form !== null && form.rows.length > 0) {
      focusOn.current = thread.last + 1
      resume({ form, plan, draftId: wanted, similar: null, ...(found ? { resumed: found } : {}) })
      return
    }
    setTimeout(() => {
      if (form === null) setProblem(DRAFT_GONE)
      else type(form.text)
      boxRef.current?.focus()
    }, 0)
  }, [wanted, newestDraft, drafts.data, drafts.isStale, drafts.isFetchedAfterMount, thread.last, setParams, resume, type, setProblem])

  // The box is off while the Planner answers, so focus would fall to the page. A card takes it at its heading, and any other
  // answer, or a send that failed, hands it back to the box.
  useEffect(() => {
    if (newest === undefined) return
    if (newest.kind === 'thinking') {
      focusOn.current = newest.id
      return
    }
    if (focusOn.current === null) return
    const arrived = newest.id === focusOn.current
    focusOn.current = null
    const card = arrived && (newest.kind === 'card' || (newest.kind === 'reply' && CARD_ANSWERS.has(newest.reply.answer)))
    const heading = card ? document.querySelector<HTMLElement>(`${NEWEST} section h3`) : null
    if (heading) {
      heading.tabIndex = -1
      heading.focus({ preventScroll: true })
    } else boxRef.current?.focus()
  }, [newest])

  const page: Page = {
    ask: (words) => {
      if (!busy) chat.send({ text: words }, words, null)
    },
    edit: (words) => {
      chat.type(words)
      setTimeout(() => boxRef.current?.focus(), 0)
    },
    box: () => setTimeout(() => boxRef.current?.focus(), 0),
  }

  const hero: BotState = offline ? 'sorry' : busy ? 'thinking' : text.trim() !== '' ? 'listening' : 'idle'
  const look = ((text.length % 24) - 12) / 12
  const toast = <Toast message={chat.note} onDismiss={chat.readNote} focusAfter={() => boxRef.current ?? document.querySelector<HTMLElement>('main h1')} />

  if (offline && !operator) {
    return (
      <div className={styles['planner']}>
        <div className={`${styles['welcome']} ${styles['offline']}`}>
          <PlannerBot state="sorry" size={phone ? 96 : 128} />
          <h1 tabIndex={-1}>{APPROVER_OFFLINE_HEADING}</h1>
          <p className={styles['lead']}>
            {APPROVER_OFFLINE_LEAD} {approverLine(home)}
          </p>
        </div>
        {needs.shown.length > 0 ? <NeedsHere needs={needs} now={now} arrival={arrival} full /> : null}
        <p className={`muted ${styles['centred']}`}>{APPROVER_NOTE}</p>
      </div>
    )
  }

  if (offline) {
    return (
      <div className={styles['planner']}>
        <div className={`${styles['welcome']} ${styles['offline']}`}>
          <PlannerBot state="sorry" size={phone ? 96 : 128} />
          <h1 tabIndex={-1}>{OFFLINE_HEADING}</h1>
          <p className={styles['lead']}>{OFFLINE_LEAD}</p>
          <div className={styles['buttons']}>
            <ButtonLink variant="primary" to="/settings?tab=model">
              Connect a model
            </ButtonLink>
          </div>
        </div>
        {needs.shown.length > 0 ? <NeedsHere needs={needs} now={now} arrival={arrival} quiet connectAbove /> : null}
        {capabilities.data ? <CapabilityLists view={capabilities.data} /> : null}
      </div>
    )
  }

  const send = (go: () => void) => (empty ? fold(go) : go())
  const box = (
    <PlannerBox
      text={text}
      busy={busy}
      empty={empty}
      problem={problem}
      boxRef={boxRef}
      onChange={(value) => {
        chat.type(value)
        setKeys((count) => count + 1)
      }}
      onSend={() => send(chat.sendText)}
    />
  )
  const chips = (
    <div className={styles['chips']} role="group" aria-label={watched ? 'Suggestions' : 'Starting points'}>
      {suggestions.map((suggestion) => (
        <button
          key={suggestion.label}
          type="button"
          className={styles['chip']}
          aria-disabled={busy || undefined}
          onClick={() => {
            if (!busy) send(() => chat.send(suggestion.ask, suggestion.label, null))
          }}
        >
          {suggestion.label}
        </button>
      ))}
    </div>
  )

  if (!empty) {
    return (
      <>
        <ChatView
          home={home}
          now={now}
          page={page}
          box={box}
          chips={chips}
          onNewChat={() => {
            chat.newChat()
            if (wanted !== null) setParams({}, { replace: true })
            setTimeout(() => boxRef.current?.focus(), 0)
          }}
        />
        {toast}
      </>
    )
  }

  return (
    <div className={styles['hero']}>
      <PlannerBot state={hero} size={96} keys={keys} look={look} />
      <p className={styles['hi']}>{greeting}</p>
      <h1 tabIndex={-1}>{operator ? OPERATOR_HEADING : approverLine(home)}</h1>
      <div className={styles['dock']}>
        {box}
        {chips}
      </div>
      <NeedRows needs={needs.shown} now={now} more={<More needs={needs} full={!operator} />} />
      {operator ? null : <p className="muted">{APPROVER_NOTE}</p>}
      {toast}
    </div>
  )
}

/** What Needs you has past its rows on Home: a link to the rest on Workflows, or, where Home lists all the platform returned, how many are left. */
function More({ needs, full }: { needs: Needs; full: boolean }) {
  if (full) {
    const said = moreWords(needs.more)
    return said === null ? null : <p className={homeStyles['more']}>{said}</p>
  }
  return needs.total > needs.shown.length ? (
    <p className={homeStyles['more']}>
      <Link to="/workflows">{SEE_ALL_WORDS}</Link>
    </p>
  ) : null
}

/**
 * `quiet`: the page has its own main button, so Needs you has none. `full`: Home already lists all the platform returned, as it does for
 * someone who isn’t an Operator, so what is left is said, not linked to Workflows, which lists no more.
 */
function NeedsHere({ needs, now, arrival, quiet = false, connectAbove = false, full = false }: { needs: Needs; now: Date; arrival: ReturnType<typeof useArrival>; quiet?: boolean; connectAbove?: boolean; full?: boolean }) {
  return (
    <NeedsSection
      needs={needs}
      now={now}
      arrival={arrival}
      quiet={quiet}
      connectAbove={connectAbove}
      anchor={NEEDS_YOU_ANCHOR}
      more={<More needs={needs} full={full} />}
      whenNone={null}
    />
  )
}
