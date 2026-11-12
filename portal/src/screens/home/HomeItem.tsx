import { useId, useState, type AnimationEvent, type CSSProperties } from 'react'
import { Link } from '../../ui/Link'
import { useChatNavigate } from '../../ui/fromChat'
import { useErrorWords } from '../../api/context'
import { useLatch } from '../../api/latch'
import { newIdempotencyKey } from '../../api/idempotency'
import { useModelOff, useRetry, useStartRun } from '../../api/queries'
import type { DraftItem, WaitingItem } from '../../api/types'
import { AgentFace } from '../../ui/AgentFace'
import { Button, ButtonLink } from '../../ui/Button'
import { cx } from '../../ui/cx'
import { IconAlert, IconChevronRight, IconInfo, IconShield, IconX, type Icon } from '../../ui/icons'
import { OpenButton } from '../../ui/OpenItem'
import { useAfterPanelAction, useShownInPanel } from '../../ui/sidePanel'
import { draftPath } from './card'
import { actionsOf, CONNECT_ABOVE, draftWords, isModelNeed, NO_MODEL_TITLE, retryProblem, waitingWords, wordsOf, type Action, type Need, type Tone } from './home'
import styles from './Home.module.css'

export const TONE_ICON: Record<Tone, Icon> = { wait: IconShield, tool: IconShield, bad: IconAlert, info: IconInfo, off: IconX }

export interface Motion {
  readonly glide: string
  readonly arrive: boolean
  readonly stagger: number
  readonly leaving: boolean
  readonly onAnimationEnd: ((event: AnimationEvent) => void) | undefined
}

function motionProps({ glide, arrive, stagger, leaving, onAnimationEnd }: Motion) {
  return {
    className: cx(leaving && styles['leaving'], !leaving && arrive && styles['arrive']),
    style: { '--i': stagger } as CSSProperties,
    'data-glide': glide,
    'aria-hidden': leaving || undefined,
    inert: leaving || undefined,
    onAnimationEnd,
  }
}

/**
 * Retries a stopped run and opens it, so the person sees it go. In the side panel the run stays where it is, with the panel back
 * at its top. While the panel shows the run, the chat hides its own Retry, because the panel has it.
 */
export function RetryButton({ runId, label, primary, describedBy }: { runId: string; label: string; primary: boolean; describedBy: string }) {
  const navigate = useChatNavigate()
  const backToTop = useAfterPanelAction()
  const retry = useRetry(runId, () => (backToTop ? backToTop() : navigate(`/runs/${runId}`)))
  const latch = useLatch()
  const words = useErrorWords()
  const inPanel = useShownInPanel({ kind: 'run', id: runId })
  const press = () => latch.run((settled) => retry.mutate(undefined, { onSettled: settled }))
  if (inPanel) return null
  return (
    <>
      <Button variant={primary ? 'primary' : 'secondary'} loading={retry.isPending} onClick={press} aria-describedby={describedBy}>
        {label}
      </Button>
      {retry.isError ? (
        <p className={styles['problem']} role="alert">
          {retryProblem(retry.error, words)}
        </p>
      ) : null}
    </>
  )
}

/** Starts a new test run of the workflow, as Do a test run does, and opens it so the person sees it go. */
function TestAgainButton({ useCaseId, label, primary, describedBy }: { useCaseId: string; label: string; primary: boolean; describedBy: string }) {
  const navigate = useChatNavigate()
  const start = useStartRun()
  const latch = useLatch()
  const words = useErrorWords()
  const [key] = useState(newIdempotencyKey)
  const press = () =>
    latch.run((settled) =>
      start.mutate({ useCaseId, idempotencyKey: key, test: true }, { onSuccess: (started) => navigate(`/runs/${started.run_id}`), onSettled: settled }),
    )
  return (
    <>
      <Button variant={primary ? 'primary' : 'secondary'} loading={start.isPending} onClick={press} aria-describedby={describedBy}>
        {label}
      </Button>
      {start.isError ? (
        <p className={styles['problem']} role="alert">
          {`Could not start the test run. ${words(start.error)}`}
        </p>
      ) : null}
    </>
  )
}

function ActionButton({ action, primary, describedBy }: { action: Action; primary: boolean; describedBy: string }) {
  if (action.kind === 'retry') return <RetryButton runId={action.runId} label={action.label} primary={primary} describedBy={describedBy} />
  if (action.kind === 'test') return <TestAgainButton useCaseId={action.useCaseId} label={action.label} primary={primary} describedBy={describedBy} />
  if (action.item) {
    return (
      <OpenButton item={action.item} to={action.to} variant={primary ? 'primary' : 'secondary'} aria-describedby={describedBy}>
        {action.label}
      </OpenButton>
    )
  }
  return (
    <ButtonLink to={action.to} variant={primary ? 'primary' : 'secondary'} aria-describedby={describedBy}>
      {action.label}
    </ButtonLink>
  )
}

interface NeedProps {
  readonly need: Need
  readonly card: boolean
  /** Its action is not the page's main button. */
  readonly quiet?: boolean
  /** Connect a model is already on the page, above the list. */
  readonly connectAbove?: boolean
  readonly now: Date
  readonly motion: Motion
}

export function NeedItem({ need, card, quiet = false, connectAbove = false, now, motion }: NeedProps) {
  const titleId = useId()
  const modelOff = useModelOff()
  const pointsUp = connectAbove && modelOff && isModelNeed(need)
  const words = pointsUp ? { ...wordsOf(need, now, modelOff), title: NO_MODEL_TITLE, meta: CONNECT_ABOVE, note: null } : wordsOf(need, now, modelOff)
  const actions = pointsUp ? [] : actionsOf(need, modelOff)
  const Icon = TONE_ICON[words.tone]
  const { className, ...moving } = motionProps(motion)
  const icon = (
    <span className={cx(styles['icon'], styles[words.tone])}>
      <Icon size={20} />
    </span>
  )
  if (!card) {
    const [first] = actions
    return (
      <li className={cx(styles['row'], className)} data-home-item={need.key} data-kind={need.kind} {...moving}>
        {icon}
        <div className={styles['rowText']}>
          <b id={titleId}>{words.title}</b>
          <span className={styles['rowMeta']}>{words.meta}</span>
          {(need.kind === 'stopped' || need.kind === 'declined' || need.kind === 'question') && words.note ? <span className={styles['rowMeta']}>{words.note}</span> : null}
          {words.why ? (
            <span className={styles['rowWhy']}>
              <b>AI troubleshooter:</b> {words.why}
            </span>
          ) : null}
        </div>
        {first ? <ActionButton action={first} primary={false} describedBy={titleId} /> : null}
      </li>
    )
  }
  return (
    <li className={cx(styles['card'], className)} data-home-item={need.key} data-kind={need.kind} {...moving}>
      {icon}
      <div className={styles['cardBody']}>
        <h4 id={titleId} className={styles['cardTitle']}>
          {words.title}
        </h4>
        <p className={styles['cardMeta']}>{words.meta}</p>
        {words.lines.length > 0 ? (
          <ul className={styles['lines']} aria-label="What it would change">
            {words.lines.map((line, index) => (
              <li key={`${index}-${line}`}>{line}</li>
            ))}
          </ul>
        ) : null}
        {words.note ? <p className={styles['note']}>{words.note}</p> : null}
        {words.why ? (
          <div className={styles['says']}>
            <AgentFace id="troubleshooter" size={32} />
            <p>
              <b>AI troubleshooter</b>
              {words.why}
            </p>
          </div>
        ) : null}
        <div className={styles['buttons']}>
          {actions.map((action, index) => (
            <ActionButton key={action.label} action={action} primary={index === 0 && !quiet} describedBy={titleId} />
          ))}
        </div>
      </div>
    </li>
  )
}

export function WaitingRow({ item, now, motion }: { item: WaitingItem; now: Date; motion: Motion }) {
  const words = waitingWords(item, now)
  const { className, ...moving } = motionProps(motion)
  return (
    <li className={className} data-waiting={item.run_id} {...moving}>
      <Link to={words.to} className={styles['rowLink']}>
        <span>
          <span className={styles['rowName']}>{words.name}</span>
          <span className={styles['rowSub']}>{words.sub}</span>
        </span>
        <IconChevronRight size={16} />
      </Link>
    </li>
  )
}

export function DraftRow({ draft, now, arrive, stagger }: { draft: DraftItem; now: Date; arrive: boolean; stagger: number }) {
  const words = draftWords(draft, now)
  return (
    <li className={arrive ? styles['arrive'] : undefined} style={{ '--i': stagger } as CSSProperties} data-draft={draft.draft_id}>
      <Link to={draftPath(draft.draft_id)} className={styles['rowLink']}>
        <span>
          <span className={styles['rowName']}>{words.name}</span>
          <span className={styles['rowSub']}>{words.sub}</span>
        </span>
        <IconChevronRight size={16} />
      </Link>
    </li>
  )
}
