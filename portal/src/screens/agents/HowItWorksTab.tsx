import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { useCapabilities } from '../../api/capabilityQueries'
import { useAgentCards, useTools } from '../../api/queries'
import { Button } from '../../ui/Button'
import { CardDialog, CardTile, PlatformDialog, PlatformTile, tileId, useCloseWithoutHistoryEntry, type ToolIndex } from './AgentCard'
import { faceId, howShowOf, PLATFORM_AGENTS, toolsUnavailableWords, type HowShow } from './agents'
import { CapabilitiesTab } from './CapabilitiesTab'
import { ToolsTab } from './ToolsTab'
import styles from './HowItWorks.module.css'

export const CARDS_UNAVAILABLE_WORDS = 'The specialist agents are not available right now.'
export const NOT_FOUND_WORDS = 'That agent is not in the library.'

const LEADS: Record<HowShow, string> = {
  can: 'What the platform can do for software versioning. An agent can use only what is listed under I can.',
  agents: 'The agents behind software version checks. Anything that changes data waits for a yes.',
  tools: 'Tools are how agents reach GitHub and Jira. A tool that changes data waits for a yes, every time.',
}

function useFocusBackToTile(shownId: string | null, cardOpen: boolean): void {
  const [lastShown, setLastShown] = useState<string | null>(null)
  if (shownId !== null && shownId !== lastShown) setLastShown(shownId)
  useEffect(() => {
    if (!cardOpen && lastShown !== null) document.getElementById(tileId(lastShown))?.focus()
  }, [cardOpen, lastShown])
}

/** The Settings tab for Operators that shows what the platform can do, its agents and its tools. */
export function HowItWorksTab({ now }: { now: Date }) {
  const [params, setParams] = useSearchParams()
  const agentId = params.get('agent')
  const cards = useAgentCards()
  const tools = useTools()
  const capabilities = useCapabilities()
  const tab = howShowOf(params.get('show'), agentId)
  const show = (next: HowShow) => setParams(next === 'can' ? { tab: 'how' } : { tab: 'how', show: next }, { replace: true })

  const toolIndex: ToolIndex = new Map((tools.data ?? []).map((tool) => [tool.id, tool]))
  const card = agentId === null ? undefined : cards.data?.find((entry) => entry.card_id === agentId)
  const platform = agentId === null ? undefined : PLATFORM_AGENTS.find((entry) => entry.id === agentId)

  useFocusBackToTile(platform ? platform.id : card ? faceId(card) : null, agentId !== null)
  const close = useCloseWithoutHistoryEntry()

  const specialists = cards.data ?? []
  return (
    <>
      <p className={styles['lead']}>{LEADS[tab]}</p>
      <div className={styles['tabs']} role="group" aria-label="Show">
        <button type="button" aria-pressed={tab === 'can'} onClick={() => show('can')}>
          What it can do
        </button>
        <button type="button" aria-pressed={tab === 'agents'} onClick={() => show('agents')}>
          Agents <span className={styles['count']}>{PLATFORM_AGENTS.length + specialists.length}</span>
        </button>
        <button type="button" aria-pressed={tab === 'tools'} onClick={() => show('tools')}>
          Tools {tools.data ? <span className={styles['count']}>{tools.data.length}</span> : null}
        </button>
      </div>
      {agentId !== null && !platform && !card && cards.isSuccess ? (
        <p className={styles['notice']} role="status">
          {NOT_FOUND_WORDS}
        </p>
      ) : null}
      {tools.isError && tab !== 'can' ? (
        <p className={styles['notice']} role="status">
          {toolsUnavailableWords(tab === 'agents' && cards.isSuccess)}{' '}
          <Button onClick={() => void tools.refetch()}>Try again</Button>
        </p>
      ) : null}
      {tab === 'tools' ? (
        tools.data ? (
          <ToolsTab tools={tools.data} cards={cards.data} capabilities={capabilities.data?.capabilities} now={now} />
        ) : tools.isError ? null : (
          <p className="muted" role="status">
            Loading
          </p>
        )
      ) : tab === 'can' ? (
        <CapabilitiesTab cards={cards.data} now={now} />
      ) : (
        <>
          <section className={styles['section']}>
            <h2>Platform agents</h2>
            <div className={styles['grid']}>
              {PLATFORM_AGENTS.map((agent) => (
                <PlatformTile key={agent.id} agent={agent} />
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
                  <CardTile key={entry.card_id} card={entry} tools={toolIndex} />
                ))}
              </div>
            )}
          </section>
        </>
      )}
      {platform ? <PlatformDialog key={platform.id} agent={platform} onClose={close} /> : null}
      {card ? <CardDialog key={card.card_id} card={card} tools={toolIndex} onClose={close} /> : null}
    </>
  )
}
