import { useEffect, useId, useRef, type ReactNode } from 'react'
import { Link } from 'react-router'
import { useFollowingPages, useHome } from '../../api/homeQueries'
import type { DraftItem, DraftView } from '../../api/types'
import { Button } from '../../ui/Button'
import { IconChevronRight, IconTrash } from '../../ui/icons'
import { ShowMore } from '../../ui/ShowMore'
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

/** The person's own requests to the team, the newest first, every one a page at a time. */
export function FollowingSection({ now, meId }: { now: Date; meId: string | undefined }) {
  const { items, total, ...pager } = useFollowingPages(useHome().data)
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
      <ShowMore shown={items.length} total={total} pager={pager} keys={items.map((item) => item.request_id)} rowAttr="data-request" />
    </Section>
  )
}
