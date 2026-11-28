import type { CSSProperties } from 'react'
import { AgentFace } from '../../ui/AgentFace'
import { cx } from '../../ui/cx'
import { IconCheck, IconGate, IconX } from '../../ui/icons'
import { STEP_ICON, STEP_STATE_WORDS, type StepState } from '../../ui/StepLine'
import { flowKeyOf, type Flow } from './flow'
import styles from './FlowDiagram.module.css'

/** The key's and the screen reader's word for a state: the step line's one map, without its colon. */
const stateWord = (state: StepState): string => STEP_STATE_WORDS[state].replace(/: $/, '')

function Badge({ state }: { state: StepState }) {
  if (state === 'err') return <IconX />
  if (state === 'wait') return <IconGate />
  return <IconCheck />
}

const MARKED: ReadonlySet<StepState> = new Set(['done', 'wait', 'err'])

/**
 * A workflow page's steps as the sketch's flow diagram: a box per step, joined by a link, coloured by the latest run when one is drawn,
 * with a short note under a stop or a wait. With no run there is no key and no state: the steps alone, nothing guessed.
 */
export function FlowDiagram({ flow }: { flow: Flow }) {
  const key = flowKeyOf(flow)
  return (
    <section className={styles['card']} aria-labelledby="flow-steps">
      <div className={styles['head']}>
        <h2 id="flow-steps">
          Steps{flow.ranWhen ? <span className={styles['when']}> {flow.ranWhen}</span> : null}
        </h2>
        {key.length > 0 ? (
          <p className={styles['key']}>
            {key.map((state) => (
              <span key={state} data-key={state}>
                <i className={styles[`kd-${state}`]} aria-hidden="true" />
                {stateWord(state)}
              </span>
            ))}
          </p>
        ) : null}
      </div>
      {/* The boxes scroll sideways when they do not fit, so the keyboard can reach them (axe: scrollable-region-focusable). */}
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
      <div className={styles['scroll']} tabIndex={0} role="group" aria-label="Steps">
        <ol className={cx(styles['flow'], flow.note && styles['hasNote'])} style={{ '--n': flow.steps.length } as CSSProperties} aria-label="Steps">
          {flow.steps.map((step) => {
            const Picture = STEP_ICON[step.icon]
            const note = flow.note?.key === step.key ? flow.note : null
            return (
              <li key={step.key} className={cx(styles['box'], step.state && styles[step.state])} data-state={step.state ?? undefined} aria-current={step.state === 'now' || step.state === 'wait' ? 'step' : undefined}>
                {step.state ? <span className="visually-hidden">{STEP_STATE_WORDS[step.state]}</span> : null}
                <span className={styles['top']}>
                  <span className={cx(styles['ico'], step.agent && styles['agent'])}>{step.agent ? <AgentFace id={step.agent.id} display={step.agent.display} size={28} state="idle" /> : <Picture />}</span>
                  <span className={styles['name']}>{step.label}</span>
                </span>
                <span className={styles['tag']}>{step.tag}</span>
                {step.state && MARKED.has(step.state) ? (
                  <span className={styles['badge']} aria-hidden="true">
                    <Badge state={step.state} />
                  </span>
                ) : null}
                {note ? (
                  <p className={styles['note']} data-note={note.tone}>
                    {note.tone === 'err' ? <IconX /> : <IconGate />}
                    <span>{note.text}</span>
                  </p>
                ) : null}
              </li>
            )
          })}
        </ol>
      </div>
    </section>
  )
}
