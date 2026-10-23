import { useMemo } from 'react'
import { useErrorWords } from '../../api/context'
import { useTemplates } from '../../api/queries'
import type { TemplateView } from '../../api/types'
import { planTrack } from '../../run'
import { TrackLine } from '../../tracker/TrackLine'
import { Button, ButtonLink } from '../../ui/Button'
import { InlineMessage, Skeleton } from '../../ui/Feedback'
import { useFirstRun } from './useFirstRun'
import styles from './FirstRun.module.css'

const TITLE = 'Start the first run'
const PROMISE = 'Describe a task in plain English. Agents do the work, and nothing is written until a person says yes.'
const NO_TEMPLATE = 'No ready-made task is available yet.'

export function FirstRun() {
  const explain = useErrorWords()
  const templates = useTemplates()
  const template = templates.data?.[0]
  if (template) return <Ready template={template} />
  return (
    <section className={styles['first']} aria-labelledby="first-run-title">
      <h1 id="first-run-title" className={styles['title']}>
        {TITLE}
      </h1>
      {templates.isPending ? (
        <Skeleton lines={4} label="Loading the example." />
      ) : (
        <div className={styles['fallback']}>
          <InlineMessage tone="error">{templates.isError ? explain(templates.error) : NO_TEMPLATE}</InlineMessage>
          <ButtonLink to="/builder">Describe your own task</ButtonLink>
        </div>
      )}
    </section>
  )
}

/** Live mode with no runs yet: the example's line with nothing done, one promise, and one way to start. */
function Ready({ template }: { template: TemplateView }) {
  const { state, start } = useFirstRun(template)
  const starting = state.is === 'starting'
  const track = useMemo(() => planTrack(template.blocks), [template.blocks])
  return (
    <section className={styles['first']} aria-labelledby="first-run-title">
      <h1 id="first-run-title" className={styles['title']}>
        {TITLE}
      </h1>
      <p className={styles['promise']}>{PROMISE}</p>
      <div className={styles['actions']}>
        <Button variant="primary" loading={starting} onClick={start}>
          {starting ? 'Starting the run' : 'Run the example'}
        </Button>
        <ButtonLink to="/builder">Describe your own task</ButtonLink>
      </div>
      {state.is === 'failed' ? <InlineMessage tone="error">{state.message}</InlineMessage> : null}
      <TrackLine track={track} still label={`Steps in ${template.name}`} />
    </section>
  )
}
