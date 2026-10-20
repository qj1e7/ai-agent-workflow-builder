import type { BlockKind } from '../api/types'
import {
  IconCheck,
  IconDash,
  IconDot,
  IconFlow,
  IconLock,
  IconPause,
  IconPerson,
  IconRing,
  IconX,
  type Icon,
} from './icons'
import { isCompleted, isCurrent, spineStateWords, type SpineState } from './spineState'
import { cx } from './cx'
import styles from './Spine.module.css'

export interface SpineBlock {
  key: string
  name: string
  kind: BlockKind
  state: SpineState
  description?: string
}

interface SpineProps {
  blocks: readonly SpineBlock[]
  orientation: 'horizontal' | 'vertical'
  compact?: boolean
  showDescriptions?: boolean
  label?: string
}

const kindIcon: Record<BlockKind, Icon> = {
  agent: IconFlow,
  approval: IconPerson,
  write_action: IconLock,
}

const stateIcon: Record<SpineState['kind'], Icon> = {
  not_reached: IconDot,
  working: IconRing,
  waiting: IconPause,
  done: IconCheck,
  approved: IconCheck,
  declined: IconX,
  failed: IconX,
  not_needed: IconDash,
}

export function Spine({ blocks, orientation, compact = false, showDescriptions = false, label = 'Steps in this run' }: SpineProps) {
  const className = cx(styles['spine'], styles[orientation], compact && styles['compact'])
  return (
    <ol className={className} aria-label={label}>
      {blocks.map((block, index) => {
        const Kind = kindIcon[block.kind]
        const State = stateIcon[block.state.kind]
        const connectorDone = isCompleted(block.state) && index < blocks.length - 1
        return (
          <li
            key={block.key}
            className={cx(styles['station'], styles[block.state.kind])}
            data-connector={connectorDone ? 'done' : 'open'}
            aria-current={isCurrent(block.state) ? 'step' : undefined}
          >
            <span className={styles['node']} aria-hidden="true">
              <Kind size={compact ? 16 : 18} />
            </span>
            <span className={styles['text']}>
              <span className={styles['name']}>{block.name}</span>
              <span className={styles['state']}>
                <State size={16} />
                {spineStateWords(block.state)}
              </span>
              {showDescriptions && block.description ? <span className={styles['description']}>{block.description}</span> : null}
            </span>
          </li>
        )
      })}
    </ol>
  )
}
