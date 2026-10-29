import { useEffect, useId, useRef, type ReactNode } from 'react'
import { Link } from 'react-router'
import type { CardView, ToolId, ToolView } from '../../api/types'
import { agentIdentity } from '../../ui/agents'
import { AgentFace } from '../../ui/AgentFace'
import { Button } from '../../ui/Button'
import { cx } from '../../ui/cx'
import { IconX } from '../../ui/icons'
import iconButton from '../../shell/IconButton.module.css'
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

const FROM_LIST = { fromList: true }

export function openedFromList(state: unknown): boolean {
  return typeof state === 'object' && state !== null && 'fromList' in state
}

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
            <Link id={tileId(id)} to={to} state={FROM_LIST} className={styles['tileLink']}>
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
  face: string
  title: string
  under: ReactNode
  onClose: () => void
  children: ReactNode
}

const TAB_STOPS = 'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])'

/** Chromium lets Tab leave a modal dialog for the browser's own controls, so the ends wrap round. */
function keepTabInside(box: HTMLElement, event: KeyboardEvent): void {
  if (event.key !== 'Tab') return
  const stops = [...box.querySelectorAll<HTMLElement>(TAB_STOPS)]
  const first = stops[0]
  const last = stops.at(-1)
  if (!first || !last) return
  const at = document.activeElement
  let next: HTMLElement | null = null
  if (!box.contains(at)) next = event.shiftKey ? last : first
  else if (event.shiftKey && at === first) next = last
  else if (!event.shiftKey && at === last) next = first
  if (!next) return
  event.preventDefault()
  next.focus()
}

function Modal({ face, title, under, onClose, children }: ModalProps) {
  const dialog = useRef<HTMLDialogElement>(null)
  const topClose = useRef<HTMLButtonElement>(null)
  const titleId = useId()
  useEffect(() => {
    const element = dialog.current
    if (!element) return
    if (!element.open) element.showModal()
    topClose.current?.focus()
    const onKey = (event: KeyboardEvent) => keepTabInside(element, event)
    const onPress = (event: MouseEvent) => {
      if (event.target !== element) return
      const box = element.getBoundingClientRect()
      const onCard = event.clientX >= box.left && event.clientX <= box.right && event.clientY >= box.top && event.clientY <= box.bottom
      if (!onCard) element.close()
    }
    document.addEventListener('keydown', onKey)
    element.addEventListener('click', onPress)
    return () => {
      document.removeEventListener('keydown', onKey)
      element.removeEventListener('click', onPress)
    }
  }, [])
  const close = () => dialog.current?.close()
  return (
    <dialog ref={dialog} className={styles['dialog']} aria-labelledby={titleId} onClose={onClose}>
      <div className={cx(styles['tileTop'], styles['dialogTop'])}>
        <AgentFace id={face} size={56} />
        <div>
          <h2 id={titleId}>{title}</h2>
          {under}
        </div>
        <button ref={topClose} type="button" className={cx(iconButton['button'], styles['dialogClose'])} aria-label="Close" onClick={close}>
          <IconX size={18} strokeWidth={3} />
        </button>
      </div>
      {children}
      <Button onClick={close}>Close</Button>
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
  return (
    <Modal face={agent.id} title={agentIdentity(agent.id).name} under={<span className={styles['mark']}>{platformAgentMark(agent.id)}</span>} onClose={onClose}>
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
  const nameOf = (id: ToolId) => tools.get(id)?.name ?? id
  return (
    <Modal face={faceId(card)} title={card.name} under={<span className="muted">{versionWords(card)}</span>} onClose={onClose}>
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
