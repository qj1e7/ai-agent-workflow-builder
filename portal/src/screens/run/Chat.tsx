import type { ReactNode, Ref } from 'react'
import type { Trigger } from '../../api/types'
import { Mark } from '../../shell/icons'
import { AgentFace, type FaceState } from '../../ui/AgentFace'
import { agentIdentity } from '../../ui/agents'
import { cx } from '../../ui/cx'
import { IconShield } from '../../ui/icons'
import { TicketKeys } from '../jira/TicketKeys'
import { usePauseUnseen } from '../../ui/loops'
import type { ChatItem } from './runModel'
import { lineOf, speakerName, type NameOf, type Speaker } from './words'
import styles from './Chat.module.css'

export function SpeakerAvatar({ speaker, state = 'idle' }: { speaker: Speaker | { kind: 'troubleshooter' }; state?: FaceState }) {
  switch (speaker.kind) {
    case 'app':
    case 'platform':
      return (
        <span className={cx(styles['sysav'], styles['app'])}>
          <Mark height={18} />
        </span>
      )
    case 'gate':
      return (
        <span className={cx(styles['sysav'], styles['gateAv'])}>
          <IconShield size={20} />
        </span>
      )
    case 'troubleshooter':
      return <AgentFace id="troubleshooter" size={40} state={state} />
    case 'agent':
      return <AgentFace id={speaker.agent.id} display={speaker.agent.display} size={40} state={state} />
  }
}

function Item({ item, fresh, nameOf, trigger }: { item: ChatItem; fresh: boolean; nameOf: NameOf; trigger: Trigger }) {
  const line = lineOf(item, nameOf, trigger)
  const tone = line.tone === 'plain' ? undefined : styles[line.tone]
  if (line.speaker.kind === 'agent') {
    const { agent } = line.speaker
    return (
      <li className={cx(styles['msg'], line.tone === 'bad' && styles['bad'], fresh && styles['in'])}>
        <span className={styles['av']}>
          <SpeakerAvatar speaker={line.speaker} state={line.tone === 'bad' ? 'error' : 'idle'} />
        </span>
        <div className={styles['body']}>
          <span className={styles['who']} style={{ color: agentIdentity(agent.id, agent.display).hue }}>
            {agent.display}
          </span>
          <div className={styles['bubble']}>{line.text}</div>
        </div>
      </li>
    )
  }
  if (line.speaker.kind === 'gate') {
    return (
      <li className={cx(styles['marker'], tone, fresh && styles['in'])} tabIndex={-1} data-gate-said={item.seq}>
        <span>
          <IconShield size={14} />
          {line.text}
        </span>
      </li>
    )
  }
  return (
    <li className={cx(styles['marker'], tone, fresh && styles['in'])}>
      <span>
        {item.kind === 'joined' ? (
          <span className={styles['faces']}>
            {item.agents.map((agent) => (
              <AgentFace key={agent.id} id={agent.id} display={agent.display} size={22} />
            ))}
          </span>
        ) : null}
        <TicketKeys text={line.text} keys={item.kind === 'written' && item.connector === 'jira' ? item.refs : []} />
      </span>
    </li>
  )
}

interface ChatProps {
  readonly items: readonly ChatItem[]
  readonly loadedUpTo: number
  readonly nameOf: NameOf
  readonly trigger: Trigger
  readonly last: ReactNode
  readonly ref?: Ref<HTMLOListElement>
}

export function Chat({ items, loadedUpTo, nameOf, trigger, last, ref }: ChatProps) {
  const pauseUnseen = usePauseUnseen()
  return (
    <div ref={pauseUnseen}>
      <ol className={styles['chat']} aria-label="What the agents said" ref={ref}>
        {items.map((item) => (
          <Item key={item.seq} item={item} fresh={item.seq > loadedUpTo} nameOf={nameOf} trigger={trigger} />
        ))}
        {last}
      </ol>
    </div>
  )
}

interface LastWordProps {
  readonly speaker: Speaker | { kind: 'troubleshooter' }
  readonly children: ReactNode
}

export const DECISION_ID = 'decision'

export function LastWord({ speaker, children }: LastWordProps) {
  const name = speaker.kind === 'troubleshooter' ? 'AI troubleshooter' : speakerName(speaker)
  const hue = speaker.kind === 'troubleshooter' ? agentIdentity('troubleshooter').hue : undefined
  return (
    <li className={styles['msg']} id={DECISION_ID} tabIndex={-1}>
      <span className={styles['av']}>
        <SpeakerAvatar speaker={speaker} />
      </span>
      <div className={styles['body']}>
        <span className={styles['who']} style={hue ? { color: hue } : undefined}>
          {name}
        </span>
        {children}
      </div>
    </li>
  )
}

export function Typing({ speaker, thinking }: { speaker: Speaker; thinking: boolean }) {
  return (
    <li className={cx(styles['msg'], styles['typing'])} aria-hidden="true">
      <span className={styles['av']}>
        <SpeakerAvatar speaker={speaker} state={thinking ? 'thinking' : 'working'} />
      </span>
      <div className={styles['body']}>
        <span className={styles['who']}>{speakerName(speaker)} is working</span>
        <div className={styles['bubble']}>
          <span className={styles['dots']}>
            <i />
            <i />
            <i />
          </span>
        </div>
      </div>
    </li>
  )
}
