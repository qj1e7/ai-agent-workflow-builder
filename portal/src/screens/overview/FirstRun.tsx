import { useMemo, useRef } from 'react'
import { errorWords } from '../../api/errors'
import { useDisplayName } from '../../api/people'
import { useTemplates } from '../../api/queries'
import { useDevUser } from '../../api/session'
import type { TemplateView } from '../../api/types'
import { CaptionLine } from '../../room/Caption'
import { useWidth } from '../../room/hooks'
import { AGENTS } from '../../room/registry'
import { Room } from '../../room/Room'
import { RunHead } from '../../room/RunHead'
import { stageSet, userId as asUserId } from '../../run'
import { Button, ButtonLink } from '../../ui/Button'
import { InlineMessage, Skeleton } from '../../ui/Feedback'
import { IconShield } from '../../ui/icons'
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
  const user = useDevUser()
  const userName = useDisplayName()(user)
  const stage = useMemo(() => stageSet(template.blocks, AGENTS, { starter: { id: asUserId(user), display: userName } }), [template, user, userName])
  const { state, start } = useFirstRun(template)
  const roomRef = useRef<HTMLDivElement>(null)
  const width = useWidth(roomRef)
  const starting = state.is === 'starting'

  return (
    <section className={styles['hero']} aria-labelledby="first-run-title">
      <RunHead titleId="first-run-title" title={TITLE} lede="Nothing has run yet." state={undefined} />
      <div className={styles['heroBody']}>
        <div className={styles['stageColumn']}>
          <div ref={roomRef}>
            <Room view={stage.view} width={width} expectedWrites={stage.expectedWrites} label={`The room, set for ${template.name}`} outlines={stage.outlines} />
          </div>
          <CaptionLine leading={<IconShield size={18} />}>{stage.words}</CaptionLine>
        </div>
        <aside className={styles['rail']} aria-label="Start here">
          <p className={styles['promise']}>
            Describe a task in plain English. The agents do it in this room while you watch every hand-off. Nothing is written to Jira or
            anywhere else until a person says yes.
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
