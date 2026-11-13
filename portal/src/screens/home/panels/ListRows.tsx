import { useId, type ReactNode } from 'react'
import type { UseCaseView, WatchedSoftwareView } from '../../../api/types'
import { OpenLink } from '../../../ui/OpenItem'
import { lifeWords, pillOf, SOFTWARE_PAGE, whenWords, workflowPath } from '../../workflows/workflow'
import { oursOf, newestOf, statusTone, statusWords } from '../../software/software'
import styles from './Lists.module.css'

type Tone = 'bad' | 'wait' | 'good' | 'open' | undefined

/** A workflow's one state, in the words its row on Workflows uses: what its newest run needs, else Paused or On. */
export function workflowState(useCase: Pick<UseCaseView, 'state' | 'last_run'>): { readonly words: string; readonly tone: Tone } {
  const run = useCase.state === 'on' && useCase.last_run ? pillOf(useCase.last_run) : null
  if (run?.pill) return { words: run.pill, tone: run.tone === 'bad' ? 'bad' : run.tone === 'wait' ? 'wait' : 'open' }
  return { words: lifeWords(useCase.state), tone: useCase.state === 'on' ? 'good' : undefined }
}

/** What the software list says under a name: the version you run and the newest when they differ, else what is known. */
export function softwareLine(row: WatchedSoftwareView): string {
  if (row.status === 'cant_check') return row.source.ref
  const ours = oursOf(row).version
  const newest = newestOf(row).version
  if (row.newest_version !== null && row.our_version !== null && row.our_version !== row.newest_version) return `${ours} → ${newest}`
  return row.our_version ?? newest
}

function Pill({ words, tone }: { words: string; tone: Tone }) {
  return (
    <span className={styles['pill']} data-tone={tone}>
      {words}
    </span>
  )
}

/** The row is one button. Its name is the workflow or software, and its line and state are read after it as its description. */
function Row({ item, to, name, line, state, data }: { item: Parameters<typeof OpenLink>[0]['item']; to: string; name: string; line: string; state: { words: string; tone: Tone }; data: Record<string, string> }) {
  const id = useId()
  return (
    <li {...data}>
      <OpenLink item={item} to={to} className={styles['row']} aria-labelledby={`${id}n`} aria-describedby={`${id}l ${id}s`}>
        <span>
          <b id={`${id}n`}>{name}</b>
          <span id={`${id}l`} className={styles['small']}>
            {line}
          </span>
        </span>
        <span id={`${id}s`}>
          <Pill words={state.words} tone={state.tone} />
        </span>
      </OpenLink>
    </li>
  )
}

/** The sketch's workflow rows: the name, when it runs, and its state. Each opens the workflow, beside the chat when the chat drew it. */
export function WorkflowRows({ useCases, label }: { useCases: readonly UseCaseView[]; label: string }): ReactNode {
  return (
    <ul className={styles['wl']} aria-label={label}>
      {useCases.map((useCase) => (
        <Row
          key={useCase.use_case_id}
          item={workflowPath(useCase) === SOFTWARE_PAGE ? { kind: 'watchlist' } : { kind: 'workflow', id: useCase.use_case_id }}
          to={workflowPath(useCase)}
          name={useCase.name}
          line={whenWords(useCase).words}
          state={workflowState(useCase)}
          data={{ 'data-workflow-id': useCase.use_case_id }}
        />
      ))}
    </ul>
  )
}

export const softwareTo = (row: Pick<WatchedSoftwareView, 'id'>): string => `${SOFTWARE_PAGE}?row=${encodeURIComponent(row.id)}`

/** The sketch's software rows: the name, its versions, and its state. Each opens the software, beside the chat when the chat drew it. */
export function SoftwareRows({ rows, label }: { rows: readonly WatchedSoftwareView[]; label: string }): ReactNode {
  return (
    <ul className={styles['wl']} aria-label={label}>
      {rows.map((row) => (
        <Row key={row.id} item={{ kind: 'software', id: row.id }} to={softwareTo(row)} name={row.name} line={softwareLine(row)} state={{ words: statusWords(row), tone: toneOf(row) }} data={{ 'data-software-id': row.id }} />
      ))}
    </ul>
  )
}

function toneOf(row: WatchedSoftwareView): Tone {
  const tone = statusTone[row.status]
  return tone === 'quiet' ? undefined : tone
}
