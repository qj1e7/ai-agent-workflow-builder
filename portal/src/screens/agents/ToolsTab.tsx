import type { CapabilityView, CardView, ToolView } from '../../api/types'
import { approvalWords, kindLabel, systemOf } from './agents'
import { toolHealth } from './capabilities'
import styles from './AgentsPage.module.css'

function usedBy(tool: ToolView, cards: readonly CardView[]): string {
  const names = cards.filter((card) => card.tools.includes(tool.id)).map((card) => card.name)
  return names.length > 0 ? `Used by ${names.join(', ')}` : 'No agent uses it yet'
}

function ToolRow({ tool, cards, capabilities, now }: { tool: ToolView; cards: readonly CardView[] | undefined; capabilities: readonly CapabilityView[] | undefined; now: Date }) {
  const write = tool.kind === 'write'
  const health = toolHealth(tool, capabilities, now)
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
      {health ? (
        <p className={styles['small']} data-health={health.ok ? 'ok' : 'warn'}>
          <b>{health.label}.</b> {health.text}
        </p>
      ) : null}
      {cards ? <p className={styles['small'] + ' muted'}>{usedBy(tool, cards)}</p> : null}
    </li>
  )
}

interface Shared {
  readonly cards: readonly CardView[] | undefined
  readonly capabilities: readonly CapabilityView[] | undefined
  readonly now: Date
}

function Group({ title, sub, tools, ...shared }: { title: string; sub: string; tools: readonly ToolView[] } & Shared) {
  if (tools.length === 0) return null
  return (
    <section className={styles['section']}>
      <h2>
        {title} <span className={styles['count']}>{tools.length}</span>
      </h2>
      <p className={styles['small'] + ' muted'}>{sub}</p>
      <ul className={styles['toolRows']}>
        {tools.map((tool) => (
          <ToolRow key={tool.id} tool={tool} {...shared} />
        ))}
      </ul>
    </section>
  )
}

/** Only the tools behind a focus capability. Without the registry there is nothing to go by, so every tool shows. */
export function focusTools(tools: readonly ToolView[], capabilities: readonly CapabilityView[] | undefined): readonly ToolView[] {
  if (!capabilities) return tools
  const ids = new Set(capabilities.filter((capability) => capability.focus).flatMap((capability) => capability.tools))
  return tools.filter((tool) => ids.has(tool.id))
}

export function ToolsTab({ tools: all, ...shared }: { tools: readonly ToolView[] } & Shared) {
  const tools = focusTools(all, shared.capabilities)
  return (
    <>
      <Group title="Tools that change data" sub="Each one waits for a yes, every time." tools={tools.filter((tool) => tool.kind === 'write')} {...shared} />
      <Group title="Tools that only read" sub="They never change anything, so they do not need a yes." tools={tools.filter((tool) => tool.kind === 'read')} {...shared} />
    </>
  )
}
