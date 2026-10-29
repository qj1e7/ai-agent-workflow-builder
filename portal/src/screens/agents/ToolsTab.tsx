import type { CardView, ToolView } from '../../api/types'
import { approvalWords, kindLabel, systemOf } from './agents'
import styles from './AgentsPage.module.css'

function usedBy(tool: ToolView, cards: readonly CardView[]): string {
  const names = cards.filter((card) => card.tools.includes(tool.id)).map((card) => card.name)
  return names.length > 0 ? `Used by ${names.join(', ')}` : 'No agent uses it yet'
}

function ToolRow({ tool, cards }: { tool: ToolView; cards: readonly CardView[] | undefined }) {
  const write = tool.kind === 'write'
  return (
    <li className={styles['toolRow']} data-tool-id={tool.id}>
      <div>
        <b>{tool.name}</b>
        <span className={styles['small'] + ' muted'}>{systemOf(tool.id)}</span>
      </div>
      <p className={styles['small']}>{tool.description}</p>
      <p className={styles['small']}>
        <span className={write ? styles['writeTag'] : styles['tag']}>{kindLabel(tool.kind)}</span>
        {write ? <span className="muted"> {approvalWords(tool.min_approvers)}</span> : null}
      </p>
      {cards ? <p className={styles['small'] + ' muted'}>{usedBy(tool, cards)}</p> : null}
    </li>
  )
}

function Group({ title, sub, tools, cards }: { title: string; sub: string; tools: readonly ToolView[]; cards: readonly CardView[] | undefined }) {
  if (tools.length === 0) return null
  return (
    <section className={styles['section']}>
      <h2>
        {title} <span className={styles['count']}>{tools.length}</span>
      </h2>
      <p className={styles['small'] + ' muted'}>{sub}</p>
      <ul className={styles['toolRows']}>
        {tools.map((tool) => (
          <ToolRow key={tool.id} tool={tool} cards={cards} />
        ))}
      </ul>
    </section>
  )
}

export function ToolsTab({ tools, cards }: { tools: readonly ToolView[]; cards: readonly CardView[] | undefined }) {
  return (
    <>
      <Group title="Tools that change data" sub="Each one waits for a yes, every time." tools={tools.filter((tool) => tool.kind === 'write')} cards={cards} />
      <Group title="Tools that only read" sub="They never change anything, so they do not need a yes." tools={tools.filter((tool) => tool.kind === 'read')} cards={cards} />
    </>
  )
}
