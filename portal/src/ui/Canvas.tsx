import { useId, type CSSProperties } from 'react'
import type { N8nBlockKind, N8nBlockView } from '../api/types'
import { edgeKey, layOut, NODE, type EdgeState, type NodeState } from './canvasLayout'
import { IconAlert, IconBell, IconClock, IconCompare, IconFork, IconGate, IconPlay, IconSearch, IconSend, IconStop, IconTicket, IconX, type Icon } from './icons'
import styles from './Canvas.module.css'

const PICTURE: Readonly<Record<N8nBlockKind, Icon>> = {
  schedule: IconClock,
  start: IconPlay,
  manual: IconPlay,
  error: IconAlert,
  read: IconSearch,
  agent: IconCompare,
  propose: IconSend,
  ask: IconGate,
  write: IconTicket,
  tell: IconBell,
  report: IconSend,
  branch: IconFork,
  merge: IconFork,
  end: IconStop,
  other: IconX,
}

/** What each block is, under its name. A block names its kind, not the system it reaches, so this says the kind. */
const SUB: Readonly<Record<N8nBlockKind, string>> = {
  schedule: 'Schedule',
  start: 'Start',
  manual: 'By hand',
  error: 'On error',
  read: 'Reads',
  agent: 'Agent',
  propose: 'Proposes',
  ask: 'Teams',
  write: 'Writes after a yes',
  tell: 'In the app',
  report: 'Reports',
  branch: 'IF',
  merge: 'Merge',
  end: 'Ends the run',
  other: 'Not allowed',
}

interface CanvasProps {
  readonly blocks: readonly N8nBlockView[]
  /** The workflow's name, which names the picture. */
  readonly name: string
  readonly nodes?: Readonly<Record<string, NodeState>>
  readonly edges?: Readonly<Record<string, EdgeState>>
}

/**
 * The workflow drawn as n8n draws it, from its blocks and their ways out: our blocks marked, an IF's true and false named. A block
 * not built yet is hidden, one a run reached gets a tick, and dashes flow into the block at work. The states come from the caller.
 */
export function Canvas({ blocks, name, nodes = {}, edges = {} }: CanvasProps) {
  const id = useId()
  const laid = layOut(blocks)
  const shown = laid.nodes.filter((node) => (nodes[node.name] ?? 'idle') !== 'off')
  return (
    // The picture scrolls sideways when the panel is narrower than it, so the keyboard can reach it (axe: scrollable-region-focusable).
    // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
    <div className={styles['canvas']} tabIndex={0} role="group" aria-labelledby={id}>
      <svg viewBox={`0 0 ${String(laid.width)} ${String(laid.height)}`} className={styles['svg']} style={{ '--w': `${String(laid.width)}px` } as CSSProperties} role="img" aria-labelledby={id}>
        <title id={id}>{`${name} in n8n${shown.length > 0 ? `: ${shown.map((node) => node.name).join(', ')}` : ''}`}</title>
        {laid.edges.map((edge) => {
          const state = edges[edgeKey(edge.from, edge.to)] ?? 'idle'
          return (
            <g key={edgeKey(edge.from, edge.to)} className={styles['edge']} data-state={state}>
              <path d={edge.path} />
              {edge.label ? (
                <text x={edge.labelAt.x} y={edge.labelAt.y}>
                  {edge.label}
                </text>
              ) : null}
            </g>
          )
        })}
        {laid.nodes.map((node, index) => {
          const Picture = PICTURE[node.kind]
          const starts = node.col === 0
          const ends = !blocks.find((block) => block.name === node.name)?.next.length
          return (
            <g key={node.name} className={styles['node']} data-state={nodes[node.name] ?? 'idle'} transform={`translate(${String(node.x)} ${String(node.y)})`} style={{ '--i': index } as CSSProperties}>
              <rect className={styles['box']} width={NODE} height={NODE} rx={14} />
              <Picture x={26} y={node.ours ? 14 : 26} size={32} />
              {node.ours ? (
                <>
                  <rect className={styles['ours']} x={14} y={58} width={56} height={16} rx={8} />
                  <text className={styles['oursText']} x={42} y={69.5} textAnchor="middle">
                    Our block
                  </text>
                </>
              ) : null}
              {starts ? null : <circle className={styles['port']} cx={0} cy={NODE / 2} r={5} />}
              {ends ? null : <circle className={styles['port']} cx={NODE} cy={NODE / 2} r={5} />}
              <g className={styles['tick']}>
                <circle cx={80} cy={4} r={9} />
                <path d="M75.8 4.2l2.8 2.8 5.2-5.4" />
              </g>
              <text className={styles['label']} x={42} y={104} textAnchor="middle">
                {node.name}
              </text>
              <text className={styles['sub']} x={42} y={121} textAnchor="middle">
                {SUB[node.kind]}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}
