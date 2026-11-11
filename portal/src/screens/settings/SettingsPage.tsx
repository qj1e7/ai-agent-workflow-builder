import { lazy, Suspense } from 'react'
import { useSearchParams } from 'react-router'
import { isOperator } from '../../api/me'
import { useAgentCards, useMe } from '../../api/queries'
import { agentShown } from '../agents/agents'
import { PageHead } from '../../shell/PageHead'
import styles from './SettingsPage.module.css'

const SettingsTabs = lazy(() => import('./SettingsTabs'))

export function SettingsPage({ heading, lead, now }: { heading: string; lead: string; now: Date }) {
  // An agent that opens from a link takes focus in its own dialog, so the heading doesn't. A link to an agent that isn't there opens nothing, so the heading does.
  const [params] = useSearchParams()
  const cards = useAgentCards().data
  const agentOpen = isOperator(useMe().data) && params.get('tab') === 'how' && agentShown(params.get('agent'), cards)
  return (
    <div className={styles['page']}>
      <PageHead heading={heading} lead={lead} movesFocus={agentOpen} />
      <Suspense
        fallback={
          <p className="muted" role="status">
            Loading
          </p>
        }
      >
        <SettingsTabs now={now} />
      </Suspense>
    </div>
  )
}
