import { useId, useState } from 'react'
import { useErrorWords } from '../../api/context'
import { useAgentCards, useTools } from '../../api/queries'
import type { CardView, ToolView } from '../../api/types'
import { Button } from '../../ui/Button'
import { EmptyState, InlineMessage, Skeleton } from '../../ui/Feedback'
import { IconPlay, IconReplay } from '../../ui/icons'
import { exampleValues } from './agentRun'
import { copyOf, draftOf } from './cardDraft'
import { RunForm } from './RunForm'
import { ToolChips } from './ToolChips'
import { editorOf, type Work } from './work'
import { tourStop } from '../../tour/stops'
import styles from './AgentLibrary.module.css'

/** The saved agents, starters first. Run opens a form in place. Edit opens the card editor beside the task. */
export function AgentLibrary({ operator, onEdit }: { operator: boolean; onEdit: (work: Work) => void }) {
  const explain = useErrorWords()
  const cards = useAgentCards()
  const tools = useTools().data

  return (
    <section className={styles['section']} aria-labelledby="library-heading" {...tourStop('agent-library')}>
      <h2 id="library-heading">Agent library</h2>
      {cards.data && cards.data.length === 0 ? <EmptyState title="No agents yet.">A saved agent appears here.</EmptyState> : null}
      {cards.data && cards.data.length > 0 ? (
        <ul className={`panel ${styles['list']}`}>
          {cards.data.map((card) => (
            <li key={card.card_id}>
              <Row card={card} tools={tools} operator={operator} onEdit={onEdit} />
            </li>
          ))}
        </ul>
      ) : null}
      {!cards.data && cards.isError ? (
        <div className={styles['problem']}>
          <InlineMessage tone="error">We could not load the agents. {explain(cards.error)}</InlineMessage>
          <Button icon={IconReplay} loading={cards.isFetching} onClick={() => void cards.refetch()}>
            Try again
          </Button>
        </div>
      ) : null}
      {!cards.data && !cards.isError ? (
        <div className={`panel ${styles['padded']}`}>
          <Skeleton lines={3} label="Loading the agents" />
        </div>
      ) : null}
    </section>
  )
}

interface RowProps {
  card: CardView
  tools: readonly ToolView[] | undefined
  operator: boolean
  onEdit: (work: Work) => void
}

function Row({ card, tools, operator, onEdit }: RowProps) {
  const id = useId()
  const [open, setOpen] = useState(false)
  return (
    <article className={styles['row']} aria-labelledby={`${id}-name`}>
      <div className={styles['what']}>
        <h3 id={`${id}-name`}>
          {card.name}
          {card.starter ? <span className={styles['starter']}> Starter</span> : null}
        </h3>
        <p className="muted">{card.purpose}</p>
        <ToolChips ids={card.tools} tools={tools} />
      </div>
      {operator ? (
        <div className={styles['acts']}>
          <Button icon={IconPlay} aria-expanded={open} aria-controls={`${id}-run`} onClick={() => setOpen((was) => !was)}>
            Run<span className="visually-hidden"> {card.name}</span>
          </Button>
          <Button
            onClick={() => onEdit(editorOf(card, card.starter ? copyOf(card) : draftOf(card)))}
            {...(card.starter ? tourStop('copy-edit') : {})}
          >
            {card.starter ? 'Copy and edit' : 'Edit'}
            <span className="visually-hidden"> {card.name}</span>
          </Button>
        </div>
      ) : null}
      {open ? (
        <div id={`${id}-run`} className={styles['run']}>
          <RunForm
            agents={[{ card, values: exampleValues(card), missing: [] }]}
            instruction={card.purpose || card.name}
            tools={tools}
            showAgents={false}
          />
        </div>
      ) : null}
    </article>
  )
}
