import { useEffect, useRef } from 'react'
import { useLocation, useNavigate, useParams, useSearchParams } from 'react-router'
import { useAgentCards, useTools } from '../../api/queries'
import { PageHead } from '../../shell/PageHead'
import { Button } from '../../ui/Button'
import { CardDialog, CardTile, PlatformDialog, PlatformTile, tileId, type ToolIndex } from './AgentCard'
import { faceId, PLATFORM_AGENTS, TOOLS_UNAVAILABLE_WORDS } from './agents'
import { ToolsTab } from './ToolsTab'
import styles from './AgentsPage.module.css'

export const CARDS_UNAVAILABLE_WORDS = 'The specialist agents are not available right now.'
export const NOT_FOUND_WORDS = 'That agent is not in the library.'

type Tab = 'agents' | 'tools'

export function AgentsPage({ heading, lead }: { heading: string; lead: string }) {
  const { agentId = null } = useParams()
  const [params, setParams] = useSearchParams()
  const { search } = useLocation()
  const navigate = useNavigate()
  const cards = useAgentCards()
  const tools = useTools()
  const tab: Tab = params.get('tab') === 'tools' ? 'tools' : 'agents'

  const toolIndex: ToolIndex = new Map((tools.data ?? []).map((tool) => [tool.id, tool]))
  const card = agentId === null ? undefined : cards.data?.find((entry) => entry.card_id === agentId)
  const platform = agentId === null ? undefined : PLATFORM_AGENTS.find((entry) => entry.id === agentId)

  // Closing a card puts focus back on its tile, also when the page was opened straight on the card's address.
  const opened = useRef<string | null>(null)
  useEffect(() => {
    if (agentId !== null) {
      opened.current = platform ? platform.id : card ? faceId(card) : null
      return
    }
    const last = opened.current
    opened.current = null
    if (last === null) return
    document.getElementById(tileId(last))?.focus()
  }, [agentId, card, platform])

  const close = () => void navigate(`/agents${search}`)

  const specialists = cards.data ?? []
  return (
    <>
      <PageHead heading={heading} lead={lead} />
      <div className={styles['tabs']} role="group" aria-label="Show">
        <button type="button" aria-pressed={tab === 'agents'} onClick={() => setParams({}, { replace: true })}>
          Agents <span className={styles['count']}>{PLATFORM_AGENTS.length + specialists.length}</span>
        </button>
        <button type="button" aria-pressed={tab === 'tools'} onClick={() => setParams({ tab: 'tools' }, { replace: true })}>
          Tools {tools.data ? <span className={styles['count']}>{tools.data.length}</span> : null}
        </button>
      </div>
      {tools.isError ? (
        <p className={styles['notice']} role="status">
          {TOOLS_UNAVAILABLE_WORDS}{' '}
          <Button onClick={() => void tools.refetch()}>Try again</Button>
        </p>
      ) : null}
      {tab === 'tools' ? (
        tools.data ? (
          <ToolsTab tools={tools.data} cards={cards.data} />
        ) : tools.isError ? null : (
          <p className="muted" role="status">
            Loading
          </p>
        )
      ) : (
        <>
          <section className={styles['section']}>
            <h2>Platform agents</h2>
            <div className={styles['grid']}>
              {PLATFORM_AGENTS.map((agent) => (
                <PlatformTile key={agent.id} agent={agent} search={search} />
              ))}
            </div>
          </section>
          <section className={styles['section']}>
            <h2>
              Specialist agents {cards.data ? <span className={styles['count']}>{specialists.length}</span> : null}
            </h2>
            {cards.isPending ? (
              <p className="muted" role="status">
                Loading
              </p>
            ) : cards.isError ? (
              <p className={styles['notice']} role="status">
                {CARDS_UNAVAILABLE_WORDS} <Button onClick={() => void cards.refetch()}>Try again</Button>
              </p>
            ) : (
              <div className={styles['grid']}>
                {specialists.map((entry) => (
                  <CardTile key={entry.card_id} card={entry} tools={toolIndex} search={search} />
                ))}
              </div>
            )}
          </section>
        </>
      )}
      {agentId !== null && !platform && !card && cards.isSuccess ? <p className={styles['notice']}>{NOT_FOUND_WORDS}</p> : null}
      {platform ? <PlatformDialog key={platform.id} agent={platform} onClose={close} /> : null}
      {card ? <CardDialog key={card.card_id} card={card} tools={toolIndex} onClose={close} /> : null}
    </>
  )
}
