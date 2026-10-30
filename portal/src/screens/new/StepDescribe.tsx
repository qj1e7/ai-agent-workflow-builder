import type { ReactNode } from 'react'
import { AgentFace, type FaceState } from '../../ui/AgentFace'
import { Button } from '../../ui/Button'
import { IconCheck } from '../../ui/icons'
import { TASK_CHIPS } from './starters'
import styles from './NewWorkflow.module.css'

export const THINKING = ['Reading your task', 'Matching it to what I can do', 'Checking your workflows and tools'] as const
const HELP = 'Say what should happen, in which system, and when. For example: “every weekday at 3pm”.'
const HELLO = 'Tell me what you want done. I’ll show you what I understood before anything is set up, and flag anything I’m not sure about.'

export function PlannerSays({ state = 'idle', children }: { state?: FaceState; children: ReactNode }) {
  return (
    <div className={styles['bubble']}>
      <AgentFace id="planner" size={48} state={state} />
      <p>
        <span className="visually-hidden">Planner: </span>
        {children}
      </p>
    </div>
  )
}

interface StepDescribeProps {
  readonly text: string
  readonly problem: string | null
  readonly thinkingLines: number
  readonly plannerSaid: string | null
  readonly onText: (text: string) => void
  readonly onPlan: () => void
}

export function StepDescribe({ text, problem, thinkingLines, plannerSaid, onText, onPlan }: StepDescribeProps) {
  const reading = thinkingLines > 0
  return (
    <div className={styles['ask']}>
      <div className={styles['field']}>
        <label htmlFor="task">What should happen?</label>
        <textarea
          id="task"
          rows={6}
          value={text}
          placeholder={`For example: ${TASK_CHIPS[0]?.task ?? ''}`}
          aria-invalid={problem ? true : undefined}
          aria-describedby={problem ? 'task-help task-error' : 'task-help'}
          onChange={(event) => onText(event.target.value)}
        />
        <span className={styles['help']} id="task-help">
          {HELP}
        </span>
        {problem ? (
          <span className={styles['error']} id="task-error">
            {problem}
          </span>
        ) : null}
        <div>
          <span className={`${styles['help']} ${styles['label']}`}>Or start from one of these</span>
          <div className={styles['chips']}>
            {TASK_CHIPS.map((chip) => (
              <button key={chip.name} type="button" className={styles['chip']} onClick={() => onText(chip.task)}>
                {chip.name}
              </button>
            ))}
          </div>
        </div>
        <div className={styles['actions']}>
          <Button variant="primary" loading={reading} onClick={onPlan}>
            Plan it
          </Button>
        </div>
      </div>
      <div className={styles['panel']} aria-live="polite">
        <PlannerSays state={reading ? 'thinking' : 'idle'}>{reading ? 'Give me a moment.' : (plannerSaid ?? HELLO)}</PlannerSays>
        {reading ? (
          <ul className={styles['thinking']} aria-label="What the Planner is doing">
            {THINKING.slice(0, thinkingLines).map((line, index) => (
              <li key={line}>
                {index + 1 < thinkingLines ? <IconCheck size={18} /> : <span className={styles['spin']} aria-hidden="true" />}
                {line}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  )
}
