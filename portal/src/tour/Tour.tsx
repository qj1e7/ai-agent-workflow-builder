import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation } from 'react-router'
import { useSession } from '../api/context'
import { useMe } from '../api/queries'
import { useReducedMotion } from '../tracker/hooks'
import { Button, ButtonLink } from '../ui/Button'
import { cx } from '../ui/cx'
import { IconCheck, IconChevronDown, IconChevronUp, IconDash, IconDot, IconFlag, IconRing, IconX } from '../ui/icons'
import { QUESTS, type Quest, type TourStep, type Where } from './quests'
import { pathMatches, placeOf, shownStep, type Place, type TourAction, type TourState, type Who } from './tourState'
import { useTour } from './TourContext'
import { useStepMet, useStop, type Box, type Side } from './watch'
import styles from './Tour.module.css'

/** How long a done step shows its tick before the next one comes. */
const TICK_MS = 700
const GLOW_PAD = 6

export const TOUR_TITLE_ID = 'tour-title'

export function Tour() {
  const { state, act } = useTour()
  return state.open ? <OpenTour state={state} act={act} /> : null
}

function OpenTour({ state, act }: { state: TourState; act: (action: TourAction) => void }) {
  const { pathname } = useLocation()
  const session = useSession()
  const me = useMe().data
  const reduced = useReducedMotion()
  const place = placeOf(state)
  const canSwitchUser = session.kind === 'dev'
  const raw = place.is === 'step' ? place.step : null
  const step = useMemo(() => (raw ? shownStep(raw, canSwitchUser) : null), [raw, canSwitchUser])
  const who = useMemo<Who | null>(() => (me ? { id: me.id, roles: me.roles } : null), [me])

  // The newest met step wins, so a step skipped while it ticks never holds up the next one.
  const [ticking, setTicking] = useState<string | null>(null)
  const met = useCallback((id: string) => setTicking(id), [])
  useEffect(() => {
    if (ticking === null) return
    const timer = window.setTimeout(() => {
      act({ type: 'done', id: ticking })
      setTicking(null)
    }, TICK_MS)
    return () => window.clearTimeout(timer)
  }, [ticking, act])
  useStepMet(step, pathname, who, met)

  const { box, side } = useStop(step?.glow, step?.keepClear, reduced)
  // On a phone the open card covers the bottom of the page, so the page gets room to scroll past it.
  useEffect(() => {
    if (state.folded) return
    document.documentElement.dataset['tourOpen'] = ''
    return () => {
      delete document.documentElement.dataset['tourOpen']
    }
  }, [state.folded])
  const away = step?.where && !pathMatches(step.where.at, pathname) ? step.where : null

  return (
    <>
      {box && !state.folded ? <Glow box={box} /> : null}
      {state.folded ? (
        <Folded place={place} state={state} act={act} side={side} />
      ) : (
        <Card
          place={place}
          step={step}
          state={state}
          act={act}
          ticking={step !== null && ticking === step.id}
          away={away}
          lost={step?.lost !== undefined && away === null && box === null ? step.lost : null}
          side={side}
        />
      )}
    </>
  )
}

function Glow({ box }: { box: Box }) {
  return (
    <div
      className={styles['glow']}
      data-tour-glow
      style={{ top: box.top - GLOW_PAD, left: box.left - GLOW_PAD, width: box.width + GLOW_PAD * 2, height: box.height + GLOW_PAD * 2 }}
      aria-hidden="true"
    />
  )
}

function questWords(state: TourState): string {
  return `Quest ${Math.min(state.quest + 1, QUESTS.length)} of ${QUESTS.length}`
}

function Folded({ place, state, act, side }: { place: Place; state: TourState; act: (action: TourAction) => void; side: Side }) {
  const words =
    place.is === 'step'
      ? `${place.quest.title}, step ${state.step + 1} of ${place.quest.steps.length}`
      : place.is === 'quest_done'
        ? `${place.quest.title} is done`
        : 'Tour complete'
  return (
    <button type="button" className={cx(styles['folded'], side === 'left' && styles['left'])} onClick={() => act({ type: 'fold', folded: false })}>
      <IconFlag size={18} />
      <span>
        <span className="visually-hidden">Show the tour: </span>
        {words}
      </span>
      <IconChevronUp size={18} />
    </button>
  )
}

interface CardProps {
  place: Place
  step: TourStep | null
  state: TourState
  act: (action: TourAction) => void
  ticking: boolean
  away: Where | null
  lost: string | null
  side: Side
}

function Card({ place, step, state, act, ticking, away, lost, side }: CardProps) {
  const card = useRef<HTMLElement>(null)
  // Escape inside the card folds it out of the way, as the fold button does for a pointer.
  useEffect(() => {
    const element = card.current
    if (!element) return
    const foldOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') act({ type: 'fold', folded: true })
    }
    element.addEventListener('keydown', foldOnEscape)
    return () => element.removeEventListener('keydown', foldOnEscape)
  }, [act])
  return (
    <section ref={card} className={cx(styles['card'], side === 'left' && styles['left'])} aria-labelledby={TOUR_TITLE_ID} data-tour-card>
      <div className={styles['top']}>
        <p className={styles['kicker']}>
          <IconFlag size={16} />
          Tour · {questWords(state)}
        </p>
        <div className={styles['corner']}>
          <button type="button" className={styles['icon']} aria-label="Fold the tour" title="Fold" onClick={() => act({ type: 'fold', folded: true })}>
            <IconChevronDown size={18} />
          </button>
          <button type="button" className={styles['icon']} aria-label="Close the tour" title="Close" onClick={() => act({ type: 'close' })}>
            <IconX size={18} />
          </button>
        </div>
      </div>
      {place.is === 'step' && step ? (
        <StepView quest={place.quest} step={step} state={state} act={act} ticking={ticking} away={away} lost={lost} />
      ) : place.is === 'quest_done' ? (
        <QuestDone quest={place.quest} state={state} act={act} />
      ) : (
        <TourDone act={act} />
      )}
    </section>
  )
}

interface StepViewProps {
  quest: Quest
  step: TourStep
  state: TourState
  act: (action: TourAction) => void
  ticking: boolean
  away: Where | null
  lost: string | null
}

function StepView({ quest, step, state, act, ticking, away, lost }: StepViewProps) {
  const first = state.quest === 0 && state.step === 0
  const toRead = step.done.kind === 'read'
  return (
    <>
      <h2 id={TOUR_TITLE_ID} className={styles['title']} tabIndex={-1}>
        {quest.title}
      </h2>
      <div className={styles['now']} aria-live="polite">
        {ticking ? (
          <p className={styles['ticked']}>
            <IconCheck size={18} strokeWidth={2.4} />
            Done.
          </p>
        ) : (
          <>
            <p className={styles['say']}>{step.say}</p>
            {step.why ? <p className={styles['why']}>{step.why}</p> : null}
            {away ? (
              <div className={styles['away']}>
                <p>This step is on {away.page}.</p>
                <ButtonLink to={away.to ?? away.at}>{away.go ?? 'Go there'}</ButtonLink>
              </div>
            ) : null}
            {lost ? <p className={cx(styles['away'], styles['lost'])}>{lost}</p> : null}
          </>
        )}
      </div>
      <ol className={styles['list']} aria-label={`Steps in ${quest.title}`}>
        {quest.steps.map((each, at) => {
          const now = at === state.step
          // The step on show is never ticked from an earlier pass, so going Back reads as doing it again.
          const did = now ? ticking : state.ticked.includes(each.id)
          const Mark = did ? IconCheck : now ? IconDot : at < state.step ? IconDash : IconRing
          return (
            <li key={each.id} className={cx(styles['item'], now && styles['current'], did && styles['did'])} aria-current={now ? 'step' : undefined}>
              <Mark size={16} strokeWidth={did ? 2.4 : 2} />
              <span>
                {each.label}
                {did ? <span className="visually-hidden"> (done)</span> : at < state.step ? <span className="visually-hidden"> (skipped)</span> : null}
              </span>
            </li>
          )
        })}
      </ol>
      <div className={styles['foot']}>
        <span className={styles['count']}>
          Step {state.step + 1} of {quest.steps.length}
        </span>
        <div className={styles['buttons']}>
          <Button disabled={first} onClick={() => act({ type: 'back' })}>
            Back
          </Button>
          {toRead ? (
            <Button variant="primary" onClick={() => act({ type: 'done', id: step.id })}>
              Next
            </Button>
          ) : (
            <Button onClick={() => act({ type: 'skip' })}>Skip</Button>
          )}
        </div>
      </div>
    </>
  )
}

function QuestDone({ quest, state, act }: { quest: Quest; state: TourState; act: (action: TourAction) => void }) {
  const next = QUESTS[state.quest + 1]
  return (
    <>
      <h2 id={TOUR_TITLE_ID} className={styles['title']} tabIndex={-1}>
        <span className={styles['badge']} aria-hidden="true">
          <IconCheck size={18} strokeWidth={2.6} />
        </span>
        Quest complete
      </h2>
      <p className={styles['say']} aria-live="polite">
        {quest.title}: done.
      </p>
      {next ? <p className={styles['why']}>Next: {next.title}.</p> : <p className={styles['why']}>That was the last quest.</p>}
      <div className={styles['foot']}>
        <span />
        <div className={styles['buttons']}>
          <Button onClick={() => act({ type: 'back' })}>Back</Button>
          <Button variant="primary" onClick={() => act({ type: 'next_quest' })}>
            {next ? 'Next quest' : 'Finish'}
          </Button>
        </div>
      </div>
    </>
  )
}

function TourDone({ act }: { act: (action: TourAction) => void }) {
  return (
    <>
      <h2 id={TOUR_TITLE_ID} className={styles['title']} tabIndex={-1}>
        <span className={styles['badge']} aria-hidden="true">
          <IconCheck size={18} strokeWidth={2.6} />
        </span>
        Tour complete
      </h2>
      <p className={styles['say']} aria-live="polite">
        You have tried every part of the Portal.
      </p>
      <p className={styles['why']}>Press the flag at the top any time to go through it again.</p>
      <div className={styles['foot']}>
        <span />
        <div className={styles['buttons']}>
          <Button onClick={() => act({ type: 'restart' })}>Start again</Button>
          <Button variant="primary" onClick={() => act({ type: 'close' })}>
            Close
          </Button>
        </div>
      </div>
    </>
  )
}

/** The flag in the header. It opens the tour where the person left off, or unfolds it. */
export function TourButton() {
  const { act } = useTour()
  function open() {
    act({ type: 'open' })
    requestAnimationFrame(() => document.getElementById(TOUR_TITLE_ID)?.focus())
  }
  return (
    <button type="button" className={styles['flag']} aria-label="Tour" title="Tour: learn the Portal step by step" onClick={open}>
      <IconFlag size={20} strokeWidth={2} />
    </button>
  )
}
