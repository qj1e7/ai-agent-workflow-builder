import type { Ref } from 'react'
import { useTools } from '../../api/queries'
import type { CardView, MissingTool } from '../../api/types'
import { Skeleton } from '../../ui/Feedback'
import { exampleValues } from './agentRun'
import { CardEditor } from './CardEditor'
import { RunForm } from './RunForm'
import { runOfSaved, type Work } from './work'
import { tourStop } from '../../tour/stops'
import styles from './PlanPanel.module.css'

interface PlanPanelProps {
  work: Work | null
  planning: boolean
  /** The card editor saved a card, so the run form for it takes the panel's place. */
  onWork: (work: Work) => void
  heading: Ref<HTMLHeadingElement>
}

export function PlanPanel({ work, planning, onWork, heading }: PlanPanelProps) {
  return (
    <section
      className={`panel ${styles['panel']}`}
      aria-labelledby="plan-heading"
      aria-busy={planning || undefined}
      {...(work && !planning ? tourStop('plan', 'plan-result') : tourStop('plan'))}
    >
      <h2 id="plan-heading" ref={heading} tabIndex={-1}>
        The Room lead's plan
      </h2>
      {planning ? <Skeleton lines={5} label="The Room lead is planning" /> : work ? <Outcome work={work} onWork={onWork} /> : <Waiting />}
    </section>
  )
}

function Waiting() {
  return (
    <div className={styles['waiting']}>
      <div className={styles['ghost']} aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
      <p className="muted">The plan appears here.</p>
    </div>
  )
}

function Outcome({ work, onWork }: { work: Work; onWork: (work: Work) => void }) {
  const tools = useTools().data
  switch (work.kind) {
    case 'run':
      return (
        <>
          <Said intro={work.intro} reason={work.reason} questions={work.questions} />
          <RunForm agents={work.agents} instruction={work.instruction} tools={tools} />
        </>
      )
    case 'editor':
      return (
        <>
          <Said intro={work.intro} reason={work.reason} questions={work.questions} />
          <Missing tools={work.missingTools} />
          <CardEditor
            initial={work.draft}
            cardId={work.cardId}
            onSaved={(card: CardView) => onWork(runOfSaved(card, exampleValues(card), card.purpose || card.name))}
          />
        </>
      )
    case 'cannot':
      return (
        <div className={styles['said']}>
          <p className={styles['intro']}>The Room lead cannot do this yet.</p>
          <p className="muted">{work.reason}</p>
          <Missing tools={work.missingTools} />
        </div>
      )
    case 'model':
      return (
        <div className={styles['said']}>
          <p className={styles['intro']}>The Room lead could not plan this.</p>
          <p className="muted">{work.message}</p>
        </div>
      )
  }
}

function Said({ intro, reason, questions }: { intro: string; reason: string | null; questions: readonly string[] }) {
  return (
    <div className={styles['said']}>
      <p className={styles['intro']}>{intro}</p>
      {reason ? <p className="muted">{reason}</p> : null}
      {questions.length > 0 ? (
        <ul className={styles['questions']} aria-label="The Room lead asks">
          {questions.map((question) => (
            <li key={question}>{question}</li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

function Missing({ tools }: { tools: readonly MissingTool[] }) {
  if (tools.length === 0) return null
  return (
    <div className={styles['missing']}>
      <h3>No tool for this yet</h3>
      <ul>
        {tools.map((tool) => (
          <li key={tool.need}>
            <strong>{tool.need}.</strong> {tool.why}
          </li>
        ))}
      </ul>
    </div>
  )
}
