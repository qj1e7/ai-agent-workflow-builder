import { errorWords } from '../../api/errors'
import { useTemplates } from '../../api/queries'
import type { TemplateView } from '../../api/types'
import { Button, ButtonLink } from '../../ui/Button'
import { InlineMessage, Skeleton } from '../../ui/Feedback'
import { Spine } from '../../ui/Spine'
import { EXAMPLE_TASK } from '../builder/plan'
import { useFirstRun } from './useFirstRun'
import styles from './FirstRun.module.css'

const TITLE = 'Start the first run'
const NO_TEMPLATE = 'No ready-made task is available yet.'

export function FirstRun() {
  const templates = useTemplates()
  const template = templates.data?.[0]
  if (template) return <SetRoom template={template} />
  return (
    <>
      <h1>{TITLE}</h1>
      {templates.isPending ? (
        <Skeleton lines={4} label="Loading the example." />
      ) : (
        <div className={styles['fallback']}>
          <InlineMessage tone="error">{templates.isError ? errorWords(templates.error) : NO_TEMPLATE}</InlineMessage>
          <ButtonLink to="/builder">Describe your own task</ButtonLink>
        </div>
      )}
    </>
  )
}

function SetRoom({ template }: { template: TemplateView }) {
  const { state, start } = useFirstRun(template)
  const starting = state.is === 'starting'

  return (
    <section className={styles['hero']} aria-labelledby="first-run-title">
      <h1 id="first-run-title">{TITLE}</h1>
      <div className={styles['heroBody']}>
        <div className={styles['stageColumn']}>
          <Spine
            blocks={template.blocks.map((block) => ({ key: block.key, name: block.name, kind: block.kind, state: { kind: 'not_reached' } }))}
            orientation="vertical"
            compact
            showState={false}
            label={`The steps of ${template.name}`}
          />
        </div>
        <aside className={styles['rail']} aria-label="Start here">
          <p className={styles['promise']}>
            Describe a task in plain English. The agents do it while you watch every hand-off. Nothing is written to Jira or anywhere else
            until a person says yes.
          </p>
          <section className={styles['example']} aria-labelledby="first-run-example">
            <h2 id="first-run-example" className={styles['exampleTitle']}>
              Example: {template.name}
            </h2>
            <blockquote className={styles['exampleTask']}>
              <p>{EXAMPLE_TASK}</p>
            </blockquote>
          </section>
          <div className={styles['actions']}>
            <Button variant="primary" loading={starting} onClick={start}>
              {starting ? 'Starting the run' : 'Run the example'}
            </Button>
            <ButtonLink to="/builder">Describe your own task</ButtonLink>
          </div>
          {state.is === 'failed' ? <InlineMessage tone="error">{state.message}</InlineMessage> : null}
        </aside>
      </div>
    </section>
  )
}
