import { useEffect, useId, useRef, type ReactNode } from 'react'
import { Link } from 'react-router'
import type { CardView, ToolId, ToolView } from '../../api/types'
import { agentIdentity } from '../../ui/agents'
import { AgentFace } from '../../ui/AgentFace'
import { Button } from '../../ui/Button'
import {
  accessLabel,
  approvalWords,
  CHANGE_LATER_NOTE,
  kindLabel,
  PLATFORM_NOTE,
  platformAgentMark,
  toolCountWords,
  versionWords,
  cardAccess,
  faceId,
  type Access,
  type PlatformAgent,
} from './agents'
import styles from './AgentsPage.module.css'

export const tileId = (id: string) => `agent-tile-${id}`

export type ToolIndex = ReadonlyMap<ToolId, ToolView>

function AccessTag({ access }: { access: Access }) {
  return <span className={access === 'writes' ? styles['writeTag'] : styles['tag']}>{accessLabel(access)}</span>
}

interface TileProps {
  id: string
  name: string
  what: string
  access: Access
  toolCount: number
  platform: boolean
  to: string
}

function Tile({ id, name, what, access, toolCount, platform, to }: TileProps) {
  return (
    <article className={styles['tile']}>
      <div className={styles['tileTop']}>
        <AgentFace id={id} size={52} />
        <div>
          <h3>
            <Link id={tileId(id)} to={to} className={styles['tileLink']}>
              {name}
            </Link>
          </h3>
          {platform ? <span className={styles['mark']}>{platformAgentMark(id)}</span> : null}
        </div>
      </div>
      <p>{what}</p>
      <p className={styles['small']}>
        <AccessTag access={access} />
        {toolCount > 0 ? <span className="muted"> {toolCountWords(toolCount)}</span> : null}
      </p>
    </article>
  )
}

export function PlatformTile({ agent, search }: { agent: PlatformAgent; search: string }) {
  return (
    <Tile
      id={agent.id}
      name={agentIdentity(agent.id).name}
      what={agent.what}
      access="none"
      toolCount={0}
      platform
      to={`/agents/${agent.id}${search}`}
    />
  )
}

export function CardTile({ card, tools, search }: { card: CardView; tools: ToolIndex; search: string }) {
  const kinds = new Map([...tools].map(([id, tool]) => [id, tool.kind]))
  return (
    <Tile
      id={faceId(card)}
      name={card.name}
      what={card.purpose}
      access={cardAccess(card, kinds)}
      toolCount={card.tools.length}
      platform={false}
      to={`/agents/${card.card_id}${search}`}
    />
  )
}

interface ModalProps {
  titleId: string
  onClose: () => void
  children: ReactNode
}

function Modal({ titleId, onClose, children }: ModalProps) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const element = dialog.current
    if (element && !element.open) element.showModal()
  }, [])
  return (
    // Escape is the dialog's own key; a click on the backdrop is a mouse shortcut for the Close button.
    // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-noninteractive-element-interactions
    <dialog
      ref={dialog}
      className={styles['dialog']}
      aria-labelledby={titleId}
      onClose={onClose}
      onClick={(event) => {
        if (event.target === dialog.current) dialog.current?.close()
      }}
    >
      {children}
      <Button onClick={() => dialog.current?.close()}>Close</Button>
    </dialog>
  )
}

function Steps({ steps }: { steps: readonly string[] }) {
  return (
    <section>
      <h3>How it works</h3>
      <ol className={styles['steps']}>
        {steps.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
    </section>
  )
}

function Rules({ rules }: { rules: readonly string[] }) {
  return (
    <section>
      <h3>Rules it always follows</h3>
      <ul className={styles['plain']}>
        {rules.map((rule) => (
          <li key={rule}>{rule}</li>
        ))}
      </ul>
    </section>
  )
}

export function PlatformDialog({ agent, onClose }: { agent: PlatformAgent; onClose: () => void }) {
  const titleId = useId()
  const { name } = agentIdentity(agent.id)
  return (
    <Modal titleId={titleId} onClose={onClose}>
      <div className={styles['tileTop']}>
        <AgentFace id={agent.id} size={56} />
        <div>
          <h2 id={titleId}>{name}</h2>
          <span className={styles['mark']}>{platformAgentMark(agent.id)}</span>
        </div>
      </div>
      <p>{agent.what}</p>
      <Steps steps={agent.steps} />
      <section>
        <h3>Tools it may use</h3>
        <p className="muted">{accessLabel('none')}. It only plans and explains.</p>
      </section>
      <Rules rules={agent.rules} />
      <p className={styles['note']}>{PLATFORM_NOTE}</p>
    </Modal>
  )
}

export function CardDialog({ card, tools, onClose }: { card: CardView; tools: ToolIndex; onClose: () => void }) {
  const titleId = useId()
  const nameOf = (id: ToolId) => tools.get(id)?.name ?? id
  return (
    <Modal titleId={titleId} onClose={onClose}>
      <div className={styles['tileTop']}>
        <AgentFace id={faceId(card)} size={56} />
        <div>
          <h2 id={titleId}>{card.name}</h2>
          <span className="muted">{versionWords(card)}</span>
        </div>
      </div>
      <p>{card.purpose}</p>
      <Steps steps={card.blocks.map((block) => block.say)} />
      <section>
        <h3>Tools it may use</h3>
        {card.tools.length === 0 ? (
          <p className="muted">{accessLabel('none')}.</p>
        ) : (
          <ul className={styles['toolList']}>
            {card.tools.map((id) => {
              const tool = tools.get(id)
              const approval = card.approvals.find((entry) => entry.tool === id)
              return (
                <li key={id} data-tool-id={id}>
                  {tool ? <span className={tool.kind === 'write' ? styles['writeTag'] : styles['tag']}>{kindLabel(tool.kind)}</span> : null}
                  <span>{nameOf(id)}</span>
                  {approval ? <span className="muted">{approvalWords(approval.approvers)}</span> : null}
                </li>
              )
            })}
          </ul>
        )}
      </section>
      {card.inputs.length > 0 ? (
        <section>
          <h3>What it asks for</h3>
          <ul className={styles['plain']}>
            {card.inputs.map((input) => (
              <li key={input.name}>
                <b>{input.name}</b>
                {input.what ? <span className="muted">. {input.what}</span> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {card.good_for.length > 0 ? (
        <section>
          <h3>Good for</h3>
          <ul className={styles['plain']}>
            {card.good_for.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </section>
      ) : null}
      <p className={styles['note']}>{CHANGE_LATER_NOTE}</p>
    </Modal>
  )
}
