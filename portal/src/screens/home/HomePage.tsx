import { useEffect, useMemo, useReducer, useRef, useState, useSyncExternalStore } from 'react'
import { Link, useSearchParams } from 'react-router'
import { useHome } from '../../api/homeQueries'
import { isOperator } from '../../api/me'
import { useCapabilities, useDrafts, usePlannerAnswer } from '../../api/plannerQueries'
import { useMe, useModelSettings, useWatchlist } from '../../api/queries'
import type { HomeOut, PlannerAnswerIn } from '../../api/types'
import { PageHead } from '../../shell/PageHead'
import { Button, ButtonLink } from '../../ui/Button'
import { IconClock } from '../../ui/icons'
import { PlannerBot, type BotState } from '../../ui/PlannerBot'
import { restoreDraft } from './card'
import { NEEDS_YOU_ANCHOR, type Page } from './AnswerCards'
import { CapabilityLists } from './CapabilityLists'
import { approverLine, comingUpOf, HOME_NEEDS_SHOWN, moreWords, needsOf, needsTotal, SEE_ALL_WORDS, stateLine, suggestionsOf, type Needs, type Next } from './home'
import { NeedsSection, useArrival } from './NeedsSection'
import { PlannerBox } from './PlannerBox'
import { EMPTY, isThinking, previousOf, threadReducer } from './threadState'
import { Thread } from './Thread'
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

/** One heading for the whole visit, so the shell's focus stays on it. Home draws no heading while it loads, and the shell moves focus to the first one drawn. */
export function HomeBody({ heading, home, now }: { heading: string; home: HomeOut; now: Date }) {
  const operator = isOperator(useMe().data)
  return operator ? <OperatorHome heading={heading} home={home} now={now} /> : <ApproverHome heading={heading} home={home} now={now} />
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

function usePhone(): boolean {
  return useSyncExternalStore(
    (notify) => {
      if (typeof window.matchMedia !== 'function') return () => undefined
      const query = window.matchMedia(PHONE)
      query.addEventListener('change', notify)
      return () => query.removeEventListener('change', notify)
    },
    () => typeof window.matchMedia === 'function' && window.matchMedia(PHONE).matches,
    () => false,
  )
}

const SEND_FAILED = 'That didn’t send. Try again.'
const DRAFT_GONE = 'That draft is gone. Ask for it again below.'
const DAY_ONE_HEADING = 'Which software should we keep up to date?'
const DAY_ONE_LEAD = 'Ask about your watchlist, or tell me what software to watch.'
const OFFLINE_HEADING = 'I can’t read new requests until an AI model is connected'
const OFFLINE_LEAD =
  'Without an AI model, the Planner can’t answer questions. The Software watchlist keeps checking for new releases.'

/** Needs you on Home, without the “no AI model” row while the page already offers Connect a model. The count stays the platform’s. */
function needsHere(home: HomeOut, withoutModel: boolean): Needs {
  const shown = needsOf(withoutModel ? { ...home, connections: home.connections.filter((item) => item.id !== 'model') } : home, HOME_NEEDS_SHOWN)
  return { ...shown, total: needsTotal(home) }
}

function OperatorHome({ heading, home, now }: { heading: string; home: HomeOut; now: Date }) {
  const model = useModelSettings()
  const capabilities = useCapabilities()
  const answer = usePlannerAnswer()
  const [thread, dispatch] = useReducer(threadReducer, EMPTY)
  const [text, setText] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [keys, setKeys] = useState(0)
  const [lists, setLists] = useState(false)
  const boxRef = useRef<HTMLTextAreaElement>(null)
  const focusAnswer = useRef(false)
  const phone = usePhone()
  const [params, setParams] = useSearchParams()
  const wanted = params.get('draft')
  const drafts = useDrafts(wanted !== null)
  const reopened = useRef<string | null>(null)
  const offline = model.data !== undefined && model.data.active === null
  const dayOne = home.workflows === 0
  const empty = thread.messages.length === 0
  const busy = isThinking(thread)
  const needs = useMemo(() => needsHere(home, offline), [home, offline])
  const arrival = useArrival(needs.shown.map((need) => need.key))
  const watching = useWatchlist().data?.software.length
  const watched = watching !== undefined && watching > 0
  const suggestions = useMemo(() => suggestionsOf(watching, capabilities.data), [watching, capabilities.data])

  // Resume on Workflows lands here with the draft's id in the address, and the draft opens as the card it was.
  useEffect(() => {
    if (wanted === null || reopened.current === wanted || thread.messages.length > 0) return
    if (!drafts.data || (drafts.isStale && !drafts.isFetchedAfterMount)) return
    reopened.current = wanted
    const found = drafts.data.find((saved) => saved.draft_id === wanted)
    const { form, plan } = found ? restoreDraft(found) : { form: null, plan: null }
    if (form !== null && form.rows.length > 0) {
      dispatch({ type: 'resumed', start: { form, plan, draftId: wanted, similar: null, ...(found ? { resumed: found } : {}) } })
      return
    }
    setParams({}, { replace: true })
    setTimeout(() => {
      if (form === null) setProblem(DRAFT_GONE)
      else setText(form.text)
      boxRef.current?.focus()
    }, 0)
  }, [wanted, drafts.data, drafts.isStale, drafts.isFetchedAfterMount, thread.messages.length, setParams])

  // A chip leaves the page when pressed, so focus would fall to the page. It goes to the answer once that arrives.
  useEffect(() => {
    if (!focusAnswer.current || thread.messages.at(-1)?.kind !== 'reply') return
    focusAnswer.current = false
    document.querySelector<HTMLElement>('#thread-h + ol > li:last-child')?.focus({ preventScroll: true })
  }, [thread.messages])

  useEffect(() => {
    if (thread.messages.length > 0) document.querySelector('#thread-h + ol > li:last-child')?.scrollIntoView({ block: 'nearest' })
  }, [thread.messages.length])

  function send(ask: PlannerAnswerIn, shown: string, restore: string | null) {
    setProblem(null)
    dispatch({ type: 'sent', text: shown })
    setText('')
    answer.mutate(ask, {
      onSuccess: (reply) => dispatch({ type: 'answered', reply, typed: shown }),
      onError: () => {
        dispatch({ type: 'failed' })
        if (restore !== null) setText(restore)
        setProblem(SEND_FAILED)
      },
    })
  }

  const sendText = () => {
    const typed = text.trim()
    if (typed === '' || busy) return
    const previous = previousOf(thread)
    send(previous === null ? { text: typed } : { text: typed, previous }, typed, text)
  }
  const page: Page = {
    ask: (words) => {
      if (!busy) send({ text: words }, words, null)
    },
    edit: (words) => {
      setText(words)
      setTimeout(() => boxRef.current?.focus(), 0)
    },
  }

  const hero: BotState = offline ? 'sorry' : busy ? 'thinking' : text.trim() !== '' ? 'listening' : 'idle'
  const look = ((text.length % 24) - 12) / 12

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
        {needs.shown.length > 0 ? <NeedsHere needs={needs} now={now} arrival={arrival} quiet /> : null}
        {capabilities.data ? <CapabilityLists view={capabilities.data} /> : null}
      </div>
    )
  }

  return (
    <div className={styles['planner']}>
      <div className={`${styles['welcome']} ${empty ? '' : styles['compact']}`}>
        <PlannerBot state={hero} size={empty ? (phone ? 96 : 128) : 52} keys={keys} look={look} />
        <div>
          {empty ? (
            dayOne ? (
              <>
                <h1 tabIndex={-1}>{DAY_ONE_HEADING}</h1>
                <p className={styles['lead']}>{DAY_ONE_LEAD}</p>
              </>
            ) : (
              <>
                <h1 tabIndex={-1}>{heading}</h1>
                <p className={styles['lead']}>{stateLine(home, now)}</p>
              </>
            )
          ) : (
            <h1 tabIndex={-1}>Planner</h1>
          )}
        </div>
      </div>
      {empty ? null : <Thread thread={thread} now={now} page={page} />}
      <PlannerBox
        text={text}
        busy={busy}
        empty={empty}
        phone={phone}
        problem={problem}
        boxRef={boxRef}
        onChange={(value) => {
          setText(value)
          setKeys((count) => count + 1)
        }}
        onSend={sendText}
      />
      {empty ? (
        <div className={styles['chips']} role="group" aria-label={watched ? 'Suggestions' : 'Starting points'}>
          {suggestions.map((suggestion) => (
            <button
              key={suggestion.label}
              type="button"
              className={styles['chip']}
              aria-disabled={busy || undefined}
              onClick={() => {
                if (busy) return
                focusAnswer.current = true
                send(suggestion.ask, suggestion.label, null)
              }}
            >
              {suggestion.label}
            </button>
          ))}
        </div>
      ) : (
        <div className={styles['centred']}>
          <button
            type="button"
            className={styles['linkButton']}
            onClick={() => {
              dispatch({ type: 'new_chat' })
              setText('')
              setProblem(null)
              if (wanted !== null) setParams({}, { replace: true })
            }}
          >
            New chat
          </button>
        </div>
      )}
      {empty && needs.shown.length > 0 ? <NeedsHere needs={needs} now={now} arrival={arrival} /> : null}
      {empty && !dayOne && !suggestions.some((suggestion) => suggestion.ask.intent === 'abilities') ? (
        <div className={styles['centred']}>
          <button type="button" className={styles['linkButton']} aria-expanded={lists} onClick={() => setLists((open) => !open)}>
            {lists ? 'Hide what I can do' : 'What can I ask for?'}
          </button>
        </div>
      ) : null}
      {empty && (dayOne || lists) && capabilities.data ? <CapabilityLists view={capabilities.data} /> : null}
    </div>
  )
}

/** `quiet`: the page has its own main button, so Needs you has none. */
function NeedsHere({ needs, now, arrival, quiet = false }: { needs: Needs; now: Date; arrival: ReturnType<typeof useArrival>; quiet?: boolean }) {
  const left = needs.total - needs.shown.length
  return (
    <NeedsSection
      needs={needs}
      now={now}
      arrival={arrival}
      quiet={quiet}
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
