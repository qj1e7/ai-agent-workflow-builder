import { useEffect, useId, useRef, type ReactNode } from 'react'
import { Link } from 'react-router'
import type { DraftItem, DraftView, FollowingUpItem, WaitingItem } from '../../api/types'
import { Button, ButtonLink } from '../../ui/Button'
import { IconChevronRight, IconTrash } from '../../ui/icons'
import { savedLeft } from '../home/card'
import { draftWords, waitingWords } from '../home/home'
import { draftPath } from '../new/starters'
import homeStyles from '../home/Home.module.css'
import { followingWords, oneLine, requestPath } from './requests'
import styles from './Workflows.module.css'

const NAME_SHOWN = 80

export function draftItem(draft: DraftView): DraftItem {
  const saved = draft.content['name']
  const name = typeof saved === 'string' && saved.trim() !== '' ? oneLine(saved, NAME_SHOWN) : null
  return { draft_id: draft.draft_id, name, step: draft.step, saved_at: draft.saved_at }
}

function Section({ id, title, count, children }: { id: string; title: string; count?: number; children: ReactNode }) {
  const headingId = useId()
  return (
    <section className={homeStyles['section']} aria-labelledby={headingId} data-section={id}>
      <h2 id={headingId}>
        {title}
        {count === undefined ? null : <span className={homeStyles['count']}>{count}</span>}
      </h2>
      {children}
    </section>
  )
}

interface DraftsProps {
  readonly drafts: readonly DraftView[]
  readonly now: Date
  readonly onDiscard: (draft: DraftView) => void
}

export function DraftsSection({ drafts, now, onDiscard }: DraftsProps) {
  if (drafts.length === 0) return null
  return (
    <Section id="drafts" title="Drafts" count={drafts.length}>
      <ul className={homeStyles['rows']}>
        {drafts.map((draft) => {
          const words = draftWords(draftItem(draft), now, savedLeft(draft))
          return (
            <li key={draft.draft_id} className={styles['draftRow']} data-draft={draft.draft_id}>
              <span className={styles['draftText']}>
                <span className={homeStyles['rowName']}>{words.name}</span>
                <span className={homeStyles['rowSub']}>{words.sub}</span>
              </span>
              <span className={styles['btns']}>
                <ButtonLink to={draftPath(draft.draft_id)}>
                  Resume<span className="visually-hidden"> {words.name}</span>
                </ButtonLink>
                <Button onClick={() => onDiscard(draft)}>
                  Discard<span className="visually-hidden"> {words.name}</span>
                </Button>
              </span>
            </li>
          )
        })}
      </ul>
    </Section>
  )
}

interface DiscardDialogProps {
  readonly name: string
  readonly busy: boolean
  readonly problem: string | null
  readonly onClose: () => void
  readonly onConfirm: () => void
}

export function DiscardDialog({ name, busy, problem, onClose, onConfirm }: DiscardDialogProps) {
  const dialog = useRef<HTMLDialogElement>(null)
  const cancel = useRef<HTMLButtonElement>(null)
  const titleId = useId()
  const textId = useId()
  useEffect(() => {
    const element = dialog.current
    if (element && !element.open) element.showModal()
    cancel.current?.focus()
  }, [])
  return (
    <dialog ref={dialog} className={styles['dialog']} role="alertdialog" aria-labelledby={titleId} aria-describedby={textId} onClose={onClose}>
      <h2 id={titleId}>Discard {name}?</h2>
      <p id={textId}>The draft and everything you wrote in it are removed. Nothing has run, and nothing changes in Jira or Teams. You can put it back right after.</p>
      {problem ? (
        <p className={styles['problem']} role="alert">
          {problem}
        </p>
      ) : null}
      <div className={styles['btns']}>
        <Button ref={cancel} onClick={() => dialog.current?.close()}>
          Keep the draft
        </Button>
        <Button variant="danger-outline" icon={IconTrash} loading={busy} onClick={onConfirm}>
          Discard draft
        </Button>
      </div>
    </dialog>
  )
}

export function WaitingSection({ items, total, now }: { items: readonly WaitingItem[]; total: number; now: Date }) {
  if (items.length === 0) return null
  return (
    <Section id="waiting" title="Waiting on others">
      <ul className={homeStyles['rows']}>
        {items.map((item) => {
          const words = waitingWords(item, now)
          return (
            <li key={item.run_id} data-waiting={item.run_id}>
              <Link to={words.to} className={homeStyles['rowLink']}>
                <span>
                  <span className={homeStyles['rowName']}>{words.name}</span>
                  <span className={homeStyles['rowSub']}>{words.sub}</span>
                </span>
                <IconChevronRight size={16} />
              </Link>
            </li>
          )
        })}
      </ul>
      {total > items.length ? <p className={homeStyles['more']}>Showing the newest {items.length} of {total}.</p> : null}
    </Section>
  )
}

export function FollowingSection({ items, total, now, meId }: { items: readonly FollowingUpItem[]; total: number; now: Date; meId: string | undefined }) {
  if (items.length === 0) return null
  return (
    <Section id="following" title="Following up">
      <ul className={homeStyles['rows']}>
        {items.map((item) => {
          const words = followingWords(item, now, meId)
          return (
            <li key={item.request_id} data-request={item.request_id}>
              <Link to={requestPath(item.request_id)} className={homeStyles['rowLink']}>
                <span>
                  <span className={homeStyles['rowName']}>{words.name}</span>
                  <span className={homeStyles['rowSub']}>{words.sub}</span>
                </span>
                <IconChevronRight size={16} />
              </Link>
            </li>
          )
        })}
      </ul>
      {total > items.length ? <p className={homeStyles['more']}>Showing the newest {items.length} of {total}.</p> : null}
    </Section>
  )
}
