import { useEffect, useMemo, useRef, useState } from 'react'
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
import { IconClock } from '../../ui/icons'
import { useMediaQuery } from '../../ui/media'
import { Toast } from '../../ui/Toast'
import { PlannerBot, type BotState } from '../../ui/PlannerBot'
import { restoreDraft } from './card'
import { NEEDS_YOU_ANCHOR, type Page } from './AnswerCards'
import { CapabilityLists } from './CapabilityLists'
import { approverLine, comingUpOf, HOME_NEEDS_SHOWN, moreWords, needsOf, needsTotal, SEE_ALL_WORDS, stateLine, suggestionsOf, type Needs, type Next } from './home'
import { NeedsSection, useArrival } from './NeedsSection'
import { ChatView, NEWEST } from './ChatView'
import { useChat } from './ChatProvider'
import { PlannerBox } from './PlannerBox'
import homeStyles from './Home.module.css'
import styles from './Planner.module.css'

interface HomePageProps {
  readonly heading: string
  readonly today: string
  readonly now: Date
}

export function HomePage({ heading, today, now }: HomePageProps) {
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
        <HomeBody heading={heading} home={loaded} now={now} />
      ) : home.isError ? (
        <>
          <PageHead heading={heading} lead={today} />
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
export function HomeBody({ heading, home, now }: { heading: string; home: HomeOut; now: Date }) {
  const operator = isOperator(useMe().data)
  const person = useCacheScope()
  return operator ? <OperatorHome key={person} heading={heading} home={home} now={now} /> : <ApproverHome heading={heading} home={home} now={now} />
}

function ComingNext({ next }: { next: Next }) {
  return (
    <div className={homeStyles['coming']}>
      <IconClock size={16} />
      <span>
        <b>Coming up next:</b> <Link to={next.to}>{next.name}</Link>, {next.when}
        {next.more > 0 ? `, and ${next.more} more` : ''}.
      </span>
      <Link to="/workflows">See all workflows</Link>
    </div>
  )
}

function AllQuiet({ next }: { next: Next | null }) {
  return (
    <div className={homeStyles['quiet']}>
      <b>All quiet</b>
      {next ? (
        <>
          Next up: <Link to={next.to}>{next.name}</Link>, {next.when}.
        </>
      ) : (
        'Nothing is scheduled yet.'
      )}
    </div>
  )
}

/** An Approver who is not an Operator: what waits for a yes, in full. No box, no suggestions, nothing to create. */
function ApproverHome({ heading, home, now }: { heading: string; home: HomeOut; now: Date }) {
  const needs = useMemo(() => needsOf(home), [home])
  const next = comingUpOf(home, now)
  const arrival = useArrival(needs.shown.map((need) => need.key))
  const total = needsTotal(home)
  return (
    <>
      <PageHead heading={heading} lead={approverLine(home)}>
        {total > 0 && next ? <ComingNext next={next} /> : null}
      </PageHead>
      <NeedsSection
        needs={needs}
        now={now}
        arrival={arrival}
        more={moreWords(needs.more) ? <p className={homeStyles['more']}>{moreWords(needs.more)}</p> : null}
        whenNone={<AllQuiet next={next} />}
      />
      <p className="muted">You’re an Approver, so you decide on requests. Operators set up workflows.</p>
    </>
  )
}

const PHONE = '(max-width: 600px)'

const DRAFT_GONE = 'That draft is gone. Ask for it again below.'
/** Answers that are a card to work on. Focus goes to the card's heading; any other answer hands it back to the box. */
const CARD_ANSWERS: ReadonlySet<PlannerReply['answer']> = new Set(['setup_card', 'part', 'watchlist', 'edit'])
const DAY_ONE_HEADING = 'Which software should we keep up to date?'
const DAY_ONE_LEAD = 'Ask about your watchlist, or tell me what software to watch.'
const OFFLINE_HEADING = 'I can’t read new requests until an AI model is connected'
const OFFLINE_LEAD =
  'Without an AI model, the Planner can’t answer questions. The Software watchlist keeps checking for new releases.'

/** Needs you on Home: the most urgent few of the grouped list. The count is the platform’s, and the model’s row stays, so every row counted is listed. */
function needsHere(home: HomeOut): Needs {
  return { ...needsOf(home, HOME_NEEDS_SHOWN), total: needsTotal(home) }
}

function OperatorHome({ heading, home, now }: { heading: string; home: HomeOut; now: Date }) {
  const model = useModelSettings()
  const capabilities = useCapabilities()
  const chat = useChat()
  const { thread, text, problem, busy } = chat
  const [keys, setKeys] = useState(0)
  const [lists, setLists] = useState(false)
  const boxRef = useRef<HTMLTextAreaElement>(null)
  const focusOn = useRef<number | null>(null)
  const phone = useMediaQuery(PHONE)
  const [params, setParams] = useSearchParams()
  const wanted = params.get('draft')
  const drafts = useDrafts(wanted !== null)
  const reopened = useRef<string | null>(null)
  /** The draft id the newest card wrote in the address, as opposed to one Resume brought here. */
  const written = useRef<string | null>(null)
  const offline = model.data !== undefined && model.data.active === null
  const dayOne = home.workflows === 0
  const empty = thread.messages.length === 0
  const needs = useMemo(() => needsHere(home), [home])
  const arrival = useArrival(needs.shown.map((need) => need.key))
  const watching = useWatchlist().data?.software.length
  const watched = watching !== undefined && watching > 0
  const suggestions = useMemo(() => suggestionsOf(watching, capabilities.data), [watching, capabilities.data])
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

  const box = (
    <PlannerBox
      text={text}
      busy={busy}
      empty={empty}
      phone={phone}
      problem={problem}
      boxRef={boxRef}
      onChange={(value) => {
        chat.type(value)
        setKeys((count) => count + 1)
      }}
      onSend={chat.sendText}
    />
  )

  if (!empty) {
    return (
      <>
        <ChatView
          home={home}
          now={now}
          page={page}
          box={box}
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
    <div className={styles['planner']}>
      <div className={styles['welcome']}>
        <PlannerBot state={hero} size={phone ? 96 : 128} keys={keys} look={look} />
        <div>
          {dayOne ? (
            <>
              <h1 tabIndex={-1}>{DAY_ONE_HEADING}</h1>
              <p className={styles['lead']}>{DAY_ONE_LEAD}</p>
            </>
          ) : (
            <>
              <h1 tabIndex={-1}>{heading}</h1>
              <p className={styles['lead']}>{stateLine(home, now)}</p>
            </>
          )}
        </div>
      </div>
      {box}
      <div className={styles['chips']} role="group" aria-label={watched ? 'Suggestions' : 'Starting points'}>
        {suggestions.map((suggestion) => (
          <button
            key={suggestion.label}
            type="button"
            className={styles['chip']}
            aria-disabled={busy || undefined}
            onClick={() => {
              if (!busy) chat.send(suggestion.ask, suggestion.label, null)
            }}
          >
            {suggestion.label}
          </button>
        ))}
      </div>
      {needs.shown.length > 0 ? <NeedsHere needs={needs} now={now} arrival={arrival} /> : null}
      {!dayOne && !suggestions.some((suggestion) => suggestion.ask.intent === 'abilities') ? (
        <div className={styles['centred']}>
          <button type="button" className={styles['linkButton']} aria-expanded={lists} onClick={() => setLists((open) => !open)}>
            {lists ? 'Hide what I can do' : 'What can I ask for?'}
          </button>
        </div>
      ) : null}
      {(dayOne || lists) && capabilities.data ? <CapabilityLists view={capabilities.data} /> : null}
      {toast}
    </div>
  )
}

/** `quiet`: the page has its own main button, so Needs you has none. */
function NeedsHere({ needs, now, arrival, quiet = false, connectAbove = false }: { needs: Needs; now: Date; arrival: ReturnType<typeof useArrival>; quiet?: boolean; connectAbove?: boolean }) {
  const left = needs.total - needs.shown.length
  return (
    <NeedsSection
      needs={needs}
      now={now}
      arrival={arrival}
      quiet={quiet}
      connectAbove={connectAbove}
      anchor={NEEDS_YOU_ANCHOR}
      more={
        left > 0 ? (
          <p className={homeStyles['more']}>
            <Link to="/workflows">{SEE_ALL_WORDS}</Link>
          </p>
        ) : null
      }
      whenNone={null}
    />
  )
}
