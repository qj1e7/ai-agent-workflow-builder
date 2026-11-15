import { Canvas } from '../../ui/Canvas'
import { IconCheck, IconX } from '../../ui/icons'
import { useSetUp } from '../../api/workflowQueries'
import { canvasOf, checksOf, shownOf, statusOf, testStatus } from './build'
import { DraftPill, TestRun, useBuilt } from './Building'
import runStyles from '../run/RunPage.module.css'
import styles from './SetupCard.module.css'

/** The capability registry has no entry for n8n's node allow list yet, so the footnote keeps only what holds without it (plan E3). */
const FOOTNOTE = 'The builder saves a draft. It can’t publish by itself.'

/**
 * Building in n8n, beside the chat: the workflow's blocks as n8n holds them, appearing as the build log says, then lit by the test
 * run's own events. The status line and the checks are the log's and the run's words, and On waits for the platform.
 */
export function BuildPanel({ id }: { id: string }) {
  const setUp = useSetUp(id)
  return <TestRun runId={setUp?.testRunId ?? null}>{(test) => <BuildView id={id} test={test} />}</TestRun>
}

function BuildView({ id, test }: { id: string; test: Parameters<typeof useBuilt>[1] }) {
  const { setUp, useCase, replay, stage } = useBuilt(id, test)
  if (!setUp) return <p className="muted">This set-up was made in an earlier visit. Open the workflow from Workflows to see it.</p>
  const { created } = setUp
  const inN8n = (created.n8n_workflow_id ?? null) !== null
  const log = created.build_log ?? []
  const blocks = created.blocks ?? []
  const shown = shownOf(log, replay.lines, replay.done)
  const on = stage.kind === 'on'
  const canvas = canvasOf(blocks, log, shown, test, on)
  const told = test ? test.chat.flatMap((item) => (item.kind === 'told' ? [item.line] : [])) : []
  const checks = checksOf(replay.lines, test ? testStatus(test) : null, told)
  return (
    <div className={runStyles['panelView']}>
      <div className={runStyles['head']}>
        <p className={runStyles['kind']}>{inN8n ? 'Building in n8n' : 'Building'}</p>
        <DraftPill label={on ? 'On' : 'Draft'} tone={on ? 'new' : 'quiet'} />
      </div>
      <p className="muted" role="status">
        {statusOf(stage, replay.lines, { inN8n, version: useCase?.version ?? created.version })}
      </p>
      {blocks.length > 0 ? <Canvas blocks={blocks} name={useCase?.name ?? 'The workflow'} nodes={canvas.nodes} edges={canvas.edges} /> : null}
      {checks.length > 0 ? (
        <ul className={styles['checks']} aria-label="Checks">
          {checks.map((check) => (
            <li key={check.text} data-ok={check.ok || undefined}>
              {check.ok ? <IconCheck size={15} /> : <IconX size={15} />}
              {check.text}
            </li>
          ))}
        </ul>
      ) : null}
      <p className={styles['footnote']}>{FOOTNOTE}</p>
    </div>
  )
}
