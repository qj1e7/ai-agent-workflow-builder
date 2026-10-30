import { useId, type AnimationEvent, type CSSProperties } from 'react'
import { Link, useNavigate } from 'react-router'
import { useErrorWords } from '../../api/context'
import { useLatch } from '../../api/latch'
import { useRetry } from '../../api/queries'
import type { DraftItem, WaitingItem } from '../../api/types'
import { AgentFace } from '../../ui/AgentFace'
import { Button, ButtonLink } from '../../ui/Button'
import { cx } from '../../ui/cx'
import { IconAlert, IconChevronRight, IconShield } from '../../ui/icons'
import { actionsOf, draftWords, retryProblem, waitingWords, wordsOf, type Action, type Need, type Tone } from './home'
import styles from './Home.module.css'

const TONE_ICON: Record<Tone, typeof IconShield> = { wait: IconShield, tool: IconShield, bad: IconAlert }

export interface Motion {
  readonly arrive: boolean
  /** Its place in the first paint, for the stagger. */
  readonly index: number
  readonly leaving: boolean
  readonly onGone: () => void
}

function motionProps({ arrive, index, leaving, onGone }: Motion) {
  return {
    className: cx(leaving && styles['leaving'], !leaving && arrive && styles['arrive']),
    style: { '--i': index } as CSSProperties,
    'aria-hidden': leaving || undefined,
    inert: leaving || undefined,
    onAnimationEnd: (event: AnimationEvent) => {
      if (leaving && event.target === event.currentTarget) onGone()
    },
  }
}

function RetryButton({ runId, label, primary, describedBy }: { runId: string; label: string; primary: boolean; describedBy: string }) {
  const retry = useRetry(runId)
  const latch = useLatch()
  const navigate = useNavigate()
  const words = useErrorWords()
  /** The retry refreshes Home first, so this item may leave before the answer is in. The promise outlives it. */
  const press = () =>
    latch.run((settled) => {
      retry
        .mutateAsync()
        .then(
          () => navigate(`/runs/${runId}`),
          () => undefined,
        )
        .finally(settled)
    })
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

function ActionButton({ action, primary, describedBy }: { action: Action; primary: boolean; describedBy: string }) {
  if (action.kind === 'retry') return <RetryButton runId={action.runId} label={action.label} primary={primary} describedBy={describedBy} />
  return (
    <ButtonLink to={action.to} variant={primary ? 'primary' : 'secondary'} aria-describedby={describedBy}>
      {action.label}
    </ButtonLink>
  )
}

interface NeedProps {
  readonly need: Need
  /** The first item is the full card with the page's one main button; the rest are rows with their first button. */
  readonly card: boolean
  readonly now: Date
  readonly motion: Motion
}

export function NeedItem({ need, card, now, motion }: NeedProps) {
  const titleId = useId()
  const words = wordsOf(need, now)
  const actions = actionsOf(need)
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
        <h3 id={titleId} className={styles['cardTitle']}>
          {words.title}
        </h3>
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
            <ActionButton key={action.label} action={action} primary={index === 0} describedBy={titleId} />
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

export function DraftRow({ draft, now, arrive, index }: { draft: DraftItem; now: Date; arrive: boolean; index: number }) {
  const words = draftWords(draft, now)
  return (
    <li className={cx(styles['plainRow'], arrive && styles['arrive'])} style={{ '--i': index } as CSSProperties} data-draft={draft.draft_id}>
      <span className={styles['rowName']}>{words.name}</span>
      <span className={styles['rowSub']}>{words.sub}</span>
    </li>
  )
}
