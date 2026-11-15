import type { UseQueryResult } from '@tanstack/react-query'
import { useErrorWords } from '../../api/context'
import type { Me, UseCaseN8nView, UseCaseView } from '../../api/types'
import { useOpenInN8n, useSweepOnOpen, useTakeBack } from '../../api/workflowQueries'
import { Button, ButtonAnchor, type ButtonVariant } from '../../ui/Button'
import { Canvas } from '../../ui/Canvas'
import { IconExternal, IconLock } from '../../ui/icons'
import { heldLine, holdOf, inUseLine, mayOpen, mayTakeBack, n8nRefusalWords, NOT_OWN, OPEN_IN_N8N, openEditorTab, SAFE_BLOCKS, TAKE_IT_BACK, takenBackWords, theirsNote, type Held, type Hold } from './n8nHold'
import styles from './Workflows.module.css'

interface OpenProps {
  readonly useCaseId: string
  readonly hold: Extract<Hold, { kind: 'free' | 'mine' }>
  readonly variant: ButtonVariant
}

/**
 * Open in n8n editor, in a new tab. While the person holds the workflow it is a plain link. Otherwise the press opens the tab, the
 * platform moves the workflow to the person's n8n space, and the tab then goes to it (ENGINE-PLAN 2.9).
 */
export function OpenInN8nEditor({ useCaseId, hold, variant }: OpenProps) {
  const open = useOpenInN8n()
  const words = useErrorWords()
  if (hold.kind === 'mine' && hold.editorUrl) {
    return (
      <ButtonAnchor href={hold.editorUrl} variant={variant}>
        {OPEN_IN_N8N}
      </ButtonAnchor>
    )
  }
  const press = () => {
    const tab = openEditorTab(window)
    open.mutate(useCaseId, {
      onSuccess: (held) => (held.editor_url ? tab?.go(held.editor_url) : tab?.close()),
      onError: () => tab?.close(),
    })
  }
  return (
    <>
      <Button variant={variant} loading={open.isPending} onClick={press}>
        {OPEN_IN_N8N}
        <IconExternal size={16} />
        <span className="visually-hidden"> (opens in a new tab)</span>
      </Button>
      {open.isError ? (
        <p className={styles['actionProblem']} role="alert">
          {n8nRefusalWords(open.error, words)}
        </p>
      ) : null}
    </>
  )
}

/** Take it back: the press, and why the platform refused it, if it did. The workflow is read again either way. */
export function useTakeBackPress(useCaseId: string, hold: Held | null, say: (text: string) => void) {
  const takeBack = useTakeBack()
  const words = useErrorWords()
  return {
    press: () => takeBack.mutate(useCaseId, { onSuccess: () => hold && say(takenBackWords(hold)) }),
    pending: takeBack.isPending,
    problem: takeBack.isError ? n8nRefusalWords(takeBack.error, words) : null,
  }
}

interface HeldProps {
  readonly useCaseId: string
  readonly hold: Held
  readonly now: Date
  readonly say: (text: string) => void
}

/** Who has the workflow open in n8n, and Take it back, which its holder and anyone else with n8n access may press. */
function HeldInN8n({ useCaseId, hold, now, say }: HeldProps) {
  const takeBack = useTakeBackPress(useCaseId, hold, say)
  return (
    <div className={styles['banner']} data-held>
      <span className={styles['bannerMark']}>
        <IconLock size={20} />
      </span>
      <p>{heldLine(hold, now)}</p>
      {mayTakeBack(hold) ? (
        <Button loading={takeBack.pending} onClick={takeBack.press}>
          {TAKE_IT_BACK}
        </Button>
      ) : (
        <span />
      )}
      {takeBack.problem ? (
        <p className={styles['problem']} role="alert">
          {takeBack.problem}
        </p>
      ) : hold.kind === 'theirs' ? (
        <p>{theirsNote(hold)}</p>
      ) : null}
    </div>
  )
}

interface PaneProps {
  readonly useCase: UseCaseView
  readonly inN8n: UseQueryResult<UseCaseN8nView>
  readonly me: Pick<Me, 'id'>
  readonly now: Date
  readonly say: (text: string) => void
}

/**
 * The workflow page's In n8n tab, as the sketch draws it: the version in use and who published it, the canvas, and Open in n8n
 * editor. It asks the platform to look in n8n as it opens, so a version just published there shows at once.
 */
export function WorkflowInN8n({ useCase, inN8n, me, now, say }: PaneProps) {
  useSweepOnOpen(useCase.use_case_id)
  const view = inN8n.data
  if (!view) {
    return inN8n.isError ? (
      <p>
        The workflow in n8n could not be loaded. <Button onClick={() => void inN8n.refetch()}>Try again</Button>
      </p>
    ) : (
      <p className="muted" role="status">
        Loading the workflow in n8n
      </p>
    )
  }
  const hold = holdOf(view, useCase, me)
  const blocks = useCase.blocks ?? []
  return (
    <div className={styles['inN8n']}>
      <div className={styles['cvMeta']}>
        <b>{inUseLine(view, useCase.state === 'draft', now)}</b>
        <span className={styles['small']}>{SAFE_BLOCKS}</span>
      </div>
      {hold.kind === 'mine' || hold.kind === 'theirs' ? <HeldInN8n useCaseId={useCase.use_case_id} hold={hold} now={now} say={say} /> : null}
      {blocks.length > 0 ? <Canvas blocks={blocks} name={useCase.name} /> : <p>{NOT_OWN}</p>}
      {mayOpen(hold) ? (
        <div className={styles['actions']}>
          <OpenInN8nEditor useCaseId={useCase.use_case_id} hold={hold} variant="primary" />
        </div>
      ) : hold.kind === 'shut' ? (
        <p className={styles['small']}>{hold.words}</p>
      ) : null}
    </div>
  )
}
